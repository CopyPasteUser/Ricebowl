"""RicePop localization and privacy contracts, independent of GTK/D-Bus."""

import os
import string
import unittest
from types import SimpleNamespace
from unittest import mock

from macrice.de import ricepop_i18n, settings


class FakeButton:
    def __init__(self, label):
        self.label = label
        self.accessible_name = label

    def get_accessible(self):
        return self

    def set_name(self, value):
        self.accessible_name = value

    def is_focus(self):
        return False


class RicePopLocaleTests(unittest.TestCase):
    def test_language_precedence_fallback_and_malformed_environment(self):
        language = ricepop_i18n.language
        self.assertEqual(language({}), "en")
        self.assertEqual(language({"LANG": "C.UTF-8"}), "en")
        self.assertEqual(language({"LANG": "de_DE.UTF-8"}), "de")
        self.assertEqual(language({"LANG": "en_US", "LANGUAGE": "de_DE:en_US"}), "de")
        self.assertEqual(language({"LANGUAGE": "de", "LC_MESSAGES": "en_GB"}), "en")
        self.assertEqual(language({"LC_ALL": "C", "LANGUAGE": "de"}), "en")
        self.assertEqual(language({"LC_ALL": "de_CH.UTF-8", "LANG": "en_US"}), "de")
        self.assertEqual(language({"LC_MESSAGES": "de_DE@euro"}), "de")
        self.assertEqual(language({"LC_ALL": "de_DE;inject"}), "en")
        self.assertEqual(language({"LANGUAGE": "de:" + "X" * 500}), "de")
        self.assertEqual(language({"LC_ALL": None}), "en")

    def test_catalog_is_complete_and_has_identical_named_fields(self):
        self.assertEqual(set(ricepop_i18n._EN), set(ricepop_i18n._DE))
        fmt = string.Formatter()
        for key in ricepop_i18n._EN:
            source = {field for _, field, _, _ in fmt.parse(ricepop_i18n._EN[key])
                      if field is not None}
            target = {field for _, field, _, _ in fmt.parse(ricepop_i18n._DE[key])
                      if field is not None}
            with self.subTest(key=key):
                self.assertEqual(source, target)
                self.assertLess(len(ricepop_i18n._DE[key]), 400)

    def test_accessibility_action_translation_keeps_private_body_and_id_out(self):
        with mock.patch.dict(os.environ, {"LC_ALL": "de_DE.UTF-8"}, clear=True):
            name = settings._ricepop_accessible_action_name(
                "Antworten", "Mail", "Kalender – 👩‍💻")
            self.assertEqual(name, "Antworten – Benachrichtigung von Mail: Kalender – 👩‍💻")
            self.assertNotIn("123456", name)
            self.assertEqual(ricepop_i18n.text(
                "accessible_action", action="Öffnen", app="A{b}", summary="C{d}"),
                "Öffnen – Benachrichtigung von A{b}: C{d}")

    def _render(self, locale):
        visible, buttons = [], {}
        page = SimpleNamespace(
            page="notifications", content=None, closed=False, busy=False,
            _ricepop_focus_buttons={}, _ricepop_inbox_widgets=(),
            _ricepop_open_pending=False, _request_ricepop_inbox=lambda: None,
            _show_content=lambda: None, _text=lambda text, **_kw: visible.append(text),
        )
        page._open_ricepop_inbox = lambda: settings.RiceSpiceWindow._open_ricepop_inbox(page)
        def button(label, _callback, **_kwargs):
            obj = FakeButton(label)
            buttons[label] = obj
            return obj
        page._button = button
        payload = {
            "owner_pid": 47, "truncated": False, "history": [],
            "active": [{"id": 12, "app_name": "Mail", "summary": "Neuer Termin",
                        "body": "Vertraulicher Inhalt", "urgency": "normal",
                        "actions": [{"key": "reply", "label": "Reply"}]}],
        }
        with mock.patch.dict(os.environ, {"LC_ALL": locale}, clear=True):
            settings.RiceSpiceWindow._render_notification_inbox(page, payload)
        return visible, buttons

    def test_real_renderer_uses_localized_labels_but_never_translates_app_actions(self):
        visible, buttons = self._render("de_DE.UTF-8")
        self.assertIn("RicePop-Posteingang · aktuelle Sitzung", visible)
        self.assertIn("Aktive Benachrichtigungen (1)", visible)
        self.assertIn("Keine aktiven Benachrichtigungen.", ricepop_i18n._DE.values())
        self.assertIn("RicePop-Posteingang aktualisieren", buttons)
        self.assertIn("Schließen · Mail · #12", buttons)
        self.assertIn("Reply · Mail · #12", buttons)
        self.assertEqual(
            buttons["Schließen · Mail · #12"].accessible_name,
            "Schließen – Benachrichtigung von Mail: Neuer Termin")
        self.assertNotIn("Vertraulicher Inhalt", " ".join(
            button.accessible_name for button in buttons.values()))

    def test_disconnected_owner_is_not_rendered_as_empty_or_actionable(self):
        # A lost DBus owner is not a successfully verified empty inbox.
        for locale, warning in (
                ("C.UTF-8", "RicePop notification host disconnected."),
                ("de_DE.UTF-8", "RicePop-Benachrichtigungsdienst getrennt.")):
            visible, buttons = self._render_disconnected(locale)
            with self.subTest(locale=locale):
                self.assertTrue(any(warning in line for line in visible))
                self.assertFalse(any("No active notifications." in line for line in visible))
                self.assertFalse(any("No notification history." in line for line in visible))
                self.assertFalse(any("Keine aktiven Benachrichtigungen." in line
                                     for line in visible))
                self.assertFalse(any("Kein Benachrichtigungsverlauf." in line
                                     for line in visible))
                self.assertEqual(len(buttons), 1)
                self.assertNotIn("Dismiss", " ".join(buttons))

    def _render_disconnected(self, locale):
        visible, buttons = [], {}
        page = SimpleNamespace(
            page="notifications", content=None, closed=False, busy=False,
            _ricepop_focus_buttons={}, _ricepop_inbox_widgets=(),
            _ricepop_open_pending=False, _request_ricepop_inbox=lambda: None,
            _show_content=lambda: None,
            _text=lambda text, **_kw: visible.append(text),
        )
        page._open_ricepop_inbox = lambda: settings.RiceSpiceWindow._open_ricepop_inbox(page)
        def button(label, _callback, **_kwargs):
            control = FakeButton(label)
            buttons[label] = control
            return control
        page._button = button
        with mock.patch.dict(os.environ, {"LC_ALL": locale}, clear=True):
            settings.RiceSpiceWindow._render_notification_inbox(page, {
                "owner_pid": None, "unavailable": True, "truncated": False,
                "active": [], "history": [],
            })
        return visible, buttons

    def test_english_rendering_remains_compatible(self):
        visible, buttons = self._render("C.UTF-8")
        self.assertIn("RicePop inbox · current session", visible)
        self.assertIn("Refresh RicePop inbox", buttons)
        self.assertEqual(
            buttons["Dismiss · Mail · #12"].accessible_name,
            "Dismiss notification from Mail: Neuer Termin")


if __name__ == "__main__":
    unittest.main()
