"""Independent routes use no retired implementation; the retired math card stays read-only."""
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / '.studio'))
import appearance
import designs
import director_plan
import lines
from visual_plan import VisualPlanError, plan_scene_rows


class IndependentLinesTest(unittest.TestCase):
    def test_routes_freeze(self):
        catalog = lines.validate_catalogues()
        self.assertEqual(set(designs.DESIGN_IDS), set(catalog))
        self.assertNotIn('card', catalog)
        self.assertNotIn('math', catalog)
        with self.assertRaisesRegex(ValueError, 'No design selected'):
            lines.select({})
        for design in designs.DESIGN_IDS:
            state = {'mode': design}
            self.assertEqual(design, lines.frozen({'line': lines.bind(state)})['id'])
            self.assertEqual(design, lines.select(state)['id'])
        if 'english' in designs.DESIGN_IDS:
            state = {'mode': 'english'}
            self.assertEqual('ENGLISH_PLAN.template.md', lines.select(state)['plan_template'])
            self.assertEqual([], director_plan.parse('', {'line': lines.bind(state)}, {'S01': {}})['findings'])

    def test_retired_math_is_recognised_but_never_run(self):
        for identity in ('math', 'explainer/math-rap'):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'retired.*reselect'):
                lines.select({'mode': identity})
        old = ({'mode': 'math'}, {'line': {'id': 'explainer/math-rap', 'version': 1}},
               {'design': 'math', 'design_live': True},
               {'mode': 'explainer', 'series_binding': {'spec': 'math-rap'}},
               {'line': {'id': 'old', 'version': 1}, 'design_snapshot': {'capabilities': {'checks': ['math', 'math-complete']}}})
        for state in old:
            with self.subTest(state=state):
                self.assertTrue(lines.retired_math(state))
        self.assertFalse(lines.retired_math({'design': 'stage-full', 'mode': 'math', 'series_binding': {'spec': 'math-rap'}}))
        # Frozen snapshots that declared the math checks still validate for reading.
        caps = designs.legacy_capabilities('math')
        designs.validate_capabilities(caps)
        self.assertEqual(['math', 'math-complete'], caps['checks'])
        # A math-plan fence is no longer special anywhere.
        header = '---\n' + json.dumps({'plan_format': '3.5.2', 'mode': 'math'}) + '\n---\n## S01\n'
        rows = plan_scene_rows(header + '```math-plan\n{"units": []}\n```\n')
        self.assertEqual([], rows['S01']['events'])
        self.assertNotIn('math_plan', rows['S01'])

    def test_retired_mode_keeps_configuration_source(self):
        for identity in ('card', 'showcase', 'math'):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'retired.*reselect'):
                lines.select({'mode': identity})
        for source in ('Account', 'Series', 'Appearance selection'):
            with self.subTest(source=source), self.assertRaisesRegex(appearance.AppearanceError, source + ' uses retired mode card'):
                appearance.check_mode('card', source)
        with self.assertRaises(ValueError):
            lines.frozen({'line': {'id': 'card', 'version': 1}})
        # Historical identities stay locatable for reading, not creation.
        self.assertEqual('explainer', lines.frozen({'line': {'id': 'explainer', 'version': 1}})['id'])

    def test_card_default_captions(self):
        expected = {'english': False, 'stage-full': True, 'stage-light': True, 'collage': True}
        for identity, enabled in expected.items():
            if identity not in designs.DESIGN_IDS:
                continue
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


if __name__ == '__main__':
    unittest.main()
