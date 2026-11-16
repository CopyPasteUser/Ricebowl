//! Coalesce a transient wl_surface.leave -> wl_surface.enter handoff.
//!
//! Wayland may report the *same* primary panel leaving and re-entering its
//! output in a single protocol burst. Rebuilding a temporary full mirror,
//! desktop icons and menu in between can steal compositor keyboard focus.
//! True output destruction bypasses this grace and synchronizes immediately.

use std::time::{Duration, Instant};

/// Short enough for a real unbound panel to recover promptly; not a polling
/// interval. The Wayland event loop arms a single wake only when necessary.
const PRIMARY_HANDOFF_GRACE: Duration = Duration::from_millis(80);

#[derive(Debug, Default)]
pub(crate) struct PrimaryOutputHandoff {
    deadline: Option<Instant>,
}

impl PrimaryOutputHandoff {
    /// A repeated Leave must never extend the grace indefinitely.
    pub(crate) fn left(&mut self, now: Instant) {
        if self.deadline.is_none() {
            self.deadline = Some(now.checked_add(PRIMARY_HANDOFF_GRACE).unwrap_or(now));
        }
    }

    /// A matching Enter or actual output destruction resolves the handoff.
    pub(crate) fn clear(&mut self) {
        self.deadline = None;
    }

    pub(crate) fn deadline(&self) -> Option<Instant> {
        self.deadline
    }

    /// Allow exactly one fallback synchronization if no Enter arrives.
    pub(crate) fn take_due(&mut self, now: Instant) -> bool {
        if self.deadline.is_some_and(|at| now >= at) {
            self.clear();
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paired_leave_enter_never_builds_a_transient_mirror() {
        let now = Instant::now();
        let mut handoff = PrimaryOutputHandoff::default();
        assert_eq!(handoff.deadline(), None);
        handoff.left(now);
        assert_eq!(handoff.deadline(), Some(now + PRIMARY_HANDOFF_GRACE));
        handoff.clear(); // Genuine compositor Enter, even for the same output.
        assert_eq!(handoff.deadline(), None);
        assert!(!handoff.take_due(now + Duration::from_secs(1)));
    }

    #[test]
    fn an_unbound_primary_gets_exactly_one_bounded_fallback() {
        let now = Instant::now();
        let mut handoff = PrimaryOutputHandoff::default();
        handoff.left(now);
        assert!(!handoff.take_due(now + PRIMARY_HANDOFF_GRACE - Duration::from_nanos(1)));
        assert!(handoff.take_due(now + PRIMARY_HANDOFF_GRACE));
        assert!(!handoff.take_due(now + PRIMARY_HANDOFF_GRACE + Duration::from_secs(1)));
        assert_eq!(handoff.deadline(), None);
    }

    #[test]
    fn repeated_leave_cannot_starve_recovery_and_destroy_can_bypass_grace() {
        let now = Instant::now();
        let mut handoff = PrimaryOutputHandoff::default();
        handoff.left(now);
        handoff.left(now + PRIMARY_HANDOFF_GRACE / 2);
        assert_eq!(handoff.deadline(), Some(now + PRIMARY_HANDOFF_GRACE));
        handoff.clear(); // Actual OutputHandler::output_destroyed path.
        assert!(!handoff.take_due(now + PRIMARY_HANDOFF_GRACE));
        handoff.left(now + Duration::from_secs(1));
        assert!(handoff.take_due(now + Duration::from_secs(1) + PRIMARY_HANDOFF_GRACE));
    }
}
