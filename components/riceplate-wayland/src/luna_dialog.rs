//! XP Luna's native Run and Help dialogs. Only explicit user input may
//! launch programs; never interpret recipe data or invoke a command shell.
use std::path::Path;

pub const WIDTH: u32 = 448;
pub const HEIGHT: u32 = 232;
pub const MAX_INPUT: usize = 192;
const MAX_ARGUMENTS: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind { Run, Help }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Hit { Input, Accept, Cancel }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CursorMove { Left, Right, Home, End }

#[derive(Debug)]
pub struct State {
    pub kind: Kind,
    pub input: String,
    /// Unicode scalar position, not a byte offset; never points into UTF-8.
    pub cursor: usize,
    pub notice: Option<&'static str>,
    pub hover: Option<Hit>,
    pub pressed: Option<Hit>,
}

impl State {
    pub fn new(kind: Kind) -> Self {
        Self { kind, input: String::new(), cursor: 0, notice: None, hover: None, pressed: None }
    }

    pub fn enter(&mut self, content: &str) -> bool {
        if self.kind != Kind::Run || content.chars().count() != 1
            || self.input.chars().count() >= MAX_INPUT
            || !content.chars().all(|c| !c.is_control()) {
            return false;
        }
        let offset = self.input.char_indices().nth(self.cursor)
            .map_or(self.input.len(), |(byte, _)| byte);
        self.input.insert_str(offset, content);
        self.cursor += 1;
        self.notice = None;
        true
    }

    /// Backspace removes the Unicode scalar immediately before the caret.
    pub fn erase(&mut self) -> bool {
        if self.kind != Kind::Run || self.cursor == 0 { return false; }
        let Some((offset, _)) = self.input.char_indices().nth(self.cursor - 1) else {
            return false;
        };
        self.input.remove(offset);
        self.cursor -= 1;
        self.notice = None;
        true
    }

    /// Delete removes the next scalar without changing caret position.
    pub fn delete(&mut self) -> bool {
        if self.kind != Kind::Run { return false; }
        let Some((offset, _)) = self.input.char_indices().nth(self.cursor) else {
            return false;
        };
        self.input.remove(offset);
        self.notice = None;
        true
    }

    pub fn move_cursor(&mut self, movement: CursorMove) -> bool {
        if self.kind != Kind::Run { return false; }
        let previous = self.cursor;
        let count = self.input.chars().count();
        self.cursor = match movement {
            CursorMove::Left => self.cursor.saturating_sub(1),
            CursorMove::Right => self.cursor.saturating_add(1).min(count),
            CursorMove::Home => 0,
            CursorMove::End => count,
        };
        self.cursor != previous
    }

    /// Use identical glyph advances for painting and mouse hit-testing.
    /// The caret is always within the visible Unicode scalar window.
    fn visible_range<F: Fn(&str) -> u32>(
        &self, max_width: u32, measure: &F,
    ) -> (usize, usize) {
        let chars: Vec<char> = self.input.chars().collect();
        let cursor = self.cursor.min(chars.len());
        let mut start = cursor;
        while start > 0 {
            let candidate: String = chars[start - 1..cursor].iter().collect();
            if measure(&candidate).saturating_add(2) > max_width { break; }
            start -= 1;
        }
        let mut end = cursor;
        while end < chars.len() {
            let candidate: String = chars[start..end + 1].iter().collect();
            if measure(&candidate).saturating_add(2) > max_width { break; }
            end += 1;
        }
        (start, end)
    }

    /// Calculate the visible input and caret from the exact active font
    /// metrics. Long input scrolls horizontally towards the caret instead
    /// of painting across the dialog or leaving the caret off-screen.
    pub fn input_view<F: Fn(&str) -> u32>(&self, max_width: u32, measure: F)
        -> (String, u32)
    {
        let chars: Vec<char> = self.input.chars().collect();
        let (start, end) = self.visible_range(max_width, &measure);
        let display: String = chars[start..end].iter().collect();
        let prefix: String = chars[start..self.cursor.min(chars.len())].iter().collect();
        (display, measure(&prefix).min(max_width.saturating_sub(1)))
    }

    /// Move the caret to the nearest glyph boundary in the *painted* input.
    /// A scrolled field must not place it on hidden characters. The caller
    /// supplies mouse X relative to the rendered text origin (128px).
    pub fn place_cursor_at<F: Fn(&str) -> u32>(
        &mut self, x: f64, max_width: u32, measure: F,
    ) -> bool {
        if self.kind != Kind::Run || !x.is_finite() || max_width == 0 {
            return false;
        }
        let chars: Vec<char> = self.input.chars().collect();
        let (start, end) = self.visible_range(max_width, &measure);
        let x = x.clamp(0.0, f64::from(max_width));
        let mut selected = start;
        let mut previous = 0_u32;
        for index in start..end {
            let segment: String = chars[start..index + 1].iter().collect();
            let next = measure(&segment);
            let midpoint = f64::from(previous) + f64::from(next.saturating_sub(previous)) / 2.0;
            if x < midpoint { break; }
            selected = index + 1;
            previous = next;
        }
        let changed = self.cursor != selected;
        self.cursor = selected;
        changed
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
    if kind == Kind::Run && (118.0..424.0).contains(&x) &&
        (111.0..143.0).contains(&y) { return Some(Hit::Input); }
    if (260.0..338.0).contains(&x) && (188.0..218.0).contains(&y) {
        return Some(Hit::Accept);
    }
    if kind == Kind::Run && (346.0..424.0).contains(&x) &&
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
        assert!(state.place_cursor_at(3.0, 80, width));
        assert_eq!(state.cursor, 0);
        assert!(!state.place_cursor_at(f64::NAN, 80, width));
        assert!(!state.place_cursor_at(f64::INFINITY, 80, width));
        assert_eq!(state.cursor, 0);
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
