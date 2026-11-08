"""Optional Rice Creator: GTK3 front end to the existing safe Wayland API.

No resident compositor, AI service or active-session mutation. Real screenshots
are produced on demand by the same isolated RicePlate renderer as the CLI.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

from .de import creator_workspace as workspace
from .de import drafts, recipes, render, review


# All paths below are existing allowlisted Creator draft-edit fields. Gtk owns
# the widgets, while RicePlate's parser owns validity and Linux semantics.
FIELDS = (
    ("Rice identity", (
        ("/name", "Name", "text", None),
    )),
    ("Shell", (
        ("/panel/position", "Panel edge", "choice", ("top", "bottom")),
        ("/panel/height", "Panel height (px)", "number", (28, 64)),
        ("/menu/presentation", "Start menu", "choice", ("tabs", "sidebar")),
        ("/desktop/wallpaper", "Wallpaper", "choice", tuple(sorted(recipes.WALLPAPERS))),
        ("/responsive/compact_max_width", "Compact below (px)", "number", (480, 1440)),
    )),
    ("Surface colors", (
        ("/colors/background", "Background", "color", None),
        ("/colors/foreground", "Foreground", "color", None),
        ("/colors/active", "Accent", "color", None),
        ("/appearance/hover", "Hover", "color", None),
        ("/appearance/focus", "Keyboard focus", "color", None),
        ("/appearance/disabled", "Disabled", "color", None),
    )),
    ("Typography & spacing", (
        ("/appearance/font_scale", "Text scale", "choice-int", (1, 2)),
        ("/appearance/font_weight", "Text weight", "choice", ("regular", "bold")),
        ("/appearance/item_spacing", "Item spacing", "number", (0, 16)),
        ("/tokens/label_padding", "Label padding", "number", (0, 16)),
        ("/tokens/task_radius", "Task radius", "number", (0, 12)),
    )),
)


def _get_field(manifest: dict, pointer: str):
    # The canonical schema deliberately omits the default tabs presentation.
    if pointer == "/menu/presentation":
        return manifest.get("menu", {}).get("presentation", "tabs")
    value = manifest
    for part in pointer.lstrip("/").split("/"):
        value = value[part]
    return value


def _node_label(node: dict) -> str:
    kind = node.get("type", "unknown")
    if kind == "widget":
        return f"▣  {node['id']}"
    if kind == "component":
        return f"◈  {node['ref']}"
    if kind == "group":
        return f"▤  Group · {len(node.get('children', []))} items"
    if kind == "gap":
        return f"↔  {node.get('width', 0)} px gap"
    if kind == "action":
        return f"◇  {node['id']} action"
    if kind == "control":
        return f"⚙  {node['id']} control"
    return kind


def run() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("Rice Creator needs a graphical desktop session.", file=__import__("sys").stderr)
        return 1
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:
        print(f"Rice Creator requires GTK3/PyGObject: {exc}", file=__import__("sys").stderr)
        return 1

    from .hub import CSS as HUB_CSS, TOKENS

    extra_css = """
    #creator-sidebar { background: %(sidebar)s; border-right: 1px solid %(border)s; }
    #creator-sidebar list, #creator-sidebar listbox, #creator-sidebar listbox row,
    #creator-sidebar scrolledwindow, #creator-sidebar viewport { background: %(sidebar)s; }
    #creator-inspector { background: %(surface)s; border-left: 1px solid %(border)s; }
    #creator-preview { background: %(sidebar)s; }
    .creator-rail-label { color: %(quiet)s; font-size: 11px; font-weight: bold; }
    .creator-preview-note { color: %(muted)s; font-size: 12px; }
    .creator-title { color: %(text)s; font-size: 22px; font-weight: bold; }
    .creator-status { color: %(muted)s; font-size: 12px; }
    .creator-error { color: %(error)s; font-size: 12px; }
    .creator-good { color: %(success)s; font-size: 12px; }
    .creator-layout-row { background: %(surface_alt)s; border-radius: 6px; margin: 2px 0; padding: 5px; }
    .creator-inspector-group { color: %(text)s; font-weight: bold; }
    .creator-section { border-top: 1px solid %(border)s; padding-top: 7px; }
    button.creator-template { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s;
      padding: 9px; border-radius: 8px; }
    button.creator-template:hover { background: %(hover)s; }
    button.creator-template:focus, button:focus { outline: 2px solid %(accent)s; outline-offset: 1px; }
    .creator-dirty { color: %(warning)s; }
    """ % TOKENS

    class CreatorWindow(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title="Rice Creator · RiceBowl")
            self.set_name("ricebowl-window")
            self.set_default_size(1280, 820)
            self.set_size_request(820, 560)
            self.info: workspace.DraftInfo | None = None
            self.baseline: dict | None = None
            self.pending: dict[str, object] = {}
            self.layout: dict[str, list[dict]] = {}
            self._building = False
            self._busy = False
            self._render_generation = 0
            self._pixbuf = None
            self._preview_fit: tuple[int, int] | None = None
            self._history: list[Path] = []
            self._build()
            self._refresh_drafts()
            self.connect("delete-event", self._close)

        def _button(self, label, handler, *, primary=False):
            button = Gtk.Button(label=label)
            button.set_size_request(-1, 36)
            button.connect("clicked", handler)
            button.get_style_context().add_class("hub-primary" if primary else "hub-action")
            return button

        def _text(self, text, css_class=None, *, wrap=False):
            label = Gtk.Label(label=text, xalign=0)
            label.set_line_wrap(wrap)
            if css_class:
                label.get_style_context().add_class(css_class)
            return label

        def _build(self):
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(outer)
            toolbar = Gtk.Box(spacing=10)
            toolbar.set_border_width(12)
            outer.pack_start(toolbar, False, False, 0)
            brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            brand.pack_start(self._text("RICE / CREATOR", "creator-rail-label"), False, False, 0)
            brand.pack_start(self._text("Build a desktop rice", "creator-title"), False, False, 0)
            toolbar.pack_start(brand, True, True, 0)
            self.undo_btn = self._button("← Previous version", self._undo)
            self.save_btn = self._button("Save version", self._save, primary=True)
            self.render_btn = self._button("Render preview", self._render)
            self.export_btn = self._button("Export RicePack…", self._export)
            for button in (self.undo_btn, self.save_btn, self.render_btn, self.export_btn):
                toolbar.pack_start(button, False, False, 0)

            self.main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            outer.pack_start(self.main, True, True, 0)
            sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            sidebar.set_name("creator-sidebar")
            sidebar.set_border_width(14)
            sidebar.set_size_request(218, -1)
            self.main.pack1(sidebar, resize=False, shrink=False)
            sidebar.pack_start(self._text("NEW FROM TEMPLATE", "creator-rail-label"), False, False, 0)
            descriptions = {
                "heritage": "Compact classic · bottom bar",
                "orbit": "Expressive · top bar + sidebar",
                "classic": "Original classic base",
                "chrome": "Original Chrome base",
            }
            for key, (name, _) in workspace.TEMPLATES.items():
                button = self._button(name, lambda _b, kind=key: self._create(kind))
                button.get_style_context().add_class("creator-template")
                button.set_tooltip_text(descriptions[key])
                sidebar.pack_start(button, False, False, 0)
            sidebar.pack_start(self._text("SAVED VERSIONS", "creator-rail-label"), False, False, 8)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sidebar.pack_start(scroll, True, True, 0)
            self.draft_list = Gtk.ListBox()
            self.draft_list.set_selection_mode(Gtk.SelectionMode.NONE)
            scroll.add(self.draft_list)
            sidebar.pack_start(self._text("Drafts are private. Saving never applies a rice.",
                                          "hub-hint", wrap=True), False, False, 4)

            content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            self.main.pack2(content, resize=True, shrink=False)
            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            preview.set_name("creator-preview")
            preview.set_border_width(17)
            content.pack1(preview, resize=True, shrink=False)
            head = Gtk.Box(spacing=12)
            preview.pack_start(head, False, False, 0)
            head.pack_start(self._text("REAL SHELL PREVIEW", "creator-rail-label"), True, True, 0)
            self.geometry = Gtk.ComboBoxText()
            for key, label in (("1024,768,1", "1024 × 768"),
                               ("1366,768,1", "1366 × 768"),
                               ("1920,1080,1", "1920 × 1080"),
                               ("1366,768,1.25", "1366 × 768 · 125%")):
                self.geometry.append(key, label)
            self.geometry.set_active_id("1366,768,1")
            head.pack_start(self.geometry, False, False, 0)
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.IN)
            preview.pack_start(frame, True, True, 0)
            self.preview_scroller = Gtk.ScrolledWindow()
            self.preview_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            frame.add(self.preview_scroller)
            self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.preview_box.set_halign(Gtk.Align.CENTER)
            self.preview_box.set_valign(Gtk.Align.CENTER)
            self.preview_scroller.add(self.preview_box)
            self.preview_image = Gtk.Image.new_from_icon_name("video-display", Gtk.IconSize.DIALOG)
            self.preview_box.pack_start(self.preview_image, True, True, 0)
            self.preview_caption = self._text("Choose a template, then render a real native RicePlate image.",
                                              "creator-preview-note", wrap=True)
            self.preview_caption.set_xalign(0.5)
            self.preview_box.pack_start(self.preview_caption, False, False, 0)
            self.preview_scroller.connect("size-allocate", self._resize_preview)
            self.spinner = Gtk.Spinner()
            preview.pack_start(self.spinner, False, False, 0)
            self.diff = self._text("Changes appear here after saving a version.",
                                   "creator-preview-note", wrap=True)
            preview.pack_start(self.diff, False, False, 0)

            inspector_scroll = Gtk.ScrolledWindow()
            inspector_scroll.set_name("creator-inspector")
            inspector_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            inspector_scroll.set_size_request(318, -1)
            content.pack2(inspector_scroll, resize=False, shrink=False)
            self.inspector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.inspector.set_border_width(15)
            inspector_scroll.add(self.inspector)
            self.inspector.pack_start(self._text("PROPERTIES", "creator-rail-label"), False, False, 0)
            self.inspector_context = self._text("Create a draft to edit its real recipe.",
                                                "hub-hint", wrap=True)
            self.inspector.pack_start(self.inspector_context, False, False, 0)

            status_box = Gtk.Box(spacing=8)
            status_box.set_border_width(8)
            outer.pack_start(status_box, False, False, 0)
            self.status = self._text("Choose a template to begin.", "creator-status")
            status_box.pack_start(self.status, True, True, 0)
            self._actions()

        def _status(self, message: str, *, error=False, success=False):
            self.status.set_text(message)
            style = self.status.get_style_context()
            for klass in ("creator-status", "creator-error", "creator-good"):
                style.remove_class(klass)
            style.add_class("creator-error" if error else "creator-good" if success else "creator-status")

        def _actions(self):
            selected = self.info is not None
            self.save_btn.set_sensitive(selected and bool(self.pending) and not self._busy)
            self.render_btn.set_sensitive(selected and not self._busy)
            self.export_btn.set_sensitive(selected and not self._busy)
            self.undo_btn.set_sensitive(bool(self._history) and not self._busy)

        def _refresh_drafts(self):
            for child in self.draft_list.get_children():
                self.draft_list.remove(child)
            try:
                found = workspace.list_drafts()
            except (workspace.WorkspaceError, OSError) as exc:
                self._status(str(exc), error=True)
                return
            for info in found:
                label = f"{info.name}\n{info.recipe_id} · {info.semantic_sha256[:8]}"
                button = self._button(label, lambda _b, path=info.path: self._open(path))
                button.set_tooltip_text("Open a saved private version")
                self.draft_list.add(button)
            self.draft_list.show_all()

        def _discard_pending(self) -> bool:
            if not self.pending:
                return True
            dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                       message_type=Gtk.MessageType.QUESTION,
                                       buttons=Gtk.ButtonsType.NONE,
                                       text="Discard unsaved changes?")
            dialog.format_secondary_text("The saved draft version remains available.")
            dialog.add_button("Keep editing", Gtk.ResponseType.CANCEL)
            dialog.add_button("Discard changes", Gtk.ResponseType.OK)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            response = dialog.run()
            dialog.destroy()
            return response == Gtk.ResponseType.OK

        def _create(self, template: str):
            if self._busy or not self._discard_pending():
                return
            try:
                info = workspace.create_draft(template)
                self._load(info, reset_history=True)
                self._refresh_drafts()
                self._status("Private schema-v10 draft created. Edit, save a version, then render.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not create draft: {exc}", error=True)

        def _open(self, path: Path):
            if self._busy or not self._discard_pending():
                return
            try:
                self._load(workspace.open_draft(path), reset_history=True)
                self._status("Saved draft opened. Nothing has been applied.", success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not open draft: {exc}", error=True)

        def _load(self, info: workspace.DraftInfo, *, reset_history=False):
            report = review.review(str(info.path))
            if report["recipe"]["schema_version"] != 10:
                raise workspace.WorkspaceError("Creator 0.1 currently edits schema-v10 recipes only")
            self._render_generation += 1
            self.info, self.baseline, self.pending = info, report["recipe"], {}
            self.layout = copy.deepcopy(self.baseline["panel"]["layout"])
            if reset_history:
                self._history = []
            self._pixbuf = None
            self._preview_fit = None
            self.preview_image.set_from_icon_name("video-display", Gtk.IconSize.DIALOG)
            self.preview_caption.set_text("Preview not rendered for this saved version.")
            self.diff.set_text(f"Recipe: {info.recipe_id} · Schema v10 · SHA {info.semantic_sha256[:12]}")
            self.inspector_context.set_text(f"Editing {info.name} · schema v10 · offline draft")
            self._build_inspector()
            self._actions()

        def _build_inspector(self):
            for child in self.inspector.get_children()[2:]:
                self.inspector.remove(child)
            assert self.baseline is not None
            self._building = True
            for title, fields in FIELDS:
                expander = Gtk.Expander(label=title)
                expander.set_expanded(title in ("Rice identity", "Shell", "Surface colors"))
                self.inspector.pack_start(expander, False, False, 0)
                grid = Gtk.Grid(column_spacing=12, row_spacing=10)
                grid.set_margin_top(10)
                grid.set_margin_bottom(12)
                expander.add(grid)
                for index, (path, label, kind, options) in enumerate(fields):
                    label_widget = self._text(label, "hub-body")
                    label_widget.set_size_request(112, -1)
                    grid.attach(label_widget, 0, index, 1, 1)
                    current = _get_field(self.baseline, path)
                    if kind == "text":
                        widget = Gtk.Entry()
                        widget.set_max_length(60)
                        widget.set_text(current)
                        widget.connect("changed", lambda w, p=path: self._change(p, w.get_text()))
                    elif kind in ("choice", "choice-int"):
                        widget = Gtk.ComboBoxText()
                        for option in options:
                            widget.append(str(option), str(option))
                        widget.set_active_id(str(current))
                        widget.connect("changed", lambda w, p=path, k=kind:
                                       self._change(p, int(w.get_active_id()) if k == "choice-int"
                                                    and w.get_active_id() is not None else w.get_active_id()))
                    elif kind == "number":
                        lower, upper = options
                        widget = Gtk.SpinButton.new_with_range(lower, upper, 1)
                        widget.set_value(current)
                        widget.connect("value-changed", lambda w, p=path:
                                       self._change(p, w.get_value_as_int()))
                    else:
                        widget = Gtk.ColorButton()
                        rgba = Gdk.RGBA()
                        rgba.parse(current)
                        widget.set_rgba(rgba)
                        widget.set_use_alpha(False)
                        widget.connect("color-set", lambda w, p=path:
                                       self._change(p, "#" + "".join(f"{round(c * 255):02x}" for c in
                                       (w.get_rgba().red, w.get_rgba().green, w.get_rgba().blue))))
                    widget.set_hexpand(True)
                    widget.set_tooltip_text(path)
                    grid.attach(widget, 1, index, 1, 1)
                    label_widget.set_mnemonic_widget(widget)
            expander = Gtk.Expander(label="Panel composition · start / center / end")
            expander.set_expanded(True)
            self.inspector.pack_start(expander, False, False, 0)
            self.layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.layout_box.set_margin_top(8)
            expander.add(self.layout_box)
            for lane in recipes.SECTIONS:
                self._build_lane(lane)
            self.inspector.show_all()
            self._building = False

        def _build_lane(self, lane: str):
            group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.layout_box.pack_start(group, False, False, 0)
            group.pack_start(self._text(lane.upper(), "creator-rail-label"), False, False, 0)
            for index, node in enumerate(self.layout[lane]):
                row = Gtk.Box(spacing=5)
                row.get_style_context().add_class("creator-layout-row")
                row.pack_start(self._text(_node_label(node), "hub-body"), True, True, 0)
                for title, delta in (("↑", -1), ("↓", 1)):
                    button = Gtk.Button(label=title)
                    button.set_tooltip_text(f"Move {_node_label(node)} {title}")
                    button.set_sensitive(0 <= index + delta < len(self.layout[lane]))
                    button.connect("clicked", lambda _b, section=lane, i=index, d=delta:
                                   self._move(section, i, d))
                    row.pack_start(button, False, False, 0)
                remove = Gtk.Button(label="×")
                remove.set_tooltip_text(f"Remove {_node_label(node)}")
                remove.connect("clicked", lambda _b, section=lane, i=index:
                               self._remove_node(section, i))
                row.pack_start(remove, False, False, 0)
                group.pack_start(row, False, False, 0)
            add_row = Gtk.Box(spacing=5)
            choices = Gtk.ComboBoxText()
            for element in sorted(recipes.WIDGETS):
                choices.append(f"widget:{element}", element)
            for component in self.baseline.get("components", []):
                choices.append(f"component:{component['id']}", f"Component: {component['label']}")
            choices.append("gap", "Spacing: 8 px")
            choices.set_active_id("gap")
            add_row.pack_start(choices, True, True, 0)
            button = Gtk.Button(label="Add")
            button.connect("clicked", lambda _b, section=lane, picker=choices:
                           self._add_node(section, picker.get_active_id()))
            add_row.pack_start(button, False, False, 0)
            group.pack_start(add_row, False, False, 0)

        def _refresh_layout(self):
            for child in self.layout_box.get_children():
                self.layout_box.remove(child)
            for lane in recipes.SECTIONS:
                self._build_lane(lane)
            self.layout_box.show_all()

        def _move(self, lane, index, delta):
            nodes = self.layout[lane]
            nodes[index], nodes[index + delta] = nodes[index + delta], nodes[index]
            self._change(f"/panel/layout/{lane}", copy.deepcopy(nodes))
            self._refresh_layout()

        def _remove_node(self, lane, index):
            self.layout[lane].pop(index)
            self._change(f"/panel/layout/{lane}", copy.deepcopy(self.layout[lane]))
            self._refresh_layout()

        def _add_node(self, lane, selection):
            if selection is None:
                return
            if selection == "gap":
                node = {"type": "gap", "width": 8}
            else:
                kind, identifier = selection.split(":", 1)
                node = {"type": kind, "ref" if kind == "component" else "id": identifier}
            self.layout[lane].append(node)
            self._change(f"/panel/layout/{lane}", copy.deepcopy(self.layout[lane]))
            self._refresh_layout()

        def _change(self, path, value):
            if self._building or self.baseline is None:
                return
            if value == _get_field(self.baseline, path):
                self.pending.pop(path, None)
            else:
                self.pending[path] = value
            self._status(f"{len(self.pending)} unsaved properties · Save version before preview/export"
                         if self.pending else "No unsaved changes")
            self._actions()

        def _commit_pending(self) -> bool:
            if not self.pending:
                return True
            assert self.info is not None
            try:
                revised, changes = workspace.save_revision(self.info.path, self.pending,
                                                expected_sha256=self.info.semantic_sha256)
                self._history.append(self.info.path)
                self._load(revised)
                self._refresh_drafts()
                self.diff.set_text("Validated changes: " + ", ".join(x["path"] for x in changes))
                self._status(f"Saved a new private version ({len(changes)} changes).", success=True)
                return True
            except (workspace.WorkspaceError, drafts.DraftError, recipes.RecipeError,
                    OSError, ValueError) as exc:
                self._status(f"Save blocked: {exc}. Fix the layout or property and retry.", error=True)
                return False

        def _save(self, _button):
            self._commit_pending()

        def _undo(self, _button):
            if self._busy or not self._discard_pending() or not self._history:
                return
            try:
                info = workspace.open_draft(self._history.pop())
                self._load(info)
                self._status("Previous private version reopened. No active rice changed.", success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not reopen previous version: {exc}", error=True)

        def _render(self, _button):
            if self._busy or not self._commit_pending() or self.info is None:
                return
            info = self.info
            width, height, scale = self.geometry.get_active_id().split(",")
            self._busy = True
            self._render_generation += 1
            generation = self._render_generation
            self.spinner.start()
            self.preview_caption.set_text("Rendering in an isolated headless labwc session…")
            self._status("Starting the native renderer. The active desktop is unchanged.")
            self._actions()

            def work():
                try:
                    with tempfile.TemporaryDirectory(prefix="ricebowl-creator-preview-") as temp:
                        target = Path(temp) / "preview.png"
                        receipt = render.render(str(info.path), target, width=int(width),
                                                height=int(height), scale=float(scale))
                        contents = target.read_bytes()
                    error = None
                except (render.RenderError, OSError, ValueError, RuntimeError) as exc:
                    receipt, contents, error = None, None, str(exc)
                GLib.idle_add(self._render_complete, generation, receipt, contents, error)

            threading.Thread(target=work, name="ricebowl-creator-render", daemon=False).start()

        def _render_complete(self, generation, receipt, contents, error):
            if generation != self._render_generation or not self.get_visible():
                return False
            self._busy = False
            self.spinner.stop()
            if error:
                self.preview_caption.set_text("Native preview unavailable. Draft editing still works.")
                self._status(f"Render failed: {error}. Check labwc, grim and native RicePlate.", error=True)
            else:
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                try:
                    loader.write(contents)
                    loader.close()
                    self._pixbuf = loader.get_pixbuf()
                    self._preview_fit = None
                    self._resize_preview()
                    self.preview_caption.set_text(
                        f"Native RicePlate · {receipt['geometry']['width']} × "
                        f"{receipt['geometry']['height']} · scale {receipt['geometry']['scale']}")
                    self._status("Real native capture ready. No desktop settings changed.", success=True)
                except (GLib.Error, ValueError, KeyError) as exc:
                    self._status(f"Cannot display rendered PNG: {exc}", error=True)
            self._actions()
            return False

        def _resize_preview(self, *_args):
            if self._pixbuf is None:
                return
            allocation = self.preview_scroller.get_allocation()
            width = max(100, allocation.width - 28)
            height = max(100, allocation.height - 88)
            if self._preview_fit == (width, height):
                return
            self._preview_fit = (width, height)
            ratio = min(width / self._pixbuf.get_width(), height / self._pixbuf.get_height(), 1)
            fitted = self._pixbuf.scale_simple(max(1, round(self._pixbuf.get_width() * ratio)),
                                                max(1, round(self._pixbuf.get_height() * ratio)),
                                                GdkPixbuf.InterpType.BILINEAR)
            self.preview_image.set_from_pixbuf(fitted)

        def _export(self, _button):
            if self._busy or not self._commit_pending() or self.info is None:
                return
            chooser = Gtk.FileChooserDialog(title="Export validated RicePack", transient_for=self,
                                            action=Gtk.FileChooserAction.SAVE)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Export RicePack", Gtk.ResponseType.ACCEPT)
            chooser.set_do_overwrite_confirmation(False)
            chooser.set_current_name(f"{self.info.recipe_id}.ricepack")
            response = chooser.run()
            destination = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if destination is None:
                return
            try:
                workspace.export_draft(self.info, destination)
                self._status(f"RicePack created: {destination.name}. Not installed or applied.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError, ValueError) as exc:
                self._status(f"Export failed: {exc}. Choose a new filename; no overwrite is allowed.",
                             error=True)

        def _close(self, *_args):
            # Closing the UI cannot kill the native renderer mid-cleanup. Its
            # non-daemon thread finishes the supervised teardown and then exits.
            return not self._discard_pending()

    provider = Gtk.CssProvider()
    provider.load_from_data(HUB_CSS + extra_css.encode("utf-8"))
    screen = Gdk.Screen.get_default()
    if screen is None:
        print("Rice Creator could not connect to the desktop display.", file=__import__("sys").stderr)
        return 1
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    app = Gtk.Application(application_id="io.github.ricebowl.creator",
                          flags=Gio.ApplicationFlags.FLAGS_NONE)
    windows = []
    smoke_failed = False

    def activate(application):
        if not windows:
            windows.append(CreatorWindow(application))
        windows[0].show_all()
        windows[0].present()
        if os.environ.get("RICEBOWL_CREATOR_SMOKE") == "1":
            GLib.idle_add(smoke_test)

    def smoke_test():
        nonlocal smoke_failed
        try:
            if not os.environ.get("XDG_STATE_HOME"):
                raise RuntimeError("Creator smoke requires an isolated XDG_STATE_HOME")
            window = windows[0]
            window._create("heritage")
            assert window.info is not None and window.info.recipe_id.startswith("creator-")
            initial = window.info
            window._change("/panel/height", 44)
            assert window.save_btn.get_sensitive()
            assert window._commit_pending()
            assert window.info.path != initial.path and len(window._history) == 1
            assert recipes.load(str(window.info.path)).height == 44
            window._move("start", 0, 1)
            assert window.pending
            window._change("/panel/layout/start", window.baseline["panel"]["layout"]["start"])
            assert not window.pending
            window._undo(None)
            assert window.info.path == initial.path
            path = os.environ.get("RICEBOWL_CREATOR_SMOKE_CAPTURE")
            if path:
                window.queue_draw()
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                surface = window.get_window()
                pixbuf = Gdk.pixbuf_get_from_window(surface, 0, 0,
                                                       window.get_allocated_width(),
                                                       window.get_allocated_height())
                if pixbuf is None:
                    raise RuntimeError("Could not capture GTK Creator window")
                pixbuf.savev(path, "png", [], [])
        except Exception:
            import traceback
            traceback.print_exc()
            smoke_failed = True
        finally:
            app.quit()
        return False

    app.connect("activate", activate)
    code = app.run([])
    return 1 if smoke_failed else code
