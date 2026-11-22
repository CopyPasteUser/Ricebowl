//! Pure keyboard navigation for a panel with a launcher and grouped windows.
//! The same model is reused by primary and secondary Wayland panels.

use crate::recipe::{self, PanelStyle, Widget};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    Launcher,
    Action(u8),
    Task(usize),
    Tray(usize),
    Status(Widget),
    Clock,
}

fn available(style: &PanelStyle, width: u32, task_count: usize,
             tray_count: usize) -> Vec<Target> {
    let layout = recipe::layout(style, width, task_count);
    let mut targets = Vec::with_capacity(task_count + 1);
    for item in layout.into_iter().filter(|item| item.x + item.width <= width) {
        match item.widget {
            Widget::Launcher => targets.push(Target::Launcher),
            Widget::Action(index) => targets.push(Target::Action(index)),
            Widget::Tasks if recipe::task_view(style, width, task_count, 0).is_some() =>
                targets.extend((0..task_count).map(Target::Task)),
            Widget::Tray if tray_count > 0 => targets.extend(
                (0..tray_count.min(crate::tray::VISIBLE_ITEMS)).map(Target::Tray)),
            Widget::Network | Widget::Audio | Widget::Battery
                if style.id == "xp-luna-columns" => targets.push(Target::Status(item.widget)),
            Widget::Clock if style.id == "xp-luna-columns" => targets.push(Target::Clock),
            _ => {},
        }
    }
    targets
}

pub fn initial(
    style: &PanelStyle,
    width: u32,
    tasks: usize,
    active_group: Option<usize>,
    tray_count: usize,
) -> Option<Target> {
    let targets = available(style, width, tasks, tray_count);
    if let Some(index) = active_group {
        let target = Target::Task(index);
        if targets.contains(&target) {
            return Some(target);
        }
    }
    targets.first().copied()
}

pub fn advance(
    style: &PanelStyle,
    width: u32,
    tasks: usize,
    current: Option<Target>,
    delta: isize,
    tray_count: usize,
) -> Option<Target> {
    let targets = available(style, width, tasks, tray_count);
    if targets.is_empty() {
        return None;
    }
    let previous = current.and_then(|selected| targets.iter().position(|t| *t == selected));
    let index = previous.map_or_else(
        || if delta >= 0 { 0 } else { targets.len() - 1 },
        |index| {
            // Never add an arbitrary signed step to an index: isize::MIN
            // and isize::MAX can overflow before rem_euclid runs.
            let shift = delta.rem_euclid(targets.len() as isize) as usize;
            (index + shift) % targets.len()
        },
    );
    Some(targets[index])
}

/// Keep keyboard selection bound to surviving compositor handles, not to a
/// shifting task-group index. Never invoke another app after its predecessor
/// closes; a vanished group has no valid target until the user navigates.
pub(crate) fn remap_after_close<H: PartialEq>(
    current: Option<Target>,
    old_members: &[H],
    remaining: &[Vec<H>],
) -> Option<Target> {
    match current {
        Some(Target::Task(_)) => remaining.iter()
            .position(|members| members.iter()
                .any(|handle| old_members.contains(handle)))
            .map(Target::Task),
        other => other,
    }
}

pub fn reveal(
    style: &PanelStyle,
    width: u32,
    tasks: usize,
    offset: usize,
    selected: Option<Target>,
) -> usize {
    let Some(Target::Task(index)) = selected else {
        return offset;
    };
    if index >= tasks {
        return offset;
    }
    let Some(view) = recipe::task_view(style, width, tasks, offset) else {
        return offset;
    };
    if index < view.start {
        index
    } else if index >= view.start + view.slots {
        index + 1 - view.slots
    } else {
        offset
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xp_luna_status_icons_are_keyboard_reachable_in_compact_panel() {
        let style = crate::recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        for width in [800, 1024, 1366] {
            let sequence = available(&style, width, 2, 0);
            for widget in [Widget::Network, Widget::Audio, Widget::Battery] {
                assert!(sequence.contains(&Target::Status(widget)));
            }
            assert!(sequence.contains(&Target::Clock));
            assert_eq!(advance(&style, width, 2,
                      Some(Target::Status(Widget::Battery)), 1, 0),
                      Some(Target::Clock));
        }
    }

    #[test]
    fn native_actions_follow_panel_order_and_disappear_with_compact_layout() {
        let style = crate::recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-actions-v6.json"),
            Some("mockup-actions")).unwrap();
        assert_eq!(advance(&style, 1280, 2, Some(Target::Launcher), 1, 0),
                   Some(Target::Action(0)));
        assert_eq!(advance(&style, 1280, 2, Some(Target::Action(0)), 1, 0),
                   Some(Target::Task(0)));
        assert_eq!(advance(&style, 600, 2, Some(Target::Launcher), 1, 0),
                   Some(Target::Task(0)));
        assert_eq!(advance(&style, 600, 2, Some(Target::Task(1)), 1, 0),
                   Some(Target::Action(1)));
    }

    #[test]
    fn stateful_control_uses_the_same_keyboard_path_on_both_layouts() {
        let style = crate::recipe::parse(
            include_str!("../../../tests/fixtures/riceplate-controls-v7.json"),
            Some("mockup-controls")).unwrap();
        assert_eq!(advance(&style, 1280, 2, Some(Target::Task(1)), 1, 0),
                   Some(Target::Action(0)));
        assert_eq!(advance(&style, 600, 2, Some(Target::Task(1)), 1, 0),
                   Some(Target::Action(1)));
    }

    #[test]
    fn closed_window_remaps_task_focus_by_handle_not_old_index() {
        let old = [30_u32];
        let remaining = [vec![10], vec![30], vec![40]];
        assert_eq!(remap_after_close(Some(Target::Task(2)), &old, &remaining),
                   Some(Target::Task(1)));
        assert_eq!(remap_after_close(Some(Target::Task(2)), &old, &[vec![10], vec![40]]),
                   None);
        assert_eq!(remap_after_close(Some(Target::Task(99)), &[], &remaining),
                   None);
        assert_eq!(remap_after_close(Some(Target::Launcher), &old, &remaining),
                   Some(Target::Launcher));
        assert_eq!(remap_after_close(Some(Target::Task(0)), &[20, 21],
                   &[vec![10], vec![21], vec![40]]), Some(Target::Task(1)));
    }

    #[test]
    fn chrome_and_xp_luna_both_expose_shared_tasks_via_keyboard() {
        let chrome = crate::recipe::load("chrome").unwrap();
        let luna = crate::recipe::load("xp-luna-columns").unwrap();
        for style in [&chrome, &luna] {
            let width = 1024;
            assert_eq!(initial(style, width, 2, Some(1), 0),
                       Some(Target::Task(1)));
            assert_eq!(advance(style, width, 2, Some(Target::Task(0)), 1, 0),
                       Some(Target::Task(1)));
            assert!(recipe::task_view(style, width, 2, 0).is_some());
        }
    }

    #[test]
    fn extreme_navigation_steps_do_not_overflow_or_select_stale_targets() {
        let style = crate::recipe::load("classic").unwrap();
        let targets = available(&style, 1200, 3, 0);
        let start = targets.iter().position(|target| *target == Target::Task(1)).unwrap();
        for delta in [isize::MIN, isize::MAX, -1, 1] {
            let shift = delta.rem_euclid(targets.len() as isize) as usize;
            let expected = targets[(start + shift) % targets.len()];
            assert_eq!(
                advance(&style, 1200, 3, Some(Target::Task(1)), delta, 0),
                Some(expected)
            );
        }
        assert_eq!(
            advance(&style, 1200, 3, Some(Target::Task(99)), isize::MIN, 0),
            targets.last().copied()
        );
    }

    #[test]
    fn keyboard_wraps_over_launcher_and_grouped_windows() {
        let style = crate::recipe::load("classic").unwrap();
        assert_eq!(initial(&style, 1200, 3, None, 0), Some(Target::Launcher));
        assert_eq!(
            advance(&style, 1200, 3, Some(Target::Launcher), 1, 0),
            Some(Target::Task(0))
        );
        assert_eq!(
            advance(&style, 1200, 3, Some(Target::Task(2)), 1, 0),
            Some(Target::Launcher)
        );
        assert_eq!(
            advance(&style, 1200, 3, Some(Target::Launcher), -1, 0),
            Some(Target::Task(2))
        );
        assert_eq!(initial(&style, 1200, 3, Some(2), 0), Some(Target::Task(2)));
    }

    #[test]
    fn keyboard_reveals_offscreen_groups_without_touching_other_outputs() {
        let style = crate::recipe::load("classic").unwrap();
        let width = 640;
        let tasks = 20;
        let view = recipe::task_view(&style, width, tasks, 0).unwrap();
        assert!(view.slots < tasks);
        let last = reveal(&style, width, tasks, 0, Some(Target::Task(19)));
        assert_eq!(last, 20 - view.slots);
        assert_eq!(reveal(&style, width, tasks, last, Some(Target::Task(0))), 0);
        assert_eq!(
            reveal(&style, width, tasks, last, Some(Target::Launcher)),
            last
        );
    }

    #[test]
    fn empty_task_only_panel_has_no_keyboard_action() {
        let mut style = crate::recipe::load("classic").unwrap();
        style.sections = [vec![Widget::Tasks], Vec::new(), Vec::new()];
        assert_eq!(advance(&style, 640, 0, None, 1, 0), None);
    }

    #[test]
    fn tray_slots_enter_keyboard_order_and_wrap_back_to_launcher() {
        let style = crate::recipe::load("classic").unwrap();
        let width = 1200;
        let selected = advance(&style, width, 0, Some(Target::Launcher), 1, 4);
        assert_eq!(selected, Some(Target::Tray(0)));
        assert_eq!(advance(&style, width, 0, Some(Target::Tray(3)), 1, 4),
                   Some(Target::Launcher));
        assert_eq!(advance(&style, width, 0, Some(Target::Tray(0)), -1, 4),
                   Some(Target::Launcher));
        assert_eq!(advance(&style, 320, 0, Some(Target::Launcher), 1, 4),
                   Some(Target::Launcher), "compact panel must not focus hidden tray slots");
    }
}
