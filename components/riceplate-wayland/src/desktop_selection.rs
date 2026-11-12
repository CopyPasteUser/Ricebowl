//! Opt-in XP Luna shortcut selection and double-click policy.
//! Pure input state: no filesystem, compositor handles, timers or polling.
use std::time::{Duration, Instant};

pub const DOUBLE_CLICK_INTERVAL: Duration = Duration::from_millis(650);
const MAX_DRIFT: f64 = 8.0;
#[derive(Debug, Clone, Copy)]
struct Click { icon: usize, at: Instant, point: (f64, f64) }

#[derive(Debug, Default)]
pub struct Selection {
    selected: Option<usize>,
    last: Option<Click>,
}
impl Selection {
    pub fn selected(&self) -> Option<usize> { self.selected }
    pub fn select(&mut self, icon: usize) -> Option<usize> {
        let prior = self.selected.replace(icon);
        if prior != Some(icon) { self.last = None; }
        prior
    }
    pub fn cancel(&mut self) { self.last = None; }
    pub fn clear(&mut self) -> Option<usize> {
        self.cancel();
        self.selected.take()
    }
    /// Use layer indices rather than recipe IDs: repeated icons on two
    /// displays must never form a double-click pair across monitors.
    pub fn release(&mut self, icon: usize, point: (f64, f64), now: Instant) -> bool {
        if !point.0.is_finite() || !point.1.is_finite()
            || !(0.0..f64::from(crate::recipe::ICON_WIDTH)).contains(&point.0)
            || !(0.0..f64::from(crate::recipe::ICON_HEIGHT)).contains(&point.1) {
            self.cancel();
            return false;
        }
        // Monotonic clocks should not move backwards, but reject a stale
        // synthetic/out-of-order timestamp rather than keep an old click.
        if self.last.is_some_and(|prev| now < prev.at) {
            self.cancel();
            return false;
        }
        let activate = self.last.is_some_and(|prev| prev.icon == icon
            && (prev.point.0 - point.0).abs() <= MAX_DRIFT
            && (prev.point.1 - point.1).abs() <= MAX_DRIFT
            && now.checked_duration_since(prev.at)
                .is_some_and(|delta| delta <= DOUBLE_CLICK_INTERVAL));
        self.last = if activate { None } else { Some(Click { icon, at: now, point }) };
        activate
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn first_click_selects_second_activates_and_third_is_only_selection() {
        let mut state = Selection::default();
        let t = Instant::now();
        assert_eq!(state.select(0), None);
        assert!(!state.release(0, (20.0, 30.0), t));
        assert_eq!(state.selected(), Some(0));
        assert!(state.release(0, (23.0, 31.0), t + Duration::from_millis(600)));
        assert!(!state.release(0, (23.0, 31.0), t + Duration::from_millis(610)));
    }
    #[test]
    fn monitor_changes_and_expiration_do_not_activate() {
        let mut state = Selection::default();
        let t = Instant::now();
        state.select(0);
        assert!(!state.release(0, (20.0, 30.0), t));
        state.select(8);
        assert!(!state.release(8, (20.0, 30.0), t + Duration::from_millis(20)));
        assert!(!state.release(8, (20.0, 30.0), t + Duration::from_millis(671)));
        assert!(state.release(8, (20.0, 30.0), t + Duration::from_millis(690)));
        assert_eq!(state.clear(), Some(8));
        assert_eq!(state.selected(), None);
    }
    #[test]
    fn drag_and_mismatched_pointer_coordinates_are_safe() {
        let mut state = Selection::default();
        let t = Instant::now();
        state.select(2);
        assert!(!state.release(2, (20.0, 30.0), t));
        assert!(!state.release(2, (50.0, 30.0), t + Duration::from_millis(50)));
        state.cancel();
        assert!(!state.release(2, (50.0, 30.0), t + Duration::from_millis(60)));
        for point in [(-1.0, 30.0), (104.0, 30.0), (20.0, 88.0),
                      (f64::NAN, 1.0), (f64::INFINITY, 1.0)] {
            assert!(!state.release(2, point, t + Duration::from_millis(70)));
        }
        assert!(!state.release(2, (50.0, 30.0), t + Duration::from_millis(80)));
    }
    #[test]
    fn order_and_timing_are_bounded() {
        let mut state = Selection::default();
        let t = Instant::now();
        state.select(1);
        assert!(!state.release(1, (8.0, 8.0), t));
        assert!(!state.release(1, (8.0, 8.0), t + Duration::from_millis(651)));
        assert!(!state.release(1, (8.0, 8.0), t)); // out of order
        assert!(!state.release(1, (8.0, 8.0), t + Duration::from_millis(651)));
        assert!(state.release(1, (8.0, 8.0), t + Duration::from_millis(660)));
    }
}
