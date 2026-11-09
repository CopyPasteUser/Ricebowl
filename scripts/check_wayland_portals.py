#!/usr/bin/python3
"""Live public XDG portal acceptance, only inside smoke_wayland_portals.sh.

Does not bypass consent in a real session. The CI compositor owns a single
synthetic output and selects it without a prompt via temporary xdpw config.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from gi.repository import Gio, GLib


DEST = "org.freedesktop.portal.Desktop"
OBJECT = "/org/freedesktop/portal/desktop"
CAST = "org.freedesktop.portal.ScreenCast"
SCREENSHOT = "org.freedesktop.portal.Screenshot"
REQUEST = "org.freedesktop.portal.Request"
FILE_CHOOSER = "org.freedesktop.portal.FileChooser"


def main() -> None:
    if os.environ.get("WLR_BACKENDS") != "headless" or not os.environ.get("RICEBOWL_DE_NESTED"):
        raise RuntimeError("Refusing to request a capture outside disposable CI")
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    seen: dict[str, tuple[int, dict]] = {}

    def on_response(_connection, _sender, path, _interface, _signal, params, _data):
        code, payload = params.unpack()
        seen[path] = (code, payload)

    subscription = connection.signal_subscribe(
        DEST, REQUEST, "Response", None, None, Gio.DBusSignalFlags.NONE,
        on_response, None,
    )

    def request(interface: str, method: str, signature: str, arguments: tuple) -> dict:
        result = connection.call_sync(
            DEST, OBJECT, interface, method, GLib.Variant(signature, arguments),
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 8_000, None,
        )
        handle = result.unpack()[0]
        deadline = time.monotonic() + 12
        while handle not in seen and time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if handle not in seen:
                time.sleep(0.04)
        if handle not in seen:
            raise RuntimeError(f"Portal {interface}.{method} did not return a response")
        status, payload = seen.pop(handle)
        if status:
            raise RuntimeError(f"Portal {interface}.{method} denied/failed: response={status}")
        return payload

    try:
        chooser_version = connection.call_sync(
            DEST, OBJECT, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (FILE_CHOOSER, "version")),
            GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 8_000, None,
        ).unpack()[0]
        if chooser_version < 1:
            raise RuntimeError("GTK-backed file chooser portal is unavailable")
        print("GTK file chooser portal is registered", flush=True)

        sources = connection.call_sync(
            DEST, OBJECT, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (CAST, "AvailableSourceTypes")),
            GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 8_000, None,
        ).unpack()[0]
        if not (sources & 1):
            raise RuntimeError(f"ScreenCast portal does not support monitor sources: {sources}")
        print("ScreenCast portal advertises real monitor sources", flush=True)

        screenshot = request(SCREENSHOT, "Screenshot", "(sa{sv})", (
            "", {"interactive": GLib.Variant("b", False)},
        ))
        uri = screenshot.get("uri", "")
        location = urlsplit(uri)
        if location.scheme != "file" or location.netloc not in ("", "localhost"):
            raise RuntimeError("Screenshot portal returned an unexpected URI")
        picture = Path(unquote(location.path))
        with picture.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("Portal screenshot is not a real PNG")
        print("Screenshot portal returned a real headless PNG", flush=True)

        session = request(CAST, "CreateSession", "(a{sv},)", ({
            "session_handle_token": GLib.Variant("s", "ricebowl_smoke_session"),
        },)).get("session_handle")
        if not isinstance(session, str) or not session.startswith("/org/freedesktop/portal/desktop/session/"):
            raise RuntimeError("ScreenCast did not return a session handle")
        request(CAST, "SelectSources", "(oa{sv})", (session, {
            "types": GLib.Variant("u", 1),
            "multiple": GLib.Variant("b", False),
        }))
        started = request(CAST, "Start", "(osa{sv})", (session, "", {}))
        streams = started.get("streams", [])
        if not streams or not any(isinstance(item[0], int) and item[0] > 0 for item in streams):
            raise RuntimeError("ScreenCast returned no PipeWire streams")
        reply, fds = connection.call_with_unix_fd_list_sync(
            DEST, OBJECT, CAST, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (session, {})),
            GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, 8_000, None, None,
        )
        descriptor = fds.get(reply.unpack()[0])
        try:
            os.fstat(descriptor)
        finally:
            os.close(descriptor)
        print("ScreenCast returned a live PipeWire stream and remote fd", flush=True)
        connection.call_sync(
            DEST, session, "org.freedesktop.portal.Session", "Close", None,
            None, Gio.DBusCallFlags.NONE, 5_000, None,
        )
    finally:
        connection.signal_unsubscribe(subscription)


if __name__ == "__main__":
    main()
