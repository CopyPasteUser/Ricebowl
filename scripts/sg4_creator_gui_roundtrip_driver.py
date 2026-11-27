#!/usr/bin/env python3
"""Scenario driver for smoke_sg4_creator_gui_roundtrip_labwc.sh (SG4 WP4.2).

Runs only inside that script's disposable labwc + private D-Bus session. Stage
``roundtrip`` (default) starts the REAL GTK Rice Creator (`launcher.py creator`)
twice, in two different private profiles, and drives its widgets:

  * real compositor pointer events open the modal choosers (see the script header
    for why), AT-SPI `doAction` / EditableText / Selection operate everything else;
  * every receipt is observed independently: the accessibility tree, grim pixels of
    the real output, and the files/validated recipes the profiles end up with.

Stage ``apply`` (see its docstring) drives the Creator's *Install / switch...*
dialogs against a real supervised nested session. Every receipt line is
"PASS: <cell>". Stage ``roundtrip`` applies or installs nothing live.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pyatspi
from gi.repository import Atspi, GLib

import gtk_keyboard

Atspi.set_timeout(8000, 8000)

ROOT = Path(os.environ["SG4G_ROOT"])
RUNTIME = Path(os.environ["SG4G_RUNTIME"])
CLICKER = os.environ["SG4G_CLICKER"]
WIDTH, HEIGHT = 1920, 1080
PACKS = RUNTIME / "packs"
SHOTS = RUNTIME / "shots"
TEMPLATE = "Heritage Composer"
TEMPLATE_KEY = "heritage-composer"
PROFILES = {name: RUNTIME / name for name in ("author", "importer", "keys", "session")}
receipts: list[str] = []
creator: subprocess.Popen | None = None


Fail = gtk_keyboard.Fail


def passed(cell: str) -> None:
    receipts.append(cell)
    print("PASS: " + cell, flush=True)


def require(condition, message: str) -> None:
    if not condition:
        raise Fail(message)


def wait_for(predicate, message: str, timeout: float = 10.0, step: float = 0.2):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except (LookupError, RuntimeError, OSError, GLib.Error, subprocess.SubprocessError):
            last = None
        if last:
            return last
        time.sleep(step)
    raise Fail("timeout: " + message)


# ------------------------------------------------------------- profiles ----
def profile_env(name: str) -> dict:
    base = PROFILES[name]
    env = dict(os.environ)
    env.update(HOME=str(base / "home"), XDG_CONFIG_HOME=str(base / "config"),
               XDG_STATE_HOME=str(base / "state"), XDG_DATA_HOME=str(base / "home/.local/share"))
    env.pop("XDG_CACHE_HOME", None)
    return env


def backend(name: str, code: str):
    """Run backend code in a profile (Creator's own modules, no GUI); JSON on stdout."""
    wrapped = ("import json, sys\nsys.path.insert(0, %r)\n" % str(ROOT)
               + "from macrice.de import creator_workspace, pack, recipes\n" + code)
    result = subprocess.run([sys.executable, "-I", "-c", wrapped], env=profile_env(name),
                            capture_output=True, text=True, timeout=60, cwd=str(RUNTIME))
    require(result.returncode == 0, "backend failed in %s: %s" % (name, result.stderr[-400:]))
    return json.loads(result.stdout.strip().splitlines()[-1])


def tree_digest(name: str) -> str:
    """Digest of every RiceBowl-owned file of a profile (relative name + content): the
    config and state trees. GTK's own per-user files (recently-used list, ...) are
    not RiceBowl state and may legitimately change while a file chooser is open."""
    digest = hashlib.sha256()
    base = PROFILES[name]
    for part in ("config", "state"):
        for path in sorted(p for p in (base / part).rglob("*") if p.is_file() or p.is_symlink()):
            digest.update(str(path.relative_to(base)).encode())
            if path.is_file():
                digest.update(path.read_bytes())
    ricebowl_elsewhere = sorted(str(p.relative_to(base)) for p in (base / "home").rglob("*")
                                if "ricebowl" in str(p.relative_to(base)).lower())
    require(ricebowl_elsewhere == [], "RiceBowl files appeared under HOME: %r" % ricebowl_elsewhere)
    return digest.hexdigest()


# --------------------------------------------------------------- AT-SPI ----
def _children(node, limit=400):
    for index in range(min(node.childCount, limit)):
        try:
            child = node.getChildAtIndex(index)
        except (LookupError, RuntimeError, GLib.Error):
            continue
        if child is not None:
            yield child


def application():
    desktop = pyatspi.Registry.getDesktop(0)
    for app in _children(desktop, 40):
        try:
            if app.name == "launcher.py":
                return app
        except (LookupError, RuntimeError, GLib.Error):
            continue
    return None


def walk(node, maximum=16):
    stack = [(node, 0)]
    visited = 0
    while stack and visited < 6000:
        current, depth = stack.pop()
        visited += 1
        yield current, depth
        if depth < maximum:
            stack.extend((child, depth + 1) for child in _children(current))


def showing(node) -> bool:
    try:
        return node.getState().contains(pyatspi.STATE_SHOWING)
    except (LookupError, RuntimeError, GLib.Error):
        return False


def find(role: str, name: str | None = None, prefix: str | None = None, under=None,
         visible: bool = True) -> list:
    root = under if under is not None else application()
    if root is None:
        return []
    found = []
    for node, _ in walk(root):
        try:
            if node.getRoleName() != role:
                continue
            title = node.name or ""
        except (LookupError, RuntimeError, GLib.Error):
            continue
        if name is not None and title != name:
            continue
        if prefix is not None and not title.startswith(prefix):
            continue
        if visible and not showing(node):
            continue
        found.append(node)
    return found


def one(role: str, name: str | None = None, prefix: str | None = None, under=None,
        timeout: float = 10.0, visible: bool = True):
    return wait_for(lambda: (lambda m: m[0] if len(m) == 1 else None)(
        find(role, name, prefix, under, visible)),
        "exactly one %s %r%s" % (role, name or "", prefix or ""), timeout)


def act(node, closes: bool = False) -> None:
    """AT-SPI doAction. A button that closes its dialog may vanish mid-call: that
    GError ("object does not exist") is the expected outcome only for closes=True."""
    try:
        action = node.queryAction()
        require(action.nActions >= 1, "no AT-SPI action on " + repr(node.name))
        require(action.doAction(0), "AT-SPI doAction refused on " + repr(node.name))
    except GLib.Error:
        if not closes:
            raise


def window_offset(dialog) -> tuple[int, int]:
    """Output position of a toplevel's AT-SPI origin. All windows sit at 0,0 without
    server decoration (labwc rule); a GTK3 CSD dialog's AT-SPI coordinates include
    its shadow margin, so its first content widget starts at the margin."""
    first = next(_children(dialog), None)
    box = first.queryComponent().getExtents(pyatspi.WINDOW_COORDS) if first else None
    if box is None or dialog.getRoleName() not in ("file chooser", "dialog"):
        return 0, 0
    return box.x, box.y


def press(node, offset=(0, 0), desktop: bool = False) -> None:
    """A real compositor pointer click at the centre of a widget. ``desktop`` uses AT-SPI
    desktop coordinates, which place a popover (its own surface) correctly; the toplevel
    sits at 0,0 by the labwc rule."""
    box = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS if desktop
                                           else pyatspi.WINDOW_COORDS)
    x = box.x + box.width // 2 - offset[0]
    y = box.y + box.height // 2 - offset[1]
    require(0 <= x < WIDTH and 0 <= y < HEIGHT, "widget %r is off screen at %d,%d" % (node.name, x, y))
    subprocess.run([CLICKER, str(x), str(y), str(WIDTH), str(HEIGHT)], check=True,
                   timeout=10, stdout=subprocess.DEVNULL)


def label_text(prefix: str) -> str | None:
    matches = find("label", prefix=prefix)
    return matches[0].name if matches else None


def shot(name: str):
    from PIL import Image
    path = SHOTS / (name + ".png")
    subprocess.run(["grim", str(path)], check=True, timeout=15)
    image = Image.open(path).convert("RGB")
    image.load()
    return image


def changed_fraction(first, second, box=None) -> float:
    from PIL import ImageChops
    if box is not None:
        first, second = first.crop(box), second.crop(box)
    pixels = list(ImageChops.difference(first, second).getdata())
    return sum(max(p) > 24 for p in pixels) / max(1, len(pixels))


# ------------------------------------------------------------- the app ----
def start_creator(name: str, display: str | None = None) -> None:
    global creator
    stop_creator()
    log = open(RUNTIME / ("creator-%s.log" % name), "ab")
    env = profile_env(name)
    if display is not None:
        env["WAYLAND_DISPLAY"] = display
    creator = subprocess.Popen(
        ["/usr/bin/python3", str(ROOT / "launcher.py"), "creator"], env=env,
        cwd=str(PACKS), stdout=log, stderr=subprocess.STDOUT)
    wait_for(lambda: find("frame", "Rice Creator · RiceBowl") and
             find("push button", "Import RicePack…"), "Creator window on the bus", 40)
    time.sleep(1.0)


def stop_creator() -> None:
    global creator
    if creator is not None and creator.poll() is None:
        creator.terminate()
        try:
            creator.wait(timeout=10)
        except subprocess.TimeoutExpired:
            creator.kill()
            creator.wait()
    creator = None
    wait_for(lambda: application() is None, "Creator left the accessibility bus", 10)


def open_modal(button_name: str, dialog_name: str):
    """Real pointer press on a button that opens a modal dialog; returns the dialog."""
    press(one("push button", button_name))
    return one("file chooser", dialog_name, timeout=20) if "RicePack" in dialog_name else \
        one("dialog", dialog_name, timeout=20)


def status_of(*prefixes: str) -> str:
    """The Creator status line (one label) once it starts with one of the prefixes."""
    return wait_for(lambda: next((t for t in (label_text(p) for p in prefixes) if t), None),
                    "status line starting %r" % (prefixes,), 20)


# ------------------------------------------------------------- scenario ----
def author_export() -> dict:
    """Author profile: create a Heritage Composer draft and export it through the GUI."""
    start_creator("author")
    act(one("push button", TEMPLATE))
    status_of("Private schema-v11 draft created")
    passed("author: template button creates a private v11 draft (status line says so)")
    drafts = backend("author", "print(json.dumps([[d.recipe_id, d.semantic_sha256, str(d.path)]"
                     " for d in creator_workspace.list_drafts()]))")
    require(len(drafts) == 1, "author profile does not hold exactly one draft: %r" % drafts)
    recipe_id, semantic, draft_path = drafts[0]

    destination = PACKS / ("3-%s.ricepack" % TEMPLATE_KEY)
    chooser = open_modal("Export RicePack…", "Export validated RicePack")
    # Export is a SAVE chooser: its name field takes the full destination path.
    name_entry = one("text", under=chooser, timeout=10)
    name_entry.queryEditableText().setTextContents(str(destination))
    act(one("push button", "Export RicePack", under=chooser), closes=True)
    review = one("dialog", "Review portable RicePack", timeout=20)
    export = one("push button", "Export reviewed bytes", under=review)
    require(not export.getState().contains(pyatspi.STATE_SENSITIVE),
            "export button is enabled before the review was acknowledged")
    act(one("check box", prefix="I reviewed the package contents", under=review))
    wait_for(lambda: export.getState().contains(pyatspi.STATE_SENSITIVE),
             "export enabled after the acknowledgement")
    act(export, closes=True)
    done = status_of("Reviewed RicePack created")
    require("Not installed or applied" in done, "export status is not honest: " + done)
    wait_for(destination.exists, "exported file on disk")
    inspected = backend("author", "print(json.dumps(pack.inspect_pack(__import__('pathlib').Path(%r))"
                        "['manifest']['recipe']))" % str(destination))
    require(inspected["semantic_sha256"] == semantic and inspected["id"] == recipe_id,
            "the pack carries a different recipe than the draft: %r" % inspected)
    passed("author: real Export RicePack... chooser + review dialog (acknowledgement gates the "
           "button) wrote %s; status: %r" % (destination.name, done[:70]))
    selection = backend("author", "print(json.dumps(recipes.current_selection()))")
    require(selection == ["classic", None], "export changed the saved selection: %r" % selection)
    stop_creator()
    return {"id": recipe_id, "semantic": semantic, "draft": draft_path,
            "archive": str(destination)}


def choose_file_row(chooser, row_index: int, expected_size: str) -> None:
    """Open chooser: click the `packs` place, then a file row, with real pointer clicks."""
    offset = window_offset(chooser)
    places = find("scroll pane", "Places", under=chooser)[0]
    place = next(n for n, _ in walk(places) if n.getRoleName() == "label" and n.name == PACKS.name)
    press(place, offset)
    table = one("table", "Files", under=chooser)
    wait_for(lambda: table.queryTable().nRows >= row_index + 1, "chooser lists the packs folder", 10)
    cells = table.queryTable()
    sizes = [cells.getAccessibleAt(row, 1).name for row in range(cells.nRows)]
    require(sizes[row_index] == expected_size,
            "row %d is not the expected file (sizes %r, wanted %r)" % (row_index, sizes, expected_size))
    # rows are 2 columns wide in name cells that expose no text: click its size cell
    press(cells.getAccessibleAt(row_index, 1), offset)


def import_via_gui(row_index: int, filename: str) -> None:
    size = GLib.format_size((PACKS / filename).stat().st_size)
    chooser = open_modal("Import RicePack…", "Import a RicePack")
    choose_file_row(chooser, row_index, size)
    inspect = one("push button", "Inspect RicePack", under=chooser)
    wait_for(lambda: inspect.getState().contains(pyatspi.STATE_SENSITIVE),
             "Inspect RicePack enabled once a file is selected")
    act(inspect, closes=True)


def importer_run(authored: dict) -> None:
    archive = Path(authored["archive"])
    garbage = PACKS / "1-garbage.ricepack"
    garbage.write_bytes(b"this is not a zip archive at all\n")
    truncated = PACKS / "2-truncated.ricepack"
    truncated.write_bytes(archive.read_bytes()[:-120])
    files = sorted(p.name for p in PACKS.glob("*.ricepack"))
    require(files == ["1-garbage.ricepack", "2-truncated.ricepack", archive.name],
            "unexpected pack folder: %r" % files)

    require(not (PROFILES["importer"] / "config/ricebowl").exists(),
            "the importing profile is not fresh")
    start_creator("importer")
    baseline = shot("importer-start")
    before = tree_digest("importer")

    # --- malformed archives: honest error in the GUI, nothing changes -------
    for index, filename, what in ((0, garbage.name, "not a zip archive"),
                                  (1, truncated.name, "truncated archive")):
        import_via_gui(index, filename)
        error = status_of("RicePack ")
        require("No session was changed" in error, "error does not say nothing changed: " + error)
        require(not find("alert", "Question"), "a malformed pack reached the import dialog")
        require("imported" not in error.lower().replace("not imported", ""),
                "error text claims an import: " + error)
        after = tree_digest("importer")
        require(after == before, "a malformed pack changed the importing profile (%s)" % what)
        listed = backend("importer", "print(json.dumps([r[0].id for r in recipes.imported_recipes()]"
                         " + [d.recipe_id for d in creator_workspace.list_drafts()]))")
        require(listed == [], "a malformed pack left an installed rice or draft: %r" % listed)
        passed("importer: %s -> GUI error %r; profile files byte-identical, no rice, no draft"
               % (what, error[:90]))
        # the error stays on screen: prove it is painted, not only in the tree
        shot("importer-error-" + str(index))

    # --- the valid pack ------------------------------------------------------
    import_via_gui(2, archive.name)
    confirm = one("alert", "Question", timeout=20)
    require(find("label", "Import this RicePack?", under=confirm), "wrong confirmation dialog")
    detail = " ".join(n.name or "" for n in find("label", under=confirm))
    require(authored["id"] in detail and authored["semantic"][:12] in detail,
            "the confirmation does not name the pack and its digest: %r" % detail)
    require("Neither desktop is changed" in detail, "confirmation hides what the import does")
    passed("importer: valid pack -> confirmation names %s and SHA-256 %s... and says nothing is applied"
           % (authored["id"], authored["semantic"][:12]))
    act(one("push button", "Import and edit", under=confirm), closes=True)
    done = status_of("RicePack imported; editing")
    require("Not applied" in done, "import status is not honest: " + done)
    passed("importer: Import and edit -> status %r" % done[:100])

    # --- the identical validated recipe --------------------------------------
    result = backend("importer", """
rices = [[r.recipe_id, str(p)] for r, p in recipes.imported_recipes()]
drafts = [[d.recipe_id, d.name, d.semantic_sha256, str(d.path)] for d in creator_workspace.list_drafts()]
print(json.dumps({"rices": rices, "drafts": drafts, "selection": recipes.current_selection()}))
""")
    require(len(result["rices"]) == 1, "expected one installed rice: %r" % result["rices"])
    rice_id, rice_path = result["rices"][0]
    # Both files are loaded through the product's strict validator; the validated
    # recipes (every field the shell consumes) must be equal. The stored JSON text
    # may differ only by normalisation (the default menu presentation is omitted).
    same = backend("importer", "import dataclasses\n"
                   "a = recipes.load(%r)\nb = recipes.load(%r)\n"
                   "print(json.dumps({'equal': a == b, 'schema': a.schema_version,"
                   " 'name': a.name, 'fields': len(dataclasses.fields(a))}))"
                   % (authored["draft"], rice_path))
    require(same["equal"], "the imported recipe is not equal to the authored one after validation")
    authored_json = json.loads(Path(authored["draft"]).read_text(encoding="utf-8"))
    installed_json = json.loads(Path(rice_path).read_text(encoding="utf-8"))
    normalised = sorted(k for k in set(authored_json) | set(installed_json)
                        if authored_json.get(k) != installed_json.get(k))
    require(normalised in ([], ["menu"]), "stored JSON differs beyond normalisation: %r" % normalised)
    require(rice_id == authored["id"], "installed rice ID differs: %r" % rice_id)
    require(len(result["drafts"]) == 1 and result["drafts"][0][0] != rice_id,
            "import did not open exactly one editable copy with a new ID: %r" % result["drafts"])
    require(result["selection"] == ["classic", None], "import changed the saved selection")
    passed("importer: installed recipe %s validates equal to the authored recipe (semantic SHA-256 %s..., "
           "%d validated fields, schema v%d); editable copy %s has a new ID; selection still classic"
           % (rice_id, authored["semantic"][:12], same["fields"], same["schema"],
              result["drafts"][0][0]))

    # --- the preview ----------------------------------------------------------
    after_import = shot("importer-imported")
    require(changed_fraction(baseline, after_import) > 0.01,
            "the window did not change after the import (no preview/inspector shown)")
    one("label", prefix="PROPERTIES")
    render = one("push button", "Render preview")
    wait_for(lambda: render.getState().contains(pyatspi.STATE_SENSITIVE),
             "Render preview enabled for the imported draft")
    act(render)
    caption = wait_for(lambda: label_text("Native RicePlate · "), "native preview caption", 120, 0.5)
    require("1366 × 768" in caption, "unexpected preview geometry: " + caption)
    status_of("Real native capture ready")
    preview = shot("importer-preview")
    require(len({preview.getpixel((x, y)) for x in range(300, 1000, 7)
                 for y in range(380, 700, 7)}) > 6, "the preview area is blank")
    # The imported rice's own look is in the capture: Heritage Composer's wallpaper
    # is the bundled "Classic Teal" (0,128,128); the schematic canvas would not show it.
    teal = sum(1 for pixel in preview.crop((300, 340, 1020, 680)).getdata()
               if abs(pixel[0] - 0) < 12 and abs(pixel[1] - 128) < 12 and abs(pixel[2] - 128) < 12)
    require(teal > 5000, "the native preview does not show the imported rice's teal desktop (%d px)" % teal)
    passed("importer: Render preview shows the real native capture of the imported rice (%s; "
           "%d px of its Classic Teal desktop on screen)" % (caption, teal))
    stop_creator()


# ===================================================================== keyboard ===
# Stage `keyboard`: REAL keyboard traversal and activation of the GTK Creator (WP4.2). Every key
# is a real compositor key from `wtype`; because GDK3 drops the highest keycode of wtype's
# throw-away keymap, each GTK key carries an unbound pad key (scripts/gtk_keyboard.py). Focus
# and results are read back from AT-SPI (the FOCUSED state, dialog roles, sensitivity) and from
# the profile's files; nothing is pressed with the pointer or an AT-SPI action except the
# file-name field of a save chooser (EditableText: typing a path is not what is under test).
TOOLBAR = ("← Previous version", "Review & save…", "Render preview", "Export RicePack…")
TEMPLATE_BUTTONS = ("Heritage Modern", "Orbit Studio", "Heritage Composer", "Orbit Composer",
                    "Classic shell", "Chrome shell")
SIDEBAR_BUTTONS = ("Edit installed rice…", "Import RicePack…", "Install / switch…")


def focused_stops() -> list[str]:
    return gtk_keyboard.focused_stops(application())


stop_name = gtk_keyboard.stop_name


def focused_names() -> list[str]:
    return [stop_name(s) for s in focused_stops()]


def key_describe() -> str:
    return "focus=%r status=%r" % (focused_stops(), [n.name for n in find("label")][:6])


def tab_to(name: str, limit: int = 60) -> int:
    """Real Tab presses until the control named `name` holds focus."""
    return gtk_keyboard.tab_to(name, focused_stops, limit=limit, describe=key_describe,
                               matches=lambda stop: stop_name(stop) == name)


def keyboard_stage() -> None:
    drafts_before: list = []
    start_creator("keys")
    baseline_digest = tree_digest("keys")

    # --- traversal: Tab visits every sensitive main control and wraps ------------------------
    first = wait_for(focused_stops, "a Creator control holds keyboard focus after launch", 20)
    require([stop_name(f) for f in first] == [TEMPLATE_BUTTONS[0]], "unexpected initial focus: %r" % first)
    trail = [first]
    previous = first
    for _ in range(80):
        gtk_keyboard.gtk_key("Tab", pause=0.25)
        # Every press must change the focused accessible; a stop that exposes no accessible
        # of its own (an inner widget of a combo box) reads as empty focus, itself a change.
        current = wait_for(lambda: (lambda now: [now] if now != previous else None)(focused_stops()),
                           "a real Tab moves keyboard focus off %r" % previous, 6)[0]
        previous = current
        # The first stop's position moves when focus scrolled the pane: wrap on its name.
        if [stop_name(c) for c in current] == [stop_name(f) for f in first]:
            break
        trail.append(current)
    else:
        raise Fail("Tab never wrapped to the first control; trail: %r" % trail)
    trail = [stop_name(t[0]) if t else "" for t in trail]
    named = [t for t in trail if t]
    missing = [n for n in TEMPLATE_BUTTONS + SIDEBAR_BUTTONS if n not in named]
    require(not missing, "Tab did not reach %r; trail: %r" % (missing, trail))
    require(not any(t in named for t in TOOLBAR),
            "Tab reached a toolbar button that has no draft to act on: %r" % trail)
    for name in TEMPLATE_BUTTONS + SIDEBAR_BUTTONS:
        require(named.count(name) == 1, "%r is focused %d times in one Tab cycle" % (
            name, named.count(name)))
    passed("keyboard: %d real Tab presses visit all %d template/sidebar controls once each and wrap to "
           "%r (trail: %s)" % (len(trail), len(TEMPLATE_BUTTONS) + len(SIDEBAR_BUTTONS), trail[0],
                               " > ".join(t or "·" for t in trail)))

    # --- Return opens a modal chooser, Escape closes it, nothing changed -----------------------
    # Negative control first: with focus on a non-template button an UNPADDED Tab (the one key of
    # wtype's keymap is its highest keycode) is dropped by GDK3, the padded one moves focus. (The
    # six template buttons are not usable for this: the window routes their Tab/Return itself.)
    tab_to("Import RicePack…")
    here = focused_stops()
    gtk_keyboard.unpadded_key("Tab")
    time.sleep(0.8)
    require(focused_stops() == here, "an unpadded single-key wtype Tab moved Creator focus: GDK no longer "
            "drops the highest keycode of a wtype keymap, so GTK_PAD_KEY can be retired")
    passed("keyboard: an unpadded one-key wtype Tab leaves focus on 'Import RicePack…' (GDK drops the highest "
           "keycode of wtype's keymap); the padded real Tab is what the traversal above used")
    gtk_keyboard.gtk_key("Return", pause=0.5)
    chooser = one("file chooser", "Import a RicePack", timeout=20)
    gtk_keyboard.gtk_key("Escape", pause=0.5)
    wait_for(lambda: not find("file chooser", "Import a RicePack"), "Escape closed the import chooser", 10)
    require(label_text("RicePack ") is None and tree_digest("keys") == baseline_digest,
            "cancelling the import chooser changed the profile or the status line")
    wait_for(lambda: focused_names() == ["Import RicePack…"],
             "keyboard focus returns to 'Import RicePack…' after the chooser closed", 10)
    passed("keyboard: Return on the focused 'Import RicePack…' opens the real chooser; Escape closes it and "
           "focus returns to the button; the profile's config/state is byte-identical, no status shown")

    # --- space activates a template (GTK's own binding: the window's key handler ignores space) ------
    tab_to(TEMPLATE_BUTTONS[2])
    gtk_keyboard.gtk_key("space", pause=0.5)
    created = status_of("Private schema-v11 draft created")
    drafts = backend("keys", "print(json.dumps([[d.recipe_id, d.name] for d in creator_workspace.list_drafts()]))")
    require(len(drafts) == 1 and drafts[0][1].startswith(TEMPLATE), "space did not create exactly one %s draft: %r" % (
        TEMPLATE, drafts))
    after_create = wait_for(focused_stops, "keyboard focus after creating the draft", 10)
    require(stop_name(after_create[0]) == TEMPLATE_BUTTONS[2],
            "keyboard focus left the activated template: %r" % after_create)
    for name in TOOLBAR[2:]:      # "Review & save…" waits for a change; "Previous version" for a history
        require(one("push button", name).getState().contains(pyatspi.STATE_SENSITIVE),
                "toolbar button %r is not enabled for the new draft" % name)
    passed("keyboard: Tab to %r + a real space creates one private draft (%r)" % (TEMPLATE_BUTTONS[2], created))

    # --- keyboard export: Return, Escape, then the whole review through the keyboard ---------------
    destination = PACKS / "keys-export.ricepack"

    def open_export_review():
        # The toolbar precedes the sidebar in the Tab order, and a loaded draft's inspector has
        # well over a hundred stops: a keyboard user reaches Export by tabbing round the window.
        reached = tab_to("Export RicePack…", limit=320)
        gtk_keyboard.gtk_key("Return", pause=0.5)
        chooser = one("file chooser", "Export validated RicePack", timeout=20)
        one("text", under=chooser, timeout=10).queryEditableText().setTextContents(str(destination))
        # The save chooser's default response is its "Export RicePack" button.
        gtk_keyboard.gtk_key("Return", pause=0.5)
        return one("dialog", "Review portable RicePack", timeout=20), reached

    review, reached = open_export_review()
    export = one("push button", "Export reviewed bytes", under=review)
    require(not export.getState().contains(pyatspi.STATE_SENSITIVE),
            "export button is enabled before the review was acknowledged")
    gtk_keyboard.gtk_key("Escape", pause=0.5)
    wait_for(lambda: not find("dialog", "Review portable RicePack"), "Escape closed the review dialog", 10)
    require(not destination.exists(), "Escape on the review dialog still wrote the RicePack")
    wait_for(lambda: focused_names() == ["Export RicePack…"],
             "keyboard focus returns to 'Export RicePack…' after the review closed", 10)
    passed("keyboard: %d real Tab presses (the loaded draft's inspector is in the chain) reach 'Export RicePack…'; "
           "Return opens the chooser, Return in it opens the review; Escape closes the review, the export "
           "button stayed disabled, no file was written, focus is back on the button" % reached)
    review, _ = open_export_review()
    acknowledgement = "I reviewed the package contents"
    gtk_keyboard.tab_to(acknowledgement, focused_stops, limit=12, describe=key_describe,
                        matches=lambda stop: stop_name(stop).startswith(acknowledgement))
    gtk_keyboard.gtk_key("space", pause=0.5)
    export = one("push button", "Export reviewed bytes", under=review)
    wait_for(lambda: export.getState().contains(pyatspi.STATE_SENSITIVE),
             "export enabled by the space key on the acknowledgement")
    require(not destination.exists(), "the file exists before the export button was pressed")
    tab_to("Export reviewed bytes", limit=8)
    gtk_keyboard.gtk_key("Return", pause=0.5)
    done = status_of("Reviewed RicePack created")
    require("Not installed or applied" in done, "export status is not honest: " + done)
    wait_for(destination.exists, "exported file on disk")
    manifest = backend("keys", "print(json.dumps(pack.inspect_pack(__import__('pathlib').Path(%r))"
                       "['manifest']['recipe']))" % str(destination))
    require(manifest["id"] == drafts[0][0], "the pack carries a different recipe than the draft: %r" % manifest)
    require(backend("keys", "print(json.dumps(recipes.current_selection()))") == ["classic", None],
            "the keyboard export changed the saved selection")
    passed("keyboard: second pass -- Tab to the acknowledgement + space enables the export, Tab to 'Export reviewed "
           "bytes' + Return writes %s (%s); status %r; selection still classic" % (
               destination.name, manifest["id"], done[:60]))
    stop_creator()


# ======================================================================= apply ===
# Stage `apply`: the Creator's "Install / switch..." dialogs against a REAL supervised
# nested session (`launcher.py de start --nested --panel native`, started by the script).
# One profile ("session") is shared by the supervisor and the Creator. Modal dialogs are
# the real Gtk.MessageDialog; buttons that open a modal are pressed with real pointer
# events, the dialog's own buttons by AT-SPI action (see the script header).
APPLY_W, APPLY_H = 1366, 768
PANEL = (0, APPLY_H - 64, APPLY_W, 64)           # the classic native panel strip
LIVE_PREFIX = "Live change"


def session_env(display: str = "wayland-0") -> dict:
    env = profile_env("session")
    env["WAYLAND_DISPLAY"] = display
    return env


def live_cli(*args: str) -> dict:
    """The supervisor through the shipped CLI (`de creator-live-*`), as the Creator uses it."""
    result = subprocess.run(
        ["/usr/bin/python3", str(ROOT / "launcher.py"), "de", *args, "--json"],
        env=session_env(), capture_output=True, text=True, timeout=90, cwd=str(RUNTIME))
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise Fail("live CLI %r gave no JSON: %s" % (args, (result.stdout + result.stderr)[-300:]))


def native_shells(recipe_path: str) -> int:
    """Live riceplate-native processes of this user that were started on a recipe file."""
    count = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != "riceplate-nativ":
                continue
            if recipe_path in (entry / "cmdline").read_bytes().decode(errors="replace"):
                count += 1
        except OSError:
            continue
    return count


def frame_box() -> tuple[int, int, int, int]:
    frame = find("frame", "Rice Creator · RiceBowl")[0]
    box = frame.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
    return box.x, box.y, box.width, box.height


def reveal(node) -> None:
    """Scroll a widget of the (now scrolling) editing pane into view the way a user would:
    GTK3 implements no AT-SPI scrollTo, so drive the scroll bars (AT-SPI Value) to their end."""
    if showing(node):
        return
    for bar in find("scroll bar", visible=False):
        value = bar.queryValue()
        if bar.getState().contains(pyatspi.STATE_VERTICAL):
            value.currentValue = value.maximumValue       # down to the sidebar's foot
        else:
            value.currentValue = value.minimumValue       # the sidebar is at the left edge
    wait_for(lambda: showing(node), "widget %r scrolled into view" % node.name, 5)


def open_wayland_menu(item: str):
    """Real pointer press on the *Install / switch...* menu button, then on one popover item."""
    menu = one("toggle button", "Install / switch…", visible=False)
    reveal(menu)
    press(menu, desktop=True)
    press(one("push button", item, timeout=10), desktop=True)


def live_dialog(title: str):
    """The confirmation dialog (a real modal MessageDialog) and its detail text."""
    dialog = one("alert", "Question", timeout=60)
    require(find("label", title, under=dialog), "wrong confirmation dialog (wanted %r)" % title)
    return dialog, " ".join(n.name or "" for n in find("label", under=dialog))


def strip_changed(before) -> float:
    return changed_fraction(before, shot("strip"), (PANEL[0], PANEL[1], PANEL[0] + PANEL[2],
                                                    PANEL[1] + PANEL[3]))


def wait_active(expected: str, why: str) -> dict:
    return wait_for(lambda: (lambda st: st if st.get("ok") and st.get("active") == expected else None)(
        live_cli("creator-live-status")), why, 60, 0.5)


def apply_stage() -> None:
    global WIDTH, HEIGHT
    WIDTH, HEIGHT = APPLY_W, APPLY_H
    status = live_cli("creator-live-status")
    require(status.get("ok") and status["active"] == "classic" and status["panel"] == "native"
            and not status["next_login_persisted"], "supervised session is not on nested classic: %r" % status)
    selection_before = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(selection_before == ["classic", None], "fresh profile selection is not classic")

    # --- the Creator in the supervised session: a draft must fit the 1366x768 output ----
    start_creator("session")
    act(one("push button", TEMPLATE))
    status_of("Private schema-v11 draft created")
    time.sleep(1.0)
    x, y, w, h = frame_box()
    require(x >= 0 and y >= 0 and x + w <= APPLY_W and y + h <= APPLY_H,
            "the Creator window runs past the %dx%d output: %r" % (APPLY_W, APPLY_H, (x, y, w, h)))
    # The classic panel as it looks with the Creator's task button on it: the baseline every
    # later panel comparison is made against.
    classic_panel = shot("apply-classic")
    drafts = backend("session", "print(json.dumps([[d.recipe_id, d.semantic_sha256, d.name, str(d.path)]"
                     " for d in creator_workspace.list_drafts()]))")
    require(len(drafts) == 1, "expected exactly one draft: %r" % drafts)
    rice_id, sha, draft_name, _draft_path = drafts[0]
    passed("apply: with a draft loaded the real Creator window is %dx%d at %d,%d, inside the %dx%d output "
           "(toolbar and status stay fixed; the editing panes scroll)" % (w, h, x, y, APPLY_W, APPLY_H))

    # --- Install saved version... : the real confirmation dialog ---------------------
    open_wayland_menu("Install saved version…")
    dialog, detail = live_dialog("Install this saved rice?")
    require(rice_id in detail and sha[:12] in detail and "will not change either desktop" in detail,
            "install dialog does not name the version or what it does: %r" % detail)
    act(one("push button", "Install version", under=dialog), closes=True)
    done = status_of("Installed ")
    require(done == "Installed %s. No desktop or login changed." % rice_id, "install status: " + done)
    installed = backend("session", "print(json.dumps([[r.recipe_id, str(p)] for r, p in recipes.imported_recipes()]))")
    require([row[0] for row in installed] == [rice_id], "install did not add exactly the draft: %r" % installed)
    recipe_path = installed[0][1]
    require(backend("session", "print(json.dumps(recipes.current_selection()))") == ["classic", None]
            and live_cli("creator-live-status")["active"] == "classic" and native_shells(recipe_path) == 0,
            "installing changed the selection or the running desktop")
    passed("apply: Install saved version... -> real dialog names %s and SHA-256 %s...; status %r; "
           "selection and running desktop still classic" % (rice_id, sha[:12], done))

    # --- NEGATIVE 1: cancelled apply -------------------------------------------------
    open_wayland_menu("Apply in Wayland…")
    dialog, detail = live_dialog("Apply this saved rice to Wayland?")
    require(rice_id in detail and "Current rice: classic" in detail
            and "nested session; the choice will not persist" in detail,
            "apply dialog is not honest about the target/nesting: %r" % detail)
    act(one("push button", "Cancel", under=dialog), closes=True)
    cancelled = status_of("Live change cancelled")
    require(cancelled == "Live change cancelled. Desktop unchanged.", cancelled)
    st = live_cli("creator-live-status")
    require(st["active"] == "classic" and native_shells(recipe_path) == 0
            and backend("session", "print(json.dumps(recipes.current_selection()))") == ["classic", None],
            "a cancelled apply changed the session: %r" % st)
    require(strip_changed(classic_panel) < 0.02, "a cancelled apply repainted the panel")
    passed("apply: cancelled apply dialog -> %r; supervisor still classic, no shell for %s, panel pixels "
           "unchanged" % (cancelled, rice_id))

    # --- NEGATIVE 2: the supervisor refuses after confirmation (active rice moved) --------
    open_wayland_menu("Apply in Wayland…")
    dialog, _ = live_dialog("Apply this saved rice to Wayland?")
    moved = live_cli("creator-live-apply", "--recipe", rice_id, "--expect-sha256", sha,
                     "--expect-active", "classic")      # the desktop moves while the dialog is open
    require(moved.get("ok") and moved["active"] == rice_id, "could not move the desktop: %r" % moved)
    act(one("push button", "Apply live", under=dialog), closes=True)
    refused = status_of("Live change not confirmed", "Active Wayland rice")
    require(refused.startswith("Live change not confirmed: ") and "Active Wayland rice" not in refused,
            "a refused apply is not an honest error: " + refused)
    st = live_cli("creator-live-status")
    require(st["active"] == rice_id and st["previous"] == "classic",
            "the refused apply changed the supervisor's state: %r" % st)
    passed("apply: apply refused after confirmation (active rice moved meanwhile) -> %r; supervisor "
           "state exactly as the other caller left it" % refused[:110])

    # --- GUI restore (undoes the CLI move) --------------------------------------------
    open_wayland_menu("Restore previous rice…")
    dialog, detail = live_dialog("Restore the previous Wayland rice?")
    require("Current: %s" % rice_id in detail and "Restore: classic" in detail, "restore dialog: %r" % detail)
    act(one("push button", "Restore live", under=dialog), closes=True)
    restored = status_of("Active Wayland rice")
    require(restored.startswith("Active Wayland rice: classic."), restored)
    wait_active("classic", "supervisor back on classic after the GUI restore")
    wait_for(lambda: native_shells(recipe_path) == 0, "the applied rice's native shell ends on restore", 20)
    passed("apply: Restore previous rice... dialog (names current %s and previous classic) -> %r; the "
           "shell of %s is gone" % (rice_id, restored[:60], rice_id))

    # --- the real apply, then the real restore, both through the GUI -----------------------
    open_wayland_menu("Apply in Wayland…")
    dialog, _ = live_dialog("Apply this saved rice to Wayland?")
    act(one("push button", "Apply live", under=dialog), closes=True)
    done = wait_for(lambda: label_text("Active Wayland rice:") or label_text("Live change not confirmed"),
                    "apply status", 90, 0.5)
    require(done.startswith("Active Wayland rice: %s." % rice_id), "apply failed in the GUI: " + done)
    st = wait_active(rice_id, "supervisor on the applied rice")
    require(st["previous"] == "classic" and st["panel"] == "native" and not st["next_login_persisted"],
            "supervisor state after apply: %r" % st)
    require(native_shells(recipe_path) == 1, "expected exactly one native shell for %s" % rice_id)
    time.sleep(1.0)
    require(strip_changed(classic_panel) > 0.02, "the panel pixels equal classic after the apply")
    require(backend("session", "print(json.dumps(recipes.current_selection()))") == ["classic", None],
            "a nested apply persisted a next-login selection")
    passed("apply: Apply in Wayland... confirmed -> %r; supervisor active=%s previous=classic, exactly "
           "one native shell, panel pixels differ from classic, nothing persisted for next login"
           % (done[:60], rice_id))
    open_wayland_menu("Restore previous rice…")
    dialog, _ = live_dialog("Restore the previous Wayland rice?")
    act(one("push button", "Restore live", under=dialog), closes=True)
    restored = wait_for(lambda: label_text("Active Wayland rice: classic")
                        or label_text("Live change not confirmed"), "restore status", 90, 0.5)
    require(restored.startswith("Active Wayland rice: classic."), "restore failed in the GUI: " + restored)
    wait_active("classic", "supervisor on classic after restore")
    wait_for(lambda: native_shells(recipe_path) == 0, "the applied rice's native shell ends on restore", 20)
    time.sleep(1.0)
    require(strip_changed(classic_panel) < 0.02, "the restored panel differs from the original classic panel")
    passed("apply: GUI restore -> %r; supervisor classic, native shell gone, panel pixels equal the "
           "original classic panel" % restored[:60])
    stop_creator()

    # --- NEGATIVE 3: supervisor unavailable ---------------------------------------------
    # A second display name for the same compositor socket has no supervisor socket
    # (ricebowl-live-<display>.sock), exactly what a Creator outside the session sees.
    runtime_dir = Path(os.environ["XDG_RUNTIME_DIR"])
    alias = runtime_dir / "wayland-1"
    if not alias.exists():
        alias.symlink_to("wayland-0")
    start_creator("session", "wayland-1")
    act(one("push button", prefix=draft_name))          # reopen the saved draft
    wait_for(lambda: find("label", prefix="Editing "), "draft reopened", 20)
    before_strip = shot("apply-unavailable-before")
    open_wayland_menu("Apply in Wayland…")
    unavailable = status_of(LIVE_PREFIX)
    require(unavailable.startswith("Live change unavailable: "), "unexpected status: " + unavailable)
    require(not find("alert", "Question"), "an apply dialog opened without a supervisor")
    st = live_cli("creator-live-status")
    require(st["active"] == "classic" and native_shells(recipe_path) == 0, "session changed: %r" % st)
    require(changed_fraction(before_strip, shot("apply-unavailable-after"), (PANEL[0], PANEL[1], PANEL[0] + PANEL[2], PANEL[1] + PANEL[3])) < 0.02,
            "the panel changed")
    passed("apply: supervisor unavailable -> %r; no dialog opened, session untouched" % unavailable[:110])
    stop_creator()


# ======================================================================== login ===
# Stage `login` (scripts/smoke_sg4_creator_full_login_labwc.sh): the Creator against the FULL,
# non-nested session that the packaged login script started as the top-level compositor.
def proc_env(pid: int) -> dict:
    try:
        raw = Path("/proc/%d/environ" % pid).read_bytes()
    except OSError:
        return {}
    return dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)


def runtime_processes() -> dict[int, tuple[str, str]]:
    """Processes of this user that belong to the smoke's disposable runtime directory
    (their environment carries its XDG_RUNTIME_DIR): pid -> (comm, command line)."""
    mine = os.environ["XDG_RUNTIME_DIR"]
    found = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            if proc_env(int(entry.name)).get("XDG_RUNTIME_DIR") != mine:
                continue
            state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
            if state in ("Z", "X"):
                continue
            found[int(entry.name)] = ((entry / "comm").read_text().strip(),
                                      (entry / "cmdline").read_bytes().decode(errors="replace").replace("\0", " "))
        except OSError:
            continue
    return found


OWNED_COMMS = ("labwc", "riceplate-nativ", "mako", "swaybg", "swayidle", "waybar", "swaylock")


def session_processes() -> dict[int, tuple[str, str]]:
    return {pid: (name, cmd) for pid, (name, cmd) in runtime_processes().items()
            if name in OWNED_COMMS or "launcher.py de " in cmd}


def named(processes: dict, comm: str) -> list[int]:
    return sorted(pid for pid, (name, _cmd) in processes.items() if name == comm)


def profile_files() -> dict[str, str]:
    """Every file below the session profile (config, state, data), relative path -> SHA-256."""
    base = PROFILES["session"]
    files = {}
    for path in sorted(base.rglob("*")):
        relative = str(path.relative_to(base))
        if path.is_symlink():
            files[relative] = "symlink:" + os.readlink(path)
        elif path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def owned_runtime_entries(runtime_dir: Path) -> list[str]:
    """Runtime-directory entries that belong to the RiceBowl session (compositor socket and
    lock, the supervisor socket, the private labwc/plate/pop directories)."""
    return sorted(p.name for p in runtime_dir.iterdir()
                  if p.name.startswith(("ricebowl", "wayland-")))


LOGIN_STATE = RUNTIME / "login-state.json"
LOGIN_PROFILE_FILES = ("config/ricebowl/recipes/.active-recipe", "config/ricebowl/recipes/.active-recipe.lock")


def login_prologue() -> tuple[int, dict, dict]:
    """The session is a real top-level full login (not nested, not a preview). Returns the
    session pid, the process table and the pids of the long-lived session processes."""
    global WIDTH, HEIGHT
    WIDTH, HEIGHT = APPLY_W, APPLY_H
    session_pid = int(os.environ["SG4G_SESSION_PID"])
    procs = runtime_processes()
    compositors = named(procs, "labwc")
    require(compositors == [session_pid], "expected exactly the login's own labwc (pid %d): %r" % (
        session_pid, compositors))
    env = proc_env(session_pid)
    require(env.get("RICEBOWL_DM_SESSION") == "1" and env.get("RICEBOWL_DE_NESTED") == "0"
            and env.get("WLR_BACKENDS") == "headless" and "WAYLAND_DISPLAY" not in env
            and env.get("RICEBOWL_DE_PANEL") == "native" and env.get("RICEBOWL_DE_LIVE") == "1",
            "labwc did not start as the top-level full-login session: %r" % {
                k: v for k, v in env.items() if k.startswith(("RICEBOWL", "WLR", "WAYLAND"))})
    shells = named(procs, "riceplate-nativ")
    require(len(shells) == 1, "expected exactly one native shell: %r" % shells)
    status = live_cli("creator-live-status")
    require(status.get("ok") and status["panel"] == "native" and status["next_login_persisted"] is True,
            "the full-login supervisor does not report a persisting native session: %r" % status)
    services = status["services"]
    require(services.get("lock_guard") == "running" and services.get("notifications") == "running",
            "the full-login session does not own its lock guard / notification host: %r" % services)
    require(named(procs, "swayidle") and named(procs, "mako") and named(procs, "swaybg"),
            "swayidle/mako/swaybg are not running in the session: %r" % sorted(
                {name for name, _ in procs.values()}))
    pids = {name: named(procs, name) for name in ("labwc", "mako", "swayidle", "swaybg", "riceplate-nativ")}
    passed("login[%s]: the packaged login script started a top-level labwc (pid %d, headless backend, "
           "RICEBOWL_DM_SESSION=1, RICEBOWL_DE_NESTED=0, no WAYLAND_DISPLAY) with exactly one "
           "riceplate-native, swaybg, Mako and the swayidle lock guard; supervisor active=%s "
           "next_login_persisted=true, lock guard %s, notifications %s, authorization %s (no agent "
           "installed here)" % (sys.argv[2], session_pid, status["active"], services["lock_guard"],
                                services["notifications"], services.get("authorization")))
    return session_pid, status, pids


def live_state() -> dict:
    try:
        return json.loads(LOGIN_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_live_state(**values) -> None:
    state = live_state()
    state.update(values)
    LOGIN_STATE.write_text(json.dumps(state), encoding="utf-8")


def saved_shot(name: str):
    from PIL import Image
    image = Image.open(SHOTS / (name + ".png")).convert("RGB")
    image.load()
    return image


def residue_check(files_before: dict, *, rice: str | None) -> None:
    """After a logout: no process, no runtime entry, and in the profile only what the user
    asked for (the installed rice and its draft) plus the selection state file."""
    runtime_dir = Path(os.environ["XDG_RUNTIME_DIR"])
    require(not session_processes(), "processes of the session survived the logout: %r" % session_processes())
    left = owned_runtime_entries(runtime_dir) + sorted(
        p.name for p in runtime_dir.iterdir() if p.name.startswith("ricebowl"))
    require(not left, "the session left runtime entries behind: %r" % left)
    after = profile_files()
    removed = sorted(set(files_before) - set(after))
    changed = sorted(k for k in files_before if k in after and files_before[k] != after[k]
                     and k not in LOGIN_PROFILE_FILES)       # the selection state is rewritten
    added = sorted(set(after) - set(files_before))
    expected = {"config/ricebowl/recipes/%s.json" % rice} if rice else set()
    unexpected = [k for k in added if k not in expected and k not in LOGIN_PROFILE_FILES
                  and not k.startswith("state/ricebowl/creator/drafts/")]
    require(not removed and not changed and not unexpected,
            "unexpected profile residue: removed %r changed %r added %r" % (removed, changed, unexpected))


def login_roundtrip() -> None:
    """Session 1: install, apply and restore through the real Creator, then log out."""
    session_pid, status, pids_before = login_prologue()
    require(status["active"] == "classic" and not status["can_restore"], "fresh login: %r" % status)
    runtime_dir = Path(os.environ["XDG_RUNTIME_DIR"])
    selection_before = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(selection_before == ["classic", None], "fresh login selection is not classic: %r" % selection_before)
    files_before = profile_files()
    require(owned_runtime_entries(runtime_dir), "no session runtime entries before the Creator")

    # --- the Creator inside the login: draft, install, apply -------------------------------------
    start_creator("session")
    act(one("push button", TEMPLATE))
    status_of("Private schema-v11 draft created")
    time.sleep(1.0)
    classic_panel = shot("login-classic")
    drafts = backend("session", "print(json.dumps([[d.recipe_id, d.semantic_sha256, d.name] "
                     "for d in creator_workspace.list_drafts()]))")
    require(len(drafts) == 1, "expected exactly one draft: %r" % drafts)
    rice_id, sha, _draft_name = drafts[0]

    open_wayland_menu("Install saved version…")
    dialog, detail = live_dialog("Install this saved rice?")
    act(one("push button", "Install version", under=dialog), closes=True)
    done = status_of("Installed ")
    require(done == "Installed %s. No desktop or login changed." % rice_id, "install status: " + done)
    installed = backend("session", "print(json.dumps([[r.recipe_id, str(p)] for r, p in recipes.imported_recipes()]))")
    require([row[0] for row in installed] == [rice_id], "install did not add exactly the draft: %r" % installed)
    recipe_path = installed[0][1]
    require(backend("session", "print(json.dumps(recipes.current_selection()))") == ["classic", None]
            and native_shells(recipe_path) == 0, "installing changed the next-login selection or the desktop")

    open_wayland_menu("Apply in Wayland…")
    dialog, detail = live_dialog("Apply this saved rice to Wayland?")
    require(rice_id in detail and "Current rice: classic" in detail
            and "The choice also persists for the next login." in detail and "nested" not in detail,
            "the apply dialog does not describe a persisting full-login apply: %r" % detail)
    act(one("push button", "Apply live", under=dialog), closes=True)
    done = wait_for(lambda: label_text("Active Wayland rice:") or label_text("Live change not confirmed"),
                    "apply status", 120, 0.5)
    require(done.startswith("Active Wayland rice: %s." % rice_id), "apply failed in the GUI: " + done)
    st = wait_active(rice_id, "supervisor on the applied rice")
    require(st["previous"] == "classic" and st["panel"] == "native" and st["next_login_persisted"] is True,
            "supervisor state after apply: %r" % st)
    time.sleep(1.0)
    now = runtime_processes()
    require(native_shells(recipe_path) == 1 and len(named(now, "riceplate-nativ")) == 1,
            "expected exactly one native shell, the applied rice's: %r" % named(now, "riceplate-nativ"))
    require(named(now, "riceplate-nativ") != pids_before["riceplate-nativ"], "the native shell was not replaced")
    require(named(now, "labwc") == pids_before["labwc"] and named(now, "mako") == pids_before["mako"]
            and named(now, "swayidle") == pids_before["swayidle"],
            "the apply restarted the compositor, Mako or the lock guard: %r" % {
                k: named(now, k) for k in ("labwc", "mako", "swayidle")})
    require(len(named(now, "swaybg")) == 1 and named(now, "swaybg") != pids_before["swaybg"],
            "the wallpaper process was not replaced exactly once")
    require(strip_changed(classic_panel) > 0.02, "the panel pixels equal classic after the apply")
    persisted = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(persisted == [rice_id, "classic"],
            "the full-login apply did not persist the next-login selection: %r" % persisted)
    passed("login[roundtrip]: Creator Apply in Wayland (dialog says the choice persists for the next login) -> "
           "%r; supervisor active=%s previous=classic; one new riceplate-native and one new swaybg, "
           "labwc/Mako/swayidle pids unchanged; panel pixels differ from classic; next-login selection "
           "now %r" % (done[:48], rice_id, persisted))

    # --- restore through the GUI ---------------------------------------------------------------------
    open_wayland_menu("Restore previous rice…")
    dialog, detail = live_dialog("Restore the previous Wayland rice?")
    require("Current: %s" % rice_id in detail and "Restore: classic" in detail, "restore dialog: %r" % detail)
    act(one("push button", "Restore live", under=dialog), closes=True)
    restored = wait_for(lambda: label_text("Active Wayland rice: classic")
                        or label_text("Live change not confirmed"), "restore status", 120, 0.5)
    require(restored.startswith("Active Wayland rice: classic."), "restore failed in the GUI: " + restored)
    wait_active("classic", "supervisor on classic after restore")
    wait_for(lambda: native_shells(recipe_path) == 0, "the applied rice's native shell ends on restore", 30)
    time.sleep(1.0)
    now = runtime_processes()
    require(len(named(now, "riceplate-nativ")) == 1 and len(named(now, "swaybg")) == 1
            and named(now, "labwc") == pids_before["labwc"],
            "restore left a duplicate shell/wallpaper or restarted labwc: %r" % {
                k: named(now, k) for k in ("riceplate-nativ", "swaybg", "labwc")})
    require(strip_changed(classic_panel) < 0.02, "the restored panel differs from the original classic panel")
    selection_after = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(selection_after[0] == "classic", "the restore did not persist classic for the next login: %r" % selection_after)
    passed("login[roundtrip]: Creator Restore previous rice -> %r; supervisor classic, native shell of %s gone, "
           "one riceplate-native and one swaybg, panel pixels equal the original classic panel; next-login "
           "selection back to %r (previous pointer %r kept for a rollback)" % (
               restored[:40], rice_id, selection_after[0], selection_after[1]))
    stop_creator()
    save_live_state(rice_id=rice_id, sha=sha, recipe_path=recipe_path, draft_name=_draft_name)

    logout(session_pid)
    residue_check(files_before, rice=rice_id)
    passed("login[roundtrip]: logout (labwc --exit) ends the login: no labwc/riceplate-native/swaybg/Mako/"
           "swayidle process, no ricebowl-* or wayland-0 runtime entry; the profile holds only the installed rice, "
           "its draft and the selection state (classic)")


def login_persist() -> None:
    """Session 2: apply again and log out WITHOUT restoring: the choice persists."""
    session_pid, status, _pids = login_prologue()
    state = live_state()
    rice_id, recipe_path = state["rice_id"], state["recipe_path"]
    require(status["active"] == "classic", "the next login after a restore is not classic: %r" % status)
    require(native_shells(recipe_path) == 0, "a native shell of the installed rice is running before the apply")
    start_creator("session")
    act(one("push button", prefix=state["draft_name"]))          # reopen the saved draft
    wait_for(lambda: find("label", prefix="Editing "), "draft reopened", 20)
    time.sleep(1.0)
    open_wayland_menu("Apply in Wayland…")
    dialog, detail = live_dialog("Apply this saved rice to Wayland?")
    require("The choice also persists for the next login." in detail, "apply dialog: %r" % detail)
    act(one("push button", "Apply live", under=dialog), closes=True)
    done = wait_for(lambda: label_text("Active Wayland rice:") or label_text("Live change not confirmed"),
                    "apply status", 120, 0.5)
    require(done.startswith("Active Wayland rice: %s." % rice_id), "apply failed in the GUI: " + done)
    wait_active(rice_id, "supervisor on the applied rice")
    require(native_shells(recipe_path) == 1, "expected one native shell for the applied rice")
    stop_creator()           # the panel shot must not carry the Creator's task button
    time.sleep(1.5)
    shot("login-applied")
    selection = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(selection == [rice_id, "classic"], "selection after the second apply: %r" % selection)
    logout(session_pid)
    require(not session_processes() and not owned_runtime_entries(Path(os.environ["XDG_RUNTIME_DIR"])),
            "residue after the logout of the applied session")
    passed("login[persist]: second session applies %s through the Creator and logs out WITHOUT restoring; "
           "next-login selection %r" % (rice_id, selection))


def login_relogin() -> None:
    """Session 3 = the next login: it must come up on the applied rice; restore it, log out."""
    session_pid, status, pids_before = login_prologue()
    state = live_state()
    rice_id, recipe_path = state["rice_id"], state["recipe_path"]
    require(status["active"] == rice_id and status["previous"] == "classic" and status["can_restore"],
            "the next login did not start on the applied rice with a classic rollback: %r" % status)
    time.sleep(1.5)
    require(native_shells(recipe_path) == 1 and len(named(runtime_processes(), "riceplate-nativ")) == 1,
            "the next login does not run exactly one native shell of %s" % rice_id)
    applied_now = shot("login-relogin-applied")
    require(changed_fraction(saved_shot("login-applied"), applied_now,
                             (0, APPLY_H - 64, APPLY_W, APPLY_H)) < 0.02,
            "the next login's panel differs from the live-applied panel")
    passed("login[relogin]: the next login starts on %s (supervisor active=%s previous=classic can_restore), "
           "exactly one native shell on that recipe, panel pixels equal the live-applied panel of the previous "
           "login" % (rice_id, rice_id))
    files_before = profile_files()
    start_creator("session")
    time.sleep(1.0)
    classic_panel = saved_shot("login-classic")
    open_wayland_menu("Restore previous rice…")
    dialog, detail = live_dialog("Restore the previous Wayland rice?")
    require("Current: %s" % rice_id in detail and "Restore: classic" in detail, "restore dialog: %r" % detail)
    act(one("push button", "Restore live", under=dialog), closes=True)
    restored = wait_for(lambda: label_text("Active Wayland rice: classic")
                        or label_text("Live change not confirmed"), "restore status", 120, 0.5)
    require(restored.startswith("Active Wayland rice: classic."), "restore failed in the GUI: " + restored)
    wait_active("classic", "supervisor on classic after restore")
    wait_for(lambda: native_shells(recipe_path) == 0, "the applied rice's native shell ends on restore", 30)
    time.sleep(1.0)
    require(strip_changed(classic_panel) < 0.02, "the restored panel differs from the original classic panel")
    selection = backend("session", "print(json.dumps(recipes.current_selection()))")
    require(selection[0] == "classic", "the restore did not persist classic: %r" % selection)
    stop_creator()
    logout(session_pid)
    residue_check(files_before, rice=rice_id)
    passed("login[relogin]: Creator Restore in the next login -> classic, native shell gone, panel pixels equal "
           "the original classic panel; next-login selection %r; after the logout no process, no runtime entry "
           "and no profile change beyond the selection state" % (selection[0],))


def login_stage() -> None:
    {"roundtrip": login_roundtrip, "persist": login_persist, "relogin": login_relogin}[sys.argv[2]]()


def logout(session_pid: int) -> None:
    """End the session the way a logout does (`labwc --exit`) and wait for the login to end."""
    subprocess.run(["labwc", "--exit"], env=dict(os.environ, LABWC_PID=str(session_pid)),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)

    def ended():
        try:
            state = Path("/proc/%d/stat" % session_pid).read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return True
        return state in ("Z", "X")
    wait_for(ended, "the login session ends after labwc --exit", 30, 0.2)
    wait_for(lambda: not session_processes(), "no process of the session is left running", 20, 0.3)



def main() -> int:
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "apply":
            apply_stage()
        elif len(sys.argv) > 1 and sys.argv[1] == "keyboard":
            keyboard_stage()
        elif len(sys.argv) > 1 and sys.argv[1] == "login":
            login_stage()
        else:
            authored = author_export()
            importer_run(authored)
    except Fail as failure:
        print("SG4 Creator GUI smoke FAILED: %s" % failure, file=sys.stderr)
        try:
            subprocess.run(["grim", str(SHOTS / "failure.png")], timeout=10)
            for node, depth in list(walk(application() or pyatspi.Registry.getDesktop(0), 6))[:80]:
                print("  " * depth + "%s %r" % (node.getRoleName(), node.name), file=sys.stderr)
        except Exception as error:  # diagnostics only
            print("diagnostics failed: %r" % error, file=sys.stderr)
        return 1
    finally:
        try:
            stop_creator()
        except Fail:
            pass
    print("SG4 Creator GUI %s: %d receipts PASS" % (sys.argv[1] if len(sys.argv) > 1 else "round trip", len(receipts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
