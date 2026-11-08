"""Cross-component mockup shell recipe: menu, wallpaper, tokens and responsiveness."""

import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from macrice.de import catalog, drafts, recipes, review, session


FIXTURE = Path(__file__).parent / "fixtures/riceplate-shell-v4.json"
SIDEBAR_V6 = Path(__file__).parent / "fixtures/riceplate-sidebar-v6.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class ShellV4Tests(unittest.TestCase):
    def test_v6_sidebar_menu_roundtrip_and_version_gate(self):
        sample = json.loads(SIDEBAR_V6.read_text(encoding="utf-8"))
        parsed = recipes.parse(SIDEBAR_V6.read_bytes())
        self.assertEqual(parsed.menu_presentation, "sidebar")
        self.assertEqual(review._manifest(parsed), sample)
        self.assertEqual(parsed.menu[0], "Y2K Desktop")
        self.assertEqual(len(parsed.menu[1]), 2)
        menu_contract = next(item for item in catalog.describe()["shell_components"]
                             if item["id"] == "native-menu")
        self.assertEqual(menu_contract["presentation"]["variants"], ["tabs", "sidebar"])

        sample["menu"].pop("presentation")
        self.assertEqual(recipes.parse(json.dumps(sample).encode()).menu_presentation, "tabs")
        sample["menu"]["presentation"] = "tabs"
        self.assertEqual(recipes.parse(json.dumps(sample).encode()).menu_presentation, "tabs")
        sample["menu"]["presentation"] = "arbitrary-layout"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(sample).encode())
        sample["menu"]["presentation"] = None
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(sample).encode())
        sample["menu"]["presentation"] = "sidebar"
        sample["schema_version"] = 5
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(sample).encode())

    def test_v6_creator_can_edit_menu_presentation_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            edit = Path(folder) / "edit.json"
            output = Path(folder) / "sidebar.json"
            sample = json.loads(SIDEBAR_V6.read_text(encoding="utf-8"))
            sample["menu"].pop("presentation")
            source.write_text(json.dumps(sample), encoding="utf-8")
            source.chmod(0o600)
            edit.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/menu/presentation", "value": "sidebar"},
            ]}), encoding="utf-8")
            result = drafts.create_edit(recipe_token=str(source), edit_source=edit,
                                        destination=output)
            self.assertEqual(result["changes"], [{
                "path": "/menu/presentation", "before": "tabs", "after": "sidebar"}])
            self.assertEqual(recipes.load(str(output)).menu_presentation, "sidebar")
            self.assertNotIn("presentation", json.loads(source.read_text())["menu"])

            legacy = Path(folder) / "legacy.json"
            sample["schema_version"] = 5
            legacy.write_text(json.dumps(sample), encoding="utf-8")
            legacy.chmod(0o600)
            with self.assertRaises(drafts.DraftError) as rejected:
                drafts.create_edit(recipe_token=str(legacy), edit_source=edit,
                                   destination=Path(folder) / "denied.json")
            self.assertEqual(rejected.exception.code, "unsupported_property_for_schema")

    def test_real_backend_outputs_and_width_specific_compilation(self):
        parsed = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(parsed.schema_version, 4)
        self.assertEqual(review._manifest(parsed), _fixture())
        self.assertEqual(parsed.tokens, (12, 6))
        self.assertEqual(recipes.wallpaper_path(parsed).name, "luna-hills.jpg")
        self.assertTrue(recipes.wallpaper_path(parsed).is_file())
        wide_config, css = recipes.waybar_config(parsed, screen_width=1200)
        compact_config, compact_css = recipes.waybar_config(parsed, screen_width=600)
        wide = json.loads(wide_config)
        small = json.loads(compact_config)
        self.assertIn("custom/rice-label", " ".join(wide["modules-left"]))
        self.assertEqual(small["modules-left"], ["custom/rice-launcher"])
        self.assertEqual(small["modules-center"], ["wlr/taskbar"])
        self.assertNotIn("custom/rice-label", " ".join(small["modules-left"]))
        self.assertIn("padding: 0 12px", css)
        self.assertIn("border-radius: 6px", compact_css)

    def test_real_labwc_menu_uses_only_fixed_safe_actions(self):
        parsed = recipes.parse(FIXTURE.read_bytes())
        xml = recipes.labwc_menu(parsed)
        root = ET.fromstring(xml)
        top = root.find("menu")
        self.assertEqual(top.attrib["id"], "root-menu")
        self.assertEqual(top.attrib["label"], "Y2K Desktop")
        groups = top.findall("menu")
        self.assertEqual([group.attrib["label"] for group in groups],
                         ["Programs", "Session"])
        actions = [item.find("action").attrib for group in groups
                   for item in group.findall("item")]
        self.assertEqual(actions, [
            {"name": "Execute", "command": "fuzzel"},
            {"name": "Execute", "command": "foot"},
            {"name": "Execute", "command": "swaylock -f"},
            {"name": "Exit"},
        ])
        # Even a custom menu that omits logout must retain an emergency exit.
        custom = _fixture()
        custom["menu"]["groups"] = [{"title": "Apps", "actions": ["applications"]}]
        parsed = recipes.parse(json.dumps(custom).encode())
        fallback = ET.fromstring(recipes.labwc_menu(parsed)).find("menu")
        self.assertEqual(fallback.findall("item")[-1].find("action").attrib,
                         {"name": "Exit"})

    def test_v4_init_edit_review_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            edit = Path(folder) / "edit.json"
            output = Path(folder) / "draft.json"
            created = recipes.create_from_template(
                source="classic", destination=source, recipe_id="new-shell",
                name="New shell", schema_version=4)
            self.assertEqual(created.schema_version, 4)
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
            edit.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/desktop/wallpaper", "value": "aurora-day"},
                {"op": "set", "path": "/menu/title", "value": "New Menu"},
                {"op": "set", "path": "/tokens/label_padding", "value": 12},
                {"op": "set", "path": "/responsive/compact_max_width", "value": 680},
            ]}), encoding="utf-8")
            drafted = drafts.create_edit(recipe_token=str(source), edit_source=edit,
                                         destination=output)
            self.assertTrue(drafted["created"])
            self.assertFalse(drafted["applied"])
            actual = recipes.load(str(output))
            self.assertEqual(actual.wallpaper, "aurora-day")
            self.assertEqual(actual.menu[0], "New Menu")
            self.assertEqual(actual.compact[0], 680)
            changed = review.review(str(output), str(source))["comparison"]["changes"]
            self.assertEqual(review.review(str(output))["scope"], "wayland-shell-preview")
            self.assertEqual({entry["path"] for entry in changed}, {
                "/desktop/wallpaper", "/menu/title", "/tokens/label_padding",
                "/responsive/compact_max_width",
            })

    def test_denies_unsafe_actions_wallpapers_tokens_compact_nodes_and_unknown_keys(self):
        failures = [
            ("menu", "groups", [{"title": "Scripts", "actions": ["exec-shell"]}]),
            ("desktop", "wallpaper", "../../etc/passwd"),
            ("tokens", "task_radius", True),
            ("responsive", "compact_max_width", 20),
            ("responsive", "compact_layout", {"start": [
                {"type": "widget", "id": "exec-command"}], "center": [], "end": []}),
        ]
        for section, key, value in failures:
            with self.subTest(section=section, key=key):
                sample = _fixture()
                sample[section][key] = value
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(sample).encode())
        for removed in ("menu", "desktop", "tokens", "responsive"):
            with self.subTest(removed=removed):
                sample = _fixture()
                sample.pop(removed)
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(sample).encode())
        sample = _fixture()
        sample["menu"]["groups"][1]["actions"].append("terminal")
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(sample).encode())

    @mock.patch("macrice.de.session.os.geteuid", return_value=os.getuid())
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_session_generates_isolated_menu_and_cleans_only_own_config(self, _check, _uid):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "shell.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            runtime = Path(folder) / "runtime"
            runtime.mkdir(mode=0o700)
            env = {"XDG_RUNTIME_DIR": str(runtime),
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=dummy"}
            tools = {name: f"/usr/bin/{name}" for name in session.REQUIRED_TOOLS}

            class Captured(Exception):
                pass

            def execute(_program, args, process_env):
                config = Path(args[args.index("--config-dir") + 1])
                self.assertEqual(config.parent, runtime)
                self.assertEqual(config.stat().st_mode & 0o777, 0o700)
                menu = ET.parse(config / "menu.xml")
                self.assertEqual(menu.getroot().find("menu").attrib["label"], "Y2K Desktop")
                self.assertEqual(process_env["RICEBOWL_DE_SESSION_CONFIG"], str(config))
                session._cleanup_labwc_config(process_env)
                self.assertFalse(config.exists())
                raise Captured

            with self.assertRaises(Captured):
                session.start(nested=True, recipe=str(source), environment=env,
                              which=tools.get, execute=execute)
            self.assertEqual(list(runtime.iterdir()), [])

    def test_shell_uses_selected_wallpaper_with_real_swaybg_argv(self):
        commands = []

        class Process:
            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

        def spawn(args, **kwargs):
            commands.append(args)
            return Process()

        with tempfile.TemporaryDirectory() as folder:
            recipe_file = Path(folder) / "shell.json"
            recipe_file.write_bytes(FIXTURE.read_bytes())
            recipe_file.chmod(0o600)
            env = {"RICEBOWL_DE_SHELL_CHILD": "1", "WAYLAND_DISPLAY": "wayland-0",
                   "RICEBOWL_DE_NESTED": "1", "RICEBOWL_DE_RECIPE": str(recipe_file),
                   "XDG_RUNTIME_DIR": folder}
            tools = {"waybar": "/usr/bin/waybar", "swaybg": "/usr/bin/swaybg"}
            with mock.patch("macrice.de.session.signal.signal"):
                self.assertEqual(session.shell(environment=env, which=tools.get,
                                               spawn=spawn), 0)
        self.assertEqual(commands[0], ["/usr/bin/swaybg", "--image",
                                       str(recipes.wallpaper_path(recipes.parse(
                                           FIXTURE.read_bytes()))), "--mode", "fill"])
        self.assertEqual(commands[-1][0], "/usr/bin/waybar")

    def test_catalog_advertises_real_renderer_limits(self):
        data = catalog.describe()
        self.assertEqual(data["catalog_version"], 6)
        self.assertEqual(data["recipe"]["schema_versions"], [1, 2, 3, 4, 5, 6])
        extensions = data["recipe"]["shell_extensions"]
        self.assertEqual(extensions["desktop"]["widgets"], "not_implemented")
        self.assertEqual(extensions["responsive"]["native"], "live-panel-layout-switch")


if __name__ == "__main__":
    unittest.main()
