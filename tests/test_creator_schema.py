"""Creator property JSON Schemas stay aligned with supported recipe versions."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from macrice.cli import main as cli
from macrice.de import creator_contract, creator_schema, recipes, review


def _paths(schema):
    return {option["properties"]["path"]["const"] for option in
            schema["properties"]["operations"]["items"]["oneOf"]}


def _edit(path, value):
    return {"edit_version": 1, "operations": [{"op": "set", "path": path, "value": value}]}


class CreatorPropertySchemaTests(unittest.TestCase):
    def test_all_advertised_paths_are_represented_in_exact_version_union(self):
        schemas = [creator_schema.describe(version) for version in range(1, 12)]
        self.assertEqual(set().union(*(_paths(schema) for schema in schemas)),
                         creator_contract.EDITABLE_PATHS)
        for version, schema in enumerate(schemas, start=1):
            with self.subTest(version=version):
                self.assertEqual(schema["x-ricebowl-recipe-version"], version)
                self.assertEqual(schema["$schema"],
                                 "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(len(_paths(schema)), len(schema["properties"]["operations"]
                                 ["items"]["oneOf"]))
        self.assertIn("/panel/sections/start", _paths(schemas[0]))
        self.assertNotIn("/panel/layout/start", _paths(schemas[0]))
        self.assertIn("/panel/layout/start", _paths(schemas[2]))
        self.assertNotIn("/panel/sections/start", _paths(schemas[2]))
        self.assertNotIn("/menu/presentation", _paths(schemas[3]))
        self.assertIn("/menu/presentation", _paths(schemas[5]))
        self.assertNotIn("/composition/widgets", _paths(schemas[6]))
        self.assertIn("/composition/widgets", _paths(schemas[7]))
        self.assertIn("/components", _paths(schemas[8]))
        self.assertIn("/artwork/font", _paths(schemas[10]))

    def test_schema_rejects_unsupported_versions(self):
        for version in (0, 12, True, "11", 1.5):
            with self.subTest(version=version), self.assertRaises(ValueError):
                creator_schema.describe(version)

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional JSON Schema validator unavailable")
    def test_standard_jsonschema_rejects_malformed_and_executable_edits(self):
        import jsonschema
        for version in range(1, 12):
            jsonschema.Draft202012Validator.check_schema(creator_schema.describe(version))
        schema = creator_schema.describe(11)
        valid = (
            _edit("/panel/height", 44),
            _edit("/panel/layout/start", [{"type": "widget", "id": "launcher"},
                                           {"type": "group", "gap": 8, "children": [
                                               {"type": "label", "text": "Tools"}]}]),
            _edit("/components", [{"id": "sys-battery", "role": "status",
                                   "binding": "battery", "label": "Battery"}]),
            _edit("/artwork/icons/lock", "icon-" + "a" * 64),
            _edit("/menu/groups", [{"title": "Apps", "actions": ["applications"],
                                    "content": [{"type": "apps-grid", "title": "Apps",
                                                 "limit": 4}]}]),
        )
        for proposal in valid:
            with self.subTest(path=proposal["operations"][0]["path"]):
                jsonschema.validate(proposal, schema)
        invalid = (
            _edit("/unsafe/exec", "sh"),
            _edit("/panel/height", 100),
            _edit("/panel/height", True),
            _edit("/name", "Title\n"),
            _edit("/menu/title", "Apps\n"),
            _edit("/colors/active", "#123456\n"),
            _edit("/artwork/icons/lock", "../../bin/sh"),
            _edit("/artwork/icons/lock", "icon-" + "a" * 64 + "\n"),
            _edit("/components", [{"id": "bad", "role": "action",
                                   "binding": "/bin/sh", "label": "Run"}]),
            _edit("/panel/layout/start", [{"type": "action", "id": "run-script",
                                           "label": "Run"}]),
            _edit("/panel/layout/start", [{"type": "group", "gap": 0,
                                           "children": [{"type": "group", "gap": 0,
                                                         "children": [{"type": "group",
                                                                       "gap": 0,
                                                                       "children": [{"type": "gap",
                                                                                     "width": 8}]}]}]}]),
            {"edit_version": 1, "operations": [{"op": "exec", "path": "/panel/height",
                                                   "value": 44}]},
        )
        for proposal in invalid:
            with self.subTest(proposal=proposal), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(proposal, schema)

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "optional JSON Schema validator unavailable")
    def test_real_legacy_and_native_template_values_fit_advertised_schemas(self):
        import jsonschema
        root = Path(__file__).resolve().parents[1]
        heritage = json.loads((root / "examples/wayland/heritage-modern-v10.json").read_text())
        latest = json.loads(json.dumps(heritage))
        latest["schema_version"] = 11
        latest["artwork"] = {"font": "builtin", "icons": {
            action: "builtin" for action in recipes.ICON_ACTIONS}}
        samples = (recipes.load("classic"),
                   recipes.parse(json.dumps(heritage).encode()),
                   recipes.parse(json.dumps(latest).encode()))
        for sample in samples:
            manifest = review._manifest(sample)
            values = review._fields(manifest)
            if sample.schema_version >= 11:
                values["/artwork/icons"] = manifest["artwork"]["icons"]
            schema = creator_schema.describe(sample.schema_version)
            for path in _paths(schema):
                if path not in values or values[path] is None:
                    continue
                with self.subTest(schema=sample.schema_version, path=path):
                    jsonschema.validate(_edit(path, values[path]), schema)

    def test_cli_schema_pins_source_and_does_not_create_files(self):
        with patch("builtins.print") as printer:
            self.assertEqual(cli(["de", "creator-schema", "--recipe", "classic", "--json"]), 0)
        payload = json.loads(printer.call_args.args[0])
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["source_semantic_sha256"],
                         review.review("classic")["summary"]["semantic_sha256"])
        self.assertEqual(payload["schema_sha256"],
                         creator_schema.fingerprint(payload["edit_json_schema"]))
        self.assertEqual(payload["edit_json_schema"]["x-ricebowl-recipe-version"],
                         recipes.load("classic").schema_version)
        with patch("sys.stderr"):
            self.assertEqual(cli(["de", "creator-schema", "--recipe", "classic",
                                  "--output", "/tmp/unwanted.json"]), 1)


if __name__ == "__main__":
    unittest.main()
