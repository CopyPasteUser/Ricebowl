//! XP Luna's native Run/Help and confirmed Desktop file dialogs.
//! Only explicit user input may
//! launch programs; never interpret recipe data or invoke a command shell.
use std::path::Path;
use unicode_segmentation::UnicodeSegmentation;

pub const WIDTH: u32 = 448;
pub const HEIGHT: u32 = 232;
pub const MAX_INPUT: usize = 192;
const MAX_ARGUMENTS: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind { Run, Help, FileRename, FileTrash }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Hit { Input, Accept, Cancel }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CursorMove { Left, Right, Home, End }

#[derive(Debug)]
pub struct State {
    pub kind: Kind,
    pub input: String,
    /// Extended grapheme position, not a byte/scalar offset. Never splits
    /// combining sequences, flags or ZWJ emoji during a rename/Run edit.
    pub cursor: usize,
    pub notice: Option<&'static str>,
    pub hover: Option<Hit>,
    pub pressed: Option<Hit>,
}

/// Pixel position of each *logical* caret in the visible, painted run.
/// The visual measurement callback must not apply Unicode BiDi a second
/// time. Text and the permutation are bounded by MAX_INPUT scalars.
fn bidi_caret_pixels<F: Fn(&str) -> u32>(display: &str, measure_visual: &F)
    -> Option<Vec<u32>>
{
    let map = crate::bidi_layout::visual_cluster_map(display)?;
    let clusters: Vec<&str> = display.graphemes(true).collect();
    let mut visual_text = String::with_capacity(display.len());
    let mut visual_edges = Vec::with_capacity(clusters.len() + 1);
    visual_edges.push(0);
    for logical in &map.visual_to_logical {
        visual_text.push_str(clusters[*logical]);
        visual_edges.push(measure_visual(&visual_text));
    }
    Some((0..=clusters.len()).map(|caret| visual_edges[map.caret_edge(caret)]).collect())
}

impl State {
    fn editable(&self) -> bool { matches!(self.kind, Kind::Run | Kind::FileRename) }

    /// Byte boundaries of complete extended graphemes, including a final
    /// end-of-input sentinel. The 192-scalar input cap bounds this Vec.
    fn boundaries(&self) -> Vec<usize> {
        let mut points: Vec<usize> = self.input.grapheme_indices(true)
            .map(|(offset, _)| offset).collect();
        points.push(self.input.len());
        points
    }

    /// Prefill a name only for an owner-selected verified Desktop entry.
    /// Refuse names outside the editor's representable bounds; never truncate.
    pub fn prefill_name(&mut self, name: &str) -> bool {
        if self.kind != Kind::FileRename || name.is_empty()
            || name.chars().count() > MAX_INPUT
            || name.chars().any(char::is_control) { return false; }
        self.input = name.to_owned();
        self.cursor = self.input.graphemes(true).count();
        true
    }

    pub fn new(kind: Kind) -> Self {
        Self { kind, input: String::new(), cursor: 0, notice: None, hover: None, pressed: None }
    }

    /// Insert exactly one user-perceived character from a native key event.
    /// Retain this narrow API for callers that dispatch individual graphemes.
    pub fn enter(&mut self, content: &str) -> bool {
        if content.graphemes(true).count() != 1 { return false; }
        self.commit_text(content)
    }

    /// Commit a whole compositor-delivered text event atomically. Compose
    /// sequences can contain multiple graphemes; rejecting everything after
    /// the first would silently lose text. A rejected event must not insert a
    /// partial string, move the caret or clear an existing error notice.
    ///
    /// This is the native keyboard/compose path, not a text-input-v3 IME
    /// implementation. IME preedit, surrounding-text and protocol focus
    /// ownership still require their own Wayland integration.
    pub fn commit_text(&mut self, content: &str) -> bool {
        let incoming = content.chars().count();
        if !self.editable() || incoming == 0 || incoming > MAX_INPUT
            || self.input.chars().count() > MAX_INPUT - incoming
            || content.chars().any(char::is_control) {
            return false;
        }
        let points = self.boundaries();
        let offset = points[self.cursor.min(points.len() - 1)];
        self.input.insert_str(offset, content);
        // Both sides can join into a new grapheme. Recalculate from the
        // actual resulting text, never by adding UTF-8 bytes or scalars.
        self.cursor = self.input[..offset + content.len()].graphemes(true).count();
        self.notice = None;
        true
    }

    /// Backspace removes the COMPLETE grapheme immediately before the caret.
    pub fn erase(&mut self) -> bool {
        if !self.editable() || self.cursor == 0 { return false; }
        let points = self.boundaries();
        if self.cursor >= points.len() { return false; }
        self.input.replace_range(points[self.cursor - 1]..points[self.cursor], "");
        self.cursor -= 1;
        self.notice = None;
        true
    }

    /// Delete removes the next complete grapheme, keeping caret position.
    pub fn delete(&mut self) -> bool {
        if !self.editable() { return false; }
        let points = self.boundaries();
        if self.cursor + 1 >= points.len() { return false; }
        self.input.replace_range(points[self.cursor]..points[self.cursor + 1], "");
        self.notice = None;
        true
    }

    pub fn move_cursor(&mut self, movement: CursorMove) -> bool {
        if !self.editable() { return false; }
        let previous = self.cursor;
        let count = self.input.graphemes(true).count();
        self.cursor = match movement {
            CursorMove::Left => self.cursor.saturating_sub(1),
            CursorMove::Right => self.cursor.saturating_add(1).min(count),
            CursorMove::Home => 0,
            CursorMove::End => count,
        };
        self.cursor != previous
    }

    /// Use identical glyph advances for painting and mouse hit-testing.
    /// The caret stays on a visible complete grapheme boundary.
    fn visible_range<F: Fn(&str) -> u32>(
        &self, max_width: u32, measure: &F, points: &[usize],
    ) -> (usize, usize) {
        let count = points.len() - 1;
        let cursor = self.cursor.min(count);
        let mut start = cursor;
        while start > 0 {
            let candidate = &self.input[points[start - 1]..points[cursor]];
            if measure(candidate).saturating_add(2) > max_width { break; }
            start -= 1;
        }
        let mut end = cursor;
        while end < count {
            let candidate = &self.input[points[start]..points[end + 1]];
            if measure(candidate).saturating_add(2) > max_width { break; }
            end += 1;
        }
        (start, end)
    }

    /// Calculate the visible input and caret from the exact active font
    /// metrics. Never clip a combining cluster or position a caret inside
    /// the invisible half of an emoji during horizontal scrolling.
    pub fn input_view<F: Fn(&str) -> u32>(&self, max_width: u32, measure: F)
        -> (String, u32)
    {
        let points = self.boundaries();
        let (start, end) = self.visible_range(max_width, &measure, &points);
        let cursor = self.cursor.min(points.len() - 1);
        let display = self.input[points[start]..points[end]].to_owned();
        let prefix = &self.input[points[start]..points[cursor]];
        (display, measure(prefix).min(max_width.saturating_sub(1)))
    }

    /// Place the caret at the nearest *painted* complete glyph boundary.
    /// A scrolled field must not select hidden characters. x is relative to
    /// the rendered input text origin in the native dialog.
    pub fn place_cursor_at<F: Fn(&str) -> u32>(
        &mut self, x: f64, max_width: u32, measure: F,
    ) -> bool {
        if !self.editable() || !x.is_finite() || max_width == 0 {
            return false;
        }
        let points = self.boundaries();
        let (start, end) = self.visible_range(max_width, &measure, &points);
        let x = x.clamp(0.0, f64::from(max_width));
        let mut selected = start;
        let mut previous = 0_u32;
        for index in start..end {
            let next = measure(&self.input[points[start]..points[index + 1]]);
            let midpoint = f64::from(previous) +
                f64::from(next.saturating_sub(previous)) / 2.0;
            if x < midpoint { break; }
            selected = index + 1;
            previous = next;
        }
        let changed = self.cursor != selected;
        self.cursor = selected;
        changed
    }

    /// BiDi-aware painted caret position, using the same visible logical
    /// substring and glyph advances as the native renderer. Existing LTR
    /// input keeps the allocation-free, legacy hit-testing behavior.
    pub fn input_view_bidi<F: Fn(&str) -> u32, G: Fn(&str) -> u32>(
        &self, max_width: u32, measure: F, measure_visual: G,
    ) -> (String, u32) {
        let (display, legacy_x) = self.input_view(max_width, &measure);
        let points = self.boundaries();
        let (start, end) = self.visible_range(max_width, &measure, &points);
        let logical_caret = self.cursor.min(end).saturating_sub(start);
        let x = bidi_caret_pixels(&display, &measure_visual)
            .and_then(|edges| edges.get(logical_caret).copied())
            .unwrap_or(legacy_x);
        (display, x.min(max_width.saturating_sub(1)))
    }

    /// Map a pointer position back to a complete logical grapheme boundary,
    /// including reversed RTL runs. Ties prefer the existing caret where
    /// two logical positions share the same visual BiDi boundary.
    pub fn place_cursor_at_bidi<F: Fn(&str) -> u32, G: Fn(&str) -> u32>(
        &mut self, x: f64, max_width: u32, measure: F, measure_visual: G,
    ) -> bool {
        if !self.editable() || !x.is_finite() || max_width == 0 {
            return false;
        }
        let points = self.boundaries();
        let (start, end) = self.visible_range(max_width, &measure, &points);
        let display = &self.input[points[start]..points[end]];
        let Some(edges) = bidi_caret_pixels(display, &measure_visual) else {
            return self.place_cursor_at(x, max_width, measure);
        };
        let x = x.clamp(0.0, f64::from(max_width));
        let old = self.cursor;
        let mut selected = start;
        let mut best = f64::INFINITY;
        for (at, pixel) in edges.into_iter().enumerate() {
            let target = start + at;
            let distance = (x - f64::from(pixel)).abs();
            if distance < best || (distance == best && target == old) {
                best = distance;
                selected = target;
            }
        }
        self.cursor = selected;
        self.cursor != old
    }

    /// A tiny argv lexer, not a shell. Only explicit user keystrokes feed
    /// this buffer. Pipes, redirects, substitutions and globbing are never
    /// executed or interpreted; no expansion and no shell invocation.
    pub fn argv(&self) -> Result<Vec<String>, &'static str> {
        if self.kind != Kind::Run { return Err("Not a Run dialog"); }
        parse_argv(&self.input)
    }
}

pub fn hit(x: f64, y: f64, kind: Kind) -> Option<Hit> {
    if !x.is_finite() || !y.is_finite()
        || !(0.0..f64::from(WIDTH)).contains(&x)
        || !(0.0..f64::from(HEIGHT)).contains(&y) {
        return None;
    }
    if (414.0..438.0).contains(&x) && (9.0..32.0).contains(&y) {
        return Some(Hit::Cancel);
    }
    if matches!(kind, Kind::Run | Kind::FileRename) && (118.0..424.0).contains(&x) &&
        (111.0..143.0).contains(&y) { return Some(Hit::Input); }
    if (260.0..338.0).contains(&x) && (188.0..218.0).contains(&y) {
        return Some(Hit::Accept);
    }
    if kind != Kind::Help && (346.0..424.0).contains(&x) &&
        (188.0..218.0).contains(&y) { return Some(Hit::Cancel); }
    None
}

pub fn position(output: (u32, u32), panel: u32, top: bool) -> Option<(u32, u32)> {
    let available = output.1.checked_sub(panel)?;
    if output.0 < WIDTH || available < HEIGHT { return None; }
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
            if c == q { quoted = None; }
            else { word.push(c); }
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
        if result.len() >= MAX_ARGUMENTS { return Err("Too many arguments"); }
    }
    if escape || quoted.is_some() { return Err("Unclosed quote or escape"); }
    if active { result.push(word); }
    if result.is_empty() || result[0].is_empty() { return Err("Enter a program name"); }
    let program = &result[0];
    // No cwd-dependent './' binaries or implicit shell aliases. A normal
    // executable from PATH or an explicit absolute executable is accepted.
    let path = Path::new(program);
    if (program.contains('/') && !path.is_absolute())
        || program == "." || program == ".."
        || program.bytes().any(|b| b < 0x21 || b == 0x7f)
        || result.len() > MAX_ARGUMENTS {
        return Err("Use an executable name or absolute path");
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

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
        assert_eq!(parse_argv("foot -e 'echo hello'").unwrap(),
                   vec!["foot", "-e", "echo hello"]);
        assert_eq!(parse_argv("gio open \"file:///tmp/a b\"").unwrap(),
                   vec!["gio", "open", "file:///tmp/a b"]);
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
        for _ in 0..MAX_INPUT { assert!(state.enter("x")); }
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
        for letter in ["ä", "🧪", "b"] { assert!(state.enter(letter)); }
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
    fn rtl_caret_and_mouse_hits_follow_painted_order() {
        let measure = |s: &str| (s.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("אבג"));
        assert_eq!(state.input_view_bidi(80, measure, measure), ("אבג".into(), 0));
        assert!(state.move_cursor(CursorMove::Home));
        assert_eq!(state.input_view_bidi(80, measure, measure), ("אבג".into(), 24));
        assert!(state.place_cursor_at_bidi(9.0, 80, measure, measure));
        assert_eq!(state.cursor, 2);
        assert!(state.enter("Z"));
        assert_eq!(state.input, "אבZג");
        assert!(state.erase());
        assert_eq!(state.input, "אבג");

        let mut mixed = State::new(Kind::FileRename);
        assert!(mixed.commit_text("abc אבג"));
        assert!(mixed.move_cursor(CursorMove::Home));
        assert_eq!(mixed.input_view_bidi(80, measure, measure), ("abc אבג".into(), 0));
        assert!(mixed.place_cursor_at_bidi(55.0, 80, measure, measure));
        assert_eq!(mixed.cursor, 4, "the RTL run starts at its right edge");
        assert!(mixed.place_cursor_at_bidi(33.0, 80, measure, measure));
        assert_eq!(mixed.cursor, 7, "the RTL run ends at its left edge");
    }

    #[test]
    fn scrolled_rtl_editor_keeps_grapheme_and_click_boundaries() {
        let measure = |s: &str| (s.graphemes(true).count() * 8) as u32;
        let mut state = State::new(Kind::FileRename);
        assert!(state.commit_text("אבגדה"));
        assert_eq!(state.input_view_bidi(18, measure, measure), ("דה".into(), 0));
        assert!(state.place_cursor_at_bidi(15.0, 18, measure, measure));
        assert_eq!(state.cursor, 3);
        assert_eq!(state.input_view_bidi(18, measure, measure), ("בג".into(), 0));
        // A joined emoji is one grapheme/caret, even inside a BiDi run.
        let mut emoji = State::new(Kind::FileRename);
        assert!(emoji.commit_text("אב👩‍💻"));
        assert!(emoji.move_cursor(CursorMove::Home));
        assert_eq!(emoji.input_view_bidi(80, measure, measure).1, 24);
        assert!(emoji.place_cursor_at_bidi(1.0, 80, measure, measure));
        assert_eq!(emoji.cursor, 3);
    }

    #[test]
    fn horizontal_view_keeps_caret_visible_with_actual_font_metrics() {
        let mut state = State::new(Kind::Run);
        for c in "abcdef".chars() { assert!(state.enter(&c.to_string())); }
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
        assert_eq!(state.input_view(13, |text| text.chars().map(|c|
            if c == 'f' { 11 } else { 7 }).sum()), ("f".into(), 11));
    }

    #[test]
    fn clicking_run_input_moves_unicode_caret_using_actual_font_widths() {
        let mut state = State::new(Kind::Run);
        for ch in "a界bc".chars() { assert!(state.enter(&ch.to_string())); }
        let width = |text: &str| text.chars().map(|ch|
            if ch == '界' { 14_u32 } else { 8_u32 }).sum();
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
        for ch in "abcdef".chars() { assert!(state.enter(&ch.to_string())); }
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
