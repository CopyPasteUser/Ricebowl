//! Transient, input-transparent RicePop volume display in the resident panel.
//! Timers use the existing Wayland event loop; no second daemon or polling.

use std::time::{Duration, Instant};

use crate::system_status::{Audio, ControlAction, SystemStatus};

pub const WIDTH: u32 = 248;
pub const HEIGHT: u32 = 70;
pub const LIFETIME: Duration = Duration::from_millis(1800);
/// A failure is something the user must be able to read and an assistive
/// technology must be able to announce, so it stays up longer than a volume
/// confirmation. It is still bounded and never takes keyboard focus.
pub const FAILURE_LIFETIME: Duration = Duration::from_millis(4000);

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

/// Generic, fixed-text failure categories for operations the user started
/// and that failed after the control had already closed (a launcher, a
/// provider, a file helper). The text never carries an application name, a
/// path, an argv or a provider error: those stay in the process log.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    AppStart,
    Launcher,
    Settings,
    Command,
    TrayProvider,
    Trash,
    OpenFile,
    NewFolder,
}

impl Failure {
    #[cfg(test)]
    pub const ALL: [Self; 8] = [
        Self::AppStart,
        Self::Launcher,
        Self::Settings,
        Self::Command,
        Self::TrayProvider,
        Self::Trash,
        Self::OpenFile,
        Self::NewFolder,
    ];

    fn notice(self, lang: Language) -> Notice {
        let (title, value) = match self {
            Self::AppStart => (
                lang.label("Application", "Anwendung"),
                lang.label("Could not start", "Start fehlgeschlagen"),
            ),
            Self::Launcher => (
                lang.label("Launcher", "Starter"),
                lang.label("Not available", "Nicht verfügbar"),
            ),
            Self::Settings => (
                lang.label("Settings", "Einstellungen"),
                lang.label("Could not open", "Öffnen fehlgeschlagen"),
            ),
            Self::Command => (
                lang.label("Command", "Befehl"),
                lang.label("Could not run", "Ausführen fehlgeschlagen"),
            ),
            Self::TrayProvider => (
                lang.label("Tray", "Infobereich"),
                lang.label("App did not respond", "App antwortet nicht"),
            ),
            Self::Trash => (
                lang.label("Recycle Bin", "Papierkorb"),
                lang.label("Could not move item", "Verschieben fehlgeschlagen"),
            ),
            Self::OpenFile => (
                lang.label("Desktop", "Desktop"),
                lang.label("Could not open item", "Öffnen fehlgeschlagen"),
            ),
            Self::NewFolder => (
                lang.label("Desktop", "Desktop"),
                lang.label("Could not create folder", "Ordner nicht erstellt"),
            ),
        };
        Notice {
            title,
            value: value.into(),
            fill: None,
            alert: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Notice {
    pub title: &'static str,
    pub value: String,
    pub fill: Option<u16>,
    /// A failure notice: painted with the error accent and exposed to
    /// assistive technology as an alert instead of a passive status.
    pub alert: bool,
}

impl Notice {
    /// The one text an assistive technology receives for this surface. It is
    /// the same title and value that are painted, never a separate string.
    pub fn accessible_label(&self) -> String {
        format!("{}: {}", self.title, self.value)
    }

    fn from_audio(audio: &Audio, lang: Language) -> Self {
        match audio {
            Audio::Volume(volume) => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: format!("{volume}%"),
                fill: Some((*volume).min(100)),
                alert: false,
            },
            Audio::Muted => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: lang.label("Muted", "Stumm").into(),
                fill: Some(0),
                alert: false,
            },
            Audio::Unavailable => Self {
                title: lang.label("Volume", "Lautstärke"),
                value: lang.label("Unavailable", "Nicht verfügbar").into(),
                fill: None,
                alert: false,
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
                alert: false,
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
            alert: false,
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

    /// Show a generic failure. A newer notice replaces the current one and
    /// restarts the bounded lifetime; nothing is queued or replayed.
    pub fn show_failure(&mut self, failure: Failure, now: Instant) {
        self.current = Some(failure.notice(self.language));
        self.deadline = Some(now + FAILURE_LIFETIME);
    }

    /// Explicit dismissal (Escape on the focused panel). Returns whether a
    /// failure notice was actually removed; a volume confirmation is left to
    /// its own short timer.
    pub fn dismiss_failure(&mut self) -> bool {
        if self.current.as_ref().is_some_and(|notice| notice.alert) {
            self.current = None;
            self.deadline = None;
            true
        } else {
            false
        }
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
    #[test]
    fn failure_notices_are_generic_alerts_with_a_bounded_lifetime() {
        let now = Instant::now();
        let mut state = english_state();
        for failure in Failure::ALL {
            state.show_failure(failure, now);
            let notice = state.current.as_ref().unwrap();
            assert!(notice.alert && notice.fill.is_none(), "{failure:?}");
            // Fixed, short, generic text: no path, argv, bus name or error.
            let text = notice.accessible_label();
            assert!(text.chars().count() <= 34, "{text}");
            assert!(
                text.chars()
                    .all(|c| c.is_ascii_alphabetic() || c == ' ' || c == ':'),
                "{text}"
            );
            assert_eq!(state.timeout(now), Some(FAILURE_LIFETIME));
        }
        assert!(FAILURE_LIFETIME > LIFETIME);
        assert!(!state.expire(now + Duration::from_millis(3999)));
        assert!(state.expire(now + FAILURE_LIFETIME));
        assert!(state.current.is_none());
    }

    #[test]
    fn a_newer_notice_replaces_and_a_volume_value_is_not_an_alert() {
        let now = Instant::now();
        let mut state = english_state();
        state.show_failure(Failure::AppStart, now);
        let later = now + Duration::from_millis(1500);
        state.show_failure(Failure::Settings, later);
        assert_eq!(state.current.as_ref().unwrap().title, "Settings");
        assert_eq!(state.timeout(later), Some(FAILURE_LIFETIME));
        // Not queued: when the second expires nothing remains behind it.
        assert!(state.expire(later + FAILURE_LIFETIME));
        assert!(state.current.is_none());
        state.show_brightness(40, later);
        assert!(!state.current.as_ref().unwrap().alert);
        assert_eq!(
            state.current.as_ref().unwrap().accessible_label(),
            "Brightness: 40%"
        );
    }

    #[test]
    fn escape_dismisses_only_a_failure_notice() {
        let now = Instant::now();
        let mut state = english_state();
        assert!(!state.dismiss_failure());
        state.show_brightness(40, now);
        assert!(
            !state.dismiss_failure(),
            "a volume/brightness OSD keeps its timer"
        );
        assert!(state.current.is_some());
        state.show_failure(Failure::Trash, now);
        assert!(state.dismiss_failure());
        assert!(state.current.is_none());
        assert_eq!(state.timeout(now), None);
        assert!(
            !state.dismiss_failure(),
            "a second Escape finds nothing to dismiss"
        );
    }

    #[test]
    fn german_failure_notices_are_translated_and_still_generic() {
        let now = Instant::now();
        let mut state = State {
            language: Language::German,
            ..State::default()
        };
        state.show_failure(Failure::Trash, now);
        assert_eq!(state.current.as_ref().unwrap().title, "Papierkorb");
        assert_eq!(
            state.current.as_ref().unwrap().value,
            "Verschieben fehlgeschlagen"
        );
    }
}
