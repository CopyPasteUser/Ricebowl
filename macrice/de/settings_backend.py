"""Explicit, bounded RiceSpice settings actions for the opt-in Wayland shell.

The GTK frontend is on demand. This module has no GTK dependency and never
starts a service, a privileged helper or a user-selected executable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Any


class SettingsError(ValueError):
    """A setting is unavailable, denied, stale, or cannot be verified."""


EXTERNAL_PAGES = {
    "connections": (("nm-connection-editor",),),
    "displays": (("wdisplays",),),
    "input": (("gnome-control-center", "mouse"),),
    "accessibility": (("gnome-control-center", "universal-access"),),
    "timezone": (("gnome-control-center", "datetime"),),
}

_TIMEZONE = re.compile(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+){0,4}\Z")
_CONNECTION_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")
_PROFILE_TYPES = frozenset(("802-3-ethernet", "ethernet", "802-11-wireless", "wifi",
                           "vpn", "wireguard"))


def _timedatectl(*args: str) -> str:
    """Bounded, locale-independent systemd-timedated query or policy action."""
    binary = shutil.which("timedatectl")
    if binary is None:
        raise SettingsError("timedatectl is not installed")
    try:
        result = subprocess.run([binary, *args], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=8, check=False,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SettingsError("System time service is unavailable or timed out") from exc
    if result.returncode or len(result.stdout) > 96 * 1024:
        raise SettingsError("System time service denied the request or returned invalid data")
    try:
        return result.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SettingsError("System time service returned invalid data") from exc


def _timezone_name(name: str) -> bool:
    return (type(name) is str and len(name) <= 80 and _TIMEZONE.fullmatch(name)
            is not None and not any(part in (".", "..") for part in name.split("/")))


def timezone_snapshot() -> dict[str, Any]:
    """Read the actual system timezone and allowlisted timezones on demand."""
    current = _timedatectl("show", "-p", "Timezone", "--value")
    rows = _timedatectl("list-timezones", "--no-pager").splitlines()
    if (not _timezone_name(current) or not 1 <= len(rows) <= 1000
            or any(not _timezone_name(item) for item in rows)
            or len(rows) != len(set(rows)) or current not in rows):
        raise SettingsError("System timezone inventory is invalid or incomplete")
    return {"current": current, "zones": tuple(sorted(rows))}


def ntp_snapshot() -> dict[str, bool]:
    """Read timedated's actual automatic time capability and state."""
    pairs = _timedatectl("show", "-p", "CanNTP", "-p", "NTP")
    rows = pairs.splitlines()
    if len(rows) != 2 or any("=" not in line for line in rows):
        raise SettingsError("timedated returned an invalid NTP state")
    values = dict(line.split("=", 1) for line in rows)
    if set(values) != {"CanNTP", "NTP"} or any(
            value not in ("yes", "no") for value in values.values()):
        raise SettingsError("timedated returned an invalid NTP state")
    return {"available": values["CanNTP"] == "yes", "enabled": values["NTP"] == "yes"}


def set_ntp(enabled: bool, *, expected: bool) -> dict[str, bool]:
    """Explicit polkit-gated system-wide time-sync action and verified readback."""
    if type(enabled) is not bool or type(expected) is not bool:
        raise SettingsError("Invalid automatic time selection")
    before = ntp_snapshot()
    if not before["available"]:
        raise SettingsError("This system does not offer automatic time synchronization")
    if before["enabled"] != expected:
        raise SettingsError("Automatic time state changed; refresh before applying")
    if enabled == expected:
        return before
    _timedatectl("set-ntp", "true" if enabled else "false")
    after = ntp_snapshot()
    if after["enabled"] != enabled:
        raise SettingsError("Automatic time may have changed; verification failed")
    return after


_CLOCK_FORMAT = "%Y-%m-%d %H:%M:%S"


def set_system_clock(value: str, *, expected_ntp: bool = False) -> str:
    """Explicit, polkit-gated local system-clock change, never an automatic adjustment."""
    if type(value) is not str or type(expected_ntp) is not bool or expected_ntp:
        raise SettingsError("Select a full local date/time with NTP disabled")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        raise SettingsError("Use YYYY-MM-DD HH:MM:SS local time")
    try:
        target = datetime.strptime(value, _CLOCK_FORMAT)
    except ValueError as exc:
        raise SettingsError("Choose a valid local calendar date and time") from exc
    if not 1970 <= target.year <= 2099:
        raise SettingsError("System clock year is outside the supported range")
    current = ntp_snapshot()
    if current["enabled"]:
        raise SettingsError("Automatic time is enabled; disable it and refresh first")
    _timedatectl("set-time", value)
    # Compare within a bounded command/verification interval, not exact seconds.
    if abs(datetime.now() - target) > timedelta(seconds=15):
        raise SettingsError("System time may have changed; verification failed")
    return value


def set_timezone(name: str, *, expected: str) -> str:
    """Polkit-gated system timezone change with stale review and readback."""
    if not _timezone_name(name) or not _timezone_name(expected):
        raise SettingsError("Choose a supported timezone")
    before = timezone_snapshot()
    if before["current"] != expected:
        raise SettingsError("System timezone changed; refresh before applying")
    if name not in before["zones"]:
        raise SettingsError("Choose a timezone from the current system list")
    if name == expected:
        return name
    _timedatectl("set-timezone", name)
    if _timedatectl("show", "-p", "Timezone", "--value") != name:
        raise SettingsError("Timezone may have changed; verification failed")
    return name


def external_tool(page: str) -> tuple[str, ...] | None:
    """Return a fixed available tool, never a recipe-defined command."""
    if page not in EXTERNAL_PAGES:
        raise SettingsError("Unsupported settings page")
    for candidate in EXTERNAL_PAGES[page]:
        if shutil.which(candidate[0]):
            return candidate
    return None


def open_external(page: str) -> None:
    candidate = external_tool(page)
    if candidate is None:
        raise SettingsError("No supported settings application is installed")
    try:
        subprocess.Popen(list(candidate), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
    except OSError as exc:
        raise SettingsError("Could not start the installed settings application") from exc


def _nmcli(*args: str) -> str:
    binary = shutil.which("nmcli")
    if not binary:
        raise SettingsError("NetworkManager nmcli is not installed")
    try:
        response = subprocess.run([binary, "--wait", "3", *args],
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=5, check=False, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SettingsError("NetworkManager is unavailable or timed out") from exc
    if response.returncode or len(response.stdout) > 4096:
        raise SettingsError("NetworkManager denied the request or returned invalid data")
    try:
        return response.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SettingsError("NetworkManager returned invalid radio state") from exc


def _nmcli_profile(*args: str, mutate: bool = False) -> str:
    """UTF-8 profile inventory/operations; no --show-secrets, shell, or credentials."""
    binary = shutil.which("nmcli")
    if not binary:
        raise SettingsError("NetworkManager nmcli is not installed")
    try:
        reply = subprocess.run([binary, "--wait", "15" if mutate else "3", *args],
                               stdin=subprocess.DEVNULL, capture_output=True,
                               timeout=19 if mutate else 6, check=False,
                               env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SettingsError("NetworkManager profile request timed out or unavailable; "
                            "refresh before retrying") from exc
    if reply.returncode or len(reply.stdout) > 32 * 1024:
        raise SettingsError("NetworkManager rejected the profile request; "
                            "the connection may have changed, refresh before retrying")
    try:
        return reply.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SettingsError("NetworkManager returned invalid profile data") from exc


def _terse_fields(line: str) -> list[str]:
    """Decode NetworkManager's -t -e yes escaped colon/backslash format."""
    fields = []
    part = []
    escaped = False
    for char in line:
        if escaped:
            if char not in (":", "\\"):
                raise SettingsError("Malformed NetworkManager escaped profile")
            part.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(part))
            part = []
        else:
            part.append(char)
    if escaped:
        raise SettingsError("Malformed NetworkManager escaped profile")
    fields.append("".join(part))
    return fields


def connection_profiles() -> list[dict[str, Any]]:
    """Read saved wired/Wi-Fi/VPN profiles without ever fetching credentials."""
    rows = _nmcli_profile("-t", "-e", "yes", "-f", "UUID,TYPE,NAME,DEVICE", "con", "show")
    active = _nmcli_profile("-t", "-e", "yes", "-f", "UUID", "con", "show", "--active")
    uuids = set()
    for item in active.splitlines():
        uuid = item.strip()
        if not _CONNECTION_UUID.fullmatch(uuid) or uuid in uuids:
            raise SettingsError("Invalid NetworkManager active profile identity")
        uuids.add(uuid)
    if len(uuids) > 128 or len(rows.splitlines()) > 128:
        raise SettingsError("Too many NetworkManager profiles")
    results = []
    found = set()
    for line in rows.splitlines():
        parts = _terse_fields(line)
        if len(parts) != 4:
            raise SettingsError("Malformed NetworkManager profile inventory")
        uuid, kind, name, device = parts
        if not _CONNECTION_UUID.fullmatch(uuid) or uuid in found:
            raise SettingsError("Invalid or duplicate NetworkManager profile")
        found.add(uuid)
        if kind not in _PROFILE_TYPES:
            continue
        if len(name) > 160 or len(device) > 80:
            raise SettingsError("Invalid NetworkManager profile label")
        label = "".join(ch for ch in name if ch.isprintable())[:120] or "Unnamed profile"
        results.append({"uuid": uuid, "kind": kind, "name": label,
                        "device": device if device != "--" else "",
                        "active": uuid in uuids})
    return results


def set_connection_profile(uuid: str, enabled: bool, *, expected: bool) -> dict[str, Any]:
    """Activate/deactivate a previously saved profile with stale-state readback."""
    if (type(uuid) is not str or not _CONNECTION_UUID.fullmatch(uuid)
            or type(enabled) is not bool or type(expected) is not bool):
        raise SettingsError("Select a saved network profile")
    before = next((item for item in connection_profiles() if item["uuid"] == uuid), None)
    if before is None or before["active"] != expected:
        raise SettingsError("Network profile changed; refresh before applying")
    if enabled == expected:
        return before
    try:
        _nmcli_profile("con", "up" if enabled else "down", "uuid", uuid, mutate=True)
    except SettingsError as exc:
        raise SettingsError("Network profile may have changed; refresh the current state") from exc
    after = next((item for item in connection_profiles() if item["uuid"] == uuid), None)
    if after is None or after["active"] != enabled:
        raise SettingsError("Network profile may have changed; verification failed")
    return after


def wifi_state() -> bool:
    state = _nmcli("radio", "wifi")
    if state not in ("enabled", "disabled"):
        raise SettingsError("Wi-Fi radio state is unavailable")
    return state == "enabled"


def set_wifi(enabled: bool, *, expected: bool) -> bool:
    """Optimistic concurrency guard prevents stale one-click radio changes."""
    if type(enabled) is not bool or type(expected) is not bool:
        raise SettingsError("Wi-Fi selection must be explicit")
    if wifi_state() != expected:
        raise SettingsError("Wi-Fi state changed; refresh before applying")
    if enabled == expected:
        return enabled
    _nmcli("radio", "wifi", "on" if enabled else "off")
    if wifi_state() != enabled:
        raise SettingsError("Wi-Fi may have changed; verification failed")
    return enabled


def wifi_snapshot(*, rescan: bool = False) -> dict[str, Any]:
    """Read NetworkManager's bounded visible-SSID inventory on demand."""
    from macrice import hardware_status

    if type(rescan) is not bool:
        raise SettingsError("Wi-Fi scan selection must be explicit")
    enabled = wifi_state()
    networks = hardware_status.read_wifi_networks(rescan=rescan) if enabled else ()
    return {"enabled": enabled, "networks": [
        {"ssid": item.ssid, "signal": item.signal, "security": item.security,
         "connected": item.connected} for item in networks]}


def _visible_wifi(ssid: str) -> dict[str, Any]:
    if type(ssid) is not str or not ssid or "\x00" in ssid:
        raise SettingsError("Select a visible Wi-Fi network")
    try:
        if len(ssid.encode("utf-8")) > 32:
            raise SettingsError("Wi-Fi network name is invalid")
    except UnicodeEncodeError as exc:
        raise SettingsError("Wi-Fi network name is invalid") from exc
    snapshot = wifi_snapshot()
    selected = next((entry for entry in snapshot["networks"]
                     if entry["ssid"] == ssid and not entry["connected"]), None)
    if not snapshot["enabled"] or selected is None:
        raise SettingsError("Wi-Fi network changed; scan again before connecting")
    return selected


def connect_visible_wifi(ssid: str) -> bool:
    """Join only a currently visible SSID; saved credentials stay with NetworkManager."""
    from macrice import hardware_status

    _visible_wifi(ssid)
    try:
        verified = hardware_status.connect_wifi(ssid)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SettingsError("Wi-Fi connection failed; saved credentials may be missing") from exc
    if not verified:
        raise SettingsError("Wi-Fi may have changed; connection could not be verified")
    return True


def connect_secure_visible_wifi(ssid: str, password: str) -> bool:
    """Send a transient WPA-Personal passphrase through the existing stdin adapter."""
    from macrice import hardware_status

    if (type(password) is not str or not 8 <= len(password) <= 63
            or any(character in password for character in ("\r", "\n", "\x00"))):
        raise SettingsError("WPA passphrase must be 8–63 characters without line breaks")
    network = _visible_wifi(ssid)
    security = network["security"].upper()
    if "WPA" not in security or "802.1X" in security or "EAP" in security:
        raise SettingsError("This network requires an external authentication editor")
    try:
        verified = hardware_status.connect_wifi_secured(ssid, password)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SettingsError("Wi-Fi authentication failed; check password or network settings") from exc
    if not verified:
        raise SettingsError("Wi-Fi may have changed; connection could not be verified")
    return True


def bluetooth_snapshot() -> dict[str, Any]:
    from macrice import bluetooth_dbus

    try:
        powered, path, devices = bluetooth_dbus.snapshot()
    except Exception as exc:
        raise SettingsError("BlueZ Bluetooth service is unavailable") from exc
    return {"powered": powered, "adapter": path,
            "devices": [{"address": address, "label": name[:80],
                         "paired": paired, "connected": connected}
                        for address, name, paired, connected in devices]}


def set_bluetooth_power(enabled: bool, *, expected: bool) -> dict[str, Any]:
    if type(enabled) is not bool or type(expected) is not bool:
        raise SettingsError("Bluetooth selection must be explicit")
    before = bluetooth_snapshot()
    if before["powered"] != expected:
        raise SettingsError("Bluetooth adapter changed; refresh before applying")
    if enabled != expected:
        from macrice import bluetooth_dbus

        try:
            bluetooth_dbus.set_power(before["adapter"], enabled)
        except Exception as exc:
            raise SettingsError("BlueZ denied the adapter change") from exc
    after = bluetooth_snapshot()
    if after["powered"] != enabled:
        raise SettingsError("Bluetooth power state could not be verified")
    return after


def set_bluetooth_connection(address: str, connected: bool, *, expected: bool) -> dict[str, Any]:
    if type(connected) is not bool or type(expected) is not bool:
        raise SettingsError("Bluetooth connection selection must be explicit")
    before = bluetooth_snapshot()
    device = next((device for device in before["devices"] if device["address"] == address), None)
    if device is None or device["connected"] != expected:
        raise SettingsError("Bluetooth device changed; refresh before applying")
    if connected and not device["paired"]:
        raise SettingsError("Pair the device in a Bluetooth manager first")
    if connected != expected:
        from macrice import bluetooth_dbus

        try:
            bluetooth_dbus.set_connection(address, connected)
        except Exception as exc:
            raise SettingsError("BlueZ denied the device operation") from exc
    after = bluetooth_snapshot()
    actual = next((item for item in after["devices"] if item["address"] == address), None)
    if actual is None or actual["connected"] != connected:
        raise SettingsError("Bluetooth connection change could not be verified")
    return after


def power_action(action: str, *, nested: bool = False) -> None:
    """User-confirmed logind suspend or screen lock. Never allow nested suspend."""
    if action not in ("lock", "suspend"):
        raise SettingsError("Unsupported power action")
    if action == "suspend" and (nested or os.environ.get("RICEBOWL_DE_NESTED") == "1"):
        raise SettingsError("Suspend is disabled in isolated nested previews")
    program, args = (("swaylock", ["-f"]) if action == "lock"
                     else ("loginctl", ["suspend"]))
    if not shutil.which(program):
        raise SettingsError(f"{program} is not installed")
    try:
        if action == "lock":
            subprocess.Popen([program, *args], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True)
        else:
            result = subprocess.run([program, *args], stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=8, check=False)
            if result.returncode:
                raise SettingsError("logind denied suspend; authorization may be required")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SettingsError("Power service could not complete the request") from exc


def power_snapshot() -> dict[str, Any]:
    """Read existing power-profile and battery services without changing state."""
    from macrice import hardware_status

    current, supported = hardware_status.read_power_profiles()
    battery = hardware_status.read_battery()
    return {"current": current, "supported": supported,
            "battery": None if battery is None else {
                "percent": battery.percent, "charging": battery.charging,
                "label": battery.label}}


def set_power_profile(name: str, *, expected: str) -> str:
    """Reject stale or unsupported selections and verify the service's result."""
    from macrice import hardware_status

    if type(name) is not str or type(expected) is not str:
        raise SettingsError("Select a supported power profile")
    current, supported = hardware_status.read_power_profiles()
    if current != expected or current not in supported:
        raise SettingsError("Power profile changed; refresh before applying")
    if name not in supported:
        raise SettingsError("Power profile is not supported by this device")
    if name == current:
        return name
    try:
        hardware_status.set_power_profile(name)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SettingsError("Power profile change was denied or could not be verified") from exc
    actual, _ = hardware_status.read_power_profiles()
    if actual != name:
        raise SettingsError("Power profile change could not be verified")
    return name
