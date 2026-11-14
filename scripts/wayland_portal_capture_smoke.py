#!/usr/bin/env python3
"""Exercise screenshot and ScreenCast portal requests in disposable headless CI.

This is deliberately not a general-purpose capture tool. It refuses to run
outside the private labwc/PipeWire/D-Bus test session prepared by the smoke
wrapper. A returned ScreenCast node and remote FD do not prove frame delivery.
"""
from __future__ import annotations

import os
import re
import subprocess
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
    """Non-successful xdg-desktop-portal Request.Response with method context."""

    def __init__(self, method: str, code: int):
        self.method = method
        self.code = code
        super().__init__(f"{method} request denied/failed: response={code}")


def strict_ci_mode(env: dict[str, str]) -> bool:
    flag = env.get("RICEBOWL_PORTAL_STRICT_CI", "0")
    if flag not in ("0", "1"):
        raise RuntimeError("RICEBOWL_PORTAL_STRICT_CI must be 0 or 1")
    if flag == "1" and env.get("WLR_RENDERER") != "gles2":
        raise RuntimeError("Strict ScreenCast requires the GLES2 renderer")
    return flag == "1"


def stream_nodes(streams: object) -> tuple[int, ...]:
    """Only well-formed, unique, positive PipeWire node IDs count as Start."""
    if not isinstance(streams, (tuple, list)) or not 1 <= len(streams) <= 16:
        raise RuntimeError("ScreenCast Start missing bounded stream nodes")
    nodes = []
    for stream in streams:
        if (not isinstance(stream, (list, tuple)) or len(stream) != 2
                or type(stream[0]) is not int or not 0 < stream[0] <= 0xffffffff
                or not isinstance(stream[1], dict)):
            raise RuntimeError("ScreenCast Start returned invalid stream shape")
        nodes.append(stream[0])
    if len(set(nodes)) != len(nodes):
        raise RuntimeError("ScreenCast Start returned duplicate node IDs")
    return tuple(nodes)


def classify_failure(exc: Exception) -> str:
    """Stable machine-readable failure families; never equate reply to frames."""
    if isinstance(exc, PortalRejected):
        if exc.code == 1:
            return "request_cancelled"
        if exc.method == "Start":
            return "session_start_failed"
        return "request_denied_or_failed"
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "request_timeout"
    message = str(exc).lower()
    if "permission" in message or "accessdenied" in message or "notallowed" in message:
        return "permission_denied"
    if "render" in message or "drm" in message or "egl" in message:
        return "renderer_unavailable"
    if "fd" in message or "file descriptor" in message:
        return "fd_missing_or_invalid"
    if "pipewire" in message or "gst" in message or "stream" in message or "frame" in message:
        return "pipewire_or_stream_failed"
    if "serviceunknown" in message or "dbus" in message or "d-bus" in message:
        return "portal_unavailable"
    if "session" in message:
        return "session_failed"
    return "protocol_or_runtime_error"


def unsupported_pixman_start(response: PortalRejected, env: dict[str, str]) -> bool:
    """Only the isolated pixman CI lane may report an untested ScreenCast FD."""
    return (not strict_ci_mode(env) and response.code == 2
            and env.get("RICEBOWL_PORTAL_CAPTURE_CI") == "1"
            and env.get("WLR_BACKENDS") == "headless"
            and env.get("WLR_RENDERER") == "pixman")


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
    if runtime != source.absolute():
        raise RuntimeError("Private portal runtime must not traverse symlinks")
    runtime_stat = runtime.stat()
    if (not stat.S_ISDIR(runtime_stat.st_mode)
            or runtime_stat.st_uid != os.geteuid()
            or stat.S_IMODE(runtime_stat.st_mode) != 0o700):
        raise RuntimeError("Private portal runtime must be owner-private mode 0700")
    marker = runtime / ".ricebowl-portal-ci"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("Missing private portal smoke marker")
    marker_stat = marker.stat()
    if (not stat.S_ISREG(marker_stat.st_mode)
            or marker_stat.st_uid != os.geteuid() or marker_stat.st_nlink != 1):
        raise RuntimeError("Private portal marker must be an owner-controlled file")
    if env.get("PIPEWIRE_RUNTIME_DIR") != str(runtime):
        raise RuntimeError("PipeWire must use the private runtime")
    bus = env.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not bus.startswith("unix:path="):
        raise RuntimeError("Expected a private Unix-path D-Bus session")
    bus_marker = runtime / ".ricebowl-portal-dbus"
    if bus_marker.is_symlink() or not bus_marker.is_file():
        raise RuntimeError("Missing private D-Bus identity marker")
    bus_stat = bus_marker.stat()
    if (bus_stat.st_uid != os.geteuid()
            or stat.S_IMODE(bus_stat.st_mode) != 0o600
            or bus_stat.st_nlink != 1
            or bus_marker.read_text(encoding="utf-8").rstrip("\n") != bus):
        raise RuntimeError("Private D-Bus identity does not match runtime")
    display = env.get("WAYLAND_DISPLAY", "")
    if not display or "/" in display or display in (".", ".."):
        raise RuntimeError("Expected a relative compositor Wayland socket name")
    display_path = runtime / display
    if display_path.is_symlink() or not display_path.is_socket():
        raise RuntimeError("Headless compositor socket is absent or symlinked")
    pipewire_path = runtime / "pipewire-0"
    if pipewire_path.is_symlink() or not pipewire_path.is_socket():
        raise RuntimeError("Private PipeWire socket is absent or symlinked")
    strict_ci_mode(env)
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
    """Require a complete, CRC-valid PNG with a bounded DEFLATE image."""
    import zlib

    fd = os.open(screenshot_file(uri), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Screenshot portal URI is not a regular file")
        if not 57 <= metadata.st_size <= 64 * 1024 * 1024:
            raise ValueError("Screenshot portal PNG outside bounded size")
        with os.fdopen(os.dup(fd), "rb") as image:
            raw = image.read(metadata.st_size + 1)
    finally:
        os.close(fd)
    if len(raw) != metadata.st_size or not raw.startswith(PNG_SIGNATURE):
        raise ValueError("Screenshot portal returned an invalid PNG")
    offset = len(PNG_SIGNATURE)
    count = 0
    seen_idat = seen_iend = False
    width = height = 0
    decoder = zlib.decompressobj()
    decoded = 0
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("Screenshot PNG truncated chunk")
        length = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        offset += 8
        if length > 64 * 1024 * 1024 or offset + length + 4 > len(raw):
            raise ValueError("Screenshot PNG oversized or truncated chunk")
        data = raw[offset:offset + length]
        crc = struct.unpack_from(">I", raw, offset + length)[0]
        if zlib.crc32(kind + data) & 0xffffffff != crc:
            raise ValueError("Screenshot PNG CRC mismatch")
        offset += length + 4
        count += 1
        if count == 1:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Screenshot PNG missing IHDR")
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data))
            depths = {0: (1, 2, 4, 8, 16), 2: (8, 16),
                      3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not 0 < width <= 32768 or not 0 < height <= 32768
                    or width * height > 32 * 1024 * 1024
                    or depth not in depths.get(color, ())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise ValueError("Screenshot portal returned invalid PNG dimensions/format")
        elif kind == b"IHDR":
            raise ValueError("Screenshot PNG duplicate IHDR")
        elif kind == b"IDAT":
            seen_idat = True
            decoded += len(decoder.decompress(
                data, 128 * 1024 * 1024 - decoded + 1))
            if decoded > 128 * 1024 * 1024:
                raise ValueError("Screenshot PNG decompression exceeds limit")
        elif kind == b"IEND":
            if length or not seen_idat or offset != len(raw):
                raise ValueError("Screenshot PNG invalid IEND")
            seen_iend = True
            break
    if not (seen_idat and seen_iend and decoder.eof and decoded > 0):
        raise ValueError("Screenshot PNG has no complete compressed image")
    return width, height, len(raw)



def request(connection, interface: str, method: str, signature: str,
            values: tuple, *, timeout_seconds: int = 12, extra_options=None):
    """Subscribe before the call; close abandoned portal requests fail-closed."""
    from gi.repository import Gio, GLib

    token = "rb_" + secrets.token_hex(12)
    sender = connection.get_unique_name().lstrip(":").replace(".", "_")
    expected = f"{DESKTOP_PATH}/request/{sender}/{token}"
    options = {"handle_token": GLib.Variant("s", token)}
    options.update(extra_options or {})
    session_token = None
    if method == "CreateSession":
        session_token = "rb_session_" + secrets.token_hex(12)
        options["session_handle_token"] = GLib.Variant("s", session_token)
    parameters = GLib.Variant(signature, (*values, options))
    outcome = []
    loop = GLib.MainLoop()
    completed = False

    def received(_bus, _sender, _path, _interface, _signal, parameters):
        if not outcome:
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
        if session_token is not None:
            expected_session = f"{DESKTOP_PATH}/session/{sender}/{session_token}"
            if results.get("session_handle") != expected_session:
                raise RuntimeError("CreateSession returned a mismatched session handle")
        completed = True
        return results
    finally:
        if not completed:
            # The remote request may still be running after a timeout or
            # exception. Close it before leaving the private session.
            try:
                connection.call_sync(
                    DESKTOP, expected, REQUEST, "Close",
                    None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except Exception:
                pass  # The request may already have vanished.
        connection.signal_unsubscribe(subscription)



def verify_pipewire_remote(connection, session: str) -> int:
    """Return a caller-owned validated socket FD from the portal's FD list."""
    from gi.repository import Gio, GLib

    reply, descriptors = connection.call_with_unix_fd_list_sync(
        DESKTOP, DESKTOP_PATH, SCREENCAST, "OpenPipeWireRemote",
        GLib.Variant("(oa{sv})", (session, {})),
        GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE,
        12000, None, None)
    if descriptors is None:
        raise RuntimeError("OpenPipeWireRemote returned no Unix FD list")
    handle = reply.unpack()
    if (not isinstance(handle, tuple) or len(handle) != 1
            or type(handle[0]) is not int):
        raise RuntimeError("OpenPipeWireRemote returned an invalid FD handle")
    fd = descriptors.get(handle[0])
    if type(fd) is not int or fd < 0:
        raise RuntimeError("OpenPipeWireRemote returned an invalid FD")
    try:
        if not stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise RuntimeError("OpenPipeWireRemote FD is not a socket")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return fd


def verify_delivered_frame(fd: int, node: int, *, timeout: int = 18) -> str:
    """Accept a successful, node-matched nonempty Gst.Sample receipt only."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         "--frame-probe", str(fd), str(node)],
        pass_fds=(fd,), capture_output=True, text=True,
        timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError("PipeWire frame probe failed: " +
                           (result.stderr or result.stdout).strip()[:700])
    receipts = [line for line in result.stdout.splitlines()
                if line.startswith("PORTAL_FRAME_OK:")]
    if len(receipts) != 1:
        raise RuntimeError("PipeWire frame probe returned no unique frame receipt")
    match = re.fullmatch(
        r"PORTAL_FRAME_OK: node=(\d+) bytes=(\d+) caps=(video/x-raw(?:[,(].*)?)",
        receipts[0])
    if not match or int(match[1]) != node or int(match[2]) <= 0:
        raise RuntimeError("PipeWire frame probe returned an invalid frame receipt")
    return receipts[0]



def frame_probe(fd: int, node: int) -> None:
    """Child-only GStreamer receiver: a D-Bus FD without a buffer fails."""
    require_private_headless_session(dict(os.environ))
    if fd < 3 or node <= 0 or node > 0xffffffff:
        raise RuntimeError("Invalid PipeWire node or inherited FD")
    if not stat.S_ISSOCK(os.fstat(fd).st_mode):
        raise RuntimeError("Inherited PipeWire remote FD is not a socket")
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    pipeline = Gst.parse_launch(
        "pipewiresrc name=remote-src ! appsink name=frame-sink "
        "sync=false max-buffers=1 drop=true")
    src = pipeline.get_by_name("remote-src")
    sink = pipeline.get_by_name("frame-sink")
    if src is None or sink is None:
        raise RuntimeError("GStreamer PipeWire source/appsink plugin unavailable")
    src.set_property("fd", fd)
    src.set_property("path", str(node))
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("PipeWire receiver failed to start")
        sample = sink.emit("try-pull-sample", 12 * Gst.SECOND)
        if sample is None:
            message = pipeline.get_bus().timed_pop_filtered(0, Gst.MessageType.ERROR)
            detail = message.parse_error()[0].message if message else "no frames within deadline"
            raise TimeoutError("PipeWire stream delivered no sample: " + detail)
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        if (buffer is None or buffer.get_size() <= 0 or caps is None
                or not caps.to_string().startswith("video/x-raw")):
            raise RuntimeError("PipeWire stream did not deliver a nonempty video frame")
        print(f"PORTAL_FRAME_OK: node={node} bytes={buffer.get_size()} "
              f"caps={caps.to_string()}", flush=True)
    finally:
        pipeline.set_state(Gst.State.NULL)



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
        remote_fd = verify_pipewire_remote(connection, session)
        try:
            print(f"PORTAL_FD_OK: {len(nodes)} ScreenCast node(s), socket FD={remote_fd}",
                  flush=True)
            if strict:
                # Do not count D-Bus Start/FD as delivered video.
                print(verify_delivered_frame(remote_fd, nodes[0]), flush=True)
                print("PORTAL_STRICT_OK: GLES2 Stream, remote FD and video sample verified",
                      flush=True)
        finally:
            os.close(remote_fd)
    except Exception as exc:
        original_failure = exc
        raise
    finally:
        try:
            connection.call_sync(DESKTOP, session, SESSION, "Close",
                                 None, None, Gio.DBusCallFlags.NONE, 5000, None)
        except Exception as cleanup_error:
            if original_failure is None and not pixman_rejected:
                raise
            print(f"PORTAL_CLEANUP_WARN: {cleanup_error}", file=sys.stderr)
    print("PORTAL_LIMIT: No Flatpak consent, frames, physical GPU or multi-output sign-off.")


if __name__ == "__main__":
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "--frame-probe":
            frame_probe(int(sys.argv[2]), int(sys.argv[3]))
        elif len(sys.argv) == 1:
            run()
        else:
            raise RuntimeError("Unexpected portal capture arguments")
    except Exception as exc:
        print(f"PORTAL_CAPTURE_FAIL: category={classify_failure(exc)} "
              f"detail={exc}", file=sys.stderr)
        raise SystemExit(1) from None
