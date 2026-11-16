//! Single-line Unicode BiDi layout for the native label rasterizers.
//!
//! Resolves UAX #9 embedding levels and reorders whole *grapheme clusters*
//! (UAX #29), never bytes or combining marks. Existing LTR labels remain
//! borrowed, allocation-free and byte-identical. Glyph shaping, mirroring,
//! multi-line paragraphs, input-method preedit and caret mapping are separate
//! SG5 requirements, not provided by this module.
use std::borrow::Cow;
use unicode_bidi::{bidi_class, BidiClass, BidiInfo};
use unicode_segmentation::UnicodeSegmentation;

/// Do not run a paragraph analysis for ordinary LTR system labels.
pub(crate) fn has_rtl(text: &str) -> bool {
    !text.is_ascii() && text.chars().any(|letter| matches!(bidi_class(letter),
        BidiClass::R | BidiClass::AL | BidiClass::RLI |
        BidiClass::RLE | BidiClass::RLO | BidiClass::FSI))
}

/// Return the visual-order grapheme sequence for a *single-line* label.
///
/// The library computes embedding levels. We then apply its reordering map to
/// extended grapheme clusters, not individual UTF-8 bytes or Unicode scalars.
/// This avoids separating base letters from their combining marks, flags and
/// joined emoji. The underlying font renderer still uses fontdue per glyph;
/// this is not contextual Arabic shaping or bracket glyph mirroring.
pub(crate) fn visual_order(text: &str) -> Cow<'_, str> {
    if !has_rtl(text) || text.contains(['\r', '\n']) {
        return Cow::Borrowed(text);
    }
    let info = BidiInfo::new(text, None);
    let Some(para) = (info.paragraphs.len() == 1).then(|| &info.paragraphs[0]) else {
        return Cow::Borrowed(text);
    };
    if !info.has_rtl() { return Cow::Borrowed(text); }
    let per_char = info.reordered_levels_per_char(para, para.range.clone());
    let clusters: Vec<&str> = text.graphemes(true).collect();
    let mut levels = Vec::with_capacity(clusters.len());
    let mut character_offset = 0_usize;
    for cluster in &clusters {
        let Some(level) = per_char.get(character_offset) else {
            // Refuse a partial or malformed mapping rather than split text.
            return Cow::Borrowed(text);
        };
        levels.push(*level);
        character_offset += cluster.chars().count();
    }
    if character_offset != per_char.len() {
        return Cow::Borrowed(text);
    }
    let visual = BidiInfo::reorder_visual(&levels);
    let mut reordered = String::with_capacity(text.len());
    for index in visual {
        reordered.push_str(clusters[index]);
    }
    Cow::Owned(reordered)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ltr_fast_path_preserves_original_bytes_and_borrows() {
        for input in ["Taskbar", "AVATAR", "日本語", "👩‍💻", "A\u{301}VP"] {
            assert!(matches!(visual_order(input), Cow::Borrowed(_)));
            assert_eq!(visual_order(input), input);
        }
    }

    #[test]
    fn rtl_reorders_runs_without_reversing_latin_or_splitting_graphemes() {
        assert_eq!(visual_order("אבגabc"), "abcגבא");
        assert_eq!(visual_order("אבג a\u{301}"), "a\u{301} גבא");
        assert_eq!(visual_order("אבג 👩‍💻"), "👩‍💻 גבא");
        assert_eq!(visual_order("abc אבג"), "abc גבא");
        assert_eq!(visual_order("אבג\nabc"), "אבג\nabc");
    }

    #[test]
    fn visual_map_preserves_grapheme_inventory_and_utf8() {
        for input in ["שלום 123 test", "A\u{301} שלום 👩‍💻 🇩🇪", "עברית ABC 42"] {
            let output = visual_order(input);
            let mut before: Vec<_> = input.graphemes(true).collect();
            let mut after: Vec<_> = output.graphemes(true).collect();
            before.sort_unstable();
            after.sort_unstable();
            assert_eq!(before, after);
            assert_eq!(input.chars().count(), output.chars().count());
        }
    }
}
