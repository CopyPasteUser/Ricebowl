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
