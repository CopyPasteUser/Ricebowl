//! OpenType shaping primitives for non-ASCII native font labels.
//!
//! Shape logical Unicode runs with rustybuzz (GSUB/GPOS, script inference,
//! combining marks) and rasterize the returned *glyph indices* with fontdue.
//! This module does not accept scripts/commands or load a host font itself.

#[derive(Debug, Clone, Copy)]
pub(crate) struct ShapedGlyph {
    pub(crate) id: u16,
    pub(crate) advance: f32,
    pub(crate) x_offset: f32,
    pub(crate) y_offset: f32,
}

/// The caller owns directional UAX #9 run segmentation and font-face
/// selection. UnicodeBuffer must see characters in their *logical* order;
/// reversing Arabic scalars before GSUB would break contextual joining.
pub(crate) fn shape_segment(
    bytes: &[u8],
    size: f32,
    text: &str,
    rtl: bool,
) -> Option<Vec<ShapedGlyph>> {
    if text.is_empty() {
        return Some(Vec::new());
    }
    if text.len() > 2048 || !size.is_finite() || size <= 0.0 {
        return None;
    }
    let face = rustybuzz::Face::from_slice(bytes, 0)?;
    shape_with_face(&face, size, text, rtl)
}

/// Same as [`shape_segment`] for an already parsed face (cached system fonts).
pub(crate) fn shape_with_face(
    face: &rustybuzz::Face<'_>,
    size: f32,
    text: &str,
    rtl: bool,
) -> Option<Vec<ShapedGlyph>> {
    if text.is_empty() {
        return Some(Vec::new());
    }
    if text.len() > 2048 || !size.is_finite() || size <= 0.0 {
        return None;
    }
    let units = face.units_per_em();
    if units <= 0 {
        return None;
    }
    let mut buffer = rustybuzz::UnicodeBuffer::new();
    buffer.push_str(text);
    buffer.guess_segment_properties();
    buffer.set_direction(if rtl {
        rustybuzz::Direction::RightToLeft
    } else {
        rustybuzz::Direction::LeftToRight
    });
    let shaped = rustybuzz::shape(face, &[], buffer);
    if shaped.len() > 1024 {
        return None;
    }
    let factor = size / units as f32;
    let glyphs = shaped
        .glyph_infos()
        .iter()
        .zip(shaped.glyph_positions().iter())
        .map(|(glyph, position)| {
            let id = u16::try_from(glyph.glyph_id).ok()?;
            Some(ShapedGlyph {
                id,
                advance: position.x_advance as f32 * factor,
                x_offset: position.x_offset as f32 * factor,
                y_offset: position.y_offset as f32 * factor,
            })
        })
        .collect::<Option<Vec<_>>>()?;
    Some(glyphs)
}

/// SG5 positive script-font fixtures. These are *installed* freely licensed
/// fonts (Debian/Ubuntu `fonts-lohit-deva`, `fonts-wqy-microhei`); RicePlate
/// bundles no script fonts. A missing or non-covering font is a loud, explicit
/// failure of the positive tests, never a silent pass or a coverage claim.
#[cfg(test)]
pub(crate) mod script_fonts {
    pub(crate) const DEVANAGARI: &[&str] =
        &["/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"];
    pub(crate) const CJK: &[&str] = &["/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"];

    #[derive(Debug)]
    pub(crate) enum Availability {
        Covered(Vec<u8>),
        /// No candidate file exists or none parses as a font.
        Unavailable,
        /// A font exists but its cmap lacks a scalar of the sample text.
        LacksGlyphs(char),
    }

    pub(crate) fn probe(candidates: &[&str], sample: &str) -> Availability {
        for path in candidates {
            let Ok(bytes) = std::fs::read(path) else {
                continue;
            };
            let Ok(face) = rustybuzz::Face::from_slice(&bytes, 0).ok_or(()) else {
                continue;
            };
            if let Some(missing) = sample
                .chars()
                .find(|&ch| face.glyph_index(ch).is_none_or(|g| g.0 == 0))
            {
                return Availability::LacksGlyphs(missing);
            }
            return Availability::Covered(bytes);
        }
        Availability::Unavailable
    }

    /// The font bytes, or a panic that says plainly the font is unavailable.
    pub(crate) fn require(candidates: &[&str], sample: &str, package: &str) -> Vec<u8> {
        match probe(candidates, sample) {
            Availability::Covered(bytes) => bytes,
            Availability::Unavailable => panic!(
                "FONT UNAVAILABLE: install `{package}` ({candidates:?}); script coverage for \
                 {sample:?} is NOT verified"
            ),
            Availability::LacksGlyphs(ch) => panic!(
                "FONT UNAVAILABLE: installed font lacks U+{:04X} for {sample:?}; script \
                 coverage is NOT verified",
                ch as u32
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::script_fonts::{self, Availability};
    use super::*;

    #[test]
    fn script_font_probe_never_reports_coverage_for_missing_or_noncovering_fonts() {
        // Always runs, in CI and locally: the negative half of the SG5 matrix.
        assert!(matches!(
            script_fonts::probe(&["/nonexistent/ricebowl/NoSuchFont.ttf"], "हिन्दी"),
            Availability::Unavailable
        ));
        let latin_only = include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf");
        let dir = std::env::temp_dir().join(format!("rb-font-probe-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("latin.ttf");
        std::fs::write(&path, latin_only).unwrap();
        let path_text = path.to_str().unwrap();
        for sample in ["हिन्दी", "日本語"] {
            assert!(
                matches!(
                    script_fonts::probe(&[path_text], sample),
                    Availability::LacksGlyphs(_)
                ),
                "a Latin-only font must not count as {sample} coverage"
            );
        }
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn devanagari_gsub_reorders_matra_and_forms_conjunct_unlike_cmap() {
        let bytes = script_fonts::require(script_fonts::DEVANAGARI, "हिन्दी", "fonts-lohit-deva");
        let face = rustybuzz::Face::from_slice(&bytes, 0).unwrap();
        let cmap = |text: &str| -> Vec<u16> {
            text.chars()
                .map(|ch| face.glyph_index(ch).unwrap().0)
                .collect()
        };
        let shaped =
            |text: &str| -> Vec<ShapedGlyph> { shape_segment(&bytes, 16.0, text, false).unwrap() };
        let ids = |glyphs: &[ShapedGlyph]| -> Vec<u16> { glyphs.iter().map(|g| g.id).collect() };

        // 1. Pre-base I matra: logically after HA (U+0939 U+093F) but the
        //    shaped run must lead with the matra glyph and end with HA.
        let naive = cmap("हि");
        let hi = shaped("हि");
        assert_ne!(ids(&hi), naive, "GSUB/GPOS must not equal naive cmap order");
        assert_eq!(hi.len(), 2);
        assert_ne!(
            hi[0].id, naive[0],
            "matra is reordered before the consonant"
        );
        assert!(hi.iter().all(|g| g.id != 0));

        // 2. Halant conjunct NA+VIRAMA+DA must collapse (ligature/half form).
        let conjunct = shaped("न्द");
        assert!(
            conjunct.len() < 3 || ids(&conjunct) != cmap("न्द"),
            "conjunct must be GSUB-substituted, not three cmap glyphs"
        );

        // 3. The whole word: different glyph IDs than naive cmap, nonzero
        //    bounded advances, no .notdef.
        let word = shaped("हिन्दी");
        assert_ne!(ids(&word), cmap("हिन्दी"));
        assert!(word.iter().all(|g| g.id != 0));
        let total: f32 = word.iter().map(|g| g.advance).sum();
        assert!(
            total > 8.0 && total < 16.0 * 6.0,
            "advance sum {total} not bounded"
        );
        assert!(word
            .iter()
            .all(|g| g.advance.is_finite() && g.advance >= 0.0 && g.x_offset.abs() < 32.0));
        assert!(word.iter().any(|g| g.advance > 0.0));
    }

    #[test]
    fn cjk_cmap_glyphs_have_nonzero_bounded_full_width_advances() {
        let bytes =
            script_fonts::require(script_fonts::CJK, "日本語中文한국어", "fonts-wqy-microhei");
        for text in ["日本語", "中文"] {
            let glyphs = shape_segment(&bytes, 16.0, text, false).unwrap();
            assert_eq!(glyphs.len(), text.chars().count());
            assert!(glyphs.iter().all(|g| g.id != 0));
            for glyph in &glyphs {
                assert!(
                    glyph.advance > 8.0 && glyph.advance <= 20.0,
                    "{text}: advance {} outside bounded full-width range",
                    glyph.advance
                );
            }
        }
    }

    #[test]
    fn simple_latin_shaping_uses_same_advance_order_of_magnitude_as_fontdue() {
        let bytes = include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf");
        let font =
            fontdue::Font::from_bytes(bytes.as_slice(), fontdue::FontSettings::default()).unwrap();
        let layout = shape_segment(bytes, 11.0, "AVATAR", false).unwrap();
        assert_eq!(layout.len(), 6);
        assert!(layout.iter().all(|glyph| glyph.id > 0));
        let width: f32 = layout.iter().map(|g| g.advance).sum();
        let direct: f32 = "AVATAR"
            .chars()
            .map(|ch| font.metrics(ch, 11.0).advance_width)
            .sum();
        assert!(width > 0.0 && width < direct + 5.0);
    }

    #[test]
    fn shaping_refuses_unbounded_input_or_missing_font() {
        let font = include_bytes!("../../../assets/fonts/LiberationSans-Regular.ttf");
        assert!(shape_segment(font, 11.0, &"A".repeat(3000), false).is_none());
        assert!(shape_segment(b"not a font", 11.0, "Hello", false).is_none());
        assert!(shape_segment(font, f32::NAN, "Hello", false).is_none());
        assert_eq!(shape_segment(font, 11.0, "", true).unwrap().len(), 0);
    }
}
