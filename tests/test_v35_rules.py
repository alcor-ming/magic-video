"""Guard explainer routing, retained authority, and release closure."""

from importlib.machinery import SourceFileLoader
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ROOT_TEMPLATE = ".studio/templates/WINDOWS_AGENTS.md"
STUDIO_TEMPLATE = ".studio/templates/STUDIO_AGENTS.md"
CLAUDE_TEMPLATE = ".studio/templates/CLAUDE.template.md"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class V35RulesTests(unittest.TestCase):
    def test_mode_scope_direction_and_authority(self):
        for path in (STUDIO_TEMPLATE, ROOT_TEMPLATE, ".studio/workflow.md",
                     ".studio/spec/creative.md", "README.md"):
            with self.subTest(path=path):
                text = read(path)
                tokens = ("Plan", "visual-design.md") if path == ".studio/spec/creative.md" else ("设计", "卡", "Plan")
                for token in tokens:
                    self.assertIn(token, text)
                self.assertNotIn("可保存到创作者平台草稿箱", text)
                self.assertNotIn("才可用已登录浏览器保存草稿", text)
        studio = read(STUDIO_TEMPLATE)
        for token in ("Asset Brief", "一并授权", "提供方",
                      "不公开发布", "不购买额度", "不得读取 Cookie", "单独取得用户授权"):
            self.assertIn(token, studio)
        for path in (ROOT_TEMPLATE, CLAUDE_TEMPLATE):
            self.assertNotIn("一并授权", read(path))
        caps = read(".studio/capabilities.yaml")
        self.assertNotIn("bottom_subtitles", caps)
        self.assertNotIn("creator_draft:", caps)
        self.assertNotIn("publish_payload:", caps)
        self.assertNotIn("podcast_quote_image", caps)
        self.assertIn("hyperframes_video:", caps)
        self.assertIn("global: [prompt_library, public_publishing]", caps)

    def test_design_and_plan_preserve_explainer_contract(self):
        design = read(".studio/spec/visual-design.md")
        for token in ("`math`", "`english`", "`explainer`",
                      "任一通道", "A1 约束第 4 层及资产明确声明的 embedded 独立文字", "第 5 层口播原文不受 A1",
                      "镜像回收", "系列声音签名", "同帧可见事件", "ducking",
                      "不设固定数量或间隔配额", "未试听", "Plan 检查", "Q1"):
            self.assertIn(token, design)
        plan = read(".studio/templates/ANIMATION_PLAN.template.md")
        for token in ("导演 Brief", "B 素材", "A/B 编排", "刻意停顿例外",
                      "起始 cue", "结束 cue", "起点口播词"):
            self.assertIn(token, plan)
        spec = read(".studio/spec/hyperframes.md")
        spec += read(".studio/spec/runtime-interfaces.md")
        spec += read(".studio/spec/hyperframes-assets.md")
        for token in ("data-hf-layer", "`background`", "`stage`", "`overlay`", "`text`",
                      "`captions`", "共同五层宿主", "cue_not_found", "cue_ambiguous", "cue_unaligned",
                      "HarnessFigures.load(lock)", "renderAt(t)", "character.json",
                      "captions_lock_mismatch", "sound_asset_outside_closure", "精确 ref/hash",
                      'data-audio-role="voice"', 'data-character-ref="<id@vN>"',
                      "其余 audio 必须来自 media 闭包"):
            self.assertIn(token, spec)

    def test_release_freezes_new_runtime_without_media_or_trellis(self):
        loader = SourceFileLoader("release_v35", str(ROOT / "release"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        release = importlib.util.module_from_spec(spec)
        loader.exec_module(release)
        files = [".studio/runtime/" + name for name in
                 ("appearance.js", "scene-binding.js", "motion.js", "cues.js", "captions.js", "figures.js")]
        files += [".studio/explainer.py"]
        files += ["AGENTS.md", ".studio/workflow.md", ".studio/spec/visual-design.md",
                  ".studio/templates/WINDOWS_AGENTS.md", ".studio/templates/ANIMATION_PLAN.template.md",
                  ".studio/templates/RESEARCH.template.md"]
        validator = read(".agents/skills/hyperframes-production-workflow/scripts/validate_package.py")
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            hashes = release.freeze_sources(stage, files, repo=ROOT)
            declared = json.loads(read('.studio/release-sources.json'))['files']
            self.assertEqual(set(hashes), set(declared) | set(files))
            for path in files:
                self.assertIn(path, validator)
                self.assertEqual(release.sha256(ROOT / path), release.sha256(stage / path))
            self.assertFalse(list(stage.rglob("*.mp3")))
            release.assert_no_development_harness(stage)


if __name__ == "__main__":
    unittest.main()
