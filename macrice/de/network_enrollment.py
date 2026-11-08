"""Bounded native RiceSpice NetworkManager profile enrollment.

Only password-based PEAP/TTLS with verified server identity is authored here.
Passwords travel through nmcli's ``passwd-file /dev/stdin`` channel, never argv,
disk, diagnostics, or the persistent connection profile. Other EAP/VPN methods
remain available through NetworkManager's established import/editor tooling.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import uuid as uuidlib
from pathlib import Path

from . import settings_backend as backend


_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_SAFE_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,160}\Z")
_UUID = backend._CONNECTION_UUID
_IMPORT_TYPES = {".ovpn": "openvpn", ".conf": "wireguard"}


def _text(value: str, title: str, *, limit: int = 128) -> str:
    if (type(value) is not str or len(value) > limit or not _SAFE_TEXT.fullmatch(value)
            or value != value.strip()):
        raise backend.SettingsError(f"Enter a valid {title} without control characters")
    return value


def _domain(value: str) -> str:
    domain = _text(value, "authentication-server domain", limit=253).lower()
    if ("." not in domain or len(domain.encode("ascii", "ignore")) != len(domain)
            or any(not _DOMAIN_LABEL.fullmatch(part) for part in domain.split("."))):
        raise backend.SettingsError("Enter the domain provided by your network administrator")
    return domain


def _certificate(value: str) -> str | None:
    if value == "":
        return None
    if type(value) is not str or "\x00" in value or len(value) > 2048:
        raise backend.SettingsError("Choose a readable CA certificate file")
    path = Path(value)
    if not path.is_absolute():
        raise backend.SettingsError("Use an absolute path for the CA certificate")
    try:
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024
                or not os.access(path, os.R_OK)):
            raise OSError("not a readable regular certificate file")
    except OSError as exc:
        raise backend.SettingsError("CA certificate is missing or not readable") from exc
    return str(path)


def _run(*args: str, secret: str | None = None, wait: int = 12) -> str:
    """Execute fixed, non-shell nmcli argv; no secrets in argv or stderr."""
    binary = shutil.which("nmcli")
    if binary is None:
        raise backend.SettingsError("NetworkManager nmcli is not installed")
    try:
        stdin = {} if secret is not None else {"stdin": subprocess.DEVNULL}
        result = subprocess.run(
            [binary, "--wait", str(wait), *args],
            input=secret, text=True, capture_output=True, check=False,
            timeout=wait + 5, env={**os.environ, "LC_ALL": "C"}, **stdin,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise backend.SettingsError("NetworkManager request timed out; refresh saved profiles") from exc
    if result.returncode or len(result.stdout) > 32 * 1024:
        raise backend.SettingsError("NetworkManager rejected the profile operation; "
                                    "check permissions, credentials or server settings")
    return result.stdout.strip()


def _profile_setting(uuid: str, field: str) -> str:
    return _run("-g", field, "con", "show", "uuid", uuid)


def create_enterprise_wifi(*, ssid: str, identity: str, domain: str,
                           eap: str, inner: str, ca_certificate: str = "") -> str:
    """Create a non-autoconnecting, password-not-saved secure EAP profile.

    This does not join the network; an explicit Connect action must follow.
    """
    name = _text(ssid, "Wi-Fi name", limit=32)
    if len(name.encode("utf-8")) > 32:
        raise backend.SettingsError("Wi-Fi names are limited to 32 UTF-8 bytes")
    username = _text(identity, "network username")
    host = _domain(domain)
    if type(eap) is not str or type(inner) is not str or (
        (eap, inner) not in {("peap", "mschapv2"), ("ttls", "pap"), ("ttls", "mschapv2")}
    ):
        raise backend.SettingsError("Unsupported enterprise authentication combination")
    cert = _certificate(ca_certificate)
    identifier = str(uuidlib.uuid4())
    before = backend.connection_profiles()
    args = ["con", "add", "type", "wifi", "ifname", "*",
            "con-name", f"RiceSpice · {name}", "ssid", name,
            "connection.uuid", identifier, "connection.autoconnect", "no",
            "802-11-wireless-security.key-mgmt", "wpa-eap",
            "802-1x.eap", eap, "802-1x.phase2-auth", inner,
            "802-1x.identity", username, "802-1x.domain-suffix-match", host,
            "802-1x.password-flags", "2"]
    if cert is None:
        args.extend(("802-1x.system-ca-certs", "yes"))
    else:
        args.extend(("802-1x.ca-cert", cert))
    _run(*args)
    after = backend.connection_profiles()
    new = next((item for item in after if item["uuid"] == identifier), None)
    if (new is None or new["kind"] not in ("802-11-wireless", "wifi")
            or new["active"] or identifier in {item["uuid"] for item in before}):
        raise backend.SettingsError("Enterprise profile creation could not be verified; "
                                    "refresh before retrying")
    return identifier


def connect_enterprise_wifi(uuid: str, password: str, *, expected_active: bool = False) -> bool:
    """Activate an EAP profile with an ephemeral stdin password, no secret persistence."""
    if type(uuid) is not str or not _UUID.fullmatch(uuid):
        raise backend.SettingsError("Choose a saved enterprise Wi-Fi profile")
    if (type(password) is not str or not 1 <= len(password) <= 512
            or len(password.splitlines()) != 1 or any(ord(char) < 32 for char in password)):
        raise backend.SettingsError("Enter a network password without line breaks")
    current = next((item for item in backend.connection_profiles() if item["uuid"] == uuid), None)
    if (current is None or current["kind"] not in ("802-11-wireless", "wifi")
            or current["active"] != expected_active or expected_active):
        raise backend.SettingsError("Enterprise Wi-Fi profile changed; refresh first")
    enterprise_password_ready(uuid)
    _run("con", "up", "uuid", uuid, "passwd-file", "/dev/stdin",
         secret="802-1x.password:" + password + "\n", wait=45)
    after = next((item for item in backend.connection_profiles() if item["uuid"] == uuid), None)
    if after is None or not after["active"]:
        raise backend.SettingsError("Wi-Fi activation may have changed; refresh to verify")
    return True


def enterprise_password_ready(uuid: str) -> bool:
    """Only accept trusted PEAP/TTLS profiles before requesting a secret."""
    if type(uuid) is not str or not _UUID.fullmatch(uuid):
        raise backend.SettingsError("Choose a saved enterprise Wi-Fi profile")
    method = _profile_setting(uuid, "802-11-wireless-security.key-mgmt")
    if method != "wpa-eap":
        raise backend.SettingsError("This is not an enterprise Wi-Fi password profile")
    eap = _profile_setting(uuid, "802-1x.eap")
    if eap not in ("peap", "ttls"):
        raise backend.SettingsError("The selected profile does not use supported password EAP")
    domain = _profile_setting(uuid, "802-1x.domain-suffix-match")
    try:
        _domain(domain)
    except backend.SettingsError as exc:
        raise backend.SettingsError("This profile has no trusted EAP server domain") from exc
    system_ca = _profile_setting(uuid, "802-1x.system-ca-certs")
    cert = _profile_setting(uuid, "802-1x.ca-cert")
    if system_ca.lower() not in ("yes", "true", "1"):
        try:
            if _certificate(cert) is None:
                raise backend.SettingsError("Missing CA")
        except backend.SettingsError as exc:
            raise backend.SettingsError("This profile does not verify a CA certificate") from exc
    return True


def import_vpn_profile(path: str) -> str:
    """Import a local OpenVPN/WireGuard configuration without reading its keys."""
    if type(path) is not str or "\x00" in path or len(path) > 2048:
        raise backend.SettingsError("Choose an OpenVPN .ovpn or WireGuard .conf file")
    source = Path(path)
    kind = _IMPORT_TYPES.get(source.suffix.lower())
    if kind is None or not source.is_absolute():
        raise backend.SettingsError("Choose an absolute .ovpn or .conf configuration file")
    try:
        info = source.stat()
        if (not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 256 * 1024
                or not os.access(source, os.R_OK)):
            raise OSError("invalid VPN configuration file")
    except OSError as exc:
        raise backend.SettingsError("VPN configuration file is missing or unreadable") from exc
    before = {entry["uuid"] for entry in backend.connection_profiles()}
    _run("con", "import", "type", kind, "file", str(source))
    additions = [entry for entry in backend.connection_profiles()
                 if entry["uuid"] not in before and entry["kind"] in ("vpn", "wireguard")]
    if len(additions) != 1:
        raise backend.SettingsError("VPN import could not be verified; refresh saved profiles")
    identifier = additions[0]["uuid"]
    # Fail closed if NetworkManager did not honor the non-autoconnect request.
    _run("con", "modify", "uuid", identifier, "connection.autoconnect", "no")
    if _profile_setting(identifier, "connection.autoconnect").lower() not in ("no", "false", "0"):
        raise backend.SettingsError("VPN imported, but autoconnect could not be disabled; "
                                    "review the saved profile immediately")
    return identifier
