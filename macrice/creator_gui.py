"""Optional Rice Creator: GTK3 front end to the existing safe Wayland API.

No resident compositor, AI service or active-session mutation. Real screenshots
are produced on demand by the same isolated RicePlate renderer as the CLI.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from .de import (creator_activation, creator_interactive, creator_layout as layout_engine,
                 creator_workspace as workspace)
from .de import (assets, creator_assets, creator_iteration, creator_mapping, creator_reference, creator_regions,
                 creator_structure, drafts,
                 fonts, pack, recipes, render, review, style_assets)


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


def _choice_options(pointer: str, options: tuple, schema_version: int) -> tuple:
    return (options + ("columns",) if pointer == "/menu/presentation" and schema_version >= 12
            else options)


def _revision_review_text(preflight: dict) -> str:
    """Complete, readable data-only before/after diff for the confirmation dialog."""
    lines = [
        f"Source SHA-256: {preflight['source_semantic_sha256']}",
        f"Proposed SHA-256: {preflight['draft_semantic_sha256']}",
        "",
    ]
    for change in preflight["changes"]:
        lines.extend((
            change["path"],
            "  Before: " + json.dumps(change["before"], ensure_ascii=False, sort_keys=True),
            "  After:  " + json.dumps(change["after"], ensure_ascii=False, sort_keys=True),
            "",
        ))
    return "\n".join(lines)


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
    if kind == "divider":
        return f"│  {node['width']} px divider"
    if kind == "label":
        return f"T  {node['text']}"
    return kind


def _node_template(choice: str) -> dict:
    """Known, safe panel primitives; no recipe-supplied command execution."""
    if choice == "group":
        return {"type": "group", "gap": 8,
                "children": [{"type": "gap", "width": 8}]}
    if choice == "gap":
        return {"type": "gap", "width": 8}
    if choice == "divider":
        return {"type": "divider", "width": 8}
    if choice == "label":
        return {"type": "label", "text": "New label"}
    kind, identifier = choice.split(":", 1)
    if kind in ("widget", "component"):
        return {"type": kind, "ref" if kind == "component" else "id": identifier}
    if kind in ("action", "control"):
        return {"type": kind, "id": identifier,
                "label": identifier.replace("-", " ").title()[:16]}
    raise creator_structure.StructureError("Unsupported panel primitive")


def run() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("Rice Creator needs a graphical desktop session.", file=__import__("sys").stderr)
        return 1
    try:
        import cairo
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
    except (ImportError, ValueError) as exc:
        print(f"Rice Creator requires GTK3/PyGObject and python3-cairo: {exc}",
              file=__import__("sys").stderr)
        return 1

    from .hub import CSS as HUB_CSS, TOKENS

    extra_css = """
    #creator-sidebar { background: %(sidebar)s; border-right: 1px solid %(border)s; }
    #creator-sidebar list, #creator-sidebar listbox, #creator-sidebar listbox row,
    #creator-sidebar scrolledwindow, #creator-sidebar viewport { background: %(sidebar)s; }
    #creator-inspector { background: %(surface)s; border-left: 1px solid %(border)s; }
    list.creator-layer-list, list.creator-layer-list row {
      background: %(surface_alt)s; color: %(text)s; }
    list.creator-layer-list row label { color: %(text)s; }
    list.creator-layer-list row:hover { background: %(hover)s; }
    list.creator-layer-list row:selected { background: %(accent)s; }
    list.creator-layer-list row:selected label { color: #ffffff; }
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
    .creator-layer-selected { color: %(accent)s; font-weight: bold; }
    .creator-layer-hint { color: %(quiet)s; font-size: 11px; }
    """ % TOKENS

    class CreatorWindow(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title="Rice Creator · RiceBowl")
            self.set_name("ricebowl-window")
            self.set_default_size(1280, 820)
            self.set_size_request(820, 560)
            self.info: workspace.DraftInfo | None = None
            self.baseline: dict | None = None
            self.working: dict | None = None
            self.pending: dict[str, object] = {}
            self._panel_compact = False
            self._building = False
            self._busy = False
            self._interactive_session: creator_interactive.InteractivePreview | None = None
            self._interactive_closing = False
            self._render_generation = 0
            self._pixbuf = None
            self._preview_fit: tuple[int, int] | None = None
            self._capture_bytes: bytes | None = None
            self._capture_size: tuple[int, int] | None = None
            self._reference: creator_reference.ReferenceInfo | None = None
            self._comparison_views: dict[str, bytes] = {}
            self._mapping: dict | None = None
            self._mapping_checks: dict[str, object] = {}
            self._mapping_busy = False
            self._mapping_generation = 0
            self._regions: list[dict] = []
            self._region_report: dict | None = None
            self._region_measurements: list[dict] = []
            self._region_drag: tuple[float, float] | None = None
            self._region_drag_end: tuple[float, float] | None = None
            self._region_drag_display: tuple[int, int] | None = None
            self._region_drag_origin: tuple[float, float] = (0, 0)
            self._previous: workspace.DraftInfo | None = None
            self._history_error: str | None = None
            self._selected_layer: tuple[str, int] | None = None
            self._drag: tuple[tuple[str, int], float, float, int, int] | None = None
            self._drag_preview: tuple[int, int] | None = None
            self._last_viewport = None
            self._canvas_refresh_queued = False
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
            self.save_btn = self._button("Review & save…", self._save, primary=True)
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
            sidebar.pack_start(self._text("CONTINUE AN EXISTING RICE", "creator-rail-label"),
                               False, False, 8)
            self.open_installed_btn = self._button("Edit installed rice…", self._open_installed)
            self.import_pack_btn = self._button("Import RicePack…", self._import_pack)
            sidebar.pack_start(self.open_installed_btn, False, False, 0)
            sidebar.pack_start(self.import_pack_btn, False, False, 0)
            sidebar.pack_start(self._text("SAVED VERSIONS", "creator-rail-label"), False, False, 8)
            self.history_btn = self._button("Version history…", self._show_history)
            sidebar.pack_start(self.history_btn, False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sidebar.pack_start(scroll, True, True, 0)
            self.draft_list = Gtk.ListBox()
            self.draft_list.set_selection_mode(Gtk.SelectionMode.NONE)
            scroll.add(self.draft_list)
            sidebar.pack_start(self._text("Drafts are private. Saving never applies a rice.",
                                          "hub-hint", wrap=True), False, False, 4)
            sidebar.pack_start(self._text("WAYLAND HANDOFF", "creator-rail-label"),
                               False, False, 7)
            self.wayland_btn = Gtk.MenuButton(label="Install / switch…")
            self.wayland_btn.get_style_context().add_class("hub-action")
            self.wayland_btn.set_size_request(-1, 36)
            sidebar.pack_start(self.wayland_btn, False, False, 0)
            self.wayland_menu = Gtk.Popover.new(self.wayland_btn)
            wayland_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            wayland_actions.set_border_width(10)
            self.wayland_menu.add(wayland_actions)
            self.wayland_btn.set_popover(self.wayland_menu)
            self.install_btn = self._button("Install saved version…", self._install_draft)
            self.fork_btn = self._button("Fork as new rice ID", self._fork_draft)
            self.apply_btn = self._button("Apply in Wayland…", lambda _: self._live_action("apply"))
            self.restore_btn = self._button("Restore previous rice…",
                                            lambda _: self._live_action("restore"))
            for button in (self.install_btn, self.fork_btn, self.apply_btn, self.restore_btn):
                wayland_actions.pack_start(button, False, False, 0)
            self.install_btn.set_tooltip_text("Copy the validated saved version into your private rice collection")
            self.fork_btn.set_tooltip_text("Keep the full layout under a fresh ID when another version is installed")
            self.apply_btn.set_tooltip_text("Only in a running opt-in RiceBowl Wayland session")
            self.restore_btn.set_tooltip_text("Restore the previously active Wayland rice")
            sidebar.pack_start(self._text(
                "Live changes require an opt-in RiceBowl Wayland session and explicit confirmation.",
                "hub-hint", wrap=True), False, False, 4)

            content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            self.main.pack2(content, resize=True, shrink=False)
            preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            preview.set_name("creator-preview")
            preview.set_border_width(17)
            content.pack1(preview, resize=True, shrink=False)
            head = Gtk.Box(spacing=12)
            preview.pack_start(head, False, False, 0)
            head.pack_start(self._text("DESKTOP COMPOSITION", "creator-rail-label"), True, True, 0)
            self.geometry = Gtk.ComboBoxText()
            for key, label in (("1024,768,1", "1024 × 768"),
                               ("1366,768,1", "1366 × 768"),
                               ("1920,1080,1", "1920 × 1080"),
                               ("1366,768,1.25", "1366 × 768 · 125%")):
                self.geometry.append(key, label)
            self.geometry.set_active_id("1366,768,1")
            self.geometry.connect("changed", self._geometry_changed)
            head.pack_start(self.geometry, False, False, 0)
            self.interactive_btn = self._button("Try interactive Wayland window", self._interactive)
            self.interactive_btn.set_tooltip_text(
                "Try this saved version in a separate nested labwc window. "
                "The active rice and next login are unchanged; real system controls "
                "inside the test can still affect devices.")
            preview.pack_start(self.interactive_btn, False, False, 0)
            self.visual_stack = Gtk.Stack()
            self.visual_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.visual_switch = Gtk.StackSwitcher()
            self.visual_switch.set_stack(self.visual_stack)
            preview.pack_start(self.visual_switch, False, False, 0)
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.IN)
            preview.pack_start(frame, True, True, 0)
            frame.add(self.visual_stack)

            # This is a clearly labeled, editable *schematic*. Only the other
            # stack page displays pixels from the supervised real renderer.
            canvas_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            # Draw into an owner-local Cairo image and display via GdkPixbuf.
            # This avoids requiring the optional gi._gi_cairo foreign converter
            # for the GTK "draw" signal while retaining native GTK input.
            self.canvas = Gtk.EventBox()
            self.canvas.set_size_request(245, 235)
            self.canvas.set_hexpand(True)
            self.canvas.set_vexpand(True)
            self.canvas.set_can_focus(True)
            self.canvas.set_tooltip_text("Click a layer; drag or press arrow keys to move it")
            self.canvas_image = Gtk.Image()
            self.canvas.add(self.canvas_image)
            self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                   Gdk.EventMask.BUTTON_RELEASE_MASK |
                                   Gdk.EventMask.POINTER_MOTION_MASK |
                                   Gdk.EventMask.KEY_PRESS_MASK)
            self.canvas.connect("size-allocate", lambda *_: self._queue_canvas())
            self.canvas.connect("button-press-event", self._canvas_press)
            self.canvas.connect("motion-notify-event", self._canvas_motion)
            self.canvas.connect("button-release-event", self._canvas_release)
            self.canvas.connect("key-press-event", self._canvas_key)
            canvas_container.pack_start(self.canvas, True, True, 0)
            self.canvas_help = self._text(
                "SCHEMATIC · Select layers in the canvas or inspector. Drag to move; "
                "arrow keys nudge 8 px, Shift+arrows 1 px. Render for real shell pixels.",
                "creator-layer-hint", wrap=True)
            self.canvas_help.set_margin_start(12)
            self.canvas_help.set_margin_end(12)
            self.canvas_help.set_margin_bottom(12)
            canvas_container.pack_start(self.canvas_help, False, False, 0)
            self.visual_stack.add_titled(canvas_container, "canvas", "Edit layout")

            self.preview_scroller = Gtk.ScrolledWindow()
            self.preview_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.visual_stack.add_titled(self.preview_scroller, "native", "Native capture")
            reference_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            reference_bar.get_style_context().add_class("creator-section")
            preview.pack_start(reference_bar, False, False, 0)
            reference_header = Gtk.Box(spacing=7)
            reference_bar.pack_start(reference_header, False, False, 0)
            reference_header.pack_start(self._text("REFERENCE / VISUAL QA", "creator-rail-label"),
                                        True, True, 0)
            self.reference_import = self._button("Load PNG…", self._reference_choose)
            self.reference_clear = self._button("Unlink", self._reference_unlink)
            reference_header.pack_start(self.reference_import, False, False, 0)
            reference_header.pack_start(self.reference_clear, False, False, 0)
            self.reference_info = self._text("No reference selected. Screenshots stay private.",
                                             "creator-preview-note", wrap=True)
            reference_bar.pack_start(self.reference_info, False, False, 0)
            compare_row = Gtk.Box(spacing=7)
            reference_bar.pack_start(compare_row, False, False, 0)
            self.reference_mode = Gtk.ComboBoxText()
            for key, label in (("native", "Native"), ("reference", "Reference"),
                               ("wipe", "Split 50/50"), ("overlay", "Overlay 50/50"),
                               ("heatmap", "Difference"), ("regions", "Marked regions")):
                self.reference_mode.append(key, label)
            self.reference_mode.set_active_id("native")
            self.reference_mode.connect("changed", self._reference_view_changed)
            compare_row.pack_start(self.reference_mode, True, True, 0)
            self.compare_btn = self._button("Compare", self._compare_reference)
            compare_row.pack_start(self.compare_btn, False, False, 0)
            options = Gtk.Box(spacing=8)
            reference_bar.pack_start(options, False, False, 0)
            options.pack_start(self._text("Pixel cutoff", "creator-layer-hint"), False, False, 0)
            self.compare_threshold = Gtk.SpinButton.new_with_range(0, 255, 1)
            self.compare_threshold.set_value(24)
            self.compare_threshold.connect("value-changed", self._comparison_policy_changed)
            options.pack_start(self.compare_threshold, False, False, 0)
            options.pack_start(self._text("Raster tolerance", "creator-layer-hint"), False, False, 0)
            self.compare_tolerance = Gtk.ComboBoxText()
            for radius in (0, 1, 2):
                self.compare_tolerance.append(str(radius), f"{radius} px")
            self.compare_tolerance.set_active_id("1")
            self.compare_tolerance.connect("changed", self._comparison_policy_changed)
            options.pack_start(self.compare_tolerance, False, False, 0)
            self.reference_metrics = self._text(
                "Compare a real capture at the same resolution. Pixel changes are not fidelity scores.",
                "creator-preview-note", wrap=True)
            reference_bar.pack_start(self.reference_metrics, False, False, 0)
            mapping_expander = Gtk.Expander(label="REFERENCE MAPPING · REVIEW BEFORE EDITING")
            mapping_expander.set_expanded(False)
            reference_bar.pack_start(mapping_expander, False, False, 0)
            mapping_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            mapping_body.set_margin_top(8)
            mapping_body.set_margin_bottom(7)
            mapping_expander.add(mapping_body)
            mapping_controls = Gtk.Box(spacing=6)
            mapping_body.pack_start(mapping_controls, False, False, 0)
            self.mapping_analyze = self._button("Analyze offline", self._mapping_analyze)
            self.mapping_import = self._button("Import JSON…", self._mapping_import)
            self.mapping_export = self._button("Export hints…", self._mapping_export)
            for control in (self.mapping_analyze, self.mapping_import, self.mapping_export):
                mapping_controls.pack_start(control, True, True, 0)
            self.mapping_info = self._text(
                "Analyze a reference for panel and color hints, or import strictly validated "
                "AI proposals. Nothing changes until you approve and Save version.",
                "creator-preview-note", wrap=True)
            mapping_body.pack_start(self.mapping_info, False, False, 0)
            mapping_scroll = Gtk.ScrolledWindow()
            mapping_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            mapping_scroll.set_size_request(-1, 146)
            mapping_body.pack_start(mapping_scroll, False, False, 0)
            self.mapping_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            mapping_scroll.add(self.mapping_list)
            self.mapping_apply = self._button("Use checked hints in unsaved draft",
                                              self._mapping_apply, primary=True)
            mapping_body.pack_start(self.mapping_apply, False, False, 0)

            region_expander = Gtk.Expander(label="REGION QA · SELECT, CORRECT, RE-MEASURE")
            region_expander.set_expanded(False)
            reference_bar.pack_start(region_expander, False, False, 0)
            region_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            region_body.set_margin_top(8)
            region_body.set_margin_bottom(7)
            region_expander.add(region_body)
            region_body.pack_start(self._text(
                "Draw up to eight rectangles on the screenshot, or enter their source-pixel "
                "coordinates below. Measure → adjust the draft in the inspector → Save version "
                "→ Render → re-measure. Only pixel errors are measured, not fidelity.",
                "creator-preview-note", wrap=True), False, False, 0)
            self.region_draw = Gtk.ToggleButton(label="Draw region on screenshot")
            self.region_draw.set_tooltip_text(
                "Select the reference view, then click and drag. Esc cancels a drag.")
            self.region_draw.connect("toggled", self._region_draw_toggled)
            region_body.pack_start(self.region_draw, False, False, 0)
            region_form = Gtk.Grid(column_spacing=7, row_spacing=5)
            region_body.pack_start(region_form, False, False, 0)
            region_form.attach(self._text("Type", "creator-layer-hint"), 0, 0, 1, 1)
            self.region_kind = Gtk.ComboBoxText()
            for kind in creator_regions.KINDS:
                self.region_kind.append(kind, kind.title())
            self.region_kind.set_active_id("panel")
            region_form.attach(self.region_kind, 1, 0, 3, 1)
            self.region_coords = {}
            for index, (key, label, default) in enumerate(
                    (("x", "X", 0), ("y", "Y", 0),
                     ("width", "Width", 160), ("height", "Height", 48))):
                col = 0 if index % 2 == 0 else 2
                row = 1 + index // 2
                region_form.attach(self._text(label, "creator-layer-hint"), col, row, 1, 1)
                spin = Gtk.SpinButton.new_with_range(0 if key in ("x", "y") else 1,
                                                     8192, 1)
                spin.set_value(default)
                spin.set_width_chars(5)
                region_form.attach(spin, col + 1, row, 1, 1)
                self.region_coords[key] = spin
            region_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            region_body.pack_start(region_controls, False, False, 0)
            self.region_add = self._button("Mark rectangle", self._region_add)
            self.region_from_hints = self._button("Use detected", self._region_from_mapping)
            self.region_compare = self._button("Measure regions", self._region_compare)
            mark_row = Gtk.Box(spacing=6)
            for button in (self.region_add, self.region_from_hints):
                mark_row.pack_start(button, True, True, 0)
            region_controls.pack_start(mark_row, False, False, 0)
            region_controls.pack_start(self.region_compare, False, False, 0)
            self.region_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            region_body.pack_start(self.region_list, False, False, 0)
            self.region_summary = self._text("No regions marked.",
                                             "creator-preview-note", wrap=True)
            region_body.pack_start(self.region_summary, False, False, 0)
            self.region_cycle = self._text("Correction cycle: no measurements yet.",
                                           "creator-layer-hint", wrap=True)
            region_body.pack_start(self.region_cycle, False, False, 0)
            self.region_export = self._button("Export pixel history JSON…", self._region_export)
            region_body.pack_start(self.region_export, False, False, 0)
            self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            self.preview_box.set_halign(Gtk.Align.CENTER)
            self.preview_box.set_valign(Gtk.Align.CENTER)
            self.preview_scroller.add(self.preview_box)
            self.preview_image = Gtk.Image.new_from_icon_name("video-display", Gtk.IconSize.DIALOG)
            self.preview_overlay = Gtk.Overlay()
            self.preview_overlay.add(self.preview_image)
            self.region_surface = Gtk.DrawingArea()
            self.region_surface.set_can_focus(True)
            self.region_surface.set_tooltip_text("Drag to select a reference region when drawing is enabled")
            self.region_surface.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                           Gdk.EventMask.BUTTON_RELEASE_MASK |
                                           Gdk.EventMask.POINTER_MOTION_MASK |
                                           Gdk.EventMask.KEY_PRESS_MASK)
            self.region_surface.connect("draw", self._region_rubberband_draw)
            self.region_surface.connect("button-press-event", self._region_pointer_press)
            self.region_surface.connect("motion-notify-event", self._region_pointer_motion)
            self.region_surface.connect("button-release-event", self._region_pointer_release)
            self.region_surface.connect("key-press-event", self._region_pointer_key)
            self.preview_overlay.add_overlay(self.region_surface)
            self.preview_box.pack_start(self.preview_overlay, True, True, 0)
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
            self.status.set_line_wrap(True)
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
            self.open_installed_btn.set_sensitive(not self._busy)
            self.import_pack_btn.set_sensitive(not self._busy)
            self.save_btn.set_sensitive(selected and bool(self.pending) and not self._busy)
            self.render_btn.set_sensitive(selected and not self._busy)
            running = self._interactive_session is not None
            self.interactive_btn.set_label(
                "Close interactive Wayland window" if running else "Try interactive Wayland window")
            self.interactive_btn.set_sensitive(
                not self._interactive_closing and
                (running or (selected and not self.pending and not self._busy)))
            if running:
                self.interactive_btn.set_tooltip_text(
                    f"Separate test of {self._interactive_session.draft.recipe_id}; "
                    "close it before applying a rice to your main Wayland session.")
            else:
                self.interactive_btn.set_tooltip_text(
                    "Test a saved version in a separate nested Wayland window. "
                    "System settings inside the test may still affect real devices.")
            self.export_btn.set_sensitive(selected and not self._busy)
            self.undo_btn.set_sensitive(self._previous is not None and not self._busy)
            self.history_btn.set_sensitive(selected and not self._busy)
            can_install = selected and not self.pending and not self._busy
            live_session = bool(os.environ.get("WAYLAND_DISPLAY"))
            self.install_btn.set_sensitive(can_install)
            self.fork_btn.set_sensitive(can_install)
            self.apply_btn.set_sensitive(can_install and live_session and not running)
            self.restore_btn.set_sensitive(not self._busy and live_session and not self.pending)
            self.wayland_btn.set_sensitive(can_install or
                                           (live_session and not self.pending and not self._busy))
            self.reference_import.set_sensitive(selected and not self.pending and
                                                not self._busy and not self._mapping_busy)
            self.reference_clear.set_sensitive(self._reference is not None and
                                               not self._busy and not self._mapping_busy)
            self.compare_btn.set_sensitive(bool(self._reference and self._capture_bytes
                                                and self._capture_size == (
                                                    self._reference.width, self._reference.height)
                                                and not self.pending and not self._busy))
            self.reference_mode.set_sensitive(bool(self._comparison_views) and not self._busy)
            self.geometry.set_sensitive(not self._busy)
            can_map = bool(selected and self._reference and not self.pending
                           and not self._busy and not self._mapping_busy)
            self.mapping_analyze.set_sensitive(can_map)
            self.mapping_import.set_sensitive(can_map)
            self.mapping_export.set_sensitive(bool(self._mapping) and not self._busy
                                              and not self._mapping_busy and not self.pending)
            self.mapping_apply.set_sensitive(can_map and any(
                widget.get_active() for widget in self._mapping_checks.values()))
            self.region_add.set_sensitive(can_map and len(self._regions) < creator_regions.MAX_REGIONS)
            self.region_draw.set_sensitive(can_map and len(self._regions) < creator_regions.MAX_REGIONS)
            self.region_from_hints.set_sensitive(can_map and bool(
                self._mapping and self._mapping["regions"]))
            can_measure = bool(can_map and self._regions and self._capture_bytes and
                               self._capture_size == (self._reference.width, self._reference.height))
            self.region_compare.set_sensitive(can_measure)
            self.region_export.set_sensitive(bool(self._region_report and can_measure))

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
                self._status("Private schema-v11 draft created. Edit, save a version, then render.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not create draft: {exc}", error=True)

        def _open_installed(self, _button):
            if self._busy or not self._discard_pending():
                return
            try:
                options = workspace.installed_editable()
                if not options:
                    self._status("No editable installed rices. Import a schema-v10+ RicePack first.")
                    return
                dialog = Gtk.Dialog(title="Edit installed rice", transient_for=self, modal=True)
                dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
                dialog.add_button("Create editable copy", Gtk.ResponseType.OK)
                dialog.set_default_response(Gtk.ResponseType.CANCEL)
                body = dialog.get_content_area()
                body.set_border_width(16)
                body.set_spacing(10)
                body.pack_start(self._text(
                    "Select an installed rice. Its original stays installed and unchanged.",
                    "hub-hint", wrap=True), False, False, 0)
                choice = Gtk.ComboBoxText()
                for item in options:
                    choice.append(item["id"], f"{item['name']} · {item['id']} (v{item['schema_version']})")
                choice.set_active(0)
                body.pack_start(choice, False, False, 0)
                dialog.show_all()
                selected = choice.get_active_id() if dialog.run() == Gtk.ResponseType.OK else None
                dialog.destroy()
                if selected is None:
                    return
                expected = next(item["semantic_sha256"] for item in options
                                if item["id"] == selected)
                info = workspace.create_draft_from_installed(selected, expected_sha256=expected)
                self._load(info, reset_history=True)
                self._refresh_drafts()
                self._status(f"Editable copy {info.recipe_id} created. Original untouched; not applied.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, pack.PackError,
                    OSError, ValueError) as exc:
                self._status(f"Could not open installed rice: {exc}", error=True)

        def _import_pack(self, _button):
            if self._busy or not self._discard_pending():
                return
            chooser = Gtk.FileChooserDialog(title="Import a RicePack", transient_for=self,
                                            action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Inspect RicePack", Gtk.ResponseType.ACCEPT)
            file_filter = Gtk.FileFilter()
            file_filter.set_name("RicePack archives (*.ricepack)")
            file_filter.add_pattern("*.ricepack")
            chooser.add_filter(file_filter)
            response = chooser.run()
            source = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if source is None:
                return
            try:
                inspection = pack.inspect_pack(source)
                record = inspection["manifest"]["recipe"]
                if record["schema_version"] < 10:
                    raise workspace.WorkspaceError("Creator can edit schema-v10+ RicePacks only")
                if not self._confirm_handoff("Import this RicePack?",
                        f"{record['id']} · SHA-256 {record['semantic_sha256'][:12]}\n\n"
                        "Installs the verified data-only pack in your private collection, "
                        "then opens an editable copy with a new ID. Neither desktop is changed.",
                        "Import and edit"):
                    return
                result = pack.import_pack(source, expected_manifest=inspection["manifest"])
                info = workspace.create_draft_from_installed(
                    result["recipe_id"], expected_sha256=result["semantic_sha256"])
                self._load(info, reset_history=True)
                self._refresh_drafts()
                self._status(f"RicePack imported; editing {info.recipe_id}. Not applied.", success=True)
            except (pack.PackError, workspace.WorkspaceError, recipes.RecipeError,
                    OSError, ValueError) as exc:
                self._status(f"Import/edit failed: {exc}. If installed, use Edit installed rice…",
                             error=True)

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
            if report["recipe"]["schema_version"] not in (10, 11, 12):
                raise workspace.WorkspaceError("Creator edits validated schema-v10/v11/v12 recipes only")
            preserve_annotations = bool(not reset_history and self.info and self._reference and
                                        self.info.recipe_id == info.recipe_id)
            reference_sha = self._reference.sha256 if preserve_annotations else None
            old_regions = copy.deepcopy(self._regions) if preserve_annotations else []
            old_measurements = list(self._region_measurements) if preserve_annotations else []
            self._render_generation += 1
            self._mapping_reset()
            self._regions_reset()
            self.info, self.baseline, self.pending = info, report["recipe"], {}
            self.working = copy.deepcopy(self.baseline)
            self._panel_compact = False
            self._selected_layer, self._drag, self._drag_preview = None, None, None
            self._previous, self._history_error = None, None
            try:
                self._previous = workspace.previous_version(info)
            except workspace.WorkspaceError as exc:
                # Broken ancestry must not hide an otherwise valid current draft.
                self._history_error = str(exc)
            self._pixbuf = None
            self._preview_fit = None
            self._capture_bytes = None
            self._capture_size = None
            self._comparison_views = {}
            self.reference_mode.set_active_id("native")
            try:
                self._reference = creator_reference.selected(info.recipe_id)
                self._reference_label()
                if self._reference is not None:
                    self._region_limits()
                    self._comparison_views["reference"] = creator_reference.image_bytes(info.recipe_id)
            except creator_reference.ReferenceError as exc:
                self._reference = None
                self.reference_info.set_text(f"Reference unavailable: {exc}. Select a new PNG.")
            self.reference_metrics.set_text("Render this version for a fresh comparison.")
            self.preview_image.set_from_icon_name("video-display", Gtk.IconSize.DIALOG)
            self.preview_caption.set_text("Preview not rendered for this saved version.")
            if self._reference is not None and reference_sha == self._reference.sha256 and old_regions:
                self._regions = creator_regions.validate(
                    old_regions, size=(self._reference.width, self._reference.height))
                self._region_measurements = old_measurements
                self._region_refresh()
                self.preview_caption.set_text("Reference annotations retained; render this saved revision to measure again.")
            history_note = (f" · History unavailable: {self._history_error}"
                            if self._history_error else "")
            self.diff.set_text(f"Recipe: {info.recipe_id} · Schema v{report['recipe']['schema_version']} · SHA {info.semantic_sha256[:12]}{history_note}")
            self.inspector_context.set_text(f"Editing {info.name} · schema v{report['recipe']['schema_version']} · offline draft")
            self._build_inspector()
            self._queue_canvas()
            self._actions()

        def _build_inspector(self):
            for child in self.inspector.get_children()[2:]:
                self.inspector.remove(child)
            assert self.baseline is not None
            self._building = True
            self._build_layer_inspector()
            self._build_wallpaper_inspector()
            self._build_component_inspector()
            self._build_style_inspector()
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
                    current = _get_field(self.working, path)
                    if kind == "text":
                        widget = Gtk.Entry()
                        widget.set_max_length(60)
                        widget.set_text(current)
                        widget.connect("changed", lambda w, p=path: self._change(p, w.get_text()))
                    elif kind in ("choice", "choice-int"):
                        widget = Gtk.ComboBoxText()
                        for option in _choice_options(path, options,
                                                      self.baseline["schema_version"]):
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
            self.panel_mode = Gtk.ComboBoxText()
            self.panel_mode.append("wide", "Wide layout · standard screens")
            self.panel_mode.append("compact", "Compact layout · narrow screens")
            self.panel_mode.set_active_id("wide")
            self.panel_mode.connect("scroll-event", lambda *_: True)
            self.panel_mode.connect("changed", self._panel_mode_changed)
            self.layout_box.pack_start(self.panel_mode, False, False, 0)
            self.layout_lanes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            self.layout_box.pack_start(self.layout_lanes, False, False, 0)
            self._refresh_layout()
            self.inspector.show_all()
            self._building = False
            self._component_selected(self.component_choice)

        def _build_wallpaper_inspector(self):
            expander = Gtk.Expander(label="Wallpaper library · local PNG assets")
            expander.set_expanded(True)
            self.inspector.pack_start(expander, False, False, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            body.set_margin_top(10)
            body.set_margin_bottom(12)
            expander.add(body)
            body.pack_start(self._text(
                "Choose an included wallpaper or a verified private PNG. "
                "Import never changes the current desktop.",
                "creator-layer-hint", wrap=True), False, False, 0)
            selection = Gtk.Box(spacing=6)
            self.wallpaper_choice = Gtk.ComboBoxText()
            self.wallpaper_choice.set_hexpand(True)
            self.wallpaper_choice.set_tooltip_text("Selected draft wallpaper")
            self.wallpaper_choice.connect("changed", self._wallpaper_selected)
            # Scrolling the long inspector must never accidentally change a rice.
            self.wallpaper_choice.connect("scroll-event", lambda *_: True)
            selection.pack_start(self.wallpaper_choice, True, True, 0)
            selection.pack_start(self._button("Refresh", lambda _b:
                self._refresh_asset_list()), False, False, 0)
            body.pack_start(selection, False, False, 0)
            self.wallpaper_image = Gtk.Image()
            self.wallpaper_image.set_size_request(-1, 92)
            self.wallpaper_image.set_halign(Gtk.Align.CENTER)
            body.pack_start(self.wallpaper_image, False, False, 0)
            self.wallpaper_details = self._text("", "creator-layer-hint", wrap=True)
            self.wallpaper_details.set_selectable(True)
            body.pack_start(self.wallpaper_details, False, False, 0)

            body.pack_start(self._text("IMPORT ONE PNG · maximum 2 MiB, 4096 px, RGB/RGBA",
                                       "creator-rail-label"), False, False, 0)
            grid = Gtk.Grid(row_spacing=6, column_spacing=8)
            body.pack_start(grid, False, False, 0)
            self.asset_label = Gtk.Entry()
            self.asset_label.set_max_length(60)
            self.asset_label.set_placeholder_text("e.g. Original summer hills")
            self.asset_author = Gtk.Entry()
            self.asset_author.set_max_length(80)
            self.asset_author.set_placeholder_text("Name or team (optional)")
            self.asset_source = Gtk.Entry()
            self.asset_source.set_max_length(256)
            self.asset_source.set_placeholder_text("Public source reference (optional)")
            self.asset_license = Gtk.ComboBoxText()
            for key in ("unspecified", "CC0-1.0", "CC-BY-4.0", "MIT",
                        "OFL-1.1", "Apache-2.0", "custom"):
                self.asset_license.append(key, key)
            self.asset_license.set_active_id("unspecified")
            self.asset_origin = Gtk.ComboBoxText()
            for key in ("unspecified", "original", "ai-assisted", "adapted"):
                self.asset_origin.append(key, key)
            self.asset_origin.set_active_id("unspecified")
            for row, (title, field) in enumerate((("Image name", self.asset_label),
                                                   ("Author", self.asset_author),
                                                   ("License", self.asset_license),
                                                   ("Origin", self.asset_origin),
                                                   ("Source", self.asset_source))):
                label = self._text(title, "creator-layer-hint")
                label.set_text("_" + title)
                label.set_use_underline(True)
                label.set_mnemonic_widget(field)
                field.set_hexpand(True)
                grid.attach(label, 0, row, 1, 1)
                grid.attach(field, 1, row, 1, 1)
            body.pack_start(self._text(
                "Attribution is declared by you, not license-verified. "
                "Keep rights and source information accurate.",
                "creator-layer-hint", wrap=True), False, False, 0)
            body.pack_start(self._button("Import PNG…", self._import_wallpaper),
                            False, False, 0)
            self._refresh_asset_list()

        def _refresh_asset_list(self, selected_id=None):
            if self.working is None:
                return
            chosen = (selected_id or self.working['desktop']['wallpaper'])
            previous = self._building
            self._building = True
            self.wallpaper_choice.remove_all()
            for asset_id in sorted(recipes.WALLPAPERS):
                self.wallpaper_choice.append(asset_id,
                                             "Included · " + asset_id.replace('-', ' ').title())
            try:
                imported = creator_assets.catalog()
            except (assets.AssetError, OSError) as exc:
                imported = []
                self._status(f"Wallpaper library unavailable: {exc}", error=True)
            for row in imported:
                self.wallpaper_choice.append(row.asset_id, "Private · " + row.label)
            if chosen not in recipes.WALLPAPERS and not any(row.asset_id == chosen for row in imported):
                self.wallpaper_choice.append(chosen, "Not listed / unavailable · " + chosen[:18])
            self.wallpaper_choice.set_active_id(chosen)
            self._building = previous
            self._show_wallpaper(chosen)

        def _show_wallpaper(self, selected):
            if not selected:
                return
            try:
                if assets.ASSET_ID.fullmatch(selected):
                    row = creator_assets.entry(selected)
                    path = assets.read(selected)[0]
                    declared = row.provenance
                    size_label = (f"{row.size} B" if row.size < 1024 else
                                  f"{row.size / 1024:.1f} KiB")
                    info = (f"{row.label} · {row.width}×{row.height} · "
                            f"{size_label}\n"
                            f"{declared['license']} · {declared['origin']} · "
                            f"by {declared['author'] or 'unknown'}\n"
                            f"Source: {declared['source_reference'] or 'not declared'}")
                else:
                    if selected not in recipes.WALLPAPERS:
                        raise assets.AssetError("Unknown bundled wallpaper")
                    path = (Path(__file__).resolve().parents[1] / "assets" / "wallpapers" /
                            (selected + ".jpg"))
                    info = "Included RiceBowl artwork · available in the standard installation"
                thumbnail = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 310, 148, True)
                self.wallpaper_image.set_from_pixbuf(thumbnail)
                self.wallpaper_details.set_text(info)
            except (assets.AssetError, GLib.Error, OSError, ValueError) as exc:
                self.wallpaper_image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
                self.wallpaper_details.set_text(f"Image unavailable: {exc}. Choose a different wallpaper.")

        def _wallpaper_selected(self, widget):
            if self._building or self.working is None or self._busy:
                return
            selected = widget.get_active_id()
            if selected is None:
                return
            try:
                if assets.ASSET_ID.fullmatch(selected):
                    creator_assets.entry(selected)
                elif selected not in recipes.WALLPAPERS:
                    raise assets.AssetError("Unknown wallpaper")
                self._change("/desktop/wallpaper", selected)
                self._show_wallpaper(selected)
            except (assets.AssetError, OSError) as exc:
                self._status(f"Cannot select wallpaper: {exc}", error=True)

        def _import_wallpaper(self, _button):
            if self.working is None or self._busy:
                return
            declaration = {"author": self.asset_author.get_text(),
                           "license": self.asset_license.get_active_id(),
                           "origin": self.asset_origin.get_active_id(),
                           "source_reference": self.asset_source.get_text()}
            # Validate before opening the picker; an invalid declaration must
            # never leave a newly installed asset with incomplete attribution.
            try:
                from .de import pack
                pack._provenance(declaration)
                label = creator_assets._label(self.asset_label.get_text())
            except (ValueError, TypeError, assets.AssetError) as exc:
                self._status(f"Check image name / attribution: {exc}", error=True)
                return
            chooser = Gtk.FileChooserDialog(title="Import a local PNG wallpaper", transient_for=self,
                                            action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Import PNG", Gtk.ResponseType.ACCEPT)
            restriction = Gtk.FileFilter()
            restriction.set_name("PNG images (*.png)")
            restriction.add_pattern("*.png")
            chooser.add_filter(restriction)
            response = chooser.run()
            source = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if source is None:
                return
            try:
                row = creator_assets.import_wallpaper(source, label=label, provenance=declaration)
                self._refresh_asset_list(row.asset_id)
                self._change("/desktop/wallpaper", row.asset_id)
                self._status("Verified PNG imported privately; save a new draft version to use it.",
                             success=True)
            except (assets.AssetError, OSError, ValueError) as exc:
                self._status(f"Cannot import PNG: {exc}. Use an owner-controlled RGB/RGBA PNG.",
                             error=True)

        def _build_component_inspector(self):
            expander = Gtk.Expander(label="Component library · real Linux bindings")
            expander.set_expanded(True)
            self.inspector.pack_start(expander, False, False, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            body.set_margin_top(10)
            body.set_margin_bottom(12)
            expander.add(body)
            body.pack_start(self._text(
                "Each component has a stable ID, an approved status or action binding "
                "and a short label. Existing desktop and panel references stay checked.",
                "creator-layer-hint", wrap=True), False, False, 0)
            self.component_choice = Gtk.ComboBoxText()
            self.component_choice.connect("changed", self._component_selected)
            self.component_choice.connect("scroll-event", lambda *_: True)
            body.pack_start(self.component_choice, False, False, 0)
            grid = Gtk.Grid(row_spacing=6, column_spacing=8)
            body.pack_start(grid, False, False, 0)
            self.component_id = Gtk.Entry()
            self.component_id.set_max_length(24)
            self.component_id.set_placeholder_text("e.g. desk-battery")
            self.component_label = Gtk.Entry()
            self.component_label.set_max_length(16)
            self.component_label.set_placeholder_text("Visible label")
            self.component_role = Gtk.ComboBoxText()
            self.component_role.append("status", "Live status")
            self.component_role.append("action", "Verified action")
            self.component_role.connect("changed", self._component_role_changed)
            self.component_binding = Gtk.ComboBoxText()
            self.component_role.connect("scroll-event", lambda *_: True)
            self.component_binding.connect("scroll-event", lambda *_: True)
            for index, (caption, field) in enumerate((
                    ("Component ID", self.component_id),
                    ("Visible label", self.component_label),
                    ("Role", self.component_role),
                    ("Linux binding", self.component_binding))):
                label = self._text("_" + caption, "creator-layer-hint")
                label.set_use_underline(True)
                label.set_mnemonic_widget(field)
                field.set_hexpand(True)
                grid.attach(label, 0, index, 1, 1)
                grid.attach(field, 1, index, 1, 1)
            self.component_uses = self._text("", "creator-layer-hint", wrap=True)
            body.pack_start(self.component_uses, False, False, 0)
            actions = Gtk.Box(spacing=6)
            self.component_add = self._button("Add", lambda _b: self._component_edit("add"))
            self.component_update = self._button("Update", lambda _b: self._component_edit("update"))
            self.component_remove = self._button(
                "Remove unused", lambda _b: self._component_edit("remove"))
            for button in (self.component_add, self.component_update, self.component_remove):
                actions.pack_start(button, True, True, 0)
            body.pack_start(actions, False, False, 0)
            self._refresh_component_library()

        def _build_style_inspector(self):
            expander = Gtk.Expander(label="Visual asset library · fonts and icon artwork")
            expander.set_expanded(True)
            self.inspector.pack_start(expander, False, False, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            body.set_margin_top(10)
            body.set_margin_bottom(12)
            expander.add(body)
            if self.working["schema_version"] == 10:
                body.pack_start(self._text(
                    "This saved draft uses schema v10. Upgrade to v11 in a new private "
                    "version before importing icon or font artwork.",
                    "creator-layer-hint", wrap=True), False, False, 0)
                body.pack_start(self._button("Upgrade saved draft to v11", self._upgrade_artwork),
                                False, False, 0)
                return
            body.pack_start(self._text(
                "Icons are original/licensed 48×48 RGBA PNGs. Fonts are TrueType "
                "(.ttf, up to 1 MiB). Choose an installed face or import a file, "
                "and declare its redistribution license. Neither changes system fonts. "
                "Save a version before rendering or exporting.",
                "creator-layer-hint", wrap=True), False, False, 0)
            self.style_choices = {}
            for key, label in (("font", "Text font"),
                               ("applications", "Applications icon"),
                               ("terminal", "Terminal icon"),
                               ("lock", "Lock icon")):
                field = Gtk.Box(spacing=6)
                choice = Gtk.ComboBoxText()
                choice.set_hexpand(True)
                choice.connect("scroll-event", lambda *_: True)
                choice.connect("changed", lambda widget, field_key=key:
                               self._style_selected(field_key, widget))
                self.style_choices[key] = choice
                field.pack_start(choice, True, True, 0)
                button = self._button("Import…", lambda _b, field_key=key:
                                      self._import_style_asset(field_key))
                field.pack_start(button, False, False, 0)
                body.pack_start(self._text(label, "creator-rail-label"), False, False, 0)
                body.pack_start(field, False, False, 0)
                if key == "font":
                    installed = self._button("Choose installed font…", self._choose_installed_font)
                    installed.set_tooltip_text(
                        "Browse local TrueType faces; copy the selected face privately after "
                        "checking its license. Does not change the active desktop.")
                    body.pack_start(installed, False, False, 0)
            self.style_details = self._text("", "creator-layer-hint", wrap=True)
            self.style_details.set_selectable(True)
            body.pack_start(self.style_details, False, False, 0)
            self.style_preview = Gtk.Image()
            self.style_preview.set_halign(Gtk.Align.START)
            body.pack_start(self.style_preview, False, False, 0)
            body.pack_start(self._text("ATTRIBUTION FOR NEW FONT / ICON",
                                       "creator-rail-label"), False, False, 0)
            grid = Gtk.Grid(row_spacing=5, column_spacing=8)
            body.pack_start(grid, False, False, 0)
            self.style_label = Gtk.Entry()
            self.style_label.set_max_length(60)
            self.style_label.set_placeholder_text("Artwork or font name")
            self.style_author = Gtk.Entry()
            self.style_author.set_max_length(80)
            self.style_source = Gtk.Entry()
            self.style_source.set_max_length(256)
            self.style_license = Gtk.ComboBoxText()
            for value in ("unspecified", "CC0-1.0", "CC-BY-4.0", "MIT",
                          "OFL-1.1", "Apache-2.0", "custom"):
                self.style_license.append(value, value)
            self.style_license.set_active_id("unspecified")
            self.style_origin = Gtk.ComboBoxText()
            for value in ("unspecified", "original", "ai-assisted", "adapted"):
                self.style_origin.append(value, value)
            self.style_origin.set_active_id("unspecified")
            for index, (label, widget) in enumerate((
                    ("Name", self.style_label), ("Author", self.style_author),
                    ("License", self.style_license), ("Origin", self.style_origin),
                    ("Source", self.style_source))):
                caption = self._text("_" + label, "creator-layer-hint")
                caption.set_use_underline(True)
                caption.set_mnemonic_widget(widget)
                grid.attach(caption, 0, index, 1, 1)
                grid.attach(widget, 1, index, 1, 1)
            self._refresh_style_choices()

        def _refresh_style_choices(self):
            if self.working is None or self.working["schema_version"] < 11:
                return
            prior = self._building
            self._building = True
            for field, choice in self.style_choices.items():
                kind = "font" if field == "font" else "icon"
                current = (self.working["artwork"]["font"] if field == "font" else
                           self.working["artwork"]["icons"][field])
                choice.remove_all()
                choice.append("builtin", "RicePlate built-in")
                known = {"builtin"}
                if field == "font" and self.working["schema_version"] >= 12:
                    choice.append("builtin-luna-ui", "Luna UI · Liberation Sans (OFL)")
                    known.add("builtin-luna-ui")
                if field != "font" and self.working["schema_version"] >= 12:
                    choice.append("builtin-luna", "Luna originals · built-in")
                    known.add("builtin-luna")
                for item in style_assets.list_assets(kind):
                    known.add(item.identifier)
                    choice.append(item.identifier, item.label + " · " + item.identifier[:13])
                if current not in known:
                    choice.append(current, "Missing private asset · " + current[:13])
                choice.set_active_id(current)
            self._building = prior
            self._refresh_style_preview()

        def _refresh_style_preview(self):
            if self.working is None or self.working["schema_version"] < 11:
                return
            fields = []
            illustration = None
            for key in ("font", *style_assets.ICON_ACTIONS):
                identifier = (self.working["artwork"]["font"] if key == "font" else
                              self.working["artwork"]["icons"][key])
                if identifier in ("builtin", "builtin-luna", "builtin-luna-ui"):
                    continue
                try:
                    entry = style_assets.entry(identifier)
                    fields.append(f"{key}: {entry.label} · {entry.provenance['license']} "
                                  f"· {entry.provenance['author'] or 'author unspecified'}")
                    if illustration is None and key != "font":
                        image = GdkPixbuf.PixbufLoader.new_with_type("png")
                        image.write(style_assets.read(identifier))
                        image.close()
                        illustration = image.get_pixbuf()
                except (style_assets.StyleAssetError, ValueError, GLib.Error, OSError):
                    fields.append(f"{key}: missing or damaged private asset · {identifier[:13]}")
            self.style_details.set_text("\n".join(fields) if fields else
                "Built-in font and icons selected. Private assets are hashed and included "
                "in RicePack v4 only when referenced.")
            self.style_preview.set_from_pixbuf(illustration)

        def _style_selected(self, field, widget):
            if self._building or self._busy or self.working is None:
                return
            selected = widget.get_active_id()
            if selected is None:
                return
            try:
                if selected not in ("builtin", "builtin-luna", "builtin-luna-ui"):
                    item = style_assets.entry(selected)
                    if item.kind != ("font" if field == "font" else "icon"):
                        raise style_assets.StyleAssetError("Wrong asset type")
                pointer = ("/artwork/font" if field == "font" else
                           "/artwork/icons/" + field)
                self._change(pointer, selected)
                self._refresh_style_preview()
            except (style_assets.StyleAssetError, OSError) as exc:
                self._status(f"Cannot choose visual asset: {exc}", error=True)

        def _import_style_asset(self, field):
            if self._busy or self.working is None:
                return
            kind = "font" if field == "font" else "icon"
            try:
                label, declared = self._style_import_declaration()
            except (ValueError, TypeError) as exc:
                self._status(f"Check visual asset attribution: {exc}", error=True)
                return
            chooser = Gtk.FileChooserDialog(
                title="Import private font" if kind == "font" else "Import private icon PNG",
                transient_for=self, action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Import", Gtk.ResponseType.ACCEPT)
            restriction = Gtk.FileFilter()
            restriction.set_name("TrueType (*.ttf)" if kind == "font" else "RGBA PNG (*.png)")
            restriction.add_pattern("*.ttf" if kind == "font" else "*.png")
            chooser.add_filter(restriction)
            response = chooser.run()
            source = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if source is None:
                return
            try:
                item = style_assets.import_asset(source, kind=kind, label=label,
                                                 provenance=declared)
                self._refresh_style_choices()
                self.style_choices[field].set_active_id(item.identifier)
                self._status(f"Imported private {kind} · save version to use it.", success=True)
            except (style_assets.StyleAssetError, OSError, ValueError) as exc:
                self._status(f"Visual asset import rejected: {exc}", error=True)

        def _style_import_declaration(self):
            from .de import pack
            declared = {"author": self.style_author.get_text(),
                        "license": self.style_license.get_active_id(),
                        "origin": self.style_origin.get_active_id(),
                        "source_reference": self.style_source.get_text()}
            pack._provenance(declared)
            label = self.style_label.get_text().strip()
            if not label:
                raise style_assets.StyleAssetError("Name the asset before importing")
            return label, declared

        def _choose_installed_font(self, _button):
            if self._busy or self.working is None:
                return
            chooser = Gtk.FontChooserDialog(title="Choose an installed TrueType font",
                                            transient_for=self)
            chooser.set_preview_text("RiceBowl · ÄÖÜ é € 123")
            result = chooser.run()
            selected = chooser.get_font_face() if result == Gtk.ResponseType.OK else None
            family = selected.get_family().get_name() if selected is not None else None
            style = selected.get_face_name() if selected is not None else None
            chooser.destroy()
            if family is None or style is None:
                return
            if not self.style_label.get_text().strip():
                suggestion = "".join(ch for ch in f"{family} {style}"
                                     if ch.isascii() and (ch.isalnum() or ch in " ._+-"))
                self.style_label.set_text(suggestion[:60].strip() or "Installed font")
            try:
                label, declared = self._style_import_declaration()
                if declared["license"] == "unspecified":
                    raise style_assets.StyleAssetError(
                        "Declare the verified font redistribution license before copying")
            except (ValueError, TypeError) as exc:
                self._status(f"Check font name / attribution: {exc}", error=True)
                return
            self._busy = True
            self._actions()
            self._status("Checking installed font and importing private copy…")

            def work():
                item, error = None, None
                try:
                    face = fonts.choose_font(family, style)
                    item = style_assets.import_asset(face.path, kind="font", label=label,
                                                     provenance=declared)
                except (fonts.FontCatalogError, style_assets.StyleAssetError,
                        OSError, ValueError) as exc:
                    error = str(exc)
                GLib.idle_add(done, item, error)

            def done(item, error):
                self._busy = False
                self._actions()
                if error:
                    self._status(f"Installed font import rejected: {error}", error=True)
                else:
                    self._refresh_style_choices()
                    self.style_choices["font"].set_active_id(item.identifier)
                    self._status("Installed font imported privately · save version to use it.",
                                 success=True)
                return False

            threading.Thread(target=work, name="ricebowl-font-import", daemon=True).start()

        def _upgrade_artwork(self, _button):
            if self._busy or self.info is None or not self._commit_pending():
                return
            try:
                previous = self.info
                updated = workspace.upgrade_to_artwork(previous)
                self._load(updated)
                self._refresh_drafts()
                self._status("Created new v11 version. Previous v10 draft remains intact.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not upgrade draft safely: {exc}", error=True)

        def _component_role_changed(self, _widget):
            role = self.component_role.get_active_id()
            current = self.component_binding.get_active_id()
            self.component_binding.remove_all()
            bindings = (sorted(recipes.COMPONENT_STATUS_BINDINGS) if role == "status" else
                        sorted(recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS) if role == "action"
                        else [])
            for key in bindings:
                self.component_binding.append(key, key.replace("-", " ").title())
            if bindings:
                self.component_binding.set_active_id(current if current in bindings else bindings[0])

        def _refresh_component_library(self, selected=None):
            if self.working is None:
                return
            previous = self._building
            self._building = True
            self.component_choice.remove_all()
            self.component_choice.append("new", "New component…")
            for component in self.working["components"]:
                self.component_choice.append(component["id"],
                                             component["label"] + " · " + component["id"])
            self.component_choice.set_active_id(selected if selected in {
                component["id"] for component in self.working["components"]} else "new")
            self._building = previous
            self._component_selected(self.component_choice)

        def _component_selected(self, widget):
            if self._building or self.working is None:
                return
            selected = widget.get_active_id()
            row = next((item for item in self.working["components"]
                        if item["id"] == selected), None)
            previous = self._building
            self._building = True
            self.component_id.set_text(row["id"] if row else "")
            self.component_id.set_sensitive(row is None)
            self.component_label.set_text(row["label"] if row else "")
            self.component_role.set_active_id(row["role"] if row else "status")
            self._component_role_changed(self.component_role)
            if row:
                self.component_binding.set_active_id(row["binding"])
            self._building = previous
            in_use = creator_structure.component_uses(self.working, selected) if row else []
            self.component_uses.set_text(
                "Used at: " + ", ".join(in_use[:3]) + ("…" if len(in_use) > 3 else "")
                if in_use else "Unused component · may be removed" if row else
                "Add a stable ID, then place it in the panel or on the desktop.")
            self.component_add.set_sensitive(row is None and not self._busy)
            self.component_update.set_sensitive(row is not None and not self._busy)
            self.component_remove.set_sensitive(row is not None and not in_use and
                                                len(self.working["components"]) > 1 and
                                                not self._busy)

        def _component_edit(self, action):
            if self.working is None or self._busy:
                return
            selected = self.component_choice.get_active_id()
            try:
                definition = ({"id": self.component_id.get_text().strip(),
                               "role": self.component_role.get_active_id(),
                               "binding": self.component_binding.get_active_id(),
                               "label": self.component_label.get_text().strip()}
                              if action != "remove" else None)
                changed = creator_structure.edit_component(
                    self.working, action, definition, identifier=selected)
                self._change("/components", changed)
                focus = definition["id"] if definition else "new"
                self._refresh_component_library(focus)
                self._refresh_layer_choices()
                self._refresh_layer_list()
                self._refresh_layout()
            except creator_structure.StructureError as exc:
                self._status(f"Cannot {action} component: {exc}", error=True)

        def _build_layer_inspector(self):
            expander = Gtk.Expander(label="Desktop layers · visual editor")
            expander.set_expanded(True)
            self.inspector.pack_start(expander, False, False, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            body.set_margin_top(10)
            body.set_margin_bottom(10)
            expander.add(body)
            body.pack_start(self._text("Choose a layer or click it on the canvas.",
                                       "creator-layer-hint", wrap=True), False, False, 0)
            self.layer_list = Gtk.ListBox()
            self.layer_list.get_style_context().add_class('creator-layer-list')
            self.layer_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.layer_list.connect("row-selected", self._layer_selected)
            body.pack_start(self.layer_list, False, False, 0)

            add_row = Gtk.Box(spacing=6)
            self.layer_choices = Gtk.ComboBoxText()
            self._refresh_layer_choices()
            add_row.pack_start(self.layer_choices, True, True, 0)
            add = self._button("Add", self._add_layer)
            add_row.pack_start(add, False, False, 0)
            body.pack_start(add_row, False, False, 0)

            self.layer_detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            body.pack_start(self.layer_detail, False, False, 0)
            self._refresh_layer_list()

        def _refresh_layer_choices(self):
            selected = self.layer_choices.get_active_id()
            self.layer_choices.remove_all()
            for key, title in (("text", "Static text"), ("clock", "Clock"),
                               ("date", "Date"), ("system", "System info")):
                self.layer_choices.append(key, title)
            for component in self.working.get("components", []):
                if component["role"] in ("status", "action"):
                    self.layer_choices.append("component:" + component["id"],
                                              component["role"].capitalize() + ": " + component["label"])
            for action, label in (("applications", "Applications"),
                                  ("terminal", "Terminal"), ("lock", "Lock")):
                self.layer_choices.append("icon:" + action, "Shortcut: " + label)
            if not self.layer_choices.set_active_id(selected):
                self.layer_choices.set_active(0)

        def _layer_keys(self):
            assert self.working is not None
            return ([('widget', n) for n in range(len(self.working['composition']['widgets']))] +
                    [('icon', n) for n in range(len(self.working['desktop']['icons']))] +
                    [('region', 0)])

        def _refresh_layer_list(self):
            # Keep GTK's own ListBox navigation and focused-row semantics.
            previous = self._building
            self._building = True
            for row in self.layer_list.get_children():
                self.layer_list.remove(row)
            self._layer_order = self._layer_keys()
            for key in self._layer_order:
                label = self._text(layout_engine.layer_label(self.working, *key), "hub-body")
                label.set_margin_top(5)
                label.set_margin_bottom(5)
                label.set_margin_start(5)
                self.layer_list.add(label)
            if self._selected_layer not in self._layer_order:
                self._selected_layer = self._layer_order[0] if self._layer_order else None
            if self._selected_layer is not None:
                self.layer_list.select_row(self.layer_list.get_row_at_index(
                    self._layer_order.index(self._selected_layer)))
            self._building = previous
            self.layer_list.show_all()
            self._render_layer_details()
            self._queue_canvas()

        def _layer_selected(self, _listbox, row):
            if self._building or row is None:
                return
            self._selected_layer = self._layer_order[row.get_index()]
            self._render_layer_details()
            self._queue_canvas()

        def _render_layer_details(self):
            for child in self.layer_detail.get_children():
                self.layer_detail.remove(child)
            if self._selected_layer is None or self.working is None:
                return
            layer, index = self._selected_layer
            manifest = self.working
            item = (manifest['composition']['window_region'] if layer == 'region' else
                    manifest['composition']['widgets'][index] if layer == 'widget' else
                    manifest['desktop']['icons'][index])
            self.layer_detail.pack_start(self._text(
                layout_engine.layer_label(manifest, layer, index), 'creator-layer-selected',
                wrap=True), False, False, 0)
            grid = Gtk.Grid(row_spacing=6, column_spacing=6)
            self.layer_detail.pack_start(grid, False, False, 0)
            for row, key in enumerate(('x', 'y', 'width', 'height') if layer == 'region'
                                      else ('x', 'y')):
                label = self._text(key.upper() + (' (%)' if layer == 'region' else ' (px)'),
                                   'creator-layer-hint')
                upper = (100 if layer == 'region' else
                         4096 if layer == 'icon' else 16384)
                minimum = (1 if layer == 'region' and key in ('width', 'height') else
                           72 if layer == 'icon' and key == 'y' else 0)
                field = Gtk.SpinButton.new_with_range(minimum, upper, 1)
                field.set_value(item[key])
                field.connect('value-changed', lambda w, name=key:
                              self._edit_layer({name: w.get_value_as_int()}))
                label.set_mnemonic_widget(field)
                grid.attach(label, 0, row, 1, 1)
                grid.attach(field, 1, row, 1, 1)
            if layer == 'widget' and item['kind'] == 'text':
                field = Gtk.Entry()
                field.set_max_length(22)
                field.set_text(item['text'])
                field.set_tooltip_text('1–22 Latin letters, digits or basic punctuation')
                field.connect('activate', lambda w: self._edit_layer({'text': w.get_text()}))
                field.connect('focus-out-event', lambda w, _e:
                              (self._edit_layer({'text': w.get_text()}), False)[1])
                self.layer_detail.pack_start(self._text('Static text · Enter to commit',
                                                         'creator-layer-hint'), False, False, 0)
                self.layer_detail.pack_start(field, False, False, 0)
            if layer == 'icon':
                field = Gtk.Entry()
                field.set_max_length(12)
                field.set_text(item['label'])
                field.set_tooltip_text('1–12 Latin letters, digits or basic punctuation')
                field.connect('activate', lambda w: self._edit_layer({'label': w.get_text()}))
                field.connect('focus-out-event', lambda w, _e:
                              (self._edit_layer({'label': w.get_text()}), False)[1])
                self.layer_detail.pack_start(self._text('Shortcut label · Enter to commit',
                                                         'creator-layer-hint'), False, False, 0)
                self.layer_detail.pack_start(field, False, False, 0)
                choice = Gtk.ComboBoxText()
                for action in sorted(recipes.ICON_ACTIONS):
                    choice.append(action, action.title())
                choice.set_active_id(item['action'])
                choice.connect('changed', lambda w:
                               self._edit_layer({'action': w.get_active_id()})
                               if w.get_active_id() else None)
                self.layer_detail.pack_start(choice, False, False, 0)
            if layer == 'widget':
                compact = Gtk.CheckButton(label='Hide on compact displays')
                compact.set_active(item['id'] in manifest['composition']['compact_hide_widgets'])
                compact.connect('toggled', lambda w: self._set_compact_hidden(w.get_active()))
                self.layer_detail.pack_start(compact, False, False, 0)
            if layer != 'region':
                remove = self._button('Remove selected layer', self._remove_layer)
                remove.set_sensitive(not (layer == 'icon' and
                                          len(manifest['desktop']['icons']) == 1))
                self.layer_detail.pack_start(remove, False, False, 0)
            self.layer_detail.show_all()

        def _apply_layout(self, updated):
            assert self.working is not None
            paths = ('/composition/widgets', '/composition/window_region',
                     '/composition/compact_hide_widgets', '/desktop/icons')
            for path in paths:
                value = _get_field(updated, path)
                if value != _get_field(self.working, path):
                    self._change(path, value)

        def _edit_layer(self, fields):
            if self._selected_layer is None or self._busy or self.working is None:
                return
            try:
                updated = layout_engine.edit_layer(self.working, *self._selected_layer, fields)
                self._apply_layout(updated)
                self._status('Layer updated · Save version to persist.', success=True)
            except layout_engine.LayoutError as exc:
                self._status(f'Cannot edit layer: {exc}', error=True)

        def _set_compact_hidden(self, hidden):
            if self._selected_layer is None or self.working is None:
                return
            try:
                updated = layout_engine.set_compact_hidden(self.working,
                                                          self._selected_layer[1], hidden)
                self._apply_layout(updated)
            except layout_engine.LayoutError as exc:
                self._status(f'Cannot change compact visibility: {exc}', error=True)

        def _add_layer(self, _button):
            if self.working is None or self._busy:
                return
            kind = self.layer_choices.get_active_id()
            if kind is None:
                return
            try:
                updated = layout_engine.add_layer(self.working, kind)
                self._apply_layout(updated)
                layer = 'icon' if kind.startswith('icon:') else 'widget'
                items = (self.working['desktop']['icons'] if layer == 'icon' else
                         self.working['composition']['widgets'])
                self._selected_layer = (layer, len(items) - 1)
                self._refresh_layer_list()
                self._status('Layer added. Save version to keep it.', success=True)
            except layout_engine.LayoutError as exc:
                self._status(f'Cannot add layer: {exc}', error=True)

        def _remove_layer(self, _button):
            if self._selected_layer is None or self.working is None or self._busy:
                return
            try:
                updated = layout_engine.remove_layer(self.working, *self._selected_layer)
                self._apply_layout(updated)
                self._selected_layer = None
                self._refresh_layer_list()
                self._status('Layer removed in unsaved version. Previous drafts are intact.',
                             success=True)
            except layout_engine.LayoutError as exc:
                self._status(f'Cannot remove layer: {exc}', error=True)

        def _geometry_changed(self, *_args):
            if hasattr(self, 'canvas'):
                self._capture_bytes = None
                self._capture_size = None
                self._region_report = None
                self._comparison_views = {k: v for k, v in self._comparison_views.items()
                                          if k == "reference"}
                self.reference_mode.set_active_id("native")
                self.reference_metrics.set_text("Output size changed. Render again before comparing.")
                self.preview_caption.set_text("Output size changed; previous capture is stale.")
                self._actions()
                self._queue_canvas()

        def _screen_geometry(self):
            selected = self.geometry.get_active_id() or '1366,768,1'
            width, height, _scale = selected.split(',')
            return int(width), int(height)

        def _queue_canvas(self):
            if self._canvas_refresh_queued:
                return
            self._canvas_refresh_queued = True
            GLib.idle_add(self._refresh_canvas_pixels)

        def _refresh_canvas_pixels(self):
            self._canvas_refresh_queued = False
            width = max(245, self.canvas.get_allocated_width())
            height = max(235, self.canvas.get_allocated_height())
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            self._paint_canvas(self.canvas, cairo.Context(surface))
            content = io.BytesIO()
            surface.write_to_png(content)
            loader = GdkPixbuf.PixbufLoader.new_with_type('png')
            loader.write(content.getvalue())
            loader.close()
            self.canvas_image.set_from_pixbuf(loader.get_pixbuf())
            return False

        def _paint_canvas(self, area, cr):
            width = max(245, area.get_allocated_width())
            height = max(235, area.get_allocated_height())
            cr.set_source_rgb(.055, .075, .105)
            cr.paint()
            if self.working is None:
                cr.set_source_rgb(.69, .78, .86)
                cr.move_to(18, height / 2)
                cr.set_font_size(14)
                cr.show_text('Create a draft to edit its desktop layers.')
                return False
            screen_w, screen_h = self._screen_geometry()
            view = layout_engine.fit_viewport(width, height, screen_w, screen_h)
            self._last_viewport = view
            recipe = self.working

            def color(value, alpha=1):
                rgb = tuple(int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))
                cr.set_source_rgba(*rgb, alpha)

            def rectangle(x, y, w, h, fill, *, border=None, radius=0):
                # Simple rectilinear geometry intentionally mirrors recipe hit regions.
                px, py = view.to_canvas(x, y)
                pw, ph = w * view.scale, h * view.scale
                cr.rectangle(px, py, pw, ph)
                color(fill)
                cr.fill_preserve() if border else cr.fill()
                if border:
                    cr.set_line_width(2 if radius else 1)
                    color(border)
                    cr.stroke()

            cr.rectangle(view.x - 1, view.y - 1, view.width + 2, view.height + 2)
            cr.set_source_rgb(.65, .72, .79)
            cr.stroke()
            # A schematic canvas intentionally does not imitate the wallpaper.
            rectangle(0, 0, screen_w, screen_h, '#18364b')
            cr.save()
            cr.rectangle(view.x, view.y, view.width, view.height)
            cr.clip()
            cr.set_line_width(.5)
            cr.set_source_rgba(.75, .84, .92, .12)
            for logical_x in range(0, screen_w, 128):
                px, _ = view.to_canvas(logical_x, 0)
                cr.move_to(px, view.y)
                cr.line_to(px, view.y + view.height)
            for logical_y in range(0, screen_h, 128):
                _, py = view.to_canvas(0, logical_y)
                cr.move_to(view.x, py)
                cr.line_to(view.x + view.width, py)
            cr.stroke()

            def selected(kind, index):
                return self._selected_layer == (kind, index)

            region = recipe['composition']['window_region']
            rx, ry = screen_w * region['x'] / 100, screen_h * region['y'] / 100
            if selected('region', 0) and self._drag_preview:
                rx, ry = self._drag_preview
            px, py = view.to_canvas(round(rx), round(ry))
            pw = view.width * region['width'] / 100
            ph = view.height * region['height'] / 100
            cr.rectangle(px, py, pw, ph)
            cr.set_source_rgba(.59, .73, .87, .13)
            cr.fill_preserve()
            cr.set_dash([7, 4])
            cr.set_line_width(2.5 if selected('region', 0) else 1.4)
            cr.set_source_rgba(.79, .88, 1, 1)
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgb(.86, .92, 1)
            cr.set_font_size(11)
            cr.move_to(px + 8, py + 16)
            cr.show_text('APPLICATION WINDOWS · RESERVED')

            panel = recipe['panel']
            panel_y = 0 if panel['position'] == 'top' else screen_h - panel['height']
            rectangle(0, panel_y, screen_w, panel['height'], recipe['colors']['background'],
                      border=recipe['colors']['active'])
            px, py = view.to_canvas(14, panel_y + max(16, panel['height'] / 2 + 4))
            cr.move_to(px, py)
            cr.set_font_size(max(8, min(12, 12 * view.scale)))
            color(recipe['colors']['foreground'])
            cr.show_text('PANEL · ' + panel['position'].upper())

            for index, icon in enumerate(recipe['desktop']['icons']):
                x, y = icon['x'], icon['y']
                if selected('icon', index) and self._drag_preview:
                    x, y = self._drag_preview
                rectangle(x, y, recipes.ICON_WIDTH, recipes.ICON_HEIGHT,
                          '#467187' if selected('icon', index) else '#30566b',
                          border='#ffe5a0' if selected('icon', index) else '#7398aa')
                px, py = view.to_canvas(x + 8, y + 33)
                cr.set_source_rgb(.96, .97, 1)
                cr.set_font_size(max(8, min(12, 11 * view.scale)))
                cr.move_to(px, py)
                cr.show_text(icon['label'][:12])

            hidden = recipe['composition']['compact_hide_widgets']
            for index, widget in enumerate(recipe['composition']['widgets']):
                x, y = widget['x'], widget['y']
                if selected('widget', index) and self._drag_preview:
                    x, y = self._drag_preview
                rectangle(x, y, recipes.DESKTOP_WIDGET_WIDTH, recipes.DESKTOP_WIDGET_HEIGHT,
                          '#335d72' if selected('widget', index) else '#24495e',
                          border='#ffe5a0' if selected('widget', index) else '#7398aa')
                px, py = view.to_canvas(x + 12, y + 32)
                cr.set_source_rgb(.95, .97, 1)
                cr.set_font_size(max(9, min(14, 13 * view.scale)))
                cr.move_to(px, py)
                name = widget.get('text') if widget['kind'] == 'text' else widget.get('ref', widget['kind'])
                cr.show_text(name[:22])
                cr.move_to(px, py + max(12, 18 * view.scale))
                cr.set_font_size(max(8, min(11, 10 * view.scale)))
                cr.show_text('HIDDEN ON COMPACT' if widget['id'] in hidden else
                             'DESKTOP WIDGET')
            cr.restore()
            if self._selected_layer is not None:
                area.get_style_context().add_class('creator-layer-selected')
            return False

        def _canvas_press(self, _area, event):
            if event.button != 1 or self.working is None or self._busy or self._last_viewport is None:
                return False
            x, y = self._last_viewport.to_screen(event.x, event.y)
            key = layout_engine.hit_test(self.working, x, y, *self._screen_geometry())
            self._selected_layer = key
            if key is not None:
                layer, index = key
                item = (self.working['composition']['window_region'] if layer == 'region' else
                        self.working['composition']['widgets'][index] if layer == 'widget' else
                        self.working['desktop']['icons'][index])
                sx, sy = ((round(self._screen_geometry()[0] * item['x'] / 100),
                           round(self._screen_geometry()[1] * item['y'] / 100))
                          if layer == 'region' else (item['x'], item['y']))
                self._drag = (key, event.x, event.y, sx, sy)
            else:
                self._drag = None
            self._refresh_layer_list()
            self.canvas.grab_focus()
            return True

        def _canvas_motion(self, _area, event):
            if self._drag is None or self._last_viewport is None:
                return False
            _key, start_x, start_y, x, y = self._drag
            scale = self._last_viewport.scale
            self._drag_preview = (round(x + (event.x - start_x) / scale),
                                  round(y + (event.y - start_y) / scale))
            self._queue_canvas()
            return True

        def _canvas_release(self, _area, event):
            if event.button != 1 or self._drag is None:
                return False
            key, *_ = self._drag
            self._drag = None
            point = self._drag_preview
            self._drag_preview = None
            if point is not None:
                self._move_selected(*point, snap=1 if event.state & Gdk.ModifierType.SHIFT_MASK else 8)
            self._queue_canvas()
            return True

        def _canvas_key(self, _area, event):
            directions = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0),
                          Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
            if (event.keyval not in directions or self._selected_layer is None or
                    self.working is None or self._busy):
                return False
            direction = directions[event.keyval]
            step = 1 if event.state & Gdk.ModifierType.SHIFT_MASK else 8
            layer, index = self._selected_layer
            item = (self.working['composition']['window_region'] if layer == 'region' else
                    self.working['composition']['widgets'][index] if layer == 'widget' else
                    self.working['desktop']['icons'][index])
            width, height = self._screen_geometry()
            x, y = ((round(width * item['x'] / 100), round(height * item['y'] / 100))
                    if layer == 'region' else (item['x'], item['y']))
            if layer == 'region':
                # Percent-based reserved region: each keypress is one percent.
                x += round(width / 100) * direction[0]
                y += round(height / 100) * direction[1]
            else:
                x += step * direction[0]
                y += step * direction[1]
            self._move_selected(x, y, snap=step)
            return True

        def _move_selected(self, x, y, *, snap):
            if self._selected_layer is None or self.working is None:
                return
            try:
                updated = layout_engine.move_layer(self.working, *self._selected_layer,
                                                  x, y, *self._screen_geometry(), snap=snap)
                self._apply_layout(updated)
                self._refresh_layer_list()
                self.canvas.grab_focus()
            except layout_engine.LayoutError as exc:
                self._status(f'Cannot move layer: {exc}', error=True)

        def _active_layout(self):
            assert self.working is not None
            return (self.working["responsive"]["compact_layout"] if self._panel_compact
                    else self.working["panel"]["layout"])

        def _panel_mode_changed(self, widget):
            if self._building:
                return
            self._panel_compact = widget.get_active_id() == "compact"
            self._refresh_layout()

        def _panel_choice(self):
            choices = Gtk.ComboBoxText()
            for key in sorted(recipes.WIDGETS):
                choices.append("widget:" + key, "Widget · " + key)
            for component in self.working.get("components", []):
                choices.append("component:" + component["id"],
                               "Component · " + component["label"])
            for key, label in (("gap", "Gap · 8px"), ("divider", "Divider · 8px"),
                               ("label", "Text label"), ("group", "Nested group")):
                choices.append(key, label)
            for key in sorted(recipes.PANEL_ACTIONS):
                choices.append("action:" + key, "Action · " + key)
            for key in sorted(recipes.PANEL_CONTROLS):
                choices.append("control:" + key, "Control · " + key)
            choices.set_active_id("gap")
            choices.connect("scroll-event", lambda *_: True)
            return choices

        def _panel_add_controls(self, holder, lane, parent_path=()):
            line = Gtk.Box(spacing=5)
            picker = self._panel_choice()
            picker.set_hexpand(True)
            line.pack_start(picker, True, True, 0)
            button = Gtk.Button(label="Add child" if parent_path else "Add to lane")
            button.connect("clicked", lambda _b, p=parent_path, c=picker:
                           self._add_node(lane, c.get_active_id(), parent_path=p))
            line.pack_start(button, False, False, 0)
            holder.pack_start(line, False, False, 0)

        def _build_panel_row(self, holder, lane, path, node, siblings):
            kind = node["type"]
            frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            frame.get_style_context().add_class("creator-layout-row")
            frame.set_margin_start(12 * (len(path) - 1))
            holder.pack_start(frame, False, False, 0)
            row = Gtk.Box(spacing=5)
            frame.pack_start(row, False, False, 0)
            title = self._text(_node_label(node), "hub-body")
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_tooltip_text(_node_label(node))
            row.pack_start(title, True, True, 0)
            for symbol, direction in (("↑", "up"), ("↓", "down")):
                button = Gtk.Button(label=symbol)
                button.set_tooltip_text(f"Move {_node_label(node)} {direction}")
                button.set_sensitive(path[-1] > 0 if direction == "up" else
                                     path[-1] < siblings - 1)
                button.connect("clicked", lambda _b, p=path, d=direction:
                               self._mutate_panel(lane, p, d))
                row.pack_start(button, False, False, 0)
            tools = Gtk.Box(spacing=5)
            frame.pack_start(tools, False, False, 0)
            if kind == "group":
                ungroup = Gtk.Button(label="Ungroup")
                ungroup.connect("clicked", lambda _b, p=path:
                                self._mutate_panel(lane, p, "ungroup"))
                tools.pack_start(ungroup, False, False, 0)
            else:
                wrap = Gtk.Button(label="Group")
                wrap.connect("clicked", lambda _b, p=path:
                             self._mutate_panel(lane, p, "wrap"))
                tools.pack_start(wrap, False, False, 0)
                remove = Gtk.Button(label="Remove")
                remove.connect("clicked", lambda _b, p=path:
                               self._mutate_panel(lane, p, "remove"))
                tools.pack_start(remove, False, False, 0)

            # Recompose the panel without round-tripping through raw JSON.
            # This uses the same transaction-safe validator as structural edits.
            destination = Gtk.ComboBoxText()
            for target_lane in recipes.SECTIONS:
                if target_lane != lane:
                    destination.append(target_lane, target_lane.capitalize())
            destination.set_active(0)
            destination.connect("scroll-event", lambda *_: True)
            destination.set_tooltip_text("Destination lane in this wide/compact layout")
            tools.pack_start(destination, False, False, 0)
            move = Gtk.Button(label="Move to lane")
            move.set_tooltip_text("Move this element, including any children, to the selected lane")
            move.connect("clicked", lambda _b, p=path, choice=destination:
                         self._transfer_panel(lane, p, choice.get_active_id()))
            tools.pack_start(move, False, False, 0)

            editable = Gtk.Box(spacing=5)
            frame.pack_start(editable, False, False, 0)
            key = ("gap" if kind == "group" else "width" if kind in ("gap", "divider")
                   else "text" if kind == "label" else "label" if kind in ("action", "control")
                   else "ref" if kind == "component" else "id" if kind == "widget" else None)
            if kind in ("group", "gap", "divider"):
                limits = {"group": (0, 32), "gap": (4, 64), "divider": (6, 32)}
                lower, upper = limits[kind]
                field = Gtk.SpinButton.new_with_range(lower, upper, 1)
                field.set_value(node[key])
                changed = lambda: field.get_value_as_int()
            elif kind in ("label", "action", "control"):
                field = Gtk.Entry()
                field.set_max_length(24 if kind == "label" else 16)
                field.set_text(node[key])
                changed = field.get_text
            else:
                field = Gtk.ComboBoxText()
                values = (sorted(recipes.WIDGETS) if kind == "widget" else
                          [item["id"] for item in self.working["components"]])
                for value in values:
                    field.append(value, value)
                field.set_active_id(node[key])
                field.connect("scroll-event", lambda *_: True)
                changed = field.get_active_id
            field.set_hexpand(True)
            field.set_tooltip_text(f"Edit {kind} {key}")
            editable.pack_start(field, True, True, 0)

            def commit(_widget=None, p=path, original=node, attr=key, reader=changed):
                replacement = copy.deepcopy(original)
                replacement[attr] = reader()
                self._mutate_panel(lane, p, "replace", replacement)

            if isinstance(field, Gtk.Entry):
                field.connect("activate", commit)
            button = Gtk.Button(label="Set")
            button.connect("clicked", commit)
            editable.pack_start(button, False, False, 0)
            if kind == "group":
                for index, child in enumerate(node["children"]):
                    self._build_panel_row(frame, lane, path + (index,), child,
                                          len(node["children"]))
                self._panel_add_controls(frame, lane, parent_path=path)

        def _build_lane(self, lane: str):
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            self.layout_lanes.pack_start(section, False, False, 0)
            section.pack_start(self._text(lane.upper(), "creator-rail-label"), False, False, 0)
            items = self._active_layout()[lane]
            for index, node in enumerate(items):
                self._build_panel_row(section, lane, (index,), node, len(items))
            self._panel_add_controls(section, lane)

        def _refresh_layout(self):
            for child in self.layout_lanes.get_children():
                self.layout_lanes.remove(child)
            for lane in recipes.SECTIONS:
                self._build_lane(lane)
            destination = "wide" if self._panel_compact else "compact"
            clone = Gtk.Button(label=f"Use this layout for {destination.capitalize()}…")
            clone.set_tooltip_text(
                "Replace all three destination lanes in the private draft; confirmation required")
            clone.connect("clicked", lambda _button: self._clone_panel_mode())
            self.layout_lanes.pack_start(clone, False, False, 0)
            self.layout_lanes.show_all()

        def _stage_panel_lanes(self, updates):
            # Only individual lane pointers belong to the public bounded edit
            # vocabulary. Save version validates all pending lanes atomically.
            prefix = ("/responsive/compact_layout" if self._panel_compact else
                      "/panel/layout")
            for lane, nodes in updates.items():
                self._change(f"{prefix}/{lane}", nodes)

        def _clone_panel_mode(self):
            if self.working is None or self._busy:
                return
            target_name = "wide" if self._panel_compact else "compact"
            target = (self.working["panel"]["layout"] if self._panel_compact else
                      self.working["responsive"]["compact_layout"])
            try:
                replacement = creator_structure.clone_layout_mode(
                    self.working, from_compact=self._panel_compact)
            except creator_structure.StructureError as exc:
                self._status(f"Cannot copy layout: {exc}", error=True)
                return
            if replacement == target:
                self._status(f"{target_name.capitalize()} layout already matches")
                return
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                text=f"Replace {target_name} panel layout?")
            dialog.format_secondary_text(
                "All three destination lanes will be replaced in this private draft. "
                "The running desktop stays unchanged. Save version is still required.")
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Replace in draft", Gtk.ResponseType.OK)
            try:
                response = dialog.run()
            finally:
                dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
            prefix = ("/panel/layout" if self._panel_compact else
                      "/responsive/compact_layout")
            # Replace only the three allowlisted lane edits. Existing unsaved
            # edits to those lanes are superseded via _change, while unrelated
            # pending properties remain untouched.
            for lane in recipes.SECTIONS:
                self._change(f"{prefix}/{lane}", replacement[lane])
            self._refresh_layout()

        def _mutate_panel(self, lane, path, action, node=None):
            if self.working is None or self._busy:
                return
            try:
                result = creator_structure.edit_layout(self.working, lane, path, action,
                                                       node=node, compact=self._panel_compact)
                self._stage_panel_lanes({lane: result})
                self._refresh_layout()
            except creator_structure.StructureError as exc:
                self._status(f"Cannot edit {lane} lane: {exc}", error=True)

        def _transfer_panel(self, lane, path, destination):
            if self.working is None or self._busy or destination is None:
                return
            try:
                updated = creator_structure.transfer_layout(
                    self.working, lane, path, destination, compact=self._panel_compact)
                # Stage both lanes as one validated operation before re-rendering.
                self._stage_panel_lanes(updated)
                self._refresh_layout()
            except creator_structure.StructureError as exc:
                self._status(f"Cannot move element to {destination}: {exc}", error=True)

        def _move(self, lane, index, delta):
            self._mutate_panel(lane, (index,), "up" if delta < 0 else "down")

        def _remove_node(self, lane, index):
            self._mutate_panel(lane, (index,), "remove")

        def _add_node(self, lane, selection, *, parent_path=()):
            if selection is None:
                return
            try:
                node = _node_template(selection)
            except (ValueError, creator_structure.StructureError):
                self._status("Choose a supported panel element", error=True)
                return
            self._mutate_panel(lane, parent_path, "add", node)

        def _change(self, path, value):
            if self._building or self.baseline is None:
                return
            if self._mapping is not None or self._mapping_busy:
                self._mapping_reset()
            assert self.working is not None
            target = self.working
            parts = path.lstrip("/").split("/")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = copy.deepcopy(value)
            if value == _get_field(self.baseline, path):
                self.pending.pop(path, None)
            else:
                self.pending[path] = value
            if self._pixbuf is not None and self.pending:
                self.preview_caption.set_text(
                    "Last native capture is from a saved version. Render again for changed pixels.")
            if self.pending:
                self._region_report = None
                self._comparison_views = {k: v for k, v in self._comparison_views.items()
                                          if k == "reference"}
                self.reference_mode.set_active_id("native")
                self.reference_metrics.set_text("Draft changed. Save and render before comparing.")
            self._queue_canvas()
            self._status(f"{len(self.pending)} unsaved properties · Save version before preview/export"
                         if self.pending else "No unsaved changes")
            self._actions()

        def _commit_pending(self) -> bool:
            if not self.pending:
                return True
            assert self.info is not None
            try:
                preflight = workspace.preview_revision(
                    self.info.path, self.pending, expected_sha256=self.info.semantic_sha256)
                if not self._confirm_revision(preflight):
                    self._status("Review cancelled. Unsaved edits were kept; no version created.")
                    return False
                revised, changes = workspace.save_revision(
                    self.info.path, self.pending,
                    expected_sha256=preflight["source_semantic_sha256"],
                    expected_draft_sha256=preflight["draft_semantic_sha256"])
                self._load(revised)
                self._refresh_drafts()
                self.diff.set_text("Validated changes: " + ", ".join(x["path"] for x in changes))
                self._status(f"Saved a new private version ({len(changes)} changes).", success=True)
                return True
            except (workspace.WorkspaceError, drafts.DraftError, recipes.RecipeError,
                    OSError, ValueError) as exc:
                self._status(f"Save blocked: {exc}. Fix the layout or property and retry.", error=True)
                return False

        def _confirm_revision(self, preflight: dict) -> bool:
            """Make creation of a new private file an explicit, reviewed action."""
            dialog = Gtk.Dialog(title="Review proposed Rice version", transient_for=self,
                                modal=True)
            dialog.add_button("Keep editing", Gtk.ResponseType.CANCEL)
            dialog.add_button("Create private version", Gtk.ResponseType.OK)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            content = dialog.get_content_area()
            content.set_border_width(12)
            content.set_spacing(10)
            content.pack_start(self._text(
                f"{len(preflight['changes'])} validated changes. Compare the values below "
                "before saving. The active desktop and next-login choice are untouched.",
                wrap=True), False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_size_request(600, 320)
            summary = Gtk.TextView()
            summary.set_editable(False)
            summary.set_cursor_visible(False)
            summary.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            summary.set_monospace(True)
            summary.set_left_margin(10)
            summary.set_right_margin(10)
            summary.get_buffer().set_text(_revision_review_text(preflight))
            scroll.add(summary)
            content.pack_start(scroll, True, True, 0)
            dialog.show_all()
            accepted = dialog.run() == Gtk.ResponseType.OK
            dialog.destroy()
            return accepted

        def _save(self, _button):
            self._commit_pending()

        def _confirm_handoff(self, title: str, detail: str, action: str) -> bool:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                       message_type=Gtk.MessageType.QUESTION,
                                       buttons=Gtk.ButtonsType.NONE, text=title)
            dialog.format_secondary_text(detail)
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button(action, Gtk.ResponseType.OK)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            response = dialog.run()
            dialog.destroy()
            return response == Gtk.ResponseType.OK

        def _install_draft(self, _button):
            self.wayland_menu.popdown()
            if self._busy or self.pending or self.info is None:
                return
            try:
                plan = creator_activation.inspect_install(self.info)
            except (creator_activation.ActivationError, OSError) as exc:
                self._status(f"Installation unavailable: {exc}", error=True)
                return
            if plan.already_installed:
                self._status("This exact saved version is already installed. Nothing changed.",
                             success=True)
                return
            if not self._confirm_handoff("Install this saved rice?",
                    f"{plan.draft.recipe_id} · SHA-256 {plan.draft.semantic_sha256[:12]}\n\n"
                    "Copies this immutable version into your private Wayland rice collection. "
                    "It will not change either desktop or the next login selection.",
                    "Install version"):
                return
            try:
                creator_activation.install(plan)
                self._status(f"Installed {plan.draft.recipe_id}. No desktop or login changed.",
                             success=True)
            except (creator_activation.ActivationError, OSError) as exc:
                self._status(f"Installation blocked: {exc}", error=True)

        def _fork_draft(self, _button):
            self.wayland_menu.popdown()
            if self._busy or self.pending or self.info is None:
                return
            try:
                new = workspace.fork_version(self.info)
                self._load(new, reset_history=True)
                self._refresh_drafts()
                self._status(f"Forked saved layout as {new.recipe_id}. Not installed or applied.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not fork version: {exc}", error=True)

        def _live_action(self, action: str):
            self.wayland_menu.popdown()
            if (self._busy or self.pending or not os.environ.get("WAYLAND_DISPLAY") or
                    (action == "apply" and self.info is None)):
                return
            draft = self.info
            self._busy = True
            self._actions()
            self._status("Checking the active RiceBowl Wayland session…")

            def prepare():
                try:
                    plan = (creator_activation.inspect_live(draft) if action == "apply" else
                            creator_activation.inspect_restore())
                    error = None
                except (creator_activation.ActivationError, OSError) as exc:
                    plan, error = None, str(exc)
                GLib.idle_add(self._live_review, action, plan, error)

            threading.Thread(target=prepare, name="ricebowl-creator-live-review",
                             daemon=False).start()

        def _live_review(self, action, plan, error):
            if not self.get_visible():
                self._busy = False
                return False
            if error:
                self._busy = False
                self._actions()
                self._status(f"Live change unavailable: {error}", error=True)
                return False
            if action == "apply":
                title = "Apply this saved rice to Wayland?"
                detail = (f"{plan.draft.recipe_id} · SHA-256 {plan.draft.semantic_sha256[:12]}\n"
                          f"Current rice: {plan.expected_active}\n\n"
                          "Changes the active RiceBowl panel, wallpaper and supported profiles. "
                          "The supervisor performs preflight checks and rolls back on failure. "
                          + ("The choice also persists for the next login." if plan.next_login_persisted
                             else "This is a nested session; the choice will not persist."))
                label = "Apply live"
            else:
                title = "Restore the previous Wayland rice?"
                detail = (f"Current: {plan.expected_active}\nRestore: {plan.previous}\n\n"
                          "The supervisor verifies the active rice and restores the previous "
                          "selection with rollback on failure.")
                label = "Restore live"
            if not self._confirm_handoff(title, detail, label):
                self._busy = False
                self._actions()
                self._status("Live change cancelled. Desktop unchanged.")
                return False
            self._status(f"{label} requested. Waiting for the Wayland supervisor…")

            def work():
                try:
                    response = (creator_activation.apply_live(plan) if action == "apply" else
                                creator_activation.restore_live(plan))
                    error_message = None
                except (creator_activation.ActivationError, OSError) as exc:
                    response, error_message = None, str(exc)
                GLib.idle_add(self._live_done, response, error_message)

            threading.Thread(target=work, name="ricebowl-creator-live-change",
                             daemon=False).start()
            return False

        def _live_done(self, response, error):
            self._busy = False
            if self.get_visible():
                self._actions()
                if error:
                    self._status(f"Live change not confirmed: {error}", error=True)
                else:
                    self._status(f"Active Wayland rice: {response['active']}. "
                                 "Restore is available when a previous version exists.",
                                 success=True)
            return False

        def _interactive(self, _button):
            if self._interactive_session is not None:
                if not self._interactive_closing:
                    self._interactive_closing = True
                    self._interactive_session.stop()
                    self._actions()
                    self._status("Closing the separate Wayland test window…")
                return
            if self._busy or self.pending or self.info is None:
                self._status("Save the current version before starting an interactive test.",
                             error=True)
                return
            try:
                self._interactive_session = creator_interactive.launch(
                    self.info, lambda running, result: GLib.idle_add(
                        self._interactive_done, running, result))
            except (creator_interactive.InteractivePreviewError, OSError) as exc:
                self._status(f"Interactive test unavailable: {exc}", error=True)
                return
            self._actions()
            self._status(f"Starting a separate interactive test of "
                         f"{self._interactive_session.draft.recipe_id}. "
                         "Current rice and next login remain unchanged.")

        def _interactive_done(self, running, result):
            if self._interactive_session is not running:
                return False
            self._interactive_session = None
            self._interactive_closing = False
            if not self.get_visible():
                return False
            self._actions()
            if result.stopped_by_user or result.exit_code == 0:
                self._status("Interactive Wayland test closed. Current rice and next login "
                             "were not switched.", success=True)
            else:
                extra = f" {result.diagnostic}" if result.diagnostic else " Check Wayland dependencies."
                self._status(f"Interactive test exited ({result.exit_code}).{extra}", error=True)
            return False

        def _undo(self, _button):
            if self._busy or self.info is None or self._previous is None:
                return
            if not self._discard_pending():
                return
            try:
                # Recheck the saved receipt instead of trusting a cached path.
                info = workspace.previous_version(self.info)
                if (info is None or info.path != self._previous.path
                        or info.semantic_sha256 != self._previous.semantic_sha256):
                    raise workspace.WorkspaceError("Creator history changed; reopen the draft")
                self._load(info)
                self._status("Verified previous private version reopened. No active rice changed.",
                             success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not reopen previous version: {exc}", error=True)

        def _show_history(self, _button):
            if self._busy or self.info is None:
                return
            try:
                chain = workspace.version_history(self.info)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not verify saved history: {exc}", error=True)
                return
            dialog = Gtk.Dialog(title="Creator version history", transient_for=self, modal=True)
            dialog.add_button("Close", Gtk.ResponseType.CANCEL)
            dialog.add_button("Open selected version", Gtk.ResponseType.OK)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            content = dialog.get_content_area()
            content.set_border_width(12)
            content.set_spacing(8)
            content.pack_start(self._text(
                f"{len(chain)} verified saved version(s), newest first. "
                "Opening an earlier version never applies it to Wayland.", wrap=True),
                False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_size_request(520, 300)
            entries = Gtk.ListBox()
            entries.set_selection_mode(Gtk.SelectionMode.SINGLE)
            for index, info in enumerate(chain):
                timestamp = datetime.fromtimestamp(info.modified_ns / 1_000_000_000).strftime(
                    "%Y-%m-%d %H:%M")
                label = (f"{'Current' if index == 0 else f'Previous {index}'} · {timestamp}\n"
                         f"{info.name} · {info.recipe_id} · SHA {info.semantic_sha256[:16]}")
                row = Gtk.ListBoxRow()
                row.add(self._text(label, wrap=True))
                entries.add(row)
            entries.select_row(entries.get_row_at_index(0))
            scroll.add(entries)
            content.pack_start(scroll, True, True, 0)
            dialog.show_all()
            response = dialog.run()
            selected = entries.get_selected_row()
            index = selected.get_index() if selected is not None else 0
            dialog.destroy()
            if response != Gtk.ResponseType.OK or index == 0 or not self._discard_pending():
                return
            try:
                chosen = workspace.open_draft(chain[index].path)
                if chosen.semantic_sha256 != chain[index].semantic_sha256:
                    raise workspace.WorkspaceError("Selected version changed since review")
                self._load(chosen, reset_history=True)
                self._status("Verified saved version opened. No active rice changed.", success=True)
            except (workspace.WorkspaceError, recipes.RecipeError, OSError) as exc:
                self._status(f"Could not open saved version: {exc}", error=True)

        def _render(self, _button):
            if self._busy or not self._commit_pending() or self.info is None:
                return
            info = self.info
            width, height, scale = self.geometry.get_active_id().split(",")
            self._busy = True
            self._render_generation += 1
            generation = self._render_generation
            self._capture_bytes = None
            self._capture_size = None
            self._region_report = None
            self._comparison_views = {k: v for k, v in self._comparison_views.items()
                                      if k in ("reference", "regions")}
            self.reference_mode.set_active_id("native")
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
                    self._capture_bytes = contents
                    self._capture_size = (receipt["geometry"]["width"],
                                          receipt["geometry"]["height"])
                    self._comparison_views = {k: v for k, v in self._comparison_views.items()
                                              if k == "reference"}
                    self.reference_mode.set_active_id("native")
                    if (self._reference is not None and self._capture_size !=
                            (self._reference.width, self._reference.height)):
                        self.reference_metrics.set_text(
                            "Reference and capture sizes differ. Choose matching output geometry.")
                    else:
                        self.reference_metrics.set_text(
                            "Native capture ready. Compare with the selected reference.")
                    self._preview_fit = None
                    self._resize_preview()
                    self.preview_caption.set_text(
                        f"Native RicePlate · {receipt['geometry']['width']} × "
                        f"{receipt['geometry']['height']} · scale {receipt['geometry']['scale']}")
                    self.visual_stack.set_visible_child_name("native")
                    self._status("Real native capture ready. No desktop settings changed.", success=True)
                except (GLib.Error, ValueError, KeyError) as exc:
                    self._status(f"Cannot display rendered PNG: {exc}", error=True)
            self._actions()
            return False

        def _reference_label(self):
            if self._reference is None:
                self.reference_info.set_text("No reference selected. Screenshots stay private.")
            else:
                self.reference_info.set_text(
                    f"{self._reference.name} · {self._reference.width} × {self._reference.height} "
                    f"· SHA-256 {self._reference.sha256[:12]} · private, not exported")

        def _regions_reset(self):
            """A rectangle and its measurements belong to exactly one reference."""
            self._region_cancel_drag()
            self.region_draw.set_active(False)
            self._regions = []
            self._region_report = None
            self._region_measurements = []
            for child in self.region_list.get_children():
                self.region_list.remove(child)
            self.region_summary.set_text("No regions marked.")
            self.region_cycle.set_text("Correction cycle: no measurements yet.")
            self._comparison_views.pop("regions", None)
            if self.reference_mode.get_active_id() == "regions":
                self.reference_mode.set_active_id("reference")

        def _region_cycle_label(self):
            if not self._region_measurements:
                self.region_cycle.set_text(
                    "Correction cycle: no measurements yet. Save an edit and render again "
                    "to compare the same regions.")
                return
            cycle = creator_iteration.journal(self._region_measurements)
            lines = [f"Correction cycle · {len(self._region_measurements)} real "
                     "capture(s) · last 12 retained"]
            for index, measurement in enumerate(self._region_measurements, start=1):
                lines.append(f"{index}. recipe {measurement['recipe_sha256'][:10]} "
                             f"· capture {measurement['capture_sha256'][:10]}")
            if cycle["comparisons"]:
                last = cycle["comparisons"][-1]
                for item in last["regions"]:
                    delta = item["tolerated_changed_percentage_point_delta"]
                    lines.append(f"Region {item['number']} · {delta:+.3f} percentage points "
                                 f"({item['direction']} pixel error)")
            lines.append("Comparable pixels only; lower error does not prove higher fidelity.")
            self.region_cycle.set_text("\n".join(lines))

        def _region_cancel_drag(self):
            self._region_drag = None
            self._region_drag_end = None
            self._region_drag_display = None
            if hasattr(self, "region_surface"):
                self.region_surface.queue_draw()

        def _region_draw_toggled(self, _button):
            self._region_cancel_drag()
            if self.region_draw.get_active():
                if self._reference is None or self._busy or self.pending:
                    self.region_draw.set_active(False)
                    return
                if self.reference_mode.get_active_id() not in ("reference", "regions"):
                    self.reference_mode.set_active_id("reference")
                self.visual_stack.set_visible_child_name("native")
                self._status("Drag a rectangle over the reference. Esc cancels; "
                             "the original PNG stays unchanged.")

        def _region_screen_geometry(self):
            displayed = self.preview_image.get_pixbuf()
            if displayed is None or self._reference is None:
                return None
            allocation = self.region_surface.get_allocation()
            width, height = displayed.get_width(), displayed.get_height()
            return ((width, height),
                    ((allocation.width - width) / 2, (allocation.height - height) / 2))

        def _region_pointer_press(self, _surface, event):
            if (event.button != 1 or not self.region_draw.get_active() or self._busy or
                    self.pending or len(self._regions) >= creator_regions.MAX_REGIONS or
                    self.reference_mode.get_active_id() not in ("reference", "regions")):
                return False
            geometry = self._region_screen_geometry()
            if geometry is None:
                return False
            displayed, origin = geometry
            pos = (event.x - origin[0], event.y - origin[1])
            if not 0 <= pos[0] <= displayed[0] or not 0 <= pos[1] <= displayed[1]:
                return False
            self._region_drag, self._region_drag_end = pos, pos
            self._region_drag_display, self._region_drag_origin = displayed, origin
            self.region_surface.grab_focus()
            self.region_surface.queue_draw()
            return True

        def _region_pointer_motion(self, _surface, event):
            if self._region_drag is None:
                return False
            self._region_drag_end = (event.x - self._region_drag_origin[0],
                                     event.y - self._region_drag_origin[1])
            self.region_surface.queue_draw()
            return True

        def _region_pointer_release(self, _surface, event):
            if self._region_drag is None or event.button != 1:
                return False
            start = self._region_drag
            end = (event.x - self._region_drag_origin[0],
                   event.y - self._region_drag_origin[1])
            displayed = self._region_drag_display
            self._region_cancel_drag()
            if self._reference is None or displayed is None or self.pending or self._busy:
                return True
            try:
                rect = creator_iteration.drag_rectangle(
                    start, end, displayed=displayed,
                    source=(self._reference.width, self._reference.height),
                    kind=self.region_kind.get_active_id())
                updated = creator_regions.validate(
                    [*self._regions, rect],
                    size=(self._reference.width, self._reference.height))
                self._regions = updated
                self._region_measurements = []
                for key in ("x", "y", "width", "height"):
                    self.region_coords[key].set_value(rect[key])
                self._region_refresh()
                self._status("Region selected in original screenshot pixels. "
                             "Measure it against a native render.", success=True)
            except creator_regions.RegionError as exc:
                self._status(f"Selection rejected: {exc}", error=True)
            return True

        def _region_pointer_key(self, _surface, event):
            if event.keyval == Gdk.KEY_Escape and self._region_drag is not None:
                self._region_cancel_drag()
                self._status("Region drag cancelled; annotations unchanged.")
                return True
            return False

        def _region_rubberband_draw(self, _surface, context):
            if self._region_drag is None or self._region_drag_end is None:
                return False
            width, height = self._region_drag_display
            ox, oy = self._region_drag_origin
            x1, y1 = self._region_drag
            x2, y2 = self._region_drag_end
            x1, x2 = sorted((max(0, min(width, x1)), max(0, min(width, x2))))
            y1, y2 = sorted((max(0, min(height, y1)), max(0, min(height, y2))))
            context.rectangle(ox + x1, oy + y1, x2 - x1, y2 - y1)
            context.set_source_rgba(0.19, 0.89, 0.70, 0.18)
            context.fill_preserve()
            context.set_source_rgba(0.19, 0.89, 0.70, 1)
            context.set_line_width(2)
            context.set_dash([5, 3])
            context.stroke()
            return False

        def _region_limits(self):
            if self._reference is None:
                return
            for key, limit in (("x", self._reference.width - 1),
                               ("y", self._reference.height - 1),
                               ("width", self._reference.width),
                               ("height", self._reference.height)):
                self.region_coords[key].set_range(0 if key in ("x", "y") else 1,
                                                  limit)
            self.region_coords["width"].set_value(min(self._reference.width, 160))
            self.region_coords["height"].set_value(min(self._reference.height, 48))

        def _region_refresh(self):
            self._region_report = None
            self._region_cancel_drag()
            for child in self.region_list.get_children():
                self.region_list.remove(child)
            for index, item in enumerate(self._regions):
                row = Gtk.Box(spacing=6)
                row.pack_start(self._text(
                    f"{index + 1}. {item['kind']} · {item['x']},{item['y']} · "
                    f"{item['width']}×{item['height']} px", "creator-layer-hint"),
                    True, True, 0)
                button = self._button("Remove", lambda _button, i=index: self._region_remove(i))
                row.pack_start(button, False, False, 0)
                self.region_list.pack_start(row, False, False, 0)
            self.region_list.show_all()
            self.region_summary.set_text(
                f"{len(self._regions)} user-reviewed rectangles. Measure against a matching "
                "native render; results expire when regions, policy or capture change."
                if self._regions else "No regions marked.")
            self._region_cycle_label()
            self._comparison_views.pop("regions", None)
            if self._reference is not None and self._regions and self.info is not None:
                try:
                    creator_mapping.ensure_current_reference(
                        self.info.recipe_id, self._reference.sha256)
                    data = creator_reference.image_bytes(self.info.recipe_id)
                    self._comparison_views["regions"] = creator_regions.annotated_view(
                        data, reference_sha256=self._reference.sha256, regions=self._regions)
                    if self.reference_mode.get_active_id() == "regions":
                        self._reference_view_changed()  # New image under the same selector.
                    else:
                        self.reference_mode.set_active_id("regions")
                except (creator_reference.ReferenceError, creator_mapping.MappingError,
                        creator_regions.RegionError, OSError) as exc:
                    self._status(f"Cannot mark reference: {exc}", error=True)
            elif self.reference_mode.get_active_id() == "regions":
                self.reference_mode.set_active_id("reference")
            self._actions()

        def _region_add(self, _button):
            if (self._busy or self.pending or self.info is None or self._reference is None):
                return
            item = {"kind": self.region_kind.get_active_id(),
                    **{key: widget.get_value_as_int()
                       for key, widget in self.region_coords.items()}}
            try:
                self._regions = creator_regions.validate(
                    [*self._regions, item],
                    size=(self._reference.width, self._reference.height))
                self._region_measurements = []
                self._region_refresh()
                self._status("Region marked locally. No screenshot or recipe was changed.",
                             success=True)
            except creator_regions.RegionError as exc:
                self._status(f"Region rejected: {exc}", error=True)

        def _region_remove(self, index: int):
            if self._busy or not 0 <= index < len(self._regions):
                return
            self._regions.pop(index)
            self._region_measurements = []
            self._region_refresh()

        def _region_from_mapping(self, _button):
            if (not self._mapping or not self._reference or self.pending or self._busy):
                return
            try:
                creator_mapping.ensure_current_reference(
                    self.info.recipe_id, self._reference.sha256)
                rectangles = [{key: item[key] for key in
                               ("kind", "x", "y", "width", "height")}
                              for item in self._mapping["regions"]]
                self._regions = creator_regions.validate(
                    rectangles, size=(self._reference.width, self._reference.height))
                self._region_measurements = []
                self._region_refresh()
                self._status("Suggested geometry copied for visual review. No edits applied.",
                             success=True)
            except (creator_mapping.MappingError, creator_regions.RegionError) as exc:
                self._status(f"Cannot use suggested regions: {exc}", error=True)

        def _region_compare(self, _button):
            if (self._busy or self.pending or not self.info or not self._reference or
                    not self._capture_bytes or not self._regions or
                    self._capture_size != (self._reference.width, self._reference.height)):
                return
            info, expected_sha = self.info, self._reference.sha256
            actual, rectangles = self._capture_bytes, copy.deepcopy(self._regions)
            threshold = self.compare_threshold.get_value_as_int()
            radius = int(self.compare_tolerance.get_active_id() or "1")
            self._region_report = None
            self._busy = True
            self._render_generation += 1
            generation = self._render_generation
            self.spinner.start()
            self.region_summary.set_text("Measuring only the marked screenshot regions…")
            self._actions()

            def work():
                try:
                    creator_mapping.ensure_current_reference(info.recipe_id, expected_sha)
                    reference = creator_reference.image_bytes(info.recipe_id)
                    report = creator_regions.inspect(
                        reference, actual, reference_sha256=expected_sha,
                        recipe_sha256=info.semantic_sha256, regions=rectangles,
                        threshold=threshold, tolerance_radius=radius)
                    creator_mapping.ensure_current_reference(info.recipe_id, expected_sha)
                    error = None
                except (creator_regions.RegionError, creator_reference.ReferenceError,
                        creator_mapping.MappingError, OSError, ValueError) as exc:
                    report, error = None, str(exc)
                GLib.idle_add(self._region_complete, generation, report, error)

            threading.Thread(target=work, name="ricebowl-creator-regions", daemon=False).start()

        def _region_complete(self, generation, report, error):
            if generation != self._render_generation or not self.get_visible():
                return False
            self._busy = False
            self.spinner.stop()
            if error:
                self.region_summary.set_text("Region comparison unavailable. Check the reference and retry.")
                self._status(f"Region QA failed: {error}", error=True)
            else:
                try:
                    creator_mapping.ensure_current_reference(
                        self.info.recipe_id, report["reference_sha256"])
                    measured = list(self._region_measurements)
                    if not measured or (measured[-1]["capture_sha256"],
                                        measured[-1]["recipe_sha256"]) != (
                                            report["capture_sha256"], report["recipe_sha256"]):
                        measured.append(report)
                    measured = measured[-creator_iteration.MAX_MEASUREMENTS:]
                    creator_iteration.journal(measured)
                    self._region_measurements = measured
                    self._region_report = report
                    lines = [f"{r['number']}. {r['kind']} · raw "
                             f"{100 * r['changed_pixel_ratio']:.2f}% · tolerant "
                             f"{100 * r['tolerance']['changed_pixel_ratio']:.2f}% · "
                             f"RGB error {r['mean_absolute_rgb_error']:.2f}"
                             for r in report["regions"]]
                    self.region_summary.set_text("\n".join(lines) +
                        "\nPixel errors only · no inferred functional or perceptual accuracy.")
                    self._region_cycle_label()
                    self._status("Measured annotated regions against the real native capture.",
                                 success=True)
                except (creator_mapping.MappingError, creator_regions.RegionError,
                        TypeError, KeyError) as exc:
                    self.region_summary.set_text("Reference changed. Measure regions again.")
                    self._status(f"Region QA rejected: {exc}", error=True)
            self._actions()
            return False

        def _region_export(self, _button):
            if (not self._region_report or not self.info or not self._reference or
                    not self._capture_bytes or self.pending or self._busy):
                return
            chooser = Gtk.FileChooserDialog(title="Export region pixel diagnostics JSON",
                                            transient_for=self, action=Gtk.FileChooserAction.SAVE)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Export report", Gtk.ResponseType.ACCEPT)
            chooser.set_do_overwrite_confirmation(False)
            chooser.set_current_name(f"{self.info.recipe_id}-regions.json")
            response = chooser.run()
            destination = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if destination is None:
                return
            try:
                creator_mapping.ensure_current_reference(
                    self.info.recipe_id, self._region_report["reference_sha256"])
                if (self.info.semantic_sha256 != self._region_report["recipe_sha256"] or
                        hashlib.sha256(self._capture_bytes).hexdigest() !=
                        self._region_report["capture_sha256"]):
                    raise creator_regions.RegionError("Capture or saved recipe changed; measure again")
                history = creator_iteration.journal(self._region_measurements)
                payload = (json.dumps({**self._region_report, "correction_cycle": history},
                                      indent=2, sort_keys=True) + "\n").encode()
                if len(payload) > 96 * 1024:
                    raise creator_regions.RegionError("Region report exceeds private JSON limit")
                recipes._write_private_new(destination, payload)
                self._status("Pixel report exported without source or capture image bytes.",
                             success=True)
            except (OSError, creator_mapping.MappingError, creator_regions.RegionError,
                    recipes.RecipeError) as exc:
                self._status(f"Report export blocked: {exc}", error=True)

        def _mapping_reset(self):
            """Invalidate mappings when the draft or reference identity changes."""
            self._mapping_generation += 1
            self._mapping_busy = False
            self._mapping = None
            self._mapping_checks = {}
            if hasattr(self, "mapping_list"):
                for child in self.mapping_list.get_children():
                    self.mapping_list.remove(child)
                self.mapping_info.set_text(
                    "No current mapping. Analyze the reference or import new proposals.")

        def _mapping_set_result(self, mapping: dict):
            assert self.info is not None and self._reference is not None
            creator_mapping.ensure_current_reference(
                self.info.recipe_id, self._reference.sha256)
            creator_mapping.validate(
                mapping, reference_sha256=self._reference.sha256,
                recipe_sha256=self.info.semantic_sha256,
                size=(self._reference.width, self._reference.height),
                manifest=self.baseline)
            self._mapping_reset()
            self._mapping = mapping
            property_labels = {path: label for _group, fields in FIELDS
                               for path, label, _kind, _options in fields}
            property_labels.update({
                "/panel/layout/start": "Panel · start lane",
                "/panel/layout/center": "Panel · center lane",
                "/panel/layout/end": "Panel · end lane",
            })
            for item in mapping["suggestions"]:
                path = item["path"]
                if item["value"] == _get_field(self.working, path):
                    continue
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                value = item["value"]
                display = (f"{len(value)} declarative nodes" if isinstance(value, list)
                           else str(value))
                checkbox = Gtk.CheckButton(
                    label=f"{property_labels.get(path, path)}  →  {display}")
                checkbox.set_tooltip_text(f"{path}\n{item['evidence']}")
                # External confidence is only a claim from untrusted input;
                # all externally authored edits require deliberate selection.
                checkbox.set_active(mapping["source"] == "offline" and
                                    item["confidence"] >= 0.72)
                checkbox.connect("toggled", lambda *_: self._actions())
                row.pack_start(checkbox, False, False, 0)
                strength = ("strong" if item["confidence"] >= 0.8 else
                            "moderate" if item["confidence"] >= 0.55 else "tentative")
                source_label = (f"{strength} offline hint" if mapping["source"] == "offline"
                                else "unverified external claim")
                explanation = self._text(
                    f"{path} · {source_label} · {item['evidence']}",
                    "creator-layer-hint", wrap=True)
                explanation.set_margin_start(22)
                row.pack_start(explanation, False, False, 0)
                self.mapping_list.pack_start(row, False, False, 0)
                self._mapping_checks[path] = checkbox
            if not self._mapping_checks:
                self.mapping_list.pack_start(self._text(
                    "Nothing new to apply; all proposed values match the current draft.",
                    "creator-layer-hint", wrap=True), False, False, 0)
            region_summary = ", ".join(f"{item['kind']} {item['width']}×{item['height']}"
                                       for item in mapping["regions"]) or "none"
            self.mapping_info.set_text(
                f"{mapping['source']} proposals · {len(mapping['suggestions'])} hints · "
                f"detected regions: {region_summary}. " + " ".join(mapping["notes"]))
            self.mapping_list.show_all()
            self._actions()

        def _mapping_analyze(self, _button):
            if self._busy or self._mapping_busy or self.pending or not self.info or not self._reference:
                return
            info, reference = self.info, self._reference
            self._mapping_reset()
            self._mapping_busy = True
            generation = self._mapping_generation
            self.mapping_info.set_text("Analyzing the private PNG offline…")
            self._actions()

            def work():
                try:
                    data = creator_reference.image_bytes(info.recipe_id)
                    result = creator_mapping.analyze(
                        data, reference_sha256=reference.sha256,
                        recipe_sha256=info.semantic_sha256)
                    error = None
                except (creator_mapping.MappingError, creator_reference.ReferenceError,
                        ValueError, OSError) as exc:
                    result, error = None, str(exc)
                GLib.idle_add(self._mapping_complete, generation, result, error)

            threading.Thread(target=work, name="ricebowl-creator-mapping", daemon=False).start()

        def _mapping_complete(self, generation, result, error):
            if generation != self._mapping_generation:
                return False
            self._mapping_busy = False
            if error:
                self.mapping_info.set_text("Reference analysis unavailable. Retry or import JSON.")
                self._status(f"Mapping analysis failed: {error}", error=True)
            else:
                try:
                    self._mapping_set_result(result)
                    self._status("Offline hints ready for review. No changes applied.",
                                 success=True)
                except creator_mapping.MappingError as exc:
                    self._status(f"Mapping rejected: {exc}", error=True)
            self._actions()
            return False

        def _mapping_import(self, _button):
            if self._busy or self._mapping_busy or self.pending or not self.info or not self._reference:
                return
            chooser = Gtk.FileChooserDialog(
                title="Import reviewable reference mapping JSON", transient_for=self,
                action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Validate proposals", Gtk.ResponseType.ACCEPT)
            files = Gtk.FileFilter()
            files.set_name("Mapping proposals (JSON)")
            files.add_pattern("*.json")
            chooser.add_filter(files)
            response = chooser.run()
            source = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if source is None:
                return
            try:
                descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(descriptor, "rb") as stream:
                    metadata = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(metadata.st_mode) or
                            metadata.st_uid != os.geteuid() or
                            metadata.st_mode & 0o022 or
                            metadata.st_size > creator_mapping.MAX_MAPPING_BYTES):
                        raise creator_mapping.MappingError(
                            "Mapping must be an owner-controlled JSON file under 24 KiB")
                    raw = stream.read(creator_mapping.MAX_MAPPING_BYTES + 1)
                creator_mapping.ensure_current_reference(
                    self.info.recipe_id, self._reference.sha256)
                mapping = creator_mapping.import_proposals(
                    raw, reference_sha256=self._reference.sha256,
                    recipe_sha256=self.info.semantic_sha256,
                    size=(self._reference.width, self._reference.height),
                    manifest=self.baseline)
                self._mapping_set_result(mapping)
                self._status("JSON mapping validated. Review each checkbox before using hints.",
                             success=True)
            except (OSError, creator_mapping.MappingError) as exc:
                self._status(f"Mapping import blocked: {exc}", error=True)

        def _mapping_export(self, _button):
            if not self._mapping or not self.info or self.pending or self._mapping_busy:
                return
            chooser = Gtk.FileChooserDialog(title="Export private mapping hints JSON",
                                            transient_for=self, action=Gtk.FileChooserAction.SAVE)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Export hints", Gtk.ResponseType.ACCEPT)
            chooser.set_do_overwrite_confirmation(False)
            chooser.set_current_name(f"{self.info.recipe_id}-mapping.json")
            response = chooser.run()
            destination = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if destination is None:
                return
            try:
                creator_mapping.ensure_current_reference(
                    self.info.recipe_id, self._reference.sha256)
                payload = (json.dumps(self._mapping, ensure_ascii=False, indent=2) + "\n").encode()
                if len(payload) > creator_mapping.MAX_MAPPING_BYTES:
                    raise creator_mapping.MappingError("Mapping exceeds safe export limit")
                recipes._write_private_new(destination, payload)
                self._status("Mapping hints exported privately without screenshot pixels.",
                             success=True)
            except (OSError, creator_mapping.MappingError, recipes.RecipeError) as exc:
                self._status(f"Mapping export failed: {exc}. Choose a new filename.", error=True)

        def _mapping_apply(self, _button):
            if (not self._mapping or not self.info or not self._reference or self.pending
                    or self._busy or self._mapping_busy):
                return
            checked = {path for path, widget in self._mapping_checks.items()
                       if widget.get_active()}
            try:
                creator_mapping.ensure_current_reference(
                    self.info.recipe_id, self._reference.sha256)
                changes = creator_mapping.selected_changes(
                    self._mapping, checked, reference_sha256=self._reference.sha256,
                    recipe_sha256=self.info.semantic_sha256,
                    size=(self._reference.width, self._reference.height),
                    manifest=self.baseline)
            except creator_mapping.MappingError as exc:
                self._status(f"Suggestions rejected: {exc}", error=True)
                return
            self._mapping_reset()
            for path, value in changes.items():
                self._change(path, value)
            self._build_inspector()
            self._queue_canvas()
            self._actions()
            self._status(f"{len(changes)} reviewed hints in unsaved draft. "
                         "Inspect fields and Save version to persist.", success=True)

        def _reference_choose(self, _button):
            if self._busy or self._mapping_busy or self.info is None or self.pending:
                self._status("Save the draft before selecting a reference.", error=True)
                return
            chooser = Gtk.FileChooserDialog(title="Choose a reference PNG screenshot",
                                            transient_for=self, action=Gtk.FileChooserAction.OPEN)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                                "Use as reference", Gtk.ResponseType.ACCEPT)
            images = Gtk.FileFilter()
            images.set_name("PNG screenshots")
            images.add_pattern("*.png")
            chooser.add_filter(images)
            response = chooser.run()
            source = Path(chooser.get_filename()) if response == Gtk.ResponseType.ACCEPT else None
            chooser.destroy()
            if source is None:
                return
            try:
                self._reference = creator_reference.select(self.info.recipe_id, source)
                self._mapping_reset()
                self._regions_reset()
                self._region_limits()
                self._comparison_views = {
                    "reference": creator_reference.image_bytes(self.info.recipe_id)}
                self.reference_mode.set_active_id("reference")
                self._reference_label()
                if (self._capture_size is not None and self._capture_size !=
                        (self._reference.width, self._reference.height)):
                    self.reference_metrics.set_text(
                        "Reference resolution differs from the native capture. "
                        "Select matching output geometry and render again.")
                else:
                    self.reference_metrics.set_text(
                        "Reference loaded. Compare after a matching native render.")
                self._status("Private reference linked to this draft. RicePack unchanged.", success=True)
            except (creator_reference.ReferenceError, OSError, ValueError) as exc:
                self._status(f"Cannot load reference: {exc}", error=True)
            self._actions()

        def _reference_unlink(self, _button):
            if self._busy or self._mapping_busy or self.info is None or self._reference is None:
                return
            try:
                creator_reference.clear(self.info.recipe_id)
                self._reference = None
                self._mapping_reset()
                self._regions_reset()
                self._comparison_views = {}
                self.reference_mode.set_active_id("native")
                self._reference_label()
                self.reference_metrics.set_text("Reference unlinked. Saved screenshots remain private.")
                self._status("Reference detached without changing a draft or desktop.", success=True)
            except (creator_reference.ReferenceError, OSError) as exc:
                self._status(f"Cannot unlink reference: {exc}", error=True)
            self._actions()

        def _comparison_policy_changed(self, *_args):
            if not hasattr(self, 'reference_metrics'):
                return
            self._region_report = None
            self._region_measurements = []
            if hasattr(self, 'region_cycle'):
                self._region_cycle_label()
            if hasattr(self, 'region_summary') and self._regions:
                self.region_summary.set_text("Pixel policy changed. Measure marked regions again.")
            self._comparison_views = {k: v for k, v in self._comparison_views.items()
                                      if k in ("reference", "regions")}
            self.reference_mode.set_active_id("native")
            self.reference_metrics.set_text("Comparison policy changed. Compare again for fresh metrics.")
            self._actions()

        def _reference_view_changed(self, *_args):
            name = self.reference_mode.get_active_id()
            if name not in ("reference", "regions") and self.region_draw.get_active():
                self.region_draw.set_active(False)
            if name == "native" and self._capture_bytes:
                data = self._capture_bytes
            else:
                data = self._comparison_views.get(name)
            if data is None:
                fallback = "reference" if "reference" in self._comparison_views else "native"
                if name != fallback:
                    self.reference_mode.set_active_id(fallback)
                self._status("Compare first to generate the split, overlay and heatmap.")
                return
            try:
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.write(data)
                loader.close()
                self._pixbuf = loader.get_pixbuf()
                self._preview_fit = None
                self._resize_preview()
                self._region_cancel_drag()
                self.visual_stack.set_visible_child_name("native")
                labels = {"native": "Real isolated RicePlate capture",
                          "reference": "Imported reference screenshot · not rendered by RicePlate",
                          "wipe": "Split: left reference / right native capture · no scaling",
                          "overlay": "50% reference + 50% native capture",
                          "heatmap": "Tolerance-aware changed pixels · red = difference",
                          "regions": "Reference screenshot with owner-marked rectangles"}
                self.preview_caption.set_text(labels[name])
            except (GLib.Error, ValueError) as exc:
                self._status(f"Cannot display visual QA image: {exc}", error=True)

        def _compare_reference(self, _button):
            if (self._busy or self.info is None or self._reference is None
                    or self._capture_bytes is None or self._capture_size != (
                        self._reference.width, self._reference.height) or self.pending):
                return
            info, image, reference_sha = self.info, self._capture_bytes, self._reference.sha256
            threshold = self.compare_threshold.get_value_as_int()
            radius = int(self.compare_tolerance.get_active_id() or "1")
            self._busy = True
            self._render_generation += 1
            generation = self._render_generation
            self.spinner.start()
            self.reference_metrics.set_text("Measuring real pixels…")
            self._actions()

            def work():
                try:
                    metrics, images = creator_reference.compare_capture(
                        info.recipe_id, image, recipe_token=str(info.path),
                        threshold=threshold, tolerance_radius=radius,
                        expected_sha256=reference_sha)
                    error = None
                except (creator_reference.ReferenceError, OSError, ValueError) as exc:
                    metrics, images, error = None, None, str(exc)
                GLib.idle_add(self._comparison_complete, generation, metrics, images, error)

            threading.Thread(target=work, name="ricebowl-creator-compare", daemon=False).start()

        def _comparison_complete(self, generation, metrics, images, error):
            if generation != self._render_generation or not self.get_visible():
                return False
            self._busy = False
            self.spinner.stop()
            if error:
                self._comparison_views = {}
                self._reference = None  # A raced or damaged selection must be revalidated.
                self._regions_reset()
                self._reference_label()
                self.reference_metrics.set_text("Comparison unavailable. Reference and capture were not modified.")
                self._status(f"Compare failed: {error}", error=True)
            else:
                self._comparison_views = images
                self.reference_mode.set_active_id("overlay")
                raw = 100 * metrics["changed_pixel_ratio"]
                tolerated = 100 * metrics.get("tolerance", {}).get(
                    "changed_pixel_ratio", metrics["changed_pixel_ratio"])
                issues = len(metrics.get("layout_issues", []))
                self.reference_metrics.set_text(
                    f"Changed: {raw:.2f}% raw · {tolerated:.2f}% with tolerance · "
                    f"mean RGB error {metrics['mean_absolute_rgb_error']:.2f} · "
                    f"layout warnings {issues}. No perceptual/functional score.")
                self._status("Comparison ready: use the view selector for split, overlay and difference.",
                             success=True)
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
            self.region_surface.queue_draw()

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
            if not self._discard_pending():
                return True
            if self._interactive_session is not None:
                self._interactive_session.stop()
            return False

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
            if not os.environ.get("XDG_STATE_HOME") or not os.environ.get("XDG_CONFIG_HOME"):
                raise RuntimeError("Creator smoke requires isolated XDG state and config")
            window = windows[0]
            window._create("heritage")
            assert window.info is not None and window.info.recipe_id.startswith("creator-")
            interactive_review = window._confirm_revision

            def smoke_review(preflight):
                # Exercise the actual GTK dialog in disposable CI state, with
                # a synthetic approval only in this explicit smoke scenario.
                def accept_dialog():
                    dialogs = [item for item in Gtk.Window.list_toplevels()
                               if isinstance(item, Gtk.Dialog)
                               and item.get_title() == "Review proposed Rice version"]
                    assert len(dialogs) == 1, "Creator review dialog missing"
                    dialogs[0].response(Gtk.ResponseType.OK)
                    return False

                GLib.idle_add(accept_dialog)
                return interactive_review(preflight)

            window._confirm_revision = smoke_review
            initial = window.info
            window._change("/panel/height", 44)
            assert window.save_btn.get_sensitive()
            assert window._commit_pending()
            assert window.info.path != initial.path and window._previous.path == initial.path
            # Clear all in-memory selection state as though reopening Creator.
            window._load(workspace.open_draft(window.info.path), reset_history=True)
            assert window.undo_btn.get_sensitive() and window._previous.path == initial.path
            assert window.history_btn.get_sensitive()

            def dismiss_history():
                dialogs = [item for item in Gtk.Window.list_toplevels()
                           if isinstance(item, Gtk.Dialog)
                           and item.get_title() == "Creator version history"]
                assert len(dialogs) == 1, "Creator history dialog missing"
                dialogs[0].response(Gtk.ResponseType.CANCEL)
                return False

            GLib.idle_add(dismiss_history)
            window._show_history(None)
            assert recipes.load(str(window.info.path)).height == 44
            window._move("start", 0, 1)
            assert window.pending
            window._change("/panel/layout/start", window.baseline["panel"]["layout"]["start"])
            assert not window.pending
            window._undo(None)
            assert window.info.path == initial.path
            # Exercise the real 2-D editor rather than only its pure model:
            # add one static layer, move it, set compact visibility, persist.
            assert window.layer_choices.set_active_id("text"), "Static text choice missing"
            window._add_layer(None)
            assert window._selected_layer == ('widget', 2), (
                f"Adding a text widget selected {window._selected_layer!r}; "
                f"widget count={len(window.working['composition']['widgets'])}; "
                f"choice={window.layer_choices.get_active_id()!r}")
            window._move_selected(168, 568, snap=8)
            window._set_compact_hidden(True)
            assert len(window.working['composition']['widgets']) == 3
            assert window.working['composition']['widgets'][2]['x'] == 168
            assert window._commit_pending()
            saved = recipes.load(str(window.info.path))
            assert len(saved.composition.widgets) == 3
            assert saved.composition.widgets[2].widget_id in saved.composition.compact_hide_widgets
            window._refresh_canvas_pixels()
            assert window.canvas_image.get_pixbuf() is not None
            # Exercise real GTK forms, component insertion and nested wide +
            # compact panel authoring through the same offline editor methods.
            window.component_choice.set_active_id("new")
            window.component_id.set_text("test-battery")
            window.component_label.set_text("Battery")
            window.component_role.set_active_id("status")
            window.component_binding.set_active_id("battery")
            window._component_edit("add")
            assert any(c["id"] == "test-battery" for c in window.working["components"])
            window._add_node("center", "component:test-battery")
            window._add_node("center", "group")
            window._mutate_panel("center", (1,), "add",
                                 {"type": "label", "text": "Shell"})
            assert window.working["panel"]["layout"]["center"][1]["children"][1]["text"] == "Shell"
            window.panel_mode.set_active_id("compact")
            assert window._panel_compact
            window._add_node("center", "label")
            assert window.working["responsive"]["compact_layout"]["center"][-1]["type"] == "label"
            window.panel_mode.set_active_id("wide")
            assert window._commit_pending()
            updated = recipes.load(str(window.info.path))
            assert any(c.component_id == "test-battery" for c in updated.components)
            # Exercise the actual asset catalog and GTK choice binding. A PNG
            # shipped with the repo is a valid owner-controlled, tiny test image.
            sample = (Path(__file__).resolve().parents[1] / "assets" / "themes" /
                      "RiceHub-Ten-Dark" / "xfwm4" / "maximize-active.png")
            declared = dict(creator_assets.UNKNOWN_PROVENANCE)
            imported = creator_assets.import_wallpaper(sample, label="Creator smoke PNG",
                                                       provenance=declared)
            window._refresh_asset_list()
            window.wallpaper_choice.set_active_id(imported.asset_id)
            assert window.working['desktop']['wallpaper'] == imported.asset_id
            assert window.pending['/desktop/wallpaper'] == imported.asset_id
            assert window._commit_pending()
            with tempfile.TemporaryDirectory(prefix="ricebowl-creator-pack-test-") as temp:
                receipt = workspace.export_draft(window.info, Path(temp) / "smoke.ricepack")
                assert receipt['pack_version'] == 3 and not receipt['applied']
                # v0.5: exercise the actual GTK selector, the schema-v11 edit
                # pathway and v4 archive export without touching the session.
                source = Path(temp) / "creator-shortcut.png"
                icon = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 48, 48)
                icon.fill(0x438bd4ff)
                icon.savev(str(source), "png", [], [])
                declared_icon = style_assets.import_asset(
                    source, kind="icon", label="Creator GTK icon",
                    provenance={"author": "RiceBowl", "license": "CC0-1.0",
                                "origin": "original", "source_reference": "GTK smoke"})
                window._refresh_style_choices()
                window.style_choices["applications"].set_active_id(declared_icon.identifier)
                assert window.pending["/artwork/icons/applications"] == declared_icon.identifier
                assert window._commit_pending()
                assert recipes.load(str(window.info.path)).artwork.icons[0] == declared_icon.identifier
                packed = workspace.export_draft(window.info, Path(temp) / "smoke-art.ricepack")
                assert packed["pack_version"] == 4 and not packed["applied"]
                # v0.6: drive the native reference selector and view stack
                # with test-generated pixels. No headless Wayland runtime is
                # needed for the GTK smoke; real comparison uses the same QA API.
                window._reference = creator_reference.select(window.info.recipe_id, source)
                window._region_limits()
                window._reference_label()
                window._capture_bytes = source.read_bytes()
                window._capture_size = (48, 48)
                window._actions()
                assert window.compare_btn.get_sensitive()
                metrics, views = creator_reference.compare_capture(
                    window.info.recipe_id, window._capture_bytes)
                window._comparison_complete(window._render_generation, metrics, views, None)
                assert window.reference_mode.get_active_id() == "overlay"
                assert window.preview_image.get_pixbuf() is not None
                window.reference_mode.set_active_id("heatmap")
                assert "difference" in window.preview_caption.get_text().lower()
                # v0.8: a numbered, owner-defined rectangle visibly overlays
                # the actual reference. Measurement is strictly read-only and
                # uses the same bounds, screenshot identity and pixel policy.
                window.region_kind.set_active_id("menu")
                window.region_coords["x"].set_value(4)
                window.region_coords["y"].set_value(5)
                window.region_coords["width"].set_value(24)
                window.region_coords["height"].set_value(18)
                window._region_add(None)
                assert len(window._regions) == 1
                assert window.reference_mode.get_active_id() == "regions"
                assert window.preview_image.get_pixbuf() is not None
                local_report = creator_regions.inspect(
                    source.read_bytes(), window._capture_bytes,
                    reference_sha256=window._reference.sha256,
                    recipe_sha256=window.info.semantic_sha256,
                    regions=window._regions, threshold=24, tolerance_radius=1)
                window._region_complete(window._render_generation, local_report, None)
                assert window.region_export.get_sensitive()
                assert "0.00%" in window.region_summary.get_text()
                window._region_remove(0)
                assert not window.region_export.get_sensitive()
                # v0.9: the actual GTK overlay receives a mouse drag, maps
                # fitted display coordinates to reference pixels and starts
                # a comparable QA history across validated saved revisions.
                from types import SimpleNamespace
                window.region_draw.set_active(True)
                assert window.reference_mode.get_active_id() == "reference"
                geometry = window._region_screen_geometry()
                assert geometry is not None
                _, origin = geometry
                start = SimpleNamespace(button=1, x=origin[0] + 3, y=origin[1] + 4)
                end = SimpleNamespace(button=1, x=origin[0] + 27, y=origin[1] + 22)
                assert window._region_pointer_press(window.region_surface, start)
                assert window._region_pointer_motion(window.region_surface, end)
                assert window._region_pointer_release(window.region_surface, end)
                assert len(window._regions) == 1 and window._regions[0]["x"] == 3
                assert window._regions[0]["width"] == 24
                baseline_report = creator_regions.inspect(
                    source.read_bytes(), window._capture_bytes,
                    reference_sha256=window._reference.sha256,
                    recipe_sha256=window.info.semantic_sha256,
                    regions=window._regions, tolerance_radius=1)
                window._region_complete(window._render_generation, baseline_report, None)
                assert len(window._region_measurements) == 1
                previous_recipe = window.info.semantic_sha256
                revised_height = 48 if window.working["panel"]["height"] != 48 else 49
                window._change("/panel/height", revised_height)
                assert window._commit_pending()
                assert window.info.semantic_sha256 != previous_recipe
                assert len(window._regions) == 1 and len(window._region_measurements) == 1
                assert window._region_report is None
                window._capture_bytes = source.read_bytes()
                window._capture_size = (48, 48)
                newer_report = creator_regions.inspect(
                    source.read_bytes(), window._capture_bytes,
                    reference_sha256=window._reference.sha256,
                    recipe_sha256=window.info.semantic_sha256,
                    regions=window._regions, tolerance_radius=1)
                window._region_complete(window._render_generation, newer_report, None)
                assert len(window._region_measurements) == 2
                assert "Correction cycle" in window.region_cycle.get_text()
                assert "unchanged pixel error" in window.region_cycle.get_text()
                window._region_remove(0)
                assert not window._region_measurements
                # v0.7: no ML inference is necessary to verify that external
                # declarative proposals stay behind an explicit GTK approval.
                requested_height = (50 if window.working["panel"]["height"] != 50 else 51)
                untrusted = {
                    "mapping_version": 1, "source": "offline",
                    "reference_sha256": window._reference.sha256,
                    "recipe_sha256": window.info.semantic_sha256,
                    "reference_size": {"width": 48, "height": 48},
                    "regions": [], "notes": ["Explicitly reviewed mapping smoke"],
                    "suggestions": [{"path": "/panel/height", "value": requested_height,
                                     "confidence": 0.9,
                                     "evidence": "Fixture proposal; no screenshot semantics asserted"}],
                }
                imported = creator_mapping.import_proposals(
                    json.dumps(untrusted).encode("utf-8"),
                    reference_sha256=window._reference.sha256,
                    recipe_sha256=window.info.semantic_sha256,
                    size=(48, 48), manifest=window.baseline)
                assert imported["source"] == "external"
                window._mapping_set_result(imported)
                assert not window.mapping_apply.get_sensitive(), (
                    "Externally claimed confidence must never preselect a change")
                window._mapping_checks["/panel/height"].set_active(True)
                assert window.mapping_apply.get_sensitive()
                window._mapping_apply(None)
                assert window.pending["/panel/height"] == requested_height
                assert window._mapping is None
                assert window._commit_pending()
                assert recipes.load(str(window.info.path)).height == requested_height
                window._reference_unlink(None)
                assert not window.compare_btn.get_sensitive()
                assert window._reference is None
            # Handoff is explicitly confirmed, owner-private and offline in
            # this X11 smoke; never create a live compositor as part of CI.
            from unittest.mock import patch
            assert window.install_btn.get_sensitive()
            with patch.object(window, "_confirm_handoff", return_value=True):
                window.install_btn.clicked()
            assert recipes.load(window.info.recipe_id).recipe_id == window.info.recipe_id
            assert "Installed" in window.status.get_text()
            installed_id = window.info.recipe_id
            window.fork_btn.clicked()
            assert window.info.recipe_id != installed_id
            assert recipes.load(installed_id).recipe_id == installed_id
            assert "Not installed or applied" in window.status.get_text()
            forked_id = window.info.recipe_id
            # Exercise the actual GTK installed-rice picker, not only its
            # backend: an immutable new draft must open without switching.
            def accept_installed():
                dialogs = [item for item in Gtk.Window.list_toplevels()
                           if isinstance(item, Gtk.Dialog)
                           and item.get_title() == "Edit installed rice"]
                assert len(dialogs) == 1, "Installed-rice picker missing"
                dialogs[0].response(Gtk.ResponseType.OK)
                return False

            GLib.idle_add(accept_installed)
            window.open_installed_btn.clicked()
            assert window.info.recipe_id not in (installed_id, forked_id)
            assert recipes.load(installed_id).recipe_id == installed_id
            assert "Original untouched" in window.status.get_text()
            # Exercise the real GTK interaction state without launching a
            # compositor in CI. Nested process behavior has separate tests.
            from unittest.mock import Mock
            assert window.interactive_btn.get_sensitive()
            fake_session = Mock(draft=window.info)
            with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-gtk-smoke"}):
                window._actions()
                assert window.apply_btn.get_sensitive()
                with patch.object(creator_interactive, "launch", return_value=fake_session) as begin:
                    window.interactive_btn.clicked()
                    begin.assert_called_once()
                    assert "Close" in window.interactive_btn.get_label()
                    assert window._interactive_session is fake_session
                    assert not window.apply_btn.get_sensitive()
                    window.interactive_btn.clicked()
                    fake_session.stop.assert_called_once_with()
                    assert not window.interactive_btn.get_sensitive()
                    window._interactive_done(fake_session,
                        creator_interactive.PreviewResult(-15, True, ""))
                    assert window._interactive_session is None
                    assert window.interactive_btn.get_sensitive()
                    assert window.apply_btn.get_sensitive()
                    assert "Current rice" in window.status.get_text()
            window._actions()
            if not os.environ.get("WAYLAND_DISPLAY"):
                assert not window.apply_btn.get_sensitive()
                assert not window.restore_btn.get_sensitive()
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
