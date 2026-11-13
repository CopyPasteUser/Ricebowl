#!/usr/bin/env python3
"""Exercise screenshot and ScreenCast portal requests in disposable headless CI.

This is deliberately not a general-purpose capture tool. It refuses to run
outside the private labwc/PipeWire/D-Bus test session prepared by the smoke
wrapper. A returned ScreenCast node and remote FD do not prove frame delivery.
"""
from __future__ import annotations

import os
import secrets
import stat
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

DESKTOP = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
REQUEST = "org.freedesktop.portal.Request"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
SCREENSHOT = "org.freedesktop.portal.Screenshot"
SESSION = "org.freedesktop.portal.Session"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PortalRejected(RuntimeError):
    def __init__(self, method: str, code: int):
        super().__init__(f"{method} request denied/failed: response={code}")
        self.code = code


def strict_ci_mode(env: dict[str, str]) -> bool:
    """Reject ambiguous strict flags and accidental pixman fallback in strict CI."""
    flag = env.get("RICEBOWL_PORTAL_STRICT_CI", "0")
    if flag not in ("0", "1"):
        raise RuntimeError("RICEBOWL_PORTAL_STRICT_CI must be 0 or 1")
    if flag == "1" and env.get("WLR_RENDERER") != "gles2":
        raise RuntimeError("Strict ScreenCast CI requires a GLES2 compositor")
    return flag == "1"


def unsupported_pixman_start(response: PortalRejected, env: dict[str, str]) -> bool:
    """Only the non-strict, isolated pixman lane may report an untested FD."""
    return (not strict_ci_mode(env) and response.code == 2
            and env.get("RICEBOWL_PORTAL_CAPTURE_CI") == "1"
            and env.get("WLR_BACKENDS") == "headless"
            and env.get("WLR_RENDERER") == "pixman")


def stream_nodes(streams: object) -> tuple[int, ...]:
    """Accept only nonempty, distinct PipeWire nodes from a successful Start.

    Each portal stream has D-Bus type (ua{sv}); bool is not a valid node ID.
    A valid node is negotiation evidence, never proof of delivered frames.
    """
    if not isinstance(streams, (tuple, list)) or not 1 <= len(streams) <= 16:
        raise RuntimeError("ScreenCast Start did not return bounded PipeWire streams")
    nodes = []
    for stream in streams:
        if (not isinstance(stream, (tuple, list)) or len(stream) != 2
                or type(stream[0]) is not int or not 0 < stream[0] <= 0xffffffff
                or not isinstance(stream[1], dict)):
            raise RuntimeError("ScreenCast Start returned malformed PipeWire stream data")
        nodes.append(stream[0])
    if len(set(nodes)) != len(nodes):
        raise RuntimeError("ScreenCast Start returned duplicate PipeWire stream nodes")
    return tuple(nodes)


def require_private_headless_session(env: dict[str, str]) -> Path:
    """Refuse to capture from an installed or interactive Wayland session."""
    required = {
        "RICEBOWL_PORTAL_CAPTURE_CI": "1",
        "RICEBOWL_DE_NESTED": "1",
        "WLR_BACKENDS": "headless",
        "XDG_SESSION_TYPE": "wayland",
    }
    for key, value in required.items():
        if env.get(key) != value:
            raise RuntimeError(f"Capture smoke requires {key}={value}")
    runtime_text = env.get("XDG_RUNTIME_DIR", "")
    if not runtime_text or not Path(runtime_text).is_absolute():
        raise RuntimeError("Missing absolute isolated XDG_RUNTIME_DIR")
    source = Path(runtime_text)
    if source.is_symlink():
        raise RuntimeError("Private portal runtime must not be a symlink")
    runtime = source.resolve(strict=True)
    details = runtime.stat()
    if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o700):
        raise RuntimeError("Private portal runtime must be owner-private mode 0700")
    marker = runtime / ".ricebowl-portal-ci"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_uid != os.geteuid():
        raise RuntimeError("Missing private owner-controlled portal smoke marker")
    if env.get("PIPEWIRE_RUNTIME_DIR") != str(runtime):
        raise RuntimeError("PipeWire must use the private runtime")
    if not env.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:"):
        raise RuntimeError("Expected an isolated Unix D-Bus session")
    display = env.get("WAYLAND_DISPLAY", "")
    if not display or "/" in display or display in (".", ".."):
        raise RuntimeError("Expected a relative compositor Wayland socket name")
    display_path = runtime / display
    if not display_path.is_socket():
        raise RuntimeError("Headless compositor socket is absent")
    return runtime


def screenshot_file(uri: str) -> Path:
    parsed = urlsplit(uri)
    if (parsed.scheme != "file" or parsed.netloc not in ("", "localhost")
            or parsed.query or parsed.fragment or not parsed.path):
        raise ValueError("Screenshot portal returned a non-local file URI")
    path = Path(unquote(parsed.path))
    if not path.is_absolute():
        raise ValueError("Screenshot portal returned a relative path")
    return path


def verify_png(uri: str) -> tuple[int, int, int]:
    """Inspect a bounded PNG header, without following symlinks or loading pixels."""
    path = screenshot_file(uri)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("Screenshot portal URI is not a regular file")
        size = details.st_size
        header = os.read(fd, 24)
    finally:
        os.close(fd)
    if (size < 33 or header[:8] != PNG_SIGNATURE
            or header[8:12] != b"\x00\x00\x00\x0d"
            or header[12:16] != b"IHDR" or len(header) != 24):
        raise ValueError("Screenshot portal returned an invalid PNG")
    width, height = struct.unpack(">II", header[16:24])
    if not (0 < width <= 32768 and 0 < height <= 32768):
        raise ValueError("Screenshot portal returned invalid dimensions")
    return width, height, size


def request(connection, interface: str, method: str, signature: str,
            values: tuple, *, timeout_seconds: int = 12, extra_options=None):
    """Subscribe to the predictable Request path *before* invoking a method."""
    from gi.repository import Gio, GLib

    token = "rb_" + secrets.token_hex(12)
    sender = connection.get_unique_name().lstrip(":").replace(".", "_")
    expected = f"{DESKTOP_PATH}/request/{sender}/{token}"
    options = {"handle_token": GLib.Variant("s", token)}
    options.update(extra_options or {})
    if method == "CreateSession":
        options["session_handle_token"] = GLib.Variant(
            "s", "rb_session_" + secrets.token_hex(12))
    parameters = GLib.Variant(signature, (*values, options))
    outcome = []
    loop = GLib.MainLoop()

    def received(_bus, _sender, _path, _interface, _signal, parameters):
        outcome.append(parameters.unpack())
        if loop.is_running():
            loop.quit()

    subscription = connection.signal_subscribe(
        DESKTOP, REQUEST, "Response", expected, None,
        Gio.DBusSignalFlags.NONE, received)
    try:
        reply = connection.call_sync(
            DESKTOP, DESKTOP_PATH, interface, method, parameters,
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE,
            timeout_seconds * 1000, None)
        returned_handle = reply.unpack()[0]
        if returned_handle != expected:
            raise RuntimeError(f"Unexpected portal request handle: {returned_handle}")
        if not outcome:
            expired = []

            def timed_out():
                expired.append(True)
                if loop.is_running():
                    loop.quit()
                return GLib.SOURCE_REMOVE

            timer = GLib.timeout_add_seconds(timeout_seconds, timed_out)
            try:
                loop.run()
            finally:
                if not expired:
                    GLib.source_remove(timer)
        if not outcome:
            raise TimeoutError(f"{method} request did not respond")
        response, results = outcome[0]
        if response != 0:
            raise PortalRejected(method, response)
        return results
    finally:
        connection.signal_unsubscribe(subscription)


def verify_pipewire_remote(connection, session: str) -> None:
    from gi.repository import Gio, GLib

    reply, descriptors = connection.call_with_unix_fd_list_sync(
        DESKTOP, DESKTOP_PATH, SCREENCAST, "OpenPipeWireRemote",
        GLib.Variant("(oa{sv})", (session, {})),
        GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE,
        12000, None, None)
    if descriptors is None:
        raise RuntimeError("OpenPipeWireRemote did not return a Unix FD list")
    fd = descriptors.get(reply.unpack()[0])
    try:
        if not stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise RuntimeError("PipeWire remote FD is not a socket")
    finally:
        os.close(fd)


def run() -> None:
    env = dict(os.environ)
    require_private_headless_session(env)
    strict = strict_ci_mode(env)
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    screenshot = request(connection, SCREENSHOT, "Screenshot", "(sa{sv})", ("",))
    uri = screenshot.get("uri")
    if not isinstance(uri, str):
        raise RuntimeError("Screenshot response did not contain a local URI")
    width, height, size = verify_png(uri)
    print(f"PORTAL_CAPTURE_OK: screenshot PNG {width}x{height}, {size} bytes", flush=True)

    created = request(connection, SCREENCAST, "CreateSession", "(a{sv})", ())
    session = created.get("session_handle")
    if not isinstance(session, str) or not session.startswith(DESKTOP_PATH + "/session/"):
        raise RuntimeError("CreateSession did not return a valid session handle")
    print("PORTAL_CAPTURE_STAGE: CreateSession responded", flush=True)
    original_failure = None
    pixman_rejected = False
    try:
        request(connection, SCREENCAST, "SelectSources", "(oa{sv})", (session,),
                extra_options={"types": GLib.Variant("u", 1),
                               "multiple": GLib.Variant("b", False)})
        print("PORTAL_CAPTURE_STAGE: SelectSources responded", flush=True)
        try:
            started = request(connection, SCREENCAST, "Start", "(osa{sv})", (session, ""))
        except PortalRejected as rejected:
            if not unsupported_pixman_start(rejected, env):
                raise
            pixman_rejected = True
            print("PORTAL_CAPTURE_LIMIT: ScreenCast Start returned response=2 on "
                  "headless pixman; no PipeWire streams/frames/FD verified. "
                  "Real GPU acceptance still required.", flush=True)
            return
        print("PORTAL_CAPTURE_STAGE: Start responded", flush=True)
        nodes = stream_nodes(started.get("streams"))
        verify_pipewire_remote(connection, session)
        print(f"PORTAL_CAPTURE_OK: screencast {len(nodes)} node(s), PipeWire FD", flush=True)
        if strict:
            print("PORTAL_STRICT_OK: GLES2 Start nodes and PipeWire remote FD verified; "
                  "frame delivery and user consent remain untested.", flush=True)
    except Exception as exc:
        original_failure = exc
        raise
    finally:
        try:
            connection.call_sync(DESKTOP, session, SESSION, "Close",
                                 None, None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as cleanup_error:
            if original_failure is None and not pixman_rejected:
                raise
            print(f"PORTAL_CLEANUP_WARN: {cleanup_error}", file=sys.stderr)
    print("PORTAL_LIMIT: No Flatpak consent, frames, physical GPU or multi-output sign-off.")


if __name__ == "__main__":
    try:
        run()
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"PORTAL_CAPTURE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
