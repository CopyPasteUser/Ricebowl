"""Unclipped, on-demand Frutiger tray windows for the shallow XFWM4 dock."""

from __future__ import annotations

_TRAY_CLASS = None


def flyout_geometry(anchor_x: int, anchor_width: int, popup_width: int,
                   popup_height: int, screen_x: int, screen_y: int,
                   screen_width: int, screen_height: int) -> tuple[int, int]:
    """Place the flyout above the bottom dock and clamp it to its monitor."""
    x = max(screen_x + 5, min(anchor_x + anchor_width - popup_width,
                              screen_x + screen_width - popup_width - 5))
    y = max(screen_y + 5, screen_y + screen_height - popup_height - 48)
    return x, y


def create_tray_window(anchor, Gtk, *, title="Aqua World controls"):
    """Offer the old Popover popup/popdown contract on an independent window.

    The GTK class is registered lazily: unused flyouts create no extra widgets.
    """
    global _TRAY_CLASS
    from gi.repository import Gdk, GLib

    if _TRAY_CLASS is None:
        class AquaTrayWindow(Gtk.Window):
            __gtype_name__ = "RiceBowlAquaTrayWindow"

            def __init__(self, anchor, title):
                super().__init__(type=Gtk.WindowType.TOPLEVEL)
                self._anchor = anchor
                self.set_title(title)
                self.set_decorated(False)
                self.set_resizable(False)
                self.set_skip_taskbar_hint(True)
                self.set_skip_pager_hint(True)
                self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
                self.set_keep_above(True)
                self.set_transient_for(anchor.get_toplevel())
                self.get_style_context().add_class("aqua-flyout")
                # WM focus handoffs during first map/present can emit a
                # transient focus-out before a new flyout becomes active.
                # Deferring dismissal and checking the presentation generation
                # prevents that stale signal from closing a newly opened menu.
                self._presentation = 0
                self.connect("focus-out-event", self._focus_out)
                self.connect("key-press-event", self._escape)
                self.connect("size-allocate", self._size_changed)

            def _focus_out(self, _window, _event):
                generation = self._presentation
                GLib.timeout_add(180, self._dismiss_if_unfocused, generation)
                return False

            def _dismiss_if_unfocused(self, generation):
                if (generation == self._presentation and self.get_visible()
                        and not self.is_active()):
                    self.hide()
                return False

            def _escape(self, _window, event):
                if event.keyval == Gdk.KEY_Escape:
                    self.popdown()
                    return True
                return False

            def _size_changed(self, *_args):
                if self.get_visible():
                    GLib.idle_add(self._place)

            def _place(self):
                anchor = self._anchor
                if not self.get_visible() or not anchor.get_realized():
                    return False
                parent = anchor.get_toplevel()
                if not parent.get_window():
                    return False
                offset = anchor.translate_coordinates(parent, 0, 0)
                if offset is None:
                    return False
                origin_x, _origin_y = parent.get_window().get_root_origin()
                screen = anchor.get_screen()
                monitor = screen.get_monitor_geometry(
                    screen.get_monitor_at_window(parent.get_window()))
                width, height = self.get_size()
                x, y = flyout_geometry(origin_x + offset[0],
                                       anchor.get_allocated_width(), width, height,
                                       monitor.x, monitor.y, monitor.width, monitor.height)
                if self.get_position() != (x, y):
                    self.move(x, y)
                return False

            def popup(self):
                self._presentation += 1
                self.show_all()
                self.present()
                self._place()
                GLib.idle_add(self._place)

            def popdown(self):
                self._presentation += 1
                self.hide()

        _TRAY_CLASS = AquaTrayWindow
    return _TRAY_CLASS(anchor, title)
