"""Native development wiring must not inherit production scope."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('macos_dev', str(Path(__file__).resolve().parents[1] / 'dev-macos'))
spec = importlib.util.spec_from_loader(loader.name, loader)
DEV = importlib.util.module_from_spec(spec)
loader.exec_module(DEV)


class MacDevelopmentTest(unittest.TestCase):
    def test_environment_is_native_and_scoped_even_with_production_inheritance(self):
        with tempfile.TemporaryDirectory(prefix='mac dev ') as temporary:
            root = Path(temporary).resolve()
            local = root / '.studio/.runtime/macos-preview'
            cli = local / 'npm/node_modules/hyperframes/dist/cli.js'
            cli.parent.mkdir(parents=True)
            cli.write_text('fixture')
            config = {}
            for name in ('python', 'node', 'browser', 'ffmpeg', 'ffprobe'):
                path = root / ('tool ' + name)
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
                config[name] = str(path)
            inherited = {'PATH': '/usr/bin', 'HYPERFRAMES_AI_WORK_ROOT': '/production',
                         'HYPERFRAMES_AI_CONFIG': '/production/config.json',
                         'HYPERFRAMES_AI_ASSET_ROOT': '/production/assets',
                         'HYPERFRAMES_AI_RESOLVED_CONFIG': '{"work_root":"/production"}',
                         'NODE_OPTIONS': '--require /windows/preload.cjs'}
            with patch.object(DEV, 'ROOT', root), patch.object(DEV, 'LOCAL', local), \
                    patch.dict(os.environ, inherited, clear=True), \
                    patch.object(DEV.tempfile, 'gettempdir', return_value='/tmp'):
                env = DEV.environment(config, review=True)
                self.assertEqual(str(local / 'sandbox/review/macos'), env['HYPERFRAMES_AI_WORK_ROOT'])
                self.assertEqual('1', env['HYPERFRAMES_AI_REVIEW'])
                self.assertEqual(str(Path('/tmp').resolve()), env['TMPDIR'])
                self.assertEqual(str(cli), env['HYPERFRAMES_CLI'])
                self.assertEqual(config['browser'], env['HYPERFRAMES_STUDIO_BROWSER_PATH'])
                self.assertEqual(str(local / 'content.json'), env['HYPERFRAMES_AI_CONFIG'])
                self.assertEqual(str(local / 'content.json'), env['HYPERFRAMES_AI_ASSET_CONFIG'])
                for key in ('HYPERFRAMES_AI_ASSET_ROOT',
                            'HYPERFRAMES_AI_RESOLVED_CONFIG', 'NODE_OPTIONS'):
                    self.assertNotIn(key, env)
                test_env = DEV.environment(config)
                self.assertFalse(any(key.startswith('HYPERFRAMES_AI_') for key in test_env))
                unit_env = DEV.unit_environment(config)
                self.assertFalse(any(key.startswith('HYPERFRAMES_') for key in unit_env))
                self.assertNotIn('HF_PACKAGE', unit_env)
                self.assertNotIn('CHROME_PATH', unit_env)
                self.assertEqual(test_env['PATH'], unit_env['PATH'])
                Path(config['browser']).unlink()
                with self.assertRaisesRegex(ValueError, 'Executable unavailable'):
                    DEV.environment(config)


if __name__ == '__main__':
    unittest.main()
