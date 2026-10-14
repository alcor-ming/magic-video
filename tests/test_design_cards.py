"""Design cards, five-layer appearance config, and Work CLI design selection."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import os
import shutil
import tempfile
import unittest
from unittest import mock

from test_work_cli import REPO, WORK_CLI as cli
import designs


EXPECTED_DEFAULTS = {
    "math": {"captions": False, "sfx": False},
    "english": {"captions": False, "sfx": False},
    "pdoom": {"captions": False, "sfx": True},
    "stage-full": {"captions": True, "sfx": True},
    "stage-light": {"captions": True, "sfx": True},
    "collage": {"captions": True, "sfx": True},
    "starline": {"captions": True, "sfx": True},
}


class DesignCatalogTest(unittest.TestCase):
    def test_installed_cards_and_default_table(self):
        catalog = designs.catalog()
        self.assertIn(set(catalog), ({"stage-full", "stage-light"}, set(designs.DESIGN_IDS)))
        for identity in catalog:
            expected = EXPECTED_DEFAULTS[identity]
            with self.subTest(identity=identity):
                card = catalog[identity]
                self.assertEqual(identity, card["id"])
                self.assertIsInstance(card["version"], int)
                self.assertGreaterEqual(card["version"], 1)
                self.assertNotIn("author_model", card)
                self.assertIsInstance(card["compatibility"], dict)
                values = designs.defaults(identity)
                self.assertEqual(expected["captions"], values["captions.enabled"])
                self.assertEqual(expected["sfx"], values["sfx.enabled"])
                self.assertTrue(values["cover.enabled"])

    def test_adopted_card_is_independent_of_installed_catalog(self):
        import lines
        card = designs.get('stage-full')
        state = {'line': {'id': 'stage-full', 'version': card['version']}, 'design_snapshot': card,
                 'design_sha256': lines.card_digest(card)}
        with mock.patch.object(designs, 'catalog', side_effect=AssertionError('latest read')):
            self.assertEqual(card, lines.frozen(state))
        state['design_snapshot']['defaults']['captions']['enabled'] = False
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            lines.frozen(state)

    def test_bgm_is_an_unknown_field(self):
        self.assertNotIn("bgm", designs.SCHEMA)
        with self.assertRaisesRegex(designs.DesignError, "Unknown override field: bgm"):
            designs.resolve("stage-full", variant={"bgm": {"enabled": True}})

    def test_identity_version_and_declarations_are_separate_from_overrides(self):
        card = designs.get("stage-full")
        self.assertEqual({"id", "version", "compatibility"}, {"id", "version", "compatibility"} & set(card))
        # An identity is never silently replaced by an ordinary appearance field.
        self.assertTrue(set(designs.FIELDS).issuperset({"captions.enabled", "sfx.enabled", "cover.enabled"}))
        with self.assertRaisesRegex(designs.DesignError, "Unknown override field: design"):
            designs.resolve("stage-full", account={"design": "math"})

    def test_retired_identities_reselect_and_history_locates(self):
        for identity, hint in (("explainer", "stage-full"), ("showcase", "pdoom"),
                               ("showcase/pdoom", "pdoom"), ("science", "collage")):
            with self.subTest(identity=identity), self.assertRaisesRegex(designs.DesignError, "retired"):
                designs.require(identity)
        with self.assertRaisesRegex(designs.DesignError, "reselect"):
            designs.require("card")
        import lines
        self.assertEqual("explainer", lines.frozen({"line": {"id": "explainer", "version": 1}})["id"])
        if "collage" in designs.catalog():
            self.assertEqual("showcase/science", lines.frozen({"line": {"id": "showcase/science", "version": 1}})["id"])
        else:
            with self.assertRaisesRegex(ValueError, "personal package"):
                lines.select({"mode": "showcase", "submodule": "science"})
        self.assertEqual({"id": "explainer", "version": 1}, lines.bind({"mode": "explainer"}))
        with self.assertRaises(ValueError):
            lines.frozen({"line": {"id": "card", "version": 1}})


class LayerMergeTest(unittest.TestCase):
    def test_five_layer_order_and_sources(self):
        result = designs.resolve(
            "stage-full",
            series={"captions": {"enabled": False}},
            work={"captions": {"enabled": True}},
            account={"captions": {"enabled": False}, "fps": 24},
            variant={"captions": {"enabled": True}},
        )
        self.assertEqual(True, result["values"]["captions.enabled"])
        self.assertEqual("variant", result["sources"]["captions.enabled"])
        self.assertEqual("account", result["sources"]["fps"])
        self.assertEqual(24, result["values"]["fps"])

    def test_omit_inherits_false_and_legal_zero_are_values(self):
        base = designs.resolve("stage-full")
        self.assertEqual("design", base["sources"]["captions.enabled"])
        overridden = designs.resolve("stage-full", account={"captions": {"enabled": False}, "seed": 0})
        self.assertEqual(False, overridden["values"]["captions.enabled"])
        self.assertEqual("account", overridden["sources"]["captions.enabled"])
        self.assertEqual(0, overridden["values"]["seed"])
        self.assertEqual("account", overridden["sources"]["seed"])
        # Removing the field from the layer restores the design default.
        restored = designs.resolve("stage-full", account={})
        self.assertTrue(restored["values"]["captions.enabled"])
        self.assertEqual("design", restored["sources"]["captions.enabled"])

    def test_unknown_and_invalid_fields_reject(self):
        cases = (
            ({"account": {"unknown": 1}}, "Unknown override field"),
            ({"variant": {"captions": {"enabled": "on"}}}, "must be a boolean"),
            ({"variant": {"fps": 0}}, "at least 1"),
            ({"variant": {"fps": True}}, "must be an integer"),
            ({"variant": {"voice": {"duration_factor": 0}}}, "positive finite"),
            ({"variant": {"voice": {"duration_factor": -1}}}, "positive finite"),
            ({"variant": {"voice": {"duration_factor": float("inf")}}}, "finite number"),
            ({"variant": {"voice": {"ref": 5}}}, "must be a string"),
        )
        for layers, message in cases:
            with self.subTest(layers=layers), self.assertRaisesRegex(designs.DesignError, message):
                designs.resolve("stage-full", **layers)

    def test_resource_references_replace_atomically(self):
        first = {"ref": "theme@v1", "kind": "theme", "package_sha256": "a" * 64}
        second = {"ref": "theme@v2", "kind": "theme", "package_sha256": "b" * 64}
        resolved = designs.resolve("stage-full", series={"cover": {"theme": first}}, account={"cover": {"theme": second}})
        self.assertEqual(second, resolved["values"]["cover.theme"])
        with self.assertRaisesRegex(designs.DesignError, "exact ref/kind/package_sha256"):
            designs.resolve("stage-full", variant={"cover": {"theme": {"ref": "theme@v3"}}})
        with self.assertRaisesRegex(designs.DesignError, "exact ref/kind/package_sha256"):
            designs.resolve("stage-full", variant={"cover": {"theme": {"ref": "theme@v3", "kind": "theme", "package_sha256": "x"}}})


class DesignCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(REPO / ".studio/templates", self.root / ".studio/templates")
        environment = mock.patch.dict(os.environ, {"HYPERFRAMES_AI_ASSET_ROOT": str(self.root / "store"),
            "HYPERFRAMES_AI_ASSET_CONFIG": str(self.root / "assets.json"), "HYPERFRAMES_AI_REVIEW": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        cli.account_service(self.root).put("account", "a", {"name": "A"})
        cli.account_service(self.root).put("account", "b", {"name": "B"})
        cli.account_service(self.root).put("series", "alpha", {"name": "Alpha"})

    def invoke(self, *arguments):
        parsed = cli.build_parser().parse_args(["--json", *arguments])
        with redirect_stdout(io.StringIO()) as output:
            parsed.handler(self.root, parsed)
        return output.getvalue().strip()

    def new_work(self, title, *extra):
        return self.invoke("new", title, "--workflow", "hyperframes_video", "--purpose", "standard",
                           "--series", "alpha", "--account", "a", "--variant-id", "main", *extra)

    def variant(self, work_id, name="main"):
        work, _ = cli.locate_work(self.root, work_id)
        return cli.read_json(work / "variants" / name / "variant.yaml")

    def test_work_cli_creates_all_six_designs(self):
        for identity in designs.catalog():
            with self.subTest(identity=identity):
                work_id = self.new_work("Work " + identity, "--design", identity)
                state = self.variant(work_id)
                self.assertEqual(identity, state["design"])
                self.assertEqual({"id": identity, "version": designs.get(identity)["version"]}, state["line"])
                expected = EXPECTED_DEFAULTS[identity]
                self.assertEqual(expected["captions"], state["captions"])
                self.assertEqual(expected["sfx"], state["sfx"]["enabled"])
                self.assertTrue(state["cover"]["enabled"])
                if "appearance_lock" in state:
                    self.assertEqual(expected["captions"], state["appearance_lock"]["selection"]["captions"])

    def test_design_and_account_change_and_series_inheritance(self):
        first = self.new_work("First", "--design", "stage-light")
        self.assertEqual("stage-light", self.variant(first)["design"])
        work, _ = cli.locate_work(self.root, first)
        self.invoke("--work", first, "variant", "add", "stage", "--design", "stage-full", "--account", "b")
        changed = self.variant(first, "stage")
        self.assertEqual("stage-full", changed["design"])
        self.assertEqual("b", changed["account"])
        # Two Variants with different account/design pairs make an unset choice
        # ambiguous; an explicitly selected design is honored for the new Work.
        with self.assertRaisesRegex(cli.HarnessError, "multiple account/design"):
            self.new_work("Second")
        second = self.new_work("Second", "--design", "stage-full")
        self.assertEqual("stage-full", self.variant(second)["design"])

    def test_retired_identity_fails_creation_with_guidance(self):
        for identity in ("explainer", "showcase", "science", "card"):
            with self.subTest(identity=identity), self.assertRaisesRegex(cli.HarnessError, "retired"):
                self.new_work("Bad " + identity, "--design", identity)
        self.assertFalse(list((self.root / "works" / "active").glob("work-*")))

    def test_account_overrides_feed_the_five_layer_chain(self):
        cli.account_service(self.root).put("account", "a", {"name": "A", "design": "stage-full",
                                                            "overrides": {"captions": {"enabled": False}, "seed": 7}})
        work_id = self.new_work("Overridden")
        state = self.variant(work_id)
        self.assertEqual("stage-full", state["design"])
        self.assertFalse(state["captions"])
        self.assertEqual("account", state["design_sources"]["captions.enabled"])
        self.assertEqual(7, state["seed"])
        self.assertEqual("account", state["design_sources"]["seed"])

    def test_unknown_account_override_rejects(self):
        with self.assertRaisesRegex(cli.HarnessError, "Unknown override field"):
            cli.account_service(self.root).put("account", "c", {"name": "C", "overrides": {"bgm": {"enabled": True}}})


if __name__ == "__main__":
    unittest.main()
