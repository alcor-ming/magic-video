import json
import shutil
import unittest
from unittest import mock

import test_rc2_control as rc2

cli = rc2.cli


class SuccessorTest(unittest.TestCase):
    setUp = rc2.Rc2ControlTest.setUp
    run_cli = rc2.Rc2ControlTest.run_cli
    new = rc2.Rc2ControlTest.new

    def accepted_archive(self, work_id):
        work, _ = cli.locate_work(self.root, work_id)
        variant = work / "variants" / "main"
        preview = variant / "previews" / "draft-v001"
        project = preview / "source-snapshot"
        (project / "compositions").mkdir(parents=True)
        (project / "index.html").write_text('<html><img src="compositions/image.png"></html>')
        (project / "compositions" / "image.png").write_bytes(b"fixture media")
        (project / "DESIGN.md").write_text("# Design\n")
        (project / "project-config.json").write_text('{}\n')
        for name in cli.PREVIEW_DOCUMENTS:
            shutil.copy2(cli.input_path(variant, name), preview / name)
        metadata = {"id": preview.name, "purpose": "draft", "scope": "full", "media_readiness": "complete",
                    "snapshot_sha256": cli.snapshot_digest(project), "input_sha256": cli.preview_input_hashes(preview)}
        cli.atomic_write(preview / "preview.md", "---\n" + json.dumps(metadata) + "\n---\n")
        state = cli.read_json(variant / "variant.yaml")
        state["accepted_preview"] = preview.name
        cli.write_variant(variant, state)
        self.run_cli("--work", work_id, "archive", "--outcome", "completed")
        return work

    def successor_args(self, work_id):
        return ("successor", work_id, "--source-variant", "main", "--source-version", "draft-v001", "--account", "a")

    def test_retired_series_mode_blocks_new_successor_without_allocation(self):
        source = self.accepted_archive(self.new("Original"))
        service = cli.account_service(self.root)
        series_path = service.directory / 'series/one.json'
        series = cli.read_json(series_path)
        before = cli.identity_state(self.root)
        source_before = cli.snapshot_tree_manifest(source)
        for mode in ('card', 'text-led', 'animation-led'):
            cli.write_json(series_path, {**series, 'mode': mode})
            self.assertIn('choose explainer, showcase, math or english', self.run_cli(*self.successor_args(source.name), expected=2))
            self.assertEqual(before, cli.identity_state(self.root))
            self.assertEqual(source_before, cli.snapshot_tree_manifest(source))
            self.assertEqual(1, len(cli.list_work_rows(self.root)))

    def test_original_numbers_history_content_and_highwater(self):
        originals = [self.new(f"Episode {number}") for number in range(1, 16)]
        for number in (1, 2, 4):
            old = self.accepted_archive(originals[number - 1])
            before = cli.snapshot_tree_manifest(old)
            new_id = self.run_cli(*self.successor_args(old.name))
            self.assertNotEqual(old.name, new_id)
            new, _ = cli.locate_work(self.root, new_id)
            self.assertEqual(number, cli.read_frontmatter(new / "WORK.md")["series_number"])
            self.assertEqual(before, cli.snapshot_tree_manifest(old))
            self.assertEqual(old, cli.locate_work(self.root, old.name)[0])
            self.assertEqual(new_id, json.loads(self.run_cli("find", "--series", "one", "--number", str(number)))[0]["work"])
            history = json.loads(self.run_cli("find", "--series", "one", "--number", str(number), "--history"))
            self.assertEqual([old.name, new_id], [row["work"] for row in history])
            self.assertEqual(new_id, self.run_cli(*self.successor_args(old.name)))
            state = cli.read_json(new / "variants" / "main" / "variant.yaml")
            self.assertIsNone(state["accepted_preview"])
            self.assertIsNone(state["current_final"])
            self.assertEqual("a", state["account"])
            self.assertEqual(b"fixture media", (new / "materials/predecessor/source-snapshot/compositions/image.png").read_bytes())
            self.assertEqual((old / "variants/main/previews/draft-v001/SCRIPT.md").read_bytes(), (new / "shared/SCRIPT.md").read_bytes())
            self.assertIn("remain archived", self.run_cli("reopen", old.name, expected=2))
            self.assertIn("read-only", self.run_cli("--work", old.name, "series", "move", "two", expected=2))
            self.assertEqual(before, cli.snapshot_tree_manifest(old))
        next_id = self.new("Next episode")
        self.assertEqual(16, cli.read_frontmatter(cli.locate_work(self.root, next_id)[0] / "WORK.md")["series_number"])
        rows = json.loads(self.run_cli("list", "--all"))
        self.assertEqual(3, sum(row["location"] == "archive" for row in rows))
        plan = cli.work_migration.build_plan(self.root, cli.SimpleNamespace(**vars(cli)))
        self.assertFalse(plan["blockers"], plan["blockers"])

    def test_failure_after_rename_recovers_same_request(self):
        source = self.accepted_archive(self.new("Original"))
        before = cli.identity_state(self.root)
        with mock.patch.object(cli, "write_identity", side_effect=OSError("simulated disk failure")):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.run_cli(*self.successor_args(source.name))
        self.assertEqual(before, cli.identity_state(self.root))
        self.assertIn("recovery pending", self.run_cli("find", "--series", "one", "--number", "1", expected=2))
        self.assertIn("original successor", self.run_cli(*self.successor_args(source.name), "--title", "Different", expected=2))
        target = self.run_cli(*self.successor_args(source.name))
        self.assertEqual(target, self.run_cli(*self.successor_args(source.name)))
        self.assertEqual(2, len(cli.list_work_rows(self.root)))

    def test_deleted_or_archived_tail_never_falls_back(self):
        source = self.accepted_archive(self.new("Original"))
        target_id = self.run_cli(*self.successor_args(source.name))
        self.run_cli("archive", "--outcome", "abandoned")
        self.assertEqual(target_id, json.loads(self.run_cli("find", "--series", "one", "--number", "1"))[0]["work"])
        target, _ = cli.locate_work(self.root, target_id)
        shutil.rmtree(target)
        self.assertIn("historical number remains occupied", self.run_cli("find", "--series", "one", "--number", "1", expected=2))
        history = json.loads(self.run_cli("find", "--series", "one", "--number", "1", "--history"))
        self.assertEqual("missing", history[-1]["location"])
        self.assertIn("Unknown work", self.run_cli(*self.successor_args(source.name), expected=2))

    def test_prepublication_failure_blocks_writers_already_past_main_guard(self):
        source = self.accepted_archive(self.new("Original"))
        rename = cli.Path.rename

        def interrupt(path, target):
            if path.name.startswith(".pending-") and path.parent.name == "one":
                raise OSError("interrupted before publication")
            return rename(path, target)

        with mock.patch.object(cli.Path, "rename", new=interrupt):
            with self.assertRaisesRegex(OSError, "before publication"):
                self.run_cli(*self.successor_args(source.name))
        before = cli.identity_state(self.root)
        waiting_new = cli.build_parser().parse_args([
            "new", "Concurrent", "--workflow", "hyperframes_video", "--purpose", "standard", "--series", "one"])
        # This writer has already passed main's journal check before the interruption.
        with self.assertRaisesRegex(cli.HarnessError, "recovery pending"):
            cli.command_new(self.root, waiting_new)
        self.assertEqual(before, cli.identity_state(self.root))
        self.assertEqual(1, len(cli.list_work_rows(self.root)))
        target = self.run_cli(*self.successor_args(source.name))
        self.assertEqual(target, self.run_cli(*self.successor_args(source.name)))

    def test_postcommit_failure_preserves_identity_and_retry(self):
        source = self.accepted_archive(self.new("Original"))
        write = cli.write_identity

        def interrupt(root, state):
            write(root, state)
            raise OSError("interrupted after identity commit")

        with mock.patch.object(cli, "write_identity", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "after identity commit"):
                self.run_cli(*self.successor_args(source.name))
        committed = cli.identity_state(self.root)
        target = self.run_cli(*self.successor_args(source.name))
        self.assertEqual(committed, cli.identity_state(self.root))
        self.assertEqual(target, committed["successions"]["one:1"]["chain"][-1])

    def test_source_alias_and_explicit_series_move_keep_identity_history(self):
        source = self.accepted_archive(self.new("Original"))
        state = cli.identity_state(self.root)
        state["aliases"]["legacy-source"] = source.name
        cli.write_identity(self.root, state)
        target = self.run_cli(*self.successor_args("legacy-source"))
        self.assertEqual(source, cli.locate_work(self.root, "legacy-source")[0])
        self.run_cli("series", "move", "two")
        self.assertEqual(target, json.loads(self.run_cli("find", "--series", "one", "--number", "1"))[0]["work"])
        self.accepted_archive(target)
        next_target = self.run_cli(*self.successor_args(target))
        self.assertEqual(next_target, json.loads(self.run_cli("find", "--series", "one", "--number", "1"))[0]["work"])
        self.assertEqual(next_target, json.loads(self.run_cli("find", "--series", "two", "--number", "1"))[0]["work"])

    def test_reject_fork_duplicate_unaccepted_and_changed_snapshot(self):
        source_id = self.new("Original")
        self.assertIn("archived", self.run_cli(*self.successor_args(source_id), expected=2))
        source = self.accepted_archive(source_id)
        snapshot = source / "variants/main/previews/draft-v001/source-snapshot/index.html"
        original = snapshot.read_text()
        snapshot.write_text("changed")
        self.assertIn("snapshot changed", self.run_cli(*self.successor_args(source_id), expected=2))
        snapshot.write_text(original)
        target = self.run_cli(*self.successor_args(source_id))
        self.assertIn("another successor", self.run_cli(*self.successor_args(source_id), "--account", "b", expected=2))
        unrelated = self.new("Unrelated")
        path = cli.locate_work(self.root, unrelated)[0] / "WORK.md"
        metadata = cli.read_frontmatter(path)
        metadata["series_number"] = 1
        cli.atomic_write(path, "---\n" + json.dumps(metadata) + "\n---\n" + cli.document_body(path))
        self.assertIn("Unrelated duplicate", self.run_cli("list", expected=2))
        self.assertNotEqual(target, unrelated)

    def test_chained_successors_and_frozen_new_account(self):
        source = self.accepted_archive(self.new("Original"))
        first = self.run_cli(*self.successor_args(source.name))
        self.accepted_archive(first)
        second = self.run_cli(*self.successor_args(first))
        cli.account_service(self.root).put("account", "a", {"name": "Changed account"})
        self.assertEqual(second, self.run_cli(*self.successor_args(first)))
        work, _ = cli.locate_work(self.root, second)
        self.assertEqual(1, cli.read_json(work / "variants/main/variant.yaml")["account_revision"])
        history = json.loads(self.run_cli("find", "--series", "one", "--number", "1", "--history"))
        self.assertEqual([source.name, first, second], [row["work"] for row in history])

    def test_missing_frozen_inputs_and_unaccepted_source_fail_without_allocation(self):
        source = self.accepted_archive(self.new("Original"))
        variant = source / "variants/main"
        state = cli.read_json(variant / "variant.yaml")
        state["accepted_preview"] = None
        cli.write_variant(variant, state)
        before = cli.identity_state(self.root)
        self.assertIn("not an accepted", self.run_cli(*self.successor_args(source.name), expected=2))
        state["accepted_preview"] = "draft-v001"
        cli.write_variant(variant, state)
        preview = variant / "previews/draft-v001"
        (preview / "SCRIPT.md").unlink()
        self.assertIn("frozen SCRIPT", self.run_cli(*self.successor_args(source.name), expected=2))
        self.assertEqual(before, cli.identity_state(self.root))
        self.assertEqual(1, len(cli.list_work_rows(self.root)))


if __name__ == "__main__":
    unittest.main()
