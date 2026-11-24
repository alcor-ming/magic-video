"""Public history example and a silent Work's actual registration path."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_work_cli import REPO, WORK_CLI as cli
import design_examples
import designs
import storage

CARD = REPO / '.studio/designs/history-map'
THREE = 'runtime/three.min.js'
HOST_THREE = 'runtime/npm/node_modules/three/build/three.min.js'
GSAP_FILES = ('gsap.min.js', 'MotionPathPlugin.min.js')
HOST_GSAP_DIST = 'runtime/npm/node_modules/gsap/dist'


def fixture_host(root):
    shutil.copyfile(REPO / 'windows-npm.lock.json', root / 'windows-npm.lock.json')
    for name in (HOST_THREE, *(f'{HOST_GSAP_DIST}/{name}' for name in GSAP_FILES)):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('// test fixture for ' + Path(name).name + '\n', encoding='utf-8')
    return root / HOST_THREE


class HistoryMapTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(REPO / '.studio/templates', self.root / '.studio/templates')
        self.three = fixture_host(self.root)

    def invoke(self, *args, status=0):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            actual = cli.main(['--json', *args], root=self.root)
        self.assertEqual(status, actual, out.getvalue() + err.getvalue())
        return out.getvalue().strip() if status == 0 else err.getvalue().strip()

    def new(self, status=0):
        return self.invoke('new', '历史地图夹具', '--workflow', 'hyperframes_video',
                           '--purpose', 'test', '--design', 'history-map', '--detached', '--separate', status=status)

    def test_builtin_example_dependencies_and_artwork_provenance(self):
        card = designs.get('history-map')
        self.assertEqual('0.160.0', card['runtime']['three'])
        self.assertNotIn('english', designs.capabilities(card)['checks'])
        destination = self.root / 'example'
        design_examples.build('history-map', destination, runtime_root=self.root)
        self.assertEqual(self.three.read_bytes(), (destination / THREE).read_bytes())
        self.assertEqual(['MotionPathPlugin'], card['runtime']['plugins'])
        html = (destination / 'index.html').read_text(encoding='utf-8')
        self.assertLess(html.index('runtime/gsap.min.js'), html.index('runtime/MotionPathPlugin.min.js'))
        self.assertLess(html.index('runtime/MotionPathPlugin.min.js'), html.index('scene.js'))
        for name in GSAP_FILES:
            self.assertEqual((self.root / HOST_GSAP_DIST / name).read_bytes(),
                             (destination / 'runtime' / name).read_bytes())
            self.assertFalse((CARD / 'runtime' / name).exists())
        self.assertFalse((CARD / THREE).exists())
        self.assertEqual({'world', 'plates'}, {p.name for p in (CARD / 'assets').iterdir()})
        rows = dict(re.findall(r'^\| `([^`]+\.webp)` \| .*? `([0-9a-f]{64})` \|$',
                               (CARD / 'ASSETS.md').read_text(encoding='utf-8'), re.M))
        self.assertEqual({p.relative_to(CARD).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in CARD.rglob('*.webp')}, rows)
        self.assertLess(sum((CARD / path).stat().st_size for path in rows), 15_000_000)
        manifest = json.loads((REPO / '.studio/release-sources.json').read_text(encoding='utf-8'))
        self.assertEqual({p.relative_to(REPO).as_posix() for p in CARD.rglob('*') if p.is_file()},
                         {name for name in manifest['files'] if name.startswith('.studio/designs/history-map/')})

    def test_work_copies_runtime_and_preserves_local_bytes(self):
        work_id = self.new()
        work = cli.locate_work(self.root, work_id)[0]
        project = work / 'variants/variant1/project'
        original = self.three.read_bytes()
        self.assertEqual(original, (project / THREE).read_bytes())
        self.assertFalse((project / THREE).is_symlink())
        self.assertIn(THREE, cli.read_json(project / 'project-config.json')['snapshot_dependencies'])
        self.three.unlink()
        self.assertEqual(original, (project / THREE).read_bytes())
        self.assertIn('Host runtime does not provide: three.min.js', self.new(status=2))
        self.assertEqual([work], list(work.parent.iterdir()))

    def test_reselect_materializes_runtime_and_keeps_existing_dependencies(self):
        work_id = self.invoke('new', '历史地图重选夹具', '--workflow', 'hyperframes_video',
                              '--purpose', 'test', '--design', 'stage-light', '--detached', '--separate')
        variant = cli.locate_work(self.root, work_id)[0] / 'variants/variant1'
        project = variant / 'project'
        config = project / 'project-config.json'
        cli.write_json(config, {'snapshot_dependencies': ['media.txt'], 'authored': True})
        for name in ('DESIGN.md', 'index.html', 'media.txt'):
            (project / name).write_text('authored', encoding='utf-8')
        reselect = ('--work', work_id, '--variant', 'variant1', 'variant', 'reselect', '--design', 'history-map')
        self.assertEqual('preview', json.loads(self.invoke(*reselect))['status'])
        self.assertFalse((project / THREE).exists())
        (project / THREE).parent.mkdir(exist_ok=True)
        (project / THREE).write_bytes(b'authored runtime')
        state = variant / 'variant.yaml'
        before = state.read_bytes()
        self.assertIn('Project runtime differs from host', self.invoke(*reselect, '--apply', status=2))
        self.assertEqual(before, state.read_bytes())
        self.assertEqual(b'authored runtime', (project / THREE).read_bytes())
        (project / THREE).unlink()
        self.assertEqual('reselected', json.loads(self.invoke(*reselect, '--apply'))['status'])
        self.assertEqual(self.three.read_bytes(), (project / THREE).read_bytes())
        self.assertEqual({'snapshot_dependencies': ['media.txt', THREE], 'authored': True}, cli.read_json(config))
        self.assertIn(THREE, storage.snapshot_files(project))
        self.assertEqual('authored', (project / 'index.html').read_text(encoding='utf-8'))

    def test_design_update_supplies_runtime_to_older_history_variant(self):
        import design_snapshot
        work_id = self.new()
        variant = cli.locate_work(self.root, work_id)[0] / 'variants/variant1'
        project = variant / 'project'
        receipt = design_snapshot.freeze(variant, 'history-map')
        state = cli.read_json(variant / 'variant.yaml')
        cli.adopt_card_files(state, receipt)
        cli.write_variant(variant, state)
        (project / THREE).unlink()
        cli.write_json(project / 'project-config.json', {'snapshot_dependencies': []})
        for name in ('DESIGN.md', 'index.html'):
            (project / name).touch()
        with patch.object(cli, 'command_preview_open', return_value={'status': 'fixture'}):
            self.invoke('--work', work_id, '--variant', 'variant1', 'variant', 'design-update')
        self.assertEqual(self.three.read_bytes(), (project / THREE).read_bytes())
        self.assertIn(THREE, storage.snapshot_files(project))
        design_snapshot.verify(variant / receipt['path'], receipt)

    def test_no_voice_plan_and_executable_snapshot(self):
        work_id = self.new()
        work = cli.locate_work(self.root, work_id)[0]
        variant = work / 'variants/variant1'
        project = variant / 'project'
        selector = ('--work', work_id, '--variant', 'variant1')
        example = design_examples.build('history-map', self.root / 'example', runtime_root=self.root)
        for name in ('SCRIPT.md', 'RESEARCH.md'):
            shutil.copyfile(example / name, cli.input_path(variant, name))
        plan = variant / 'ANIMATION_PLAN.md'
        plan.write_text('---\n' + json.dumps(cli.read_frontmatter(plan)) + '\n---\n' +
                        cli.document_body(example / plan.name), encoding='utf-8')
        for item in design_examples.manifest('history-map')['files']:
            name = item['target']
            if name in {'SCRIPT.md', 'RESEARCH.md', 'ANIMATION_PLAN.md', 'project-config.json'}:
                continue
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example / name, target)
        for name in GSAP_FILES:
            shutil.copyfile(example / 'runtime' / name, project / 'runtime' / name)
        config_path = project / 'project-config.json'
        config = cli.read_json(config_path)
        config['snapshot_dependencies'] = sorted(set(config['snapshot_dependencies']) |
                                                 set(cli.read_json(example / config_path.name)['snapshot_dependencies']))
        cli.write_json(config_path, config)
        self.invoke(*selector, 'plan', 'refresh')
        report = json.loads(self.invoke(*selector, 'plan', 'check'))
        self.assertEqual('diagnostic_only', report['status'])
        self.assertFalse([item for item in report['findings'] if re.search(r'voice|tts|alignment|cue|caption', item['kind'])],
                         report['findings'])
        registered = self.invoke(*selector, 'preview', 'register', '--purpose', 'plan')
        frozen = variant / 'previews' / registered / 'source-snapshot'
        self.assertEqual(self.three.read_bytes(), (frozen / THREE).read_bytes())
        closure = storage.snapshot_files(frozen)
        self.assertIn(THREE, closure)
        for name in GSAP_FILES:
            relative = f'runtime/{name}'
            self.assertIn(relative, closure)
            self.assertEqual((self.root / HOST_GSAP_DIST / name).read_bytes(), (frozen / relative).read_bytes())
        self.assertNotIn('<audio', (frozen / 'index.html').read_text(encoding='utf-8'))
