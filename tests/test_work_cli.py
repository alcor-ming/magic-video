from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("work_cli", REPO / ".studio" / "work.py")
assert SPEC and SPEC.loader
WORK_CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORK_CLI)


class WorkCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".studio").mkdir()
        shutil.copytree(REPO / ".studio" / "templates", self.root / ".studio" / "templates")
        for identity in ("main", "douyin-9x16", "wide", "bilibili-16x9"):
            WORK_CLI.account_service(self.root).put("account", identity, {"name": identity})
        WORK_CLI.account_service(self.root).put("series", "alpha", {"name": "Alpha", "design": "stage-full"})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, *arguments: str, expected: int = 0) -> str:
        if "new" in arguments and "hyperframes_video" in arguments and "--account" not in arguments:
            arguments += ("--account", "main")
        if "new" in arguments and "hyperframes_video" in arguments:
            if "--purpose" not in arguments:
                arguments += ("--purpose", "standard")
            if "--series" not in arguments and "--purpose" in arguments and arguments[arguments.index("--purpose") + 1] != "test":
                arguments += ("--series", "alpha")
            if "--variant-id" not in arguments and arguments[arguments.index("--purpose") + 1] != "test":
                arguments += ("--variant-id", "main")
        if len(arguments) > 2 and arguments[:2] == ("variant", "add") and "--account" not in arguments:
            arguments += ("--account", arguments[2])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = WORK_CLI.main(['--json', *arguments], root=self.root)
        self.assertEqual(expected, result, stderr.getvalue())
        return stdout.getvalue().strip() or stderr.getvalue().strip()

    def new_work(self, title: str = "Test Work") -> tuple[str, Path]:
        work_id = self.invoke("new", title, "--workflow", "hyperframes_video")
        return work_id, WORK_CLI.locate_work(self.root, work_id)[0]

    def test_explicit_missing_variant_never_falls_back_to_main(self):
        work_id, _ = self.new_work()
        result = self.invoke("--work", work_id, "--variant", "missing", "status", expected=2)
        self.assertIn("Unknown variant: missing", result)

    def test_naming_lock_recovers_dead_local_owner(self) -> None:
        lock = self.root / ".studio" / ".runtime" / "naming.lock.d"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "host": WORK_CLI.socket.gethostname(),
                    "platform": WORK_CLI.sys.platform,
                    "acquired_at": WORK_CLI.now(),
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(WORK_CLI.os, "kill", side_effect=ProcessLookupError):
            with WORK_CLI.naming_lock(self.root, timeout=0.01):
                self.assertEqual(WORK_CLI.os.getpid(), json.loads((lock / "owner.json").read_text())["pid"])
        self.assertFalse(lock.exists())

    def test_plan_metadata_uses_adopted_identity_and_shared_inputs(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        path = variant / 'ANIMATION_PLAN.md'
        metadata = WORK_CLI.read_frontmatter(path)
        self.assertEqual(work.name, metadata['work'])
        self.assertEqual('main', metadata['variant'])
        self.assertNotIn('.pending-', path.read_text())
        self.assertEqual('shared/RESEARCH.md', metadata['inputs']['RESEARCH.md']['path'])
        self.assertEqual(1, metadata['research_revision'])
        self.assertEqual(1, path.read_text().count('<!-- plan-metadata:start -->'))
        self.assertEqual(WORK_CLI.read_json(variant / 'variant.yaml')['appearance_lock']['sha256'],
                         metadata['appearance_lock_sha256'])

    @staticmethod
    def update_frontmatter(path: Path, **updates: object) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        end = lines.index("---", 1)
        data = json.loads("\n".join(lines[1:end]))
        data.update(updates)
        path.write_text(
            "---\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n---\n" + "\n".join(lines[end + 1 :]) + "\n",
            encoding="utf-8",
        )

    def prepare_preview(self, work: Path, variant_id: str = "main", content: bytes = b"draft") -> Path:
        variant = work / "variants" / variant_id
        self.update_frontmatter(variant / "ANIMATION_PLAN.md", status="approved")
        self.update_frontmatter(WORK_CLI.input_path(variant, "RESEARCH.md"), status="ready")
        project = variant / "project"
        project.mkdir(exist_ok=True)
        (project / "index.html").write_text("<html></html>", encoding="utf-8")
        (project / "compositions").mkdir(exist_ok=True)
        (project / "compositions" / "main.html").write_text("<section id='S01'></section>", encoding="utf-8")
        (project / "DESIGN.md").write_text("# Design\n", encoding="utf-8")
        (project / "project-config.json").write_text("{}\n", encoding="utf-8")
        (project / "node_modules").mkdir(exist_ok=True)
        (project / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
        draft = self.root / f"{variant_id}-draft.mp4"
        draft.write_bytes(content)
        return draft

    def test_new_variant_and_status(self) -> None:
        work_id, work = self.new_work("中文标题")
        self.assertTrue((work / "shared" / "SCRIPT.md").is_file())
        self.assertTrue((work / "shared" / "RESEARCH.md").is_file())
        self.assertEqual("16:9", json.loads((work / "variants" / "main" / "variant.yaml").read_text())["ratio"])
        self.assertFalse((work / "variants" / "main" / "PACKAGE.md").exists())
        self.assertEqual(work_id, (self.root / ".studio" / ".runtime" / "current-work").read_text().strip())
        self.assertEqual("hyperframes_video", WORK_CLI.read_frontmatter(work / "WORK.md")["workflow"])

        script = work / "shared" / "SCRIPT.md"
        script.write_text(script.read_text(encoding="utf-8") + "正文\n", encoding="utf-8")
        self.update_frontmatter(script, revision=2)
        self.update_frontmatter(work / "shared" / "RESEARCH.md", status="ready", revision=3, script_revision=2)
        self.invoke("variant", "add", "douyin-9x16", "--from", "main", "--profile", "kami_editorial")
        copied_variant = work / "variants" / "douyin-9x16"
        copied = copied_variant / "SCRIPT.md"
        self.assertIn("正文", copied.read_text(encoding="utf-8"))
        self.assertEqual(2, json.loads((copied_variant / "variant.yaml").read_text())["script_revision"])
        self.assertEqual(3, WORK_CLI.read_frontmatter(copied_variant / "ANIMATION_PLAN.md")["research_revision"])
        self.assertEqual("ready", WORK_CLI.read_frontmatter(copied_variant / "RESEARCH.md")["status"])
        status = json.loads(self.invoke("status"))
        self.assertEqual("douyin-9x16", status["variant"]["id"])

    def test_workflow_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            WORK_CLI.main(["new", "Missing workflow"], root=self.root)

    def test_script_text_excludes_scene_index_and_preserves_legacy_anchors(self) -> None:
        _, work = self.new_work()
        script = work / "shared" / "SCRIPT.md"
        narration = "<!-- P001 -->\nOriginal narration.\n\n<!-- P002 -->\nSecond paragraph."
        header = '---\n{"revision":1}\n---\n\n'
        script.write_text(header + narration + "\n", encoding="utf-8")
        original = self.invoke("script", "text")
        anchored = self.invoke("script", "text", "--anchors")
        self.assertEqual(narration, anchored)
        self.assertNotIn("P001", original)
        index = ("<!-- scene-index:start -->\n## Scene index (not narration)\n"
                 "| Scene | Anchor | Budget | Research direction |\n"
                 "| S02 | P002 | 12s | This must never be spoken |\n<!-- scene-index:end -->")
        for content in (index + "\n\n" + narration, narration + "\n\n" + index):
            script.write_text(header + content + "\n", encoding="utf-8")
            self.assertEqual(original, self.invoke("script", "text"))
            self.assertEqual(anchored, self.invoke("script", "text", "--anchors"))
        for content in (index.replace("<!-- scene-index:end -->", ""), index + index):
            script.write_text(header + narration + content, encoding="utf-8")
            self.assertIn("paired scene-index", self.invoke("script", "text", expected=2))

    def test_legacy_draft_without_research_keeps_original_lifecycle(self) -> None:
        _, work = self.new_work()
        movie = self.prepare_preview(work)
        variant = work / "variants" / "main"
        self.update_frontmatter(variant / "ANIMATION_PLAN.md", research_revision=None)
        WORK_CLI.input_path(variant, "RESEARCH.md").unlink()
        self.assertEqual("draft-v001", self.invoke("preview", "register", str(movie)))
        preview = variant / "previews" / "draft-v001"
        self.assertNotIn("input_sha256", WORK_CLI.preview_metadata(preview))
        self.assertEqual("draft-v001", self.invoke("preview", "accept", "draft-v001"))
        self.assertTrue(Path(self.invoke("finalize", str(movie), "--qa-passed")).is_file())

    def test_detached_work_keeps_foreground_and_explicit_binding_is_isolated(self) -> None:
        foreground_id, _ = self.new_work("Foreground")
        self.invoke("variant", "add", "wide", "--from", "main")

        background_id = self.invoke(
            "new", "Background", "--workflow", "hyperframes_video", "--detached", "--design", "stage-full"
        )
        runtime = self.root / ".studio" / ".runtime"
        self.assertEqual(foreground_id, (runtime / "current-work").read_text().strip())
        self.assertEqual("wide", (runtime / "current-variant").read_text().strip())

        status = json.loads(self.invoke("--work", background_id, "status"))
        self.assertEqual("main", status["variant"]["id"])
        self.invoke("--work", background_id, "--variant", "main", "wait", "script_approval")
        row = next(item for item in json.loads(self.invoke("list")) if item["id"] == background_id)
        self.assertEqual("waiting_user", row["status"])
        self.assertEqual("script_approval", row["wait_for"])
        self.assertEqual(foreground_id, (runtime / "current-work").read_text().strip())
        self.assertEqual("wide", (runtime / "current-variant").read_text().strip())

    def test_external_work_root_is_persisted_and_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary)
            (external / "works").mkdir(parents=True)

            configured = json.loads(self.invoke("root", "set", str(external)))
            self.assertTrue(configured["configured"])
            self.assertEqual(str(external), configured["work_root"])
            WORK_CLI.account_service(self.root).put("account", "main", {"name": "External fixture"})
            WORK_CLI.account_service(self.root).put("series", "alpha", {"name": "Alpha", "design": "stage-full"})
            work_id = self.invoke("new", "External", "--workflow", "hyperframes_video")
            self.assertTrue((external / "works" / "alpha" / work_id).is_dir())
            self.assertEqual(work_id, (external / ".runtime" / "current-work").read_text().strip())
            self.assertFalse((self.root / "works").exists())
            self.invoke("list")
            self.assertFalse((external / "works/parked").exists())
            self.assertFalse((external / "works/archive").exists())

    def test_work_ids_and_series_numbers_are_independent_of_titles_and_sorted(self) -> None:
        first_id, first = self.new_work("Video A")
        second_id, second = self.new_work("Video B")

        self.assertEqual("work-hyperframes_video-001-Video-A", first_id)
        self.assertEqual("work-hyperframes_video-002-Video-B", second_id)
        self.assertEqual("Video A", WORK_CLI.read_frontmatter(first / "WORK.md")["title"])
        self.assertEqual(1, WORK_CLI.read_frontmatter(first / "WORK.md")["series_number"])
        self.assertEqual(2, WORK_CLI.read_frontmatter(second / "WORK.md")["series_number"])
        self.assertEqual(first_id, WORK_CLI.read_frontmatter(first / "WORK.md")["id"])
        self.assertEqual("Lucy Guo-创业", self.invoke("--work", first_id, "name", "Lucy Guo-创业"))
        self.assertEqual("李飞飞-AI工作", self.invoke("--work", second_id, "name", "李飞飞-AI工作"))
        self.assertEqual("999-Lucy Guo-转型", self.invoke("--work", first_id, "name", "999-Lucy Guo-转型"))
        self.assertEqual("999-Lucy Guo-转型", WORK_CLI.read_frontmatter(first / "WORK.md")["title"])
        self.assertEqual(1, WORK_CLI.read_frontmatter(first / "WORK.md")["series_number"])
        self.assertIn("# 李飞飞-AI工作", (second / "WORK.md").read_text(encoding="utf-8"))

        rows = json.loads(self.invoke("list"))
        self.assertEqual([first_id, second_id], [row["id"] for row in rows])
        self.assertIn("T", rows[0]["created_at"])

        numbered_id, numbered = self.new_work("007-Old video")
        future_id, _ = self.new_work("Future video")
        self.assertEqual("work-hyperframes_video-003-007-Old-video", numbered_id)
        self.assertEqual("007-Old video", WORK_CLI.read_frontmatter(numbered / "WORK.md")["title"])
        self.assertEqual("新主题", self.invoke("--work", future_id, "name", "新主题"))

    def test_detached_concurrent_work_creation_allocates_unique_ids(self) -> None:
        def create(title: str) -> None:
            WORK_CLI.command_new(
                self.root,
                WORK_CLI.build_parser().parse_args([
                    "new", title, "--workflow", "hyperframes_video", "--purpose", "standard",
                    "--series", "alpha", "--account", "main", "--detached",
                ]),
            )

        with mock.patch("builtins.print"), ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(create, ("Same title", "Same title")))

        ids = {row["id"] for row in json.loads(self.invoke("list"))}
        self.assertEqual({"work-hyperframes_video-001-Same-title", "work-hyperframes_video-002-Same-title"}, ids)

    def test_legacy_archive_directory_is_ignored(self) -> None:
        (self.root / "works" / "archive" / "tasks" / "001-legacy").mkdir(parents=True)
        self.assertEqual([], json.loads(self.invoke("list")))
        self.new_work()

    def test_wait_park_resume_archive_and_reopen(self) -> None:
        work_id, work = self.new_work()
        self.invoke("wait", "voiceover")
        state = json.loads((work / "variants" / "main" / "variant.yaml").read_text())
        self.assertEqual("waiting_asset", state["status"])

        self.invoke("park")
        self.assertTrue(work.is_dir())
        self.assertTrue((work / ".runtime" / "parked.json").is_file())
        self.assertEqual(state, json.loads((work / "variants" / "main" / "variant.yaml").read_text()))
        self.invoke("resume")
        self.assertTrue(work.is_dir())
        self.assertFalse((work / ".runtime" / "parked.json").exists())
        state = json.loads((work / "variants" / "main" / "variant.yaml").read_text())
        self.assertEqual("waiting_asset", state["status"])

        archived_path = Path(self.invoke("archive", "--outcome", "abandoned"))
        self.assertTrue(archived_path.is_dir())
        self.assertEqual("archive", WORK_CLI.locate_work(self.root, work_id)[1])
        self.assertEqual("archived", WORK_CLI.read_json(work / "variants/main/variant.yaml")["lifecycle"])
        reopened_path = Path(self.invoke("reopen", work_id))
        self.assertEqual(work, reopened_path)
        self.assertEqual("active", WORK_CLI.locate_work(self.root, work_id)[1])
        self.assertEqual("active", WORK_CLI.read_json(work / "variants/main/variant.yaml")["lifecycle"])

    def test_preview_registration_is_approved_snapshot_and_idempotent(self) -> None:
        _, work = self.new_work()
        draft = self.prepare_preview(work)
        variant = work / "variants" / "main"

        draft_id = self.invoke("preview", "register", str(draft))
        self.assertEqual("draft-v001", draft_id)
        self.assertEqual(draft_id, self.invoke("preview", "register", str(draft)))
        snapshot = variant / "previews" / draft_id / "source-snapshot"
        self.assertTrue((snapshot / "compositions" / "main.html").is_file())
        self.assertFalse((snapshot / "node_modules").exists())

        self.invoke("preview", "accept", draft_id)
        state = json.loads((variant / "variant.yaml").read_text())
        self.assertEqual(draft_id, state["accepted_preview"])
        self.assertEqual(1, state["accepted_plan_revision"])

        state["plan_revision"] = 2
        (variant / "variant.yaml").write_text(json.dumps(state), encoding="utf-8")
        result = self.invoke("preview", "accept", draft_id, expected=2)
        self.assertIn("different Plan revision", result)

    def test_card_snapshot_update_preserves_project_and_previous_draft(self):
        cards = self.root / 'cards'
        shutil.copytree(REPO / '.studio/designs/stage-full', cards / 'stage-full')
        with mock.patch.object(WORK_CLI.designs, 'CARD_DIR', cards):
            _, work = self.new_work()
            variant = work / 'variants/main'
            self.assertNotIn('design_snapshot', WORK_CLI.read_json(variant / 'variant.yaml'))
            draft = self.prepare_preview(work)
            project_copy = variant / 'project/local-asset.txt'
            project_copy.write_text('Work-specific modification')
            first = self.invoke('preview', 'register', str(draft))
            state = WORK_CLI.read_json(variant / 'variant.yaml')
            old = state['design_files']
            frozen = variant / 'previews' / first / 'design-snapshot'
            original = (frozen / 'card/GUIDE.md').read_bytes()
            (cards / 'stage-full/GUIDE.md').write_text('Updated guidance')
            rig = cards / 'stage-full/assets/stage-rig/stage-rig.js'
            rig.write_text(rig.read_text() + '\n// source update\n')
            status = json.loads(self.invoke('status'))
            self.assertIn('卡片自本 Draft 后有变化', status['design_changes']['message'])
            with mock.patch.object(WORK_CLI, 'command_preview_open', return_value={'target': 'current'}) as opened:
                report = json.loads(self.invoke('variant', 'design-update'))
                self.assertEqual('current', opened.call_args.args[1].preview_id)
            self.assertIn('stage-full/stage-rig', report['reinstall_assets'])
            self.assertEqual('Work-specific modification', project_copy.read_text())
            self.assertEqual(original, (frozen / 'card/GUIDE.md').read_bytes())
            self.assertNotEqual(old['path'], WORK_CLI.read_json(variant / 'variant.yaml')['design_files']['path'])
            self.assertEqual('draft-v002', self.invoke('preview', 'register', str(draft)))
            self.assertNotIn('design_changes', json.loads(self.invoke('status')))
            WORK_CLI.checked_preview(variant, first)

    def test_preview_rejects_unapproved_plan(self) -> None:
        _, work = self.new_work()
        variant = work / "variants" / "main"
        state = WORK_CLI.read_json(variant / "variant.yaml")
        state.pop("line", None)  # Historical Variants retain the direction gate.
        self.update_frontmatter(variant / "ANIMATION_PLAN.md", plan_format="3.5.2", line=None)
        WORK_CLI.write_variant(variant, state)
        draft = self.root / "draft.mp4"
        draft.write_bytes(b"draft")
        result = self.invoke("preview", "register", str(draft), expected=2)
        self.assertIn("not approved", result)
        self.assertFalse((variant / "previews" / "draft-v001").exists())

    def test_preview_rejects_stale_research(self) -> None:
        _, work = self.new_work()
        variant = work / "variants" / "main"
        self.update_frontmatter(variant / "ANIMATION_PLAN.md", status="approved")
        draft = self.root / "draft.mp4"
        draft.write_bytes(b"draft")
        result = self.invoke("preview", "register", str(draft), expected=2)
        self.assertIn("RESEARCH.md is not ready", result)
        self.assertFalse((variant / "previews" / "draft-v001").exists())

    def test_finalize_stays_active_and_rotates_video_with_its_receipt(self) -> None:
        work_id, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke("preview", "register", str(draft))
        self.invoke("preview", "accept", "draft-v001")
        final_one = self.root / "final-one.mp4"
        final_one.write_bytes(b"final-one")

        self.invoke("finalize", str(final_one), "--qa-passed")
        self.assertEqual(b"final-one", (work / "variants" / "main" / "final" / "final.mp4").read_bytes())
        self.assertEqual("active", WORK_CLI.locate_work(self.root, work_id)[1])
        self.assertEqual("active", WORK_CLI.read_json(work / "variants/main/variant.yaml")["lifecycle"])
        manifest_path = work / "variants" / "main" / "final" / "manifest.json"
        first_manifest = manifest_path.read_bytes()
        first_receipt = WORK_CLI.file_sha256(manifest_path)

        active_final = Path(self.invoke("finalize", str(final_one), "--qa-passed"))
        self.assertTrue(active_final.is_file())
        self.assertIn("/alpha/", active_final.as_posix())
        self.assertEqual(first_manifest, (active_final.parent / "manifest.json").read_bytes())
        active_variant = active_final.parent.parent
        receipt_path = active_variant / ".runtime" / "finalize.json"
        receipt = WORK_CLI.read_json(receipt_path)
        receipt["state"] = "promoted"
        WORK_CLI.write_json(receipt_path, receipt)
        (self.root / ".studio" / ".runtime" / "current-work").write_text(work_id, encoding="utf-8")
        (self.root / ".studio" / ".runtime" / "current-variant").write_text("main", encoding="utf-8")
        with mock.patch.object(WORK_CLI, "command_finalize_video", side_effect=AssertionError("must reuse promoted Final")):
            self.assertEqual(str(active_final), self.invoke("--work", work_id, "finalize", str(final_one), "--qa-passed"))
        self.assertEqual("complete", json.loads((active_variant / ".runtime" / "finalize.json").read_text())["state"])
        self.assertTrue((self.root / ".studio" / ".runtime" / "current-work").exists())
        self.assertEqual([], list((active_final.parent / "history").glob("*/manifest.json")))

        self.assertEqual(b"final-one", active_final.read_bytes())
        final_two = self.root / "final-two.mp4"
        final_two.write_bytes(b"final-two")
        second = Path(self.invoke("finalize", str(final_two), "--qa-passed"))
        history = second.parent / "history" / first_receipt
        self.assertEqual(b"final-one", (history / "final.mp4").read_bytes())
        self.assertEqual(first_manifest, (history / "manifest.json").read_bytes())
        self.assertEqual(b"final-two", second.read_bytes())
        self.assertEqual("active", WORK_CLI.locate_work(self.root, work_id)[1])
        self.assertEqual(str(second), self.invoke("finalize", str(final_two), "--qa-passed"))
        self.assertEqual([history], list((second.parent / "history").iterdir()))

    def test_finalize_accepts_legacy_digest_with_identical_render_mirror(self) -> None:
        _, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke("preview", "register", str(draft))
        self.invoke("preview", "accept", "draft-v001")
        variant = work / "variants" / "main"
        preview = variant / "previews" / "draft-v001"
        metadata = WORK_CLI.preview_metadata(preview)
        frozen = variant / ".runtime" / "render-legacy" / "source-snapshot"
        shutil.copytree(preview / "source-snapshot", frozen)
        candidate = self.root / "legacy-final.mp4"
        candidate.write_bytes(b"legacy-final")
        state = json.loads((variant / "variant.yaml").read_text(encoding="utf-8"))
        state["accepted_visual_plan"] = "plan-v001"
        (variant / "variant.yaml").write_text(json.dumps(state), encoding="utf-8")
        WORK_CLI.write_json(
            variant / ".runtime" / "render.json",
            {
                "purpose": "final",
                "source_preview": "draft-v001",
                "parent_snapshot_sha256": metadata["snapshot_sha256"],
                "snapshot_sha256": metadata["snapshot_sha256"],
                "source_snapshot": ".runtime/render-legacy/source-snapshot",
                "changed_files": [],
                "output_sha256": WORK_CLI.file_sha256(candidate),
                "script_revision": 1,
                "plan_revision": 1,
            },
        )

        with mock.patch.object(WORK_CLI, "snapshot_digest", return_value="f" * 64):
            promoted_final = Path(self.invoke("finalize", str(candidate), "--qa-passed"))

        evidence = json.loads(
            (promoted_final.parent.parent / ".runtime" / "qa" / "legacy-snapshot-compatibility.json").read_text()
        )
        self.assertEqual(metadata["snapshot_sha256"], evidence["recorded_snapshot_sha256"])
        self.assertEqual("f" * 64, evidence["current_snapshot_sha256"])
        self.assertGreater(evidence["verified_file_count"], 0)

    def test_finalize_rejects_legacy_digest_when_render_mirror_differs(self) -> None:
        _, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke("preview", "register", str(draft))
        self.invoke("preview", "accept", "draft-v001")
        variant = work / "variants" / "main"
        preview = variant / "previews" / "draft-v001"
        metadata = WORK_CLI.preview_metadata(preview)
        frozen = variant / ".runtime" / "render-legacy" / "source-snapshot"
        shutil.copytree(preview / "source-snapshot", frozen)
        (frozen / "index.html").write_text("changed", encoding="utf-8")
        candidate = self.root / "legacy-final.mp4"
        candidate.write_bytes(b"legacy-final")
        state = json.loads((variant / "variant.yaml").read_text(encoding="utf-8"))
        state["accepted_visual_plan"] = "plan-v001"
        (variant / "variant.yaml").write_text(json.dumps(state), encoding="utf-8")
        WORK_CLI.write_json(
            variant / ".runtime" / "render.json",
            {
                "purpose": "final",
                "source_preview": "draft-v001",
                "parent_snapshot_sha256": metadata["snapshot_sha256"],
                "snapshot_sha256": metadata["snapshot_sha256"],
                "source_snapshot": ".runtime/render-legacy/source-snapshot",
                "changed_files": [],
                "output_sha256": WORK_CLI.file_sha256(candidate),
                "script_revision": 1,
                "plan_revision": 1,
            },
        )
        with mock.patch.object(WORK_CLI, "snapshot_digest", return_value="f" * 64):
            result = self.invoke("finalize", str(candidate), "--qa-passed", expected=2)
        self.assertIn("legacy final-render snapshot differs", result)
        self.assertTrue(work.is_dir())

    def test_finalize_stays_active_until_each_variant_is_explicitly_archived(self) -> None:
        work_id, work = self.new_work()
        self.invoke("variant", "add", "bilibili-16x9", "--from", "main", "--ratio", "16:9")

        for variant_id in ("main", "bilibili-16x9"):
            self.invoke("variant", "use", variant_id)
            draft = self.prepare_preview(work, variant_id, content=variant_id.encode())
            self.invoke("preview", "register", str(draft))
            self.invoke("preview", "accept", "draft-v001")
            final = self.root / f"{variant_id}-final.mp4"
            final.write_bytes((variant_id + "-final").encode())
            output = Path(self.invoke("finalize", str(final), "--qa-passed"))
            self.assertIn("/alpha/", output.as_posix())
            self.assertEqual("active", WORK_CLI.read_json(work / "variants" / variant_id / "variant.yaml")["lifecycle"])
            if variant_id == "main":
                self.assertEqual("active", WORK_CLI.locate_work(self.root, work_id)[1])
                self.assertEqual("active", WORK_CLI.read_json(work / "variants/bilibili-16x9/variant.yaml")["lifecycle"])
            self.invoke("--variant", variant_id, "archive")
            if variant_id == "main":
                self.assertEqual("archived", WORK_CLI.read_json(work / "variants/main/variant.yaml")["lifecycle"])
                self.assertEqual("active", WORK_CLI.locate_work(self.root, work_id)[1])

        archived, location = WORK_CLI.locate_work(self.root, work_id)
        self.assertEqual("archive", location)
        self.assertEqual("archived", WORK_CLI.read_json(archived / "variants/bilibili-16x9/variant.yaml")["lifecycle"])
        self.assertEqual(work, archived)
        self.assertTrue((archived / "variants" / "main" / "final" / "final.mp4").is_file())

    def test_final_manifest_failure_restores_prior_video_metadata_and_state(self):
        _, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke("preview", "register", str(draft))
        self.invoke("preview", "accept", "draft-v001")
        first, second = self.root / "one.mp4", self.root / "two.mp4"
        first.write_bytes(b"original")
        second.write_bytes(b"replacement")
        self.invoke("finalize", str(first), "--qa-passed")
        variant = work / "variants/main"
        paths = [variant / name for name in ("final/final.mp4", "final/manifest.json", "variant.yaml")]
        before = [path.read_bytes() for path in paths]
        original_write = WORK_CLI.write_json
        def fail_manifest(path, data):
            if path == variant / "final/manifest.json":
                raise OSError("injected manifest write failure")
            original_write(path, data)
        with mock.patch.object(WORK_CLI, "write_json", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "injected manifest"):
                self.invoke("finalize", str(second), "--qa-passed")
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.assertTrue((variant / ".runtime/final-promotion/restored.json").is_file())
        original_replace = WORK_CLI.os.replace
        def fail_commit(source, target):
            if Path(target).name == "committed.json":
                raise OSError("injected commit marker failure")
            original_replace(source, target)
        with mock.patch.object(WORK_CLI.os, "replace", side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, "commit marker"):
                self.invoke("finalize", str(second), "--qa-passed")
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.invoke("finalize", str(second), "--qa-passed")
        self.assertEqual(b"replacement", paths[0].read_bytes())


    def test_finalize_writes_package_description_and_reuses_bytes(self):
        work_id, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        document = work / 'WORK.md'
        document.write_text(document.read_text(encoding='utf-8') + '\n- 作品简介：xxx\n', encoding='utf-8')
        final_source = self.root / 'final-package.mp4'
        final_source.write_bytes(b'final package fixture')
        final = Path(self.invoke('finalize', str(final_source), '--qa-passed')).parent
        package = WORK_CLI.read_json(final / 'package.json')
        self.assertEqual('xxx\n', (final / '简介.md').read_text(encoding='utf-8'))
        self.assertEqual(WORK_CLI.file_sha256(final / '简介.md'), package['description']['sha256'])
        state = WORK_CLI.read_json(final.parent / 'variant.yaml')
        if state.get('current_cover'):
            cover = WORK_CLI.storage.scoped_path(final.parent, state['current_cover'])
            self.assertEqual(cover.read_bytes(), (final / cover.name).read_bytes())
        else:
            self.assertIn('cover', package['missing'])
        self.assertEqual(package, WORK_CLI.read_json(final.parent / '.runtime/finalize.json')['package'])
        original = (final / 'package.json').read_bytes()
        self.invoke('--work', work_id, 'finalize', str(final_source), '--qa-passed')
        self.assertEqual(original, (final / 'package.json').read_bytes())

    def test_final_package_work_sources_cleanup_and_collisions(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        first, second = work / 'first.png', work / 'second.webp'
        first.write_bytes(b'first cover')
        second.write_bytes(b'second cover')
        document = work / 'WORK.md'
        original = document.read_text(encoding='utf-8')
        document.write_text(original + '\n- 封面: `first.png` `missing.jpg` `second.webp`\n'
                            '- 封面：`ignored.png`\n- 作品简介: description\n', encoding='utf-8')
        package = WORK_CLI.write_final_package(work, variant, {})
        final = variant / 'final'
        self.assertEqual(['first.png', 'second.webp'], [item['file'] for item in package['covers']])
        self.assertEqual(['first.png', 'second.webp'], [item['source'] for item in package['covers']])
        self.assertEqual([], package['missing'])
        stamp = (final / 'first.png').stat().st_mtime_ns
        self.assertEqual(package, WORK_CLI.write_final_package(work, variant, {}))
        self.assertEqual(stamp, (final / 'first.png').stat().st_mtime_ns)
        (final / 'manifest.json').write_bytes(b'bound manifest')
        (final / 'unknown.png').write_bytes(b'keep unknown')
        document.write_text(original + '\n- 封面：`second.webp`\n', encoding='utf-8')
        reduced = WORK_CLI.write_final_package(work, variant, {})
        self.assertEqual(['description'], reduced['missing'])
        self.assertFalse((final / 'first.png').exists())
        self.assertFalse((final / '简介.md').exists())
        self.assertEqual(b'bound manifest', (final / 'manifest.json').read_bytes())
        self.assertEqual(b'keep unknown', (final / 'unknown.png').read_bytes())
        other = work / 'other'
        other.mkdir()
        (other / 'second.webp').write_bytes(b'different source')
        document.write_text(original + '\n- 封面：`second.webp` `other/second.webp`\n', encoding='utf-8')
        with self.assertRaises(WORK_CLI.HarnessError):
            WORK_CLI.write_final_package(work, variant, {})
        self.assertEqual(b'second cover', (final / 'second.webp').read_bytes())
        (work / 'unknown.png').write_bytes(b'new unknown')
        document.write_text(original + '\n- 封面：`unknown.png`\n', encoding='utf-8')
        with self.assertRaises(WORK_CLI.HarnessError):
            WORK_CLI.write_final_package(work, variant, {})
        self.assertEqual(b'keep unknown', (final / 'unknown.png').read_bytes())
        with self.assertRaises(WORK_CLI.HarnessError):
            WORK_CLI.write_final_package(work, variant, {'current_cover': 'final/manifest.json'})

    def test_final_package_current_cover_has_priority_and_updates(self):
        _, work = self.new_work()
        variant = work / 'variants/main'
        source = variant / 'chosen.png'
        source.write_bytes(b'chosen')
        (work / 'fallback.jpg').write_bytes(b'fallback')
        document = work / 'WORK.md'
        document.write_text(document.read_text(encoding='utf-8') + '\n- 封面：`fallback.jpg`\n', encoding='utf-8')
        state = {'current_cover': 'chosen.png'}
        first = WORK_CLI.write_final_package(work, variant, state)
        self.assertEqual(['chosen.png'], [item['file'] for item in first['covers']])
        self.assertEqual('chosen.png', first['covers'][0]['source'])
        source.write_bytes(b'updated')
        second = WORK_CLI.write_final_package(work, variant, state)
        self.assertNotEqual(first['covers'][0]['sha256'], second['covers'][0]['sha256'])
        self.assertEqual(b'updated', (variant / 'final/chosen.png').read_bytes())

    def test_index_cover_publish_without_final_writes_nothing(self):
        import argparse
        _, work = self.new_work()
        variant = work / 'variants/main'
        (variant / 'cover.png').write_bytes(b'cover')
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with mock.patch.object(WORK_CLI, 'selected_work', return_value=(work, 'active')), \
                mock.patch.object(WORK_CLI, 'selected_variant', return_value=(variant, {'current_cover': 'cover.png'})), \
                mock.patch.dict(WORK_CLI.os.environ, {'HYPERFRAMES_AI_RESOLVED_CONFIG': '{"export_mode":"index"}'}):
            with self.assertRaisesRegex(WORK_CLI.HarnessError, '^Index export needs a Final; run finalize first$'):
                WORK_CLI.command_cover(self.root, argparse.Namespace(cover_command='export'))
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((variant / 'final').exists())
        self.assertFalse((self.root / 'exports').exists())

    def test_index_finalize_and_cover_publish_use_final_package(self):
        import cover
        work_id, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        variant = work / 'variants/main'
        (variant / 'chosen.png').write_bytes(b'cover fixture')
        state = WORK_CLI.read_json(variant / 'variant.yaml')
        state['current_cover'] = 'chosen.png'
        WORK_CLI.write_variant(variant, state)
        final_source = self.root / 'index-final.mp4'
        final_source.write_bytes(b'final fixture')
        with mock.patch.dict(WORK_CLI.os.environ, {'HYPERFRAMES_AI_RESOLVED_CONFIG': '{"export_mode":"index"}'}), \
                mock.patch.object(cover, 'verify'):
            final = Path(self.invoke('finalize', str(final_source), '--qa-passed')).parent
            receipt = WORK_CLI.read_json(final.parent / '.runtime/finalize.json')['export']
            self.assertEqual(str(final), receipt['directory'])
            self.assertEqual({'video': 'final.mp4', 'cover': 'chosen.png'}, receipt['files'])
            self.assertEqual(b'cover fixture', (final / 'chosen.png').read_bytes())
            (final.parent / 'chosen.png').write_bytes(b'new cover')
            self.invoke('--work', work_id, 'cover', 'export')
        self.assertEqual(b'new cover', (final / 'chosen.png').read_bytes())
        episodes = WORK_CLI.read_json(self.root / 'exports/.exports.json')['episodes']
        episode = next(iter(episodes.values()))
        self.assertEqual(2, episode['version'])
        current = {item['role']: item for item in episode['files'] if item['current']}
        self.assertEqual({'video', 'cover'}, set(current))
        for item in current.values():
            self.assertTrue(item['indexed'])
            self.assertEqual(final, (self.root / item['file']).parent)
        self.assertFalse((self.root / 'exports/main').exists())


    def test_cover_export_replaces_managed_cover_from_new_render(self):
        import cover
        work_id, work = self.new_work()
        draft = self.prepare_preview(work)
        self.invoke('preview', 'register', str(draft))
        self.invoke('preview', 'accept', 'draft-v001')
        variant = work / 'variants/main'
        # Model two render outputs with the same basename in distinct render directories.
        first = variant / 'covers/render-one/cover.png'
        first.parent.mkdir(parents=True)
        first.write_bytes(b'first rendered cover')
        state = WORK_CLI.read_json(variant / 'variant.yaml')
        state['current_cover'] = first.relative_to(variant).as_posix()
        WORK_CLI.write_variant(variant, state)
        video = self.root / 'cover-replacement-final.mp4'
        video.write_bytes(b'final fixture')
        with mock.patch.object(cover, 'verify'):
            final = Path(self.invoke('finalize', str(video), '--qa-passed')).parent
            old_package = WORK_CLI.read_json(final / 'package.json')
            manifest = (final / 'manifest.json').read_bytes()
            second = final.parent / 'covers/render-two/cover.png'
            second.parent.mkdir(parents=True)
            second.write_bytes(b'second rendered cover')
            state = WORK_CLI.read_json(final.parent / 'variant.yaml')
            state['current_cover'] = second.relative_to(final.parent).as_posix()
            WORK_CLI.write_variant(final.parent, state)
            with mock.patch.object(WORK_CLI.os, 'replace', wraps=WORK_CLI.os.replace) as replace:
                self.invoke('--work', work_id, 'cover', 'export')
            cover_replacements = [call.args for call in replace.call_args_list
                                  if Path(call.args[1]) == final / 'cover.png']
            self.assertEqual(1, len(cover_replacements))
            self.assertEqual(final, Path(cover_replacements[0][0]).parent)
        package = WORK_CLI.read_json(final / 'package.json')
        self.assertEqual(b'second rendered cover', (final / 'cover.png').read_bytes())
        self.assertEqual('covers/render-two/cover.png', package['covers'][0]['source'])
        self.assertEqual(WORK_CLI.file_sha256(second), package['covers'][0]['sha256'])
        self.assertNotEqual(old_package['covers'][0]['sha256'], package['covers'][0]['sha256'])
        self.assertEqual(manifest, (final / 'manifest.json').read_bytes())
        self.assertEqual(b'final fixture', (final / 'final.mp4').read_bytes())


if __name__ == "__main__":
    unittest.main()
