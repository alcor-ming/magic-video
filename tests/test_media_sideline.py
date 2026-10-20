import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import asset_contract
import bgm_import
import cover
import designs
import explainer
import sfx_generate
from component_harness import ComponentError


def png(path, color_type, shade=0x10):
    """A 1x1 PNG; colour type 6 carries alpha, 2 is opaque RGB."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixel = b'\x00' + bytes([shade, 0x20, 0x30]) + (b'\x00' if color_type == 6 else b'')
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, color_type, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(pixel)) + chunk(b'IEND', b''))
    return path


class AccountCharacterTest(unittest.TestCase):
    def test_generated_character_is_registered_on_the_account_and_reaches_the_cover(self):
        import test_work_cli as fixtures
        cli = fixtures.WORK_CLI
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(fixtures.REPO / '.studio/templates', root / '.studio/templates')
            font = root / 'font.ttf'
            font.write_bytes(b'font')
            cli.account_service(root).put('account', 'account', {'name': 'A', 'overrides': {'cover': {
                'width': 1080, 'height': 1440, 'font': {'path': str(font), 'sha256': cover.digest(b'font')},
                'layout': 'character-bottom', 'character_style': '剪纸舞台风，暖色'}}})
            cli.account_service(root).put('series', 'series', {'name': 'S', 'design': 'stage-full'})

            def invoke(*args, status=0):
                with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(status, cli.main(['--json', *args], root=root), errors.getvalue())
                return output.getvalue().strip() if status == 0 else errors.getvalue()

            opaque = png(root / 'opaque.png', 2)
            self.assertIn('transparency', invoke('account', 'character', 'add', 'account', '--name', 'calm', '--image',
                                                 str(opaque), '--prompt', 'p', '--model', 'm', status=2))
            calm = png(root / 'calm.png', 6)
            added = json.loads(invoke('account', 'character', 'add', 'account', '--name', 'calm', '--image', str(calm),
                                      '--prompt', '站立微笑', '--model', 'gpt-image-2.5'))
            self.assertNotEqual(str(calm), added['path'])
            self.assertEqual(cover.digest(calm.read_bytes()), added['sha256'])
            provenance = json.loads(Path(added['provenance']).read_text())
            self.assertEqual(('gpt-image-2.5', '站立微笑', '剪纸舞台风，暖色', {}),
                             (provenance['model'], provenance['prompt'], provenance['character_style'], provenance['references']))
            self.assertIn('already exists', invoke('account', 'character', 'add', 'account', '--name', 'calm', '--image',
                                                   str(calm), '--prompt', 'p', '--model', 'm', status=2))
            self.assertIn('Unknown reference', invoke('account', 'character', 'add', 'account', '--name', 'grin', '--image',
                                                      str(calm), '--prompt', 'p', '--model', 'm', '--reference', 'nope', status=2))
            grin = png(root / 'grin.png', 6, shade=0x40)
            second = json.loads(invoke('account', 'character', 'add', 'account', '--name', 'grin', '--image',
                                       str(grin), '--prompt', '大笑', '--model', 'm', '--reference', 'calm'))
            self.assertEqual({'calm': added['sha256']}, json.loads(Path(second['provenance']).read_text())['references'])
            account = cli.account_service(root).get('account', 'account')
            self.assertEqual({'calm', 'grin'}, set(account['overrides']['cover']['characters']))
            self.assertEqual('剪纸舞台风，暖色', account['overrides']['cover']['character_style'])

            identity = invoke('new', 'Cover', '--workflow', 'hyperframes_video', '--purpose', 'standard', '--series', 'series',
                              '--account', 'account', '--design', 'stage-full', '--variant-id', 'main')

            def screenshot(command, **kwargs):
                (Path(command[2]) / 'cover.png').write_bytes((Path(command[2]) / 'index.html').read_bytes())
            with patch.object(cover.subprocess, 'run', side_effect=screenshot):
                rendered = json.loads(invoke('cover', 'render', '--title', '标题', '--tagline', '一句话', '--character', 'calm'))
            self.assertEqual(added['sha256'], rendered['files']['character.png'])


class BgmTest(unittest.TestCase):
    def test_stage_cards_keep_bgm_off_until_the_account_turns_it_on(self):
        for card in ('stage-full', 'stage-light'):
            self.assertIs(False, designs.resolve(card)['values']['bgm.enabled'])
        values = designs.resolve('stage-full', account={'bgm': {'enabled': True, 'policy': 'incompetech 轻快'}})['values']
        self.assertEqual((True, 'incompetech 轻快'), (values['bgm.enabled'], values['bgm.policy']))

    def test_license_flags(self):
        self.assertEqual((False, False), bgm_import.license_flags('CC BY 4.0'))
        self.assertEqual((True, True), bgm_import.license_flags('CC BY-NC-SA 4.0'))
        self.assertEqual((False, False), bgm_import.license_flags('CC0 1.0'))
        for bad in ('CC BY-ND 4.0', 'CC BY-NC-ND 3.0', ''):
            with self.assertRaises(ComponentError):
                bgm_import.license_flags(bad)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local ffmpeg required')
    def test_import_transcodes_records_rights_and_freezes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = root / 'download.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=1.5',
                            str(track)], check=True)
            arguments = dict(library='Free Music Archive', source_url='https://freemusicarchive.org/music/x/y',
                             license_name='CC BY-NC 4.0', attribution='"Y" by X, CC BY-NC 4.0', title='Y', moods=['calm'])
            report = bgm_import.import_bgm(track, root / 'source', 'calm-y', **arguments)
            self.assertFalse(report['accepted'])
            metadata = json.loads((root / 'source/calm-y/asset.json').read_text())
            self.assertEqual(('bgm', ['bgm', 'calm']), (metadata['audio_role'], metadata['tags']))
            self.assertEqual((True, False), (metadata['rights']['non_commercial'], metadata['rights']['share_alike']))
            frozen = asset_contract.freeze_source(root / 'source/calm-y', root / 'frozen')
            self.assertEqual(frozen, asset_contract.validate_asset(root / 'frozen'))
            with self.assertRaisesRegex(ComponentError, 'already exists'):
                bgm_import.import_bgm(track, root / 'source', 'calm-y', **arguments)
            with self.assertRaisesRegex(ComponentError, 'No-derivatives'):
                bgm_import.import_bgm(track, root / 'source', 'nd', **{**arguments, 'license_name': 'CC BY-ND 4.0'})
            self.assertFalse((root / 'source/nd').exists())
            metadata.pop('rights')
            (root / 'source/calm-y/asset.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ComponentError, 'BGM requires'):
                asset_contract.freeze_source(root / 'source/calm-y', root / 'frozen-2')

    def test_library_bgm_rule_only_on_cards_that_declare_bgm(self):
        cues = explainer.build_cues('ab', json.dumps({'characters': [
            {'char': 'a', 'start': 0.5, 'end': 1}, {'char': 'b', 'start': 3, 'end': 3.5}]}).encode())
        plan = {'bgm': {'ref': 'song@v1', 'start_cue': 'a', 'end_cue': 'b', 'gain': 0.4}, 'sfx': []}
        made = {'song@v1': {'vendor_path': 'vendor/song', 'metadata': {'kind': 'media', 'entry': 'audio.mp3'}}}
        explainer.sound_elements(plan, cues, made)
        with self.assertRaisesRegex(explainer.ExplainerError, 'open-source library'):
            explainer.sound_elements(plan, cues, made, library_bgm=True)
        library = {'song@v1': {'vendor_path': 'vendor/song', 'metadata': {'kind': 'media', 'entry': 'audio.mp3', 'audio_role': 'bgm'}}}
        elements, tracks = explainer.sound_elements(plan, cues, library, library_bgm=True)
        self.assertEqual('harness-bgm-track', tracks[0]['id'])


class EarshotTest(unittest.TestCase):
    def fake_earshot(self, root):
        script = root / 'earshot'
        script.write_text('''#!/usr/bin/env python3
import json, sys, wave
args = sys.argv[1:]
if args[:2] == ['sfx', 'list']:
    print(json.dumps({'version': 'forge_test', 'sounds': []})); sys.exit(0)
if args[2] == 'nope/x':
    print('BankError: unknown sound id', file=sys.stderr); sys.exit(1)
out = args[args.index('-o') + 1]
with wave.open(out, 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b'\\x00\\x00' * 4800 + b'\\xff\\x3f' * 4800 + b'\\x00\\x00' * 4800)
print(json.dumps({'summary': 'ok', 'file': out, 'meta': {'id': args[2], 'seed': 7, 'peak_s': 0.1,
      'checks': {'ok': True, 'warnings': []}, 'argv': args}}))
''')
        script.chmod(0o755)
        return str(script)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'local ffmpeg required')
    def test_bank_render_records_seed_peak_audit_and_asset(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            earshot = self.fake_earshot(root)
            result = sfx_generate.generate(None, {'id': 'whoosh_fast/crisp', 'duration': 0.8, 'apex': 0.32},
                                           root / 'out', engine='earshot', earshot=earshot)
            self.assertEqual(('earshot bank forge_test', 7, 0.1), (result['engine_version'], result['parameters']['seed'], result['hit_offset']))
            self.assertTrue(result['audit']['ok'])
            asset = json.loads((root / 'out/asset.json').read_text())
            self.assertEqual(('whoosh-fast-generated', 'sfx', 0.1), (asset['id'], asset['audio_role'], asset['hit_offset']))
            log = (root / 'out/render.log').read_text()
            self.assertIn('"--dur", "0.8"', log)
            self.assertIn('"--apex", "0.32"', log)
            frozen = asset_contract.freeze_source(root / 'out', root / 'frozen')
            self.assertEqual(frozen, asset_contract.validate_asset(root / 'frozen'))
            with self.assertRaisesRegex(ValueError, 'exists'):
                sfx_generate.generate(None, {'id': 'whoosh_fast/crisp'}, root / 'out', engine='earshot', earshot=earshot)
            with self.assertRaisesRegex(ValueError, 'rendering failed'):
                sfx_generate.generate(None, {'id': 'nope/x'}, root / 'bad', engine='earshot', earshot=earshot)
            self.assertFalse((root / 'bad').exists())

    def test_parameters_are_checked_before_rendering(self):
        for params in ({'kind': 'click'}, {'id': 'whoosh'}, {'id': 'a/b', 'gain': 1}, {'id': 'a/b', 'peak_db': 1},
                       {'id': 'a/b', 'seed': -1}, {'id': 'a/b', 'duration': float('nan')}, {'id': 'a/b', 'pitch': True}):
            with self.assertRaises(ValueError):
                sfx_generate.earshot_parameters(params)

    @unittest.skipUnless(os.environ.get('HYPERFRAMES_EARSHOT') and shutil.which('ffmpeg'), 'real earshot not configured')
    def test_real_earshot_bank_render_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            params = {'id': 'whoosh_fast/crisp', 'duration': 0.8, 'apex': 0.32}
            first = sfx_generate.generate(None, params, root / 'a', engine='earshot', earshot=os.environ['HYPERFRAMES_EARSHOT'])
            second = sfx_generate.generate(None, params, root / 'b', engine='earshot', earshot=os.environ['HYPERFRAMES_EARSHOT'])
            self.assertEqual(first['files']['audio.wav'], second['files']['audio.wav'])
            self.assertAlmostEqual(0.32, first['hit_offset'], delta=0.01)


if __name__ == '__main__':
    unittest.main()
