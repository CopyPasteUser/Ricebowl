//! Shared input interpretation for native panel surfaces.
//!
//! Device/protocol ownership remains in SCTK and RicePlate. These pure
//! transitions decide focus navigation, pointer cosmetics and hit bounds;
//! recipes still define layout and the approved action that executes.

use smithay_client_toolkit::seat::keyboard::Keysym;
use crate::{
    panel_chrome::ButtonVisual,
    recipe::{self, Hit, PanelStyle},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PanelKey {
    Step(isize),
    Invoke,
    Dismiss,
}

pub(crate) fn panel_key(key: Keysym) -> Option<PanelKey> {
    match key {
        Keysym::Right | Keysym::Down | Keysym::Tab => Some(PanelKey::Step(1)),
        Keysym::Left | Keysym::Up | Keysym::ISO_Left_Tab => Some(PanelKey::Step(-1)),
        Keysym::Return | Keysym::KP_Enter | Keysym::space | Keysym::Menu =>
            Some(PanelKey::Invoke),
        Keysym::Escape => Some(PanelKey::Dismiss),
        _ => None,
    }
}

/// All panel mouse actions use recipe::hit after checking the same logical
/// surface bounds. A collapsed 3px handle is not an interactive taskbar.
pub(crate) fn panel_hit(
    style: &PanelStyle, width: u32, height: u32, position: (f64, f64),
    tasks: usize, offset: usize,
) -> Option<Hit> {
    let (x, y) = position;
    if !x.is_finite() || !y.is_finite() || x < 0.0 || y < 0.0
        || x >= f64::from(width) || y >= f64::from(height) {
        return None;
    }
    recipe::hit(x, width, tasks, offset, style)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum PointerSignal { Hover, Leave, Press, Release }

/// Physical hover/pressed feedback is strictly surface scoped. A leave on
/// one monitor must not erase a newer hover on another monitor. Release
/// clears the captured pressed state, even when delivered on another surface.
/// Change one output-owned target only when the hit or owner actually
/// changes. A high-frequency Motion over the same widget must not clone a
/// Wayland surface proxy or schedule another frame.
fn assign_target<S: Clone + PartialEq, T: PartialEq>(
    slot: &mut Option<(S, T)>, surface: &S, target: Option<T>,
) -> bool {
    if slot.as_ref().is_none_or(|(owner, _)| owner != surface)
        || slot.as_ref().is_some_and(|(_, old)| target.as_ref() != Some(old)) {
        if slot.is_none() && target.is_none() { return false; }
        *slot = target.map(|hit| (surface.clone(), hit));
        return true;
    }
    if slot.is_some() && target.is_none() {
        *slot = None;
        return true;
    }
    false
}

pub(crate) fn update_feedback<S: Clone + PartialEq, T: Clone + PartialEq>(
    hovered: &mut Option<(S, T)>,
    pressed: &mut Option<(S, T)>,
    surface: &S,
    target: Option<T>,
    signal: PointerSignal,
) -> bool {
    match signal {
        PointerSignal::Hover => assign_target(hovered, surface, target),
        PointerSignal::Leave => {
            let mut changed = false;
            if hovered.as_ref().is_some_and(|(owner, _)| owner == surface) {
                *hovered = None;
                changed = true;
            }
            if pressed.as_ref().is_some_and(|(owner, _)| owner == surface) {
                *pressed = None;
                changed = true;
            }
            changed
        }
        PointerSignal::Press => {
            let hover_changed = assign_target(hovered, surface, target.clone());
            let press_changed = assign_target(pressed, surface, target);
            hover_changed || press_changed
        }
        PointerSignal::Release => {
            let press_changed = pressed.take().is_some();
            let hover_changed = assign_target(hovered, surface, target);
            press_changed || hover_changed
        }
    }
}

/// Paint-only feedback: the recipe's hit test and command path remain the
/// only sources of actual activation, while a button paints pressed only
/// if the same target is still hovered.
#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub(crate) struct PanelPointerVisual {
    pub(crate) hovered: Option<Hit>,
    pub(crate) pressed: Option<Hit>,
}

impl PanelPointerVisual {
    pub(crate) fn button(self, target: Hit) -> ButtonVisual {
        if self.pressed == Some(target) && self.hovered == Some(target) {
            ButtonVisual::Pressed
        } else if self.hovered == Some(target) {
            ButtonVisual::Hovered
        } else {
            ButtonVisual::Normal
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe::Widget;

    #[test]
    fn panel_keys_have_identical_meaning_across_recipes() {
        assert_eq!(panel_key(Keysym::Tab), Some(PanelKey::Step(1)));
        assert_eq!(panel_key(Keysym::ISO_Left_Tab), Some(PanelKey::Step(-1)));
        assert_eq!(panel_key(Keysym::Down), Some(PanelKey::Step(1)));
        assert_eq!(panel_key(Keysym::Left), Some(PanelKey::Step(-1)));
        assert_eq!(panel_key(Keysym::Return), Some(PanelKey::Invoke));
        assert_eq!(panel_key(Keysym::KP_Enter), Some(PanelKey::Invoke));
        assert_eq!(panel_key(Keysym::Menu), Some(PanelKey::Invoke));
        assert_eq!(panel_key(Keysym::Escape), Some(PanelKey::Dismiss));
        assert_eq!(panel_key(Keysym::F2), None);
    }

    #[test]
    fn hit_testing_rejects_outside_and_non_finite_positions_for_two_rices() {
        let classic = recipe::load("classic").unwrap();
        let luna = recipe::parse(
            include_str!("../../../examples/wayland/xp-luna-columns.json"),
            Some("xp-luna-columns")).unwrap();
        for style in [&classic, &luna] {
            let width = 1366;
            let placed = recipe::layout(style, width, 2);
            let launcher = placed.iter()
                .find(|item| item.widget == Widget::Launcher).unwrap();
            let position = (f64::from(launcher.x + launcher.width / 2),
                            f64::from(style.height / 2));
            assert_eq!(panel_hit(style, width, style.height, position, 2, 0),
                       Some(Hit::Launcher));
            for bad in [
                (-1.0, position.1), (position.0, -1.0),
                (f64::from(width), position.1),
                (position.0, f64::from(style.height)),
                (position.0, f64::NAN),
                (f64::INFINITY, position.1),
            ] {
                assert_eq!(panel_hit(style, width, style.height, bad, 2, 0), None);
            }
        }
    }

    #[test]
    fn pointer_feedback_is_latched_per_surface_and_does_not_redraw_on_motion_spam() {
        let mut hovered = None;
        let mut pressed = None;
        let a = "output-a";
        let b = "output-b";
        assert!(update_feedback(&mut hovered, &mut pressed, &a,
            Some(Hit::Launcher), PointerSignal::Hover));
        assert!(!update_feedback(&mut hovered, &mut pressed, &a,
            Some(Hit::Launcher), PointerSignal::Hover));
        assert!(update_feedback(&mut hovered, &mut pressed, &a,
            Some(Hit::Launcher), PointerSignal::Press));
        assert_eq!(pressed, Some((a, Hit::Launcher)));
        assert!(update_feedback(&mut hovered, &mut pressed, &b,
            Some(Hit::Task(0)), PointerSignal::Hover));
        assert!(update_feedback(&mut hovered, &mut pressed, &a,
            None, PointerSignal::Leave));
        assert_eq!(hovered, Some((b, Hit::Task(0))));
        assert_eq!(pressed, None);
        assert!(!update_feedback(&mut hovered, &mut pressed, &a,
            None, PointerSignal::Leave));
        assert!(update_feedback(&mut hovered, &mut pressed, &b,
            Some(Hit::Task(0)), PointerSignal::Press));
        assert!(update_feedback(&mut hovered, &mut pressed, &b,
            Some(Hit::Task(0)), PointerSignal::Release));
        assert_eq!(pressed, None);
        assert!(update_feedback(&mut hovered, &mut pressed, &b,
            None, PointerSignal::Leave));
        assert_eq!(hovered, None);
    }

    #[test]
    fn pressed_visual_only_appears_over_its_hit_target() {
        let visual = PanelPointerVisual {
            hovered: Some(Hit::Launcher), pressed: Some(Hit::Launcher),
        };
        assert_eq!(visual.button(Hit::Launcher), ButtonVisual::Pressed);
        assert_eq!(visual.button(Hit::Task(0)), ButtonVisual::Normal);
        assert_eq!(PanelPointerVisual { hovered: None,
                     pressed: Some(Hit::Launcher) }.button(Hit::Launcher),
                   ButtonVisual::Normal);
    }
    #[test]
    fn unchanged_motion_does_not_clone_wayland_surface_owner() {
        use std::{cell::Cell, rc::Rc};
        #[derive(Debug)]
        struct Owner { id: usize, clones: Rc<Cell<u64>> }
        impl PartialEq for Owner {
            fn eq(&self, other: &Self) -> bool { self.id == other.id }
        }
        impl Clone for Owner {
            fn clone(&self) -> Self {
                self.clones.set(self.clones.get() + 1);
                Self { id: self.id, clones: self.clones.clone() }
            }
        }
        let clones = Rc::new(Cell::new(0));
        let owner = Owner { id: 1, clones: clones.clone() };
        let mut hovered = None;
        let mut pressed = None;
        assert!(update_feedback(&mut hovered, &mut pressed, &owner,
            Some(Hit::Launcher), PointerSignal::Hover));
        for _ in 0..10_000 {
            assert!(!update_feedback(&mut hovered, &mut pressed, &owner,
                Some(Hit::Launcher), PointerSignal::Hover));
        }
        assert_eq!(clones.get(), 1, "unchanged hover must not clone a wl_surface");
    }

}
