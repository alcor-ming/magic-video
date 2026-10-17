"""Tracked public-repository boundary: no personal cards, local wiring or new personal paths.

Runs on a Git checkout (locally and in CI); staged release trees have no Git metadata and skip.
"""
import json
from pathlib import Path
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
# Already published history that names the owner's paths; new files must not add more.
PATH_ALLOWLIST = {
    'docs/PRD/hyperframes-v343-text-imagery.md',
    'docs/PRD/hyperframes-v352-acceptance-checklist.md',
    'docs/PRD/hyperframes-v36-showcase-math.md',
    'docs/PRD/hyperframes-v361-broll-asset-authoring.md',
    'docs/PRD/hyperframes-v361-motion-broll.md',
    'docs/PRD/hyperframes-windows-workbench-wsl-handoff.md',
    'tests/test_release_cli.py',
    'tests/test_release_personal.py',
    'tests/test_root_deploy.py',
    'tests/test_series_layout.py',
    'tests/test_public_boundary.py',
}
TRELLIS_ALLOWLIST = {
    '.trellis/tasks/10-13-github-release/acceptance.md',
    '.trellis/tasks/10-13-github-release/windows-install-check.log',
}
PERSONAL_MARKERS = ('/home/jym', 'AI+hyperframes', 'yimingchat886@')
PERSONAL_ENTRIES = {'asr-wsl.cmd', '.studio/asr_wsl_bridge.py', 'tests/test_asr_wsl_bridge.py',
                    'personal/dev-notes.md', 'AGENTS.override.md'}


def tracked():
    try:
        output = subprocess.run(['git', 'ls-files', '-z'], cwd=REPO, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [name for name in output.decode('utf-8').split('\0') if name]


@unittest.skipUnless((REPO / '.git').exists(), 'Boundary applies to the Git checkout, not staged packages')
class PublicBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.files = tracked()
        if self.files is None:
            self.skipTest('git unavailable')

    def test_only_public_cards_are_tracked(self):
        public = set(json.loads((REPO / '.studio/package-scopes.json').read_text(encoding='utf-8'))['public_cards'])
        cards = {name.split('/')[2] for name in self.files
                 if name.startswith('.studio/designs/') and name.count('/') >= 3}
        self.assertLessEqual(cards - {'shared'}, public)

    def test_no_personal_entries_or_new_trellis_material(self):
        self.assertEqual([], sorted(PERSONAL_ENTRIES & set(self.files)))
        self.assertEqual([], sorted(name for name in self.files
                                    if name.startswith('.trellis/') and name not in TRELLIS_ALLOWLIST))

    def test_public_source_manifest_is_complete_and_public(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from test_release_cli import RELEASE
        # Raises on any declared file that is missing, linked or not a public product source.
        self.assertTrue(RELEASE.source_hashes([]))

    def test_no_new_personal_paths(self):
        found = []
        for name in self.files:
            if name in PATH_ALLOWLIST:
                continue
            path = REPO / name
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            if b'\0' in data[:4096]:
                continue
            text = data.decode('utf-8', 'ignore')
            found += [f'{name}: {marker}' for marker in PERSONAL_MARKERS if marker in text]
        self.assertEqual([], found)


if __name__ == '__main__':
    unittest.main()
