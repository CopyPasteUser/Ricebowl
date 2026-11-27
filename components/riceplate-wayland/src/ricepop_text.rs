//! Translated, UI-owned labels of the native RicePop notification center.
//!
//! One catalog for every rice (the Luna Start-menu inbox, the compact popup
//! and the accessibility tree all read it); it uses the same core
//! [`Language`] selection as the volume/brightness OSD. Only text the UI owns
//! is translated: a notification's summary, body, application name, action
//! labels and urgency come from the verified notification host and are shown
//! exactly as received.

use crate::ui_language::Language;

// ---------------------------------------------------------------- painted --
pub fn title(lang: Language, large_font: bool) -> &'static str {
    if large_font {
        lang.label("Alerts", "Meldungen")
    } else {
        lang.label("Notifications", "Benachrichtigungen")
    }
}

/// "Active (n)" tab of the full-size inbox.
pub fn tab_active(lang: Language, count: usize) -> String {
    format!("{} ({count})", lang.label("Active", "Aktiv"))
}

/// "Past (n)" tab of the full-size inbox.
pub fn tab_past(lang: Language, count: usize) -> String {
    format!("{} ({count})", lang.label("Past", "Früher"))
}

/// Compact popup tabs; a large font only has room for a one-letter tab.
pub fn compact_tab_active(lang: Language, large_font: bool, count: usize) -> String {
    if large_font {
        format!("A {count}")
    } else {
        format!("{} {count}", lang.label("Active", "Aktiv"))
    }
}

pub fn compact_tab_past(lang: Language, large_font: bool, count: usize) -> String {
    if large_font {
        format!("{} {count}", lang.label("P", "F"))
    } else {
        format!("{} {count}", lang.label("Past", "Früher"))
    }
}

pub fn offline(lang: Language, short: bool) -> &'static str {
    if short {
        lang.label("Off", "Aus")
    } else {
        "Offline"
    }
}

pub fn loading(lang: Language) -> &'static str {
    lang.label("Loading alerts...", "Meldungen werden geladen...")
}

pub fn retry_hint(lang: Language) -> &'static str {
    lang.label("Refresh to try again", "Zum Wiederholen aktualisieren")
}

pub fn empty(lang: Language, history: bool) -> &'static str {
    if history {
        lang.label("No past alerts", "Keine früheren Meldungen")
    } else {
        lang.label("No active alerts", "Keine aktiven Meldungen")
    }
}

pub fn untitled(lang: Language) -> &'static str {
    lang.label("(No title)", "(Ohne Titel)")
}

pub fn unknown_app(lang: Language) -> &'static str {
    lang.label("Unknown app", "Unbekannte App")
}

pub fn no_actions(lang: Language) -> &'static str {
    lang.label("No available actions", "Keine Aktionen verfügbar")
}

/// Header of the action list of the open message.
pub fn actions_header(lang: Language, large_font: bool, count: usize) -> String {
    let word = lang.label("Actions", "Aktionen");
    if large_font {
        format!("{word} ({count})")
    } else {
        format!(
            "{word} ({count}) - {}",
            lang.label("Enter to use", "Enter zum Ausführen")
        )
    }
}

/// Body pagination hint of the full-size detail view.
pub fn text_pages(current: usize, pages: usize) -> String {
    format!("Text {current}/{pages} < >")
}

pub fn footer_back(lang: Language, large_font: bool, detail: bool) -> &'static str {
    if large_font {
        "Esc"
    } else if detail {
        lang.label("Esc List", "Esc Liste")
    } else {
        lang.label("Esc Back", "Esc Zurück")
    }
}

/// The compact popup footer has three narrow columns; a longer German word
/// would run into its neighbour, so a narrow popup keeps the bare key.
pub fn compact_footer_back(lang: Language, large_font: bool, width: u32) -> &'static str {
    if large_font || (lang == Language::German && width < 264) {
        "Esc"
    } else {
        lang.label("Esc Back", "Esc Zurück")
    }
}

pub fn footer_refresh(lang: Language, large_font: bool) -> &'static str {
    if large_font {
        "R"
    } else {
        lang.label("R Refresh", "R Neu laden")
    }
}

pub fn compact_footer_retry(lang: Language, large_font: bool) -> &'static str {
    if large_font {
        "R"
    } else {
        lang.label("R Retry", "R Neu")
    }
}

pub fn footer_dismiss(lang: Language, large_font: bool, available: bool) -> &'static str {
    match (large_font, available) {
        (true, true) => lang.label("Del", "Entf"),
        (true, false) => lang.label("N/A", "k. A."),
        (false, true) => lang.label("Del Dismiss", "Entf Schließen"),
        (false, false) => lang.label("Unavailable", "Nicht möglich"),
    }
}

pub fn compact_footer_dismiss(lang: Language) -> &'static str {
    lang.label("Del", "Entf")
}

// ------------------------------------------------------------ accessible --
pub fn dialog_name(lang: Language) -> &'static str {
    lang.label("Notifications", "Benachrichtigungen")
}

pub fn tab_active_name(lang: Language, count: usize) -> String {
    format!(
        "{}: {count}",
        lang.label("Active notifications", "Aktive Benachrichtigungen")
    )
}

pub fn tab_past_name(lang: Language, count: usize) -> String {
    format!(
        "{}: {count}",
        lang.label("Past notifications", "Frühere Benachrichtigungen")
    )
}

pub fn host_unavailable_retrying(lang: Language) -> &'static str {
    lang.label(
        "Notification host unavailable; retrying",
        "Benachrichtigungsdienst nicht verfügbar; neuer Versuch",
    )
}

pub fn page_status(lang: Language, first: usize, last: usize, total: usize) -> String {
    match lang {
        Language::English => format!("Showing notifications {first} to {last} of {total}"),
        Language::German => format!("Benachrichtigungen {first} bis {last} von {total}"),
    }
}

pub fn loading_name(lang: Language) -> &'static str {
    lang.label("Loading notifications", "Benachrichtigungen werden geladen")
}

pub fn detail_group(lang: Language, app: &str) -> String {
    format!(
        "{} {app}",
        lang.label("Notification from", "Benachrichtigung von")
    )
}

pub fn previous_page(lang: Language) -> &'static str {
    lang.label("Previous message page", "Vorherige Nachrichtenseite")
}

pub fn next_page(lang: Language) -> &'static str {
    lang.label("Next message page", "Nächste Nachrichtenseite")
}

pub fn view_row(lang: Language, app: &str, summary: &str) -> String {
    match lang {
        Language::English => format!("View notification from {app}: {summary}"),
        Language::German => format!("Benachrichtigung von {app} anzeigen: {summary}"),
    }
}

pub fn back_name(lang: Language, detail: bool) -> &'static str {
    if detail {
        lang.label(
            "Back to notification list",
            "Zurück zur Benachrichtigungsliste",
        )
    } else {
        lang.label("Back to menu", "Zurück zum Menü")
    }
}

pub fn refresh_name(lang: Language) -> &'static str {
    lang.label("Refresh notifications", "Benachrichtigungen aktualisieren")
}

pub fn dismiss_name(lang: Language) -> &'static str {
    lang.label(
        "Dismiss selected notification",
        "Ausgewählte Benachrichtigung schließen",
    )
}

// ----------------------------------------------------------------- errors --
/// Every fixed failure text the inbox can show, with its German form. The
/// text never carries notification content or a provider error.
const ERRORS: &[(&str, &str)] = &[
    (
        "Notification data too large",
        "Benachrichtigungsdaten zu groß",
    ),
    (
        "Notification list unavailable",
        "Benachrichtigungsliste nicht verfügbar",
    ),
    (
        "Invalid Mako owner identity",
        "Ungültige Mako-Eigentümerkennung",
    ),
    (
        "Invalid notification data",
        "Ungültige Benachrichtigungsdaten",
    ),
    (
        "Notification list too long",
        "Benachrichtigungsliste zu lang",
    ),
    (
        "Notification host unavailable",
        "Benachrichtigungsdienst nicht verfügbar",
    ),
    (
        "RicePop private action snapshot too large",
        "Private RicePop-Aktionsdaten zu groß",
    ),
    ("RicePop CLI unavailable", "RicePop-Befehl nicht verfügbar"),
    ("Stale RicePop selection", "Veraltete RicePop-Auswahl"),
    (
        "Stale RicePop action selection",
        "Veraltete RicePop-Aktionsauswahl",
    ),
    (
        "Unverified RicePop notification host",
        "Nicht verifizierter RicePop-Benachrichtigungsdienst",
    ),
    (
        "Invalid native notification snapshot",
        "Ungültiger Benachrichtigungsstand",
    ),
    (
        "RicePop action unconfirmed; refresh before retry",
        "RicePop-Aktion unbestätigt; vor dem Wiederholen aktualisieren",
    ),
    ("RicePop worker busy", "RicePop ist beschäftigt"),
    (
        "Stale RicePop action; refresh",
        "Veraltete RicePop-Aktion; aktualisieren",
    ),
    (
        "RicePop busy or unavailable",
        "RicePop beschäftigt oder nicht verfügbar",
    ),
];

/// The displayed form of a fixed inbox failure text. An unknown text is
/// returned unchanged (English) rather than hidden.
pub fn error(lang: Language, message: &'static str) -> &'static str {
    if lang == Language::English {
        return message;
    }
    ERRORS
        .iter()
        .find(|(english, _)| *english == message)
        .map_or(message, |(_, german)| german)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn literals_after(source: &str, marker: &str) -> Vec<String> {
        // Every fixed failure literal handed to the inbox state in `source`.
        let mut found = Vec::new();
        for line in source.lines() {
            let mut rest = line;
            while let Some(at) = rest.find(marker) {
                rest = &rest[at + marker.len()..];
                if let Some(end) = rest.find('"') {
                    found.push(rest[..end].to_owned());
                    rest = &rest[end..];
                }
            }
        }
        found
    }

    #[test]
    fn every_fixed_inbox_failure_has_a_german_text() {
        let ricepop = include_str!("ricepop.rs");
        let production = &ricepop[..ricepop.find("#[cfg(test)]").unwrap()];
        let main = include_str!("main.rs");
        let mut used = literals_after(production, "Err(\"");
        used.extend(literals_after(production, ".ok_or(\""));
        used.extend(literals_after(main, ".update(revision, Err(\""));
        used.push("Notification host unavailable".into()); // cli_failure(false)
        used.push("RicePop action unconfirmed; refresh before retry".into()); // MUTATION_UNCONFIRMED
        assert!(used.len() >= 12, "scanner found too few literals: {used:?}");
        for message in used {
            assert!(
                ERRORS.iter().any(|(english, _)| *english == message),
                "no German text for inbox failure {message:?}"
            );
        }
        for (english, german) in ERRORS {
            assert!(!german.is_empty() && german != english, "{english}");
        }
    }

    #[test]
    fn german_footer_and_tab_labels_fit_the_fixed_full_size_columns() {
        // The full-size popup draws on 8px cells: footer columns start at
        // x = 14, 98 and 193 of 320, the tabs are 152px wide. A label that
        // does not fit is clipped with an ellipsis by the painter.
        let de = Language::German;
        let cells = |text: &str| text.chars().count();
        for detail in [false, true] {
            assert!(cells(footer_back(de, false, detail)) <= (98 - 14) / 8);
        }
        assert!(cells(footer_refresh(de, false)) <= (193 - 98) / 8);
        for available in [false, true] {
            assert!(cells(footer_dismiss(de, false, available)) <= (320 - 193 - 8) / 8);
        }
        assert!(cells(&tab_active(de, 99)) <= (152 - 14) / 8);
        assert!(cells(&tab_past(de, 99)) <= (152 - 14) / 8);
        assert!(cells(title(de, false)) <= (320 - 14 - 8 - 7 * 8) / 8);
        assert!(cells(&actions_header(de, false, 9)) <= (320 - 14 - 8) / 8);
    }

    #[test]
    fn unknown_failure_text_stays_visible_and_english_is_untouched() {
        assert_eq!(error(Language::German, "Something new"), "Something new");
        assert_eq!(
            error(Language::English, "Notification host unavailable"),
            "Notification host unavailable"
        );
        assert_eq!(
            error(Language::German, "Notification host unavailable"),
            "Benachrichtigungsdienst nicht verfügbar"
        );
    }

    #[test]
    fn german_labels_are_translated_and_english_is_the_historic_text() {
        let en = Language::English;
        let de = Language::German;
        // Historic English strings are byte-for-byte unchanged.
        assert_eq!(title(en, false), "Notifications");
        assert_eq!(title(en, true), "Alerts");
        assert_eq!(tab_active(en, 3), "Active (3)");
        assert_eq!(tab_past(en, 0), "Past (0)");
        assert_eq!(compact_tab_active(en, false, 2), "Active 2");
        assert_eq!(compact_tab_active(en, true, 2), "A 2");
        assert_eq!(compact_tab_past(en, true, 2), "P 2");
        assert_eq!(footer_back(en, false, true), "Esc List");
        assert_eq!(footer_dismiss(en, false, true), "Del Dismiss");
        assert_eq!(actions_header(en, false, 2), "Actions (2) - Enter to use");
        assert_eq!(
            view_row(en, "Mail", "Hi"),
            "View notification from Mail: Hi"
        );
        assert_eq!(
            page_status(en, 1, 3, 7),
            "Showing notifications 1 to 3 of 7"
        );
        assert_eq!(tab_active_name(en, 1), "Active notifications: 1");
        // German: the same keys, different non-empty text, count preserved.
        assert_eq!(title(de, false), "Benachrichtigungen");
        assert_eq!(tab_active(de, 3), "Aktiv (3)");
        assert_eq!(tab_past(de, 0), "Früher (0)");
        assert_eq!(compact_tab_past(de, true, 2), "F 2");
        assert_eq!(footer_back(de, false, false), "Esc Zurück");
        assert_eq!(footer_dismiss(de, false, true), "Entf Schließen");
        assert_eq!(
            view_row(de, "Mail", "Hi"),
            "Benachrichtigung von Mail anzeigen: Hi"
        );
        assert_eq!(tab_active_name(de, 1), "Aktive Benachrichtigungen: 1");
        assert_eq!(page_status(de, 1, 3, 7), "Benachrichtigungen 1 bis 3 von 7");
        assert_eq!(detail_group(de, "Mail"), "Benachrichtigung von Mail");
        // Narrow compact popup keeps the bare key; a wide one has room.
        assert_eq!(compact_footer_back(de, false, 168), "Esc");
        assert_eq!(compact_footer_back(de, false, 320), "Esc Zurück");
        assert_eq!(compact_footer_back(en, false, 168), "Esc Back");
        // Every translatable label differs between the languages.
        let pairs: Vec<(&str, &str)> = vec![
            (title(en, false), title(de, false)),
            (title(en, true), title(de, true)),
            (offline(en, true), offline(de, true)),
            (loading(en), loading(de)),
            (retry_hint(en), retry_hint(de)),
            (empty(en, true), empty(de, true)),
            (empty(en, false), empty(de, false)),
            (untitled(en), untitled(de)),
            (unknown_app(en), unknown_app(de)),
            (no_actions(en), no_actions(de)),
            (footer_refresh(en, false), footer_refresh(de, false)),
            (
                compact_footer_retry(en, false),
                compact_footer_retry(de, false),
            ),
            (
                footer_dismiss(en, true, true),
                footer_dismiss(de, true, true),
            ),
            (
                footer_dismiss(en, false, false),
                footer_dismiss(de, false, false),
            ),
            (dialog_name(en), dialog_name(de)),
            (host_unavailable_retrying(en), host_unavailable_retrying(de)),
            (loading_name(en), loading_name(de)),
            (previous_page(en), previous_page(de)),
            (next_page(en), next_page(de)),
            (back_name(en, true), back_name(de, true)),
            (back_name(en, false), back_name(de, false)),
            (refresh_name(en), refresh_name(de)),
            (dismiss_name(en), dismiss_name(de)),
        ];
        for (english, german) in pairs {
            assert!(
                !german.is_empty() && english != german,
                "{english} / {german}"
            );
        }
    }
}
