"""Card asset replacement in an isolated project."""
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
import asset_store
from asset_contract import freeze_source
import component_harness as component
from work_requests import RequestError


class ComponentUpgradeTest(unittest.TestCase):
    card_ref = 'fixture-card/marker'
    default_binding = f'component-bindings/S01.{card_ref}.json'
    alternate_binding = 'component-bindings/alternate.json'

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.project = self.root / 'project'
        self.project.mkdir()
        self.lock = self.project / 'COMPONENT_LOCK.json'
        self.index = self.project / 'index.html'

    def package(self, version, *, card=True):
        source = self.root / f'source-v{version}'
        source.mkdir()
        (source / 'asset.json').write_text(json.dumps({'schema_version': 1, 'id': 'marker',
            'version': version, 'kind': 'module', 'entry': 'main.js'}), encoding='utf-8')
        (source / 'main.js').write_text(f'window.marker = {version};', encoding='utf-8')
        frozen = self.root / f'package-v{version}'
        release = freeze_source(source, frozen, card_ref=self.card_ref if card else None)
        return frozen, release

    def binding(self, version, *, role='subject', card=True):
        return {'schema_version': 3, 'component_ref': f'{self.card_ref if card else "marker"}@v{version}',
                'scene': 'S01', 'usage': {'role': role, 'required': True, 'fit': 'cover', 'focal_point': [0.2, 0.8]}}

    def vendor(self, version):
        return f'vendor/components/{self.card_ref}/v{version}'

    def mount(self, version):
        self.index.write_text(f'<script src="{self.vendor(version)}/main.js"></script>', encoding='utf-8')

    def install(self, version, *, role='subject', path=None):
        return component.install_component(self.package(version)[0], self.project, self.binding(version, role=role),
                                           binding_path=path)

    def components(self):
        return json.loads(self.lock.read_text(encoding='utf-8'))['components']

    def assert_installation(self, version, release, bindings):
        record, = self.components()
        self.assertEqual(f'{self.card_ref}@v{version}', record['component_ref'])
        self.assertEqual(sorted(bindings), [item['path'] for item in record['bindings']])
        for item in record['bindings']:
            path = self.project / item['path']
            self.assertEqual(bindings[item['path']], json.loads(path.read_text(encoding='utf-8')))
            self.assertEqual(component.file_sha256(path), item['sha256'])
        mounts = [{'entry': f'{self.vendor(version)}/main.js'}]
        self.assertEqual(mounts, component.validate_component_mounts(self.project, release, record)['mounts'])
        self.assertEqual(mounts, component.verify_installation(self.project)['components'][0]['mounts'])

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes() if p.is_file() else None
                for p in self.project.rglob('*')}

    def test_default_binding_upgrade_reports_index_and_scene(self):
        self.assertNotIn('replaced', self.install(1))
        self.mount(1)
        scene = self.project / 'scenes/S01.html'
        scene.parent.mkdir()
        scene.write_text(f'<script src="../{self.vendor(1)}/main.js?cache=1"></script>', encoding='utf-8')
        old_index, old_scene = self.index.read_bytes(), scene.read_bytes()
        frozen, release = self.package(2)
        request = self.binding(2, role='auxiliary')
        result = component.install_component(frozen, self.project, request)
        self.assertEqual([{'component_ref': f'{self.card_ref}@v1', 'vendor_path': self.vendor(1),
                           'bindings': [self.default_binding], 'referenced_by': ['index.html', 'scenes/S01.html']}],
                         result['replaced'])
        self.assertEqual(old_index, self.index.read_bytes())
        self.assertEqual(old_scene, scene.read_bytes())
        self.assertFalse((self.project / self.vendor(1)).exists())
        self.mount(2)
        scene.write_text(old_scene.decode().replace('/v1/', '/v2/'), encoding='utf-8')
        self.assert_installation(2, release, {self.default_binding: request})

    def add_preexisting_version(self, frozen, version, request, path):
        # Assemble the lock and vendor layout produced by the previous installer.
        other_project = self.root / f'other-project-v{version}'
        other_project.mkdir()
        record = component.install_component(frozen, other_project, request, binding_path=path)['component']
        shutil.copytree(other_project / record['vendor_path'], self.project / record['vendor_path'])
        shutil.copyfile(other_project / path, self.project / path)
        lock = json.loads(self.lock.read_text(encoding='utf-8'))
        lock['components'].append(record)
        self.lock.write_text(json.dumps(lock), encoding='utf-8')

    def test_reinstall_repairs_preexisting_two_versions(self):
        old = self.install(1, role='evidence')['component']
        frozen, release = self.package(2)
        request = self.binding(2, role='auxiliary')
        self.add_preexisting_version(frozen, 2, request, self.alternate_binding)
        self.mount(2)
        with self.assertRaisesRegex(component.ComponentError, 'not referenced'):
            component.verify_installation(self.project)
        result = component.install_component(frozen, self.project, request, binding_path=self.alternate_binding)
        self.assertEqual([{'component_ref': old['component_ref'], 'vendor_path': old['vendor_path'],
                           'bindings': [self.default_binding], 'referenced_by': []}], result['replaced'])
        self.assertFalse((self.project / self.vendor(1)).exists())
        self.assert_installation(2, release, {self.default_binding: self.binding(2, role='evidence'),
                                             self.alternate_binding: request})

    def test_replaces_multiple_old_versions(self):
        self.install(1, role='evidence')
        self.add_preexisting_version(self.package(2)[0], 2, self.binding(2, role='auxiliary'), self.alternate_binding)
        self.mount(1)
        frozen, release = self.package(3)
        request_path = 'component-bindings/new.json'
        request = self.binding(3)
        result = component.install_component(frozen, self.project, request, binding_path=request_path)
        self.assertEqual([f'{self.card_ref}@v1', f'{self.card_ref}@v2'],
                         [item['component_ref'] for item in result['replaced']])
        for version in (1, 2):
            self.assertFalse((self.project / self.vendor(version)).exists())
        self.mount(3)
        self.assert_installation(3, release, {self.default_binding: self.binding(3, role='evidence'),
                                             self.alternate_binding: self.binding(3, role='auxiliary'),
                                             request_path: request})

    def test_downgrade(self):
        self.install(2)
        self.mount(2)
        frozen, release = self.package(1)
        result = component.install_component(frozen, self.project, self.binding(1))
        self.assertEqual([f'{self.card_ref}@v2'], [item['component_ref'] for item in result['replaced']])
        self.assertFalse((self.project / self.vendor(2)).exists())
        self.mount(1)
        self.assert_installation(1, release, {self.default_binding: self.binding(1)})

    def test_invalid_migration_leaves_project_untouched(self):
        self.install(1, path=self.alternate_binding)
        self.mount(1)
        invalid = self.binding(1)
        invalid['usage']['unsupported'] = 1
        path = self.project / self.alternate_binding
        path.write_text(json.dumps(invalid), encoding='utf-8')
        lock = json.loads(self.lock.read_text(encoding='utf-8'))
        lock['components'][0]['bindings'][0]['sha256'] = component.file_sha256(path)
        self.lock.write_text(json.dumps(lock), encoding='utf-8')
        before = self.snapshot()
        with self.assertRaisesRegex(component.ComponentError, 'Unsupported asset usage fields'):
            self.install(2)
        self.assertEqual(before, self.snapshot())

    def test_publish_failure_restores_vendor_bindings_and_lock(self):
        self.install(1)
        self.mount(1)
        frozen, _ = self.package(2)
        before = self.snapshot()
        replace = component.os.replace

        def fail_lock_publish(source, target):
            if Path(target) == self.lock and Path(source).name == self.lock.name:
                raise OSError('fixture lock publish failure')
            return replace(source, target)

        with patch.object(component.os, 'replace', side_effect=fail_lock_publish):
            with self.assertRaisesRegex(OSError, 'fixture lock publish failure'):
                component.install_component(frozen, self.project, self.binding(2),
                                            binding_path='new/nested/binding.json')
        self.assertEqual(before, self.snapshot())

    def test_vendor_staging_failure_removes_partial_copy(self):
        self.install(1)
        frozen, _ = self.package(2)
        before = self.snapshot()

        def fail_copy(source, target):
            target.mkdir()
            (target / 'partial').write_bytes(b'partial')
            raise OSError('fixture staging failure')

        with patch.object(component.shutil, 'copytree', side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, 'fixture staging failure'):
                component.install_component(frozen, self.project, self.binding(2))
        self.assertEqual(before, self.snapshot())

    def test_unsafe_old_vendor_is_rejected(self):
        self.install(1)
        old_vendor = self.project / self.vendor(1)
        outside = self.root / 'outside'
        old_vendor.rename(outside)
        old_vendor.symlink_to(outside, target_is_directory=True)
        before = self.snapshot()
        with self.assertRaisesRegex(RequestError, 'Linked path'):
            self.install(2)
        self.assertEqual(before, self.snapshot())
        self.assertTrue((outside / 'main.js').is_file())

    def test_accepted_legacy_versions_still_coexist(self):
        harness, store = self.root / 'harness', self.root / 'store'
        harness.mkdir()
        shutil.copyfile(REPO / 'windows-runtime.lock.json', harness / 'windows-runtime.lock.json')
        (harness / '.release.json').write_text('{"target": "windows-x64", "channel": "local"}', encoding='utf-8')
        # The fixture models a Windows package on any test host, so acceptance reads this harness lock.
        environment = patch.dict(os.environ, {'HYPERFRAMES_AI_ROOT': str(harness)})
        environment.start()
        self.addCleanup(environment.stop)
        entries = []
        for version in (1, 2):
            package, release = self.package(version, card=False)
            ref = release['component_ref']
            asset_store.import_component(store, package)
            acceptance = asset_store.accept_component(store, ref, release['package_sha256'], 'synthetic fixture',
                                                      runtime_root=harness)
            result = component.install_component(package, self.project, self.binding(version, card=False),
                                                 binding_path=f'component-bindings/legacy-v{version}.json',
                                                 acceptance=acceptance)
            self.assertEqual({'component', 'lock_path'}, set(result))
            self.assertNotIn('card_ref', result['component'])
            entries.append(f'<script src="{result["component"]["vendor_path"]}/main.js"></script>')
        self.index.write_text(''.join(entries), encoding='utf-8')
        self.assertEqual(['marker@v1', 'marker@v2'], [item['component_ref'] for item in self.components()])
        self.assertEqual(2, len(component.verify_installation(self.project)['components']))


if __name__ == '__main__':
    unittest.main()
