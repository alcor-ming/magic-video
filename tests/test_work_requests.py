from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("request_work", REPO / ".studio" / "work.py")
WORK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WORK)
REQUEST = WORK.work_requests


class RequestTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / "store"
        for name in ("active", "parked", "archive"):
            (self.store / "works" / name).mkdir(parents=True)
        self.work = self.store / "works" / "active" / "work-hyperframes_video-001"
        self.variant = self.work / "variants" / "main"
        self.project = self.variant / "project"
        self.project.mkdir(parents=True)
        (self.project / "scene.html").write_text("before")
        (self.project / "other.html").write_text("unaffected")
        (self.work / "WORK.md").write_text('---\nworkflow: "hyperframes_video"\n---\n')
        WORK.write_variant(self.variant, {"accepted_preview": "draft-001", "status": "active"})
        self.brief = self.root / "brief.md"
        self.brief.write_text("Real input: improve S01; preserve S02.")
        self.revision = REQUEST.freeze(self.store, self.work, self.variant, "gap-001", self.brief,
                                       ["S01"], ["scene.html", "new.js"], ["other.html"])
        self.source = self.root / "patch"
        self.source.mkdir()
        (self.source / "scene.html").write_text("candidate")
        (self.source / "new.js").write_text("new")
        self.delivery = REQUEST.deliver(self.revision, "c001", self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_roundtrip_preserves_other_work_and_acceptance(self):
        exported = REQUEST.export_request(self.revision, self.root / "private-repro")
        self.assertEqual(REQUEST.digest(self.revision / "request.json"), REQUEST.digest(exported / "request.json"))
        review = REQUEST.review(self.store, self.revision, self.delivery, WORK.read_json, WORK.write_variant)
        self.assertEqual("before", (self.project / "scene.html").read_text())
        self.assertFalse((self.store / ".runtime" / "current-work").exists())
        review_variant = review / "works" / "active" / self.work.name / "variants" / "main"
        self.assertTrue((review_variant / "project" / "compositions").is_dir())
        self.assertIsNone(WORK.read_json(review_variant / "variant.yaml")["accepted_preview"])
        self.assertEqual("candidate", (review_variant / "project" / "scene.html").read_text())
        (self.project / "other.html").write_text("ongoing production edit")
        receipt = REQUEST.accept(self.store, self.revision, self.delivery, self.variant)
        self.assertEqual("accepted", REQUEST.read(receipt)["decision"])
        self.assertEqual("ongoing production edit", (self.project / "other.html").read_text())
        self.assertEqual("candidate", (self.project / "scene.html").read_text())
        self.assertEqual("draft-001", WORK.read_json(self.variant / "variant.yaml")["accepted_preview"])

    def test_stale_affected_file_and_tampered_delivery_fail_before_writes(self):
        (self.project / "scene.html").write_text("new baseline")
        with self.assertRaisesRegex(REQUEST.RequestError, "Affected file changed"):
            REQUEST.accept(self.store, self.revision, self.delivery, self.variant)
        self.assertFalse((self.project / "new.js").exists())
        (self.delivery / "patch" / "scene.html").write_text("tampered")
        with self.assertRaisesRegex(REQUEST.RequestError, "Frozen handoff changed"):
            REQUEST.checked_pair(self.revision, self.delivery)

    def test_failed_acceptance_receipt_restores_affected_files(self):
        REQUEST.review(self.store, self.revision, self.delivery, WORK.read_json, WORK.write_variant)
        with patch.object(REQUEST, "write", side_effect=OSError("receipt write failed")):
            with self.assertRaisesRegex(OSError, "receipt write failed"):
                REQUEST.accept(self.store, self.revision, self.delivery, self.variant)
        self.assertEqual("before", (self.project / "scene.html").read_text())
        self.assertFalse((self.project / "new.js").exists())

    def test_revisions_scope_and_link_boundaries(self):
        newer = REQUEST.freeze(self.store, self.work, self.variant, "gap-001", self.brief, ["S01"], ["scene.html"], [])
        self.assertEqual("r002", newer.name)
        with self.assertRaisesRegex(REQUEST.RequestError, "exact request revision"):
            REQUEST.checked_pair(newer, self.delivery)
        (self.source / "other.html").write_text("out of scope")
        with self.assertRaisesRegex(REQUEST.RequestError, "outside"):
            REQUEST.deliver(self.revision, "c002", self.source)
        with self.assertRaises(REQUEST.RequestError):
            REQUEST.safe(self.project, "../variant.yaml")
        (self.project / "linked").symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(REQUEST.RequestError):
            REQUEST.safe(self.project, "linked/scene.html")

    def test_review_never_uses_production_and_forbids_promotion(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch.dict(os.environ, {"HYPERFRAMES_AI_WORK_ROOT": str(self.store), "HYPERFRAMES_AI_REVIEW": "1"}):
                self.assertEqual(2, WORK.main(["root", "show"], root=self.root))
        review = REQUEST.review(self.store, self.revision, self.delivery, WORK.read_json, WORK.write_variant)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch.dict(os.environ, {"HYPERFRAMES_AI_WORK_ROOT": str(review), "HYPERFRAMES_AI_REVIEW": "1"}):
                for args in (["finalize", "x.mp4"], ["preview", "accept", "plan-001"], ["archive", "--outcome", "abandoned"],
                             ["preview", "render", "plan-001", "--final", "--output", "x.mp4"]):
                    self.assertEqual(2, WORK.main(args, root=self.root))
        self.assertFalse((self.store / ".runtime" / "current-work").exists())
        (self.root / ".release.json").write_text(json.dumps({"channel": "candidate"}))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch.dict(os.environ, {"HYPERFRAMES_AI_WORK_ROOT": str(self.store), "HYPERFRAMES_AI_REVIEW": "0"}):
                self.assertEqual(2, WORK.main(["archive", "--outcome", "abandoned"], root=self.root))
                self.assertEqual(0, WORK.main(["review", "init", "candidate-bootstrap"], root=self.root))
        self.assertTrue((self.store / "review/candidate-bootstrap/.runtime/review.json").is_file())
        self.assertFalse((self.store / ".runtime/current-work").exists())

    def test_external_config_and_pinned_runtime(self):
        config = self.root / "config.json"
        config.write_text(json.dumps({"work_root": str(self.store), "provider": "preserve"}))
        with patch.dict(os.environ, {"HYPERFRAMES_AI_CONFIG": str(config), "HYPERFRAMES_AI_WORK_ROOT": ""}):
            self.assertEqual(self.store, WORK.configured_work_root(self.root))
        with patch.dict(os.environ, {"HYPERFRAMES_DIST": str(self.root / "dist")}):
            self.assertEqual(self.root / "dist", WORK.runtime_path(None, "HYPERFRAMES_DIST"))
            with self.assertRaises(WORK.HarnessError):
                WORK.runtime_path(str(self.root / "other"), "HYPERFRAMES_DIST")

    def test_harness_review_can_create_test_work_without_production_pointer(self):
        shutil.copytree(REPO / ".studio" / "templates", self.root / ".studio" / "templates")
        review = REQUEST.init_review(self.store, "native-smoke")
        with patch.dict(os.environ, {"HYPERFRAMES_AI_WORK_ROOT": str(review), "HYPERFRAMES_AI_REVIEW": "1"}):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, WORK.main(["new", "Native test", "--workflow", "hyperframes_video",
                                               "--design", "stage-full"], root=self.root))
        self.assertTrue((review / ".runtime" / "current-work").is_file())
        self.assertFalse((self.store / ".runtime" / "current-work").exists())

    def test_component_approval_changes_only_status_not_implementation(self):
        import component_harness as component
        approved = REPO / "tests" / "fixtures" / "components" / "chapter-intro" / "v1"
        package = self.root / "component"
        shutil.copytree(approved, package)
        metadata = package / "COMPONENT.md"
        metadata.write_text(metadata.read_text(encoding="utf-8").replace("library-approved", "migration-ready"), encoding="utf-8")
        component.write_hashes(package)
        release = component.validate_component_release(package, allow_unapproved=True)
        binding = self.root / "binding.json"
        REQUEST.write(binding, {"schema_version": 1, "component_ref": release["component_ref"], "scene": "S01",
                                "slots": release["fixture"]["slots"], "surfaces": release["fixture"]["surfaces"],
                                "placement": {"width": 1440, "height": 1080}, "assets": {},
                                "timing": {"offset": 0, "time_scale": 1, "hero_hold": 0, "handoff_hold": 0}})
        delivery = REQUEST.deliver(self.revision, "component-001", self.source, package, binding)
        with self.assertRaisesRegex(REQUEST.RequestError, "library-approved"):
            REQUEST.accept(self.store, self.revision, delivery, self.variant)
        review = REQUEST.review(self.store, self.revision, delivery, WORK.read_json, WORK.write_variant)
        self.assertTrue(REQUEST.review_identity(review)["ready"])
        REQUEST.accept(self.store, self.revision, delivery, self.variant, approved)
        result = component.verify_installation(self.project)
        self.assertEqual(release["component_ref"], result["components"][0]["component_ref"])


if __name__ == "__main__":
    unittest.main()
