"""RicePlate recipe security and actual Waybar adapter behavior."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import recipes, session


class _Panel:
    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _valid():
    return json.loads(recipes.BUILTINS["classic"].read_text())


class RecipeTests(unittest.TestCase):
    def test_bundled_recipes_have_different_real_panel_structures(self):
        classic = recipes.load("classic")
        chrome = recipes.load("chrome")
        self.assertNotEqual(classic.sections, chrome.sections)
        self.assertEqual(classic.sections[0], ("launcher", "tasks"))
        self.assertEqual(chrome.sections[1], ("tasks",))
        self.assertEqual(classic.position, "bottom")
        self.assertNotEqual(classic.colors, chrome.colors)
        for recipe in (classic, chrome):
            config, css = recipes.waybar_config(recipe)
            parsed = json.loads(config)
            self.assertEqual(parsed["height"], recipe.height)
            self.assertIn("custom/rice-launcher", json.dumps(parsed))
            self.assertIn(recipe.colors[0], css)

    def test_schema_rejects_unsupported_executable_or_extra_keys(self):
        data = _valid()
        data["on_click"] = "curl https://example.org | sh"
        with self.assertRaisesRegex(recipes.RecipeError, "exactly"):
            recipes.parse(json.dumps(data).encode())
        data.pop("on_click")
        data["colors"]["background"] = "red; background-image: url(file:///secret)"
        with self.assertRaisesRegex(recipes.RecipeError, "hexadecimal"):
            recipes.parse(json.dumps(data).encode())
        data = _valid()
        data["panel"]["sections"]["start"].append("exec:rm -rf /")
        with self.assertRaisesRegex(recipes.RecipeError, "Invalid widget"):
            recipes.parse(json.dumps(data).encode())

    def test_duplicates_invalid_types_and_oversized_recipe_fail_closed(self):
        raw = recipes.BUILTINS["classic"].read_bytes()
        with self.assertRaisesRegex(recipes.RecipeError, "64 KiB"):
            recipes.parse(raw + b" " * (recipes.MAX_RECIPE_BYTES + 1))
        with self.assertRaisesRegex(recipes.RecipeError, "Duplicate recipe key"):
            recipes.parse(b'{"id":"one","id":"two"}')
        data = _valid()
        data["panel"]["height"] = True
        with self.assertRaisesRegex(recipes.RecipeError, "Panel height"):
            recipes.parse(json.dumps(data).encode())
        data = _valid()
        data["panel"]["sections"]["end"].append("tasks")
        with self.assertRaisesRegex(recipes.RecipeError, "only once"):
            recipes.parse(json.dumps(data).encode())

    def test_custom_recipe_requires_absolute_owner_private_file_without_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "owner.json"
            source.write_bytes(recipes.BUILTINS["classic"].read_bytes())
            source.chmod(0o600)
            self.assertEqual(recipes.load(str(source)).recipe_id, "classic")
            source.chmod(0o644)
            with self.assertRaisesRegex(recipes.RecipeError, "owner-only"):
                recipes.load(str(source))
            source.chmod(0o600)
            symlink = Path(folder) / "link.json"
            symlink.symlink_to(source)
            with self.assertRaisesRegex(recipes.RecipeError, "safely"):
                recipes.load(str(symlink))
        with self.assertRaisesRegex(recipes.RecipeError, "absolute"):
            recipes.load("relative.json")

    def test_cli_exposes_read_only_recipe_discovery(self):
        from macrice.cli import main
        with mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "recipes"]), 0)
            self.assertTrue(any("classic" in str(call) for call in printed.call_args_list))
            self.assertTrue(any("chrome" in str(call) for call in printed.call_args_list))

    def test_cli_validates_an_authored_recipe_without_starting_wayland(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "authored.json"
            file.write_bytes(recipes.BUILTINS["classic"].read_bytes())
            file.chmod(0o600)
            with mock.patch("builtins.print") as printed:
                self.assertEqual(main(["de", "recipes", "--recipe", str(file), "--json"]), 0)
            result = json.loads(printed.call_args.args[0])
            self.assertEqual([item["id"] for item in result], ["classic"])
            file.chmod(0o644)
            with mock.patch("sys.stderr"):
                self.assertEqual(main(["de", "recipes", "--recipe", str(file)]), 1)

    def test_recipe_init_creates_private_editable_template_without_overwrite(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "my chrome rice.json"
            command = ["de", "recipe-init", "--base", "chrome", "--id", "my-rice",
                       "--name", "My Chrome Rice", "--output", str(destination)]
            with mock.patch("builtins.print") as printed:
                self.assertEqual(main(command), 0)
                self.assertTrue(any("--nested" in str(call) for call in printed.call_args_list))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(recipes.load(str(destination)).recipe_id, "my-rice")
            self.assertEqual(recipes.load(str(destination)).sections,
                             recipes.load("chrome").sections)
            original = destination.read_bytes()
            with mock.patch("sys.stderr"):
                self.assertEqual(main(command), 1)
            self.assertEqual(destination.read_bytes(), original)

    def test_schema_v2_changes_waybar_widget_widths_but_preserves_v1(self):
        source = _valid()
        legacy = recipes.parse(json.dumps(source).encode())
        self.assertIsNone(legacy.metrics)
        _, legacy_css = recipes.waybar_config(legacy)
        self.assertNotIn("min-width", legacy_css)

        source["schema_version"] = 2
        source["panel"]["metrics"] = {
            "launcher_width": 120, "task_width": 196, "clock_width": 80,
        }
        authored = recipes.parse(json.dumps(source).encode())
        self.assertEqual(authored.metrics, (120, 196, 80))
        config, css = recipes.waybar_config(authored)
        self.assertEqual(json.loads(config)["height"], 36)
        self.assertIn("#custom-rice-launcher { min-width: 104px; }", css)
        self.assertIn("#taskbar button { min-width: 182px; }", css)
        self.assertIn("#clock { min-width: 64px; }", css)

    def test_schema_v2_requires_all_metrics_and_rejects_invalid_values(self):
        source = _valid()
        source["schema_version"] = 2
        with self.assertRaisesRegex(recipes.RecipeError, "exactly"):
            recipes.parse(json.dumps(source).encode())
        source["panel"]["metrics"] = {
            "launcher_width": 104, "task_width": 164, "clock_width": 96,
        }
        for key, invalid in (("launcher_width", 63), ("launcher_width", 257),
                             ("task_width", 95), ("task_width", True),
                             ("clock_width", 257), ("clock_width", "96")):
            with self.subTest(key=key, invalid=invalid):
                broken = json.loads(json.dumps(source))
                broken["panel"]["metrics"][key] = invalid
                with self.assertRaisesRegex(recipes.RecipeError, "bounded integer"):
                    recipes.parse(json.dumps(broken).encode())
        for malformed in (dict(launcher_width=100, task_width=100),
                          dict(launcher_width=100, task_width=100, clock_width=100,
                               exec="anything")):
            with self.assertRaisesRegex(recipes.RecipeError, "exactly"):
                source["panel"]["metrics"] = malformed
                recipes.parse(json.dumps(source).encode())
        source = _valid()
        source["panel"]["metrics"] = {
            "launcher_width": 104, "task_width": 164, "clock_width": 96,
        }
        with self.assertRaisesRegex(recipes.RecipeError, "exactly"):
            recipes.parse(json.dumps(source).encode())

    def test_cli_schema_v2_template_roundtrip_and_flag_scope(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "v2.json"
            command = ["de", "recipe-init", "--schema-version", "2", "--base", "chrome",
                       "--id", "tuned-panel", "--name", "Custom panel", "--output",
                       str(destination)]
            with mock.patch("builtins.print"):
                self.assertEqual(main(command), 0)
            authored = recipes.load(str(destination))
            self.assertEqual(authored.recipe_id, "tuned-panel")
            self.assertEqual(authored.metrics, recipes.METRIC_DEFAULTS)
            self.assertEqual(json.loads(destination.read_text())["schema_version"], 2)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with mock.patch("sys.stderr"):
                self.assertEqual(main(command), 1)
                self.assertEqual(main(["de", "recipes", "--schema-version", "2"]), 1)
            with self.assertRaisesRegex(recipes.RecipeError, "Unsupported"):
                recipes.create_from_template(source="chrome", destination=destination,
                                             recipe_id="valid-id", name="Valid name",
                                 schema_version=11)

    def test_recipe_init_rejects_invalid_metadata_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new.json"
            for recipe_id, name in (("Invalid_ID", "Good name"),
                                    ("safe-id", "Has\x00control"),
                                    ("safe-id", "Hidden\x7fdelete"),
                                    ("safe-id", "Hidden\u0085separator")):
                with self.subTest(recipe_id=recipe_id):
                    with self.assertRaises(recipes.RecipeError):
                        recipes.create_from_template(source="classic", destination=destination,
                                                     recipe_id=recipe_id, name=name)
                    self.assertFalse(destination.exists())
            with self.assertRaisesRegex(recipes.RecipeError, "absolute"):
                recipes.create_from_template(source="classic", destination=Path("relative.json"),
                                             recipe_id="valid-id", name="Good name")

    def test_recipe_init_does_not_follow_existing_destination_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            important = Path(directory) / "keep.json"
            important.write_text("must not be replaced", encoding="utf-8")
            destination = Path(directory) / "authored.json"
            destination.symlink_to(important)
            with self.assertRaises(FileExistsError):
                recipes.create_from_template(source="classic", destination=destination,
                                             recipe_id="safe-id", name="Good name")
            self.assertEqual(important.read_text(encoding="utf-8"), "must not be replaced")
            self.assertTrue(destination.is_symlink())

    def test_offline_import_export_and_named_preview_are_round_trippable(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir(mode=0o700)
            source = root / "shared.json"
            data = _valid()
            data["id"] = "my-offline-rice"
            data["name"] = "An offline rice"
            source.write_text(json.dumps(data), encoding="utf-8")
            source.chmod(0o644)  # Shareable input does not have to be private.
            exported = root / "export.json"
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                self.assertEqual(main(["de", "recipe-import", "--recipe", str(source)]), 0)
                installed = config / "ricebowl" / "recipes" / "my-offline-rice.json"
                self.assertEqual(installed.stat().st_mode & 0o777, 0o600)
                self.assertEqual(installed.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(recipes.load("my-offline-rice").name, "An offline rice")
                self.assertEqual(recipes.native_token("my-offline-rice"), str(installed))
                with mock.patch("builtins.print") as printed:
                    self.assertEqual(main(["de", "recipes", "--json"]), 0)
                self.assertIn("my-offline-rice", json.loads(printed.call_args.args[0])[-1]["id"])
                self.assertEqual(main(["de", "recipe-export", "--recipe", "my-offline-rice",
                                       "--output", str(exported)]), 0)
                self.assertEqual(exported.read_bytes(), source.read_bytes())
                self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
                with mock.patch("sys.stderr"):
                    self.assertEqual(main(["de", "recipe-import", "--recipe", str(source)]), 1)
                    self.assertEqual(main(["de", "recipe-export", "--recipe", "my-offline-rice",
                                           "--output", str(exported)]), 1)
                self.assertEqual(exported.read_bytes(), source.read_bytes())
            self.assertEqual(source.stat().st_mode & 0o777, 0o644)

    def test_offline_import_rejects_invalid_unsafe_or_reserved_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir(mode=0o700)
            source = root / "source.json"
            data = _valid()
            data["id"] = "custom-one"
            source.write_text(json.dumps(data), encoding="utf-8")
            source.chmod(0o666)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                with self.assertRaisesRegex(recipes.RecipeError, "owner-controlled"):
                    recipes.import_recipe(source)
                source.chmod(0o600)
                link = root / "alias.json"
                link.symlink_to(source)
                with self.assertRaisesRegex(recipes.RecipeError, "safely"):
                    recipes.import_recipe(link)
                data["id"] = "classic"
                source.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(recipes.RecipeError, "reserved"):
                    recipes.import_recipe(source)
                data["id"] = "invalid!"
                source.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(recipes.RecipeError, "Recipe ID"):
                    recipes.import_recipe(source)
            self.assertFalse((config / "ricebowl").exists())

    def test_import_rejects_symlinked_or_exposed_collection_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir(mode=0o700)
            exposed = root / "exposed"
            exposed.mkdir(mode=0o700)
            (config / "ricebowl").symlink_to(exposed, target_is_directory=True)
            source = root / "owner.json"
            data = _valid()
            data["id"] = "custom-one"
            source.write_text(json.dumps(data), encoding="utf-8")
            source.chmod(0o600)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                with self.assertRaisesRegex(recipes.RecipeError, "Unsafe"):
                    recipes.import_recipe(source)
            (config / "ricebowl").unlink()
            (config / "ricebowl").mkdir(mode=0o755)
            (config / "ricebowl" / "recipes").mkdir(mode=0o755)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                with self.assertRaisesRegex(recipes.RecipeError, "owner-only"):
                    recipes.import_recipe(source)

    def test_recipe_portability_does_not_accept_irrelevant_cli_flags(self):
        from macrice.cli import main
        with mock.patch("sys.stderr"):
            for arguments in (["de", "recipe-import", "--recipe", "/tmp/unused.json", "--nested"],
                              ["de", "recipe-export", "--recipe", "classic"],
                              ["de", "recipes", "--output", "/tmp/new.json"]):
                with self.subTest(arguments=arguments):
                    self.assertEqual(main(arguments), 1)

    def test_nested_shell_generates_private_files_then_removes_them(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            commands = []
            config_paths = []

            def spawn(command, **_kwargs):
                commands.append(command)
                if command[0] == "/usr/bin/waybar":
                    config = Path(command[command.index("--config") + 1])
                    style = Path(command[command.index("--style") + 1])
                    self.assertEqual(json.loads(config.read_text())["modules-center"],
                                     ["wlr/taskbar"])
                    self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(style.stat().st_mode & 0o777, 0o600)
                    config_paths.extend([config, style])
                return _Panel()

            env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
                   "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": directory,
                   "RICEBOWL_DE_RECIPE": "chrome"}
            with mock.patch("macrice.de.session.signal.signal"):
                self.assertEqual(session.shell(environment=env,
                                 which=lambda name: "/usr/bin/waybar" if name == "waybar" else None,
                                 spawn=spawn), 0)
            self.assertEqual(len(config_paths), 2)
            self.assertTrue(all(not path.exists() for path in config_paths))


if __name__ == "__main__":
    unittest.main()
