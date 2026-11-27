//! The ONE UI-language selection for every native, rice-independent label.
//!
//! RiceBowl core owns functionality and its translated, state-bearing text; a
//! rice owns presentation. A label that a core feature (the volume/brightness
//! OSD, the RicePop notification center) draws or exposes to assistive
//! technology is therefore translated here, once, for every rice, instead of
//! in a per-rice string table. Only UI-owned labels are translated: status
//! values and notification content still come from verified Linux service
//! readback, never from a fabricated locale backend.
//!
//! The language is a snapshot taken when a feature's state is created
//! (session start), not re-read per frame. English is the default and the
//! fallback for every locale that has no catalog.

/// A language that has a catalog of core UI labels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Language {
    #[default]
    English,
    German,
}

impl Language {
    pub fn parse(locale: &str) -> Self {
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

    pub fn from_env() -> Self {
        // LC_ALL takes precedence over message/desktop locale and LANG.
        for key in ["LC_ALL", "LANGUAGE", "LC_MESSAGES", "LANG"] {
            if let Ok(value) = std::env::var(key) {
                if !value.is_empty() {
                    return Self::parse(&value);
                }
            }
        }
        Self::English
    }

    pub fn label(self, english: &'static str, german: &'static str) -> &'static str {
        match self {
            Self::English => english,
            Self::German => german,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locale_selection_is_exact_and_never_reinterprets_untrusted_prefixes() {
        for locale in ["de", "de_DE.UTF-8", "de-AT", "de:en", "de_DE@euro"] {
            assert_eq!(Language::parse(locale), Language::German, "{locale}");
        }
        for locale in ["C", "C.UTF-8", "en_US.UTF-8", "debug", "", "fr_FR", "en:de"] {
            assert_eq!(Language::parse(locale), Language::English, "{locale}");
        }
    }

    #[test]
    fn english_is_the_default_and_label_selects_by_language() {
        assert_eq!(Language::default(), Language::English);
        assert_eq!(Language::English.label("Volume", "Lautstärke"), "Volume");
        assert_eq!(Language::German.label("Volume", "Lautstärke"), "Lautstärke");
    }
}
