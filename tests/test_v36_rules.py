"""Exercise v3.6 template contracts and their local rule links."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.studio'))
from visual_plan import plan_scene_rows


@unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/spec/showcase.md').is_file(), 'Personal rule files; checked in personal assembly')
class V36RulesTest(unittest.TestCase):
    def test_templates_and_production_boundaries(self):
        template = (ROOT / '.studio/templates/SHOWCASE_PLAN.template.md').read_text()
        values = {'TEMPLATE': 'pure_hyperframes', 'RATIO': '16:9',
                  'SCRIPT_REVISION': '1', 'RESEARCH_REVISION': '1', 'SUBJECT_POSITION': 'null'}
        for key, value in values.items():
            template = template.replace(f'__{key}__', value)
        metadata = json.loads(template.split('---', 2)[1])
        self.assertEqual(metadata['status'], 'draft')
        self.assertIsNone(metadata['author_model'])
        self.assertEqual(list(plan_scene_rows(template)), ['S01'])
        self.assertIn('<!-- plan-metadata:start -->', template)
        research = (ROOT / '.studio/templates/MATH_RESEARCH.template.md').read_text()
        for term in ('原片出处', '原作者', '所用片段', '声音来源', '不插值'):
            self.assertIn(term, research)
        for name in ('.studio/templates/STUDIO_AGENTS.md',
                     '.studio/templates/WINDOWS_AGENTS.md',
                     '.studio/templates/CLAUDE.template.md'):
            text = (ROOT / name).read_text()
            for term in ('开发仓', '/mnt/', 'Opus 5.5',
                         '/home/', 'D:\\', 'Codex'):
                self.assertNotIn(term, text)
        for name in ('.studio/templates/WINDOWS_AGENTS.md',
                     '.studio/templates/CLAUDE.template.md'):
            self.assertIn('[.studio/AGENTS.md](.studio/AGENTS.md)',
                          (ROOT / name).read_text())
        refinement = (ROOT / '.studio/templates/VISUAL_RETRO.template.md').read_text()
        for term in ('积木', '动作配方或规则', '内容资产', '仅属于本片', 'pack / validate / accept'):
            self.assertIn(term, refinement)

    def test_new_rule_links(self):
        paths = ['.studio/spec/showcase.md', '.studio/spec/showcase-pdoom.md',
                 '.studio/spec/showcase-science.md',
                 '.studio/templates/CLAUDE.template.md']
        for name in paths:
            path = ROOT / name
            base = ROOT if name.endswith('CLAUDE.template.md') else path.parent
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                resolved = (base / target.split('#')[0]).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT) and resolved.is_file(), target)


if __name__ == '__main__':
    unittest.main()
