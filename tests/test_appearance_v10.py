"""v10 declarative styling shares native and fallback presentation tokens."""

import json
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from macrice.de import catalog, creator_contract, drafts, pack, recipes, review, session


class AppearanceV10Tests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((Path(__file__).parent / "fixtures/riceplate-components-v9.json")
                               .read_text(encoding="utf-8"))
        self.base["schema_version"] = 10
        self.base["appearance"] = {
            "font_scale": 2, "font_weight": "bold", "item_spacing": 6,
            "hover": "#336699", "focus": "#ffffff", "disabled": "#7a7a7a",
        }

    def test_style_roundtrip_and_waybar_css_and_compact(self):
        sample_path = Path(__file__).parent / 'fixtures/riceplate-appearance-v10.json'
        sample = recipes.parse(sample_path.read_bytes())
        self.assertEqual(review._manifest(sample), json.loads(sample_path.read_text()))
        recipe = recipes.parse(json.dumps(self.base).encode())
        self.assertEqual(review._manifest(recipe), self.base)
        wide_json, wide_css = recipes.waybar_config(recipe, screen_width=1366)
        compact_json, _ = recipes.waybar_config(recipe, screen_width=640)
        self.assertEqual(json.loads(wide_json)["spacing"], 6)
        self.assertIn('font-size: 16px', wide_css)
        self.assertIn('font-weight: bold', wide_css)
        self.assertIn('#336699', wide_css)
        self.assertIn('#ffffff', wide_css)
        self.assertIn('#7a7a7a', wide_css)
        self.assertIn('Wi-Fi (N/A)', wide_json)
        self.assertNotIn('Wi-Fi (N/A)', compact_json)
        self.assertIn('/appearance/font_scale', creator_contract.EDITABLE_PATHS)
        self.assertEqual(catalog.describe()['recipe']['shell_extensions']['appearance']['since_schema'], 10)

    def test_reject_unsafe_values_and_missing_or_legacy_appearance(self):
        for key, value in (
            ('font_scale', 0), ('font_scale', True), ('font_scale', 3),
            ('font_weight', 'font.ttf'), ('item_spacing', -1), ('item_spacing', 99),
            ('hover', 'red'), ('focus', '#ffffff; exec'), ('disabled', None),
        ):
            with self.subTest(key=key, value=value):
                data = json.loads(json.dumps(self.base))
                data['appearance'][key] = value
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())
        for mutation in ('missing', 'extra', 'old-version'):
            data = json.loads(json.dumps(self.base))
            if mutation == 'missing':
                del data['appearance']
            elif mutation == 'extra':
                data['appearance']['exec'] = 'sh'
            else:
                data['schema_version'] = 9
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(data).encode())

    def test_template_draft_and_pack_preserve_tokens_without_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.json'
            recipe = recipes.create_from_template(source='classic', destination=source,
                recipe_id='styled-shell', name='Styled Shell', schema_version=10)
            self.assertIsNotNone(recipe.appearance)
            edit = Path(folder) / 'edit.json'
            edit.write_text(json.dumps({'edit_version': 1, 'operations': [
                {'op': 'set', 'path': '/appearance/item_spacing', 'value': 8},
                {'op': 'set', 'path': '/appearance/font_weight', 'value': 'bold'},
            ]}), encoding='utf-8')
            target = Path(folder) / 'draft.json'
            drafts.create_edit(recipe_token=str(source), edit_source=edit, destination=target)
            self.assertEqual(recipes.load(str(target)).appearance.item_spacing, 8)
            self.assertEqual(recipes.load(str(source)).appearance.item_spacing, 4)
            archive = Path(folder) / 'style.ricepack'
            pack.export_pack(str(target), archive)
            self.assertTrue(pack.inspect_pack(archive)['ok'])

    def test_waybar_compiles_distinct_compact_rules_per_output(self):
        recipe = recipes.parse(json.dumps(self.base).encode())
        config, css = recipes.waybar_output_configs(recipe,
                                                     {'eDP-1': 640, 'HDMI-A-1': 1920})
        bars = json.loads(config)
        self.assertEqual(len(bars), 3)
        self.assertEqual({bar['output'] for bar in bars if isinstance(bar['output'], str)},
                         {'eDP-1', 'HDMI-A-1'})
        fallback_bar = next(bar for bar in bars if bar['name'] == 'rice-output-fallback')
        self.assertEqual(fallback_bar['output'], ['!HDMI-A-1', '!eDP-1', '*'])
        self.assertNotIn('custom/rice-control-0', fallback_bar['modules-left'])
        compact = next(bar for bar in bars if bar['output'] == 'eDP-1')
        wide = next(bar for bar in bars if bar['output'] == 'HDMI-A-1')
        self.assertNotIn('custom/rice-control-0', compact['modules-left'])
        self.assertTrue(any('rice-control' in key for key in wide['modules-left']))
        self.assertIn('rice-output-0', css)
        self.assertIn('rice-output-1', css)
        self.assertIn('rice-output-fallback', css)
        with mock.patch('macrice.de.session.subprocess.run') as run:
            run.return_value.stdout = json.dumps([
                {'name': 'eDP-1', 'enabled': True, 'scale': 2.0,
                 'modes': [{'width': 1280, 'height': 800, 'current': True}]},
                {'name': 'HDMI-A-1', 'enabled': True, 'scale': 1.0,
                 'modes': [{'width': 1920, 'height': 1080, 'current': True}]},
            ])
            rendered, _ = session._waybar_recipe_config(recipe, {'WAYLAND_DISPLAY': 'wayland-1'},
                lambda name: '/usr/bin/wlr-randr' if name == 'wlr-randr' else None)
            self.assertEqual(len(json.loads(rendered)), 3)
            run.assert_called_once()
        fallback, _ = session._waybar_recipe_config(recipe, {}, lambda _name: None)
        self.assertIsInstance(json.loads(fallback), dict)


if __name__ == '__main__':
    unittest.main()
