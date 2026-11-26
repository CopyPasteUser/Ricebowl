//! Trusted system font fallback for scripts the bundled Latin face lacks.
//!
//! The candidate list is a compile-time table of absolute paths under
//! `/usr/share/fonts`. No fontconfig, no environment/recipe/pack supplied
//! paths and no directory scan. A candidate is opened with `O_NOFOLLOW`,
//! must be a regular file of at most 32 MiB and must parse with rustybuzz.
//! Glyphs are rasterized *by glyph index from the outline* with a small
//! coverage-accumulation rasterizer, not by fontdue: fontdue eagerly builds
//! geometry for every glyph, which measured +182 MB resident for the 5 MB
//! WenQuanYi collection, while outline rasterization keeps the cost at the
//! file size. Loading is lazy
//! (first cluster that needs a script group), happens at most once per
//! candidate per process, and a failure is cached as "unavailable": there is
//! no retry loop and no polling. Latin/Greek/Cyrillic/emoji never reach this
//! module's loader, so ASCII-only sessions pay nothing.
//!
//! `RICEBOWL_SYSTEM_FONT_FALLBACK=0` is an opt-out kill switch only (it can
//! never add a path); it exists for rollback and for the negative compositor
//! test.

use std::{
    fs::OpenOptions,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
    sync::OnceLock,
};

/// Upper bound for one font file (the largest candidate is a CJK collection).
pub(crate) const MAX_FONT_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ScriptGroup {
    Devanagari,
    Cjk,
    Hangul,
    ArabicHebrew,
}

/// Ordered, trusted candidates. The index is the cache slot.
pub(crate) const CANDIDATES: [&str; 5] = [
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
];

fn slots(group: ScriptGroup) -> &'static [u8] {
    match group {
        ScriptGroup::Devanagari => &[0, 1],
        // Han/Kana and Hangul share the CJK collections (face 0).
        ScriptGroup::Cjk | ScriptGroup::Hangul => &[2, 3],
        ScriptGroup::ArabicHebrew => &[4],
    }
}

pub(crate) fn script_group(letter: char) -> Option<ScriptGroup> {
    match letter as u32 {
        0x0900..=0x097F | 0xA8E0..=0xA8FF | 0x1CD0..=0x1CFF => Some(ScriptGroup::Devanagari),
        0x2E80..=0x2FDF
        | 0x3000..=0x303F
        | 0x3040..=0x30FF
        | 0x31F0..=0x31FF
        | 0x3400..=0x4DBF
        | 0x4E00..=0x9FFF
        | 0xF900..=0xFAFF
        | 0xFF00..=0xFFEF
        | 0x20000..=0x2FA1F => Some(ScriptGroup::Cjk),
        0x1100..=0x11FF | 0x3130..=0x318F | 0xA960..=0xA97F | 0xAC00..=0xD7FF => {
            Some(ScriptGroup::Hangul)
        }
        0x0590..=0x08FF | 0xFB1D..=0xFDFF | 0xFE70..=0xFEFF => Some(ScriptGroup::ArabicHebrew),
        _ => None,
    }
}

/// Group of a whole grapheme cluster: the first scalar that names a script.
pub(crate) fn cluster_group(cluster: &str) -> Option<ScriptGroup> {
    cluster.chars().find_map(script_group)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Reject {
    Missing,
    /// Symlink (O_NOFOLLOW), or any other open failure that is not "absent".
    Unsafe,
    NotRegular,
    TooLarge,
    Unreadable,
    InvalidFont,
}

pub(crate) struct SystemFont {
    /// Borrows file bytes that are intentionally leaked: a cached font lives
    /// for the whole process and is never reloaded.
    pub(crate) face: rustybuzz::Face<'static>,
    glyph_count: u16,
    units: f32,
}

impl SystemFont {
    pub(crate) fn glyph_count(&self) -> u16 {
        self.glyph_count
    }

    pub(crate) fn glyph_index(&self, letter: char) -> u16 {
        self.face.glyph_index(letter).map_or(0, |glyph| glyph.0)
    }
}

/// Open and parse one font file. Nothing outside the trusted table calls this
/// in production; tests use it with fixture paths.
pub(crate) fn load_font(path: &Path) -> Result<SystemFont, Reject> {
    let file = OpenOptions::new()
        .read(true)
        // O_NONBLOCK: a FIFO must be rejected by fstat, never block the open.
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => Reject::Missing,
            _ => Reject::Unsafe,
        })?;
    let info = file.metadata().map_err(|_| Reject::Unreadable)?;
    if (info.mode() & libc::S_IFMT) != libc::S_IFREG {
        return Err(Reject::NotRegular);
    }
    if info.len() > MAX_FONT_BYTES {
        return Err(Reject::TooLarge);
    }
    let mut bytes = Vec::with_capacity(info.len() as usize);
    file.take(MAX_FONT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| Reject::Unreadable)?;
    if bytes.len() as u64 > MAX_FONT_BYTES {
        return Err(Reject::TooLarge);
    }
    // Validate before leaking so a rejected file never stays resident.
    let probe = rustybuzz::Face::from_slice(&bytes, 0).ok_or(Reject::InvalidFont)?;
    if probe.units_per_em() <= 0 {
        return Err(Reject::InvalidFont);
    }
    drop(probe);
    let bytes: &'static [u8] = Box::leak(bytes.into_boxed_slice());
    let face = rustybuzz::Face::from_slice(bytes, 0).ok_or(Reject::InvalidFont)?;
    Ok(SystemFont {
        glyph_count: face.number_of_glyphs(),
        units: f32::from(face.units_per_em() as u16),
        face,
    })
}

fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED
        .get_or_init(|| std::env::var_os("RICEBOWL_SYSTEM_FONT_FALLBACK").is_none_or(|v| v != "0"))
}

static LOADED: [OnceLock<Option<SystemFont>>; CANDIDATES.len()] =
    [const { OnceLock::new() }; CANDIDATES.len()];

#[cfg(test)]
thread_local! {
    /// Times this thread asked for a candidate font (cache hit or load).
    pub(crate) static CONSULTED: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

/// The cached font for a slot, loading it on first use. Failure is cached.
pub(crate) fn font(slot: u8) -> Option<&'static SystemFont> {
    #[cfg(test)]
    CONSULTED.with(|count| count.set(count.get() + 1));
    let cell = LOADED.get(usize::from(slot))?;
    cell.get_or_init(|| {
        if !enabled() {
            return None;
        }
        load_font(Path::new(CANDIDATES[usize::from(slot)])).ok()
    })
    .as_ref()
}

/// Scalars that need no glyph of their own inside a covered cluster.
fn ignorable(letter: char) -> bool {
    letter.is_control() || matches!(letter as u32, 0x200B..=0x200F | 0x2060 | 0xFE00..=0xFE0F)
}

fn covers(font: &SystemFont, cluster: &str) -> bool {
    cluster
        .chars()
        .all(|letter| ignorable(letter) || font.glyph_index(letter) != 0)
}

/// First trusted candidate (in table order) that covers the whole cluster.
/// `None` means no installed fallback covers it: the caller keeps its visible
/// replacement and never claims coverage.
pub(crate) fn select(cluster: &str) -> Option<u8> {
    let group = cluster_group(cluster)?;
    slots(group)
        .iter()
        .copied()
        .find(|&slot| font(slot).is_some_and(|candidate| covers(candidate, cluster)))
}

/// Bitmap of one glyph, in the same convention fontdue metrics use: `xmin`
/// is the left bearing in pixels, `ymin` the bitmap bottom above the baseline.
pub(crate) struct Raster {
    pub(crate) width: u32,
    pub(crate) height: u32,
    pub(crate) xmin: i32,
    pub(crate) ymin: i32,
    pub(crate) pixels: Vec<u8>,
}

/// Collects a glyph outline as flattened line segments in bitmap space.
struct Flattener {
    scale: f32,
    x0: f32,
    y1: f32,
    limit_x: f32,
    start: (f32, f32),
    pen: (f32, f32),
    lines: Vec<((f32, f32), (f32, f32))>,
}

impl Flattener {
    fn map(&self, x: f32, y: f32) -> (f32, f32) {
        (
            (x * self.scale - self.x0).clamp(0.0, self.limit_x),
            self.y1 - y * self.scale,
        )
    }

    fn line_to_point(&mut self, to: (f32, f32)) {
        if self.lines.len() < 8192 {
            self.lines.push((self.pen, to));
        }
        self.pen = to;
    }
}

impl rustybuzz::ttf_parser::OutlineBuilder for Flattener {
    fn move_to(&mut self, x: f32, y: f32) {
        self.start = self.map(x, y);
        self.pen = self.start;
    }
    fn line_to(&mut self, x: f32, y: f32) {
        let to = self.map(x, y);
        self.line_to_point(to);
    }
    fn quad_to(&mut self, x1: f32, y1: f32, x: f32, y: f32) {
        let (p0, p1, p2) = (self.pen, self.map(x1, y1), self.map(x, y));
        let dd = (p0.0 - 2.0 * p1.0 + p2.0).hypot(p0.1 - 2.0 * p1.1 + p2.1);
        let steps = ((dd / 0.4).sqrt().ceil() as u32).clamp(1, 16);
        for step in 1..=steps {
            let t = step as f32 / steps as f32;
            let u = 1.0 - t;
            self.line_to_point((
                u * u * p0.0 + 2.0 * u * t * p1.0 + t * t * p2.0,
                u * u * p0.1 + 2.0 * u * t * p1.1 + t * t * p2.1,
            ));
        }
    }
    fn curve_to(&mut self, x1: f32, y1: f32, x2: f32, y2: f32, x: f32, y: f32) {
        let (p0, p1, p2, p3) = (self.pen, self.map(x1, y1), self.map(x2, y2), self.map(x, y));
        let d1 = (p0.0 - 2.0 * p1.0 + p2.0).hypot(p0.1 - 2.0 * p1.1 + p2.1);
        let d2 = (p1.0 - 2.0 * p2.0 + p3.0).hypot(p1.1 - 2.0 * p2.1 + p3.1);
        let steps = (((0.75 * d1.max(d2)) / 0.1).sqrt().ceil() as u32).clamp(1, 24);
        for step in 1..=steps {
            let t = step as f32 / steps as f32;
            let u = 1.0 - t;
            let (a, b, c, d) = (u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t);
            self.line_to_point((
                a * p0.0 + b * p1.0 + c * p2.0 + d * p3.0,
                a * p0.1 + b * p1.1 + c * p2.1 + d * p3.1,
            ));
        }
    }
    fn close(&mut self) {
        let start = self.start;
        if self.pen != start {
            self.line_to_point(start);
        }
    }
}

/// Signed-area coverage accumulation of one line into `acc` (row stride
/// `stride`, `height` rows). Points are already inside `0..=width`.
fn accumulate_line(acc: &mut [f32], stride: usize, height: usize, p0: (f32, f32), p1: (f32, f32)) {
    if p0.1 == p1.1 {
        return;
    }
    let (dir, p0, p1) = if p0.1 < p1.1 {
        (1.0, p0, p1)
    } else {
        (-1.0, p1, p0)
    };
    let dxdy = (p1.0 - p0.0) / (p1.1 - p0.1);
    let mut x = p0.0;
    let mut y = p0.1.max(0.0) as usize;
    if p0.1 < 0.0 {
        x -= p0.1 * dxdy;
    }
    let end = height.min(p1.1.ceil().max(0.0) as usize);
    while y < end {
        let row = y * stride;
        let dy = ((y + 1) as f32).min(p1.1) - (y as f32).max(p0.1);
        let next = x + dxdy * dy;
        let d = dy * dir;
        let (left, right) = if x < next { (x, next) } else { (next, x) };
        let left_floor = left.floor();
        let li = left_floor as usize;
        let ri = right.ceil() as usize;
        if ri <= li + 1 {
            let mid = 0.5 * (x + next) - left_floor;
            acc[row + li] += d - d * mid;
            acc[row + li + 1] += d * mid;
        } else {
            let s = 1.0 / (right - left);
            let lf = left - left_floor;
            let a0 = 0.5 * s * (1.0 - lf) * (1.0 - lf);
            let rf = right - right.ceil() + 1.0;
            let am = 0.5 * s * rf * rf;
            acc[row + li] += d * a0;
            if ri == li + 2 {
                acc[row + li + 1] += d * (1.0 - a0 - am);
            } else {
                let a1 = s * (1.5 - lf);
                acc[row + li + 1] += d * (a1 - a0);
                for xi in li + 2..ri - 1 {
                    acc[row + xi] += d * s;
                }
                let a2 = a1 + (ri - li - 3) as f32 * s;
                acc[row + ri - 1] += d * (1.0 - a2 - am);
            }
            acc[row + ri] += d * am;
        }
        x = next;
        y += 1;
    }
}

/// Rasterize one glyph (by index) at `px` pixels per em. `None` when the
/// bitmap would exceed `max_side` (the caller's glyph cache bound). A glyph
/// without an outline (space) is an empty bitmap.
pub(crate) fn rasterize(font: &SystemFont, glyph: u16, px: f32, max_side: u32) -> Option<Raster> {
    let scale = px / font.units;
    let mut flattener = Flattener {
        scale,
        x0: 0.0,
        y1: 0.0,
        limit_x: 0.0,
        start: (0.0, 0.0),
        pen: (0.0, 0.0),
        lines: Vec::new(),
    };
    let id = rustybuzz::ttf_parser::GlyphId(glyph);
    // First pass only for the bounds; the second maps into bitmap space.
    let bounds = font.face.glyph_bounding_box(id);
    let Some(bounds) = bounds else {
        return Some(Raster {
            width: 0,
            height: 0,
            xmin: 0,
            ymin: 0,
            pixels: Vec::new(),
        });
    };
    let left = (f32::from(bounds.x_min) * scale).floor();
    let right = (f32::from(bounds.x_max) * scale).ceil();
    let bottom = (f32::from(bounds.y_min) * scale).floor();
    let top = (f32::from(bounds.y_max) * scale).ceil();
    let (width, height) = ((right - left).max(0.0), (top - bottom).max(0.0));
    if width as u32 > max_side || height as u32 > max_side {
        return None;
    }
    let (width, height) = (width as usize, height as usize);
    flattener.x0 = left;
    flattener.y1 = top;
    flattener.limit_x = width as f32;
    font.face.outline_glyph(id, &mut flattener)?;
    let stride = width + 2;
    let mut acc = vec![0.0_f32; stride * height.max(1)];
    for (a, b) in &flattener.lines {
        accumulate_line(&mut acc, stride, height, *a, *b);
    }
    let mut pixels = vec![0_u8; width * height];
    for row in 0..height {
        let mut sum = 0.0_f32;
        for col in 0..width {
            sum += acc[row * stride + col];
            pixels[row * width + col] = (sum.abs().min(1.0) * 255.0 + 0.5) as u8;
        }
    }
    Some(Raster {
        width: width as u32,
        height: height as u32,
        xmin: left as i32,
        ymin: bottom as i32,
        pixels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("rb-sysfont-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn candidate_table_is_absolute_system_paths_only() {
        for path in CANDIDATES {
            assert!(path.starts_with("/usr/share/fonts/"), "{path}");
            assert!(!path.contains(".."), "{path}");
        }
        for group in [
            ScriptGroup::Devanagari,
            ScriptGroup::Cjk,
            ScriptGroup::Hangul,
            ScriptGroup::ArabicHebrew,
        ] {
            assert!(slots(group)
                .iter()
                .all(|&s| usize::from(s) < CANDIDATES.len()));
        }
    }

    #[test]
    fn script_groups_cover_target_scripts_and_never_latin() {
        assert_eq!(cluster_group("हि"), Some(ScriptGroup::Devanagari));
        assert_eq!(cluster_group("日"), Some(ScriptGroup::Cjk));
        assert_eq!(cluster_group("あ"), Some(ScriptGroup::Cjk));
        assert_eq!(cluster_group("한"), Some(ScriptGroup::Hangul));
        assert_eq!(cluster_group("س"), Some(ScriptGroup::ArabicHebrew));
        assert_eq!(cluster_group("ש"), Some(ScriptGroup::ArabicHebrew));
        for latin in ["a", "é", "Ünï", "Ж", "α", "€", "😀", "\u{10FFFF}", " "] {
            assert_eq!(cluster_group(latin), None, "{latin:?}");
        }
    }

    #[test]
    fn unsafe_or_missing_candidates_are_unavailable() {
        let dir = scratch("reject");
        let real = dir.join("real.ttf");
        std::fs::write(
            &real,
            include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf"),
        )
        .unwrap();
        assert!(load_font(&real).is_ok(), "a regular parsable font loads");

        assert_eq!(
            load_font(&dir.join("absent.ttf")).err(),
            Some(Reject::Missing)
        );
        let link = dir.join("link.ttf");
        symlink(&real, &link).unwrap();
        assert_eq!(load_font(&link).err(), Some(Reject::Unsafe), "symlink");
        assert_eq!(load_font(&dir).err(), Some(Reject::NotRegular), "directory");
        let fifo = dir.join("fifo.ttf");
        let c_path = std::ffi::CString::new(fifo.to_str().unwrap()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(c_path.as_ptr(), 0o600) }, 0);
        assert_eq!(load_font(&fifo).err(), Some(Reject::NotRegular), "fifo");
        let big = dir.join("big.ttf");
        let file = std::fs::File::create(&big).unwrap();
        file.set_len(MAX_FONT_BYTES + 1).unwrap();
        assert_eq!(load_font(&big).err(), Some(Reject::TooLarge), "oversized");
        let junk = dir.join("junk.ttf");
        std::fs::write(&junk, b"not a font at all").unwrap();
        assert_eq!(load_font(&junk).err(), Some(Reject::InvalidFont));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn latin_and_emoji_clusters_never_consult_or_load_a_system_font() {
        CONSULTED.with(|count| count.set(0));
        for cluster in ["a", "é", "Ж", "α", "😀", "\u{10FFFF}", "e\u{301}"] {
            assert_eq!(select(cluster), None, "{cluster:?}");
        }
        assert_eq!(CONSULTED.with(std::cell::Cell::get), 0);
    }

    #[test]
    fn installed_fallbacks_cover_hindi_cjk_hangul_or_fail_explicitly() {
        // Explicit failure (never a silent skip) when the apt fonts are absent.
        crate::native_shaping::script_fonts::require(
            crate::native_shaping::script_fonts::DEVANAGARI,
            "हिन्दी",
            "fonts-lohit-deva",
        );
        crate::native_shaping::script_fonts::require(
            crate::native_shaping::script_fonts::CJK,
            "日本語한국어",
            "fonts-wqy-microhei",
        );
        for cluster in ["हि", "न्दी", "日", "本", "語", "한", "국", "어"] {
            let slot = select(cluster).unwrap_or_else(|| {
                panic!("FONT UNAVAILABLE: no trusted system fallback covers {cluster:?}")
            });
            assert!(font(slot).is_some());
        }
        // Table order: Lohit before Noto, wqy before Noto CJK.
        assert_eq!(select("हि"), Some(0));
        assert_eq!(select("日"), Some(2));
        assert_eq!(select("한"), Some(2));
        // A cluster with a scalar no font maps: the caller keeps '?'.
        assert_eq!(select("日\u{10FFFF}"), None);
    }

    #[test]
    fn outline_rasterizer_matches_fontdue_coverage_and_bounds() {
        // Cross-check the small outline rasterizer against fontdue on a font
        // that is already a hard dependency of the existing tests.
        let path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf";
        let font = load_font(Path::new(path)).expect("FONT UNAVAILABLE: install fonts-dejavu-core");
        let reference = fontdue::Font::from_bytes(
            std::fs::read(path).unwrap(),
            fontdue::FontSettings::default(),
        )
        .unwrap();
        for letter in ['I', 'O', 'g', 'W', '@', 'é'] {
            let id = font.glyph_index(letter);
            assert_ne!(id, 0, "{letter}");
            let ours = rasterize(&font, id, 16.0, 48).unwrap();
            let (metrics, pixels) = reference.rasterize_indexed(id, 16.0);
            assert!(
                (ours.width as i32 - metrics.width as i32).abs() <= 1
                    && (ours.height as i32 - metrics.height as i32).abs() <= 1,
                "{letter}: bbox {}x{} vs {}x{}",
                ours.width,
                ours.height,
                metrics.width,
                metrics.height
            );
            assert!((ours.xmin - metrics.xmin).abs() <= 1, "{letter} xmin");
            assert!((ours.ymin - metrics.ymin).abs() <= 1, "{letter} ymin");
            let ink = |data: &[u8]| data.iter().map(|&v| f32::from(v)).sum::<f32>();
            let (a, b) = (ink(&ours.pixels), ink(&pixels));
            assert!(
                (a - b).abs() <= 0.12 * b + 255.0,
                "{letter}: total coverage {a} vs fontdue {b}"
            );
        }
        // No outline (space) is an empty bitmap; the cache bound is honoured.
        let space = rasterize(&font, font.glyph_index(' '), 16.0, 48).unwrap();
        assert_eq!((space.width, space.height), (0, 0));
        assert!(rasterize(&font, font.glyph_index('W'), 400.0, 48).is_none());
    }
}
