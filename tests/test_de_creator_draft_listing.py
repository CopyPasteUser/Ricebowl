"""SG4: Creator draft inventory stays bounded and resilient to concurrent edits."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import creator_workspace as workspace


class CreatorDraftListingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state = Path(temporary.name) / "state"
        state.mkdir(mode=0o700)
        environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        environment.start()
        self.addCleanup(environment.stop)
        self.temp_root = Path(temporary.name)

    def test_latest_drafts_win_without_unbounded_open_attempts(self):
        older = workspace.create_draft("classic")
        newer = workspace.create_draft("chrome")
        folder = older.path.parent
        os.utime(older.path, ns=(10_000_000_000, 10_000_000_000))
        os.utime(newer.path, ns=(20_000_000_000, 20_000_000_000))
        for index in range(200):
            fake = folder / f"draft-invalid-{index:04d}.json"
            fake.write_text("{}", encoding="utf-8")
            fake.chmod(0o600)
            os.utime(fake, ns=(1_000_000_000, 1_000_000_000))
        outside = self.temp_root / "outside.json"
        outside.write_text("untouched", encoding="utf-8")
        (folder / "draft-external.json").symlink_to(outside)
        with mock.patch.object(workspace, "open_draft",
                               wraps=workspace.open_draft) as opened:
            listed = workspace.list_drafts()
        self.assertEqual([item.path for item in listed], [newer.path, older.path])
        self.assertLessEqual(opened.call_count, workspace.MAX_LISTED_DRAFTS)
        self.assertEqual(outside.read_text(), "untouched")

    def test_entry_deleted_during_scandir_is_ignored(self):
        created = workspace.create_draft("heritage")

        class Disappeared:
            name = "draft-disappeared.json"

            def stat(self, *, follow_symlinks):
                self.assertion(follow_symlinks)
                raise FileNotFoundError("removed during directory scan")

            @staticmethod
            def assertion(follow_symlinks):
                assert not follow_symlinks

        class Existing:
            name = created.path.name

            def stat(self, *, follow_symlinks):
                if follow_symlinks:
                    raise AssertionError("symlink following was requested")
                return created.path.stat()

        class Scanner:
            def __enter__(self):
                return iter([Disappeared(), Existing()])

            def __exit__(self, *_):
                return False

        with mock.patch.object(workspace.os, "scandir", return_value=Scanner()):
            self.assertEqual([item.path for item in workspace.list_drafts()],
                             [created.path])


if __name__ == "__main__":
    unittest.main()
