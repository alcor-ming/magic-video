import csv
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import exports


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


if __name__ == '__main__': unittest.main()
