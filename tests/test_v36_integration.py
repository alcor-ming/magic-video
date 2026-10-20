from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

import test_work_appearance
from test_work_cli import WORK_CLI as cli
import appearance
import appearance_rebind
import beat_grid
import explainer


class V36IntegrationTest(unittest.TestCase):
    setUp = test_work_appearance.WorkAppearanceTest.setUp
    asset = test_work_appearance.WorkAppearanceTest.asset

    def invoke(self, *arguments):
        args = cli.build_parser().parse_args(["--json", *arguments])
        with redirect_stdout(io.StringIO()) as output:
            args.handler(self.root, args)
        return output.getvalue().strip()

    def create(self, *arguments):
        identity = self.invoke("new", "Fixture", "--workflow", "hyperframes_video", "--account", "a",
                               "--purpose", "standard", "--series", "fixture", "--variant-id", "main", *arguments)
        work, _ = cli.locate_work(self.root, identity)
        return identity, work / "variants/main"

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_pdoom_creation_and_rebind_freeze(self):
        # Retired showcase entrypoints fail with reselect guidance, not silently.
        with self.assertRaisesRegex(cli.HarnessError, "retired"):
            self.create("--mode", "showcase")
        # Submodule stays exclusive to showcase designs.
        with self.assertRaisesRegex(cli.HarnessError, "only supported by showcase designs"):
            self.create("--submodule", "pdoom")
        identity, variant = self.create("--design", "pdoom")
        state = cli.read_json(variant / "variant.yaml")
        plan = cli.read_frontmatter(variant / "ANIMATION_PLAN.md")
        self.assertEqual(state["design"], "pdoom")
        self.assertEqual(state["appearance_lock"]["submodule"], "pdoom")
        self.assertEqual(state['line'], {'id': 'pdoom', 'version': 1})
        self.assertEqual(plan["submodule"], "pdoom")
        self.assertEqual(plan["appearance_lock_sha256"], state["appearance_lock"]["sha256"])
        self.assertIn("# Showcase Plan", (variant / "ANIMATION_PLAN.md").read_text())
        before = (variant / "variant.yaml").read_bytes()
        with self.assertRaisesRegex(appearance.AppearanceError, "frozen"):
            self.invoke("--work", identity, "--variant", "main", "appearance", "rebind", "--submodule", "science", "--apply")
        self.assertEqual(before, (variant / "variant.yaml").read_bytes())
        with self.assertRaisesRegex(cli.HarnessError, "retired"):
            self.invoke("variant", "add", "missing", "--account", "a", "--design", "showcase")
        self.invoke("variant", "add", "collage", "--account", "a", "--design", "collage")
        sibling = variant.parent / "collage"
        self.assertEqual(cli.read_json(sibling / 'variant.yaml')['line'], {'id': 'collage', 'version': 1})
        self.assertEqual(cli.read_json(sibling / "variant.yaml")['design'], "collage")

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_pdoom_test_work_needs_no_appearance_assets(self):
        identity = self.invoke("new", "Free", "--workflow", "hyperframes_video", "--purpose", "test",
                               "--design", "pdoom")
        work, _ = cli.locate_work(self.root, identity)
        variant = cli.variant_paths(work)[0]
        lock = cli.read_json(variant / "variant.yaml")["appearance_lock"]
        self.assertEqual((lock["selection"]["theme"], lock["selection"]["background"], lock["assets"]), (None, None, []))
        appearance.verify(variant / "project", lock, check_mounts=False)
        plan = cli.read_frontmatter(variant / "ANIMATION_PLAN.md")
        self.assertEqual((plan["theme"], plan["background"], plan["submodule"]), (None, None, "pdoom"))
        self.invoke("--work", identity, "--variant", variant.name, "appearance", "rebind", "--background", self.green["ref"], "--apply")
        rebound = cli.read_json(variant / "variant.yaml")["appearance_lock"]
        self.assertEqual(rebound["selection"]["background"], self.green)
        self.assertIsNone(rebound["selection"]["theme"])
        with self.assertRaisesRegex(cli.HarnessError, "retired"):
            self.invoke("new", "Plain", "--workflow", "hyperframes_video", "--purpose", "test", "--mode", "explainer")

    def run_cli(self, *arguments):
        args = cli.build_parser().parse_args(["--json", *arguments])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            code = cli.execute_command(self.root, args)
        return code, errors.getvalue()

    def test_retired_math_series_and_old_works_are_read_only(self):
        service = cli.account_service(self.root)
        for series in ({"name": "Math", "mode": "explainer", "spec": "math-rap"}, {"name": "Math", "mode": "math"}):
            with self.subTest(series=series), self.assertRaisesRegex(cli.HarnessError, "math card .* retired"):
                service.put("series", "fixture", series)
        identity, variant = self.create()
        state = cli.read_json(variant / "variant.yaml")
        # An old math Work as frozen before the card retired.
        cli.write_json(variant / "variant.yaml", {**state, "design": "math", "line": {"id": "math", "version": 1}})
        code, errors = self.run_cli("--work", identity, "--variant", "main", "plan", "check")
        self.assertEqual((2, True), (code, "math card is retired" in errors), errors)
        code, errors = self.run_cli("--work", identity, "status")
        self.assertEqual(0, code, errors)
        with self.assertRaisesRegex(cli.HarnessError, "retired"):
            self.invoke("variant", "add", "next", "--account", "a", "--design", "math")
        # Reselecting another card is the way out; leftover math history no longer blocks it.
        code, errors = self.run_cli("--work", identity, "--variant", "main", "variant", "reselect",
                                    "--account", "a", "--design", "stage-full", "--apply")
        self.assertEqual(0, code, errors)
        reselected = cli.read_json(variant / "variant.yaml")
        self.assertEqual("stage-full", reselected["design"])
        cli.write_json(variant / "variant.yaml", {**reselected, "series_binding": {"spec": "math-rap"}})
        code, errors = self.run_cli("--work", identity, "--variant", "main", "plan", "check")
        self.assertNotIn("math card is retired", errors)

    def test_retired_modes_require_reselect_and_default_binds_stage_full(self):
        for mode, target in (("explainer", "stage-full"), ("showcase", "pdoom"), ("science", "collage"), ("math", None)):
            with self.subTest(mode=mode), self.assertRaisesRegex(cli.HarnessError, f"reselect {target}" if target in cli.designs.DESIGN_IDS else "reselect a design"):
                self.create("--mode", mode)
        with self.assertRaisesRegex(cli.HarnessError, "reselect a design"):
            self.create("--mode", "card")
        # No implicit explainer default: an unset design resolves to stage-full.
        _, variant = self.create()
        card = json.loads((Path(__file__).resolve().parents[1] / '.studio/designs/stage-full/design.json').read_text())
        self.assertEqual(cli.read_json(variant / 'variant.yaml')['line'], {'id': 'stage-full', 'version': card['version']})

    def test_beats_build_binds_grid_to_formal_audio(self):
        identity, variant = self.create()
        work = variant.parent.parent
        cue_path = variant / "project/runtime/cues.json"
        cli.write_json(cue_path, explainer.build_cues("a", b'{"characters":[{"char":"a","start":0,"end":1}]}'))
        audio = work / "formal.wav"
        audio.write_bytes(b"audio fixture")
        upstream = self.base / "hyperframes.mjs"
        upstream.write_text("fixture")
        grid = beat_grid.make_beat_grid([0, 1, 2], cli.file_sha256(audio), 3, 0)
        with patch("beat_grid.extract", return_value=grid) as extract:
            self.invoke("--work", identity, "--variant", "main", "beats", "build", "--audio", "formal.wav",
                        "--beats-per-bar", "3", "--first-downbeat", "0", "--hyperframes-cli", str(upstream))
            self.assertEqual(extract.call_args.args, (audio, upstream, 3, 0))
        cues = cli.read_json(cue_path)
        self.assertEqual(cues["beat_grid"], grid)
        self.assertEqual(2, explainer.find_cue(cues, {"bar": 1, "beat": 3}))

    def test_known_cue_runtime_requires_explicit_upgrade(self):
        identity, variant = self.create()
        runtime = variant / "project/runtime/cues.js"
        runtime.write_text("known old cue fixture")
        with patch.object(appearance_rebind, "KNOWN_CUE_RUNTIMES", {cli.file_sha256(runtime)}):
            with self.assertRaisesRegex(appearance.AppearanceError, "upgrade-runtime"):
                self.invoke("--work", identity, "--variant", "main", "appearance", "rebind", "--apply")
            report = json.loads(self.invoke("--work", identity, "--variant", "main", "appearance", "rebind", "--apply", "--upgrade-runtime"))
            self.assertTrue(report["runtime_upgrade"])
        self.assertEqual(runtime.read_bytes(), (test_work_appearance.REPO / ".studio/runtime/cues.js").read_bytes())


if __name__ == "__main__":
    unittest.main()
