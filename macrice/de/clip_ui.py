"""On-demand GTK3 RiceClip browser. No autostart, polling or private disk state.

Only the original 80-character previews cross the watcher socket. A copy is
guarded by the exact history revision displayed when the user chose the row.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Thread

from . import clip


@dataclass(frozen=True)
class ClipRow:
    index: int
    preview: str
    characters: int
    pinned: bool = False


@dataclass(frozen=True)
class ClipSnapshot:
    revision: int
    session_id: str
    paused: bool
    rows: tuple[ClipRow, ...]
    hidden_count: int = 0


def read_snapshot() -> ClipSnapshot:
    """Read a consistent, bounded snapshot without starting the watcher."""
    for _attempt in range(2):
        status = clip.request("status")
        # Paused history is intentionally hidden: de lock pauses before its
        # clear IPC request. Never fetch sensitive previews in that interval.
        if status.get("paused") is True:
            identity = status.get("session_id")
            revision = status.get("revision")
            hidden = status.get("count")
            if (type(revision) is not int or revision < 0
                    or type(hidden) is not int or not 0 <= hidden <= clip.MAX_ITEMS
                    or not isinstance(identity, str) or len(identity) != 32
                    or any(ch not in "0123456789abcdef" for ch in identity)):
                raise clip.ClipError("invalid_request")
            return ClipSnapshot(revision, identity, True, (), hidden_count=hidden)
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
                or type(status.get("pinned_count")) is not int
                or status["pinned_count"] < 0
                or status["pinned_count"] > clip.MAX_PINS
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
                    or item["characters"] < len(item["preview"])
                    or type(item.get("pinned")) is not bool):
                raise clip.ClipError("invalid_request")
            # Pinned entries form one bounded prefix in the watcher.
            if item["pinned"] != (position < status["pinned_count"]):
                raise clip.ClipError("invalid_request")
            rows.append(ClipRow(position, item["preview"], item["characters"],
                                item["pinned"]))
        return ClipSnapshot(revision, identity, status["paused"], tuple(rows))
    raise clip.ClipError("stale_history")


def visible_rows(snapshot: ClipSnapshot, query: str) -> tuple[ClipRow, ...]:
    """Search only the visible preview, never unseen private clipboard text."""
    needle = query[:80].casefold().strip()
    return tuple(row for row in snapshot.rows if needle in row.preview.casefold())


def snapshot_message(snapshot: ClipSnapshot, query: str) -> str:
    """Truthful empty/search state without leaking unseen clipboard contents."""
    state = "Paused" if snapshot.paused else "Recording"
    count = len(snapshot.rows)
    if snapshot.paused:
        return "Paused · Clipboard previews hidden until recording resumes"
    if count == 0:
        return f"{state} · No clipboard text saved in this session"
    if query.strip() and not visible_rows(snapshot, query):
        return f"No previews match your search · {count} stored in session memory"
    noun = "item" if count == 1 else "items"
    pins = sum(row.pinned for row in snapshot.rows)
    return f"{state} · {count} {noun} in volatile session memory · {pins} pinned"


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
        self.events_epoch = 0
        self.events_conn = None
        self.event_listener_active = False
        self.pending_event_refresh = False

        self.window = Gtk.Window(title="RiceClip · Clipboard history")
        self.window.set_default_size(700, 480)
        self.window.set_size_request(430, 300)
        self.window.connect("destroy", self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        root.set_border_width(14)
        self.window.add(root)

        heading = Gtk.Label()
        heading.set_markup("<span size='x-large' weight='bold'>RiceClip</span>")
        heading.set_xalign(0)
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
            column = Gtk.TreeViewColumn(title, renderer, text=number)
            if number == 1:
                # Grow previews into the available viewport instead of
                # ellipsizing at a tiny default column width.
                column.set_expand(True)
                column.set_resizable(True)
            self.list.append_column(column)
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
        self.pin_button = Gtk.Button(label="Pin selected")
        self.pin_button.get_accessible().set_name("Pin selected clipboard item")
        self.pin_button.connect("clicked", lambda _button: self._toggle_pin())
        controls.pack_start(self.pin_button, False, False, 0)
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
        self._start_events()
        self.refresh()

    def _close(self, _window):
        self.closed = True
        connection = self.events_conn
        if connection is not None:
            try:
                connection.shutdown(2)
            except OSError:
                pass
            connection.close()
        self.events_conn = None
        self.snapshot = None
        self.store.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.Gtk.main_quit()

    def _buttons(self):
        row = self._selected_row()
        ready = not self.busy and self.snapshot is not None
        self.copy_button.set_sensitive(ready and row is not None)
        self.pin_button.set_label("Unpin selected" if row and row.pinned else "Pin selected")
        self.pin_button.set_sensitive(
            ready and row is not None and
            (row.pinned or sum(entry.pinned for entry in self.snapshot.rows) < clip.MAX_PINS)
        )
        self.refresh_button.set_sensitive(not self.busy)
        self.pause_button.set_sensitive(ready)
        self.clear_button.set_sensitive(ready and bool(self.snapshot.rows or self.snapshot.hidden_count))

    def _work(self, operation, completed):
        if self.busy or self.closed:
            return
        self.busy = True
        epoch = self.events_epoch
        self._buttons()
        future = self.executor.submit(operation)

        def callback(finished):
            def on_main():
                if self.closed:
                    return False
                self.busy = False
                if epoch != self.events_epoch:
                    # A lock/clear event invalidated this async operation;
                    # never reintroduce an old snapshot after the event.
                    if self.pending_event_refresh:
                        self.pending_event_refresh = False
                        self.refresh()
                    self._buttons()
                    return False
                try:
                    value = finished.result()
                except clip.ClipError as exc:
                    if exc.code in ("not_running", "unavailable", "invalid_request", "stale_history"):
                        self.snapshot = None
                        self.store.clear()
                    self.status.set_text(str(exc))
                except Exception:
                    self.status.set_text("RiceClip request failed; use Refresh to retry")
                else:
                    completed(value)
                if self.pending_event_refresh:
                    self.pending_event_refresh = False
                    self.refresh()
                self._buttons()
                return False
            self.GLib.idle_add(on_main)

        future.add_done_callback(callback)

    def _start_events(self):
        if self.closed or self.event_listener_active:
            return
        self.event_listener_active = True

        def listen():
            connection = None
            reader = None
            try:
                connection, reader, initial = clip.open_event_subscription()
                self.events_conn = connection
                self.GLib.idle_add(self._history_event,
                                   {**initial, "event": "connected"})
                while not self.closed:
                    message = clip._read_event_line(reader)
                    if (message.get("session_id") != initial["session_id"]
                            or message.get("event") not in ("privacy", "state")):
                        raise clip.ClipError("invalid_request")
                    self.GLib.idle_add(self._history_event, message)
            except (OSError, clip.ClipError):
                if not self.closed:
                    self.GLib.idle_add(self._events_disconnected)
            finally:
                self.event_listener_active = False
                self.events_conn = None
                if connection is not None:
                    try:
                        connection.shutdown(2)
                    except OSError:
                        pass
                if reader is not None:
                    reader.close()
                if connection is not None:
                    connection.close()

        Thread(target=listen, name="riceclip-privacy-events",
               daemon=True).start()

    def _expire_previews(self, status: str, *, reload: bool):
        # Called only from the GTK main context. Drop old list state before
        # any pending worker result can put the private previews back.
        self.events_epoch += 1
        self.snapshot = None
        self.store.clear()
        self.search.set_text("")
        self.status.set_text(status)
        self.pending_event_refresh = reload
        self._buttons()
        if reload and not self.busy:
            self.pending_event_refresh = False
            self.refresh()

    def _history_event(self, message):
        if self.closed:
            return False
        if message.get("event") == "connected":
            snapshot = self.snapshot
            if (snapshot is None or
                    (not message["paused"] and message["count"] > 0
                     and snapshot.session_id == message["session_id"]
                     and snapshot.revision == message["revision"])):
                return False
        self._expire_previews(
            "RiceClip history changed · refreshing private session state",
            reload=True,
        )
        return False

    def _events_disconnected(self):
        if not self.closed:
            self._expire_previews(
                "RiceClip watcher unavailable · Refresh after restarting it",
                reload=False,
            )
        return False

    def refresh(self, *, preferred_index=None, expected_revision=None):
        if not self.event_listener_active:
            self._start_events()
        def show(snapshot):
            self.snapshot = snapshot
            self.pause_button.set_label("Resume recording" if snapshot.paused else "Pause recording")
            # A moved row can only be reselected if no clipboard event
            # intervened after the server reported its new index.
            target = (preferred_index if snapshot.revision == expected_revision
                      and type(preferred_index) is int else None)
            self._render_rows(preferred_index=target)
        self._work(read_snapshot, show)

    def _render_rows(self, *, preferred_index=None):
        self.store.clear()
        if self.snapshot is None:
            self._buttons()
            return
        selected_path = None
        for path_index, row in enumerate(visible_rows(self.snapshot, self.search.get_text())):
            preview = row.preview.replace("\n", " ↵ ").replace("\r", " ").replace("\t", " ⇥ ")
            self.store.append((row.index,
                               ("★ " if row.pinned else "") + preview,
                               str(row.characters)))
            if row.index == preferred_index:
                selected_path = path_index
        if len(self.store):
            self.list.get_selection().select_path(
                selected_path if selected_path is not None else 0)
        self.status.set_text(snapshot_message(self.snapshot, self.search.get_text()))
        self._buttons()

    def _selected_row(self) -> ClipRow | None:
        if self.snapshot is None:
            return None
        model, selected = self.list.get_selection().get_selected()
        if selected is None:
            return None
        index = model.get_value(selected, 0)
        return next((row for row in self.snapshot.rows if row.index == index), None)

    def _toggle_pin(self):
        if self.busy or self.snapshot is None:
            return
        row = self._selected_row()
        if row is None:
            return
        snapshot = self.snapshot
        op = "unpin" if row.pinned else "pin"
        def updated(receipt):
            self.refresh(preferred_index=receipt.get("selected_index"),
                         expected_revision=receipt.get("revision"))

        self._work(
            lambda: clip.request(op, index=row.index,
                                 revision=snapshot.revision,
                                 session_id=snapshot.session_id),
            updated,
        )

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
        if self.snapshot is None or not (self.snapshot.rows or self.snapshot.hidden_count):
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
