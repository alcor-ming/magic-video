import sys
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
from test_release_cli import RELEASE

class PersonalPackageTest(unittest.TestCase):
    def test_card_validation_cleans_expected_locks_and_rejects_other_writes(self):
        for locks in [('operations.lock',), ('operations.lock', 'catalog.lock'),
                      ('operations.lock', 'catalog.lock', 'unexpected.json')]:
            with self.subTest(locks=locks), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(RELEASE, 'check_env', return_value={}):
                root = Path(tmp)
                (root / '.studio').mkdir()
                (root / '.studio/work.py').write_text(
                    'from pathlib import Path\n'
                    'root = Path(".studio/.runtime")\n'
                    'root.mkdir()\n'
                    f'for name in {locks!r}: (root / name).touch()\n'
                    'print(\'{"ok": true}\')\n')
                if 'unexpected.json' in locks:
                    with self.assertRaisesRegex(RELEASE.ReleaseError, 'Card validation wrote'):
                        RELEASE.validate_cards(root)
                    self.assertTrue((root / '.studio/.runtime/unexpected.json').exists())
                else:
                    RELEASE.validate_cards(root)
                    self.assertFalse((root / '.studio/.runtime').exists())

    def test_personal_skill_exclusions_filter_files_and_lock_without_changing_public(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hashes = {}
            for name in ('keep', 'drop'):
                skill = root / '.agents/skills' / name
                skill.mkdir(parents=True)
                (skill / 'SKILL.md').write_text(name)
                (skill / 'helper.txt').write_text('nested content')
                hashes[name] = RELEASE.directory_sha256(skill)
            declaration = {'version': '1', 'compatibility': {'product': RELEASE.PRODUCT_VERSION}, 'files': {'personal/tool.txt': 'a' * 64},
                           'exclude_skills': ['drop']}
            (root / 'release-sources.json').write_text(json.dumps(declaration))
            with patch.object(RELEASE, 'REPO', root), patch.object(RELEASE, 'LOCAL_SKILLS', hashes):
                excluded = RELEASE.personal_manifest(root)['exclude_skills']
                for flavor, exclusions in [('personal', excluded), ('public', [])]:
                    stage = root / flavor
                    stage.mkdir()
                    lock = {'version': 1, 'skills': {'keep': {}, 'drop': {}}}
                    (stage / 'skills-lock.json').write_text(json.dumps(lock))
                    result = RELEASE.stage_skills(stage, exclusions)
                    self.assertEqual({'keep'} if exclusions else {'keep', 'drop'}, set(result))
                    self.assertEqual(set(result), set(json.loads((stage / 'skills-lock.json').read_text())['skills']))
                    self.assertEqual(not exclusions, (stage / '.agents/skills/drop/helper.txt').exists())
                for invalid in ('drop', ['unknown'], ['drop', 'drop'], ['../drop'], [None]):
                    declaration['exclude_skills'] = invalid
                    (root / 'release-sources.json').write_text(json.dumps(declaration))
                    with self.assertRaisesRegex(RELEASE.ReleaseError, 'excluded skills'):
                        RELEASE.personal_manifest(root)

    def test_card_lock_ships_exact_commit_without_study_or_worktree_edits(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cards, personal = root / 'cards', root / 'personal'
            (cards / 'mycard/study').mkdir(parents=True)
            personal.mkdir()
            (cards / 'mycard/design.json').write_text('{"id": "mycard"}')
            (cards / 'mycard/GUIDE.md').write_text('committed D:\\AI\\AI+hyperframes')
            (cards / 'mycard/study/notes.md').write_text('research')
            (cards / 'loose').mkdir()
            (cards / 'loose/README.md').write_text('no design.json')
            git = lambda *args: subprocess.run(['git', '-C', str(cards), *args], capture_output=True, text=True, check=True).stdout.strip()
            git('init', '-q')
            git('add', '-A')
            git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'cards')
            commit = git('rev-parse', 'HEAD')
            (cards / 'mycard/GUIDE.md').write_text('uncommitted edit')
            lock = RELEASE.card_lock(personal, {'source': '../cards', 'commit': commit, 'ids': ['mycard']})
            stage = root / 'stage'
            stage.mkdir()
            files = RELEASE.stage_cards(stage, lock)
            self.assertEqual({'.studio/designs/mycard/design.json', '.studio/designs/mycard/GUIDE.md'}, set(files))
            self.assertEqual(set(files), RELEASE.card_members(lock))
            self.assertIn('committed', (stage / '.studio/designs/mycard/GUIDE.md').read_text())
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'overlaps'):
                RELEASE.stage_cards(stage, lock)
            for value, message in [({'source': '../cards', 'commit': commit, 'ids': ['stage-full']}, 'collides'),
                                   ({'source': '../cards', 'commit': commit, 'ids': ['loose']}, 'no loose/design.json'),
                                   ({'source': '../cards', 'commit': 'b' * 40, 'ids': ['mycard']}, 'missing'),
                                   ({'source': '../cards', 'commit': commit[:12], 'ids': ['mycard']}, '40-character'),
                                   ({'source': '../cards', 'commit': commit, 'ids': []}, 'ids'),
                                   ({'source': '../cards', 'commit': commit, 'ids': ['Bad']}, 'ids'),
                                   ({'source': '../cards', 'commit': commit, 'ids': ['mycard', 'mycard']}, 'ids'),
                                   ({'source': '../nowhere', 'commit': commit, 'ids': ['mycard']}, 'not found'),
                                   ({'source': '../cards', 'commit': commit, 'ids': ['mycard'], 'ref': 'main'}, 'source, commit and ids')]:
                with self.assertRaisesRegex(RELEASE.ReleaseError, message):
                    RELEASE.card_lock(personal, value)
            (cards / 'mycard/font.ttf').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:' + 'a' * 64 + '\nsize 1\n')
            git('add', '-A')
            git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'pointer')
            pointer = RELEASE.card_lock(personal, {'source': '../cards', 'commit': git('rev-parse', 'HEAD'), 'ids': ['mycard']})
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'LFS pointer'):
                RELEASE.stage_cards(root / 'pointer-stage', pointer)
            git('rm', '-q', 'mycard/font.ttf')
            (cards / 'mycard/link.txt').symlink_to('design.json')
            git('add', '-A')
            git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'link')
            linked = RELEASE.card_lock(personal, {'source': '../cards', 'commit': git('rev-parse', 'HEAD'), 'ids': ['mycard']})
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'link'):
                RELEASE.stage_cards(root / 'other-stage', linked)

    def test_personal_package_ships_only_locked_cards_and_skips_their_text_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for card in [*RELEASE.package_scopes()['public_cards'], 'math']:
                path = root / '.studio/designs' / card / 'design.json'
                path.parent.mkdir(parents=True)
                path.write_text('{}')
            (root / '.studio/designs/math/GUIDE.md').write_text('source D:\\AI\\AI+hyperframes\\asset-library')
            RELEASE.validate_distribution(root, ['math'])
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'Incomplete'):
                RELEASE.validate_distribution(root)
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'Incomplete'):
                RELEASE.validate_distribution(root, ['math', 'english'])
            self.assertIn('machine path', RELEASE.forbidden_artifact(root))
            (root / '.release.json').write_text(json.dumps({'personal_source': {'cards': {'commit': 'a' * 40, 'ids': ['math']}}}))
            self.assertIsNone(RELEASE.forbidden_artifact(root))
            (root / '.studio/designs/stage-full/GUIDE.md').write_text('D:\\AI\\AI+hyperframes')
            self.assertEqual('.studio/designs/stage-full/GUIDE.md contains a machine path', RELEASE.forbidden_artifact(root))

    def test_standalone_installer_bootstrap_does_not_read_build_sources(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'release.py'
            shutil.copyfile(RELEASE.REPO / 'release', script)
            result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('_install', result.stdout)

    def test_distribution_requires_builtin_catalog_and_forbids_personal_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual([], RELEASE.package_scopes()['personal_cards'])
            for card in RELEASE.package_scopes()['public_cards']:
                path = root / '.studio/designs' / card / 'design.json'
                path.parent.mkdir(parents=True)
                path.write_text('{}')
            RELEASE.validate_distribution(root)
            (root / '.studio/designs/stage-light/design.json').unlink()
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'Incomplete'):
                RELEASE.validate_distribution(root)
            (root / '.studio/designs/stage-light/design.json').write_text('{}')
            card = root / '.studio/designs/math/design.json'
            card.parent.mkdir(parents=True)
            card.write_text('{}')
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'Incomplete'):
                RELEASE.validate_distribution(root)
            self.assertFalse(RELEASE.public_source(card.relative_to(root).as_posix()))
            for name in ('.studio/fonts/noto-sans/OFL.txt', '.studio/painter/vendor/p5/lib/p5.js',
                         '.studio/runtime/math-kit.js', '.studio/templates/ENGLISH_PLAN.template.md'):
                self.assertFalse(RELEASE.public_source(name))
                with self.assertRaisesRegex(RELEASE.ReleaseError, 'not a public product file'):
                    RELEASE.source_hashes([name])

    def test_personal_card_resource_is_rejected_in_every_product_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for card in RELEASE.package_scopes()['public_cards']:
                path = root / '.studio/designs' / card / 'design.json'
                path.parent.mkdir(parents=True)
                path.write_text('{}')
            resource = root / '.studio/runtime/math-kit.js'
            resource.parent.mkdir(parents=True)
            resource.write_text('personal card runtime')
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'Personal card resource'):
                RELEASE.validate_distribution(root)
            resource.unlink()
            RELEASE.validate_distribution(root)

    def test_private_overlay_rejects_public_core_and_retired_personal_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; stage = root / 'stage'
            stage.mkdir()
            tool = source / 'personal/tool.py'; tool.parent.mkdir(parents=True)
            tool.write_text('print("fixture")')
            data = {'version':'1', 'compatibility':{'product':'4.2.0'}, 'files':{'personal/tool.py':RELEASE.sha256(tool)}}
            (source / 'release-sources.json').write_text(json.dumps(data))
            result = RELEASE.stage_personal(stage, source)
            self.assertEqual(result['files'], data['files'])
            self.assertIn('personal', RELEASE.module_manifest(stage))
            name = '.studio/designs/math/design.json'
            card = source / name; card.parent.mkdir(parents=True)
            card.write_text('{"id":"math","version":1}')
            data['files'] = {name:RELEASE.sha256(card)}
            (source / 'release-sources.json').write_text(json.dumps(data))
            self.assertEqual({}, RELEASE.stage_personal(stage, source)['files'])
            self.assertFalse((stage / name).exists())
            data['files'] = {'.studio/work.py':'a'*64}
            (source / 'release-sources.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'unsupported content'):
                RELEASE.stage_personal(stage, source)

    def test_private_resources_do_not_change_shared_core_or_fonts_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'work').write_text('shared core')
            font = root / '.studio/fonts/source-han-sans/font.otf'
            font.parent.mkdir(parents=True); font.write_bytes(b'shared font')
            before = RELEASE.module_manifest(root)
            for name in ('personal/dev-notes.md', 'personal/tool.py', 'personal/config.json'):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'personal resource')
            after = RELEASE.module_manifest(root)
            self.assertEqual(before['core'], after['core'])
            self.assertEqual(before['assets/fonts'], after['assets/fonts'])
            self.assertEqual(3, len(after['personal']['files']))

    def test_module_hashes_isolate_card_changes_and_runtime_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('math', 'english'):
                card = root / '.studio/designs' / name / 'design.json'
                card.parent.mkdir(parents=True)
                card.write_text(json.dumps({'id': name, 'version': 1}))
            (root / 'work').write_text('core')
            (root / 'windows-runtime.lock.json').write_text('{}')
            before = RELEASE.module_manifest(root)
            (root / '.studio/designs/math/design.json').write_text(json.dumps({'id': 'math', 'version': 2}))
            after = RELEASE.module_manifest(root)
            self.assertNotEqual(before['design/math']['sha256'], after['design/math']['sha256'])
            for module in ('design/english', 'core', 'runtime'):
                self.assertEqual(before[module], after[module])

    def test_exact_private_files_and_public_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'private';stage=root/'stage';stage.mkdir()
            (source/'personal').mkdir(parents=True)
            tool=source/'personal/tool.py';tool.write_text('print("fixture")')
            manifest={'version':'1.0.0','compatibility':{'product':RELEASE.PRODUCT_VERSION},'files':{'personal/tool.py':RELEASE.sha256(tool)}}
            (source/'release-sources.json').write_text(json.dumps(manifest))
            result=RELEASE.stage_personal(stage,source)
            self.assertEqual(result['files'],manifest['files'])
            self.assertFalse(RELEASE.public_source('personal/tool.py'))
            self.assertFalse(RELEASE.public_source('.agents/skills/tts/SKILL.md'))
            self.assertFalse(RELEASE.public_source('.agents/skills/hermes-media-download/SKILL.md'))
            rules=source/'AGENTS.md';rules.write_text('private root rules')
            entry=source/'work-wsl.sh';entry.write_text('#!/bin/sh\nexec local-bridge "$@"\n')
            skill=source/'.agents/skills/hermes-media-download/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('route')
            overlay={'AGENTS.md':RELEASE.sha256(rules),'work-wsl.sh':RELEASE.sha256(entry),'.agents/skills/hermes-media-download/SKILL.md':RELEASE.sha256(skill)}
            bases={name:RELEASE.sha256(RELEASE.REPO/RELEASE.PRIVATE_RULE_BASES[name]) for name in ('AGENTS.md','work-wsl.sh')}
            (source/'release-sources.json').write_text(json.dumps({**manifest,'files':overlay,'bases':bases}))
            target=root/'overlay';target.mkdir()
            (target/'AGENTS.md').write_text('public template')
            (target/'work-wsl.sh').write_text('public entry')
            staged=RELEASE.stage_personal(target,source)
            self.assertEqual(staged['files'],overlay)
            self.assertEqual((target/'AGENTS.md').read_text(),'public template')
            RELEASE.stage_personal_rules(target,source,staged)
            self.assertEqual((target/'AGENTS.md').read_text(),'private root rules')
            self.assertEqual((target/'work-wsl.sh').read_text(),entry.read_text())
            self.assertEqual((target/'.agents/skills/hermes-media-download/SKILL.md').read_text(),'route')
            RELEASE.stage_personal_rules(target,None,{})
            (source/'release-sources.json').write_text(json.dumps(manifest))
            declared = json.loads((RELEASE.REPO / '.studio/release-sources.json').read_text())['files']
            for name in ('asr-wsl.cmd', '.studio/asr_wsl_bridge.py', 'tests/test_asr_wsl_bridge.py'):
                self.assertFalse(RELEASE.public_source(name))
                self.assertNotIn(name, declared)
            with self.assertRaises(RELEASE.ReleaseError): RELEASE.stage_personal(stage,source)
            tool.write_text('changed')
            with self.assertRaises(RELEASE.ReleaseError): RELEASE.stage_personal(root/'other',source)
            with self.assertRaises(RELEASE.ReleaseError): RELEASE.stage_personal(root/'other',root/'missing')
            self.assertEqual(RELEASE.stage_personal(stage,None),{})

    def test_private_root_files_pin_their_public_base_and_product_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            rules = source / 'AGENTS.md'
            rules.write_text('private root rules')
            current = RELEASE.sha256(RELEASE.REPO / '.studio/templates/WINDOWS_AGENTS.md')
            declaration = {'version': '1', 'compatibility': {'product': RELEASE.PRODUCT_VERSION},
                           'files': {'AGENTS.md': RELEASE.sha256(rules)}, 'bases': {'AGENTS.md': current}}
            def check(**changes):
                (source / 'release-sources.json').write_text(json.dumps({**declaration, **changes}))
                return RELEASE.personal_manifest(source)
            self.assertEqual(current, check()['bases']['AGENTS.md'])
            with self.assertRaisesRegex(RELEASE.ReleaseError, 'older public .studio/templates/WINDOWS_AGENTS.md'):
                check(bases={'AGENTS.md': '0' * 64})
            for bases in ({}, {'AGENTS.md': current, 'CLAUDE.md': current}):
                with self.assertRaisesRegex(RELEASE.ReleaseError, 'exactly the replaced root files'):
                    check(bases=bases)
            for compatibility in ({'product': '4.0.0'}, {}, None):
                with self.assertRaisesRegex(RELEASE.ReleaseError, 'compatibility.product'):
                    check(compatibility=compatibility)
            self.assertEqual({}, check(files={'personal/tool.py': '0' * 64}, bases={}).get('bases'))

    def test_machine_paths_are_allowed_only_in_private_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('personal/media-workflow.md', '.agents/skills/tts/SKILL.md',
                         '.agents/skills/hermes-media-download/SKILL.md'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('IndexTTS lives at D:\\AI\\IndexTTS-2.5')
            self.assertIsNone(RELEASE.forbidden_artifact(root))
            leaked = root / '.studio/spec/creative.md'
            leaked.parent.mkdir(parents=True)
            leaked.write_text('see /home/someone/notes')
            self.assertEqual('.studio/spec/creative.md contains a machine path', RELEASE.forbidden_artifact(root))

if __name__=='__main__':unittest.main()
