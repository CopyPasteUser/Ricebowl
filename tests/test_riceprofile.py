"""Versioned RiceBowl→RiceField/Taskotto session contract and recovery."""

import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from macrice.de import recipes, riceprofile


class RiceProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.marker = self.root / ".ricebowl-managed"
        self.marker.touch(mode=0o600)
        self.root.chmod(0o700)
        self.env = {"RICEBOWL_DE_SESSION_CONFIG": str(self.root)}
        self.checked = []

    def check(self, args, **kwargs):
        self.checked.append(tuple(args))
        content = Path(args[2]).read_text()
        if args[0] == "taskotto":
            valid = "base_theme = " in content and "navigation = \"auto\"" in content
        else:
            valid = "base_theme = \"win7\"" in content or "base_theme = \"chromeos\"" in content
        return SimpleNamespace(returncode=0 if valid else 2)

    def prepare(self):
        return riceprofile.ProfileSession.prepare(self.root, self.env, recipes.load("classic"),
                                                  which=lambda binary: binary, run=self.check)

    def test_data_only_profile_schema_and_known_rice_mappings(self):
        classic = recipes.load("classic")
        text = riceprofile.render_ricefield(classic).decode()
        self.assertEqual(text, (Path(__file__).parent / "fixtures/ricefield-classic-v1.toml").read_text())
        self.assertIn("format_version = 1\n", text)
        self.assertIn('base_theme = "win7"', text)
        self.assertIn('accent = "#4179aa"', text)
        self.assertNotIn("command", text)
        for wallpaper, base in riceprofile.FIELD_THEMES.items():
            candidate = next((name for name, alias in riceprofile.taskotto.WALLPAPER_THEME.items()
                              if alias == wallpaper), None)
            if candidate is not None:
                profile = riceprofile.render_ricefield(dataclasses.replace(classic, wallpaper=candidate))
                self.assertIn(f'base_theme = "{base}"'.encode(), profile)

    def test_discovery_only_advertises_supported_clients_and_never_changes_user_config(self):
        calls = []

        def check(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0 if args[0] == "taskotto" else 2)

        session = riceprofile.ProfileSession.prepare(self.root, self.env, recipes.load("classic"),
                                                     which=lambda name: name, run=check)
        self.assertEqual(session.status(), {"taskotto": "managed", "ricefield": "not_managed"})
        self.assertEqual(set(self.env) - {"RICEBOWL_DE_SESSION_CONFIG"},
                         {"RICEBOWL_TASKOTTO_RICEPACK"})
        self.assertFalse((self.root / "ricefield.riceprofile.toml").exists())
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.root / "taskotto.ricepack.toml").stat().st_mode & 0o777, 0o600)

    def test_preflight_then_commit_then_restore_preserves_both_files(self):
        session = self.prepare()
        self.assertEqual(len(session.clients), 2)
        self.assertEqual(riceprofile.ProfileSession.from_environment(self.env).status(),
                         {"taskotto": "managed", "ricefield": "managed"})
        old = {client: (self.root / client.filename).read_bytes() for client in session.clients}
        proposed = session.preflight(recipes.load("chrome"))
        self.assertEqual(old, {client: (self.root / client.filename).read_bytes() for client in session.clients})
        previous = session.commit(proposed)
        self.assertEqual(previous, old)
        for client, content in proposed.items():
            self.assertEqual((self.root / client.filename).read_bytes(), content)
            self.assertEqual((self.root / client.filename).stat().st_mode & 0o777, 0o600)
        session.restore(previous)
        for client, content in old.items():
            self.assertEqual((self.root / client.filename).read_bytes(), content)

    def test_external_modification_refuses_overwrite(self):
        session = self.prepare()
        field = self.root / "ricefield.riceprofile.toml"
        field.write_text("external owner edit")
        with self.assertRaisesRegex(riceprofile.ProfileError, "outside RiceBowl"):
            session.preflight(recipes.load("chrome"))
        self.assertEqual(field.read_text(), "external owner edit")

    def test_invalid_candidate_is_rejected_before_commit(self):
        session = self.prepare()
        self.checked.clear()

        def fail_field(args, **kwargs):
            return SimpleNamespace(returncode=2 if args[0] == "ricefield" else 0)

        session.run = fail_field
        with self.assertRaisesRegex(riceprofile.ProfileError, "ricefield rejected"):
            session.preflight(recipes.load("chrome"))
        self.assertIn(b'base_theme = "win7"',
                      (self.root / "ricefield.riceprofile.toml").read_bytes())

    def test_partial_commit_rolls_back_all_previously_written_profiles(self):
        session = self.prepare()
        proposed = session.preflight(recipes.load("chrome"))
        original = {client: (self.root / client.filename).read_bytes() for client in session.clients}
        real = riceprofile._atomic_replace
        count = 0

        def fail_second(path, content):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated disk error")
            real(path, content)

        with mock.patch.object(riceprofile, "_atomic_replace", side_effect=fail_second):
            with self.assertRaisesRegex(riceprofile.ProfileError, "previous files restored"):
                session.commit(proposed)
        for client, content in original.items():
            self.assertEqual((self.root / client.filename).read_bytes(), content)

    def test_paths_cannot_escape_owner_private_managed_directory(self):
        self.prepare()
        with self.assertRaisesRegex(riceprofile.ProfileError, "escapes"):
            riceprofile.ProfileSession.from_environment({**self.env,
                "RICEBOWL_RICEFIELD_THEME_FILE": "/tmp/untrusted.toml"})
        self.root.chmod(0o755)
        with self.assertRaisesRegex(riceprofile.ProfileError, "owner-private"):
            riceprofile.ProfileSession.from_environment(self.env)


if __name__ == "__main__":
    unittest.main()
