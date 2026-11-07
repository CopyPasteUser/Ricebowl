//! Transient, input-transparent RicePop volume display in the resident panel.
//! Timers use the existing Wayland event loop; no second daemon or polling.

use std::time::{Duration, Instant};

use crate::system_status::{Audio, ControlAction, SystemStatus};

pub const WIDTH: u32 = 248;
pub const HEIGHT: u32 = 70;
pub const LIFETIME: Duration = Duration::from_millis(1800);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notice {
    pub title: &'static str,
    pub value: String,
    pub fill: Option<u16>,
}

impl Notice {
    fn from_result(action: ControlAction, success: bool, status: &SystemStatus) -> Option<Self> {
        if !matches!(action, ControlAction::AudioMute | ControlAction::AudioUp |
            ControlAction::AudioDown) {
            return None;
        }
        if !success {
            return Some(Self { title: "Volume", value: "Change failed".into(), fill: None });
        }
        Some(match status.audio {
            Audio::Volume(volume) => Self {
                title: "Volume", value: format!("{volume}%"),
                fill: Some(volume.min(100)),
            },
            Audio::Muted => Self { title: "Volume", value: "Muted".into(), fill: Some(0) },
            Audio::Unavailable => Self {
                title: "Volume", value: "Unavailable".into(), fill: None,
            },
        })
    }
}

#[derive(Debug, Default)]
pub struct State {
    pub current: Option<Notice>,
    deadline: Option<Instant>,
}

impl State {
    pub fn show(&mut self, action: ControlAction, success: bool, status: &SystemStatus,
                now: Instant) -> bool {
        let Some(notice) = Notice::from_result(action, success, status) else {
            return false;
        };
        self.current = Some(notice);
        self.deadline = Some(now + LIFETIME);
        true
    }

    pub fn timeout(&self, now: Instant) -> Option<Duration> {
        self.deadline.map(|deadline| deadline.saturating_duration_since(now))
    }

    pub fn expire(&mut self, now: Instant) -> bool {
        if !self.deadline.is_some_and(|deadline| deadline <= now) {
            return false;
        }
        self.current = None;
        self.deadline = None;
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn volume_osd_uses_verified_sink_readback_and_bounded_duration() {
        let now = Instant::now();
        let mut state = State::default();
        let status = SystemStatus { audio: Audio::Volume(68), ..SystemStatus::default() };
        assert!(!state.show(ControlAction::WifiToggle, true, &status, now));
        assert_eq!(state.timeout(now), None);
        assert!(state.show(ControlAction::AudioUp, true, &status, now));
        assert_eq!(state.current.as_ref().unwrap().value, "68%");
        assert_eq!(state.current.as_ref().unwrap().fill, Some(68));
        assert_eq!(state.timeout(now), Some(LIFETIME));
        assert!(!state.expire(now + Duration::from_millis(1799)));
        assert!(state.expire(now + LIFETIME));
        assert!(state.current.is_none());
    }

    #[test]
    fn repeated_mute_and_failure_replaces_notice_and_resets_expiry() {
        let now = Instant::now();
        let mut state = State::default();
        let muted = SystemStatus { audio: Audio::Muted, ..SystemStatus::default() };
        assert!(state.show(ControlAction::AudioMute, true, &muted, now));
        assert_eq!(state.current.as_ref().unwrap().value, "Muted");
        assert_eq!(state.current.as_ref().unwrap().fill, Some(0));
        let retry_at = now + Duration::from_millis(900);
        assert!(state.show(ControlAction::AudioDown, false, &muted, retry_at));
        assert_eq!(state.current.as_ref().unwrap().value, "Change failed");
        assert_eq!(state.current.as_ref().unwrap().fill, None);
        assert_eq!(state.timeout(now + LIFETIME), Some(Duration::from_millis(900)));
        assert!(!state.expire(now + LIFETIME));
        assert!(state.expire(retry_at + LIFETIME));
    }

    #[test]
    fn oversized_audio_is_clamped_for_bar_not_text() {
        let status = SystemStatus { audio: Audio::Volume(115), ..SystemStatus::default() };
        let result = Notice::from_result(ControlAction::AudioDown, true, &status).unwrap();
        assert_eq!(result.value, "115%");
        assert_eq!(result.fill, Some(100));
    }
}
