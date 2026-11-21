"""True private-session D-Bus protocol tests for the isolated SG1 SNI provider.

The Python CI suite discovers this test automatically; no shared CI workflow,
machine D-Bus daemon, or host desktop setting is modified.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "scripts/fixtures/sg1_sni_provider.py"
SMOKE = ROOT / "scripts/smoke_sg1_sni_labwc.sh"

# Executed INSIDE dbus-run-session, not using the runner's existing bus.
PRIVATE_BUS_CHECK = r"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from gi.repository import Gio, GLib

provider = sys.argv[1]
service = "org.ricebowl.SNIFixture"
menu = "com.canonical.dbusmenu"
control = "org.ricebowl.SNIFixtureControl"
conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)

with tempfile.TemporaryDirectory(prefix="sg1-sni-bus-") as dirname:
    directory = Path(dirname)
    receipts = directory / "receipt.jsonl"
    process = None

    def call(dest, path, interface, method, args, signature, timeout=3000):
        return conn.call_sync(
            dest, path, interface, method, args,
            GLib.VariantType.new(signature), Gio.DBusCallFlags.NONE, timeout, None)

    def start(gen):
        global process
        process = subprocess.Popen(
            ["/usr/bin/python3", provider, "--no-register",
             "--ready", str(directory / ("ready-" + gen)),
             "--receipts", str(receipts), "--generation", gen],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            assert process.poll() is None, process.stderr.read().decode()
            try:
                answer = call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "GetNameOwner",
                              GLib.Variant("(s)", (service,)), "(s)", 250)
                return answer.unpack()[0]
            except GLib.Error:
                time.sleep(.05)
        raise AssertionError("Fixture never owned private session-bus name")

    def stop():
        global process
        process.terminate()
        process.communicate(timeout=4)
        process = None

    try:
        first_owner = start("first")
        properties = call(service, "/StatusNotifierItem",
                          "org.freedesktop.DBus.Properties", "GetAll",
                          GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)),
                          "(a{sv})")
        values = properties.unpack()[0]
        def unpack(value):
            return value.unpack() if isinstance(value, GLib.Variant) else value
        assert unpack(values["Title"]) == "SNI fixture first", values
        assert unpack(values["Menu"]) == "/Menu", values

        layout = call(service, "/Menu", menu, "GetLayout",
                      GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))")
        assert layout.get_type_string() == "(u(ia{sv}av))"
        assert "Submenu" in layout.print_(True), layout.print_(True)
        assert "Nested action" in layout.print_(True), layout.print_(True)
        call(service, "/Menu", menu, "Event",
             GLib.Variant("(isvu)", (21, "clicked", GLib.Variant("s", ""), 0)), "()")
        def assert_dbus_rejected(item_id, expected):
            try:
                call(service, "/Menu", menu, "Event",
                     GLib.Variant("(isvu)", (item_id, "clicked",
                                            GLib.Variant("s", ""), 0)), "()")
            except GLib.Error as error:
                assert expected in str(error), (expected, error)
            else:
                raise AssertionError(f"Invalid action {item_id} accepted: {expected}")

        assert_dbus_rejected(999, "UnknownMenuId")
        call(service, "/Control", control, "SetMode",
             GLib.Variant("(s)", ("disabled",)), "()")
        layout = call(service, "/Menu", menu, "GetLayout",
                      GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))")
        assert "Disabled action" in layout.print_(True)
        assert_dbus_rejected(11, "DisabledMenuId")
        call(service, "/Control", control, "SetMode",
             GLib.Variant("(s)", ("denied",)), "()")
        assert_dbus_rejected(10, "AccessDenied")
        call(service, "/Control", control, "SetMode",
             GLib.Variant("(s)", ("removed",)), "()")
        layout = call(service, "/Menu", menu, "GetLayout",
                      GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))")
        assert "Provider action" not in layout.print_(True)
        assert_dbus_rejected(10, "RevokedMenuId")
        call(service, "/Control", control, "SetMode",
             GLib.Variant("(s)", ("slow",)), "()")
        began = time.monotonic()
        call(service, "/Menu", menu, "GetLayout",
             GLib.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))", 3000)
        assert time.monotonic() - began >= .35, "Slow reply was not simulated"
        stop()
        next_owner = start("second")
        assert first_owner != next_owner, (first_owner, next_owner)
        call(service, "/Menu", menu, "Event",
             GLib.Variant("(isvu)", (21, "clicked", GLib.Variant("s", ""), 0)), "()")
        stop()
        records = [json.loads(line) for line in receipts.read_text().splitlines()]
        assert any(r["generation"] == "first" and
                   r["event"] == "menu-event" and r.get("id") == 21
                   for r in records), records
        assert any(r["generation"] == "second" and
                   r["event"] == "menu-event" and r.get("id") == 21
                   for r in records), records
        assert len([r for r in records if r["event"] == "owner"]) == 2, records
    finally:
        if process is not None:
            stop()
"""


class SniIntegrationFixtureTests(unittest.TestCase):
    def test_provider_python_syntax_and_declared_protocol(self):
        source = PROVIDER.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(PROVIDER))
        # Inspect the literal embedded introspection XML without importing gi.
        xml = next(node.value.value for node in ast.walk(tree)
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "XML"
                           for target in node.targets)
                   and isinstance(node.value, ast.Constant))
        interfaces = {interface.attrib["name"]: interface
                      for interface in ET.fromstring(xml).findall("interface")}
        self.assertIn("org.kde.StatusNotifierItem", interfaces)
        self.assertIn("com.canonical.dbusmenu", interfaces)
        self.assertIn("org.ricebowl.SNIFixtureControl", interfaces)
        self.assertTrue({"GetLayout", "Event", "AboutToShow"}.issubset({
            method.attrib["name"]
            for method in interfaces["com.canonical.dbusmenu"].findall("method")}))
        smoke_source = SMOKE.read_text(encoding="utf-8")
        self.assertIn("dbus-run-session", smoke_source)
        self.assertNotIn("sudo ", smoke_source)
        # The CI fixture runs as an embedded single-quoted shell program.
        # Nested apostrophes silently truncate the child script even when
        # the outer shell happens to parse after further tokens.
        header = "dbus-run-session -- sh -eu -c '"
        tail = """' sh "$root" "$runtime" "$native" "$clicker" "$provider" """
        self.assertEqual(smoke_source.count(header), 1)
        self.assertEqual(smoke_source.count(tail.rstrip()), 1)
        embedded = smoke_source.split(header, 1)[1].split(tail.rstrip(), 1)[0]
        self.assertNotIn("'", embedded)
        # The two rices share one compositor and private D-Bus session but
        # never inherit a synthetic wtype keyboard seat from the prior app.
        self.assertEqual(embedded.count("renew_keyboard_seat() {"), 1)
        self.assertIn("""        renew_keyboard_seat
        RICEBOWL_DE_TRACE_TRAY""", embedded)
        self.assertIn('wait "$keyboard_keeper" 2>/dev/null || :', embedded)
        self.assertIn('kill -0 "$keyboard_keeper"', embedded)
        syntax = subprocess.run(["sh", "-n", str(SMOKE)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    @unittest.skipUnless(shutil.which("dbus-run-session") and
                         Path("/usr/bin/python3").exists(), "D-Bus runtime unavailable")
    def test_real_provider_owner_switch_methods_and_receipts(self):
        check = subprocess.run(
            ["dbus-run-session", "--", "/usr/bin/python3", "-c",
             PRIVATE_BUS_CHECK, str(PROVIDER)],
            capture_output=True, text=True, timeout=35, check=False)
        # Failure to import Gio is a dependency failure, never silently pass.
        self.assertEqual(check.returncode, 0,
                         f"private D-Bus fixture failed:\n{check.stdout}\n{check.stderr}")


if __name__ == "__main__":
    unittest.main()
