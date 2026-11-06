import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / '.studio'))
import asset_maintenance as MAINT
import asset_store as STORE
from component_harness import ComponentError


class AssetMaintenanceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.root / 'old'
        self.target = self.root / 'target'
        self.harness = self.root / 'harness'
        self.harness.mkdir()
        shutil.copyfile(REPO / 'windows-runtime.lock.json', self.harness / 'windows-runtime.lock.json')
        # This fixture models a Windows package, regardless of the test host.
        (self.harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
        environment = patch.dict(os.environ, {
            'HYPERFRAMES_AI_ASSET_CONFIG': str(self.root / 'config.json'),
            'HYPERFRAMES_AI_ASSET_ROOT': '', 'HYPERFRAMES_AI_ROOT': str(self.harness),
            'HYPERFRAMES_AI_WORK_ROOT': '', 'HYPERFRAMES_AI_REVIEW': '',
        })
        environment.start()
        self.addCleanup(environment.stop)

    def source(self, name='sample', *, parent=None, layer='building-block', code='window.sample = 1;'):
        source = (parent or self.root / 'authoring') / name
        source.mkdir(parents=True)
        metadata = {'schema_version': 1, 'id': name, 'version': 1, 'kind': 'module', 'entry': 'main.js'}
        if layer is not None:
            metadata['asset_layer'] = layer
        (source / 'asset.json').write_text(json.dumps(metadata))
        (source / 'main.js').write_text(code)
        return source

    def candidate(self, name='sample', *, store=None, accepted=False, code='window.sample = 1;'):
        store = store or self.old
        source = self.source(name, parent=self.root / ('authoring-' + store.name), code=code)
        candidate = STORE.pack_source(store, source)
        if accepted:
            STORE.accept_component(store, candidate['component_ref'], candidate['package_sha256'],
                                   'Synthetic maintenance test', runtime_root=self.harness)
        return candidate

    def test_migrate_preserves_packages_acceptance_selection_and_retires_only_on_success(self):
        candidate = self.candidate(accepted=True)
        (self.old / 'selection.json').write_text(json.dumps({
            'sample@v1': {'asset_layer': 'building-block', 'recommendation': 'historical'}}))
        package_before = MAINT.inventory(self.old / 'packages/sample/v1')
        acceptance = json.loads((self.old / 'acceptances/sample/v1/acceptance.json').read_text())
        plan = MAINT.migrate_plan(self.old, self.target)
        self.assertEqual([], plan['pending'])
        self.assertFalse(self.target.exists())
        result = MAINT.migrate_apply(plan)
        self.assertTrue(result['source_preserved'])
        self.assertEqual(package_before, MAINT.inventory(self.target / 'packages/sample/v1'))
        self.assertEqual(package_before, MAINT.inventory(self.old / 'packages/sample/v1'))
        self.assertEqual(acceptance, json.loads((self.target / 'acceptances/sample/v1/acceptance.json').read_text()))
        self.assertEqual(candidate['package_sha256'], STORE._validate_package(self.target / 'packages/sample/v1')['package_sha256'])
        self.assertEqual('historical', json.loads((self.target / 'selection.json').read_text())['sample@v1']['recommendation'])
        self.assertEqual([str(self.old)], json.loads((self.target / 'catalog-migration.json').read_text())['retired_roots'])
        self.assertEqual(result, MAINT.migrate_apply(plan))
        original = json.loads((self.old / 'candidates/sample/v1/candidate.json').read_text())
        migrated = json.loads((self.target / 'candidates/sample/v1/candidate.json').read_text())
        self.assertEqual(original['source'], migrated['source'])
        self.assertEqual(str(self.old / 'candidates/sample/v1'), original['path'])
        self.assertEqual(str(self.target / 'candidates/sample/v1'), migrated['path'])
        self.assertEqual(str(self.target / 'candidates/sample/v1/review'), migrated['review'])

    def test_frozen_legacy_is_candidate_not_automatically_accepted(self):
        self.candidate()
        legacy = self.root / 'legacy'
        shutil.copytree(self.old / 'candidates/sample/v1/package', legacy)
        MAINT.migrate_apply(MAINT.migrate_plan(legacy, self.target))
        self.assertTrue((self.target / 'candidates/sample/v1/package/HASHES.json').is_file())
        self.assertFalse((self.target / 'packages').exists())
        self.assertFalse((self.target / 'acceptances').exists())

    def test_frozen_asset_with_sources_subdirectory_keeps_lock_outside_package(self):
        source = self.source(code='import "./sources/helper.js";')
        (source / 'sources').mkdir()
        (source / 'sources/helper.js').write_text('window.helper = 1;')
        metadata = json.loads((source / 'asset.json').read_text())
        metadata['dependencies'] = ['sources/helper.js']
        (source / 'asset.json').write_text(json.dumps(metadata))
        STORE.pack_source(self.old, source)
        frozen = self.root / 'frozen'
        shutil.copytree(self.old / 'candidates/sample/v1/package', frozen)
        before = {path.relative_to(frozen).as_posix(): path.read_bytes()
                  for path in frozen.rglob('*') if path.is_file()}
        plan = MAINT.migrate_plan(frozen, self.target)
        self.assertFalse(plan['pending'])
        self.assertEqual(['sample@v1'], [row['ref'] for row in plan['items']])
        MAINT.migrate_apply(plan)
        self.assertEqual(before, {path.relative_to(frozen).as_posix(): path.read_bytes()
                                  for path in frozen.rglob('*') if path.is_file()})
        self.assertFalse((frozen / '.asset-write.lock').exists())

    def test_pending_classification_blocks_apply_until_explicitly_resolved(self):
        source = self.source(layer=None)
        plan = MAINT.migrate_plan(source, self.target)
        self.assertTrue(plan['pending'])
        with self.assertRaises(ComponentError):
            MAINT.migrate_apply(plan)
        self.assertFalse((self.target / 'catalog-migration.json').exists())
        plan = MAINT.migrate_plan(source, self.target, {'sample@v1': {'asset_layer': 'reference'}})
        MAINT.migrate_apply(plan)
        self.assertEqual(MAINT.inventory(source), MAINT.inventory(self.target / 'sources/sample/v1'))

    def test_managed_sources_are_copied_without_freezing(self):
        source = self.source(parent=self.old / 'sources')
        MAINT.migrate_apply(MAINT.migrate_plan(self.old, self.target))
        self.assertEqual(MAINT.inventory(source), MAINT.inventory(self.target / 'sources/sample/v1'))
        self.assertFalse((self.target / 'sources/sample/v1/HASHES.json').exists())

    def test_interrupted_copy_can_replay_without_retiring_source_early(self):
        self.source('first', parent=self.old / 'sources')
        self.source('second', parent=self.old / 'sources')
        plan = MAINT.migrate_plan(self.old, self.target)
        original = MAINT.copy_checked
        calls = 0

        def interrupted(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('synthetic interruption')
            return original(*args)

        with patch.object(MAINT, 'copy_checked', side_effect=interrupted):
            with self.assertRaises(OSError):
                MAINT.migrate_apply(plan)
        self.assertFalse((self.target / 'catalog-migration.json').exists())
        self.assertEqual(2, MAINT.migrate_apply(plan)['items'])
        self.assertEqual(2, MAINT.migrate_apply(plan)['items'])

    def test_tampered_plan_and_stale_source_are_rejected(self):
        source = self.source()
        plan = MAINT.migrate_plan(source, self.target)
        tampered = copy.deepcopy(plan)
        tampered['items'][0]['destination'] = '../escaped'
        with self.assertRaises(ComponentError):
            MAINT.migrate_apply(tampered)
        (source / 'main.js').write_text('changed')
        with self.assertRaises(ComponentError):
            MAINT.migrate_apply(plan)
        self.assertFalse((self.root / 'escaped').exists())
        self.assertFalse((self.target / 'catalog-migration.json').exists())

    def test_target_identity_and_selection_conflicts_are_not_overwritten(self):
        self.candidate()
        self.candidate(store=self.target, code='window.sample = 2;')
        before = MAINT.inventory(self.target / 'candidates/sample/v1')
        with self.assertRaises(ComponentError):
            MAINT.migrate_apply(MAINT.migrate_plan(self.old, self.target))
        self.assertEqual(before, MAINT.inventory(self.target / 'candidates/sample/v1'))
        other = self.root / 'other-target'
        other.mkdir()
        (other / 'selection.json').write_text(json.dumps({'sample@v1': {'asset_layer': 'reference'}}))
        with self.assertRaises(ComponentError):
            MAINT.migrate_apply(MAINT.migrate_plan(self.old, other))
        self.assertFalse((other / 'catalog-migration.json').exists())

    def test_linked_input_and_overlapping_or_work_targets_are_rejected(self):
        source = self.source()
        (source / 'linked.js').symlink_to(source / 'main.js')
        with self.assertRaises(ComponentError):
            MAINT.migrate_plan(source, self.target)
        (source / 'linked.js').unlink()
        os.link(source / 'main.js', source / 'hard.js')
        with self.assertRaises(ComponentError):
            MAINT.migrate_plan(source, self.target)
        (source / 'hard.js').unlink()
        for target in (source, source / 'nested'):
            with self.assertRaises(ComponentError):
                MAINT.migrate_plan(source, target)
        work = self.root / 'work'
        (work / 'works').mkdir(parents=True)
        with self.assertRaises(ComponentError):
            MAINT.migrate_plan(source, work)

    def test_save_plan_is_external_and_cannot_overwrite_different_content(self):
        source = self.source()
        plan = MAINT.migrate_plan(source, self.target)
        path = self.root / 'migration.json'
        self.assertEqual(MAINT.save_plan(path, plan), MAINT.save_plan(path, plan))
        with self.assertRaises(ComponentError):
            MAINT.save_plan(source / 'plan.json', plan)
        changed = copy.deepcopy(plan)
        changed['pending'].append({'reason': 'changed'})
        with self.assertRaises(ComponentError):
            MAINT.save_plan(path, changed)

    def test_nested_targets_inside_protected_assets_and_work_are_rejected(self):
        source = self.source()
        for marker in ('HASHES.json', 'COMPONENT_LOCK.json', 'WORK.md', 'asset.json', 'acceptance.json'):
            with self.subTest(marker=marker):
                parent = self.root / ('protected-' + marker)
                parent.mkdir()
                (parent / marker).write_text('{}')
                target = parent / 'nested' / 'target'
                with self.assertRaises(ComponentError):
                    MAINT.migrate_plan(source, target)
                with self.assertRaises(ComponentError):
                    MAINT.archive_plan(target, ['workspaces/owned'])
                self.assertFalse(target.exists())

    def test_legacy_ratio_candidate_archive(self):
        legacy = self.root / 'legacy-ratio'
        shutil.copytree(REPO / 'tests/fixtures/components/chapter-intro/4x3/v1', legacy)
        candidate = STORE.import_component(self.target, legacy)
        self.assertEqual('chapter-intro/4x3@v1', candidate['component_ref'])
        relative = 'candidates/chapter-intro/4x3/v1'
        before = MAINT.inventory(self.target / relative)
        plan = MAINT.archive_plan(self.target, [relative])
        result = MAINT.archive_apply(plan)
        self.assertEqual(before, MAINT.inventory(Path(result['archive']) / relative))
        self.assertEqual(before, MAINT.inventory(self.target / relative))

    def test_cli_migration_and_archive_require_explicit_targets_and_execute_saved_plans(self):
        from test_work_cli import WORK_CLI as cli

        def invoke(*arguments):
            args = cli.build_parser().parse_args(['--json', 'component', *arguments])
            with redirect_stdout(io.StringIO()) as output:
                args.handler(self.harness, args)
            return json.loads(output.getvalue())

        with patch.object(STORE, 'asset_store_root', side_effect=AssertionError('No implicit asset target')):
            self.candidate()
            migration = self.root / 'migration.json'
            self.assertEqual(str(migration), invoke('migrate', 'plan', '--from', str(self.old),
                             '--to', str(self.target), '--output', str(migration))['plan'])
            self.assertEqual('migrate', invoke('migrate', 'apply', '--plan', str(migration))['operation'])
            archive = self.root / 'archive.json'
            invoke('archive', 'plan', '--to', str(self.target), '--item', 'candidates/sample/v1',
                   '--output', str(archive))
            self.assertEqual('archive', invoke('archive', 'apply', '--plan', str(archive))['operation'])
        for arguments in (('migrate', 'plan', '--from', str(self.old), '--output', str(migration)),
                          ('archive', 'plan', '--item', 'candidates/sample/v1', '--output', str(archive))):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.build_parser().parse_args(['component', *arguments])

    def test_archive_snapshots_are_idempotent_and_preserve_original_candidate(self):
        self.candidate(store=self.target)
        before = MAINT.inventory(self.target / 'candidates/sample/v1')
        plan = MAINT.archive_plan(self.target, ['candidates/sample/v1'])
        result = MAINT.archive_apply(plan)
        self.assertEqual(result, MAINT.archive_apply(plan))
        self.assertEqual(0, result['reclaimed_bytes'])
        self.assertEqual(before, MAINT.inventory(self.target / 'candidates/sample/v1'))
        self.assertEqual(before, MAINT.inventory(Path(result['archive']) / 'candidates/sample/v1'))
        self.assertEqual(plan, json.loads((Path(result['archive']) / 'manifest.json').read_text()))

    def test_archive_rejects_edited_review_packages_work_links_and_stale_plan(self):
        self.candidate(store=self.target, accepted=True)
        plan = MAINT.archive_plan(self.target, ['candidates/sample/v1'])
        review = self.target / 'candidates/sample/v1/review/main.js'
        review.write_text('edited review')
        with self.assertRaises(ComponentError):
            MAINT.archive_apply(plan)
        for item in ('candidates/sample/v1', 'packages/sample/v1', '../outside', 'works/active/example'):
            with self.subTest(item=item), self.assertRaises(ComponentError):
                MAINT.archive_plan(self.target, [item])
        workspace = self.target / 'workspaces/owned'
        workspace.mkdir(parents=True)
        marker = workspace / '.asset-workspace.json'
        marker.write_text(json.dumps({'owner': MAINT.OWNER, 'active': True}))
        with self.assertRaises(ComponentError):
            MAINT.archive_plan(self.target, ['workspaces/owned'])
        marker.write_text(json.dumps({'owner': MAINT.OWNER, 'active': False}))
        (workspace / 'WORK.md').write_text('protected')
        with self.assertRaises(ComponentError):
            MAINT.archive_plan(self.target, ['workspaces/owned'])
        (workspace / 'WORK.md').unlink()
        (workspace / 'link').symlink_to(review)
        with self.assertRaises(ComponentError):
            MAINT.archive_plan(self.target, ['workspaces/owned'])


if __name__ == '__main__':
    unittest.main()
