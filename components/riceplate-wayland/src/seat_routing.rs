//! Per-wl_seat ownership for native RicePlate input devices.
//!
//! SCTK delivers capability removal for a *specific* seat. A different seat
//! must never release the keyboard/pointer proxy owned by another seat.
//! This policy is pure; Wayland proxy acquisition/release remains in main.rs.
//! No synthetic focus, keyboard grabs, timers or new resident process.

#[derive(Debug)]
pub(crate) struct SeatAssignments<S> {
    fallback: Option<S>,
    keyboard: Option<S>,
    pointer: Option<S>,
}

impl<S> Default for SeatAssignments<S> {
    fn default() -> Self {
        Self { fallback: None, keyboard: None, pointer: None }
    }
}

impl<S: Clone + PartialEq> SeatAssignments<S> {
    pub(crate) fn appeared(&mut self, seat: S) {
        if self.fallback.is_none() {
            self.fallback = Some(seat);
        }
    }

    /// Only one input proxy per capability is currently supported.
    /// Claim ownership *after* SCTK has successfully created the proxy.
    pub(crate) fn claim_keyboard(&mut self, seat: S) {
        self.keyboard = Some(seat);
    }

    pub(crate) fn claim_pointer(&mut self, seat: S) {
        self.pointer = Some(seat);
    }

    pub(crate) fn owns_keyboard(&self, seat: &S) -> bool {
        self.keyboard.as_ref() == Some(seat)
    }

    pub(crate) fn owns_pointer(&self, seat: &S) -> bool {
        self.pointer.as_ref() == Some(seat)
    }

    pub(crate) fn release_keyboard(&mut self, seat: &S) -> bool {
        if !self.owns_keyboard(seat) { return false; }
        self.keyboard = None;
        true
    }

    pub(crate) fn release_pointer(&mut self, seat: &S) -> bool {
        if !self.owns_pointer(seat) { return false; }
        self.pointer = None;
        true
    }

    /// Prioritize the actual pointer seat for a pointer-driven taskbar
    /// activation. A previously discovered but inert seat is only a fallback.
    pub(crate) fn activation_seat(&self) -> Option<&S> {
        self.pointer.as_ref().or(self.keyboard.as_ref())
            .or(self.fallback.as_ref())
    }

    /// Called after the seat's owned devices have been released. A removed
    /// fallback must never remain available for foreign-toplevel activation.
    pub(crate) fn forget_seat(&mut self, seat: &S) {
        if self.fallback.as_ref() == Some(seat) {
            self.fallback = None;
        }
        self.release_keyboard(seat);
        self.release_pointer(seat);
    }
}

#[cfg(test)]
mod tests {
    use super::SeatAssignments;

    #[test]
    fn capability_loss_on_another_seat_does_not_release_our_devices() {
        let mut s = SeatAssignments::default();
        s.appeared("seat-a");
        s.appeared("seat-b");
        s.claim_keyboard("seat-a");
        s.claim_pointer("seat-b");
        assert!(!s.release_keyboard(&"seat-b"));
        assert!(!s.release_pointer(&"seat-a"));
        assert!(s.owns_keyboard(&"seat-a"));
        assert!(s.owns_pointer(&"seat-b"));
        assert_eq!(s.activation_seat(), Some(&"seat-b"));
    }

    #[test]
    fn unplugging_one_seat_keeps_other_input_usable() {
        let mut s = SeatAssignments::default();
        s.appeared("seat-a");
        s.claim_keyboard("seat-a");
        s.claim_pointer("seat-b");
        s.forget_seat(&"seat-a");
        assert!(!s.owns_keyboard(&"seat-a"));
        assert!(s.owns_pointer(&"seat-b"));
        assert_eq!(s.activation_seat(), Some(&"seat-b"));
        assert!(!s.release_keyboard(&"seat-a"));
        assert!(s.release_pointer(&"seat-b"));
        assert_eq!(s.activation_seat(), None);
    }

    #[test]
    fn reattached_device_is_not_stolen_by_stale_seat_removal() {
        let mut s = SeatAssignments::default();
        s.appeared(1_u32);
        s.claim_keyboard(1);
        assert!(s.release_keyboard(&1));
        s.claim_keyboard(2);
        s.forget_seat(&1);
        assert!(s.owns_keyboard(&2));
        assert_eq!(s.activation_seat(), Some(&2));
    }

    #[test]
    fn no_keyboard_grab_or_fabricated_focus_is_needed_for_seat_selection() {
        let mut s = SeatAssignments::default();
        s.appeared(10);
        assert_eq!(s.activation_seat(), Some(&10));
        s.claim_keyboard(20);
        assert_eq!(s.activation_seat(), Some(&20));
        s.claim_pointer(30);
        assert_eq!(s.activation_seat(), Some(&30));
        assert!(s.release_pointer(&30));
        assert_eq!(s.activation_seat(), Some(&20));
    }
}
