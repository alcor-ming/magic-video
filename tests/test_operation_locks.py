import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import shutil
import threading
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import windows_runtime
from test_work_cli import WORK_CLI as cli


class OperationLocksTest(unittest.TestCase):
    def test_shared_commands_exclude_update_and_release_after_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with windows_runtime.command_lock(root, shared=True):
                with windows_runtime.command_lock(root, shared=True):
                    with self.assertRaisesRegex(ValueError, 'busy'):
                        with windows_runtime.command_lock(root):
                            self.fail('update overlapped command')
            with self.assertRaises(RuntimeError):
                with windows_runtime.command_lock(root):
                    raise RuntimeError('interrupted')
            with windows_runtime.command_lock(root):
                pass

    def test_new_work_and_versioned_catalog_put_do_not_wait_for_other_render(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(Path(cli.__file__).parent / 'templates', root / '.studio/templates')
            cli.account_service(root).put('series', 'first', {'name': 'First', 'design': 'stage-full'})
            def invoke(*args):
                with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(0, cli.main(list(args), root=root), error.getvalue())
                return out.getvalue().strip()
            first = invoke('new', 'First', '--workflow', 'hyperframes_video', '--purpose', 'standard',
                           '--series', 'first', '--design', 'stage-full', '--no-account', '--detached')
            work, _ = cli.locate_work(root, first)
            state = work / 'variants/variant1/variant.yaml'
            before = state.read_bytes()
            args = argparse.Namespace(command='finalize', work_override=first, variant_override='variant1')
            with windows_runtime.command_lock(root, shared=True), cli.operation_lock(root, args):
                definition = root / 'series.json'
                definition.write_text(json.dumps({'name': 'Second', 'design': 'stage-full'}))
                invoke('series', 'put', 'second', '--file', str(definition))
                second = invoke('new', 'Second', '--workflow', 'hyperframes_video', '--purpose', 'standard',
                                '--series', 'second', '--design', 'stage-full', '--no-account', '--detached')
                self.assertNotEqual(first, second)
                with self.assertRaisesRegex(ValueError, 'busy'):
                    with cli.operation_lock(root, argparse.Namespace(command='migrate')):
                        self.fail('migration overlapped an active render')
                with self.assertRaisesRegex(ValueError, 'busy'):
                    with windows_runtime.command_lock(root):
                        self.fail('tool update overlapped an active render')
            self.assertEqual(before, state.read_bytes())

    def test_new_work_does_not_mix_series_versions_during_catalog_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(Path(cli.__file__).parent / 'templates', root / '.studio/templates')
            service = cli.account_service(root)
            service.put('series', 'series', {'name': 'Old', 'design': 'stage-full',
                'workflow': {'human_confirmation': {'script': True}}})
            update = root / 'series.json'
            update.write_text(json.dumps({'name': 'New', 'design': 'stage-light',
                'workflow': {'human_confirmation': {'script': False}}}))
            read, release, written = threading.Event(), threading.Event(), threading.Event()
            original = cli.control_plane.AccountService.get
            results = []
            def paused_get(instance, kind, identity):
                value = original(instance, kind, identity)
                if threading.current_thread().name == 'creator' and kind == 'series' and not read.is_set():
                    read.set()
                    if not release.wait(5):
                        raise RuntimeError('test coordination timed out')
                return value
            def execute(arguments, done=None):
                try:
                    results.append(cli.main(arguments, root=root))
                finally:
                    if done is not None:
                        done.set()
            creator = threading.Thread(name='creator', target=execute, args=([
                'new', 'One', '--workflow', 'hyperframes_video', '--purpose', 'standard',
                '--series', 'series', '--no-account', '--detached'],))
            writer = threading.Thread(target=execute, args=([
                'series', 'put', 'series', '--file', str(update)], written))
            with patch.object(cli.control_plane.AccountService, 'get', paused_get), redirect_stdout(io.StringIO()):
                creator.start()
                try:
                    self.assertTrue(read.wait(3))
                    writer.start()
                    written.wait(.2)
                finally:
                    release.set()
                    creator.join(5)
                    if writer.ident is not None:
                        writer.join(5)
            self.assertFalse(creator.is_alive() or writer.is_alive())
            self.assertEqual([0, 0], sorted(results))
            work = cli.work_paths(root)[0][0]
            work_meta = cli.read_frontmatter(work / 'WORK.md')
            state = cli.read_json(work / 'variants/variant1/variant.yaml')
            self.assertTrue(work_meta['series_workflow']['human_confirmation']['script'])
            self.assertEqual('stage-full', state['design'])
            self.assertEqual(1, state['series_binding']['revision'])
            self.assertEqual(2, service.get('series', 'series')['revision'])

    def test_distinct_variants_parallel_same_variant_and_work_write_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for work in ('work-hyperframes_video-001-a', 'work-hyperframes_video-002-b'):
                base = root / 'works/one' / work
                base.mkdir(parents=True)
                (base / 'WORK.md').write_text('---\n{"id":"'+work+'","workflow":"hyperframes_video"}\n---\n')
                for variant in ('variant1','variant2'):
                    path = base / 'variants' / variant
                    path.mkdir(parents=True)
                    (path / 'variant.yaml').write_text('{"mode":"english"}')
            def args(work, variant):
                return argparse.Namespace(command='finalize', work_override=work, variant_override=variant)
            one,two = sorted((root / 'works/one').iterdir())
            with cli.operation_lock(root,args(one.name,'variant1')):
                with cli.operation_lock(root,args(one.name,'variant2')):
                    with cli.operation_lock(root,args(two.name,'variant1')):
                        with self.assertRaisesRegex(ValueError,'busy'):
                            with cli.operation_lock(root,args(one.name,'variant1')):
                                self.fail('same variant wrote concurrently')
                        work_args=args(one.name,'variant1');work_args.command='archive'
                        with self.assertRaisesRegex(ValueError,'busy'):
                            with cli.operation_lock(root,work_args):
                                self.fail('archive raced with rendering')


if __name__ == '__main__': unittest.main()
