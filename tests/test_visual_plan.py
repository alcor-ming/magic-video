"""Focused lifecycle checks; real browser/render exercise is visual-mixed.mjs."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_work_cli import WORK_CLI
from visual_plan import scene_projection, layout_projection, reference_projection, validate_dependencies, VisualPlanError
from visual_plan import plan_scene_rows


class VisualPlanTest(unittest.TestCase):
    def test_scene_local_parser_rejects_old_and_invalid_information(self):
        plan = '---\n{"plan_format":"3.5.2"}\n---\n## S04B\n### I01 · SCRIPT.md#P001\n```screen\n## not a Scene\ntext\n```\n## S05\n**延续信息：** I01\n'
        rows = plan_scene_rows(plan)
        self.assertEqual(['S04B', 'S05'], list(rows))
        self.assertEqual(rows['S04B']['screens'], rows['S05']['screens'])
        for bad in ('| Scene | Intent |\n| S01 | old |', plan + '## S04B\n',
                    plan + '## S06\n### I01\n```screen\nDuplicate\n```\n',
                    '## S01\n```screen\nUnclosed', '## S01\n**延续信息：** I99'):
            with self.subTest(bad=bad), self.assertRaises(VisualPlanError):
                plan_scene_rows(bad)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        repo = Path(__file__).resolve().parents[1]
        shutil.copytree(repo / ".studio" / "templates", self.root / ".studio" / "templates")
        WORK_CLI.account_service(self.root).put("account", "main", {"name": "Fixture"})
        WORK_CLI.account_service(self.root).put("series", "fixture", {"name": "Fixture", "design": "stage-full"})
        self.run_cli("new", "Visual test", "--workflow", "hyperframes_video", "--account", "main")
        self.variant = WORK_CLI.work_paths(self.root)[0][0] / "variants" / "main"
        # This suite protects existing 3.5.2 Variant behavior.
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state.pop("line", None)
        state.pop("design_live", None)
        WORK_CLI.write_variant(self.variant, state)
        self.update("ANIMATION_PLAN.md", plan_format="3.5.2", line=None)
        self.project = self.variant / "project"
        self.update("RESEARCH.md", status="ready")
        plan = self.variant / "ANIMATION_PLAN.md"
        machine_body = WORK_CLI.document_body(plan).split('# Animation Plan', 1)[0]
        plan.write_text("---\n" + json.dumps(WORK_CLI.read_frontmatter(plan)) + "\n---\n\n"
                        + machine_body + "## S01\nP001: Complete conditions remain visible.\n")
        (self.project / "compositions").mkdir(exist_ok=True)
        (self.project / "index.html").write_text('<div id="S01" data-start="0" data-duration="4" data-composition-src="compositions/S01.html"></div>')
        (self.project / "compositions" / "S01.html").write_text('<p>Complete conditions remain visible.</p>')
        (self.project / "DESIGN.md").write_text("Test design")
        (self.project / "project-config.json").write_text("{}")

    def run_cli(self, *args):
        if "new" in args and "hyperframes_video" in args:
            args += ("--purpose", "standard", "--series", "fixture")
            if "--variant-id" not in args:
                args += ("--variant-id", "main")
        parsed = WORK_CLI.build_parser().parse_args(args)
        return parsed.handler(self.root, parsed)

    def update(self, name, **fields):
        path = WORK_CLI.input_path(self.variant, name)
        text = path.read_text()
        end = text.index("\n---", 3)
        data = WORK_CLI.read_frontmatter(path)
        data.update(fields)
        path.write_text("---\n" + json.dumps(data) + text[end:])

    def layout_sample(self):
        sample = self.variant / "layout"
        sample.mkdir()
        (sample / "index.html").write_text(
            '<link rel="stylesheet" href="styles.css">'
            '<main id="S01" data-width="1080" data-height="1920">'
            '<h1>Complete conditions remain visible.</h1>'
            '<aside>Portrait placeholder: speaker, 9:16, centered crop.</aside></main>'
        )
        (sample / "styles.css").write_text('h1 { color: #246; }')
        return sample

    def test_studio_draft_without_mp4_freezes_accepts_renders_and_archives(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v001")
        self.run_cli("preview", "register", "--media-readiness", "planned_placeholders")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "media-complete"):
            self.run_cli("preview", "accept", "draft-v001")
        self.run_cli("preview", "register")
        self.run_cli("preview", "register")
        preview, metadata = WORK_CLI.checked_preview(self.variant, "draft-v002")
        self.assertEqual("studio", metadata["review_mode"])
        self.assertIsNone(metadata["draft_sha256"])
        self.assertFalse((preview / "draft.mp4").exists())
        self.assertFalse((self.variant / ".runtime" / "render.json").exists())
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "No Studio process record"):
            self.run_cli("preview", "accept", "draft-v002")

        cli = self.root / "cli.js"
        cli.write_text("// Mock transport; native playback is checked separately")
        response = {"port": 3101, "studioUrl": "http://127.0.0.1:3101/#project/draft-v002", "pid": 123}
        with patch.object(WORK_CLI.studio_preview, "start", return_value=response):
            self.run_cli("preview", "open", "draft-v002", "--hyperframes-cli", str(cli))
        record = WORK_CLI.bound_studio(self.variant, "draft-v002")
        review_scene = Path(record["project"]) / "compositions/S01.html"
        original = review_scene.read_bytes()
        review_scene.chmod(0o644)
        review_scene.write_bytes(b"changed review copy")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Studio review source changed"):
            self.run_cli("preview", "accept", "draft-v002")
        review_scene.write_bytes(original)
        scene = self.project / "compositions/S01.html"
        scene.write_bytes(b"changed editable project")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Project changed"):
            self.run_cli("preview", "accept", "draft-v002")
        scene.write_bytes(original)
        self.run_cli("preview", "accept", "draft-v002")

        final = self.root / "final.mp4"
        def render(command, **kwargs):
            self.assertEqual(metadata["snapshot_sha256"], WORK_CLI.snapshot_digest(kwargs["cwd"]))
            final.write_bytes(b"synthetic encoded test output")
            return WORK_CLI.subprocess.CompletedProcess(command, 0, stdout="test renderer")
        scene.write_bytes(b"unaccepted edit must not reach Final")
        with patch.object(WORK_CLI.subprocess, "run", side_effect=render) as renderer:
            with self.assertRaisesRegex(WORK_CLI.HarnessError, "Final source differs"):
                self.run_cli("preview", "render", "draft-v002", "--final", "--refined-project", str(self.project),
                             "--hyperframes-cli", str(cli), "--output", str(final))
            renderer.assert_not_called()
            self.run_cli("preview", "render", "draft-v002", "--final", "--hyperframes-cli", str(cli), "--output", str(final))
            self.run_cli("finalize", str(final), "--qa-passed")
            renderer.assert_called_once()
        archived = self.variant
        self.assertEqual("active", WORK_CLI.locate_work(self.root, self.variant.parent.parent.name)[1])
        self.assertEqual(final.read_bytes(), (archived / "final/final.mp4").read_bytes())
        self.assertEqual(original, (archived / "previews/draft-v002/source-snapshot/compositions/S01.html").read_bytes())

    def test_studio_draft_without_plan_record_still_requires_final_receipt(self):
        self.update("ANIMATION_PLAN.md", status="approved")
        self.run_cli("preview", "register")
        cli = self.root / "cli.js"
        cli.write_text("// mock Studio")
        response = {"port": 3101, "studioUrl": "http://127.0.0.1:3101/#project/draft-v001", "pid": 123}
        with patch.object(WORK_CLI.studio_preview, "start", return_value=response):
            self.run_cli("preview", "open", "draft-v001", "--hyperframes-cli", str(cli))
        self.run_cli("preview", "accept", "draft-v001")
        movie = self.root / "unrelated.mp4"
        movie.write_bytes(b"not a final render")
        WORK_CLI.write_json(self.variant / ".runtime/render.json", {})
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "matching preview render"):
            self.run_cli("finalize", str(movie), "--qa-passed")
        self.update("RESEARCH.md", revision=2)
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Preview inputs changed"):
            self.run_cli("preview", "accept", "draft-v001")

    def test_scene_direction_and_placeholder_draft_do_not_authorize_final(self):
        self.run_cli("preview", "register", "--purpose", "plan", "--scope", "scene", "--scene", "S01",
                     "--media-readiness", "planned_placeholders")
        preview, metadata = WORK_CLI.checked_preview(self.variant, "plan-v001")
        self.assertEqual("direction", metadata["approval_purpose"])
        self.run_cli("preview", "accept", "plan-v001")
        self.assertIsNone(WORK_CLI.read_json(self.variant / "variant.yaml")["accepted_preview"])
        movie = self.root / "draft.mp4"
        cli = self.root / "hyperframes.js"
        cli.write_text("// Mock render transport, not a native renderer")
        def render(command, **kwargs):
            movie.write_bytes(b"synthetic placeholder test")
            return WORK_CLI.subprocess.CompletedProcess(command, 0, stdout="test renderer")
        with patch.object(WORK_CLI.subprocess, "run", side_effect=render) as renderer:
            with self.assertRaisesRegex(WORK_CLI.HarnessError, "export is forbidden"):
                self.run_cli("preview", "render", "plan-v001", "--hyperframes-cli", str(cli), "--output", str(movie))
            renderer.assert_not_called()
        self.run_cli("preview", "register", "--media-readiness", "planned_placeholders")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "media-complete"):
            self.run_cli("preview", "accept", "draft-v001")
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state.update(accepted_preview="draft-v001", accepted_script_revision=state["script_revision"],
                     accepted_plan_revision=state["plan_revision"])
        WORK_CLI.write_variant(self.variant, state)
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "media-complete"):
            self.run_cli("preview", "render", "draft-v001", "--final", "--output", str(self.root / "final.mp4"))
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "media-complete"):
            self.run_cli("finalize")
        self.run_cli("preview", "register", "--media-readiness", "complete")
        self.assertEqual("complete", WORK_CLI.preview_metadata(self.variant / "previews/draft-v002")["media_readiness"])
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "No Studio process"):
            self.run_cli("preview", "accept", "draft-v002")

    def test_scene_reference_checks_exact_scene_and_keeps_dependency_failures(self):
        with self.assertRaisesRegex(VisualPlanError, "exactly one"):
            self.run_cli("preview", "register", "--purpose", "plan", "--scope", "scene", "--scene", "S99")
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state["template"] = "talking_head"
        WORK_CLI.write_variant(self.variant, state)
        plan = self.variant / "ANIMATION_PLAN.md"
        plan.write_text(plan.read_text() + "\n## S02\nP002\n")
        self.run_cli("preview", "register", "--purpose", "plan", "--scope", "scene", "--scene", "S01",
                     "--media-readiness", "planned_placeholders")
        WORK_CLI.checked_preview(self.variant, "plan-v001")
        with self.assertRaisesRegex(VisualPlanError, "match exactly"):
            self.run_cli("preview", "register", "--purpose", "plan", "--media-readiness", "planned_placeholders")
        with (self.project / "index.html").open("a") as stream:
            stream.write('<script src="missing.js"></script>')
        with self.assertRaisesRegex(VisualPlanError, "missing"):
            self.run_cli("preview", "register", "--purpose", "plan", "--scope", "scene", "--scene", "S01", "--media-readiness", "planned_placeholders")

    def test_existing_letter_suffix_scenes_are_preserved_in_all_projections(self):
        ids = ["S01", "S04", "S04B", "S04C"]
        plan = '---\n{"plan_format":"3.5.2"}\n---\n' + "\n".join(f"## {sid}\nAccepted layout\n" for sid in ids)
        html = '<main data-width="1920" data-height="1080">' + "".join(
            f'<section data-scene-id="{sid}" data-start="{i * 4}" data-duration="4"></section>'
            for i, sid in enumerate(ids)) + '</main>'
        index = self.project / "index.html"
        index.write_text(html)
        self.assertEqual(ids, [row["id"] for row in reference_projection(plan)])
        self.assertEqual(ids, [row["id"] for row in reference_projection(plan.replace("| Scene |", "| 原 Scene ID |"))])
        self.assertEqual(ids, [row["id"] for row in scene_projection(self.project, plan)])
        self.assertEqual(["S04B"], [row["id"] for row in layout_projection(self.project, plan, ["S04B"])])
        index.write_text('<section id="S04B" data-start="0" data-duration="4"></section>')
        self.assertEqual(["S04B"], [row["id"] for row in scene_projection(self.project, plan, ["S04B"])])
        with self.assertRaisesRegex(VisualPlanError, "match exactly"):
            scene_projection(self.project, plan)
        for invalid in ("S04b", "S04-B", "intro"):
            with self.assertRaisesRegex(VisualPlanError, "exactly one"):
                scene_projection(self.project, plan, [invalid])

    def register_layout(self):
        self.run_cli("preview", "register", "--purpose", "plan", "--kind", "layout",
                     "--sample-dir", "layout", "--scene", "S01")

    def test_reference_plan_needs_no_sample_project_or_recording(self):
        backup = self.root / "project-backup"
        shutil.move(self.project, backup)
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state["template"] = "talking_head"
        WORK_CLI.write_variant(self.variant, state)
        self.run_cli("preview", "register", "--purpose", "plan", "--kind", "reference")
        self.run_cli("preview", "register", "--purpose", "plan", "--kind", "reference")
        preview = self.variant / "previews" / "plan-v001"
        metadata = WORK_CLI.preview_metadata(preview)
        self.assertEqual("reference", metadata["kind"])
        self.assertEqual([], metadata["sample_scenes"])
        self.assertEqual([], list((preview / "source-snapshot").iterdir()))
        self.assertFalse(self.project.exists())
        self.run_cli("preview", "accept", "plan-v001")
        self.run_cli("preview", "accept", "plan-v001")
        self.assertIsNone(WORK_CLI.read_json(self.variant / "variant.yaml")["accepted_preview"])
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "no new sample"):
            self.run_cli("preview", "open", "plan-v001")
        shutil.move(backup, self.project)
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"synthetic test output")
        self.run_cli("preview", "register", str(movie))
        self.run_cli("preview", "accept", "draft-v001")
        self.assertEqual("draft-v001", WORK_CLI.read_json(self.variant / "variant.yaml")["accepted_preview"])

    def test_one_gap_sample_can_cover_explicit_matching_scenes(self):
        self.layout_sample()
        with (self.variant / "ANIMATION_PLAN.md").open("a") as stream:
            stream.write("\n## S02\nP001 Same information structure as S01\n")
        self.run_cli("preview", "register", "--purpose", "plan", "--kind", "layout",
                     "--sample-dir", "layout", "--scene", "S01", "--scene", "S02")
        self.run_cli("preview", "accept", "plan-v001")
        metadata = WORK_CLI.preview_metadata(self.variant / "previews" / "plan-v001")
        self.assertEqual(["S01", "S02"], metadata["sample_scenes"])
        self.assertNotIn("S02", (self.variant / "layout" / "index.html").read_text())

    def test_studio_default_isolates_layout_and_rebuilds_changed_review(self):
        self.layout_sample()
        self.register_layout()
        snapshot = self.variant / "previews" / "plan-v001" / "source-snapshot"
        before = WORK_CLI.snapshot_digest(snapshot, "layout")
        cli = self.root / "pinned-cli.js"
        cli.write_text("// fixture CLI; launch is checked by visual-studio.mjs")
        response = {"port": 3101, "studioUrl": "http://127.0.0.1:3101/#project/plan-v001", "pid": 123}
        with patch.object(WORK_CLI.studio_preview, "start", return_value=response) as start, patch.object(WORK_CLI, "serve") as legacy:
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            project = start.call_args.args[1]
            self.assertNotEqual(project, snapshot)
            self.assertFalse(os.path.samefile(project / "index.html", snapshot / "index.html"))
            self.assertIn('data-composition-id="layout-sample"', (project / "index.html").read_text())
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            self.assertEqual(project, start.call_args.args[1])
            (project / "styles.css").chmod(0o644)
            (project / "styles.css").write_text("h1 { color: red; }")
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            self.assertNotEqual(project, start.call_args.args[1])
            self.assertEqual("h1 { color: #246; }", (start.call_args.args[1] / "styles.css").read_text())
            self.assertEqual("h1 { color: red; }", (project / "styles.css").read_text())
            legacy.assert_not_called()
        self.assertEqual(before, WORK_CLI.snapshot_digest(snapshot, "layout"))
        self.run_cli("preview", "accept", "plan-v001")

    def test_executable_review_is_readonly_reused_then_rebuilt_without_deleting_old_copy(self):
        self.run_cli("preview", "register", "--purpose", "plan", "--scope", "scene", "--scene", "S01")
        snapshot = self.variant / "previews/plan-v001/source-snapshot"
        expected = WORK_CLI.snapshot_digest(snapshot)
        cli = self.root / "cli.js"
        cli.write_text("// fixture")

        def start(cli, project, *args, **kwargs):
            for file in project.rglob("*"):
                if file.is_file():
                    self.assertEqual(0, file.stat().st_mode & 0o222, str(file))
            self.assertEqual(expected, WORK_CLI.snapshot_digest(project))
            return {"port": 3101, "studioUrl": "http://127.0.0.1:3101/#project/plan-v001"}

        with patch.object(WORK_CLI.studio_preview, "start", side_effect=start):
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            first = WORK_CLI.bound_studio(self.variant, "plan-v001")
            project = Path(first["project"])
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            self.assertEqual(first["project"], WORK_CLI.bound_studio(self.variant, "plan-v001")["project"])
            # Emulate an older writable review copy stamped by Studio.
            index = project / "index.html"
            index.chmod(0o644)
            index.write_text(index.read_text().replace('<div ', '<div data-hf-id="old" '))
            self.run_cli("preview", "open", "plan-v001", "--hyperframes-cli", str(cli))
            rebuilt = WORK_CLI.bound_studio(self.variant, "plan-v001")
            self.assertNotEqual(first["project"], rebuilt["project"])
            self.assertEqual(expected, rebuilt["opened_source_sha256"])
            self.assertIn('data-hf-id="old"', index.read_text())
            self.assertEqual(expected, WORK_CLI.snapshot_digest(snapshot))
            self.assertTrue((self.project / "index.html").stat().st_mode & 0o200)

    def test_old_output_cannot_be_registered_as_edited_source(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v001")
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"synthetic original output")
        self.run_cli("preview", "register", str(movie))
        (self.project / "compositions" / "S01.html").write_text("<p>Edited in Studio.</p>")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "output belongs to different source"):
            self.run_cli("preview", "register", str(movie))
        movie.write_bytes(b"synthetic rerender output")
        self.run_cli("preview", "register", str(movie))
        self.assertTrue((self.variant / "previews" / "draft-v002").is_dir())

    def test_layout_lifecycle_without_project_or_recording(self):
        sample = self.layout_sample()
        shutil.rmtree(self.project)
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state["template"] = "talking_head"
        WORK_CLI.write_variant(self.variant, state)
        self.assertFalse((self.variant / "section_map.json").exists())
        self.register_layout()
        self.register_layout()
        preview = self.variant / "previews" / "plan-v001"
        self.assertEqual([preview], list((self.variant / "previews").iterdir()))
        metadata = WORK_CLI.preview_metadata(preview)
        self.assertEqual("layout", metadata["kind"])
        self.assertEqual("layout", metadata["sample_dir"])
        self.assertEqual(["S01"], metadata["sample_scenes"])
        self.assertTrue(metadata["demonstrated"])
        self.assertTrue(metadata["unverified"])
        with patch.object(WORK_CLI, "serve") as serve, patch.object(WORK_CLI, "runtime_path") as runtime:
            self.run_cli("preview", "open", "plan-v001", "--legacy")
            runtime.assert_not_called()
            serve.assert_called_once_with(preview, None, 0, metadata.get("review"), layout=True)
        self.run_cli("preview", "accept", "plan-v001")
        self.run_cli("preview", "accept", "plan-v001")
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        self.assertEqual("plan-v001", state["accepted_visual_plan"])
        self.assertIsNone(state["accepted_preview"])
        self.assertEqual("approved", WORK_CLI.read_frontmatter(self.variant / "ANIMATION_PLAN.md")["status"])
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"test-only, not a render")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "No accepted preview"):
            self.run_cli("finalize", str(movie), "--qa-passed")
        (sample / "styles.css").write_text("h1 { color: red; }")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Project changed"):
            self.run_cli("preview", "accept", "plan-v001")

    def test_layout_freezes_only_referenced_dependencies(self):
        sample = self.layout_sample()
        (sample / "unused.html").write_text('<video src="missing.mp4"></video>')
        (sample / "styles.css").write_text('@import "tokens.css"; h1 { color: #246; }')
        (sample / "tokens.css").write_text(":root { --text: black; }")
        self.register_layout()
        snapshot = self.variant / "previews" / "plan-v001" / "source-snapshot"
        self.assertEqual(["index.html", "styles.css", "tokens.css"],
                         sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()))
        (sample / "unused.html").write_text("Not part of this sample")
        self.register_layout()
        self.assertFalse((self.variant / "previews" / "plan-v002").exists())
        self.run_cli("preview", "accept", "plan-v001")
        (snapshot / "tokens.css").write_text(":root { --text: red; }")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "snapshot changed"):
            self.run_cli("preview", "accept", "plan-v001")

    def test_layout_rejects_nonlocal_media_and_compositions(self):
        sample = self.layout_sample()
        path = sample / "index.html"
        original = path.read_text()
        for extra, error in (
            ('<link rel="stylesheet" href="https://example.com/live.css">', "Non-local"),
            ('<img src="../outside.png">', "outside snapshot"),
            ('<video src="missing.mp4"></video>', "semantic placeholders"),
            ('<audio src="missing.wav"></audio>', "semantic placeholders"),
            ('<div data-composition-src="missing.html"></div>', "semantic placeholders"),
            ('<img srcset="missing.png 2x">', "single local src"),
        ):
            with self.subTest(extra=extra):
                path.write_text(original + extra)
                with self.assertRaisesRegex(VisualPlanError, error):
                    self.register_layout()
        for text in (original.replace('id="S01"', 'id="S99"'), original.replace('data-width="1080"', 'data-width="0"')):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(VisualPlanError):
                    self.register_layout()

    def test_draft_expands_layout_baseline_but_requires_real_dependencies(self):
        self.layout_sample()
        with (self.variant / "ANIMATION_PLAN.md").open("a") as stream:
            stream.write("\n## S02\nP001\n")
        self.register_layout()
        self.run_cli("preview", "accept", "plan-v001")
        with (self.project / "index.html").open("a") as stream:
            stream.write('<div id="S02" data-start="4" data-duration="4" data-composition-src="compositions/S02.html"></div>')
        scene = self.project / "compositions" / "S02.html"
        scene.write_text('<video src="missing.mp4"></video>')
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"test-only, not a render")
        with self.assertRaisesRegex(VisualPlanError, "missing or outside snapshot"):
            self.run_cli("preview", "register", str(movie))
        scene.write_text("<p>Second complete explanation.</p>")
        self.run_cli("preview", "register", str(movie))
        draft = self.variant / "previews" / "draft-v001"
        metadata = WORK_CLI.preview_metadata(draft)
        plan = self.variant / "previews" / "plan-v001"
        self.assertEqual("executable", metadata["kind"])
        self.assertEqual("plan-v001", metadata["source_plan"])
        self.assertEqual(WORK_CLI.preview_metadata(plan)["snapshot_sha256"], metadata["source_plan_sha256"])
        self.assertIn("compositions/S02.html", metadata["changed_files"])
        self.assertEqual(["S01", "S02"], [s["id"] for s in WORK_CLI.read_json(draft / "visual-plan.json")["scenes"]])
        self.run_cli("preview", "accept", "draft-v001")
        self.assertEqual("draft-v001", WORK_CLI.read_json(self.variant / "variant.yaml")["accepted_preview"])

    def test_plan_to_same_source_draft_and_local_diff(self):
        with (self.project / "index.html").open("a") as stream:
            stream.write('<div id="S02" data-start="4" data-duration="4" data-composition-src="compositions/S02.html"></div>')
        with (self.variant / "ANIMATION_PLAN.md").open("a") as stream:
            stream.write("\n## S02\nP001\n")
        untouched = self.project / "compositions" / "S02.html"
        untouched.write_text("<p>Unchanged explanation.</p>")
        self.run_cli("preview", "register", "--purpose", "plan")
        preview = self.variant / "previews" / "plan-v001"
        metadata = WORK_CLI.preview_metadata(preview)
        self.assertEqual("executable", metadata.pop("kind"))
        (preview / "preview.md").write_text("---\n" + json.dumps(metadata) + "\n---\n\n# Preview\n")
        original = (preview / "source-snapshot" / "compositions" / "S01.html").read_bytes()
        self.run_cli("preview", "accept", "plan-v001")
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        self.assertIsNone(state["accepted_preview"])
        self.assertEqual("plan-v001", state["accepted_visual_plan"])
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"test-only, not a render")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "No accepted preview"):
            self.run_cli("finalize", str(movie), "--qa-passed")
        (self.project / "compositions" / "S01.html").write_text("<p>Same meaning; adjusted line break.</p>")
        self.run_cli("preview", "diff", "plan-v001")
        self.run_cli("preview", "diff", "plan-v001", "--scene", "S01", "--range", "1", "3", "--note", "Adjust focus only")
        feedback = WORK_CLI.read_json(self.variant / ".runtime" / "feedback.json")["entries"]
        self.assertEqual(["S01"], feedback[0]["requested_scenes"])
        self.assertEqual(["compositions/S01.html"], feedback[0]["changed_files"])
        self.assertEqual(untouched.read_bytes(), (preview / "source-snapshot" / "compositions" / "S02.html").read_bytes())
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "range"):
            self.run_cli("preview", "diff", "plan-v001", "--scene", "S01", "--range", "5", "7", "--note", "Invalid range")
        self.run_cli("preview", "register", str(movie))
        metadata = WORK_CLI.preview_metadata(self.variant / "previews" / "draft-v001")
        self.assertEqual(["compositions/S01.html"], metadata["changed_files"])
        self.assertEqual("plan-v001", metadata["source_plan"])
        self.assertEqual(original, (preview / "source-snapshot" / "compositions" / "S01.html").read_bytes())
        self.run_cli("preview", "accept", "draft-v001")
        with self.assertRaises(WORK_CLI.HarnessError):
            self.run_cli("finalize", str(movie), "--qa-passed")

    def test_changed_plan_source_and_stale_research_cannot_be_accepted(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        self.update("RESEARCH.md", status="pending")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "not ready"):
            self.run_cli("preview", "accept", "plan-v001")
        self.update("RESEARCH.md", status="ready")
        (self.project / "compositions" / "S01.html").write_text("changed")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Project changed"):
            self.run_cli("preview", "accept", "plan-v001")
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v002")
        self.run_cli("preview", "accept", "plan-v002")
        self.update("ANIMATION_PLAN.md", revision=2)
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state["plan_revision"] = 2
        WORK_CLI.write_variant(self.variant, state)
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "stale"):
            self.run_cli("preview", "accept", "plan-v002")

    def test_scene_coverage_and_dependency_closure(self):
        plan = (self.variant / "ANIMATION_PLAN.md").read_text()
        scenes = scene_projection(self.project, plan)
        self.assertEqual(2, scenes[0]["reading"])
        with self.assertRaisesRegex(VisualPlanError, "match exactly"):
            scene_projection(self.project, plan + "\n## S02\nP002\n")
        self.assertEqual(["compositions/S01.html", "index.html"], validate_dependencies(self.project))
        (self.project / "compositions" / "S01.html").write_text('<script src="https://example.com/live.js"></script>')
        with self.assertRaisesRegex(VisualPlanError, "Non-local"):
            validate_dependencies(self.project)
        (self.project / "compositions" / "S01.html").write_text('<script src="../../escape.js"></script>')
        with self.assertRaisesRegex(VisualPlanError, "outside snapshot"):
            validate_dependencies(self.project)

    def test_local_research_revision_reuses_plan_but_not_draft_acceptance(self):
        # Technical fixture: no live research, media or production Work.
        plan = self.variant / "ANIMATION_PLAN.md"
        plan.write_text(plan.read_text() + "\n## S02\nP002\n")
        index = self.project / "index.html"
        index.write_text(index.read_text() + '<div id="S02" data-start="4" data-duration="4" data-composition-src="compositions/S02.html"></div>')
        scene = self.project / "compositions" / "S02.html"
        scene.write_text("<p>First provide input, then inspect output.</p>")
        research = WORK_CLI.input_path(self.variant, "RESEARCH.md")
        research.write_text(research.read_text() + "\n## S02 / P002 - Process\nFirst provide input, then inspect output.\n")
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v001")
        baseline = self.variant / "previews" / "plan-v001"
        original = {p.relative_to(baseline): p.read_bytes() for p in baseline.rglob("*") if p.is_file()}
        untouched = (self.project / "compositions" / "S01.html").read_bytes()
        research.write_text(research.read_text().replace("First provide input, then inspect output.", "Provide input -> inspect output."))
        scene.write_text("<p>Provide input -> inspect output.</p>")
        args = ("preview", "diff", "plan-v001", "--scene", "S02", "--note", "Same ordered process; checked S02 and handoff", "--compatible")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "without an increased revision"):
            self.run_cli(*args)
        self.update("RESEARCH.md", revision=2)
        self.run_cli("plan", "refresh")
        updated = WORK_CLI.read_frontmatter(plan)
        self.assertEqual(2, updated["research_revision"])
        self.assertEqual(2, updated["inputs"]["RESEARCH.md"]["revision"])
        self.assertIn('<!-- plan-metadata:start -->', plan.read_text())
        stable = plan.read_bytes()
        self.run_cli("plan", "refresh")
        self.assertEqual(stable, plan.read_bytes())
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"test-only")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "scoped --compatible"):
            self.run_cli("preview", "register", str(movie))
        self.run_cli(*args)
        record = WORK_CLI.read_json(self.variant / ".runtime" / "feedback.json")["entries"][-1]
        self.assertEqual(["S02"], record["requested_scenes"])
        self.assertEqual(["compositions/S02.html"], record["changed_files"])
        self.assertEqual(WORK_CLI.preview_input_hashes(self.variant), record["current_inputs"])
        cli = self.root / "cli.js"
        cli.write_text("// Render validation fixture; no runtime execution")
        with patch.dict(os.environ, {"HYPERFRAMES_BROWSER_PATH": str(self.root / "missing-browser")}):
            with self.assertRaisesRegex(WORK_CLI.HarnessError, "export is forbidden"):
                self.run_cli("preview", "render", "plan-v001", "--hyperframes-cli", str(cli), "--output", str(self.root / "render.mp4"))
        self.run_cli("preview", "register", str(movie))
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        self.assertEqual("plan-v001", state["accepted_visual_plan"])
        self.assertIsNone(state["accepted_preview"])
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "No accepted preview"):
            self.run_cli("finalize", str(movie), "--qa-passed")
        self.run_cli("preview", "accept", "draft-v001")
        self.assertEqual(untouched, (self.project / "compositions" / "S01.html").read_bytes())
        self.assertEqual(original, {p.relative_to(baseline): p.read_bytes() for p in baseline.rglob("*") if p.is_file()})
        for target in (research, scene):
            previous = target.read_bytes()
            target.write_bytes(previous + b"\nchanged after check")
            with self.assertRaisesRegex(WORK_CLI.HarnessError, "scoped --compatible"):
                self.run_cli("preview", "register", str(movie))
            with self.assertRaisesRegex(WORK_CLI.HarnessError, "export is forbidden"):
                self.run_cli("preview", "render", "plan-v001", "--hyperframes-cli", str(cli), "--output", str(self.root / "render.mp4"))
            target.write_bytes(previous)
        research.write_text(research.read_text() + "\nNew current content")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Preview inputs changed"):
            self.run_cli("preview", "accept", "draft-v001")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Preview inputs changed"):
            self.run_cli("finalize", str(movie), "--qa-passed")

    def test_compatibility_rejects_changed_intent_narration_and_unchecked_scenes(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v001")
        args = ("preview", "diff", "plan-v001", "--scene", "S01", "--note", "Checked", "--compatible")
        for name, addition, error in (("ANIMATION_PLAN.md", "\nA different visual goal", "intent changed"),
                                      ("ANIMATION_PLAN.md", "\n| S02 | P002 |", "intent changed"),
                                      ("SCRIPT.md", "\nDifferent narration", "Narration changed")):
            path = WORK_CLI.input_path(self.variant, name)
            before = path.read_text()
            path.write_text(before + addition)
            with self.assertRaisesRegex(WORK_CLI.HarnessError, error):
                self.run_cli(*args)
            path.write_text(before)
        (self.project / "compositions" / "S01.html").write_text("changed")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "outside checked scope"):
            self.run_cli("preview", "diff", "plan-v001", "--scene", "S99", "--note", "Checked", "--compatible")
        baseline = self.variant / "previews" / "plan-v001"
        frozen = baseline / "RESEARCH.md"
        frozen.write_text(frozen.read_text() + "\nTampered frozen input")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Frozen preview inputs changed"):
            self.run_cli(*args)
        metadata = WORK_CLI.preview_metadata(baseline)
        metadata.pop("input_sha256")
        (baseline / "preview.md").write_text("---\n" + json.dumps(metadata) + "\n---\n")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "no frozen inputs"):
            self.run_cli(*args)

    def test_plan_registration_and_acceptance_bind_research_content(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        research = WORK_CLI.input_path(self.variant, "RESEARCH.md")
        original = research.read_text()
        research.write_text(original + "\nChanged input with the same revision")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Preview inputs changed"):
            self.run_cli("preview", "accept", "plan-v001")
        self.run_cli("preview", "register", "--purpose", "plan")
        self.assertTrue((self.variant / "previews" / "plan-v002").is_dir())
        frozen = self.variant / "previews" / "plan-v002" / "RESEARCH.md"
        frozen.write_text("tampered")
        with self.assertRaisesRegex(WORK_CLI.HarnessError, "Frozen preview inputs changed"):
            self.run_cli("preview", "accept", "plan-v002")

    def test_layout_compatibility_uses_full_draft_scope_and_ignores_scene_index_narration(self):
        self.layout_sample()
        plan = self.variant / "ANIMATION_PLAN.md"
        plan.write_text(plan.read_text() + "\n## S02\nP002\n")
        self.register_layout()
        self.run_cli("preview", "accept", "plan-v001")
        index = self.project / "index.html"
        index.write_text(index.read_text() + '<div id="S02" data-start="4" data-duration="4" data-composition-src="compositions/S02.html"></div>')
        (self.project / "compositions" / "S02.html").write_text("<p>Equivalent ordered process</p>")
        script = WORK_CLI.input_path(self.variant, "SCRIPT.md")
        script.write_text("---\n" + json.dumps(WORK_CLI.read_frontmatter(script)) + "\n---\n"
                          + WORK_CLI.script_text(script, anchors=True)
                          + "\n\n<!-- scene-index:start -->\n| Scene | Anchor | Budget | Direction |\n"
                          + "| S02 | P002 | 4s | Process evidence |\n<!-- scene-index:end -->\n")
        self.update("SCRIPT.md", revision=2)
        self.update("RESEARCH.md", revision=2, script_revision=2)
        self.update("ANIMATION_PLAN.md", revision=2, script_revision=2, research_revision=2)
        state = WORK_CLI.read_json(self.variant / "variant.yaml")
        state.update(script_revision=2, plan_revision=2)
        WORK_CLI.write_variant(self.variant, state)
        self.run_cli("preview", "diff", "plan-v001", "--scene", "S02", "--note", "Only index metadata and S02 input checked", "--compatible")
        movie = self.root / "draft.mp4"
        movie.write_bytes(b"technical fixture")
        self.run_cli("preview", "register", str(movie))
        self.run_cli("preview", "accept", "draft-v001")

    def test_missing_pinned_browser_fails_before_invoking_hyperframes(self):
        self.run_cli("preview", "register", "--purpose", "plan")
        self.run_cli("preview", "accept", "plan-v001")
        movie = self.root / "legacy-draft.mp4"
        movie.write_bytes(b"legacy test input, not encoded video")
        self.run_cli("preview", "register", str(movie))
        self.run_cli("preview", "accept", "draft-v001")
        cli = self.root / "cli.js"
        cli.write_text("// unreachable")
        with patch.dict(os.environ, {"HYPERFRAMES_BROWSER_PATH": str(self.root / "missing.exe")}):
            with patch.object(WORK_CLI.subprocess, "run") as launch:
                with self.assertRaisesRegex(WORK_CLI.HarnessError, "Pinned render dependency"):
                    self.run_cli("preview", "render", "draft-v001", "--final", "--hyperframes-cli", str(cli), "--output", str(self.root / "test.mp4"))
                launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
