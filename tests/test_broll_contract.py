"""Contract, packaging and catalog tests for the synthetic B-roll fixture.

Covers revised docs/PRD/hyperframes-v361-motion-broll.md REQ-006..009 and 012.
Only environment/temporary roots are mocked, mirroring the existing asset store
and Motion tests; there is no business engine in the loop.
"""
import json
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO
import asset_contract
import asset_store
import component_harness
import work

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "broll-sample"
ComponentError = component_harness.ComponentError


def fixture_manifest():
    return json.loads((FIXTURE / "asset.json").read_text(encoding="utf-8"))


def base_metadata():
    return fixture_manifest()


def copy_source(destination):
    destination.mkdir()
    for name in ("asset.json", "main.js", "USAGE.md"):
        shutil.copyfile(FIXTURE / name, destination / name)
    return destination


class BrollManifestContractTest(unittest.TestCase):
    def test_schema_two_embedded_text_declaration(self):
        with tempfile.TemporaryDirectory() as temp:
            source = copy_source(Path(temp) / 'source')
            metadata = base_metadata()
            metadata['text_ownership'] = {'mode': 'embedded', 'kinds': ['title']}
            (source / 'asset.json').write_text(json.dumps(metadata))
            asset_contract.validate_card_asset(source)
            metadata['text_ownership']['kinds'] = ['title', 'title']
            (source / 'asset.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ComponentError, 'text_ownership'):
                asset_contract.validate_card_asset(source)

    def test_valid_fixture_and_hold_end_variant(self):
        metadata = base_metadata()
        self.assertIsNone(asset_contract.validate_broll(metadata))
        broll = metadata["broll"]
        self.assertEqual("concept", broll["role"])
        self.assertEqual("building-block", metadata["asset_layer"])
        self.assertEqual({"9:16", "16:9"}, set(broll["caption_safe_zone"]))
        self.assertEqual({"title", "value"}, set(broll["slots"]))
        self.assertIn("const shot = await mount", broll["usage"])
        self.assertIsInstance(broll["examples"], list)
        self.assertTrue(broll["examples"])

        hold_end = base_metadata()
        hold_end["broll"]["timing"] = "hold-end"
        hold_end["broll"]["duration"] = {"min": 3, "max": 6, "default": 3}
        self.assertIsNone(asset_contract.validate_broll(hold_end))

        stage_only = base_metadata()
        stage_only["broll"]["carries_info"] = False
        stage_only["broll"]["slots"] = {"title": {"type": "text", "layer": "stage", "max_chars": 12}}
        self.assertIsNone(asset_contract.validate_broll(stage_only))

    def test_absence_of_broll_preserves_plain_module(self):
        plain = base_metadata()
        plain.pop("broll")
        self.assertIsNone(asset_contract.validate_broll(plain))
        with tempfile.TemporaryDirectory() as temp:
            source, frozen = Path(temp) / "plain", Path(temp) / "frozen"
            source.mkdir()
            (source / "asset.json").write_text(json.dumps(plain), encoding="utf-8")
            (source / "main.js").write_text("export async function mount() {}\n", encoding="utf-8")
            shutil.copyfile(FIXTURE / "USAGE.md", source / "USAGE.md")
            result = asset_contract.freeze_source(source, frozen)
            self.assertNotIn("broll", result["metadata"])

    def test_invalid_broll_metadata_is_rejected(self):
        def invalid(change):
            metadata = base_metadata()
            change(metadata)
            with self.subTest(change=change), self.assertRaises(ComponentError):
                asset_contract.validate_broll(metadata)

        cases = [
            lambda m: m["broll"].pop("role"),
            lambda m: m["broll"].pop("usage"),
            lambda m: m["broll"].pop("examples"),
            lambda m: m["broll"].pop("caption_safe_zone"),
            lambda m: m["broll"].__setitem__("role", "center"),
            lambda m: m["broll"].__setitem__("takeover", "cover"),
            lambda m: m["broll"].__setitem__("timing", "hold"),
            lambda m: m["broll"].__setitem__("role", True),
            lambda m: m["broll"].pop("duration"),
            lambda m: m["broll"]["duration"].__setitem__("min", True),
            lambda m: m["broll"]["duration"].__setitem__("min", 0),
            lambda m: m["broll"]["duration"].__setitem__("default", "3"),
            lambda m: m["broll"]["duration"].__setitem__("default", 9),
            lambda m: m["broll"]["duration"].__setitem__("max", 2),
            lambda m: m["broll"].__setitem__("timing", "hold-end"),
            lambda m: m["broll"]["key_moments"].clear(),
            lambda m: m["broll"].__setitem__("key_moments", [0, 0.75, 0.75]),
            lambda m: m["broll"].__setitem__("key_moments", [1.5, 0]),
            lambda m: m["broll"].__setitem__("key_moments", [0, 4]),
            lambda m: m["broll"].__setitem__("key_moments", [0, "x"]),
            lambda m: m["broll"].__setitem__("sfx_cues", "none"),
            lambda m: m["broll"].__setitem__("sfx_cues", [{"time": 0}]),
            lambda m: m["broll"].__setitem__("sfx_cues", [{"time": -1, "purpose": "x"}]),
            lambda m: m["broll"].__setitem__("carries_info", 1),
            lambda m: m["broll"].__setitem__("carries_info", False),
            lambda m: m["broll"]["slots"].__setitem__("bad name!", {"type": "text", "layer": "text", "max_chars": 5}),
            lambda m: m["broll"]["slots"]["title"].pop("max_chars"),
            lambda m: m["broll"]["slots"]["title"].__setitem__("max_chars", True),
            lambda m: m["broll"]["slots"]["title"].__setitem__("max_chars", 0),
            lambda m: m["broll"]["slots"]["title"].__setitem__("layer", "overlay"),
            lambda m: m["broll"]["slots"]["title"].__setitem__("extra", 1),
            lambda m: m["broll"]["slots"].__setitem__("bad", {"type": "color"}),
            lambda m: m["broll"].__setitem__("params", {"x": {"type": "number", "default": 1}}),
            lambda m: m["broll"]["caption_safe_zone"].pop("9:16"),
            lambda m: m["broll"]["caption_safe_zone"].__setitem__("9:16", [0, 0.9, 1, 0.16]),
            lambda m: m["broll"]["caption_safe_zone"].__setitem__("9:16", [0, 0.84, 1]),
            lambda m: m["compatibility"].__setitem__("ratios", ["21:9"]),
            lambda m: m["broll"].__setitem__("usage", ""),
            lambda m: m["broll"].__setitem__("examples", []),
            lambda m: m["broll"].__setitem__("examples", [""]),
            lambda m: m.__setitem__("kind", "media"),
        ]
        for change in cases:
            invalid(change)


class BrollFixturePipelineTest(unittest.TestCase):
    def test_pack_accept_interface_install_and_offline_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            harness, store, project = (root / name for name in ("harness", "store", "project"))
            harness.mkdir()
            project.mkdir()
            shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            # This fixture models a Windows package, regardless of the test host.
            (harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
            source = copy_source(root / "synthetic-broll")
            manifest = fixture_manifest()
            with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(store), "HYPERFRAMES_AI_ROOT": str(harness)}):
                candidate = asset_store.pack_source(store, source)
                ref = candidate["component_ref"]
                record = asset_store.accept_component(
                    store, ref, candidate["package_sha256"], "Isolated B-roll contract test", runtime_root=harness)
                package, acceptance = asset_store.resolve_component(harness, ref)
                frozen = asset_contract.validate_asset(package)
                self.assertEqual(manifest["broll"], frozen["metadata"]["broll"])
                self.assertEqual(candidate["package_sha256"], frozen["package_sha256"])
                self.assertIsInstance(record, dict)
                self.assertIsInstance(acceptance, dict)
                args = work.build_parser().parse_args(["component", "interface", ref])
                args.json = True
                output = io.StringIO()
                with redirect_stdout(output):
                    work.command_component_interface(harness, args)
                interface = json.loads(output.getvalue())["interface"]
                self.assertEqual(manifest["broll"], interface["broll"])
                self.assertIn("await rolls.renderAt", interface["usage"])

                reference = {"ref": ref, "kind": "module", "package_sha256": candidate["package_sha256"]}
                item = asset_store.resolve_asset_closure(harness, [reference])[0]
                binding = {"schema_version": 3, "component_ref": ref, "scene": "S01",
                           "usage": {"role": "auxiliary", "required": True}}
                self.assertNotIn("slots", binding)
                identity, version = component_harness.parse_component_ref(ref)
                component_harness.install_component(
                    Path(item["path"]), project, binding,
                    binding_path=f"component-bindings/broll.{identity}.v{version}.json",
                    expected_ref=ref, acceptance=item["acceptance"])
                entry = f"vendor/components/{identity}/v{version}/main.js"
                (project / "index.html").write_text(f'<script type="module" src="{entry}"></script>')
                (project / "project-config.json").write_text(json.dumps({"snapshot_dependencies": [entry]}))
                component_harness.verify_installation(project)
                shutil.rmtree(store)
                component_harness.verify_installation(project)

    def test_component_list_filters_and_cli_parser_expose_broll_role(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            harness, store = root / "harness", root / "store"
            harness.mkdir()
            shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            # This fixture models a Windows package, regardless of the test host.
            (harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
            card = harness / '.studio/designs/kit'
            card.mkdir(parents=True)
            (card / 'design.json').write_text(json.dumps({'id': 'kit', 'version': 1, 'type': 'material',
                'assets': {'directory': 'assets'}, 'runtime': {}}))
            (card / 'assets').mkdir()
            source = copy_source(card / 'assets/synthetic-broll')
            with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(store), "HYPERFRAMES_AI_ROOT": str(harness)}):
                ref = 'kit/synthetic-broll'
                matched = {item["component_ref"] for item in asset_store.discover_components(harness, broll_role="concept")["assets"]}
                self.assertIn(ref, matched)
                self.assertFalse(asset_store.discover_components(harness, broll_role="hook")["assets"])
                tagged = {item["component_ref"] for item in asset_store.discover_components(harness, tag="style:synthetic")["assets"]}
                self.assertIn(ref, tagged)
                self.assertFalse(asset_store.discover_components(harness, tag="style:missing")["assets"])

        args = work.build_parser().parse_args(["component", "list", "--broll-role", "concept", "--tag", "style:synthetic"])
        self.assertEqual(("concept", "style:synthetic"), (args.broll_role, args.tag))

    def test_malformed_and_hold_end_copies_fail_or_pass_in_temp_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            harness = root / "harness"
            harness.mkdir()
            shutil.copyfile(REPO / "windows-runtime.lock.json", harness / "windows-runtime.lock.json")
            # This fixture models a Windows package, regardless of the test host.
            (harness / ".release.json").write_text('{"target": "windows-x64", "channel": "local"}')
            with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(store), "HYPERFRAMES_AI_ROOT": str(harness)}):
                malformed = copy_source(root / "malformed")
                broken = fixture_manifest()
                broken["broll"]["slots"]["title"]["max_chars"] = True
                (malformed / "asset.json").write_text(json.dumps(broken), encoding="utf-8")
                with self.assertRaises(ComponentError):
                    asset_store.pack_source(store, malformed)

                hold_end = copy_source(root / "hold-end")
                variant = fixture_manifest()
                variant["broll"]["timing"] = "hold-end"
                variant["broll"]["duration"] = {"min": 3, "max": 6, "default": 3}
                (hold_end / "asset.json").write_text(json.dumps(variant), encoding="utf-8")
                candidate = asset_store.pack_source(store, hold_end)
                asset_store.accept_component(store, candidate["component_ref"], candidate["package_sha256"], "Isolated hold-end test", runtime_root=harness)
                package = asset_store.resolve_component(harness, candidate["component_ref"])[0]
                self.assertEqual("hold-end", asset_contract.validate_asset(package)["metadata"]["broll"]["timing"])

            self.assertEqual(fixture_manifest(), json.loads((FIXTURE / "asset.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
