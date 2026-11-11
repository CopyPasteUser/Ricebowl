"""On-demand RiceSpice GTK settings window for the experimental Wayland DE.

Real services are queried only when their page is opened or refreshed; this
program exits on close and does not replace a distribution settings daemon.
"""

from __future__ import annotations

import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from macrice import display_guard
from macrice.riceware import media

from . import audio_devices, display_presets, display_restore, network_enrollment
from . import notifications, preferences, recipes
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
