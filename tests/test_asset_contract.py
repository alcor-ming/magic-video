from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".studio"))
import asset_contract as ASSET
import component_harness as COMPONENT


class AssetContractTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.destination = self.root / "frozen"
        self.metadata = {"schema_version": 1, "id": "local-module", "version": 1,
                         "kind": "module", "entry": "main.mjs", "license": "LICENSE"}
        (self.source / "LICENSE").write_text("Synthetic test asset", encoding="utf-8")
        (self.source / "main.mjs").write_text("import './helper.js'; fetch('./icon.svg');", encoding="utf-8")
        (self.source / "helper.js").write_text("export const pixels = fetch('./image.png');", encoding="utf-8")
        (self.source / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<defs><linearGradient id="paint"><stop offset="0" stop-color="red"/></linearGradient></defs>'
            '<path d="M0 0h10v10H0z" fill="url(#paint)"/></svg>', encoding="utf-8")
        Image.new("RGBA", (8, 8), (20, 100, 200, 128)).save(self.source / "image.png")

    def manifest(self, **changes):
        self.metadata.update(changes)
        (self.source / "asset.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def freeze(self, **changes):
        self.manifest(**changes)
        return ASSET.freeze_source(self.source, self.destination)

    def test_recursive_closure_is_independent_and_ignores_unselected_private_files(self):
        private = self.source / ".git"
        private.mkdir()
        (private / "config").write_text("private", encoding="utf-8")
        (self.source / "unrelated.bin").write_bytes(b"ignored")
        release = self.freeze()
        self.assertEqual("local-module@v1", release["component_ref"])
        self.assertEqual("module", release["metadata"]["asset_type"])
        self.assertEqual({"asset.json", "main.mjs", "helper.js", "icon.svg", "image.png", "LICENSE"},
                         {item["path"] for item in release["files"]})
        self.assertFalse((self.source / "HASHES.json").exists())
        (self.source / "main.mjs").write_text("changed", encoding="utf-8")
        self.assertEqual(release, ASSET.validate_asset(self.destination, "local-module@v1"))
        (self.destination / "surprise.txt").write_text("undeclared", encoding="utf-8")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "outside its declared"):
            ASSET.validate_asset(self.destination)

    def test_explicit_dependencies_and_whitelist_enforce_actual_inputs(self):
        (self.source / "dynamic.json").write_text('{"seed":1}', encoding="utf-8")
        self.manifest(dependencies=["dynamic.json"], files=["main.mjs", "helper.js", "LICENSE", "dynamic.json"])
        with self.assertRaisesRegex(COMPONENT.ComponentError, "outside file whitelist"):
            ASSET.freeze_source(self.source, self.destination)
        self.metadata["files"] += ["image.png", "icon.svg"]
        release = self.freeze()
        self.assertIn("dynamic.json", [item["path"] for item in release["files"]])

    def test_frozen_legacy_audio_roles_keep_their_manifest_and_hashes(self):
        self.metadata.update(schema_version=2, kind="media", entry="audio.mp3",
                             contract_version=1, parameters={}, compatibility={})
        (self.source / "audio.mp3").write_bytes(b"synthetic audio fixture")
        rights = {"library": "Synthetic library", "license": "CC BY 4.0",
                  "attribution": "Synthetic artist", "non_commercial": False, "share_alike": False}
        with patch.object(ASSET, "_check_audio", return_value={"duration": 1.0}):
            for role in ("bgm", "sfx"):
                with self.subTest(role=role):
                    if self.destination.exists():
                        shutil.rmtree(self.destination)
                    report = self.freeze(audio_role=role, source_url="https://example.invalid/audio", rights=rights)
                    before = {p.name: p.read_bytes() for p in self.destination.iterdir()}
                    self.assertEqual(report, COMPONENT.validate_component_release(self.destination))
                    self.assertEqual(before, {p.name: p.read_bytes() for p in self.destination.iterdir()})
                    self.assertEqual(role, json.loads(before["asset.json"])["audio_role"])

    def test_legacy_audio_roles_still_validate_kind_and_rights(self):
        metadata = dict(self.metadata, schema_version=2, kind="media", contract_version=1,
                        parameters={}, compatibility={}, audio_role="bgm")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "BGM requires"):
            ASSET._schema2(self.source, metadata)
        for changes in ({"audio_role": "unknown"}, {"audio_role": "sfx", "kind": "module"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(COMPONENT.ComponentError, "audio_role"):
                ASSET._schema2(self.source, dict(metadata, **changes))

    def test_media_needs_no_runtime_and_image_bytes_are_verified(self):
        report = self.freeze(kind="media", entry="image.png")
        self.assertNotIn("runtime", report["metadata"])
        self.assertEqual({"asset.json", "image.png", "LICENSE"}, {item["path"] for item in report["files"]})
        shutil.rmtree(self.destination)
        (self.source / "image.png").write_bytes(b"not a PNG")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "Invalid image"):
            self.freeze()

    def test_metadata_types_and_generated_hash_filename_fail_closed(self):
        original = dict(self.metadata)
        for changes in ({"schema_version": True}, {"schema_version": 1.0}, {"version": True},
                        {"kind": []}, {"kind": "recipe"}, {"id": "con"}, {"entry": {}},
                        {"files": ["main.mjs"]}, {"runtime": []}):
            with self.subTest(changes=changes), self.assertRaises(COMPONENT.ComponentError):
                self.metadata = dict(original)
                self.freeze(**changes)
        self.metadata = original
        (self.source / "hashes.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "generated only"):
            self.freeze(dependencies=["hashes.json"])

    def test_missing_remote_and_escape_dependencies_fail(self):
        for text in ("import './missing.mjs';", "import 'https://example.invalid/module.js';",
                     "fetch('../outside.png');"):
            with self.subTest(text=text):
                (self.source / "main.mjs").write_text(text, encoding="utf-8")
                with self.assertRaises(COMPONENT.ComponentError):
                    self.freeze()
                self.assertFalse(self.destination.exists())

    def test_links_private_paths_and_windows_names_are_rejected(self):
        self.manifest()
        target = self.root / "secret.js"
        target.write_text("private", encoding="utf-8")
        for mode in ("symlink", "hardlink"):
            alias = self.source / "alias.js"
            if mode == "symlink":
                alias.symlink_to(target)
            else:
                os.link(target, alias)
            (self.source / "main.mjs").write_text("import './alias.js';", encoding="utf-8")
            with self.assertRaisesRegex(COMPONENT.ComponentError, "links"):
                self.freeze()
            alias.unlink()
        for name in ("../secret.js", ".git/config", "private/data.json", "CON.js", "bad:name.js", "bad. ", "a\\b.js"):
            with self.subTest(name=name), self.assertRaises(COMPONENT.ComponentError):
                self.freeze(dependencies=[name])

    def test_case_collisions_are_rejected_at_directory_level(self):
        for name in ("Images/a.svg", "images/b.svg"):
            path = self.source / name
            path.parent.mkdir(exist_ok=True)
            shutil.copyfile(self.source / "icon.svg", path)
        with self.assertRaisesRegex(COMPONENT.ComponentError, "case-insensitive"):
            self.freeze(dependencies=["Images/a.svg", "images/b.svg"])

    def test_frozen_package_rejects_linked_and_nonregular_extras(self):
        self.freeze()
        extra = self.destination / "extra.txt"
        os.link(self.source / "LICENSE", extra)
        with self.assertRaisesRegex(COMPONENT.ComponentError, "links"):
            ASSET.validate_asset(self.destination)
        extra.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(extra)
            with self.assertRaisesRegex(COMPONENT.ComponentError, "non-regular"):
                ASSET.validate_asset(self.destination)

    def test_svg_allowlist_rejects_active_content_and_missing_fragments(self):
        invalid = (
            '<script>alert(1)</script>', '<path onload="alert(1)"/>',
            '<foreignObject><div>active</div></foreignObject>',
            '<style>path {fill:url(https://example.invalid)}</style>',
            '<path style="fill:red"/>', '<use href="https://example.invalid/a.svg#id"/>',
            '<path fill="url(https://example.invalid/a.svg#id)"/>',
            '<path fill="url(#missing)"/>', '<use href="#missing"/>',
            '<path id="duplicate"/><path id="duplicate"/>',
            '<?xml-stylesheet href="https://example.invalid/style.css"?>',
            '<path xmlns:other="https://example.invalid" other:href="#safe"/>',
            '<path fill="u\\72l(https://example.invalid/a.svg#id)"/>',
        )
        for body in invalid:
            with self.subTest(body=body):
                (self.source / "icon.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>', encoding="utf-8")
                with self.assertRaisesRegex(COMPONENT.ComponentError, "SVG"):
                    self.freeze(kind="media", entry="icon.svg")
        (self.source / "icon.svg").write_text('<!DOCTYPE svg [<!ENTITY x "value">]><svg>&x;</svg>', encoding="utf-8")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "SVG declarations"):
            self.freeze()
        (self.source / "icon.svg").write_text('<?xml-stylesheet href="external.css"?><svg/>', encoding="utf-8")
        with self.assertRaisesRegex(COMPONENT.ComponentError, "SVG declarations"):
            self.freeze()

    def test_source_change_during_copy_leaves_no_candidate(self):
        copy = shutil.copy2

        def changing_copy(source, destination):
            result = copy(source, destination)
            if Path(source).name == "main.mjs":
                Path(source).write_text("export const changed = true;", encoding="utf-8")
            return result

        self.manifest()
        with patch.object(ASSET.shutil, "copy2", side_effect=changing_copy):
            with self.assertRaisesRegex(COMPONENT.ComponentError, "changed during freezing"):
                ASSET.freeze_source(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.source / "HASHES.json").exists())


if __name__ == "__main__":
    unittest.main()
