"""Design/material catalog, card format and non-CLI authoring helpers."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import designs
import lines


def write_card(root, identity, card):
    directory = Path(root) / identity
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'design.json').write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
    return directory


def write_asset(directory, identity, entry='main.js', body='window.__asset = 1;\n'):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'asset.json').write_text(json.dumps({
        'schema_version': 1, 'id': identity, 'version': 1, 'kind': 'module',
        'entry': entry, 'license': 'Apache-2.0'}, ensure_ascii=False) + '\n', encoding='utf-8')
    (directory / entry).write_text(body, encoding='utf-8')
    return directory


class CatalogRootTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / 'repo'
        self.builtin = self.repo / '.studio/designs'
        self.builtin.mkdir(parents=True)
        self.user = base / 'user'
        self.user.mkdir()
        self.config = {'design_root': str(self.user)}
        write_card(self.builtin, 'alpha', designs._skeleton('alpha', 'design'))

    def test_double_root_discovery_and_card_path(self):
        write_card(self.user, 'beta', designs._skeleton('beta', 'design'))
        found = designs.catalog(self.repo, self.config)
        self.assertEqual(['alpha', 'beta'], sorted(found))
        self.assertEqual(self.user / 'beta', designs.card_path('beta', self.repo, self.config))
        self.assertEqual(('alpha', 'beta'), designs.design_ids(self.repo, self.config))
        self.assertEqual(self.builtin / 'alpha', designs.card_path('alpha', self.repo, self.config))

    def test_work_root_environment_protects_live_work_directories(self):
        work = Path(self.temp.name) / 'work'
        with mock.patch.dict('os.environ', {'HYPERFRAMES_AI_WORK_ROOT': str(work)}):
            with self.assertRaisesRegex(designs.DesignError, 'asset-library'):
                designs.user_root(self.repo, {'design_root': str(work / 'works/active/cards')}, create=True)
        self.assertFalse((work / 'works').exists())

    def test_work_root_environment_supplies_default_card_root(self):
        work = Path(self.temp.name) / 'work'
        with mock.patch.dict('os.environ', {'HYPERFRAMES_AI_WORK_ROOT': str(work)}):
            self.assertEqual(work / 'asset-library/designs', designs.user_root(self.repo, {}, create=True))

    def test_conflicting_ids_are_refused_with_both_paths(self):
        write_card(self.user, 'alpha', designs._skeleton('alpha', 'design'))
        with self.assertRaisesRegex(designs.DesignError, 'Duplicate design id'):
            designs.catalog(self.repo, self.config)
        with self.assertRaisesRegex(designs.DesignError, 'Duplicate design id'):
            designs.card_path('alpha', self.repo, self.config)

    def test_default_user_root_from_work_root_and_missing_default(self):
        work = Path(self.temp.name) / 'work'
        config = {'work_root': str(work)}
        self.assertIsNone(designs.user_root(self.repo, config))
        self.assertEqual(['alpha'], sorted(designs.catalog(self.repo, config)))
        write_card(work / 'asset-library/designs', 'gamma', designs._skeleton('gamma', 'design'))
        self.assertEqual(work / 'asset-library/designs', designs.user_root(self.repo, config))
        self.assertIn('gamma', designs.catalog(self.repo, config))

    def test_design_root_requires_absolute_safe_location(self):
        with self.assertRaisesRegex(designs.DesignError, 'absolute path'):
            designs.user_root(self.repo, {'design_root': 'relative/cards'})
        with self.assertRaisesRegex(designs.DesignError, 'outside the harness'):
            designs.user_root(self.repo, {'design_root': str(self.repo / 'cards')})

    def test_missing_configured_root_is_not_an_error(self):
        config = {'design_root': str(Path(self.temp.name) / 'absent')}
        self.assertIsNone(designs.user_root(self.repo, config))
        self.assertEqual(['alpha'], sorted(designs.catalog(self.repo, config)))

    def test_traversal_identity_is_refused(self):
        with self.assertRaisesRegex(designs.DesignError, 'Invalid design identity'):
            designs.card_path('../alpha', self.repo, self.config)

    def test_design_ids_is_dynamic_not_a_hardcoded_tuple(self):
        with mock.patch.object(designs, 'CARD_DIR', self.builtin):
            self.assertEqual(('alpha',), tuple(designs.DESIGN_IDS))
            self.assertIn('alpha', designs.DESIGN_IDS)
            write_card(self.builtin, 'delta', designs._skeleton('delta', 'design'))
            self.assertEqual(('alpha', 'delta'), designs.design_ids())

    def test_symlinked_card_is_refused(self):
        (self.builtin / 'linked').symlink_to(self.builtin / 'alpha', target_is_directory=True)
        with self.assertRaisesRegex(designs.DesignError, 'Linked'):
            designs.catalog(self.repo, self.config)


class MaterialCardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / 'repo'
        self.builtin = self.repo / '.studio/designs'
        self.builtin.mkdir(parents=True)
        self.config = {}
        write_card(self.builtin, 'alpha', designs._skeleton('alpha', 'design'))
        write_card(self.builtin, 'mats', designs._skeleton('mats', 'material'))

    def test_material_cards_load_but_are_never_selectable(self):
        self.assertEqual(['alpha', 'mats'], sorted(designs.catalog(self.repo, self.config)))
        self.assertEqual(('alpha',), designs.design_ids(self.repo, self.config))
        self.assertEqual('material', designs.get('mats', self.repo, self.config)['type'])
        with self.assertRaisesRegex(designs.DesignError, 'material card'):
            designs.require('mats', self.repo, self.config)
        with self.assertRaisesRegex(designs.DesignError, 'material card'):
            designs.defaults('mats', self.repo, self.config)

    def test_lines_selection_excludes_material_cards(self):
        with mock.patch.object(designs, 'CARD_DIR', self.builtin):
            selected = lines.catalogue('lines')['lines']
            self.assertIn('alpha', selected)
            self.assertNotIn('mats', selected)
            self.assertEqual({'alpha'}, set(lines.designs_catalogue()))

    def test_material_card_requires_runtime_and_assets(self):
        write_card(self.builtin, 'broken', {'id': 'broken', 'version': 1, 'type': 'material'})
        with self.assertRaisesRegex(designs.DesignError, 'Invalid material card fields'):
            designs.catalog(self.repo, self.config)


class LegacySnapshotTest(unittest.TestCase):
    def test_legacy_card_without_type_still_resolves(self):
        legacy = designs.get('stage-full')
        for key in ('type', 'runtime', 'references', 'capabilities'):
            legacy.pop(key, None)
        legacy['mode'] = 'explainer'
        legacy['assets'] = {'scope': 'frozen-library-and-opus-heroes', 'opus_heroes': 2}
        result = designs.resolve('stage-full', card=legacy)
        self.assertEqual(True, result['values']['captions.enabled'])
        digest = lines.card_digest(legacy)
        state = {'line': {'id': 'stage-full', 'version': legacy['version']},
                 'design_snapshot': deepcopy(legacy), 'design_sha256': digest}
        with mock.patch.object(designs, 'catalog', side_effect=AssertionError('latest read')):
            self.assertEqual(legacy, lines.frozen(state))


class AuthoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.builtin = self.repo / '.studio/designs'
        self.builtin.mkdir(parents=True)
        self.user = self.base / 'user'
        self.user.mkdir()
        self.config = {'design_root': str(self.user)}
        write_card(self.repo / '.studio/designs', 'alpha', designs._skeleton('alpha', 'design'))

    def test_new_skeleton_and_validate_round_trip(self):
        directory = designs.new('fresh', root=self.repo, config=self.config)
        self.assertEqual(self.user / 'fresh', directory)
        self.assertTrue((directory / 'assets').is_dir())
        result = designs.validate('fresh', root=self.repo, config=self.config)
        self.assertTrue(result['ok'], result)

    def test_new_from_card_copies_and_renames(self):
        designs.new('copy', from_card='alpha', root=self.repo, config=self.config)
        card = designs.get('copy', self.repo, self.config)
        self.assertEqual('copy', card['id'])
        self.assertEqual('design', card['type'])
        self.assertTrue((self.user / 'copy' / 'design.json').is_file())

    def test_new_requires_a_configured_user_root(self):
        with self.assertRaisesRegex(designs.DesignError, 'No user design root'):
            designs.new('fresh', root=self.repo, config={})

    def test_builtin_card_is_read_only(self):
        with self.assertRaisesRegex(designs.DesignError, 'built-in card'):
            designs.localize('alpha', 'source/rig', root=self.repo, config=self.config)

    def test_localize_then_compare_and_source_diff(self):
        source = write_card(self.builtin, 'source', designs._skeleton('source', 'design'))
        write_asset(source / 'assets/rig', 'rig')
        owner_card = designs._skeleton('owner', 'design')
        owner_card['references'] = ['source/rig']
        owner = write_card(self.user, 'owner', owner_card)
        (owner / 'assets').mkdir()
        result = designs.localize('owner', 'source/rig', root=self.repo, config=self.config)
        self.assertEqual('source/rig', result['source'])
        self.assertTrue((owner / 'assets/rig/main.js').is_file())
        self.assertEqual([], json.loads((owner / 'design.json').read_text())['references'])
        borrowed = json.loads((owner / 'borrowed.json').read_text())
        self.assertEqual('source', borrowed['assets']['rig']['card'])
        comparison = designs.compare('owner', 'rig', root=self.repo, config=self.config)
        self.assertFalse(comparison['rig']['source_changed'])
        self.assertFalse(comparison['rig']['local_changed'])
        write_asset(source / 'assets/rig', 'rig', body='window.__asset = 2;\n')
        comparison = designs.compare('owner', root=self.repo, config=self.config)
        self.assertTrue(comparison['rig']['source_changed'])
        self.assertIn('main.js', comparison['rig']['files'])

    def test_localize_redirects_example_sources_to_owned_copy(self):
        source = write_card(self.builtin, 'source', designs._skeleton('source', 'design'))
        write_asset(source / 'assets/rig', 'rig')
        card = designs._skeleton('owner', 'design'); card['references'] = ['source/rig']
        owner = write_card(self.user, 'owner', card)
        manifest = owner / 'example-manifest.json'
        manifest.write_text(json.dumps({'files': [{'source': '.studio/designs/source/assets/rig/main.js'}]}))
        designs.localize('owner', 'source/rig', root=self.repo, config=self.config)
        self.assertEqual('assets/rig/main.js', json.loads(manifest.read_text())['files'][0]['source'])

    def test_localize_metadata_failure_preserves_reference_and_removes_copy(self):
        source = write_card(self.builtin, 'source', designs._skeleton('source', 'design'))
        write_asset(source / 'assets/rig', 'rig')
        card = designs._skeleton('owner', 'design'); card['references'] = ['source/rig']
        owner = write_card(self.user, 'owner', card)
        before = (owner / 'design.json').read_bytes()
        with mock.patch.object(designs, '_write_borrowed', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                designs.localize('owner', 'source/rig', root=self.repo, config=self.config)
        self.assertFalse((owner / 'assets/rig').exists())
        self.assertFalse((owner / 'borrowed.json').exists())
        self.assertEqual(before, (owner / 'design.json').read_bytes())

    def test_validate_reports_broken_reference_gsap_and_determinism(self):
        (self.repo / 'windows-npm.lock.json').write_text(json.dumps({
            'packages': {'node_modules/gsap': {'version': '3.14.2'}}}))
        card = designs._skeleton('problems', 'design')
        card['references'] = ['missing/thing']
        card['runtime'] = {'gsap': '^99.0', 'plugins': []}
        directory = write_card(self.user, 'problems', card)
        (directory / 'assets').mkdir()
        (directory / 'scene.js').write_text('gsap.to(x, {repeat: -1, x: Math.random()});\n')
        (directory / 'gsap.min.js').write_text('/* vendored copy */\n')
        result = designs.validate('problems', root=self.repo, config=self.config)
        errors = result['cards']['problems']['errors']
        warnings = result['cards']['problems']['warnings']
        self.assertFalse(result['ok'])
        self.assertTrue(any('not installed' in item for item in errors), errors)
        self.assertTrue(any('not satisfied by host' in item for item in errors), errors)
        self.assertTrue(any('GSAP file' in item for item in errors), errors)
        self.assertTrue(any('Math.random' in item for item in warnings), warnings)
        self.assertTrue(any('repeat: -1' in item for item in warnings), warnings)

    def test_shipped_cards_validate_clean(self):
        result = designs.validate()
        self.assertTrue(result['ok'], result)


if __name__ == '__main__':
    unittest.main()
