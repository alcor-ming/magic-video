from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import unittest

REPO = Path(__file__).resolve().parents[1]
LOADER = SourceFileLoader('mac_compat_audit', str(REPO / 'mac-compat-audit'))
SPEC = importlib.util.spec_from_loader('mac_compat_audit', LOADER)
AUDIT = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(AUDIT)


class MacCompatAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))

    def snapshot(self):
        result = []
        for directory, folders, files in os.walk(self.root):
            for name in folders + files:
                path = Path(directory) / name
                stat = path.stat()
                result.append((str(path.relative_to(self.root)), stat.st_size, stat.st_mtime_ns))
        stat = self.root.stat()
        result.append(('.', stat.st_size, stat.st_mtime_ns))
        return sorted(result)

    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = AUDIT.main(list(args))
        self.assertEqual(code, 0)
        return output.getvalue()

    def test_scan_root_and_read_only(self):
        self.put('a.json', r'{"path": "D:\\AI\\x"}')
        self.put('b.yaml', 'path: /mnt/d/AI')
        self.put('c.md', 'https://example.com http://example.com\nD:/AI')
        self.put('node_modules/x.json', 'D:\\')
        nfd = unicodedata.normalize('NFD', 'café.txt')
        self.put(nfd, '')
        self.put('Readme.md', '')
        self.put('README.md', '')
        self.put('run.sh', b'#!/bin/sh\r\necho\r\n')
        self.put('ok.sh', b'#!/bin/sh\necho\n')
        self.put('work.cmd', '')
        self.put('x.ps1', '')
        self.put('bin.json', b'D:\\AI\0')
        before = self.snapshot()
        report = AUDIT.scan_root(self.root)
        self.assertEqual(len(report['windows_paths']), 3)
        self.assertEqual({row['path'] for row in report['windows_paths']}, {'a.json', 'b.yaml', 'c.md'})
        self.assertEqual(report['windows_paths'][-1]['line'], 2)
        self.assertEqual(report['totals']['files'], 12)
        self.assertEqual(report['totals']['bytes'], sum(size for path, size, _ in before if (self.root / path).is_file()))
        self.assertEqual(report['totals']['by_directory']['node_modules'], {'files': 1, 'bytes': 3})
        self.assertIn(nfd, report['nfd_names'])
        self.assertEqual(report['case_conflicts'], [['README.md', 'Readme.md']])
        self.assertEqual(report['crlf_scripts'], ['run.sh'])
        self.assertEqual(report['windows_only']['counts']['.cmd'], 1)
        self.assertEqual(report['windows_only']['counts']['.ps1'], 1)
        self.assertEqual(report, json.loads(self.invoke('scan-root', str(self.root), '--json')))
        self.assertIn('windows_paths: 3 total', self.invoke('scan-root', str(self.root)))
        self.assertEqual(before, self.snapshot())

    def test_text_limits_wsl_and_custom_skip(self):
        self.put('paths.txt', '\n'.join([r'D:\AI', r'\\wsl$\Ubuntu', r'\\wsl.localhost\Ubuntu', r'\\\\wsl$\\Ubuntu']))
        self.put('large.json', b'D:/AI' + b' ' * (2 * 1024 * 1024))
        self.put('skip/x.json', 'D:/AI')
        self.put('bad.txt', b'\xff D:/AI' + b'x' * 200)
        self.put('tool', b'#!/bin/sh\r\necho\r\n')
        self.put('plain', b'plain\r\n')
        report = json.loads(self.invoke('scan-root', str(self.root), '--json', '--skip-text-dir', 'skip'))
        self.assertEqual(len(report['windows_paths']), 5)
        self.assertEqual(sum(row['kind'] == 'wsl' for row in report['windows_paths']), 3)
        self.assertTrue(all(len(row['snippet']) <= 160 for row in report['windows_paths']))
        self.assertEqual(report['crlf_scripts'], ['tool'])

    def test_scan_fonts_and_read_only(self):
        self.put('s.css', 'font-family: "Microsoft YaHei", sans-serif;')
        self.put('t.css', 'font-family: "Source Han Sans SC", "PingFang SC", sans-serif;')
        self.put('u.mjs', '''fontFamily: '\"Noto Sans\", sans-serif' ''')
        self.put('node_modules/skip.css', 'font-family: SimHei;')
        self.put('.git/skip.css', 'font-family: SimSun;')
        before = self.snapshot()
        report = AUDIT.scan_fonts([self.root])
        self.assertEqual(report['risks'], {'leading': 1, 'fallback': 1})
        self.assertEqual(report['platform_fonts'], {'Microsoft YaHei': 1, 'PingFang SC': 1})
        self.assertEqual(len(report['stacks']), 2)
        self.assertEqual(report['stacks'][0]['stack'], ['Microsoft YaHei', 'sans-serif'])
        self.assertEqual(report['stacks'][0]['line'], 1)
        self.assertEqual(report, json.loads(self.invoke('scan-fonts', str(self.root), '--json')))
        self.assertIn('stacks: 2 total', self.invoke('scan-fonts', str(self.root)))
        self.assertEqual(before, self.snapshot())

    def test_js_fonts_multiple_roots(self):
        self.put('one/x.json', '\n{"fontFamily": "segoe ui, sans-serif"}')
        self.put('two/y.vue', '''fontFamily: `Custom, '-APPLE-SYSTEM', serif`''')
        report = json.loads(self.invoke('scan-fonts', str(self.root / 'one'), str(self.root / 'two'), '--json'))
        self.assertEqual(report['risks'], {'leading': 1, 'fallback': 1})
        self.assertEqual(report['platform_fonts'], {'Segoe UI': 1, '-apple-system': 1})
        self.assertEqual(report['stacks'][0]['line'], 2)

    def test_broken_symlink_and_large_extensionless_file(self):
        (self.root / 'dangling').symlink_to(self.root / 'missing-target')
        self.put('blob', b'#!' + b'\r\n' * (2 * 1024 * 1024))
        self.put('node_modules/lib.js', 'x\r\n')
        report = AUDIT.scan_root(self.root)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['totals']['files'], 3)
        self.assertEqual(report['crlf_scripts'], [])

    def test_missing_path(self):
        for command in ('scan-root', 'scan-fonts'):
            with self.subTest(command=command):
                output, error = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(AUDIT.main([command, str(self.root / 'missing')]), 2)
                self.assertEqual(output.getvalue(), '')
                self.assertIn('missing', error.getvalue())


if __name__ == '__main__':
    unittest.main()
