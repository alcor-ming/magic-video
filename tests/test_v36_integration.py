from pathlib import Path
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

import test_work_appearance
from test_work_cli import WORK_CLI as cli
import appearance
import appearance_rebind
import explainer
import math_chain


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

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_math_series_freezes_spec_and_adopts_successor(self):
        service = cli.account_service(self.root)
        service.put("series", "fixture", {"name": "Math", "mode": "explainer", "spec": "math-rap"})
        series = service.get("series", "fixture")
        identity, variant = self.create("--captions", "off")
        state = cli.read_json(variant / "variant.yaml")
        expected = {key: series[key] for key in ("id", "revision", "mode", "spec")}
        self.assertEqual(state["series_binding"], expected)
        self.assertEqual(state['line'], {'id': 'math', 'version': 1})
        self.assertEqual(state["design"], "math")
        # Math defaults captions off; an explicit false is honored, not rejected.
        self.assertFalse(state["captions"])
        self.assertEqual(state["appearance_lock"]["mode"], "math")
        self.assertFalse(state["appearance_lock"]["selection"]["captions"])
        self.assertEqual(cli.read_frontmatter(variant / "ANIMATION_PLAN.md")["series_binding"], expected)
        before = {name: (variant / name).read_bytes() for name in ("variant.yaml", "ANIMATION_PLAN.md")}
        service.put("series", "fixture", {"name": "Changed", "mode": "english"})
        for name, content in before.items():
            self.assertEqual((variant / name).read_bytes(), content)
        self.invoke("variant", "add", "next", "--account", "a")
        adopted = cli.read_json(variant.parent / "next/variant.yaml")
        self.assertEqual(adopted["series_binding"]["revision"], series["revision"] + 1)
        self.assertEqual(adopted["mode"], "english")
        self.assertEqual(adopted['line'], {'id': 'english', 'version': 1})

    def test_retired_modes_require_reselect_and_default_binds_stage_full(self):
        for mode, target in (("explainer", "stage-full"), ("showcase", "pdoom"), ("science", "collage")):
            with self.subTest(mode=mode), self.assertRaisesRegex(cli.HarnessError, f"reselect {target}" if target in cli.designs.DESIGN_IDS else "reselect a design"):
                self.create("--mode", mode)
        with self.assertRaisesRegex(cli.HarnessError, "reselect a design"):
            self.create("--mode", "card")
        # No implicit explainer default: an unset design resolves to stage-full.
        _, variant = self.create()
        card = json.loads((Path(__file__).resolve().parents[1] / '.studio/designs/stage-full/design.json').read_text())
        self.assertEqual(cli.read_json(variant / 'variant.yaml')['line'], {'id': 'stage-full', 'version': card['version']})

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / '.studio/designs/math/design.json').is_file(), 'Personal card resources; checked in personal assembly')
    def test_plan_and_beats_cli_use_frozen_math_contract(self):
        cli.account_service(self.root).put("series", "fixture", {"name": "Math", "mode": "explainer", "spec": "math-rap"})
        identity, variant = self.create()
        work = variant.parent.parent
        self.assertIn("原作者", (work / "shared/RESEARCH.md").read_text())
        metadata = cli.read_frontmatter(variant / "ANIMATION_PLAN.md")
        metadata["plan_format"] = "3.5.2"
        contract = dict(units=[dict(id="u1", symbol="x", graphic="square")], symbols={"x": "square"},
                        invariants=["fixed equality"], zero_basics=[dict(relation="same value", action="retain square")],
                        cues=[dict(cue="a", keep=[], reveal=["u1"], remove=[])])
        (variant / "ANIMATION_PLAN.md").write_text("---\n" + json.dumps(metadata) + "\n---\n## S01\n```math-plan\n" + json.dumps(contract) + "\n```\n")
        (variant / "project/index.html").write_text('<main data-scene-id="S01" data-start="0" data-duration="6"></main><script>const tween={onUpdate:()=>{window.x=1}};</script>')
        cues = explainer.build_cues("a", b'{"characters":[{"char":"a","start":0,"end":1}]}')
        cue_path = variant / "project/runtime/cues.json"
        cli.write_json(cue_path, cues)
        report = json.loads(self.invoke("--work", identity, "--variant", "main", "plan", "check"))
        kinds = {f.get("code", f.get("kind")) for f in report["findings"]}
        self.assertTrue({"math_trailing_gap", "on_update_seek_risk"}.issubset(kinds))
        audio = work / "formal.wav"
        audio.write_bytes(b"audio fixture")
        upstream = self.base / "hyperframes.mjs"
        upstream.write_text("fixture")
        grid = math_chain.make_beat_grid([0, 1, 2], cli.file_sha256(audio), 3, 0)
        with patch("math_audio.extract", return_value=grid) as extract:
            self.invoke("--work", identity, "--variant", "main", "beats", "build", "--audio", "formal.wav",
                        "--beats-per-bar", "3", "--first-downbeat", "0", "--hyperframes-cli", str(upstream))
            self.assertEqual(extract.call_args.args, (audio, upstream, 3, 0))
        self.assertEqual(cli.read_json(cue_path)["beat_grid"], grid)

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
