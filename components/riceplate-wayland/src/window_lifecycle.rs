//! Compositor-handle-based Show Desktop transaction.
//!
//! Only windows that were ready and not minimized at activation are restored.
//! Capturing an empty desktop must still count as an active transaction: a
//! window opened afterwards must never be implicitly minimized or restored.
//! All proxy operations are performed by the caller, after live-handle checks.

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ShowDesktopAction<H> {
    Minimize(H),
    Restore(H),
}

#[derive(Debug)]
pub(crate) struct ShowDesktop<H> {
    active: bool,
    restore: Vec<H>,
}

impl<H> Default for ShowDesktop<H> {
    fn default() -> Self {
        Self { active: false, restore: Vec::new() }
    }
}

impl<H: Clone + PartialEq> ShowDesktop<H> {
    pub(crate) fn toggle(
        &mut self,
        windows: impl IntoIterator<Item = (H, bool, bool)>,
    ) -> Vec<ShowDesktopAction<H>> {
        if self.active {
            self.active = false;
            return std::mem::take(&mut self.restore)
                .into_iter().map(ShowDesktopAction::Restore).collect();
        }
        self.active = true;
        self.restore.clear();
        for (handle, ready, minimized) in windows {
            if ready && !minimized && !self.restore.contains(&handle) {
                self.restore.push(handle);
            }
        }
        self.restore.iter().cloned()
            .map(ShowDesktopAction::Minimize).collect()
    }

    pub(crate) fn closed(&mut self, handle: &H) {
        self.restore.retain(|existing| existing != handle);
    }

    pub(crate) fn reset(&mut self) {
        self.restore.clear();
        self.active = false;
    }

    #[cfg(test)]
    pub(crate) fn active(&self) -> bool { self.active }
}

// Pending taskbar intent must not be confused with a compositor-confirmed
// foreign-toplevel state. No polling or resident timer: stale requests expire
// only when the next click arrives.
use std::time::{Duration, Instant};

const TASKBAR_REQUEST_GRACE: Duration = Duration::from_millis(1200);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum TaskbarAction { Minimize, Restore, Activate }

#[derive(Debug)]
struct PendingTaskbarRequest<H> {
    handle: H,
    minimized: bool,
    issued_at: Instant,
}

#[derive(Debug)]
pub(crate) struct TaskbarWindowActions<H> {
    pending: Vec<PendingTaskbarRequest<H>>,
}

impl<H> Default for TaskbarWindowActions<H> {
    fn default() -> Self { Self { pending: Vec::new() } }
}

impl<H: Clone + PartialEq> TaskbarWindowActions<H> {
    /// A second click reverses the outstanding request even when State/Done
    /// has not arrived yet. The caller invokes actual Wayland proxy methods.
    pub(crate) fn click(
        &mut self, handle: &H, active_singleton: bool,
        observed_minimized: bool, now: Instant,
    ) -> TaskbarAction {
        self.pending.retain(|request|
            now.saturating_duration_since(request.issued_at) < TASKBAR_REQUEST_GRACE);
        if let Some(request) = self.pending.iter_mut()
            .find(|request| request.handle == *handle)
        {
            request.minimized = !request.minimized;
            request.issued_at = now;
            return if request.minimized { TaskbarAction::Minimize }
                   else { TaskbarAction::Restore };
        }
        let requested = if observed_minimized { Some(false) }
            else if active_singleton { Some(true) }
            else { None };
        match requested {
            Some(minimized) => {
                self.pending.push(PendingTaskbarRequest {
                    handle: handle.clone(), minimized, issued_at: now,
                });
                if minimized { TaskbarAction::Minimize } else { TaskbarAction::Restore }
            }
            None => TaskbarAction::Activate,
        }
    }

    /// Use the final State at Done, never an intermediate State notification.
    pub(crate) fn confirmed(&mut self, handle: &H, minimized: bool) {
        self.pending.retain(|request|
            request.handle != *handle || request.minimized != minimized);
    }

    pub(crate) fn closed(&mut self, handle: &H) {
        self.pending.retain(|request| request.handle != *handle);
    }

    pub(crate) fn reset(&mut self) { self.pending.clear(); }
}

#[cfg(test)]
mod taskbar_window_tests {
    use super::*;
    use TaskbarAction::*;

    #[test]
    fn rapid_double_click_reverses_pending_intent_without_state_event() {
        let now = Instant::now();
        let mut actions = TaskbarWindowActions::<u64>::default();
        assert_eq!(actions.click(&10, true, false, now), Minimize);
        assert_eq!(actions.click(&10, true, false, now), Restore);
        actions.confirmed(&10, true); // first click arrives late
        assert_eq!(actions.click(&10, true, true, now), Minimize);
        actions.confirmed(&10, true);
        assert_eq!(actions.click(&10, false, true, now), Restore);
        actions.confirmed(&10, false);
        assert_eq!(actions.click(&10, true, false, now), Minimize);
    }

    #[test]
    fn inactive_visible_window_activates_without_unnecessary_restore() {
        let now = Instant::now();
        let mut actions = TaskbarWindowActions::<u8>::default();
        assert_eq!(actions.click(&1, false, false, now), Activate);
        assert_eq!(actions.click(&1, false, true, now), Restore);
        assert_eq!(actions.click(&2, true, false, now), Minimize);
        actions.confirmed(&1, false); // unrelated window
        assert_eq!(actions.click(&2, true, false, now), Restore);
    }

    #[test]
    fn closing_or_restarting_registry_drops_stale_intent() {
        let now = Instant::now();
        let mut actions = TaskbarWindowActions::<u32>::default();
        assert_eq!(actions.click(&4, true, false, now), Minimize);
        actions.closed(&4);
        assert_eq!(actions.click(&4, true, false, now), Minimize);
        actions.reset();
        assert_eq!(actions.click(&4, true, false, now), Minimize);
    }

    #[test]
    fn refused_request_expires_on_input_without_polling() {
        let now = Instant::now();
        let mut actions = TaskbarWindowActions::<u32>::default();
        assert_eq!(actions.click(&9, true, false, now), Minimize);
        assert_eq!(actions.click(&9, true, false, now + TASKBAR_REQUEST_GRACE), Minimize);
    }
}

#[cfg(test)]
mod tests {
    use super::{ShowDesktop, ShowDesktopAction as Action};

    #[test]
    fn restores_only_windows_minimized_by_this_transaction() {
        let mut desktop = ShowDesktop::<u32>::default();
        assert_eq!(desktop.toggle([(1, true, false), (2, true, true),
            (3, false, false), (4, true, false)]),
            [Action::Minimize(1), Action::Minimize(4)]);
        // A rapid double-toggle occurs before any compositor State event.
        assert_eq!(desktop.toggle([(1, true, false), (2, true, true)]),
            [Action::Restore(1), Action::Restore(4)]);
        assert!(!desktop.active());
    }

    #[test]
    fn an_empty_transaction_stays_active_until_toggled_again() {
        let mut desktop = ShowDesktop::<u32>::default();
        assert!(desktop.toggle([(1, true, true)]).is_empty());
        assert!(desktop.active());
        // Window 2 opened after Show Desktop: do not minimize/restore it.
        assert!(desktop.toggle([(1, true, true), (2, true, false)]).is_empty());
        assert!(!desktop.active());
        assert_eq!(desktop.toggle([(2, true, false)]),
            [Action::Minimize(2)]);
    }

    #[test]
    fn closed_windows_are_excluded_even_if_a_new_proxy_arrives() {
        let mut desktop = ShowDesktop::<u64>::default();
        assert_eq!(desktop.toggle([(101, true, false), (102, true, false)]),
            [Action::Minimize(101), Action::Minimize(102)]);
        desktop.closed(&101);
        assert_eq!(desktop.toggle([(102, true, true), (103, true, false)]),
            [Action::Restore(102)]);
    }

    #[test]
    fn manager_reset_discards_all_stale_proxy_ids() {
        let mut desktop = ShowDesktop::<u64>::default();
        desktop.toggle([(7, true, false)]);
        desktop.reset();
        assert!(!desktop.active());
        assert!(desktop.toggle([(7, true, true)]).is_empty());
        assert!(desktop.active());
    }

    #[test]
    fn duplicate_handles_never_generate_duplicate_minimize_requests() {
        let mut desktop = ShowDesktop::<u8>::default();
        assert_eq!(desktop.toggle([(1, true, false), (1, true, false)]),
            [Action::Minimize(1)]);
        assert_eq!(desktop.toggle([]), [Action::Restore(1)]);
    }
}
