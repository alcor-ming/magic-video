"""Real lifecycle functions with isolated files; mock only Studio transport/sampling."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from PIL import Image
import test_visual_plan as legacy_fixture
from test_work_cli import WORK_CLI as cli
from test_v370 import plan
import critic
import lines


class V370CliTest(unittest.TestCase):
    run_cli = legacy_fixture.VisualPlanTest.run_cli
    update = legacy_fixture.VisualPlanTest.update

    def setUp(self):
        legacy_fixture.VisualPlanTest.setUp(self)
        state = cli.read_json(self.variant / 'variant.yaml')
        # This suite deliberately constructs the legacy line-only state.
        for key in ('design_live', 'design', 'design_snapshot', 'design_sha256', 'design_values', 'design_sources'):
            state.pop(key, None)
        state['line'] = lines.bind({'mode': 'explainer'})
        state['settings'] = {'direction_approval': False, 'critic.provider': 'off'}
        cli.write_variant(self.variant, state)
        metadata = {**cli.plan_metadata(self.variant, state), 'status': 'draft'}
        self.plan_path = self.variant / 'ANIMATION_PLAN.md'
        self.plan_path.write_text('---\n' + json.dumps(metadata) + '\n---\n' + plan().split('---\n', 2)[2])
        self.cli_path = self.root / 'cli.js'
        self.cli_path.write_text('// isolated transport identity')
        self.scope = ('--work', self.variant.parent.parent.name, '--variant', 'main')
        def start(executable, project, port, **kwargs):
            return {'port': 3101, 'studioUrl': f'http://127.0.0.1:3101/#project/{project.name}', 'pid': 123}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(cli.studio_preview, 'start', side_effect=start).start()
        mock.patch.object(cli.studio_preview, 'context', return_value={}).start()

    def call(self, *args):
        with redirect_stdout(io.StringIO()) as output:
            self.run_cli(*self.scope, *args, '--json')
        return output.getvalue().strip()

    def test_creator_recovers_same_object_from_cli_evidence(self):
        import os
        before_cwd = Path.cwd()
        self.addCleanup(os.chdir, before_cwd)
        os.chdir(self.root)
        with redirect_stdout(io.StringIO()) as output:
            self.run_cli('current')
        located = json.loads(output.getvalue())
        self.assertEqual(self.scope[1], located['work'])
        before = json.loads(self.call('status'))
        self.call('settings', 'set', 'critic.model', 'text-only')
        opened = json.loads(self.call('preview', 'open', 'current', '--hyperframes-cli', str(self.cli_path), '--no-open'))
        self.assertEqual('current', opened['target'])
        with mock.patch.object(cli.visual_diagnostics, 'probe', side_effect=self.sampled):
            evidence = json.loads(self.call('critic', 'round', '--hyperframes-cli', str(self.cli_path), '--browser', '/usr/bin/google-chrome'))
        self.assertEqual('unverified', evidence['visual_review'])
        self.assertTrue((Path(evidence['package']) / 'contact-sheet.png').is_file())
        # A fresh invocation recovers from disk; a lost reply is not a reason to replay new.
        self.scope = ('--work', located['work'], '--variant', located['variant'])
        recovered = json.loads(self.call('status'))
        self.assertEqual(before['path'], recovered['path'])
        self.assertEqual('text-only', recovered['variant']['settings']['critic.model'])
        with redirect_stdout(io.StringIO()) as output:
            self.run_cli('list', '--json')
        self.assertEqual(1, len(json.loads(output.getvalue())))
        self.assertIsNone(recovered['variant']['accepted_preview'])

    def test_settings_cli_precedence_and_creation_binding(self):
        self.assertEqual({'id': 'explainer', 'version': 1}, cli.read_json(self.variant / 'variant.yaml')['line'])
        self.call('settings', 'set', '--layer', 'user', 'direction_approval', 'true')
        self.call('settings', 'set', 'direction_approval', 'false')
        values = json.loads(self.call('settings', 'show'))['values']
        self.assertEqual({'value':False, 'source':'variant'}, values['direction_approval'])
        self.call('settings', 'unset', 'direction_approval')
        self.assertEqual('user', json.loads(self.call('settings', 'show'))['values']['direction_approval']['source'])
        for key, value in [('direction_approval', '1'), ('unknown','true'), ('critic.model','   ')]:
            with self.assertRaises(cli.HarnessError):
                self.call('settings', 'set', key, value)

    def test_old_provider_does_not_block_unrelated_settings_edit(self):
        state = cli.read_json(self.variant / 'variant.yaml')
        state['settings']['critic.provider'] = 'codex-subagent'
        cli.write_variant(self.variant, state)
        self.call('settings', 'set', 'critic.max_rounds', '2')
        self.assertEqual('codex-subagent', cli.read_json(self.variant / 'variant.yaml')['settings']['critic.provider'])
        with self.assertRaises(cli.HarnessError):
            self.call('settings', 'set', 'critic.provider', 'codex-subagent')
        self.call('settings', 'set', 'critic.provider', 'external')

    def test_direction_toggle_accepts_only_exact_draft_and_plan(self):
        draft = self.call('preview', 'register')
        preview = self.variant / 'previews' / draft
        frozen = (preview / 'ANIMATION_PLAN.md').read_bytes()
        self.call('preview', 'open', draft, '--hyperframes-cli', str(self.cli_path), '--no-open')
        self.call('settings', 'set', 'direction_approval', 'true')
        with self.assertRaisesRegex(cli.HarnessError, 'not approved'):
            self.call('preview', 'accept', draft)
        self.call('settings', 'set', 'direction_approval', 'false')
        content = self.plan_path.read_bytes()
        self.plan_path.write_bytes(content + b'changed direction')
        with self.assertRaisesRegex(cli.HarnessError, 'inputs changed'):
            self.call('preview', 'accept', draft)
        self.plan_path.write_bytes(content)
        self.call('preview', 'accept', draft)
        state = cli.read_json(self.variant / 'variant.yaml')
        self.assertFalse(state['draft_acceptance']['direction_approval'])
        self.assertEqual('approved', cli.read_frontmatter(self.plan_path)['status'])
        self.assertEqual(frozen, (preview / 'ANIMATION_PLAN.md').read_bytes())
        cli.assert_preview_ready(self.variant, state)
        self.assertFalse(list(self.variant.rglob('*.mp4')))
        self.assertFalse(list(self.variant.rglob('*.webm')))

    def test_embedded_text_confirmation_is_frozen_per_scene(self):
        import module_texts
        import test_module_texts
        with mock.patch.object(module_texts, 'needs_inventory', return_value=True), \
                mock.patch.object(module_texts, 'collect', return_value=test_module_texts.inventory()):
            draft = self.call('preview', 'register')
            preview = self.variant / 'previews' / draft
            self.call('preview', 'open', draft, '--hyperframes-cli', str(self.cli_path), '--no-open')
            with self.assertRaisesRegex(cli.HarnessError, 'per Scene'):
                self.call('preview', 'accept', draft)
            self.assertIsNone(cli.read_json(self.variant / 'variant.yaml')['accepted_preview'])
            frozen = (preview / 'module-texts.json').read_bytes()
            (preview / 'module-texts.json').write_bytes(frozen + b' ')
            with self.assertRaisesRegex(cli.HarnessError, 'inventory changed'):
                self.call('preview', 'accept', draft, '--confirm-embedded', 'S01')
            (preview / 'module-texts.json').write_bytes(frozen)
            self.call('preview', 'accept', draft, '--confirm-embedded', 'S01')
            receipt = cli.read_json(preview / 'embedded-text-acceptance.json')
            self.assertEqual([{'scene':'S01','confirmed':True}], receipt['scenes'])
            self.assertEqual(cli.preview_metadata(preview)['module_texts_sha256'], receipt['module_texts_sha256'])

    def sampled(self, request, *args):
        destination = Path(request['evidence_dir'])
        destination.mkdir(parents=True)
        samples = []
        for time in (0, .5, 1, 1.5, 1.8, 1.9, 2 - 1/request['fps'], 2, 2.1, 2.2, 2.4, 3, 3.5):
            name = f'{time:.6f}.png'
            Image.new('RGB', (32, 18), 'white').save(destination / name)
            samples.append({'time':round(time,6), 'ready':True, 'texts':[], 'rhythm_candidates':[], 'carry':[], 'screenshot':name})
        return {'samples':samples, 'timeline':[], 'unverified':[], 'boundaries':[0,2]}

    def test_imported_draft_rechecks_reenabled_direction_approval(self):
        movie = self.root / 'imported.mp4'
        movie.write_bytes(b'synthetic import fixture, not a rendered video')
        draft = self.call('preview', 'register', str(movie))
        self.call('settings', 'set', 'direction_approval', 'true')
        with self.assertRaisesRegex(cli.HarnessError, 'not approved'):
            self.call('preview', 'accept', draft)
        self.assertIsNone(cli.read_json(self.variant / 'variant.yaml')['accepted_preview'])

    def test_critic_feed_sheet_keeps_every_frame_at_phone_width_in_time_order(self):
        package = self.root / 'feed-evidence'
        images = package / 'images'
        images.mkdir(parents=True)
        samples = []
        for time in reversed(range(81)):
            name = f'{time}.png'
            Image.new('RGB', (640, 360), (time + 1, 50, 100)).save(images / name)
            samples.append({'time': time, 'ready': True, 'screenshot': name})
        report = {'status': 'diagnostic_only', 'samples': samples}
        entry = {'settings': {'critic.provider': {'value': 'off'}}}
        files = critic.package(package, report, {}, [], entry)
        self.assertTrue((package / 'feed-sheet.png').is_file())
        self.assertEqual(critic.hashes(package)['feed-sheet.png'], files['feed-sheet.png'])
        with Image.open(package / 'feed-sheet.png') as sheet:
            self.assertEqual((4 * 480, 21 * (270 + 23)), sheet.size)
            for time in range(81):
                x, y = (time % 4) * 480, (time // 4) * 293
                with self.subTest(time=time):
                    self.assertEqual((time + 1, 50, 100), sheet.getpixel((x, y)))
                    self.assertEqual((time + 1, 50, 100), sheet.getpixel((x + 479, y + 269)))
                    self.assertEqual((255, 255, 255), sheet.getpixel((x + 479, y + 270)))
                    self.assertLess(sheet.crop((x, y + 270, x + 480, y + 293)).convert('L').getextrema()[0], 255)
        viewer = (package / 'index.html').read_text()
        self.assertIn('<a href="contact-sheet.png">Contact sheet</a> <a href="feed-sheet.png">feed-sheet.png</a>', viewer)
        self.assertIn('480 px 宽约等于手机信息流里的实际大小；在这张图上读不出的字和脸，手机上也读不出', viewer)

    def test_two_rounds_off_mode_and_previous_issue_coverage(self):
        mock.patch.object(cli.visual_diagnostics, 'probe', side_effect=self.sampled).start()
        self.call('settings', 'set', 'critic.provider', 'external')
        one = json.loads(self.call('critic','round','--hyperframes-cli',str(self.cli_path),'--browser','/usr/bin/google-chrome'))
        self.assertEqual('unverified', one['visual_review'])
        self.assertTrue(one['human_checks'])
        package = Path(one['package'])
        self.assertTrue((package/'PROMPT.md').is_file())
        self.assertTrue((package/'contact-sheet.png').is_file())
        pairs = json.loads((package/'boundary-pairs.json').read_text())
        self.assertEqual('sampled', pairs[0]['status'])
        self.assertEqual(6, len(json.loads((package/'strips.json').read_text())[1]['frames']))
        ledger_path = self.variant/'critic/ledger.json'
        ledger = cli.read_json(ledger_path)
        entry = ledger['rounds'][0]
        verdict = {key:entry[key] for key in ('round','draft_id','snapshot_sha256')}
        verdict.update(new_issues=[{'id':'Q1','description':'sample visual issue'}], previous=[])
        file = self.root/'verdict.json'; cli.write_json(file,verdict)
        self.call('critic','record','--file',str(file))
        limited = json.loads(self.call('critic','round','--automatic','--hyperframes-cli',str(self.cli_path),'--browser','/usr/bin/google-chrome'))
        self.assertEqual('round_limit',limited['status'])
        self.call('settings','set','critic.provider','off')
        two = json.loads(self.call('critic','round','--hyperframes-cli',str(self.cli_path),'--browser','/usr/bin/google-chrome'))
        self.assertFalse((Path(two['package'])/'PROMPT.md').exists())
        entry = cli.read_json(ledger_path)['rounds'][1]
        verdict = {key:entry[key] for key in ('round','draft_id','snapshot_sha256')}
        verdict.update(new_issues=[],previous=[]);cli.write_json(file,verdict)
        with self.assertRaisesRegex(cli.HarnessError,'every previous'):
            self.call('critic','record','--file',str(file))
        verdict['previous']=[{'id':'Q1','status':'FIXED','detail':'frame evidence'}];cli.write_json(file,verdict)
        self.call('critic','record','--file',str(file))
        ledger=cli.read_json(ledger_path)
        self.assertEqual(2,len(ledger['rounds']))
        self.assertEqual([],critic.pending_issues(ledger['rounds']))
        self.assertIsNone(cli.read_json(self.variant/'variant.yaml')['accepted_preview'])
        self.assertEqual('draft',cli.read_frontmatter(self.plan_path)['status'])
        self.assertFalse(list(self.variant.rglob('*.mp4')))


if __name__ == '__main__':
    unittest.main()
