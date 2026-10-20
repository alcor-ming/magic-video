"""Legacy AssetStore refs, card-library discovery branches and the read-only asset trace.

Every case builds its own isolated harness root, legacy AssetStore and user card root;
nothing reads production Work, accounts or asset libraries.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO, WORK_CLI as cli
import appearance
import asset_store
import designs


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "harness"
        self.store = self.base / "store"
        self.cards = self.base / "cards"
        self.cards.mkdir()
        shutil.copytree(REPO / ".studio/templates", self.root / ".studio/templates")
        config = self.base / "assets.json"
        config.write_text(json.dumps({"design_root": str(self.cards)}))
        environment = mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(self.store),
            "HYPERFRAMES_AI_ASSET_CONFIG": str(config), "HYPERFRAMES_AI_REVIEW": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        for key in ("HYPERFRAMES_AI_RESOLVED_CONFIG", "HYPERFRAMES_AI_WORK_ROOT"):
            os.environ.pop(key, None)

    def legacy(self, identity, kind, payload):
        source = self.base / "sources" / identity
        source.mkdir(parents=True)
        (source / "asset.json").write_text(json.dumps({"schema_version": 2, "contract_version": 1,
            "id": identity, "kind": kind, "version": 1, "entry": "preset.json", "parameters": {}, "compatibility": {}}))
        (source / "preset.json").write_text(json.dumps(payload))
        candidate = asset_store.pack_source(self.store, source)
        asset_store.accept_component(self.store, candidate["component_ref"], candidate["package_sha256"],
                                     "Synthetic isolated test", runtime_root=self.root)
        return {"ref": candidate["component_ref"], "kind": kind, "package_sha256": candidate["package_sha256"]}

    def card(self, identity, *, kind="design", references=()):
        directory = designs.new(identity, kind=kind, **({"from_card": "stage-full"} if kind == "design" else {}))
        data = json.loads((directory / "design.json").read_text(encoding="utf-8"))
        data["references"] = list(references)
        (directory / "design.json").write_text(json.dumps(data), encoding="utf-8")
        return directory

    def card_asset(self, card, identity, kind="theme", color="#101010"):
        directory = self.cards / card / "assets" / identity
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "asset.json").write_text(json.dumps({"schema_version": 2, "contract_version": 1,
            "id": identity, "kind": kind, "version": 1, "entry": "preset.json", "parameters": {}, "compatibility": {}}))
        payload = ({"tokens": {"colors": {"text": color}}} if kind == "theme"
                   else {"renderer": "solid", "parameters": {"color": color}})
        (directory / "preset.json").write_text(json.dumps(payload))
        return directory

    def invoke(self, *arguments):
        if "new" in arguments and "hyperframes_video" in arguments:
            arguments += ("--purpose", "standard", "--series", "fixture", "--variant-id", "main")
        args = cli.build_parser().parse_args(['--json', *arguments])
        with redirect_stdout(io.StringIO()) as output:
            args.handler(self.root, args)
        return output.getvalue().strip()


class LegacyReferenceTest(Fixture):
    """REQ-001: account refs such as math-paper@v1 keep resolving through the legacy AssetStore."""

    def setUp(self):
        super().setUp()
        self.math_paper = self.legacy("math-paper", "theme", {"tokens": {"colors": {"text": "#111111"}}})
        self.pro_c = self.legacy("paper-pro-c", "theme", {"tokens": {"colors": {"text": "#222222"}}})
        self.white = self.legacy("white", "background", {"renderer": "solid", "parameters": {"color": "#ffffff"}})
        service = cli.account_service(self.root)
        service.put("account", "math", {"name": "Math", "theme": self.math_paper, "background": self.white})
        service.put("account", "c", {"name": "C", "theme": self.pro_c, "background": self.white})
        service.put("series", "fixture", {"name": "Fixture", "design": "stage-full"})

    def test_new_variant_add_and_rebind_with_legacy_refs(self):
        resolved = json.loads(self.invoke("appearance", "resolve", "--account", "math"))
        self.assertEqual(self.math_paper, resolved["selection"]["theme"])
        work_id = self.invoke("new", "Legacy", "--workflow", "hyperframes_video", "--account", "math")
        work, _ = cli.locate_work(self.root, work_id)
        self.assertEqual("c2", self.invoke("--work", work_id, "variant", "add", "c2", "--account", "c"))
        state = cli.read_json(work / "variants/c2/variant.yaml")
        self.assertEqual(self.pro_c, state["appearance_lock"]["selection"]["theme"])
        preview = json.loads(self.invoke("--work", work_id, "--variant", "main", "appearance", "rebind",
                                         "--theme", "paper-pro-c@v1"))
        self.assertEqual("preview", preview["status"])
        applied = json.loads(self.invoke("--work", work_id, "--variant", "main", "appearance", "rebind",
                                         "--theme", "paper-pro-c@v1", "--apply"))
        self.assertEqual("rebound", applied["status"])
        trace = json.loads(self.invoke("--work", work_id, "component", "trace", "--account", "math"))
        self.assertEqual(["available", "available"],
                         [row["source_status"]["source"] for row in trace["account"]["bindings"]])
        self.assertEqual({"in-sync"}, {item["relation"] for variant in trace["work"]["variants"] for item in variant["assets"]})

    def test_missing_store_package_blocks_new_bindings_but_not_frozen_work(self):
        work_id = self.invoke("new", "Frozen", "--workflow", "hyperframes_video", "--account", "math")
        work, _ = cli.locate_work(self.root, work_id)
        state = cli.read_json(work / "variants/main/variant.yaml")
        for area in ("packages", "candidates", "acceptances"):
            shutil.rmtree(self.store / area / "math-paper", ignore_errors=True)
        with self.assertRaisesRegex(Exception, "Legacy AssetStore package is missing: math-paper@v1"):
            self.invoke("appearance", "resolve", "--account", "math")
        with self.assertRaisesRegex(Exception, "Legacy AssetStore package is missing: math-paper@v1"):
            self.invoke("--work", work_id, "variant", "add", "again", "--account", "math")
        appearance.verify(work / "variants/main/project", state["appearance_lock"])
        trace = json.loads(self.invoke("--work", work_id, "--variant", "main", "component", "trace", "--account", "math"))
        variant = trace["work"]["variants"][0]
        self.assertEqual("intact", variant["frozen_closure"])
        theme = next(item for item in variant["assets"] if item["ref"] == "math-paper@v1")
        self.assertEqual(("intact", "missing", "frozen-intact-source-missing"),
                         (theme["frozen"], theme["source_status"]["source"], theme["relation"]))
        self.assertEqual("missing", trace["account"]["bindings"][0]["source_status"]["source"])

    def test_unconfigured_store_and_damaged_vendor_are_distinguished(self):
        work_id = self.invoke("new", "Offline", "--workflow", "hyperframes_video", "--account", "math")
        work, _ = cli.locate_work(self.root, work_id)
        with mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": ""}):
            with self.assertRaisesRegex(Exception, "needs the retired AssetStore, which is not configured"):
                self.invoke("appearance", "resolve", "--account", "math")
            trace = json.loads(self.invoke("--work", work_id, "component", "trace"))
        variant = trace["work"]["variants"][0]
        self.assertEqual("intact", variant["frozen_closure"])
        self.assertEqual({"frozen-intact-source-store-unconfigured"}, {item["relation"] for item in variant["assets"]})
        vendor = work / "variants/main/project" / next(item["vendor_path"] for item in
                 cli.read_json(work / "variants/main/variant.yaml")["appearance_lock"]["assets"] if item["ref"] == "math-paper@v1")
        (vendor / "preset.json").write_text("{}")
        damaged = json.loads(self.invoke("--work", work_id, "component", "trace"))["work"]["variants"][0]
        self.assertEqual("damaged", damaged["frozen_closure"])
        self.assertIn("frozen-damaged", {item["relation"] for item in damaged["assets"]})


class CardDiscoveryTest(Fixture):
    """REQ-002: owned, referenced, material, conflicting and missing branches with the real catalog."""

    def setUp(self):
        super().setUp()
        self.card("kit", kind="material")
        self.card_asset("kit", "paper")
        self.card("mine", references=["kit/paper"])
        self.card_asset("mine", "ink")
        self.card("other")
        self.card_asset("other", "foreign")

    def rows(self, root=None, **kwargs):
        result = asset_store.discover_components(root or self.root, include_references=True, audit=True, **kwargs)
        return result, {(row["component_ref"], row["origin"]): row for row in result["assets"]
                        if not row["path"].startswith(str(REPO))}

    def test_owned_reference_and_material_rows_state_their_real_scope(self):
        result, rows = self.rows()
        self.assertEqual([], [item for item in result["errors"] if not item["path"].startswith(str(REPO))])
        self.assertEqual(["kit", "mine"], rows[("kit/paper", "card")]["usable_by"])
        self.assertEqual(["mine"], rows[("mine/ink", "card")]["usable_by"])
        reference = rows[("kit/paper", "reference")]
        self.assertEqual(("mine", "referenced-use"), (reference["referenced_by"], reference["next_step"]["action"]))
        with self.assertRaisesRegex(designs.DesignError, "material card"):
            designs.require("kit")
        _, mine = self.rows(design="mine")
        self.assertEqual({("mine/ink", "card"), ("mine/stage-rig", "card"), ("mine/stage-kit", "card"), ("mine/stage-motion", "card"), ("kit/paper", "reference")}, set(mine))
        # The reference row describes a real call: the declaring card resolves the source read-only.
        path, acceptance = asset_store.resolve_component(self.root, "kit/paper")
        self.assertEqual(((self.cards / "kit/assets/paper").resolve(), None), (path.resolve(), acceptance))

    def test_missing_reference_source_is_isolated(self):
        shutil.rmtree(self.cards / "kit/assets/paper")
        result, rows = self.rows()
        self.assertIn(("mine/ink", "card"), rows)
        self.assertTrue(any("kit/paper targets a missing asset" in item["error"] for item in result["errors"]))

    def test_invalid_unrelated_card_hides_only_itself(self):
        legacy = self.cards / "oldcard"
        legacy.mkdir()
        (legacy / "design.json").write_text(json.dumps({"id": "oldcard", "version": 1, "mode": "explainer"}))
        data = json.loads((self.cards / "mine/design.json").read_text())
        data["references"].append("oldcard/thing")
        (self.cards / "mine/design.json").write_text(json.dumps(data))
        result, rows = self.rows()
        self.assertIn(("mine/ink", "card"), rows)
        self.assertIn(("other/foreign", "card"), rows)
        unavailable = [item for item in result["errors"] if item.get("code") == "card_unavailable"]
        self.assertEqual(["oldcard"], [item["card"] for item in unavailable])
        self.assertTrue(any("targets an unavailable card: Design card requires a type" in item["error"]
                            for item in result["errors"]))
        listing = json.loads(self.invoke("design", "list"))
        self.assertIn("requires a type", next(row for row in listing if row["id"] == "oldcard")["error"])
        self.assertIn("mine", [row["id"] for row in listing if "error" not in row])

    def test_duplicate_id_refuses_that_id_only(self):
        shutil.copytree(REPO / ".studio/designs/stage-light", self.cards / "stage-light")
        with self.assertRaisesRegex(designs.DesignError, "Duplicate design id 'stage-light'"):
            designs.card_path("stage-light")
        with self.assertRaisesRegex(designs.DesignError, "Duplicate design id"):
            designs.catalog()
        with self.assertRaisesRegex(designs.DesignError, "already exists"):
            designs.new("stage-light")
        self.assertEqual("mine", designs.require("mine")["id"])
        self.assertEqual("mine/ink@v1", asset_store.card_asset_reference(self.root, "mine/ink")[1]["ref"])
        # The repository root carries the builtin copy that the user card collides with.
        result, rows = self.rows(REPO)
        self.assertIn(("mine/ink", "card"), rows)
        self.assertTrue(any("Duplicate design id 'stage-light'" in item["error"] for item in result["errors"]))
        self.assertFalse([row for row in result["assets"] if row.get("card") == "stage-light"])


class CardTraceTest(Fixture):
    """REQ-005: card -> reference -> account -> Work relations without mutating anything."""

    def setUp(self):
        super().setUp()
        self.card("mine")
        self.card_asset("mine", "paper")
        self.card_asset("mine", "plain", kind="background", color="#ffffff")
        self.card("other")
        self.card_asset("other", "foreign")
        refs = {name: {key: asset_store.card_asset_reference(self.root, name)[1][key]
                       for key in ("ref", "kind", "package_sha256")}
                for name in ("mine/paper", "mine/plain", "other/foreign")}
        self.refs = refs
        service = cli.account_service(self.root)
        service.put("account", "a", {"name": "A", "theme": refs["mine/paper"], "background": refs["mine/plain"]})
        service.put("account", "x", {"name": "X", "theme": refs["other/foreign"], "background": refs["mine/plain"]})
        service.put("series", "fixture", {"name": "Fixture", "design": "mine"})

    def snapshot(self):
        return {path: path.read_bytes() for path in sorted(self.base.rglob("*")) if path.is_file()}

    def test_trace_separates_older_frozen_copy_and_missing_source(self):
        work_id = self.invoke("new", "Card", "--workflow", "hyperframes_video", "--account", "a")
        before = self.snapshot()
        trace = json.loads(self.invoke("--work", work_id, "component", "trace", "--design", "mine", "--account", "x"))
        self.assertEqual(before, self.snapshot())
        self.assertEqual({"in-sync"}, {item["relation"] for item in trace["work"]["variants"][0]["assets"]})
        self.assertEqual([False, True], [row["selected_card_scope"] for row in trace["account"]["bindings"]])
        self.assertEqual({"mine/paper", "mine/plain", "mine/stage-rig", "mine/stage-kit", "mine/stage-motion"},
                         {row["component_ref"] for row in trace["design"]["assets"]})
        self.card_asset("mine", "paper", color="#333333")
        changed = json.loads(self.invoke("--work", work_id, "component", "trace"))["work"]["variants"][0]
        paper = next(item for item in changed["assets"] if item["ref"].startswith("mine/paper@"))
        self.assertEqual(("older-frozen-copy", "intact"), (paper["relation"], changed["frozen_closure"]))
        shutil.rmtree(self.cards / "mine")
        missing = json.loads(self.invoke("--work", work_id, "component", "trace"))["work"]["variants"][0]
        self.assertEqual("intact", missing["frozen_closure"])
        self.assertEqual({"frozen-intact-source-missing"}, {item["relation"] for item in missing["assets"]})
        self.assertEqual("missing", missing["design_snapshot"]["source"])

    def test_trace_requires_a_scope(self):
        with self.assertRaisesRegex(cli.HarnessError, "Select --design"):
            self.invoke("component", "trace")


if __name__ == "__main__":
    unittest.main()
