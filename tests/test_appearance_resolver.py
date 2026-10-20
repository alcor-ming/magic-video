import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import WORK_CLI as cli
import appearance
import asset_store
import component_harness


class AppearanceResolverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = []
        for kind, payload in (("theme", {"tokens": {"surface": {"amount": 1, "enabled": True}}}), ("background", {"renderer": "solid", "parameters": {"color": "#ffffff"}}), ("motion", {"slots": {"reveal": {"duration": 0.2, "easing": "linear"}}, "reduced_motion": {}})):
            path = self.root / kind
            path.mkdir()
            (path / "entry.json").write_text(json.dumps(payload))
            self.assets.append({"ref": f"{kind}@v1", "kind": kind, "package_sha256": "a" * 64, "path": path,
                                "metadata": {"kind": kind, "entry": "entry.json", "parameters": {}, "compatibility": {"ratios": ["16:9"]}}, "acceptance": {}})
        self.assets[0]["metadata"]["parameters"] = {"tokens.surface.amount": {"type": "number", "default": 1, "minimum": 0}, "tokens.surface.enabled": {"type": "boolean", "default": True}}
        self.account = {"id": "main", "revision": 1, "theme": self.ref("theme"), "background": self.ref("background"), "mode": "explainer", "overrides": {"theme": {"tokens.surface.amount": 2}}}
        # Frozen account Motion from an old lock; new accounts can no longer bind Motion.
        self.legacy_motion = {"reveal": {"asset": self.ref("motion"), "entry": "reveal"}}
        patcher = mock.patch("asset_store.resolve_asset_closure", return_value=self.assets, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ref(self, kind):
        return {"ref": f"{kind}@v1", "kind": kind, "package_sha256": "a" * 64}

    def test_precedence_disable_determinism_and_snapshot(self):
        explicit = {"motion": {"reveal": None}, "parameters": {"theme": {"tokens.surface.amount": 0, "tokens.surface.enabled": False}}}
        lock = appearance.resolve(self.root, self.account, explicit)
        self.assertEqual(lock, appearance.resolve(self.root, self.account, explicit))
        self.assertEqual(lock["parameters"]["theme"], {"tokens.surface.amount": 0, "tokens.surface.enabled": False})
        self.assertIsNone(lock["selection"]["motion"]["reveal"])
        self.assertNotIn(str(self.root), json.dumps(lock))
        self.account["overrides"]["theme"]["tokens.surface.amount"] = 4
        self.assertEqual(lock["overrides"]["account"]["theme"]["tokens.surface.amount"], 2)
        self.assertEqual(lock["mode"], "explainer")
        appearance._check_lock(lock)
        lock["mode"] = "text-led"
        with self.assertRaisesRegex(appearance.AppearanceError, "hash mismatch"):
            appearance._check_lock(lock)

    def test_reject_bad_overrides_and_unresolved_source(self):
        for change in ({"parameters": {"theme": {"unknown": 1}}}, {"ratio": "source"}, {"motion": {"bogus": None}}, {"background": None}, {"fps": False}, {"parameters": {"motion": {"exit": {"amount": 2}}}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                appearance.resolve(self.root, self.account, change)

    def test_theme_mode_is_not_a_gate(self):
        service = cli.account_service(self.root)
        service.put("theme", "single-mode", {"name": "Legacy", "ratios": ["16:9"], "modes": ["text-led"]})
        result = service.appearance({"theme": "single-mode", "ratio": "16:9", "mode": "explainer"})
        self.assertEqual(result["name"], "Legacy")

    def test_explainer_captions_and_legacy_lock(self):
        lock = appearance.resolve(self.root, self.account, {"mode": "explainer"})
        self.assertTrue(lock["selection"]["captions"])
        appearance._check_lock(lock)
        self.assertFalse(appearance.resolve(self.root, self.account, {"mode": "explainer", "captions": False})["selection"]["captions"])
        self.assertTrue(appearance.resolve(self.root, self.account, {"captions": True})["selection"]["captions"])
        for change in ({"captions": "on"}, {"mode": "explainer", "ratio": "4:3"}, {"mode": "explainer", "ratio": "source", "width": 800, "height": 600}):
            with self.subTest(change=change), self.assertRaises(appearance.AppearanceError):
                appearance.resolve(self.root, self.account, change)
        old = appearance.resolve(self.root, self.account)
        del old["selection"]["captions"]
        old["sha256"] = appearance.digest({k: v for k, v in old.items() if k != "sha256"})
        before = json.dumps(old)
        appearance._check_lock(old)
        self.assertEqual(before, json.dumps(old))

    def test_module_background_in_supported_modes(self):
        background = self.assets[1]
        (background["path"] / "main.js").write_text("export function create() {}")
        background["metadata"]["dependencies"] = ["main.js"]
        (background["path"] / "entry.json").write_text(json.dumps({"renderer": "module", "entry": "main.js", "parameters": {"moods": [{"cue": "hello", "tint": "#ffffff"}]}}))
        appearance._check_lock(appearance.resolve(self.root, self.account))
        appearance._check_lock(appearance.resolve(self.root, self.account, {"mode": "english"}))

    def test_effective_declaration_rejects_semantically_invalid_parameters(self):
        self.assets[2]["metadata"]["parameters"] = {"slots.reveal.duration": {"type": "number", "default": 0.2}}
        self.assets[1]["metadata"]["parameters"] = {"parameters.color": {"type": "string", "default": "#ffffff"}}
        for parameters in ({"motion": {"reveal": {"slots.reveal.duration": -1}}}, {"background": {"parameters.color": "not-a-color"}}):
            with self.subTest(parameters=parameters), self.assertRaises(component_harness.ComponentError):
                appearance.resolve(self.root, self.account, {"parameters": parameters}, legacy_motion=self.legacy_motion)
        self.assets[1]["metadata"]["parameters"] = {"renderer": {"type": "string", "default": "solid"}}
        with self.assertRaisesRegex(component_harness.ComponentError, "cannot be overridden"):
            appearance.resolve(self.root, self.account)

    def test_source_dimensions_and_rehashed_lock_schema(self):
        lock = appearance.resolve(self.root, self.account, {"ratio": "source", "width": 1280, "height": 720})
        self.assertEqual((lock["ratio"], lock["width"], lock["height"]), ("16:9", 1280, 720))
        appearance._check_lock(lock)
        from copy import deepcopy
        for change in (lambda data: data["selection"]["theme"].update(ref="missing@v1"), lambda data: data["selection"]["theme"].update(package_sha256="b" * 64), lambda data: data.update(width=1), lambda data: data.update(resolver_version=99)):
            damaged = deepcopy(lock)
            change(damaged)
            damaged["sha256"] = appearance.digest({key: value for key, value in damaged.items() if key != "sha256"})
            with self.assertRaises(appearance.AppearanceError):
                appearance._check_lock(damaged)

    def test_real_store_offline_materialization(self):
        from test_work_cli import REPO
        harness = self.root / "harness"
        harness.mkdir()
        shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
        store = self.root / "store"
        with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(store), "HYPERFRAMES_AI_ROOT": str(harness)}):
            selections = {}
            for kind, payload in (("theme", {"tokens": {"colors": {"text": "#111111"}}}), ("background", {"renderer": "solid", "parameters": {"color": "#ffffff"}})):
                source = self.root / f"source-{kind}"
                source.mkdir()
                metadata = {"schema_version": 2, "id": f"real-{kind}", "kind": kind, "version": 1, "contract_version": 1, "parameters": {}, "compatibility": {}, "entry": "entry.json"}
                (source / "asset.json").write_text(json.dumps(metadata))
                (source / "entry.json").write_text(json.dumps(payload))
                candidate = asset_store.pack_source(store, source)
                asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Synthetic isolated appearance test", runtime_root=harness)
                selections[kind] = {"ref": candidate["component_ref"], "kind": kind, "package_sha256": candidate["package_sha256"]}
            selections["motion"] = {}
            for version, slot in ((1, "reveal"), (2, "exit")):
                source = self.root / f"source-motion-v{version}"
                source.mkdir()
                metadata = {"schema_version": 2, "id": "real-motion", "kind": "motion", "version": version, "contract_version": 1, "parameters": {}, "compatibility": {}, "entry": "entry.json"}
                (source / "asset.json").write_text(json.dumps(metadata))
                (source / "entry.json").write_text(json.dumps({"slots": {slot: {"duration": 0.2, "easing": "linear"}}, "reduced_motion": {}}))
                candidate = asset_store.pack_source(store, source)
                asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Synthetic isolated appearance test", runtime_root=harness)
                selections["motion"][slot] = {"asset": {"ref": candidate["component_ref"], "kind": "motion", "package_sha256": candidate["package_sha256"]}, "entry": slot}
            with mock.patch("asset_store.resolve_asset_closure", side_effect=lambda root, refs: asset_store._accepted_closure(store, refs, runtime_root=root)):
                lock = appearance.resolve(harness, {key: value for key, value in selections.items() if key != "motion"}, legacy_motion=selections["motion"])
                project = self.root / "project"
                project.mkdir()
                (project / "index.html").write_text("<html><body>isolated fixture</body></html>")
                appearance.materialize(harness, project, lock)
                self.assertTrue((project / "component-bindings/appearance.real-motion.v1.json").is_file())
                self.assertTrue((project / "component-bindings/appearance.real-motion.v2.json").is_file())
            shutil.rmtree(store)
            appearance.verify(project, lock)
            from copy import deepcopy
            changed = deepcopy(lock)
            changed["parameters"]["theme"]["undeclared"] = 0
            changed["sha256"] = appearance.digest({key: value for key, value in changed.items() if key != "sha256"})
            (project / "appearance-lock.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(appearance.AppearanceError, "effective parameters"):
                appearance.verify(project, changed)
            (project / "appearance-lock.json").write_text(json.dumps(lock))
            (project / lock["assets"][0]["vendor_path"] / "entry.json").write_text("{}")
            with self.assertRaises(component_harness.ComponentError):
                appearance.verify(project, lock)


if __name__ == "__main__":
    unittest.main()
