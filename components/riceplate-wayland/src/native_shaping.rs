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
    let shaped = rustybuzz::shape(&face, &[], buffer);
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

#[cfg(test)]
mod tests {
    use super::*;

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
