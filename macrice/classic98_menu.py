"""Windows 98 SE Start menu and safe local descendants for the Linux shell.

No executable commands are assembled through a shell. The GTK recent list,
XDG bookmarks and Gio application catalog are the actual sources of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class Favorite:
    label: str
    uri: str


def favorites_path() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return config / "ricebowl" / "classic98-favorites.json"


def valid_favorite(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return False
    return parsed.scheme in {"file", "https", "http", "smb", "sftp", "ftp"} and bool(
        parsed.netloc or parsed.path)


def user_favorites(path: Path | None = None) -> tuple[Favorite, ...]:
    source = path or favorites_path()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    items = []
    for row in data[:300]:
        if isinstance(row, dict) and isinstance(row.get("label"), str) and isinstance(row.get("uri"), str):
            label, uri = row["label"].strip()[:100], row["uri"].strip()
            if label and valid_favorite(uri):
                items.append(Favorite(label, uri))
    return tuple(items)


def save_favorites(items: tuple[Favorite, ...], path: Path | None = None) -> None:
    """Atomic user-scoped persistence; GTK bookmarks are never overwritten."""
    dest = path or favorites_path()
    if len(items) > 300 or any(not item.label.strip() or not valid_favorite(item.uri) for item in items):
        raise ValueError("Invalid favorite")
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix=".classic98-", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump([{"label": item.label, "uri": item.uri} for item in items], stream,
                      ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, dest)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def gtk_bookmarks() -> tuple[Favorite, ...]:
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    source = config / "gtk-3.0" / "bookmarks"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    result = []
    for line in lines[:300]:
        uri, _, label = line.strip().partition(" ")
        if not valid_favorite(uri):
            continue
        name = label.strip() or unquote(urlsplit(uri).path.rstrip("/").split("/")[-1]) or uri
        result.append(Favorite(name[:100], uri))
    return tuple(result)


def all_favorites() -> tuple[Favorite, ...]:
    seen, result = set(), []
    for item in (*user_favorites(), *gtk_bookmarks()):
        if item.uri not in seen:
            seen.add(item.uri)
            result.append(item)
    return tuple(result)


def parse_run_target(value: str) -> tuple[str, object]:
    """Classify user input without invoking /bin/sh or expanding command substitutions."""
    value = value.strip()
    if not value:
        raise ValueError("Enter a program, document, folder or web address.")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https", "file", "sftp", "smb"}:
        if not valid_favorite(value):
            raise ValueError("Invalid address")
        return "uri", value
    try:
        argv = shlex.split(value)
    except ValueError as exc:
        raise ValueError("Unbalanced quotes in command") from exc
    if not argv:
        raise ValueError("Enter a command")
    first = os.path.expanduser(os.path.expandvars(argv[0]))
    path = Path(first)
    if ("/" in first or first.startswith(".")) and path.exists():
        if path.is_dir() or (path.is_file() and not os.access(path, os.X_OK)):
            if len(argv) != 1:
                raise ValueError("Documents and folders cannot have command arguments")
            return "uri", path.resolve().as_uri()
        return "command", (str(path), *argv[1:])
    if not shutil.which(first):
        raise ValueError("Program is not installed: " + first)
    return "command", (first, *argv[1:])


def launch_run_target(target: tuple[str, object], Gio):
    kind, value = target
    if kind == "uri":
        Gio.AppInfo.launch_default_for_uri(value, None)
    elif kind == "command":
        subprocess.Popen(list(value), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    else:
        raise ValueError("Unsupported Run target")


def quick_launch_menu_action(identifier: str | None, pins: tuple[str, ...],
                             limit: int) -> tuple[str, bool, bool] | None:
    """Label, enabled, intended pin state for the real per-rice pins store."""
    if not identifier:
        return None
    already_pinned = identifier in pins
    return ("Remove from Quick Launch" if already_pinned else "Add to Quick Launch",
            already_pinned or len(pins) < limit, not already_pinned)


def remember_run(history: tuple[str, ...], value: str, maximum: int = 12) -> tuple[str, ...]:
    """Session-only most-recent-first entries; no credentials written to disk."""
    text = value.strip()
    if not text:
        return history[:maximum]
    return (text, *(entry for entry in history if entry != text))[:maximum]


def show_run(shell, Gtk, Gio, *, theme="winclassic"):
    """Shared safe Run backend with Win98 or XP-native UI and isolated history."""
    if theme not in ("winclassic", "winxp"):
        raise ValueError("Unsupported Run dialog theme")
    shell._hide_menu()
    history_name = "_luna_run_history" if theme == "winxp" else "_classic98_run_history"
    history = tuple(getattr(shell, history_name, ()))
    dialog = Gtk.Dialog(title="Run", transient_for=shell.bar,
                        flags=(Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
                               if theme == "winxp" else Gtk.DialogFlags.MODAL))
    if theme == "winxp":
        dialog.get_style_context().add_class("luna-run-dialog")
        shell._luna_run_dialog = dialog
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("OK", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_default_size(450, -1)
    if theme == "winxp":
        from gi.repository import Gdk
        from .luna_dialog import attach_luna_dialog_chrome

        body = attach_luna_dialog_chrome(
            dialog, Gtk, Gdk, role="ricebowl-xp-run", title="Run",
            close_response=Gtk.ResponseType.CANCEL)
    else:
        body = dialog.get_content_area()
    body.set_spacing(9)
    body.set_margin_start(14)
    body.set_margin_end(14)
    body.set_margin_top(12)
    body.set_margin_bottom(12)
    prompt = Gtk.Label(label=("Type the name of a program, folder, document or Internet\n"
                              "resource, and RiceBowl will open it for you."
                              if theme == "winxp" else
                              "Type the name of a program, folder, document, or Internet resource:"),
                       xalign=0)
    prompt.set_line_wrap(True)
    if theme == "winxp":
        intro = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=13)
        intro.pack_start(Gtk.Image.new_from_icon_name(
            "system-run", Gtk.IconSize.DIALOG), False, False, 0)
        intro.pack_start(prompt, True, True, 0)
        body.pack_start(intro, False, False, 2)
    else:
        body.pack_start(prompt, False, False, 0)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.pack_start(Gtk.Label(label="Open:"), False, False, 0)
    combo = Gtk.ComboBoxText.new_with_entry()
    combo.set_hexpand(True)
    entry = combo.get_child()
    entry.set_activates_default(True)
    entry.get_accessible().set_name("Open command or address")
    for previous in history:
        combo.append_text(previous)
    row.pack_start(combo, True, True, 0)
    body.pack_start(row, False, False, 0)
    feedback = Gtk.Label(xalign=0)
    feedback.set_line_wrap(True)
    feedback.set_no_show_all(True)
    body.pack_start(feedback, False, False, 0)

    def browse(_button):
        chooser = Gtk.FileChooserDialog(title="Browse", transient_for=dialog,
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        try:
            if chooser.run() == Gtk.ResponseType.OK:
                selected = chooser.get_filename()
                if selected:
                    entry.set_text(shlex.quote(selected))
                    feedback.hide()
        finally:
            chooser.destroy()

    tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
    browse_button = Gtk.Button(label="Browse…")
    browse_button.connect("clicked", browse)
    tools.pack_start(browse_button, False, False, 0)
    clear = Gtk.Button(label="Clear history")
    clear.set_sensitive(bool(history))
    if theme == "winxp" and not history:
        clear.set_no_show_all(True)
    def clear_history(_button):
        setattr(shell, history_name, ())
        combo.remove_all()
        clear.set_sensitive(False)
        if theme == "winxp":
            clear.hide()
    clear.connect("clicked", clear_history)
    tools.pack_start(clear, False, False, 0)
    body.pack_start(tools, False, False, 0)
    dialog.show_all()
    if theme == "winxp":
        from .luna_taskbar_settings import center_on_workarea

        dialog.move(*center_on_workarea(shell._desktop_rect(), *dialog.get_size()))
    feedback.hide()
    entry.grab_focus()
    try:
        while dialog.run() == Gtk.ResponseType.OK:
            typed = entry.get_text()
            try:
                target = parse_run_target(typed)
                launch_run_target(target, Gio)
            except Exception as exc:
                # GLib.Error and OSError are shown without closing the modal.
                feedback.set_text("Could not open: " + str(exc))
                feedback.show()
                entry.grab_focus()
                continue
            setattr(shell, history_name, remember_run(
                tuple(getattr(shell, history_name, ())), typed))
            shell._hide_menu()
            break
    finally:
        dialog.destroy()
        if theme == "winxp":
            shell._luna_run_dialog = None


def show_favorite_manager(shell, Gtk):
    dialog = Gtk.Dialog(title="Organize Favorites", transient_for=shell.bar,
                        flags=Gtk.DialogFlags.MODAL)
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    dialog.set_default_size(430, 330)
    body = dialog.get_content_area()
    body.set_spacing(7)
    body.set_margin_start(12)
    body.set_margin_end(12)
    body.set_margin_top(10)
    body.pack_start(Gtk.Label(label="Your RiceBowl favorites (GTK bookmarks are read-only here)",
                              xalign=0), False, False, 0)
    entries = list(user_favorites())
    store = Gtk.ListStore(str, str)
    view = Gtk.TreeView(model=store)
    for index, name in enumerate(("Name", "Address")):
        view.append_column(Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=index))
    area = Gtk.ScrolledWindow()
    area.set_min_content_height(150)
    area.add(view)
    body.pack_start(area, True, True, 0)
    name = Gtk.Entry(placeholder_text="Name")
    uri = Gtk.Entry(placeholder_text="file:///… or https://…")
    body.pack_start(name, False, False, 0)
    body.pack_start(uri, False, False, 0)

    def refresh():
        store.clear()
        for item in entries:
            store.append((item.label, item.uri))

    def save():
        try:
            save_favorites(tuple(entries))
        except (OSError, ValueError) as exc:
            shell._error("Could not save Favorites: " + str(exc))
            return False
        refresh()
        return True

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    add = Gtk.Button(label="Add")
    update = Gtk.Button(label="Rename / Update")
    remove = Gtk.Button(label="Remove selected")
    move_up = Gtk.Button(label="Move up")
    move_down = Gtk.Button(label="Move down")

    def add_entry(_button):
        if not name.get_text().strip() or not valid_favorite(uri.get_text().strip()):
            shell._error("Enter a name and a supported file or web address.")
            return
        entries.append(Favorite(name.get_text().strip()[:100], uri.get_text().strip()))
        if save():
            name.set_text("")
            uri.set_text("")

    def selected_index():
        model, iterator = view.get_selection().get_selected()
        return model.get_path(iterator).get_indices()[0] if iterator is not None else None

    def select_entry(selection):
        index = selected_index()
        if index is not None:
            name.set_text(entries[index].label)
            uri.set_text(entries[index].uri)

    view.get_selection().connect("changed", select_entry)

    def update_entry(_button):
        index = selected_index()
        if index is None or not name.get_text().strip() or not valid_favorite(uri.get_text().strip()):
            shell._error("Select a favorite and enter a valid name and address.")
            return
        entries[index] = Favorite(name.get_text().strip()[:100], uri.get_text().strip())
        save()

    def change(which):
        index = selected_index()
        if index is None:
            return
        if which == "delete":
            entries.pop(index)
        else:
            to = index + (-1 if which == "up" else 1)
            if not 0 <= to < len(entries):
                return
            entries[index], entries[to] = entries[to], entries[index]
        save()

    add.connect("clicked", add_entry)
    update.connect("clicked", update_entry)
    remove.connect("clicked", lambda _button: change("delete"))
    move_up.connect("clicked", lambda _button: change("up"))
    move_down.connect("clicked", lambda _button: change("down"))
    for widget in (add, update, remove, move_up, move_down):
        buttons.pack_start(widget, False, False, 0)
    body.pack_start(buttons, False, False, 0)
    refresh()
    dialog.show_all()
    dialog.run()
    dialog.destroy()


def show_file_search(shell, Gtk, GLib):
    """Read-only, bounded Win98 Find with real content and metadata filters."""
    from .classic98_find import FindCriteria, search_folder, validate_criteria
    dialog = Gtk.Dialog(title="Find: All Files", transient_for=shell.bar)
    dialog.add_button("Close", Gtk.ResponseType.CLOSE)
    dialog.set_default_size(580, 450)
    body = dialog.get_content_area()
    body.set_spacing(7)
    body.set_margin_start(10)
    body.set_margin_end(10)
    body.set_margin_top(10)
    query = Gtk.Entry(placeholder_text="Name contains…")
    query.get_accessible().set_name("Find files by name")
    body.pack_start(query, False, False, 0)
    chooser = Gtk.FileChooserButton(title="Look in", action=Gtk.FileChooserAction.SELECT_FOLDER)
    chooser.set_filename(str(Path.home()))
    body.pack_start(chooser, False, False, 0)
    advanced = Gtk.Expander(label="Advanced options: type, date, size and text")
    grid = Gtk.Grid(column_spacing=8, row_spacing=7)
    grid.set_border_width(8)
    file_type = Gtk.ComboBoxText()
    for key, label in (("both", "Files and folders"), ("files", "Files only"),
                       ("folders", "Folders only")):
        file_type.append(key, label)
    file_type.set_active_id("both")
    grid.attach(Gtk.Label(label="Type:", xalign=0), 0, 0, 1, 1)
    grid.attach(file_type, 1, 0, 1, 1)
    date = Gtk.ComboBoxText()
    for key, label in (("any", "Any time"), ("1", "Last 24 hours"),
                       ("7", "Last 7 days"), ("30", "Last 30 days"),
                       ("365", "Last year")):
        date.append(key, label)
    date.set_active_id("any")
    grid.attach(Gtk.Label(label="Modified:", xalign=0), 0, 1, 1, 1)
    grid.attach(date, 1, 1, 1, 1)
    extension = Gtk.Entry(placeholder_text="e.g. txt (optional)")
    extension.get_accessible().set_name("File extension")
    grid.attach(Gtk.Label(label="Extension:", xalign=0), 0, 2, 1, 1)
    grid.attach(extension, 1, 2, 1, 1)
    contents = Gtk.Entry(placeholder_text="Search text inside files (up to 1 MiB)")
    contents.get_accessible().set_name("Text within files")
    grid.attach(Gtk.Label(label="Containing:", xalign=0), 0, 3, 1, 1)
    grid.attach(contents, 1, 3, 1, 1)
    minimum = Gtk.Entry(placeholder_text="Minimum MiB (optional)")
    maximum = Gtk.Entry(placeholder_text="Maximum MiB (optional)")
    minimum.get_accessible().set_name("Minimum file size in MiB")
    maximum.get_accessible().set_name("Maximum file size in MiB")
    grid.attach(Gtk.Label(label="Size in MiB:", xalign=0), 0, 4, 1, 1)
    limits = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    limits.pack_start(minimum, True, True, 0)
    limits.pack_start(maximum, True, True, 0)
    grid.attach(limits, 1, 4, 1, 1)
    hidden = Gtk.CheckButton(label="Include hidden files and folders")
    grid.attach(hidden, 1, 5, 1, 1)
    advanced.add(grid)
    body.pack_start(advanced, False, False, 0)
    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    start = Gtk.Button(label="Find Now")
    cancel = Gtk.Button(label="Stop")
    cancel.set_sensitive(False)
    controls.pack_start(start, False, False, 0)
    controls.pack_start(cancel, False, False, 0)
    body.pack_start(controls, False, False, 0)
    info = Gtk.Label(label="Read-only search · up to 50,000 entries and 500 results.", xalign=0)
    body.pack_start(info, False, False, 0)
    results = Gtk.ListBox()
    area = Gtk.ScrolledWindow()
    area.set_min_content_height(190)
    area.add(results)
    body.pack_start(area, True, True, 0)
    current = {"stop": threading.Event(), "generation": 0}

    def open_result(_list, row):
        shell._open_uri(Path(row._rice_path).as_uri())

    results.connect("row-activated", open_result)

    def batch(generation, found, scanned, final=False, reason=""):
        if generation != current["generation"] or not dialog.get_visible():
            return False
        for path in found:
            item = Gtk.ListBoxRow()
            item._rice_path = str(path)
            label = Gtk.Label(label=str(path), xalign=0)
            label.set_line_wrap(True)
            item.add(label)
            results.add(item)
        results.show_all()
        info.set_text(f"{scanned} entries searched · {len(results.get_children())} found"
                      + (" · " + (reason or "complete") if final else "…"))
        if final:
            start.set_sensitive(True)
            cancel.set_sensitive(False)
        return False

    def size_bytes(widget, name):
        value = widget.get_text().strip()
        if not value:
            return None
        if len(value) > 7 or not value.isdecimal():
            raise ValueError(name + " must be a non-negative whole number in MiB.")
        return int(value) * 1024 * 1024

    def perform(_button):
        folder = chooser.get_filename()
        if not folder or not Path(folder).is_dir():
            info.set_text("Choose an existing folder to search.")
            return
        try:
            days = date.get_active_id()
            criteria = FindCriteria(
                name=query.get_text(), text=contents.get_text(),
                extension=extension.get_text(),
                kind=file_type.get_active_id(),
                modified_within_days=None if days == "any" else int(days),
                min_bytes=size_bytes(minimum, "Minimum size"),
                max_bytes=size_bytes(maximum, "Maximum size"),
                include_hidden=hidden.get_active())
            validate_criteria(criteria)
        except (ValueError, TypeError) as exc:
            info.set_text(str(exc))
            return
        current["stop"].set()
        stop = threading.Event()
        current["stop"] = stop
        current["generation"] += 1
        generation = current["generation"]
        for row in results.get_children():
            results.remove(row)
        start.set_sensitive(False)
        cancel.set_sensitive(True)
        info.set_text("Searching…")

        def worker():
            def send(paths, scanned, final, reason):
                GLib.idle_add(batch, generation, paths, scanned, final, reason)
            try:
                search_folder(Path(folder), criteria, stop, send)
            except (OSError, ValueError) as exc:
                send([], 0, True, "Search failed: " + str(exc))

        threading.Thread(target=worker, name="ricebowl98-find", daemon=True).start()

    start.connect("clicked", perform)
    cancel.connect("clicked", lambda _button: current["stop"].set())
    query.connect("activate", perform)
    contents.connect("activate", perform)
    extension.connect("activate", perform)
    dialog.show_all()
    dialog.run()
    current["stop"].set()
    current["generation"] += 1
    dialog.destroy()


def show_help(shell, Gtk):
    """Launch the native, navigable Classic Help viewer."""
    from .classic98_help import show_help as open_help
    open_help(shell, Gtk)



def build(shell, Gtk, Gdk, Gio, GLib, Pango):
    """Create the period menu and publish compatible shell fields."""
    menu = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    menu.set_title("RiceBowl Windows 98 Start")
    menu.set_decorated(False)
    menu.set_resizable(True)
    menu.set_skip_taskbar_hint(True)
    menu.set_skip_pager_hint(True)
    menu.set_type_hint(Gdk.WindowTypeHint.UTILITY)
    menu.set_transient_for(shell.bar)
    menu.set_keep_above(True)
    menu.set_default_size(262, 332)
    root = shell._class(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), "classic-menu")
    rail = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "classic-brand")
    rail.set_size_request(27, -1)
    brand = shell._class(Gtk.Label(label="RiceBowl 98"), "classic-brand-label")
    brand.set_angle(90)
    rail.pack_end(brand, False, False, 9)
    root.pack_start(rail, False, False, 0)
    main = shell._class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "classic-menu-list")

    def row(title, icon, *, cascade=None, action=None):
        button = shell._class(Gtk.MenuButton() if cascade else Gtk.Button(), "classic-menu-item")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.pack_start(shell._icon(icon, Gtk.IconSize.MENU), False, False, 0)
        content.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
        if cascade is not None:
            content.pack_end(shell._class(Gtk.Label(label="▶"), "classic-chevron"),
                             False, False, 0)
            button.set_direction(Gtk.ArrowType.RIGHT)
            button.set_popup(cascade)
            button.connect("enter-notify-event", lambda widget, _event:
                           widget.set_active(True) if widget.get_sensitive() else None)
        else:
            button.connect("clicked", lambda _widget: action())
        button.add(content)
        button.get_accessible().set_name(title)
        main.pack_start(button, False, False, 0)
        return button

    def item(title, icon=None, action=None, enabled=True, explanation=None):
        entry = Gtk.ImageMenuItem.new_with_label(title)
        if icon:
            entry.set_image(shell._icon(icon, Gtk.IconSize.MENU))
            entry.set_always_show_image(True)
        entry.set_sensitive(enabled)
        if explanation:
            entry.set_tooltip_text(explanation)
        if action is not None:
            entry.connect("activate", lambda _entry: action())
        return entry

    programs = shell._track_start_popup(Gtk.Menu())
    row("Programs", "applications-other", cascade=programs)
    favorites = shell._track_start_popup(Gtk.Menu())
    row("Favorites", "user-home", cascade=favorites)
    documents = shell._track_start_popup(Gtk.Menu())
    row("Documents", "folder-documents", cascade=documents)
    main.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)
    settings = shell._track_start_popup(Gtk.Menu())
    row("Settings", "classic-control-panel", cascade=settings)
    finder = shell._track_start_popup(Gtk.Menu())
    row("Find", "edit-find", cascade=finder)
    row("Help", "help-browser", action=lambda: show_help(shell, Gtk))
    row("Run…", "system-run", action=lambda: show_run(shell, Gtk, Gio))
    main.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

    shell.classic_search = shell._class(Gtk.SearchEntry(), "aero-menu-search")
    shell.classic_search.set_placeholder_text("Find programs")
    shell.classic_search.get_accessible().set_name("Find installed programs")
    shell.classic_search.set_no_show_all(True)
    main.pack_start(shell.classic_search, False, False, 3)
    shell.classic_results_scroll = Gtk.ScrolledWindow()
    shell.classic_results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    shell.classic_results_scroll.set_min_content_height(112)
    shell.classic_results_scroll.set_no_show_all(True)
    shell.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    shell.classic_results_scroll.add(shell.results)
    main.pack_start(shell.classic_results_scroll, True, True, 0)
    row("Shut Down…", "system-shutdown", action=lambda:
        shell._open_tool("xfce4-session-logout"))
    root.pack_start(main, True, True, 0)
    menu.add(root)

    def replace_children(target, entries):
        for child in target.get_children():
            target.remove(child)
        for child in entries:
            target.append(child)
        target.show_all()

    def refresh_programs():
        categories = (
            ("Accessories", {"Utility", "Accessories", "TextEditor"}),
            ("Games", {"Game"}),
            ("Graphics", {"Graphics", "Photography"}),
            ("Internet", {"Network", "WebBrowser", "Email"}),
            ("Multimedia", {"Audio", "Video", "Player"}),
            ("Office", {"Office", "Spreadsheet", "WordProcessor"}),
            ("System Tools", {"System", "Settings", "FileManager", "Terminal"}),
        )
        groups = {name: [] for name, _ in categories}
        groups["Other Programs"] = []
        for app in shell.apps:
            names = set((app.get_categories() or "").split(";")) if hasattr(app, "get_categories") else set()
            target = next((title for title, tags in categories if names & tags), "Other Programs")
            groups[target].append(app)
        entries = [item("My Computer", "computer", lambda:
                        open_computer()),
                   item("Windows Explorer (Home)", "folder", lambda:
                        open_classic_home())]
        entries.append(Gtk.SeparatorMenuItem())
        for group, apps in groups.items():
            if not apps:
                continue
            submenu = shell._track_start_popup(Gtk.Menu())
            submenu.get_style_context().add_class("classic98-flyout")
            children = []
            for app in sorted(apps, key=lambda a: (a.get_display_name() or a.get_name() or "").casefold()):
                name = app.get_display_name() or app.get_name() or "Application"
                entry = Gtk.MenuItem(label=name)
                entry.connect("activate", lambda _widget, selected=app: shell._launch(selected))
                entry.set_tooltip_text(name + " · Right-click to manage Quick Launch")
                def program_context(widget, selected, event=None):
                    if event is not None and event.button != 3:
                        return False
                    identifier = selected.get_id()
                    context = shell._track_start_popup(Gtk.Menu())
                    open_item = Gtk.MenuItem(label="Open")
                    open_item.connect("activate", lambda _item: shell._launch(selected))
                    context.append(open_item)
                    if identifier:
                        from .aero_pins import PIN_LIMIT
                        label, enabled, should_pin = quick_launch_menu_action(
                            identifier, shell._pinned_ids, PIN_LIMIT)
                        pin_item = Gtk.MenuItem(label=label)
                        pin_item.set_sensitive(enabled)
                        pin_item.connect("activate", lambda _item:
                                         shell._change_pin(identifier, should_pin))
                        context.append(pin_item)
                    context.show_all()
                    if event is not None:
                        context.popup_at_pointer(event)
                    else:
                        context.popup_at_widget(widget, Gdk.Gravity.SOUTH_WEST,
                                                Gdk.Gravity.NORTH_WEST, None)
                    return True
                entry.connect("button-press-event", lambda widget, event, selected=app:
                              program_context(widget, selected, event))
                entry.connect("popup-menu", lambda widget, selected=app:
                              program_context(widget, selected))
                children.append(entry)
            replace_children(submenu, children)
            parent = Gtk.MenuItem(label=group)
            parent.set_submenu(submenu)
            entries.append(parent)
        entries.append(Gtk.SeparatorMenuItem())
        entries.append(item("Find a program…", "edit-find", shell._reveal_classic_search))
        replace_children(programs, entries)

    def refresh_favorites():
        entries = [item(fav.label, "folder" if fav.uri.startswith("file:") else "applications-internet",
                        lambda uri=fav.uri: shell._open_uri(uri)) for fav in all_favorites()]
        if not entries:
            entries.append(item("No bookmarks yet", enabled=False))
        entries.append(Gtk.SeparatorMenuItem())
        entries.append(item("Organize Favorites…", "document-properties",
                            lambda: show_favorite_manager(shell, Gtk)))
        replace_children(favorites, entries)

    def refresh_documents():
        items = Gtk.RecentManager.get_default().get_items()
        items.sort(key=lambda i: i.get_modified(), reverse=True)
        entries = [item("My Documents", "folder-documents", lambda:
                        shell._open_uri((Path.home() / "Documents").as_uri()),
                        enabled=(Path.home() / "Documents").is_dir())]
        entries.append(Gtk.SeparatorMenuItem())
        count = 0
        for info in items:
            if count >= 12:
                break
            uri = info.get_uri()
            if not uri:
                continue
            label = info.get_display_name() or uri.rsplit("/", 1)[-1]
            exists = info.exists()
            entries.append(item(label, "text-x-generic", lambda selected=uri:
                                shell._open_uri(selected), enabled=exists,
                                explanation=None if exists else "This recent document no longer exists"))
            count += 1
        if not count:
            entries.append(item("No recent documents", enabled=False))
        entries.append(Gtk.SeparatorMenuItem())
        entries.append(item("Clear Recent Documents…", "edit-clear", clear_recent,
                            enabled=bool(count)))
        replace_children(documents, entries)

    def clear_recent():
        question = Gtk.MessageDialog(transient_for=shell.bar,
                                     flags=Gtk.DialogFlags.MODAL,
                                     message_type=Gtk.MessageType.QUESTION,
                                     buttons=Gtk.ButtonsType.YES_NO,
                                     text="Clear the recent documents list?")
        question.format_secondary_text("This removes GTK recent-history entries, not the actual files.")
        try:
            confirmed = question.run() == Gtk.ResponseType.YES
        finally:
            question.destroy()
        if confirmed:
            try:
                Gtk.RecentManager.get_default().purge_items()
                refresh_documents()
            except Exception as exc:
                shell._error("Could not clear recent history: " + str(exc))

    def available_tool(name, candidates):
        command = next((candidate for candidate in candidates if shutil.which(candidate)), None)
        return item(name, "preferences-system", lambda cmd=command: shell._open_tool(cmd)
                    if cmd else None, enabled=command is not None,
                    explanation="Requires: " + " / ".join(candidates) if not command else None)

    replace_children(settings, (
        item("Control Panel", "classic-control-panel", shell._toggle_actions),
        available_tool("Printers", ("system-config-printer",)),
        item("Taskbar & Start Menu", "preferences-desktop",
             shell.classic98_open_taskbar_properties),
        available_tool("Folder Options", ("xfce4-settings-manager",)),
    ))
    def open_computer():
        from .classic98_computer import show as show_computer
        return show_computer(shell, Gtk, Gio)

    def open_classic_home():
        from .classic98_computer import open_location
        return open_location(shell, Path.home().as_uri(), Gio)

    replace_children(finder, (
        item("Files or Folders…", "edit-find", lambda: show_file_search(shell, Gtk, GLib)),
        item("Computer…", "network-workgroup", open_computer),
    ))

    def refresh():
        refresh_programs()
        refresh_favorites()
        refresh_documents()

    shell.classic_menus = (programs, favorites, documents, settings, finder)
    shell.classic_refresh_submenus = refresh
    refresh()
    shell._finish_heritage_menu(menu, shell.classic_search)
