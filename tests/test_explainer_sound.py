import json
import subprocess
import unittest
from unittest import mock

from test_explainer_cues import alignment
import test_work_appearance as fixture
import asset_store
import explainer
from component_harness import install_component, ComponentError
from visual_plan import Composition

cli = fixture.cli


class SoundTests(unittest.TestCase):
    def test_cue_preroll_ducking_closure_and_idempotent_markup(self):
        cues = explainer.build_cues("ABC", alignment("ABC", step=1))
        assets = {"tone@v1": {"vendor_path": "vendor/tone", "metadata": {
            "kind": "media", "entry": "tone.mp3", "hit_offset": 0.2, "audio": {"duration": 0.4}}}}
        plan = {"bgm": {"ref": "tone@v1", "start_cue": "A", "end_cue": {"token": "C", "edge": "end"}, "gain": 0.3},
                "sfx": [{"ref": "tone@v1", "cue": "B", "event": "reveal", "tier": "light", "gain": 0.6}]}
        elements, tracks = explainer.sound_elements(plan, cues, assets)
        self.assertEqual(0.8, tracks[1]["data-start"])
        group = next(attrs for tag, attrs in Composition(elements).nodes if tag == "hf-audio-group")
        points = json.loads(group["data-automation"])["lanes"][0]["points"]
        self.assertIn({"t": 1, "v": 0.25}, points)
        self.assertTrue(any(abs(point["t"] - 1.22) < 1e-8 and point["v"] == 1 for point in points))
        html = explainer.insert_sound("<html><body><p>Keep</p></body></html>", elements)
        self.assertEqual(html, explainer.insert_sound(html, elements))
        self.assertIn("<p>Keep</p>", html)
        plan["sfx"][0]["cue"] = "A"
        with self.assertRaisesRegex(explainer.ExplainerError, "sound_negative_preroll"):
            explainer.sound_elements(plan, cues, assets)
        plan["sfx"][0]["ref"] = "outside@v1"
        with self.assertRaisesRegex(explainer.ExplainerError, "sound_asset_outside_closure"):
            explainer.sound_elements(plan, cues, assets)


class ExplainerCliTests(unittest.TestCase):
    setUp = fixture.WorkAppearanceTest.setUp
    asset = fixture.WorkAppearanceTest.asset
    invoke = fixture.WorkAppearanceTest.invoke

    def test_cli_mode_caption_and_ratio_contract(self):
        for ratio in ("16:9", "9:16"):
            lock = json.loads(self.invoke("appearance", "resolve", "--account", "a", "--mode", "explainer", "--ratio", ratio))
            self.assertTrue(lock["selection"]["captions"])
        lock = json.loads(self.invoke("appearance", "resolve", "--account", "a", "--mode", "explainer", "--captions", "off"))
        self.assertFalse(lock["selection"]["captions"])
        for option in ("on", "off"):
            lock = json.loads(self.invoke("appearance", "resolve", "--account", "a", "--captions", option))
            self.assertEqual("explainer", lock["mode"])
            self.assertEqual(option == "on", lock["selection"]["captions"])
        with self.assertRaises(cli.appearance.AppearanceError):
            self.invoke("appearance", "resolve", "--account", "a", "--mode", "explainer", "--ratio", "4:3")

    def test_explicit_build_from_approved_narration_and_installed_sound(self):
        self.check_sound_build("explainer")

    @unittest.skipUnless((fixture.REPO / '.studio/designs/english/design.json').is_file(), 'Personal English card not installed')
    def test_english_build_from_approved_narration_and_installed_sound(self):
        self.check_sound_build("english")

    def test_build_without_account_checks_closure(self):
        self.check_sound_build("explainer", no_account=True)

    def check_sound_build(self, mode, no_account=False):
        design = "stage-full" if mode == "explainer" else mode
        overrides = self.base / 'sound-overrides.json'
        overrides.write_text(json.dumps({'sfx': {'enabled': True}}))
        identity = self.invoke("new", "Sound", "--workflow", "hyperframes_video",
                               *( ["--no-account"] if no_account else ["--account", "a"] ), "--design", design,
                               '--overrides', str(overrides))
        work, _ = cli.locate_work(self.root, identity)
        variant = work / "variants/main"
        project = variant / "project"
        script = cli.input_path(variant, "SCRIPT.md")
        script.write_text('---\n{"revision":1,"approval":"approved"}\n---\n<!-- P001 -->\nABC\n')
        raw = self.base / "alignment.json"
        raw.write_bytes(alignment("ABC", step=1))
        self.invoke("--work", identity, "--variant", "main", "cues", "build", "--alignment", str(raw))
        self.assertEqual("ABC", json.loads((project / "runtime/cues.json").read_text())["text"])
        if no_account:
            runtime = project / 'runtime/cues.js'
            original_runtime = runtime.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            runtime.write_bytes(original_runtime)
            with mock.patch.object(explainer, 'declare_files', side_effect=explainer.ExplainerError('config failure')):
                with self.assertRaisesRegex(explainer.ExplainerError, 'config failure'):
                    self.invoke('--work', identity, '--variant', 'main', 'cues', 'build', '--alignment', str(raw))
            self.assertEqual(original_runtime, runtime.read_bytes())
        source = self.base / "tone"
        source.mkdir()
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                 "sine=frequency=660:duration=0.5", str(source / "tone.mp3")], capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        (source / "asset.json").write_text(json.dumps({"schema_version": 1, "id": "tone", "version": 1,
            "kind": "media", "entry": "tone.mp3", "hit_offset": 0.1}))
        package = asset_store.pack_source(self.store, source)
        asset_store.accept_component(self.store, "tone@v1", package["package_sha256"], "Synthetic test", runtime_root=self.root)
        path, accepted = asset_store.resolve_component(self.root, "tone@v1")
        install_component(path, project, {"schema_version": 3, "component_ref": "tone@v1", "scene": "S01",
            "usage": {"role": "auxiliary", "required": True}}, acceptance=accepted)
        (project / "index.html").write_text("<html><body></body></html>")
        sound = {"bgm": None, "sfx": [{"ref": "tone@v1", "cue": "B", "event": "reveal", "tier": "light", "gain": 0.6}]}
        (variant / "ANIMATION_PLAN.md").write_text('---\n{"plan_format":"3.5.2","status":"approved"}\n---\n## S01\nSound event\n## 声音导出\n```sound\n' + json.dumps(sound) + '\n```\n')
        state = cli.read_json(variant / 'variant.yaml')
        state['design_values']['sfx.enabled'] = False
        cli.write_variant(variant, state)
        before_disabled = (project / 'index.html').read_bytes()
        with self.assertRaisesRegex(cli.HarnessError, 'SFX are disabled'):
            self.invoke('--work', identity, '--variant', 'main', 'sound', 'build')
        self.assertEqual(before_disabled, (project / 'index.html').read_bytes())
        self.assertFalse((project / 'sound.json').exists())
        state['design_values']['sfx.enabled'] = True
        cli.write_variant(variant, state)
        self.invoke("--work", identity, "--variant", "main", "sound", "build")
        self.assertIn('data-start="0.9"', (project / "index.html").read_text())
        self.assertEqual(sound, json.loads((project / "sound.json").read_text()))
        if no_account:
            closure = project / 'COMPONENT_LOCK.json'
            original_closure = closure.read_bytes()
            closure.write_text('{}')
            try:
                with self.assertRaises(ComponentError):
                    self.invoke('--work', identity, '--variant', 'main', 'sound', 'build')
            finally:
                closure.write_bytes(original_closure)
            self.assertEqual(sound, json.loads((project / 'sound.json').read_text()))
        config = json.loads((project / "project-config.json").read_text())
        self.assertIn("runtime/cues.json", config["snapshot_dependencies"])
        self.assertIn("sound.json", config["snapshot_dependencies"])
        before = (project / "index.html").read_bytes()
        sound_before = (project / "sound.json").read_bytes()
        config_before = (project / "project-config.json").read_bytes()
        with mock.patch.object(explainer, "declare_files", side_effect=explainer.ExplainerError("config failure")):
            with self.assertRaisesRegex(explainer.ExplainerError, "config failure"):
                self.invoke("--work", identity, "--variant", "main", "sound", "build")
        self.assertEqual(before, (project / "index.html").read_bytes())
        self.assertEqual(sound_before, (project / "sound.json").read_bytes())
        self.assertEqual(config_before, (project / "project-config.json").read_bytes())
        plan_path = variant / "ANIMATION_PLAN.md"
        plan_before = plan_path.read_text()
        plan_path.write_text('---\n{"plan_format":"3.5.2","status":"approved"}\n---\n## S01\nNo approved sound table.\n')
        with self.assertRaisesRegex(cli.HarnessError, "one sound JSON block"):
            self.invoke("--work", identity, "--variant", "main", "sound", "build")
        plan_path.write_text(plan_before)
        script.write_text(script.read_text().replace("ABC", "ABD"))
        with self.assertRaisesRegex(cli.HarnessError, "Narration changed"):
            self.invoke("--work", identity, "--variant", "main", "sound", "build")
        self.assertEqual(before, (project / "index.html").read_bytes())
        with self.assertRaisesRegex(cli.HarnessError, "explicit"):
            self.invoke("cues", "build", "--alignment", str(raw))


if __name__ == "__main__":
    unittest.main()
