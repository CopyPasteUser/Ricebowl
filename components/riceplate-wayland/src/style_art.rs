//! Load private Rice Creator v0.5 assets once before opening Wayland surfaces.
//! Only content-addressed fonts and 48px PNGs can be used by the renderer.

use std::{collections::{HashMap, VecDeque}, env, error::Error, fs::{self, OpenOptions},
          io::{Cursor, Read}, os::unix::fs::{MetadataExt, OpenOptionsExt}, path::PathBuf,
          sync::{Mutex, OnceLock}};

use sha2::{Digest, Sha256};
use crate::recipe::ArtworkSelection;

const ICON_MAX: usize = 128 * 1024;
const FONT_MAX: usize = 1024 * 1024;
// Keep the common Latin glyphs warm and bound any additional Unicode masks.
// A glyph occupies no more than 32x32 bytes at the two supported scales.
const DYNAMIC_GLYPH_LIMIT: usize = 512;

pub struct IconPixels(pub Vec<u8>);

struct Glyph {
    width: u32,
    height: u32,
    xmin: i32,
    ymin: i32,
    advance: f32,
    pixels: Vec<u8>,
}

// Loaded once per process, not once per output/surface. Private recipe fonts
// can fall back to the already-distributed OFL font without host discovery.
static BUNDLED_FALLBACK: OnceLock<fontdue::Font> = OnceLock::new();

#[derive(Debug, Clone, Copy, Hash, PartialEq, Eq)]
enum FontFace { Primary, Fallback }
type GlyphKey = (FontFace, char);

pub struct FontSprites {
    font: fontdue::Font,
    fallback: Option<&'static fontdue::Font>,
    cache: Mutex<GlyphCache>,
    cell: u32,
    size: f32,
    proportional: bool,
}

struct GlyphCache {
    glyphs: HashMap<GlyphKey, Glyph>,
    dynamic: VecDeque<GlyphKey>,
}

impl GlyphCache {
    fn insert_dynamic(&mut self, key: GlyphKey, glyph: Glyph) {
        if self.dynamic.len() == DYNAMIC_GLYPH_LIMIT {
            if let Some(oldest) = self.dynamic.pop_front() {
                self.glyphs.remove(&oldest);
            }
        }
        self.dynamic.push_back(key);
        self.glyphs.insert(key, glyph);
    }
}

pub struct LoadedArtwork {
    pub font: Option<FontSprites>,
    pub icons: [Option<IconPixels>; 3],
}

fn private_directory() -> Result<PathBuf, Box<dyn Error>> {
    let config = match env::var_os("XDG_CONFIG_HOME") {
        Some(value) => {
            let path = PathBuf::from(value);
            if !path.is_absolute() { return Err("XDG_CONFIG_HOME must be absolute".into()); }
            path
        }
        None => {
            let home = env::var_os("HOME").ok_or("HOME is missing")?;
            PathBuf::from(home).join(".config")
        }
    };
    let ricebowl = config.join("ricebowl");
    let directory = ricebowl.join("visual-assets");
    for (index, path) in [&config, &ricebowl, &directory].into_iter().enumerate() {
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.is_dir() || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.mode() & 0o022 != 0
            || (index == 2 && metadata.mode() & 0o077 != 0)
        {
            return Err("Unsafe visual asset directory".into());
        }
    }
    Ok(directory)
}

fn read_asset(folder: &PathBuf, id: &str, suffix: &str, max: usize)
              -> Result<Vec<u8>, Box<dyn Error>> {
    // Parse already verified the 64 lowercase hexadecimal characters. Even if
    // the recipe is swapped after validation, only a fixed filename is opened.
    let file = OpenOptions::new().read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(folder.join(format!("{id}.{suffix}")))?;
    let info = file.metadata()?;
    if !info.is_file() || info.uid() != unsafe { libc::geteuid() }
        || info.mode() & 0o077 != 0 || info.len() > max as u64
    {
        return Err("Unsafe private visual asset".into());
    }
    let mut data = Vec::new();
    file.take((max + 1) as u64).read_to_end(&mut data)?;
    if data.len() > max || hex_digest(&data) != id[5..] {
        return Err("Visual asset exceeds limit or differs from SHA-256 ID".into());
    }
    Ok(data)
}

fn hex_digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn icon_png(data: &[u8]) -> Result<IconPixels, Box<dyn Error>> {
    let decoder = png::Decoder::new(Cursor::new(data));
    let mut reader = decoder.read_info()?;
    let info = reader.info();
    if info.width != 48 || info.height != 48
        || info.color_type != png::ColorType::Rgba || info.bit_depth != png::BitDepth::Eight
    {
        return Err("Creator icons require 48x48 8-bit RGBA PNG".into());
    }
    let mut pixels = vec![0; reader.output_buffer_size()];
    let frame = reader.next_frame(&mut pixels)?;
    if frame.buffer_size() != 48 * 48 * 4 {
        return Err("Unexpected decoded icon size".into());
    }
    pixels.truncate(frame.buffer_size());
    Ok(IconPixels(pixels))
}

fn font_glyphs(data: Vec<u8>, scale: u32, proportional: bool)
               -> Result<FontSprites, Box<dyn Error>> {
    let font = fontdue::Font::from_bytes(data, fontdue::FontSettings::default())?;
    let cell = 8 * scale;
    let size = if proportional { 11.0 * scale as f32 } else { (cell + 2) as f32 };
    let mut glyphs = HashMap::new();
    // Bounded upfront rasterization: each redraw only reads cached masks.
    // Unsupported Unicode falls back to the built-in bitmap tables.
    for code in 32..=255_u32 {
        let Some(character) = char::from_u32(code) else { continue; };
        // A missing cmap entry must use the visible '?' fallback; otherwise
        // prewarming .notdef under the original scalar hides the fallback.
        if font.lookup_glyph_index(character) == 0 { continue; }
        let bounds = font.metrics(character, size);
        if bounds.width > 32 || bounds.height > 32 { continue; }
        let (metrics, pixels) = font.rasterize(character, size);
        glyphs.insert((FontFace::Primary, character), Glyph {
            width: metrics.width as u32, height: metrics.height as u32,
            xmin: metrics.xmin, ymin: metrics.ymin,
            advance: metrics.advance_width, pixels,
        });
    }
    let fallback = if proportional { None } else {
        Some(BUNDLED_FALLBACK.get_or_init(|| {
            fontdue::Font::from_bytes(
                include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf") as &[u8],
                fontdue::FontSettings::default()
            ).expect("bundled OFL fallback font must be valid")
        }))
    };
    Ok(FontSprites { font, fallback, cache: Mutex::new(GlyphCache {
        glyphs, dynamic: VecDeque::new(),
    }), cell, size, proportional })
}

#[cfg(test)]
pub fn fixture_font(scale: u32) -> Option<FontSprites> {
    let data = fs::read("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf").ok()?;
    font_glyphs(data, scale, false).ok()
}

pub fn load(selection: &ArtworkSelection, scale: u32) -> Result<LoadedArtwork, Box<dyn Error>> {
    let needs_files = selection.font.as_ref().is_some_and(|id| id != "builtin-luna-ui")
        || selection.icons.iter()
        .any(|icon| icon.as_deref().is_some_and(|id| id != "builtin-luna"));
    if selection.font.is_none() && selection.icons.iter().all(Option::is_none) {
        return Ok(LoadedArtwork { font: None, icons: [None, None, None] });
    }
    let folder = if needs_files { Some(private_directory()?) } else { None };
    let font = selection.font.as_ref().map(|id| {
        if id == "builtin-luna-ui" {
            // Unmodified Liberation Sans, distributed under SIL OFL 1.1.
            // The font is embedded at compile time; no host font discovery,
            // shared mutable state or private asset directory is required.
            font_glyphs(include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf").to_vec(),
                        scale, true)
        } else {
            let data = read_asset(folder.as_ref().ok_or("Missing private font directory")?,
                                  id, "ttf", FONT_MAX)?;
            font_glyphs(data, scale, false)
        }
    }).transpose()?;
    let mut icons: [Option<IconPixels>; 3] = [None, None, None];
    for (index, id) in selection.icons.iter().enumerate() {
        if let Some(id) = id {
            icons[index] = Some(if id == "builtin-luna" {
                luna_icon(index)
            } else {
                icon_png(&read_asset(folder.as_ref().ok_or("Missing private icon directory")?,
                                          id, "png", ICON_MAX)?)?
            });
        }
    }
    Ok(LoadedArtwork { font, icons })
}

/// Original 48px Luna-inspired pictograms. Rasterized once at start-up; no
/// image decoder, external asset or Microsoft artwork is needed at runtime.
fn luna_icon(kind: usize) -> IconPixels {
    fn rect(pixels: &mut [u8], x: usize, y: usize, w: usize, h: usize, color: [u8; 4]) {
        for row in y..(y + h).min(48) {
            for col in x..(x + w).min(48) {
                let at = (row * 48 + col) * 4;
                pixels[at..at + 4].copy_from_slice(&color);
            }
        }
    }
    let mut pixels = vec![0; 48 * 48 * 4];
    let p = &mut pixels;
    match kind {
        0 => { // Applications: warm document folder with a blue file tab.
            rect(p, 7, 39, 35, 3, [15, 40, 70, 100]);
            rect(p, 12, 8, 24, 27, [25, 62, 125, 255]);
            rect(p, 15, 11, 18, 20, [232, 245, 255, 255]);
            rect(p, 17, 16, 14, 2, [62, 123, 190, 255]);
            rect(p, 17, 21, 10, 2, [103, 155, 204, 255]);
            rect(p, 6, 16, 20, 6, [164, 91, 23, 255]);
            rect(p, 8, 14, 17, 6, [245, 188, 70, 255]);
            rect(p, 5, 20, 38, 21, [174, 102, 26, 255]);
            rect(p, 7, 22, 34, 15, [244, 183, 57, 255]);
            rect(p, 9, 23, 30, 3, [255, 224, 128, 255]);
            rect(p, 9, 36, 30, 2, [208, 136, 35, 255]);
        }
        1 => { // Terminal: shaded CRT with an actual prompt glyph.
            rect(p, 5, 8, 38, 29, [30, 47, 70, 255]);
            rect(p, 7, 10, 34, 24, [145, 167, 186, 255]);
            rect(p, 9, 12, 30, 19, [13, 43, 70, 255]);
            rect(p, 10, 13, 28, 2, [27, 86, 114, 255]);
            rect(p, 14, 19, 3, 3, [165, 241, 222, 255]);
            rect(p, 17, 22, 3, 3, [165, 241, 222, 255]);
            rect(p, 14, 25, 3, 3, [165, 241, 222, 255]);
            rect(p, 22, 26, 10, 2, [165, 241, 222, 255]);
            rect(p, 20, 37, 8, 4, [94, 116, 140, 255]);
            rect(p, 13, 41, 22, 3, [43, 63, 88, 255]);
        }
        _ => { // Lock: silver shackle and original brass body/keyhole.
            rect(p, 14, 12, 5, 17, [64, 79, 94, 255]);
            rect(p, 17, 7, 15, 5, [88, 106, 126, 255]);
            rect(p, 29, 12, 5, 17, [64, 79, 94, 255]);
            rect(p, 16, 13, 2, 12, [203, 220, 230, 255]);
            rect(p, 19, 9, 11, 2, [203, 220, 230, 255]);
            rect(p, 31, 13, 2, 12, [203, 220, 230, 255]);
            rect(p, 9, 24, 30, 19, [119, 75, 23, 255]);
            rect(p, 11, 25, 26, 16, [223, 166, 51, 255]);
            rect(p, 12, 26, 24, 3, [255, 214, 115, 255]);
            rect(p, 12, 39, 24, 2, [169, 106, 24, 255]);
            rect(p, 22, 30, 5, 5, [69, 51, 31, 255]);
            rect(p, 23, 34, 3, 5, [69, 51, 31, 255]);
        }
    }
    IconPixels(pixels)
}

/// Composite a non-premultiplied source RGBA pixel into Wayland ARGB8888.
fn blend_pixel(canvas: &mut [u8], index: usize, r: u8, g: u8, b: u8, a: u8) {
    if a == 0 { return; }
    let old = u32::from_le_bytes(canvas[index..index + 4].try_into().expect("canvas pixel"));
    let prior = 255_u32 - u32::from(a);
    let premultiply = |new: u8, shift: u32| {
        (u32::from(new) * u32::from(a)
            + ((old >> shift) & 0xff) * prior) / 255
    };
    let blue = premultiply(b, 0);
    let green = premultiply(g, 8);
    let red = premultiply(r, 16);
    let alpha = u32::from(a) + (old >> 24) * prior / 255;
    canvas[index..index + 4]
        .copy_from_slice(&(alpha << 24 | red << 16 | green << 8 | blue).to_le_bytes());
}

pub fn paint_icon(canvas: &mut [u8], canvas_width: u32,
                  asset: &IconPixels, at_x: u32, at_y: u32) {
    for row in 0..48_u32 {
        for col in 0..48_u32 {
            let src = ((row * 48 + col) * 4) as usize;
            let dst = (((at_y + row) * canvas_width + at_x + col) * 4) as usize;
            blend_pixel(canvas, dst, asset.0[src], asset.0[src + 1],
                        asset.0[src + 2], asset.0[src + 3]);
        }
    }
}

impl FontSprites {
    fn font_for(&self, face: FontFace) -> &fontdue::Font {
        match face {
            FontFace::Primary => &self.font,
            FontFace::Fallback => self.fallback.unwrap_or(&self.font),
        }
    }

    fn select_face(&self, cluster: &str) -> Option<FontFace> {
        // Choose ONE face for an entire extended grapheme cluster. Mixing
        // fonts inside a combining sequence could paint separated marks or
        // produce inconsistencies between hit boxes, measurement and raster.
        let supported = |font: &fontdue::Font| cluster.chars().all(|letter|
            letter.is_control() || font.lookup_glyph_index(letter) != 0);
        if supported(&self.font) {
            Some(FontFace::Primary)
        } else if self.fallback.is_some_and(supported) {
            Some(FontFace::Fallback)
        } else {
            None
        }
    }

    fn resolved_letters<'a>(&'a self, text: &'a str)
        -> impl Iterator<Item = GlyphKey> + 'a {
        use unicode_segmentation::UnicodeSegmentation;
        // Missing clusters map to one readable replacement. Both font
        // selection and replacement are shared by measurement and painting.
        text.graphemes(true).flat_map(move |cluster| {
            let face = self.select_face(cluster);
            let replacement_face = if self.font.lookup_glyph_index('?') != 0 {
                FontFace::Primary
            } else if self.fallback.is_some_and(|font|
                font.lookup_glyph_index('?') != 0) {
                FontFace::Fallback
            } else {
                FontFace::Primary
            };
            std::iter::once(face.is_none().then_some((replacement_face, '?')))
                .flatten()
                .chain(cluster.chars().filter(move |letter|
                    face.is_some() && !letter.is_control()
                ).map(move |letter| (face.unwrap_or(FontFace::Primary), letter)))
        })
    }

    #[cfg(test)]
    fn displayed_letters<'a>(&'a self, text: &'a str) -> impl Iterator<Item = char> + 'a {
        self.resolved_letters(text).map(|(_, letter)| letter)
    }

    fn proportional_advance(&self, text: &str) -> f32 {
        // Kerning applies within a single font, never between distinct faces.
        let mut width = 0.0_f32;
        let mut previous: Option<GlyphKey> = None;
        for (face, letter) in self.resolved_letters(text) {
            let font = self.font_for(face);
            if let Some((left_face, left)) = previous {
                if left_face == face {
                    width += font.horizontal_kern(left, letter, self.size).unwrap_or(0.0);
                }
            }
            width += font.metrics(letter, self.size).advance_width.max(0.0);
            previous = Some((face, letter));
        }
        width.max(0.0)
    }

    /// Longest complete grapheme prefix whose actual proportional advance
    /// *with* a trailing ellipsis fits, including cross-cluster kerning
    /// only when both glyphs are from the same selected face.
    pub fn fitting_prefix_end(&self, label: &str, available: u32, suffix: char) -> usize {
        use unicode_segmentation::UnicodeSegmentation;

        if !self.proportional {
            let budget = available.saturating_sub(self.cell);
            let mut length = 0_usize;
            let mut cells = 0_u32;
            for (offset, cluster) in label.grapheme_indices(true) {
                cells = cells.saturating_add(u32::try_from(self.resolved_letters(cluster).count())
                    .unwrap_or(u32::MAX));
                if cells.saturating_mul(self.cell) > budget {
                    break;
                }
                length = offset + cluster.len();
            }
            return length;
        }

        let mut buffer = [0_u8; 4];
        let suffix_text = suffix.encode_utf8(&mut buffer);
        let (suffix_face, suffix_letter) = self.resolved_letters(suffix_text).next()
            .unwrap_or((FontFace::Primary, '?'));
        let suffix_font = self.font_for(suffix_face);
        let suffix_advance = suffix_font.metrics(suffix_letter, self.size)
            .advance_width.max(0.0);
        let mut width = 0.0_f32;
        let mut previous: Option<GlyphKey> = None;
        let mut best_end = 0_usize;
        for (offset, cluster) in label.grapheme_indices(true) {
            for (face, letter) in self.resolved_letters(cluster) {
                let font = self.font_for(face);
                if let Some((left_face, left)) = previous {
                    if left_face == face {
                        width += font.horizontal_kern(left, letter, self.size).unwrap_or(0.0);
                    }
                }
                width += font.metrics(letter, self.size).advance_width.max(0.0);
                previous = Some((face, letter));
            }
            let suffix_kern = previous.and_then(|(face, left)|
                (face == suffix_face).then(|| suffix_font
                    .horizontal_kern(left, suffix_letter, self.size).unwrap_or(0.0))
            ).unwrap_or(0.0);
            if (width + suffix_kern + suffix_advance).max(0.0).ceil() as u32 <= available {
                best_end = offset + cluster.len();
            }
        }
        best_end
    }

    pub fn measure_text(&self, text: &str) -> u32 {
        if !self.proportional {
            return u32::try_from(self.resolved_letters(text).count())
                .unwrap_or(u32::MAX).saturating_mul(self.cell);
        }
        self.proportional_advance(text).ceil() as u32
    }

    pub fn draw(&self, canvas: &mut [u8], width: u32, height: u32,
                x: u32, y: u32, text: &str, color: u32, bold: bool) {
        let mut cache = self.cache.lock().unwrap_or_else(|poison| poison.into_inner());
        let mut cursor = x as f32;
        let mut previous: Option<GlyphKey> = None;
        for (offset, (face, letter)) in self.resolved_letters(text).enumerate() {
            let font = self.font_for(face);
            if self.proportional {
                if let Some((left_face, left)) = previous {
                    if left_face == face {
                        cursor += font.horizontal_kern(left, letter, self.size).unwrap_or(0.0);
                    }
                }
            }
            let origin_x = if self.proportional { cursor.max(0.0) as u32 }
                else { x.saturating_add((offset as u32).saturating_mul(self.cell)) };
            if origin_x >= width { break; }
            let key = (face, letter);
            if !cache.glyphs.contains_key(&key) && font.lookup_glyph_index(letter) != 0 {
                let bounds = font.metrics(letter, self.size);
                if bounds.width <= 32 && bounds.height <= 32 {
                    let (metrics, pixels) = font.rasterize(letter, self.size);
                    cache.insert_dynamic(key, Glyph {
                        width: metrics.width as u32,
                        height: metrics.height as u32, xmin: metrics.xmin,
                        ymin: metrics.ymin, advance: metrics.advance_width,
                        pixels,
                    });
                }
            }
            let Some(glyph) = cache.glyphs.get(&key)
                .or_else(|| cache.glyphs.get(&(FontFace::Primary, '?')))
                .or_else(|| cache.glyphs.get(&(FontFace::Fallback, '?')))
                else { continue; };
            let (left, top, draw_width, draw_height) = if self.proportional {
                (cursor.round() as i32 + glyph.xmin,
                 y as i32 + self.size.ceil() as i32 - glyph.ymin - glyph.height as i32,
                 glyph.width, glyph.height)
            } else {
                (origin_x.saturating_add(self.cell.saturating_sub(glyph.width) / 2) as i32,
                 y.saturating_add(self.cell.saturating_sub(glyph.height) / 2) as i32,
                 glyph.width.min(self.cell), glyph.height.min(self.cell))
            };
            for row in 0..draw_height {
                for col in 0..draw_width {
                    let dx = left + col as i32;
                    let dy = top + row as i32;
                    if dx < 0 || dy < 0 || dx >= width as i32 || dy >= height as i32 {
                        continue;
                    }
                    let dx = dx as u32;
                    let dy = dy as u32;
                    let opacity = glyph.pixels[(row * glyph.width + col) as usize];
                    let a = ((color >> 24) & 0xff) as u8;
                    blend_pixel(canvas, ((dy * width + dx) * 4) as usize,
                        (color >> 16) as u8, (color >> 8) as u8,
                        color as u8, (u32::from(opacity) * u32::from(a) / 255) as u8);
                    if bold && dx + 1 < width && opacity > 0 {
                        blend_pixel(canvas, ((dy * width + dx + 1) * 4) as usize,
                            (color >> 16) as u8, (color >> 8) as u8, color as u8,
                            (u32::from(opacity) * u32::from(a) / 255) as u8);
                    }
                }
            }
            if self.proportional { cursor += glyph.advance.max(0.0); }
            previous = Some(key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn luna_icons_are_distinct_alpha_art_without_private_directory() {
        let selection = ArtworkSelection { font: None, icons: [
            Some("builtin-luna".into()), Some("builtin-luna".into()),
            Some("builtin-luna".into()),
        ] };
        let art = load(&selection, 1).unwrap();
        let icons = art.icons.map(|icon| icon.unwrap().0);
        assert_ne!(icons[0], icons[1]);
        assert_ne!(icons[1], icons[2]);
        for pixels in icons {
            assert_eq!(pixels.len(), 48 * 48 * 4);
            assert_eq!(&pixels[..4], &[0, 0, 0, 0]);
            assert!(pixels.chunks_exact(4).any(|rgba| rgba[3] == 255));
        }
    }

    #[test]
    fn bundled_luna_typeface_renders_proportional_glyphs_without_private_files() {
        let selection = ArtworkSelection { font: Some("builtin-luna-ui".into()),
                                           icons: [None, None, None] };
        let art = load(&selection, 1).unwrap();
        let font = art.font.unwrap();
        assert!(font.proportional);
        assert!(font.measure_text("WWW") > font.measure_text("iii"));
        let mut pixels = vec![0_u8; 180 * 32 * 4];
        font.draw(&mut pixels, 180, 32, 5, 4, "Luna text", 0xff_ff_ff_ff, false);
        assert!(pixels.chunks_exact(4).any(|pixel| pixel[3] > 0));
    }

    #[test]
    fn missing_font_cmap_entries_use_visible_fallback_metrics_and_pixels() {
        let selection = ArtworkSelection { font: Some("builtin-luna-ui".into()),
                                           icons: [None, None, None] };
        let art = load(&selection, 1).unwrap();
        let font = art.font.unwrap();
        // Valid Unicode noncharacter, deliberately absent from the bundled font.
        let missing = '\u{10ffff}';
        assert_eq!(font.font.lookup_glyph_index(missing), 0);
        assert_eq!(font.measure_text(&format!("A{missing}V")), font.measure_text("A?V"));
        let mut actual = vec![0_u8; 180 * 32 * 4];
        let mut expected = actual.clone();
        font.draw(&mut actual, 180, 32, 4, 4, &format!("A{missing}V"), 0xffff_ffff, false);
        font.draw(&mut expected, 180, 32, 4, 4, "A?V", 0xffff_ffff, false);
        assert_eq!(actual, expected);
        assert!(actual.iter().any(|byte| *byte != 0));
    }

    #[test]
    fn missing_multi_scalar_graphemes_paint_one_replacement_each() {
        let selection = ArtworkSelection { font: Some("builtin-luna-ui".into()),
                                           icons: [None, None, None] };
        let font = load(&selection, 1).unwrap().font.unwrap();
        for cluster in ["👩‍💻", "🇩🇪", "👍🏽"] {
            assert!(cluster.chars().any(|ch| font.font.lookup_glyph_index(ch) == 0));
            assert_eq!(font.displayed_letters(cluster).collect::<String>(), "?");
            assert_eq!(font.measure_text(cluster), font.measure_text("?"));
            let original = format!("A{cluster}V");
            let mut actual = vec![0_u8; 160 * 32 * 4];
            let mut expected = actual.clone();
            font.draw(&mut actual, 160, 32, 4, 4, &original, 0xffff_ffff, false);
            font.draw(&mut expected, 160, 32, 4, 4, "A?V", 0xffff_ffff, false);
            assert_eq!(actual, expected, "cluster: {cluster}");
        }
        assert_eq!(font.displayed_letters("🇩🇪👩‍💻").collect::<String>(), "??");
        assert_eq!(font.displayed_letters("AV").collect::<String>(), "AV");
        assert_eq!(font.displayed_letters("A\nV").collect::<String>(), "AV");
    }

    #[test]
    fn proportional_kern_pairs_align_measured_width_and_painted_cursor() {
        let selection = ArtworkSelection { font: Some("builtin-luna-ui".into()),
                                           icons: [None, None, None] };
        let art = load(&selection, 1).unwrap();
        let font = art.font.unwrap();
        let pair = "AV";
        let first = font.font.metrics('A', font.size).advance_width;
        let second = font.font.metrics('V', font.size).advance_width;
        let kerning = font.font.horizontal_kern('A', 'V', font.size).unwrap_or(0.0);
        let expected = first + second + kerning;
        assert!((font.proportional_advance(pair) - expected).abs() < 0.001);
        assert_eq!(font.measure_text(pair), expected.ceil() as u32);
        let mut paint = vec![0; 96 * 24 * 4];
        font.draw(&mut paint, 96, 24, 0, 0, pair, 0xffff_ffff, false);
        assert!(paint.chunks_exact(4).any(|p| p[3] != 0));
        // The original monospace mode preserves its strict 8px grid.
        let mono = fixture_font(1);
        if let Some(mono) = mono {
            assert_eq!(mono.measure_text(pair), 16);
        }
    }

    #[test]
    fn extra_unicode_glyph_cache_is_bounded_and_evicts_oldest() {
        let mut cache = GlyphCache { glyphs: HashMap::new(), dynamic: VecDeque::new() };
        for index in 0..DYNAMIC_GLYPH_LIMIT + 1 {
            let letter = char::from_u32(0x400 + index as u32).unwrap();
            cache.insert_dynamic((FontFace::Primary, letter), Glyph {
                width: 1, height: 1, xmin: 0, ymin: 0,
                advance: 1.0, pixels: vec![255],
            });
        }
        assert_eq!(cache.dynamic.len(), DYNAMIC_GLYPH_LIMIT);
        assert_eq!(cache.glyphs.len(), DYNAMIC_GLYPH_LIMIT);
        assert!(!cache.glyphs.contains_key(&(FontFace::Primary, '\u{400}')));
        assert!(cache.glyphs.contains_key(&(FontFace::Primary,
            char::from_u32(0x400 + DYNAMIC_GLYPH_LIMIT as u32).unwrap())));
    }

    #[test]
    fn installed_fixture_rasterizes_greek_only_when_needed() {
        let Ok(bytes) = fs::read("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf") else {
            return; // The redistributable system fixture is optional on developers' machines.
        };
        let sprites = font_glyphs(bytes, 1, false).unwrap();
        assert!(!sprites.cache.lock().unwrap().glyphs.contains_key(&(FontFace::Primary, '\u{393}')));
        let mut canvas = vec![0; 32 * 16 * 4];
        sprites.draw(&mut canvas, 32, 16, 0, 0, "\u{393}\u{03b5}", 0xffeeddcc, false);
        let cache = sprites.cache.lock().unwrap();
        assert!(cache.glyphs.contains_key(&(FontFace::Primary, '\u{393}')));
        assert!(cache.glyphs.contains_key(&(FontFace::Primary, '\u{3b5}')));
        assert!(canvas.chunks_exact(4).any(|pixel| pixel[3] != 0));
    }

    #[test]
    fn transparent_icon_preserves_background_and_opaque_pixels_replace() {
        let mut canvas = vec![0_u8; 104 * 88 * 4];
        let mut icon = IconPixels(vec![0_u8; 48 * 48 * 4]);
        icon.0[0..4].copy_from_slice(&[200, 100, 50, 255]);
        paint_icon(&mut canvas, 104, &icon, 28, 4);
        let pixel = ((4 * 104 + 28) * 4) as usize;
        assert_eq!(&canvas[pixel..pixel + 4], &0xffc86432_u32.to_le_bytes());
        let clear = ((5 * 104 + 29) * 4) as usize;
        assert_eq!(&canvas[clear..clear + 4], &[0, 0, 0, 0]);
    }
}
