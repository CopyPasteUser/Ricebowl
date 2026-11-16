//! Single-line Unicode BiDi layout for the native label rasterizers.
//!
//! Resolves UAX #9 embedding levels and reorders whole *grapheme clusters*
//! (UAX #29), never bytes or combining marks. Existing LTR labels remain
//! borrowed, allocation-free and byte-identical. Glyph shaping, mirroring,
//! multi-line paragraphs and input-method preedit remain separate SG5
//! requirements. This module also exposes visual grapheme edges for single-line
//! editor caret hit-testing; it does not perform OpenType shaping.
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
/// Visual cluster permutation and directional edges for a *single-line*
/// editor. Indices refer to UAX #29 graphemes in logical storage order.
/// Always derive a map from the exact visible substring: UAX #9 embedding
/// levels may change at a truncation or paragraph boundary.
pub(crate) struct VisualClusterMap {
    pub(crate) visual_to_logical: Vec<usize>,
    rtl_by_logical: Vec<bool>,
}

impl VisualClusterMap {
    /// A logical caret is before grapheme N (or after the last grapheme).
    /// At a BiDi run boundary two visual positions may be valid; consistently
    /// prefer the leading edge of the following logical grapheme.
    pub(crate) fn caret_edge(&self, cursor: usize) -> usize {
        let len = self.visual_to_logical.len();
        if len == 0 { return 0; }
        let at_end = cursor >= len;
        let logical = if at_end { len - 1 } else { cursor };
        let visual = self.visual_to_logical.iter().position(|&i| i == logical)
            .expect("reordering is a permutation");
        if self.rtl_by_logical[logical] == at_end { visual } else { visual + 1 }
    }
}

pub(crate) fn visual_cluster_map(text: &str) -> Option<VisualClusterMap> {
    if !has_rtl(text) || text.contains('\r') || text.contains('\n') {
        return None;
    }
    let info = BidiInfo::new(text, None);
    let para = (info.paragraphs.len() == 1).then(|| &info.paragraphs[0])?;
    if !info.has_rtl() { return None; }
    let per_char = info.reordered_levels_per_char(para, para.range.clone());
    let clusters: Vec<&str> = text.graphemes(true).collect();
    let mut levels = Vec::with_capacity(clusters.len());
    let mut offset = 0_usize;
    for cluster in &clusters {
        levels.push(*per_char.get(offset)?);
        offset += cluster.chars().count();
    }
    if offset != per_char.len() { return None; }
    let rtl_by_logical = levels.iter().map(|level| level.is_rtl()).collect();
    Some(VisualClusterMap {
        visual_to_logical: BidiInfo::reorder_visual(&levels),
        rtl_by_logical,
    })
}

/// Return the visual-order grapheme sequence for a *single-line* label.
/// LTR and unsupported paragraph inputs keep their existing borrowed path.
pub(crate) fn visual_order(text: &str) -> Cow<'_, str> {
    let Some(map) = visual_cluster_map(text) else {
        return Cow::Borrowed(text);
    };
    let clusters: Vec<&str> = text.graphemes(true).collect();
    let mut reordered = String::with_capacity(text.len());
    for index in map.visual_to_logical {
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
    #[test]
    fn pure_rtl_caret_edges_follow_painted_visual_clusters() {
        let map = visual_cluster_map("אבג").unwrap();
        assert_eq!(map.visual_to_logical, [2, 1, 0]);
        assert_eq!((0..=3).map(|i| map.caret_edge(i)).collect::<Vec<_>>(),
                   [3, 2, 1, 0]);
    }

    #[test]
    fn mixed_bidi_run_boundaries_preserve_logical_storage() {
        let map = visual_cluster_map("abc אבג").unwrap();
        assert_eq!(map.visual_to_logical, [0, 1, 2, 3, 6, 5, 4]);
        assert_eq!((0..=7).map(|i| map.caret_edge(i)).collect::<Vec<_>>(),
                   [0, 1, 2, 3, 7, 6, 5, 4]);
        assert!(visual_cluster_map("regular ASCII").is_none());
        assert!(visual_cluster_map("אבג\nabc").is_none());
    }

}
