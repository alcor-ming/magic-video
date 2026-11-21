"""Keep production dispatch on the shared visual and asset contracts."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V34RulesTests(unittest.TestCase):
    def test_dispatch_reaches_real_discovery_and_visual_defaults(self):
        for name in (".studio/workflow.md", ".studio/templates/ANIMATION_PLAN.template.md",
                     ".agents/skills/hyperframes-production-workflow/SKILL.md"):
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("visual-design.md", text)
        workflow = (ROOT / ".studio/workflow.md").read_text(encoding="utf-8")
        self.assertIn("work component list --query", workflow)
        self.assertIn("隔离开发任务或生产会话授权的可编辑源", workflow)
        design = (ROOT / ".studio/spec/visual-design.md").read_text(encoding="utf-8")
        for rule in ("文字与 SVG/icon 互补", "普通图标一律从本地图标集按精确版本取用",
                     "保留原声、Anchor 与源对齐", "宿主唯一时间线",
                     "阅读期间保持信息可读", "按用途查库"):
            self.assertIn(rule, design)
        self.assertNotIn("必要时才少量辅助运动", design)
        self.assertNotIn("连续完全静止不超过2秒", design)

    def test_tool_contract_names_real_operations_and_safety_boundaries(self):
        spec = (ROOT / ".studio/spec/hyperframes.md").read_text(encoding="utf-8")
        spec += (ROOT / ".studio/spec/hyperframes-assets.md").read_text(encoding="utf-8")
        spec += (ROOT / ".studio/spec/hyperframes-research.md").read_text(encoding="utf-8")
        spec += (ROOT / ".studio/spec/runtime-interfaces.md").read_text(encoding="utf-8")
        for entry in ("appearance rebind", "--apply", "--upgrade-runtime", "appearance recover",
                      "references", "borrowed.json", "--revision", "--sha256",
                      "await HarnessAppearance.load()", "dispose()", "MP3", "ffprobe/ffmpeg"):
            self.assertIn(entry, spec)
        for boundary in ("冻结快照不动", "不自动接受", "不升级已有 Work",
                         "不自动改 Work、Plan、冻结包或接受状态", "不静默退回系统字体"):
            self.assertIn(boundary, spec)
        self.assertNotIn("字体由宿主管理", spec)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("既有 Variant 外观更新入口、", readme)
        self.assertIn("组件也可纳入 WSL 开发计划", readme)


if __name__ == "__main__":
    unittest.main()
