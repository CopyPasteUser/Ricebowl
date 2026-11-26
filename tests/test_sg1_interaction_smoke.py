"""Structure and fixture tests for the SG1 WP1.2-1.7 interaction compositor smoke.

The compositor receipts themselves run in `scripts/smoke_sg1_interaction_labwc.sh`
(real labwc, needs the release binaries); these tests keep its contract from
silently eroding on machines without a compositor: syntax, stage coverage,
workflow wiring and the plain-item/`item-error` modes of the SNI fixture on a
private D-Bus session.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts/smoke_sg1_interaction_labwc.sh"
PROVIDER = ROOT / "scripts/fixtures/sg1_sni_provider.py"
WORKFLOW = ROOT / ".github/workflows/riceplate-native.yml"

PLAIN_ITEM_CHECK = r"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from gi.repository import Gio, GLib

provider = sys.argv[1]
service = "org.ricebowl.SNIFixture"
conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)

with tempfile.TemporaryDirectory(prefix="sg1-plain-item-") as dirname:
    directory = Path(dirname)
    receipts = directory / "receipts.jsonl"
    process = subprocess.Popen(
        ["/usr/bin/python3", provider, "--no-register", "--plain",
         "--ready", str(directory / "ready"), "--receipts", str(receipts),
         "--generation", "plain"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def call(path, interface, method, args, signature):
        return conn.call_sync(
            service, path, interface, method, args,
            GLib.VariantType.new(signature), Gio.DBusCallFlags.NONE, 3000, None)

    try:
        deadline = time.monotonic() + 4
        while True:
            assert process.poll() is None, process.stderr.read().decode()
            try:
                conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", "GetNameOwner",
                               GLib.Variant("(s)", (service,)),
                               GLib.VariantType.new("(s)"),
                               Gio.DBusCallFlags.NONE, 250, None)
                break
            except GLib.Error:
                assert time.monotonic() < deadline, "fixture never owned its name"
                time.sleep(.05)
        item = "org.kde.StatusNotifierItem"
        def get(name):
            return call("/StatusNotifierItem", "org.freedesktop.DBus.Properties",
                        "Get", GLib.Variant("(ss)", (item, name)), "(v)").unpack()[0]
        assert get("ItemIsMenu") is False
        try:
            get("Menu")
        except GLib.Error:
            pass
        else:
            raise AssertionError("a plain item must not advertise a DBusMenu")
        call("/StatusNotifierItem", item, "ContextMenu",
             GLib.Variant("(ii)", (1200, 750)), "()")
        call("/Control", "org.ricebowl.SNIFixtureControl", "SetMode",
             GLib.Variant("(s)", ("item-error",)), "()")
        try:
            call("/StatusNotifierItem", item, "ContextMenu",
                 GLib.Variant("(ii)", (1201, 751)), "()")
        except GLib.Error as error:
            assert "AccessDenied" in str(error), error
        else:
            raise AssertionError("item-error mode must fail the item method")
        rows = [json.loads(line) for line in receipts.read_text().splitlines()]
        calls = [r for r in rows if r["event"] == "item"]
        assert [(c["method"], c["coords"], c["mode"]) for c in calls] == [
            ("ContextMenu", [1200, 750], "normal"),
            ("ContextMenu", [1201, 751], "item-error")], calls
    finally:
        process.terminate()
        process.communicate(timeout=4)
"""


class InteractionSmokeContractTests(unittest.TestCase):
    def setUp(self):
        self.source = SMOKE.read_text(encoding="utf-8")

    def test_script_parses_and_covers_every_stage(self):
        syntax = subprocess.run(["sh", "-n", str(SMOKE)], capture_output=True,
                                text=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        for stage in ("windows", "launcher", "clock", "sni", "files", "outputs"):
            self.assertIn(f"stage_{stage}() {{", self.source)
        self.assertIn("for s in windows launcher clock sni files outputs; do run_stage", self.source)
        self.assertNotIn("sudo ", self.source)

    def test_negative_paths_stay_genuine(self):
        # Real denials and real focus theft, never a unit-level stand-in.
        for needle in (
                'chmod 0000 "$fh/Desktop/03-secret.txt"',
                'chmod 0500 "$fh/Desktop"',
                'chmod 0500 "$fc/ricebowl"',
                "cannot open Luna settings page timezone: No such file",
                "cannot open Luna settings page timezone: Permission denied",
                "finished settings helper left a zombie child",
                '"$probe" overlay exclusive',
                "wtype -M logo -k a -m logo",       # labwc maximize
                "wtype -M alt -k F4 -m alt",        # labwc close request
                "kill -9 \"$plate\"",               # RicePlate transient loss
                "secondary click fell back to a provider item method",
                "--right-click 1200",
                "WLR_HEADLESS_OUTPUTS=2 labwc",
                'wlr-randr --output "$o1" --off',
                'wlr-randr --output "$o1" --scale 1.5',
                "--plain"):
            self.assertIn(needle, self.source, needle)

    def test_workflow_filters_syntax_check_and_runs_it(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        name = "scripts/smoke_sg1_interaction_labwc.sh"
        # push + pull_request path filters, `sh -n`, and one run step.
        self.assertEqual(workflow.count(f"- '{name}'"), 2)
        self.assertIn(f"sh -n {name}", workflow)
        self.assertEqual(workflow.count(f"sh {name}"), 1)

    def test_output_removal_closes_transient_surfaces(self):
        # Structural guard for the product fix behind WP1.8: removing an
        # output must close the Start menu (an invisible menu kept keyboard
        # focus and launched its highlighted entry on Return), the tray
        # popup and the calendar. Compositor proof: stage `outputs`.
        native = (ROOT / "components/riceplate-wayland/src/main.rs").read_text(
            encoding="utf-8")
        begin = native.index("    fn output_destroyed(")
        body = native[begin:native.index("impl SeatHandler for RicePlate", begin)]
        for needle in ("self.set_menu_visible(false, qh);",
                       "self.set_tray_popup_visible(false, qh);",
                       "self.set_calendar_visible(false, qh);"):
            self.assertIn(needle, body)
        self.assertLess(body.index("self.set_menu_visible(false, qh);"),
                        body.index("self.primary_output = None;"))

    @unittest.skipUnless(shutil.which("dbus-run-session") and
                         Path("/usr/bin/python3").exists(), "D-Bus runtime unavailable")
    def test_plain_item_fixture_has_context_menu_only_and_item_errors(self):
        check = subprocess.run(
            ["dbus-run-session", "--", "/usr/bin/python3", "-c",
             PLAIN_ITEM_CHECK, str(PROVIDER)],
            capture_output=True, text=True, timeout=35, check=False)
        self.assertEqual(check.returncode, 0,
                         f"plain-item fixture failed:\n{check.stdout}\n{check.stderr}")


if __name__ == "__main__":
    unittest.main()
