"""v3.7.1 acceptance using real lifecycle/files and synthetic PNG Studio transport."""
import copy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest import mock

import test_v370_cli as fixtures
from test_work_cli import WORK_CLI as cli
import critic
import lines
import visual_memory as memory
from visual_diagnostics import rhythm_diagnostics


class V371Test(unittest.TestCase):
    run_cli = fixtures.V370CliTest.run_cli
    update = fixtures.V370CliTest.update
    call = fixtures.V370CliTest.call
    sampled = fixtures.V370CliTest.sampled

    def setUp(self):
        fixtures.V370CliTest.setUp(self)
        import explainer
        text = '词证据所以'
        cues = explainer.build_cues(text, json.dumps({'characters': [{'char': c, 'start': t, 'end': t + .2} for c,t in zip(text,[0,1,1.2,3,3.2])]}).encode())
        cli.write_json(self.project / 'runtime/cues.json', cues)
        mock.patch.object(cli.visual_diagnostics, 'probe', side_effect=self.sampled).start()

    def round(self, target=None):
        args = ('critic', 'round', *([target] if target else []), '--hyperframes-cli', str(self.cli_path), '--browser', '/usr/bin/google-chrome')
        return json.loads(self.call(*args))

    def retro(self, target):
        return json.loads(self.call('retro', 'open', target, '--hyperframes-cli', str(self.cli_path), '--browser', '/usr/bin/google-chrome'))

    def add_sample(self, name='demo'):
        round_ = self.round()
        self.retro(round_['draft_id'])
        sample = json.loads(self.call('sample', 'add', name, '--draft', round_['draft_id'], '--segment', 'S01', '--reason', '逐步揭示清晰'))
        return sample, round_

    def refs(self, refs):
        text = self.plan_path.read_text()
        if '**参考机制：**' in text:
            import re
            text = re.sub(r'^\*\*参考机制：\*\*[^\n]*', '**参考机制：** ' + refs, text, flags=re.M)
        else:
            text = text.replace('## 导演 Brief', '## 导演 Brief\n\n**参考机制：** ' + refs)
        self.plan_path.write_text(text)

    def tree(self, root):
        return {p.relative_to(root).as_posix(): memory.digest(p) for p in root.rglob('*') if p.is_file()}

    def test_retro_reuses_evidence_preserves_drafts_and_rejects_tampering(self):
        first = self.round()
        ledger = (self.variant / 'critic/ledger.json').read_bytes()
        result = self.retro(first['draft_id'])
        path = Path(result['path'])
        self.assertFalse(result['reused'])
        self.assertEqual([], json.loads(self.call('retro', 'check', first['draft_id']))['findings'])
        path.write_text(path.read_text() + '\nUser note\n')
        self.assertTrue(self.retro(first['draft_id'])['reused'])
        self.assertIn('User note', path.read_text())
        self.assertEqual(ledger, (self.variant / 'critic/ledger.json').read_bytes())
        (self.project / 'compositions/S01.html').write_text('<p>New frame</p>')
        second = self.call('preview', 'register')
        self.assertNotEqual(first['draft_id'], second)
        result2 = self.retro(second)
        self.assertNotEqual(str(path), result2['path'])
        self.assertIn('User note', path.read_text())
        self.assertEqual(ledger, (self.variant / 'critic/ledger.json').read_bytes())
        with self.assertRaises(cli.HarnessError):
            self.retro('draft-v999')
        self.assertFalse(list(self.variant.rglob('*.mp4')) + list(self.variant.rglob('*.webm')))
        binding = memory.read(path.parent / 'binding.json')
        self.assertEqual(cli.preview_metadata(self.variant / 'previews' / first['draft_id'])['snapshot_sha256'], binding['snapshot_sha256'])
        (path.parent / 'evidence/measurements.json').write_text('{}')
        with self.assertRaisesRegex(cli.HarnessError, 'evidence changed'):
            self.retro(first['draft_id'])

    def test_retro_schema_and_sample_independent_copies_states(self):
        sample, round_ = self.add_sample()
        sample_path = memory.library(self.root, 'sample') / sample['frames'][0]['path']
        original = self.variant / 'retro' / round_['draft_id'] / 'evidence/images/0.000000.png'
        self.assertNotEqual(original.stat().st_ino, sample_path.stat().st_ino)
        self.assertFalse(sample_path.is_symlink())
        self.assertEqual('explainer', sample['line'])
        self.assertTrue((self.root / 'sample-library/index/explainer.json').is_file())
        shown = json.loads(self.call('sample', 'show', sample['id']))
        self.assertEqual(str(sample_path), shown['frames'][0]['path'])
        with self.assertRaisesRegex(cli.HarnessError, 'already exists'):
            self.call('sample', 'add', 'demo', '--draft', round_['draft_id'], '--segment', 'S01', '--reason', 'again')
        self.call('sample', 'consolidate', sample['id'], '--into', 'rule:scene-reading')
        self.assertEqual('已巩固', json.loads(self.call('sample', 'show', sample['id']))['status'])
        self.call('sample', 'retire', sample['id'], '--reason', 'superseded')
        self.assertTrue(sample_path.exists())
        path = self.variant / 'retro' / round_['draft_id'] / 'VISUAL.md'
        path.write_text(path.read_text().replace('|---|---|---|---|---|---|---|---|', '|---|---|---|---|---|---|---|---|\n| broken | S01 | 0 | invalid | 单 Scene | 诊断 | 仅本片 | |', 1))
        self.assertIn('retro_enum', [x['kind'] for x in json.loads(self.call('retro', 'check', round_['draft_id']))['findings']])
        path.write_text(path.read_text().replace('现象 | Scene', 'missing | Scene'))
        self.assertIn('retro_fields', [x['kind'] for x in json.loads(self.call('retro', 'check', round_['draft_id']))['findings']])

    def test_plan_draft_reference_freezing_settings_and_verdict_coverage(self):
        sample, _ = self.add_sample()
        self.refs(sample['id'])
        with self.assertRaisesRegex(cli.HarnessError, 'plan refresh'):
            self.call('preview', 'register')
        refresh = json.loads(self.call('plan', 'refresh'))
        revision = refresh['revision']
        shown = json.loads(self.call('sample', 'show', sample['id'], '--plan-revision', str(revision)))
        self.assertEqual(6, len(shown['frames']))
        self.call('settings', 'set', 'critic.provider', 'external')
        round_ = self.round()
        package = Path(round_['package'])
        frozen = memory.frozen(package / 'reference-memory')
        self.assertEqual([f['sha256'] for f in shown['frames']], [f['sha256'] for f in frozen['references'][0]['frames']])
        self.assertIn('不评相似度', (package / 'PROMPT.md').read_text())
        original_files = critic.hashes(package / 'reference-memory')
        self.call('sample', 'retire', sample['id'], '--reason', 'new style')
        self.call('settings', 'set', 'samples.frames_per_reference', '2')
        repeat = self.round(round_['draft_id'])
        self.assertEqual(original_files, critic.hashes(Path(repeat['package']) / 'reference-memory'))
        entry = cli.read_json(self.variant / 'critic/ledger.json')['rounds'][-1]
        self.assertEqual([sample['id']], entry['reference_ids'])
        self.assertEqual(6, entry['settings']['samples.frames_per_reference']['value'])
        verdict = {key: entry[key] for key in ('round', 'draft_id', 'snapshot_sha256')}
        verdict.update(new_issues=[], previous=[], references=[{'id': sample['id'], 'status': '部分', 'detail': '文字揭示明确，后半段缺层次'}])
        file = self.root / 'verdict.json'
        for bad in ([], verdict['references'] * 2, [{'id': 'unknown', 'status': '达到', 'detail': 'frame'}], [{'id': sample['id'], 'status': 'similar', 'detail': 'frame'}]):
            cli.write_json(file, {**verdict, 'references': bad})
            with self.assertRaises(cli.HarnessError):
                self.call('critic', 'record', '--file', str(file))
        cli.write_json(file, verdict)
        self.call('critic', 'record', '--file', str(file))
        new = json.loads(self.call('plan', 'refresh'))
        self.assertGreater(new['revision'], revision)
        self.assertEqual(2, len(json.loads(self.call('sample', 'show', sample['id'], '--plan-revision', str(new['revision'])))['frames']))
        self.assertEqual(original_files, critic.hashes(package / 'reference-memory'))
        target = self.variant / 'previews' / round_['draft_id'] / 'reference-memory'
        (target / frozen['references'][0]['frames'][0]['path']).write_bytes(b'corrupt')
        with self.assertRaises((cli.HarnessError, ValueError)):
            self.round(round_['draft_id'])

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_cross_line_status_and_behavior_findings_showcase_reference(self):
        sample, _ = self.add_sample()
        path = memory.index_path(self.root, 'sample', 'explainer')
        records = memory.read(path); records[0]['runtime_version'] = '3.6.0'; memory.write(path, records)
        self.refs(sample['id'])
        findings = json.loads(self.call('plan', 'check'))['findings']
        self.assertIn('sample_predates_behavior', [v['kind'] for v in findings])
        effective = cli.effective_settings(self.root, cli.read_json(self.variant / 'variant.yaml'))
        _, _, findings = memory.resolve(self.root, '**参考机制：** ' + sample['id'], 'showcase/pdoom', effective)
        self.assertIn('mechanism_line_mismatch', [v['kind'] for v in findings])
        _, _, findings = memory.resolve(self.root, '**参考机制：** 跨线:' + sample['id'], 'showcase/pdoom', effective)
        self.assertNotIn('mechanism_line_mismatch', [v['kind'] for v in findings])
        self.call('sample', 'consolidate', sample['id'], '--into', 'mechanism:one-shape')
        self.assertIn('sample_consolidated', [v['kind'] for v in json.loads(self.call('plan', 'check'))['findings']])
        self.call('sample', 'retire', sample['id'], '--reason', 'covered')
        self.assertIn('sample_retired', [v['kind'] for v in json.loads(self.call('plan', 'check'))['findings']])
        self.assertEqual([], json.loads(self.call('sample', 'list', '--line', 'showcase/pdoom'))['samples'])
        self.assertEqual(1, len(json.loads(self.call('sample', 'list', '--all-lines'))['samples']))
        state = cli.read_json(self.variant / 'variant.yaml')
        state.update(mode='showcase', submodule='pdoom')
        state['line'] = lines.bind(state)
        cli.write_variant(self.variant, state)
        metadata = cli.plan_metadata(self.variant, state)
        self.plan_path.write_text('---\n' + json.dumps(metadata) + '\n---\n## 概念\n**参考机制：** 跨线:' + sample['id'] + '\n## S01\n')
        findings = json.loads(self.call('plan', 'check'))['findings']
        self.assertNotIn('mechanism_line_mismatch', [v['kind'] for v in findings])
        self.assertIn('sample_retired', [v['kind'] for v in findings])
        self.plan_path.write_text(self.plan_path.read_text().replace('跨线:', ''))
        self.assertIn('mechanism_line_mismatch', [v['kind'] for v in json.loads(self.call('plan', 'check'))['findings']])

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_known_defects_and_summary_leave_work_unchanged(self):
        sample, round_ = self.add_sample()
        path = self.variant / 'retro' / round_['draft_id'] / 'VISUAL.md'
        path.write_text(path.read_text().replace('|---|---|---|---|---|---|---|---|', '|---|---|---|---|---|---|---|---|\n| 后半静止 | S01 | 2 | 用户审查 | 单 Scene | 诊断 | 已知缺陷条目 | D01 |', 1))
        self.call('defect', 'add', 'D01', '--draft', round_['draft_id'], '--description', '后半静止', '--frame', 'images/2.000000.png')
        defects = json.loads(self.call('defect', 'list'))['defects']
        self.assertEqual(1, len(defects))
        self.assertEqual([], json.loads(self.call('defect', 'list', '--line', 'showcase/pdoom'))['defects'])
        second = self.round()
        review = memory.read(Path(second['package']) / 'memory.json')
        self.assertEqual(['D01'], [item['id'] for item in review['known_defects']])
        self.assertTrue(review['profile_checks'])
        entry = cli.read_json(self.variant / 'critic/ledger.json')['rounds'][-1]
        self.assertEqual(['D01'], entry['defect_ids'])
        self.call('defect', 'retire', 'D01', '--blocked-by', 'math_trailing_gap')
        self.assertTrue((self.root / 'known-defects' / defects[0]['frames'][0]['path']).is_file())
        third = self.round()
        self.assertEqual([], memory.read(Path(third['package']) / 'memory.json')['known_defects'])
        self.refs(sample['id']); self.call('plan', 'refresh')
        self.round(); self.round()
        before = self.tree(self.variant.parent.parent)
        report = json.loads(self.call('retro', 'summary'))
        self.assertEqual(before, self.tree(self.variant.parent.parent))
        self.assertEqual(1, report['sample_references'][sample['id']])
        self.assertEqual(1, report['defects'][0]['count'])
        self.assertTrue((self.root / 'retro-summary/SUMMARY.md').is_file())
        self.call('settings', 'set', 'samples.frames_per_reference', '2')
        self.call('plan', 'refresh')
        self.assertEqual(2, json.loads(self.call('retro', 'summary'))['sample_references'][sample['id']])

    def test_legacy_settings_defaults_overrides_invalid_values_and_scope(self):
        state = cli.read_json(self.variant / 'variant.yaml')
        for old in (False, True):
            if old:
                state.pop('line', None); cli.write_variant(self.variant, state)
            values = json.loads(self.call('settings', 'show'))['values']
            self.assertEqual(3, values['samples.max_references']['value'])
            self.assertEqual(6, values['samples.frames_per_reference']['value'])
        self.call('settings', 'set', '--layer', 'user', 'samples.frames_per_reference', '5')
        self.assertEqual('user', json.loads(self.call('settings', 'show'))['values']['samples.frames_per_reference']['source'])
        self.call('settings', 'set', 'samples.frames_per_reference', '2')
        self.assertEqual('variant', json.loads(self.call('settings', 'show'))['values']['samples.frames_per_reference']['source'])
        self.assertNotIn('line', cli.read_json(self.variant / 'variant.yaml'))
        for bad in ('0', '-1', 'true', '2.5'):
            with self.assertRaises(cli.HarnessError):
                self.call('settings', 'set', 'samples.max_references', bad)
        with self.assertRaises(cli.HarnessError):
            self.run_cli('sample', 'list')
        with self.assertRaises(cli.HarnessError):
            self.call('settings', 'set', 'direction_approval', 'false')

    def test_scene_tail_and_visible_other_events(self):
        scenes = [{'id': 'S01', 'start': 0, 'duration': 6}]
        def event(time, kind, layer, ident):
            common = dict(id=ident, time=time, duration=.2, kind=kind, layer=layer, scene='S01')
            return [dict(time=time-.001, ready=True, rhythm_candidates=[{**common, 'signature':'before', 'visible': True}]),
                    dict(time=time+.1, ready=True, rhythm_candidates=[{**common, 'signature':'after', 'visible': True}])]
        samples = event(3, 'enter', 'stage', 'M1')
        report = rhythm_diagnostics(samples, scenes)
        self.assertEqual('enter', report['events'][0]['kind'])
        self.assertIn((3, 6), [(v['start'], v['end']) for v in report['findings'] if v['kind'] == 'rhythm_gap'])
        samples += event(4.5, 'text_reveal', 'text', 'T1')
        report = rhythm_diagnostics(samples, scenes)
        self.assertNotIn((3, 6), [(v['start'], v['end']) for v in report['findings'] if v['kind'] == 'rhythm_gap'])

    def test_summary_multiple_variants_closure_and_explicit_links(self):
        sample, round_ = self.add_sample()
        path = memory.index_path(self.root, 'sample', 'explainer')
        records = memory.read(path); records[0]['mechanism_id'] = 'one-shape'; memory.write(path, records)
        self.refs(sample['id']); self.call('plan', 'refresh')
        self.round(); self.round()
        retro = self.variant / 'retro' / round_['draft_id'] / 'VISUAL.md'
        text = retro.read_text()
        head = '| 条目 | 留存粒度 | 分类 | Scene | 理由 | 去向 | 机制 ID | 手写重复 |\n|---|---|---|---|---|---|---|---|'
        text = text.replace(head, head + '\n| point | 组件或动作 | 积木 | S01 | 清楚 | Asset Brief | one-shape | 是 |')
        retro.write_text(text)
        other = self.variant.parent / 'other'
        shutil.copytree(self.variant, other)
        # No source registration needed for a mechanical closure count.
        shutil.rmtree(other / 'retro'); shutil.rmtree(other / 'previews')
        for index, variant in enumerate((self.variant, other)):
            state = cli.read_json(variant / 'variant.yaml')
            state['id'] = variant.name
            state['updated_at'] = f'2026-10-0{index + 1}T00:00:00Z'
            asset = {'ref': 'theme:sample@1.0.0', 'version':'1.0.0', 'kind':'theme', 'package_sha256':'a'*64, 'vendor_path':'vendor/theme'}
            state['appearance_lock'] = {'assets': [asset, asset]}
            cli.write_variant(variant, state)
        before = self.tree(self.variant.parent.parent)
        summary = json.loads(self.call('retro', 'summary'))
        self.assertEqual(before, self.tree(self.variant.parent.parent))
        self.assertEqual(2, summary['assets'][0]['count'])
        self.assertEqual('2026-10-02T00:00:00Z', summary['assets'][0]['last_used'])
        self.assertEqual(2, summary['sample_references'][sample['id']])
        self.assertEqual({'one-shape':1}, summary['mechanism_samples'])
        self.assertEqual(1, len(summary['asset_candidates']))
        self.assertEqual(1, summary['handwritten_repetitions'])

    def test_ab_segment_selects_only_its_frames_and_maximum(self):
        # v3.7.0 fixture Plan already has A1/B1/A2 and a semantic cue map.
        first = self.round(); self.retro(first['draft_id'])
        sample = json.loads(self.call('sample', 'add', 'ab', '--draft', first['draft_id'], '--segment', 'S01·B1', '--reason', 'B roll'))
        self.assertEqual('B', sample['role'])
        rows = cli.plan_scene_rows(self.plan_path.read_text())['S01']['segments']
        import explainer
        cues = cli.read_json(self.project / 'runtime/cues.json')
        start = explainer.find_cue(cues, rows[1]['cue'])
        end = explainer.find_cue(cues, rows[2]['cue'])
        self.assertTrue(all(start <= frame['time'] < end for frame in sample['frames']))
        other = json.loads(self.call('sample', 'add', 'ab', '--draft', first['draft_id'], '--segment', 'S01·A1', '--reason', 'A reading'))
        self.refs(sample['id'] + ' ' + other['id'])
        self.call('settings', 'set', 'samples.max_references', '1')
        self.assertIn('sample_reference_limit', [f['kind'] for f in json.loads(self.call('plan', 'check'))['findings']])
        with self.assertRaises(cli.HarnessError):
            self.call('plan', 'refresh')
        self.call('settings', 'set', 'samples.max_references', '3')
        refresh = json.loads(self.call('plan', 'refresh'))
        chosen = json.loads(self.call('sample', 'show', sample['id'], '--plan-revision', str(refresh['revision'])))
        self.assertEqual(min(6, len(sample['frames'])), len(chosen['frames']))

    def test_library_rejects_linked_or_changed_evidence_and_mixed_sample_source(self):
        sample, first = self.add_sample()
        original = memory.library(self.root, 'sample') / sample['frames'][0]['path']
        linked = self.root / 'linked.png'
        os.link(original, linked)
        with self.assertRaises(cli.HarnessError):
            self.call('sample', 'show', sample['id'])
        linked.unlink()
        original.write_bytes(b'bad frame')
        with self.assertRaises(cli.HarnessError):
            self.call('sample', 'show', sample['id'])
        (self.project / 'compositions/S01.html').write_text('<p>Another draft</p>')
        second = self.round(); self.retro(second['draft_id'])
        with self.assertRaisesRegex(cli.HarnessError, 'whole Draft'):
            self.call('sample', 'add', 'demo', '--draft', second['draft_id'], '--segment', 'S01·A1', '--reason', 'new')
        for item_id in ('../escape', '/tmp/escape', '..'):
            with self.assertRaises(cli.HarnessError):
                self.call('sample', 'show', item_id)

    def test_opening_reveal_and_exit_events(self):
        scenes = [{'id':'S01','start':0,'duration':3},{'id':'S02','start':3,'duration':3}]
        samples = []
        for time, kind, before, after, layer, duration in [(0,'text_reveal',True,True,'text',.25),(1,'exit',True,False,'stage',0)]:
            common = dict(id=kind,time=time,kind=kind,layer=layer,scene='S01',duration=duration)
            for at, visible, signature in [(max(0,time-.001),before,'same' if time==0 else 'before'),(time+duration/2 if duration else time+.001,after,'same' if time==0 else 'after')]:
                samples.append(dict(time=at,ready=True,rhythm_candidates=[{**common,'visible':visible,'signature':signature}]))
        report=rhythm_diagnostics(samples,scenes)
        self.assertEqual({'text_reveal','exit'}, {e['kind'] for e in report['events']})

    def test_retro_copy_window_rejects_changed_critic_bytes(self):
        first = self.round()
        original_copy = shutil.copytree
        def corrupt_after_copy(source, destination, *args, **kwargs):
            result = original_copy(source, destination, *args, **kwargs)
            if Path(destination).name == 'evidence':
                (Path(destination) / 'images/0.000000.png').write_bytes(b'changed during copy')
            return result
        with mock.patch('work_memory.shutil.copytree', side_effect=corrupt_after_copy):
            with self.assertRaisesRegex(cli.HarnessError, 'during copying'):
                self.retro(first['draft_id'])
        self.assertFalse((self.variant / 'retro' / first['draft_id']).exists())
        self.assertEqual(1, len(cli.read_json(self.variant / 'critic/ledger.json')['rounds']))

    def test_memory_rejects_variant_draft_and_work_directory_links(self):
        first = self.round()
        saved = self.root / 'saved-variant'
        self.variant.rename(saved)
        self.variant.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(cli.HarnessError):
            self.retro(first['draft_id'])
        with self.assertRaises(cli.HarnessError):
            self.call('retro', 'summary')
        self.assertFalse((saved / 'retro').exists())
        self.variant.unlink(); saved.rename(self.variant)
        preview = self.variant / 'previews' / first['draft_id']
        saved = self.root / 'saved-draft'; preview.rename(saved)
        preview.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(cli.HarnessError):
            self.retro(first['draft_id'])
        self.assertFalse((self.variant / 'retro' / first['draft_id']).exists())
        preview.unlink(); saved.rename(preview)
        work = self.variant.parent.parent
        saved = self.root / 'saved-work'; work.rename(saved)
        work.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(cli.HarnessError):
            self.retro(first['draft_id'])
        with self.assertRaises(cli.HarnessError):
            self.call('retro', 'summary')
        self.assertFalse((saved / 'variants/main/retro').exists())
        work.unlink(); saved.rename(work)

    def test_memory_directories_are_private_and_never_deployment_owned(self):
        import subprocess
        import root_deploy
        import test_release_cli
        repo = Path(__file__).resolve().parents[1]
        git_fixture = self.root / 'git-ignore-fixture'
        git_fixture.mkdir()
        subprocess.run(['git', '-c', 'init.defaultBranch=main', 'init', '--quiet', str(git_fixture)], check=True)
        shutil.copyfile(repo / '.gitignore', git_fixture / '.gitignore')
        for name in ('sample-library', 'known-defects', 'retro-summary'):
            with self.subTest(name=name):
                ignored = subprocess.run(['git','check-ignore',name+'/fixture.json'],cwd=git_fixture,capture_output=True)
                self.assertEqual(0, ignored.returncode)
                self.assertFalse(test_release_cli.RELEASE.public_source(name+'/fixture.json'))
                self.assertFalse(test_release_cli.RELEASE.public_source('.studio/'+name+'/fixture.json'))
                with self.assertRaises(ValueError):
                    root_deploy.managed({name+'/fixture.json':'a'*64})
