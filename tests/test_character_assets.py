import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".studio"))
import asset_contract as assets
import component_harness as components


class CharacterAssetsTest(unittest.TestCase):
    def test_character_closed_package_binding_and_invalid_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            Image.new("RGBA", (8, 8)).save(source / "idle.png")
            metadata = {"schema_version": 2, "id": "test-character", "version": 1,
                        "kind": "character", "entry": "character.json", "contract_version": 1,
                        "parameters": {}, "compatibility": {}, "dependencies": ["idle.png"]}
            character = {"name": "Test", "profile": "Synthetic", "series_style": "flat",
                         "reference": "idle.png", "provenance": {"source": "test"},
                         "states": {"idle": {"file": "idle.png", "anchor": [4, 7], "facing": "right"}},
                         "default_state": "idle"}
            (source / "asset.json").write_text(json.dumps(metadata))
            (source / "character.json").write_text(json.dumps(character))
            release = assets.freeze_source(source, root / "frozen")
            self.assertFalse(assets.asset_requires_runtime(metadata))
            binding = {"schema_version": 3, "component_ref": release["component_ref"],
                       "scene": "scene-1", "usage": {"role": "character", "required": True}}
            components.validate_binding(binding, release)
            import asset_store
            store = root / "store"
            candidate = asset_store.pack_source(store, source)
            harness = root / "harness"
            harness.mkdir()
            import shutil
            shutil.copyfile(Path(__file__).resolve().parents[1] / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            # This fixture models a Windows package, regardless of the test host.
            (harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
            asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Synthetic test", runtime_root=harness)
            # The accepted closure is also the authority used by the figure loader.
            closure = asset_store._accepted_closure(store, [{"ref": candidate["component_ref"], "kind": "character", "package_sha256": candidate["package_sha256"]}], runtime_root=harness)
            package = Path(closure[0]["path"])
            project = root / "project"
            project.mkdir()
            (project / "index.html").write_text('<script>fetch("vendor/components/test-character/v1/character.json")</script>')
            components.install_component(package, project, binding, acceptance=closure[0]["acceptance"])
            components.verify_installation(project)
            character["name"] = "Changed same version"
            (source / "character.json").write_text(json.dumps(character))
            with self.assertRaises(components.ComponentError):
                asset_store.pack_source(store, source)
            for state in ({"file": "../idle.png", "anchor": [0, 0], "facing": "right"},
                          {"file": "idle.png", "anchor": [8, 0], "facing": "right"},
                          {"file": "idle.png", "anchor": [0, 0], "facing": "up"}):
                character["states"]["idle"] = state
                with self.assertRaises(components.ComponentError):
                    assets.validate_declaration(character, metadata, source)
            character["states"]["idle"] = {"file": "idle.png", "anchor": [0, 0], "facing": "right"}
            Image.new("RGB", (8, 8)).save(source / "idle.png")
            with self.assertRaisesRegex(components.ComponentError, "alpha"):
                assets.validate_declaration(character, metadata, source)


if __name__ == "__main__":
    unittest.main()
