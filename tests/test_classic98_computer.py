"""Backend contracts for native Windows 98 Find > Computer."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from macrice.classic98_computer import (
    MAX_MOUNTS, filter_locations, mounted_locations, network_browsing_available,
    open_location,
)


class FakeRoot:
    def __init__(self, uri):
        self.uri = uri

    def get_uri(self):
        return self.uri


class FakeMount:
    def __init__(self, name, uri, *, shadowed=False, broken=False):
        self.name, self.uri, self.shadowed, self.broken = name, uri, shadowed, broken

    def is_shadowed(self):
        return self.shadowed

    def get_name(self):
        return self.name

    def get_root(self):
        if self.broken:
            raise OSError("Device disconnected")
        return FakeRoot(self.uri)


class FakeMonitor:
    def __init__(self, mounts):
        self.mounts = mounts

    def get_mounts(self):
        return self.mounts


class Classic98ComputerTests(unittest.TestCase):
    def test_real_mounts_are_deduplicated_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            monitor = FakeMonitor([
                FakeMount("USB Stick", "file:///media/usb"),
                FakeMount("NAS", "smb://nas/share"),
                FakeMount("Duplicate", "smb://nas/share"),
                FakeMount("Shadow", "file:///hidden", shadowed=True),
                FakeMount("Gone", "file:///gone", broken=True),
                FakeMount("Invalid", "not-an-uri"),
            ])
            found = mounted_locations(monitor, home=home)
            self.assertEqual([x.name for x in found],
                             ["Home", "File System", "USB Stick", "NAS"])
            self.assertEqual(found[-1].kind, "Network location")
            self.assertEqual(found[0].uri, home.as_uri())
            self.assertEqual(len({x.uri for x in found}), len(found))

    def test_search_uses_labels_not_network_credentials(self):
        found = mounted_locations(FakeMonitor([
            FakeMount("Archive NAS", "smb://alice:secret@nas/archive"),
            FakeMount("Flash Disk", "file:///media/flash"),
        ]))
        self.assertEqual([x.name for x in filter_locations(found, "nas")], ["Archive NAS"])
        self.assertEqual(filter_locations(found, "secret"), ())
        self.assertEqual(len(filter_locations(found, "")), len(found))

    def test_local_explorer_uses_win98_ricefield_without_shell(self):
        class GioFile:
            def get_path(self):
                return "/home/test/My Documents"

        class Gio:
            class File:
                @staticmethod
                def new_for_uri(uri):
                    return GioFile()

        class Shell:
            calls = []
            def _hide_menu(self):
                self.calls.append(("hide",))
            def _open_uri(self, uri):
                self.calls.append(("fallback", uri))

        shell = Shell()
        calls = []
        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))

        result = open_location(
            shell, "file:///home/test/My%20Documents", Gio,
            which=lambda name: "/usr/local/bin/ricefield", spawn=spawn)
        self.assertEqual(result, "ricefield")
        self.assertEqual(calls[0][0], [
            "/usr/local/bin/ricefield", "--theme", "win98",
            "--separate-window", "/home/test/My Documents"])
        self.assertEqual(calls[0][1]["close_fds"], True)
        self.assertNotIn("shell", calls[0][1])
        self.assertEqual(shell.calls, [("hide",)])

    def test_network_uri_and_missing_binary_fall_back_to_default_handler(self):
        class Gio:
            class File:
                @staticmethod
                def new_for_uri(uri):
                    raise AssertionError("Network URI must not be converted to a local path")

        class Shell:
            opened = []
            def _open_uri(self, uri):
                self.opened.append(uri)

        shell = Shell()
        self.assertEqual(open_location(shell, "smb://nas/share", Gio,
                                       which=lambda _: "/usr/bin/ricefield"), "default")
        self.assertEqual(shell.opened, ["smb://nas/share"])

    def test_no_automatic_remote_browsing_and_unavailable_backend(self):
        self.assertFalse(network_browsing_available(["file", "trash", "smb"]))
        self.assertTrue(network_browsing_available(["network", "file"]))
        self.assertFalse(network_browsing_available(None))
        mounts = [FakeMount("Volume", f"file:///mnt/{number}") for number in range(MAX_MOUNTS + 3)]
        self.assertEqual(len(mounted_locations(FakeMonitor(mounts))), MAX_MOUNTS + 2)


if __name__ == "__main__":
    unittest.main()
