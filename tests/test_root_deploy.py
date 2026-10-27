import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".studio"))
import root_deploy as deploy
from windows_runtime import command_lock


class RootDeploymentTests(unittest.TestCase):
    def test_personal_pruning_adopts_only_matching_files_and_rollback_keeps_deletions(self):
        old = self.package('public')
        skill = '.agents/skills/drop/SKILL.md'
        self.add_files(old, {skill: 'removed locally', 'AGENTS.md': 'public rules', 'skills-lock.json': 'full'})
        deploy.deploy(old, self.root, self.config)
        (self.root / skill).unlink()
        (self.root / 'AGENTS.md').write_text('personal rules')
        (self.root / 'skills-lock.json').write_text('pruned')
        new = self.package('personal')
        self.add_files(new, {'AGENTS.md': 'personal rules', 'skills-lock.json': 'pruned'})
        proposed = deploy.read(new / '.release.json')['files']
        retained = set(proposed) | {'.release.json'}
        with self.assertRaisesRegex(ValueError, 'Locally modified'):
            deploy.preflight(self.root, retained=retained)
        self.assertEqual('ready', deploy.preflight(self.root, retained=retained, expected=proposed)['status'])
        (self.root / 'AGENTS.md').write_text('unrelated local edit')
        with self.assertRaisesRegex(ValueError, 'Locally modified'):
            deploy.preflight(self.root, retained=retained, expected=proposed)
        with self.assertRaisesRegex(ValueError, 'Locally modified'):
            deploy.deploy(new, self.root, None)
        (self.root / 'AGENTS.md').write_text('personal rules')
        result = deploy.deploy(new, self.root, None)
        self.assertNotIn(skill, result['files'])
        self.assertFalse((self.root / skill).exists())
        deploy.verify_root(self.root)
        restored = deploy.recover(self.root, rollback=True)
        self.assertFalse((self.root / skill).exists())
        self.assertEqual('personal rules', (self.root / 'AGENTS.md').read_text())
        self.assertEqual('pruned', (self.root / 'skills-lock.json').read_text())
        self.assertEqual('restored_with_local_modifications', restored['integrity'])
        self.assertIn(skill, restored['restored_modified_files'])

    def test_personal_cards_retire_identical_user_copies_and_refuse_divergent_ones(self):
        package = self.package('cards')
        card = {'.studio/designs/mycard/design.json': '{"id": "mycard"}', '.studio/designs/mycard/assets/a.txt': 'asset'}
        self.add_files(package, card)
        manifest = deploy.read(package / '.release.json')
        manifest['personal_source'] = {'cards': {'commit': 'a' * 40, 'ids': ['mycard']}}
        (package / '.release.json').write_text(json.dumps(manifest))
        user = self.root / 'asset-library/designs/mycard'
        (user / 'assets').mkdir(parents=True)
        (user / 'design.json').write_text('{"id": "mycard"}')
        (user / 'assets/a.txt').write_text('edited in production')
        (self.root / 'asset-library/designs/other').mkdir()
        with self.assertRaisesRegex(ValueError, 'differs from the deployed card.*assets/a.txt'):
            deploy.deploy(package, self.root, self.config)
        self.assertFalse((self.root / deploy.MANIFEST).exists())
        self.assertFalse((self.root / '.studio/designs/mycard').exists())
        (user / 'assets/a.txt').write_text('asset')
        (user / 'study').mkdir()
        (user / 'study/notes.md').write_text('research stays with the retired copy')
        result = deploy.deploy(package, self.root, self.config)
        retired = self.root / 'asset-library' / ('designs-retired-' + deploy.time.strftime('%Y%m%d')) / 'mycard'
        self.assertEqual([{'card': 'mycard', 'from': str(user), 'to': str(retired)}], result['user_cards']['retired'])
        self.assertFalse(user.exists())
        self.assertTrue((self.root / 'asset-library/designs/other').is_dir())
        self.assertEqual('research stays with the retired copy', (retired / 'study/notes.md').read_text())
        self.assertEqual('asset', (self.root / '.studio/designs/mycard/assets/a.txt').read_text())
        again = deploy.deploy(package, self.root, None)
        self.assertEqual('unchanged', again['status'])
        self.assertEqual({'retired': [], 'failed': []}, again['user_cards'])

    def test_idle_ignores_host_cwd_but_blocks_root_children(self):
        root = r'D:\AI\AI+hyperframes'
        host = {'ProcessId': 987654, 'CommandLine': 'node kernel.js --working-dir ' + root,
                'ExecutablePath': r'C:\Codex\node.exe'}
        with patch.object(deploy.os, 'name', 'nt'), patch.object(deploy.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps([host])
            deploy.idle(root)
            script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|node|ffmpeg|ffprobe|chrome|chrome-headless-shell|esbuild)(\\.exe)?$' } | Select-Object ProcessId,CommandLine,ExecutablePath | ConvertTo-Json -Compress"
            run.assert_called_once_with(['powershell.exe', '-NoLogo', '-NoProfile', '-Command', script],
                                        capture_output=True, encoding='utf-8', check=True)
            for command in (root + r'\runtime\node\node.exe', 'node ' + root + r'\works\build.js'):
                run.return_value.stdout = json.dumps([{**host, 'CommandLine': command}])
                with self.assertRaisesRegex(ValueError, 'is active'):
                    deploy.idle(root)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        for name in ("works/active", "works/parked", "works/archive", "asset-library/store", "asset-library/sources/demo"):
            (self.root / name).mkdir(parents=True)
        self.config = self.base / "config.json"
        self.settings = {"work_root": str(self.root), "asset_root": str(self.root / "asset-library/store"), "asset_review_root": str(self.root / "asset-library"), "asset_source_roots": [str(self.root / "asset-library/sources/demo")], "review": True, "review_protected_roots": [str(self.base / "production")]}
        self.config.write_text(json.dumps(self.settings))

    def package(self, name):
        root = self.base / name
        root.mkdir()
        (root / "work.cmd").write_text(name)
        deploy.write_json(root / ".release.json", {"release": "candidate-" + name, "channel": "candidate", "target": "windows-x64", "layout": "root-v1", "files": {"work.cmd": deploy.digest(root / "work.cmd")}})
        return root

    def add_files(self, package, files):
        manifest = deploy.read(package / ".release.json")
        for name, content in files.items():
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            manifest["files"][name] = deploy.digest(path)
        (package / ".release.json").write_text(json.dumps(manifest))

    def test_deployment_and_preflight_only_require_workstore_root(self):
        (self.root / 'works/parked').rmdir()
        (self.root / 'works/archive').rmdir()
        package = self.package('active-only')
        self.assertEqual('ready', deploy.preflight(self.root, self.config)['status'])
        deploy.deploy(package, self.root, self.config)
        deploy.verify_root(self.root)
        self.assertEqual('ready', deploy.preflight(self.root)['status'])
        self.assertFalse((self.root / 'works/parked').exists())
        self.assertFalse((self.root / 'works/archive').exists())
        (self.root / 'works/active').rmdir()
        self.assertEqual('ready', deploy.preflight(self.root)['status'])
        (self.root / 'works').rmdir()
        with self.assertRaisesRegex(ValueError, 'Missing WorkStore directory: works'):
            deploy.preflight(self.root)

    def test_incremental_backup_removal_and_two_step_rollback(self):
        first = self.package("one")
        self.add_files(first, {"runtime/python/python.exe": "fixed", "obsolete.txt": "old"})
        deploy.deploy(first, self.root, self.config)
        runtime = self.root / "runtime/python/python.exe"
        stamp = runtime.stat().st_mtime_ns
        second = self.package("two")
        self.add_files(second, {"runtime/python/python.exe": "fixed", "new.txt": "new"})
        result = deploy.deploy(second, self.root, None)
        self.assertEqual(runtime.stat().st_mtime_ns, stamp)
        self.assertFalse((self.root / result["backup"] / "runtime").exists())
        self.assertFalse((self.root / "obsolete.txt").exists())
        third = self.package("three")
        self.add_files(third, {"runtime/python/python.exe": "fixed", "new.txt": "newer"})
        deploy.deploy(third, self.root, None)
        self.assertEqual(len(list((self.root / deploy.STATE / "deploy-backups").iterdir())), 1)
        deploy.recover(self.root, rollback=True)
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        with self.assertRaises((ValueError, OSError)):
            deploy.recover(self.root, rollback=True)
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(runtime.read_text(), "fixed")

    def test_preflight_rejects_changes_and_recovers_valid_pending_once(self):
        deploy.deploy(self.package('preflight'), self.root, self.config)
        self.assertEqual('ready', deploy.preflight(self.root)['status'])
        state = deploy.read(self.root / deploy.MANIFEST)
        transaction = deploy.read(self.root / state['backup'] / 'transaction.json')
        deploy.write_json(self.root / deploy.PENDING, transaction)
        with self.assertRaisesRegex(ValueError, 'Interrupted deployment'):
            deploy.preflight(self.root)
        # The completed first install can be rolled back; preflight then revalidates the supplied config.
        result = deploy.preflight(self.root, self.config, recover_pending=True)
        self.assertTrue(result['recovered'])
        self.assertFalse((self.root / deploy.PENDING).exists())
        deploy.deploy(self.package('after-preflight'), self.root, self.config)
        (self.root / 'work.cmd').write_text('user edit')
        with self.assertRaisesRegex(ValueError, 'Locally modified'):
            deploy.preflight(self.root)

    def test_identical_candidate_preserves_previous_rollback(self):
        first, second = self.package('original'), self.package('new')
        deploy.deploy(first, self.root, self.config)
        adopted = deploy.deploy(second, self.root, None)
        again = deploy.deploy(second, self.root, None)
        self.assertEqual('unchanged', again['status'])
        self.assertEqual(adopted['backup'], again['backup'])
        deploy.recover(self.root, rollback=True)
        self.assertEqual('original', (self.root / 'work.cmd').read_text())

    def test_retention_preserves_legacy_unknown_modified_and_failed_backups(self):
        deploy.deploy(self.package("one"), self.root, self.config)
        parent = self.root / deploy.STATE / "deploy-backups"
        legacy = parent / ("a" * 32)
        legacy.mkdir()
        (legacy / "transaction.json").write_text("{}")
        original = deploy.replace_file
        def fail(source, destination, data=None):
            if source and Path(source).name == "work.cmd" and Path(source).read_text() == "failure":
                raise OSError("failure")
            original(source, destination, data)
        with patch.object(deploy, "replace_file", side_effect=fail):
            with self.assertRaisesRegex(OSError, "failure"):
                deploy.deploy(self.package("failure"), self.root, None)
        failed = next(path for path in parent.iterdir() if path != legacy and not (path / "completed.json").exists())
        result = deploy.deploy(self.package("two"), self.root, None)
        modified = self.root / result["backup"]
        (modified / "user.txt").write_text("keep me")
        deploy.deploy(self.package("three"), self.root, None)
        result = deploy.deploy(self.package("four"), self.root, None)
        self.assertTrue(legacy.exists())
        self.assertTrue(failed.exists())
        self.assertEqual((modified / "user.txt").read_text(), "keep me")
        self.assertEqual(len(result["cleanup"]["retained"]), 3)
        deploy.write_json(self.root / deploy.PENDING, {})
        with self.assertRaisesRegex(ValueError, "Interrupted"):
            deploy.prune_backups(self.root)

    def test_tools_package_pins_runtime_and_can_roll_back(self):
        full = self.package("full")
        self.add_files(full, {"windows-runtime.lock.json": "locked", "runtime/python/python.exe": "fixed"})
        initial = deploy.deploy(full, self.root, self.config)
        tools = self.package("tools")
        self.add_files(tools, {"windows-runtime.lock.json": "locked"})
        manifest = deploy.read(tools / ".release.json")
        manifest.update(package_kind="tools", runtime_files={"runtime/python/python.exe": initial["files"]["runtime/python/python.exe"]},
                        runtime_lock_sha256=initial["files"]["windows-runtime.lock.json"])
        (tools / ".release.json").write_text(json.dumps(manifest))
        result = deploy.deploy(tools, self.root, None)
        self.assertFalse((self.root / result["backup"] / "runtime").exists())
        self.assertIn("runtime/python/python.exe", result["files"])
        deploy.recover(self.root, rollback=True)
        self.assertEqual(deploy.verify_root(self.root)["release"], "candidate-full")
        manifest["runtime_files"]["runtime/python/python.exe"] = "0" * 64
        (tools / ".release.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Installed runtime differs"):
            deploy.deploy(tools, self.root, None)
        manifest["runtime_lock_sha256"] = "1" * 64
        (tools / ".release.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "runtime lock mismatch"):
            deploy.verify_package(tools)

    def test_retention_does_not_follow_links(self):
        deploy.deploy(self.package("one"), self.root, self.config)
        parent = self.root / deploy.STATE / "deploy-backups"
        external = self.base / "external"
        external.mkdir()
        (external / "valuable").write_text("keep")
        link = parent / ("b" * 32)
        if os.name == "nt":
            subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(external)], check=True, capture_output=True)
            self.addCleanup(lambda: os.rmdir(link))
        else:
            link.symlink_to(external, target_is_directory=True)
        with command_lock(self.root):
            result = deploy.prune_backups(self.root)
        self.assertEqual(len(result["retained"]), 1)
        self.assertEqual((external / "valuable").read_text(), "keep")

    def test_update_rollback_preserves_user_content_and_config(self):
        first = self.package("one")
        deploy.deploy(first, self.root, self.config)
        user = self.root / ".agents/skills/user/SKILL.md"
        user.parent.mkdir(parents=True)
        user.write_text("user content")
        content = self.root / "works/active/scene.html"
        content.write_text("M2-M3 content")
        config = (self.root / deploy.CONFIG).read_bytes()
        deploy.deploy(self.package("two"), self.root, None)
        self.assertEqual(deploy.verify_root(self.root)["release"], "candidate-two")
        deploy.recover(self.root, rollback=True)
        self.assertEqual(deploy.verify_root(self.root)["release"], "candidate-one")
        self.assertEqual(user.read_text(), "user content")
        self.assertEqual(content.read_text(), "M2-M3 content")
        self.assertEqual((self.root / deploy.CONFIG).read_bytes(), config)
        self.assertFalse((self.root / ".harness").exists())

    def test_strict_package_and_managed_root_are_different(self):
        package = self.package("one")
        (package / "extra.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "Unmanifested"):
            deploy.verify_package(package)
        (package / "extra.txt").unlink()
        deploy.deploy(package, self.root, self.config)
        (self.root / "extra.txt").write_text("x")
        deploy.verify_root(self.root)
        (self.root / "work.cmd").write_text("user edit")
        with self.assertRaisesRegex(ValueError, "Locally modified"):
            deploy.deploy(self.package("two"), self.root, None)
        with self.assertRaisesRegex(ValueError, "Locally modified"):
            deploy.recover(self.root, rollback=True)

    def test_unmanaged_collision_and_links_rejected(self):
        package = self.package("one")
        (self.root / "work.cmd").write_text("old entry")
        with self.assertRaisesRegex(ValueError, "Unmanaged"):
            deploy.deploy(package, self.root, self.config)
        retained = {"work.cmd", ".release.json"}
        with self.assertRaisesRegex(ValueError, "Unmanaged"):
            deploy.preflight(self.root, self.config, retained=retained, expected={"work.cmd": deploy.digest(package / "work.cmd")})
        (self.root / "work.cmd").write_text("one")
        self.assertEqual("ready", deploy.preflight(self.root, self.config, retained=retained,
                                                    expected={"work.cmd": deploy.digest(package / "work.cmd")})["status"])
        with self.assertRaisesRegex(ValueError, "Unmanaged"):
            deploy.preflight(self.root, self.config, retained=retained)
        (self.root / "work.cmd").unlink()
        link = self.root / "asset-library/sources/demo/link"
        if os.name == "nt":
            subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(self.base)], check=True, capture_output=True)
            self.addCleanup(lambda: os.rmdir(link))
        else:
            link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Links"):
            deploy.deploy(package, self.root, self.config)

    def test_identical_unmanaged_file_is_adopted(self):
        package = self.package("adopt")
        self.add_files(package, {"personal/tool.md": "same bytes"})
        (self.root / "personal").mkdir()
        (self.root / "personal/tool.md").write_text("same bytes")
        result = deploy.deploy(package, self.root, self.config)
        self.assertIn("personal/tool.md", result["files"])
        deploy.verify_root(self.root)
        self.assertEqual("same bytes", (self.root / "personal/tool.md").read_text())

    def test_failed_copy_restores_and_pending_recovery(self):
        deploy.deploy(self.package("one"), self.root, self.config)
        package = self.package("two")
        replace = deploy.os.replace
        def fail(source, target):
            if Path(source).name.startswith("work.cmd.deploy-") and Path(source).read_text() == "two":
                raise OSError("injected copy failure")
            return replace(source, target)
        with patch.object(deploy.os, "replace", side_effect=fail):
            with self.assertRaisesRegex(OSError, "injected"):
                deploy.deploy(package, self.root, None)
        self.assertEqual(deploy.verify_root(self.root)["release"], "candidate-one")
        deploy.deploy(package, self.root, None)
        state = deploy.verify_root(self.root)
        transaction = deploy.read(self.root / state["backup"] / "transaction.json")
        deploy.write_json(self.root / deploy.PENDING, transaction)
        with self.assertRaisesRegex(ValueError, "Interrupted"):
            deploy.verify_root(self.root)
        deploy.recover(self.root)
        self.assertEqual(deploy.verify_root(self.root)["release"], "candidate-one")

    def test_candidate_scope_and_lock(self):
        package = self.package("one")
        self.settings["review"] = False
        self.config.write_text(json.dumps(self.settings))
        with self.assertRaisesRegex(ValueError, "review=true"):
            deploy.deploy(package, self.root, self.config)
        with command_lock(self.root):
            with self.assertRaisesRegex(ValueError, "busy"):
                deploy.deploy(package, self.root, self.config)
        with self.assertRaisesRegex(ValueError, "case-colliding"):
            deploy.managed({"work.cmd": "a" * 64, "WORK.CMD": "b" * 64})
        with self.assertRaisesRegex(ValueError, "user/runtime"):
            deploy.managed({"works/a": "a" * 64})

    def test_installer_runs_with_isolated_python_imports(self):
        package = self.package("isolated")
        result = subprocess.run([sys.executable, "-I", "-S", "-B", deploy.__file__, "deploy",
                                 "--package", str(package), "--root", str(self.root),
                                 "--config", str(self.config)], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["release"], "candidate-isolated")

    def test_config_edits_block_rollback_and_protected_root_is_rejected(self):
        package = self.package("one")
        self.settings["review_protected_roots"] = [str(self.root)]
        self.config.write_text(json.dumps(self.settings))
        with self.assertRaisesRegex(ValueError, "overlaps"):
            deploy.deploy(package, self.root, self.config)
        self.settings["review_protected_roots"] = [str(self.base / "production")]
        self.config.write_text(json.dumps(self.settings))
        deploy.deploy(package, self.root, self.config)
        deploy.deploy(self.package("two"), self.root, None)
        (self.root / deploy.CONFIG).write_text("{}")
        with self.assertRaisesRegex(ValueError, "configuration edit"):
            deploy.recover(self.root, rollback=True)
        self.assertEqual((self.root / "work.cmd").read_text(), "two")
        self.assertFalse((self.root / deploy.PENDING).exists())


if __name__ == "__main__":
    unittest.main()
