"""Protect production routing and the v3.3 non-export contract."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ".agents/skills/hyperframes-production-workflow/SKILL.md"
PROFILE = (
    ".agents/skills/hyperframes-production-workflow/references/"
    "hyperframes-design-profile-pack-v0.1.0/SKILL.md"
)
ROOT_TEMPLATE = ".studio/templates/WINDOWS_AGENTS.md"
STUDIO_TEMPLATE = ".studio/templates/STUDIO_AGENTS.md"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ProductionRulesTests(unittest.TestCase):
    def test_stage_and_visual_contract_have_one_owner(self):
        workflow = read(".studio/workflow.md")
        self.assertEqual(
            re.findall(r"^## (\d+)\. ", workflow, re.MULTILINE),
            ["1", "2", "3", "4"],
        )
        for path in (
            ROUTER,
            ".studio/recipes/pure-hyperframes.md",
            ".studio/recipes/talking-head.md",
        ):
            with self.subTest(path=path):
                content = read(path)
                self.assertIn(".studio/workflow.md", content)
                self.assertIn(".studio/spec/visual-design.md", content)
                self.assertNotIn("preview render", content)
                self.assertNotIn("自动归档", content)
        profile = read(PROFILE)
        self.assertNotIn("## Execution order", profile)
        self.assertIn("optional", profile)
        self.assertIn(".studio/workflow.md", profile)

    def test_timing_contract_covers_actual_onset_and_seek(self):
        design = read(".studio/spec/visual-design.md")
        for requirement in (
            "最小完整语义单元", "实际起点", "不等说完整句",
            "不得挤动旧文字", "A → B → A", "A → B", "虚化（`blur`）",
            "不新增 A 的内容", "seek", "回拖", "事件间隔不超过 2 秒",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, design)
        plan = read(".studio/templates/ANIMATION_PLAN.template.md")
        self.assertIn("延续信息", plan)
        self.assertIn("A/B 编排说明", plan)

    def test_video_only_routing_retains_export_and_reopen_boundaries(self):
        workflow = read(".studio/workflow.md")
        self.assertIn("PACKAGE.md", workflow)
        self.assertIn("不是视频设计、制作或接受的前置", workflow)
        self.assertIn("test-work 不进入任何视频导出链", workflow)
        self.assertIn("导出与归档不包含上传/发布", workflow)
        self.assertIn("Variant 保持 active", workflow)
        self.assertIn("work reopen <Work-ID> --variant-id <Variant-ID>", workflow)
        self.assertIn("不改等待事项或兄弟版本的归档状态", workflow)
        for path in (ROUTER, ".studio/capabilities.yaml", ".studio/workflow.md",
                     ".studio/spec/creative.md", "README.md", STUDIO_TEMPLATE,
                     ROOT_TEMPLATE):
            with self.subTest(path=path):
                content = read(path)
                for retired in ("podcast_quote_image", "podcast-quote-image",
                                "xiaohongshu-article-copy", "native-subtitle-quote-image",
                                "planner_skill", "copy_skill"):
                    self.assertNotIn(retired, content)
        for path in (STUDIO_TEMPLATE, "README.md"):
            self.assertIn("Draft 与 test-work 不导出视频", read(path))

    def test_new_video_examples_separate_work_and_variant_accounts(self):
        for line in read("README.md").splitlines():
            if line.startswith("./work new ") and "--workflow hyperframes_video" in line:
                self.assertIn("--purpose ", line)
                if "--purpose test" not in line:
                    self.assertIn("--series ", line)
                if "--variant-id " in line:
                    self.assertIn("--account ", line)
        self.assertIn("shared_inputs", read(ROUTER))
        self.assertIn("english", read(ROUTER))


if __name__ == "__main__":
    unittest.main()
