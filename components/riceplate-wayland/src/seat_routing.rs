//! Per-wl_seat ownership for native RicePlate input devices.
//!
//! SCTK delivers capability removal for a *specific* seat. A different seat
//! must never release the keyboard/pointer proxy owned by another seat.
//! This policy is pure; Wayland proxy acquisition/release remains in main.rs.
//! No synthetic focus, keyboard grabs, timers or new resident process.

#[derive(Debug)]
pub(crate) struct SeatAssignments<S> {
    // Preserve all advertised seats so removing the first one cannot leave
    // a stale or empty assistive-activation fallback while others remain.
    present: Vec<S>,
    keyboard: Option<S>,
    pointer: Option<S>,
}

impl<S> Default for SeatAssignments<S> {
    fn default() -> Self {
        Self { present: Vec::new(), keyboard: None, pointer: None }
    }
}

/// Select the Wayland seat that actually initiated a window activation.
/// Assistive actions have no accompanying compositor input serial/seat.
#[derive(Debug, Clone, Copy)]
pub(crate) enum ActivationSource { Pointer, Keyboard, Assistive }

impl<S: Clone + PartialEq> SeatAssignments<S> {
    pub(crate) fn appeared(&mut self, seat: S) {
        if !self.present.contains(&seat) {
            self.present.push(seat);
        }
    }

    /// Only one input proxy per capability is currently supported.
    /// Claim ownership *after* SCTK has successfully created the proxy.
    pub(crate) fn claim_keyboard(&mut self, seat: S) {
        self.appeared(seat.clone());
        self.keyboard = Some(seat);
    }

    pub(crate) fn claim_pointer(&mut self, seat: S) {
        self.appeared(seat.clone());
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

    /// Never use the pointer's seat for a keyboard action if its own seat
    /// exists. This matters when a compositor advertises several input seats.
    pub(crate) fn activation_seat_for(&self, source: ActivationSource) -> Option<&S> {
        match source {
            ActivationSource::Keyboard => self.keyboard.as_ref()
                .or(self.pointer.as_ref()).or(self.present.first()),
            ActivationSource::Pointer | ActivationSource::Assistive => self.pointer.as_ref()
                .or(self.keyboard.as_ref()).or(self.present.first()),
        }
    }

    /// Called after the seat's owned devices have been released. A removed
    /// fallback must never remain available for foreign-toplevel activation.
    pub(crate) fn forget_seat(&mut self, seat: &S) {
        self.present.retain(|candidate| candidate != seat);
        self.release_keyboard(seat);
        self.release_pointer(seat);
    }
}

#[cfg(test)]
mod tests {
    use super::{ActivationSource, SeatAssignments};

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
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&"seat-b"));
        assert_eq!(s.activation_seat_for(ActivationSource::Keyboard), Some(&"seat-a"));
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
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&"seat-b"));
        assert!(!s.release_keyboard(&"seat-a"));
        assert!(s.release_pointer(&"seat-b"));
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), None);
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
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&2));
    }

    #[test]
    fn removed_primary_seat_falls_back_to_a_still_advertised_seat() {
        let mut seats = SeatAssignments::default();
        seats.appeared("primary");
        seats.appeared("secondary");
        seats.appeared("secondary");
        seats.forget_seat(&"primary");
        assert_eq!(seats.activation_seat_for(ActivationSource::Assistive), Some(&"secondary"));
        assert_eq!(seats.activation_seat_for(ActivationSource::Keyboard), Some(&"secondary"));
        seats.forget_seat(&"secondary");
        assert_eq!(seats.activation_seat_for(ActivationSource::Assistive), None);
    }

    #[test]
    fn removing_a_different_seat_keeps_live_capability_owner_and_fallback() {
        let mut seats = SeatAssignments::default();
        seats.appeared(1_u8);
        seats.appeared(2_u8);
        seats.claim_pointer(2);
        seats.forget_seat(&1);
        assert_eq!(seats.activation_seat_for(ActivationSource::Pointer), Some(&2));
        assert!(seats.owns_pointer(&2));
        seats.release_pointer(&2);
        assert_eq!(seats.activation_seat_for(ActivationSource::Assistive), Some(&2));
    }

    #[test]
    fn no_keyboard_grab_or_fabricated_focus_is_needed_for_seat_selection() {
        let mut s = SeatAssignments::default();
        s.appeared(10);
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&10));
        s.claim_keyboard(20);
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&20));
        s.claim_pointer(30);
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&30));
        assert!(s.release_pointer(&30));
        assert_eq!(s.activation_seat_for(ActivationSource::Assistive), Some(&20));
    }
}
