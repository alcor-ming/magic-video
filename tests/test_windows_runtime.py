import importlib.util
import io
import json
from pathlib import Path
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from subprocess import CompletedProcess


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".studio"))
spec = importlib.util.spec_from_file_location("windows_runtime", Path(__file__).resolve().parents[1] / ".studio/windows_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
seed_spec = importlib.util.spec_from_file_location("prepare_windows_runtime", Path(__file__).resolve().parents[1] / ".studio/prepare_windows_runtime.py")
seed = importlib.util.module_from_spec(seed_spec)
seed_spec.loader.exec_module(seed)


class WindowsRootTest(unittest.TestCase):
    def make_root(self, base, *, review=False):
        root = base / "root with spaces \u6d4b\u8bd5"
        (root / ".studio/.runtime").mkdir(parents=True)
        (root / ".release.json").write_text(json.dumps({"release": "candidate-test" if review else "local-test",
                                                       "channel": "candidate" if review else "local"}))
        (root / "windows-runtime.lock.json").write_text("{}")
        (root / "works/active").mkdir(parents=True)
        for name in ("store", "sources"):
            (root / "asset-library" / name).mkdir(parents=True)
        config = {"work_root": str(root), "asset_root": str(root / "asset-library/store"),
                  "asset_source_roots": [str(root / "asset-library/sources")], "review": review}
        if review:
            config.update(asset_review_root=str(root / "asset-library"),
                          review_protected_roots=[str(base / "production")])
            (root / ".runtime").mkdir()
            (root / ".runtime/review.json").write_text(json.dumps({"mode": "review", "review_id": root.name}))
        path = root / ".studio/.runtime/local.json"
        path.write_text(json.dumps(config))
        return root, config, path

    def test_work_store_requires_works_but_not_legacy_lifecycle_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, config, _ = self.make_root(Path(temporary))
            self.assertEqual(config["work_root"], runtime.resolved_config(root)["work_root"])
            self.assertFalse((root / "works/parked").exists())
            self.assertFalse((root / "works/archive").exists())
            (root / "works/active").rmdir()
            self.assertEqual(config["work_root"], runtime.resolved_config(root)["work_root"])
            (root / "works").rmdir()
            with self.assertRaisesRegex(ValueError, "WorkStore missing works"):
                runtime.resolved_config(root)

    def test_doctor_reports_identity_and_invocation_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, _, _ = self.make_root(Path(temporary))
            env = runtime.environment(root)
            inherited = dict(os.environ)
            with patch.object(runtime.subprocess, 'run', return_value=CompletedProcess([], 0, 'libx264 aac', '')):
                native = runtime.doctor(root, env)
                forwarded = runtime.doctor(root, {**env, 'HYPERFRAMES_INVOCATION': 'wsl-forwarded'})
            self.assertEqual(inherited, dict(os.environ))
            self.assertEqual('windows-native', native['invocation'])
            self.assertEqual('wsl-forwarded', forwarded['invocation'])
            for key in ('backend', 'release', 'runtime', 'work_root', 'release_manifest_sha256'):
                self.assertEqual(native[key], forwarded[key])
            self.assertEqual('pending-native-render-verification', forwarded['gpu'])
            self.assertEqual({'warning_count': 0, 'error_count': 0}, forwarded['asset_audit'])

    def test_design_root_defaults_and_protected_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, config, path = self.make_root(Path(temporary))
            self.assertEqual(str(root / "asset-library/designs"), runtime.resolved_config(root)["design_root"])
            for invalid in ("relative", str(root / "works/active/cards"), str(root / ".studio/cards"),
                            config["asset_root"], str(root)):
                path.write_text(json.dumps({**config, "design_root": invalid}))
                with self.subTest(path=invalid), self.assertRaisesRegex(ValueError, "design_root"):
                    runtime.resolved_config(root)
            external = Path(temporary) / "my-cards"
            path.write_text(json.dumps({**config, "design_root": str(external)}))
            self.assertEqual(str(external), runtime.resolved_config(root)["design_root"])

    def test_review_design_root_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, config, path = self.make_root(Path(temporary), review=True)
            path.write_text(json.dumps({**config, "design_root": str(Path(temporary) / "production/cards")}))
            with self.assertRaisesRegex(ValueError, "Review"):
                runtime.resolved_config(root)

    def test_physical_root_ignores_inherited_identity_and_freezes_config(self):
        import asset_store
        with tempfile.TemporaryDirectory() as temporary:
            root, config, path = self.make_root(Path(temporary))
            pollution = {key: "missing.json" for key in ("HYPERFRAMES_AI_SESSION", "HYPERFRAMES_AI_ROOT",
                         "HYPERFRAMES_AI_HOME", "HYPERFRAMES_AI_ASSET_CONFIG", "HYPERFRAMES_AI_ASSET_ROOT")}
            with patch.dict(os.environ, pollution):
                env = runtime.environment(root)
            self.assertNotIn("HYPERFRAMES_AI_SESSION", env)
            with patch.dict(os.environ, {"NODE_OPTIONS": '--require "foreign-root.cjs"'}):
                self.assertEqual(runtime.environment(root)["NODE_OPTIONS"],
                                 "--require " + json.dumps(str(root / ".studio/windows_node.cjs"), ensure_ascii=False))
            self.assertEqual(env["HYPERFRAMES_AI_ROOT"], str(root))
            self.assertEqual(env["HYPERFRAMES_AI_CONFIG"], str(path))
            self.assertEqual(env["HYPERFRAMES_AI_ASSET_ROOT"], config["asset_root"])
            path.write_text(json.dumps({**config, "asset_source_roots": []}))
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(asset_store._configured_sources(root, Path(config["asset_root"])),
                                 config["asset_source_roots"])
                project = Path(config["asset_source_roots"][0]) / "sample"
                project.mkdir()
                self.assertEqual(asset_store.authoring_project(root, project), project)
            with patch.object(runtime, "__file__", str(root / ".studio/windows_runtime.py")), \
                 patch.dict(os.environ, pollution), patch.object(runtime.subprocess, "call", return_value=0) as call:
                self.assertEqual(runtime.main(["list"]), 0)
                self.assertEqual(call.call_args.kwargs["env"]["HYPERFRAMES_AI_ROOT"], str(root))
            self.assertFalse((root / "sessions").exists())
            self.assertFalse((root / ".harness").exists())

    def test_review_rejects_production_sources_and_accepts_independent_identity(self):
        import work_requests
        with tempfile.TemporaryDirectory() as temporary:
            root, config, path = self.make_root(Path(temporary), review=True)
            env = runtime.environment(root)
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(work_requests.review_identity(root)["review_id"], root.name)
            config["asset_source_roots"] = [str(Path(temporary) / "production/sources")]
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "Review"):
                runtime.environment(root)
            config["review"] = False
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "Candidate"):
                runtime.environment(root)

    def test_pending_update_and_running_command_block_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, _, _ = self.make_root(Path(temporary))
            with runtime.command_lock(root):
                with self.assertRaisesRegex(ValueError, "busy"):
                    with runtime.command_lock(root):
                        self.fail("Second writer acquired the root")
            (root / ".studio/.runtime/deploy-pending.json").write_text("{}")
            with patch.object(runtime, "__file__", str(root / ".studio/windows_runtime.py")):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    runtime.main(["list"])

    def test_local_acceptance_requires_physical_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, config, path = self.make_root(Path(temporary))
            config['acceptance_protected_roots'] = [str(Path(temporary) / 'production')]
            path.write_text(json.dumps(config))
            self.assertFalse(runtime.resolved_config(root)['review'])
            with patch.dict(os.environ, {'SESSION_DIR': 'old-session'}):
                with self.assertRaisesRegex(ValueError, 'session'):
                    runtime.resolved_config(root)
            for invalid in ([str(root.parent)], [], [str(root / 'nested-production')]):
                path.write_text(json.dumps({**config, 'acceptance_protected_roots': invalid}))
                with self.subTest(protected=invalid), self.assertRaises(ValueError):
                    runtime.resolved_config(root)
            path.write_text(json.dumps({**config, 'export_root': str(root.parent / 'exports')}))
            with self.assertRaisesRegex(ValueError, 'escapes'):
                runtime.resolved_config(root)
            path.write_text(json.dumps(config))
            linked = root / 'linked'
            linked.symlink_to(Path(temporary) / 'outside')
            with self.assertRaisesRegex(ValueError, 'links'):
                runtime.resolved_config(root)
            linked.unlink()
            os.link(path, linked)
            with self.assertRaisesRegex(ValueError, 'links'):
                runtime.resolved_config(root)

    @unittest.skipUnless(os.name == "nt", "Native Windows CMD")
    def test_no_argument_cmd_explains_its_purpose(self):
        result = runtime.subprocess.run([os.environ["COMSPEC"], "/d", "/c",
                                         str(Path(__file__).resolve().parents[1] / "work.cmd")],
                                        input="\n", capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("production session", result.stdout)

    def test_launcher_loads_siblings_under_isolated_python(self):
        code = ("import importlib.util,sys; "
                "s=importlib.util.spec_from_file_location('launcher',sys.argv[1]); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "from work_requests import review_identity")
        result = runtime.subprocess.run([sys.executable, "-I", "-S", "-c", code, str(spec.origin)],
                                        capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_seed_checks_locked_registry_and_cached_bytes_without_network(self):
        lock = seed.read(Path(__file__).resolve().parents[1] / "windows-npm.lock.json")
        seed.validate_npm_lock(lock)
        lock["packages"]["node_modules/gsap"]["resolved"] = "https://untrusted.invalid/package.tgz"
        with self.assertRaisesRegex(ValueError, "registry URL"):
            seed.validate_npm_lock(lock)
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary) / "asset.zip"
            asset.write_bytes(b"locked")
            expected = seed.digest(asset)
            self.assertEqual(seed.download("", asset, expected), expected)
            asset.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                seed.download("", asset, expected)

    def test_prepare_updates_versions_and_verifies_archive_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            npm_lock = base / "npm.json"
            npm_lock.write_text("{}")
            archive = base / "npm.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("node_modules/hyperframes/bin/hyperframes.mjs", "// fixture")
            required = "runtime/npm/node_modules/hyperframes/bin/hyperframes.mjs"
            definition = {"python": "3.14.0", "versions": {"hyperframes": "old"},
                          "assets": [], "required_files": [required]}
            source, output = base / "windows-runtime.lock.json", base / "prepared.json"
            source.write_text(json.dumps(definition))
            with patch.object(seed, "REPO", base), patch.object(seed, "ARCHIVES", []), \
                    patch.object(seed, "urlopen", side_effect=lambda *a, **k: io.BytesIO(b"")), \
                    patch.object(seed, "npm_archive", return_value=archive):
                seed.prepare(base, npm_lock, output)
                result = seed.read(output)
                self.assertEqual(result["versions"]["hyperframes"], seed.VERSIONS["hyperframes"])
                self.assertEqual(result["versions"]["onnxruntime-node"], "1.21.1")
                self.assertEqual(result["assets"][0]["sha256"], seed.digest(archive))
                self.assertEqual(result["assets"][0]["package_lock_sha256"], seed.digest(npm_lock))
                definition["required_files"].append("runtime/npm/missing.dll")
                source.write_text(json.dumps(definition))
                with self.assertRaisesRegex(ValueError, "missing.dll"):
                    seed.prepare(base, npm_lock, output)
                self.assertEqual(seed.read(output), result)

    def test_seed_preserves_pinned_loader_native_dependencies(self):
        lock = seed.read(Path(__file__).resolve().parents[1] / "windows-npm.lock.json")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            metadata = []
            for key in list(lock["packages"]):
                if key == "node_modules/koffi" or key.startswith("node_modules/@koromix/koffi-"):
                    package = lock["packages"].pop(key)
                    package.update(name=key.removeprefix("node_modules/"),
                                   dist={"tarball": package["resolved"], "integrity": package["integrity"]})
                    path = base / f"metadata-{len(metadata)}.json"
                    path.write_text(json.dumps(package))
                    metadata.append(path)
            source, output = base / "source.json", base / "output.json"
            source.write_text(json.dumps(lock))
            seed.seed_lock(source, metadata, output)
            result = seed.read(output)["packages"]
            self.assertEqual(result[""]["dependencies"]["koffi"], seed.VERSIONS["koffi"])
            self.assertEqual(result["node_modules/koffi"]["optionalDependencies"]["@koromix/koffi-win32-x64"],
                             seed.VERSIONS["koffi"])
            self.assertEqual(result["node_modules/@koromix/koffi-win32-x64"]["os"], ["win32"])
            self.assertTrue(result["node_modules/@koromix/koffi-win32-x64"]["optional"])



if __name__ == "__main__":
    unittest.main()
