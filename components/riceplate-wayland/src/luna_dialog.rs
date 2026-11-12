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

#[derive(Debug)]
pub struct State {
    pub kind: Kind,
    pub input: String,
    pub notice: Option<&'static str>,
    pub hover: Option<Hit>,
    pub pressed: Option<Hit>,
}

impl State {
    pub fn new(kind: Kind) -> Self {
        Self { kind, input: String::new(), notice: None, hover: None, pressed: None }
    }

    pub fn enter(&mut self, content: &str) -> bool {
        if self.kind != Kind::Run || content.chars().count() != 1
            || self.input.chars().count() >= MAX_INPUT
            || !content.chars().all(|c| !c.is_control()) {
            return false;
        }
        self.input.push_str(content);
        self.notice = None;
        true
    }

    pub fn erase(&mut self) -> bool {
        if self.kind != Kind::Run { return false; }
        let erased = self.input.pop().is_some();
        if erased { self.notice = None; }
        erased
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
    fn geometry_and_targets_follow_actual_dialog() {
        assert_eq!(position((1366, 768), 40, false), Some((459, 248)));
        assert_eq!(position((1366, 768), 40, true), Some((459, 288)));
        assert_eq!(position((440, 600), 40, false), None);
        assert_eq!(hit(280.0, 195.0, Kind::Run), Some(Hit::Accept));
        assert_eq!(hit(375.0, 195.0, Kind::Run), Some(Hit::Cancel));
        assert_eq!(hit(375.0, 195.0, Kind::Help), None);
        assert_eq!(hit(200.0, 120.0, Kind::Run), Some(Hit::Input));
        assert_eq!(hit(200.0, 120.0, Kind::Help), None);
        assert_eq!(hit(-1.0, 120.0, Kind::Run), None);
        assert_eq!(hit(f64::NAN, 120.0, Kind::Run), None);
    }
}
