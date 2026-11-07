"""On-demand RiceSpice GTK settings window for the experimental Wayland DE.

Real services are queried only when their page is opened or refreshed; this
program exits on close and does not replace a distribution settings daemon.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from macrice.riceware import media

from . import audio_devices, recipes, settings_backend as backend


SECTIONS = (
    ("network", "Network", "NetworkManager connectivity and Wi-Fi radio"),
    ("audio", "Sound", "Audio devices and media playback"),
    ("bluetooth", "Bluetooth", "Adapter and paired devices"),
    ("displays", "Displays", "Monitors, scaling and arrangement"),
    ("input", "Input", "Pointer and keyboard preferences"),
    ("accessibility", "Accessibility", "Assistive preferences"),
    ("timezone", "Date & time", "System clock and timezone preferences"),
    ("power", "Power & security", "Lock and suspend via system services"),
    ("appearance", "Rice & appearance", "Next-login shell recipe selection"),
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


class RiceSpiceWindow:
    def __init__(self, Gtk, Gdk, GLib):
        self.Gtk, self.GLib = Gtk, GLib
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ricespice")
        self.worker_slots = threading.BoundedSemaphore(2)
        self.generation = 0
        self.busy = False
        self.closed = False
        self.page = "network"
        self._selecting_nav = False
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        if Gdk.Screen.get_default() is not None:
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.window = Gtk.Window(title="RiceSpice · System settings")
        self.window.set_default_size(810, 580)
        self.window.set_size_request(570, 400)
        self.window.get_style_context().add_class("ricespice-window")
        self.window.connect("destroy", self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.window.add(root)
        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        navigation.set_size_request(215, -1)
        navigation.get_style_context().add_class("ricespice-nav")
        root.pack_start(navigation, False, False, 0)
        brand = Gtk.Label(label="RiceSpice")
        brand.set_xalign(0)
        brand.get_style_context().add_class("ricespice-brand")
        navigation.pack_start(brand, False, False, 0)
        self.nav_buttons = {}
        for key, title, _description in SECTIONS:
            button = Gtk.ToggleButton(label=title)
            button.get_child().set_xalign(0)
            button.get_accessible().set_name(f"RiceSpice {title} settings")
            button.connect("clicked", lambda _button, name=key:
                           None if self._selecting_nav else self.show_page(name))
            navigation.pack_start(button, False, False, 0)
            self.nav_buttons[key] = button

        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.pack_start(viewport, True, True, 0)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        self.content.get_style_context().add_class("ricespice-content")
        viewport.add(self.content)
        self.show_page("network")
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
        self.content.pack_start(self._label(message, css=css), False, False, 0)

    def _button(self, label: str, callback: Callable[[], None], *, primary: bool = False,
                parent=None):
        button = self.Gtk.Button(label=label)
        button.get_accessible().set_name(label)
        if primary:
            button.get_style_context().add_class("ricespice-action")
        button.connect("clicked", lambda _button: callback())
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
        future = self.executor.submit(work)

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

    def show_page(self, name: str, *, rescan: bool = False):
        if name not in self.nav_buttons:
            return
        self.generation += 1
        self.busy = False
        self.page = name
        self._selecting_nav = True
        try:
            for key, button in self.nav_buttons.items():
                if button.get_active() != (key == name):
                    button.set_active(key == name)
        finally:
            self._selecting_nav = False
        for widget in tuple(self.content.get_children()):
            widget.destroy()
        _key, title, description = next(section for section in SECTIONS if section[0] == name)
        self._text(title, css="ricespice-title")
        self._text(description, css="ricespice-desc")
        self.status = self._label("", css="ricespice-state")
        self.content.pack_end(self.status, False, False, 0)
        if name == "network":
            self._network(rescan=rescan)
        elif name == "audio":
            self._audio()
        elif name == "bluetooth":
            self._bluetooth()
        elif name == "power":
            self._power()
        elif name == "timezone":
            self._timezone()
        elif name == "appearance":
            self._appearance()
        else:
            self._external(name)
        self.content.show_all()

    def _network(self, *, rescan: bool = False):
        self._text("Turning Wi-Fi off can disconnect an active network session.", css="ricespice-note")
        self._button("Refresh visible networks", lambda: self.show_page("network", rescan=True))

        def present(snapshot):
            enabled = snapshot["enabled"]
            self._state("Wi-Fi radio: enabled" if enabled else "Wi-Fi radio: disabled")
            self._button("Disable Wi-Fi" if enabled else "Enable Wi-Fi", lambda: self._background(
                lambda: backend.set_wifi(not enabled, expected=enabled),
                lambda _result: self.show_page("network")), primary=True)
            self._text("Visible networks", css="ricespice-section")
            networks = snapshot["networks"]
            if not enabled:
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
            self.content.show_all()

        self._background(lambda: backend.wifi_snapshot(rescan=rescan), present)

    def _audio(self):
        self._button("Refresh devices and players", lambda: self.show_page("audio"))

        def collect():
            # Both services are optional; failure of one must not hide the other.
            def read(reader):
                try:
                    return reader()
                except Exception as exc:
                    return exc

            return read(audio_devices.inspect), read(media.read_media_players)

        def present(snapshot):
            inventory, players = snapshot
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

            search.connect("search-changed", update)
            search.connect("activate", lambda _entry: choose(visible[0]) if visible else None)
            update()
            self.content.show_all()

        self._background(backend.timezone_snapshot, present)

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

    def _appearance(self):
        self._text("Changes here apply at the next RiceBowl Wayland login, not immediately.",
                   css="ricespice-note")

        def present():
            current, previous = recipes.current_selection()
            choices = [name for name in recipes.BUILTINS]
            choices.extend(recipe.recipe_id for recipe, _path in recipes.imported_recipes())
            combo = self.Gtk.ComboBoxText()
            for name in choices:
                combo.append(name, name)
            combo.set_active_id(current)
            self.content.pack_start(combo, False, False, 0)
            self._state("Next-login rice: " + current)

            def apply():
                selected = combo.get_active_id()
                if selected is None:
                    return
                self._background(lambda: recipes.change_selection(
                    selected, expected_active=current),
                    lambda _result: self.show_page("appearance"))

            self._button("Use at next login", apply, primary=True)
            if previous is not None:
                self._button("Restore previous next-login rice", lambda: self._background(
                    lambda: recipes.change_selection(restore=True, expected_active=current),
                    lambda _result: self.show_page("appearance")))
            self.content.show_all()

        try:
            present()
        except (OSError, recipes.RecipeError) as exc:
            self._state(f"Rice selection unavailable: {exc}")


def launch() -> None:
    try:
        Gtk, Gdk, GLib = _gtk_modules()
    except (ImportError, ValueError) as exc:
        raise backend.SettingsError("RiceSpice requires GTK3 introspection support") from exc
    ok, _arguments = Gtk.init_check([])
    if not ok:
        raise backend.SettingsError("A working graphical display is required for RiceSpice")
    RiceSpiceWindow(Gtk, Gdk, GLib)
    Gtk.main()
