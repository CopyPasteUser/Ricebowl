#!/usr/bin/env python3
"""Scenario driver for smoke_sg4_creator_gui_roundtrip_labwc.sh (SG4 WP4.2).

Runs only inside that script's disposable labwc + private D-Bus session. It starts
the REAL GTK Rice Creator (`launcher.py creator`) twice, in two different private
profiles, and drives its widgets:

  * real compositor pointer events open the modal choosers (see the script header
    for why), AT-SPI `doAction` / EditableText / Selection operate everything else;
  * every receipt is observed independently: the accessibility tree, grim pixels of
    the real output, and the files/validated recipes the profiles end up with.

Every receipt line is "PASS: <cell>". Nothing is applied or installed live.
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

Atspi.set_timeout(8000, 8000)

ROOT = Path(os.environ["SG4G_ROOT"])
RUNTIME = Path(os.environ["SG4G_RUNTIME"])
CLICKER = os.environ["SG4G_CLICKER"]
WIDTH, HEIGHT = 1920, 1080
PACKS = RUNTIME / "packs"
SHOTS = RUNTIME / "shots"
TEMPLATE = "Heritage Composer"
TEMPLATE_KEY = "heritage-composer"
PROFILES = {name: RUNTIME / name for name in ("author", "importer")}
receipts: list[str] = []
creator: subprocess.Popen | None = None


class Fail(Exception):
    pass


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


def press(node, offset=(0, 0)) -> None:
    """A real compositor pointer click at the centre of a widget."""
    box = node.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
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
def start_creator(name: str) -> None:
    global creator
    stop_creator()
    log = open(RUNTIME / ("creator-%s.log" % name), "ab")
    creator = subprocess.Popen(
        ["/usr/bin/python3", str(ROOT / "launcher.py"), "creator"], env=profile_env(name),
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


def main() -> int:
    try:
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
    print("SG4 Creator GUI round trip: %d receipts PASS" % len(receipts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
