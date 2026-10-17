"""Offline provider, measured alignment, and transactional formal-voice regressions."""
import base64
from contextlib import nullcontext
from email.message import Message
import io
import json
from pathlib import Path
import sys
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl
import wave

STUDIO = Path(__file__).resolve().parents[1] / '.studio'
sys.path.insert(0, str(STUDIO))
import tts
import work as work_api
import work_tts


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x01\x00' * 2000)
    return stream.getvalue()


def alignment(text):
    return tts.json_bytes({'characters': [
        {'text': char, 'start': index * 0.04, 'end': (index + 1) * 0.04, 'aligned': True}
        for index, char in enumerate(text)]})


PROVIDER = '''import argparse, json, pathlib, sys, wave
p = argparse.ArgumentParser()
p.add_argument('--request', required=True)
p.add_argument('--result', required=True)
a = p.parse_args()
request = json.loads(pathlib.Path(a.request).read_text())
assert request['schema_version'] == 1 and request['output'] == 'audio.wav'
assert request['anchor'].startswith('P') and request['text']
mode = request['options'].get('mode')
if mode == 'exit':
    print('PRIVATE-PROVIDER-SECRET', file=sys.stderr)
    sys.exit(7)
if mode == 'missing':
    sys.exit(0)
output = pathlib.Path(request['output'])
if mode == 'bad-wave':
    output.write_bytes(b'not WAV')
else:
    with wave.open(str(output), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\\x01\\x00' * 2000)
result = str(output)
if mode == 'escape':
    result = '../outside.wav'
elif mode == 'absolute':
    result = str(output.resolve())
elif mode == 'symlink':
    output.unlink()
    output.symlink_to(pathlib.Path(a.request))
model = 'unexpected-model' if mode == 'wrong-model' else request['model']
options = {'undeclared': True} if mode == 'wrong-options' else request['options']
pathlib.Path(a.result).write_text(json.dumps({'audio': result, 'model': model, 'options': options}))
'''


class TTSTests(unittest.TestCase):
    def test_voice_defaults_only_fill_an_explicit_synthesis_task(self):
        local = {'tools': {'tts': self.config, 'voices': {'narrator': {'reference_audio': '/reference.wav', 'duration_factor': 1.2}}}}
        state = {'design_values': {'voice.ref': 'narrator', 'voice.duration_factor': 1.05}}
        with mock.patch.dict('os.environ', {'HYPERFRAMES_AI_RESOLVED_CONFIG': json.dumps(local)}):
            config = work_tts.generation_config(state)
            self.assertEqual(1.05, config['options']['duration_factor'])
            self.assertEqual('/reference.wav', config['options']['reference_audio'])
            explicit = {**self.config, 'options': {'duration_factor': 0.9}, 'anchors': {'P001': {'duration_factor': 1.1}}}
            chosen = work_tts.generation_config(state, explicit)
            self.assertEqual(0.9, chosen['options']['duration_factor'])
            self.assertEqual(1.1, chosen['anchors']['P001']['duration_factor'])
            with self.assertRaisesRegex(ValueError, 'not mapped'):
                work_tts.generation_config({'design_values': {'voice.ref': 'missing'}})
        self.assertNotIn('audio', state)

    def test_batch_import_checks_every_result_without_calling_provider(self):
        script_hash = tts.digest(b'current script')
        request = tts.generation_request(self.rows, self.config, script_hash)
        folder = self.root / 'batch'
        folder.mkdir()
        entries = []
        for row, basis in zip(request['segments'], request['generation_basis']):
            audio = folder / (row['anchor'] + '.wav')
            audio.write_bytes(wav_bytes())
            entries.append({**row, 'basis': basis, 'model': request['model'],
                            'audio': audio.name, 'sha256': tts.digest(audio.read_bytes())})
        batch = {'version': 1, 'script_sha256': script_hash, 'segments': entries}
        source = folder / 'batch.json'
        for invalid in ({**batch, 'segments': entries[:1]},
                        {**batch, 'segments': [entries[0], {**entries[1], 'text': 'wrong'}]},
                        {**batch, 'segments': [entries[0], {**entries[1], 'sha256': '0' * 64}]}):
            source.write_bytes(tts.json_bytes(invalid))
            with self.assertRaises(ValueError):
                tts.import_batch(self.variant, self.rows, self.config, script_hash, source)
            self.assertFalse((self.variant / 'materials/tts').exists())
        source.write_bytes(tts.json_bytes(batch))
        with mock.patch.object(tts, 'script_provider', side_effect=AssertionError('must use batch')):
            result = tts.import_batch(self.variant, self.rows, self.config, script_hash, source)
            again = tts.generate(self.variant, self.rows, self.config, script_hash)
        self.assertEqual(result['id'], again['id'])
        self.assertEqual(0.5, result['duration'])
        self.assertIsNone(result['alignment'])
        self.assertTrue((folder / 'P001.wav').exists())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / 'work'
        self.variant = self.work / 'variants' / 'main'
        self.variant.mkdir(parents=True)
        self.provider = self.root / 'provider.py'
        self.provider.write_text(PROVIDER)
        self.config = {'provider': 'script', 'model': 'fixture-v1', 'command': [sys.executable, str(self.provider)]}
        self.rows = [{'anchor': 'P001', 'text': '猫'}, {'anchor': 'P002', 'text': 'cat'}]

    def test_volcengine_defaults_wire_headers_options_and_wav(self):
        requests = []

        def respond(request, timeout):
            requests.append(request)
            self.assertEqual(timeout, 300)
            return io.BytesIO(json.dumps({'code': 0, 'audio': base64.b64encode(wav_bytes()).decode()}).encode())

        secret = 'PRIVATE-KEY-FIXTURE'
        with mock.patch.dict('os.environ', {'VOLCENGINE_TTS_API_KEY': secret}), mock.patch.object(tts, 'urlopen', respond):
            result = tts.generate(self.variant, self.rows,
                                  {'anchors': {'P002': {'instruction': 'Standard English', 'speaker': 'fixture-speaker'}}}, 'a' * 64)
        self.assertEqual((result['status'], result['alignment'], result['duration']), ('generated', None, 0.5))
        self.assertEqual(result['request']['provider'], 'volcengine')
        self.assertEqual(len(requests), 2)
        first = requests[0]
        self.assertEqual((first.full_url, first.get_method()), (tts.VOLCENGINE_URL, 'POST'))
        headers = {key.lower(): value for key, value in first.header_items()}
        self.assertEqual(headers['x-api-key'], secret)
        self.assertTrue(headers['x-api-request-id'])
        payload = json.loads(first.data)
        self.assertEqual((payload['model'], payload['text_prompt']), ('seed-audio-1.0', '猫'))
        self.assertEqual(payload['audio_config'], {'format': 'wav', 'sample_rate': 48000,
                                                'speech_rate': 0, 'pitch_rate': 0, 'loudness_rate': 0})
        second = json.loads(requests[1].data)
        self.assertEqual(second['text_prompt'], 'Standard English\ncat')
        self.assertEqual(second['references'], [{'speaker': 'fixture-speaker'}])
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret.encode(), (Path(result['path']) / 'manifest.json').read_bytes())
        self.assertEqual(tts.wav_info(Path(result['path']) / 'audio.wav')['sample_rate'], 8000)

    def test_provider_failure_is_redacted_and_keeps_prior_candidate(self):
        previous = tts.generate(self.variant, self.rows, self.config, 'a' * 64)
        snapshot = {p.relative_to(previous['path']): p.read_bytes() for p in Path(previous['path']).rglob('*') if p.is_file()}
        secret = 'PRIVATE-PROVIDER-SECRET'
        for response in (URLError(secret), io.BytesIO(json.dumps({'code': 42, 'message': secret}).encode()),
                         io.BytesIO(json.dumps({'audio': secret}).encode())):
            with self.subTest(response=type(response).__name__), mock.patch.dict('os.environ', {'VOLCENGINE_TTS_API_KEY': secret}):
                kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                with mock.patch.object(tts, 'urlopen', **kwargs), self.assertRaises(ValueError) as raised:
                    tts.generate(self.variant, self.rows, {}, 'a' * 64)
                self.assertNotIn(secret, str(raised.exception))
            self.assertEqual(snapshot, {p.relative_to(previous['path']): p.read_bytes() for p in Path(previous['path']).rglob('*') if p.is_file()})
            self.assertEqual([Path(previous['path'])], list((self.variant / 'materials/tts').iterdir()))
        for options in ({'api_key': secret}, {'nested': [{'Authorization': secret}]}):
            with self.assertRaisesRegex(ValueError, 'credentials'):
                tts.configuration({'options': options})
        for key in ('access_token', 'client_secret', 'secret_key', 'api_secret'):
            for field, value in (('options', {'nested': [{key: secret}]}),
                                 ('anchors', {'P001': {'nested': [{key: secret}]}})):
                with self.subTest(key=key, field=field), self.assertRaisesRegex(ValueError, 'credentials'):
                    tts.configuration({field: value})

    def test_cloud_redirect_never_resends_key_or_narration(self):
        requests = []

        class RedirectResponse(HTTPSHandler):
            def https_open(self, request):
                requests.append(request)
                headers = Message()
                headers['Location'] = 'https://other-provider.invalid/collect'
                response = addinfourl(io.BytesIO(b''), headers, request.full_url, 302)
                response.msg = 'Found'
                return response

        with mock.patch.dict('os.environ', {'VOLCENGINE_TTS_API_KEY': 'PRIVATE-KEY-FIXTURE'}), \
                mock.patch.object(tts, 'build_opener', side_effect=lambda redirect: build_opener(redirect, RedirectResponse())):
            with self.assertRaisesRegex(ValueError, 'synthesis failed'):
                tts.generate(self.variant, self.rows, {}, 'a' * 64)
        self.assertEqual([request.full_url for request in requests], [tts.VOLCENGINE_URL])
        self.assertEqual([], list((self.variant / 'materials/tts').iterdir()))

    def test_offline_script_contract_cache_identity_and_tamper_refusal(self):
        config = {**self.config, 'options': {'language': 'en'}, 'anchors': {'P001': {'language': 'zh'}}}
        result = tts.generate(self.variant, self.rows, config, 'b' * 64)
        self.assertEqual([row['options']['language'] for row in result['request']['segments']], ['zh', 'en'])
        self.assertEqual(result['segments'][1]['start'], 0.25)
        self.assertEqual(tts.candidate(self.variant, result['id'])['files'], result['files'])
        with mock.patch.object(tts, 'script_provider', side_effect=AssertionError('cache must not synthesize')):
            self.assertEqual(tts.generate(self.variant, self.rows, config, 'b' * 64)['id'], result['id'])
        changed = tts.generate(self.variant, self.rows, {**config, 'model': 'fixture-v2'}, 'b' * 64)
        self.assertNotEqual(changed['id'], result['id'])
        manifest = Path(changed['path']) / 'manifest.json'
        corrupted = json.loads(manifest.read_bytes())
        corrupted['status'] = 'aligned'
        manifest.write_bytes(tts.json_bytes(corrupted))
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            tts.candidate(self.variant, changed['id'])
        audio = Path(result['path']) / 'audio.wav'
        data = bytearray(audio.read_bytes())
        data[-1] ^= 1
        audio.write_bytes(data)
        with mock.patch.object(tts, 'script_provider', side_effect=AssertionError('must reject corrupted cache')):
            with self.assertRaisesRegex(ValueError, 'audio changed'):
                tts.generate(self.variant, self.rows, config, 'b' * 64)

    def test_script_errors_missing_audio_and_relative_path_escape_leave_no_candidate(self):
        for mode in ('exit', 'missing', 'bad-wave', 'escape', 'absolute', 'symlink', 'wrong-model', 'wrong-options'):
            with self.subTest(mode=mode), self.assertRaises(ValueError) as raised:
                tts.generate(self.variant, self.rows, {**self.config, 'options': {'mode': mode}}, 'a' * 64)
            self.assertNotIn('PRIVATE-PROVIDER-SECRET', str(raised.exception))
            self.assertEqual([], list((self.variant / 'materials/tts').iterdir()))
        with self.assertRaisesRegex(ValueError, 'model'):
            tts.configuration({'provider': 'script', 'command': self.config['command']})

    def test_stable_anchor_selection_excludes_scene_index(self):
        script = self.variant / 'SCRIPT.md'
        script.write_text('---\n{"approval":"approved"}\n---\n'
                          '<!-- scene-index:start -->\nPRIVATE PLAN INDEX\n<!-- scene-index:end -->\n'
                          '<!-- P001 -->\n猫\n\n<!-- P002 -->\ncat\n')
        narration = work_api.script_text(script, anchors=True)
        self.assertEqual(tts.segments(narration, ['P002', 'P001']), self.rows)
        self.assertEqual(tts.segments(narration, ['P002']), self.rows[1:])
        self.assertNotIn('PRIVATE PLAN INDEX', work_api.script_text(script))
        for invalid in ('no anchor', '<!-- P001 -->a<!-- P001 -->b', '<!-- P001 -->'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                tts.segments(invalid)
        with self.assertRaisesRegex(ValueError, 'Unknown TTS anchors'):
            tts.segments(narration, ['P999'])
        for rows in ([], self.rows + self.rows, [{'anchor': '../escape', 'text': 'word'}],
                     [{'anchor': 'P001', 'text': ''}]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'unique nonempty'):
                tts.generate(self.variant, rows, self.config, 'a' * 64)
        with self.assertRaisesRegex(ValueError, 'Script SHA-256'):
            tts.generate(self.variant, self.rows, self.config, 'not-a-digest')

    def test_segment_reuse_and_tool_version_invalidation(self):
        with mock.patch.object(tts, 'script_provider', wraps=tts.script_provider) as provider:
            first = tts.generate(self.variant, self.rows, self.config, 'a' * 64)
            changed_rows = [self.rows[0], {**self.rows[1], 'text': 'kitten'}]
            second = tts.generate(self.variant, changed_rows, self.config, 'b' * 64)
            self.assertEqual(provider.call_count, 3)
            self.assertEqual(first['segments'][0]['segment_id'], second['segments'][0]['segment_id'])
            self.assertTrue((Path(second['path']) / 'P001/audio.wav').is_file())
            self.assertIsNone(second['alignment'])
            self.provider.write_text(PROVIDER + '\n# adapter revision\n')
            third = tts.generate(self.variant, changed_rows, self.config, 'b' * 64)
            self.assertEqual(provider.call_count, 5)
            self.assertNotEqual(second['id'], third['id'])

    def test_partial_failure_retains_successful_segments_but_no_candidate(self):
        config = {**self.config, 'anchors': {'P002': {'mode': 'exit'}}}
        with self.assertRaises(ValueError):
            tts.generate(self.variant, self.rows, config, 'a' * 64)
        self.assertEqual([], list((self.variant / 'materials/tts').iterdir()))
        with mock.patch.object(tts, 'script_provider', wraps=tts.script_provider) as provider:
            result = tts.generate(self.variant, self.rows, self.config, 'a' * 64)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(len(result['segments']), 2)

    def test_reference_and_effective_options_invalidate_only_affected_segment(self):
        reference = self.root / 'ref.wav'
        reference.write_bytes(wav_bytes())
        config = {**self.config, 'anchors': {'P001': {'reference_audio': str(reference), 'duration_factor': 1}}}
        with mock.patch.object(tts, 'script_provider', wraps=tts.script_provider) as provider:
            first = tts.generate(self.variant, self.rows, config, 'a' * 64)
            reference.write_bytes(reference.read_bytes()[:-2] + b'\x02\x00')
            second = tts.generate(self.variant, self.rows, config, 'a' * 64)
            self.assertEqual(provider.call_count, 3)
            self.assertNotEqual(first['id'], second['id'])
            config['anchors']['P001']['duration_factor'] = 1.2
            tts.generate(self.variant, self.rows, config, 'a' * 64)
            self.assertEqual(provider.call_count, 4)
        for factor in (0, -1, True, float('nan'), float('inf')):
            with self.subTest(factor=factor), self.assertRaisesRegex(ValueError, 'duration_factor'):
                tts.configuration({**self.config, 'options': {'duration_factor': factor}})

    def test_float_reference_is_hashed_but_output_still_requires_pcm(self):
        reference = self.root / 'float.wav'
        samples = struct.pack('<ff', 0.0, 0.5)
        raw = (b'RIFF' + struct.pack('<I', 36 + len(samples)) + b'WAVEfmt '
               + struct.pack('<IHHIIHH', 16, 3, 1, 8000, 32000, 4, 32)
               + b'data' + struct.pack('<I', len(samples)) + samples)
        reference.write_bytes(raw)
        options = {'reference_audio': str(reference)}
        self.assertEqual(tts.digest(raw), tts.generation_basis(self.config, options)['reference_sha256'])
        with self.assertRaises(ValueError):
            tts.wav_info(reference)
        reference.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'reference_audio'):
            tts.generation_basis(self.config, options)
        reference.unlink()
        reference.symlink_to(self.root / 'missing.wav')
        with self.assertRaisesRegex(ValueError, 'reference_audio'):
            tts.generation_basis(self.config, options)

    def test_only_measured_complete_in_range_alignment_can_be_adopted(self):
        text = '猫 cat'
        raw = alignment(text)
        cues, sections = tts.aligned_sections(text, self.rows, raw, 0.5)
        self.assertEqual([row['anchor'] for row in sections['sections']], ['P001', 'P002'])
        self.assertEqual(sections['sections'][1]['start'], 0.08)
        self.assertEqual(cues['sources']['alignment_sha256'], tts.digest(raw))
        with self.assertRaisesRegex(ValueError, 'characters'):
            tts.aligned_sections(text, self.rows, b'{}', 0.5)
        missing = json.loads(raw)
        missing['characters'][2] = {'text': 'c', 'aligned': False}
        with self.assertRaisesRegex(ValueError, 'aligned spoken characters'):
            tts.aligned_sections(text, self.rows, tts.json_bytes(missing), 0.5)
        outside = json.loads(raw)
        outside['characters'][-1]['end'] = 2
        with self.assertRaisesRegex(ValueError, 'beyond candidate audio'):
            tts.aligned_sections(text, self.rows, tts.json_bytes(outside), 0.5)
        zero_length = json.loads(raw)
        zero_length['characters'][0]['end'] = 0
        for invalid in (tts.json_bytes(zero_length), alignment(text + 'x')):
            with self.assertRaisesRegex(ValueError, 'aligned spoken characters'):
                tts.aligned_sections(text, self.rows, invalid, 0.5)

    def adoption_fixture(self):
        def document(path, metadata, body):
            path.write_text('---\n' + json.dumps(metadata) + '\n---\n' + body)
        document(self.work / 'WORK.md', {'id': 'work', 'workflow': 'hyperframes_video'}, '')
        document(self.variant / 'SCRIPT.md', {'approval': 'approved', 'revision': 1},
                 '<!-- P001 -->\n猫\n\n<!-- P002 -->\ncat\n')
        document(self.variant / 'RESEARCH.md', {'revision': 1}, '')
        document(self.variant / 'ANIMATION_PLAN.md', {'revision': 1, 'status': 'accepted'}, '## S01\n')
        state = {'id': 'main', 'mode': 'english', 'plan_revision': 1, 'accepted_preview': 'draft-v001',
                 'current_final': 'historical-final', 'line': {'id': 'english', 'version': 1}}
        work_api.write_variant(self.variant, state)
        project = self.variant / 'project'
        project.mkdir()
        (project / 'index.html').write_text('<html><body><main>English fixture</main></body></html>')
        (project / 'project-config.json').write_text('{"snapshot_dependencies":[]}')
        historical = self.variant / 'previews' / 'draft-v001'
        historical.mkdir(parents=True)
        (historical / 'accepted.txt').write_text('frozen history')
        text = work_api.script_text(self.variant / 'SCRIPT.md')
        result = tts.generate(self.variant, self.rows, self.config, tts.digest(text.encode()))
        evidence = {**json.loads(alignment(text)), 'method': 'forced-alignment', 'engine': 'fixture-aligner 1',
                    'audio_sha256': result['files']['audio.wav']}
        (self.work / 'alignment.json').write_bytes(tts.json_bytes(evidence))
        api = SimpleNamespace(**vars(work_api))
        api.selected_work = lambda root, args: (self.work, 'active')
        api.selected_variant = lambda root, work, args: (self.variant, state)
        api.naming_lock = lambda root: nullcontext()
        api.print_result = mock.Mock()
        args = SimpleNamespace(work_override='work', variant_override='main', tts_command='adopt',
                               candidate=result['id'], alignment='alignment.json')
        return api, args, project

    def test_adoption_carries_frozen_reference_memory_to_the_new_plan_revision(self):
        api, args, _ = self.adoption_fixture()
        memory = work_api.visual_memory
        frozen = self.variant / 'reference-memory/1'
        memory.write(frozen / 'references.json', {'revision': 1, 'input': {'references': ['跨线:persistent-anchor']},
                                                  'references': [], 'seeds': [], 'findings': []})
        plan = self.variant / 'ANIMATION_PLAN.md'
        reference_hash = memory.digest(frozen / 'references.json')
        plan.write_text('---\n' + json.dumps({'revision': 1, 'status': 'accepted', 'reference_memory_sha256': reference_hash})
                        + '\n---\n## S01\n')
        with mock.patch.object(api, 'write_variant', side_effect=OSError('fixture adoption failure')):
            with self.assertRaisesRegex(OSError, 'fixture adoption failure'):
                work_tts.command(self.root, args, api)
        self.assertEqual(['1'], sorted(path.name for path in frozen.parent.iterdir()))
        work_tts.command(self.root, args, api)
        metadata = work_api.read_frontmatter(plan)
        self.assertEqual((2, reference_hash), (metadata['revision'], metadata['reference_memory_sha256']))
        self.assertEqual((frozen / 'references.json').read_bytes(),
                         (self.variant / 'reference-memory/2/references.json').read_bytes())
        # Variants adopted before the fix: the bumped revision reads the identical earlier freeze.
        work_api.shutil.rmtree(self.variant / 'reference-memory/2')
        self.assertEqual(frozen, memory.located(self.variant, 2, reference_hash))
        self.assertEqual(self.variant / 'reference-memory/2', memory.located(self.variant, 2, '0' * 64))
        memory.carry(self.variant, 2, 2, reference_hash)
        self.assertEqual(reference_hash, memory.digest(self.variant / 'reference-memory/2/references.json'))

    def test_formal_adoption_rolls_back_failure_then_guards_stale_script_audio_alignment(self):
        api, args, project = self.adoption_fixture()

        def snapshot():
            return {str(p.relative_to(self.variant)): p.read_bytes() for p in self.variant.rglob('*')
                    if p.is_file() and '.runtime' not in p.relative_to(self.variant).parts}

        full_id = args.candidate
        text = work_api.script_text(self.variant / 'SCRIPT.md')
        partial = tts.generate(self.variant, self.rows[:1], self.config, tts.digest(text.encode()))
        before = snapshot()
        evidence_path = self.work / 'alignment.json'
        evidence_bytes = evidence_path.read_bytes()
        for changes in ({'audio_sha256': '0' * 64}, {'method': 'estimated-per-character'},
                        {'audio_sha256': None}, {'method': None}):
            evidence_path.write_bytes(tts.json_bytes({**json.loads(evidence_bytes), **changes}))
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'candidate audio SHA-256|Alignment method'):
                work_tts.command(self.root, args, api)
            self.assertEqual(snapshot(), before)
        for changes, message in (({'method': 'manual-measured'}, 'no longer accepted'), ({'engine': ''}, 'engine')):
            evidence_path.write_bytes(tts.json_bytes({**json.loads(evidence_bytes), **changes}))
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                work_tts.command(self.root, args, api)
            self.assertEqual(snapshot(), before)
        evidence_path.write_bytes(evidence_bytes)
        args.candidate = partial['id']
        with self.assertRaisesRegex(ValueError, 'all current Script anchors'):
            work_tts.command(self.root, args, api)
        self.assertEqual(snapshot(), before)
        args.candidate = full_id
        with mock.patch.object(api, 'write_variant', side_effect=OSError('fixture adoption failure')):
            with self.assertRaisesRegex(OSError, 'fixture adoption failure'):
                work_tts.command(self.root, args, api)
        self.assertEqual(snapshot(), before)
        work_tts.command(self.root, args, api)
        work_tts.verify(self.variant, api)
        state = work_api.read_json(self.variant / 'variant.yaml')
        self.assertIsNone(state['accepted_preview'])
        self.assertIsNone(state['current_final'])
        self.assertEqual(state['plan_revision'], 2)
        self.assertEqual((self.variant / 'previews/draft-v001/accepted.txt').read_text(), 'frozen history')
        self.assertIn('harness-voice', (project / 'index.html').read_text())
        for path, error in ((self.variant / 'SCRIPT.md', 'Narration changed'),
                            (project / state['audio']['path'], 'audio changed'),
                            (project / state['alignment']['path'], 'alignment changed'),
                            (project / 'runtime/cues.json', 'timing changed'),
                            (project / 'runtime/section_map.json', 'timing changed')):
            data = path.read_bytes()
            path.write_bytes(data + b' changed')
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, error):
                work_tts.verify(self.variant, api)
            path.write_bytes(data)
        script = self.variant / 'SCRIPT.md'
        script_bytes = script.read_bytes()
        script.write_bytes(script_bytes.replace(b'P001', b'P009'))
        with self.assertRaisesRegex(ValueError, 'Narration anchors changed'):
            work_tts.verify(self.variant, api)
        script.write_bytes(script_bytes)
        index = project / 'index.html'
        html = index.read_text()
        index.write_text(html.replace('data-start="0"', 'data-start="99"'))
        with self.assertRaisesRegex(ValueError, 'voice track changed'):
            work_tts.verify(self.variant, api)


if __name__ == '__main__':
    unittest.main()
