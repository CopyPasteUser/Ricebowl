"""Sprint 6 read-only service integration diagnostics: no D-Bus activation."""

import json
import subprocess
import unittest
from unittest import mock

from macrice.de import integration_health as health
from macrice.de.session import DESKTOP_NAME


class IntegrationHealthTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": DESKTOP_NAME,
            "RICEBOWL_DE_SHELL_CHILD": "1",
            "RICEBOWL_DE_NESTED": "0",
            "WAYLAND_DISPLAY": "wayland-7",
            "XDG_RUNTIME_DIR": "/redacted/current-uid",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/private/session-bus",
        }

    def test_xfce_nested_and_missing_socket_never_query_parent_buses(self):
        for change in ({"XDG_SESSION_TYPE": "x11"},
                       {"XDG_CURRENT_DESKTOP": "XFCE"},
                       {"RICEBOWL_DE_NESTED": "1"},
                       {"RICEBOWL_DE_SHELL_CHILD": "0"}):
            with self.subTest(change=change):
                report = health.inspect(
                    environment={**self.env, **change},
                    which=lambda _: self.fail("must not inspect binaries outside RiceBowl"),
                    run=lambda *_a, **_k: self.fail("must not touch an external D-Bus"),
                    socket_probe=lambda _: self.fail("must not probe outside full login"))
                self.assertFalse(report["session"]["full_ricebowl"])
                self.assertEqual(set(report["services"].values()), {"not-run"})
                self.assertFalse(report["hardware_accepted"])
        report = health.inspect(
            environment=self.env, which=lambda _: self.fail("invalid socket"),
            socket_probe=lambda _: "invalid")
        self.assertEqual(report["session"]["socket"], "invalid")
        self.assertEqual(set(report["services"].values()), {"not-run"})

    def test_session_and_system_bus_query_are_non_activating_and_allowlisted(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            self.assertEqual(argv[1:4],
                             ["--session", "--type=method_call", "--print-reply=literal"]
                             if argv[1] == "--session" else
                             ["--system", "--type=method_call", "--print-reply=literal"])
            self.assertIn("--reply-timeout=1000", argv)
            self.assertEqual(argv[5:8],
                             ["--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus.NameHasOwner"])
            self.assertTrue(argv[8].startswith("string:org."))
            self.assertNotIn("StartServiceByName", " ".join(argv))
            self.assertEqual(kwargs["timeout"], 2.0)
            self.assertFalse(kwargs["check"])
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            observed = "false" if "Notifications" in argv[-1] else "true"
            return subprocess.CompletedProcess(argv, 0,
                "method return serial=123\n   boolean " + observed + "\n", "")
        report = health.inspect(
            environment=self.env, which=lambda cmd: "/usr/bin/dbus-send" if cmd == "dbus-send" else None,
            socket_probe=lambda _: "present", run=runner)
        self.assertEqual(len(calls), 6)
        self.assertTrue(report["session"]["full_ricebowl"])
        self.assertEqual(report["services"]["notifications"], "not-owned")
        self.assertEqual(report["services"]["xdg_desktop_portal"], "owned")
        self.assertEqual(report["services"]["logind"], "owned")
        self.assertEqual(report["services"]["polkit_authority"], "owned")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["hardware_accepted"])
        self.assertNotIn("/private/session-bus", json.dumps(report))
        self.assertNotIn("serial=123", json.dumps(report))

    def test_missing_dbus_tool_and_session_bus_never_invent_owners(self):
        output = health.inspect(environment=self.env, socket_probe=lambda _: "present",
                                which=lambda _name: None,
                                run=lambda *_a, **_kw: self.fail("tool missing"))
        self.assertEqual(set(output["services"].values()), {"tool-missing"})
        commands = []
        def runner(argv, **kwargs):
            commands.append(argv)
            return subprocess.CompletedProcess(argv, 0, "   boolean false\n", "")
        env = {key: value for key, value in self.env.items()
               if key != "DBUS_SESSION_BUS_ADDRESS"}
        report = health.inspect(environment=env, socket_probe=lambda _: "present",
                                which=lambda _: "/usr/bin/dbus-send", run=runner)
        self.assertEqual(report["services"]["xdg_desktop_portal"], "not-declared")
        self.assertEqual(report["services"]["notifications"], "not-declared")
        self.assertEqual(len(commands), 4)
        self.assertTrue(all("--system" in command for command in commands))
        self.assertEqual(report["services"]["bluez"], "not-owned")

    def test_errors_oversized_and_ambiguous_replies_fail_closed(self):
        for response, expected in (
            (subprocess.CompletedProcess([], 1, "", "secret!"), "unreachable"),
            (subprocess.CompletedProcess([], 0, "invalid", ""), "invalid-response"),
            (subprocess.CompletedProcess([], 0,
                 " boolean true\n boolean false\n", ""), "invalid-response"),
            (subprocess.CompletedProcess([], 0, "x" * 5000, ""), "invalid-response"),
        ):
            with self.subTest(expected=expected, response=response.stdout[:15]):
                value = health._owner("org.freedesktop.login1", "system",
                    binary="/usr/bin/dbus-send", env=self.env,
                    run=lambda *_a, **_kw: response)
                self.assertEqual(value, expected)
        self.assertEqual(health._owner("org.freedesktop.login1", "system",
            binary="/usr/bin/dbus-send", env=self.env,
            run=lambda *_a, **_kw: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("dbus-send", 2))), "unreachable")
        with self.assertRaisesRegex(ValueError, "Unknown integration"):
            health._owner("org.evil.RunArbitrary", "system",
                          binary="/usr/bin/dbus-send", env=self.env,
                          run=lambda *_a, **_kw: self.fail("invalid name dispatched"))

    def test_cli_is_on_demand_and_keeps_an_honest_json_contract(self):
        from macrice.cli import main
        report = health.inspect(environment={"XDG_SESSION_TYPE": "x11"},
                                which=lambda _: None)
        with mock.patch("macrice.de.integration_health.inspect", return_value=report), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "integration-health", "--json"]), 0)
            self.assertEqual(json.loads(printed.call_args.args[0]), report)
        self.assertEqual(report["services"]["logind"], "not-run")
        self.assertFalse(report["hardware_accepted"])


if __name__ == "__main__":
    unittest.main()
