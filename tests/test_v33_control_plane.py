from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO, WORK_CLI as cli


class ControlPlaneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / ".studio/templates", self.root / ".studio/templates")
        cli.account_service(self.root).put("account", "main", {"name": "Fixture"})
        cli.account_service(self.root).put("series", "fixture", {"name": "Fixture", "design": "stage-full"})

    def run_cli(self, *args):
        if "new" in args and "--account" not in args and "test" not in args:
            args += ("--account", "main")
        if "new" in args and "hyperframes_video" in args:
            if "--purpose" not in args:
                args += ("--purpose", "standard")
            if "--series" not in args and args[args.index("--purpose") + 1] != "test":
                args += ("--series", "fixture")
            if "--design" not in args and "--mode" not in args:
                args += ("--design", "stage-full")
            if "--variant-id" not in args:
                args += ("--variant-id", "main")
        parsed = cli.build_parser().parse_args(args)
        with redirect_stdout(io.StringIO()) as output:
            parsed.handler(self.root, parsed)
        return output.getvalue().strip()

    def put(self, kind, identity, **data):
        path = self.root / "config.json"
        path.write_text(json.dumps(data))
        return json.loads(self.run_cli(kind, "put", identity, "--file", str(path)))

    def test_accounts_share_inputs_and_freeze_adopted_configuration(self):
        self.put("theme", "clean", name="Clean", ratios=["16:9"], modes=["text-led", "animation-led"])
        self.put("account", "a", name="A", theme="clean", ratio="16:9")
        self.put("account", "b", name="B", theme="clean", ratio="16:9")
        self.put("series", "agents", name="Agents", accounts=["a", "b"], design="stage-full")
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video", "--series", "agents", "--account", "a")
        work, _ = cli.locate_work(self.root, identity)
        self.run_cli("variant", "add", "b", "--account", "b")
        a, b = work / "variants/main", work / "variants/b"
        self.assertEqual(cli.input_path(a, "SCRIPT.md"), cli.input_path(b, "SCRIPT.md"))
        self.assertEqual(cli.input_path(a, "RESEARCH.md"), cli.input_path(b, "RESEARCH.md"))
        self.assertNotEqual(a / "ANIMATION_PLAN.md", b / "ANIMATION_PLAN.md")
        self.assertFalse((b / "SCRIPT.md").exists())
        self.put("account", "b", name="New B", theme="clean", ratio="16:9")
        self.assertEqual(1, cli.read_json(b / "variant.yaml")["account_revision"])
        self.assertEqual("B", cli.read_json(b / "variant.yaml")["account_settings"]["name"])
        self.run_cli("variant", "add", "duplicate", "--account", "b")
        self.assertEqual("b", cli.read_json(work / "variants/duplicate/variant.yaml")["account"])
        self.assertEqual("New B", cli.read_json(work / "variants/duplicate/variant.yaml")["account_settings"]["name"])
        with self.assertRaisesRegex(cli.HarnessError, "does not support"):
            self.run_cli("variant", "add", "portrait", "--account", "main", "--theme", "clean", "--ratio", "9:16")
        self.put("account", "branch", name="Branch")
        self.run_cli("variant", "add", "branch", "--from", "main", "--account", "branch")
        branch = work / "variants/branch"
        self.assertEqual("main", cli.read_json(branch / "variant.yaml")["content_branch"]["source_variant"])
        self.assertNotEqual(cli.input_path(a, "SCRIPT.md"), cli.input_path(branch, "SCRIPT.md"))
        self.put("series", "agents", name="Renamed", accounts=["a"])
        self.assertEqual([identity], json.loads(self.run_cli("series", "get", "agents"))["works"])
        self.assertTrue(work.is_dir())

    def test_test_batches_never_encode_or_accept(self):
        identity = self.run_cli("new", "Experiment", "--workflow", "hyperframes_video", "--purpose", "test")
        work, _ = cli.locate_work(self.root, identity)
        self.assertEqual("test", cli.read_frontmatter(work / "WORK.md")["series"])
        self.run_cli("variant", "add", "second", "--batch", "contrast", "--design", "stage-full")
        with self.assertRaisesRegex(cli.HarnessError, "batch already"):
            self.run_cli("variant", "add", "third", "--batch", "contrast", "--design", "stage-full")
        with mock.patch.object(cli.subprocess, "run") as process:
            for arguments in (("preview", "render", "draft-v001", "--final", "--output", str(self.root / "bad.mp4")),
                              ("finalize",), ("preview", "accept", "draft-v001")):
                with self.assertRaises(cli.HarnessError):
                    self.run_cli(*arguments)
            process.assert_not_called()

    def test_soft_archive_preserves_state_paths_and_readonly_view(self):
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        state = cli.read_json(variant / "variant.yaml")
        (variant / "final").mkdir()
        (variant / "final/final.mp4").write_bytes(b"existing artifact")
        self.assertEqual(str(work), self.run_cli("archive"))
        self.assertEqual("archive", cli.locate_work(self.root, identity)[1])
        self.run_cli("--work", identity, "status")
        self.assertEqual("archive", cli.locate_work(self.root, identity)[1])
        self.run_cli("reopen", identity)
        reopened = cli.read_json(variant / "variant.yaml")
        self.assertEqual(state, {key: reopened[key] for key in state})
        self.assertEqual(b"existing artifact", (variant / "final/final.mp4").read_bytes())

    def test_finalize_runs_target_only_and_preserves_final_on_qa_failure(self):
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        state = cli.read_json(variant / "variant.yaml")
        state["accepted_preview"] = "draft-v001"
        cli.write_variant(variant, state)
        old = variant / "final/final.mp4"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        def render(root, args):
            self.assertEqual("draft-v001", args.preview_id)
            self.assertTrue(args.final)
            Path(args.output).write_bytes(b"mock output")
        with mock.patch.object(cli, "command_preview_render", side_effect=render) as renderer:
            with mock.patch.object(cli, "encoded_video_qa", side_effect=cli.HarnessError("decode failure")):
                with self.assertRaisesRegex(cli.HarnessError, "Finalize failed"):
                    self.run_cli("finalize")
            renderer.assert_called_once()
        self.assertEqual(b"old", old.read_bytes())
        self.assertEqual(1, len(list((variant / ".runtime").glob("finalize-*/failure.json"))))

    def test_encoded_qa_requires_valid_stream_and_full_decode(self):
        candidate = self.root / "candidate.mp4"
        candidate.write_bytes(b"not a real export")
        probe = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}], "format": {"duration": "2"}}
        results = [mock.Mock(returncode=0, stdout=json.dumps(probe)), mock.Mock(returncode=1, stderr="decode error")]
        with mock.patch.object(cli.subprocess, "run", side_effect=results):
            with self.assertRaisesRegex(cli.HarnessError, "full decode"):
                cli.encoded_video_qa(candidate)

    def test_shared_inputs_materialize_in_frozen_request_and_review(self):
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        (variant / "project/scene.html").write_text("original scene")
        brief = self.root / "brief.md"
        brief.write_text("Adjust S01")
        requests = cli.work_requests
        revision = requests.freeze(self.root, work, variant, "fix-001", brief, ["S01"], ["scene.html"], [])
        patch = self.root / "patch"
        patch.mkdir()
        (patch / "scene.html").write_text("new scene")
        delivery = requests.deliver(revision, "d001", patch)
        review = requests.review(self.root, revision, delivery, cli.read_json, cli.write_variant)
        review_variant = review / "works/active" / identity / "variants/main"
        self.assertNotIn("shared_inputs", cli.read_json(review_variant / "variant.yaml"))
        for name in ("SCRIPT.md", "RESEARCH.md"):
            self.assertEqual(cli.input_path(variant, name).read_bytes(), cli.input_path(review_variant, name).read_bytes())
        self.assertEqual(cli.script_text(cli.input_path(variant, "SCRIPT.md")),
                         cli.script_text(cli.input_path(review_variant, "SCRIPT.md")))

    def test_process_telemetry_records_observations_without_inventing_usage(self):
        evidence = self.root / "telemetry.json"
        success = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(cli.subprocess, "run", return_value=success) as process:
            with mock.patch.object(cli.time, "perf_counter", side_effect=[10.0, 12.5]):
                self.assertIs(success, cli.measured_process(["mock-tool"], evidence, "render", check=False))
            process.assert_called_once_with(["mock-tool"], check=False)
        call = cli.read_json(evidence)["calls"][0]
        self.assertEqual(1, call["completed_process_calls"])
        self.assertEqual(2.5, call["elapsed_seconds"])
        self.assertEqual("succeeded", call["state"])
        for field in ("tool_retries", "cache_hits", "tokens", "cost"):
            self.assertIsNone(call[field])
        with mock.patch.object(cli.subprocess, "run", side_effect=OSError("launch failed")):
            with self.assertRaisesRegex(OSError, "launch failed"):
                cli.measured_process(["unavailable"], evidence, "decode", check=False)
        failed = cli.read_json(evidence)["calls"][1]
        self.assertEqual(0, failed["completed_process_calls"])
        self.assertEqual(1, failed["launch_attempts"])
        self.assertEqual("interrupted-or-launch-failed", failed["state"])

    def test_qa_collects_probe_and_full_decode_calls(self):
        candidate = self.root / "candidate.mp4"
        candidate.write_bytes(b"mock encoded bytes")
        evidence = self.root / "telemetry.json"
        probe = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}], "format": {"duration": "2"}}
        results = [mock.Mock(returncode=0, stdout=json.dumps(probe)), mock.Mock(returncode=0, stderr="")]
        with mock.patch.object(cli.subprocess, "run", side_effect=results):
            self.assertTrue(cli.encoded_video_qa(candidate, evidence=evidence)["passed"])
        calls = cli.read_json(evidence)["calls"]
        self.assertEqual(["ffprobe-qa", "ffmpeg-decode-qa"], [call["operation"] for call in calls])
        self.assertEqual(2, sum(call["completed_process_calls"] for call in calls))

    def test_registered_cleanup_retries_only_while_final_proof_is_valid(self):
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        runtime = variant / ".runtime"
        job = runtime / "finalize-fixture"
        job.mkdir(parents=True)
        candidate = job / "candidate.mp4"
        candidate.write_bytes(b"valid Final")
        final = variant / "final/final.mp4"
        final.parent.mkdir(parents=True)
        final.write_bytes(candidate.read_bytes())
        digest = cli.file_sha256(final)
        cli.write_json(variant / "final/manifest.json", {"final_sha256": digest})
        cli.write_json(job / "qa.json", {"passed": True, "sha256": digest})
        (job / "failure-notes.log").write_text("keep evidence")
        unknown = runtime / "unregistered.mp4"
        unknown.write_bytes(candidate.read_bytes())
        with cli.naming_lock(self.root), mock.patch.object(cli.storage, "reclaim", side_effect=OSError("busy")):
            with self.assertRaisesRegex(OSError, "busy"):
                cli.reclaim_final_candidates(variant, candidate)
        self.assertTrue(candidate.exists())
        final.write_bytes(b"new version")
        cli.write_json(variant / "final/manifest.json", {"final_sha256": cli.file_sha256(final)})
        with cli.naming_lock(self.root):
            self.assertEqual([], cli.reclaim_final_candidates(variant))
        self.assertTrue(candidate.exists())
        final.write_bytes(candidate.read_bytes())
        cli.write_json(variant / "final/manifest.json", {"final_sha256": digest,
                       "render": {"source_snapshot": ".runtime/finalize-fixture/candidate.mp4"}})
        with cli.naming_lock(self.root):
            self.assertEqual([], cli.reclaim_final_candidates(variant))
        self.assertTrue(candidate.exists())
        cli.write_json(variant / "final/manifest.json", {"final_sha256": digest})
        self.run_cli("storage", "cleanup", "--apply")
        self.assertFalse(candidate.exists())
        self.assertTrue((job / "qa.json").exists())
        self.assertTrue((job / "failure-notes.log").exists())
        self.assertTrue(unknown.exists())
        self.assertEqual("removed", cli.read_json(runtime / "final-candidates.json")["entries"][0]["state"])

    def test_cleanup_registry_failure_does_not_fail_committed_finalize(self):
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        state = cli.read_json(variant / "variant.yaml")
        state["accepted_preview"] = "draft-v001"
        cli.write_variant(variant, state)
        def render(root, args):
            Path(args.output).write_bytes(b"mock encoded result")
        def promote(root, args, work, location):
            (variant / "final").mkdir(parents=True)
            shutil.copy2(args.final_file, variant / "final/final.mp4")
        warning = io.StringIO()
        with mock.patch.object(cli, "command_preview_render", side_effect=render), \
                mock.patch.object(cli, "encoded_video_qa", return_value={"passed": True}), \
                mock.patch.object(cli, "command_finalize_video", side_effect=promote), \
                mock.patch.object(cli, "reclaim_final_candidates", side_effect=cli.HarnessError("registry invalid")), \
                mock.patch.object(cli.sys, "stderr", warning):
            self.run_cli("finalize")
        self.assertEqual(b"mock encoded result", (variant / "final/final.mp4").read_bytes())
        self.assertEqual(1, len(list((variant / ".runtime").glob("finalize-*/candidate.mp4"))))
        self.assertIn("Final is complete; temporary cleanup deferred", warning.getvalue())

    def test_series_rules_are_addressed_by_identity_and_keep_history(self):
        empty = json.loads(self.run_cli("series", "rules", "show", "fixture"))
        self.assertFalse(empty["exists"])
        rules = self.root / "rules.md"
        rules.write_text("# Fixture\n\n- 避免重复的开场\n", encoding="utf-8")
        written = json.loads(self.run_cli("series", "rules", "put", "fixture", "--file", str(rules)))
        self.assertTrue(written["changed"])
        path = Path(written["path"])
        self.assertEqual(self.root / "works/fixture/AGENTS.md", path)
        self.assertFalse(json.loads(self.run_cli("series", "rules", "put", "fixture", "--file", str(rules)))["changed"])
        rules.write_text("# Fixture\n\n- 第二版\n", encoding="utf-8")
        self.run_cli("series", "rules", "put", "fixture", "--file", str(rules))
        shown = json.loads(self.run_cli("series", "rules", "show", "fixture"))
        self.assertEqual("# Fixture\n\n- 第二版\n", shown["content"])
        self.assertEqual(2, shown["revisions"])
        self.assertIn("避免重复的开场", (cli.runtime_root(self.root) / "control-plane/series/fixture/history/1.md").read_text(encoding="utf-8"))
        self.assertEqual(["fixture"], [row["id"] for row in json.loads(self.run_cli("series", "list"))])

        # A Work reached through a linked series folder still resolves rules from WORK.md metadata.
        identity = self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        work, _ = cli.locate_work(self.root, identity)
        linked = self.root / "series-view" / identity
        linked.parent.mkdir()
        linked.symlink_to(work, target_is_directory=True)
        status = json.loads(self.run_cli("--work", identity, "--json", "status"))
        self.assertEqual({"series": "fixture", "path": str(path), "exists": True}, status["series_rules"])

        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "rules", "show", "missing")
        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "rules", "show", "history")
        rules.write_text("  \n", encoding="utf-8")
        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "rules", "put", "fixture", "--file", str(rules))
        path.unlink()
        path.symlink_to(rules)
        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "rules", "show", "fixture")

    def test_series_delete_archives_unreferenced_series_and_rules(self):
        service = cli.account_service(self.root)
        service.put("series", "spare", {"name": "Spare"})
        service.put("series", "spare", {"name": "Spare renamed"})
        rules = self.root / "rules.md"
        rules.write_text("# Spare\n", encoding="utf-8")
        self.run_cli("series", "rules", "put", "spare", "--file", str(rules))
        removed = json.loads(self.run_cli("series", "rules", "delete", "spare"))
        self.assertTrue(removed["changed"])
        self.assertFalse(removed["exists"])
        self.assertFalse(json.loads(self.run_cli("series", "rules", "delete", "spare"))["changed"])
        self.assertEqual(1, json.loads(self.run_cli("series", "rules", "show", "spare"))["revisions"])

        self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        with self.assertRaisesRegex(cli.HarnessError, "still owns Works"):
            self.run_cli("series", "delete", "fixture")

        # Materials without WORK.md in another series folder are not Works and do not block.
        (cli.series_folder(self.root, "fixture") / "materials").mkdir()
        self.assertEqual(1, len(json.loads(self.run_cli("series", "get", "fixture"))["works"]))
        deleted = json.loads(self.run_cli("series", "delete", "spare"))
        archive = Path(deleted["archive"])
        self.assertEqual(cli.runtime_root(self.root) / "control-plane/deleted/series", archive.parent)
        self.assertEqual("Spare renamed", json.loads((archive / "spare.json").read_text(encoding="utf-8"))["name"])
        self.assertTrue((archive / "history/1.json").is_file())
        self.assertTrue((archive / "rules/history/1.md").is_file())
        self.assertEqual(["fixture"], [row["id"] for row in json.loads(self.run_cli("series", "list"))])
        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "get", "spare")
        with self.assertRaises(cli.HarnessError):
            self.run_cli("series", "delete", "spare")
        # A recreated identity starts a fresh revision history.
        self.assertEqual(1, service.put("series", "spare", {"name": "Spare again"})["revision"])


    def test_account_delete_archives_only_unused_accounts(self):
        service = cli.account_service(self.root)
        service.put("account", "spare", {"name": "Spare"})
        service.put("account", "spare", {"name": "Spare renamed"})
        service.put("account", "listed", {"name": "Listed"})
        service.put("series", "listing", {"name": "Listing", "accounts": ["listed"]})
        self.run_cli("new", "Episode", "--workflow", "hyperframes_video")
        with self.assertRaisesRegex(cli.HarnessError, "frozen into Variants"):
            self.run_cli("account", "delete", "main")
        with self.assertRaisesRegex(cli.HarnessError, "listed by series: listing"):
            self.run_cli("account", "delete", "listed")
        # A materials folder without WORK.md inside a series folder is not a Work and does not block.
        (cli.series_folder(self.root, "fixture") / "materials").mkdir()

        deleted = json.loads(self.run_cli("account", "delete", "spare"))
        archive = Path(deleted["archive"])
        self.assertEqual(cli.runtime_root(self.root) / "control-plane/deleted/account", archive.parent)
        self.assertEqual("Spare renamed", json.loads((archive / "spare.json").read_text(encoding="utf-8"))["name"])
        self.assertTrue((archive / "history/1.json").is_file())
        self.assertEqual(["listed", "main"], [row["id"] for row in json.loads(self.run_cli("account", "list"))])
        with self.assertRaises(cli.HarnessError):
            self.run_cli("account", "delete", "spare")
        self.assertEqual(1, service.put("account", "spare", {"name": "Spare again"})["revision"])

if __name__ == "__main__":
    unittest.main()
