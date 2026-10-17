"""Independent routes and shared math delivery use no retired implementation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / '.studio'))
import appearance
import designs
import director_plan
import lines
import math_build
import math_kit_assets
from visual_plan import VisualPlanError, plan_scene_rows


@unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card contract; checked in personal assembly')
class IndependentLinesTest(unittest.TestCase):
    def test_routes_freeze_and_legacy_math(self):
        catalog = lines.validate_catalogues()
        self.assertEqual(set(designs.DESIGN_IDS), set(catalog))
        self.assertEqual({'explainer', 'showcase', 'math', 'english'}, set(appearance.MODES))
        self.assertNotIn('card', catalog)
        with self.assertRaisesRegex(ValueError, 'No design selected'):
            lines.select({})
        for design in designs.DESIGN_IDS:
            state = {'mode': design}
            self.assertEqual(design, lines.frozen({'line': lines.bind(state)})['id'])
            self.assertEqual(design, lines.select(state)['id'])
        for mode in ('math', 'english'):
            state = {'mode': mode}
            self.assertEqual(mode.upper() + '_PLAN.template.md', lines.select(state)['plan_template'])
            self.assertEqual([], director_plan.parse('', {'line': lines.bind(state)}, {'S01': {}})['findings'])
        for state in ({'mode': 'math'}, {'line': {'id': 'explainer/math-rap', 'version': 1}},
                      {'mode': 'explainer', 'series_binding': {'spec': 'math-rap'}}):
            self.assertTrue(lines.is_math(state))
        self.assertFalse(lines.is_math({'mode': 'english', 'series_binding': {'spec': 'math-rap'}}))
        self.assertEqual('explainer/math-rap', lines.frozen({'line': {'id': 'explainer/math-rap', 'version': 1}})['id'])

    def test_retired_mode_keeps_configuration_source(self):
        for identity in ('card', 'showcase'):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'retired.*reselect'):
                lines.select({'mode': identity})
        for source in ('Account', 'Series', 'Appearance selection'):
            with self.subTest(source=source), self.assertRaisesRegex(appearance.AppearanceError, source + ' uses retired mode card'):
                appearance.check_mode('card', source)
        with self.assertRaises(ValueError):
            lines.frozen({'line': {'id': 'card', 'version': 1}})
        # Historical identities stay locatable for reading, not creation.
        self.assertEqual('explainer', lines.frozen({'line': {'id': 'explainer', 'version': 1}})['id'])

    def test_math_and_english_default_captions_off(self):
        expected = {'math': False, 'english': False, 'stage-full': True,
                    'stage-light': True, 'collage': True}
        for identity, enabled in expected.items():
            with self.subTest(identity=identity):
                self.assertEqual(enabled, designs.defaults(identity)['captions.enabled'])

    def test_card_fences_are_rejected_but_plain_panels_and_screens_remain(self):
        header = '---\n{"plan_format":"3.5.2"}\n---\n'
        with self.assertRaisesRegex(VisualPlanError, 'retired card Plan'):
            plan_scene_rows(header.replace('"plan_format":', '"mode":"card","plan_format":') + '## S01\n')
        for fence in ('```', '~~~~'):
            with self.assertRaisesRegex(VisualPlanError, 'retired card Plan block'):
                plan_scene_rows(header + f'## S01\n{fence}card C1 · P001\ntitle: old\n{fence}\n')
        rows = plan_scene_rows(header + '## S01\n### I01 · P001\n```screen\nA card-shaped panel\n```\n')
        self.assertEqual('A card-shaped panel', rows['S01']['screens']['I01']['实际表达'])
        self.assertNotIn('cards', rows['S01'])

    def test_direct_math_requires_actual_teaching_contract(self):
        header = '---\n' + json.dumps({'plan_format': '3.7.0', 'mode': 'math',
                                     'line': {'id': 'math', 'version': 1}}) + '\n---\n## S01\n'
        intent = {'units': [{'id': 'U1', 'symbol': 'x', 'graphic': 'square'}],
                  'symbols': {'x': 'square'}, 'invariants': ['Fixed equality'],
                  'zero_basics': [{'relation': 'same value', 'action': 'retain square'}],
                  'cues': [{'cue': 'x', 'keep': [], 'reveal': ['U1'], 'remove': []}]}
        plan = header + '```math-plan\n' + json.dumps(intent) + '\n```\n'
        rows = plan_scene_rows(plan)
        self.assertEqual('math_reveal', rows['S01']['events'][0]['change'])
        self.assertEqual([], rows['S01']['segments'])
        self.assertEqual(rows, plan_scene_rows(plan.replace('"mode": "math", ', '')))
        intent['units'][0]['graphic'] = '<graphic>'
        with self.assertRaisesRegex(VisualPlanError, 'incomplete_math_plan'):
            plan_scene_rows(header + '```math-plan\n' + json.dumps(intent) + '\n```\n')

    def test_math_export_and_embedded_json_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'math-source'
            result = math_kit_assets.export_math_kit(REPO, source)
            self.assertEqual('math-kit@v1', result['component_ref'])
            self.assertEqual({'asset.json', 'math-kit.js', 'math-kit.css', 'USAGE.md'},
                             {p.name for p in source.iterdir()})
            self.assertEqual(result, math_kit_assets.export_math_kit(REPO, source))
        self.assertNotIn('</script>', math_build.script_json({'text': '</script>'}))
        self.assertEqual(64, len(math_build.digest(b'math')))


if __name__ == '__main__':
    unittest.main()
