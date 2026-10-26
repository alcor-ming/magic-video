import csv
from contextlib import redirect_stdout
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import exports
import work as work_cli


STEM = 'english-learning_E012_acct-a'


class ExportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.work = self.base / 'work001'
        self.variant = self.work / 'variants/variant1'
        self.variant.mkdir(parents=True)
        self.video = self.variant / 'final.mp4'
        self.video.write_bytes(b'video fixture')
        self.cover = self.variant / 'cover.png'
        self.cover.write_bytes(b'cover fixture')
        self.root = self.base / 'exports'
        self.folder = self.root / 'acct-a/english-learning'

    def publish(self, files=None, **kwargs):
        options = {'series': 'english-learning', 'number': 12, 'account': 'acct-a', 'label': 'acct-a',
                   'series_name': '英语歪理', 'account_name': '账号A', **kwargs}
        return exports.publish(self.root, self.work, self.variant, files or {'video': self.video, 'cover': self.cover},
                               **options)

    def log(self):
        return list(csv.DictReader(io.StringIO((self.root / exports.LOG).read_text(encoding='utf-8-sig'))))

    def test_episode_packages_sit_under_account_and_series(self):
        first = self.publish()
        self.assertEqual(str(self.folder), first['directory'])
        self.assertEqual({'video': f'{STEM}_v01.mp4',
                          'cover': f'{STEM}_v01.png'}, first['files'])
        self.assertEqual(b'video fixture', (self.folder / first['files']['video']).read_bytes())
        self.assertEqual(first, self.publish())
        self.publish(number=13)
        self.assertEqual({f'{STEM}_v01.mp4', f'{STEM}_v01.png', 'english-learning_E013_acct-a_v01.mp4',
                          'english-learning_E013_acct-a_v01.png'}, {path.name for path in self.folder.iterdir()})
        self.assertEqual([(STEM, '账号A', '英语歪理', '12', '1', f'{STEM}_v01.mp4', f'{STEM}_v01.png', '待发'),
                          ('english-learning_E013_acct-a', '账号A', '英语歪理', '13', '1',
                           'english-learning_E013_acct-a_v01.mp4', 'english-learning_E013_acct-a_v01.png', '待发')],
                         [(row['编号'], row['账号'], row['系列'], row['期数'], row['版本'], row['视频'], row['封面'],
                           row['状态']) for row in self.log()])

    def test_new_version_moves_the_whole_package_and_keeps_names(self):
        self.publish()
        self.cover.write_bytes(b'new cover')
        second = self.publish({'cover': self.cover}, revision=2)
        self.assertEqual((2, {'video': f'{STEM}_v02.mp4',
                              'cover': f'{STEM}_v02.png'}), (second['version'], second['files']))
        self.assertEqual(b'new cover', (self.folder / f'{STEM}_v02.png').read_bytes())
        self.assertEqual(b'video fixture', (self.folder / f'{STEM}_v02.mp4').read_bytes())
        self.assertEqual({f'{STEM}_v01.mp4': b'video fixture', f'{STEM}_v01.png': b'cover fixture'},
                         {path.name: path.read_bytes() for path in (self.folder / '_superseded').iterdir()})
        index = json.loads((self.root / exports.INDEX).read_text())['episodes'][f'acct-a/english-learning/{STEM}']
        self.assertEqual([('cover', 1, False), ('video', 1, False), ('cover', 2, True), ('video', 2, True)],
                         [(item['role'], item['version'], item['current']) for item in index['files']])

    def test_publish_log_keeps_user_cells_and_flags_republish(self):
        self.publish()
        rows = self.log()
        rows[0].update({'状态': '已发', '发布日期': '2026-10-21', '链接': 'https://example.invalid/v/1', '平台': '抖音'})
        rows.append({'编号': 'hand-written', '状态': '计划中'})
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=[*exports.TOOL_COLUMNS, *exports.USER_COLUMNS, '平台'])
        writer.writeheader()
        writer.writerows(rows)
        (self.root / exports.LOG).write_text(text.getvalue(), encoding='utf-8-sig')
        self.publish()
        row = next(row for row in self.log() if row['编号'] == STEM)
        self.assertEqual(('已发', 'https://example.invalid/v/1', '抖音'), (row['状态'], row['链接'], row['平台']))
        self.video.write_bytes(b'fixed video')
        self.publish(revision=2)
        row = next(row for row in self.log() if row['编号'] == STEM)
        self.assertEqual(('2', '待重发', '2026-10-21', '抖音'), (row['版本'], row['状态'], row['发布日期'], row['平台']))
        self.assertIn('hand-written', [row['编号'] for row in self.log()])

    def test_locked_log_does_not_fail_the_export(self):
        with patch.object(exports, '_sync_log', side_effect=PermissionError('open in Excel')):
            result = self.publish()
        self.assertIn('open in Excel', result['log_error'])
        self.assertTrue((self.folder / result['files']['video']).is_file())
        self.assertNotIn('log_error', self.publish())
        self.assertEqual([STEM], [row['编号'] for row in self.log()])

    def test_user_changed_current_file_is_never_overwritten(self):
        first = self.publish()
        target = self.folder / first['files']['video']
        target.write_bytes(b'user changed')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.publish()
        self.cover.write_bytes(b'new cover')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.publish()
        self.assertEqual(b'user changed', target.read_bytes())

    def test_retry_only_copies_missing_files(self):
        real = exports.shutil.copyfileobj
        def fail(source, target):
            if source.name.endswith('cover.png'):
                raise OSError('disk full')
            return real(source, target)
        with patch.object(exports.shutil, 'copyfileobj', fail), self.assertRaises(OSError):
            self.publish()
        result = self.publish()
        self.assertEqual(1, result['version'])
        self.assertTrue((self.folder / result['files']['cover']).is_file())

    def test_without_series_number_or_account_falls_back_to_work_and_variant(self):
        self.assertEqual(('_no-account', '_no-series', 'work001_variant1'), exports.shelf_target('work001', 'variant1'))
        self.assertEqual(('acct-a', 'english-learning', 'work001_variant1'),
                         exports.shelf_target('work001', 'variant1', series='english-learning', account='acct-a'))
        self.assertEqual(('_no-account', 'eng', 'eng_E002_variant1'),
                         exports.shelf_target('work001', 'variant1', series='eng', number=2))
        self.assertEqual(('acct-a', 'eng', 'eng_E002_acct-a-variant1'),
                         exports.shelf_target('work001', 'variant1', series='eng', number=2, account='acct-a',
                                              label='acct-a-variant1'))
        result = self.publish(series=None, number=None)
        self.assertEqual(str(self.root / 'acct-a/_no-series'), result['directory'])
        self.assertEqual('work001_variant1_v01.mp4', result['files']['video'])

    def test_review_escape_and_links_rejected(self):
        with self.assertRaises(ValueError): self.publish(review=True)
        with self.assertRaises(ValueError): self.publish(series='../escape')
        with self.assertRaises(ValueError): self.publish(account='a/b')
        with self.assertRaises(ValueError): self.publish(number=0)
        self.root.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(Exception): self.publish()

    def test_interrupted_index_write_does_not_block_retry_or_erase_unknown_files(self):
        with patch.object(exports.os, 'replace', side_effect=OSError('interrupted index promotion')):
            with self.assertRaises(OSError):
                self.publish()
        for name in ('.exports-a.pending', '.exports-b.pending'):
            (self.root / name).write_bytes(b'unknown interrupted write')
        result = self.publish()
        self.assertEqual(1, result['version'])
        self.assertEqual(result, self.publish())
        self.video.write_bytes(b'new video')
        self.assertEqual(2, self.publish()['version'])
        for name in ('.exports-a.pending', '.exports-b.pending'):
            self.assertEqual(b'unknown interrupted write', (self.root / name).read_bytes())


    def test_index_publish_references_sources_without_copying(self):
        with patch.object(exports, '_copy_verified', side_effect=AssertionError('must not copy')), \
                patch.object(exports, '_retire', side_effect=AssertionError('must not retire')):
            first = self.publish(mode='index')
            self.assertEqual(first, self.publish(mode='index'))
        self.assertEqual(str(self.variant), first['directory'])
        self.assertEqual({'video': 'final.mp4', 'cover': 'cover.png'}, first['files'])
        self.assertFalse((self.root / 'acct-a').exists())
        self.assertFalse(any(path.suffix in ('.mp4', '.png', '.jpg', '.jpeg', '.webp')
                             for path in self.root.rglob('*')))
        episode = json.loads((self.root / exports.INDEX).read_text())['episodes'][f'acct-a/english-learning/{STEM}']
        for item in episode['files']:
            self.assertTrue(item['indexed'])
            self.assertEqual(1, item['version'])
            self.assertEqual(self.video if item['role'] == 'video' else self.cover,
                             self.root.parent / item['file'])
        self.assertEqual(self.video.relative_to(self.root.parent).as_posix(), self.log()[0]['视频'])
        self.assertEqual(self.cover.relative_to(self.root.parent).as_posix(), self.log()[0]['封面'])

    def test_index_new_version_does_not_retire_or_carry_roles(self):
        self.publish(mode='index')
        self.video.write_bytes(b'new final')
        with patch.object(exports, '_copy_verified', side_effect=AssertionError('must not copy')), \
                patch.object(exports, '_retire', side_effect=AssertionError('must not retire')):
            second = self.publish({'video': self.video}, mode='index', revision=2)
        self.assertEqual(2, second['version'])
        self.assertEqual({'video': 'final.mp4'}, second['files'])
        episode = json.loads((self.root / exports.INDEX).read_text())['episodes'][f'acct-a/english-learning/{STEM}']
        self.assertEqual([('cover', 1, False), ('video', 1, False), ('video', 2, True)],
                         [(item['role'], item['version'], item['current']) for item in episode['files']])
        self.assertEqual([], list(self.root.rglob('_superseded')))
        self.assertEqual('', self.log()[0]['封面'])

    def test_copy_to_index_keeps_version_published_status_and_copies(self):
        first = self.publish()
        copies = {role: self.folder / name for role, name in first['files'].items()}
        rows = self.log()
        rows[0]['状态'] = '已发'
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=[*exports.TOOL_COLUMNS, *exports.USER_COLUMNS])
        writer.writeheader()
        writer.writerows(rows)
        (self.root / exports.LOG).write_text(text.getvalue(), encoding='utf-8-sig')
        with patch.object(exports, '_copy_verified', side_effect=AssertionError('must not copy')), \
                patch.object(exports, '_retire', side_effect=AssertionError('must not retire')):
            result = self.publish(mode='index')
        self.assertEqual(first['version'], result['version'])
        self.assertEqual('已发', self.log()[0]['状态'])
        episode = json.loads((self.root / exports.INDEX).read_text())['episodes'][f'acct-a/english-learning/{STEM}']
        self.assertEqual(2, len(episode['files']))
        self.assertTrue(all(item['indexed'] and item['current'] for item in episode['files']))
        for role, path in copies.items():
            self.assertEqual((self.video if role == 'video' else self.cover).read_bytes(), path.read_bytes())
        self.assertEqual([], list(self.root.rglob('_superseded')))

    def test_publish_rejects_unknown_mode_before_writing(self):
        with self.assertRaisesRegex(ValueError, 'export_mode must be copy or index'):
            self.publish(mode='bogus')
        self.assertFalse(self.root.exists())


    def prepare_reindex(self, *, cover=True):
        (self.work / 'WORK.md').write_text('# Fixture\n', encoding='utf-8')
        state = {'revision': 2, **({'current_cover': 'cover.png'} if cover else {})}
        (self.variant / 'variant.yaml').write_text(json.dumps(state), encoding='utf-8')
        final = self.variant / 'final'
        final.mkdir(exist_ok=True)
        (final / 'final.mp4').write_bytes(self.video.read_bytes())
        return final

    def reindex(self, *flags, mode='index', missing_work=False):
        args = work_cli.build_parser().parse_args(['exports', 'reindex', *flags])
        output = io.StringIO()
        with patch.dict(os.environ, {'HYPERFRAMES_AI_RESOLVED_CONFIG': json.dumps(
                {'export_root': str(self.root), 'export_mode': mode})}), \
                patch.object(work_cli, 'locate_work', return_value=(self.work, 'archived'),
                             side_effect=work_cli.HarnessError('Unknown work') if missing_work else None), \
                redirect_stdout(output):
            args.handler(self.base, args)
        return json.loads(output.getvalue())

    def shelf_episode(self):
        return json.loads((self.root / exports.INDEX).read_text())['episodes'][f'acct-a/english-learning/{STEM}']

    def snapshot(self):
        return {path.relative_to(self.base).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                if path.is_file() else None for path in self.base.rglob('*')}

    def test_reindex_cli_preview_does_not_create_runtime_locks_or_reports(self):
        self.publish()
        self.prepare_reindex()
        before = self.snapshot()
        output = io.StringIO()
        with patch.dict(os.environ, {'HYPERFRAMES_AI_RESOLVED_CONFIG': json.dumps(
                {'export_root': str(self.root), 'export_mode': 'index'})}), \
                patch.object(work_cli, 'locate_work', return_value=(self.work, 'archived')), redirect_stdout(output):
            self.assertEqual(0, work_cli.main(['exports', 'reindex'], root=self.base))
        self.assertEqual('converted', json.loads(output.getvalue())['episodes'][0]['status'])
        self.assertEqual(before, self.snapshot())

    def test_reindex_preview_apply_then_delete_preserves_versions_and_user_columns(self):
        self.publish()
        first_video = self.video.read_bytes()
        self.video.write_bytes(b'second video')
        self.publish(revision=2)
        final = self.prepare_reindex()
        history = final / 'history/revision1'
        history.mkdir(parents=True)
        (history / 'final.mp4').write_bytes(first_video)
        rows = self.log()
        user = {'状态': '已发', '发布日期': '2026-10-21', '链接': 'https://example.invalid/1',
                '备注': 'keep notes', '平台': 'manual platform'}
        rows[0].update(user)
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=[*exports.TOOL_COLUMNS, *exports.USER_COLUMNS, '平台'])
        writer.writeheader()
        writer.writerows(rows)
        (self.root / exports.LOG).write_text(text.getvalue(), encoding='utf-8-sig')
        before = self.snapshot()
        preview = self.reindex()
        self.assertEqual('converted', preview['episodes'][0]['status'])
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(item['deleted'] for item in preview['copies']))
        applied = self.reindex('--apply')
        self.assertEqual('converted', applied['episodes'][0]['status'])
        episode = self.shelf_episode()
        self.assertEqual(2, episode['version'])
        self.assertTrue(all(item['indexed'] for item in episode['files'] if item['current']))
        self.assertEqual(4, len([item for item in episode['files'] if not item.get('indexed')]))
        self.assertEqual(user, {key: self.log()[0][key] for key in user})
        self.assertTrue(all((self.root / item['path']).is_file() for item in applied['copies']))
        deleted = self.reindex('--apply', '--delete-copies')
        self.assertEqual('already_indexed', deleted['episodes'][0]['status'])
        self.assertEqual(4, len(deleted['copies']))
        self.assertTrue(all(item['deleted'] for item in deleted['copies']))
        self.assertEqual(sum(item['bytes'] for item in deleted['copies']), deleted['deletable_bytes'])
        self.assertFalse((self.folder / '_superseded').exists())
        self.assertTrue(all('deleted_at' in item for item in self.shelf_episode()['files'] if not item.get('indexed')))
        self.assertEqual(user, {key: self.log()[0][key] for key in user})
        self.assertEqual([], self.reindex('--apply', '--delete-copies')['copies'])

    def test_reindex_keeps_unique_copies_and_inventories_legacy_and_other_variants(self):
        self.publish()
        old_video = self.video.read_bytes()
        self.video.write_bytes(b'new video')
        self.cover.write_bytes(b'new cover')
        self.publish(revision=2)
        self.prepare_reindex()
        other = self.work / 'variants/other/final'
        other.mkdir(parents=True)
        (other / 'final.mp4').write_bytes(old_video)
        legacy = self.root / 'old-series/work001/variant1'
        legacy.mkdir(parents=True)
        (legacy / 'old.mp4').write_bytes(old_video)
        (legacy / 'unique.png').write_bytes(b'only copy')
        (legacy / exports.INDEX).write_text(json.dumps([{'sequence': 1, 'revision': 1,
            'files': {'video': 'old.mp4', 'cover': 'unique.png'},
            'hashes': {'video': exports.sha256(legacy / 'old.mp4'), 'cover': exports.sha256(legacy / 'unique.png')}}]))
        result = self.reindex('--apply', '--delete-copies')
        copies = {item['path']: item for item in result['copies']}
        self.assertTrue(copies['old-series/work001/variant1/old.mp4']['deleted'])
        unique = [item for item in result['copies'] if item['class'] == 'unique']
        self.assertEqual(2, len(unique))
        self.assertTrue(all(not item['deleted'] and (self.root / item['path']).is_file() for item in unique))
        self.assertTrue((legacy / exports.INDEX).is_file())
        self.assertTrue((self.folder / '_superseded').is_dir())
        legacy_record = next(item for item in self.shelf_episode()['files']
                             if item['file'] == 'old-series/work001/variant1/old.mp4')
        self.assertIn('deleted_at', legacy_record)

    def test_reindex_refuses_copy_mode_and_delete_without_apply(self):
        self.publish()
        before = self.snapshot()
        with self.assertRaisesRegex(work_cli.HarnessError, 'Set export_mode to index before reindexing'):
            self.reindex('--apply', mode='copy')
        with self.assertRaisesRegex(work_cli.HarnessError, '--delete-copies requires --apply'):
            self.reindex('--delete-copies')
        self.assertEqual(before, self.snapshot())

    def test_reindex_video_mismatch_does_not_change_files(self):
        self.publish()
        final = self.prepare_reindex()
        (final / 'final.mp4').write_bytes(b'different final')
        before = self.snapshot()
        with patch.object(exports, 'place', side_effect=AssertionError('must not place')):
            result = self.reindex('--apply', '--delete-copies')
        self.assertEqual('mismatch', result['episodes'][0]['status'])
        self.assertFalse(any(item['deleted'] for item in result['copies']))
        self.assertEqual(before, self.snapshot())

    def test_reindex_cover_mismatch_keeps_every_copy_unique_and_unchanged(self):
        self.publish()
        self.prepare_reindex()
        state = json.loads((self.variant / 'variant.yaml').read_text())
        work_cli.write_final_package(self.work, self.variant, state)
        # The old package still proves the copies' hashes; the next cover differs.
        self.cover.write_bytes(b'new unpublished cover')
        before = self.snapshot()
        with patch.object(exports, 'place', side_effect=AssertionError('must not place')), \
                patch.object(work_cli, 'write_final_package', side_effect=AssertionError('must not write')):
            for flags in ((), ('--apply', '--delete-copies')):
                result = self.reindex(*flags)
                self.assertEqual('cover_mismatch', result['episodes'][0]['status'])
                self.assertEqual(0, result['deletable_bytes'])
                self.assertTrue(all(item['class'] == 'unique' and not item['deleted'] for item in result['copies']))
                self.assertEqual(before, self.snapshot())
        self.assertEqual(1, self.shelf_episode()['version'])

    def test_reindex_only_indexes_existing_roles_and_omits_missing_package_cover(self):
        for exported_cover, package_cover in ((False, True), (True, False)):
            with self.subTest(exported_cover=exported_cover):
                self.root = self.base / f'exports-{exported_cover}'
                self.publish({'video': self.video, **({'cover': self.cover} if exported_cover else {})})
                self.prepare_reindex(cover=package_cover)
                self.reindex('--apply')
                current = [item for item in self.shelf_episode()['files'] if item['current']]
                self.assertEqual(['video'], [item['role'] for item in current])
                self.assertEqual(1, self.shelf_episode()['version'])

    def test_reindex_uses_first_work_document_cover(self):
        self.publish()
        self.prepare_reindex(cover=False)
        (self.work / 'WORK.md').write_text('---\n{}\n---\n- 封面：`missing.png` `variants/variant1/cover.png`\n')
        before = self.snapshot()
        self.assertEqual('converted', self.reindex()['episodes'][0]['status'])
        self.assertEqual(before, self.snapshot())
        self.reindex('--apply')
        cover = next(item for item in self.shelf_episode()['files'] if item['current'] and item['role'] == 'cover')
        self.assertEqual(exports.sha256(self.cover), cover['sha256'])

    def test_reindex_missing_work_or_variant_keeps_copies(self):
        self.publish()
        before = self.snapshot()
        self.assertEqual('missing_work', self.reindex('--apply', missing_work=True)['episodes'][0]['status'])
        self.assertEqual(before, self.snapshot())
        data = json.loads((self.root / exports.INDEX).read_text())
        next(iter(data['episodes'].values()))['variant'] = 'absent'
        (self.root / exports.INDEX).write_text(json.dumps(data))
        before = self.snapshot()
        self.assertEqual('missing_work', self.reindex('--apply')['episodes'][0]['status'])
        self.assertEqual(before, self.snapshot())

    def test_reindex_rechecks_copy_hash_before_deletion(self):
        receipt = self.publish()
        self.prepare_reindex()
        self.reindex('--apply')
        target = self.folder / receipt['files']['video']
        real_hash, calls = exports.sha256, 0
        def change_before_delete(path):
            nonlocal calls
            if path == target:
                calls += 1
                if calls == 2:
                    path.write_bytes(b'edited after inventory')
            return real_hash(path)
        with patch.object(exports, 'sha256', side_effect=change_before_delete):
            result = self.reindex('--apply', '--delete-copies')
        item = next(item for item in result['copies'] if item['path'] == target.relative_to(self.root).as_posix())
        self.assertFalse(item['deleted'])
        self.assertEqual(b'edited after inventory', target.read_bytes())
        record = next(item for item in self.shelf_episode()['files'] if item['file'] == target.relative_to(self.root).as_posix())
        self.assertNotIn('deleted_at', record)


if __name__ == '__main__': unittest.main()
