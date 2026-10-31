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
import cover
import designs
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
                                      '--prompt', '站立微笑', '--model', 'gpt-image-2.5', '--tool', 'generate_image'))
            self.assertNotEqual(str(calm), added['path'])
            self.assertEqual(cover.digest(calm.read_bytes()), added['sha256'])
            provenance = json.loads(Path(added['provenance']).read_text())
            self.assertEqual(('generate_image', 'gpt-image-2.5', '站立微笑', '剪纸舞台风，暖色', {}),
                             (provenance['tool'], provenance['model'], provenance['prompt'], provenance['character_style'],
                              provenance['references']))
            self.assertIn('already exists', invoke('account', 'character', 'add', 'account', '--name', 'calm', '--image',
                                                   str(calm), '--prompt', 'p', '--model', 'm', status=2))
            self.assertIn('Unknown reference', invoke('account', 'character', 'add', 'account', '--name', 'grin', '--image',
                                                      str(calm), '--prompt', 'p', '--model', 'm', '--reference', 'nope', status=2))
            grin = png(root / 'grin.png', 6, shade=0x40)
            second = json.loads(invoke('account', 'character', 'add', 'account', '--name', 'grin', '--image',
                                       str(grin), '--prompt', '大笑', '--model', 'm', '--reference', 'calm'))
            second_provenance = json.loads(Path(second['provenance']).read_text())
            self.assertEqual(({'calm': added['sha256']}, None), (second_provenance['references'], second_provenance['tool']))
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
