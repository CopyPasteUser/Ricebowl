"""Windows 98 Find > Computer: real mounted locations, not invented drives.

GIO owns mount discovery and URI launching. This window never mounts, unmounts,
enumerates remote folders or changes XFDesktop / file-manager ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import shutil
import subprocess
from urllib.parse import urlsplit


MAX_MOUNTS = 128
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputerLocation:
    name: str
    kind: str
    uri: str


def mounted_locations(monitor, *, home: Path | None = None) -> tuple[ComputerLocation, ...]:
    """List real GIO mounts, deduplicated and bounded for the Classic shell."""
    home = Path.home() if home is None else home
    result = [
        ComputerLocation("Home", "Local folder", home.resolve().as_uri()),
        ComputerLocation("File System", "Local filesystem", Path("/").as_uri()),
    ]
    seen = {item.uri for item in result}
    for mount in tuple(monitor.get_mounts())[:MAX_MOUNTS]:
        try:
            if mount.is_shadowed():
                continue
            uri = mount.get_root().get_uri()
            name = mount.get_name()
            if not isinstance(uri, str) or not urlsplit(uri).scheme or uri in seen:
                continue
            if not isinstance(name, str) or not name.strip():
                name = "Unnamed volume"
            kind = "Mounted volume" if urlsplit(uri).scheme == "file" else "Network location"
            result.append(ComputerLocation(name.strip()[:120], kind, uri))
            seen.add(uri)
        except Exception as exc:
            # A disappearing device must not take down Start or the browser.
            LOG.debug("Skipping unavailable GIO mount: %s", exc)
    return tuple(result)


def filter_locations(locations: tuple[ComputerLocation, ...],
                     query: str) -> tuple[ComputerLocation, ...]:
    needle = query.strip().casefold()
    return tuple(item for item in locations if not needle or
                 needle in item.name.casefold() or needle in item.kind.casefold())


def network_browsing_available(schemes) -> bool:
    """A network:/// entry requires a GVfs network backend, not a guessed host."""
    return "network" in (schemes or ())


def open_location(shell, uri: str, Gio, *, which=shutil.which,
                  spawn=subprocess.Popen) -> str:
    """Use RiceField's real Win98 shell for local folders if installed.

    The explicit Classic Explorer entry does not alter XDG MIME handlers or
    the user's default manager. Network URIs stay with GIO/the current handler.
    A failed spawn falls back to that same handler rather than losing the click.
    """
    path = None
    if urlsplit(uri).scheme == "file":
        try:
            path = Gio.File.new_for_uri(uri).get_path()
        except Exception as exc:
            LOG.warning("Could not resolve local Explorer location %s: %s", uri, exc)
    executable = which("ricefield") if path else None
    if executable:
        try:
            spawn([executable, "--theme", "win98", "--separate-window", path],
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True,
                  start_new_session=True)
        except OSError as exc:
            LOG.warning("RiceField launch failed, falling back to default handler: %s", exc)
        else:
            shell._hide_menu()
            return "ricefield"
    shell._open_uri(uri)
    return "default"


def show(shell, Gtk, Gio):
    """Open the one nonmodal Classic browser; safely re-resolve mounts on change."""
    shell._hide_menu()
    existing = getattr(shell, "_classic98_computer_dialog", None)
    if existing is not None:
        existing.present()
        return existing

    dialog = Gtk.Dialog(title="Find: Computer", transient_for=shell.bar,
                        flags=Gtk.DialogFlags.DESTROY_WITH_PARENT)
    dialog.set_default_size(570, 420)
    dialog.set_resizable(True)
    dialog.set_modal(False)
    dialog.get_style_context().add_class("classic98-computer-dialog")
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    open_button = dialog.add_button("Open", Gtk.ResponseType.OK)
    open_button.set_sensitive(False)
    dialog.set_default_response(Gtk.ResponseType.OK)

    body = dialog.get_content_area()
    body.set_spacing(8)
    body.set_border_width(12)
    heading = Gtk.Label(label="Find a computer or a mounted volume:", xalign=0)
    body.pack_start(heading, False, False, 0)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Search local and mounted locations")
    search.get_accessible().set_name("Search computer locations")
    body.pack_start(search, False, False, 0)

    store = Gtk.ListStore(str, str, str)
    tree = Gtk.TreeView(model=store)
    tree.set_headers_visible(True)
    tree.get_accessible().set_name("Available computers and mounted volumes")
    for index, caption in enumerate(("Name", "Type")):
        column = Gtk.TreeViewColumn(caption, Gtk.CellRendererText(), text=index)
        column.set_resizable(True)
        column.set_expand(index == 0)
        tree.append_column(column)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroller.add(tree)
    body.pack_start(scroller, True, True, 0)

    status = Gtk.Label(xalign=0)
    status.set_line_wrap(True)
    body.pack_start(status, False, False, 0)
    network = Gtk.Button(label="Browse Network Neighborhood…")
    try:
        supports_network = network_browsing_available(
            Gio.Vfs.get_default().get_supported_uri_schemes())
    except Exception as exc:
        LOG.debug("GVfs network capability unavailable: %s", exc)
        supports_network = False
    network.set_sensitive(supports_network)
    if not supports_network:
        network.set_tooltip_text("Install/configure a GVfs network backend for network:/// browsing")
    body.pack_start(network, False, False, 0)

    monitor = Gio.VolumeMonitor.get()
    state = {"locations": ()}
    connections = []

    def selection_changed(selection):
        model, selected = selection.get_selected()
        open_button.set_sensitive(selected is not None and bool(model[selected][2]))

    def refresh(*_args):
        try:
            state["locations"] = mounted_locations(monitor)
            matches = filter_locations(state["locations"], search.get_text())
            store.clear()
            for location in matches:
                store.append((location.name, location.kind, location.uri))
            total = len(state["locations"])
            status.set_text(f"{len(matches)} of {total} available locations. "
                            "Only currently mounted volumes are listed.")
            selection_changed(tree.get_selection())
        except Exception as exc:
            LOG.warning("Could not refresh Classic computer locations: %s", exc)
            store.clear()
            open_button.set_sensitive(False)
            status.set_text("Device discovery unavailable: " + str(exc))

    def open_selected(*_args):
        model, selected = tree.get_selection().get_selected()
        if selected is None or not model[selected][2]:
            return
        uri = model[selected][2]
        # The system's configured file manager handles authentication and I/O.
        open_location(shell, uri, Gio)

    def respond(_dialog, response):
        if response == Gtk.ResponseType.OK:
            open_selected()
        else:
            _dialog.destroy()

    def destroy(_dialog):
        for handler in connections:
            try:
                monitor.disconnect(handler)
            except (TypeError, ValueError):
                pass
        shell._classic98_computer_dialog = None

    tree.get_selection().connect("changed", selection_changed)
    tree.connect("row-activated", open_selected)
    search.connect("changed", refresh)
    for signal in ("mount-added", "mount-removed", "mount-changed"):
        connections.append(monitor.connect(signal, refresh))
    network.connect("clicked", lambda _button: shell._open_uri("network:///"))
    dialog.connect("response", respond)
    dialog.connect("destroy", destroy)
    shell._classic98_computer_dialog = dialog
    dialog.show_all()
    refresh()
    search.grab_focus()
    return dialog
