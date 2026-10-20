"""Capabilities cross the card, appearance and diagnostic boundaries."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_appearance_resolver as fixtures
import appearance
import designs
import lines
import visual_diagnostics


class CapabilitiesTest(unittest.TestCase):
    setUp = fixtures.AppearanceResolverTest.setUp
    ref = fixtures.AppearanceResolverTest.ref

    def test_card_without_mode_or_subjects_when_rolls_disabled(self):
        card = designs._skeleton('free', 'design')
        card['capabilities']['rolls'] = False
        del card['subjects']
        self.assertNotIn('mode', designs._validate_card('free', card, strict=True))
        card['capabilities']['rolls'] = True
        with self.assertRaisesRegex(designs.DesignError, 'subjects'):
            designs._validate_card('free', card, strict=True)

    def test_bad_capabilities_are_rejected(self):
        for key, value in [('rolls', 1), ('layers', {'required': ['stage'], 'optional': ['stage']}),
                           ('checks', ['not-a-check']), ('research_template', '../outside'),
                           ('bindings', {'theme': 'optional'})]:
            caps = designs.legacy_capabilities('explainer')
            caps[key] = value
            with self.subTest(key=key), self.assertRaises(designs.DesignError):
                designs.validate_capabilities(caps)

    def test_new_lock_freezes_capabilities_and_validates_digest(self):
        caps = designs.legacy_capabilities('explainer')
        lock = appearance.resolve(self.root, self.account, {'capabilities': caps, 'captions': False})
        self.assertNotIn('mode', lock)
        self.assertEqual(caps, lock['capabilities'])
        self.assertFalse(lock['selection']['captions'])
        appearance._check_lock(lock)
        lock['capabilities']['rolls'] = False
        with self.assertRaisesRegex(appearance.AppearanceError, 'digest'):
            appearance._check_lock(lock)

    def test_binding_none_suppresses_inheritance_but_accepts_explicit_assets(self):
        caps = designs.legacy_capabilities('showcase')
        lock = appearance.resolve(self.root, self.account, {'capabilities': caps})
        self.assertIsNone(lock['selection']['theme'])
        self.assertIsNone(lock['selection']['background'])
        self.assertTrue(all(value is None for value in lock['selection']['motion'].values()))
        explicit = appearance.resolve(self.root, self.account,
                                      {'capabilities': caps, 'theme': self.ref('theme')})
        self.assertEqual(self.ref('theme'), explicit['selection']['theme'])

    def test_required_motion_accepts_one_slot_and_rejects_empty(self):
        caps = designs.legacy_capabilities('explainer')
        caps['bindings']['motion'] = 'required'
        lock = appearance.resolve(self.root, self.account, {'capabilities': caps}, legacy_motion=self.legacy_motion)
        appearance._check_lock(lock)
        with self.assertRaisesRegex(appearance.AppearanceError, 'at least one'):
            appearance.resolve(self.root, self.account,
                {'capabilities': caps, 'motion': dict.fromkeys(appearance.SLOTS)})
        lock['selection']['motion'] = dict.fromkeys(appearance.SLOTS)
        lock['sha256'] = appearance.digest({k: v for k, v in lock.items() if k != 'sha256'})
        with self.assertRaisesRegex(appearance.AppearanceError, 'at least one'):
            appearance._check_lock(lock)

    def test_old_modes_map_without_mutating_records(self):
        for mode in designs.MODES:
            with self.subTest(mode=mode):
                args = {'mode': mode}
                if mode == 'showcase':
                    args['submodule'] = 'pdoom'
                lock = appearance.resolve(self.root, self.account, args,
                                         legacy_motion=None if mode == 'showcase' else self.legacy_motion)
                fixtures_path = Path(__file__).parent / 'fixtures/capabilities/legacy-locks.json'
                baseline = json.loads(fixtures_path.read_text())['locks'][mode]
                # 夹具账号当年带四槽 Motion，现改由 legacy_motion 带入：只有账号摘要与整锁摘要不同。
                strip = lambda value: {**value, 'sha256': None, 'account': {**value['account'], 'sha256': None}}
                self.assertEqual(strip(baseline), strip(lock))
                before = json.dumps(lock, sort_keys=True)
                caps = designs.capabilities(lock)
                self.assertTrue(caps['rolls'])
                self.assertEqual([] if mode == 'showcase' else list(designs.LAYERS), caps['layers']['required'])
                appearance._check_lock(lock)
                self.assertEqual(before, json.dumps(lock, sort_keys=True))
                self.assertNotIn('capabilities', lock)

    def test_layers_only_require_declared_hosts(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'index.html').write_text('<div data-hf-layer="stage"></div>')
        caps = designs.legacy_capabilities('explainer')
        caps['layers'] = {'required': ['stage'], 'optional': ['text']}
        with patch('explainer.installed_assets', return_value={}):
            report = visual_diagnostics.explainer_diagnostics(project, ['index.html'],
                {'capabilities': caps, 'selection': {'captions': False}})
        self.assertFalse(report['findings'], report)

    def test_legacy_math_rap_is_retired_and_runs_no_math_check(self):
        state = {'mode': 'explainer', 'series_binding': {'spec': 'math-rap'}}
        self.assertTrue(lines.retired_math(state))
        self.assertFalse(lines.has_check(state, 'math'))
        self.assertNotIn('math', designs.CHECKS)

    def test_rolls_false_does_not_install_ab_runtime(self):
        caps = designs.legacy_capabilities('showcase')
        caps['rolls'] = False
        with patch('asset_store.resolve_asset_closure', return_value=[]):
            lock = appearance.resolve(self.root, {}, {'capabilities': caps})
            project = self.root / 'project'
            project.mkdir()
            appearance.materialize(self.root, project, lock)
        self.assertTrue((project / 'runtime/cues.js').is_file())
        self.assertTrue((project / 'runtime/motion.js').is_file())
        self.assertIn('runtime/motion.js', json.loads((project / 'project-config.json').read_text())['snapshot_dependencies'])
        self.assertFalse((project / 'runtime/rolls.js').exists())
        self.assertFalse((project / 'runtime/broll.js').exists())
        appearance.verify(project, lock)

    def _create_mode_free_work(self, bindings):
        import shutil
        import test_work_cli
        cli = test_work_cli.WORK_CLI
        shutil.copytree(Path(designs.__file__).parent / 'templates', self.root / '.studio/templates')
        card = designs._skeleton('independent', 'design')
        card['capabilities'] = designs.legacy_capabilities('showcase')
        card['capabilities']['rolls'] = False
        card['capabilities']['checks'] = []
        card['capabilities']['bindings'] = dict.fromkeys(('theme', 'background', 'motion'), bindings)
        card['capabilities']['research_template'] = 'MATH_RESEARCH.template.md'
        del card['subjects']
        directory = self.root / 'cards/independent'
        directory.mkdir(parents=True)
        (directory / 'MATH_RESEARCH.template.md').write_text('---\n{"revision":1,"status":"draft"}\n---\n# Synthetic alternative research\n')
        (directory / 'design.json').write_text(json.dumps(card))
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(designs, 'CARD_DIR', directory.parent), \
                patch('asset_store.resolve_asset_closure', return_value=[]), \
                redirect_stdout(output), redirect_stderr(errors):
            status = cli.main(['new', 'Synthetic', '--workflow', 'hyperframes_video', '--purpose', 'test',
                               '--no-account', '--design', 'independent'], root=self.root)
        self.assertEqual(0, status, errors.getvalue())
        work, _ = cli.locate_work(self.root, output.getvalue().strip())
        variant = work / 'variants/variant1'
        state = cli.read_json(variant / 'variant.yaml')
        self.assertIsNone(state.get('mode'))
        self.assertEqual(card['capabilities'], state['appearance_lock']['capabilities'])
        self.assertFalse((variant / 'project/runtime/rolls.js').exists())
        self.assertFalse((variant / 'project/runtime/broll.js').exists())
        self.assertTrue((variant / 'project/runtime/cues.js').is_file())
        with patch.object(designs, 'CARD_DIR', directory.parent), \
                patch('showcase_tools.stage', return_value={'fixture': True}) as stage, \
                redirect_stdout(io.StringIO()), redirect_stderr(errors):
            status = cli.main(['--work', work.name, '--variant', 'variant1', 'showcase', 'stage',
                               '--output', 'assets/stage'], root=self.root)
        self.assertEqual(0, status, errors.getvalue())
        stage.assert_called_once_with(variant / 'project/assets/stage', overwrite=False)
        with patch.object(designs, 'CARD_DIR', directory.parent):
            other = cli.create_video_variant(self.root, work, 'variant2', template='pure_hyperframes',
                profile=None, ratio='16:9', subject_position=None, design='independent')
        expected = cli.document_body(directory / 'MATH_RESEARCH.template.md')
        self.assertEqual(expected, cli.document_body(other / 'RESEARCH.md'))

    def test_mode_free_card_creates_work_with_selected_runtime(self):
        self._create_mode_free_work('none')

    def test_optional_card_without_assets_still_installs_runtime(self):
        self._create_mode_free_work('optional')

    def test_capabilities_rebind_ignores_legacy_account_mode(self):
        from types import SimpleNamespace
        import appearance_rebind
        caps = designs.legacy_capabilities('showcase')
        with patch('asset_store.resolve_asset_closure', return_value=[]):
            lock = appearance.resolve(self.root, {}, {'capabilities': caps})
            state = {'capabilities': caps, 'appearance_lock': lock, 'captions': False,
                     'account_settings': {'mode': 'showcase'}}
            api = SimpleNamespace(appearance_options=lambda *_: {})
            args = SimpleNamespace(account=None, captions=None, apply=False, upgrade_runtime=False)
            report = appearance_rebind.rebind(self.root, self.root, self.root / 'variant', state, args, api)
        self.assertEqual('preview', report['status'])
