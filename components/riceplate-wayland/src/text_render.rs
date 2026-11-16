//! Shared native text rendering and bounded label fitting.
//!
//! The bitmap fallback intentionally preserves the historical 8x8 output.
//! Optional native fonts are supplied by validated recipes; no global font
//! changes or text worker are needed.

use font8x8::{UnicodeFonts, BASIC_FONTS, LATIN_FONTS, GREEK_FONTS, HIRAGANA_FONTS, MISC_FONTS};
use unicode_segmentation::UnicodeSegmentation;
use crate::{raster::fill_rect, recipe::PanelStyle};

pub(crate) fn draw_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32, text: &str, color: u32) {
    draw_bitmap_text(canvas, width, height, x, y, text, color, 1, false);
}

/// Small auxiliary surfaces historically use fixed 8-pixel bitmap text. Keep
/// that default byte-for-byte for all existing rices while honoring an
/// explicitly imported native face on the calendar and OSD.
pub(crate) fn draw_auxiliary_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32,
                       text: &str, color: u32, style: &PanelStyle) {
    if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
        font.draw(canvas, width, height, x, y, text, color, style.font_bold);
    } else {
        draw_text(canvas, width, height, x, y, text, color);
    }
}

pub(crate) fn text_pixel_width(text: &str, scale: u32) -> u32 {
    // Bitmap labels have one 8x8 cell per EXTENDED GRAPHEME. A flag,
    // combining sequence or ZWJ emoji must never consume several painted
    // replacement cells while the visual hit region assumes one character.
    // This is fallback cell layout, not OpenType shaping or BiDi support.
    u32::try_from(text.graphemes(true).count()).unwrap_or(u32::MAX)
        .saturating_mul(8_u32.saturating_mul(scale))
}


/// Use measured glyph advances for native Luna rather than assumed 8px cells.
/// Other rices deliberately retain their historical bitmap layout.
pub(crate) fn rice_text_width(text: &str, style: &PanelStyle) -> u32 {
    if style.id == "xp-luna-columns" {
        if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
            return font.measure_text(text);
        }
    }
    text_pixel_width(text, style.font_scale)
}

/// Constrain labels to their actual task/menu hit rectangles, preserving
/// extended grapheme clusters (UAX #29) rather than only UTF-8 scalar values.
/// This prevents dangling accents, half of a regional flag or a partial ZWJ
/// emoji after elision. Pixel drawing/shaping remains the font renderer's job.
pub(crate) fn fit_rice_text(label: &str, available: u32, style: &PanelStyle) -> String {
    if rice_text_width(label, style) <= available {
        return label.to_owned();
    }
    let suffix = "…";
    let suffix_width = rice_text_width(suffix, style);
    if available < suffix_width {
        return String::new();
    }
    // With a proportional face, measuring graphemes independently loses
    // kerning across their boundaries (including the final ellipsis). Use
    // the font's exact advance model in a single linear pass instead.
    if style.id == "xp-luna-columns" {
        if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
            let end = font.fitting_prefix_end(label, available, '…');
            let mut fitted = String::with_capacity(end + suffix.len());
            fitted.push_str(&label[..end]);
            fitted.push_str(suffix);
            return fitted;
        }
    }
    let mut clipped = String::new();
    let mut width = 0_u32;
    for cluster in UnicodeSegmentation::graphemes(label, true) {
        let next = rice_text_width(cluster, style);
        if width.saturating_add(next) > available - suffix_width {
            break;
        }
        width = width.saturating_add(next);
        clipped.push_str(cluster);
    }
    clipped.push_str(suffix);
    clipped
}

pub(crate) fn draw_rice_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32,
                  text: &str, color: u32, style: &PanelStyle) {
    if let Some(font) = style.native_art.as_ref().and_then(|art| art.font.as_ref()) {
        font.draw(canvas, width, height, x, y, text, color, style.font_bold);
        return;
    }
    draw_bitmap_text(canvas, width, height, x, y, text, color,
                     style.font_scale, style.font_bold);
}

pub(crate) fn draw_bitmap_text(canvas: &mut [u8], width: u32, height: u32, x: u32, y: u32,
                    text: &str, color: u32, scale: u32, bold: bool) {
    let visual = crate::bidi_layout::visual_order(text);
    for (offset, cluster) in visual.graphemes(true).enumerate() {
        // The 8x8 table has no combining/ligature shaping. Never paint one
        // misleading '?' per scalar in a user-perceived glyph or detach a
        // combining mark. Unsupported clusters show ONE replacement cell;
        // single scalar Latin/Greek/Hiragana retain byte-identical sprites.
        // CRLF is one UAX #29 cluster, but remains control text. It must
        // never accidentally become a visible '?' after grapheme grouping.
        if cluster.chars().any(char::is_control) { continue; }
        let mut letters = cluster.chars();
        let first = letters.next();
        let single = first.filter(|_| letters.next().is_none());
        let bitmap = single.and_then(|letter|
            BASIC_FONTS.get(letter)
            .or_else(|| LATIN_FONTS.get(letter))
            .or_else(|| GREEK_FONTS.get(letter))
            .or_else(|| HIRAGANA_FONTS.get(letter))
            .or_else(|| MISC_FONTS.get(letter)))
            .or_else(|| BASIC_FONTS.get('?'));
        let Some(bitmap) = bitmap else { continue; };
        let origin = x.saturating_add((offset as u32)
            .saturating_mul(8_u32.saturating_mul(scale)));
        for (row, bits) in bitmap.iter().enumerate() {
            for column in 0..8_u32 {
                if *bits & (1_u8 << column) != 0 {
                    fill_rect(
                        canvas,
                        width,
                        height,
                        origin.saturating_add(column * scale),
                        y.saturating_add(row as u32 * scale),
                        scale + u32::from(bold && column < 7),
                        scale,
                        color,
                    );
                }
            }
        }
    }
}



#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rtl_bitmap_raster_follows_unicode_runs_without_split_clusters() {
        // Bitmap glyphs are available for ASCII; compare a mixed label
        // against its Unicode BiDi visual order at the pixel level.
        let logical = "אבגabc";
        let visual = crate::bidi_layout::visual_order(logical);
        assert_eq!(visual, "abcגבא");
        let mut actual = vec![0_u8; 6 * 8 * 8 * 4];
        let mut reference = actual.clone();
        draw_bitmap_text(&mut actual, 48, 8, 0, 0, logical, 0xffff_ffff, 1, false);
        // Hebrew is unsupported in this 8x8 table: exactly three '?' cells,
        // after the Latin run, without affecting existing Latin glyphs.
        draw_bitmap_text(&mut reference, 48, 8, 0, 0, "abc???", 0xffff_ffff, 1, false);
        assert_eq!(actual, reference);
        assert_eq!(text_pixel_width(logical, 1), 48);
    }

    #[test]
    fn glyph_widths_count_complete_graphemes_not_utf8_bytes_or_scalars() {
        assert_eq!(text_pixel_width("Aéλ", 2), 48);
        assert_eq!(text_pixel_width("a\u{301}👩‍💻🇩🇪", 2), 48);
        assert_eq!(text_pixel_width("", 2), 0);
        assert_eq!(text_pixel_width("A", u32::MAX), u32::MAX);
    }

    #[test]
    fn bitmap_fallback_has_exactly_one_cell_for_multi_scalar_graphemes() {
        let text = "A👩‍💻🇩🇪a\u{301}V";
        assert_eq!(text_pixel_width(text, 1), 40);
        let mut actual = vec![0_u8; 40 * 8 * 4];
        let mut expected = actual.clone();
        draw_bitmap_text(&mut actual, 40, 8, 0, 0, text, 0xffff_ffff, 1, false);
        draw_bitmap_text(&mut expected, 40, 8, 0, 0, "A???V", 0xffff_ffff, 1, false);
        assert_eq!(actual, expected, "Fallback and hit-measurement disagree");
        assert!(actual.iter().any(|&value| value != 0));
    }

    #[test]
    fn joined_control_cluster_remains_blank_not_a_visible_replacement() {
        let mut actual = vec![0_u8; 24 * 8 * 4];
        let mut expected = actual.clone();
        draw_bitmap_text(&mut actual, 24, 8, 0, 0, "A\r\nB", 0xffff_ffff, 1, false);
        draw_bitmap_text(&mut expected, 24, 8, 0, 0, "A B", 0xffff_ffff, 1, false);
        assert_eq!(actual, expected);
        assert_eq!(text_pixel_width("A\r\nB", 1), 24);
    }

    #[test]
    fn long_labels_fit_without_splitting_unicode_or_allocating_per_glyph() {
        let classic = crate::recipe::load("classic").expect("built-in classic recipe");
        let cell = 8 * classic.font_scale;
        assert_eq!(fit_rice_text("ÄBC", cell * 2, &classic), "Ä…");
        assert_eq!(fit_rice_text("ÄBC", cell - 1, &classic), "");
        assert_eq!(fit_rice_text("ÄB", cell * 2, &classic), "ÄB");
    }

    #[test]
    fn ellipsis_does_not_cut_accent_zwj_emoji_or_regional_flag_pairs() {
        let classic = crate::recipe::load("classic").unwrap();
        let cell = 8 * classic.font_scale;
        // Fitting a base character while cutting away its combining mark
        // would produce visibly incomplete user-facing text.
        assert_eq!(fit_rice_text("a\u{301}bc", cell, &classic), "…");
        assert_eq!(fit_rice_text("a\u{301}bc", cell * 2, &classic),
                   "a\u{301}…");
        assert_eq!(fit_rice_text("a\u{301}bc", cell * 3, &classic),
                   "a\u{301}bc");
        // One fallback glyph = one measured cell, without splitting or
        // spraying question marks across the neighboring control.
        assert_eq!(fit_rice_text("👩‍💻 task", cell * 2, &classic), "👩‍💻…");
        assert_eq!(fit_rice_text("🇩🇪 done", cell * 2, &classic), "🇩🇪…");
        assert_eq!(fit_rice_text("👍🏽 done", cell * 2, &classic), "👍🏽…");
        assert_eq!(fit_rice_text("ABC", cell * 3, &classic), "ABC");
        assert_eq!(fit_rice_text("A長い", cell * 2, &classic), "A…");
    }

    #[test]
    fn proportional_fit_uses_actual_kerning_including_the_ellipsis() {
        let mut luna = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns"),
        ).unwrap();
        luna.native_art = Some(crate::style_art::load(
            luna.artwork.as_ref().unwrap(), luna.font_scale,
        ).unwrap());
        for label in ["AVATAR Tomorrow", "To AVA", "a\u{301} and AV", "🇩🇪 Done",
                      "👩‍💻 Workspace", "WWW iii"] {
            for available in 0..=rice_text_width(label, &luna) {
                let actual = fit_rice_text(label, available, &luna);
                // Independent brute-force oracle: fit the *entire* painted
                // prefix plus suffix, not the sum of individual advances.
                let expected = if rice_text_width(label, &luna) <= available {
                    label.to_string()
                } else if rice_text_width("…", &luna) > available {
                    String::new()
                } else {
                    let mut best = "…".to_string();
                    let mut prefix = String::new();
                    for grapheme in UnicodeSegmentation::graphemes(label, true) {
                        prefix.push_str(grapheme);
                        let candidate = format!("{prefix}…");
                        if rice_text_width(&candidate, &luna) <= available {
                            best = candidate;
                        }
                    }
                    best
                };
                assert_eq!(actual, expected, "{label:?} in {available}px");
                assert!(rice_text_width(&actual, &luna) <= available);
            }
        }
    }

    #[test]
    fn unsupported_glyphs_have_visible_bitmap_fallback_and_clipping() {
        let mut frame = vec![0_u8; 8 * 8 * 4];
        draw_bitmap_text(&mut frame, 8, 8, 0, 0, "🦀", 0xff12_3456, 1, false);
        assert!(frame.chunks_exact(4).any(|pixel| pixel != [0, 0, 0, 0]));
        // Text partly or completely outside the surface must be harmless.
        draw_bitmap_text(&mut frame, 8, 8, u32::MAX, 0, "Long", 0xffff_ffff, 1, false);
    }
}
