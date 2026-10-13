"""Studio launcher regressions found in production reopen failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_work_cli import WORK_CLI

studio_preview = WORK_CLI.studio_preview


class StudioPreviewTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "variant" / "project"
        self.project.mkdir(parents=True)
        self.preferences = self.project.parent / ".runtime" / "studio-browser" / "Default" / "Preferences"

    def test_profile_restores_do_not_track_after_chrome_rewrites_preferences(self):
        self.preferences.parent.mkdir(parents=True)
        self.preferences.write_text(json.dumps({"enable_do_not_track": None, "profile": {"name": "kept"}}), encoding="utf-8")
        studio_preview.private_browser_profile(self.project)
        data = json.loads(self.preferences.read_text(encoding="utf-8"))
        self.assertIs(True, data["enable_do_not_track"])
        self.assertEqual({"name": "kept"}, data["profile"])

    def test_profile_replaces_unreadable_preferences(self):
        self.preferences.parent.mkdir(parents=True)
        self.preferences.write_text("{truncated", encoding="utf-8")
        studio_preview.private_browser_profile(self.project)
        self.assertEqual({"enable_do_not_track": True}, json.loads(self.preferences.read_text(encoding="utf-8")))

    def test_unrequested_port_lets_official_cli_reuse_running_project_server(self):
        calls = []

        def run_cli(cli, project, arguments, *, json_output=True):
            calls.append(arguments)
            if arguments == ["--help"]:
                return "--background --json --context --context-fields --context-detail --stop"
            return {"ok": True, "result": {"projectDir": str(project), "port": 3005, "projectName": "project",
                                           "studioUrl": "http://127.0.0.1:3005/#project/project", "state": "reused"}}

        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        with mock.patch.object(studio_preview, "run_cli", side_effect=run_cli), \
                mock.patch.object(studio_preview, "context") as context, \
                mock.patch.object(studio_preview, "build_opener") as opener:
            opener.return_value.open.return_value = response
            session = studio_preview.start(Path("cli.js"), self.project, 0, no_open=True)
        self.assertNotIn("--port", calls[1])
        self.assertEqual(3005, session["port"])
        context.assert_called_once_with(Path("cli.js"), self.project, 3005, "server")


if __name__ == "__main__":
    unittest.main()
