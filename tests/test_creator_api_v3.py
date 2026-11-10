"""Creator v3 discovery is safe, structured and matches actual CLI support."""

import unittest

from macrice.de import catalog, creator_contract, recipes


class CreatorApiV3Tests(unittest.TestCase):
    def test_feature_negotiation_tracks_catalog_and_recipe_parsers(self):
        api = creator_contract.describe_creator_api()
        cat = catalog.describe()
        features = api["feature_negotiation"]
        self.assertEqual(api["api_version"], 3)
        self.assertEqual(features["catalog_version"], cat["catalog_version"])
        self.assertEqual(features["recipe_schema_versions"], cat["recipe"]["schema_versions"])
        self.assertEqual(features["recommended_authoring_schema"], 11)
        self.assertEqual(creator_contract.describe_ricepack()["recipe_schema_versions"],
                         features["recipe_schema_versions"])
        flags = {item["id"]: item for item in features["features"]}
        self.assertEqual(len(flags), len(features["features"]))
        self.assertTrue(flags["shared-status-action-bindings"]["supported"])
        self.assertTrue(flags["cross-surface-design-tokens"]["supported"])
        self.assertTrue(flags["private-native-font-and-icon-assets"]["supported"])
        self.assertTrue(flags["manual-region-pixel-qa"]["supported"])
        self.assertTrue(flags["interactive-region-correction-qa"]["supported"])
        self.assertTrue(flags["read-only-draft-preflight-and-fingerprint-guards"]["supported"])
        self.assertTrue(flags["private-creator-version-lineage"]["supported"])
        self.assertEqual(api["manual_region_qa"]["max_regions"], 8)
        self.assertEqual(api["manual_region_qa"]["correction_cycle"]["max_measurements"], 12)
        self.assertTrue(flags["interactive-desktop-widgets"]["supported"])
        self.assertFalse(flags["arbitrary-screenshot-one-click-conversion"]["supported"])
        self.assertFalse(flags["window-decoration-control-across-all-apps"]["supported"])

    def test_command_effects_require_user_approval_for_active_changes(self):
        api = creator_contract.describe_creator_api()
        commands = {item["command"]: item for item in api["commands"]}
        self.assertEqual(len(commands), len(api["commands"]))
        for name, command in commands.items():
            with self.subTest(name=name):
                self.assertIn(command["mutation_scope"], api["mutation_scope_values"])
                self.assertFalse(command["executes_recipe_commands"])
        for name in ("creator-live-apply", "creator-live-restore"):
            self.assertEqual(commands[name]["mutation_scope"], "active-wayland-session")
            self.assertTrue(commands[name]["requires_explicit_user_invocation"])
        for name in ("audio-default", "notification-dismiss", "notification-invoke"):
            self.assertEqual(commands[name]["mutation_scope"], "active-user-session")
            self.assertTrue(commands[name]["requires_explicit_user_invocation"])
        for name in ("creator-stage", "creator-rollback"):
            self.assertEqual(commands[name]["mutation_scope"], "next-login")
            self.assertTrue(commands[name]["requires_explicit_user_invocation"])
        self.assertEqual(commands["catalog"]["mutation_scope"], "none")
        self.assertEqual(commands["review"]["mutation_scope"], "none")
        self.assertEqual(commands["render"]["mutation_scope"], "private-file")
        self.assertEqual(commands["draft-check"]["mutation_scope"], "none")
        self.assertEqual(commands["creator-history"]["mutation_scope"], "none")
        self.assertFalse(commands["draft-check"]["requires_explicit_user_invocation"])
        self.assertEqual(commands["visual-compare"]["mutation_scope"],
                         "private-file-optional")
        self.assertFalse(commands["draft-edit"]["requires_explicit_user_invocation"])
        self.assertEqual(commands["draft-edit"]["mutation_scope"], "private-file")

    def test_documented_workflow_uses_only_advertised_commands(self):
        spec = creator_contract.describe_creator_api()
        names = {item["command"] for item in spec["commands"]} | {"creator-api"}
        for step in spec["authoring_workflow"]:
            self.assertTrue(set(step["commands"]) <= names)
        self.assertEqual(set(recipes.Appearance.__dataclass_fields__),
                         {"font_scale", "font_weight", "item_spacing", "hover", "focus", "disabled"})


if __name__ == "__main__":
    unittest.main()
