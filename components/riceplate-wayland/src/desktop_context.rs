//! Tiny XP Luna shortcut context menu, shared by pointer and keyboard input.
//! Only fixed, user-visible allowlisted actions; never execute recipe strings.
pub const WIDTH: u32 = 224;
pub const HEIGHT: u32 = 134;
const FIRST_ROW: u32 = 36;
const ROW_HEIGHT: u32 = 28;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action { Open, NextDisplay, AllDisplays }

impl Action {
    pub const ALL: [Self; 3] = [Self::Open, Self::NextDisplay, Self::AllDisplays];
    pub fn label(self) -> &'static str {
        match self {
            Self::Open => "Open",
            Self::NextDisplay => "Next display",
            Self::AllDisplays => "All displays",
        }
    }
    pub fn enabled(self, multi_output: bool) -> bool {
        self != Self::NextDisplay || multi_output
    }
    pub fn index(self) -> usize {
        match self { Self::Open => 0, Self::NextDisplay => 1, Self::AllDisplays => 2 }
    }
}

pub fn row(action: Action) -> u32 { FIRST_ROW + action.index() as u32 * ROW_HEIGHT }

pub fn hit(x: f64, y: f64) -> Option<Action> {
    if !x.is_finite() || !y.is_finite()
        || x < 5.0 || x >= f64::from(WIDTH - 5)
        || y < f64::from(FIRST_ROW) || y >= f64::from(FIRST_ROW + 3 * ROW_HEIGHT) {
        return None;
    }
    Action::ALL.get(((y as u32 - FIRST_ROW) / ROW_HEIGHT) as usize).copied()
}

pub fn navigate(current: Action, delta: i32, multi_output: bool) -> Action {
    let mut index = current.index() as i32;
    for _ in 0..Action::ALL.len() {
        index = (index + delta).rem_euclid(Action::ALL.len() as i32);
        let action = Action::ALL[index as usize];
        if action.enabled(multi_output) { return action; }
    }
    current
}

/// Position in the chosen wl_output's logical coordinates, never outside its
/// work area; no global pointer coordinates or cross-output assumptions.
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
    fn real_rows_and_disabled_action_are_bounded() {
        for action in Action::ALL {
            assert_eq!(hit(20.0, f64::from(row(action) + 14)), Some(action));
        }
        for (x, y) in [(-1.0, 46.0), (224.0, 46.0), (7.0, 35.0),
                        (7.0, 134.0), (f64::NAN, 40.0), (50.0, f64::INFINITY)] {
            assert_eq!(hit(x, y), None);
        }
        assert!(!Action::NextDisplay.enabled(false));
        assert!(Action::NextDisplay.enabled(true));
        assert_eq!(navigate(Action::Open, 1, false), Action::AllDisplays);
        assert_eq!(navigate(Action::AllDisplays, -1, false), Action::Open);
        assert_eq!(navigate(Action::Open, -1, true), Action::AllDisplays);
    }

    #[test]
    fn popup_stays_within_logical_output_and_clear_of_panel() {
        assert_eq!(placement((24, 400), (44.0, 35.0), (1366, 768), 40, false),
                   Some((68, 435)));
        assert_eq!(placement((1000, 700), (100.0, 80.0), (1024, 768), 40, false),
                   Some((800, 594)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (224, 200), 40, true),
                   Some((2, 40)));
        assert_eq!(placement((0, 0), (2.0, 2.0), (200, 200), 40, false), None);
        assert_eq!(placement((0, 0), (f64::NAN, 2.0), (1366, 768), 40, false), None);
        assert_eq!(placement((0, 0), (-1.0, 0.0), (1366, 768), 40, false), None);
    }
}
