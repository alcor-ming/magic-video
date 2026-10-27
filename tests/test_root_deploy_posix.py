import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import root_deploy as deploy


class PosixDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'Root With Spaces'
        for name in ('works', 'asset-library/store', 'asset-library/sources/demo'):
            (self.root / name).mkdir(parents=True)
        self.settings = {'work_root': str(self.root),
                         'asset_root': str(self.root / 'asset-library/store'),
                         'asset_review_root': str(self.root / 'asset-library'),
                         'asset_source_roots': [str(self.root / 'asset-library/sources/demo')],
                         'review': True, 'review_protected_roots': [str(self.base / 'protected')]}
        self.config = self.base / 'config.json'
        self.config.write_text(json.dumps(self.settings))
        self.sentinel = self.root / 'works/user.txt'
        self.sentinel.write_text('user content')
        self.run = self.enterContext(patch.object(deploy.subprocess, 'run'))
        self.run.return_value.stdout = ''

    def package(self, name, *, tools=False, extra=False):
        package = self.base / name
        package.mkdir()
        files = {'work': '#!/bin/sh\n# ' + name + '\nexit 0\n',
                 'darwin-runtime.lock.json': '{"synthetic": true}\n'}
        if not tools:
            files['runtime/python/python'] = 'fake runtime\n'
        if extra:
            files['new.txt'] = 'new managed content'
        hashes = {}
        for relative, content in files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            hashes[relative] = deploy.digest(path)
        (package / 'work').chmod(0o755)
        manifest = {'release': 'candidate-' + name, 'channel': 'candidate',
                    'target': 'darwin-arm64', 'layout': 'root-v1', 'files': hashes}
        if tools:
            manifest.update(package_kind='tools',
                            runtime_lock_sha256=hashes['darwin-runtime.lock.json'],
                            runtime_files={'runtime/python/python': deploy.digest(self.root / 'runtime/python/python')})
        deploy.write_json(package / '.release.json', manifest)
        return package

    def assert_user_content(self, config_bytes):
        self.assertEqual(self.sentinel.read_text(), 'user content')
        self.assertEqual((self.root / deploy.CONFIG).read_bytes(), config_bytes)

    def assert_completed(self, state):
        backup = self.root / state['backup']
        transaction = deploy.read(backup / 'transaction.json')
        self.assertEqual(transaction['backup'], state['backup'])
        self.assertEqual(deploy.read(backup / 'completed.json')['transaction_sha256'],
                         deploy.digest(backup / 'transaction.json'))
        self.assertFalse((self.root / deploy.PENDING).exists())

    def test_full_update_unchanged_and_rollback(self):
        first = self.package('a')
        initial = deploy.deploy(first, self.root, self.config)
        self.assertEqual(deploy.verify_root(self.root)['release'], 'candidate-a')
        self.assertTrue(os.access(self.root / 'work', os.X_OK))
        self.assert_completed(initial)
        config_bytes = (self.root / deploy.CONFIG).read_bytes()
        self.assertEqual(json.loads(config_bytes), self.settings)
        second = self.package('b', extra=True)
        updated = deploy.deploy(second, self.root, None)
        self.assert_completed(updated)
        stamps = {p: p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        again = deploy.deploy(second, self.root, None)
        self.assertEqual(again['status'], 'unchanged')
        for key in ('changed_count', 'backup_bytes', 'written_bytes'):
            self.assertEqual(again[key], 0)
        self.assertEqual(again['backup'], updated['backup'])
        self.assertEqual(stamps, {p: p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()})
        self.assert_user_content(config_bytes)
        deploy.recover(self.root, rollback=True)
        self.assertEqual(deploy.verify_root(self.root)['release'], 'candidate-a')
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual((self.root / 'work').read_bytes(), (first / 'work').read_bytes())
        self.assert_user_content(config_bytes)
        for call in self.run.call_args_list:
            self.assertEqual(call.args[0], ['ps', '-axo', 'pid=,command='])

    def test_tools_binding_and_rollback(self):
        initial = deploy.deploy(self.package('full'), self.root, self.config)
        config_bytes = (self.root / deploy.CONFIG).read_bytes()
        runtime = self.root / 'runtime/python/python'
        stamp = runtime.stat().st_mtime_ns
        tools = self.package('tools', tools=True)
        result = deploy.deploy(tools, self.root, None)
        self.assertEqual(runtime.stat().st_mtime_ns, stamp)
        self.assertFalse((self.root / result['backup'] / 'runtime').exists())
        self.assertEqual(result['files']['runtime/python/python'], initial['files']['runtime/python/python'])
        self.assert_completed(result)
        deploy.recover(self.root, rollback=True)
        self.assertEqual(deploy.verify_root(self.root)['release'], 'candidate-full')
        manifest = deploy.read(tools / '.release.json')
        manifest['runtime_files']['runtime/python/python'] = '0' * 64
        (tools / '.release.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Installed runtime differs'):
            deploy.deploy(tools, self.root, None)
        manifest['runtime_files']['runtime/python/python'] = initial['files']['runtime/python/python']
        (tools / 'darwin-runtime.lock.json').write_text('{"synthetic": "different"}')
        manifest['runtime_lock_sha256'] = deploy.digest(tools / 'darwin-runtime.lock.json')
        manifest['files']['darwin-runtime.lock.json'] = manifest['runtime_lock_sha256']
        (tools / '.release.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Installed runtime differs'):
            deploy.deploy(tools, self.root, None)
        manifest['runtime_lock_sha256'] = '1' * 64
        (tools / '.release.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'runtime lock mismatch'):
            deploy.deploy(tools, self.root, None)
        self.assertEqual(runtime.stat().st_mtime_ns, stamp)
        self.assert_user_content(config_bytes)

    def test_idle_process_matching(self):
        pid = os.getpid() + 100000
        for command in (f'/usr/bin/python {self.root}/works/render.py',
                        f'node {self.root}/works/build.js',
                        f'/opt/Chrome.EXE {self.root}/preview',
                        '/tmp/root/runtime/ffmpeg -version'):
            root = Path('/tmp/root') if command.startswith('/tmp/root/') else self.root
            with self.subTest(command=command):
                self.run.return_value.stdout = f'\n {pid} {command}\n'
                with self.assertRaisesRegex(ValueError, f'Root process {pid} is active'):
                    deploy.idle(root, target='darwin-arm64')
        for command in (f'node --cwd {self.root}', f'other {self.root}/file',
                        f'node {str(self.root).lower()}/file', f'node {self.root}-other/file',
                        'python /unrelated/file'):
            with self.subTest(command=command):
                self.run.return_value.stdout = f'{pid} {command}\n'
                deploy.idle(self.root, target='darwin-arm64')
        self.run.return_value.stdout = f'{os.getpid()} node {self.root}/file\n'
        deploy.idle(self.root, target='darwin-arm64')
        for call in self.run.call_args_list:
            self.assertEqual(call.args, (['ps', '-axo', 'pid=,command='],))
            self.assertEqual(call.kwargs, dict(capture_output=True, encoding='utf-8', check=True))
        self.run.side_effect = subprocess.CalledProcessError(1, 'ps')
        with self.assertRaises(subprocess.CalledProcessError):
            deploy.idle(self.root, target='darwin-arm64')
        self.run.reset_mock()
        for target in (None, '', 'unknown'):
            with self.assertRaisesRegex(ValueError, 'Unsupported package identity'):
                deploy.idle(self.root, target=target)
        self.run.assert_not_called()

    def test_preflight_and_rollback_use_current_target(self):
        self.assertEqual(deploy.preflight(self.root, self.config)['status'], 'ready')
        self.run.assert_not_called()
        deploy.deploy(self.package('first'), self.root, self.config)
        deploy.deploy(self.package('second'), self.root, None)
        self.run.return_value.stdout = f'{os.getpid() + 100000} node {self.root}/build.js\n'
        for operation in (lambda: deploy.preflight(self.root),
                          lambda: deploy.recover(self.root, rollback=True),
                          lambda: deploy.deploy(self.package('blocked'), self.root, None)):
            with self.assertRaisesRegex(ValueError, 'is active'):
                operation()
        self.assertFalse((self.root / deploy.PENDING).exists())
        release = self.root / '.release.json'
        manifest = deploy.read(release)
        for target in (None, 'unknown'):
            manifest['target'] = target
            release.write_text(json.dumps(manifest))
            for operation in (lambda: deploy.preflight(self.root),
                              lambda: deploy.recover(self.root, rollback=True)):
                with self.assertRaisesRegex(ValueError, 'Unsupported package identity'):
                    operation()

    def test_pending_prefers_backup_identity(self):
        deploy.deploy(self.package('old'), self.root, self.config)
        state = deploy.deploy(self.package('new'), self.root, None)
        transaction = deploy.read(self.root / state['backup'] / 'transaction.json')
        deploy.write_json(self.root / deploy.PENDING, transaction)
        (self.root / '.release.json').write_text('incomplete JSON')
        self.run.return_value.stdout = f'{os.getpid() + 100000} node {self.root}/build.js\n'
        with self.assertRaisesRegex(ValueError, 'is active'):
            deploy.recover(self.root)
        # Model an interrupted write whose current bytes are recorded in the transaction.
        transaction['after']['.release.json'] = deploy.digest(self.root / '.release.json')
        (self.root / deploy.PENDING).write_text(json.dumps(transaction))
        self.run.return_value.stdout = ''
        deploy.recover(self.root)
        self.assertEqual(deploy.verify_root(self.root)['release'], 'candidate-old')
        self.assertFalse((self.root / deploy.PENDING).exists())

    def test_pending_first_install_fallbacks(self):
        state = deploy.deploy(self.package('initial'), self.root, self.config)
        transaction = deploy.read(self.root / state['backup'] / 'transaction.json')
        deploy.write_json(self.root / deploy.PENDING, transaction)
        self.run.return_value.stdout = f'{os.getpid() + 100000} node {self.root}/build.js\n'
        with self.assertRaisesRegex(ValueError, 'is active'):
            deploy.recover(self.root)
        (self.root / '.release.json').unlink()
        self.run.reset_mock()
        deploy.recover(self.root)
        self.run.assert_not_called()
        self.assertFalse((self.root / deploy.PENDING).exists())
        self.assertEqual(self.sentinel.read_text(), 'user content')

    def test_isolated_cli_uses_fake_ps(self):
        package = self.package('isolated')
        fake_bin = self.base / 'bin'
        fake_bin.mkdir()
        ps = fake_bin / 'ps'
        ps.write_text('#!/bin/sh\n[ "$#" = 2 ] && [ "$1" = "-axo" ] && [ "$2" = "pid=,command=" ] || exit 9\nexit 0\n')
        ps.chmod(0o755)
        # Restore subprocess.run only for this isolated child; its ps is a fake command.
        with patch.object(subprocess, 'run', self.real_run):
            result = subprocess.run([sys.executable, '-I', '-S', '-B', deploy.__file__, 'deploy',
                                     '--package', str(package), '--root', str(self.root),
                                     '--config', str(self.config)], capture_output=True, text=True,
                                    timeout=45, env={**os.environ, 'PATH': str(fake_bin)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['release'], 'candidate-isolated')
        self.assertEqual(deploy.verify_root(self.root)['release'], 'candidate-isolated')

    real_run = staticmethod(subprocess.run)


if __name__ == '__main__':
    unittest.main()
