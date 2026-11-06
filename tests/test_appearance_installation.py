from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".studio"))
import asset_store as STORE
import component_harness as COMPONENT


class AppearanceInstallationTest(unittest.TestCase):
    def test_declarative_installation_offline_closure_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store, harness, project = (root / name for name in ("store", "harness", "project"))
            harness.mkdir()
            project.mkdir()
            shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            # This fixture models a Windows package, regardless of the test host.
            (harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
            environment = {"HYPERFRAMES_AI_ASSET_CONFIG": str(root / "config.json"),
                           "HYPERFRAMES_AI_ASSET_ROOT": "", "HYPERFRAMES_AI_ROOT": str(harness)}
            with patch.dict(os.environ, environment):
                STORE.configure_asset_store(harness, store)
                payloads = {
                    "theme": {"tokens": {"colors": {"text": "#111111"}, "surface": {"color": "#ffffff"}}},
                    "background": {"renderer": "solid", "parameters": {"color": "#ffffff"}},
                    "motion": {"slots": {"reveal": {"duration": 0.3, "easing": "power2.out"}}, "reduced_motion": {}},
                }
                source = root / "media"
                source.mkdir()
                (source / "asset.json").write_text(json.dumps({"schema_version": 1, "id": "swatch", "version": 1, "kind": "media", "entry": "swatch.svg"}))
                (source / "swatch.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>')
                candidate = STORE.pack_source(store, source)
                ref, digest = candidate["component_ref"], candidate["package_sha256"]
                acceptance = STORE.accept_component(store, ref, digest, "synthetic fixture", runtime_root=harness)
                package, _ = STORE.resolve_component(harness, ref)
                COMPONENT.install_component(package, project, {"schema_version": 3, "component_ref": ref, "scope": "dependency"}, acceptance=acceptance)
                with self.assertRaisesRegex(COMPONENT.ComponentError, "not reachable"):
                    COMPONENT.verify_installation(project)
                dependency = {"ref": ref, "kind": "media", "package_sha256": digest}
                for kind in ("theme", "background", "motion"):
                    source = root / kind
                    source.mkdir()
                    metadata = {"schema_version": 2, "id": f"test-{kind}", "version": 1,
                                "kind": kind, "entry": f"{kind}.json", "contract_version": 1,
                                "parameters": {}, "compatibility": {}}
                    if dependency:
                        metadata["asset_dependencies"] = [dependency]
                    (source / "asset.json").write_text(json.dumps(metadata))
                    (source / f"{kind}.json").write_text(json.dumps(payloads[kind]))
                    candidate = STORE.pack_source(store, source)
                    ref, digest = candidate["component_ref"], candidate["package_sha256"]
                    acceptance = STORE.accept_component(store, ref, digest, "synthetic fixture", runtime_root=harness)
                    package, _ = STORE.resolve_component(harness, ref)
                    binding = {"schema_version": 3, "component_ref": ref,
                               "usage": {"role": kind, "required": True}}
                    with self.assertRaisesRegex(COMPONENT.ComponentError, "exact asset acceptance"):
                        COMPONENT.install_component(package, project, binding)
                    COMPONENT.install_component(package, project, binding, acceptance=acceptance)
                shutil.rmtree(store)
                shutil.rmtree(harness)
                lock_path = project / "COMPONENT_LOCK.json"
                original = lock_path.read_bytes()
                report = COMPONENT.verify_installation(project)
                self.assertEqual(4, len(report["components"]))
                self.assertTrue(all(not item["mounts"] for item in report["components"]))
                self.assertEqual(original, lock_path.read_bytes())
                lock = json.loads(original)
                lock["components"][0]["acceptance"]["package_sha256"] = "0" * 64
                lock_path.write_text(json.dumps(lock))
                with self.assertRaisesRegex(COMPONENT.ComponentError, "exact package"):
                    COMPONENT.verify_installation(project)
                lock_path.write_bytes(original)
                entry = project / "vendor/components/test-theme/v1/theme.json"
                entry.write_text(entry.read_text() + " ")
                with self.assertRaises(COMPONENT.ComponentError):
                    COMPONENT.verify_installation(project)


if __name__ == "__main__":
    unittest.main()
