from __future__ import annotations

from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
LOADER = SourceFileLoader("dev_storage", str(REPO / "dev-storage"))
SPEC = importlib.util.spec_from_loader("dev_storage", LOADER)
DEV_STORAGE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(DEV_STORAGE)


class DevStorageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def task(self, name, work_state="completed", archive_state="logical_archived"):
        task = self.repo / ".trellis/tasks" / name
        unpacked = task / "packages/deployments/target/staging/deploy-1/unpacked/runtime/node_modules/pkg"
        unpacked.mkdir(parents=True)
        (unpacked / "index.js").write_bytes(b"x" * 10)
        (task / "packages/deployments/target/staging/deploy-1/retained.json").write_text("{}")
        (task / "packages/deployments/target/build/receipt.json").parent.mkdir(parents=True)
        (task / "packages/deployments/target/build/receipt.json").write_text("{}")
        (task / "packages/deployments/target/build/stdout.log").write_text("log")
        (task / "packages/deployments/target/build/local-windows-x64.zip").write_bytes(b"z")
        (task / "node_modules/pkg").mkdir(parents=True)
        (task / "node_modules/pkg/index.js").write_bytes(b"y")
        (task / "packages/build.zip").write_bytes(b"z" * 20)
        (task / "packages/build.zip.sha256").write_text("digest")
        (task / "evidence").mkdir()
        (task / "evidence/receipt.json").write_text("{}")
        (task / "prd.md").write_text("# PRD")
        (task / "task.json").write_text(json.dumps({"work_state": work_state, "archive_state": archive_state}))
        return task

    def run_cli(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = DEV_STORAGE.main(list(arguments), repo=self.repo)
        return code, json.loads(output.getvalue())

    def test_cleanup_previews_then_reclaims_only_archived_task_artifacts(self):
        archived = self.task("10-01-done")
        active = self.task("10-02-open", "ready", "open")
        cancelled = self.task("10-03-cancelled", "cancelled")
        broken = self.task("10-04-broken")
        (broken / "task.json").write_text("not json")
        code, report = self.run_cli("cleanup")
        self.assertEqual(0, code)
        self.assertNotIn("removed", report)
        self.assertTrue((archived / "packages/build.zip").exists())
        paths = {item["path"] for item in report["reclaimable"]}
        self.assertEqual({f".trellis/tasks/{name}/{item}" for name in ("10-01-done", "10-03-cancelled")
                          for item in ("node_modules", "packages/build.zip", "packages/build.zip.sha256",
                                       "packages/deployments/target/staging/deploy-1/unpacked",
                                       "packages/deployments/target/build/local-windows-x64.zip")}, paths)
        skipped = {row["task"]: row.get("skipped") for row in report["tasks"]}
        self.assertEqual("not archived (ready/open)", skipped["10-02-open"])
        self.assertEqual("task.json unreadable", skipped["10-04-broken"])
        code, report = self.run_cli("cleanup", "--apply")
        self.assertEqual(0, code)
        self.assertEqual(sorted(paths), sorted(report["removed"]))
        for task in (archived, cancelled):
            self.assertFalse((task / "packages/deployments/target/staging/deploy-1/unpacked").exists())
            self.assertFalse((task / "packages/build.zip").exists())
            self.assertFalse((task / "node_modules").exists())
            for kept in ("evidence/receipt.json", "packages/deployments/target/build/receipt.json",
                         "packages/deployments/target/staging/deploy-1/retained.json"):
                self.assertEqual("{}", (task / kept).read_text())
            self.assertEqual("log", (task / "packages/deployments/target/build/stdout.log").read_text())
            self.assertEqual("# PRD", (task / "prd.md").read_text())
        for task in (active, broken):
            self.assertTrue((task / "packages/build.zip").exists())
            self.assertTrue((task / "packages/deployments/target/staging/deploy-1/unpacked").exists())

    def test_apply_rechecks_task_state_and_links(self):
        task = self.task("10-01-done")
        outside = self.repo.parent / (self.repo.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: (outside / "keep.zip").unlink(missing_ok=True) or outside.rmdir())
        (outside / "keep.zip").write_bytes(b"keep")
        os.symlink(outside, task / "linked", target_is_directory=True)
        report = DEV_STORAGE.plan(self.repo)
        self.assertNotIn(".trellis/tasks/10-01-done/linked/keep.zip", {item["path"] for item in report["reclaimable"]})
        (task / "task.json").write_text(json.dumps({"work_state": "ready", "archive_state": "open"}))
        injected = report["reclaimable"] + [{"path": ".trellis/tasks/10-01-done/linked/keep.zip", "bytes": 4}]
        removed, errors = DEV_STORAGE.apply(self.repo, injected)
        self.assertEqual([], removed)
        self.assertEqual(len(injected), len(errors))
        self.assertTrue((outside / "keep.zip").exists())
        self.assertTrue((task / "packages/build.zip").exists())

    def test_dist_keeps_newest_archive_per_channel_and_deployments(self):
        dist = self.repo / "dist"
        (dist / "deployments/target/old").mkdir(parents=True)
        names = ("magic-video-local-a-windows-x64.zip", "magic-video-harness-2026.10.0-windows-x64.zip",
                 "magic-video-local-b-windows-x64.zip", "unknown.zip")
        for index, name in enumerate(names):
            (dist / name).write_bytes(b"a")
            (dist / (name + ".sha256")).write_text("digest")
            os.utime(dist / name, (index + 1, index + 1))
        report = DEV_STORAGE.plan(self.repo)
        self.assertEqual(["dist/magic-video-local-a-windows-x64.zip", "dist/magic-video-local-a-windows-x64.zip.sha256"],
                         [item["path"] for item in report["reclaimable"]])
        self.assertIn("dist", report["areas_bytes"])

if __name__ == "__main__":
    unittest.main()
