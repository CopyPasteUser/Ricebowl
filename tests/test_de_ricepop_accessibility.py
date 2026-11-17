"""Screen-reader names for explicitly opened RicePop notifications.

No GTK display or user D-Bus is needed: model the same accessible object
contract GTK3 exposes to AT-SPI and exercise the actual RiceSpice renderer.
"""

import unittest
from types import SimpleNamespace

from macrice.de import settings


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


class RicePopAccessibilityTests(unittest.TestCase):
    def _render(self, snapshot):
        buttons = {}
        page = SimpleNamespace(
            content=None, page="notifications", _ricepop_focus_buttons={},
            _ricepop_inbox_widgets=(), _request_ricepop_inbox=lambda: None,
            _show_content=lambda: None,
            _text=lambda *_args, **_kwargs: None,
        )

        def button(label, _callback, **_kwargs):
            result = FakeButton(label)
            buttons[label] = result
            return result

        page._button = button
        # Rendering tests model a real view, but do not trigger a private read.
        page.closed = False
        page.busy = False
        page._ricepop_open_pending = False
        page._open_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._open_ricepop_inbox(page))
        settings.RiceSpiceWindow._render_notification_inbox(page, snapshot)
        return buttons

    def test_same_app_messages_have_distinct_at_spi_action_names(self):
        snapshot = {
            "owner_pid": 55, "history": [], "truncated": False,
            "active": [
                {"id": 2, "app_name": "Mail", "summary": "New message",
                 "body": "Sensitive body A", "urgency": "normal",
                 "actions": [{"key": "reply", "label": "Reply"}]},
                {"id": 3, "app_name": "Mail", "summary": "Calendar invite",
                 "body": "Sensitive body B", "urgency": "normal",
                 "actions": [{"key": "reply", "label": "Reply"}]},
            ],
        }
        buttons = self._render(snapshot)
        first = buttons["Reply · Mail · #2"].accessible_name
        second = buttons["Reply · Mail · #3"].accessible_name
        self.assertEqual(first, "Reply notification from Mail: New message")
        self.assertEqual(second, "Reply notification from Mail: Calendar invite")
        self.assertNotEqual(first, second)
        self.assertEqual(buttons["Dismiss · Mail · #2"].accessible_name,
                         "Dismiss notification from Mail: New message")
        self.assertNotIn("Sensitive body A", " ".join(
            button.accessible_name for button in buttons.values()))
        self.assertNotIn("Sensitive body B", " ".join(
            button.accessible_name for button in buttons.values()))
        self.assertEqual(buttons["Refresh RicePop inbox"].accessible_name,
                         "Refresh RicePop inbox")

    def test_unicode_and_read_only_history_never_create_extra_actions(self):
        snapshot = {
            "owner_pid": 55, "truncated": False,
            "active": [{"id": 4, "app_name": "Messages",
                        "summary": "👩‍💻 Témoignage", "body": "",
                        "urgency": "normal", "actions": []}],
            "history": [{"id": 5, "app_name": "Messages",
                         "summary": "Private old notification", "body": "",
                         "urgency": "normal"}],
        }
        buttons = self._render(snapshot)
        self.assertEqual(buttons["Dismiss · Messages · #4"].accessible_name,
                         "Dismiss notification from Messages: 👩‍💻 Témoignage")
        self.assertFalse(any("#5" in label for label in buttons))

    def test_mock_buttons_without_atk_do_not_break_headless_unit_contract(self):
        self.assertIsNone(
            settings._ricepop_set_accessible_name(None, "Dismiss", "Mail", "Inbox"))
        settings._ricepop_set_accessible_name(
            object(), "Dismiss", "Mail", "Inbox")


if __name__ == "__main__":
    unittest.main()
