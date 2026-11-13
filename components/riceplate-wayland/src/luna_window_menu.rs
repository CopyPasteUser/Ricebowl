//! XP Luna task-button context menu policy.
//! Only real foreign-toplevel windows are exposed. The popup is local to
//! RicePlate and reuses its existing Wayland popup, not application SNI menus.
use crate::{task_groups, tray};

pub const WINDOW_BASE: i32 = 6_000;
pub const SWITCH_NEXT: i32 = 6_100;
pub const RESTORE: i32 = 6_101;
pub const MINIMIZE: i32 = 6_102;
pub const MAXIMIZE: i32 = 6_103;
pub const CLOSE: i32 = 6_104;
pub const RESTORE_ALL: i32 = 6_105;
pub const MINIMIZE_ALL: i32 = 6_106;
pub const CLOSE_ALL: i32 = 6_107;
pub const MAX_WINDOW_ROWS: usize = 20;

#[derive(Clone, Copy)]
pub struct Window<'a> {
    pub title: &'a str,
    pub app_id: &'a str,
    pub active: bool,
    pub minimized: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    Activate(usize),
    NextWindow,
    Restore,
    Minimize,
    Maximize,
    Close,
    RestoreAll,
    MinimizeAll,
    CloseAll,
}

pub fn decode(id: i32, window_count: usize) -> Option<Action> {
    if let Some(index) = id.checked_sub(WINDOW_BASE) {
        if (0..MAX_WINDOW_ROWS as i32).contains(&index)
            && (index as usize) < window_count {
            return Some(Action::Activate(index as usize));
        }
    }
    Some(match id {
        SWITCH_NEXT if window_count > 1 => Action::NextWindow,
        RESTORE if window_count == 1 => Action::Restore,
        MINIMIZE if window_count == 1 => Action::Minimize,
        MAXIMIZE if window_count == 1 => Action::Maximize,
        CLOSE if window_count == 1 => Action::Close,
        RESTORE_ALL if window_count > 1 => Action::RestoreAll,
        MINIMIZE_ALL if window_count > 1 => Action::MinimizeAll,
        CLOSE_ALL if window_count > 1 => Action::CloseAll,
        _ => return None,
    })
}

/// Window titles are untrusted app-controlled text. The existing taskband
/// capacity is preserved, but control characters cannot alter menu rows.
fn title_label(title: &str, app_id: &str) -> String {
    task_groups::task_label(title, app_id).chars()
        .filter(|ch| !ch.is_control()).collect()
}

fn item(id: i32, label: &str, enabled: bool, checked: bool) -> tray::MenuRow {
    tray::MenuRow {
        id,
        label: label.to_owned(),
        enabled,
        kind: tray::MenuKind::Action { checked, radio: false },
    }
}

/// No user-supplied command strings are ever placed in local popup actions.
/// Long groups retain access to every window through "Next window" and group
/// operations, while menu painting remains bounded.
pub fn entries(windows: &[Window<'_>]) -> Option<(String, Vec<tray::MenuRow>)> {
    let first = windows.first()?;
    let title = if windows.len() == 1 {
        title_label(first.title, first.app_id)
    } else {
        format!("{} windows", windows.len())
    };
    let mut rows = Vec::with_capacity(MAX_WINDOW_ROWS + 5);
    if windows.len() == 1 {
        rows.push(item(RESTORE, "Restore", first.minimized, false));
        rows.push(item(MINIMIZE, "Minimize", !first.minimized, false));
        rows.push(item(MAXIMIZE, "Maximize", true, false));
        rows.push(item(CLOSE, "Close", true, false));
    } else {
        for (index, window) in windows.iter().take(MAX_WINDOW_ROWS).enumerate() {
            let label = title_label(window.title, window.app_id);
            rows.push(item(WINDOW_BASE + index as i32, &label, true, window.active));
        }
        if windows.len() > MAX_WINDOW_ROWS {
            rows.push(item(0, "More: use Next window", false, false));
        }
        rows.push(item(SWITCH_NEXT, "Next window", true, false));
        rows.push(item(RESTORE_ALL, "Restore all", windows.iter().any(|w| w.minimized), false));
        rows.push(item(MINIMIZE_ALL, "Minimize all", windows.iter().any(|w| !w.minimized), false));
        rows.push(item(CLOSE_ALL, "Close group", true, false));
    }
    Some((title, rows))
}

/// A right-anchored layer-shell popup is positioned alongside the clicked
/// task, clamped to the visible panel; it never crosses to another output.
pub fn right_margin(panel_width: u32, click_x: f64) -> i32 {
    const EDGE: u32 = 8;
    let desired = if click_x.is_finite() {
        click_x.max(0.0).min(f64::from(panel_width)) as u32
    } else {
        EDGE
    };
    let max_left = panel_width.saturating_sub(tray::POPUP_WIDTH + EDGE).max(EDGE);
    let left = desired.clamp(EDGE, max_left);
    panel_width.saturating_sub(left + tray::POPUP_WIDTH).max(EDGE) as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    fn w(title: &'static str, active: bool, minimized: bool) -> Window<'static> {
        Window { title, app_id: "org.example.Editor", active, minimized }
    }

    #[test]
    fn singleton_menu_has_live_window_actions_and_no_fake_sni_commands() {
        let (title, rows) = entries(&[w("Document", true, false)]).unwrap();
        assert_eq!(title, "Document");
        assert_eq!(rows.iter().map(|row| row.id).collect::<Vec<_>>(),
                   [RESTORE, MINIMIZE, MAXIMIZE, CLOSE]);
        assert!(!rows[0].enabled);
        assert!(rows[1].enabled);
        assert_eq!(decode(CLOSE, 1), Some(Action::Close));
        assert_eq!(decode(CLOSE_ALL, 1), None);
        let (_, minimized) = entries(&[w("Draft", false, true)]).unwrap();
        assert!(minimized[0].enabled);
        assert!(!minimized[1].enabled);
        assert!(entries(&[]).is_none());
    }

    #[test]
    fn groups_include_real_titles_count_and_bounded_fallback_navigation() {
        let windows = [w("First", false, false), w("Second", true, true)];
        let (title, rows) = entries(&windows).unwrap();
        assert_eq!(title, "2 windows");
        assert_eq!(rows[0].label, "First");
        assert_eq!(rows[1].label, "Second");
        assert!(matches!(&rows[1].kind, tray::MenuKind::Action { checked: true, .. }));
        assert_eq!(decode(rows[1].id, 2), Some(Action::Activate(1)));
        assert_eq!(decode(SWITCH_NEXT, 2), Some(Action::NextWindow));
        assert_eq!(decode(RESTORE_ALL, 2), Some(Action::RestoreAll));
        assert_eq!(decode(MINIMIZE_ALL, 2), Some(Action::MinimizeAll));
        assert_eq!(decode(CLOSE_ALL, 2), Some(Action::CloseAll));
        assert_eq!(decode(WINDOW_BASE + 5, 2), None);
        assert_eq!(title_label("A\nB\rC", ""), "ABC");

        let many = vec![w("Window", false, false); 128];
        let (_, rows) = entries(&many).unwrap();
        assert_eq!(rows.len(), MAX_WINDOW_ROWS + 5);
        assert!(!rows[MAX_WINDOW_ROWS].enabled);
        assert_eq!(decode(WINDOW_BASE + 21, 128), None);
        assert_eq!(decode(SWITCH_NEXT, 128), Some(Action::NextWindow));
    }

    #[test]
    fn right_anchored_popup_tracks_pointer_and_clamps_on_both_edges() {
        assert_eq!(right_margin(1024, 100.0), 636);
        assert_eq!(right_margin(1024, 999.0), 8);
        assert_eq!(right_margin(1024, -40.0), 728);
        assert_eq!(right_margin(320, f64::NAN), 24);
        assert_eq!(right_margin(320, f64::INFINITY), 24);
    }
}
