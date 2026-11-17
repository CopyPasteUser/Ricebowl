"""Small, reviewed RicePop UI catalog; no system locale mutation or gettext daemon.

Only the notification-specific RiceSpice surface is localized here. The rest
of RiceSpice and Mako-owned notification contents are deliberately untouched.
Use LC_ALL > LC_MESSAGES > LANGUAGE > LANG, falling back to English.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

_EN = {
    "intro": "Do Not Disturb hides incoming notification banners while retaining RicePop's active and past alerts.",
    "owner_info": "This setting is available only when the full RiceBowl Wayland session owns its Mako notification service.",
    "refresh_state": "Refresh notification state",
    "show_inbox": "Show RicePop inbox",
    "dnd_on": "Do Not Disturb: on",
    "dnd_off": "Do Not Disturb: off",
    "toggle_on": "Turn on Do Not Disturb",
    "toggle_off": "Turn off Do Not Disturb",
    "inbox_title": "RicePop inbox · current session",
    "refresh_inbox": "Refresh RicePop inbox",
    "verified_info": "Only messages from this verified RiceBowl notification host are shown. They are not saved by RiceSpice.",
    "truncated": "Showing at most 64 entries per section. Refresh to check for changes.",
    "active": "Active notifications",
    "history": "Previous notifications",
    "empty_active": "No active notifications.",
    "empty_history": "No notification history.",
    "unknown_app": "Unknown application",
    "untitled": "(untitled)",
    "dismiss": "Dismiss",
    "accessible_action": "{action} notification from {app}: {summary}",
    "owner_changed": "Notification host changed; verifying RicePop owner",
    "host_unavailable": "RicePop notification host disconnected. Previous messages were removed. Refresh after reconnection.",
    "queued": "RicePop inbox queued until the current request completes",
    "live_unavailable": "Live notification updates unavailable; use Refresh RicePop inbox",
    "appearance_title": "RicePop banner appearance · next full Wayland login",
    "appearance_info": "These choices never modify XFCE notifications or a running Mako instance. Only the RiceBowl-owned host reads them at login.",
    "appearance_unavailable": "Saved RicePop appearance unavailable: {error}",
    "font": "Notification font",
    "font_size": "Font size",
    "duration": "Default banner duration",
    "app_timeout": "Follow application / no default timeout",
    "seconds": "{count} seconds",
    "max_visible": "Maximum visible banners",
    "found_fonts": "{count} installed TrueType font families available",
    "find_fonts": "Find installed TrueType fonts",
    "save_appearance": "Save RicePop appearance for next login",
}
_DE = {
    "intro": "Nicht stören blendet neue Benachrichtigungsbanner aus. Aktuelle und frühere RicePop-Meldungen bleiben erhalten.",
    "owner_info": "Diese Einstellung ist nur verfügbar, wenn die vollständige RiceBowl-Wayland-Sitzung ihren Mako-Benachrichtigungsdienst besitzt.",
    "refresh_state": "Benachrichtigungsstatus aktualisieren",
    "show_inbox": "RicePop-Posteingang anzeigen",
    "dnd_on": "Nicht stören: ein",
    "dnd_off": "Nicht stören: aus",
    "toggle_on": "Nicht stören aktivieren",
    "toggle_off": "Nicht stören deaktivieren",
    "inbox_title": "RicePop-Posteingang · aktuelle Sitzung",
    "refresh_inbox": "RicePop-Posteingang aktualisieren",
    "verified_info": "Nur Meldungen dieses verifizierten RiceBowl-Dienstes werden angezeigt. RiceSpice speichert sie nicht.",
    "truncated": "Pro Bereich werden höchstens 64 Einträge angezeigt. Zum Prüfen erneut aktualisieren.",
    "active": "Aktive Benachrichtigungen",
    "history": "Frühere Benachrichtigungen",
    "empty_active": "Keine aktiven Benachrichtigungen.",
    "empty_history": "Kein Benachrichtigungsverlauf.",
    "unknown_app": "Unbekannte Anwendung",
    "untitled": "(ohne Titel)",
    "dismiss": "Schließen",
    "accessible_action": "{action} – Benachrichtigung von {app}: {summary}",
    "owner_changed": "Benachrichtigungsdienst gewechselt; RicePop prüft den Besitzer",
    "host_unavailable": "RicePop-Benachrichtigungsdienst getrennt. Vorherige Meldungen wurden entfernt. Nach der Wiederverbindung aktualisieren.",
    "queued": "RicePop-Posteingang öffnet nach Abschluss der laufenden Anfrage",
    "live_unavailable": "Live-Aktualisierung nicht verfügbar; RicePop-Posteingang manuell aktualisieren",
    "appearance_title": "RicePop-Banner · nächste vollständige Wayland-Anmeldung",
    "appearance_info": "Diese Auswahl verändert weder XFCE-Benachrichtigungen noch einen laufenden Mako-Dienst. Nur RiceBowls eigener Dienst liest sie beim Anmelden.",
    "appearance_unavailable": "Gespeicherte RicePop-Darstellung nicht verfügbar: {error}",
    "font": "Benachrichtigungsschrift",
    "font_size": "Schriftgröße",
    "duration": "Standarddauer der Banner",
    "app_timeout": "Anwendungsvorgabe / keine Standarddauer",
    "seconds": "{count} Sekunden",
    "max_visible": "Maximal sichtbare Banner",
    "found_fonts": "{count} installierte TrueType-Schriftfamilien verfügbar",
    "find_fonts": "Installierte TrueType-Schriften suchen",
    "save_appearance": "RicePop-Darstellung für nächste Anmeldung speichern",
}

if set(_EN) != set(_DE):
    raise RuntimeError("Incomplete RicePop translation catalog")

# Do not trust arbitrary environment text as a language code or path.
_LOCALE = re.compile(r"^[A-Za-z]{1,8}(?:[_-][A-Za-z0-9]{1,8})?(?:\.[A-Za-z0-9_-]{1,32})?(?:@[A-Za-z0-9_-]{1,32})?$")


def language(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        raw = values.get(variable, "")
        if not isinstance(raw, str) or not raw:
            continue
        first = raw.split(":", 1)[0]
        if len(first) > 96 or not _LOCALE.fullmatch(first):
            return "en"
        return "de" if first.split("_", 1)[0].split("-", 1)[0].lower() == "de" else "en"
    return "en"


def text(key: str, **fields: object) -> str:
    catalog = _DE if language() == "de" else _EN
    return catalog[key].format(**fields)
