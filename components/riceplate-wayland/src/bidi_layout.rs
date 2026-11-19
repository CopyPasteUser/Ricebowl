//! Single-line Unicode BiDi layout for the native label rasterizers.
//!
//! Resolves UAX #9 embedding levels and reorders whole *grapheme clusters*
//! (UAX #29), never bytes or combining marks. Existing LTR labels remain
//! borrowed, allocation-free and byte-identical. Common paired punctuation
//! gets Unicode 18 UCD character-based L4 mirroring in odd-level runs.
//! Font-level mirroring when no alternate code point exists, multi-line
//! layout and IME remain separate SG5 work. This module also exposes visual grapheme edges for single-line
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
    // Editors measure and visit every caret after one reorder. Store the
    // inverse once instead of scanning the visual permutation per caret.
    logical_to_visual: Vec<usize>,
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
        let visual = self.logical_to_visual[logical];
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
    let visual_to_logical = BidiInfo::reorder_visual(&levels);
    // UAX #9 returns a permutation of grapheme indices. Build its inverse
    // in O(n): editor visual-arrow selection and painted caret layout then
    // need only O(1) per edge instead of searching n entries every time.
    let mut logical_to_visual = vec![0; visual_to_logical.len()];
    for (visual, &logical) in visual_to_logical.iter().enumerate() {
        logical_to_visual[logical] = visual;
    }
    Some(VisualClusterMap {
        visual_to_logical,
        logical_to_visual,
        rtl_by_logical,
    })
}

/// Resolve an editor Left/Right key against *painted* bidi caret edges.
/// The selected text stays in logical order; only navigation order changes.
/// LTR text does not allocate or enter this path. At run boundaries with
/// multiple equivalent visual positions, prefer the nearest logical caret
/// deterministically instead of jumping unpredictably.
pub(crate) fn visual_arrow_target(
    text: &str, cursor: usize, toward_right: bool,
) -> Option<usize> {
    let map = visual_cluster_map(text)?;
    let count = map.visual_to_logical.len();
    let current = cursor.min(count);
    let current_edge = map.caret_edge(current);
    let mut best: Option<(usize, usize)> = None;
    for candidate in 0..=count {
        let edge = map.caret_edge(candidate);
        if (toward_right && edge <= current_edge)
            || (!toward_right && edge >= current_edge) {
            continue;
        }
        let better = match best {
            None => true,
            Some((other, other_edge)) => {
                let closer = if toward_right { edge < other_edge }
                    else { edge > other_edge };
                closer || (edge == other_edge
                    && candidate.abs_diff(current) < other.abs_diff(current))
            }
        };
        if better { best = Some((candidate, edge)); }
    }
    Some(best.map(|(candidate, _)| candidate).unwrap_or(current))
}

/// Unicode BiDi rule L4: use the *display glyph* of common paired
/// punctuation in odd-level runs. This intentionally does not rewrite the
/// logical label or editor buffer. Leave unfamiliar characters unchanged
/// rather than guessing at a visually or semantically incorrect substitute.
/// U+FD3E/U+FD3F ornate parentheses deliberately are not mirrored.
fn mirrored_punctuation(ch: char) -> char {
    crate::bidi_mirroring::mirrored(ch)
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
        let cluster = clusters[index];
        if map.rtl_by_logical[index] {
            let mut chars = cluster.chars();
            if let Some(first) = chars.next() {
                reordered.push(mirrored_punctuation(first));
                // Keep grapheme-internal combining marks and ZWJ sequences
                // together; only the visible base punctuation can change.
                reordered.extend(chars);
            }
        } else {
            reordered.push_str(cluster);
        }
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
    fn unicode_l4_brackets_mirror_only_in_rtl_visual_runs() {
        for (a, b) in [('(', ')'), ('[', ']'), ('{', '}'),
                       ('<', '>'), ('«', '»'), ('‹', '›'),
                       ('⟨', '⟩'), ('〈', '〉'), ('（', '）')] {
            assert_eq!(mirrored_punctuation(a), b);
            assert_eq!(mirrored_punctuation(b), a);
        }
        // The mirrored glyph is a paint-only transform: the logical text,
        // classic LTR screenshots and the caret map remain unchanged.
        let rtl = "אבג(";
        let before = visual_cluster_map(rtl).unwrap();
        assert_eq!(visual_order(rtl), ")גבא");
        let after = visual_cluster_map(rtl).unwrap();
        assert_eq!(before.visual_to_logical, after.visual_to_logical);
        assert!(matches!(visual_order("Hello (world)"), Cow::Borrowed(_)));
        assert_eq!(mirrored_punctuation('﴾'), '﴾');
        assert_eq!(mirrored_punctuation('﴿'), '﴿');
    }

    #[test]
    fn full_unicode18_mapping_is_paint_only_across_non_latin_brackets() {
        // Previously unsupported Tibetans, bracket families and a
        // supplementary-plane mathematical symbol must be mirrored in RTL.
        for (left, right) in [
            ('⟦', '⟧'), ('⟪', '⟫'), ('\u{0F3A}', '\u{0F3B}'),
            ('\u{221D}', '\u{1DB10}'),
        ] {
            assert_eq!(mirrored_punctuation(left), right);
            assert_eq!(mirrored_punctuation(right), left);
        }
        let logical = "אבג⟦";
        assert_eq!(visual_order(logical), "⟧גבא");
        assert_eq!(visual_cluster_map(logical).unwrap().visual_to_logical,
                   [3, 2, 1, 0]);
        assert_eq!(visual_order("plain ⟦LTR⟧"), "plain ⟦LTR⟧");
        assert_eq!(visual_order("שלום 👩‍💻"), "👩‍💻 םולש");
        // Ornate parentheses have Bidi_Mirrored=Yes but NO alternate
        // Unicode scalar mapping; do not invent one.
        assert_eq!(mirrored_punctuation('﴾'), '﴾');
        assert_eq!(mirrored_punctuation('﴿'), '﴿');
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
    fn arrows_follow_visual_caret_order_without_reversing_stored_text() {
        let rtl = "אבג";
        assert_eq!(visual_arrow_target(rtl, 0, false), Some(1));
        assert_eq!(visual_arrow_target(rtl, 1, false), Some(2));
        assert_eq!(visual_arrow_target(rtl, 2, true), Some(1));
        assert_eq!(visual_arrow_target(rtl, 3, false), Some(3));
        assert_eq!(visual_arrow_target(rtl, 0, true), Some(0));

        let mixed = "abc אבג";
        assert_eq!(visual_arrow_target(mixed, 3, true), Some(7));
        assert_eq!(visual_arrow_target(mixed, 7, true), Some(6));
        assert_eq!(visual_arrow_target(mixed, 6, false), Some(7));
        assert_eq!(visual_arrow_target(mixed, 4, false), Some(5));

        assert_eq!(visual_arrow_target("plain English", 2, true), None);
        assert_eq!(visual_arrow_target("אבג\nabc", 2, false), None);
    }

    #[test]
    fn pure_rtl_caret_edges_follow_painted_visual_clusters() {
        let map = visual_cluster_map("אבג").unwrap();
        assert_eq!(map.visual_to_logical, [2, 1, 0]);
        assert_eq!((0..=3).map(|i| map.caret_edge(i)).collect::<Vec<_>>(),
                   [3, 2, 1, 0]);
    }

    #[test]
    fn inverse_caret_map_matches_original_search_for_long_unicode_editor_lines() {
        // The old map walked visual_to_logical for *each* caret. Keep an
        // independent oracle for the exact legacy caret semantics, including
        // run boundaries, combined accents and joined Unicode emoji.
        let long = "abc אבג مرحبا 👩‍💻 🇩🇪 ".repeat(8);
        for text in ["אבג", "abc אבג", "مرحبا 👩‍💻 🇩🇪 A\u{301} עברית", &long] {
            let map = visual_cluster_map(text).expect("contains an RTL run");
            let len = map.visual_to_logical.len();
            assert_eq!(map.logical_to_visual.len(), len);
            for logical in 0..len {
                let reference = map.visual_to_logical.iter()
                    .position(|&value| value == logical).unwrap();
                assert_eq!(map.logical_to_visual[logical], reference);
            }
            for cursor in 0..=len {
                let at_end = cursor == len;
                let logical = if at_end { len - 1 } else { cursor };
                let reference = map.visual_to_logical.iter()
                    .position(|&value| value == logical).unwrap();
                let expected = if map.rtl_by_logical[logical] == at_end {
                    reference
                } else {
                    reference + 1
                };
                assert_eq!(map.caret_edge(cursor), expected, "cursor={cursor} text={text:?}");
            }
            // Calling visual-order painting must never rewrite logical input.
            assert_eq!(text.graphemes(true).count(), len);
        }
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
