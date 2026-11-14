//! Shared input interpretation for native panel surfaces.
//!
//! Device/protocol ownership remains in SCTK and RicePlate. These pure
//! transitions decide focus navigation, pointer cosmetics and hit bounds;
//! recipes still define layout and the approved action that executes.

use std::time::{Duration, Instant};
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

/// Opt-in desktop focus intent. This is not a Wayland focus request:
/// only a compositor wl_keyboard.enter can confirm ownership. In particular,
/// Bottom-layer OnDemand surfaces may never receive focus on labwc.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)] // Integration owns main.rs and will wire this contract.
pub(crate) enum DesktopFocusIntent {
    PointerSelection,
    KeyboardNavigation,
    AssistiveAction,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)]
pub(crate) enum DesktopFocusPhase {
    Idle,
    AwaitingCompositor,
    Confirmed,
}

/// Pending acquisition is intentionally bounded; the integrator should arm
/// one calloop deadline and tear down the temporary surface on expiry.
pub(crate) const DESKTOP_FOCUS_TIMEOUT: Duration = Duration::from_millis(1500);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)]
pub(crate) struct DesktopFocusTicket(u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[allow(dead_code)]
pub(crate) enum DesktopFocusError {
    /// A live or just-retired Wayland surface cannot represent a fresh gesture.
    /// Use a new wl_surface object, not the Bottom icon or an old popup.
    ReusedSurface,
    ClockOverflow,
    GenerationExhausted,
}

#[derive(Debug)]
struct DesktopFocusRequest<S, O, W> {
    seat: S,
    output: O,
    surface: W,
    intent: DesktopFocusIntent,
    ticket: DesktopFocusTicket,
    deadline: Instant,
}

/// A fail-closed focus ledger for one ephemeral desktop keyboard target.
///
/// Acquiring a lease is NOT a Wayland focus request. A compositor-confirmed
/// wl_keyboard.enter for the exact seat and fresh surface is required before
/// *any* keyboard key/repeat can be dispatched. A late Enter after the
/// acquisition timeout is refused. The completed focus remains valid until
/// Leave, cancellation or an owned resource disappears, not for a fixed TTL.
///
/// No timer is created by this type. The integrator installs a one-shot
/// event-loop deadline from pending_deadline() and calls expire_pending_at().
/// If the compositor never gives focus, tear down the focus surface and leave
/// the desktop pointer-only. Never activate a permanent Exclusive Bottom layer.
#[derive(Debug)]
#[allow(dead_code)] // Integration owns main.rs and must attach real SCTK events.
pub(crate) struct DesktopFocusLease<S, O, W> {
    request: Option<DesktopFocusRequest<S, O, W>>,
    confirmed: bool,
    next_generation: u64,
    // Reject immediately reusing a live/stale surface after close/re-activation:
    // wl_keyboard.enter carries no application generation ID.
    last_surface: Option<W>,
}

impl<S, O, W> Default for DesktopFocusLease<S, O, W> {
    fn default() -> Self {
        Self {
            request: None,
            confirmed: false,
            next_generation: 0,
            last_surface: None,
        }
    }
}

#[allow(dead_code)] // Staged Core API, wired by the Integration lane.
impl<S: PartialEq, O: PartialEq, W: PartialEq + Clone> DesktopFocusLease<S, O, W> {
    /// Compatibility wrapper for the initial #367 contract. New integration
    /// must use request_at() and handle errors rather than ignoring them.
    pub(crate) fn request(
        &mut self, intent: DesktopFocusIntent, seat: S, output: O, surface: W,
    ) {
        let _ = self.request_at(intent, seat, output, surface, Instant::now());
    }

    /// Start a new explicitly user-initiated activation. Every new attempt
    /// cancels the previous grant before checking validity. A surface reused
    /// across consecutive generations is rejected: an old Enter could
    /// otherwise authorize the new gesture with no compositor round-trip.
    pub(crate) fn request_at(
        &mut self, intent: DesktopFocusIntent, seat: S, output: O,
        surface: W, now: Instant,
    ) -> Result<DesktopFocusTicket, DesktopFocusError> {
        self.cancel();
        if self.last_surface.as_ref() == Some(&surface) {
            return Err(DesktopFocusError::ReusedSurface);
        }
        let Some(deadline) = now.checked_add(DESKTOP_FOCUS_TIMEOUT) else {
            return Err(DesktopFocusError::ClockOverflow);
        };
        let Some(generation) = self.next_generation.checked_add(1) else {
            return Err(DesktopFocusError::GenerationExhausted);
        };
        self.next_generation = generation;
        self.last_surface = Some(surface.clone());
        let ticket = DesktopFocusTicket(generation);
        self.request = Some(DesktopFocusRequest {
            seat, output, surface, intent, ticket, deadline,
        });
        Ok(ticket)
    }

    pub(crate) fn phase(&self) -> DesktopFocusPhase {
        match (&self.request, self.confirmed) {
            (None, _) => DesktopFocusPhase::Idle,
            (Some(_), false) => DesktopFocusPhase::AwaitingCompositor,
            (Some(_), true) => DesktopFocusPhase::Confirmed,
        }
    }

    pub(crate) fn ticket(&self) -> Option<DesktopFocusTicket> {
        self.request.as_ref().map(|r| r.ticket)
    }

    /// Only pending acquisitions require a one-shot deadline; confirmed focus
    /// is revoked by genuine compositor events and explicit teardown.
    pub(crate) fn pending_deadline(&self) -> Option<Instant> {
        self.request.as_ref().filter(|_| !self.confirmed).map(|r| r.deadline)
    }

    /// Called at/after pending_deadline by integration's one-shot timer. It is
    /// safe to call redundantly, including after another focus was confirmed.
    pub(crate) fn expire_pending_at(&mut self, now: Instant) -> bool {
        if self.pending_deadline().is_some_and(|deadline| now >= deadline) {
            self.cancel();
            true
        } else {
            false
        }
    }

    /// Returns true *only* on the first matching real wl_keyboard.enter.
    pub(crate) fn compositor_enter(&mut self, seat: &S, surface: &W) -> bool {
        self.compositor_enter_at(seat, surface, Instant::now())
    }

    /// The event time is injectable for deterministic compositor-order tests.
    /// An Enter for a different RicePlate surface on the owning keyboard seat
    /// revokes the lease. An unrelated seat cannot revoke or confirm it.
    pub(crate) fn compositor_enter_at(
        &mut self, seat: &S, surface: &W, now: Instant,
    ) -> bool {
        if self.expire_pending_at(now) {
            return false;
        }
        let Some(target) = &self.request else { return false; };
        if &target.seat != seat { return false; }
        if &target.surface != surface {
            self.cancel();
            return false;
        }
        if self.confirmed { return false; }
        self.confirmed = true;
        true
    }

    pub(crate) fn compositor_leave(&mut self, seat: &S, surface: &W) -> bool {
        if self.request.as_ref().is_some_and(|target|
            &target.seat == seat && &target.surface == surface) {
            self.cancel();
            return true;
        }
        false
    }

    /// A key or repeat requires the ticket from the original gesture as well
    /// as a matching seat/surface and a compositor-confirmed Enter. Tickets
    /// prevent UI actions queued for a previous popup being replayed later.
    pub(crate) fn can_dispatch_ticket(
        &self, ticket: DesktopFocusTicket, seat: &S, surface: &W,
    ) -> bool {
        self.confirmed && self.request.as_ref().is_some_and(|target|
            target.ticket == ticket && &target.seat == seat && &target.surface == surface)
    }

    /// Legacy surface-only check; integration should use can_dispatch_ticket()
    /// for queued keys and keyboard repeats.
    pub(crate) fn can_dispatch(&self, seat: &S, surface: &W) -> bool {
        self.ticket().is_some_and(|ticket| self.can_dispatch_ticket(ticket, seat, surface))
    }

    pub(crate) fn intent(&self) -> Option<DesktopFocusIntent> {
        self.request.as_ref().map(|target| target.intent)
    }

    pub(crate) fn surface_closed(&mut self, surface: &W) -> bool {
        self.revoke_when(|target| &target.surface == surface)
    }

    pub(crate) fn output_removed(&mut self, output: &O) -> bool {
        self.revoke_when(|target| &target.output == output)
    }

    pub(crate) fn seat_removed(&mut self, seat: &S) -> bool {
        self.revoke_when(|target| &target.seat == seat)
    }

    fn revoke_when(&mut self, condition: impl FnOnce(&DesktopFocusRequest<S, O, W>) -> bool) -> bool {
        if self.request.as_ref().is_some_and(condition) {
            self.cancel();
            true
        } else {
            false
        }
    }

    pub(crate) fn cancel(&mut self) {
        self.request = None;
        self.confirmed = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recipe::Widget;

    #[test]
    fn desktop_focus_is_not_fabricated_by_a_pointer_selection() {
        let mut focus = DesktopFocusLease::default();
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        assert!(!focus.compositor_enter(&"seat-a", &"icon"));
        focus.request(DesktopFocusIntent::PointerSelection,
                      "seat-a", "HDMI-A-1", "temporary-focus-surface");
        assert_eq!(focus.phase(), DesktopFocusPhase::AwaitingCompositor);
        assert!(!focus.can_dispatch(&"seat-a", &"temporary-focus-surface"));
        assert!(!focus.compositor_enter(&"seat-b", &"temporary-focus-surface"));
        assert_eq!(focus.phase(), DesktopFocusPhase::AwaitingCompositor);
        assert!(focus.compositor_enter(&"seat-a", &"temporary-focus-surface"));
        assert_eq!(focus.phase(), DesktopFocusPhase::Confirmed);
        assert!(focus.can_dispatch(&"seat-a", &"temporary-focus-surface"));
        assert!(!focus.can_dispatch(&"seat-b", &"temporary-focus-surface"));
        assert!(!focus.can_dispatch(&"seat-a", &"another-app"));
    }

    #[test]
    fn another_riceplate_surface_enter_cancels_pending_focus() {
        let mut focus = DesktopFocusLease::default();
        focus.request(DesktopFocusIntent::KeyboardNavigation, 1, 10, 100);
        assert!(!focus.compositor_enter(&1, &101));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        assert!(!focus.compositor_enter(&1, &100),
                "stale compositor Enter cannot revive a cancelled request");
    }

    #[test]
    fn keyboard_leave_revokes_access_until_a_new_gesture_and_enter() {
        let mut focus = DesktopFocusLease::default();
        focus.request(DesktopFocusIntent::PointerSelection, 1, 10, 100);
        assert!(focus.compositor_enter(&1, &100));
        assert!(!focus.compositor_leave(&2, &100));
        assert!(focus.can_dispatch(&1, &100));
        assert!(focus.compositor_leave(&1, &100));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        assert!(!focus.can_dispatch(&1, &100));
        assert!(!focus.compositor_enter(&1, &100));
        focus.request(DesktopFocusIntent::PointerSelection, 1, 10, 200);
        assert!(focus.compositor_enter(&1, &200));
        assert!(!focus.can_dispatch(&1, &100));
    }

    #[test]
    fn removing_the_target_output_seat_or_surface_revokes_focus() {
        let mut focus = DesktopFocusLease::default();
        focus.request(DesktopFocusIntent::PointerSelection,
                      "seat-a", "DP-1", "surface-a");
        assert!(!focus.output_removed(&"HDMI-A-1"));
        assert!(!focus.seat_removed(&"seat-b"));
        assert!(!focus.surface_closed(&"other-surface"));
        assert!(focus.compositor_enter(&"seat-a", &"surface-a"));
        assert!(focus.output_removed(&"DP-1"));
        assert!(!focus.can_dispatch(&"seat-a", &"surface-a"));
        focus.request(DesktopFocusIntent::AssistiveAction,
                      "seat-a", "DP-1", "surface-b");
        assert!(focus.seat_removed(&"seat-a"));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        focus.request(DesktopFocusIntent::KeyboardNavigation,
                      "seat-a", "DP-1", "surface-c");
        assert!(focus.surface_closed(&"surface-c"));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
    }

    #[test]
    fn popup_lifecycle_requires_fresh_compositor_confirmation() {
        let mut focus = DesktopFocusLease::default();
        focus.request(DesktopFocusIntent::PointerSelection, 1, 10, 100);
        assert_eq!(focus.intent(), Some(DesktopFocusIntent::PointerSelection));
        assert!(focus.compositor_enter(&1, &100));
        focus.cancel(); // Escape / popup teardown returns keyboard to normal clients.
        assert!(!focus.compositor_leave(&1, &100));
        assert!(!focus.can_dispatch(&1, &100));
        focus.request(DesktopFocusIntent::PointerSelection, 1, 10, 101);
        assert!(!focus.can_dispatch(&1, &101));
        assert!(focus.compositor_enter(&1, &101));
        assert!(focus.can_dispatch(&1, &101));
        focus.cancel();
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
    }

    #[test]
    fn focus_timeout_never_grants_late_keyboard_enter() {
        let now = Instant::now();
        let mut focus = DesktopFocusLease::default();
        let ticket = focus.request_at(DesktopFocusIntent::PointerSelection,
            "seat", "DP-1", "temporary-1", now).unwrap();
        assert_eq!(focus.pending_deadline(), Some(now + DESKTOP_FOCUS_TIMEOUT));
        assert!(!focus.expire_pending_at(now + DESKTOP_FOCUS_TIMEOUT - Duration::from_nanos(1)));
        assert_eq!(focus.phase(), DesktopFocusPhase::AwaitingCompositor);
        assert!(!focus.compositor_enter_at(&"seat", &"temporary-1",
            now + DESKTOP_FOCUS_TIMEOUT));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        assert!(!focus.can_dispatch_ticket(ticket, &"seat", &"temporary-1"));
        assert!(!focus.compositor_enter(&"seat", &"temporary-1"));
    }

    #[test]
    fn consecutive_activation_rejects_reused_surface_and_old_enter() {
        let now = Instant::now();
        let mut focus = DesktopFocusLease::default();
        let first = focus.request_at(DesktopFocusIntent::PointerSelection,
            1, 2, 10, now).unwrap();
        assert!(focus.compositor_enter_at(&1, &10, now));
        assert!(focus.can_dispatch_ticket(first, &1, &10));
        assert_eq!(focus.request_at(DesktopFocusIntent::PointerSelection,
            1, 2, 10, now), Err(DesktopFocusError::ReusedSurface));
        assert_eq!(focus.phase(), DesktopFocusPhase::Idle);
        assert!(!focus.compositor_enter_at(&1, &10, now));
        let second = focus.request_at(DesktopFocusIntent::KeyboardNavigation,
            1, 2, 11, now).unwrap();
        assert_ne!(first, second);
        assert!(!focus.can_dispatch_ticket(first, &1, &10));
        assert!(focus.compositor_enter_at(&1, &11, now));
        assert!(focus.can_dispatch_ticket(second, &1, &11));
        assert!(!focus.can_dispatch_ticket(first, &1, &11));
    }

    #[test]
    fn wrong_seat_and_stale_leave_do_not_revoke_new_target() {
        let now = Instant::now();
        let mut focus = DesktopFocusLease::default();
        let _ = focus.request_at(DesktopFocusIntent::PointerSelection,
            5, 1, 100, now).unwrap();
        assert!(focus.compositor_enter_at(&5, &100, now));
        let next = focus.request_at(DesktopFocusIntent::PointerSelection,
            5, 2, 101, now).unwrap();
        assert!(!focus.compositor_leave(&5, &100));
        assert!(!focus.compositor_enter_at(&6, &101, now));
        assert_eq!(focus.phase(), DesktopFocusPhase::AwaitingCompositor);
        assert!(focus.compositor_enter_at(&5, &101, now));
        assert!(!focus.output_removed(&1));
        assert!(!focus.seat_removed(&6));
        assert!(focus.can_dispatch_ticket(next, &5, &101));
        assert!(focus.output_removed(&2));
        assert!(!focus.can_dispatch_ticket(next, &5, &101));
        assert_eq!(focus.pending_deadline(), None);
    }

    #[test]
    fn confirmed_focus_is_not_expired_by_acquisition_deadline() {
        let now = Instant::now();
        let mut focus = DesktopFocusLease::default();
        let ticket = focus.request_at(DesktopFocusIntent::AssistiveAction,
            1, 1, 42, now).unwrap();
        assert!(focus.compositor_enter_at(&1, &42,
            now + DESKTOP_FOCUS_TIMEOUT - Duration::from_millis(1)));
        assert_eq!(focus.pending_deadline(), None);
        assert!(!focus.expire_pending_at(now + DESKTOP_FOCUS_TIMEOUT * 10));
        assert!(focus.can_dispatch_ticket(ticket, &1, &42));
        assert!(focus.compositor_leave(&1, &42));
        assert!(!focus.can_dispatch_ticket(ticket, &1, &42));
    }

    #[test]
    fn standalone_focus_smoke_is_valid_posix_shell() {
        // Syntax-only: actual labwc compositor evidence remains a separate
        // acceptance step, and must never be inferred from this test.
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../scripts/smoke_riceplate_desktop_focus.sh",
        );
        let result = std::process::Command::new("sh")
            .arg("-n")
            .arg(path)
            .output()
            .expect("POSIX shell is required by the Linux desktop test suite");
        assert!(result.status.success(), "focus smoke syntax: {}",
            String::from_utf8_lossy(&result.stderr));
    }

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
