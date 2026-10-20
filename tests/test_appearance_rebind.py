import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_work_appearance as fixtures
import appearance
import appearance_rebind

cli = fixtures.cli


class AppearanceRebindTest(unittest.TestCase):
    asset = fixtures.WorkAppearanceTest.asset
    invoke = fixtures.WorkAppearanceTest.invoke

    def setUp(self):
        fixtures.WorkAppearanceTest.setUp(self)
        self.work_id = self.invoke("new", "Rebind", "--workflow", "hyperframes_video", "--account", "a")
        self.work, _ = cli.locate_work(self.root, self.work_id)
        self.variant = self.work / "variants/main"
        (self.variant / "project/index.html").write_text('<div id="S01">Keep approved text</div>')
        self.before = self.contents()

    def contents(self):
        return {p.relative_to(self.variant).as_posix(): p.read_bytes() for p in self.variant.rglob("*")
                if p.is_file() and ".runtime" not in p.relative_to(self.variant).parts}

    def update(self, *args):
        return json.loads(self.invoke("--work", self.work_id, "--variant", "main", "appearance", "rebind",
                                      "--background", "green@v1", *args))

    def drift_checks(self):
        state = cli.read_json(self.variant / "variant.yaml")
        lock = state["appearance_lock"]
        lock.pop("mode", None)
        lock["capabilities"] = cli.designs.legacy_capabilities("explainer")
        lock["capabilities"]["checks"] = []
        self.seal(lock)
        cli.write_json(self.variant / "project/appearance-lock.json", lock)
        lock["capabilities"]["checks"] = ["css-contract", "frame-blank"]
        self.seal(lock)
        state["capabilities"] = lock["capabilities"]
        cli.write_variant(self.variant, state)
        return state

    def seal(self, lock):
        lock["capabilities_sha256"] = appearance.digest(lock["capabilities"])
        lock["sha256"] = appearance.digest({k: v for k, v in lock.items() if k != "sha256"})

    def recover_checks(self):
        return json.loads(self.invoke("--work", self.work_id, "--variant", "main",
                                      "appearance", "recover", "--sync-checks"))

    def test_sync_checks_preserves_every_other_file_and_is_idempotent(self):
        state = self.drift_checks()
        state.update(accepted_visual_plan="plan-v006", accepted_plan_revision=6,
                     accepted_preview="draft-v001", current_final="final.mp4")
        cli.write_variant(self.variant, state)
        for name in ("audio/voice.wav", "captions/subtitles.srt", "previews/draft-v001/source-snapshot/index.html"):
            path = self.variant / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"preserved fixture")
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "differs from Variant"):
            appearance.verify(self.variant / "project", state["appearance_lock"])
        result = self.recover_checks()
        self.assertEqual("checks-synced", result["status"])
        appearance.verify(self.variant / "project", state["appearance_lock"])
        for name, content in before.items():
            if name != "project/appearance-lock.json":
                self.assertEqual(content, (self.variant / name).read_bytes(), name)
        self.assertEqual(before["project/appearance-lock.json"],
                         (Path(result["history"]) / "appearance-lock.json").read_bytes())
        self.assertEqual("unchanged", self.recover_checks()["status"])

    def test_registration_passes_lock_gate_after_sync(self):
        self.drift_checks()
        # Stop at the next gate: this fixture has no complete video project.
        with patch.object(cli, "assert_preview_ready"), patch.object(cli, "assert_snapshot_source",
                side_effect=cli.HarnessError("reached source validation")):
            with self.assertRaisesRegex(appearance.AppearanceError, "differs from Variant"):
                self.invoke("--work", self.work_id, "--variant", "main", "preview", "register")
            self.recover_checks()
            with self.assertRaisesRegex(cli.HarnessError, "reached source validation"):
                self.invoke("--work", self.work_id, "--variant", "main", "preview", "register")

    def test_sync_write_failure_and_removed_checks_preserve_original(self):
        state = self.drift_checks()
        before = self.contents()
        with patch.object(cli.os, "replace", side_effect=OSError("injected atomic replace failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.recover_checks()
        self.assertEqual(before, self.contents())

        self.recover_checks()
        state["appearance_lock"]["capabilities"]["checks"] = []
        self.seal(state["appearance_lock"])
        cli.write_variant(self.variant, state)
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "only permits added checks"):
            self.recover_checks()
        self.assertEqual(before, self.contents())

    def test_sync_checks_requires_pending_rebind_recovery_first(self):
        self.drift_checks()
        cli.write_json(appearance_rebind.journal_path(self.variant), {})
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "without --sync-checks first"):
            self.recover_checks()
        self.assertEqual(before, self.contents())

    def test_sync_checks_rejects_other_drift_corruption_and_running_studio(self):
        state = self.drift_checks()
        state["appearance_lock"]["seed"] += 1
        self.seal(state["appearance_lock"])
        cli.write_variant(self.variant, state)
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "only permits added checks"):
            self.recover_checks()
        self.assertEqual(before, self.contents())
        state["appearance_lock"]["seed"] -= 1
        self.seal(state["appearance_lock"])
        cli.write_variant(self.variant, state)
        cli.write_json(cli.studio_record(self.variant, "current"), {"pid": os.getpid()})
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "Stop"):
            self.recover_checks()
        self.assertEqual(before, self.contents())
        state["appearance_lock"]["sha256"] = "0" * 64
        cli.write_variant(self.variant, state)
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "hash mismatch"):
            self.recover_checks()
        self.assertEqual(before, self.contents())

    def test_preview_apply_history_acceptance_and_idempotency(self):
        state = cli.read_json(self.variant / "variant.yaml")
        state.update(accepted_visual_plan="plan-v001", accepted_preview="draft-v001", current_final="final.mp4")
        cli.write_variant(self.variant, state)
        for name in ("previews/plan-v001/source-snapshot/index.html", "previews/draft-v001/source-snapshot/index.html", "final/final.mp4"):
            path = self.variant / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"historical fixture, not generated video")
        before = self.contents()
        self.assertEqual("preview", self.update()["status"])
        self.assertEqual(before, self.contents())
        result = self.update("--apply")
        self.assertEqual("rebound", result["status"])
        after = cli.read_json(self.variant / "variant.yaml")
        self.assertEqual("main", after["id"])
        metadata = cli.read_frontmatter(self.variant / 'ANIMATION_PLAN.md')
        self.assertEqual(after['appearance_lock']['selection']['background'], metadata['background'])
        self.assertEqual(after['appearance_lock']['sha256'], metadata['appearance_lock_sha256'])
        self.assertEqual(after['plan_revision'], metadata['revision'])
        self.assertEqual(before['ANIMATION_PLAN.md'].decode().split('## 导演 Brief', 1)[1],
                         (self.variant / 'ANIMATION_PLAN.md').read_text().split('## 导演 Brief', 1)[1])
        for field in ("accepted_visual_plan", "accepted_preview", "accepted_plan_revision", "accepted_script_revision", "current_final"):
            self.assertIsNone(after[field])
        self.assertEqual("final.mp4", after["appearance_history"][-1]["current_final"])
        for name, content in before.items():
            if name in ("SCRIPT.md", "project/index.html") or name.startswith(("previews/", "final/")):
                self.assertEqual(content, (self.variant / name).read_bytes())
        self.assertEqual(before["variant.yaml"], (Path(result["history"]) / "variant.yaml").read_bytes())
        appearance.verify(self.variant / "project", after["appearance_lock"])
        stable = self.contents()
        self.assertEqual("unchanged", self.update("--apply")["status"])
        self.assertEqual(stable, self.contents())

    def test_frozen_account_motion_carries_forward_but_cannot_be_added(self):
        # 旧 Work 的冻结锁带一个账号动作槽：重绑原样带过去、可关闭，但不能新加或换成别的动作。
        stamp = self.asset("stamp", "motion", {"slots": {"reveal": {"duration": 0.2, "easing": "linear"}}, "reduced_motion": {}})
        state = cli.read_json(self.variant / "variant.yaml")
        old = state["appearance_lock"]
        frozen = {"reveal": {"asset": stamp, "entry": "reveal"}}
        lock = appearance.resolve(self.root, state["account_settings"],
                                  {**{key: old[key] for key in ("ratio", "width", "height", "fps", "seed") if key in old},
                                   "capabilities": old["capabilities"], "captions": old["selection"].get("captions", False)},
                                  legacy_motion=frozen)
        appearance.materialize(self.root, self.variant / "project", lock)
        state.update(appearance_lock=lock, motion=lock["selection"]["motion"])
        cli.write_variant(self.variant, state)
        self.assertEqual("rebound", self.update("--apply")["status"])
        after = cli.read_json(self.variant / "variant.yaml")["appearance_lock"]
        self.assertEqual(lock["selection"]["motion"], after["selection"]["motion"])
        appearance.verify(self.variant / "project", after)
        choice = self.base / "motion-choice.json"
        choice.write_text(json.dumps({"motion": {"exit": {"asset": stamp, "entry": "reveal"}}}))
        with self.assertRaisesRegex(appearance.AppearanceError, "Account-level Motion is retired"):
            self.update("--appearance-file", str(choice))
        with self.assertRaisesRegex(cli.HarnessError, "Account-level Motion is retired"):
            cli.account_service(self.root).put("account", "b", {**self.account, "motion": {"reveal": frozen["reveal"]}})
        cli.account_service(self.root).put("account", "c", {**self.account, "motion": dict.fromkeys(appearance.SLOTS)})
        choice.write_text(json.dumps({"motion": {"reveal": None}}))
        self.update("--appearance-file", str(choice), "--apply")
        self.assertIsNone(cli.read_json(self.variant / "variant.yaml")["appearance_lock"]["selection"]["motion"]["reveal"])

    def test_prepare_failure_and_unknown_runtime_do_not_touch_original(self):
        with patch.object(appearance, "materialize", side_effect=appearance.AppearanceError("injected second asset failure")):
            with self.assertRaisesRegex(appearance.AppearanceError, "injected"):
                self.update("--apply")
        self.assertEqual(self.before, self.contents())
        runtime = self.variant / "project/runtime/appearance.js"
        runtime.write_text("user-customized-runtime")
        before = self.contents()
        with self.assertRaisesRegex(appearance.AppearanceError, "user-modified"):
            self.update("--apply", "--upgrade-runtime")
        self.assertEqual(before, self.contents())

    def test_mode_switch_defaults_captions_without_mutating_preview(self):
        preview = self.update("--mode", "explainer")
        self.assertTrue(preview["changes"]["selection"]["after"]["captions"])
        self.assertEqual(self.before, self.contents())
        preview = self.update("--mode", "explainer", "--captions", "off")
        self.assertFalse(preview["changes"]["selection"]["after"]["captions"])

    def test_commit_failure_rolls_back_and_interruption_requires_recovery(self):
        plan = self.variant / "ANIMATION_PLAN.md"
        plan.write_bytes(plan.read_bytes().replace(b"\n", b"\r\n"))
        self.before = self.contents()
        write = cli.atomic_write
        count = 0

        def fail_once(path, text):
            nonlocal count
            if path == self.variant / "variant.yaml" and count == 0:
                count += 1
                raise OSError("injected variant write failure")
            return write(path, text)

        with patch.object(cli, "atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected"):
                self.update("--apply")
        self.assertEqual(self.before, self.contents())

        def interrupt(path, text):
            if path == self.variant / "variant.yaml":
                raise SystemExit("injected process exit")
            return write(path, text)

        with patch.object(cli, "atomic_write", side_effect=interrupt):
            with self.assertRaises(SystemExit):
                self.update("--apply")
        self.assertTrue(appearance_rebind.journal_path(self.variant).is_file())
        with self.assertRaisesRegex(cli.HarnessError, "recovery pending"):
            self.invoke("--work", self.work_id, "--variant", "main", "status")
        result = json.loads(self.invoke("--work", self.work_id, "--variant", "main", "appearance", "recover"))
        self.assertEqual("restored", result["status"])
        self.assertEqual(self.before, self.contents())

    def test_no_project_and_running_studio(self):
        shutil.rmtree(self.variant / "project")
        self.assertEqual("rebound", self.update("--apply")["status"])
        record = cli.studio_record(self.variant, "current")
        cli.write_json(record, {"pid": os.getpid()})
        with self.assertRaisesRegex(appearance.AppearanceError, "Stop"):
            self.invoke("--work", self.work_id, "--variant", "main", "appearance", "rebind", "--background", "white@v1", "--apply")

    def test_v361_runtime_requires_explicit_upgrade(self):
        runtime = self.variant / "project/runtime/appearance.js"
        runtime.write_text("v3.6.1 frozen runtime fixture")
        before = self.contents()
        file_sha256 = cli.file_sha256
        old_hash = "77cf4869f89604a42b1e7cfa3f09fda7c4b5ad4d593f7a6aece18a3e02f29abe"
        with patch.object(cli, "file_sha256", side_effect=lambda path: old_hash if Path(path) == runtime else file_sha256(path)):
            with self.assertRaisesRegex(appearance.AppearanceError, "upgrade-runtime"):
                self.update("--apply")
            self.assertEqual(before, self.contents())
            self.assertTrue(self.update("--apply", "--upgrade-runtime")["runtime_upgrade"])
        self.assertEqual((Path(appearance.__file__).parent / "runtime/appearance.js").read_bytes(), runtime.read_bytes())

    def test_explicit_target_required_and_known_runtime_upgrade(self):
        preview = self.update("--ratio", "9:16")
        self.assertEqual(1080, preview["changes"]["width"]["after"])
        self.assertEqual(1920, preview["changes"]["height"]["after"])
        with self.assertRaisesRegex(appearance.AppearanceError, "explicit"):
            self.invoke("appearance", "rebind", "--background", "green@v1", "--apply")
        runtime = self.variant / "project/runtime/appearance.js"
        runtime.write_text("known-old-fixture")
        with patch.object(appearance_rebind, "KNOWN_RUNTIMES", {cli.file_sha256(runtime)}):
            with self.assertRaisesRegex(appearance.AppearanceError, "upgrade-runtime"):
                self.update("--apply")
            self.assertTrue(self.update("--apply", "--upgrade-runtime")["runtime_upgrade"])
        self.assertEqual((Path(appearance.__file__).parent / "runtime/appearance.js").read_bytes(), runtime.read_bytes())


if __name__ == "__main__":
    unittest.main()
