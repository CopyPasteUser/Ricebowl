//! Bounded retry policy for a disconnected native StatusNotifier D-Bus host.
//! Only the existing Wayland reactor performs connection attempts; there is
//! no resident worker or per-frame bus polling.

use std::time::{Duration, Instant};

pub(crate) const RETRY_INTERVAL: Duration = Duration::from_secs(5);

pub(crate) struct Retry {
    enabled: bool,
    next: Instant,
}

impl Retry {
    pub(crate) fn new(enabled: bool, now: Instant) -> Self {
        Self { enabled, next: now + RETRY_INTERVAL }
    }

    pub(crate) fn timeout(&self, connected: bool, now: Instant) -> Option<Duration> {
        (self.enabled && !connected).then(|| self.next.saturating_duration_since(now))
    }

    pub(crate) fn due(&self, connected: bool, now: Instant) -> bool {
        self.enabled && !connected && now >= self.next
    }

    pub(crate) fn attempted(&mut self, now: Instant) {
        self.next = now + RETRY_INTERVAL;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_bus_retries_only_after_bounded_delay_and_never_spins() {
        let now = Instant::now();
        let mut retry = Retry::new(true, now);
        assert_eq!(retry.timeout(false, now), Some(RETRY_INTERVAL));
        assert!(!retry.due(false, now + RETRY_INTERVAL - Duration::from_millis(1)));
        assert!(retry.due(false, now + RETRY_INTERVAL));
        retry.attempted(now + RETRY_INTERVAL);
        assert!(!retry.due(false, now + RETRY_INTERVAL));
        assert!(retry.due(false, now + 2 * RETRY_INTERVAL));
    }

    #[test]
    fn connected_or_disabled_tray_never_poll_or_connect() {
        let now = Instant::now();
        let retry = Retry::new(true, now);
        assert_eq!(retry.timeout(true, now + RETRY_INTERVAL), None);
        assert!(!retry.due(true, now + 3 * RETRY_INTERVAL));
        let disabled = Retry::new(false, now);
        assert_eq!(disabled.timeout(false, now + 5 * RETRY_INTERVAL), None);
        assert!(!disabled.due(false, now + 5 * RETRY_INTERVAL));
    }

    #[test]
    fn hot_disconnect_defers_reconnection_until_prior_deadline() {
        let now = Instant::now();
        let mut retry = Retry::new(true, now);
        retry.attempted(now + RETRY_INTERVAL);
        assert!(!retry.due(false, now + RETRY_INTERVAL));
        assert_eq!(retry.timeout(false, now + RETRY_INTERVAL), Some(RETRY_INTERVAL));
        assert!(retry.due(false, now + 2 * RETRY_INTERVAL));
    }
}
