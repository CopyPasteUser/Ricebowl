"""Regression coverage for client-owned XP dialogs under the XFWM DOCK parent."""

import unittest
from unittest import mock

from macrice.luna_dialog import attach_luna_dialog_chrome, uses_native_wayland_decoration


class LunaDialogChromeTests(unittest.TestCase):
    def test_fixed_dialog_has_movable_caption_and_safe_close_response(self):
        dialog = mock.Mock()
        gtk = mock.Mock()
        caption, body = mock.Mock(), mock.Mock()
        gtk.Box.side_effect = (caption, body)
        gtk.Orientation.HORIZONTAL = "horizontal"
        gtk.Orientation.VERTICAL = "vertical"
        gtk.Label.return_value = mock.Mock()
        close = gtk.Button.return_value
        gdk = mock.Mock()

        result = attach_luna_dialog_chrome(
            dialog, gtk, gdk, role="ricebowl-xp-run", title="Run",
            close_response=gtk.ResponseType.CANCEL)

        self.assertIs(result, body)
        self.assertIs(dialog._luna_caption, caption)
        dialog.set_type_hint.assert_called_once_with(gdk.WindowTypeHint.NORMAL)
        dialog.set_role.assert_called_once_with("ricebowl-xp-run")
        dialog.set_decorated.assert_called_once_with(False)
        dialog.set_resizable.assert_called_once_with(False)
        dialog.get_style_context().add_class.assert_called_once_with("luna-owned-dialog")
        caption.get_style_context().add_class.assert_called_once_with("luna-control-caption")
        close.get_accessible().set_name.assert_called_once_with("Close Run")
        close.connect.call_args.args[1](None)
        dialog.response.assert_called_once_with(gtk.ResponseType.CANCEL)

    def test_native_wayland_delegates_titlebar_entirely_to_window_manager(self):
        dialog, gtk, gdk = mock.Mock(), mock.Mock(), mock.Mock()
        body = gtk.Box.return_value
        gdk.Display.get_default.return_value.get_name.return_value = "wayland-0"
        self.assertTrue(uses_native_wayland_decoration(gdk))
        result = attach_luna_dialog_chrome(
            dialog, gtk, gdk, role="ricebowl-xp-help-center",
            title="Help and Support Center", close_response=21, resizable=True)
        self.assertIs(result, body)
        self.assertIsNone(dialog._luna_caption)
        dialog.set_decorated.assert_called_once_with(True)
        gtk.Box.assert_called_once_with(
            orientation=gtk.Orientation.VERTICAL, spacing=0)
        gtk.EventBox.assert_not_called()
        dialog.get_content_area().pack_start.assert_called_once_with(
            body, True, True, 0)
        gdk.Display.get_default.return_value.get_name.return_value = ":0"
        self.assertFalse(uses_native_wayland_decoration(gdk))

    def test_help_center_remains_resizable_with_keyboard_draggable_caption(self):
        dialog = mock.Mock()
        gtk = mock.Mock()
        gtk.Box.side_effect = (mock.Mock(), mock.Mock())
        gdk = mock.Mock()
        attach_luna_dialog_chrome(dialog, gtk, gdk, role="ricebowl-xp-help-center",
                                  title="Help and Support Center", close_response=21,
                                  resizable=True)
        dialog.set_resizable.assert_called_once_with(True)
        gtk.EventBox.return_value.set_can_focus.assert_called_once_with(True)
        gtk.EventBox.return_value.connect.assert_any_call(
            "key-press-event", mock.ANY)


if __name__ == "__main__":
    unittest.main()
