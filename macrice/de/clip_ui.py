"""On-demand GTK3 RiceClip browser. No autostart, polling or private disk state.

Only the original 80-character previews cross the watcher socket. A copy is
guarded by the exact history revision displayed when the user chose the row.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import clip


@dataclass(frozen=True)
class ClipRow:
    index: int
    preview: str
    characters: int


@dataclass(frozen=True)
class ClipSnapshot:
    revision: int
    session_id: str
    paused: bool
    rows: tuple[ClipRow, ...]


def read_snapshot() -> ClipSnapshot:
    """Read a consistent, bounded snapshot without starting the watcher."""
    for _attempt in range(2):
        status = clip.request("status")
        listing = clip.request("list")
        revision = listing.get("revision")
        identity = listing.get("session_id")
        if (type(revision) is not int or type(status.get("revision")) is not int
                or not isinstance(identity, str) or len(identity) != 32
                or any(character not in "0123456789abcdef" for character in identity)
                or not isinstance(status.get("session_id"), str)):
            raise clip.ClipError("invalid_request")
        if revision != status["revision"] or identity != status["session_id"]:
            continue
        items = listing.get("items")
        if (type(status.get("paused")) is not bool or type(status.get("count")) is not int
                or not isinstance(items, list) or len(items) > clip.MAX_ITEMS
                or status["count"] != len(items) or revision < 0):
            raise clip.ClipError("invalid_request")
        rows = []
        for position, item in enumerate(items):
            if (not isinstance(item, dict)
                    or type(item.get("index")) is not int or item["index"] != position
                    or not isinstance(item.get("preview"), str)
                    or len(item["preview"]) > 80
                    or type(item.get("characters")) is not int
                    or item["characters"] < len(item["preview"])):
                raise clip.ClipError("invalid_request")
            rows.append(ClipRow(position, item["preview"], item["characters"]))
        return ClipSnapshot(revision, identity, status["paused"], tuple(rows))
    raise clip.ClipError("stale_history")


def visible_rows(snapshot: ClipSnapshot, query: str) -> tuple[ClipRow, ...]:
    """Search only the visible preview, never unseen private clipboard text."""
    needle = query[:80].casefold().strip()
    return tuple(row for row in snapshot.rows if needle in row.preview.casefold())


def restore_row(row: ClipRow, snapshot: ClipSnapshot) -> None:
    """Fail closed when a new clipboard event has changed the selected index."""
    clip.request("copy", index=row.index, revision=snapshot.revision,
                 session_id=snapshot.session_id)


class RiceClipWindow:
    def __init__(self, Gtk, GLib):
        self.Gtk, self.GLib = Gtk, GLib
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="riceclip-ui")
        self.closed = False
        self.busy = False
        self.snapshot: ClipSnapshot | None = None

        self.window = Gtk.Window(title="RiceClip · Clipboard history")
        self.window.set_default_size(700, 480)
        self.window.set_size_request(430, 300)
        self.window.connect("destroy", self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        root.set_border_width(14)
        self.window.add(root)

        heading = Gtk.Label(label="RiceClip")
        heading.set_xalign(0)
        heading.get_style_context().add_class("title")
        root.pack_start(heading, False, False, 0)

        description = Gtk.Label(label="Session-only text history · search visible previews")
        description.set_xalign(0)
        root.pack_start(description, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Filter clipboard previews")
        self.search.get_accessible().set_name("Search RiceClip history previews")
        self.search.connect("search-changed", lambda _entry: self._render_rows())
        root.pack_start(self.search, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.store = Gtk.ListStore(int, str, str)
        self.list = Gtk.TreeView(model=self.store)
        self.list.set_headers_visible(True)
        for number, title in enumerate(("Index", "Text preview", "Length")):
            renderer = Gtk.CellRendererText()
            if number == 1:
                renderer.set_property("ellipsize", 3)  # Pango.EllipsizeMode.END
            self.list.append_column(Gtk.TreeViewColumn(title, renderer, text=number))
        self.list.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        self.list.get_selection().connect("changed", lambda _selection: self._buttons())
        self.list.connect("row-activated", lambda *_args: self._copy())
        scroller.add(self.list)
        root.pack_start(scroller, True, True, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(controls, False, False, 0)
        self.copy_button = Gtk.Button(label="Copy selected")
        self.copy_button.get_accessible().set_name("Restore selected history item to clipboard")
        self.copy_button.connect("clicked", lambda _button: self._copy())
        controls.pack_start(self.copy_button, False, False, 0)
        self.refresh_button = Gtk.Button(label="Refresh")
        self.refresh_button.connect("clicked", lambda _button: self.refresh())
        controls.pack_start(self.refresh_button, False, False, 0)
        self.pause_button = Gtk.Button(label="Pause recording")
        self.pause_button.connect("clicked", lambda _button: self._pause())
        controls.pack_start(self.pause_button, False, False, 0)
        self.clear_button = Gtk.Button(label="Clear history")
        self.clear_button.connect("clicked", lambda _button: self._clear())
        controls.pack_end(self.clear_button, False, False, 0)

        self.status = Gtk.Label(label="Connecting to existing RiceClip watcher…")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        self.status.get_accessible().set_name("RiceClip status")
        root.pack_start(self.status, False, False, 0)
        self._buttons()
        self.window.show_all()
        self.refresh()

    def _close(self, _window):
        self.closed = True
        self.snapshot = None
        self.store.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.Gtk.main_quit()

    def _buttons(self):
        selection = self.list.get_selection().get_selected()[1]
        ready = not self.busy and self.snapshot is not None
        self.copy_button.set_sensitive(ready and selection is not None)
        self.refresh_button.set_sensitive(not self.busy)
        self.pause_button.set_sensitive(ready)
        self.clear_button.set_sensitive(ready and bool(self.snapshot.rows))

    def _work(self, operation, completed):
        if self.busy or self.closed:
            return
        self.busy = True
        self._buttons()
        future = self.executor.submit(operation)

        def callback(finished):
            def on_main():
                if self.closed:
                    return False
                self.busy = False
                try:
                    value = finished.result()
                except clip.ClipError as exc:
                    if exc.code in ("not_running", "unavailable", "invalid_request"):
                        self.snapshot = None
                        self.store.clear()
                    self.status.set_text(str(exc))
                except Exception:
                    self.status.set_text("RiceClip request failed; use Refresh to retry")
                else:
                    completed(value)
                self._buttons()
                return False
            self.GLib.idle_add(on_main)

        future.add_done_callback(callback)

    def refresh(self):
        def show(snapshot):
            self.snapshot = snapshot
            self.pause_button.set_label("Resume recording" if snapshot.paused else "Pause recording")
            self._render_rows()
            state = "Paused" if snapshot.paused else "Recording"
            self.status.set_text(f"{state} · {len(snapshot.rows)} items in volatile session memory")
        self._work(read_snapshot, show)

    def _render_rows(self):
        self.store.clear()
        if self.snapshot is None:
            self._buttons()
            return
        for row in visible_rows(self.snapshot, self.search.get_text()):
            preview = row.preview.replace("\n", " ↵ ").replace("\r", " ").replace("\t", " ⇥ ")
            self.store.append((row.index, preview, str(row.characters)))
        if len(self.store):
            self.list.get_selection().select_path(0)
        self._buttons()

    def _copy(self):
        if self.busy or self.snapshot is None:
            return
        model, selected = self.list.get_selection().get_selected()
        if selected is None:
            return
        index = model.get_value(selected, 0)
        row = next((row for row in self.snapshot.rows if row.index == index), None)
        if row is None:
            return
        snapshot = self.snapshot
        def copied(_value):
            self.status.set_text("Restored selected text to Wayland clipboard")
            self.refresh()
        self._work(lambda: restore_row(row, snapshot), copied)

    def _pause(self):
        if self.snapshot is None:
            return
        op = "resume" if self.snapshot.paused else "pause"
        self._work(lambda: clip.request(op), lambda _result: self.refresh())

    def _clear(self):
        if self.snapshot is None or not self.snapshot.rows:
            return
        dialog = self.Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=self.Gtk.MessageType.WARNING,
            buttons=self.Gtk.ButtonsType.NONE,
            text="Delete this session's RiceClip history?")
        dialog.format_secondary_text("This cannot be undone. The clipboard selection itself is not cleared.")
        dialog.add_buttons("Cancel", self.Gtk.ResponseType.CANCEL,
                           "Clear history", self.Gtk.ResponseType.OK)
        approved = dialog.run() == self.Gtk.ResponseType.OK
        dialog.destroy()
        if approved:
            self._work(lambda: clip.request("clear"), lambda _result: self.refresh())


def launch() -> None:
    """A standalone GTK window: never start the watcher implicitly."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError("RiceClip GUI requires GTK 3 and PyGObject") from exc
    if Gdk.Display.get_default() is None:
        raise RuntimeError("RiceClip GUI requires a graphical Wayland display")
    RiceClipWindow(Gtk, GLib)
    Gtk.main()
