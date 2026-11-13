//! Opt-in XP Luna desktop selection and double-click policy.
//! Pure, bounded in-memory state: no compositor handles, services or persistence.
//! Indices identify real icon layers, not recipe IDs repeated across outputs.
use std::{collections::BTreeSet, time::{Duration, Instant}};

pub const DOUBLE_CLICK_INTERVAL: Duration = Duration::from_millis(650);
const MAX_DRIFT: f64 = 8.0;

/// Bounded, Unicode-safe shortcut search. Only the caller's visible
/// shortcuts on a single wl_output are ever eligible for selection.
const TYPE_TIMEOUT: Duration = Duration::from_millis(1200);
const MAX_TYPE_CHARS: usize = 32;

#[derive(Debug, Default)]
pub struct TypeSelect {
    prefix: String,
    last: Option<Instant>,
}

impl TypeSelect {
    pub fn reset(&mut self) {
        self.prefix.clear();
        self.last = None;
    }

    /// A repeated initial letter cycles eligible icons. Longer prefixes
    /// retain the same match. Never launch an action from an ordinary key.
    pub fn feed(&mut self, labels: &[Option<&str>], current: usize,
                typed: &str, now: Instant) -> Option<usize> {
        if typed.chars().count() != 1 || !typed.chars().all(char::is_alphanumeric)
            || labels.is_empty() || current >= labels.len() { return None; }
        if self.last.is_none_or(|previous| now.checked_duration_since(previous)
            .is_none_or(|elapsed| elapsed > TYPE_TIMEOUT)) {
            self.reset();
        }
        let single = typed.to_lowercase();
        let extended = format!("{}{}", self.prefix, single);
        let match_from = |query: &str, include_current: bool| -> Option<usize> {
            (0..labels.len()).find_map(|step| {
                let start = usize::from(!include_current);
                let index = (current + start + step) % labels.len();
                labels[index].filter(|label|
                    label.to_lowercase().starts_with(query)).map(|_| index)
            })
        };
        let extended_hit = (extended.chars().count() <= MAX_TYPE_CHARS)
            .then(|| match_from(&extended, !self.prefix.is_empty())).flatten();
        let (query, selected) = if let Some(index) = extended_hit {
            (extended, index)
        } else {
            (single.clone(), match_from(&single, false)?)
        };
        self.prefix = query;
        self.last = Some(now);
        Some(selected)
    }
}


#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode { Replace, Toggle, Range }

#[derive(Debug, Clone, Copy)]
struct Click { icon: usize, at: Instant, point: (f64, f64) }

#[derive(Debug, Default)]
pub struct Selection {
    selected: BTreeSet<usize>,
    anchor: Option<usize>,
    last: Option<Click>,
}

impl Selection {
    /// Keyboard-range anchor; kept for existing single-selection callers.
    pub fn selected(&self) -> Option<usize> { self.anchor }

    pub fn is_selected(&self, icon: usize) -> bool { self.selected.contains(&icon) }

    pub fn count(&self) -> usize { self.selected.len() }

    /// Previous anchor of a normal single click, for backwards compatibility.
    pub fn select(&mut self, icon: usize) -> Option<usize> {
        let old = self.anchor;
        if self.selected.len() != 1 || !self.selected.contains(&icon) {
            self.last = None;
        }
        self.selected.clear();
        self.selected.insert(icon);
        self.anchor = Some(icon);
        old
    }

    pub fn cancel(&mut self) { self.last = None; }

    pub fn clear(&mut self) -> Option<usize> {
        let anchor = self.anchor;
        self.clear_all();
        anchor
    }

    pub fn clear_all(&mut self) -> Vec<usize> {
        let removed = self.selected.iter().copied().collect();
        self.selected.clear();
        self.anchor = None;
        self.cancel();
        removed
    }

    /// Every operation is restricted to visible icon layers on the SAME
    /// wl_output as the clicked icon. A synthetic or hidden index is ignored.
    /// Returns only changed layer indices so rendering stays event-driven.
    pub fn choose(&mut self, icon: usize, mode: Mode, peers: &[bool]) -> Vec<usize> {
        if !peers.get(icon).copied().unwrap_or(false) { return Vec::new(); }
        let before = self.selected.clone();
        self.selected.retain(|old| peers.get(*old).copied().unwrap_or(false));
        if self.anchor.is_some_and(|old| !peers.get(old).copied().unwrap_or(false)) {
            self.anchor = None;
        }
        match mode {
            Mode::Replace => { self.select(icon); }
            Mode::Toggle => {
                self.cancel();
                if !self.selected.remove(&icon) {
                    self.selected.insert(icon);
                }
                self.anchor = Some(icon);
            }
            Mode::Range => {
                self.cancel();
                let start = self.anchor.filter(|old| peers.get(*old).copied().unwrap_or(false))
                    .unwrap_or(icon);
                self.selected.clear();
                for index in start.min(icon)..=start.max(icon) {
                    if peers[index] { self.selected.insert(index); }
                }
                self.anchor = Some(start);
            }
        }
        before.symmetric_difference(&self.selected).copied().collect()
    }

    /// Ctrl+A selects only shortcuts on the currently focused output.
    /// This is not a batch launch, file operation or cross-monitor selection.
    pub fn all_on_output(&mut self, peers: &[bool], anchor: usize) -> Vec<usize> {
        if !peers.get(anchor).copied().unwrap_or(false) { return Vec::new(); }
        let before = self.selected.clone();
        self.selected = peers.iter().enumerate()
            .filter_map(|(index, visible)| visible.then_some(index)).collect();
        self.anchor = Some(anchor);
        self.cancel();
        before.symmetric_difference(&self.selected).copied().collect()
    }

    /// Disconnect/reflow must never keep an invisible shortcut selected.
    pub fn retain_visible(&mut self, visible: &[bool]) -> Vec<usize> {
        let before = self.selected.clone();
        self.selected.retain(|index| visible.get(*index).copied().unwrap_or(false));
        if self.anchor.is_some_and(|index| !visible.get(index).copied().unwrap_or(false)) {
            self.anchor = self.selected.iter().next().copied();
        }
        if before != self.selected { self.cancel(); }
        before.difference(&self.selected).copied().collect()
    }

    /// A modified click cannot accidentally activate a shortcut. Only a
    /// single, currently selected icon is eligible for a double-click.
    pub fn release(&mut self, icon: usize, point: (f64, f64), now: Instant) -> bool {
        if self.selected.len() != 1 || !self.selected.contains(&icon)
            || !point.0.is_finite() || !point.1.is_finite()
            || !(0.0..f64::from(crate::recipe::ICON_WIDTH)).contains(&point.0)
            || !(0.0..f64::from(crate::recipe::ICON_HEIGHT)).contains(&point.1) {
            self.cancel();
            return false;
        }
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

    fn all(count: usize) -> Vec<bool> { vec![true; count] }

    #[test]
    fn type_to_select_filters_hidden_output_and_keeps_unicode_prefix() {
        let labels = [Some("My Computer"), Some("My Documents"), None,
                      Some("Programs"), Some("Pictures"), Some("Äpfel")];
        let mut search = TypeSelect::default();
        let now = Instant::now();
        assert_eq!(search.feed(&labels, 1, "P", now), Some(3));
        assert_eq!(search.feed(&labels, 3, "r", now + Duration::from_millis(100)), Some(3));
        assert_eq!(search.feed(&labels, 3, "o", now + Duration::from_millis(150)), Some(3));
        assert_eq!(search.feed(&labels, 3, "P", now + Duration::from_millis(1400)), Some(4));
        assert_eq!(search.feed(&labels, 4, "p", now + Duration::from_millis(1450)), Some(3));
        search.reset();
        assert_eq!(search.feed(&labels, 4, "ä", now + Duration::from_millis(1600)), Some(5));
        assert_eq!(search.feed(&labels, 0, "\n", now), None);
        assert_eq!(search.feed(&labels, 0, "ab", now), None);
        assert_eq!(search.feed(&labels, 0, " ", now), None);
        assert_eq!(search.feed(&labels, 0, "D", now), Some(1));
        assert_eq!(search.feed(&[None, None], 0, "D", now), None);
        assert_eq!(search.feed(&labels, 99, "D", now), None);
        assert_eq!(search.feed(&[], 0, "D", now), None);
    }

    #[test]
    fn type_to_select_stays_bounded_and_resets_clock() {
        let mut search = TypeSelect::default();
        let labels = [Some("abcdefghijklmnopqrstuvwxyz123456789")];
        let now = Instant::now();
        for (i, c) in "abcdefghijklmnopqrstuvwxyz123456789".chars().enumerate() {
            let _ = search.feed(&labels, 0, &c.to_string(),
                                now + Duration::from_millis(i as u64 * 10));
            assert!(search.prefix.chars().count() <= MAX_TYPE_CHARS);
        }
        let past = now - Duration::from_millis(1);
        assert_eq!(search.feed(&labels, 0, "a", past), Some(0));
        assert_eq!(search.prefix, "a");
    }


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
    fn ctrl_toggle_and_shift_range_are_bounded_and_never_activate() {
        let mut state = Selection::default();
        let t = Instant::now();
        let peers = all(6);
        assert_eq!(state.choose(1, Mode::Replace, &peers), vec![1]);
        assert_eq!(state.choose(3, Mode::Toggle, &peers), vec![3]);
        assert_eq!(state.count(), 2);
        assert!(!state.release(3, (20.0, 30.0), t));
        assert_eq!(state.choose(5, Mode::Range, &peers), vec![1, 4, 5]);
        // Anchor remains index 3; range includes 3, 4, 5.
        assert_eq!(state.selected(), Some(3));
        assert_eq!(state.count(), 3);
        assert_eq!(state.choose(4, Mode::Toggle, &peers), vec![4]);
        assert_eq!(state.count(), 2);
        assert_eq!(state.choose(3, Mode::Toggle, &peers), vec![3]);
        assert_eq!(state.count(), 1);
        assert!(!state.release(5, (20.0, 30.0), t + Duration::from_millis(10)));
    }

    #[test]
    fn ctrl_a_and_cross_output_clicks_do_not_leak_selection() {
        let mut state = Selection::default();
        let first = [true, true, false, false, false, false];
        let second = [false, false, true, true, false, false];
        assert_eq!(state.all_on_output(&first, 0), vec![0, 1]);
        assert!(!state.is_selected(2));
        assert_eq!(state.choose(3, Mode::Toggle, &second), vec![0, 1, 3]);
        assert!(!state.is_selected(0));
        assert!(state.is_selected(3));
        assert_eq!(state.all_on_output(&second, 3), vec![2]);
        assert_eq!(state.count(), 2);
        assert_eq!(state.choose(4, Mode::Replace, &second), Vec::<usize>::new());
        assert_eq!(state.count(), 2);
    }

    #[test]
    fn hotplug_hides_selected_icons_and_invalidates_double_click() {
        let mut state = Selection::default();
        let t = Instant::now();
        state.choose(0, Mode::Replace, &all(3));
        assert!(!state.release(0, (20.0, 30.0), t));
        state.choose(2, Mode::Toggle, &all(3));
        assert_eq!(state.retain_visible(&[false, true, true]), vec![0]);
        assert_eq!(state.count(), 1);
        assert!(!state.release(2, (20.0, 30.0), t + Duration::from_millis(50)));
        assert_eq!(state.retain_visible(&[false, false, false]), vec![2]);
        assert_eq!(state.selected(), None);
        assert!(state.clear_all().is_empty());
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
