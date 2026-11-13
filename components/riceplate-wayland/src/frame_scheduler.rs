//! Pure, per-surface Wayland frame lifecycle.
//!
//! A compositor frame callback is a throttle, not a repaint request. Multiple
//! state changes during an outstanding callback coalesce into one dirty frame.
//! Busy SHM buffers are retried at the *next callback* without busy looping.
//! Keep this independent of a particular recipe or layer-shell role.

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct FrameGate {
    pending: bool,
    dirty: bool,
    stats: FrameStats,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct FrameStats {
    pub invalidations: u64,
    pub coalesced: u64,
    pub commits: u64,
    pub busy_retries: u64,
}

impl FrameGate {
    /// Mark the attached surface as outdated. Return true only if there is
    /// no outstanding compositor frame callback and rendering may start now.
    pub(crate) fn invalidate(&mut self) -> bool {
        self.stats.invalidations = self.stats.invalidations.saturating_add(1);
        if self.pending || self.dirty {
            self.stats.coalesced = self.stats.coalesced.saturating_add(1);
        }
        self.dirty = true;
        !self.pending
    }

    /// A callback belongs to exactly one wl_surface. It unblocks at most one
    /// paint, and should not generate a new frame if no state changed.
    pub(crate) fn frame_ready(&mut self) -> bool {
        self.pending = false;
        self.dirty
    }

    /// A successful buffer attachment, damage and frame request were committed.
    pub(crate) fn submitted(&mut self) {
        self.pending = true;
        self.dirty = false;
        self.stats.commits = self.stats.commits.saturating_add(1);
    }

    /// The SHM pool has no free slot: arrange one callback for the retry.
    /// Crucially do not clear dirty, or the compositor would stop redrawing.
    pub(crate) fn buffer_busy(&mut self) {
        self.pending = true;
        self.dirty = true;
        self.stats.busy_retries = self.stats.busy_retries.saturating_add(1);
    }

    pub(crate) fn stats(&self) -> FrameStats { self.stats }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repeated_invalidations_coalesce_while_a_frame_is_outstanding() {
        let mut gate = FrameGate::default();
        assert!(gate.invalidate());
        gate.submitted();
        for _ in 0..10_000 {
            assert!(!gate.invalidate());
        }
        assert!(gate.frame_ready());
        gate.submitted();
        assert!(!gate.frame_ready());
        assert_eq!(gate.stats().invalidations, 10_001);
        assert_eq!(gate.stats().commits, 2);
        assert_eq!(gate.stats().coalesced, 10_000);
    }

    #[test]
    fn busy_shm_buffers_retry_once_per_frame_not_in_a_spin_loop() {
        let mut gate = FrameGate::default();
        assert!(gate.invalidate());
        gate.buffer_busy();
        assert!(!gate.invalidate());
        assert!(gate.frame_ready());
        gate.buffer_busy();
        assert!(gate.frame_ready());
        gate.submitted();
        assert!(!gate.frame_ready());
        assert_eq!(gate.stats().busy_retries, 2);
        assert_eq!(gate.stats().commits, 1);
    }

    #[test]
    fn frame_callback_without_dirty_does_not_repaint() {
        let mut gate = FrameGate::default();
        gate.submitted(); // initial Configure paint
        assert!(!gate.frame_ready());
        assert!(gate.invalidate());
        assert!(gate.frame_ready());
        // A spurious late callback cannot remove a pending repaint.
        assert!(gate.frame_ready());
    }

    #[test]
    fn independent_surfaces_and_lost_output_have_independent_state() {
        let mut primary = FrameGate::default();
        let mut secondary = FrameGate::default();
        assert!(primary.invalidate());
        primary.submitted();
        assert!(secondary.invalidate());
        secondary.submitted();
        assert!(!primary.invalidate());
        assert!(!secondary.frame_ready());
        assert!(primary.frame_ready());
        assert_eq!(primary.stats().commits, 1);
        assert_eq!(secondary.stats().commits, 1);
        let hotplugged = FrameGate::default(); // destroyed mirror is dropped
        assert!(hotplugged.stats() == FrameStats::default());
    }
}
