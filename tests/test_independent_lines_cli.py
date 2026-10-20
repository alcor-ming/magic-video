"""Real CLI routes in isolated roots; synthetic speech is not pronunciation evidence."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

import test_work_appearance
from test_work_cli import REPO, WORK_CLI as cli
from test_tts import PROVIDER
from test_english_plan import lesson
import appearance
import english_plan
import explainer
import work_tts


@unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/english/design.json').is_file(), 'Personal card contract; checked in personal assembly')
class IndependentLinesCliTest(unittest.TestCase):
    asset = test_work_appearance.WorkAppearanceTest.asset

    def setUp(self):
        test_work_appearance.WorkAppearanceTest.setUp(self)
        shutil.copytree(REPO / '.studio', self.root / '.studio', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.runtime', '__pycache__'))

    def invoke(self, *arguments):
        args = cli.build_parser().parse_args(['--json', *arguments])
        with redirect_stdout(io.StringIO()) as output:
            args.handler(self.root, args)
        return output.getvalue().strip()

    def create(self, *arguments):
        identity = self.invoke('new', 'Isolated vocabulary fixture', '--workflow', 'hyperframes_video',
                               '--account', 'a', '--purpose', 'standard', '--series', 'fixture',
                               '--variant-id', 'main', *arguments)
        work, _ = cli.locate_work(self.root, identity)
        return identity, work

    def test_default_and_explicit_english_variants_bind_their_own_plans(self):
        identity, work = self.create()
        main = cli.read_json(work / 'variants/main/variant.yaml')
        self.assertEqual((main['mode'], main['line']), ('explainer', {'id': 'stage-full', 'version': 1}))
        self.assertEqual(main['design'], 'stage-full')
        for mode, heading in (('english', '# 英语学习 Plan'),):
            self.invoke('--work', identity, 'variant', 'add', mode, '--account', 'a', '--mode', mode)
            variant = work / 'variants' / mode
            state = cli.read_json(variant / 'variant.yaml')
            plan = cli.read_frontmatter(variant / 'ANIMATION_PLAN.md')
            self.assertEqual((state['mode'], state['line']), (mode, {'id': mode, 'version': 1}))
            self.assertEqual(plan['line'], state['line'])
            self.assertEqual(plan['appearance_lock_sha256'], state['appearance_lock']['sha256'])
            self.assertIn(heading, (variant / 'ANIMATION_PLAN.md').read_text())
            self.assertEqual(state['appearance_lock']['mode'], mode)
            self.assertFalse(state['appearance_lock']['selection']['captions'])
            self.assertFalse(plan['captions'])
        # Explicit captions still override the per-design default in both directions.
        self.invoke('--work', identity, 'variant', 'add', 'with-lyrics', '--account', 'a', '--mode', 'english', '--captions', 'on')
        with_lyrics = cli.read_json(work / 'variants/with-lyrics/variant.yaml')
        self.assertTrue(with_lyrics['appearance_lock']['selection']['captions'])

    def test_retired_card_is_browsable_and_explicit_content_adoption_preserves_history(self):
        identity, work = self.create()
        original = work / 'variants/main'
        old = work / 'variants/old'
        shutil.copytree(original, old)
        for name in ('SCRIPT.md', 'RESEARCH.md'):
            shutil.copy2(cli.input_path(original, name), old / name)
        state = cli.read_json(old / 'variant.yaml')
        state.pop('shared_inputs', None)
        state.update(id='old', mode='card', line={'id': 'card', 'version': 1}, accepted_preview='draft-v001')
        state['appearance_lock']['mode'] = 'card'
        state['appearance_lock']['sha256'] = appearance.digest({k: v for k, v in state['appearance_lock'].items() if k != 'sha256'})
        cli.write_variant(old, state)
        cli.write_json(old / 'project/appearance-lock.json', state['appearance_lock'])
        script = old / 'SCRIPT.md'
        script.write_text('---\n{"approval":"approved","revision":3}\n---\n<!-- P001 -->\ncat means 猫。\n')
        frozen = old / 'previews/draft-v001/snapshot'
        frozen.mkdir(parents=True)
        (frozen / 'index.html').write_text('<html>Historic card fixture; never rendered by the new runtime</html>')
        (frozen.parent / 'accepted.json').write_text('{"status":"accepted"}')

        def snapshot():
            return {p.relative_to(old).as_posix(): p.read_bytes() for p in old.rglob('*') if p.is_file()}

        before = snapshot()
        status = json.loads(self.invoke('--work', identity, '--variant', 'old', 'status'))
        self.assertEqual(status['variant']['mode'], 'card')
        listing = json.loads(self.invoke('list'))
        old_row = next(v for row in listing if row['id'] == identity for v in row['variants'] if v['id'] == 'old')
        self.assertFalse(old_row['production_supported'])
        for command in (('plan', 'check'), ('tts', 'generate'), ('preview', 'open', 'current')):
            with self.subTest(command=command), self.assertRaisesRegex(cli.HarnessError, 'unsupported production mode'):
                self.invoke('--work', identity, '--variant', 'old', *command)
        self.invoke('--work', identity, 'variant', 'add', 'english', '--from', 'old', '--account', 'a', '--mode', 'english')
        adopted = work / 'variants/english'
        new = cli.read_json(adopted / 'variant.yaml')
        self.assertEqual(new['line'], {'id': 'english', 'version': 1})
        self.assertEqual(new['content_branch']['source_variant'], 'old')
        self.assertNotIn('shared_inputs', new)
        for name in ('SCRIPT.md', 'RESEARCH.md'):
            self.assertEqual((adopted / name).read_bytes(), before[name])
        self.assertIn('# 英语学习 Plan', (adopted / 'ANIMATION_PLAN.md').read_text())
        self.assertEqual(snapshot(), before)
        self.assertIn('english', [row['id'] for row in json.loads(self.invoke('--work', identity, 'variant', 'list'))])

    def test_english_cli_script_to_offline_speech_adoption_and_plan_cues(self):
        identity, work = self.create('--mode', 'english', '--captions', 'on')
        variant = work / 'variants/main'
        script = cli.input_path(variant, 'SCRIPT.md')
        script.write_text('---\n{"approval":"approved","revision":2}\n---\n'
                          '<!-- scene-index:start -->\n| Scene | Anchors |\n|---|---|\n| S01 | P001 P002 |\n'
                          '<!-- scene-index:end -->\n<!-- P001 -->\ncat\n\n<!-- P002 -->\n试答\n')
        plan = variant / 'ANIMATION_PLAN.md'
        metadata = cli.read_frontmatter(plan)
        plan.write_text('---\n' + json.dumps(metadata) + '\n---\n## S01\n```english-plan\n'
                        + json.dumps(lesson()) + '\n```\n### I01 · SCRIPT.md#P001\n```screen\ncat\n猫\n```\n')
        project = variant / 'project'
        (project / 'index.html').write_text('<html><body><main data-composition-id="root" data-duration="0.5">'
            '<div data-hf-layer="background"></div><section data-scene-id="S01" data-start="0" data-duration="0.5">'
            '<div data-hf-layer="stage"></div><div data-hf-layer="overlay"></div>'
            '<div data-hf-layer="text"><p id="I01">cat 猫</p></div></section>'
            '<div data-hf-layer="captions"></div></main>'
            '<script src="runtime/cues.js"></script></body></html>')
        provider = self.base / 'fixture-tts.py'
        provider.write_text(PROVIDER)
        config = self.base / 'fixture-tts.json'
        cli.write_json(config, {'provider': 'script', 'model': 'synthetic-test-only',
                               'command': [sys.executable, str(provider)]})
        generated = json.loads(self.invoke('--work', identity, '--variant', 'main', 'tts', 'generate', '--config', str(config)))
        self.assertEqual((generated['status'], generated['alignment']), ('generated', None))
        audio_hash = cli.file_sha256(Path(generated['path']) / 'audio.wav')
        text = cli.script_text(script)
        timings = iter([(0, .06), (.06, .12), (.12, .18), (.25, .32), (.42, .48)])
        characters = []
        for char in text:
            start, end = next(timings) if char.isalnum() else (None, None)
            characters.append({'text': char, 'start': start, 'end': end, 'aligned': start is not None})
        # All timing and PCM are synthetic fixtures; this only exercises the measured-evidence contract.
        cli.write_json(work / 'materials/fixture-chars.json', {'characters': characters,
                       'audio_sha256': audio_hash, 'method': 'forced-alignment', 'engine': 'fixture-aligner 1'})
        adopted = json.loads(self.invoke('--work', identity, '--variant', 'main', 'tts', 'adopt', generated['id'],
                                         '--alignment', 'materials/fixture-chars.json'))
        self.assertEqual(adopted['status'], 'aligned')
        audited = json.loads(self.invoke('--work', identity, '--variant', 'main', 'tts', 'audit', generated['id'],
                                         '--alignment', 'materials/fixture-chars.json'))
        recorded = cli.read_json(project / 'runtime/alignment-report.json')
        self.assertEqual((recorded['ok'], recorded['engine'], recorded['suspects']),
                         (audited['ok'], 'fixture-aligner 1', audited['suspects']))
        work_tts.verify(variant, cli.SimpleNamespace(**vars(cli)))
        cues = cli.read_json(project / 'runtime/cues.json')
        self.assertEqual(cues['sources']['audio_sha256'], audio_hash)
        self.assertEqual(explainer.find_cue(cues, 'cat'), 0)
        self.assertEqual(explainer.find_cue(cues, '答'), .42)
        self.assertEqual([], english_plan.check(plan.read_text(), cues, [{'id': 'S01', 'start': 0, 'duration': .5}]))
        report = json.loads(self.invoke('--work', identity, '--variant', 'main', 'plan', 'check'))
        self.assertEqual([], report['findings'])
        self.assertIn('data-audio-role="voice"', (project / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
