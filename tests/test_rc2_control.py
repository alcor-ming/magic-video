from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_work_cli import REPO, WORK_CLI as cli


class Rc2ControlTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / ".studio" / "templates", self.root / ".studio" / "templates")
        for account in ("a", "b"):
            cli.account_service(self.root).put("account", account, {"name": account})
        for series in ("one", "two"):
            cli.account_service(self.root).put("series", series, {"name": series, "design": "stage-full"})

    def run_cli(self, *arguments, expected=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = cli.main(['--json', *arguments], root=self.root)
        self.assertEqual(expected, result, error.getvalue())
        return output.getvalue().strip() or error.getvalue().strip()

    def new(self, title, *, series="one", purpose="standard"):
        return self.run_cli("new", title, "--workflow", "hyperframes_video", "--purpose", purpose,
                            "--series", series, "--account", "a", "--variant-id", "main")

    def test_video_scope_and_account_variants(self):
        self.assertIn("requires --purpose", self.run_cli("new", "No purpose", "--workflow", "hyperframes_video", expected=2))
        self.assertIn("requires --series", self.run_cli("new", "No series", "--workflow", "hyperframes_video",
                                                    "--purpose", "ip", "--account", "a", expected=2))
        work_id = self.new("Agent四大阶段", purpose="ip")
        self.assertEqual("work-hyperframes_video-001-Agent四大阶段", work_id)
        self.run_cli("variant", "add", "second", "--account", "a", "--name", "横版完整版")
        self.run_cli("variant", "add", "third", "--account", "a", "--name", "短版")
        rows = json.loads(self.run_cli("find", "--series", "one", "--number", "1", "--account", "a"))
        self.assertEqual({"main", "second", "third"}, {row["variant"]["id"] for row in rows})
        self.assertEqual(3, len(json.loads(self.run_cli("account", "get", "a"))["variants"]))
        self.assertIsNone(next(row for row in json.loads(self.run_cli("list")) if row["id"] == work_id)["status"])
        tree = self.run_cli("list", "--tree")
        self.assertIn("生产系列\n  one\n    001 · Agent四大阶段", tree)
        self.assertIn("Variant name", self.run_cli("variant", "add", "invalid", "--account", "a",
                                                    "--name", "bad\nname", expected=2))
        self.assertFalse((cli.locate_work(self.root, work_id)[0] / "variants" / "invalid").exists())

    def test_unbounded_independent_numbers_and_stable_directory(self):
        cli.write_identity(self.root, {"video_highwater": 999, "series_highwater": {"one": 999},
                                       "aliases": {}, "series_aliases": {}})
        work_id = self.new("初始标题")
        self.assertEqual("work-hyperframes_video-1000-初始标题", work_id)
        work, _ = cli.locate_work(self.root, work_id)
        self.assertEqual(1000, cli.read_frontmatter(work / "WORK.md")["series_number"])
        self.run_cli("name", "新标题")
        self.assertTrue(work.is_dir())
        self.assertEqual("新标题", cli.read_frontmatter(work / "WORK.md")["title"])
        cli.account_service(self.root).put("series", "one", {"name": "Renamed"})
        self.assertEqual(1000, cli.identity_state(self.root)["series_highwater"]["one"])
        self.assertIn("works/one/", (self.root / "浏览目录.md").read_text(encoding="utf-8"))

    def test_semantic_video_title_keeps_numeric_prefix(self):
        work_id = self.new("2026-AI趋势")
        work, _ = cli.locate_work(self.root, work_id)
        self.assertEqual("2026-AI趋势", cli.read_frontmatter(work / "WORK.md")["title"])
        self.run_cli("name", "2030-新趋势")
        self.assertEqual("2030-新趋势", cli.read_frontmatter(work / "WORK.md")["title"])

    def test_adopted_production_copy_survives_experiment_removal(self):
        experiment_id = self.run_cli("new", "S03 对照", "--workflow", "hyperframes_video", "--purpose", "test",
                                     "--design", "stage-full", "--variant-id", "main")
        experiment, _ = cli.locate_work(self.root, experiment_id)
        result = experiment / "variants" / "main" / "selected.txt"
        result.write_text("adopted result", encoding="utf-8")
        production_id = self.run_cli("new", "正式版", "--workflow", "hyperframes_video",
                                     "--purpose", "standard", "--series", "one", "--account", "a",
                                     "--source-work", experiment_id, "--source-variant", "main")
        production, _ = cli.locate_work(self.root, production_id)
        adopted = production / "shared" / "selected.txt"
        shutil.copyfile(result, adopted)
        shutil.rmtree(experiment)
        self.assertEqual("adopted result", adopted.read_text(encoding="utf-8"))
        self.assertEqual(experiment_id, cli.read_frontmatter(production / "WORK.md")["source_work"])

    def test_series_move_keeps_historical_number(self):
        work_id = self.new("Original")
        self.run_cli("series", "move", "two")
        old = json.loads(self.run_cli("find", "--series", "one", "--number", "1"))
        self.assertEqual(work_id, old[0]["work"])
        self.assertEqual("two", old[0]["series"])
        next_id = self.new("Next")
        next_work, _ = cli.locate_work(self.root, next_id)
        self.assertEqual(2, cli.read_frontmatter(next_work / "WORK.md")["series_number"])

    def test_duplicate_experiment_requires_explicit_separation(self):
        first = self.run_cli("new", "S03 对照", "--workflow", "hyperframes_video", "--purpose", "test",
                             "--design", "stage-full", "--variant-id", "main")
        self.assertIn(first, self.run_cli("new", "S03 对照", "--workflow", "hyperframes_video",
                                          "--purpose", "test", "--design", "stage-full", expected=2))
        second = self.run_cli("new", "S03 对照", "--workflow", "hyperframes_video",
                              "--purpose", "test", "--separate", "--design", "stage-full", "--variant-id", "main")
        self.assertNotEqual(first, second)
        browser = (self.root / "浏览目录.md").read_text(encoding="utf-8")
        self.assertIn("S03 对照 · 001", browser)
        self.assertIn("S03 对照 · 002", browser)

    def test_migration_cli_uses_exact_dry_run_mapping(self):
        old_id = "work-hyperframes_video-027"
        work = self.root / "works" / "active" / old_id
        variant = work / "variants" / "main"
        variant.mkdir(parents=True)
        (work / "WORK.md").write_text("---\n" + json.dumps({
            "id": old_id, "title": "027-旧标题", "workflow": "hyperframes_video",
            "purpose": "standard", "series": "one"}, ensure_ascii=False)
            + "\n---\n\n# 027-旧标题\n", encoding="utf-8")
        (variant / "variant.yaml").write_text('{"id":"main","account":"a"}\n', encoding="utf-8")
        map_dir = tempfile.TemporaryDirectory()
        self.addCleanup(map_dir.cleanup)
        mapping = Path(map_dir.name) / "rc2-map.json"
        self.run_cli("migrate", "dry-run", "--only", old_id, "--output", str(mapping))
        self.assertTrue(work.is_dir())
        plan = json.loads(mapping.read_text(encoding="utf-8"))
        self.assertEqual([old_id], plan["only_ids"])
        self.assertIn("Cannot create migration mapping", self.run_cli(
            "migrate", "dry-run", "--only", old_id, "--output", str(mapping), expected=2))
        self.assertEqual(plan, json.loads(mapping.read_text(encoding="utf-8")))
        self.assertEqual([], plan["blockers"])
        self.run_cli("migrate", "apply", "--mapping", str(mapping))
        self.assertEqual("work-hyperframes_video-027-旧标题", cli.locate_work(self.root, old_id)[0].name)
        self.assertIn("旧标题", (self.root / "浏览目录.md").read_text(encoding="utf-8"))
        self.assertEqual(0, json.loads(self.run_cli("migrate", "apply", "--mapping", str(mapping)))["migrated"])


if __name__ == "__main__":
    unittest.main()
