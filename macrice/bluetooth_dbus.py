"""BlueZ system D-Bus transport, independent of the bluetoothctl executable.

BlueZ is the Linux Bluetooth stack; bluetoothctl and this module are separate
control interfaces to that stack. All calls are bounded and run off the UI thread.
"""

from __future__ import annotations

import re
import threading


_ADDRESS = re.compile(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}\Z")
_DISCOVERY_LOCK = threading.Lock()


def _connection():
    from gi.repository import Gio

    return Gio, Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def _objects():
    from gi.repository import GLib

    Gio, bus = _connection()
    answer = bus.call_sync(
        "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
        "GetManagedObjects", None, GLib.VariantType.new("(a{oa{sa{sv}}})"),
        Gio.DBusCallFlags.NONE, 2500, None,
    )
    return answer.unpack()[0]


def _value(value):
    return value.unpack() if hasattr(value, "unpack") else value


def snapshot():
    """Return (powered, adapter path, [(address, name, paired, connected)]).

    An empty list is a valid adapter with no cached devices; no adapter is an
    error, distinct from an adapter that is switched off.
    """
    objects = _objects()
    adapters = sorted((path, props["org.bluez.Adapter1"])
                      for path, props in objects.items()
                      if "org.bluez.Adapter1" in props)
    if not adapters:
        raise RuntimeError("No BlueZ adapter is available on system D-Bus")
    path, adapter = adapters[0]
    powered = _value(adapter.get("Powered"))
    if not isinstance(powered, bool):
        raise RuntimeError("Adapter power state is missing")
    devices = []
    for device_path, interfaces in objects.items():
        props = interfaces.get("org.bluez.Device1")
        if not props or not device_path.startswith(path + "/"):
            continue
        address = _value(props.get("Address"))
        if not isinstance(address, str) or not address:
            continue
        alias = _value(props.get("Alias")) or _value(props.get("Name"))
        paired = _value(props.get("Paired"))
        connected = _value(props.get("Connected"))
        # BlueZ's Paired/Connected properties are booleans. A malformed
        # service response must never turn e.g. "false" into True or make
        # an unverified device appear safely connected in the tray.
        if type(paired) is not bool or type(connected) is not bool:
            raise RuntimeError("BlueZ device state is unavailable; refresh")
        devices.append((address, str(alias or address), paired, connected))
    return powered, path, tuple(sorted(devices, key=lambda item: item[1].casefold()))[:32]


def set_power(adapter_path: str, enabled: bool) -> None:
    from gi.repository import GLib

    Gio, bus = _connection()
    bus.call_sync(
        "org.bluez", adapter_path, "org.freedesktop.DBus.Properties",
        "Set", GLib.Variant("(ssv)",
                            ("org.bluez.Adapter1", "Powered", GLib.Variant("b", enabled))),
        None, Gio.DBusCallFlags.NONE, 4000, None,
    )


def set_connection(address: str, connected: bool, *,
                   expected_adapter: str | None = None) -> None:
    """Act only on one unambiguous, live BlueZ device under the selected adapter.

    A Bluetooth address alone is not an ObjectManager identity: the same
    address can be cached on multiple USB adapters. An explicit RiceSpice
    request is bound to its reviewed adapter; legacy callers without an
    adapter may continue only when a single matching device is present.
    """
    if (type(address) is not str or not _ADDRESS.fullmatch(address)
            or type(connected) is not bool):
        raise ValueError("Select a valid Bluetooth device and action")
    objects = _objects()
    if expected_adapter is not None:
        if (type(expected_adapter) is not str
                or "org.bluez.Adapter1" not in objects.get(expected_adapter, {})):
            raise ValueError("Bluetooth adapter changed; refresh before applying")
    matches = []
    for path, interfaces in objects.items():
        props = interfaces.get("org.bluez.Device1")
        value = _value(props.get("Address")) if props else None
        if type(value) is not str or value.upper() != address.upper():
            continue
        if expected_adapter is not None and not path.startswith(expected_adapter + "/"):
            continue
        matches.append((path, props))
    if len(matches) != 1:
        raise ValueError("Bluetooth device is missing or ambiguous; refresh before applying")
    path, props = matches[0]
    paired = _value(props.get("Paired"))
    current = _value(props.get("Connected"))
    if type(paired) is not bool or type(current) is not bool:
        raise ValueError("Bluetooth connection state is unavailable; refresh")
    if connected and not paired:
        raise ValueError("Pair the device in Bluetooth settings first")
    if current is connected:
        # Explicit idempotence: a disconnected/connected device must never
        # receive another possibly disruptive BlueZ action for a no-op.
        return
    Gio, bus = _connection()
    bus.call_sync(
        "org.bluez", path, "org.bluez.Device1",
        "Connect" if connected else "Disconnect", None, None,
        Gio.DBusCallFlags.NONE, 8000, None,
    )


def discover(duration: int = 9, *, cancel: threading.Event | None = None):
    """Own one short BlueZ discovery session and always release that session.

    This runs in the existing Riceware worker, never on GTK's main thread.
    Closing the flyout sets ``cancel`` and releases discovery promptly.
    Other applications' independent BlueZ discovery sessions are unaffected.
    """
    if not isinstance(duration, int) or not 2 <= duration <= 15:
        raise ValueError("Discovery duration must be 2–15 seconds")
    if cancel is None:
        cancel = threading.Event()
    if not _DISCOVERY_LOCK.acquire(blocking=False):
        raise RuntimeError("A Bluetooth discovery session is already running")
    try:
        return _discover_owned(duration, cancel)
    finally:
        _DISCOVERY_LOCK.release()


def _discover_owned(duration, cancel):
    if cancel.is_set():
        return snapshot()
    powered, adapter_path, _devices = snapshot()
    if powered is not True:
        raise RuntimeError("Turn Bluetooth on before scanning")
    if cancel.is_set():
        return snapshot()
    Gio, bus = _connection()
    acquired = False
    failure = None
    try:
        bus.call_sync("org.bluez", adapter_path, "org.bluez.Adapter1",
                      "StartDiscovery", None, None, Gio.DBusCallFlags.NONE, 5000, None)
        acquired = True
        cancel.wait(duration)
    finally:
        if acquired:
            try:
                bus.call_sync("org.bluez", adapter_path, "org.bluez.Adapter1",
                              "StopDiscovery", None, None, Gio.DBusCallFlags.NONE, 5000, None)
            except Exception as exc:
                failure = exc
    if failure is not None:
        raise RuntimeError("Could not stop this Bluetooth discovery session") from failure
    return snapshot()


def pair_device(address: str, *, expected_adapter: str | None = None) -> None:
    """Pair exactly one live BlueZ device through the system's existing agent.

    A MAC address alone is ambiguous across multiple cached USB adapters.
    Never pair the first match blindly, even if another match is already
    paired. Caller-supplied adapter identity remains optional for old UIs.
    """
    if type(address) is not str or not _ADDRESS.fullmatch(address):
        raise ValueError("Select a valid Bluetooth address")
    objects = _objects()
    if expected_adapter is not None:
        if (type(expected_adapter) is not str
                or "org.bluez.Adapter1" not in objects.get(expected_adapter, {})):
            raise ValueError("Bluetooth adapter changed; rescan before pairing")
    matches = []
    for path, interfaces in objects.items():
        props = interfaces.get("org.bluez.Device1")
        if not props:
            continue
        value = _value(props.get("Address"))
        if type(value) is not str or value.upper() != address.upper():
            continue
        if expected_adapter is not None and not path.startswith(expected_adapter + "/"):
            continue
        matches.append((path, props))
    if len(matches) != 1:
        raise ValueError("Bluetooth device missing or ambiguous; rescan before pairing")
    path, props = matches[0]
    paired = _value(props.get("Paired"))
    if type(paired) is not bool:
        raise ValueError("Bluetooth pairing state is unavailable; rescan before pairing")
    if paired:
        return
    Gio, bus = _connection()
    bus.call_sync("org.bluez", path, "org.bluez.Device1",
                  "Pair", None, None, Gio.DBusCallFlags.NONE, 25000, None)
