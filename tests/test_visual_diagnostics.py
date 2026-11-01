"""Small advisory text checks, without browser, WorkStore or rendering."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
from visual_diagnostics import normalize, plan_information, static_inventory, text_diagnostics
from visual_plan import VisualPlanError
from visual_diagnostics import explainer_diagnostics


SOURCE = '系统首先读取用户提供的原始材料然后提取关键事实并保留必要条件最后生成简洁清楚且便于理解的上屏文字'
FORMAT = '---\n{"plan_format":"3.5.2"}\n---\n'


def plan(expression=SOURCE, info='I01'):
    return FORMAT + '## S01\n' + information('I01', expression)


def information(identity, expression):
    return f'\n### {identity} · {identity} · P001\n```screen\n{expression}\n```\n'


def samples(*parts, info='I01'):
    return [{'time': index * 0.5, 'ready': True, 'texts': [
        {'scene': 'S01', 'info': info, 'text': part, 'selector': '#card'}]}
        for index, part in enumerate(parts)]


class ExplainerDiagnosticsTests(unittest.TestCase):
    def test_math_checks_layer_and_explicit_assets_without_explainer_plan_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / 'index.html').write_text('<main data-hf-layer="background">'
                '<img data-character-ref="missing@v1"><audio src="outside.mp3"></audio></main>', encoding='utf-8')
            report = explainer_diagnostics(project, ['index.html'], {'mode': 'math'},
                '| 原 Scene ID | 使用信息 ID |\n|---|---|\n| S01 | I01 |\n')
            kinds = [item['kind'] for item in report['findings']]
            self.assertEqual(3, kinds.count('explainer_layer_missing'))
            self.assertIn('sound_asset_outside_closure', kinds)
            self.assertIn('character_asset_outside_closure', kinds)
            self.assertNotIn('explainer_plan_missing', kinds)

    def test_local_stems_are_exempt_but_remote_or_missing_ones_are_not(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / 'assets').mkdir()
            (project / 'assets/bgm.mp3').write_bytes(b'x')
            (project / 'index.html').write_text('<main data-hf-layer="background">'
                '<audio data-audio-role="stem" src="assets/bgm.mp3"></audio>'
                '<audio data-audio-role="stem" src="assets/gone.mp3"></audio>'
                '<audio data-audio-role="stem" src="https://example.com/a.mp3"></audio></main>', encoding='utf-8')
            report = explainer_diagnostics(project, ['index.html'], {'mode': 'math'},
                '| 原 Scene ID | 使用信息 ID |\n|---|---|\n| S01 | I01 |\n')
            flagged = [item['src'] for item in report['findings'] if item['kind'] == 'sound_asset_outside_closure']
            self.assertEqual(['assets/gone.mp3', 'https://example.com/a.mp3'], flagged)

    def test_layers_captions_assets_and_plan_are_advisory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / 'index.html').write_text('<main data-hf-layer="background"><audio src="outside.mp3"></audio>'
                '<img data-character-ref="missing@v1"></main>', encoding='utf-8')
            lock = {'mode': 'explainer', 'selection': {'captions': True}}
            report = explainer_diagnostics(project, ['index.html'], lock,
                '| 原 Scene ID | 主载体 | 事件与层 |\n|---|---|---|\n| S01 | | |\n')
            kinds = [item['kind'] for item in report['findings']]
            self.assertEqual(3, kinds.count('explainer_layer_missing'))
            self.assertIn('captions_lock_mismatch', kinds)
            self.assertIn('sound_asset_outside_closure', kinds)
            self.assertIn('character_asset_outside_closure', kinds)
            self.assertNotIn('explainer_plan_missing', kinds)
            self.assertEqual([], explainer_diagnostics(project, ['index.html'], {'mode': 'text-led'})['findings'])
            (project / 'index.html').write_text(''.join(f'<div data-hf-layer="{layer}"></div>'
                for layer in ('background', 'stage', 'overlay', 'text'))
                + '<audio data-audio-role="voice" src="speech.wav"></audio>'
                + '<audio data-asset-ref="tone@v1" src="vendor/tone.mp3"></audio>'
                + '<img data-character-ref="host@v1">', encoding='utf-8')
            assets = {'tone@v1': {'vendor_path': 'vendor', 'metadata': {'kind': 'media', 'entry': 'tone.mp3'}},
                      'host@v1': {'vendor_path': 'vendor', 'metadata': {'kind': 'character', 'entry': 'character.json'}}}
            with mock.patch('explainer.installed_assets', return_value=assets):
                self.assertEqual([], explainer_diagnostics(project, ['index.html'],
                    {'mode': 'explainer', 'selection': {'captions': False}})['findings'])


class VisualTextTests(unittest.TestCase):
    def diagnose(self, parts, **kwargs):
        return text_diagnostics(parts, '<!-- P001 -->\n' + SOURCE, '', kwargs.pop('plan', plan()), **kwargs)

    def test_five_layer_copy_hint_only_applies_to_text_layer(self):
        states = samples(SOURCE)
        for mode in ('math', 'english', 'explainer'):
            for layer in ('captions', 'background', 'stage', 'overlay', 'text', None):
                with self.subTest(mode=mode, layer=layer):
                    states[0]['texts'][0]['layer'] = layer
                    report = self.diagnose(states, mode=mode)
                    self.assertEqual(layer == 'text', any(hit['kind'] == 'suspected_copy' for hit in report['findings']))
                    if layer != 'text':
                        self.assertEqual(0, report['observed_groups'])
        states[0]['texts'][0]['layer'] = 'captions'
        self.assertTrue(any(hit['kind'] == 'suspected_copy' for hit in self.diagnose(states)['findings']))

    def test_same_information_id_in_other_layers_does_not_contaminate_text(self):
        text = '材料与结论之间的联系'
        for mode in ('math', 'english', 'explainer'):
            with self.subTest(mode=mode):
                states = samples(text)
                states[0]['texts'][0]['layer'] = 'text'
                states[0]['texts'].extend({'scene': 'S01', 'info': 'I01', 'text': SOURCE,
                    'selector': '#' + layer, 'layer': layer}
                    for layer in ('background', 'stage', 'overlay', 'captions'))
                report = self.diagnose(states, mode=mode, plan=plan(text))
                self.assertEqual([], report['findings'])
                self.assertEqual(1, report['observed_groups'])

    def test_reference_scope_skips_outside_text_and_shared_information(self):
        document = plan('完整定义') + '\n## S02\n**延续信息：** I01\n' + information('I02', '其他场景的完整结论')
        states = samples('完整定义')
        states[0]['texts'].append({'scene': 'S02', 'info': 'I02', 'text': '其他', 'selector': '#outside'})
        report = self.diagnose(states, plan=document, scene_ids=['S01'])
        self.assertEqual([], report['findings'])
        self.assertEqual(1, report['observed_groups'])
        self.assertFalse(any(hit.get('info') or hit.get('scene') for hit in report['unverified']))
        self.assertEqual([{'scene': 'S02', 'information_ids': ['I02', 'I01'],
                           'reason': 'outside_reference_scope'}], report['out_of_scope'])

    def test_copy_split_cards_and_distributed_rewording(self):
        changed = SOURCE.replace('首先', '先行').replace('然后', '随后').replace('最后', '最终')
        for states in (samples(SOURCE), samples(SOURCE[:16], SOURCE[16:32], SOURCE[32:]), samples(changed)):
            with self.subTest(states=states):
                report = self.diagnose(states)
                hits = [hit for hit in report['findings'] if hit['kind'] == 'suspected_copy']
                self.assertEqual(1, len(hits))
                self.assertGreaterEqual(hits[0]['coverage'], 0.8)

    def test_persistent_text_is_not_repeated_and_progressive_reveal_is_merged(self):
        report = self.diagnose(samples(SOURCE[:15], SOURCE[:30], SOURCE, SOURCE))
        self.assertEqual(SOURCE, report['findings'][0]['text'])

    def test_short_cards_with_shared_source_anchor_aggregate(self):
        expression = plan(SOURCE[:16], info='I01 I02 I03')
        expression += information('I02', SOURCE[16:32]) + information('I03', SOURCE[32:])
        states = samples(SOURCE[:16], SOURCE[16:32], SOURCE[32:])
        for index, sample in enumerate(states):
            sample['texts'][0]['info'] = f'I0{index + 1}'
        report = self.diagnose(states, plan=expression)
        self.assertEqual(['suspected_split_copy'], [item['kind'] for item in report['findings']])

    def test_explicit_exception_excludes_only_confirmed_fragment(self):
        confirmed = {'scene': 'S01', 'text': SOURCE[:20], 'source': 'SCRIPT.md#P001', 'reason': 'User confirmed exact definition'}
        report = self.diagnose(samples(SOURCE), exceptions=[confirmed])
        self.assertTrue(any(hit['kind'] == 'suspected_copy' for hit in report['findings']))
        self.assertEqual([confirmed], report['confirmed_exceptions'])
        for text in (SOURCE[:12], SOURCE[:32], SOURCE):
            approved = {**confirmed, 'text': text}
            report = self.diagnose(samples(text), plan=plan(text), exceptions=[approved])
            self.assertEqual([], report['findings'])
        with self.assertRaises(VisualPlanError):
            self.diagnose(samples(SOURCE), exceptions=[{**confirmed, 'text': 'not in source'}])

    def test_definition_label_is_not_automatic_exemption(self):
        self.assertEqual('suspected_copy', self.diagnose(samples(SOURCE))['findings'][0]['kind'])

    def test_plan_difference_and_missing_mapping_are_advisory(self):
        report = self.diagnose(samples(SOURCE), plan=plan('读取材料，保留条件，提炼表达'))
        self.assertIn('plan_implementation_difference', [hit['kind'] for hit in report['findings']])
        ambiguous = plan(info='I01 I02') + information('I02', SOURCE)
        report = self.diagnose(samples(SOURCE, info=''), plan=ambiguous)
        self.assertIn('semantic_mapping_requires_review', [entry['reason'] for entry in report['unverified']])
        self.assertIn('suspected_copy', [hit['kind'] for hit in report['findings']])
        self.assertNotIn('plan_information_missing', [hit['kind'] for hit in report['findings']])
        report = self.diagnose(samples('Unrelated decorative label', info=''), plan=plan())
        self.assertFalse(any(hit['kind'] == 'plan_implementation_difference' for hit in report['findings']))
        self.assertIn('semantic_mapping_requires_review', [entry['reason'] for entry in report['unverified']])

    def test_unready_sample_is_not_text_evidence_and_symbols_survive(self):
        states = samples(SOURCE)
        states[0]['ready'] = False
        self.assertEqual([], self.diagnose(states)['findings'])
        self.assertEqual('不低于-1.5%且≤20kg', normalize('不低于 -1.5%，且 ≤ 20 kg。'))

    def test_screen_blocks_keep_line_breaks_sources_and_information_boundaries(self):
        document = FORMAT + '''## S01

### I01
**来源：** SCRIPT.md#P001
```screen
给模型厂商和工具服务商
制定统一协议
# 字面标题
### I99
```

### I02
**来源：** RESEARCH.md#R001
尚无上屏正文。
````markdown
### I97
```screen
示例而非当前信息正文
```
````

### I03
**来源：** RESEARCH.md#R002
```screen
完整结论
| Scene | 信息 ID |
| --- | --- |
| S99 | I99 |
```

````markdown
### I98
```screen
示例而非信息声明
```
````
'''
        information, mapping = plan_information(document)
        self.assertEqual('给模型厂商和工具服务商\n制定统一协议\n# 字面标题\n### I99', information['I01']['实际表达'])
        self.assertEqual({'I01', 'I03'}, set(information))
        self.assertEqual('SCRIPT.md#P001', information['I01']['信息 ID / 来源'])
        self.assertNotIn('I02', information)
        self.assertEqual('完整结论\n| Scene | 信息 ID |\n| --- | --- |\n| S99 | I99 |', information['I03']['实际表达'])
        self.assertEqual({'S01': ['I01', 'I03']}, mapping)
        report = self.diagnose(samples('给模型厂商和工具服务商\n制定统一协议'), plan=document)
        self.assertFalse(any(item.get('info') == 'I02' for item in report['unverified']))

    def test_missing_truncated_difference_uncovered_and_old_format_rejected(self):
        expected = '统一协议让模型厂商与工具服务商交换完整消息'
        with self.assertRaisesRegex(VisualPlanError, '格式不支持'):
            plan_information('| Scene | 信息 ID |\n| --- | --- |\n| S01 | I01 |\n')
        formats = [plan(expected) + '\n## S02\n**延续信息：** I01\n']
        timeline = [{'id': 'S01', 'start': 0, 'duration': 2}, {'id': 'S02', 'start': 2, 'duration': 2}]
        for document in formats:
            for actual, kind in [('统一协议', 'plan_information_truncated'),
                                 ('模型厂商与工具服务商交换消息', 'plan_information_truncated'),
                                 ('互通', 'plan_information_truncated'),
                                 ('另一项流程为所有业务对象提供完全不同且更详细的处理方案', 'plan_implementation_difference')]:
                with self.subTest(document=document, actual=actual):
                    report = self.diagnose(samples(actual), plan=document, scenes=timeline)
                    self.assertEqual([kind], [hit['kind'] for hit in report['findings']])
                    self.assertIn({'scene': 'S02', 'info': 'I01', 'source': plan_information(document)[0]['I01']['信息 ID / 来源'],
                                   'reason': 'plan_information_not_observed'}, report['unverified'])
            report = self.diagnose([{'time': 0, 'ready': True, 'texts': []}], plan=document, scenes=timeline)
            self.assertEqual([('S01', 'plan_information_missing')],
                             [(hit['scene'], hit['kind']) for hit in report['findings']])
            states = samples(expected) + [{'time': 2, 'ready': True, 'texts': []}]
            report = self.diagnose(states, plan=document, scenes=timeline)
            self.assertEqual([('S02', 'plan_information_missing')],
                             [(hit['scene'], hit['kind']) for hit in report['findings']])
            states[1]['ready'] = False
            self.assertEqual([], self.diagnose(states, plan=document, scenes=timeline)['findings'])

    def test_empty_visible_text_does_not_create_a_group_or_hide_missing_information(self):
        report = self.diagnose(samples('   '))
        self.assertEqual(0, report['observed_groups'])
        self.assertEqual(['plan_information_missing'], [hit['kind'] for hit in report['findings']])

    def test_partly_unready_scene_keeps_unobserved_information_unverified(self):
        document = plan('完整定义和结论', info='I01 I02') + information('I02', '另一个完整结论')
        timeline = [{'id': 'S01', 'start': 0, 'duration': 2}]
        states = samples('定义') + [{'time': 1, 'ready': False, 'texts': []}]
        report = self.diagnose(states, plan=document, scenes=timeline)
        self.assertEqual(['plan_information_truncated'], [hit['kind'] for hit in report['findings']])
        self.assertIn({'scene': 'S01', 'info': 'I02', 'source': 'I02 · P001',
                       'reason': 'plan_information_not_observed'}, report['unverified'])
        states[1]['ready'] = True
        report = self.diagnose(states, plan=document, scenes=timeline)
        self.assertEqual(['plan_information_truncated', 'plan_information_missing'],
                         [hit['kind'] for hit in report['findings']])

    def test_multi_information_scene_resolves_exact_text_without_ids(self):
        # Synthetic mirror of a native reference Scene: seven blocks, split nodes, shared words, no data-info-id.
        blocks = {'I15': 'ALPHA', 'I16': '共同规则，使两端连通', 'I17': 'R = Rule\n规则', 'I18': '约定\n逐条执行',
                  'I19': 'ALPHA 甲端\n请求方', 'I20': 'ALPHA 乙端\n提供方', 'I21': '经 ALPHA 连接'}
        document = FORMAT + '## S06\n'
        narration = {'I15': 'ALPHA 是这一段的主题。', 'I16': '它是一套共同规则，它使两端连通。', 'I17': 'R 就是 Rule，也就是规则。',
                     'I18': '可以把它想成一份约定，大家逐条执行。', 'I19': '一边是 ALPHA 甲端，也就是请求方；',
                     'I20': '另一边是 ALPHA 乙端，也就是提供方；', 'I21': '两端经 ALPHA 连接。'}
        # Each block cites its own anchor, as the native Plan does.
        document += ''.join(f'\n### {info}\n**来源：** SCRIPT.md#P0{60 + int(info[1:])}\n```screen\n{text}\n```\n'
                            for info, text in blocks.items())
        script = ''.join(f'<!-- P0{60 + int(info[1:])} -->\n{text}\n' for info, text in narration.items())
        # Role lines are sampled before names to prove comparison follows Plan order, not DOM/reveal order.
        visible = ['ALPHA', '共同规则', '使两端连通', 'R = Rule', '规则', '约定', '逐条执行',
                   '请求方', 'ALPHA 甲端', '提供方', 'ALPHA 乙端', '经 ALPHA 连接']
        timeline = [{'id': 'S06', 'start': 0, 'duration': 6}]
        states = [{'time': index * 0.5, 'ready': True,
                   'texts': [{'scene': 'S06', 'info': None, 'text': text, 'selector': f'#n{position}'}
                             for position, text in enumerate(visible[:index + 1])]}
                  for index in range(len(visible))]
        report = text_diagnostics(states, script, '', document, scenes=timeline)
        self.assertEqual([], report['findings'])
        self.assertEqual(7, report['observed_groups'])
        self.assertNotIn('semantic_mapping_requires_review', [entry['reason'] for entry in report['unverified']])

        # Ambiguous (several blocks) or unmatched text keeps element identity: no merged copy candidate, missing becomes unverified.
        extra = [{'scene': 'S06', 'info': None, 'text': text, 'selector': f'#x{position}'}
                 for position, text in enumerate(['端', '装饰小字'])]
        report = text_diagnostics([{'time': 0, 'ready': True, 'texts': extra}], script, '', document, scenes=timeline)
        self.assertEqual([], report['findings'])
        unresolved = [entry for entry in report['unverified'] if entry['reason'] == 'semantic_mapping_requires_review']
        self.assertEqual([['#x0'], ['#x1']], [entry['selectors'] for entry in unresolved])
        self.assertEqual(7, sum(entry['reason'] == 'plan_information_mapping_unresolved' for entry in report['unverified']))

        # Explicit data-info-id takes precedence over text matching.
        explicit = [{'scene': 'S06', 'info': 'I18', 'text': 'ALPHA', 'selector': '#card'}]
        report = text_diagnostics([{'time': 0, 'ready': True, 'texts': explicit}], script, '', document, scenes=timeline)
        self.assertIn(('I18', 'plan_implementation_difference'),
                      [(hit.get('info'), hit['kind']) for hit in report['findings']])
        self.assertIn(('I15', 'plan_information_missing'), [(hit.get('info'), hit['kind']) for hit in report['findings']])

    def test_static_text_is_inventory_not_visibility_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('<p hidden>hidden candidate</p><!-- comment --><script>secret()</script><svg><text>visible</text></svg>')
            (root / 'data.json').write_text('{"title":"candidate"}')
            entries = static_inventory(root, ['index.html', 'data.json'])
            self.assertEqual(['hidden candidate', 'visible', 'candidate'], [entry['text'] for entry in entries])
            self.assertEqual('/title', entries[-1]['pointer'])


if __name__ == '__main__':
    unittest.main()
