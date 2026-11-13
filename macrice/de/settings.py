"""On-demand RiceSpice GTK settings window for the experimental Wayland DE.

Real services are queried only when their page is opened or refreshed; this
program exits on close and does not replace a distribution settings daemon.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from macrice import display_guard
from macrice.riceware import media

from . import audio_devices, display_presets, display_restore, network_enrollment
from . import notifications, preferences, recipes, luna_panel_settings, luna_taskbar_settings
from . import settings_backend as backend, wayland_displays


SECTIONS = (
    ("network", "Network", "NetworkManager connectivity and Wi-Fi radio"),
    ("audio", "Sound", "Audio devices and media playback"),
    ("notifications", "Notifications", "RicePop alerts and Do Not Disturb"),
    ("bluetooth", "Bluetooth", "Adapter and paired devices"),
    ("displays", "Displays", "Monitors, scaling and arrangement"),
    ("input", "Input", "Pointer and keyboard preferences"),
    ("accessibility", "Accessibility", "Assistive preferences"),
    ("timezone", "Date & time", "System clock and timezone preferences"),
    ("power", "Power & security", "Lock and suspend via system services"),
    ("appearance", "Rice & appearance", "Next-login shell recipe selection"),
)


# Same native Linux backends, but Luna's familiar Control Panel category
# organization and layout. No XFCE configuration is changed from this view.
LUNA_SECTIONS = (
    ("appearance", "Appearance and Themes", "Choose the RiceBowl appearance for next login"),
    ("network", "Network and Internet Connections", "Real Wi-Fi radio and saved connections"),
    ("audio", "Sounds and Audio Devices", "Real output, input and player controls"),
    ("displays", "Display", "Wayland displays, scaling and safe rollback"),
    ("input", "Mouse and Keyboard", "Input settings for the next RiceBowl login"),
    ("bluetooth", "Bluetooth Devices", "Real adapter and paired devices"),
    ("power", "Performance and Maintenance", "Power profiles and session controls"),
    ("timezone", "Date, Time and Regional Options", "Time zone and time synchronization"),
    ("accessibility", "Accessibility Options", "Assistive preferences for next login"),
    ("notifications", "Notifications", "RicePop history and banner preferences"),
    ("taskbar", "Taskbar and Start Menu", "XP panel actions and notification area"),
)

LUNA_ICONS = {
    "appearance": "preferences-desktop-theme",
    "network": "network-workgroup",
    "audio": "audio-card",
    "displays": "video-display",
    "input": "input-mouse",
    "bluetooth": "bluetooth",
    "power": "preferences-system-power",
    "timezone": "preferences-system-time",
    "accessibility": "preferences-desktop-accessibility",
    "notifications": "preferences-desktop-notification",
    "taskbar": "preferences-desktop",
}




# Use RiceBowl's original Luna artwork, not host-dependent icon-theme names.
LUNA_ICON_FILES = {
    "appearance": "ricehub-luna-cp-appearance.svg",
    "network": "ricehub-luna-cp-network.svg",
    "audio": "ricehub-luna-cp-audio.svg",
    "displays": "ricehub-luna-task-video-display.svg",
    "input": "ricehub-luna-task-input-mouse.svg",
    "bluetooth": "ricehub-luna-task-bluetooth.svg",
    "power": "ricehub-luna-cp-performance.svg",
    "timezone": "ricehub-luna-cp-regional.svg",
    "accessibility": "ricehub-luna-cp-accessibility.svg",
    "notifications": "ricehub-luna-task-preferences-desktop-notification.svg",
    "taskbar": "ricehub-luna-task-preferences-system-windows.svg",
}
LUNA_ICON_DIR = (Path(__file__).resolve().parents[2] /
                 "assets/icons/RiceHub-Luna-Icons/scalable/apps")


# Luna's navigation is a separate presentation of the same service-backed pages.
# Keep these keys stable: CLI deep links and backend dispatch depend on them.
LUNA_GROUPS = (
    ("Appearance & desktop", ("appearance", "displays", "taskbar")),
    ("Hardware & connectivity", ("network", "audio", "bluetooth", "input")),
    ("System & accessibility", ("power", "timezone", "notifications", "accessibility")),
)

# Explorer-style XP overview. Every item is a real native settings page;
# categories are navigation only and do not execute service commands.
# Keep each destination in exactly one category and retain the public page IDs.
LUNA_CONTROL_CATEGORIES = (
    ("appearance", "Appearance and Themes", "appearance",
     "Desktop style, monitors and taskbar", ("appearance", "displays", "taskbar")),
    ("network", "Network and Internet Connections", "network",
     "Wi-Fi, saved connections and Bluetooth", ("network", "bluetooth")),
    ("sound", "Sounds, Speech, and Audio Devices", "audio",
     "Playback, recording and notifications", ("audio", "notifications")),
    ("hardware", "Mouse, Keyboard and Other Hardware", "input",
     "Pointer, keyboard and touchpad", ("input",)),
    ("maintenance", "Performance and Maintenance", "power",
     "Power profiles, date and time", ("power", "timezone")),
    ("accessibility", "Accessibility Options", "accessibility",
     "Make the desktop easier to use", ("accessibility",)),
)


def luna_category_pages(category: str) -> tuple[str, ...]:
    """Resolve only known native page IDs; a category cannot launch a command."""
    for key, _title, _icon, _help, pages in LUNA_CONTROL_CATEGORIES:
        if key == category:
            return pages
    raise ValueError("Unknown Control Panel category")


# Search only real destinations, but index the controls that users naturally
# look for instead of relying on long page names. Purely local, no I/O.
LUNA_SEARCH_HINTS = {
    "network": "wifi wlan ethernet vpn connections",
    "audio": "volume speaker microphone recording playback sounds speech",
    "displays": "monitor resolution scale scaling screen",
    "input": "mouse keyboard touchpad pointer hardware devices",
    "taskbar": "clock clock format time format 12h 24h 12-hour 24-hour tray start",
    "power": "battery suspend energy profile lock performance maintenance",
    "timezone": "clock synchronization ntp time zone",
    "notifications": "alerts banners do not disturb",
}


def luna_search_matches(query: str) -> tuple[str, ...]:
    """Match all user-entered words against real categories and supported tasks."""
    terms = query.strip().casefold().split()
    if not terms:
        return tuple(key for key, _title, _description in LUNA_SECTIONS)
    return tuple(
        key for key, title, description in LUNA_SECTIONS
        if all(term in " ".join((key, title, description,
                                LUNA_SEARCH_HINTS.get(key, ""))).casefold()
               for term in terms)
    )



def _gtk_modules():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gtk, Gdk, GLib


CSS = b"""
.ricespice-window { background: #eff3f7; color: #203249; }
.ricespice-nav { background: #182b43; padding: 16px 9px; }
.ricespice-brand { color: #dfeffa; font-size: 19px; font-weight: 700; margin: 9px 12px 19px; }
.ricespice-nav button { background: transparent; box-shadow: none; border: none;
  border-radius: 7px; color: #dce7ef; text-shadow: none; padding: 12px 13px; }
.ricespice-nav button:checked { background: #427daf; color: white; font-weight: 700; }
.ricespice-content { padding: 29px 32px; }
.ricespice-title { font-size: 25px; font-weight: 700; color: #1b354e; }
.ricespice-desc { color: #5b7288; margin-bottom: 16px; }
.ricespice-section { color: #294561; font-weight: 700; margin: 13px 0 5px; }
.ricespice-note { color: #65788b; }
.ricespice-action { background: #2b6697; color: #fff; padding: 9px 14px;
  border-radius: 6px; text-shadow: none; }
.ricespice-action:hover { background: #377eaf; }
.ricespice-state { padding: 13px 0 4px; color: #244c6e; }
"""

# Applied only to XP Luna. Other rices retain their existing appearance.
LUNA_CSS = b"""
.ricespice-luna.ricespice-window {
  background: #f8f8f5; color: #202636;
  font-family: "Liberation Sans", "Tahoma", sans-serif; font-size: 12px;
}
.ricespice-luna .luna-header {
  /* XP Explorer content banner, never a second window-manager caption. */
  background: #ffffff; border-bottom: 1px solid #a9bfdc;
  border-top: 3px solid #f2bb65; padding: 10px 18px 9px;
}
.ricespice-luna .luna-header-title {
  color: #174b8c; font-size: 16px; font-weight: bold;
  text-shadow: none;
}
.ricespice-luna .luna-header-subtitle {
  color: #526981; font-size: 11px;
}
.ricespice-luna .luna-toolbar {
  background: #f0eee8; padding: 5px 11px;
  border-bottom: 1px solid #a4b0c0;
  border-top: 1px solid #ffffff;
}
.ricespice-luna .luna-toolbar button {
  border: 1px solid #8ca7cb; border-radius: 3px;
  padding: 5px 11px; color: #164580; text-shadow: none;
  background-image: linear-gradient(to bottom, #ffffff, #dbe7f7);
}
.ricespice-luna .luna-toolbar button:hover {
  background: #d0e2fa; border-color: #447dc0;
}
.ricespice-luna .luna-breadcrumb { color: #355782; font-weight: bold; }
.ricespice-luna .luna-search {
  background: #ffffff; color: #1d2835;
  border: 1px solid #839cbf; border-radius: 3px;
  padding: 6px 8px;
}
.ricespice-luna .luna-side-scroll {
  background: #dce7f8; border-right: 1px solid #8199ba;
}
.ricespice-luna .ricespice-nav {
  background: #dce7f8; padding: 10px 9px 18px;
}
.ricespice-luna .ricespice-brand {
  color: #1b427d; font-size: 12px; font-weight: bold;
  margin: 1px 9px 11px;
}
.ricespice-luna .luna-nav-heading {
  color: #174a91; font-size: 11px; font-weight: bold;
  background: #c4d8f3; border-top: 1px solid #ffffff;
  border-bottom: 1px solid #9ab5da; padding: 5px 7px;
  margin: 12px 0 4px;
}
.ricespice-luna .ricespice-nav button {
  background: transparent; color: #1d417c; text-shadow: none;
  border: 1px solid transparent; border-radius: 3px;
  box-shadow: none; padding: 8px 8px; font-weight: normal;
}
.ricespice-luna .ricespice-nav button:hover {
  background: #d9e7fa; border-color: #a9c1e0;
}
.ricespice-luna .ricespice-nav button:checked {
  background-image: linear-gradient(to bottom, #4a83d3, #2e63b3);
  color: #ffffff; border-color: #1a4a95; font-weight: bold;
}
.ricespice-luna .ricespice-content { padding: 16px 19px; background: #ffffff; }
.ricespice-luna .ricespice-title {
  font-size: 21px; font-weight: bold; color: #153e80;
}
.ricespice-luna .ricespice-desc {
  color: #586577; margin-bottom: 10px;
}
.ricespice-luna .ricespice-section {
  color: #1c4e92; font-weight: bold; margin: 12px 0 5px;
}
.ricespice-luna .ricespice-note { color: #586577; }
.ricespice-luna .ricespice-state { color: #2a4b75; }
.ricespice-luna .luna-category-row {
  background: transparent; border: 1px solid transparent;
  box-shadow: none; border-radius: 0;
  padding: 8px 7px; text-shadow: none;
}
.ricespice-luna .luna-category-row:hover {
  background: #eaf3ff; border-color: #bbd1ed;
}
.ricespice-luna .luna-control-group {
  background: transparent; border: 1px solid transparent; padding: 8px 6px;
  border-radius: 0; box-shadow: none; text-shadow: none;
}
.ricespice-luna .luna-control-group:hover {
  background: #ecf3ff; border-color: #b5cbed;
}
.ricespice-luna .luna-classic-row { padding: 6px 5px; }
.ricespice-luna .luna-view-switch {
  background: transparent; box-shadow: none; border: none; border-radius: 2px;
  color: #154b97; text-decoration: underline; text-shadow: none;
  padding: 7px 8px;
}
.ricespice-luna .luna-view-switch:hover { background: #d8e6fa; }
.ricespice-luna .luna-control-group:focus,
.ricespice-luna .luna-view-switch:focus,
.ricespice-luna .luna-search:focus {
  outline: 2px solid #f0a23b; outline-offset: -2px;
}
.ricespice-luna button:focus {
  outline-style: solid; outline-color: #f0a23b; outline-width: 2px;
  outline-offset: -2px;
}
.ricespice-luna .luna-divider {
  background: #ccd6e3; margin-top: 11px; margin-bottom: 3px;
}
.ricespice-luna .luna-category-title {
  color: #1555a1; font-weight: bold; font-size: 13px;
}
.ricespice-luna .luna-category-detail {
  color: #5d6a77; font-size: 11px;
}
.ricespice-luna .ricespice-action {
  background-image: linear-gradient(to bottom, #fcfdff, #ccddf5);
  color: #173f79; text-shadow: none;
  border: 1px solid #7899c7; border-radius: 3px;
  box-shadow: inset 1px 1px #fff; padding: 7px 11px;
}
.ricespice-luna .ricespice-action:hover { background: #bdd5f9; }
/* Standalone Luna dialogs are siblings of RiceSpice, not descendants of
   its main content box. Reuse the era widgets without drawing a titlebar. */
.luna-owned-dialog {
  background-color: #ece9d8; color: #1d2531;
  font-family: "Liberation Sans", "Tahoma", sans-serif; font-size: 12px;
}
.luna-owned-dialog button {
  background-image: linear-gradient(to bottom, #fffefd, #e5e3d8);
  border: 1px solid #8993a2; border-radius: 3px;
  box-shadow: inset 1px 1px #ffffff;
  color: #252d3b; padding: 4px 11px; text-shadow: none;
}
.luna-owned-dialog button:hover { border-color: #4375ae; background: #f2f8ff; }
.luna-owned-dialog button:focus, .luna-owned-dialog entry:focus,
.luna-owned-dialog notebook tab:focus {
  outline: 2px solid #e9a343; outline-offset: -2px;
}
.luna-owned-dialog entry, .luna-owned-dialog textview {
  background-color: #ffffff; border: 1px solid #8c9aab;
  color: #273243;
}
.luna-owned-dialog notebook > header {
  background: #ece9d8; border-bottom: 1px solid #9eaabd;
}
.luna-owned-dialog notebook tab {
  padding: 5px 12px; background: #dbdacf;
  border: 1px solid #9da6b5; border-radius: 3px 3px 0 0;
}
.luna-owned-dialog notebook tab:checked { background: #ffffff; color: #173f7d; }
"""


class RiceSpiceWindow:
    def __init__(self, Gtk, Gdk, GLib, *, page: str = "network",
                 luna: bool = False):
        self.Gtk, self.Gdk, self.GLib = Gtk, Gdk, GLib
        self.luna = luna
        self.sections = LUNA_SECTIONS if luna else SECTIONS
        valid_pages = {section[0] for section in self.sections}
        if luna:
            valid_pages.add("home")
        if page not in valid_pages:
            raise backend.SettingsError("Unknown RiceSpice settings page")
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ricespice")
        self.worker_slots = threading.BoundedSemaphore(2)
        self.generation = 0
        self.busy = False
        self.closed = False
        self.page = "network"
        self._selecting_nav = False
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS + LUNA_CSS)
        if Gdk.Screen.get_default() is not None:
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.window = Gtk.Window(title=("Control Panel · RiceBowl Luna" if luna
                                        else "RiceSpice · System settings"))
        self.window.set_default_size(960 if luna else 810, 660 if luna else 580)
        self.window.set_size_request(580 if luna else 570, 450 if luna else 400)
        self.window.get_style_context().add_class("ricespice-window")
        if luna:
            self.window.get_style_context().add_class("ricespice-luna")
        self.window.connect("destroy", self._close)
        if luna:
            self.window.connect("key-press-event", self._luna_key_press)

        root = Gtk.Box(orientation=(Gtk.Orientation.VERTICAL if luna
                                     else Gtk.Orientation.HORIZONTAL))
        self.window.add(root)
        self.search_entry = None
        self.breadcrumb = None
        self.nav_groups = []
        self._luna_icon_cache = {}
        self._suppress_luna_search = False
        self.luna_view = "categories"
        self.luna_flow = None
        # Bounded, view-local Explorer-style history. Routes contain only
        # allowlisted page/category IDs and local search text; no commands.
        self.luna_history: list[tuple[str, str]] = []
        self.luna_history_index = -1
        self._luna_replaying = False
        self.luna_back = None
        self.luna_forward = None

        if luna:
            header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            header.get_style_context().add_class("luna-header")
            title = Gtk.Label(label="Choose a Control Panel task", xalign=0)
            title.get_style_context().add_class("luna-header-title")
            header.pack_start(title, False, False, 0)
            subtitle = Gtk.Label(label="Real Linux settings · changes are applied only when confirmed", xalign=0)
            subtitle.get_style_context().add_class("luna-header-subtitle")
            header.pack_start(subtitle, False, False, 0)
            root.pack_start(header, False, False, 0)

            toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            toolbar.get_style_context().add_class("luna-toolbar")
            self.luna_back = Gtk.Button(label="◀ Back")
            self.luna_back.get_accessible().set_name("Back to previous Control Panel view")
            self.luna_back.set_sensitive(False)
            self.luna_back.connect("clicked", lambda _button: self._luna_navigate(-1))
            toolbar.pack_start(self.luna_back, False, False, 0)
            self.luna_forward = Gtk.Button(label="Forward ▶")
            self.luna_forward.get_accessible().set_name("Forward to next Control Panel view")
            self.luna_forward.set_sensitive(False)
            self.luna_forward.connect("clicked", lambda _button: self._luna_navigate(1))
            toolbar.pack_start(self.luna_forward, False, False, 0)
            home = Gtk.Button(label="Home")
            home.get_accessible().set_name("Show all Control Panel settings")
            home.connect("clicked", lambda _button: self.show_home())
            toolbar.pack_start(home, False, False, 0)
            self.breadcrumb = Gtk.Label(label="All settings", xalign=0)
            self.breadcrumb.get_style_context().add_class("luna-breadcrumb")
            toolbar.pack_start(self.breadcrumb, True, True, 0)
            self.search_entry = Gtk.SearchEntry()
            self.search_entry.set_placeholder_text("Find a setting…")
            self.search_entry.set_size_request(160, -1)
            self.search_entry.set_tooltip_text("Search available Control Panel pages")
            self.search_entry.get_style_context().add_class("luna-search")
            self.search_entry.connect("changed", self._luna_search_changed)
            self.search_entry.connect("activate", self._luna_search_activate)
            toolbar.pack_end(self.search_entry, False, False, 0)
            root.pack_start(toolbar, False, False, 0)

            body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            root.pack_start(body, True, True, 0)
        else:
            body = root

        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        navigation.set_size_request(210 if luna else 215, -1)
        navigation.get_style_context().add_class("ricespice-nav")
        if luna:
            nav_scroll = Gtk.ScrolledWindow()
            nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            nav_scroll.set_size_request(216, -1)
            nav_scroll.get_style_context().add_class("luna-side-scroll")
            nav_scroll.add(navigation)
            body.pack_start(nav_scroll, False, False, 0)
        else:
            body.pack_start(navigation, False, False, 0)

        brand = Gtk.Label(label="Control Panel Tasks" if luna else "RiceSpice")
        brand.set_xalign(0)
        brand.get_style_context().add_class("ricespice-brand")
        navigation.pack_start(brand, False, False, 0)
        self.luna_view_switch = None
        if luna:
            self.luna_view_switch = Gtk.Button(label="Switch to Classic View")
            self.luna_view_switch.get_style_context().add_class("luna-view-switch")
            self.luna_view_switch.get_accessible().set_name(
                "Switch Control Panel category or classic view")
            self.luna_view_switch.connect("clicked", self._luna_switch_view)
            navigation.pack_start(self.luna_view_switch, False, False, 0)

        self.nav_buttons = {}

        def add_nav(key, title):
            if luna:
                button = Gtk.ToggleButton()
                label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
                glyph = self._luna_icon(key, 18)
                label = Gtk.Label(label=title, xalign=0)
                label.set_line_wrap(True)
                label_box.pack_start(glyph, False, False, 0)
                label_box.pack_start(label, True, True, 0)
                button.add(label_box)
            else:
                button = Gtk.ToggleButton(label=title)
                button.get_child().set_xalign(0)
            button.get_accessible().set_name(f"RiceSpice {title} settings")
            button.connect("clicked", lambda _button, name=key:
                           None if self._selecting_nav else self.show_page(name))
            navigation.pack_start(button, False, False, 0)
            self.nav_buttons[key] = button

        if luna:
            for group_title, names in LUNA_GROUPS:
                heading = Gtk.Label(label=group_title.upper(), xalign=0)
                heading.get_style_context().add_class("luna-nav-heading")
                navigation.pack_start(heading, False, False, 0)
                self.nav_groups.append((heading, names))
                for key in names:
                    title = next(item[1] for item in LUNA_SECTIONS if item[0] == key)
                    add_nav(key, title)
        else:
            for key, title, _description in self.sections:
                add_nav(key, title)

        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        body.pack_start(viewport, True, True, 0)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        self.content.get_style_context().add_class("ricespice-content")
        viewport.add(self.content)
        if luna:
            self.window.connect("size-allocate", self._luna_size_allocate)
        if page == "home" and luna:
            self.show_home()
        else:
            self.show_page(page)
        self.window.show_all()

    def _close(self, _window):
        self.closed = True
        self.generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.Gtk.main_quit()

    def _label(self, message: str, *, css: str = ""):
        label = self.Gtk.Label(label=message)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_selectable(True)
        if css:
            label.get_style_context().add_class(css)
        return label

    def _text(self, message: str, *, css: str = ""):
        if self.luna and css == "ricespice-section":
            divider = self.Gtk.Separator(orientation=self.Gtk.Orientation.HORIZONTAL)
            divider.get_style_context().add_class("luna-divider")
            self.content.pack_start(divider, False, False, 0)
        self.content.pack_start(self._label(message, css=css), False, False, 0)

    def _button(self, label: str, callback: Callable[[], None], *, primary: bool = False,
                parent=None):
        button = self.Gtk.Button(label=label)
        button.get_accessible().set_name(label)
        if primary:
            button.get_style_context().add_class("ricespice-action")
        button.connect("clicked", lambda _button: callback())
        if self.luna and parent is None:
            # XP Control Panel commands are compact actions, not full-width bars.
            row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL)
            row.pack_start(button, False, False, 0)
            self.content.pack_start(row, False, False, 0)
        else:
            (parent or self.content).pack_start(button, False, False, 0)
        return button

    def _state(self, message: str):
        self.status.set_text(message)

    def _background(self, work: Callable[[], object], done: Callable[[object], None]):
        if self.busy or self.closed:
            return
        if not self.worker_slots.acquire(blocking=False):
            self._state("Another system request is still finishing…")
            return
        self.busy = True
        serial = self.generation
        self._state("Working with system services…")
        try:
            future = self.executor.submit(work)
        except RuntimeError:
            # A closing window can race a control click. Never leave the
            # bounded worker slot or busy indicator permanently latched.
            self.worker_slots.release()
            self.busy = False
            if not self.closed:
                self._state("System request unavailable: settings window is closing")
            return

        def complete(finished):
            self.worker_slots.release()
            def on_ui():
                if self.closed or serial != self.generation:
                    return False
                self.busy = False
                try:
                    done(finished.result())
                except Exception as exc:
                    self._state(f"Unavailable or denied: {exc}")
                return False

            self.GLib.idle_add(on_ui)

        future.add_done_callback(complete)

    def _begin_view(self, name: str):
        """Cancel stale results and switch views without changing any system state."""
        self.generation += 1
        self.busy = False
        self.page = name
        self.luna_flow = None
        self._selecting_nav = True
        try:
            for key, button in self.nav_buttons.items():
                if button.get_active() != (key == name):
                    button.set_active(key == name)
        finally:
            self._selecting_nav = False
        for widget in tuple(self.content.get_children()):
            widget.destroy()
        self.status = self._label("", css="ricespice-state")
        self.content.pack_end(self.status, False, False, 0)
        if self.breadcrumb is not None:
            title = next((text for key, text, _desc in LUNA_SECTIONS if key == name),
                         "Search results" if name == "search" else "All settings")
            self.breadcrumb.set_text(title)

    def _luna_clear_search(self):
        if self.search_entry is None or not self.search_entry.get_text():
            return
        self._suppress_luna_search = True
        try:
            self.search_entry.set_text("")
        finally:
            self._suppress_luna_search = False
        self._luna_filter_sidebar("")

    def _luna_filter_sidebar(self, query: str):
        visible = set(luna_search_matches(query))
        for key, button in self.nav_buttons.items():
            button.set_visible(key in visible)
        for heading, keys in self.nav_groups:
            heading.set_visible(any(key in visible for key in keys))

    def _luna_search_changed(self, entry):
        if self._suppress_luna_search:
            return
        query = entry.get_text().strip()
        self._luna_filter_sidebar(query)
        if query:
            self.show_search_results(query)
        else:
            self.show_home()

    def _luna_search_activate(self, _entry):
        """Enter opens only the first real matching page; never runs an action."""
        if not self.luna or self.search_entry is None:
            return
        query = self.search_entry.get_text().strip()
        if not query:
            return
        matches = luna_search_matches(query)
        if matches:
            self.show_page(matches[0])

    def _luna_key_press(self, _window, event):
        """Control Panel keyboard navigation without a global keyboard grab."""
        if not self.luna or self.search_entry is None:
            return False
        control = event.state & self.Gdk.ModifierType.CONTROL_MASK
        if control and event.keyval in (self.Gdk.KEY_f, self.Gdk.KEY_F):
            self.search_entry.grab_focus()
            self.search_entry.select_region(0, -1)
            return True
        if control and event.keyval in (self.Gdk.KEY_1, self.Gdk.KEY_2):
            self.luna_view = ("categories" if event.keyval == self.Gdk.KEY_1
                              else "classic")
            self.show_home()
            return True
        if event.state & self.Gdk.ModifierType.MOD1_MASK:
            if event.keyval == self.Gdk.KEY_Left:
                self._luna_navigate(-1)
                return True
            if event.keyval == self.Gdk.KEY_Right:
                self._luna_navigate(1)
                return True
        if event.keyval == self.Gdk.KEY_Escape and self.search_entry.get_text():
            self.show_home()
            self.search_entry.grab_focus()
            return True
        return False

    def _luna_record_route(self, kind: str, detail: str = "") -> None:
        if not self.luna or self._luna_replaying:
            return
        route = (kind, detail)
        if self.luna_history and self.luna_history[self.luna_history_index] == route:
            return
        # Typing a search query updates the current history entry rather than
        # adding one entry per keystroke; Back returns to the previous screen.
        if (kind == "search" and self.luna_history_index >= 0
                and self.luna_history[self.luna_history_index][0] == "search"):
            self.luna_history[self.luna_history_index] = route
        else:
            del self.luna_history[self.luna_history_index + 1:]
            self.luna_history.append(route)
            if len(self.luna_history) > 32:
                del self.luna_history[0]
            self.luna_history_index = len(self.luna_history) - 1
        self._luna_update_history_buttons()

    def _luna_update_history_buttons(self):
        if self.luna_back is not None:
            self.luna_back.set_sensitive(self.luna_history_index > 0)
        if self.luna_forward is not None:
            self.luna_forward.set_sensitive(
                self.luna_history_index + 1 < len(self.luna_history))

    def _luna_navigate(self, delta: int) -> None:
        """Replay exactly a validated local view without applying settings."""
        destination = self.luna_history_index + delta
        if not self.luna or destination < 0 or destination >= len(self.luna_history):
            return
        kind, detail = self.luna_history[destination]
        self._luna_replaying = True
        try:
            if kind == "home":
                self.luna_view = detail
                self.show_home()
            elif kind == "category":
                self.show_category(detail)
            elif kind == "search":
                self._suppress_luna_search = True
                try:
                    self.search_entry.set_text(detail)
                finally:
                    self._suppress_luna_search = False
                self._luna_filter_sidebar(detail)
                self.show_search_results(detail)
            elif kind in self.nav_buttons:
                self.show_page(kind)
            else:
                return
            self.luna_history_index = destination
        finally:
            self._luna_replaying = False
            self._luna_update_history_buttons()

    def _luna_switch_view(self, _button):
        self.luna_view = "classic" if self.luna_view == "categories" else "categories"
        self.show_home()

    def _luna_size_allocate(self, _window, allocation):
        # Changing a FlowBox column count is cheap and prevents truncated XP
        # captions at 1024x768, fractional scaling and narrow window sizes.
        if self.luna_flow is not None:
            columns = 1 if allocation.width < 880 else 2
            # Avoid queueing a fresh FlowBox resize from *every* size-allocate
            # emission. This can starve rendering under headless labwc.
            if self.luna_flow.get_max_children_per_line() != columns:
                self.luna_flow.set_max_children_per_line(columns)

    def _luna_new_flow(self):
        flow = self.Gtk.FlowBox()
        flow.set_selection_mode(self.Gtk.SelectionMode.NONE)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(1 if self.window.get_allocated_width() < 880 else 2)
        flow.set_row_spacing(5)
        flow.set_column_spacing(10)
        self.luna_flow = flow
        return flow

    def _luna_icon(self, key: str, pixels: int):
        """Load bundled XP-style SVGs; fall back safely if packaging is incomplete."""
        try:
            from gi.repository import GdkPixbuf
            cache_key = (key, pixels)
            pixbuf = self._luna_icon_cache.get(cache_key)
            if pixbuf is None:
                asset = LUNA_ICON_DIR / LUNA_ICON_FILES[key]
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(asset), pixels, pixels, True)
                self._luna_icon_cache[cache_key] = pixbuf
            return self.Gtk.Image.new_from_pixbuf(pixbuf)
        except (KeyError, OSError, ImportError, self.GLib.Error):
            # An unavailable SVG loader cannot block access to system settings.
            return self.Gtk.Image.new_from_icon_name(
                LUNA_ICONS[key], self.Gtk.IconSize.DIALOG if pixels > 24
                else self.Gtk.IconSize.MENU)

    def _luna_category_button(self, key: str):
        """An accessible XP category row, never a fake setting control."""
        Gtk = self.Gtk
        _name, title, description = next(item for item in LUNA_SECTIONS
                                         if item[0] == key)
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("luna-category-row")
        button.get_accessible().set_name(title + ". " + description)
        button.set_tooltip_text(description)
        button.connect("clicked", lambda _button: self.show_page(key))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        image = self._luna_icon(key, 40)
        image.set_valign(Gtk.Align.START)
        row.pack_start(image, False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name = Gtk.Label(label=title, xalign=0)
        name.set_line_wrap(True)
        name.get_style_context().add_class("luna-category-title")
        labels.pack_start(name, False, False, 0)
        detail = Gtk.Label(label=description, xalign=0)
        detail.set_line_wrap(True)
        detail.get_style_context().add_class("luna-category-detail")
        labels.pack_start(detail, False, False, 0)
        row.pack_start(labels, True, True, 0)
        button.add(row)
        return button

    def _luna_group_button(self, category: tuple):
        """XP-style category opens tasks first, not an unrelated system tool."""
        key, title, icon, description, _pages = category
        Gtk = self.Gtk
        button = Gtk.Button()
        button.get_style_context().add_class("luna-control-group")
        button.get_accessible().set_name("Browse " + title)
        button.set_tooltip_text(description)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        row.pack_start(self._luna_icon(icon, 40), False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading = Gtk.Label(label=title, xalign=0)
        heading.set_line_wrap(True)
        heading.get_style_context().add_class("luna-category-title")
        labels.pack_start(heading, False, False, 0)
        detail = Gtk.Label(label=description, xalign=0)
        detail.set_line_wrap(True)
        detail.get_style_context().add_class("luna-category-detail")
        labels.pack_start(detail, False, False, 0)
        row.pack_start(labels, True, True, 0)
        button.add(row)
        button.connect("clicked", lambda _button: self.show_category(key))
        return button

    def show_category(self, category: str):
        if not self.luna:
            return
        match = next((entry for entry in LUNA_CONTROL_CATEGORIES
                      if entry[0] == category), None)
        if match is None:
            return
        self._luna_clear_search()
        self._luna_record_route("category", category)
        self._begin_view("category")
        _key, title, _icon, description, pages = match
        self.breadcrumb.set_text("Control Panel  /  " + title)
        self._text(title, css="ricespice-title")
        self._text(description, css="ricespice-desc")
        self._button("‹  Back to categories", self.show_home)
        flow = self._luna_new_flow()
        for key in pages:
            flow.add(self._luna_category_button(key))
        self.content.pack_start(flow, False, False, 0)
        self.content.show_all()

    def show_home(self):
        if not self.luna:
            return
        self._luna_clear_search()
        self._luna_record_route("home", self.luna_view)
        self._begin_view("home")
        classic = self.luna_view == "classic"
        self.luna_view_switch.set_label(
            "Switch to Category View" if classic else "Switch to Classic View")
        self.breadcrumb.set_text("Control Panel" + ("  /  Classic View" if classic else ""))
        self._text("Classic View" if classic else "Pick a category",
                   css="ricespice-title")
        self._text("Open an individual settings applet." if classic else
                   "Pick a category to configure your computer.",
                   css="ricespice-desc")
        flow = self._luna_new_flow()
        if classic:
            for key, _title, _description in sorted(
                    LUNA_SECTIONS, key=lambda entry: entry[1].casefold()):
                button = self._luna_category_button(key)
                button.get_style_context().add_class("luna-classic-row")
                flow.add(button)
        else:
            for category in LUNA_CONTROL_CATEGORIES:
                flow.add(self._luna_group_button(category))
        self.content.pack_start(flow, False, False, 0)
        self.content.show_all()

    def show_search_results(self, query: str):
        if not self.luna:
            return
        self._luna_record_route("search", query)
        self._begin_view("search")
        matches = luna_search_matches(query)
        self._text("Search settings", css="ricespice-title")
        self._text(f"{len(matches)} matching settings for “{query}”",
                   css="ricespice-desc")
        if matches:
            flow = self._luna_new_flow()
            for key in matches:
                flow.add(self._luna_category_button(key))
            self.content.pack_start(flow, False, False, 0)
        else:
            self._text("No matching settings. Try Network, Sound, Display or Power.",
                       css="ricespice-note")
        self.content.show_all()

    def show_page(self, name: str, *, rescan: bool = False):
        if name not in self.nav_buttons:
            return
        if self.luna:
            self._luna_clear_search()
            self._luna_record_route(name)
        self._begin_view(name)
        _key, title, description = next(section for section in self.sections
                                        if section[0] == name)
        self._text(title, css="ricespice-title")
        self._text(description, css="ricespice-desc")
        if name == "network":
            self._network(rescan=rescan)
        elif name == "audio":
            self._audio()
        elif name == "notifications":
            self._notifications()
        elif name == "bluetooth":
            self._bluetooth()
        elif name == "power":
            self._power()
        elif name == "timezone":
            self._timezone()
        elif name == "appearance":
            self._appearance()
        elif name == "taskbar":
            self._taskbar()
        elif name in ("input", "accessibility"):
            self._preferences(name)
        elif name == "displays":
            self._displays()
        else:
            self._external(name)
        self.content.show_all()

    def _notifications(self):
        self._text("Do Not Disturb hides incoming notification banners while retaining "
                   "RicePop's active and past alerts.", css="ricespice-note")
        self._text("This setting is available only when the full RiceBowl Wayland "
                   "session owns its Mako notification service.", css="ricespice-note")
        self._button("Refresh notification state", lambda: self.show_page("notifications"))

        def present(status):
            enabled = status["do_not_disturb"]
            self._state("Do Not Disturb: on" if enabled else "Do Not Disturb: off")
            self._button("Turn off Do Not Disturb" if enabled else "Turn on Do Not Disturb",
                         lambda: self._background(
                             lambda: notifications.set_dnd(not enabled, expected=enabled),
                             lambda _result: self.show_page("notifications")), primary=True)
            self.content.show_all()

        self._background(notifications.dnd_status, present)
        self._notification_appearance()

    def _notification_appearance(self):
        """Change only the next full Wayland login's RicePop Mako styling."""
        from . import notification_prefs
        self._text("RicePop banner appearance · next full Wayland login",
                   css="ricespice-section")
        self._text("These choices never modify XFCE notifications or a running Mako "
                   "instance. Only the RiceBowl-owned host reads them at login.",
                   css="ricespice-note")
        try:
            current = notification_prefs.load()
        except (OSError, ValueError) as exc:
            self._text("Saved RicePop appearance unavailable: " + str(exc),
                       css="ricespice-note")
            return

        def choice(title, choices, selected):
            self._text(title)
            combo = self.Gtk.ComboBoxText()
            combo.get_accessible().set_name(title)
            for value, label in choices:
                combo.append(str(value), label)
            combo.set_active_id(str(selected))
            self.content.pack_start(combo, False, False, 0)
            return combo

        family = choice("Notification font", [(name, name) for name in
                        dict.fromkeys(("Sans", "Serif", "Monospace",
                                       current["font_family"]))], current["font_family"])
        size = choice("Font size", [(n, f"{n} pt") for n in notification_prefs._SIZES],
                      current["font_size"])
        timeout = choice("Default banner duration", [
            (0, "Follow application / no default timeout"),
            (4000, "4 seconds"), (7000, "7 seconds"), (12000, "12 seconds")],
            current["default_timeout"])
        visible = choice("Maximum visible banners", [(n, str(n))
                          for n in notification_prefs._COUNTS], current["max_visible"])

        def installed():
            from . import fonts
            return sorted({face.family for face in fonts.installed_fonts()
                           if notification_prefs._FAMILY.fullmatch(face.family)})[:128]

        def show_installed(names):
            current_name = family.get_active_id()
            family.remove_all()
            for name in dict.fromkeys(("Sans", "Serif", "Monospace", current_name, *names)):
                if name:
                    family.append(name, name)
            family.set_active_id(current_name)
            self._state(f"{len(names)} installed TrueType font families available")

        self._button("Find installed TrueType fonts", lambda: self._background(
            installed, show_installed))

        def apply():
            values = {"font_family": family.get_active_id(),
                      "font_size": int(size.get_active_id()),
                      "default_timeout": int(timeout.get_active_id()),
                      "max_visible": int(visible.get_active_id())}
            self._background(lambda: notification_prefs.save(values, expected=current),
                             lambda _result: self.show_page("notifications"))

        self._button("Save RicePop appearance for next login", apply,
                     primary=True)
        self._button("Restore RicePop appearance defaults", lambda: self._background(
            lambda: notification_prefs.save(notification_prefs.DEFAULTS,
                                            expected=current),
            lambda _result: self.show_page("notifications")))

    def _network(self, *, rescan: bool = False):
        self._text("Turning Wi-Fi off can disconnect an active network session.", css="ricespice-note")
        self._button("Refresh visible networks", lambda: self.show_page("network", rescan=True))

        def present(results):
            snapshot, profiles = results
            if isinstance(snapshot, Exception):
                self._text("Wi-Fi radio/scan unavailable: " + str(snapshot),
                           css="ricespice-note")
                enabled = False
                networks = []
            else:
                enabled = snapshot["enabled"]
                self._state("Wi-Fi radio: enabled" if enabled else "Wi-Fi radio: disabled")
                self._button("Disable Wi-Fi" if enabled else "Enable Wi-Fi", lambda: self._background(
                    lambda: backend.set_wifi(not enabled, expected=enabled),
                    lambda _result: self.show_page("network")), primary=True)
                networks = snapshot["networks"]
            self._text("Visible networks", css="ricespice-section")
            if isinstance(snapshot, Exception):
                pass
            elif not enabled:
                self._text("Enable Wi-Fi to look for networks.", css="ricespice-note")
            elif not networks:
                self._text("No networks reported. Try Refresh; scanning may be unavailable.",
                           css="ricespice-note")
            for network in networks:
                ssid = network["ssid"]
                description = f"{ssid} · {network['signal']}% signal · {network['security'] or 'Open'}"
                if network["connected"]:
                    description += " · Connected"
                self._text(description)
                if network["connected"]:
                    continue

                def confirm_switch(target):
                    active = next((entry["ssid"] for entry in networks
                                   if entry["connected"]), None)
                    if active is not None:
                        dialog = self.Gtk.MessageDialog(
                            transient_for=self.window, modal=True,
                            message_type=self.Gtk.MessageType.QUESTION,
                            buttons=self.Gtk.ButtonsType.YES_NO,
                            text=f"Switch Wi-Fi from {active} to {target}?")
                        approved = dialog.run() == self.Gtk.ResponseType.YES
                        dialog.destroy()
                        if not approved:
                            return False
                    return True

                def connect(target=ssid):
                    if not confirm_switch(target):
                        return
                    self._background(lambda: backend.connect_visible_wifi(target),
                                     lambda _result: self.show_page("network"))

                self._button(f"Connect to {ssid}", connect)
                security = network["security"].upper()
                if "WPA" in security and "802.1X" not in security and "EAP" not in security:
                    def connect_password(target=ssid):
                        if not confirm_switch(target):
                            return
                        dialog = self.Gtk.Dialog(title="Wi-Fi password",
                                                 transient_for=self.window,
                                                 flags=self.Gtk.DialogFlags.MODAL)
                        dialog.add_buttons("Cancel", self.Gtk.ResponseType.CANCEL,
                                           "Connect", self.Gtk.ResponseType.OK)
                        dialog.get_content_area().add(self._label(f"Password for {target}"))
                        entry = self.Gtk.Entry()
                        entry.set_visibility(False)
                        entry.set_input_purpose(self.Gtk.InputPurpose.PASSWORD)
                        entry.set_max_length(63)
                        entry.set_activates_default(True)
                        entry.get_accessible().set_name("Wi-Fi password")
                        dialog.get_content_area().add(entry)
                        dialog.set_default_response(self.Gtk.ResponseType.OK)
                        dialog.show_all()
                        password = entry.get_text() if dialog.run() == self.Gtk.ResponseType.OK else None
                        entry.set_text("")
                        dialog.destroy()
                        if password is None:
                            return
                        if not 8 <= len(password) <= 63:
                            self._state("WPA password must contain 8–63 characters")
                            return
                        self._background(
                            lambda: backend.connect_secure_visible_wifi(target, password),
                            lambda _result: self.show_page("network"))

                    self._button(f"Enter password for {ssid}", connect_password)

            self._text("Enterprise Wi-Fi and VPN enrollment", css="ricespice-section")
            self._text("Add PEAP/TTLS Wi-Fi only with the server domain supplied by your "
                       "administrator. The system CA store or a chosen CA file must "
                       "verify the server. Passwords are not saved by RiceSpice.",
                       css="ricespice-note")
            self._button("Add enterprise Wi-Fi profile…", self._new_enterprise_wifi)
            self._button("Import OpenVPN / WireGuard profile…", self._import_vpn)
            self._text("Saved Ethernet, Wi-Fi and VPN profiles", css="ricespice-section")
            self._text("Connecting may interrupt an active network or tunnel. "
                       "An imported profile is not activated automatically.",
                       css="ricespice-note")
            if isinstance(profiles, Exception):
                self._text(f"Network profiles unavailable: {profiles}", css="ricespice-note")
            elif not profiles:
                self._text("No supported saved profiles were reported.", css="ricespice-note")
            else:
                for profile in profiles:
                    self._text(f"{profile['name']} · {profile['kind']} · "
                               + ("Connected" if profile["active"] else "Disconnected"))

                    def confirm_profile(item=profile):
                        verb = "Disconnect" if item["active"] else "Connect"
                        dialog = self.Gtk.MessageDialog(
                            transient_for=self.window, modal=True,
                            message_type=self.Gtk.MessageType.QUESTION,
                            buttons=self.Gtk.ButtonsType.YES_NO,
                            text=f"{verb} saved profile {item['name']}? "
                                 "This can interrupt your current network or VPN connection.")
                        approved = dialog.run() == self.Gtk.ResponseType.YES
                        dialog.destroy()
                        if approved:
                            self._background(lambda: backend.set_connection_profile(
                                item["uuid"], not item["active"], expected=item["active"]),
                                lambda _result: self.show_page("network"))

                    self._button(("Disconnect " if profile["active"] else "Connect ")
                                 + profile["name"], confirm_profile)
                    if profile["kind"] in ("802-11-wireless", "wifi") and not profile["active"]:
                        self._button("Connect with 802.1X password: " + profile["name"],
                                     lambda item=profile: self._enterprise_password(item))
            if backend.external_tool("connections") is not None:
                self._button("Advanced certificate/VPN settings (NetworkManager)…",
                             lambda: self._background(
                                 lambda: backend.open_external("connections"),
                                 lambda _result: self._state("NetworkManager editor launched")))
            else:
                self._text("For EAP-TLS/client certificates and advanced VPN protocols, "
                           "install NetworkManager's connection editor.",
                           css="ricespice-note")
            self.content.show_all()

        def collect():
            def safe(work):
                try:
                    return work()
                except Exception as exc:
                    return exc

            return (safe(lambda: backend.wifi_snapshot(rescan=rescan)),
                    safe(backend.connection_profiles))

        self._background(collect, present)

    def _new_enterprise_wifi(self):
        Gtk = self.Gtk
        dialog = Gtk.Dialog(title="Add enterprise Wi-Fi", transient_for=self.window,
                            flags=Gtk.DialogFlags.MODAL)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Save profile", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin=14)
        dialog.get_content_area().add(grid)

        def field(row, label, placeholder=""):
            entry = Gtk.Entry()
            entry.set_max_length(253)
            entry.set_placeholder_text(placeholder)
            entry.get_accessible().set_name(label)
            grid.attach(self._label(label), 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            return entry

        ssid = field(0, "Wi-Fi SSID", "Campus-WiFi")
        username = field(1, "Network username", "username@institution.edu")
        domain = field(2, "RADIUS server domain", "radius.institution.edu")
        ca = field(3, "CA certificate (optional)", "Absolute path, otherwise system CAs")
        grid.attach(self._label("Authentication"), 0, 4, 1, 1)
        method = Gtk.ComboBoxText()
        for identifier, label in (("peap-mschapv2", "PEAP / MSCHAPv2"),
                                  ("ttls-pap", "TTLS / PAP"),
                                  ("ttls-mschapv2", "TTLS / MSCHAPv2")):
            method.append(identifier, label)
        method.set_active_id("peap-mschapv2")
        method.get_accessible().set_name("Enterprise EAP authentication method")
        grid.attach(method, 1, 4, 1, 1)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        confirmed = dialog.run() == Gtk.ResponseType.OK
        values = (ssid.get_text(), username.get_text(), domain.get_text(),
                  ca.get_text().strip(), method.get_active_id()) if confirmed else None
        dialog.destroy()
        if values is None:
            return
        network, identity, server_domain, cert, selection = values
        choices = {"peap-mschapv2": ("peap", "mschapv2"),
                   "ttls-pap": ("ttls", "pap"),
                   "ttls-mschapv2": ("ttls", "mschapv2")}
        if selection not in choices:
            self._state("Choose an enterprise authentication method")
            return
        eap, inner = choices[selection]
        self._background(lambda: network_enrollment.create_enterprise_wifi(
            ssid=network, identity=identity, domain=server_domain,
            ca_certificate=cert, eap=eap, inner=inner),
            lambda _result: self.show_page("network"))

    def _enterprise_password(self, profile):
        self._background(lambda: network_enrollment.enterprise_password_ready(profile["uuid"]),
                         lambda _result: self._prompt_enterprise_password(profile))

    def _prompt_enterprise_password(self, profile):
        Gtk = self.Gtk
        dialog = Gtk.Dialog(title="Enterprise Wi-Fi password", transient_for=self.window,
                            flags=Gtk.DialogFlags.MODAL)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Connect", Gtk.ResponseType.OK)
        dialog.get_content_area().add(self._label("Password for " + profile["name"] +
                                                  " (not saved)"))
        password_entry = Gtk.Entry()
        password_entry.set_visibility(False)
        password_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        password_entry.set_max_length(512)
        password_entry.set_activates_default(True)
        password_entry.get_accessible().set_name("Enterprise network password")
        dialog.get_content_area().add(password_entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        approved = dialog.run() == Gtk.ResponseType.OK
        secret = password_entry.get_text() if approved else None
        password_entry.set_text("")
        dialog.destroy()
        if secret is None:
            return
        self._background(lambda: network_enrollment.connect_enterprise_wifi(
            profile["uuid"], secret, expected_active=profile["active"]),
            lambda _result: self.show_page("network"))

    def _import_vpn(self):
        Gtk = self.Gtk
        chooser = Gtk.FileChooserDialog(
            title="Import VPN configuration", transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                            "Import profile", Gtk.ResponseType.OK)
        chooser.set_local_only(True)
        selection = Gtk.FileFilter()
        selection.set_name("OpenVPN (*.ovpn) / WireGuard (*.conf)")
        selection.add_pattern("*.ovpn")
        selection.add_pattern("*.conf")
        chooser.add_filter(selection)
        chosen = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        chooser.destroy()
        if chosen:
            self._background(lambda: network_enrollment.import_vpn_profile(chosen),
                             lambda _result: self.show_page("network"))

    def _audio(self):
        self._button("Refresh devices and players", lambda: self.show_page("audio"))

        def collect():
            # Both services are optional; failure of one must not hide the other.
            def read(reader):
                try:
                    return reader()
                except Exception as exc:
                    return exc

            return (read(audio_devices.inspect), read(media.read_media_players),
                    read(audio_devices.playback_streams))

        def present(snapshot):
            inventory, players, stream_state = snapshot
            self._state("Current audio and media state")
            self._text("Playback and recording devices", css="ricespice-section")
            if isinstance(inventory, Exception):
                self._text(f"Audio devices unavailable: {inventory}", css="ricespice-note")
            else:
                for kind, key, title in (("sink", "outputs", "Output"),
                                         ("source", "inputs", "Microphone")):
                    self._text(title, css="ricespice-section")
                    options = inventory[key]
                    if not options:
                        self._text("No devices available", css="ricespice-note")
                        continue
                    combo = self.Gtk.ComboBoxText()
                    for option in options:
                        combo.append(option["name"], option["description"] or option["name"])
                    current = next((item["name"] for item in options if item["default"]), None)
                    if current:
                        combo.set_active_id(current)
                    self.content.pack_start(combo, False, False, 0)

                    def apply(kind=kind, widget=combo, before=current):
                        name = widget.get_active_id()
                        if name is None:
                            self._state("Select an available device first")
                            return
                        self._background(
                            lambda: audio_devices.set_default(kind, name, expected_current=before),
                            lambda _result: self.show_page("audio"))

                    self._button(f"Set default {title.lower()}", apply, primary=True)

            self._text("Volume and output per application", css="ricespice-section")
            if isinstance(stream_state, Exception):
                self._text(f"Application playback controls unavailable: {stream_state}",
                           css="ricespice-note")
            elif not stream_state["streams"]:
                self._text("No active playback streams. Start audio in an application "
                           "and refresh this page.", css="ricespice-note")
            else:
                for stream in stream_state["streams"]:
                    self._text(f"{stream['label']} · {stream['volume']}%"
                               + (" · Muted" if stream["mute"] else ""),
                               css="ricespice-section")
                    choices = self.Gtk.ComboBoxText()
                    choices.get_accessible().set_name(stream["label"] + " output device")
                    for sink in stream_state["outputs"]:
                        choices.append(sink["name"], sink["description"] or sink["name"])
                        if sink["index"] == stream["sink"]:
                            choices.set_active_id(sink["name"])
                    self.content.pack_start(choices, False, False, 0)
                    def apply_output(entry=stream, combo=choices):
                        # GTK widgets must only be read on the UI thread.
                        selected = combo.get_active_id()
                        if selected is None:
                            self._state("Choose an output device for " + entry["label"])
                            return
                        self._background(
                            lambda: audio_devices.set_stream_output(
                                entry["index"], selected, expected_sink=entry["sink"]),
                            lambda _result: self.show_page("audio"))

                    self._button("Move " + stream["label"] + " to selected output",
                                 apply_output)
                    levels = self.Gtk.ComboBoxText()
                    levels.get_accessible().set_name(stream["label"] + " stream volume")
                    for percent in range(0, 151, 10):
                        levels.append(str(percent), f"{percent}%")
                    if stream["volume"] in range(0, 151, 10):
                        levels.set_active_id(str(stream["volume"]))
                    self.content.pack_start(levels, False, False, 0)

                    def apply_volume(entry=stream, widget=levels):
                        value = widget.get_active_id()
                        if value is None:
                            self._state("Choose a volume level (0–150%)")
                            return
                        self._background(lambda: audio_devices.set_stream_volume(
                            entry["index"], int(value), expected=entry["volume"]),
                            lambda _result: self.show_page("audio"))

                    self._button("Set " + stream["label"] + " volume", apply_volume)
                    self._button(("Unmute " if stream["mute"] else "Mute ") + stream["label"],
                                 lambda entry=stream: self._background(
                                     lambda: audio_devices.set_stream_mute(
                                         entry["index"], not entry["mute"],
                                         expected=entry["mute"]),
                                     lambda _result: self.show_page("audio")))
            self._text("Now playing", css="ricespice-section")
            if isinstance(players, Exception):
                self._text("Media session unavailable: " + str(players), css="ricespice-note")
            elif not players:
                self._text("No MPRIS-compatible media player is running.",
                           css="ricespice-note")
            else:
                for player in players:
                    description = f"{player.label} · {player.title}"
                    if player.artist:
                        description += f" — {player.artist}"
                    self._text(description + f" · {player.status}")
                    controls = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL,
                                            spacing=8)
                    self.content.pack_start(controls, False, False, 0)
                    for title, command, enabled in (
                        ("Previous", "Previous", player.can_previous),
                        ("Pause" if player.status == "Playing" else "Play",
                         "PlayPause", player.can_play_pause),
                        ("Next", "Next", player.can_next),
                    ):
                        button = self._button(
                            f"{title} · {player.label}",
                            lambda bus=player.bus_name, action=command: self._background(
                                lambda: media.media_action(bus, action),
                                lambda _result: self.show_page("audio")),
                            parent=controls)
                        button.set_sensitive(enabled)
            self.content.show_all()

        self._background(collect, present)

    def _bluetooth(self):
        self._button("Refresh Bluetooth devices", lambda: self.show_page("bluetooth"))

        def present(inventory):
            powered = inventory["powered"]
            self._state("Bluetooth adapter: on" if powered else "Bluetooth adapter: off")
            self._button("Turn Bluetooth off" if powered else "Turn Bluetooth on",
                         lambda: self._background(
                             lambda: backend.set_bluetooth_power(not powered, expected=powered),
                             lambda _result: self.show_page("bluetooth")), primary=True)
            self._text("Known devices", css="ricespice-section")
            if not inventory["devices"]:
                self._text("No known devices. Pairing is handled by a Bluetooth agent.",
                           css="ricespice-note")
            for device in inventory["devices"]:
                state = "connected" if device["connected"] else "disconnected"
                self._text(f"{device['label']} · {state}")
                if device["paired"] and powered:
                    self._button("Disconnect" if device["connected"] else "Connect",
                                 lambda d=device: self._background(
                                     lambda: backend.set_bluetooth_connection(
                                         d["address"], not d["connected"], expected=d["connected"]),
                                     lambda _result: self.show_page("bluetooth")))
            self.content.show_all()

        self._background(backend.bluetooth_snapshot, present)

    def _external(self, page):
        self._text("This setting is not yet implemented directly by RiceSpice.",
                   css="ricespice-note")
        tool = backend.external_tool(page)
        if tool is None:
            self._state("No compatible settings application installed")
        else:
            self._text("Available system editor: " + tool[0])
            self._button("Open system settings…", lambda: self._background(
                lambda: backend.open_external(page),
                lambda _result: self._state("System settings launch requested")), primary=True)

    def _preferences(self, page: str):
        self._text("These preferences affect only the next RiceBowl Wayland login. "
                   "Your XFCE desktop and other desktop sessions are not modified.",
                   css="ricespice-note")
        try:
            current = preferences.load()
        except (OSError, preferences.PreferenceError) as error:
            self._state(f"Private RiceSpice preferences unavailable: {error}")
            return
        options = (
            (("pointer_speed", "Pointer speed", (-1.0, -0.5, 0.0, 0.5, 1.0)),
             ("natural_scroll", "Natural scrolling", (False, True)),
             ("tap_to_click", "Touchpad tap to click", (False, True)),
             ("repeat_rate", "Keyboard repeats per second", (15, 25, 35, 50)),
             ("repeat_delay", "Keyboard repeat delay (ms)", (300, 450, 600, 800, 1000)))
            if page == "input" else
            (("cursor_size", "Cursor size (theme dependent)", (24, 32, 48, 64)),
             ("gtk_text_scale", "GTK text scale (GTK apps only)", (1.0, 1.25, 1.5)),
             ("high_contrast", "Request high-contrast GTK theme", (False, True)),
             ("screen_reader_enabled", "Start Orca on full RiceBowl login", (False, True)))
        )
        combos = {}
        section_flag = "input_enabled" if page == "input" else "accessibility_enabled"
        for key, description, choices in options:
            if self.luna and choices == (False, True):
                # XP-era checkboxes for Boolean options, still backed by
                # the same validated owner-private preferences and readback.
                check = self.Gtk.CheckButton(label=description)
                check.get_accessible().set_name(description)
                check.set_active(bool(current[key]))
                combos[key] = (check, choices)
                self.content.pack_start(check, False, False, 0)
            else:
                self._text(description, css="ricespice-section")
                combo = self.Gtk.ComboBoxText()
                combo.get_accessible().set_name(description)
                for choice in choices:
                    title = ("On" if choice else "Off") if type(choice) is bool else str(choice)
                    combo.append(str(choice), title)
                combo.set_active_id(str(current[key]))
                combos[key] = (combo, choices)
                self.content.pack_start(combo, False, False, 0)
        if page == "accessibility":
            self._text("Cursor themes can ignore requested sizes. Text scaling uses "
                       "GDK_DPI_SCALE and does not scale Qt, Electron or the native "
                       "RicePlate panel. Screen readers and magnification still require "
                       "dedicated assistive tools.", css="ricespice-note")
            self._text("Orca is " + ("installed" if shutil.which("orca") else "not installed")
                       + ". When enabled, RiceBowl starts it only in a full, non-nested "
                       "login session. Native RicePlate still needs an accessibility "
                       "bridge and physical AT testing.", css="ricespice-note")
        else:
            self._text("Pointer settings depend on connected device support. "
                       "Keyboard repeat uses labwc's compositor settings.",
                       css="ricespice-note")

        def apply():
            requested = dict(current)
            requested[section_flag] = True
            for key, (combo, choices) in combos.items():
                if isinstance(combo, self.Gtk.CheckButton):
                    requested[key] = combo.get_active()
                else:
                    requested[key] = next((choice for choice in choices
                                           if str(choice) == combo.get_active_id()), None)
                if requested[key] is None:
                    self._state("Choose a supported value for each option")
                    return
            self._background(lambda: preferences.save(requested, expected=current),
                             lambda _result: self.show_page(page))

        self._button("Save for next RiceBowl login", apply, primary=True)
        if current[section_flag]:
            self._button("Restore inherited settings for next login", lambda: self._background(
                lambda: preferences.save({**current, section_flag: False}, expected=current),
                lambda _result: self.show_page(page)))
        self._state("RiceBowl overrides enabled" if current[section_flag]
                    else "Currently using inherited settings")

    def _displays(self):
        self._text("Active monitors only. A trial resolution or scale is automatically "
                   "reverted after 18 seconds unless you confirm it. Changes apply "
                   "only to the current RiceBowl session.", css="ricespice-note")
        self._button("Refresh monitors", lambda: self.show_page("displays"))
        if not wayland_displays._in_session():
            self._text("Open RiceSpice inside the opt-in RiceBowl labwc session "
                       "to inspect or edit monitors.", css="ricespice-note")
            tool = backend.external_tool("displays")
            if tool is not None:
                self._button("Open external display editor…", lambda: self._background(
                    lambda: backend.open_external("displays"),
                    lambda _result: self._state("External editor launched")))
            return

        def present(outputs):
            try:
                saved = display_presets.load()
            except (OSError, ValueError) as exc:
                self._text(f"Saved monitor layout unavailable: {exc}", css="ricespice-note")
                saved = None
            for output in outputs:
                self._text(output.name, css="ricespice-section")
                self._text(f"Current: {output.current_mode}, scale {output.scale:g}, "
                           f"position {output.position[0]},{output.position[1]}",
                           css="ricespice-note")
                mode = self.Gtk.ComboBoxText()
                mode.get_accessible().set_name(output.name + " resolution and refresh rate")
                for choice in output.modes:
                    mode.append(choice, choice)
                mode.set_active_id(output.current_mode)
                self.content.pack_start(mode, False, False, 0)
                scale = self.Gtk.ComboBoxText()
                scale.get_accessible().set_name(output.name + " display scale")
                for factor in wayland_displays.SCALES:
                    scale.append(str(factor), f"{factor:g}×")
                if output.scale in wayland_displays.SCALES:
                    scale.set_active_id(str(output.scale))
                else:
                    scale.append("current", f"Keep current ({output.scale:g}×)")
                    scale.set_active_id("current")
                self.content.pack_start(scale, False, False, 0)

                coordinates = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
                positions = []
                for label, value in zip(("X", "Y"), output.position):
                    coordinates.pack_start(self._label(label), False, False, 0)
                    spin = self.Gtk.SpinButton.new_with_range(-16384, 16384, 1)
                    spin.set_value(value)
                    spin.get_accessible().set_name(output.name + " position " + label)
                    coordinates.pack_start(spin, False, False, 0)
                    positions.append(spin)
                self.content.pack_start(coordinates, False, False, 0)

                def try_change(current=output, modes=mode, factors=scale, coords=positions):
                    chosen_mode = modes.get_active_id()
                    chosen_scale = factors.get_active_id()
                    if chosen_mode is None or chosen_scale is None:
                        self._state("Choose a supported mode and scale")
                        return
                    factor = (current.scale if chosen_scale == "current"
                              else float(chosen_scale))
                    target_position = (coords[0].get_value_as_int(),
                                       coords[1].get_value_as_int())
                    self._background(
                        lambda: wayland_displays.begin_change(
                            current.name, chosen_mode, factor,
                            position=target_position),
                        lambda change: self._display_confirmation(change))

                self._button("Try settings on " + output.name, try_change, primary=True)
            self._text("Saved monitor layout", css="ricespice-section")
            self._text("Save the current arrangement as a private preset. "
                       "Restoring all monitors requires one guarded trial and confirmation. "
                       "Automatic next-login trials are optional and off by default.",
                       css="ricespice-note")
            if saved is not None:
                self._button("Save current layout as preset", lambda: self._background(
                    lambda: display_presets.save(display_presets.from_outputs(
                        wayland_displays.inventory()), expected=saved),
                    lambda _result: self.show_page("displays")))
                if saved:
                    auto_trial = display_presets.auto_trial_enabled()
                    self._text("Optional next login: try this exact monitor layout "
                               "automatically, then confirm it within 18 seconds. "
                               "Otherwise the original arrangement returns.",
                               css="ricespice-note")
                    self._button("Disable next-login monitor trial" if auto_trial else
                                 "Enable next-login monitor trial", lambda: self._background(
                                     lambda: display_presets.set_auto_trial(
                                         not auto_trial, expected=auto_trial),
                                     lambda _result: self.show_page("displays")))
                    try:
                        display_restore.plan(saved, outputs)
                    except ValueError as exc:
                        self._text("Full restore unavailable: " + str(exc),
                                   css="ricespice-note")
                    else:
                        self._button("Try entire saved monitor layout", lambda: self._background(
                            lambda: display_restore.begin(saved),
                            lambda change: self._display_confirmation(change)), primary=True)
                    for entry in saved:
                        self._text(f"{entry['name']} · {entry['mode']} · "
                                   f"{entry['scale']:g}× · {entry['x']},{entry['y']}")
                        if entry["name"] in {out.name for out in outputs}:
                            self._button("Try saved layout on " + entry["name"],
                                         lambda choice=entry: self._background(
                                             lambda: wayland_displays.begin_change(
                                                 choice["name"], choice["mode"], choice["scale"],
                                                 position=(choice["x"], choice["y"])),
                                             lambda change: self._display_confirmation(change)))
                    self._button("Forget saved monitor layout", lambda: self._background(
                        lambda: display_presets.save([], expected=saved),
                        lambda _result: self.show_page("displays")))
                else:
                    self._text("No monitor layout has been saved.", css="ricespice-note")
            self._state(f"{len(outputs)} active monitor(s) detected")
            self.content.show_all()

        self._background(wayland_displays.inventory, present)

    def _display_confirmation(self, change):
        self._state("Monitor trial started. Confirm before the 18-second timeout.")
        keep_button = self._button("Keep these display settings",
                                   lambda: self._keep_display(change), primary=True)
        self.content.show_all()
        serial = self.generation

        def poll():
            if self.closed or serial != self.generation or self.page != "displays":
                return False
            try:
                state, detail = display_guard.read_status(change)
            except (OSError, ValueError, RuntimeError) as exc:
                self._state(f"Display guard unavailable; wait for its automatic rollback: {exc}")
                keep_button.set_sensitive(False)
                return False
            self._state(f"Display trial: {state}. {detail}")
            if state not in ("starting", "pending"):
                keep_button.set_sensitive(False)
            return state in ("starting", "pending")

        self.GLib.timeout_add(240, poll)

    def _keep_display(self, change):
        try:
            display_guard.keep_change(change)
            self._state("Confirmation sent; checking the display guard…")
        except (RuntimeError, ValueError, OSError) as exc:
            self._state(f"Could not confirm; automatic rollback remains active: {exc}")

    def _timezone(self):
        self._button("Refresh timezone", lambda: self.show_page("timezone"))
        self._text("Changes to the system timezone require authorization from the OS.",
                   css="ricespice-note")
        if backend.external_tool("timezone") is not None:
            self._button("Open alternate system date settings…",
                         lambda: self._background(
                             lambda: backend.open_external("timezone"),
                             lambda _result: self._state("System settings launch requested")))

        def present(snapshot):
            current, zones = snapshot["current"], snapshot["zones"]
            self._state("System timezone: " + current)
            self._text("Automatic clock synchronization", css="ricespice-section")
            ntp = snapshot["ntp"]
            if ntp is None:
                self._text("System time synchronization state is unavailable.",
                           css="ricespice-note")
            elif not ntp["available"]:
                self._text("This system does not offer an automatic time service.",
                           css="ricespice-note")
            else:
                enabled = ntp["enabled"]
                self._text("Current state: " + ("enabled" if enabled else "disabled"),
                           css="ricespice-note")
                self._text("Changing this affects the whole system and may require polkit "
                           "authorization.", css="ricespice-note")

                def change_ntp():
                    if enabled:
                        dialog = self.Gtk.MessageDialog(
                            transient_for=self.window, modal=True,
                            message_type=self.Gtk.MessageType.QUESTION,
                            buttons=self.Gtk.ButtonsType.YES_NO,
                            text="Disable system-wide automatic time synchronization?")
                        choice = dialog.run()
                        dialog.destroy()
                        if choice != self.Gtk.ResponseType.YES:
                            return
                    self._background(lambda: backend.set_ntp(not enabled, expected=enabled),
                                     lambda _result: self.show_page("timezone"))

                self._button("Disable automatic time" if enabled else "Enable automatic time",
                             change_ntp)
            if ntp is not None and not ntp["enabled"]:
                self._text("Set local system date and time", css="ricespice-section")
                self._text("Only when automatic time is disabled. This changes the whole "
                           "computer clock and can affect TLS, logs and running services.",
                           css="ricespice-note")
                clock = self.Gtk.Entry()
                clock.set_max_length(19)
                clock.set_placeholder_text("YYYY-MM-DD HH:MM:SS")
                clock.get_accessible().set_name("Local system date and time")
                self.content.pack_start(clock, False, False, 0)

                def apply_clock():
                    value = clock.get_text().strip()
                    if len(value) != 19:
                        self._state("Enter a complete local date/time: YYYY-MM-DD HH:MM:SS")
                        return
                    dialog = self.Gtk.MessageDialog(
                        transient_for=self.window, modal=True,
                        message_type=self.Gtk.MessageType.QUESTION,
                        buttons=self.Gtk.ButtonsType.YES_NO,
                        text=f"Set the entire computer's local clock to {value}?")
                    approved = dialog.run() == self.Gtk.ResponseType.YES
                    dialog.destroy()
                    if approved:
                        self._background(lambda: backend.set_system_clock(value, expected_ntp=False),
                                         lambda _result: self.show_page("timezone"))

                self._button("Set system date/time…", apply_clock)
            self._text("Search for a timezone", css="ricespice-section")
            search = self.Gtk.SearchEntry()
            search.set_placeholder_text("e.g. Europe/Berlin")
            search.get_accessible().set_name("Search system timezones")
            self.content.pack_start(search, False, False, 0)
            chosen = {"name": current}
            selected = self._label("Selected: " + current, css="ricespice-note")
            self.content.pack_start(selected, False, False, 0)
            choices = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=3)
            self.content.pack_start(choices, False, False, 0)
            visible = []

            def apply():
                name = chosen["name"]
                if name == current:
                    self._state("System timezone is already " + current)
                    return
                self._background(lambda: backend.set_timezone(name, expected=current),
                                 lambda _result: self.show_page("timezone"))

            apply_button = self._button("Apply system timezone", apply, primary=True)
            apply_button.set_sensitive(False)

            def choose(name):
                chosen["name"] = name
                selected.set_text("Selected: " + name)
                apply_button.set_sensitive(name != current)

            def update(_entry=None):
                for child in tuple(choices.get_children()):
                    child.destroy()
                text = search.get_text().strip().casefold()
                visible[:] = [name for name in zones if text in name.casefold()][:12] if text else []
                if not text:
                    choices.pack_start(self._label("Type to find a timezone; current selection is unchanged.",
                                                   css="ricespice-note"), False, False, 0)
                elif not visible:
                    choices.pack_start(self._label("No matching system timezones.",
                                                   css="ricespice-note"), False, False, 0)
                else:
                    for name in visible:
                        self._button(name, lambda value=name: choose(value), parent=choices)
                    if len([name for name in zones if text in name.casefold()]) > len(visible):
                        choices.pack_start(self._label("More matches exist; refine the search.",
                                                       css="ricespice-note"), False, False, 0)
                choices.show_all()

            # Local filtering is immediate; SearchEntry's search-changed may be delayed.
            search.connect("changed", update)
            search.connect("activate", lambda _entry: choose(visible[0]) if visible else None)
            update()
            self.content.show_all()

        def time_snapshot():
            result = backend.timezone_snapshot()
            try:
                result["ntp"] = backend.ntp_snapshot()
            except backend.SettingsError:
                result["ntp"] = None
            return result

        self._background(time_snapshot, present)

    def _power(self):
        self._button("Refresh power state", lambda: self.show_page("power"))

        def present(snapshot):
            battery = snapshot["battery"]
            self._text("Battery: " + (f"{battery['percent']}% · {battery['label']}"
                                      if battery is not None else "No battery detected"),
                       css="ricespice-note")
            current, supported = snapshot["current"], snapshot["supported"]
            self._text("Energy profile", css="ricespice-section")
            if current not in supported:
                self._text("No supported power-profile service or active profile available.",
                           css="ricespice-note")
            else:
                combo = self.Gtk.ComboBoxText()
                combo.get_accessible().set_name("Energy profile")
                for profile in supported:
                    combo.append(profile, profile.replace("-", " ").title())
                combo.set_active_id(current)
                self.content.pack_start(combo, False, False, 0)

                def apply():
                    selected = combo.get_active_id()
                    if selected is None:
                        self._state("Select a power profile first")
                        return
                    self._background(
                        lambda: backend.set_power_profile(selected, expected=current),
                        lambda _result: self.show_page("power"))

                self._button("Apply energy profile", apply, primary=True)
            self.content.show_all()

        self._background(backend.power_snapshot, present)
        self._text("Lock the current desktop or request a system suspend.",
                   css="ricespice-note")
        self._button("Lock screen", lambda: self._background(
            lambda: backend.power_action("lock"),
            lambda _result: self._state("Lock screen launched")), primary=True)

        def confirm():
            if os.environ.get("RICEBOWL_DE_NESTED") == "1":
                self._state("Suspend is disabled in nested preview")
                return
            dialog = self.Gtk.MessageDialog(
                transient_for=self.window, modal=True, message_type=self.Gtk.MessageType.QUESTION,
                buttons=self.Gtk.ButtonsType.YES_NO,
                text="Suspend this computer now?")
            response = dialog.run()
            dialog.destroy()
            if response == self.Gtk.ResponseType.YES:
                self._background(lambda: backend.power_action("suspend"),
                                 lambda _result: self._state("Suspend requested"))

        self._button("Suspend computer…", confirm)

    def _taskbar(self):
        """Real Luna-only taskbar preferences and actual service deep links."""
        self._text("The native XP taskbar shows your running windows, "
                   "application tray and live system indicators.", css="ricespice-note")
        self._text("Clock", css="ricespice-section")
        try:
            current = luna_panel_settings.load()
        except luna_panel_settings.LunaPanelError as exc:
            self._text(f"Clock preferences unavailable: {exc}", css="ricespice-note")
            self._button("Retry clock preferences", lambda: self.show_page("taskbar"))
        else:
            current_format = current["clock_format"]
            self._text("Choose the time format shown in the native Luna taskbar. "
                       "This applies when Luna is next started; the current "
                       "desktop and other rices are not changed.",
                       css="ricespice-note")
            formats = self.Gtk.ComboBoxText()
            formats.get_accessible().set_name("Luna clock format")
            formats.append("24h", "24-hour  ·  14:05")
            formats.append("12h", "12-hour  ·  2:05 PM")
            formats.set_active_id(current_format)
            self.content.pack_start(formats, False, False, 0)
            example = self._label("", css="ricespice-note")
            self.content.pack_start(example, False, False, 0)

            def apply():
                chosen = formats.get_active_id()
                if chosen not in luna_panel_settings.FORMATS:
                    self._state("Choose a valid clock format")
                    return
                self._background(
                    lambda: luna_panel_settings.save({"clock_format": chosen},
                                                     expected=current),
                    lambda _saved: self.show_page("taskbar"))

            save = self._button("Save clock format for next Luna login",
                                apply, primary=True)

            def update(_widget=None):
                selected = formats.get_active_id()
                example.set_text("Preview: " + ("2:05 PM" if selected == "12h"
                                                else "14:05"))
                save.set_sensitive(selected in luna_panel_settings.FORMATS
                                   and selected != current_format)

            formats.connect("changed", update)
            update()
            self._state(f"Current saved clock format: {current_format} · next Luna login")

        self._text("Taskbar behavior", css="ricespice-section")
        try:
            saved = luna_taskbar_settings.load()
        except luna_taskbar_settings.TaskbarSettingsError as exc:
            self._text(f"Taskbar preferences unavailable: {exc}", css="ricespice-note")
            self._button("Retry taskbar preferences", lambda: self.show_page("taskbar"))
        else:
            self._text("Quick Launch exposes Apps, Terminal and Show Desktop. "
                       "Auto-hide reduces the panel to a 3-pixel edge handle; "
                       "enter the edge to reveal it. Both apply at the next "
                       "Luna session, without changing XFCE or other rices.",
                       css="ricespice-note")
            auto_hide = self.Gtk.CheckButton(label="Automatically hide the taskbar")
            quick_launch = self.Gtk.CheckButton(label="Show Quick Launch buttons")
            auto_hide.set_active(saved["auto_hide"])
            quick_launch.set_active(saved["quick_launch"])
            for control in (auto_hide, quick_launch):
                self.content.pack_start(control, False, False, 0)

            def save_behavior():
                desired = {"auto_hide": auto_hide.get_active(),
                           "quick_launch": quick_launch.get_active()}
                self._background(
                    lambda: luna_taskbar_settings.save(desired, expected=saved),
                    lambda _value: self.show_page("taskbar"))

            save_button = self._button("Save taskbar options for next Luna login",
                                       save_behavior, primary=True)

            def sync_button(_widget=None):
                save_button.set_sensitive(
                    auto_hide.get_active() != saved["auto_hide"]
                    or quick_launch.get_active() != saved["quick_launch"])

            auto_hide.connect("toggled", sync_button)
            quick_launch.connect("toggled", sync_button)
            sync_button()
        self._text("Taskbar position is specified by the selected Rice recipe; "
                   "drag-to-reposition and a separate Lock taskbar switch are "
                   "not supported.", css="ricespice-note")

        self._text("Related controls", css="ricespice-section")
        flow = self._luna_new_flow()
        for key in ("notifications", "network", "audio", "power", "timezone", "appearance"):
            flow.add(self._luna_category_button(key))
        self.content.pack_start(flow, False, False, 0)
        self._text("Start favorites and recent programs are managed in the Start menu. "
                   "Per-app icon visibility is provider-owned; no false toggles "
                   "are shown.", css="ricespice-note")

    def _appearance(self):
        self._text("Changes here apply at the next RiceBowl Wayland login, not immediately.",
                   css="ricespice-note")

        def present():
            current, previous = recipes.current_selection()
            choices = [name for name in recipes.BUILTINS]
            choices.extend(recipe.recipe_id for recipe, _path in recipes.imported_recipes())
            self._text("Desktop theme", css="ricespice-section")
            combo = self.Gtk.ComboBoxText()
            combo.get_accessible().set_name("Rice recipe for the next Wayland login")
            for name in choices:
                combo.append(name, name)
            combo.set_active_id(current)
            self.content.pack_start(combo, False, False, 0)
            self._state("Next-login rice: " + current)

            def apply():
                selected = combo.get_active_id()
                if selected is None or selected == current:
                    return
                self._background(lambda: recipes.change_selection(
                    selected, expected_active=current),
                    lambda _result: self.show_page("appearance"))

            save = self._button("Use at next login", apply, primary=True)
            combo.connect("changed", lambda widget: save.set_sensitive(
                widget.get_active_id() is not None
                and widget.get_active_id() != current))
            save.set_sensitive(False)
            if previous is not None:
                self._button("Restore previous next-login rice", lambda: self._background(
                    lambda: recipes.change_selection(restore=True, expected_active=current),
                    lambda _result: self.show_page("appearance")))
            self._text("Desktop background", css="ricespice-section")
            self._text("Wallpapers belong to Rice recipes. The installed Rice Creator "
                       "can select bundled backgrounds or import verified private PNGs. "
                       "Save and activate that recipe to use its wallpaper; this Control "
                       "Panel does not silently overwrite the running desktop.",
                       css="ricespice-note")
            if backend.external_tool("luna_creator") is not None:
                self._button("Open Rice Creator for wallpaper and themes…",
                             lambda: self._background(
                                 lambda: backend.open_external("luna_creator"),
                                 lambda _result: self._state("Rice Creator launch requested")))
            else:
                self._text("Rice Creator is not installed. Wallpaper editing is "
                           "unavailable in this session.", css="ricespice-note")
            self.content.show_all()

        try:
            present()
        except (OSError, recipes.RecipeError) as exc:
            self._state(f"Rice selection unavailable: {exc}")


def launch(*, page: str = "network", luna: bool = False) -> None:
    valid_pages = {section[0] for section in (LUNA_SECTIONS if luna else SECTIONS)}
    if luna:
        valid_pages.add("home")
    if page not in valid_pages:
        raise backend.SettingsError("This settings page is unavailable")
    try:
        Gtk, Gdk, GLib = _gtk_modules()
    except (ImportError, ValueError) as exc:
        raise backend.SettingsError("RiceSpice requires GTK3 introspection support") from exc
    ok, _arguments = Gtk.init_check([])
    if not ok:
        raise backend.SettingsError("A working graphical display is required for RiceSpice")
    RiceSpiceWindow(Gtk, Gdk, GLib, page=page, luna=luna)
    Gtk.main()


def launch_display_confirmation(token: str) -> None:
    """Short-lived on-login approval window; closing it never commits a trial."""
    if not wayland_displays._in_session() or os.environ.get("RICEBOWL_DE_NESTED") != "0":
        raise backend.SettingsError("Display confirmation requires a full RiceBowl login")
    change = display_guard.DisplayChange(token, wayland_displays.runtime_root())
    display_guard._state_path(change)  # Validate the exact token before GTK startup.
    Gtk, _Gdk, GLib = _gtk_modules()
    if not Gtk.init_check([])[0]:
        raise backend.SettingsError("Cannot show the monitor confirmation window")
    window = Gtk.Window(title="RiceBowl · Confirm monitor layout")
    window.set_default_size(470, 180)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.set_keep_above(True)
    window.connect("destroy", lambda _widget: Gtk.main_quit())
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    content.set_border_width(24)
    window.add(content)
    label = Gtk.Label(label="The saved monitor layout was tried automatically. "
                      "Keep it within 18 seconds or it will be restored.")
    label.set_line_wrap(True)
    label.set_xalign(0)
    content.pack_start(label, True, True, 0)
    keep = Gtk.Button(label="Keep this monitor layout")
    keep.get_accessible().set_name("Confirm and keep the complete monitor layout")
    keep.set_sensitive(False)
    content.pack_start(keep, False, False, 0)
    approval_sent = [False]

    def approve(_button):
        if approval_sent[0]:
            return
        try:
            display_guard.keep_change(change)
            approval_sent[0] = True
            label.set_text("Confirmation sent. Verifying the display layout…")
            keep.set_sensitive(False)
        except (OSError, RuntimeError, ValueError) as exc:
            label.set_text("Cannot confirm: " + str(exc) + ". Rollback remains active.")

    keep.connect("clicked", approve)

    def refresh():
        try:
            state, detail = display_guard.read_status(change)
        except (OSError, RuntimeError, ValueError):
            label.set_text("Monitor guard unavailable. Await its automatic rollback.")
            keep.set_sensitive(False)
            return False
        if state == "pending":
            if not approval_sent[0]:
                label.set_text("Confirm the saved layout within 18 seconds, or it will roll back.")
            keep.set_sensitive(not approval_sent[0])
        elif state == "starting":
            keep.set_sensitive(False)
        else:
            keep.set_sensitive(False)
            label.set_text("Monitor layout: " + state + ". " + detail)
            GLib.timeout_add(1300, lambda: (window.destroy(), False)[1])
            return False
        return True

    window.show_all()
    window.present()
    refresh()
    GLib.timeout_add(220, refresh)
    Gtk.main()
