"""stage-full motion reaches a Work: tool runtime/motion.js plus in-card assets installed into vendor."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

import asset_store
from asset_contract import freeze_source
from component_harness import ComponentError, install_component, verify_installation

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('stage-full/stage-rig', 'stage-full/stage-kit', 'stage-full/stage-motion')


class StageMotionInstallTest(unittest.TestCase):
    def install(self, project, ref):
        source, _ = asset_store.resolve_component(ROOT, ref)
        with tempfile.TemporaryDirectory() as temporary:
            release = freeze_source(source, Path(temporary) / 'asset', card_ref=ref)
            binding = {'schema_version': 3, 'component_ref': release['component_ref'], 'scene': 'S01',
                       'usage': {'role': 'auxiliary', 'required': True}}
            install_component(Path(temporary) / 'asset', project, binding,
                              binding_path=f"component-bindings/{ref.split('/')[1]}.json",
                              expected_ref=release['component_ref'])

    def test_work_project_loads_tool_runtime_then_card_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            (project / 'runtime').mkdir(parents=True)
            shutil.copyfile(ROOT / '.studio/runtime/motion.js', project / 'runtime/motion.js')
            scripts = ['runtime/motion.js', 'vendor/components/stage-full/stage-rig/v1/stage-rig.js',
                       'vendor/components/stage-full/stage-kit/v1/stage-kit.js',
                       'vendor/components/stage-full/stage-kit/v1/blocks/disc-scene.js',
                       'vendor/components/stage-full/stage-motion/v1/stage-motion.js']
            (project / 'index.html').write_text(
                '<!doctype html><html><body>' + ''.join(f'<script src="{s}"></script>' for s in scripts) + '</body></html>',
                encoding='utf-8')
            for ref in ASSETS:
                self.install(project, ref)
            report = verify_installation(project)
            self.assertEqual({'stage-full/stage-rig@v1', 'stage-full/stage-kit@v1', 'stage-full/stage-motion@v1'},
                             {item['component_ref'] for item in json.loads((project / 'COMPONENT_LOCK.json').read_text())['components']})
            self.assertIn({'entry': 'vendor/components/stage-full/stage-motion/v1/stage-motion.js'},
                          [mount for item in report['components'] for mount in item['mounts']])
            # 装了动作包却没在页面加载，校验要拦下。
            (project / 'index.html').write_text('<!doctype html><html><body>' + ''.join(
                f'<script src="{s}"></script>' for s in scripts[:-1]) + '</body></html>', encoding='utf-8')
            with self.assertRaisesRegex(ComponentError, 'stage-motion.js'):
                verify_installation(project)


if __name__ == '__main__':
    unittest.main()
