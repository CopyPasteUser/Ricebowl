"""On-demand RiceSpice GTK settings window for the experimental Wayland DE.

Real services are queried only when their page is opened or refreshed; this
program exits on close and does not replace a distribution settings daemon.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import audio_devices, recipes, settings_backend as backend


SECTIONS = (
    ("network", "Network", "NetworkManager connectivity and Wi-Fi radio"),
    ("audio", "Sound", "Playback and recording devices"),
    ("bluetooth", "Bluetooth", "Adapter and paired devices"),
    ("displays", "Displays", "Monitors, scaling and arrangement"),
    ("input", "Input", "Pointer and keyboard preferences"),
    ("accessibility", "Accessibility", "Assistive preferences"),
    ("timezone", "Date & time", "System clock and timezone"),
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

    def _button(self, label: str, callback: Callable[[], None], *, primary: bool = False):
        button = self.Gtk.Button(label=label)
        button.get_accessible().set_name(label)
        if primary:
            button.get_style_context().add_class("ricespice-action")
        button.connect("clicked", lambda _button: callback())
        self.content.pack_start(button, False, False, 0)
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

    def show_page(self, name: str):
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
            self._network()
        elif name == "audio":
            self._audio()
        elif name == "bluetooth":
            self._bluetooth()
        elif name == "power":
            self._power()
        elif name == "appearance":
            self._appearance()
        else:
            self._external(name)
        self.content.show_all()

    def _network(self):
        self._text("Turning Wi-Fi off can disconnect an active network session.", css="ricespice-note")
        self._button("Refresh connection state", lambda: self.show_page("network"))

        def present(enabled):
            self._state("Wi-Fi radio: enabled" if enabled else "Wi-Fi radio: disabled")
            self._button("Disable Wi-Fi" if enabled else "Enable Wi-Fi", lambda: self._background(
                lambda: backend.set_wifi(not enabled, expected=enabled),
                lambda _result: self.show_page("network")), primary=True)
            self.content.show_all()

        self._background(backend.wifi_state, present)

    def _audio(self):
        self._button("Refresh audio devices", lambda: self.show_page("audio"))

        def present(inventory):
            self._state("Devices from the active PulseAudio-compatible server")
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
            self.content.show_all()

        self._background(audio_devices.inspect, present)

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
