"""RiceSpice keeps keyboard focus on the page control across a write's re-render.

Found by the real-labwc keyboard pass (scripts/sg2_settings_gui_driver.py `keyboard`): after
Return/space on a settings control the page is rebuilt from the provider's state and every
widget, the focused one included, is destroyed, so GTK left the window with no focus and a
keyboard user was sent back to the start of the window after every action.
"""
import unittest

from tests.test_de_settings_gui_controls import _GuiCase


class FocusSurvivesRerender(_GuiCase):
    def focus(self):
        return self.window.window.get_focus()

    def test_focus_follows_the_toggled_control(self):
        self.open_page("network", "Disable Wi-Fi")
        before = self.button("Disable Wi-Fi")
        before.grab_focus()
        self.assertIs(self.focus(), before)
        self.click("Disable Wi-Fi")
        self.assertTrue(self.pump(lambda: self.button("Enable Wi-Fi") is not None))
        self.settle()
        after = self.button("Enable Wi-Fi")
        self.assertIsNot(after, before, "the page was not rebuilt")
        self.assertTrue(self.pump(lambda: self.focus() is after),
                        "keyboard focus was not restored to the rebuilt control: %r" % self.focus())
        self.assertEqual(len(self.fake.calls), 1)

    def test_navigating_to_another_page_does_not_move_focus_into_it(self):
        self.open_page("network", "Disable Wi-Fi")
        self.button("Disable Wi-Fi").grab_focus()
        self.window.show_page("bluetooth")
        self.assertTrue(self.pump(lambda: self.button("Turn Bluetooth off") is not None))
        self.settle()
        self.pump(lambda: False, limit=10)
        self.assertIsNone(self.focus(), "navigation must not steal focus into the new page")

    def test_a_control_that_became_unusable_hands_focus_to_the_nearest_one(self):
        self.open_page("network", "Disable Wi-Fi")
        controls = self.window._page_controls()
        target = self.button("Disable Wi-Fi")
        target.grab_focus()
        self.window._remember_focus(True)
        self.assertEqual(self.window._focus_return[2], controls.index(target))
        # The remembered control is no longer usable (a Save button after a save).
        target.set_sensitive(False)
        self.window.window.set_focus(None)
        self.window._restore_focus()
        focus = self.focus()
        self.assertIsNotNone(focus, "no control took the focus")
        self.assertTrue(focus.get_sensitive())
        self.assertIsNot(focus, target)

    def test_a_focus_the_user_already_moved_is_respected(self):
        self.open_page("network", "Disable Wi-Fi")
        self.button("Disable Wi-Fi").grab_focus()
        self.window._remember_focus(True)
        other = self.button("Refresh visible networks")
        other.grab_focus()
        self.window._restore_focus()
        self.assertIs(self.focus(), other)


if __name__ == "__main__":
    unittest.main()
