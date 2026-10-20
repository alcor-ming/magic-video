import json
from pathlib import Path
from unittest.mock import patch
import unittest
import test_design_choice as choice
cli = choice.cli


class DesignMigrationTest(unittest.TestCase):
    setUp = choice.ChoiceTest.setUp
    invoke = choice.ChoiceTest.invoke
    new = choice.ChoiceTest.new

    def test_exact_mapping_preserves_content_and_atomic_failure(self):
        identity = self.new('legacy', '--no-account', '--design', 'stage-full', '--variant-id', 'alternate')
        work, _ = cli.locate_work(self.root, identity)
        variant = work / 'variants/alternate'
        state = cli.read_json(variant / 'variant.yaml')
        state.update(design='explainer', mode='explainer', line={'id': 'explainer', 'version': 1})
        for key in ('design_snapshot', 'design_sha256', 'design_sources', 'design_live'):
            state.pop(key, None)
        cli.write_variant(variant, state)
        before = {p.relative_to(work).as_posix(): p.read_bytes() for p in work.rglob('*') if p.is_file()}
        recipe = self.root / 'migration-overrides.json'
        recipe.write_text('{}')
        args = ('--work', identity, '--variant', 'alternate', 'migrate', 'design',
                '--design', 'stage-light', '--design-version', str(cli.designs.get('stage-light')['version']), '--no-account', '--overrides', str(recipe),
                '--source-sha256', cli.file_sha256(variant / 'variant.yaml'))
        self.assertEqual('preview', json.loads(self.invoke(*args))['status'])
        with patch.object(cli, 'write_variant', side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError):
                self.invoke(*args, '--apply')
        self.assertEqual(before['variants/alternate/variant.yaml'], (variant / 'variant.yaml').read_bytes())
        self.invoke(*args, '--apply')
        migrated = cli.read_json(variant / 'variant.yaml')
        self.assertEqual('explainer', migrated['design_migration']['original'])
        self.assertEqual('stage-light', migrated['design'])
        self.assertIn('ratio', migrated['design_migration']['unknown_sources'])
        self.assertNotEqual('variant', migrated['design_sources'].get('ratio'))
        for name, content in before.items():
            if name != 'variants/alternate/variant.yaml':
                self.assertEqual(content, (work / name).read_bytes(), name)

    def test_remotion_reports_unfinished_and_retirement_keeps_bytes(self):
        identity = self.new('old render', '--no-account', '--design', 'stage-full')
        work, _ = cli.locate_work(self.root, identity)
        variant = work / 'variants/variant1'
        package = variant / 'project/package.json'
        package.write_text(json.dumps({'dependencies': {'remotion': '4.0.0'}}))
        before = (variant / 'variant.yaml').read_bytes()
        result = json.loads(self.invoke('--work', identity, '--variant', 'variant1', 'migrate', 'design',
                                        '--design', 'stage-full', '--design-version',
                                        str(cli.designs.get('stage-full')['version']), '--no-account'))
        self.assertEqual('needs-native-adaptation', result['status'])
        self.assertEqual(before, (variant / 'variant.yaml').read_bytes())
        self.invoke('--work', identity, '--variant', 'variant1', 'migrate', 'retire', '--note', 'Preserve history',
                    '--source-sha256', cli.file_sha256(variant / 'variant.yaml'), '--apply')
        self.assertTrue(package.is_file())
        self.assertIn('retired', self.invoke('--work', identity, '--variant', 'variant1',
                                            'preview', 'register', code=2))
        retired = (variant / 'variant.yaml').read_bytes()
        self.assertIn('retired', self.invoke('--variant', 'variant1', 'reopen', identity, code=2))
        self.assertEqual(retired, (variant / 'variant.yaml').read_bytes())

    def test_retirement_preserves_pending_final_recovery(self):
        identity = self.new('pending final', '--no-account', '--design', 'stage-full')
        work, _ = cli.locate_work(self.root, identity)
        variant = work / 'variants/variant1'
        before = (variant / 'variant.yaml').read_bytes()
        for name, value in (('final-promotion/prepared.json', {}), ('finalize.json', {'state': 'promoted'})):
            with self.subTest(name=name):
                pending = variant / '.runtime' / name
                pending.parent.mkdir(parents=True, exist_ok=True)
                pending.write_text(json.dumps(value))
                self.assertIn('Final recovery pending', self.invoke('--work', identity, '--variant', 'variant1',
                    'migrate', 'retire', '--note', 'Preserve history', '--apply',
                    '--source-sha256', cli.file_sha256(variant / 'variant.yaml'), code=2))
                self.assertEqual(before, (variant / 'variant.yaml').read_bytes())
                self.assertTrue(pending.is_file())
                pending.unlink()


if __name__ == '__main__':
    unittest.main()
