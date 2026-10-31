"""Keep stage loading and v3.5.2 authoring contracts discoverable."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.studio'))
from visual_plan import plan_scene_rows


def read(name):
    return (ROOT / name).read_text(encoding='utf-8')


class V352RulesTest(unittest.TestCase):
    def test_draft_closure_and_write_boundary(self):
        workflow = read('.studio/workflow.md')
        design = read('.studio/spec/visual-design.md')
        for text in (workflow, design):
            for term in ('preview diagnose', 'rhythm_gap', '未验证区间', '修正', '例外行', '交付说明', '未处理项', '不新增审批门'):
                self.assertIn(term, text)
        for term in ('Plan 路径', 'Scene ID', '负责范围', '写入边界', '模板之外', 'CLI 与诊断', 'probe.json', '--json'):
            self.assertIn(term, workflow)
        for term in ('图标可辨认', '所指对象一致', '精确版本', '自制', '派生时除外'):
            self.assertIn(term, design)

    def test_stage_links_and_runtime_cards(self):
        router = read('.agents/skills/hyperframes-production-workflow/SKILL.md')
        for name in ('hyperframes-assets', 'hyperframes-final', 'hyperframes-research', 'runtime-interfaces'):
            self.assertIn(name + '.md', router)
            self.assertTrue((ROOT / '.studio/spec' / (name + '.md')).is_file())
        interfaces = read('.studio/spec/runtime-interfaces.md')
        names = [path.name for path in (ROOT / '.studio/runtime').glob('*.js')] + ['Background', 'Icons']
        for name in names:
            with self.subTest(name=name):
                section = interfaces.split('## ' + name + '\n', 1)[1].split('\n## ', 1)[0]
                for term in ('用途', '画幅', '占层', '参数', '```'):
                    self.assertIn(term, section)
        self.assertIn('不读源码', interfaces)
        self.assertIn('派生', interfaces)
        core = read('.studio/spec/hyperframes.md')
        for link in re.findall(r'\]\(([^)]+\.md)\)', core):
            self.assertTrue((ROOT / '.studio/spec' / link).resolve().is_file(), link)

    def test_comparison_mcp_fixture_preserves_texts_and_event_cues(self):
        text = read('tests/fixtures/v352-plan.md')
        rows = plan_scene_rows(text)
        self.assertEqual(['S01', 'S02', 'S03', 'S04'], list(rows))
        expected = {
            'I01': '会聊天 ≠ 能调用外部能力\n缺的可能是连接',
            'I021': 'MCP\n共同的连接规则', 'I022': '客户端在主机内', 'I023': '服务器提供能力',
            'I031': '示例：本周销售情况\n工具取数 → 助手组织答案',
            'I032': '工具：执行查询\n资源：提供资料\n提示模板：复用任务表达',
            'I041': '接通 ≠ 授权', 'I042': '服务器提供哪些能力\n应用允许访问哪些能力\nMCP 不是无限操作许可',
        }
        self.assertEqual(expected, {identity: info['实际表达'] for row in rows.values()
                                    for identity, info in row['screens'].items()})
        original_events = {
            'S01': [('AI', 2), ('能聊天', 2), ('却不一定', 4), ('查你的文件', 2), ('读数据库', 2),
                    ('完成一个操作', 2), ('问题常常', 3), ('不会想', 3), ('没有接上', 4), ('能用的工具', 2)],
            'S02': [('MCP', 4), ('连接协议', 4), ('AI', 2), ('里面的客户端', 2), ('里面的客户端', 4),
                    ('连接#2', 2), ('服务器#1', 2), ('服务器#2', 4), ('工具', 2), ('资料', 2),
                    ('共同', 3), ('提供出来', 2)],
            'S03': [('比如', 2), ('本周销售情况', 4), ('助手可以', 3), ('通过服务器', 2), ('查询工具', 4),
                    ('取得数据', 2), ('再组织答案', 4), ('资料可以', 2), ('资源', 4), ('常用任务', 2), ('提示模板', 4)],
            'S04': [('但接通', 2), ('不等于授权', 4), ('能看到什么', 3), ('能执行什么', 3), ('仍然取决于', 2),
                    ('服务器提供的能力', 4), ('应用的权限控制', 4), ('MCP', 3), ('随便操作电脑', 2), ('万能钥匙', 4)],
        }
        for sid, row in rows.items():
            observed = [(event['cue']['token'] + (f"#{event['cue']['nth']}" if 'nth' in event['cue'] else ''), event['layer'])
                        for event in row['events']]
            self.assertCountEqual(original_events[sid], observed)
            for info in row['screens'].values():
                self.assertIn('SCRIPT.md#P00' + sid[-1], info['信息 ID / 来源'])
        self.assertEqual(43, sum(len(row['events']) for row in rows.values()))
        self.assertEqual(0, sum(bool(event.get('derived')) for row in rows.values() for event in row['events']))
        self.assertIn('Original: 7122 characters', text)
        self.assertIn(f'Migrated: {len(text)} characters', text)
        self.assertIn('7091a8d92b1df014abf6074103bf6f0f454bbbd78a37f40484a0989d699db3e0', text)
        self.assertLess(len(text), 7122)
        for limitation in ('未绑定 Work/Variant', '无方向批准', '不代表正式音频通过', '不提前写 PASS',
                           '不复述或重新投影文字', '不意味着已生成画面或挂载'):
            self.assertIn(limitation, text)


if __name__ == '__main__':
    unittest.main()
