from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
LOADER = SourceFileLoader("export_stage_cards", str(REPO / "export-stage-cards"))
SPEC = importlib.util.spec_from_loader("export_stage_cards", LOADER)
EXPORT = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(EXPORT)


class ExportStageCardsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_export(self, *arguments):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = EXPORT.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_package_drops_examples_and_fonts_and_rewrites_their_references(self):
        output = self.root / "pkg"
        code, out, err = self.run_export("--output", str(output), "--zip")
        self.assertEqual(0, code, err)
        names = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
        self.assertFalse([name for name in names if "/example" in name or name.startswith("fonts/") or name.endswith(".otf")])
        self.assertTrue({"README.md", "AGENTS.md", "LICENSE", "runtime/motion.js", "runtime/scene-binding.js",
                         "designs/stage-full/assets/stage-kit/stage-kit.js", "designs/stage-light/design.json"} <= names)
        self.assertEqual([], EXPORT.scan(output))
        versions = {card: json.loads((REPO / f".studio/designs/{card}/design.json").read_text())["version"] for card in EXPORT.CARDS}
        readme = (output / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"`stage-full` v{versions['stage-full']}、`stage-light` v{versions['stage-light']}", readme)
        self.assertNotIn("可运行示例", (output / "designs/stage-full/GUIDE.md").read_text(encoding="utf-8"))
        first = (self.root / "pkg.zip").read_bytes()
        self.assertEqual(0, self.run_export("--output", str(output), "--zip", "--force")[0])
        self.assertEqual(first, (self.root / "pkg.zip").read_bytes())

    def test_stale_rewrite_rule_stops_the_export(self):
        share = self.root / "share"
        shutil.copytree(EXPORT.SHARE, share)
        rules = json.loads((share / "rewrites.json").read_text(encoding="utf-8"))
        rules["rewrites"][0]["old"] += "（源文档已改）"
        (share / "rewrites.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(EXPORT, "SHARE", share):
            code, _, err = self.run_export("--output", str(self.root / "pkg"))
        self.assertEqual(1, code)
        self.assertIn("rewrite matches 0 times", err)
        self.assertFalse((self.root / "pkg").exists())

    def test_scan_reports_leaks_and_dangling_example_paths(self):
        (self.root / "a").mkdir()
        (self.root / "a/GUIDE.md").write_text("Work 071 实测\n见 `example/index.html`\n用 DeepSeek 做\n", encoding="utf-8")
        (self.root / "a/CHANGELOG.md").write_text("- v3：新增 `example/kit-demo.html`\n", encoding="utf-8")
        self.assertEqual(["a/GUIDE.md:1: Work number", "a/GUIDE.md:2: example reference", "a/GUIDE.md:3: model name"],
                         EXPORT.scan(self.root))

    def test_existing_output_is_replaced_only_when_forced_and_previously_exported(self):
        other = self.root / "notes"
        other.mkdir()
        (other / "keep.txt").write_text("mine")
        self.assertEqual(1, self.run_export("--output", str(other))[0])
        self.assertEqual(1, self.run_export("--output", str(other), "--force")[0])
        self.assertEqual("mine", (other / "keep.txt").read_text())


if __name__ == "__main__":
    unittest.main()
