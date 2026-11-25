//! Transient, input-transparent RicePop volume display in the resident panel.
//! Timers use the existing Wayland event loop; no second daemon or polling.

use std::time::{Duration, Instant};

use crate::system_status::{Audio, ControlAction, SystemStatus};

pub const WIDTH: u32 = 248;
pub const HEIGHT: u32 = 70;
pub const LIFETIME: Duration = Duration::from_millis(1800);

/// Only UI-owned OSD labels are translated. Status values still come from
/// verified Linux service readback, never from a fabricated locale backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Language {
    English,
    German,
}

impl Language {
    fn parse(locale: &str) -> Self {
        // GNU LANGUAGE can be a colon-delimited preference; the first entry
        // is the requested UI language. Never treat "debug" as German.
        let primary = locale.split(':').next().unwrap_or("");
        let language = primary.split(['_', '-', '.', '@']).next().unwrap_or("");
        if language.eq_ignore_ascii_case("de") {
            Self::German
        } else {
            Self::English
        }
    }

    fn from_env() -> Self {
        // Snapshot at session creation, not once per OSD or frame. LC_ALL
        // takes precedence over message/desktop locale and LANG.
        for key in ["LC_ALL", "LANGUAGE", "LC_MESSAGES", "LANG"] {
            if let Ok(value) = std::env::var(key) {
                if !value.is_empty() {
                    return Self::parse(&value);
                }
            }
        }
        Self::English
    }

    fn label(self, english: &'static str, german: &'static str) -> &'static str {
        match self {
            Self::English => english,
            Self::German => german,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notice {
    pub title: &'static str,
    pub value: String,
    pub fill: Option<u16>,
}

impl Notice {
    fn from_audio(audio: &Audio, lang: Language) -> Self {
        match audio {
            Audio::Volume(volume) => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: format!("{volume}%"),
                fill: Some((*volume).min(100)),
            },
            Audio::Muted => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: lang.label("Muted", "Stumm").into(),
                fill: Some(0),
            },
            Audio::Unavailable => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: lang.label("Unavailable", "Nicht verfügbar").into(),
                fill: None,
            },
        }
    }

    fn from_result(
        action: ControlAction,
        success: bool,
        status: &SystemStatus,
        lang: Language,
    ) -> Option<Self> {
        if !matches!(
            action,
            ControlAction::AudioMute | ControlAction::AudioUp | ControlAction::AudioDown
        ) {
            return None;
        }
        if !success {
            return Some(Self {
                title: lang.label("Volume", "Lautstärke"),
                value: lang
                    .label("Change failed", "Änderung fehlgeschlagen")
                    .into(),
                fill: None,
            });
        }
        Some(Self::from_audio(&status.audio, lang))
    }
}

#[derive(Debug)]
pub struct State {
    pub current: Option<Notice>,
    deadline: Option<Instant>,
    language: Language,
}

impl Default for State {
    fn default() -> Self {
        Self {
            current: None,
            deadline: None,
            language: Language::from_env(),
        }
    }
}

impl State {
    pub fn show_brightness(&mut self, percent: u16, now: Instant) {
        self.current = Some(Notice {
            title: self.language.label("Brightness", "Helligkeit"),
            value: format!("{percent}%"),
            fill: Some(percent.min(100)),
        });
        self.deadline = Some(now + LIFETIME);
    }
    pub fn show_external(&mut self, previous: &Audio, current: &Audio, now: Instant) -> bool {
        // Never display a spurious OSD at startup, after missing services or
        // for a duplicate event following our own already-verified quick action.
        if previous == current
            || matches!(previous, Audio::Unavailable)
            || matches!(current, Audio::Unavailable)
        {
            return false;
        }
        self.current = Some(Notice::from_audio(current, self.language));
        self.deadline = Some(now + LIFETIME);
        true
    }

    pub fn show(
        &mut self,
        action: ControlAction,
        success: bool,
        status: &SystemStatus,
        now: Instant,
    ) -> bool {
        let Some(notice) = Notice::from_result(action, success, status, self.language) else {
            return false;
        };
        self.current = Some(notice);
        self.deadline = Some(now + LIFETIME);
        true
    }

    pub fn timeout(&self, now: Instant) -> Option<Duration> {
        self.deadline
            .map(|deadline| deadline.saturating_duration_since(now))
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

    fn english_state() -> State {
        State {
            language: Language::English,
            ..State::default()
        }
    }

    #[test]
    fn volume_osd_uses_verified_sink_readback_and_bounded_duration() {
        let now = Instant::now();
        let mut state = english_state();
        let status = SystemStatus {
            audio: Audio::Volume(68),
            ..SystemStatus::default()
        };
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
        let mut state = english_state();
        let muted = SystemStatus {
            audio: Audio::Muted,
            ..SystemStatus::default()
        };
        assert!(state.show(ControlAction::AudioMute, true, &muted, now));
        assert_eq!(state.current.as_ref().unwrap().value, "Muted");
        assert_eq!(state.current.as_ref().unwrap().fill, Some(0));
        let retry_at = now + Duration::from_millis(900);
        assert!(state.show(ControlAction::AudioDown, false, &muted, retry_at));
        assert_eq!(state.current.as_ref().unwrap().value, "Change failed");
        assert_eq!(state.current.as_ref().unwrap().fill, None);
        assert_eq!(
            state.timeout(now + LIFETIME),
            Some(Duration::from_millis(900))
        );
        assert!(!state.expire(now + LIFETIME));
        assert!(state.expire(retry_at + LIFETIME));
    }

    #[test]
    fn oversized_audio_is_clamped_for_bar_not_text() {
        let status = SystemStatus {
            audio: Audio::Volume(115),
            ..SystemStatus::default()
        };
        let result =
            Notice::from_result(ControlAction::AudioDown, true, &status, Language::English)
                .unwrap();
        assert_eq!(result.value, "115%");
        assert_eq!(result.fill, Some(100));
    }

    #[test]
    fn external_audio_changes_show_once_without_startup_or_error_noise() {
        let now = Instant::now();
        let mut state = english_state();
        assert!(!state.show_external(&Audio::Unavailable, &Audio::Volume(45), now));
        assert!(!state.show_external(&Audio::Volume(45), &Audio::Volume(45), now));
        assert!(state.show_external(&Audio::Volume(45), &Audio::Volume(55), now));
        assert_eq!(state.current.as_ref().unwrap().value, "55%");
        assert!(!state.show_external(&Audio::Volume(55), &Audio::Unavailable, now));
        assert!(state.show_external(&Audio::Volume(55), &Audio::Muted, now));
        assert_eq!(state.current.as_ref().unwrap().value, "Muted");
        assert_eq!(state.timeout(now), Some(LIFETIME));
    }

    #[test]
    fn locale_selection_is_exact_and_never_reinterprets_untrusted_prefixes() {
        for locale in ["de", "de_DE.UTF-8", "de-AT", "de:en", "de_DE@euro"] {
            assert_eq!(Language::parse(locale), Language::German, "{locale}");
        }
        for locale in ["C", "C.UTF-8", "en_US.UTF-8", "debug", "", "fr_FR"] {
            assert_eq!(Language::parse(locale), Language::English, "{locale}");
        }
    }

    #[test]
    fn german_osd_uses_real_readback_and_preserves_failure_and_expiry_states() {
        let now = Instant::now();
        let mut state = State {
            language: Language::German,
            ..State::default()
        };
        let status = SystemStatus {
            audio: Audio::Volume(52),
            ..SystemStatus::default()
        };
        assert!(state.show(ControlAction::AudioUp, true, &status, now));
        assert_eq!(state.current.as_ref().unwrap().title, "Lautstärke");
        assert_eq!(state.current.as_ref().unwrap().value, "52%");
        assert!(state.show(ControlAction::AudioDown, false, &status, now));
        assert_eq!(
            state.current.as_ref().unwrap().value,
            "Änderung fehlgeschlagen"
        );
        assert_eq!(state.current.as_ref().unwrap().fill, None);
        assert!(state.show_external(&Audio::Volume(52), &Audio::Muted, now));
        assert_eq!(state.current.as_ref().unwrap().value, "Stumm");
        assert!(!state.show_external(&Audio::Muted, &Audio::Unavailable, now));
        state.show_brightness(37, now);
        assert_eq!(state.current.as_ref().unwrap().title, "Helligkeit");
        assert_eq!(state.current.as_ref().unwrap().fill, Some(37));
        assert!(state.expire(now + LIFETIME));
        assert!(state.current.is_none());
    }

    #[test]
    fn brightness_uses_the_existing_input_transparent_osd_and_expiration() {
        let now = Instant::now();
        let mut state = english_state();
        state.show_brightness(37, now);
        assert_eq!(state.current.as_ref().unwrap().title, "Brightness");
        assert_eq!(state.current.as_ref().unwrap().fill, Some(37));
        assert!(state.expire(now + LIFETIME));
    }
}
