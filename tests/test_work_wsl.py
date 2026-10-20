from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import test_work_cli
import work_wsl


class WorkWslTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "production root"
        self.root.mkdir()
        self.convert = mock.patch.object(work_wsl.subprocess, "check_output", side_effect=self.wslpath)
        self.convert.start()
        self.addCleanup(self.convert.stop)

    def wslpath(self, args, **kwargs):
        self.assertEqual(args[0], "wslpath")
        self.assertTrue(kwargs["text"])
        if args[1] == "-u":
            return str(self.root / "notes / source.json") if args[2].startswith("D:") else str(self.base / "outside.json")
        self.assertEqual(args[1], "-w")
        return "D:\\production root\\" + Path(args[2]).relative_to(self.root).as_posix().replace("/", "\\")

    def test_paths_and_unicode_arguments_preserved(self):
        command = work_wsl.command(self.root, ["new", "中文 title", "A/B test", "--appearance-file", "notes / source.json"])
        self.assertEqual(command[:4], ["cmd.exe", "/d", "/s", "/c"])
        self.assertEqual(command[4:6], ['call', 'D:\\production root\\work.cmd'])
        self.assertIn('中文 title', command)
        self.assertIn('A/B test', command)
        self.assertIn('D:\\production root\\notes \\ source.json', command)
        equals = work_wsl.command(self.root, ["--appearance-file=D:\\production root\\notes \\ source.json"])
        self.assertIn('--appearance-file=D:\\production root\\notes \\ source.json', equals)

    def test_production_commands_and_card_identity_forwarded(self):
        for args in (['doctor'], ['status', '--json'],
                     ['preview', 'open', 'current', '--no-open', '--json'],
                     ['finalize', '--work', 'fixture', '--variant', 'main', '--json'],
                     ['design', 'new', 'example', '--from', 'stage-full']):
            with self.subTest(args=args):
                self.assertEqual(work_wsl.command(self.root, args)[6:], args)

    def test_external_traversal_symlink_and_metacharacters_rejected(self):
        (self.root / "escape").symlink_to(self.base, target_is_directory=True)
        for value in (str(self.base / "outside.json"), "../outside.json", "escape/outside.json", "C:\\outside.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                work_wsl.command(self.root, ["--appearance-file", value])
        for value in ('a&whoami', 'a|b', '%PATH%', 'a^b', '!PATH!', 'a"b', 'a>b', 'a<b', "a\nb", "a\rb", "a\x00b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                work_wsl.command(self.root, ["new", value])
        for arguments in (["--to=C:\\outside"], ["--mapping=../outside.json"], ["--align=C:\\outside"],
                          ["--appearance-file", "..\\outside.json"], ["C:relative"], ["root", "set", "../outside"],
                          ["component", "install", "asset@v1", "--binding-file", "escape/binding.json"],
                          ["--binding-file=C:\\outside.json"], ["component", "pack", "--json", "escape/source"]):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                work_wsl.command(self.root, arguments)

    def test_run_inherits_streams_and_propagates_status(self):
        with mock.patch.object(work_wsl, "__file__", str(self.root / ".studio/work_wsl.py")), \
                mock.patch.object(work_wsl.shutil, 'which', return_value='cmd.exe'), \
                mock.patch.object(work_wsl.subprocess, "run", return_value=subprocess.CompletedProcess([], 17)) as run:
            self.assertEqual(work_wsl.main(["status"]), 17)
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)
        self.assertEqual(run.call_args.kwargs["env"]["HYPERFRAMES_INVOCATION"], "wsl-forwarded")
        self.assertIn("HYPERFRAMES_INVOCATION", run.call_args.kwargs["env"]["WSLENV"].split(":"))
        self.assertEqual(run.call_args.args[0][:4], ["cmd.exe", "/d", "/s", "/c"])
        with mock.patch.object(work_wsl, "__file__", str(self.root / ".studio/work_wsl.py")), \
                mock.patch.object(work_wsl.subprocess, "run") as run, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(work_wsl.main(["new", "bad&input"]), 2)
            run.assert_not_called()
            self.assertIn("metacharacter", error.getvalue())

    def test_missing_windows_path_uses_cmd_without_changing_environment(self):
        with mock.patch.object(work_wsl, '__file__', str(self.root / '.studio/work_wsl.py')), \
                mock.patch.object(work_wsl.shutil, 'which', return_value=None), \
                mock.patch.object(work_wsl.subprocess, 'check_output', return_value='/custom/c/Windows/System32/cmd.exe') as convert, \
                mock.patch.object(Path, 'is_file', return_value=True), \
                mock.patch.object(work_wsl.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(work_wsl.main(['preview', 'diagnose', '--help']), 0)
        self.assertEqual('/custom/c/Windows/System32/cmd.exe', run.call_args.args[0][0])
        convert.assert_any_call(['wslpath', '-u', r'C:\Windows\System32\cmd.exe'], text=True)
        self.assertEqual(self.root, run.call_args.kwargs['cwd'])
        self.assertEqual(os.environ.get('PATH'), run.call_args.kwargs['env'].get('PATH'))


if __name__ == "__main__":
    unittest.main()
