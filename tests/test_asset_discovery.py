import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_asset_store as fixtures
STORE = fixtures.STORE


class DiscoveryTest(unittest.TestCase):
    setUp = fixtures.AssetStoreTest.setUp
    accept = fixtures.AssetStoreTest.accept

    def reference_source(self):
        directory = self.root / "references"
        directory.mkdir()
        STORE.register_source(self.store, directory)
        metadata = {"source_ref": "card-family-v1", "title": "Card family", "purpose": "Explain relationships",
                    "tags": ["cards"], "workflow_role": "derive", "primary_category": "text",
                    "classification_status": "approved", "limits": ["Not installable"], "entry": "index.html"}
        (directory / "manifest.json").write_text(json.dumps(metadata))
        (directory / "index.html").write_text("<main>fixture</main>")
        return directory, metadata

    def test_self_described_sources_recipes_and_install_boundary(self):
        directory, metadata = self.reference_source()
        recipe = {key: value for key, value in metadata.items() if key != "entry"}
        recipe.update(source_ref="card-recipe", title="Layered sequence")
        (directory / "recipe.md").write_text("---\n" + json.dumps(recipe) + "\n---\n# Recipe\n", encoding="utf-8-sig")
        (directory / "unknown.md").write_text("# Undescribed recipe")
        (directory / "notes.md").write_text("---\ntitle: Ordinary note\ntags: [notes]\n---\n# Note")
        self.assertEqual([], STORE.legacy_discover_components(self.harness, audit=True)["audit"]["warnings"])
        (directory / "invalid.md").write_text('---\n{"source_ref": broken}\n---\n')
        warning, = STORE.legacy_discover_components(self.harness, audit=True)["audit"]["warnings"]
        self.assertEqual("invalid_discovery_metadata", warning["code"])
        (directory / "invalid.md").unlink()
        (directory / "reuse-index.json").write_text('{"accepted_scenes":["ignored"]}')
        for kind, query in (("scene-source", "relationships"), ("recipe", "Layered")):
            row, = STORE.legacy_discover_components(self.harness, query, kind=kind, include_references=True)["assets"]
            self.assertEqual(kind, row["asset_type"])
            self.assertFalse(row["available"])
            self.assertFalse(row["installable"])
            self.assertTrue(row["reference_only"])
            self.assertIn("derivation", row["use"])
        self.accept()
        metadata["source_ref"] = self.ref
        (directory / "manifest.json").write_text(json.dumps(metadata))
        selected, acceptance = STORE.resolve_component(self.harness, self.ref)
        self.assertTrue(selected.is_relative_to(self.store / "packages"))
        self.assertEqual(self.ref, acceptance["component_ref"])

    def test_readonly_audit_incomplete_missing_and_unsafe_sources(self):
        directory, metadata = self.reference_source()
        for name, data in (("entry-only", {"entry": "index.html"}), ("ref-only", {"source_ref": "unfinished"}),
                           ("unknown", {"files": ["index.html"]})):
            child = directory / name
            child.mkdir()
            (child / "manifest.json").write_text(json.dumps(data))
        child = directory / "accepted-undescribed"
        child.mkdir()
        (child / "ACCEPTANCE.json").write_text("{}")
        (directory / "request.json").write_text('{"entry":"requested.html"}')
        (directory / "repair.json").write_text('{"source_ref":"repair-only"}')
        (directory / "index.html").unlink()
        outside = self.root / "outside.html"
        outside.write_text("private fixture")
        for name, entry in (("traversal", "../../outside.html"), ("absolute", str(outside)), ("symlink", "linked.html")):
            child = directory / name
            child.mkdir()
            (child / "manifest.json").write_text(json.dumps({**metadata, "entry": entry}))
            if name == "symlink":
                (child / entry).symlink_to(outside)
        (directory / "linked.md").symlink_to(outside)
        loop = directory / "loop"
        loop.mkdir()
        (loop / "manifest.json").symlink_to("manifest.json")
        entry_loop = directory / "entry-loop"
        entry_loop.mkdir()
        (entry_loop / "manifest.json").write_text(json.dumps(metadata))
        (entry_loop / "index.html").symlink_to("index.html")
        self.accept()
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        with patch.object(STORE, "_atomic_json", side_effect=AssertionError("Audit must not write")):
            result = STORE.legacy_discover_components(self.harness, audit=True)
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        warnings = result["audit"]["warnings"]
        codes = [item["code"] for item in warnings]
        self.assertEqual(2, codes.count("missing_discovery_fields"))
        self.assertIn("unknown_source_approval", codes)
        self.assertCountEqual(
            [(str(directory / name), entry) for name, entry in (
                ("traversal/manifest.json", "../../outside.html"),
                ("absolute/manifest.json", str(outside)),
                ("symlink/manifest.json", "linked.html"),
                ("linked.md", None),
                ("loop/manifest.json", None),
                ("entry-loop/manifest.json", "index.html"),
            )],
            [(item["path"], item.get("entry")) for item in warnings if item["code"] == "unsafe_reference_path"],
        )
        self.assertCountEqual(
            [{"path": str(directory / name), "code": "missing_reference_file", "entry": "index.html"}
             for name in ("manifest.json", "entry-only/manifest.json")],
            [item for item in warnings if item["code"] == "missing_reference_file"],
        )
        self.assertIn("missing_selection_fields", codes)
        self.assertFalse(any("request.json" in item["path"] or "repair.json" in item["path"] for item in warnings))
        self.assertFalse(any(row.get("reference_only") for row in result["assets"]))
        (self.store / "selection.json").write_text(json.dumps({self.ref: {"purpose": "Explain", "tags": ["text"]}}))
        self.assertFalse(any(item["code"] == "missing_selection_fields"
                            for item in STORE.legacy_discover_components(self.harness, audit=True)["audit"]["warnings"]))

    def test_reference_entry_intermediate_loops_and_missing_paths(self):
        directory, metadata = self.reference_source()
        (directory / "cycle").symlink_to("cycle", target_is_directory=True)
        (directory / "link-a").symlink_to("link-b", target_is_directory=True)
        (directory / "link-b").symlink_to("link-a", target_is_directory=True)
        (directory / "valid-link.html").symlink_to("index.html")
        (directory / "broken-link.html").symlink_to("absent.html")
        outside = self.root / "outside-dir"
        outside.mkdir()
        (directory / "escape").symlink_to(outside, target_is_directory=True)
        for entry, expected in (("cycle/index.html", "unsafe_reference_path"),
                                ("link-a/index.html", "unsafe_reference_path"),
                                ("broken-link.html", "unsafe_reference_path"),
                                ("escape/missing.html", "unsafe_reference_path"),
                                ("absent.html", "missing_reference_file"),
                                ("absent/index.html", "missing_reference_file"),
                                ("valid-link.html", None)):
            with self.subTest(entry=entry):
                (directory / "manifest.json").write_text(json.dumps({**metadata, "entry": entry}))
                with patch.object(STORE, "_atomic_json", side_effect=AssertionError("Audit must not write")):
                    result = STORE.legacy_discover_components(self.harness, audit=True)
                warnings = [item["code"] for item in result["audit"]["warnings"]
                            if item["path"] == str(directory / "manifest.json")]
                self.assertEqual([] if expected is None else [expected], warnings)

    def test_cli_and_doctor_audit(self):
        from contextlib import redirect_stdout
        import io
        import work
        import windows_runtime
        import subprocess
        directory, metadata = self.reference_source()
        args = work.build_parser().parse_args(["component", "list", "--kind", "scene-source", "--query", "cards", "--include-references", "--audit"])
        self.assertTrue(args.audit)
        output = io.StringIO()
        with redirect_stdout(output), patch.object(STORE, "_atomic_json", side_effect=AssertionError("CLI audit must not write")):
            work.command_component_store(self.harness, args)
        self.assertEqual([], json.loads(output.getvalue())["assets"])  # Legacy sources are not active card discovery.
        (self.harness / ".release.json").write_text('{"release":"fixture"}')
        config = {"asset_root": str(self.store), "asset_source_roots": [str(directory)]}
        env = {key: "fixture" for key in ("HYPERFRAMES_AI_CONFIG", "HYPERFRAMES_AI_ASSET_CONFIG", "TEMP", "HYPERFRAMES_NODE",
               "HYPERFRAMES_CLI", "HYPERFRAMES_BROWSER_PATH", "FFMPEG_PATH", "FFPROBE_PATH")}
        env.update(HYPERFRAMES_AI_RESOLVED_CONFIG=json.dumps(config), HYPERFRAMES_AI_REVIEW="0")
        with patch.object(windows_runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
             patch.object(STORE, "_atomic_json", side_effect=AssertionError("Doctor audit must not write")):
            result = windows_runtime.doctor(self.harness, env)
        self.assertEqual({"warning_count": 0, "error_count": 0}, result["asset_audit"])

    def test_incremental_selection_missing_files_and_acceptance(self):
        self.accept()
        first = STORE.legacy_discover_components(self.harness)
        self.assertTrue(first["refreshed"])
        self.assertFalse(STORE.legacy_discover_components(self.harness)["refreshed"])
        accepted = next(row for row in first["assets"] if row["origin"] == "accepted")
        self.assertEqual("pending", accepted["recommendation"])
        self.assertIn("metadata-only", accepted["check_scope"])
        metadata = self.store / "selection.json"
        metadata.write_text(json.dumps({self.ref: {"aliases": ["章节开场"], "tags": ["title"], "recommendation": "recommended"}}, ensure_ascii=False))
        found = STORE.legacy_discover_components(self.harness, "章节开场", tag="title", recommendation="recommended")
        self.assertTrue(found["assets"][0]["available"])
        self.assertEqual([str(metadata)], found["refreshed"])
        self.assertIn("aliases", found["assets"][0]["match_reasons"])
        self.assertFalse(STORE.legacy_discover_components(self.harness, ratio="unknown-format")["assets"])
        package = Path(accepted["path"])
        (package / "component.html").unlink()
        broken = STORE.legacy_discover_components(self.harness)
        self.assertFalse(any(row["available"] for row in broken["assets"]))
        self.assertTrue(broken["errors"])
        with self.assertRaises(STORE.ComponentError):
            STORE.resolve_component(self.harness, self.ref)

    def test_conflict_even_when_conflicting_package_has_missing_files(self):
        self.accept()
        work = self.root / "work-lock.json"
        work.write_text('{"unchanged":true}')
        before = work.read_bytes()
        candidate = self.store / "candidates" / STORE._relative(self.ref) / "package"
        manifest = candidate / "HASHES.json"
        data = json.loads(manifest.read_text())
        data["package_sha256"] = "0" * 64
        manifest.write_text(json.dumps(data))
        (candidate / "component.html").unlink()
        result = STORE.legacy_discover_components(self.harness)
        accepted = next(row for row in result["assets"] if row["origin"] == "accepted")
        self.assertFalse(accepted["available"])
        self.assertIn("conflict", accepted)
        self.assertEqual(result["assets"], STORE.legacy_discover_components(self.harness, rebuild=True)["assets"])
        self.assertEqual(before, work.read_bytes())
        acceptance = self.store / "acceptances" / STORE._relative(self.ref) / "acceptance.json"
        acceptance.unlink()
        self.assertFalse(any(row["available"] for row in STORE.legacy_discover_components(self.harness)["assets"]))

    def test_selection_states_query_scope_and_cache_failure(self):
        self.accept()
        for state in ("recommended", "historical", "pending"):
            with self.subTest(state=state):
                (self.store / "selection.json").write_text(json.dumps({self.ref: {
                    "aliases": ["中文别名"], "recommendation": state, "replacement": "next@v2"}}))
                rows = STORE.legacy_discover_components(self.harness, "中文别名", recommendation=state)["assets"]
                self.assertTrue(rows)
                self.assertTrue(rows[0]["available"])
                self.assertEqual(state, rows[0]["recommendation"])
        for query in (str(self.root), "automated contract tests"):
            self.assertFalse(STORE.legacy_discover_components(self.harness, query)["assets"])
        with patch.object(STORE, "_atomic_json", side_effect=OSError("read-only cache")):
            result = STORE.legacy_discover_components(self.harness, rebuild=True)
        self.assertTrue(result["assets"][0]["available"])
        self.assertTrue(result["errors"][-1]["unsynchronized"])
        self.assertFalse(STORE.legacy_discover_components(self.harness, rebuild=True)["errors"])

    def test_new_registered_sources_and_schema2_ratios(self):
        STORE.legacy_discover_components(self.harness)
        source = self.root / "new-source"
        source.mkdir()
        STORE.register_source(self.store, source)
        for ratios in (["16:9", "9:16"], []):
            (source / "asset.json").write_text(json.dumps({"id": "new-source", "version": 1,
                "schema_version": 2, "kind": "theme", "compatibility": {"ratios": ratios}}))
            rows = STORE.legacy_discover_components(self.harness, ratio="16:9" if ratios else "unknown")["assets"]
            self.assertEqual(1, len(rows))
            self.assertEqual(ratios, rows[0]["ratios"])
            self.assertEqual("source", rows[0]["group"])
            self.assertFalse(rows[0]["available"])


if __name__ == "__main__":
    unittest.main()
