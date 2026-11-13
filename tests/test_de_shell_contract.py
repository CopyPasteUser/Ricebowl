"""Cross-rice shell contract and schema acceptance; offline test only."""
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from macrice.de import catalog, creator_contract, recipes, shell_contract as shell
ROOT = Path(__file__).resolve().parents[1] / "examples" / "wayland"

class ShellContractTests(unittest.TestCase):
    def test_two_distinct_layouts_share_backend_components(self):
        a = recipes.parse((ROOT / "test-taskbar-shell.json").read_bytes())
        b = recipes.parse((ROOT / "test-dock-shell.json").read_bytes())
        self.assertNotEqual(a.layout, b.layout)
        self.assertNotEqual(a.menu_presentation, b.menu_presentation)
        self.assertNotEqual(a.colors, b.colors)
        self.assertEqual({(c.role,c.binding) for c in a.components},
                         {(c.role,c.binding) for c in b.components})
        for item in (a,b):
            self.assertEqual(item.schema_version, 12)
            config, _ = recipes.waybar_config(item)
            self.assertIn("wlr/taskbar", config)
            self.assertIn("custom/rice-launcher", config)

    def test_downgrade_and_unknown_binding_fail_closed(self):
        data = json.loads((ROOT / "test-taskbar-shell.json").read_text())
        bad = dict(data, schema_version=8)
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(bad).encode())
        bad = json.loads(json.dumps(data))
        bad["components"][0]["binding"] = "exec:sh"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(bad).encode())
        data["components"].append({"id":"desktop-switch","role":"action",
                                   "binding":"show-desktop","label":"Desktop"})
        data["panel"]["layout"]["start"].append({"type":"component","ref":"desktop-switch"})
        parsed = recipes.parse(json.dumps(data).encode())
        self.assertIn("show-desktop", {c.binding for c in parsed.components})

    def test_existing_recipes_remain_accepted(self):
        recipes.load("classic")
        recipes.load("chrome")
        recipes.parse((ROOT / "xp-luna.json").read_bytes())

    def test_actions_are_strict_and_surfaces_match_native(self):
        description = shell.describe()
        self.assertEqual(set(description["surfaces"]["panel"]),
                         recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS)
        self.assertEqual(set(description["surfaces"]["menu"]), recipes.MENU_ACTIONS)
        self.assertEqual(set(description["surfaces"]["desktop"]),
                         recipes.ICON_ACTIONS | recipes.PANEL_ACTIONS | recipes.PANEL_CONTROLS)
        for surface in shell.Surface:
            for action in description["surfaces"][surface.value]:
                self.assertEqual(shell.bind(action, surface).action_id, action)
            for action in ["", "exec:sh", "desktop:fake.desktop", "wifi-on", "run;sh"]:
                with self.assertRaises(ValueError):
                    shell.bind(action, surface)
        with self.assertRaises(ValueError):
            shell.bind("logout", shell.Surface.PANEL)
        with self.assertRaises(ValueError):
            shell.bind("settings", "panel")

    def test_unavailable_denied_busy_failed_feedback(self):
        action = shell.bind("audio-mute", shell.Surface.PANEL)
        base = {"backend_present":True, "capability_present":True}
        self.assertEqual(shell.feedback(action, **base).state, shell.State.READY)
        self.assertEqual(shell.feedback(action, **base, pending="audio-mute").state, shell.State.APPLYING)
        self.assertEqual(shell.feedback(action, **base, pending="wifi-toggle").state, shell.State.BUSY)
        self.assertEqual(shell.feedback(action, **base, permitted=False).state, shell.State.DENIED)
        self.assertTrue(shell.feedback(action, **base, failed="audio-mute").actionable)
        self.assertEqual(shell.feedback(action, backend_present=False, capability_present=True).state,
                         shell.State.UNAVAILABLE)

    def test_atomic_next_session_switch_restore_and_invalid_target(self):
        # This is the actual selection transaction in a disposable XDG tree.
        # It is intentionally NOT a claim of a live compositor switch.
        with tempfile.TemporaryDirectory(prefix="ricebowl-shell-contract-") as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                imported = {}
                for name in ("test-taskbar-shell", "test-dock-shell"):
                    _, imported[name] = recipes.import_recipe(ROOT / f"{name}.json")
                self.assertEqual(recipes.current_selection(), ("classic", None))
                recipes.change_selection("test-taskbar-shell", expected_active="classic")
                self.assertEqual(recipes.current_selection(), ("test-taskbar-shell", "classic"))
                recipes.change_selection("test-dock-shell", expected_active="test-taskbar-shell")
                self.assertEqual(recipes.current_selection(), ("test-dock-shell", "test-taskbar-shell"))
                recipes.change_selection(restore=True, expected_active="test-dock-shell")
                self.assertEqual(recipes.current_selection(), ("test-taskbar-shell", "test-dock-shell"))
                selection = Path(tmp) / "ricebowl" / "recipes" / ".active-recipe"
                unchanged = selection.read_bytes()
                # Unsafe/malformed recipe must not alter current or rollback state.
                imported["test-dock-shell"].write_text('{"schema_version":12,"id":"x"}')
                with self.assertRaises(recipes.RecipeError):
                    recipes.change_selection("test-dock-shell", expected_active="test-taskbar-shell")
                self.assertEqual(selection.read_bytes(), unchanged)
                self.assertEqual(recipes.current_selection(), ("test-taskbar-shell", "test-dock-shell"))

    def test_creator_catalog_discovers_action_contract(self):
        self.assertEqual(catalog.describe()["action_contract"], shell.describe())
        self.assertEqual(creator_contract.describe()["shell_action_contract"], shell.describe())
        catalog.validate_catalog_contract()

if __name__ == "__main__":
    unittest.main()
