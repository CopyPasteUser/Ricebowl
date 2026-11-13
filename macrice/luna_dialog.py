"""One consistent, movable title bar for RiceBowl-owned XP Luna dialogs.

XFWM4 may omit decorations for windows transient to a DOCK.  These are normal
WM-managed GTK3 windows with a small client-drawn XP caption, not an alternate
window manager.  Other rice profiles continue using their existing dialogs.
"""

from __future__ import annotations

from .rice_windows import configure_settings_window, draggable_caption


def uses_native_wayland_decoration(Gdk) -> bool:
    """Ask GTK's chosen display backend, never infer from DISPLAY variables."""
    try:
        display = Gdk.Display.get_default()
        name = display.get_name() if display is not None else ""
    except (AttributeError, RuntimeError):
        return False
    return isinstance(name, str) and name.startswith("wayland")


def attach_luna_dialog_chrome(dialog, Gtk, Gdk, *, role: str, title: str,
                              close_response: int, resizable: bool = False):
    """Attach a caption and return the content box below it.

    The close control emits a GTK dialog response, so modal ``run()`` callers
    and non-modal ``response`` handlers retain their original semantics.
    """
    configure_settings_window(dialog, Gdk, role=role, resizable=resizable)
    dialog.get_style_context().add_class("luna-owned-dialog")

    content = dialog.get_content_area()
    content.set_border_width(0)
    content.set_spacing(0)
    if uses_native_wayland_decoration(Gdk):
        # labwc owns the sole titlebar, move/maximize and close controls.
        # Never stack a client caption below the compositor decoration.
        dialog.set_decorated(True)
        dialog._luna_caption = None
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.pack_start(body, True, True, 0)
        return body

    # Legacy XFWM DOCK-transient requires its existing single client caption.
    dialog.set_decorated(False)
    caption = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    caption.get_style_context().add_class("luna-control-caption")
    caption.pack_start(draggable_caption(
        dialog, Gtk.Label(label=title, xalign=0), Gtk, Gdk,
        maximizable=resizable), True, True, 0)

    close = Gtk.Button(label="×")
    close.get_style_context().add_class("luna-control-close")
    close.get_accessible().set_name("Close " + title)
    close.connect("clicked", lambda _button: dialog.response(close_response))
    caption.pack_end(close, False, False, 0)
    content.pack_start(caption, False, False, 0)
    dialog._luna_caption = caption

    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    content.pack_start(body, True, True, 0)
    return body
