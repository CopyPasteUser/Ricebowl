//! Native desktop shortcut context state, shared by pointer and keyboard input.
//! Actions are strictly allowlisted; recipes never inject commands into menus.
pub const WIDTH: u32 = 224;
pub const HEIGHT: u32 = 190;
const FIRST_ROW: u32 = 36;
const ROW_HEIGHT: u32 = 28;
pub const BACK_ROW: u32 = 150;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Open,
    NextDisplay,
    AllDisplays,
    ResetPosition,
    Properties,
}

impl Action {
    pub const ALL: [Self; 5] = [
        Self::Open, Self::NextDisplay, Self::AllDisplays,
        Self::ResetPosition, Self::Properties,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Self::Open => "Open",
            Self::NextDisplay => "Next display",
            Self::AllDisplays => "All displays",
            Self::ResetPosition => "Reset position",
            Self::Properties => "Properties",
        }
    }
    pub fn label_for_file(self) -> &'static str {
        match self {
            Self::NextDisplay => "Rename...",
            Self::AllDisplays => "Move to Trash",
            Self::ResetPosition => "Open in Explorer",
            _ => self.label(),
        }
    }
    pub fn enabled(self, multi_output: bool, can_reset: bool) -> bool {
        match self {
            Self::NextDisplay => multi_output,
            Self::ResetPosition => can_reset,
            _ => true,
        }
    }
    pub fn index(self) -> usize {
        match self {
            Self::Open => 0,
            Self::NextDisplay => 1,
            Self::AllDisplays => 2,
            Self::ResetPosition => 3,
            Self::Properties => 4,
        }
    }
}

/// Keyboard and pointer share the same bounded edit policy.
#[derive(Debug, Clone)]
pub struct RenameInput {
    value: String,
    pub error: Option<&'static str>,
}
impl RenameInput {
    pub fn new(current: &str) -> Option<Self> {
        let mut next = Self { value: current.to_owned(), error: None };
        if !next.valid() { return None; }
        next.error = None;
        Some(next)
    }
    pub fn value(&self) -> &str { &self.value }
    pub fn insert(&mut self, typed: &str) -> bool {
        if typed.chars().count() != 1 || typed.chars().any(|c|
            c.is_control() || matches!(c, '/' | '\0')) { return false; }
        if self.value.chars().count() >= 64 || self.value.len() + typed.len() > 255 {
            self.error = Some("Name too long");
            return false;
        }
        self.value.push_str(typed);
        self.error = None;
        true
    }
    pub fn erase(&mut self) -> bool {
        let changed = self.value.pop().is_some();
        if changed { self.error = None; }
        changed
    }
    pub fn valid(&self) -> bool {
        let b = self.value.as_bytes();
        !b.is_empty() && b.len() <= 255 && b[0] != b'.'
            && self.value != "." && self.value != ".."
            && !self.value.chars().any(|c| c.is_control() || c == '/')
    }
    pub fn set_error(&mut self, message: &'static str) { self.error = Some(message); }
}

#[derive(Debug, Clone)]
pub enum FileOperation {
    Rename(RenameInput),
    ConfirmTrash,
}

pub fn row(action: Action) -> u32 { FIRST_ROW + action.index() as u32 * ROW_HEIGHT }

pub fn hit(x: f64, y: f64) -> Option<Action> {
    if !x.is_finite() || !y.is_finite()
        || x < 5.0 || x >= f64::from(WIDTH - 5)
        || y < f64::from(FIRST_ROW)
        || y >= f64::from(FIRST_ROW + Action::ALL.len() as u32 * ROW_HEIGHT)
    {
        return None;
    }
    Action::ALL.get(((y as u32 - FIRST_ROW) / ROW_HEIGHT) as usize).copied()
}

/// The read-only properties page only accepts a fixed, clearly visible Back
/// affordance; there is no hidden file operation or arbitrary action dispatch.
pub fn back_hit(x: f64, y: f64) -> bool {
    x.is_finite() && y.is_finite() && (5.0..f64::from(WIDTH - 5)).contains(&x)
        && (f64::from(BACK_ROW)..f64::from(BACK_ROW + ROW_HEIGHT)).contains(&y)
}

pub fn navigate(current: Action, delta: i32, multi_output: bool,
                can_reset: bool) -> Action {
    let mut index = current.index() as i32;
    for _ in 0..Action::ALL.len() {
        index = (index + delta).rem_euclid(Action::ALL.len() as i32);
        let action = Action::ALL[index as usize];
        if action.enabled(multi_output, can_reset) { return action; }
    }
    current
}

/// Show only static metadata for an already validated desktop action. This is
/// NOT a filesystem stat and must not imply the target exists or is mounted.
pub fn details(action: &str) -> (&'static str, &'static str) {
    match action {
        "applications" => ("Application", "App launcher"),
        "terminal" => ("Application", "Terminal launcher"),
        "lock" => ("System action", "Lock screen"),
        "trash" => ("Virtual folder", "Trash via Gio"),
        "documents" => ("User folder", "Documents via Gio"),
        action if action.starts_with("desktop-file:") =>
            ("Local file", "Open via Gio MIME handler"),
        action if action.starts_with("desktop-folder:") =>
            ("Local folder", "Open via RiceField / Gio"),
        action if action.starts_with("desktop-link:") =>
            ("Symbolic link", "Link activation is disabled"),
        "computer" => ("Virtual folder", "Computer via Gio"),
        "network" => ("Virtual folder", "Network via Gio"),
        _ => ("Shortcut", "Supported action"),
    }
}

/// Position in the chosen wl_output's logical coordinates, never outside its
/// work area; no global pointer coordinates or cross-output assumptions.
/// The compositor reports popup coordinates relative to its icon parent.
/// Use 64-bit arithmetic to validate every output work-area edge.
pub fn configured_inside_output(
    icon: (u32, u32), offset: (i32, i32), output: (u32, u32),
    panel_height: u32, top_panel: bool,
) -> bool {
    let x = i64::from(icon.0) + i64::from(offset.0);
    let y = i64::from(icon.1) + i64::from(offset.1);
    let upper = if top_panel { panel_height } else { 0 };
    let lower = if top_panel { 0 } else { panel_height };
    x >= 0 && y >= i64::from(upper)
        && x + i64::from(WIDTH) <= i64::from(output.0)
        && y + i64::from(HEIGHT) + i64::from(lower) <= i64::from(output.1)
}

pub fn placement(icon: (u32, u32), pointer: (f64, f64),
                 output: (u32, u32), panel_height: u32, top_panel: bool)
                 -> Option<(u32, u32)> {
    if !pointer.0.is_finite() || !pointer.1.is_finite()
        || pointer.0 < 0.0 || pointer.1 < 0.0
        || pointer.0 >= f64::from(crate::recipe::ICON_WIDTH)
        || pointer.1 >= f64::from(crate::recipe::ICON_HEIGHT) {
        return None;
    }
    let upper = if top_panel { panel_height } else { 0 };
    let bottom = if top_panel { 0 } else { panel_height };
    if output.0 < WIDTH || output.1 < HEIGHT.saturating_add(upper).saturating_add(bottom) {
        return None;
    }
    let x = icon.0.saturating_add(pointer.0.round() as u32)
        .min(output.0 - WIDTH);
    let y = icon.1.saturating_add(pointer.1.round() as u32)
        .clamp(upper, output.1 - HEIGHT - bottom);
    Some((x, y))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_filename_editor_blocks_traversal_and_supports_unicode() {
        let mut input = RenameInput::new("Report").unwrap();
        for c in " Grüße🚀".chars() {
            assert!(input.insert(&c.to_string()));
        }
        assert_eq!(input.value(), "Report Grüße🚀");
        assert!(!input.insert("/"));
        assert!(input.valid());
        for _ in 0.."Report Grüße🚀".chars().count() { assert!(input.erase()); }
        assert!(!input.valid());
        assert!(!input.insert("\0"));
        assert_eq!(Action::NextDisplay.label_for_file(), "Rename...");
        assert_eq!(Action::AllDisplays.label_for_file(), "Move to Trash");
        assert_eq!(Action::ResetPosition.label_for_file(), "Open in Explorer");
    }

    #[test]
    fn rows_disabled_navigation_and_back_are_bounded() {
        for action in Action::ALL {
            assert_eq!(hit(20.0, f64::from(row(action) + 14)), Some(action));
        }
        for (x, y) in [(-1.0, 46.0), (224.0, 46.0), (7.0, 35.0),
                        (7.0, 190.0), (f64::NAN, 40.0), (50.0, f64::INFINITY)] {
            assert_eq!(hit(x, y), None);
        }
        assert!(!Action::NextDisplay.enabled(false, true));
        assert!(!Action::ResetPosition.enabled(true, false));
        assert!(Action::Properties.enabled(false, false));
        assert_eq!(navigate(Action::Open, 1, false, false), Action::AllDisplays);
        assert_eq!(navigate(Action::AllDisplays, 1, false, false), Action::Properties);
        assert_eq!(navigate(Action::Properties, -1, false, true), Action::ResetPosition);
        assert_eq!(navigate(Action::Open, -1, true, true), Action::Properties);
        assert!(back_hit(20.0, f64::from(BACK_ROW + 12)));
        for (x, y) in [(2.0, 163.0), (224.0, 163.0), (20.0, 149.0),
                        (20.0, 178.0), (f64::NAN, 160.0)] {
            assert!(!back_hit(x, y));
        }
    }

    #[test]
    fn metadata_is_allowlisted_and_never_treated_as_file_attributes() {
        assert_eq!(details("trash"), ("Virtual folder", "Trash via Gio"));
        assert_eq!(details("network"), ("Virtual folder", "Network via Gio"));
        assert_eq!(details("terminal"), ("Application", "Terminal launcher"));
        assert_eq!(details("dangerous arbitrary shell string"),
                   ("Shortcut", "Supported action"));
    }

    #[test]
    fn configured_popup_respects_parent_and_panel_after_reposition() {
        assert!(configured_inside_output((24, 400), (44, 35),
                                         (1366, 768), 40, false));
        assert!(configured_inside_output((1000, 700), (-200, -162),
                                         (1024, 768), 40, false));
        assert!(configured_inside_output((0, 0), (0, 40),
                                         (224, 250), 40, true));
        assert!(!configured_inside_output((24, 400), (-25, 35),
                                          (1366, 768), 40, false));
        assert!(!configured_inside_output((1000, 700), (0, 0),
                                          (1024, 768), 40, false));
        assert!(!configured_inside_output((0, 0), (0, 0),
                                          (224, 250), 40, true));
        assert!(!configured_inside_output((0, 0), (i32::MAX, 0),
                                          (1366, 768), 40, false));
        assert!(!configured_inside_output((0, 0), (0, i32::MIN),
                                          (1366, 768), 40, false));
    }

    #[test]
    fn popup_stays_within_logical_output_and_clear_of_panel() {
        assert_eq!(placement((24, 400), (44.0, 35.0), (1366, 768), 40, false),
                   Some((68, 435)));
        assert_eq!(placement((1000, 700), (100.0, 80.0), (1024, 768), 40, false),
                   Some((800, 538)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (224, 250), 40, true),
                   Some((0, 40)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (200, 250), 40, false), None);
        assert_eq!(placement((0, 0), (2.0, 2.0), (224, 200), 40, true), None);
        assert_eq!(placement((0, 0), (f64::NAN, 2.0), (1366, 768), 40, false), None);
        assert_eq!(placement((0, 0), (-1.0, 0.0), (1366, 768), 40, false), None);
    }
}
