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
import asset_contract as CONTRACT
import asset_store as STORE
import component_harness as COMPONENT


class AppearanceAssetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = self.root / "store"
        self.harness = self.root / "harness"
        self.harness.mkdir()
        environment = patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(self.store),
                                              "HYPERFRAMES_AI_REVIEW": "0",
                                              "HYPERFRAMES_AI_ASSET_CONFIG": str(self.root / "config.json")})
        environment.start()
        self.addCleanup(environment.stop)

    def source(self, kind, payload, **changes):
        source = self.root / f"source-{kind}"
        source.mkdir(exist_ok=True)
        manifest = {"schema_version": 2, "id": f"test-{kind}", "version": 1, "kind": kind,
                    "entry": "preset.json", "contract_version": 1, "parameters": {}, "compatibility": {}}
        manifest.update(changes)
        (source / "asset.json").write_text(json.dumps(manifest), encoding="utf-8")
        (source / "preset.json").write_text(json.dumps(payload), encoding="utf-8")
        return source

    def accept(self, source):
        candidate = STORE.pack_source(self.store, source)
        STORE.accept_component(self.store, candidate["component_ref"], candidate["package_sha256"],
                               "isolated synthetic fixture", runtime_root=self.harness)
        return {"ref": candidate["component_ref"], "kind": json.loads((source / "asset.json").read_text())["kind"],
                "package_sha256": candidate["package_sha256"]}

    def test_declarative_round_trip_requires_no_runtime_and_freezes_exact_packages(self):
        payloads = {"theme": {"tokens": {"colors": {"text": "#121212"}}},
                    "background": {"renderer": "solid", "parameters": {"color": "#ffffff"}},
                    "motion": {"slots": {"reveal": {"duration": 0.3, "easing": "power2.out"}}, "reduced_motion": {}}}
        references = [self.accept(self.source(kind, payload)) for kind, payload in payloads.items()]
        closure = STORE.resolve_asset_closure(self.harness, references)
        self.assertEqual(3, len(closure))
        self.assertEqual({"theme", "background", "motion"}, {item["metadata"]["kind"] for item in closure})
        self.assertEqual(3, sum(item["available"] for item in STORE.legacy_discover_components(self.harness)["assets"]))
        for reference in references:
            path, report, acceptance = STORE.resolve_asset(self.harness, reference)
            self.assertEqual(reference["package_sha256"], report["package_sha256"])
            self.assertEqual("accepted", acceptance["status"])
            self.assertTrue(path.is_dir())
        with self.assertRaisesRegex(COMPONENT.ComponentError, "kind/hash"):
            STORE.resolve_asset(self.harness, {**references[0], "package_sha256": "0" * 64})
        source = self.source("theme", {"tokens": {"colors": {"text": "#454545"}}})
        with self.assertRaisesRegex(COMPONENT.ComponentError, "different content"):
            STORE.pack_source(self.store, source)

    def test_exact_cross_package_dependencies_must_be_accepted(self):
        media = self.root / "media"
        media.mkdir()
        (media / "asset.json").write_text(json.dumps({"schema_version": 2, "id": "font-swatch", "version": 1,
            "kind": "media", "entry": "swatch.svg", "contract_version": 1, "parameters": {}, "compatibility": {}}))
        (media / "swatch.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
        candidate = STORE.pack_source(self.store, media)
        dependency = {"ref": "font-swatch@v1", "kind": "media", "package_sha256": candidate["package_sha256"]}
        theme = self.source("theme", {"tokens": {}}, asset_dependencies=[dependency])
        with self.assertRaisesRegex(COMPONENT.ComponentError, "not accepted"):
            STORE.pack_source(self.store, theme)
        self.accept(media)
        reference = self.accept(theme)
        self.assertEqual([dependency["ref"], reference["ref"]],
                         [item["ref"] for item in STORE.resolve_asset_closure(self.harness, [reference])])
        shutil.rmtree(media)
        self.assertEqual(2, len(STORE.resolve_asset_closure(self.harness, [reference])))
        (self.store / "packages/font-swatch/v1/swatch.svg").write_text("corrupt")
        with self.assertRaises(COMPONENT.ComponentError):
            STORE.resolve_asset_closure(self.harness, [reference])

    def test_schema2_module_uses_the_existing_executable_pipeline(self):
        shutil.copyfile(REPO / "windows-runtime.lock.json", self.harness / "windows-runtime.lock.json")
        # This fixture models a Windows package, regardless of the test host.
        (self.harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
        source = self.source("module", {}, entry="main.mjs")
        (source / "main.mjs").write_text("export const ready = true;")
        reference = self.accept(source)
        _, report, acceptance = STORE.resolve_asset(self.harness, reference)
        self.assertEqual("module", report["metadata"]["kind"])
        self.assertIn("hyperframes", acceptance["runtime"]["versions"])

    def test_module_background_closes_javascript_and_rejects_escape(self):
        payload = {"renderer": "module", "entry": "main.mjs", "parameters": {
            "moods": [{"cue": {"token": "hello", "nth": 1}, "tint": "#112233"}]}}
        source = self.source("background", payload, dependencies=["main.mjs"])
        (source / "main.mjs").write_text("import './helper.js'; export function create() {}")
        (source / "helper.js").write_text("export const seed = 1;")
        reference = self.accept(source)
        _, report, _ = STORE.resolve_asset(self.harness, reference)
        self.assertIn("helper.js", [item["path"] for item in report["files"]])
        payload["entry"] = "../outside.js"
        with self.assertRaises(COMPONENT.ComponentError):
            STORE.pack_source(self.store, self.source("background", payload, dependencies=["main.mjs"]))

    def test_schema_rejects_cross_responsibility_fields_and_unsafe_declarations(self):
        bad = [("theme", {"tokens": {}, "modes": ["text-led"]}),
               ("theme", {"tokens": {"background": {"color": "red"}}}),
               ("theme", {"tokens": {"colors": {"text": "url(https://example.invalid)"}}}),
               ("background", {"renderer": "three", "parameters": {}}),
               ("background", {"renderer": "solid", "parameters": {"color": "red"}}),
               ("motion", {"slots": {"reveal": {"duration": 1, "easing": "linear", "cue": 3}}, "reduced_motion": {}})]
        for kind, payload in bad:
            with self.subTest(kind=kind, payload=payload), self.assertRaises(COMPONENT.ComponentError):
                STORE.pack_source(self.store, self.source(kind, payload))
        for changes in ({"compatibility": {"modes": ["text-led"]}},
                        {"contract_version": True},
                        {"asset_dependencies": [{"ref": "other@v1", "kind": "media"}]},
                        {"asset_dependencies": [{"ref": "test-theme@v1", "kind": "theme", "package_sha256": "0" * 64}]}):
            with self.subTest(changes=changes), self.assertRaises(COMPONENT.ComponentError):
                STORE.pack_source(self.store, self.source("theme", {"tokens": {}}, **changes))

    def test_parameter_schema_and_font_license_are_closed(self):
        payload = {"tokens": {"radius": {"card": 8}}}
        schema = {"tokens.radius.card": {"type": "number", "default": 8, "minimum": 0, "maximum": 12}}
        source = self.source("theme", payload, parameters=schema)
        self.accept(source)
        for value in (-1, 13, True, float("nan")):
            with self.assertRaises(COMPONENT.ComponentError):
                CONTRACT.validate_parameter(value, schema["tokens.radius.card"])
        for changes in ({"parameters": {"tokens.missing": schema["tokens.radius.card"]}},
                        {"parameters": {"tokens.radius.card": {"type": "number", "default": 9}}}):
            with self.assertRaises(COMPONENT.ComponentError):
                STORE.pack_source(self.store, self.source("theme", payload, **changes))
        with self.assertRaisesRegex(COMPONENT.ComponentError, "font"):
            STORE.pack_source(self.store, self.source("theme", {"tokens": {}, "fonts": [{"family": "Test", "path": "font.woff2"}]}))

    def test_recursive_resolver_rejects_cycles_even_if_acceptance_records_exist(self):
        refs = [{"ref": f"{name}@v1", "kind": "theme", "package_sha256": name * 64} for name in ("a", "b")]
        for reference in refs:
            (self.store / "packages" / reference["ref"].split("@")[0] / "v1").mkdir(parents=True)
            record = self.store / "acceptances" / reference["ref"].split("@")[0] / "v1/acceptance.json"
            record.parent.mkdir(parents=True)
            record.write_text("{}")
        def report(path, ref):
            index = 0 if ref == "a@v1" else 1
            return {"component_ref": ref, "package_sha256": refs[index]["package_sha256"],
                    "metadata": {"kind": "theme", "asset_dependencies": [refs[1 - index]]}}
        with patch.object(STORE, "_validate_package", side_effect=report), patch.object(STORE, "validate_component_acceptance"):
            with self.assertRaisesRegex(COMPONENT.ComponentError, "Cyclic"):
                STORE.resolve_asset_closure(self.harness, [refs[0]])


if __name__ == "__main__":
    unittest.main()
