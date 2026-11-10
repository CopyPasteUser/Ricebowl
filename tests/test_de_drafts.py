"""Data-only Creator edits for reusable RicePlate components."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import catalog, creator_contract, drafts, recipes, review


def _edit(path, *changes):
    path.write_text(json.dumps({
        "edit_version": 1,
        "operations": [{"op": "set", "path": name, "value": value}
                       for name, value in changes],
    }))
    path.chmod(0o644)


class DraftEditorTests(unittest.TestCase):
    def test_read_only_preflight_and_pinned_publish_have_identical_semantics(self):
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "edit.json"
            output = Path(folder) / "candidate.json"
            _edit(patch, ("/name", "Original Creator Rice"),
                  ("/panel/height", 48))
            checked = drafts.check_edit(recipe_token="classic", edit_source=patch)
            self.assertTrue(checked["validated"])
            self.assertFalse(checked["created"])
            self.assertFalse(checked["applied"])
            self.assertFalse(output.exists())
            published = drafts.create_edit(
                recipe_token="classic", edit_source=patch, destination=output,
                expected_sha256=checked["source_semantic_sha256"],
                expected_draft_sha256=checked["draft_semantic_sha256"])
            self.assertTrue(published["created"])
            for key in ("changes", "source_semantic_sha256", "draft_semantic_sha256"):
                self.assertEqual(published[key], checked[key])
            self.assertEqual(review.review(str(output))["summary"]["semantic_sha256"],
                             checked["draft_semantic_sha256"])

    def test_stale_source_or_changed_proposal_never_creates_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "edit.json"
            output = Path(folder) / "candidate.json"
            _edit(patch, ("/panel/height", 48))
            checked = drafts.check_edit(recipe_token="classic", edit_source=patch)
            with self.assertRaises(drafts.DraftError) as stale:
                drafts.create_edit(recipe_token="classic", edit_source=patch,
                                   destination=output, expected_sha256="0" * 64)
            self.assertEqual(stale.exception.code, "source_changed")
            _edit(patch, ("/panel/height", 50))
            with self.assertRaises(drafts.DraftError) as changed:
                drafts.create_edit(
                    recipe_token="classic", edit_source=patch, destination=output,
                    expected_sha256=checked["source_semantic_sha256"],
                    expected_draft_sha256=checked["draft_semantic_sha256"])
            self.assertEqual(changed.exception.code, "draft_changed")
            for invalid in ("A" * 64, "x", "", "0" * 65):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(drafts.DraftError) as error:
                        drafts.create_edit(recipe_token="classic", edit_source=patch,
                                           destination=output,
                                           expected_draft_sha256=invalid)
                    self.assertEqual(error.exception.code, "invalid_draft_fingerprint")
            self.assertFalse(output.exists())

    def test_cli_preflight_is_read_only_and_flags_do_not_leak(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "edit.json"
            output = Path(folder) / "candidate.json"
            _edit(patch, ("/panel/height", 46))
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "draft-check", "--recipe", "classic",
                                       "--edit", str(patch), "--json"]), 0)
                checked = json.loads(printer.call_args.args[0])
            self.assertTrue(checked["validated"])
            self.assertFalse(output.exists())
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main([
                    "de", "draft-edit", "--recipe", "classic", "--edit", str(patch),
                    "--output", str(output), "--json",
                    "--expect-sha256", checked["source_semantic_sha256"],
                    "--expect-draft-sha256", checked["draft_semantic_sha256"]]), 0)
                self.assertTrue(json.loads(printer.call_args.args[0])["created"])
            with mock.patch("sys.stderr"):
                self.assertEqual(main(["de", "draft-check", "--recipe", "classic",
                                       "--edit", str(patch), "--output", str(output)]), 1)
                self.assertEqual(main(["de", "review", "--recipe", "classic",
                                       "--expect-draft-sha256", "0" * 64]), 1)

    def test_agent_can_author_from_catalog_example_without_custom_shell_code(self):
        spec = catalog.describe()["authoring"]["draft_edit"]
        self.assertEqual(spec, creator_contract.describe())
        self.assertEqual(spec["edit_version"], 1)
        self.assertLessEqual(len(spec["example"]["operations"]), spec["max_operations"])
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "agent-edit.json"
            output = Path(folder) / "agent-rice.json"
            patch.write_text(json.dumps(spec["example"]))
            result = drafts.create_edit(recipe_token=spec["example_source_recipe"],
                                        edit_source=patch, destination=output)
            self.assertTrue(result["created"])
            self.assertEqual(recipes.load(str(output)).sections[1], ("tasks",))
            self.assertEqual(recipes.load(str(output)).sections[0], ("launcher",))
            self.assertEqual(review.review(str(output))["recipe"]["panel"]["height"], 44)

    def test_edit_builds_real_runtime_recipe_from_reusable_components(self):
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "edit.json"
            destination = Path(folder) / "ai-inspired-panel.json"
            _edit(patch,
                  ("/name", "Original Y2K Panel"),
                  ("/panel/position", "top"),
                  ("/panel/height", 48),
                  ("/panel/sections/start", ["launcher", "network"]),
                  ("/panel/sections/center", ["tasks"]),
                  ("/panel/sections/end", ["clock", "audio", "battery", "tray"]),
                  ("/colors/background", "#123456"))
            result = drafts.create_edit(recipe_token="classic", edit_source=patch,
                                        destination=destination)
            rendered = recipes.load(str(destination))
            config, css = recipes.waybar_config(rendered)
            self.assertIn("clock", config)
            self.assertIn("#123456", css)
            self.assertEqual(rendered.position, "top")
            self.assertEqual(rendered.sections[1], ("tasks",))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertFalse(result["applied"])
            self.assertEqual(result["recipe_id"], "classic")
            self.assertEqual(result["source_semantic_sha256"],
                             review.review("classic")["summary"]["semantic_sha256"])
            self.assertEqual(result["draft_semantic_sha256"],
                             review.review(str(destination))["summary"]["semantic_sha256"])
            self.assertIn({"path": "/panel/height", "before": 36, "after": 48},
                          result["changes"])

    def test_independent_templates_share_one_authoring_and_runtime_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            for base, position in (("classic", "top"), ("chrome", "bottom")):
                source = Path(folder) / f"{base}-edit.json"
                output = Path(folder) / f"{base}-new.json"
                _edit(source, ("/panel/position", position),
                      ("/panel/height", 32 if base == "classic" else 56))
                drafts.create_edit(recipe_token=base, edit_source=source, destination=output)
                result = review.review(str(output), base)
                self.assertTrue(result["comparison"]["changed"])
                self.assertEqual(result["recipe"]["panel"]["height"],
                                 32 if base == "classic" else 56)
                self.assertEqual(recipes.load(str(output)).recipe_id, base)

    def test_v2_metrics_are_editable_but_v1_metrics_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "v2.json"
            original = Path(folder) / "base.json"
            recipes.create_from_template(source="chrome", destination=original,
                                         recipe_id="my-modern", name="Custom",
                                         schema_version=2)
            source = Path(folder) / "edit.json"
            _edit(source, ("/panel/metrics/task_width", 210),
                  ("/panel/metrics/clock_width", 100))
            result = drafts.create_edit(recipe_token=str(original), edit_source=source,
                                        destination=output)
            self.assertEqual(recipes.load(str(output)).metrics, (104, 210, 100))
            self.assertEqual(recipes.load(str(original)).metrics, recipes.METRIC_DEFAULTS)
            self.assertEqual(len(result["changes"]), 2)
            with self.assertRaisesRegex(drafts.DraftError, "schema-v2"):
                drafts.create_edit(recipe_token="classic", edit_source=source,
                                   destination=Path(folder) / "invalid.json")
            self.assertFalse((Path(folder) / "invalid.json").exists())

    def test_rejects_unsupported_actions_widgets_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "edit.json"
            output = Path(folder) / "out.json"
            invalid = [
                (("/panel/sections/start", ["exec:curl", "tasks"]),),
                (("/panel/sections/start", ["launcher", "tasks", "tasks"]),),
                (("/panel/height", True),),
                (("/panel/height", 1000),),
                (("/panel/sections/end", {"on_click": "rm -rf"}),),
                (("/panel/sections/start", ["tasks"]),
                 ("/panel/sections/start", ["launcher"])),
                (("/id", "modified-id"),),
                (("/action", "run-script"),),
                (("/panel/metrics/launcher_width", 104),),
                (("/colors/background", "url(file:///private)"),),
            ]
            for changes in invalid:
                with self.subTest(changes=changes):
                    _edit(source, *changes)
                    with self.assertRaises(drafts.DraftError):
                        drafts.create_edit(recipe_token="classic", edit_source=source,
                                           destination=output)
                    self.assertFalse(output.exists())

    def test_rejects_invalid_edit_documents_before_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "edit.json"
            output = Path(folder) / "out.json"
            examples = [
                b'{"edit_version":1,"edit_version":1,"operations":[]}',
                b'{"edit_version":true,"operations":[]}',
                b'{"edit_version":2,"operations":[]}',
                b'{"edit_version":1,"operations":[]}',
                b'{"edit_version":1,"operations":[{"op":"del","path":"/name","value":"x"}]}',
                b'{"edit_version":1,"operations":[{"op":"set","path":"/name","value":"x","extra":1}]}',
                b'x' * (drafts.MAX_EDIT_BYTES + 1),
            ]
            for raw in examples:
                with self.subTest(size=len(raw)):
                    source.write_bytes(raw)
                    with self.assertRaises(drafts.DraftError):
                        drafts.create_edit(recipe_token="classic", edit_source=source,
                                           destination=output)
                    self.assertFalse(output.exists())

    def test_private_file_permissions_symlink_and_collision_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "edit.json"
            output = Path(folder) / "draft.json"
            _edit(source, ("/panel/height", 47))
            source.chmod(0o666)
            with self.assertRaises(drafts.DraftError):
                drafts.create_edit(recipe_token="classic", edit_source=source,
                                   destination=output)
            source.chmod(0o600)
            link = Path(folder) / "link.json"
            link.symlink_to(source)
            with self.assertRaises(drafts.DraftError):
                drafts.create_edit(recipe_token="classic", edit_source=link,
                                   destination=output)
            output.write_text("do not overwrite me")
            with self.assertRaisesRegex(drafts.DraftError, "overwriting"):
                drafts.create_edit(recipe_token="classic", edit_source=source,
                                   destination=output)
            self.assertEqual(output.read_text(), "do not overwrite me")

    def test_no_op_and_bad_output_path_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "edit.json"
            _edit(source, ("/panel/height", 36))
            output = Path(folder) / "not-created.json"
            with self.assertRaisesRegex(drafts.DraftError, "change"):
                drafts.create_edit(recipe_token="classic", edit_source=source,
                                   destination=output)
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(drafts.DraftError, "absolute"):
                drafts.create_edit(recipe_token="classic", edit_source=source,
                                   destination=Path("relative.json"))

    def test_cli_json_success_error_and_flag_isolation(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "patch.json"
            output = Path(folder) / "draft.json"
            _edit(patch, ("/colors/active", "#abcdef"))
            with mock.patch("macrice.de.session.start") as session, \
                 mock.patch("macrice.de.recipes.change_selection") as selection, \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "draft-edit", "--recipe", "classic",
                                       "--edit", str(patch), "--output", str(output),
                                       "--json"]), 0)
                result = json.loads(printer.call_args.args[0])
            self.assertTrue(result["created"])
            self.assertFalse(result["applied"])
            session.assert_not_called()
            selection.assert_not_called()
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "draft-edit", "--recipe", "classic",
                                       "--edit", str(patch), "--output", str(output),
                                       "--json"]), 2)
                failed = json.loads(printer.call_args.args[0])
                self.assertEqual(failed["error"]["code"], "output_unavailable")
                self.assertFalse(failed["created"])
            self.assertNotIn(folder, json.dumps(failed))
            bad = (
                ["de", "review", "--recipe", "classic", "--edit", str(patch)],
                ["de", "catalog", "--edit", str(patch)],
                ["de", "draft-edit", "--recipe", "classic", "--edit", str(patch)],
                ["de", "draft-edit", "--recipe", "classic", "--edit", str(patch),
                 "--output", str(output), "--nested"],
                ["de", "draft-edit", "--recipe", "classic", "--edit", str(patch),
                 "--output", str(output), "--panel", "native"],
            )
            for command in bad:
                with self.subTest(command=command), mock.patch("sys.stderr"):
                    self.assertEqual(main(command), 1)

    def test_agent_errors_point_to_supported_fields_without_private_paths(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            patch = Path(folder) / "secret-edit.json"
            output = Path(folder) / "out.json"
            _edit(patch, ("/panel/height", 900))
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "draft-edit", "--recipe", "classic",
                                       "--edit", str(patch), "--output", str(output),
                                       "--json"]), 2)
                result = json.loads(printer.call_args.args[0])
            self.assertEqual(result["error"]["code"], "invalid_value")
            self.assertEqual(result["error"]["path"], "/panel/height")
            self.assertNotIn(folder, json.dumps(result))
            self.assertFalse(output.exists())

            _edit(patch, ("/panel/sections/start", ["launcher", "clock"]))
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "draft-edit", "--recipe", "classic",
                                       "--edit", str(patch), "--output", str(output),
                                       "--json"]), 2)
                result = json.loads(printer.call_args.args[0])
            self.assertEqual(result["error"]["code"], "invalid_composition")
            self.assertNotIn("path", result["error"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
