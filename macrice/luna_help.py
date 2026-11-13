"""Native XP Luna Help and Support plus read-only Linux System Properties.

All instructional content is RiceBowl-owned; system facts use existing bounded
/proc and /sys collectors, never Windows registry/driver terminology as fact.
"""

from __future__ import annotations

from .classic98_system import collect_system, report_sections


TOPICS = {
    "Getting started": (
        "This is Linux running the RiceBowl XP Luna desktop. Start opens "
        "installed applications, documents and real system settings. "
        "Press Super to open Start and Right Ctrl for Control Panel."),
    "Start menu": (
        "Search installed applications from Start. All Programs groups actual "
        "Linux launchers. Right-click an application to pin or unpin it from "
        "Start favorites and reorder your shortcuts. Open Taskbar and Start "
        "Menu Properties to choose how many recent programs appear."),
    "Taskbar and Quick Launch": (
        "Quick Launch contains your pinned programs and Show Desktop. Running "
        "windows appear separately on the blue taskbar. Right-click a task "
        "for live window operations. When crowded, similar applications can "
        "be grouped. Right-click empty taskbar space for Properties."),
    "Connecting to networks": (
        "Click the network indicator to inspect the current connection and "
        "nearby Wi-Fi networks. Connecting requires NetworkManager and appropriate "
        "permissions. The Bluetooth menu uses BlueZ via bluetoothctl or system "
        "D-Bus; rfkill only reports radio block state."),
    "Sound and battery": (
        "Click the speaker icon to adjust real output volume, mute or select "
        "a supported audio device. Battery and brightness controls are offered "
        "only if the hardware and system backend expose them."),
    "Files and the desktop": (
        "Your files stay in Linux directories. Thunar currently remains the "
        "functional explorer. RiceExplorer is being developed separately. "
        "You can explicitly add four XP desktop shortcuts via the empty-taskbar "
        "context menu; XFDesktop manages their drag, trash and context actions."),
    "Accessibility and recovery": (
        "Use Control Panel > Accessibility Options for installed Linux input "
        "and display settings. RiceBowl's changes can be rolled back with "
        "'macrice rice restore'. Native Linux utilities and other rice profiles "
        "are not replaced by the XP theme."),
}


# Only destinations provided by the existing XP Control Panel. Topic text
# without a supported destination remains Help-only, not an inert fake link.
TOPIC_DESTINATIONS = {
    "Connecting to networks": "Network and Internet Connections",
    "Sound and battery": "Sounds, Speech, and Audio Devices",
    "Files and the desktop": "Appearance and Themes",
    "Accessibility and recovery": "Accessibility Options",
}


def search_topics(text: str) -> tuple[str, ...]:
    query = text.strip().casefold()
    return tuple(key for key, value in TOPICS.items()
                 if query and (query in key.casefold() or query in value.casefold()))


def show_system(shell, Gtk):
    """XP-styled tabbed system details; refresh is on demand, not a daemon."""
    existing = getattr(shell, "_luna_system_dialog", None)
    if existing is not None:
        existing.present()
        return existing
    parent = getattr(shell, "_luna_help_dialog", None) or shell.bar
    dialog = Gtk.Dialog(title="System Properties", transient_for=parent)
    dialog.set_default_size(560, 422)
    dialog.get_style_context().add_class("luna-help-window")
    dialog.add_button("Refresh", Gtk.ResponseType.APPLY)
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    from gi.repository import Gdk
    from .luna_dialog import attach_luna_dialog_chrome

    area = attach_luna_dialog_chrome(
        dialog, Gtk, Gdk, role="ricebowl-xp-system-properties",
        title="System Properties", close_response=Gtk.ResponseType.CLOSE)
    area.set_border_width(12)
    area.set_spacing(9)
    heading = Gtk.Label(label="RiceBowl XP · System Properties (Linux)", xalign=0)
    heading.get_style_context().add_class("luna-properties-heading")
    area.pack_start(heading, False, False, 0)
    tabs = Gtk.Notebook()
    area.pack_start(tabs, True, True, 0)
    buffers = {}
    for name in ("General", "Device Manager", "Performance"):
        scroller = Gtk.ScrolledWindow()
        text = Gtk.TextView()
        text.set_editable(False)
        text.set_cursor_visible(False)
        text.set_wrap_mode(Gtk.WrapMode.WORD)
        text.set_left_margin(12)
        text.set_right_margin(12)
        text.set_top_margin(12)
        scroller.add(text)
        tabs.append_page(scroller, Gtk.Label(label=name))
        buffers[name] = text.get_buffer()

    def refresh():
        sections = report_sections(collect_system(), rice_name="Windows XP Luna")
        for title, buffer in buffers.items():
            buffer.set_text(sections[title])

    def respond(_dialog, action):
        if action == Gtk.ResponseType.APPLY:
            refresh()
        else:
            _dialog.destroy()

    dialog.connect("response", respond)
    dialog.connect("destroy", lambda *_args: setattr(shell, "_luna_system_dialog", None))
    shell._luna_system_dialog = dialog
    refresh()
    dialog.show_all()
    # A transient inherited from the XP DOCK otherwise gets placed directly
    # above/beside the taskbar by XFWM, sometimes clipping the bottom controls.
    from .luna_taskbar_settings import center_on_workarea

    dialog.move(*center_on_workarea(shell._desktop_rect(), *dialog.get_size()))
    return dialog


def show_help(shell, Gtk):
    """Searchable, navigable Help Center with real settings destinations."""
    shell._hide_menu()
    existing = getattr(shell, "_luna_help_dialog", None)
    if existing is not None:
        existing.present()
        return existing
    dialog = Gtk.Dialog(title="Help and Support Center", transient_for=shell.bar)
    dialog.set_default_size(720, 496)
    dialog.get_style_context().add_class("luna-help-window")
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    from gi.repository import Gdk
    from .luna_dialog import attach_luna_dialog_chrome

    area = attach_luna_dialog_chrome(
        dialog, Gtk, Gdk, role="ricebowl-xp-help-center",
        title="Help and Support Center", close_response=Gtk.ResponseType.CLOSE,
        resizable=True)
    area.set_spacing(8)
    area.set_border_width(10)
    banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    banner.get_style_context().add_class("luna-help-banner")
    title = Gtk.Label(label="Help and Support Center", xalign=0)
    title.get_style_context().add_class("luna-help-title")
    banner.pack_start(title, False, False, 0)
    banner.pack_start(Gtk.Label(label="Find answers and open real Linux settings", xalign=0),
                      False, False, 0)
    area.pack_start(banner, False, False, 0)

    toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
    back = Gtk.Button(label="◂ Back")
    forward = Gtk.Button(label="Forward ▸")
    forward.set_sensitive(False)
    forward.get_accessible().set_name("Next Help topic")
    back.get_accessible().set_name("Previous Help topic")
    home = Gtk.Button(label="Home")
    system = Gtk.Button(label="System Information…")
    for widget in (back, forward, home):
        toolbar.pack_start(widget, False, False, 0)
    toolbar.pack_end(system, False, False, 0)
    area.pack_start(toolbar, False, False, 0)

    body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    body.set_position(238)
    area.pack_start(body, True, True, 0)
    navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    navigation.get_style_context().add_class("luna-help-navigation")
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Search Help…")
    search.get_accessible().set_name("Search XP help topics")
    navigation.pack_start(search, False, False, 0)
    left_scroll = Gtk.ScrolledWindow()
    listing = Gtk.ListBox()
    listing.set_activate_on_single_click(True)
    left_scroll.add(listing)
    navigation.pack_start(left_scroll, True, True, 0)
    body.pack1(navigation, resize=False, shrink=False)

    article = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
    article.set_border_width(14)
    article.get_style_context().add_class("luna-help-article")
    topic_title = Gtk.Label(xalign=0)
    topic_title.get_style_context().add_class("luna-properties-heading")
    article.pack_start(topic_title, False, False, 0)
    text_scroll = Gtk.ScrolledWindow()
    text = Gtk.TextView()
    text.set_editable(False)
    text.set_cursor_visible(False)
    text.set_wrap_mode(Gtk.WrapMode.WORD)
    text_scroll.add(text)
    article.pack_start(text_scroll, True, True, 0)
    related = Gtk.Button(label="Open related Control Panel category…")
    related.get_accessible().set_name("Open the related Control Panel category")
    related.get_style_context().add_class("luna-help-related")
    article.pack_start(related, False, False, 0)
    body.pack2(article, resize=True, shrink=False)

    history = ["Getting started"]
    position = 0

    def display():
        name = history[position]
        topic_title.set_text(name)
        text.get_buffer().set_text(TOPICS[name])
        back.set_sensitive(position > 0)
        forward.set_sensitive(position + 1 < len(history))
        category = TOPIC_DESTINATIONS.get(name)
        available = (category is not None
                     and callable(getattr(shell, "luna_control_show_category", None)))
        related.set_sensitive(available)
        related.set_tooltip_text(
            "Navigate to the installed Linux settings tasks for " + category
            if available else "No additional Control Panel action for this topic")

    def visit(name):
        nonlocal position
        if name == history[position] or name not in TOPICS:
            return
        del history[position + 1:]
        history.append(name)
        position += 1
        display()

    def refresh(_widget=None):
        for child in listing.get_children():
            listing.remove(child)
        matches = search_topics(search.get_text()) if search.get_text().strip() else tuple(TOPICS)
        for name in matches:
            row = Gtk.ListBoxRow()
            row.topic = name
            label = Gtk.Label(label=name, xalign=0)
            label.set_margin_top(7)
            label.set_margin_bottom(7)
            label.set_margin_start(7)
            row.add(label)
            listing.add(row)
        if not matches:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.add(Gtk.Label(label="No matching help topics"))
            listing.add(row)
        listing.show_all()

    def go_back(_button):
        nonlocal position
        if position > 0:
            position -= 1
            display()

    def go_forward(_button):
        nonlocal position
        if position + 1 < len(history):
            position += 1
            display()

    def open_related(_button):
        category = TOPIC_DESTINATIONS.get(history[position])
        callback = getattr(shell, "luna_control_show_category", None)
        if category is None or not callable(callback):
            return
        # Use the real existing Control Panel window and its allowlisted
        # category route; no duplicate Linux settings launcher or shell command.
        if not shell.actions.get_visible():
            shell._toggle_actions()
        if shell.actions.get_visible():
            callback(category)
            shell.actions.present()

    def key_press(_widget, event):
        if event.state & Gdk.ModifierType.MOD1_MASK:
            if event.keyval == Gdk.KEY_Left:
                go_back(None)
                return True
            if event.keyval == Gdk.KEY_Right:
                go_forward(None)
                return True
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (
                Gdk.KEY_f, Gdk.KEY_F):
            search.grab_focus()
            search.select_region(0, -1)
            return True
        if event.keyval == Gdk.KEY_Escape:
            if search.get_text():
                search.set_text("")
            else:
                dialog.response(Gtk.ResponseType.CLOSE)
            return True
        return False

    listing.connect("row-activated", lambda _list, row:
                    visit(row.topic) if hasattr(row, "topic") else None)
    search.connect("search-changed", refresh)
    back.connect("clicked", go_back)
    forward.connect("clicked", go_forward)
    related.connect("clicked", open_related)
    dialog.connect("key-press-event", key_press)
    home.connect("clicked", lambda _button: visit("Getting started"))
    system.connect("clicked", lambda _button: show_system(shell, Gtk))
    dialog.connect("response", lambda window, _response: window.destroy())
    dialog.connect("destroy", lambda *_args: setattr(shell, "_luna_help_dialog", None))
    shell._luna_help_dialog = dialog
    refresh()
    display()
    dialog.show_all()
    from .luna_taskbar_settings import center_on_workarea

    dialog.move(*center_on_workarea(shell._desktop_rect(), *dialog.get_size()))
    return dialog
