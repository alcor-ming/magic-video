import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import design_examples
import designs


def host_runtime(root):
    """A minimal host npm GSAP runtime, standing in for runtime/npm on Windows."""
    dist = Path(root) / 'runtime/npm/node_modules/gsap/dist'
    dist.mkdir(parents=True)
    for name in ('gsap.min.js', 'MotionPathPlugin.min.js'):
        (dist / name).write_text('/* ' + name + ' host fixture */\n')
    return Path(root)


class ExampleBuildTest(unittest.TestCase):
    def test_retired_empty_directory_does_not_shadow_user_card(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'tool'; user = Path(temp) / 'cards'
            (root / '.studio/designs/custom').mkdir(parents=True)
            (user / 'custom').mkdir(parents=True)
            (user / 'custom/design.json').write_text('{}')
            self.assertEqual(user / 'custom', design_examples.card_dir('custom', root, {'design_root':str(user)}))

    def test_cards_declare_host_runtime_and_load_it_before_scene(self):
        for identity in designs.design_ids():
            with self.subTest(design=identity):
                card = designs.get(identity)
                self.assertTrue(card['runtime']['gsap'])
                self.assertIn('MotionPathPlugin', card['runtime']['plugins'])
                value = design_examples.manifest(identity)
                files = {item['target']: item for item in value['files']}
                sources = {item['source'] for item in value['files']}
                self.assertFalse(any('designs/shared/' in source for source in sources))
                self.assertTrue(any(source.endswith('assets/stage-rig/stage-rig.js') for source in sources))
                html = (design_examples.REPO / files['index.html']['source']).read_text()
                self.assertLess(html.index('src="runtime/gsap.min.js"'),
                                html.index('src="runtime/MotionPathPlugin.min.js"'))
                self.assertLess(html.index('src="runtime/MotionPathPlugin.min.js"'),
                                html.index('src="scene.js"'))

    def test_built_examples_inject_host_runtime_and_authored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = host_runtime(Path(tmp) / 'host')
            for identity in designs.design_ids():
                with self.subTest(design=identity):
                    project = design_examples.build(identity, Path(tmp) / identity, runtime_root=runtime)
                    files = {path.relative_to(project).as_posix()
                             for path in project.rglob('*') if path.is_file()}
                    self.assertTrue({'index.html', 'scene.js', 'style.css', 'DESIGN.md',
                                     'runtime/gsap.min.js', 'runtime/MotionPathPlugin.min.js',
                                     'runtime/stage-rig.js'} <= files)
                    self.assertTrue(any(name.startswith('media/') for name in files))
                    receipt = json.loads((project / 'resource-manifest.json').read_text())
                    injected = {item['target'] for item in receipt['runtime']}
                    self.assertEqual({'runtime/gsap.min.js', 'runtime/MotionPathPlugin.min.js'}, injected)
                    self.assertTrue(all(item['package'] == 'gsap' for item in receipt['runtime']))
                    # GSAP is host-provided; no authored card entry ships it.
                    self.assertFalse(any('gsap' in item['source'].casefold() for item in receipt['files']))
                    design_examples.build(identity, project, runtime_root=runtime)

    def test_declared_three_is_injected_from_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = host_runtime(Path(tmp) / 'host')
            three = runtime / 'runtime/npm/node_modules/three/build/three.min.js'
            three.parent.mkdir(parents=True)
            three.write_text('/* three host fixture */\n')
            original = designs.get
            designs.get = lambda identity, **kwargs: {'runtime': {'gsap': '^3.14', 'three': '0.160.0'}}
            try:
                entries = design_examples.runtime_manifest('stage-full', runtime_root=runtime)
                (three).unlink()
                with self.assertRaisesRegex(ValueError, 'three.min.js'):
                    design_examples.runtime_manifest('stage-full', runtime_root=runtime)
            finally:
                designs.get = original
            targets = {entry['target']: entry for entry, _source in entries}
            self.assertEqual({'runtime/gsap.min.js', 'runtime/three.min.js'}, set(targets))
            self.assertEqual('three', targets['runtime/three.min.js']['package'])

    def test_three_runtime_declaration_is_validated(self):
        designs._validate_runtime('card', {'gsap': '^3.14', 'three': '0.160.0'})
        with self.assertRaisesRegex(designs.DesignError, 'three'):
            designs._validate_runtime('card', {'three': ' '})
        self.assertTrue(designs._is_three_file('three.min.js'))
        self.assertFalse(designs._is_three_file('three-scene.js'))

    def test_missing_host_runtime_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Host runtime'):
                design_examples.build('stage-full', Path(tmp) / 'missing', runtime_root=Path(tmp) / 'absent')

    def test_exact_resources_idempotence_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / '.studio/designs/example'
            source.mkdir(parents=True)
            files = []
            for name in ('index.html', 'style.css', 'scene.js'):
                (source / name).write_text(name)
                files.append(dict(source=(source / name).relative_to(root).as_posix(),
                                  target=name, sha256=hashlib.sha256(name.encode()).hexdigest(),
                                  origin='Authored test fixture', version='1', license='Apache-2.0',
                                  purpose='Example source', packages=['public', 'personal']))
            data = dict(design='example', version=1, files=files)
            (source / 'example-manifest.json').write_text(json.dumps(data))
            target = root / 'built'
            self.assertEqual(target, design_examples.build('example', target, repo=root))
            self.assertEqual(target, design_examples.build('example', target, repo=root))
            (target / 'scene.js').write_text('user edit')
            with self.assertRaisesRegex(ValueError, 'changed'):
                design_examples.build('example', target, repo=root)
            self.assertEqual('user edit', (target / 'scene.js').read_text())
            data['files'][0]['source'] = '../../private'
            (source / 'example-manifest.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'escaped'):
                design_examples.build('example', root / 'other', repo=root)
            self.assertFalse((root / 'other').exists())


if __name__ == "__main__":
    unittest.main()
