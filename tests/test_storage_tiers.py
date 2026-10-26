"""Tiered storage reclamation uses only isolated Work fixtures."""
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from tests import test_work_cli as fixture

API = fixture.WORK_CLI
STORAGE = API.work_storage


class StorageTiersTest(unittest.TestCase):
    setUp = fixture.WorkCliTest.setUp
    tearDown = fixture.WorkCliTest.tearDown
    invoke = fixture.WorkCliTest.invoke
    new_work = fixture.WorkCliTest.new_work
    prepare_preview = fixture.WorkCliTest.prepare_preview
    update_frontmatter = staticmethod(fixture.WorkCliTest.update_frontmatter)

    def put(self, path, data=b'content'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def complete(self, variant):
        self.put(variant / 'final/final.mp4', b'final')
        API.write_json(variant / 'final/manifest.json', {'final_sha256': API.file_sha256(variant / 'final/final.mp4')})
        API.write_json(variant / '.runtime/finalize.json', {'state': 'complete'})

    def plan(self, work, tier, **kwargs):
        output = self.root / f'plan-{tier}.json'
        result = json.loads(self.invoke('storage', 'plan', '--tier', str(tier), '--work', work.name,
                                       '--output', str(output), **kwargs))
        self.assertEqual(result, API.read_json(output))
        self.assertEqual(STORAGE.plan_digest(result['items']), result['digest'])
        return result, output

    def publish(self, work, *, link='', status='已发', directory=None):
        directory = directory or self.root / 'exports'
        directory.mkdir(exist_ok=True)
        with (directory / 'publish-log.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['Work', '链接', '状态'])
            writer.writeheader()
            writer.writerow({'Work': work.name, '链接': link, '状态': status})

    def preview(self, variant, name, **metadata):
        path = variant / 'previews' / name
        self.put(path / 'source-snapshot/index.html')
        self.put(path / 'preview.md', ('---\n' + json.dumps(metadata) + '\n---\n').encode())
        return path

    def review(self, variant, target='draft-v001', *, pid=None, identity='a'):
        directory = variant / '.runtime' / ('studio-review-' + identity * 32)
        self.put(directory / target / 'index.html')
        record = {'project': str(directory / target), 'target': target}
        if pid is not None:
            record['pid'] = pid
        API.write_json(variant / '.runtime' / f'studio-{target}.json', record)
        return directory

    def test_finalize_reclaims_stopped_review_and_preview_open_rebuilds(self):
        work_id, work = self.new_work()
        variant = work / 'variants/main'
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        review = self.review(variant, pid=2147483647)
        current = variant / '.runtime/studio-current.json'
        API.write_json(current, {'project': str(variant / 'project'), 'target': 'current'})
        self.invoke('finalize', str(self.put(self.root / 'final.mp4', b'final')), '--qa-passed')
        self.assertFalse(review.exists())
        self.assertFalse((variant / '.runtime/studio-draft-v001.json').exists())
        self.assertTrue(current.exists())
        receipt = API.read_json(variant / '.runtime/finalize.json')
        self.assertEqual('complete', receipt['state'])
        self.assertIn('studio_review', [item['kind'] for item in receipt['storage']['removed']])
        self.assertGreater(receipt['storage']['bytes'], 0)
        args = SimpleNamespace(work_override=work_id, variant_override='main', preview_id='draft-v001',
                               legacy=False, no_open=True, port=0, hyperframes_cli=None, hyperframes_dist=None)
        cli = self.put(self.root / 'cli.mjs')
        with mock.patch.object(API, 'runtime_path', return_value=cli), \
                mock.patch.object(API.studio_preview, 'start', side_effect=RuntimeError('new copy reached Studio')) as start:
            with self.assertRaisesRegex(RuntimeError, 'new copy reached Studio'):
                API._command_preview_open(self.root, args)
        project = start.call_args.args[1]
        self.assertTrue((project / 'index.html').is_file())
        self.assertNotEqual(review, project.parent)

    def test_live_studio_and_browser_are_excluded(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        live = self.review(variant, pid=os.getpid())
        browser = self.review(variant, target='draft-v002', identity='b')
        self.put(browser / '.runtime/studio-browser/lockfile')
        run = self.put(variant / '.runtime/diagnose-frames/run/frame.png').parent
        plan, _ = self.plan(work, 1)
        names = {item['path'] for item in plan['items']}
        for path in (live, browser, run):
            self.assertNotIn(path.relative_to(work).as_posix(), names)
        self.assertTrue(any(item['reason'] == 'Studio or browser in use' for item in plan['excluded']))

    def test_plan_is_read_only_and_default_filename_is_utc(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        self.review(variant)
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob('*') if p.is_file()}
        plan = json.loads(self.invoke('storage', 'plan', '--tier', '1', '--work', work.name))
        outputs = list((self.root / '.studio/.runtime/storage-plans').glob('*-tier1.json'))
        self.assertEqual(1, len(outputs))
        self.assertIn('Z-tier1', outputs[0].name)
        self.assertEqual(plan, API.read_json(outputs[0]))
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob('*') if p.is_file() and p != outputs[0]}
        self.assertEqual(before, after)

    def test_apply_rechecks_stats_digest_and_records_usage(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        changed = self.put(variant / '.runtime/diagnose-frames/changed/frame.png')
        stable = self.put(variant / '.runtime/diagnose-frames/stable/frame.png')
        plan, output = self.plan(work, 1)
        changed.write_bytes(b'changed bytes after planning')
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertTrue(changed.exists())
        self.assertFalse(stable.exists())
        self.assertIn('changed', result['skipped'][0]['reason'])
        usage = API.read_json(work / '.runtime/storage.json')
        self.assertEqual(result['removed'], usage['removed'])
        self.assertEqual(plan['digest'], usage['plan_digest'])
        self.assertIn('applied_at', usage)
        plan['digest'] = 'tampered'
        API.write_json(output, plan)
        self.assertIn('digest', self.invoke('storage', 'apply', str(output), expected=2))

    def test_apply_enumerates_each_variant_once_and_rechecks_each_item(self):
        _, work = self.new_work()
        self.invoke('variant', 'add', 'wide', '--from', 'main')
        reviews = {}
        for identity in ('main', 'wide'):
            variant = work / 'variants' / identity
            self.complete(variant)
            reviews[identity] = [self.review(variant, target=f'draft-v{number:03}',
                                            pid=2147483647, identity=letter)
                                 for number, letter in enumerate('abc', 1)]
            candidate = self.put(variant / '.runtime/finalize-fixture/candidate.mp4', b'final')
            API.write_json(candidate.parent / 'qa.json', {'passed': True, 'sha256': API.file_sha256(candidate)})
            with API.naming_lock(self.root):
                API.reclaim_final_candidates(variant, candidate, apply=False)
        plan, output = self.plan(work, 1)
        self.assertEqual(8, len(plan['items']))
        changed = reviews['main'][1] / 'draft-v002/index.html'
        remove = STORAGE.remove_item

        def remove_and_change(api, target_work, item, **kwargs):
            remove(api, target_work, item, **kwargs)
            if target_work / item['path'] == reviews['main'][0]:
                changed.write_bytes(b'changed after eligibility enumeration, before this item recheck')

        with mock.patch.object(STORAGE, 'tier_items', wraps=STORAGE.tier_items) as enumerate_items, \
                mock.patch.object(API, 'reclaim_final_candidates', wraps=API.reclaim_final_candidates) as candidates, \
                mock.patch.object(STORAGE, 'remove_item', side_effect=remove_and_change), \
                mock.patch.object(STORAGE, 'tree_stats', wraps=STORAGE.tree_stats) as stats:
            result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertEqual(2, enumerate_items.call_count)
        self.assertEqual({'main', 'wide'}, {call.kwargs['variant'].name for call in enumerate_items.call_args_list})
        self.assertEqual(2, candidates.call_count)
        self.assertEqual({'main', 'wide'}, {call.args[0].name for call in candidates.call_args_list})
        for paths in reviews.values():
            for path in paths:
                self.assertEqual(2, sum(call.args[0] == path for call in stats.call_args_list))
        self.assertEqual(7, len(result['removed']))
        self.assertEqual(1, len(result['skipped']))
        self.assertEqual(reviews['main'][1].relative_to(work).as_posix(), result['skipped'][0]['path'])
        self.assertEqual('bytes/files/max_mtime_ns changed', result['skipped'][0]['reason'])
        self.assertTrue(changed.exists())
        for paths in reviews.values():
            for path in paths:
                self.assertEqual(path == reviews['main'][1], path.exists())

    def test_local_rechecks_reject_process_browser_and_verdict_changes(self):
        for change in ('review-pid', 'review-browser', 'diagnose-pid', 'diagnose-browser', 'critic-verdict'):
            with self.subTest(change=change):
                _, work = self.new_work(change)
                variant = work / 'variants/main'
                self.complete(variant)
                tier = 2 if change == 'critic-verdict' else 1
                if change.startswith('review'):
                    target = self.review(variant, pid=2147483647)
                    record_path = variant / '.runtime/studio-draft-v001.json'
                    lockfile = target / '.runtime/studio-browser/lockfile'
                elif change.startswith('diagnose'):
                    target = self.put(variant / '.runtime/diagnose-frames/run/frame.png').parent
                    record_path = variant / '.runtime/studio-current.json'
                    API.write_json(record_path, {'project': str(variant / 'project'), 'pid': 2147483647})
                    lockfile = variant / '.runtime/studio-browser/lockfile'
                else:
                    self.publish(work)
                    target = self.put(variant / 'critic/round-001/images/frame.png').parent.parent
                    ledger_path = variant / 'critic/ledger.json'
                    API.write_json(ledger_path, {'rounds': [{'package': 'round-001', 'verdict': {}}]})
                plan, output = self.plan(work, tier)
                self.assertEqual(1, len(plan['items']))
                enumerate_items = STORAGE.tier_items

                def enumerate_then_change(*args, **kwargs):
                    result = enumerate_items(*args, **kwargs)
                    if change.endswith('pid'):
                        API.write_json(record_path, {**API.read_json(record_path), 'pid': os.getpid()})
                    elif change.endswith('browser'):
                        self.put(lockfile)
                    else:
                        API.write_json(ledger_path, {'rounds': [{'package': 'round-001'}]})
                    return result

                with mock.patch.object(STORAGE, 'tier_items', side_effect=enumerate_then_change) as enumeration:
                    result = json.loads(self.invoke('storage', 'apply', str(output)))
                enumeration.assert_called_once()
                self.assertFalse(result['removed'])
                self.assertEqual(1, len(result['skipped']))
                expected = ('critic verdict not recorded' if change.endswith('verdict') else
                            'browser' if change.endswith('browser') else 'Studio')
                self.assertIn(expected, result['skipped'][0]['reason'])
                self.assertTrue(target.exists())

    def test_tier1_candidates_caches_residue_and_links(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        candidate = self.put(variant / '.runtime/finalize-a/candidate.mp4', b'final')
        API.write_json(candidate.parent / 'qa.json', {'passed': True, 'sha256': API.file_sha256(candidate)})
        with API.naming_lock(self.root):
            API.reclaim_final_candidates(variant, candidate, apply=False)
        self.put(variant / '.runtime/studio-browser/Default/Cache/data')
        preferences = self.put(variant / '.runtime/studio-browser/Default/Preferences')
        self.put(variant / '.runtime/final-promotion/committed.json', b'{}')
        linked = self.put(variant / '.runtime/diagnose-frames/linked/frame.png').parent
        (linked / 'outside').symlink_to(self.root / 'outside')
        plan, output = self.plan(work, 1)
        self.assertEqual({'final_candidate', 'browser_cache', 'promotion_residue'}, {item['kind'] for item in plan['items']})
        self.assertTrue(any(row['reason'] == 'contains link' for row in plan['excluded']))
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertEqual(3, len(result['removed']))
        self.assertTrue(preferences.exists())
        self.assertTrue(linked.exists())
        self.assertFalse(candidate.exists())
        self.assertEqual('removed', API.read_json(variant / '.runtime/final-candidates.json')['entries'][0]['state'])

    def test_recovery_and_live_pid_after_plan_skip_items(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        review = self.review(variant)
        plan, output = self.plan(work, 1)
        self.assertTrue(plan['items'])
        record = variant / '.runtime/studio-draft-v001.json'
        API.write_json(record, {**API.read_json(record), 'pid': os.getpid()})
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertFalse(result['removed'])
        self.assertTrue(review.exists())
        self.put(variant / '.runtime/appearance-rebind.json', b'{}')
        self.assertFalse(self.plan(work, 1)[0]['items'])

    def test_unpublished_and_all_includes_archived_work(self):
        _, work = self.new_work()
        plan, _ = self.plan(work, 2)
        self.assertFalse(plan['items'])
        self.assertEqual([{'work': work.name, 'variant': None, 'path': '.', 'reason': 'not published'}], plan['excluded'])
        _, other = self.new_work('Other')
        API.write_json(other / '.runtime/archive.json', {'outcome': 'done'})
        output = self.root / 'all.json'
        all_plan = json.loads(self.invoke('storage', 'plan', '--tier', '2', '--all', '--output', str(output)))
        self.assertEqual({work.name, other.name}, {row['work'] for row in all_plan['excluded']})

    def test_tier2_protects_recursive_acceptance_source_plans_and_live_target(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        for number in range(1, 11):
            self.preview(variant, f'draft-v{number:03}')
        self.preview(variant, 'plan-v001')
        self.preview(variant, 'plan-v002')
        self.preview(variant, 'draft-v001', source_plan='plan-v001')
        state = API.read_json(variant / 'variant.yaml')
        state.update(accepted_preview='draft-v001', appearance_history=[{'nested': {'accepted_visual_plan': 'draft-v002'}}],
                     configuration_history=[{'source_preview': 'draft-v003'}])
        API.write_json(variant / 'variant.yaml', state)
        API.write_json(variant / 'final/manifest.json', {'source_preview': 'draft-v004'})
        API.write_json(variant / 'final/history/old/manifest.json', {'nested': {'source_preview': 'draft-v005'}})
        API.write_json(variant / '.runtime/studio-draft-v006.json', {'target': 'draft-v006', 'pid': os.getpid()})
        export = self.root / 'custom-exports'
        self.publish(work, link='https://example.invalid/video', status='', directory=export)
        with mock.patch.dict(os.environ, HYPERFRAMES_AI_RESOLVED_CONFIG=json.dumps({'export_root': str(export)})):
            plan, output = self.plan(work, 2)
            self.assertEqual({'draft-v007', 'draft-v008', 'draft-v009'}, {Path(item['path']).name for item in plan['items']})
            self.invoke('storage', 'apply', str(output))
        self.assertTrue((variant / 'previews/plan-v001').exists())
        self.assertTrue((variant / 'previews/draft-v010').exists())
        self.assertFalse((variant / 'previews/draft-v007').exists())

    def test_critic_frames_mark_ledger_reject_record_and_resample_retro(self):
        work_id, work = self.new_work()
        variant = work / 'variants/main'
        self.publish(work)
        package = variant / 'critic/round-001'
        self.put(package / 'images/frame.png')
        self.put(package / 'contact-sheet.png')
        measurements = self.put(package / 'measurements.json', b'{}')
        pending = self.put(variant / 'critic/round-002/images/frame.png')
        entry = {'round': 1, 'draft_id': 'draft-v001', 'snapshot_sha256': 'snapshot', 'package': 'round-001',
                 'files': API.critic.hashes(package), 'verdict': {'status': 'pass'}}
        ledger_path = variant / 'critic/ledger.json'
        API.write_json(ledger_path, {'rounds': [entry, {'round': 2, 'package': 'round-002'}]})
        plan, output = self.plan(work, 2)
        self.assertEqual(['critic_frames'], [row['kind'] for row in plan['items']])
        self.assertEqual(2, plan['items'][0]['files'])
        self.assertEqual(14, plan['items'][0]['bytes'])
        self.invoke('storage', 'apply', str(output))
        self.assertFalse((package / 'images/frame.png').exists())
        self.assertFalse((package / 'contact-sheet.png').exists())
        self.assertTrue(measurements.exists())
        self.assertTrue(pending.exists())
        ledger = API.read_json(ledger_path)
        self.assertIn('frames_reclaimed_at', ledger['rounds'][0])
        self.assertNotIn('frames_reclaimed_at', ledger['rounds'][1])
        API.write_json(ledger_path, {'rounds': ledger['rounds'][:1]})
        verdict = self.root / 'verdict.json'
        API.write_json(verdict, {})
        self.assertIn('Critic frames were reclaimed; start a new round',
                      self.invoke('--work', work_id, '--variant', 'main', 'critic', 'record', '--file', str(verdict), expected=2))
        preview = self.preview(variant, 'draft-v001')
        self.put(preview / 'ANIMATION_PLAN.md')
        metadata = {'snapshot_sha256': 'snapshot'}
        args = SimpleNamespace(work_override=work_id, variant_override='main', draft_id='draft-v001')
        report = {'snapshot_sha256': 'snapshot', 'target': 'draft-v001', 'status': 'diagnostic_only', 'samples': []}
        def package_evidence(path, *unused):
            API.write_json(path / 'measurements.json', report)
        with mock.patch.object(API.work_memory, 'context', return_value=(work, variant, {})), \
                mock.patch.object(API.work_memory, 'draft', return_value=(preview, metadata)), \
                mock.patch.object(API, 'command_preview_open') as opened, \
                mock.patch.object(API, 'command_preview_diagnose', side_effect=lambda *a: print(json.dumps(report))) as sampled, \
                mock.patch.object(API.work_memory, 'plan_scene_rows', return_value={}), \
                mock.patch.object(API.critic, 'package', side_effect=package_evidence), \
                mock.patch.object(API.work_memory.memory, 'line_id', return_value='stage-full'):
            result = API.work_memory.open_retro(API, self.root, args)
        self.assertFalse(result['reused'])
        opened.assert_called_once()
        sampled.assert_called_once()
        self.assertTrue((variant / 'retro/draft-v001/evidence/measurements.json').is_file())

    def test_tier3_requires_abandoned_unpublished_and_keeps_only_contract(self):
        _, work = self.new_work()
        output = self.root / 'reject.json'
        self.invoke('storage', 'plan', '--tier', '3', '--work', work.name, '--output', str(output), expected=2)
        self.assertFalse(output.exists())
        self.invoke('storage', 'plan', '--tier', '3', '--all', '--output', str(output), expected=2)
        self.assertFalse(output.exists())
        API.write_json(work / '.runtime/archive.json', {'outcome': 'abandoned'})
        self.publish(work)
        self.invoke('storage', 'plan', '--tier', '3', '--work', work.name, '--output', str(output), expected=2)
        self.assertFalse(output.exists())
        self.publish(work, status='待发')
        variant = work / 'variants/main'
        for name in ('final/final.mp4', 'project/index.html', 'materials/audio.wav', 'retro/draft-v001/VISUAL.md'):
            self.put(variant / name)
        kept = {p.relative_to(work): p.read_bytes() for p in [work / 'WORK.md', work / '.runtime/archive.json',
                variant / 'variant.yaml', variant / 'retro/draft-v001/VISUAL.md']}
        plan, output = self.plan(work, 3)
        self.assertTrue({'final', 'project', 'materials'} <= {Path(row['path']).name for row in plan['items']})
        self.assertFalse(any(Path(row['path']).name in {'WORK.md', 'archive.json', 'storage.json', 'variant.yaml', 'retro'}
                             for row in plan['items']))
        self.invoke('storage', 'apply', str(output))
        remaining = {p.relative_to(work) for p in work.rglob('*') if p.is_file()}
        self.assertEqual(set(kept) | {Path('.runtime/storage.json')}, remaining)
        for name, content in kept.items():
            self.assertEqual(content, (work / name).read_bytes())

    def test_protection_assertions_and_apply_requalification(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.publish(work)
        self.preview(variant, 'draft-v001')
        self.preview(variant, 'draft-v002')
        plan, output = self.plan(work, 2)
        state = API.read_json(variant / 'variant.yaml')
        state['accepted_preview'] = 'draft-v001'
        API.write_json(variant / 'variant.yaml', state)
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertFalse(result['removed'])
        self.assertEqual('protected preview', result['skipped'][0]['reason'])
        for tier in (1, 2):
            for name in ('final', 'project', 'materials', 'retro'):
                with self.assertRaisesRegex(ValueError, 'protected'):
                    STORAGE.assert_protected(work, {'path': f'variants/main/{name}/file'}, tier)
        for name in ('WORK.md', '.runtime/archive.json', '.runtime/storage.json', 'variants',
                     'variants/main', 'variants/main/variant.yaml', 'variants/main/retro/file'):
            with self.assertRaisesRegex(ValueError, 'retained'):
                STORAGE.assert_protected(work, {'path': name}, 3)
        plan['items'][0]['path'] = 'variants/main/final/final.mp4'
        plan['digest'] = STORAGE.plan_digest(plan['items'])
        API.write_json(output, plan)
        self.assertIn('protected', self.invoke('storage', 'apply', str(output), expected=2))

    def test_finalize_registers_and_reclaims_its_candidate(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        candidate = self.put(variant / '.runtime/finalize-test/candidate.mp4', b'final')
        API.write_json(candidate.parent / 'qa.json', {'passed': True, 'sha256': API.file_sha256(candidate)})
        with mock.patch.object(STORAGE, 'tier_items', wraps=STORAGE.tier_items) as enumerate_items, \
                mock.patch.object(API, 'reclaim_final_candidates', wraps=API.reclaim_final_candidates) as candidates:
            self.invoke('finalize', str(candidate), '--qa-passed')
        enumerate_items.assert_called_once()
        candidates.assert_called_once()
        receipt = API.read_json(variant / '.runtime/finalize.json')
        self.assertFalse(candidate.exists())
        self.assertIn('final_candidate', [row['kind'] for row in receipt['storage']['removed']])
        self.assertTrue((candidate.parent / 'qa.json').exists())

    def test_review_cache_is_not_double_counted_and_new_link_is_skipped(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        self.complete(variant)
        review = self.review(variant)
        record = variant / '.runtime/studio-draft-v001.json'
        API.write_json(record, {**API.read_json(record), 'pid': 2147483647})
        self.put(review / '.runtime/studio-browser/Default/Cache/data')
        plan, output = self.plan(work, 1)
        self.assertEqual(['studio_review'], [row['kind'] for row in plan['items']])
        self.assertEqual(STORAGE.tree_stats(review)['bytes'], plan['totals']['studio_review'])
        (review / 'linked').symlink_to(self.root / 'outside')
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertFalse(result['removed'])
        self.assertEqual('contains link', result['skipped'][0]['reason'])
        self.assertTrue(review.exists())
        self.assertTrue(record.exists())

    def test_tier3_rechecks_publication_before_deleting(self):
        _, work = self.new_work()
        API.write_json(work / '.runtime/archive.json', {'outcome': 'abandoned'})
        plan, output = self.plan(work, 3)
        self.assertTrue(plan['items'])
        self.publish(work)
        result = json.loads(self.invoke('storage', 'apply', str(output)))
        self.assertFalse(result['removed'])
        self.assertEqual(len(plan['items']), len(result['skipped']))
        self.assertTrue((work / 'variants/main/ANIMATION_PLAN.md').exists())

    def test_auto_reclamation_error_does_not_fail_finalize(self):
        _, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        with mock.patch.object(STORAGE, 'tier_items', side_effect=RuntimeError('cleanup failed')):
            self.invoke('finalize', str(self.put(self.root / 'final.mp4', b'final')), '--qa-passed')
        receipt = API.read_json(work / 'variants/main/.runtime/finalize.json')
        self.assertEqual('complete', receipt['state'])
        self.assertEqual('cleanup failed', receipt['storage_error'])


if __name__ == '__main__':
    unittest.main()
