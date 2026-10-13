from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO, WORK_CLI as cli


class SeriesLayoutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / ".studio/templates", self.root / ".studio/templates")
        service = cli.account_service(self.root)
        service.put("account", "main", {"name": "Fixture"})
        service.put("series", "fixture", {"name": "Fixture 系列", "design": "stage-full"})
        service.put("series", "other", {"name": "Other", "design": "stage-full"})

    def run_cli(self, *args, stdin=None):
        if "new" in args:
            args += ("--workflow", "hyperframes_video", "--design", "stage-full", "--variant-id", "main")
            if "--purpose" not in args:
                args += ("--account", "main", "--purpose", "standard")
            if "--series" not in args and "test" not in args:
                args += ("--series", "fixture")
        parsed = cli.build_parser().parse_args(args)
        with redirect_stdout(io.StringIO()) as output, mock.patch.object(cli.sys, "stdin", io.StringIO(stdin or "")):
            parsed.handler(self.root, parsed)
        return output.getvalue().strip()

    def new(self, title, *extra):
        identity = self.run_cli("new", title, *extra)
        return cli.locate_work(self.root, identity)[0]

    def legacy(self, work, container):
        """Move a Work back to a pre-layout container to simulate an old WorkStore."""
        target = self.root / "works" / container / work.name
        target.parent.mkdir(parents=True, exist_ok=True)
        work.rename(target)
        return target

    def studio_record(self, work, **extra):
        project = work / "variants/main/project"
        record = {"project": str(project), "browser_profile": str(work / "variants/main/.runtime/studio-browser"),
                  "pid": 999999, "port": 3002, **extra}
        (work / "variants/main/.runtime").mkdir(parents=True, exist_ok=True)
        (work / "variants/main/.runtime/studio-current.json").write_text(json.dumps(record), encoding="utf-8")

    def migrate(self, *extra):
        return json.loads(self.run_cli("migrate", "layout", *extra))

    def test_new_works_land_in_their_series_folder(self):
        production = self.new("Episode")
        experiment = self.new("Probe", "--purpose", "test")
        self.assertEqual(self.root / "works/fixture" / production.name, production)
        self.assertEqual(self.root / "works/test" / experiment.name, experiment)
        self.assertFalse((self.root / "works/active").exists())
        cli.refresh_browser(self.root)
        browser = (self.root / "浏览目录.md").read_text(encoding="utf-8")
        self.assertIn("## Fixture 系列 · [文件夹](works/fixture)", browser)
        self.assertIn("## 临时实验", browser)
        self.assertLess(browser.index("## Fixture 系列"), browser.index("## 临时实验"))

    def test_reserved_series_identities_are_rejected(self):
        service = cli.account_service(self.root)
        for identity in ("active", "parked", "archive", "history", "_未归系列"):
            with self.assertRaises(cli.HarnessError, msg=identity):
                service.put("series", identity, {"name": identity})

    def test_rules_live_in_series_folder_and_accept_stdin(self):
        written = json.loads(self.run_cli("series", "rules", "put", "fixture", "--file", "-", stdin="# 规则\n\n- 一\n"))
        path = self.root / "works/fixture/AGENTS.md"
        self.assertEqual(str(path), written["path"])
        self.assertEqual("# 规则\n\n- 一\n", path.read_text(encoding="utf-8"))
        self.run_cli("series", "rules", "put", "fixture", "--file", "-", stdin="# 规则\n\n- 二\n")
        history = cli.runtime_root(self.root) / "control-plane/series/fixture/history/1.md"
        self.assertIn("- 一", history.read_text(encoding="utf-8"))
        self.new("Episode")
        cli.refresh_browser(self.root)
        self.assertIn("[系列规则](works/fixture/AGENTS.md)", (self.root / "浏览目录.md").read_text(encoding="utf-8"))

    def test_series_config_accepts_stdin(self):
        self.run_cli("series", "put", "fresh", "--file", "-", stdin='{"name": "Fresh"}')
        self.assertEqual("Fresh", json.loads(self.run_cli("series", "get", "fresh"))["name"])
        with self.assertRaisesRegex(cli.HarnessError, "Invalid JSON"):
            self.run_cli("series", "put", "fresh", "--file", "-", stdin="not json")

    def test_legacy_rules_are_read_then_adopted_by_migration(self):
        legacy = cli.runtime_root(self.root) / "control-plane/series/fixture/AGENTS.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("# 旧规则\n", encoding="utf-8")
        self.assertEqual("# 旧规则\n", json.loads(self.run_cli("series", "rules", "show", "fixture"))["content"])
        report = self.migrate()
        self.assertEqual([{"series": "fixture", "from": str(legacy), "to": str(self.root / "works/fixture/AGENTS.md")}],
                         report["rules"])
        self.assertTrue(legacy.is_file())
        self.migrate("--apply")
        self.assertFalse(legacy.exists())
        self.assertEqual("# 旧规则\n", (self.root / "works/fixture/AGENTS.md").read_text(encoding="utf-8"))
        # Both copies present is ambiguous and must be resolved by a person.
        legacy.write_text("# 另一份\n", encoding="utf-8")
        self.assertIn("both", self.migrate()["errors"][0]["error"])

    def test_migration_moves_legacy_containers_and_keeps_lifecycle(self):
        active = self.legacy(self.new("Active"), "active")
        parked = self.legacy(self.new("Parked"), "parked")
        archived = self.legacy(self.new("Archived", "--series", "other"), "archive/2026-09")
        self.studio_record(active, stopped_at="2026-10-01T00:00:00")
        font = active / "variants/main/materials/cover.ttf"
        font.parent.mkdir(exist_ok=True)
        font.write_bytes(b"font")
        state = cli.read_json(active / "variants/main/variant.yaml")
        state["cover_recipe"] = {"font": {"path": str(font), "sha256": "x"}, "logo": {"path": "/library/logo.svg", "sha256": "y"},
                                 "width": 1080}
        cli.write_variant(active / "variants/main", state)
        self.assertEqual("parked", cli.locate_work(self.root, parked.name)[1])

        report = self.migrate()
        self.assertFalse(report["applied"])
        self.assertEqual([], report["errors"])
        self.assertEqual({active.name: "active", parked.name: "parked", archived.name: "archive"},
                         {item["work"]: item["legacy_container"] for item in report["works"]})
        self.assertTrue(active.is_dir())

        report = self.migrate("--apply")
        self.assertTrue(report["applied"])
        moved = {name: cli.locate_work(self.root, name) for name in (active.name, parked.name, archived.name)}
        self.assertEqual((self.root / "works/fixture" / active.name, "active"), moved[active.name])
        self.assertEqual((self.root / "works/fixture" / parked.name, "parked"), moved[parked.name])
        self.assertEqual((self.root / "works/other" / archived.name, "archive"), moved[archived.name])
        with self.assertRaisesRegex(cli.HarnessError, "read-only"):
            cli.ensure_mutable_work(self.root, moved[archived.name][0])
        record = json.loads((moved[active.name][0] / "variants/main/.runtime/studio-current.json").read_text())
        self.assertEqual(str(moved[active.name][0].resolve() / "variants/main/project"), record["project"])
        recipe = cli.read_json(moved[active.name][0] / "variants/main/variant.yaml")["cover_recipe"]
        self.assertEqual(str(moved[active.name][0].resolve() / "variants/main/materials/cover.ttf"), recipe["font"]["path"])
        self.assertEqual({"path": "/library/logo.svg", "sha256": "y"}, recipe["logo"])
        for name in ("active", "parked", "archive"):
            self.assertFalse((self.root / "works" / name).exists())
        self.assertEqual({"applied": True, "works": [], "rules": [], "errors": [], "stale_path_references": []},
                         self.migrate("--apply"))

    def test_stale_absolute_paths_in_working_files_are_reported_not_rewritten(self):
        work = self.legacy(self.new("Voice"), "active")
        config = work / "variants/main/materials/tts-audition/config.json"
        config.parent.mkdir(parents=True)
        text = json.dumps({"reference_audio": "D:\\AI\\root\\works\\active\\work-hyperframes_video-057-x\\voice.wav"})
        config.write_text(text, encoding="utf-8")
        frozen = work / "variants/main/previews/draft-v001/refs.json"
        frozen.parent.mkdir(parents=True)
        frozen.write_text(text, encoding="utf-8")
        expected = [{"work": work.name, "files": ["variants/main/materials/tts-audition/config.json"],
                     "other_works": ["work-hyperframes_video-057-x"]}]
        self.assertEqual(expected, self.migrate()["stale_path_references"])
        self.assertEqual(expected, self.migrate("--apply")["stale_path_references"])
        self.assertEqual(text, (self.root / "works/fixture" / work.name / config.relative_to(work)).read_text(encoding="utf-8"))

    def test_possibly_live_studio_blocks_migration(self):
        work = self.legacy(self.new("Live"), "active")
        self.studio_record(work)
        with mock.patch.object(cli.storage, "process_stopped", return_value=False):
            self.assertIn("preview studio stop", self.migrate()["errors"][0]["error"])
            with self.assertRaisesRegex(cli.HarnessError, "resolve them first"):
                self.migrate("--apply")
        self.assertTrue(work.is_dir())

    def test_studio_record_from_another_runtime_blocks_migration(self):
        work = self.legacy(self.new("Windows"), "active")
        self.studio_record(work, stopped_at="2026-10-01T00:00:00",
                           project="D:\\AI\\AI+hyperframes\\works\\active\\" + work.name + "\\variants\\main\\project")
        self.assertIn("runtime that wrote it", self.migrate()["errors"][0]["error"])

    def test_duplicate_work_folders_are_reported(self):
        work = self.new("Twin")
        shutil.copytree(work, self.root / "works/active" / work.name)
        with self.assertRaisesRegex(cli.HarnessError, "several folders"):
            cli.locate_work(self.root, work.name)
        with self.assertRaisesRegex(cli.HarnessError, "Duplicate physical Work ID"):
            cli.list_work_rows(self.root)
        rows = [row for row in cli.list_work_rows(self.root, validate_identity=False) if row["id"] == work.name]
        self.assertEqual(2, len(rows))
        self.assertTrue(all("several folders" in row["error"] for row in rows))

    def test_series_move_relocates_the_folder(self):
        work = self.new("Mover")
        moved = json.loads(self.run_cli("--work", work.name, "series", "move", "other"))
        self.assertEqual(str(self.root / "works/other" / work.name), moved["path"])
        self.assertFalse(work.exists())
        self.assertEqual("other", cli.read_frontmatter(Path(moved["path"]) / "WORK.md")["series"])
        # An interrupted move (metadata written, folder not yet moved) is finished by re-running it.
        back = self.root / "works/fixture" / work.name
        Path(moved["path"]).rename(back)
        again = json.loads(self.run_cli("--work", work.name, "series", "move", "other"))
        self.assertEqual(moved["path"], again["path"])
        self.assertEqual(moved["series_number"], again["series_number"])

    def test_series_delete_removes_folder_holding_only_rules(self):
        cli.account_service(self.root).put("series", "spare", {"name": "Spare"})
        self.run_cli("series", "rules", "put", "spare", "--file", "-", stdin="# Spare\n")
        (self.root / "works/spare/notes.md").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(cli.HarnessError, "besides AGENTS.md"):
            self.run_cli("series", "delete", "spare")
        (self.root / "works/spare/notes.md").unlink()
        archive = Path(json.loads(self.run_cli("series", "delete", "spare"))["archive"])
        self.assertFalse((self.root / "works/spare").exists())
        self.assertEqual("# Spare\n", (archive / "rules/AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
