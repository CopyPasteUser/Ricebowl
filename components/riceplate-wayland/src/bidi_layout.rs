//! Single-line Unicode BiDi layout for the native labels and editors.
//!
//! Resolves UAX #9 embedding levels with the paragraph direction of rules
//! P2/P3 (or a widget-forced direction) and reorders whole *grapheme
//! clusters* (UAX #29), never bytes or combining marks. Existing LTR labels
//! remain borrowed, allocation-free and byte-identical. Common paired
//! punctuation gets Unicode 18 UCD character-based L4 mirroring in odd-level
//! runs. [`LineLayout`] is the one painted-geometry model shared by labels
//! and the Run/Rename editor: trailing (right) alignment of RTL paragraphs,
//! caret x from a logical index, visual hit-testing and selection
//! rectangles. Font-level mirroring when no alternate code point exists and
//! multi-line paragraph layout remain separate work; OpenType shaping lives
//! in `native_shaping`/`style_art`.
use std::borrow::Cow;
use unicode_bidi::{bidi_class, BidiClass, BidiInfo, Direction, Level};
use unicode_segmentation::UnicodeSegmentation;

/// Do not run a paragraph analysis for ordinary LTR system labels.
pub(crate) fn has_rtl(text: &str) -> bool {
    !text.is_ascii()
        && text.chars().any(|letter| {
            matches!(
                bidi_class(letter),
                BidiClass::R
                    | BidiClass::AL
                    | BidiClass::RLI
                    | BidiClass::RLE
                    | BidiClass::RLO
                    | BidiClass::FSI
            )
        })
}

/// Paragraph base direction of a single-line widget.
///
/// `Auto` is UAX #9 rules P2/P3: the first strong character (L, R or AL),
/// skipping isolate contents, decides; a paragraph without any strong
/// character is LTR. A widget may force `Ltr`/`Rtl` instead, e.g. to keep the
/// direction of a full label when only a truncated prefix is painted.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub(crate) enum BaseDirection {
    #[default]
    Auto,
    Ltr,
    Rtl,
}

impl BaseDirection {
    /// Resolve `Auto` for `text`; a forced direction is returned unchanged.
    pub(crate) fn resolve(self, text: &str) -> BaseDirection {
        match self {
            BaseDirection::Auto => {
                if paragraph_is_rtl(text) {
                    BaseDirection::Rtl
                } else {
                    BaseDirection::Ltr
                }
            }
            forced => forced,
        }
    }

    pub(crate) fn is_rtl_for(self, text: &str) -> bool {
        self.resolve(text) == BaseDirection::Rtl
    }

    fn level(self) -> Option<Level> {
        match self {
            BaseDirection::Auto => None,
            BaseDirection::Ltr => Some(Level::ltr()),
            BaseDirection::Rtl => Some(Level::rtl()),
        }
    }
}

/// UAX #9 P2/P3 for a single-line paragraph. ASCII never allocates.
pub(crate) fn paragraph_is_rtl(text: &str) -> bool {
    has_rtl(text) && unicode_bidi::get_base_direction(text) == Direction::Rtl
}

/// Visual cluster permutation and directional edges for a *single-line*
/// editor. Indices refer to UAX #29 graphemes in logical storage order.
/// Always derive a map from the exact visible substring: UAX #9 embedding
/// levels may change at a truncation or paragraph boundary.
pub(crate) struct VisualClusterMap {
    pub(crate) visual_to_logical: Vec<usize>,
    // Editors measure and visit every caret after one reorder. Store the
    // inverse once instead of scanning the visual permutation per caret.
    logical_to_visual: Vec<usize>,
    /// Resolved embedding level of each logical grapheme.
    levels: Vec<u8>,
    /// Paragraph embedding level (0 = LTR, 1 = RTL).
    base_level: u8,
}

impl VisualClusterMap {
    /// Identity order for a plain LTR line (no reordering required).
    fn identity(count: usize) -> Self {
        Self {
            visual_to_logical: (0..count).collect(),
            logical_to_visual: (0..count).collect(),
            levels: vec![0; count],
            base_level: 0,
        }
    }

    pub(crate) fn len(&self) -> usize {
        self.visual_to_logical.len()
    }

    pub(crate) fn base_is_rtl(&self) -> bool {
        self.base_level % 2 == 1
    }

    pub(crate) fn is_rtl(&self, logical: usize) -> bool {
        self.levels[logical] % 2 == 1
    }

    /// Visual edge index (0..=len) of the *leading* edge of a grapheme.
    fn leading_edge(&self, logical: usize) -> usize {
        self.logical_to_visual[logical] + usize::from(self.is_rtl(logical))
    }

    /// Visual edge index of the *trailing* edge of a grapheme.
    fn trailing_edge(&self, logical: usize) -> usize {
        self.logical_to_visual[logical] + usize::from(!self.is_rtl(logical))
    }

    /// Visual edge (0..=len, left to right) of logical caret `cursor`, i.e.
    /// the boundary *before* grapheme `cursor`.
    ///
    /// Inside a directional run both neighbours share one edge. At a level
    /// boundary the caret has the affinity of the *outer* run (the lower
    /// embedding level, ties to the preceding grapheme), with virtual
    /// start/end-of-paragraph neighbours at the base level. This is the
    /// "strong" caret: the place a character of the paragraph direction
    /// would be inserted. Consequently the logical start of an RTL
    /// paragraph is its right edge and the logical end its left edge.
    pub(crate) fn caret_edge(&self, cursor: usize) -> usize {
        let len = self.len();
        if len == 0 {
            return 0;
        }
        let rtl = self.base_is_rtl();
        let start_edge = if rtl { len } else { 0 };
        let end_edge = if rtl { 0 } else { len };
        if cursor == 0 {
            return start_edge;
        }
        let previous = cursor.min(len) - 1;
        let previous_level = self.levels[previous];
        let next_level = self.levels.get(cursor).copied().unwrap_or(self.base_level);
        if previous_level <= next_level {
            self.trailing_edge(previous)
        } else if cursor >= len {
            end_edge
        } else {
            self.leading_edge(cursor)
        }
    }
}

/// Cluster map for a single-line label or editor in the given direction.
/// `None` means the line is painted in logical order (LTR without any RTL
/// character): existing LTR labels keep their zero-allocation fast path.
pub(crate) fn visual_cluster_map_dir(text: &str, base: BaseDirection) -> Option<VisualClusterMap> {
    if (base != BaseDirection::Rtl && !has_rtl(text)) || text.contains('\r') || text.contains('\n')
    {
        return None;
    }
    if text.is_empty() {
        return None;
    }
    let info = BidiInfo::new(text, base.level());
    let para = (info.paragraphs.len() == 1).then(|| &info.paragraphs[0])?;
    if base != BaseDirection::Rtl && !info.has_rtl() {
        return None;
    }
    let per_char = info.reordered_levels_per_char(para, para.range.clone());
    let clusters: Vec<&str> = text.graphemes(true).collect();
    let mut levels = Vec::with_capacity(clusters.len());
    let mut offset = 0_usize;
    for cluster in &clusters {
        levels.push(*per_char.get(offset)?);
        offset += cluster.chars().count();
    }
    if offset != per_char.len() {
        return None;
    }
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
        levels: levels.iter().map(|level| level.number()).collect(),
        base_level: para.level.number(),
    })
}

/// [`visual_cluster_map_dir`] with the UAX #9 P2/P3 paragraph direction.
pub(crate) fn visual_cluster_map(text: &str) -> Option<VisualClusterMap> {
    visual_cluster_map_dir(text, BaseDirection::Auto)
}

/// Resolve an editor Left/Right key against *painted* bidi caret edges.
/// The selected text stays in logical order; only navigation order changes.
/// LTR text does not allocate or enter this path. At run boundaries with
/// multiple equivalent visual positions, prefer the nearest logical caret
/// deterministically instead of jumping unpredictably.
pub(crate) fn visual_arrow_target(text: &str, cursor: usize, toward_right: bool) -> Option<usize> {
    visual_arrow_target_dir(text, BaseDirection::Auto, cursor, toward_right)
}

pub(crate) fn visual_arrow_target_dir(
    text: &str,
    base: BaseDirection,
    cursor: usize,
    toward_right: bool,
) -> Option<usize> {
    let map = visual_cluster_map_dir(text, base)?;
    let count = map.len();
    let current = cursor.min(count);
    let current_edge = map.caret_edge(current);
    let mut best: Option<(usize, usize)> = None;
    for candidate in 0..=count {
        let edge = map.caret_edge(candidate);
        if (toward_right && edge <= current_edge) || (!toward_right && edge >= current_edge) {
            continue;
        }
        let better = match best {
            None => true,
            Some((other, other_edge)) => {
                let closer = if toward_right {
                    edge < other_edge
                } else {
                    edge > other_edge
                };
                closer
                    || (edge == other_edge && candidate.abs_diff(current) < other.abs_diff(current))
            }
        };
        if better {
            best = Some((candidate, edge));
        }
    }
    Some(best.map(|(candidate, _)| candidate).unwrap_or(current))
}

/// Painted geometry of one single-line paragraph: the bidi cluster order
/// plus the pixel x of every *visual* cluster edge, measured by the font
/// that paints it. All widgets derive alignment, carets, hit-testing and
/// selection rectangles from this one structure, so painting and
/// interaction cannot disagree. Positions are relative to the line origin;
/// [`LineLayout::align_offset`] places the line in its box.
pub(crate) struct LineLayout {
    map: VisualClusterMap,
    /// `len + 1` nondecreasing x positions of visual cluster edges.
    edges: Vec<u32>,
    rtl: bool,
}

impl LineLayout {
    /// Returns the cluster map and whether the paragraph is RTL. A line the
    /// painters keep in logical order (no RTL, or a multi-line string) gets
    /// the identity order, so layout and paint agree.
    fn map_for(text: &str, base: BaseDirection, count: usize) -> (VisualClusterMap, bool) {
        let rtl = base.is_rtl_for(text);
        let forced = if rtl {
            BaseDirection::Rtl
        } else {
            BaseDirection::Ltr
        };
        let map = visual_cluster_map_dir(text, forced)
            .filter(|map| map.len() == count)
            .unwrap_or_else(|| VisualClusterMap::identity(count));
        (map, rtl)
    }

    /// Measure the painted prefix of the *visual* cluster sequence. Exact for
    /// fonts whose visual-order advance equals the painted advance (bitmap
    /// cells, unshaped proportional text incl. kerning).
    pub(crate) fn from_visual_measure<G: Fn(&str) -> u32>(
        text: &str,
        base: BaseDirection,
        measure_visual: G,
    ) -> Self {
        let clusters: Vec<&str> = text.graphemes(true).collect();
        let (map, rtl) = Self::map_for(text, base, clusters.len());
        let mut visual = String::with_capacity(text.len());
        let mut edges = Vec::with_capacity(clusters.len() + 1);
        edges.push(0);
        let mut previous = 0;
        for &logical in &map.visual_to_logical {
            visual.push_str(clusters[logical]);
            previous = measure_visual(&visual).max(previous);
            edges.push(previous);
        }
        Self { map, edges, rtl }
    }

    /// Build from per-grapheme advances in *logical* order, e.g. the summed
    /// advances of the OpenType glyphs shaped for each cluster.
    pub(crate) fn from_advances(text: &str, base: BaseDirection, advances: &[f32]) -> Self {
        let count = text.graphemes(true).count();
        let (map, rtl) = Self::map_for(text, base, count);
        let mut edges = Vec::with_capacity(count + 1);
        edges.push(0);
        let mut pen = 0.0_f32;
        for &logical in &map.visual_to_logical {
            let advance = advances.get(logical).copied().unwrap_or(0.0);
            pen += if advance.is_finite() {
                advance.max(0.0)
            } else {
                0.0
            };
            edges.push(pen.round() as u32);
        }
        if let Some(last) = edges.last_mut() {
            *last = pen.ceil() as u32;
        }
        for index in 1..edges.len() {
            edges[index] = edges[index].max(edges[index - 1]);
        }
        Self { map, edges, rtl }
    }

    /// Painted width of the line.
    pub(crate) fn width(&self) -> u32 {
        self.edges.last().copied().unwrap_or(0)
    }

    pub(crate) fn len(&self) -> usize {
        self.map.len()
    }

    /// The paragraph is RTL: the line aligns to the box's right edge.
    #[cfg(test)]
    pub(crate) fn is_rtl(&self) -> bool {
        self.rtl
    }

    /// The resolved direction, for painting the same line with the same
    /// order the layout assumed.
    pub(crate) fn direction(&self) -> BaseDirection {
        if self.rtl {
            BaseDirection::Rtl
        } else {
            BaseDirection::Ltr
        }
    }

    /// Start-edge alignment inside `box_width`: 0 for LTR, the free space
    /// for RTL (trailing/right alignment). A line wider than its box is not
    /// shifted left of the box origin.
    pub(crate) fn align_offset(&self, box_width: u32) -> u32 {
        if self.rtl {
            box_width.saturating_sub(self.width())
        } else {
            0
        }
    }

    /// Pixel x of logical caret `cursor` (see [`VisualClusterMap::caret_edge`]).
    pub(crate) fn caret_x(&self, cursor: usize) -> u32 {
        self.edges[self.map.caret_edge(cursor.min(self.len()))]
    }

    /// Nearest logical caret to pixel `x`; equal distances keep `prefer`.
    pub(crate) fn hit(&self, x: f64, prefer: usize) -> usize {
        let mut selected = 0;
        let mut best = f64::INFINITY;
        for cursor in 0..=self.len() {
            let distance = (x - f64::from(self.caret_x(cursor))).abs();
            if distance < best || (distance == best && cursor == prefer) {
                best = distance;
                selected = cursor;
            }
        }
        selected
    }

    /// Painted spans `(left, right)` of the logical grapheme range
    /// `lower..upper`, left to right. A logical range crossing a level
    /// boundary becomes several disjoint rectangles; adjacent ones merge.
    pub(crate) fn spans(&self, lower: usize, upper: usize) -> Vec<(u32, u32)> {
        let mut spans: Vec<(u32, u32)> = Vec::new();
        for (visual, &logical) in self.map.visual_to_logical.iter().enumerate() {
            if logical < lower || logical >= upper {
                continue;
            }
            let (left, right) = (self.edges[visual], self.edges[visual + 1]);
            if right <= left {
                continue;
            }
            match spans.last_mut() {
                Some(last) if last.1 == left => last.1 = right,
                _ => spans.push((left, right)),
            }
        }
        spans
    }
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
#[cfg(test)]
pub(crate) fn visual_order(text: &str) -> Cow<'_, str> {
    visual_order_dir(text, BaseDirection::Auto)
}

/// [`visual_order`] with a widget-forced paragraph direction.
pub(crate) fn visual_order_dir(text: &str, base: BaseDirection) -> Cow<'_, str> {
    let Some(map) = visual_cluster_map_dir(text, base) else {
        return Cow::Borrowed(text);
    };
    let clusters: Vec<&str> = text.graphemes(true).collect();
    let mut reordered = String::with_capacity(text.len());
    for &index in &map.visual_to_logical {
        let cluster = clusters[index];
        if map.is_rtl(index) {
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
        for (a, b) in [
            ('(', ')'),
            ('[', ']'),
            ('{', '}'),
            ('<', '>'),
            ('«', '»'),
            ('‹', '›'),
            ('⟨', '⟩'),
            ('〈', '〉'),
            ('（', '）'),
        ] {
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
            ('⟦', '⟧'),
            ('⟪', '⟫'),
            ('\u{0F3A}', '\u{0F3B}'),
            ('\u{221D}', '\u{1DB10}'),
        ] {
            assert_eq!(mirrored_punctuation(left), right);
            assert_eq!(mirrored_punctuation(right), left);
        }
        let logical = "אבג⟦";
        assert_eq!(visual_order(logical), "⟧גבא");
        assert_eq!(
            visual_cluster_map(logical).unwrap().visual_to_logical,
            [3, 2, 1, 0]
        );
        assert_eq!(visual_order("plain ⟦LTR⟧"), "plain ⟦LTR⟧");
        assert_eq!(visual_order("שלום 👩‍💻"), "👩‍💻 םולש");
        // Ornate parentheses have Bidi_Mirrored=Yes but NO alternate
        // Unicode scalar mapping; do not invent one.
        assert_eq!(mirrored_punctuation('﴾'), '﴾');
        assert_eq!(mirrored_punctuation('﴿'), '﴿');
    }

    #[test]
    fn visual_map_preserves_grapheme_inventory_and_utf8() {
        for input in ["שלום 123 test", "A\u{301} שלום 👩‍💻 🇩🇪", "עברית ABC 42"]
        {
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

        // LTR paragraph, painted "abc גבא": the visual walk from the right
        // end crosses א first (logical 5), then ב (6), then reaches the
        // run boundary after the space (4).
        let mixed = "abc אבג";
        assert_eq!(visual_arrow_target(mixed, 7, false), Some(5));
        assert_eq!(visual_arrow_target(mixed, 5, false), Some(6));
        assert_eq!(visual_arrow_target(mixed, 6, false), Some(4));
        assert_eq!(visual_arrow_target(mixed, 4, false), Some(3));
        assert_eq!(visual_arrow_target(mixed, 3, true), Some(4));
        assert_eq!(visual_arrow_target(mixed, 4, true), Some(6));
        assert_eq!(visual_arrow_target(mixed, 7, true), Some(7));

        assert_eq!(visual_arrow_target("plain English", 2, true), None);
        assert_eq!(visual_arrow_target("אבג\nabc", 2, false), None);
    }

    #[test]
    fn rtl_paragraph_arrows_walk_every_painted_edge_once() {
        // RTL paragraph "אבג abc" paints "abc גבא" right-aligned.
        let text = "אבג abc";
        let mut cursor = 0; // Home: the right edge
        let mut seen = vec![visual_cluster_map(text).unwrap().caret_edge(cursor)];
        while let Some(next) = visual_arrow_target(text, cursor, false) {
            if next == cursor {
                break;
            }
            cursor = next;
            seen.push(visual_cluster_map(text).unwrap().caret_edge(cursor));
        }
        assert_eq!(seen, [7, 6, 5, 4, 3, 2, 1, 0], "one painted step per key");
        assert_eq!(cursor, 7, "the visual left end is the logical end");
        assert_eq!(visual_arrow_target(text, 7, true), Some(5));
    }

    #[test]
    fn pure_rtl_caret_edges_follow_painted_visual_clusters() {
        let map = visual_cluster_map("אבג").unwrap();
        assert_eq!(map.visual_to_logical, [2, 1, 0]);
        assert_eq!(
            (0..=3).map(|i| map.caret_edge(i)).collect::<Vec<_>>(),
            [3, 2, 1, 0]
        );
    }

    #[test]
    fn inverse_caret_map_matches_permutation_for_long_unicode_editor_lines() {
        let long = "abc אבג مرحبا 👩‍💻 🇩🇪 ".repeat(8);
        for text in ["אבג", "abc אבג", "مرحبا 👩‍💻 🇩🇪 A\u{301} עברית", &long]
        {
            let map = visual_cluster_map(text).expect("contains an RTL run");
            let len = map.len();
            assert_eq!(map.logical_to_visual.len(), len);
            for logical in 0..len {
                let reference = map
                    .visual_to_logical
                    .iter()
                    .position(|&value| value == logical)
                    .unwrap();
                assert_eq!(map.logical_to_visual[logical], reference);
            }
            // Every caret lands on a real painted edge.
            for cursor in 0..=len {
                assert!(
                    map.caret_edge(cursor) <= len,
                    "cursor={cursor} text={text:?}"
                );
            }
            assert_eq!(text.graphemes(true).count(), len);
        }
    }

    #[test]
    fn mixed_bidi_run_boundaries_preserve_logical_storage() {
        let map = visual_cluster_map("abc אבג").unwrap();
        assert_eq!(map.visual_to_logical, [0, 1, 2, 3, 6, 5, 4]);
        // Caret 4 keeps the LTR (outer) affinity after the space; the
        // logical end of an LTR paragraph is its right edge.
        assert_eq!(
            (0..=7).map(|i| map.caret_edge(i)).collect::<Vec<_>>(),
            [0, 1, 2, 3, 4, 6, 5, 7]
        );
        assert!(visual_cluster_map("regular ASCII").is_none());
        assert!(visual_cluster_map("אבג\nabc").is_none());
    }

    #[test]
    fn base_direction_follows_first_strong_character_p2_p3() {
        let rtl = |text: &str| BaseDirection::Auto.is_rtl_for(text);
        assert!(rtl("مرحبا"), "Arabic (AL)");
        assert!(rtl("שלום"), "Hebrew (R)");
        assert!(rtl("שלום abc"));
        assert!(!rtl("abc שלום 123"), "first strong is Latin");
        assert!(rtl("123 שלום abc"), "digits are weak, Hebrew decides");
        assert!(
            rtl("... (مرحبا) Abc"),
            "neutral-first: skip to the first strong"
        );
        assert!(!rtl("123 ..."), "no strong character: LTR default (P3)");
        assert!(!rtl(""));
        assert!(
            !rtl("\u{2067}שלום\u{2069} abc"),
            "isolate contents are skipped"
        );
        assert!(!rtl("Taskbar"));
        assert_eq!(BaseDirection::Rtl.resolve("abc"), BaseDirection::Rtl);
        assert_eq!(BaseDirection::Ltr.resolve("שלום"), BaseDirection::Ltr);
        assert_eq!(BaseDirection::Auto.resolve("שלום"), BaseDirection::Rtl);
    }

    #[test]
    fn display_order_uses_the_resolved_or_forced_base_level() {
        // Auto (P2/P3) RTL: the Latin run is painted at the visual left.
        assert_eq!(visual_order("אבג abc"), "abc גבא");
        // Forcing LTR on the same text keeps the Hebrew run first.
        assert_eq!(visual_order_dir("אבג abc", BaseDirection::Ltr), "גבא abc");
        // A truncated RTL label without strong characters keeps its
        // paragraph direction: the ellipsis stays at the visual left.
        assert_eq!(visual_order_dir("123 …", BaseDirection::Rtl), "… 123");
        assert_eq!(visual_order("123 …"), "123 …");
        assert!(matches!(
            visual_order_dir("Taskbar", BaseDirection::Ltr),
            Cow::Borrowed(_)
        ));
        // Logical-end ellipsis of a fitted RTL label paints at the left.
        assert!(visual_order("שלום עולם…").starts_with('…'));
        assert!(visual_order("שלום abc…").starts_with('…'));
        assert!(visual_order("abc שלום…").ends_with('…'));
    }

    fn cells(text: &str, base: BaseDirection) -> LineLayout {
        LineLayout::from_visual_measure(text, base, |visual| {
            visual.graphemes(true).count() as u32 * 8
        })
    }

    #[test]
    fn rtl_lines_align_to_the_trailing_edge_and_ltr_lines_do_not_move() {
        let hebrew = cells("שלום", BaseDirection::Auto);
        assert!(hebrew.is_rtl());
        assert_eq!(hebrew.width(), 32);
        assert_eq!(hebrew.align_offset(100), 68);
        assert_eq!(hebrew.align_offset(20), 0, "never left of the box");
        let arabic = cells("مرحبا Abc", BaseDirection::Auto);
        assert_eq!(arabic.align_offset(100), 100 - 72);
        let mixed = cells("abc שלום 123", BaseDirection::Auto);
        assert!(!mixed.is_rtl());
        assert_eq!(mixed.align_offset(100), 0);
        let forced = cells("abc", BaseDirection::Rtl);
        assert!(forced.is_rtl());
        assert_eq!(forced.align_offset(40), 16);
        assert_eq!(cells("", BaseDirection::Auto).align_offset(40), 0);
    }

    #[test]
    fn caret_x_across_ltr_rtl_boundaries_uses_outer_run_affinity() {
        // LTR "abc שלום 123" paints "abc 123 םולש".
        let mixed = cells("abc שלום 123", BaseDirection::Auto);
        let xs: Vec<u32> = (0..=12).map(|c| mixed.caret_x(c) / 8).collect();
        assert_eq!(xs, [0, 1, 2, 3, 4, 11, 10, 9, 8, 7, 5, 6, 12]);
        // RTL "אבג abc" paints "abc גבא": Home is the right edge, End the left.
        let rtl = cells("אבג abc", BaseDirection::Auto);
        let xs: Vec<u32> = (0..=7).map(|c| rtl.caret_x(c) / 8).collect();
        assert_eq!(xs, [7, 6, 5, 4, 3, 1, 2, 0]);
        let pure = cells("שלום", BaseDirection::Auto);
        assert_eq!(pure.caret_x(0), 32);
        assert_eq!(pure.caret_x(4), 0);
        // Hit-testing returns the logical caret painted nearest the pointer.
        assert_eq!(rtl.hit(57.0, 0), 0);
        assert_eq!(rtl.hit(1.0, 0), 7);
        assert_eq!(rtl.hit(17.0, 0), 6);
        assert_eq!(mixed.hit(90.0, 0), 5);
    }

    #[test]
    fn logical_selection_paints_as_disjoint_visual_rectangles() {
        let mixed = cells("abc שלום 123", BaseDirection::Auto);
        // "c ש": logical 2..5 = 'c', space, 'ש'; ש is painted at the far right.
        assert_eq!(mixed.spans(2, 5), vec![(16, 32), (88, 96)]);
        // The whole RTL run including the digits is one rectangle.
        assert_eq!(mixed.spans(4, 12), vec![(32, 96)]);
        assert_eq!(mixed.spans(0, 12), vec![(0, 96)]);
        assert!(mixed.spans(3, 3).is_empty());
        let rtl = cells("אבג abc", BaseDirection::Auto);
        // "ג a": the end of the Hebrew run and the start of the Latin run.
        assert_eq!(rtl.spans(2, 5), vec![(0, 8), (24, 40)]);
    }

    #[test]
    fn shaped_advances_place_edges_on_the_painted_glyph_boundaries() {
        // Logical advances of a three-cluster RTL word (e.g. contextual
        // Arabic forms of different widths) are laid out right to left.
        let layout = LineLayout::from_advances("ابت", BaseDirection::Auto, &[3.0, 5.5, 7.25]);
        assert!(layout.is_rtl());
        assert_eq!(layout.width(), 16);
        assert_eq!(layout.caret_x(0), 16);
        assert_eq!(layout.caret_x(1), 13, "right edge minus the first advance");
        assert_eq!(layout.caret_x(2), 7);
        assert_eq!(layout.caret_x(3), 0);
        let ltr = LineLayout::from_advances("ab", BaseDirection::Auto, &[4.0, f32::NAN]);
        assert_eq!((ltr.caret_x(1), ltr.caret_x(2)), (4, 4));
    }
}
