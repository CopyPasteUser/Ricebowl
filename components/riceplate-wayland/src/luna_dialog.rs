//! XP Luna's native Run/Help and confirmed Desktop file dialogs.
//! Only explicit user input may
//! launch programs; never interpret recipe data or invoke a command shell.
use crate::bidi_layout::{BaseDirection, LineLayout};
use std::path::Path;
use unicode_segmentation::UnicodeSegmentation;

pub const WIDTH: u32 = 448;
pub const HEIGHT: u32 = 232;
pub const MAX_INPUT: usize = 192;
const MAX_ARGUMENTS: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Run,
    Help,
    FileRename,
    FileTrash,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Hit {
    Input,
    Accept,
    Cancel,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CursorMove {
    Left,
    Right,
    Home,
    End,
}

#[derive(Debug, Clone)]
pub struct State {
    pub kind: Kind,
    pub input: String,
    /// Noncommitted IME preedit; never included in argv or filesystem actions.
    pub preedit: Option<crate::native_ime::Preedit>,
    /// Extended grapheme position, not a byte/scalar offset. Never splits
    /// combining sequences, flags or ZWJ emoji during a rename/Run edit.
    pub cursor: usize,
    /// Opposite logical grapheme edge for a live nonempty selection.
    pub selection_anchor: Option<usize>,
    pub notice: Option<&'static str>,
    pub hover: Option<Hit>,
    pub pressed: Option<Hit>,
}

/// One painted line of the Run/Rename editor. Every x is relative to the
/// field's text box origin.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EditorView {
    /// The visible logical substring (paint with `base`, at `text_x`).
    pub text: String,
    /// Resolved paragraph direction of the whole line.
    pub base: BaseDirection,
    /// Start of the painted line: 0 for LTR, right-aligned for RTL.
    pub text_x: u32,
    pub caret_x: u32,
    /// Live IME preedit underline rectangles (empty without preedit).
    pub underline: Vec<(u32, u32)>,
}

struct VisibleLine {
    start: usize,
    text: String,
    line: LineLayout,
    offset: u32,
}

impl State {
    fn editable(&self) -> bool {
        matches!(self.kind, Kind::Run | Kind::FileRename)
    }

    /// Byte boundaries of complete extended graphemes, including a final
    /// end-of-input sentinel. The 192-scalar input cap bounds this Vec.
    fn boundaries(&self) -> Vec<usize> {
        let mut points: Vec<usize> = self
            .input
            .grapheme_indices(true)
            .map(|(offset, _)| offset)
            .collect();
        points.push(self.input.len());
        points
    }

    /// Prefill a name only for an owner-selected verified Desktop entry.
    /// Refuse names outside the editor's representable bounds; never truncate.
    pub fn prefill_name(&mut self, name: &str) -> bool {
        if self.kind != Kind::FileRename
            || name.is_empty()
            || name.chars().count() > MAX_INPUT
            || name.chars().any(char::is_control)
        {
            return false;
        }
        self.input = name.to_owned();
        self.preedit = None;
        self.cursor = self.input.graphemes(true).count();
        self.selection_anchor = None;
        true
    }

    pub fn new(kind: Kind) -> Self {
        Self {
            kind,
            input: String::new(),
            preedit: None,
            cursor: 0,
            selection_anchor: None,
            notice: None,
            hover: None,
            pressed: None,
        }
    }

    /// Insert exactly one user-perceived character from a native key event.
    /// Retain this narrow API for callers that dispatch individual graphemes.
    pub fn enter(&mut self, content: &str) -> bool {
        if content.graphemes(true).count() != 1 {
            return false;
        }
        self.commit_text(content)
    }

    /// Nonempty logical selection, independent of the visual BiDi ordering.
    /// The end points are UAX #29 grapheme indices, never byte offsets.
    pub fn selected_graphemes(&self) -> Option<(usize, usize)> {
        let count = self.input.graphemes(true).count();
        let a = self.selection_anchor?.min(count);
        let b = self.cursor.min(count);
        (a != b).then_some((a.min(b), a.max(b)))
    }

    /// Selected text is a whole-grapheme UTF-8 slice. IME preedit is not
    /// committed editor data and must never become clipboard ownership.
    pub fn selected_text(&self) -> Option<&str> {
        if !self.editable() || self.preedit.is_some() {
            return None;
        }
        let (start, end) = self.selected_graphemes()?;
        let points = self.boundaries();
        Some(&self.input[points[start]..points[end]])
    }

    /// Call only after a real Wayland selection source was accepted for
    /// publishing. A failed/unavailable clipboard must not destroy the
    /// user's selected command or filename.
    pub fn cut_selected(&mut self) -> bool {
        if self.selected_text().is_none() {
            return false;
        }
        self.remove_selection()
    }

    /// Clipboard receivers validate an entire bounded transfer *before*
    /// calling this. The editor rechecks limits and printable scalar policy
    /// atomically, including when replacement frees capacity.
    pub fn paste_text(&mut self, text: &str) -> bool {
        text.len() <= MAX_INPUT * 4 && self.commit_text(text)
    }

    fn remove_selection(&mut self) -> bool {
        let Some((start, end)) = self.selected_graphemes() else {
            return false;
        };
        let points = self.boundaries();
        self.input.replace_range(points[start]..points[end], "");
        self.cursor = start;
        self.selection_anchor = None;
        self.preedit = None;
        self.notice = None;
        true
    }

    /// Ctrl+A selects only the real editable Run/Rename buffer. Neither
    /// recipe data nor background desktop shortcuts can invoke this path.
    pub fn select_all(&mut self) -> bool {
        if !self.editable() {
            return false;
        }
        let end = self.input.graphemes(true).count();
        if end == 0 {
            return false;
        }
        let previous = (self.cursor, self.selection_anchor);
        self.cursor = end;
        self.selection_anchor = Some(0);
        let changed = previous != (self.cursor, self.selection_anchor);
        if changed {
            self.preedit = None;
        }
        changed
    }

    /// Commit one compositor-delivered text event atomically, replacing a
    /// selected range if present. Validate against the post-replacement scalar
    /// count rather than rejecting valid replacement at MAX_INPUT.
    pub fn commit_text(&mut self, content: &str) -> bool {
        let incoming = content.chars().count();
        if !self.editable()
            || incoming == 0
            || incoming > MAX_INPUT
            || content.chars().any(char::is_control)
        {
            return false;
        }
        let points = self.boundaries();
        let caret = self.cursor.min(points.len() - 1);
        let (start, end) = self.selected_graphemes().unwrap_or((caret, caret));
        let existing = self.input.chars().count();
        let replaced = self.input[points[start]..points[end]].chars().count();
        if existing.saturating_sub(replaced) > MAX_INPUT - incoming {
            return false;
        }
        let byte_start = points[start];
        self.input
            .replace_range(points[start]..points[end], content);
        // Unicode joining across replacement boundaries changes grapheme
        // counts, so derive the new cursor from the final stored buffer.
        self.cursor = self.input[..byte_start + content.len()]
            .graphemes(true)
            .count();
        self.selection_anchor = None;
        self.preedit = None;
        self.notice = None;
        true
    }

    /// Backspace removes the selected graphemes, otherwise the preceding one.
    pub fn erase(&mut self) -> bool {
        if !self.editable() {
            return false;
        }
        if self.remove_selection() {
            return true;
        }
        if self.cursor == 0 {
            return false;
        }
        let points = self.boundaries();
        if self.cursor >= points.len() {
            return false;
        }
        self.input
            .replace_range(points[self.cursor - 1]..points[self.cursor], "");
        self.cursor -= 1;
        self.selection_anchor = None;
        self.preedit = None;
        self.notice = None;
        true
    }

    /// Delete removes the selection or the next complete grapheme.
    pub fn delete(&mut self) -> bool {
        if !self.editable() {
            return false;
        }
        if self.remove_selection() {
            return true;
        }
        let points = self.boundaries();
        if self.cursor + 1 >= points.len() {
            return false;
        }
        self.input
            .replace_range(points[self.cursor]..points[self.cursor + 1], "");
        self.selection_anchor = None;
        self.preedit = None;
        self.notice = None;
        true
    }

    pub fn move_cursor(&mut self, movement: CursorMove) -> bool {
        self.move_cursor_select(movement, false)
    }

    /// Shift extends selection from the first logical caret. A plain arrow
    /// collapses an existing selection before moving further; pure RTL
    /// movement still follows the previously validated visual caret map.
    pub fn move_cursor_select(&mut self, movement: CursorMove, extend: bool) -> bool {
        if !self.editable() {
            return false;
        }
        let previous = (self.cursor, self.selection_anchor);
        if !extend {
            if let Some((start, end)) = self.selected_graphemes() {
                if matches!(movement, CursorMove::Left | CursorMove::Right) {
                    // For a pure RTL run the visual left edge is the
                    // logical end. Collapse towards the painted side,
                    // not towards the smaller stored character index.
                    let (left, right) =
                        if let Some(map) = crate::bidi_layout::visual_cluster_map(&self.input) {
                            if map.caret_edge(start) <= map.caret_edge(end) {
                                (start, end)
                            } else {
                                (end, start)
                            }
                        } else {
                            (start, end)
                        };
                    self.cursor = if movement == CursorMove::Left {
                        left
                    } else {
                        right
                    };
                    self.selection_anchor = None;
                    self.preedit = None;
                    return true;
                }
            }
        }
        let count = self.input.graphemes(true).count();
        self.cursor = match movement {
            CursorMove::Left => {
                crate::bidi_layout::visual_arrow_target(&self.input, self.cursor, false)
                    .unwrap_or_else(|| self.cursor.saturating_sub(1))
            }
            CursorMove::Right => {
                crate::bidi_layout::visual_arrow_target(&self.input, self.cursor, true)
                    .unwrap_or_else(|| self.cursor.saturating_add(1).min(count))
            }
            CursorMove::Home => 0,
            CursorMove::End => count,
        };
        self.selection_anchor = if extend && self.cursor != previous.0 {
            Some(previous.1.unwrap_or(previous.0))
        } else if extend {
            previous.1
        } else {
            None
        };
        if self.selection_anchor == Some(self.cursor) {
            self.selection_anchor = None;
        }
        let changed = previous != (self.cursor, self.selection_anchor);
        if changed {
            self.preedit = None;
        }
        changed
    }

    /// Use identical glyph advances for painting and mouse hit-testing.
    /// The caret stays on a visible complete grapheme boundary.
    fn visible_range<F: Fn(&str) -> u32>(
        &self,
        max_width: u32,
        measure: &F,
        points: &[usize],
    ) -> (usize, usize) {
        let count = points.len() - 1;
        let cursor = self.cursor.min(count);
        let mut start = cursor;
        while start > 0 {
            let candidate = &self.input[points[start - 1]..points[cursor]];
            if measure(candidate).saturating_add(2) > max_width {
                break;
            }
            start -= 1;
        }
        let mut end = cursor;
        while end < count {
            let candidate = &self.input[points[start]..points[end + 1]];
            if measure(candidate).saturating_add(2) > max_width {
                break;
            }
            end += 1;
        }
        (start, end)
    }

    /// The editor paragraph's base direction: UAX #9 P2/P3 over the whole
    /// committed line (not only its scrolled, visible part). An RTL
    /// paragraph is painted right-aligned in the field.
    pub fn paragraph_direction(&self) -> BaseDirection {
        BaseDirection::Auto.resolve(&self.input)
    }

    /// Visible logical range and its painted layout in the field. All
    /// returned pixel positions are relative to the field's text box origin;
    /// `offset` is where the line starts (nonzero for RTL alignment).
    fn visible_layout<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &self,
        max_width: u32,
        measure: &F,
        layout: &L,
    ) -> VisibleLine {
        let points = self.boundaries();
        let (start, end) = self.visible_range(max_width, measure, &points);
        let text = self.input[points[start]..points[end]].to_owned();
        let line = layout(&text, self.paragraph_direction());
        // Mirror the LTR rule of `visible_range`: keep 2px for the caret
        // beyond the line's start edge, here the right edge of the box.
        let offset = line.align_offset(max_width.saturating_sub(2));
        VisibleLine {
            start,
            text,
            line,
            offset,
        }
    }

    /// Calculate the visible input and caret from the exact active font
    /// metrics (LTR measurement model). Never clip a combining cluster or
    /// position a caret inside the invisible half of an emoji.
    #[cfg(test)]
    pub fn input_view<F: Fn(&str) -> u32>(&self, max_width: u32, measure: F) -> (String, u32) {
        self.input_view_bidi(max_width, &measure, |text, base| {
            LineLayout::from_visual_measure(text, base, &measure)
        })
    }

    /// Place the caret at the nearest *painted* complete glyph boundary.
    /// A scrolled field must not select hidden characters.
    #[cfg(test)]
    pub fn place_cursor_at<F: Fn(&str) -> u32>(
        &mut self,
        x: f64,
        max_width: u32,
        measure: F,
    ) -> bool {
        self.place_cursor_at_bidi(x, max_width, &measure, |text, base| {
            LineLayout::from_visual_measure(text, base, &measure)
        })
    }

    /// Painted caret x relative to the text box, from the same visible
    /// logical substring, paragraph direction and glyph advances as the
    /// native renderer (`layout`). RTL paragraphs are right-aligned.
    #[cfg(test)]
    pub fn input_view_bidi<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &self,
        max_width: u32,
        measure: F,
        layout: L,
    ) -> (String, u32) {
        let visible = self.visible_layout(max_width, &measure, &layout);
        let local = self
            .cursor
            .saturating_sub(visible.start)
            .min(visible.line.len());
        let x = visible.offset + visible.line.caret_x(local);
        (visible.text, x.min(max_width.saturating_sub(1)))
    }

    /// Map a pointer position (relative to the text box) back to a complete
    /// logical grapheme boundary, including reversed RTL runs and the
    /// right-aligned RTL paragraph. Ties prefer the existing caret where two
    /// logical positions share the same visual BiDi boundary.
    pub fn place_cursor_at_bidi<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &mut self,
        x: f64,
        max_width: u32,
        measure: F,
        layout: L,
    ) -> bool {
        if !self.editable() || !x.is_finite() || max_width == 0 {
            return false;
        }
        let visible = self.visible_layout(max_width, &measure, &layout);
        let x = x.clamp(0.0, f64::from(max_width)) - f64::from(visible.offset);
        let old = self.cursor;
        let prefer = old.saturating_sub(visible.start);
        self.cursor = visible.start + visible.line.hit(x, prefer);
        let changed = self.cursor != old || self.selection_anchor.is_some();
        self.selection_anchor = None;
        if changed {
            self.preedit = None;
        }
        changed
    }

    /// Visible highlight rectangles in painted order, clipped to the same
    /// one-line viewport and measured with the same glyph advances as the
    /// caret. A logical selection crossing a BiDi level boundary is painted
    /// as several disjoint rectangles, never one false span.
    pub fn selection_pixels<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &self,
        max_width: u32,
        measure: F,
        layout: L,
    ) -> Vec<(u32, u32)> {
        let Some((lower, upper)) = self.selected_graphemes() else {
            return Vec::new();
        };
        if max_width == 0 {
            return Vec::new();
        }
        let visible = self.visible_layout(max_width, &measure, &layout);
        let end = visible.start + visible.line.len();
        if lower >= end || upper <= visible.start || visible.line.len() == 0 {
            return Vec::new();
        }
        let local = |index: usize| index.clamp(visible.start, end) - visible.start;
        visible
            .line
            .spans(local(lower), local(upper))
            .into_iter()
            .map(|(left, right)| {
                (
                    (visible.offset + left).min(max_width),
                    (visible.offset + right).min(max_width),
                )
            })
            .filter(|(left, right)| right > left)
            .collect()
    }

    /// The text-input-v3 protocol expresses all offsets in UTF-8 *bytes*.
    /// This editor stores a bounded line, so the full string is safe to send
    /// without shortening a grapheme or leaking it to disk.
    pub fn surrounding_selection(&self) -> (String, i32, i32) {
        let points = self.boundaries();
        let cursor = points[self.cursor.min(points.len() - 1)] as i32;
        let anchor = points[self
            .selection_anchor
            .unwrap_or(self.cursor)
            .min(points.len() - 1)] as i32;
        (self.input.clone(), cursor, anchor)
    }

    pub fn surrounding_text(&self) -> (String, i32) {
        let (text, cursor, _) = self.surrounding_selection();
        (text, cursor)
    }

    /// Apply one complete IME Done batch. Delete, commit and preedit are
    /// validated against a clone first; a malformed byte boundary cannot
    /// mutate the original filename, command or error state.
    pub fn apply_ime(&mut self, pending: &crate::native_ime::Pending) -> bool {
        // A rejected oversize/control-character commit invalidates the
        // complete text-input-v3 Done batch, including valid-looking deletes.
        // Do not treat a dropped commit as "no commit" and delete user text.
        if !self.editable() || pending.invalid_commit {
            return false;
        }
        let mut candidate = self.clone();
        candidate.preedit = None;
        if let Some((before, after)) = pending.delete {
            let (text, cursor) = candidate.surrounding_text();
            let cursor = cursor as usize;
            let Some(start) = cursor.checked_sub(before as usize) else {
                return false;
            };
            let Some(end) = cursor.checked_add(after as usize) else {
                return false;
            };
            let points = candidate.boundaries();
            if end > text.len() || !points.contains(&start) || !points.contains(&end) {
                return false;
            }
            candidate.input.replace_range(start..end, "");
            candidate.cursor = candidate.input[..start].graphemes(true).count();
            candidate.selection_anchor = None;
        }
        if let Some(content) = pending.commit.as_deref() {
            if !content.is_empty() && !candidate.commit_text(content) {
                return false;
            }
        }
        if let Some(ref result) = pending.preedit {
            let Ok(preedit) = result else {
                return false;
            };
            // Preedit is *displayed in place of* the current selection,
            // not appended after it. Counting selected characters twice
            // rejects valid IME replacements at the 192-scalar boundary.
            let points = candidate.boundaries();
            let caret = candidate.cursor.min(points.len() - 1);
            let (start, end) = candidate.selected_graphemes().unwrap_or((caret, caret));
            let replaced = candidate.input[points[start]..points[end]].chars().count();
            let base = candidate.input.chars().count().saturating_sub(replaced);
            if base > MAX_INPUT.saturating_sub(preedit.text.chars().count()) {
                return false;
            }
            candidate.preedit = (!preedit.text.is_empty()).then(|| preedit.clone());
        }
        *self = candidate;
        true
    }

    /// Paint preedit at its logical insertion point, with IME-specified
    /// caret and underline. This is a view only: the committed input remains
    /// unchanged until a valid Done commit transaction arrives. The paragraph
    /// direction includes the preedit, exactly as the line would commit.
    pub fn view<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &self,
        max_width: u32,
        measure: F,
        layout: L,
    ) -> EditorView {
        let plain = |state: &State| {
            let visible = state.visible_layout(max_width, &measure, &layout);
            let local = state
                .cursor
                .saturating_sub(visible.start)
                .min(visible.line.len());
            let caret = visible.offset + visible.line.caret_x(local);
            (visible, caret.min(max_width.saturating_sub(1)))
        };
        let finish =
            |(visible, caret_x): (VisibleLine, u32), underline: Vec<(u32, u32)>| EditorView {
                base: visible.line.direction(),
                text_x: visible.offset,
                text: visible.text,
                caret_x,
                underline,
            };
        let Some(preedit) = self.preedit.as_ref() else {
            return finish(plain(self), Vec::new());
        };
        let mut preview = self.clone();
        preview.preedit = None;
        let points = self.boundaries();
        let caret = self.cursor.min(points.len() - 1);
        // commit_text() replaces the selected range. The old cursor can be
        // *after* that range; using its former byte offset after replacement
        // panics when a shorter preedit replaces a longer selection.
        let (selection_start, _) = self.selected_graphemes().unwrap_or((caret, caret));
        let insertion = points[selection_start];
        if !preview.commit_text(&preedit.text) {
            return finish(plain(self), Vec::new());
        }
        let end = insertion + preedit.text.len();
        // The preedit may join existing graphemes on either side: adding
        // a combining mark to "e" or a ZWJ between emoji produces *one*
        // final grapheme spanning the insertion boundary. Underline every
        // complete final grapheme touched by the preedit; counting graphemes
        // in standalone UTF-8 prefixes can yield a zero-width underline.
        let composed_points = preview.boundaries();
        let begin_cursor = composed_points
            .partition_point(|&byte| byte <= insertion)
            .saturating_sub(1);
        let end_cursor = composed_points.partition_point(|&byte| byte < end);
        let caret_byte = insertion + preedit.cursor.unwrap_or(preedit.text.len());
        // IMEs use scalar-aligned UTF-8 offsets, not necessarily grapheme
        // boundaries. Never expose a caret inside a visual cluster.
        preview.cursor = composed_points.partition_point(|&byte| byte < caret_byte);
        let (visible, caret_x) = plain(&preview);
        let last = visible.start + visible.line.len();
        let local = |index: usize| index.clamp(visible.start, last) - visible.start;
        // A preedit crossing a BiDi level boundary is underlined as several
        // painted rectangles, like a selection.
        let underline = visible
            .line
            .spans(local(begin_cursor), local(end_cursor))
            .into_iter()
            .map(|(left, right)| {
                (
                    (visible.offset + left).min(max_width.saturating_sub(1)),
                    (visible.offset + right).min(max_width.saturating_sub(1)),
                )
            })
            .collect();
        finish((visible, caret_x), underline)
    }

    /// [`Self::view`] as `(visible text, caret x, preedit underline extent)`.
    pub fn input_view_composing<F: Fn(&str) -> u32, L: Fn(&str, BaseDirection) -> LineLayout>(
        &self,
        max_width: u32,
        measure: F,
        layout: L,
    ) -> (String, u32, Option<(u32, u32)>) {
        let view = self.view(max_width, measure, layout);
        let extent = view
            .underline
            .iter()
            .map(|&(left, _)| left)
            .min()
            .zip(view.underline.iter().map(|&(_, right)| right).max());
        (view.text, view.caret_x, extent)
    }

    /// A tiny argv lexer, not a shell. Only explicit user keystrokes feed
    /// this buffer. Pipes, redirects, substitutions and globbing are never
    /// executed or interpreted; no expansion and no shell invocation.
    pub fn argv(&self) -> Result<Vec<String>, &'static str> {
        if self.kind != Kind::Run {
            return Err("Not a Run dialog");
        }
        parse_argv(&self.input)
    }
}

pub fn hit(x: f64, y: f64, kind: Kind) -> Option<Hit> {
    if !x.is_finite()
        || !y.is_finite()
        || !(0.0..f64::from(WIDTH)).contains(&x)
        || !(0.0..f64::from(HEIGHT)).contains(&y)
    {
        return None;
    }
    if (414.0..438.0).contains(&x) && (9.0..32.0).contains(&y) {
        return Some(Hit::Cancel);
    }
    if matches!(kind, Kind::Run | Kind::FileRename)
        && (118.0..424.0).contains(&x)
        && (111.0..143.0).contains(&y)
    {
        return Some(Hit::Input);
    }
    if (260.0..338.0).contains(&x) && (188.0..218.0).contains(&y) {
        return Some(Hit::Accept);
    }
    if kind != Kind::Help && (346.0..424.0).contains(&x) && (188.0..218.0).contains(&y) {
        return Some(Hit::Cancel);
    }
    None
}

pub fn position(output: (u32, u32), panel: u32, top: bool) -> Option<(u32, u32)> {
    let available = output.1.checked_sub(panel)?;
    if output.0 < WIDTH || available < HEIGHT {
        return None;
    }
    let x = (output.0 - WIDTH) / 2;
    let y = (available - HEIGHT) / 2 + if top { panel } else { 0 };
    Some((x, y))
}

pub fn parse_argv(raw: &str) -> Result<Vec<String>, &'static str> {
    if raw.chars().count() > MAX_INPUT || raw.chars().any(char::is_control) {
        return Err("Command too long or contains control characters");
    }
    let mut result = Vec::new();
    let mut word = String::new();
    let mut quoted = None;
    let mut escape = false;
    let mut active = false;
    for c in raw.chars() {
        if escape {
            word.push(c);
            escape = false;
            active = true;
        } else if c == '\\' {
            escape = true;
            active = true;
        } else if let Some(q) = quoted {
            if c == q {
                quoted = None;
            } else {
                word.push(c);
            }
        } else if matches!(c, '\'' | '"') {
            quoted = Some(c);
            active = true;
        } else if c.is_whitespace() {
            if active {
                result.push(std::mem::take(&mut word));
                active = false;
            }
        } else if matches!(c, '|' | '&' | ';' | '<' | '>' | '`' | '$') {
            return Err("Shell operators are not supported");
        } else {
            word.push(c);
            active = true;
        }
        if result.len() >= MAX_ARGUMENTS {
            return Err("Too many arguments");
        }
    }
    if escape || quoted.is_some() {
        return Err("Unclosed quote or escape");
    }
    if active {
        result.push(word);
    }
    if result.is_empty() || result[0].is_empty() {
        return Err("Enter a program name");
    }
    let program = &result[0];
    // No cwd-dependent './' binaries or implicit shell aliases. A normal
    // executable from PATH or an explicit absolute executable is accepted.
    let path = Path::new(program);
    if (program.contains('/') && !path.is_absolute())
        || program == "."
        || program == ".."
        || program.bytes().any(|b| b < 0x21 || b == 0x7f)
        || result.len() > MAX_ARGUMENTS
    {
        return Err("Use an executable name or absolute path");
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 8px per grapheme, the same model as the `metric` closures.
    fn cells(text: &str, base: BaseDirection) -> LineLayout {
        LineLayout::from_visual_measure(text, base, |visual| {
            visual.graphemes(true).count() as u32 * 8
        })
    }

    #[test]
    fn clipboard_selection_is_grapheme_bounded_and_cut_replaces_atomically() {
        for kind in [Kind::Run, Kind::FileRename] {
            let mut editor = State::new(kind);
            assert!(editor.commit_text("A👩‍💻e\u{301}🇩🇪אב"));
            assert!(editor.select_all());
            let copied = editor.selected_text().unwrap().to_owned();
            assert_eq!(copied, "A👩‍💻e\u{301}🇩🇪אב");
            assert!(editor.cut_selected());
            assert_eq!(editor.input, "");
            assert!(editor.paste_text(&copied));
            assert_eq!(editor.input, copied);
            assert_eq!(editor.cursor, editor.input.graphemes(true).count());
            assert!(editor.selection_anchor.is_none());
        }
    }

    #[test]
    fn paste_rejects_invalid_or_oversize_transfers_without_changing_selection() {
        let mut editor = State::new(Kind::Run);
        assert!(editor.commit_text("safe"));
        assert!(editor.select_all());
        let original = (editor.input.clone(), editor.cursor, editor.selection_anchor);
        for rejected in [
            "",
            "bad\nname",
            "nul\0byte",
            "\u{202e}",
            &"🧪".repeat(MAX_INPUT + 1),
        ] {
            // Unicode BiDi formatting controls are handled by a separate
            // policy; only universal editor constraints are asserted here.
            if rejected == "\u{202e}" {
                continue;
            }
            assert!(!editor.paste_text(rejected));
            assert_eq!(
                (editor.input.clone(), editor.cursor, editor.selection_anchor),
                original
            );
        }
        assert!(editor.paste_text("🇯🇵"));
        assert_eq!(editor.input, "🇯🇵");
    }

    #[test]
    fn preedit_is_not_exported_to_clipboard_and_read_only_modals_cannot_copy() {
        let mut editor = State::new(Kind::Run);
        assert!(editor.commit_text("secret"));
        assert!(editor.select_all());
        editor.preedit = Some(crate::native_ime::Preedit::parse("候補", 6, 6).unwrap());
        assert!(editor.selected_text().is_none());
        assert!(!editor.cut_selected());
        assert_eq!(editor.input, "secret");
        let mut help = State::new(Kind::Help);
        help.input = "not an editable field".to_owned();
        help.cursor = help.input.graphemes(true).count();
        help.selection_anchor = Some(0);
        assert!(help.selected_text().is_none());
        assert!(!help.paste_text("X"));
    }

    #[test]
    fn compositor_compose_commit_is_atomic_and_grapheme_safe() {
        let mut dialog = State::new(Kind::FileRename);
        assert!(dialog.commit_text("Datei_日本語_"));
        assert_eq!(dialog.input, "Datei_日本語_");
        assert_eq!(dialog.cursor, "Datei_日本語_".graphemes(true).count());
        dialog.move_cursor(CursorMove::Home);
        assert!(dialog.commit_text("👩‍💻a\u{301}"));
        assert_eq!(dialog.cursor, 2);
        assert_eq!(dialog.input, "👩‍💻a\u{301}Datei_日本語_");
        assert!(dialog.erase());
        assert_eq!(dialog.input, "👩‍💻Datei_日本語_");
        assert_eq!(dialog.cursor, 1);

        dialog.notice = Some("Keep failure notice");
        let before = (dialog.input.clone(), dialog.cursor);
        for invalid in ["", "bad\ntext", "\u{0000}", "a\r\nb"] {
            assert!(!dialog.commit_text(invalid));
            assert_eq!((dialog.input.clone(), dialog.cursor), before);
            assert_eq!(dialog.notice, Some("Keep failure notice"));
        }
        assert!(!dialog.commit_text(&"🧪".repeat(MAX_INPUT + 1)));
        assert_eq!((dialog.input.clone(), dialog.cursor), before);
        assert_eq!(dialog.notice, Some("Keep failure notice"));
        let remaining = MAX_INPUT - dialog.input.chars().count();
        assert!(dialog.commit_text(&"x".repeat(remaining)));
        assert!(!dialog.commit_text("z"));
        assert_eq!(dialog.input.chars().count(), MAX_INPUT);
        assert!(dialog.enter("a") == false);
        let mut help = State::new(Kind::Help);
        assert!(!help.commit_text("Japanese 日本語"));
        assert!(help.input.is_empty());
    }

    #[test]
    fn quoted_args_are_passed_literally_without_shell() {
        assert_eq!(
            parse_argv("foot -e 'echo hello'").unwrap(),
            vec!["foot", "-e", "echo hello"]
        );
        assert_eq!(
            parse_argv("gio open \"file:///tmp/a b\"").unwrap(),
            vec!["gio", "open", "file:///tmp/a b"]
        );
        assert_eq!(parse_argv("/usr/bin/true").unwrap(), vec!["/usr/bin/true"]);
        assert!(parse_argv("foot; rm -rf /").is_err());
        assert!(parse_argv("echo $(touch /tmp/pwn)").is_err());
        assert!(parse_argv("../relative").is_err());
        assert!(parse_argv(" \\").is_err());
        assert!(parse_argv("  ").is_err());
        assert!(parse_argv("\"unfinished").is_err());
        assert!(parse_argv(&"a ".repeat(100)).is_err());
    }

    #[test]
    fn bounded_text_entry_and_unicode_erase() {
        let mut state = State::new(Kind::Run);
        assert!(state.enter("ä"));
        assert!(!state.enter("ab"));
        assert!(!state.enter("\n"));
        assert_eq!(state.input, "ä");
        assert!(state.erase());
        assert!(!state.erase());
        for _ in 0..MAX_INPUT {
            assert!(state.enter("x"));
        }
        assert!(!state.enter("x"));
        assert!(state.argv().is_ok());
        let mut help = State::new(Kind::Help);
        assert!(!help.enter("x"));
        assert!(!help.erase());
        assert!(help.argv().is_err());
    }

    #[test]
    fn unicode_cursor_navigation_and_midline_edits() {
        let mut state = State::new(Kind::Run);
        for letter in ["ä", "🧪", "b"] {
            assert!(state.enter(letter));
        }
        assert_eq!(state.cursor, 3);
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 2);
        assert!(state.enter("Z"));
        assert_eq!(state.input, "ä🧪Zb");
        assert_eq!(state.cursor, 3);
        assert!(state.erase());
        assert_eq!(state.input, "ä🧪b");
        assert!(state.delete());
        assert_eq!(state.input, "ä🧪");
        assert!(!state.delete());
        assert!(state.move_cursor(CursorMove::Home));
        assert!(!state.erase());
        assert!(state.delete());
        assert_eq!(state.input, "🧪");
        assert!(state.move_cursor(CursorMove::End));
        assert!(!state.move_cursor(CursorMove::Right));
        assert!(state.erase());
        assert!(state.input.is_empty());
        assert_eq!(state.cursor, 0);
        let mut help = State::new(Kind::Help);
        assert!(!help.move_cursor(CursorMove::Right));
        assert!(!help.delete());
        assert_eq!(help.cursor, 0);
    }

    #[test]
    fn grapheme_editor_never_splits_emoji_or_combining_sequences() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.enter("a"));
        assert!(state.enter("\u{301}")); // attaches to the existing 'a'
        assert_eq!(state.input, "a\u{301}");
        assert_eq!(state.cursor, 1);
        assert!(state.enter("👩‍💻")); // one grapheme, three Unicode scalars
        assert!(state.enter("🇩🇪"));
        assert_eq!(state.cursor, 3);
        assert_eq!(state.input.graphemes(true).count(), 3);
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 2);
        assert!(state.erase()); // must erase all of 👩‍💻
        assert_eq!(state.input, "a\u{301}🇩🇪");
        assert!(state.delete()); // must erase the whole flag
        assert_eq!(state.input, "a\u{301}");
        assert!(state.move_cursor(CursorMove::Home));
        assert!(!state.erase());
        assert!(state.delete()); // base+combining mark are inseparable
        assert_eq!(state.input, "");
        assert_eq!(state.cursor, 0);
        assert!(!state.enter("A\n"));
        assert!(!state.enter("ab"));
        assert!(!state.enter(&"x".repeat(MAX_INPUT + 1)));
    }

    #[test]
    fn mouse_caret_and_scrolling_use_visible_grapheme_boundaries() {
        let mut state = State::new(Kind::Run);
        for cluster in ["a\u{301}", "👩‍💻", "b"] {
            assert!(state.enter(cluster));
        }
        let measure = |text: &str| text.graphemes(true).count() as u32 * 8;
        assert_eq!(state.input_view(18, measure), ("👩‍💻b".into(), 16));
        assert!(state.place_cursor_at(0.0, 18, measure));
        assert_eq!(state.cursor, 1);
        assert_eq!(state.input_view(18, measure), ("a\u{301}👩‍💻".into(), 8));
        assert!(state.place_cursor_at(14.0, 18, measure));
        assert_eq!(state.cursor, 2);
        assert!(state.enter("Z"));
        assert_eq!(state.input, "a\u{301}👩‍💻Zb");
        assert!(state.erase());
        assert_eq!(state.input, "a\u{301}👩‍💻b");
    }

    #[test]
    fn wayland_preedit_is_visible_but_never_committed_before_done() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("foot"));
        let mut pending = crate::native_ime::Pending::default();
        pending.preedit(Some(" あ".to_string()), 4, 4);
        assert!(state.apply_ime(&pending));
        let metric = |text: &str| (text.graphemes(true).count() as u32) * 8;
        let (painted, caret, underline) = state.input_view_composing(200, metric, cells);
        assert_eq!(painted, "foot あ");
        assert_eq!(caret, 48);
        assert_eq!(underline, Some((32, 48)));
        assert_eq!(state.input, "foot");
        assert_eq!(state.argv().unwrap(), ["foot"]);
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.preedit.is_none());
        assert_eq!(
            state.input_view_composing(200, metric, cells),
            ("foot".into(), 0, None)
        );
    }

    #[test]
    fn intra_grapheme_ime_preedit_has_visible_underline_and_safe_caret() {
        let metric = |text: &str| (text.graphemes(true).count() as u32) * 8;
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("e"));
        let mut pending = crate::native_ime::Pending::default();
        // A combining mark becomes part of the *preceding* grapheme,
        // although it is the only pending IME text.
        pending.preedit(Some("\u{301}".into()), 0, 0);
        assert!(state.apply_ime(&pending));
        assert_eq!(
            state.input_view_composing(200, metric, cells),
            ("e\u{301}".into(), 8, Some((0, 8)))
        );
        assert_eq!(state.input, "e", "preedit must not mutate Run argv");
        assert_eq!(state.argv().unwrap(), ["e"]);

        pending.reset();
        pending.commit(Some("\u{301}".into()));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "e\u{301}");
        assert_eq!(state.cursor, 1);
        assert!(state.preedit.is_none());

        // A valid text-input-v3 caret between the base and mark gets
        // projected to the end of the painted grapheme, not rejected.
        pending.reset();
        pending.preedit(Some("a\u{301}".into()), 1, 1);
        assert!(state.apply_ime(&pending));
        assert_eq!(
            state.input_view_composing(200, metric, cells),
            ("e\u{301}a\u{301}".into(), 16, Some((8, 16)))
        );
        assert_eq!(state.input, "e\u{301}");
    }

    #[test]
    fn zwj_preedit_underlines_the_joined_emoji_not_an_empty_range() {
        let metric = |text: &str| (text.graphemes(true).count() as u32) * 8;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("👩💻"));
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.move_cursor(CursorMove::Right));
        let mut pending = crate::native_ime::Pending::default();
        pending.preedit(Some("\u{200d}".into()), 3, 3);
        assert!(state.apply_ime(&pending));
        assert_eq!(
            state.input_view_composing(200, metric, cells),
            ("👩‍💻".into(), 8, Some((0, 8)))
        );
        assert_eq!(state.input, "👩💻");
    }

    #[test]
    fn selected_preedit_renders_from_replacement_start_without_mutating_argv() {
        let metric = |text: &str| (text.graphemes(true).count() as u32) * 8;
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("original-command"));
        assert!(state.select_all()); // caret is at the old end, anchor at 0
        let mut pending = crate::native_ime::Pending::default();
        pending.preedit(Some("é".to_owned()), 2, 2);
        assert!(state.apply_ime(&pending));
        let (painted, caret, underline) = state.input_view_composing(200, metric, cells);
        assert_eq!(painted, "é");
        assert_eq!(caret, 8);
        assert_eq!(underline, Some((0, 8)));
        assert_eq!(state.input, "original-command");
        assert_eq!(state.selected_graphemes(), Some((0, 16)));
        assert_eq!(state.argv().unwrap(), ["original-command"]);

        // A composition edit replaces the selection only on a later Done.
        pending.reset();
        pending.commit(Some("foot".to_owned()));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "foot");
        assert!(state.preedit.is_none());
        assert_eq!(state.argv().unwrap(), ["foot"]);
    }

    #[test]
    fn ime_preview_accepts_bounded_full_selection_and_unicode_partial_selection() {
        let metric = |text: &str| (text.graphemes(true).count() as u32) * 8;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text(&"a".repeat(MAX_INPUT)));
        assert!(state.select_all());
        let mut pending = crate::native_ime::Pending::default();
        pending.preedit(Some("日本語".to_owned()), 9, 9);
        assert!(
            state.apply_ime(&pending),
            "selected characters must not count against the preview limit"
        );
        let (painted, caret, underline) = state.input_view_composing(200, metric, cells);
        assert_eq!(painted, "日本語");
        assert_eq!(caret, 24);
        assert_eq!(underline, Some((0, 24)));
        assert_eq!(state.input.chars().count(), MAX_INPUT);

        // Verify the symmetric case: a short selection plus too much preedit
        // still fails atomically, without clearing the selected text.
        let mut excess = State::new(Kind::FileRename);
        assert!(excess.commit_text(&"b".repeat(MAX_INPUT)));
        assert!(excess.move_cursor(CursorMove::Home));
        assert!(excess.move_cursor_select(CursorMove::Right, true));
        let prior = (excess.input.clone(), excess.cursor, excess.selection_anchor);
        pending.reset();
        pending.preedit(Some("XYZ".to_owned()), 3, 3);
        assert!(!excess.apply_ime(&pending));
        assert_eq!(
            (excess.input.clone(), excess.cursor, excess.selection_anchor),
            prior
        );

        let mut mixed = State::new(Kind::FileRename);
        assert!(mixed.commit_text("prefix-👩‍💻-suffix"));
        assert!(mixed.move_cursor(CursorMove::Home));
        for _ in 0..7 {
            assert!(mixed.move_cursor_select(CursorMove::Right, true));
        }
        pending.reset();
        pending.preedit(Some("漢".to_owned()), 3, 3);
        assert!(mixed.apply_ime(&pending));
        let (painted, _, underline) = mixed.input_view_composing(200, metric, cells);
        assert_eq!(painted, "漢👩‍💻-suffix");
        assert!(underline.is_some());
        assert_eq!(mixed.input, "prefix-👩‍💻-suffix");
    }

    #[test]
    fn invalid_ime_commit_is_atomic_even_with_valid_delete() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("notes"));
        let mut pending = crate::native_ime::Pending::default();
        pending.delete(2, 0);
        pending.commit(Some("bad\nname".into()));
        let initial = (state.input.clone(), state.cursor);
        assert!(!state.apply_ime(&pending));
        assert_eq!((state.input.clone(), state.cursor), initial);
        pending.commit(Some("新".into()));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "not新");
        assert_eq!(state.cursor, 4);
    }

    #[test]
    fn native_keyboard_arrows_follow_visual_rtl_carets() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("אבג"));
        assert_eq!(state.cursor, 3);
        assert!(
            !state.move_cursor(CursorMove::Left),
            "at the visually leftmost edge"
        );
        assert!(state.move_cursor(CursorMove::Right));
        assert_eq!(state.cursor, 2);
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 3);
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 1);
        assert_eq!(state.input, "אבג", "never reorder stored filename/argv");

        // LTR paragraph painted "abc גבא": End is the right edge; each Left
        // crosses exactly one painted cluster (א, ב, ג, then the space).
        let mut mixed = State::new(Kind::FileRename);
        assert!(mixed.commit_text("abc אבג"));
        assert_eq!(mixed.cursor, 7);
        let mut walk = Vec::new();
        while mixed.move_cursor(CursorMove::Left) {
            walk.push(mixed.cursor);
        }
        assert_eq!(walk, [5, 6, 4, 3, 2, 1, 0]);
        assert!(mixed.move_cursor(CursorMove::Right));
        assert_eq!(mixed.cursor, 1);
        assert!(mixed.move_cursor(CursorMove::End));
        assert!(mixed.move_cursor(CursorMove::Left));
        assert!(mixed.move_cursor(CursorMove::Right));
        assert_eq!(mixed.cursor, 7);
        assert_eq!(mixed.input, "abc אבג");

        // RTL paragraph painted "abc גבא": Home is the right edge, End the
        // left edge, and Left walks one painted cluster at a time.
        let mut rtl = State::new(Kind::Run);
        assert!(rtl.commit_text("אבג abc"));
        assert!(rtl.move_cursor(CursorMove::Home));
        let mut walk = Vec::new();
        while rtl.move_cursor(CursorMove::Left) {
            walk.push(rtl.cursor);
        }
        assert_eq!(walk, [1, 2, 3, 4, 6, 5, 7]);
        assert_eq!(rtl.input, "אבג abc", "AT-SPI offsets stay logical");

        let mut ltr = State::new(Kind::Run);
        assert!(ltr.commit_text("A👩‍💻B"));
        assert_eq!(ltr.cursor, 3);
        assert!(ltr.move_cursor(CursorMove::Left));
        assert_eq!(ltr.cursor, 2, "keep LTR grapheme movement unchanged");
    }

    #[test]
    fn rtl_caret_and_mouse_hits_follow_painted_order() {
        let measure = |s: &str| (s.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("אבג"));
        // Right-aligned in an 80px field (2px kept for the caret): the
        // 24px line spans 54..78. End = left edge, Home = right edge.
        assert_eq!(
            state.input_view_bidi(80, measure, cells),
            ("אבג".into(), 54)
        );
        assert!(state.move_cursor(CursorMove::Home));
        assert_eq!(
            state.input_view_bidi(80, measure, cells),
            ("אבג".into(), 78)
        );
        let view = state.view(80, measure, cells);
        assert_eq!((view.text_x, view.base), (54, BaseDirection::Rtl));
        assert!(state.place_cursor_at_bidi(63.0, 80, measure, cells));
        assert_eq!(state.cursor, 2);
        assert!(state.enter("Z"));
        assert_eq!(state.input, "אבZג");
        assert!(state.erase());
        assert_eq!(state.input, "אבג");
        // Clicking the empty left part of an RTL field selects the end.
        assert!(state.place_cursor_at_bidi(3.0, 80, measure, cells));
        assert_eq!(state.cursor, 3);

        let mut mixed = State::new(Kind::FileRename);
        assert!(mixed.commit_text("abc אבג"));
        assert!(mixed.move_cursor(CursorMove::Home));
        assert_eq!(
            mixed.input_view_bidi(80, measure, cells),
            ("abc אבג".into(), 0)
        );
        assert_eq!(mixed.view(80, measure, cells).text_x, 0, "LTR stays left");
        assert!(mixed.place_cursor_at_bidi(33.0, 80, measure, cells));
        assert_eq!(mixed.cursor, 4, "after the space, LTR affinity");
        assert!(mixed.place_cursor_at_bidi(49.0, 80, measure, cells));
        assert_eq!(mixed.cursor, 5, "between the painted ב and א");
        assert!(mixed.place_cursor_at_bidi(55.0, 80, measure, cells));
        assert_eq!(mixed.cursor, 7, "the right edge is the logical end");
    }

    #[test]
    fn scrolled_rtl_editor_keeps_grapheme_and_click_boundaries() {
        let measure = |s: &str| (s.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("אבגדה"));
        assert_eq!(state.input_view_bidi(18, measure, cells), ("דה".into(), 0));
        assert!(state.place_cursor_at_bidi(15.0, 18, measure, cells));
        assert_eq!(state.cursor, 3);
        assert_eq!(state.input_view_bidi(18, measure, cells), ("בג".into(), 0));
        // A joined emoji is one grapheme/caret, even inside a BiDi run.
        let mut emoji = State::new(Kind::FileRename);
        assert!(emoji.commit_text("אב👩‍💻"));
        assert!(emoji.move_cursor(CursorMove::Home));
        assert_eq!(emoji.input_view_bidi(80, measure, cells).1, 78);
        assert!(emoji.place_cursor_at_bidi(1.0, 80, measure, cells));
        assert_eq!(emoji.cursor, 3);
    }

    #[test]
    fn horizontal_view_keeps_caret_visible_with_actual_font_metrics() {
        let mut state = State::new(Kind::Run);
        for c in "abcdef".chars() {
            assert!(state.enter(&c.to_string()));
        }
        let measure = |text: &str| text.chars().count() as u32 * 8;
        assert_eq!(state.input_view(26, measure), ("def".into(), 24));
        assert!(state.move_cursor(CursorMove::Home));
        assert_eq!(state.input_view(26, measure), ("abc".into(), 0));
        assert!(state.move_cursor(CursorMove::Right));
        assert_eq!(state.input_view(26, measure), ("abc".into(), 8));
        assert!(state.move_cursor(CursorMove::End));
        assert_eq!(state.input_view(10, measure), ("f".into(), 8));
        assert_eq!(state.input_view(1, measure), ("".into(), 0));
        // Variable-width fonts use their real measured advances instead of
        // assuming eight fixed pixels per glyph.
        assert_eq!(
            state.input_view(13, |text| text
                .chars()
                .map(|c| if c == 'f' { 11 } else { 7 })
                .sum()),
            ("f".into(), 11)
        );
    }

    #[test]
    fn clicking_run_input_moves_unicode_caret_using_actual_font_widths() {
        let mut state = State::new(Kind::Run);
        for ch in "a界bc".chars() {
            assert!(state.enter(&ch.to_string()));
        }
        let width = |text: &str| {
            text.chars()
                .map(|ch| if ch == '界' { 14_u32 } else { 8_u32 })
                .sum()
        };
        assert_eq!(state.input_view(80, width), ("a界bc".into(), 38));
        assert!(state.place_cursor_at(16.0, 80, width));
        assert_eq!(state.cursor, 2, "click past wide glyph midpoint");
        assert!(state.enter("Z"));
        assert_eq!(state.input, "a界Zbc");
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.place_cursor_at(5.0, 80, width));
        assert_eq!(state.cursor, 1);
        assert!(!state.place_cursor_at(f64::NAN, 80, width));
        assert!(!state.place_cursor_at(f64::INFINITY, 80, width));
        assert_eq!(state.cursor, 1);
        assert!(!state.place_cursor_at(8.0, 0, width));
        let mut help = State::new(Kind::Help);
        assert!(!help.place_cursor_at(12.0, 80, width));
    }

    #[test]
    fn clicking_scrolled_run_input_never_selects_invisible_prefix() {
        let mut state = State::new(Kind::Run);
        for ch in "abcdef".chars() {
            assert!(state.enter(&ch.to_string()));
        }
        let width = |text: &str| text.chars().count() as u32 * 8;
        assert_eq!(state.input_view(26, width), ("def".into(), 24));
        assert!(state.place_cursor_at(-50.0, 26, width));
        assert_eq!(state.cursor, 3, "left click selects first visible scalar");
        assert_eq!(state.input_view(26, width), ("abc".into(), 24));
        assert_eq!(state.input, "abcdef", "click never changes text");
        assert!(state.place_cursor_at(1.0, 26, width));
        assert_eq!(state.cursor, 0);
        assert!(state.place_cursor_at(999.0, 26, width));
        assert_eq!(state.cursor, 3, "right click selects last visible boundary");
    }

    #[test]
    fn shift_selection_replace_and_delete_preserve_unicode_clusters() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("a\u{301}👩‍💻🇩🇪.txt"));
        assert_eq!(state.cursor, 7);
        assert!(state.move_cursor_select(CursorMove::Left, true));
        assert_eq!(state.selected_graphemes(), Some((6, 7)));
        assert!(state.move_cursor_select(CursorMove::Home, true));
        assert_eq!(state.selected_graphemes(), Some((0, 7)));
        assert!(state.commit_text("新.txt"));
        assert_eq!(state.input, "新.txt");
        assert!(state.selection_anchor.is_none());
        assert_eq!(state.cursor, 5);
        assert!(state.select_all());
        assert_eq!(state.selected_graphemes(), Some((0, 5)));
        assert!(state.erase());
        assert_eq!(state.input, "");
        assert_eq!(state.cursor, 0);
        assert!(!state.select_all());
        assert!(!state.erase());
    }

    #[test]
    fn keyboard_selection_collapses_on_unshifted_arrows_and_click() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("abcdef"));
        assert!(state.move_cursor_select(CursorMove::Left, true));
        assert!(state.move_cursor_select(CursorMove::Left, true));
        assert_eq!(state.selected_graphemes(), Some((4, 6)));
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 4);
        assert!(state.selected_graphemes().is_none());
        assert!(state.move_cursor_select(CursorMove::Home, true));
        assert_eq!(state.selected_graphemes(), Some((0, 4)));
        let measure = |t: &str| (t.graphemes(true).count() * 8) as u32;
        assert!(state.place_cursor_at_bidi(8.0, 80, measure, cells));
        assert!(state.selected_graphemes().is_none());
        assert_eq!(state.input, "abcdef");
    }

    #[test]
    fn unshifted_rtl_arrows_collapse_selection_to_painted_edges() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("אבג"));
        assert!(state.select_all());
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 3, "painted left is logical end");
        assert!(state.select_all());
        assert!(state.move_cursor(CursorMove::Right));
        assert_eq!(state.cursor, 0, "painted right is logical start");
        assert!(state.selection_anchor.is_none());
    }

    #[test]
    fn selected_bidi_visual_clusters_are_not_painted_as_one_false_span() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("abc אבג"));
        state.selection_anchor = Some(2);
        state.cursor = 5;
        let measure = |t: &str| (t.graphemes(true).count() * 8) as u32;
        // Two separate painted ranges across the LTR/RTL run boundary.
        assert_eq!(
            state.selection_pixels(80, measure, cells),
            vec![(16, 32), (48, 56)]
        );
        assert_eq!(state.surrounding_selection(), ("abc אבג".into(), 6, 2));
        assert!(state.delete());
        assert_eq!(state.input, "abבג");
        assert_eq!(state.cursor, 2);
    }

    #[test]
    fn rtl_paragraph_selection_is_right_aligned_disjoint_rectangles() {
        let measure = |t: &str| (t.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::Run);
        // Painted "abc גבא" right-aligned at 22..78 in an 80px field.
        assert!(state.commit_text("אבג abc"));
        assert_eq!(state.view(80, measure, cells).text_x, 22);
        // Logical 2..5 = "ג", space, "a": the Latin "a" is painted at the
        // far left of the line, "ג " in the middle: two rectangles.
        state.selection_anchor = Some(2);
        state.cursor = 5;
        assert_eq!(
            state.selection_pixels(80, measure, cells),
            vec![(22, 30), (46, 62)]
        );
        // Shift+Left in the RTL run extends the logical selection while the
        // painted caret moves left; offsets stay logical for AT-SPI.
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.move_cursor_select(CursorMove::Left, true));
        assert!(state.move_cursor_select(CursorMove::Left, true));
        assert_eq!(state.selected_graphemes(), Some((0, 2)));
        assert_eq!(state.selection_pixels(80, measure, cells), vec![(62, 78)]);
        assert_eq!(state.surrounding_selection(), ("אבג abc".into(), 4, 0));
    }

    #[test]
    fn rtl_ime_preedit_is_inserted_at_the_logical_caret() {
        let measure = |t: &str| (t.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text("שלום"));
        assert!(state.move_cursor(CursorMove::Home));
        assert!(state.move_cursor(CursorMove::Left));
        assert!(state.move_cursor(CursorMove::Left));
        assert_eq!(state.cursor, 2, "two painted steps left of the right edge");
        let mut pending = crate::native_ime::Pending::default();
        pending.preedit(Some("ab".into()), 2, 2);
        assert!(state.apply_ime(&pending));
        // Preview "שלabום" (logical): painted "םוabלש", right-aligned at
        // 30..78. The preedit sits between the logical neighbours ל and ו.
        let view = state.view(80, measure, cells);
        assert_eq!(view.text, "שלabום");
        assert_eq!((view.text_x, view.base), (30, BaseDirection::Rtl));
        assert_eq!(view.underline, vec![(46, 62)]);
        // Logical caret after "b" at the boundary to the RTL run: the outer
        // (paragraph-level) run's affinity puts it at the leading edge of ו.
        assert_eq!(view.caret_x, 46);
        assert_eq!(state.input, "שלום", "preedit is never committed early");
        assert_eq!(state.surrounding_text(), ("שלום".into(), 4));
        pending.reset();
        pending.commit(Some("ab".into()));
        assert!(state.apply_ime(&pending));
        assert_eq!(state.input, "שלabום");
        assert_eq!(state.cursor, 4);
    }

    #[test]
    fn replacing_full_capacity_selection_is_permitted_but_overflow_is_atomic() {
        let mut state = State::new(Kind::Run);
        assert!(state.commit_text(&"x".repeat(MAX_INPUT)));
        assert!(state.select_all());
        assert!(state.commit_text("🦀"));
        assert_eq!(state.input, "🦀");
        assert!(state.select_all());
        let snapshot = (state.input.clone(), state.cursor, state.selection_anchor);
        assert!(!state.commit_text(&"x".repeat(MAX_INPUT + 1)));
        assert_eq!(
            (state.input.clone(), state.cursor, state.selection_anchor),
            snapshot
        );
        assert!(state.commit_text("foot"));
        assert_eq!(state.argv().unwrap(), ["foot"]);
    }

    #[test]
    fn geometry_and_targets_follow_actual_dialog() {
        assert_eq!(position((1366, 768), 40, false), Some((459, 248)));
        assert_eq!(position((1366, 768), 40, true), Some((459, 288)));
        assert_eq!(position((440, 600), 40, false), None);
        assert_eq!(hit(280.0, 195.0, Kind::Run), Some(Hit::Accept));
        assert_eq!(hit(375.0, 195.0, Kind::Run), Some(Hit::Cancel));
        assert_eq!(hit(375.0, 195.0, Kind::Help), None);
        assert_eq!(hit(420.0, 18.0, Kind::Help), Some(Hit::Cancel));
        assert_eq!(hit(200.0, 120.0, Kind::Run), Some(Hit::Input));
        assert_eq!(hit(200.0, 120.0, Kind::Help), None);
        assert_eq!(hit(-1.0, 120.0, Kind::Run), None);
        assert_eq!(hit(f64::NAN, 120.0, Kind::Run), None);
    }
}

#[cfg(test)]
mod file_dialog_tests {
    use super::*;

    #[test]
    fn rename_edit_is_unicode_safe_and_never_executes_argv() {
        let mut state = State::new(Kind::FileRename);
        assert!(state.prefill_name("notes 🍚.txt"));
        assert_eq!(state.cursor, 11);
        assert!(state.erase());
        assert!(state.enter("x"));
        assert!(state.argv().is_err());
        assert!(!state.prefill_name(&"x".repeat(MAX_INPUT + 1)));
        assert_eq!(state.input, "notes 🍚.txx");
        assert!(!state.enter("/\n"));
        assert_eq!(hit(130.0, 125.0, Kind::FileRename), Some(Hit::Input));
        assert_eq!(hit(370.0, 200.0, Kind::FileTrash), Some(Hit::Cancel));
    }

    #[test]
    fn trash_dialog_has_no_mutable_text_input() {
        let mut state = State::new(Kind::FileTrash);
        assert!(!state.enter("x"));
        assert!(!state.erase());
        assert!(!state.delete());
        assert_eq!(hit(130.0, 125.0, Kind::FileTrash), None);
    }
}
