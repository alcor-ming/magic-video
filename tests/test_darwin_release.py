"""Native delivery regressions: executable bytes, target identity and isolation."""
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.studio'))
import windows_runtime as runtime
import root_deploy
loader = SourceFileLoader('native_release', str(ROOT / 'release'))
spec = importlib.util.spec_from_loader(loader.name, loader)
release = importlib.util.module_from_spec(spec)
loader.exec_module(release)


class DarwinReleaseTests(unittest.TestCase):
    def test_archive_retains_execution_without_privileged_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive = base / 'runtime.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                for name, mode in [('bin/tool', 0o104755), ('data.json', 0o100644)]:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    z.writestr(info, 'fixture')
            release.extract_zip(archive, base / 'out')
            self.assertEqual(0o755, (base / 'out/bin/tool').stat().st_mode & 0o7777)
            self.assertEqual(0o644, (base / 'out/data.json').stat().st_mode & 0o7777)

    def test_archive_link_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'runtime.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                info = zipfile.ZipInfo('escape')
                info.external_attr = 0o120777 << 16
                z.writestr(info, '/outside')
            with self.assertRaisesRegex(release.ReleaseError, 'symlinks'):
                release.extract_zip(archive, Path(temp) / 'out')

    def test_native_runtime_stages_without_windows_python_pth(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); stage = base / 'stage'; stage.mkdir()
            archive = base / 'runtime.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                info = zipfile.ZipInfo('python/bin/python3'); info.external_attr = 0o755 << 16
                z.writestr(info, 'fixture')
            lock = {'target': 'darwin-arm64', 'required_files': ['runtime/python/bin/python3'],
                    'assets': [{'kind': 'zip', 'target': 'runtime', 'file': archive.name, 'sha256': release.sha256(archive)}]}
            (stage / 'darwin-runtime.lock.json').write_text(json.dumps(lock))
            release.stage_runtime(stage, base, 'darwin-arm64')
            self.assertTrue(os.access(stage / 'runtime/python/bin/python3', os.X_OK))
            self.assertFalse((stage / 'runtime/python/Lib').exists())

    def test_native_environment_ignores_foreign_preload_and_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / '.release.json').write_text(json.dumps({'release': 'local-mac', 'target': 'darwin-arm64'}))
            config = {'work_root': str(root), 'asset_root': str(root / 'asset-library/store')}
            with patch.dict(os.environ, {'PYTHONHOME': '/foreign/python', 'PYTHONPATH': '/foreign/python', 'NODE_OPTIONS': '--require /foreign/preload', 'HYPERFRAMES_NODE': '/foreign/node', 'HYPERFRAMES_DEPENDENCY_MODULE_ROOT': '/foreign/npm', 'HYPERFRAMES_STUDIO_BROWSER_PATH': '/foreign/chrome'}):
                env = runtime.environment(root, config)
            self.assertNotIn('NODE_OPTIONS', env)
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertEqual('1', env['PYTHONNOUSERSITE'])
            self.assertEqual(str(root / 'runtime/npm'), env['HYPERFRAMES_DEPENDENCY_MODULE_ROOT'])
            self.assertNotIn('HYPERFRAMES_STUDIO_BROWSER_PATH', env)
            self.assertEqual(str(root / 'runtime/node/node'), env['HYPERFRAMES_NODE'])
            self.assertEqual(str(root / 'runtime/chromium/chrome-headless-shell'), env['HYPERFRAMES_BROWSER_PATH'])
            self.assertEqual(str(root / '.studio/.runtime/cache'), env['TMPDIR'])

    def test_native_process_detection_includes_versioned_python(self):
        for executable in ('python3', 'python3.12', 'node', 'chrome-headless-shell'):
            with self.subTest(executable=executable), patch.object(root_deploy.subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, f'987654 /fixture/runtime/{executable} /fixture/.studio/work.py\n', '')):
                with self.assertRaisesRegex(ValueError, 'active'):
                    root_deploy.idle(Path('/fixture'), target='darwin-arm64')

    def test_personal_native_rules_come_from_frozen_overlay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'personal').mkdir(); (root / '.studio/templates').mkdir(parents=True)
            for name in ('AGENTS.md', 'CLAUDE.md'):
                (root / ('personal/macos-' + name)).write_text('private native ' + name)
            (root / '.studio/templates/work-macos.sh').write_text('#!/bin/sh\n')
            release.stage_darwin_rules(root, True)
            self.assertEqual('private native AGENTS.md', (root / 'AGENTS.md').read_text())
            self.assertTrue(os.access(root / 'work', os.X_OK))

    def test_target_changes_build_fingerprint(self):
        with patch.object(release, 'source_hashes', return_value={}), patch.object(release, 'LOCAL_SKILLS', {}):
            self.assertNotEqual(release.candidate_fingerprint([], 'local', None, target='darwin-arm64'),
                                release.candidate_fingerprint([], 'local', None, target='windows-x64'))

    def test_native_process_detection_with_spaces_in_root(self):
        with patch.object(root_deploy.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                '987654 /fixture/Root With Spaces/runtime/node/node /fixture/Root With Spaces/.studio/preview.js\n', '')):
            with self.assertRaisesRegex(ValueError, 'active'):
                root_deploy.idle(Path('/fixture/Root With Spaces'), target='darwin-arm64')

    def test_source_runtime_paths_do_not_require_release_manifest(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runtime.sys, 'platform', 'darwin'):
            self.assertEqual(Path(temp) / 'runtime/node/node', runtime.runtime_paths(Path(temp))['HYPERFRAMES_NODE'])
