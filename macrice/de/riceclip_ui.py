"""On-demand GTK3 history window; inherits the selected RiceBowl GTK theme."""

from __future__ import annotations

from typing import Callable


def show(request: Callable[..., dict[str, object]]) -> None:
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError("RiceClip requires python3-gi and GTK3 for its history window") from exc

    window = Gtk.Window(title="RiceClip · Clipboard history")
    window.set_default_size(660, 480)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("destroy", Gtk.main_quit)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_border_width(16)
    window.add(outer)

    heading = Gtk.Label()
    heading.set_markup("<b>RiceClip</b>  ·  private session history")
    heading.set_xalign(0)
    outer.pack_start(heading, False, False, 0)

    search = Gtk.SearchEntry()
    search.set_placeholder_text("Search copied text, links or images…")
    search.set_tooltip_text("Ctrl+F to search; Enter to copy the selected item")
    outer.pack_start(search, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    outer.pack_start(scroll, True, True, 0)
    listing = Gtk.ListBox()
    listing.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scroll.add(listing)

    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    outer.pack_start(controls, False, False, 0)
    copy_button = Gtk.Button(label="Copy back")
    pin_button = Gtk.Button(label="Pin")
    refresh_button = Gtk.Button(label="Refresh")
    clear_button = Gtk.Button(label="Clear history")
    pause_button = Gtk.ToggleButton(label="Pause capture")
    for button in (copy_button, pin_button, refresh_button, clear_button, pause_button):
        controls.pack_start(button, False, False, 0)
    status = Gtk.Label(label="History stays in RAM. Closing this window does not stop recording.")
    status.set_xalign(0)
    status.set_line_wrap(True)
    outer.pack_start(status, False, False, 0)

    all_items: list[dict[str, object]] = []
    updating_pause = False

    def selection() -> dict[str, object] | None:
        row = listing.get_selected_row()
        return next((item for item in all_items if item["id"] == getattr(row, "item_id", None)), None)

    def controls_state(*_args: object) -> None:
        selected = selection()
        copy_button.set_sensitive(selected is not None)
        pin_button.set_sensitive(selected is not None)
        pin_button.set_label("Unpin" if selected and selected["pinned"] else "Pin")

    def filter_row(row: object) -> bool:
        query = search.get_text().casefold().strip()
        return not query or query in getattr(row, "preview", "").casefold()

    listing.set_filter_func(filter_row)
    listing.connect("row-selected", controls_state)
    search.connect("search-changed", lambda *_: listing.invalidate_filter())

    def refresh(*_args: object) -> None:
        nonlocal all_items, updating_pause
        try:
            result = request("list")
            all_items = result["items"]
            for row in listing.get_children():
                listing.remove(row)
            for item in all_items:
                row = Gtk.ListBoxRow()
                row.item_id = item["id"]
                row.preview = str(item["preview"])
                label = Gtk.Label(label=("★  " if item["pinned"] else "") + row.preview,
                                  xalign=0)
                label.set_ellipsize(3)  # Pango.EllipsizeMode.END
                label.set_margin_top(10)
                label.set_margin_bottom(10)
                label.set_margin_start(12)
                label.set_margin_end(12)
                row.add(label)
                listing.add(row)
            listing.show_all()
            listing.invalidate_filter()
            updating_pause = True
            pause_button.set_active(bool(result["paused"]))
            updating_pause = False
            status.set_text(f"{len(all_items)} items · in memory only · nothing saved to disk")
            controls_state()
        except Exception as exc:
            status.set_text(str(exc))

    def copy(*_args: object) -> None:
        item = selection()
        if item:
            try:
                request("paste", id=item["id"])
                status.set_text("Restored to clipboard. Paste in the destination application.")
            except Exception as exc:
                status.set_text(str(exc))

    def pin(*_args: object) -> None:
        item = selection()
        if item:
            try:
                request("unpin" if item["pinned"] else "pin", id=item["id"])
                refresh()
            except Exception as exc:
                status.set_text(str(exc))

    def clear(*_args: object) -> None:
        dialog = Gtk.MessageDialog(transient_for=window, flags=Gtk.DialogFlags.MODAL,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text="Clear all clipboard history?")
        dialog.format_secondary_text("This permanently discards the in-memory items, including pins.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Clear history", Gtk.ResponseType.OK)
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            request("clear")
            refresh()

    def pause(*_args: object) -> None:
        if not updating_pause:
            try:
                request("pause" if pause_button.get_active() else "resume")
                refresh()
            except Exception as exc:
                status.set_text(str(exc))

    def on_key(_widget: object, event: object) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            window.destroy()
            return True
        if event.keyval == Gdk.KEY_f and event.state & Gdk.ModifierType.CONTROL_MASK:
            search.grab_focus()
            return True
        return False

    copy_button.connect("clicked", copy)
    pin_button.connect("clicked", pin)
    refresh_button.connect("clicked", refresh)
    clear_button.connect("clicked", clear)
    pause_button.connect("toggled", pause)
    listing.connect("row-activated", lambda *_: copy())
    window.connect("key-press-event", on_key)
    refresh()
    window.show_all()
    search.grab_focus()
    Gtk.main()
