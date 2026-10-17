"""Isolated v3.7 product contracts; no production roots or external providers."""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import designs
import lines
import settings
import visual_diagnostics as diagnostics
from visual_plan import plan_scene_rows, VisualPlanError


def plan(mode='explainer', spec=None):
    line = lines.select({'mode': mode, 'series_binding': {'spec': spec} if spec else {}})
    fields = {key: '说明' for key in line['brief']['required']}
    if mode == 'explainer':
        fields['参考机制'] = 'persistent-anchor'
    document = ('---\n' + json.dumps({'plan_format': '3.7.0', 'line': {key: line[key] for key in ('id', 'version')}}) + '\n---\n## 导演 Brief\n' +
            '\n'.join(f'**{key}：** {value}' for key, value in fields.items()) +
            '\n## 分镜表\n| 段 | 起点口播词 | 观众看到什么 | 本段任务 | 主体 | 交接例外 | 延续 |\n'
            '|---|---|---|---|---|---|---|\n| S01·A1 | 词 | 卡片 | 解释 | | | node |\n'
            '| S01·B1 | 证据 | 媒体 | 证明 | | cut | node |\n| S01·A2 | 所以 | 卡片 | 总结 | | | |\n## S01\n')
    if spec == 'math-rap':
        from test_math_chain import contract
        intent = contract()
        intent['cues'][0]['cue'] = '词'
        document += '```math-plan\n' + json.dumps(intent) + '\n```\n'
    return document


class V370Test(unittest.TestCase):
    def test_lines_settings_and_legacy(self):
        self.assertIn(len(lines.validate_catalogues()), (2, len(designs.DESIGN_IDS)))
        state = {'line': lines.bind({'mode': 'explainer'}), 'settings': {'direction_approval': False}}
        self.assertEqual({'value': False, 'source': 'variant'}, settings.effective(state, {'direction_approval': True})['direction_approval'])
        del state['settings']
        self.assertEqual({'value': True, 'source': 'user'}, settings.effective(state, {'direction_approval': True})['direction_approval'])
        self.assertTrue(settings.effective(state)['direction_approval']['value'])
        self.assertTrue(settings.effective({}, {'direction_approval': False})['direction_approval']['value'])
        for value in ({'unknown': True}, {'direction_approval': 1}, {'critic.max_rounds': True}, {'critic.model': '   '}):
            with self.assertRaises(ValueError):
                settings.validate(value, 'user')
        for mode, suffix in (('explainer', None), ('explainer', 'math-rap'), ('showcase', 'science')):
            state = {'mode': mode, 'submodule': suffix, 'series_binding': {'spec': suffix} if mode == 'explainer' and suffix else {}}
            if mode == 'showcase' and not (Path(lines.__file__).with_name('designs') / 'collage/design.json').is_file():
                continue
            values = settings.effective({'line': lines.bind(state)})
            self.assertTrue(values['direction_approval']['value'])
            self.assertEqual('external' if mode == 'explainer' else 'off', values['critic.provider']['value'])

    def test_neutral_critic_provenance_and_frozen_compatibility(self):
        import copy
        settings.validate({'critic.provider': 'external', 'critic.model': 'text-only'}, 'variant')
        state = {'line': lines.bind({'mode': 'explainer'}),
                 'settings': {'critic.provider': 'codex-subagent', 'critic.model': 'old-model'}}
        before = copy.deepcopy(state)
        self.assertEqual('codex-subagent', settings.effective(state)['critic.provider']['value'])
        self.assertEqual(state, before)
        with self.assertRaises(ValueError):
            settings.validate(state['settings'], 'variant')
        self.assertEqual('', settings.effective({'line': state['line']})['critic.model']['value'])

    def test_storyboard_and_legacy_parser(self):
        row = plan_scene_rows(plan())['S01']
        self.assertEqual(['A', 'B', 'A'], [segment['role'] for segment in row['segments']])
        self.assertEqual('第2层动态图解或第4层文字', row['segments'][0]['subject'])
        self.assertEqual('第2层媒体', row['segments'][1]['subject'])
        plan_scene_rows(plan('explainer'))
        plan_scene_rows(plan('explainer', 'math-rap'))
        self.assertEqual([], plan_scene_rows('---\n{"plan_format":"3.5.2"}\n---\n## S01\n')['S01']['events'])
        cases = [plan().replace('**禁止项：** 说明', ''), plan().replace('S01·A1', 'S01·B1'),
                 plan().replace('S01·A2', 'S01·B2'), plan().replace('## S01\n', '## S02\n'),
                 plan('explainer').replace('persistent-anchor', 'unknown'), plan('explainer').replace('persistent-anchor', '')]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(VisualPlanError):
                plan_scene_rows(text)

    def test_pixels_exceptions_camera_and_missing(self):
        samples = [{'time': t / 2, 'ready': True, 'still': {'from': (t - 1) / 2, 'mean_delta': 0}} for t in range(1, 7)]
        thresholds = lines.select({'mode': 'explainer'})['thresholds']
        rhythm = {'declared_exceptions': []}
        result = diagnostics.still_diagnostics(samples, rhythm, thresholds)
        self.assertEqual(3, result['intervals'][0]['duration'])
        rhythm['declared_exceptions'] = [{'kind': 'pause', 'start': 0, 'end': 3}]
        self.assertTrue(diagnostics.still_diagnostics(samples, rhythm, thresholds)['intervals'][0]['declared_exception'])
        rhythm['declared_exceptions'][0]['kind'] = 'talking_head'
        self.assertEqual([], diagnostics.still_diagnostics(samples, rhythm, thresholds)['intervals'])
        rhythm['declared_exceptions'] = []
        samples[0]['rhythm_candidates'] = [{'kind': 'camera_start', 'time': 0, 'duration': 3}]
        self.assertEqual([], diagnostics.still_diagnostics(samples, rhythm, thresholds)['intervals'])

    def test_carry_exact_boundary_and_missing_markers(self):
        samples = [{'time': 1 - 1 / 60, 'ready': True, 'carry': [{'id': 'object', 'box': [0, 0, 80, 80]}]},
                   {'time': 1, 'ready': True, 'carry': [{'id': 'object', 'box': [40, 0, 80, 80]}]}]
        result = diagnostics.carry_diagnostics(samples, [1], declared={1: ['missing']})['boundaries']
        self.assertEqual('unpaired', result[0]['status'])
        self.assertEqual(40, result[1]['delta']['x'])
        samples[1]['carry'][0]['box'][0] = 0
        self.assertEqual(0, diagnostics.carry_diagnostics(samples, [1])['boundaries'][0]['delta']['x'])
        samples[1]['carry'] = []
        self.assertEqual('unpaired', diagnostics.carry_diagnostics(samples, [1])['boundaries'][0]['status'])


if __name__ == '__main__':
    unittest.main()
