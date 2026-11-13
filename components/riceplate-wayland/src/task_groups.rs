//! Pure window grouping for RicePlate: no compositor handle or background work.
//! Groups are rebuilt only when a Wayland event or frame needs them (<=128 tasks).

use std::collections::HashMap;

#[derive(Debug, Default, PartialEq, Eq)]
pub struct WindowState {
    pub active: bool,
    pub minimized: bool,
    pub maximized: bool,
}

/// wlroots foreign-toplevel `state` is a native-endian array of u32 values.
/// Ignore an incomplete trailing value instead of treating it as a state.
pub fn decode_window_state(raw: &[u8]) -> WindowState {
    let mut result = WindowState::default();
    for chunk in raw.chunks_exact(4) {
        let state = u32::from_ne_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
        match state {
            0 => result.maximized = true,
            1 => result.minimized = true,
            2 => result.active = true,
            _ => {}
        }
    }
    result
}

pub struct WindowInfo<'a> {
    pub index: usize,
    pub app_id: &'a str,
    pub title: &'a str,
    pub active: bool,
    pub minimized: bool,
    pub ready: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub struct TaskGroup {
    pub members: Vec<usize>,
    pub representative: usize,
    pub label: String,
    pub active: bool,
    /// A group is shown as minimized only when every member is minimized.
    pub minimized: bool,
}

pub fn task_label(title: &str, app_id: &str) -> String {
    // wlroots titles are supplied by applications, not by the compositor.
    // Strip control characters *before* applying the fixed taskband budget.
    let clean = |value: &str| -> String {
        value.chars().filter(|ch| {
            !ch.is_control() && !matches!(*ch,
                '\u{061c}' | '\u{200e}' | '\u{200f}' |
                '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
        }).take(18).collect::<String>().trim().to_owned()
    };
    let title = clean(title);
    if !title.is_empty() { return title; }
    let app = clean(app_id);
    if !app.is_empty() { app } else { "Window".to_owned() }
}

/// Stable application order, but no accidental grouping of unknown app IDs.
pub fn group_windows<'a>(windows: impl IntoIterator<Item = WindowInfo<'a>>) -> Vec<TaskGroup> {
    group_windows_with_policy(windows, true)
}

/// Keep identity and order stable while honoring Luna's opt-in grouping
/// preference. Other rices retain their established grouped behavior.
pub fn group_windows_with_policy<'a>(
    windows: impl IntoIterator<Item = WindowInfo<'a>>, grouped: bool,
) -> Vec<TaskGroup> {
    let mut groups: Vec<TaskGroup> = Vec::new();
    let mut by_app_id: HashMap<&'a str, usize> = HashMap::new();
    for window in windows {
        if !window.ready { continue; }
        let id = window.app_id.trim();
        if grouped && !id.is_empty() {
            if let Some(&index) = by_app_id.get(id) {
                let group = &mut groups[index];
                group.members.push(window.index);
                group.minimized &= window.minimized;
                if window.active {
                    group.active = true;
                    group.representative = window.index;
                    group.label = task_label(window.title, window.app_id);
                }
                continue;
            }
            by_app_id.insert(id, groups.len());
        }
        groups.push(TaskGroup {
            members: vec![window.index], representative: window.index,
            label: task_label(window.title, window.app_id), active: window.active,
            minimized: window.minimized,
        });
    }
    groups
}

/// Always preserve a visible window count in the available text width.
pub fn visible_label(group: &TaskGroup, cell_width: u32) -> String {
    let capacity = (cell_width.saturating_sub(16) / 8) as usize;
    let suffix = if group.members.len() > 1 {
        format!(" ({})", group.members.len())
    } else { String::new() };
    if capacity < suffix.len() {
        // On a compressed taskband, retain the rightmost count digits rather
        // than showing only the otherwise meaningless leading " (".
        return suffix.chars().skip(suffix.len() - capacity).collect();
    }
    let mut label: String = group.label.chars().take(capacity - suffix.len()).collect();
    label.push_str(&suffix);
    label
}

/// Clicking an active group cycles its windows. A singleton minimizes instead.
pub fn click_target(group: &TaskGroup, active_index: Option<usize>) -> (usize, bool) {
    if group.active && group.members.len() == 1 {
        return (group.representative, true);
    }
    if group.active && group.members.len() > 1 {
        let next = active_index.and_then(|current| group.members.iter()
            .position(|&member| member == current))
            .map_or(0, |position| (position + 1) % group.members.len());
        return (group.members[next], false);
    }
    (group.representative, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn window<'a>(index: usize, app_id: &'a str, title: &'a str, active: bool) -> WindowInfo<'a> {
        WindowInfo { index, app_id, title, active, minimized: false, ready: true }
    }

    #[test]
    fn groups_repeated_app_ids_but_never_unknown_or_not_ready_windows() {
        let list = vec![window(0, "editor", "First", false),
                        window(1, "terminal", "Shell", false),
                        window(2, "editor", "Second", true),
                        window(3, "", "Anonymous A", false),
                        window(4, "", "Anonymous B", false),
                        WindowInfo { index: 5, app_id: "editor", title: "Incomplete",
                                     active: false, minimized: false, ready: false }];
        let groups = group_windows(list);
        assert_eq!(groups.len(), 4);
        assert_eq!(groups[0].members, [0, 2]);
        assert_eq!(groups[0].representative, 2);
        assert_eq!(groups[0].label, "Second");
        assert!(groups[0].active);
        assert_eq!(groups[1].members, [1]);
        assert_eq!(groups[2].members, [3]);
        assert_eq!(groups[3].members, [4]);
    }

    #[test]
    fn clicking_active_group_cycles_but_a_singleton_minimizes() {
        let groups = group_windows([
            window(0, "editor", "One", false),
            window(1, "editor", "Two", true),
            window(2, "editor", "Three", false),
            window(3, "terminal", "Shell", true),
        ]);
        assert_eq!(click_target(&groups[0], Some(1)), (2, false));
        assert_eq!(click_target(&groups[0], Some(2)), (0, false));
        assert_eq!(click_target(&groups[0], None), (0, false));
        assert_eq!(click_target(&groups[1], Some(3)), (3, true));
    }

    #[test]
    fn compact_labels_preserve_ascii_window_count() {
        let mut groups = group_windows([
            window(0, "editor", "Untitled very long document", false),
            window(1, "editor", "Second document", true),
        ]);
        let group = groups.remove(0);
        assert_eq!(visible_label(&group, 164), "Second documen (2)");
        assert_eq!(visible_label(&group, 64), "Se (2)");
        assert_eq!(visible_label(&group, 8), "");
        assert_eq!(visible_label(&group, 32), "2)");
        assert_eq!(visible_label(&group, 40), "(2)");
    }

    #[test]
    fn task_labels_ignore_untrusted_controls_before_clipping() {
        assert_eq!(task_label("\n\tA document", "app"), "A document");
        assert_eq!(task_label("\r\n", "org.example.App"), "org.example.App");
        assert_eq!(task_label("", ""), "Window");
        assert_eq!(task_label("\n\t12345678901234567890", ""),
                   "123456789012345678");
    }

    #[test]
    fn group_policy_retains_distinct_instances_and_minimized_state() {
        let entries = [
            WindowInfo { minimized: true, ..window(0, "editor", "First", false) },
            window(1, "editor", "Second", true),
            WindowInfo { minimized: true, ..window(2, "editor", "Third", false) },
            WindowInfo { minimized: true, ..window(3, "music", "Player", false) },
        ];
        let grouped = group_windows_with_policy(entries.iter().map(|w| WindowInfo {
            index: w.index, app_id: w.app_id, title: w.title, active: w.active,
            minimized: w.minimized, ready: w.ready,
        }), true);
        assert_eq!(grouped.len(), 2);
        assert_eq!(grouped[0].members, [0, 1, 2]);
        assert!(!grouped[0].minimized, "one visible editor keeps the group unminimized");
        assert!(grouped[1].minimized);
        let ungrouped = group_windows_with_policy(entries, false);
        assert_eq!(ungrouped.iter().map(|g| g.members.as_slice()).collect::<Vec<_>>(),
                   vec![&[0][..], &[1][..], &[2][..], &[3][..]]);
        assert_eq!(ungrouped.iter().map(|g| g.minimized).collect::<Vec<_>>(),
                   [true, false, true, true]);
        assert_eq!(click_target(&ungrouped[1], Some(1)), (1, true));
    }

    #[test]
    fn title_labels_strip_bidi_spoofing_without_affecting_unicode() {
        assert_eq!(task_label("Report\u{202e}cod.exe\u{202c}", ""), "Reportcod.exe");
        assert_eq!(task_label("\u{2066}Dokumentä\u{2069}", ""), "Dokumentä");
    }

    #[test]
    fn foreign_toplevel_states_track_activation_and_minimize_independently() {
        let encoded: Vec<u8> = [0_u32, 2, 3, 1]
            .iter().flat_map(|value| value.to_ne_bytes()).collect();
        assert_eq!(decode_window_state(&encoded), WindowState { active: true, minimized: true, maximized: true });
        assert_eq!(decode_window_state(&1_u32.to_ne_bytes()),
            WindowState { active: false, minimized: true, maximized: false });
        assert!(decode_window_state(&0_u32.to_ne_bytes()).maximized);
        assert_eq!(decode_window_state(&[0, 0, 0]), WindowState::default());
        assert_eq!(decode_window_state(&[]), WindowState::default());
    }
}
