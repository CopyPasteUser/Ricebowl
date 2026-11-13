//! Shared native text rendering and bounded label fitting.
//!
//! The bitmap fallback intentionally preserves the historical 8x8 output.
//! Optional native fonts are supplied by validated recipes; no global font
//! changes or text worker are needed.

use font8x8::{UnicodeFonts, BASIC_FONTS, LATIN_FONTS, GREEK_FONTS, HIRAGANA_FONTS, MISC_FONTS};
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
    // Every native glyph advances one cell, even when its UTF-8 encoding uses
    // multiple bytes. This is a monospace width, not a Unicode shaping claim.
    u32::try_from(text.chars().count()).unwrap_or(u32::MAX)
        .saturating_mul(8 * scale)
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

/// Constrain labels to their actual task/menu hit rectangles, without splitting
/// UTF-8 characters or letting long localized XDG names overlap neighbours.
pub(crate) fn fit_rice_text(label: &str, available: u32, style: &PanelStyle) -> String {
    if rice_text_width(label, style) <= available {
        return label.to_owned();
    }
    let suffix = "…";
    let suffix_width = rice_text_width(suffix, style);
    if available < suffix_width {
        return String::new();
    }
    let mut clipped = String::new();
    let mut width = 0_u32;
    for letter in label.chars() {
        let mut utf8 = [0; 4];
        let next = rice_text_width(letter.encode_utf8(&mut utf8), style);
        if width.saturating_add(next) > available - suffix_width {
            break;
        }
        width = width.saturating_add(next);
        clipped.push(letter);
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
    for (offset, character) in text.chars().enumerate() {
        if character.is_control() { continue; }
        // The existing 8x8 renderer is intentionally allocation-free: support
        // the crate's non-ASCII tables and show a visible replacement glyph
        // instead of silently erasing unsupported scripts.
        let bitmap = BASIC_FONTS.get(character)
            .or_else(|| LATIN_FONTS.get(character))
            .or_else(|| GREEK_FONTS.get(character))
            .or_else(|| HIRAGANA_FONTS.get(character))
            .or_else(|| MISC_FONTS.get(character))
            .or_else(|| BASIC_FONTS.get('?'));
        let Some(bitmap) = bitmap else { continue; };
        let origin = x.saturating_add((offset as u32).saturating_mul(8 * scale));
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
    fn glyph_widths_count_characters_not_utf8_bytes() {
        assert_eq!(text_pixel_width("Aéλ", 2), 48);
        assert_eq!(text_pixel_width("", 2), 0);
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
    fn unsupported_glyphs_have_visible_bitmap_fallback_and_clipping() {
        let mut frame = vec![0_u8; 8 * 8 * 4];
        draw_bitmap_text(&mut frame, 8, 8, 0, 0, "🦀", 0xff12_3456, 1, false);
        assert!(frame.chunks_exact(4).any(|pixel| pixel != [0, 0, 0, 0]));
        // Text partly or completely outside the surface must be harmless.
        draw_bitmap_text(&mut frame, 8, 8, u32::MAX, 0, "Long", 0xffff_ffff, 1, false);
    }
}
