"""Contract tests for offline RiceBowl Creator component discovery."""

import json
import unittest
from unittest import mock

from macrice.de import catalog, recipes
from macrice.de import creator_contract


class ComponentCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_truthful_and_declarative(self):
        info = catalog.describe()
        catalog.validate_catalog_contract()
        self.assertEqual(info["catalog_version"], 10)
        self.assertEqual(info["scope"], "wayland-shell-preview")
        self.assertFalse(info["complete_desktop_environment"])
        self.assertEqual(info["recipe"]["schema_versions"], [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertFalse(info["recipe"]["custom_commands"])
        self.assertFalse(info["recipe"]["custom_actions"])
        self.assertEqual(info["recipe"]["external_assets"], "PNG")
        self.assertEqual(info["recipe"]["maximum_bytes"], recipes.MAX_RECIPE_BYTES)
        self.assertEqual(info["authoring"]["draft_edit"], creator_contract.describe())
        catalog_command = next(command for command in
                               creator_contract.describe_creator_api()["commands"]
                               if command["command"] == "catalog")
        self.assertEqual(catalog_command["contract_version"], info["catalog_version"])
        self.assertEqual(info["authoring"]["draft_edit"]["operation"], "set")
        self.assertFalse(info["authoring"]["draft_edit"]["mutates_active_desktop"])
        self.assertEqual(info["authoring"]["visual_compare"],
                         creator_contract.describe_visual_qa())
        self.assertFalse(info["authoring"]["visual_compare"]["captures_live_desktop"])
        self.assertEqual(info["recipe"]["sections"], ["start", "center", "end"])
        self.assertEqual(info["recipe"]["panel_positions"], ["top", "bottom"])
        self.assertEqual({part["id"] for part in info["components"]}, recipes.WIDGETS)
        implemented = {part["id"] for part in info["components"]
                       if part["native"] != "unavailable"}
        self.assertEqual(implemented, {"launcher", "tasks", "clock", "battery", "network", "audio", "tray"})
        components = {part["id"]: part for part in info["components"]}
        self.assertEqual(components["network"]["status_backend"], "bounded-nmcli-worker")
        self.assertEqual(components["audio"]["status_backend"], "bounded-wpctl-worker")
        self.assertFalse(components["network"]["interactive"])
        self.assertFalse(components["audio"]["interactive"])
        self.assertEqual(components["tray"]["native"], "experimental-sni")
        self.assertEqual(components["tray"]["visible_slots"], 4)
        self.assertEqual(components["tray"]["overflow_navigation"],
                         "native-output-local-popup")
        self.assertEqual(components["battery"]["status_backend"],
                         "read-only-linux-sysfs-power-supply")
        self.assertFalse(components["battery"]["interactive"])
        self.assertTrue(components["launcher"]["keyboard_navigation"])
        self.assertTrue(components["tasks"]["keyboard_navigation"])
        self.assertFalse(components["clock"]["keyboard_navigation"])
        self.assertTrue(components["clock"]["calendar_popup"])
        self.assertTrue(components["clock"]["popup_keyboard_navigation"])
        self.assertEqual(components["launcher"]["output_ownership"], "per-output")
        self.assertEqual(components["tasks"]["output_ownership"], "per-output")
        self.assertEqual(components["clock"]["output_ownership"], "per-output")
        shell = {part["id"]: part for part in info["shell_components"]}
        self.assertEqual(set(shell), {"native-menu", "calendar-popup", "desktop-shortcut", "desktop-widget", "shared-component"})
        self.assertEqual(shell["native-menu"]["actions"], sorted(recipes.MENU_ACTIONS))
        self.assertTrue(shell["native-menu"]["search"])
        self.assertEqual(shell["native-menu"]["pins"], "private-per-rice-fixed-actions")
        self.assertEqual(shell["native-menu"]["saved_actions_max"], 8)
        self.assertEqual(shell["native-menu"]["visible_action_rows"], 4)
        self.assertTrue(shell["native-menu"]["close_on_output_removal"])
        self.assertEqual(shell["native-menu"]["notifications"]["action"], "notifications")
        self.assertTrue(shell["native-menu"]["notifications"]["dismiss_one"])
        self.assertEqual(shell["native-menu"]["notifications"]["osd"], "native-audio-actions")
        self.assertEqual(shell["native-menu"]["notifications"]["history_ui"],
                         "read-only-past-tab")
        self.assertEqual(shell["native-menu"]["settings"]["action"], "settings")
        self.assertFalse(shell["native-menu"]["settings"]["fully_native_settings"])
        self.assertFalse(shell["calendar-popup"]["events"])
        self.assertFalse(shell["calendar-popup"]["localized_month_labels"])
        self.assertTrue(shell["calendar-popup"]["close_on_output_removal"])
        self.assertEqual(shell["desktop-shortcut"]["actions"], sorted(recipes.ICON_ACTIONS))
        self.assertTrue(shell["desktop-shortcut"]["hotplug_across_outputs"])
        self.assertFalse(shell["desktop-shortcut"]["arbitrary_commands"])
        self.assertEqual(shell["desktop-widget"]["kinds"], sorted(recipes.DESKTOP_WIDGET_KINDS))
        self.assertEqual(shell["desktop-widget"]["waybar"], "not_available")
        icons = info["recipe"]["shell_extensions"]["desktop"]["icons"]
        self.assertTrue(icons["keyboard_navigation"])
        self.assertEqual(icons["keyboard_focus_entry"], "pointer-or-compositor-focus")
        self.assertTrue(icons["pointer_drag"])
        self.assertEqual(icons["keyboard_arrow_movement_px"], 16)
        self.assertEqual(icons["position_storage"], "private-per-rice-not-source-recipe")
        self.assertEqual({name: field["default"] for name, field in
                          info["recipe"]["metrics"]["fields"].items()},
                         dict(zip(recipes.METRIC_FIELDS, recipes.METRIC_DEFAULTS)))

    def test_agent_json_catalog_is_deterministic_read_only_and_flag_scoped(self):
        from macrice.cli import main

        with mock.patch("builtins.print") as printer:
            self.assertEqual(main(["de", "catalog", "--json"]), 0)
            first = printer.call_args.args[0]
        self.assertEqual(json.loads(first), catalog.describe())
        with mock.patch("builtins.print") as printer:
            self.assertEqual(main(["de", "catalog", "--json"]), 0)
            self.assertEqual(printer.call_args.args[0], first)
        with mock.patch("builtins.print") as printer:
            self.assertEqual(main(["de", "catalog"]), 0)
            rows = "\n".join(args.args[0] for args in printer.call_args_list)
            self.assertIn("launcher", rows)
            self.assertIn("not available", rows)
        for flags in (("--recipe", "classic"), ("--nested",),
                      ("--panel", "native"), ("--output", "/tmp/unused.json"),
                      ("--schema-version", "2")):
            with self.subTest(flags=flags), mock.patch("sys.stderr"):
                self.assertEqual(main(["de", "catalog", *flags]), 1)

    def test_catalog_serializes_to_json_without_private_environment_data(self):
        payload = json.dumps(catalog.describe(), sort_keys=True, ensure_ascii=False)
        # The bounded Creator inventory grows when existing components gain
        # real variants; preserve a sensible wire-size ceiling without hiding
        # new documented properties to satisfy the old near-full 16 KiB cap.
        self.assertLess(len(payload), 24_576)
        self.assertNotIn("/home/", payload)
        self.assertNotIn("https://", payload)
        self.assertNotIn("exec:", payload)


if __name__ == "__main__":
    unittest.main()
