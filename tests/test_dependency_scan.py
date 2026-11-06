"""Public dependency closure regressions; all sources are disposable fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".studio"))
from visual_plan import VisualPlanError, validate_dependencies


class DependencyScanTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def scan(self, source):
        self.write("entry.js", source)
        return validate_dependencies(self.root, entry="entry.js")

    @unittest.skipUnless(sys.platform == "linux", "WSL staging parser precedence")
    def test_pinned_parser_overrides_staged_windows_runtime(self):
        source = Path(__file__).resolve().parents[1] / ".studio/dependency_scan.cjs"
        script = self.root / ".studio/dependency_scan.cjs"
        script.parent.mkdir()
        shutil.copy2(source, script)
        self.write("runtime/npm/package.json", '{"name":"windows-runtime"}')
        parser = os.environ.get("HYPERFRAMES_DEPENDENCY_MODULE_ROOT") or str(source.parent / ".runtime/dependency-parser")
        env = {**os.environ, "HYPERFRAMES_DEPENDENCY_MODULE_ROOT": parser}
        result = subprocess.run(["node", str(script)], input=json.dumps([{"kind": "js", "mode": "module",
                                                                    "text": "const value = 1"}]),
                                capture_output=True, text=True, env=env)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_diagnostics_comments_regex_and_template_text_are_not_imports(self):
        source = r'''
const diagnostic = "Use import {Composition} from 'remotion' instead";
const expression = /import\s+from 'missing-regex.js'/;
const example = `import 'missing-template.js'`;
// import 'missing-comment.js';
/* fetch('missing-block.js') */
function from(value) { return value; }
from('ordinary-argument');
'''
        self.assertEqual(["entry.js"], self.scan(source))

    def test_literal_references_include_escapes_and_template_expressions(self):
        for name in ("static.js", "reexport.js", "dynamic.js", "data.json", "nested.json"):
            self.write(name, "{}" if name.endswith(".json") else "export const x = 1;")
        source = r'''
import {x} from './static.js';
export {x as other} from './reexport.js';
import('./dyn\u0061mic.js');
fetch('./data.json');
const message = `value ${fetch('./nested.json')}`;
'''
        self.assertEqual(sorted(["entry.js", "static.js", "reexport.js", "dynamic.js", "data.json", "nested.json"]),
                         self.scan(source))

    def test_minified_bundle_and_regex_division_ambiguity(self):
        self.write("data.json", "{}")
        self.assertEqual(["data.json", "entry.js"], self.scan(
            '(()=>{if(true)/import "missing.js"/.test("x");'
            'const n=12/3/2;return `n=${n},data=${fetch("./data.json")}`})()'))

    def test_html_routes_inline_languages_without_scanning_prose(self):
        self.write("index.html", '''
<p>import 'missing-prose.js'; url(missing-prose.png)</p>
<!-- <script src="missing-comment.js"></script> -->
<script type="application/json">{"sample": "import 'missing-json.js'"}</script>
<script>fetch('./data.json'); const x = "url(missing-script.png)";</script>
<style>p { content: "import 'missing-style.js'"; background: url('./image.png'); }</style>
<div style="background: url('./inline.png')"></div>
''')
        for name in ("data.json", "image.png", "inline.png"):
            self.write(name, "{}")
        self.assertEqual(["data.json", "image.png", "index.html", "inline.png"],
                         validate_dependencies(self.root))

    def test_composition_sources_are_executable_snapshot_dependencies(self):
        self.write("index.html", '<div data-composition-src="vendor/scene.html"></div>')
        self.write("vendor/scene.html", '<script src="scene.js"></script>')
        self.write("vendor/scene.js", 'const scene = true;')
        self.assertEqual(["index.html", "vendor/scene.html", "vendor/scene.js"],
                         validate_dependencies(self.root))
        with self.assertRaisesRegex(VisualPlanError, "semantic placeholders"):
            validate_dependencies(self.root, layout=True)
        for source in ("missing.html", "../escape.html", "https://example.invalid/scene.html",
                       "data:text/html,scene", "blob:scene"):
            with self.subTest(source=source), self.assertRaises(VisualPlanError):
                self.write("index.html", f'<div data-composition-src="{source}"></div>')
                validate_dependencies(self.root)

    def test_css_imports_are_checked_outside_layout_and_ignore_content(self):
        self.write("style.css", '''@import "./base.css";
/* url(missing-comment.png) */
p { content: "url(missing-string.png)"; background: url('./image.png'); }
''')
        self.write("base.css", "p {color: red}")
        self.write("image.png", "image")
        self.assertEqual(["base.css", "image.png", "style.css"],
                         validate_dependencies(self.root, entry="style.css"))

    def test_missing_remote_and_escape_still_fail(self):
        for source in ("import './missing.js';", "export * from './missing.js';",
                       "fetch('https://example.invalid/data');", "import('../escape.js');",
                       r"fetch('\u0068ttps://example.invalid/data');"):
            with self.subTest(source=source), self.assertRaises(VisualPlanError):
                self.scan(source)

    def test_declared_snapshot_dependencies_remain_checked(self):
        from storage import snapshot_files
        self.write("index.html", "<p>fixture</p>")
        self.write("DESIGN.md", "fixture")
        self.write("project-config.json", json.dumps({"snapshot_dependencies": ["missing.json"]}))
        with self.assertRaises(VisualPlanError):
            snapshot_files(self.root)

    def test_snapshot_accepts_aliased_parent_but_rejects_linked_dependency(self):
        from storage import snapshot_files, StorageError
        self.write('project/index.html', '<p>fixture</p>')
        self.write('project/DESIGN.md', 'fixture')
        self.write('project/project-config.json', json.dumps({'snapshot_dependencies': ['data.json']}))
        self.write('project/data.json', '{}')
        alias = self.root / 'alias'
        alias.symlink_to(self.root / 'project', target_is_directory=True)
        self.assertIn('data.json', snapshot_files(alias))
        (self.root / 'project/data.json').unlink()
        self.write('outside.json', '{}')
        (self.root / 'project/data.json').symlink_to(self.root / 'outside.json')
        with self.assertRaises(StorageError):
            snapshot_files(alias)

    def test_dynamic_loading_requires_and_traverses_declarations(self):
        with self.assertRaisesRegex(VisualPlanError, 'requires explicit'):
            self.scan('fetch(name); import(`./${name}.js`);')
        self.write('project-config.json', json.dumps({'snapshot_dependencies': ['data.json']}))
        with self.assertRaisesRegex(VisualPlanError, 'missing'):
            self.scan('fetch(name);')
        self.write('data.json', '{}')
        self.assertEqual(['data.json', 'entry.js', 'project-config.json'], self.scan('fetch(name);'))
        self.write('project-config.json', json.dumps({'snapshot_dependencies': ['https://example.invalid/x']}))
        with self.assertRaisesRegex(VisualPlanError, 'Non-local'):
            self.scan('fetch(name);')

    def test_asset_dynamic_declaration_and_global_fetch(self):
        self.write('asset.json', json.dumps({'dependencies': []}))
        self.assertEqual(['asset.json', 'entry.js'], self.scan('globalThis.fetch(name);'))
        for expression in ('window.fetch', 'globalThis["fetch"]', 'self.fetch'):
            with self.subTest(expression=expression), self.assertRaisesRegex(VisualPlanError, 'Non-local'):
                self.scan(expression + '("https://example.invalid/x");')

    def test_invalid_syntax_and_unavailable_parser_fail_closed(self):
        with self.assertRaisesRegex(VisualPlanError, 'syntax parsing failed'):
            self.scan('const broken = ;')
        with patch.dict(os.environ, {'HYPERFRAMES_NODE': str(self.root / 'missing-node')}):
            with self.assertRaisesRegex(VisualPlanError, 'parser unavailable'):
                self.scan('const value = 1;')

    def test_css_escapes_remote_and_nested_imports(self):
        for source in ('@import "https://example.invalid/style.css";',
                       'p {background: url(https://example.invalid/a.png)}',
                       r'p {background: url(\68 ttps://example.invalid/a.png)}'):
            self.write('style.css', source)
            with self.subTest(source=source), self.assertRaisesRegex(VisualPlanError, 'Non-local'):
                validate_dependencies(self.root, entry='style.css')

    def test_html_handlers_and_classic_script_grammar(self):
        self.write('index.html', '<button onclick="return fetch(\'./data.json\')">Read</button>'
                   '<script>with ({x: 1}) { console.log(x) }</script>')
        self.write('data.json', '{}')
        self.assertEqual(['data.json', 'index.html'], validate_dependencies(self.root))

    def test_fetch_uses_document_base_through_script_imports(self):
        self.write('index.html', '<script type="module" src="scripts/main.js"></script>')
        self.write('scripts/main.js', 'import "./child.js";')
        self.write('scripts/child.js', 'fetch("./data.json")')
        self.write('data.json', '{}')
        self.assertEqual(['data.json', 'index.html', 'scripts/child.js', 'scripts/main.js'],
                         validate_dependencies(self.root))
        (self.root / 'data.json').unlink()
        self.write('scripts/data.json', '{}')
        with self.assertRaisesRegex(VisualPlanError, 'missing'):
            validate_dependencies(self.root)

    def test_declarations_are_paths_not_urls_and_base_href_is_rejected(self):
        self.write('project-config.json', json.dumps({'snapshot_dependencies': ['font#1%20.otf']}))
        self.write('font#1%20.otf', 'font fixture')
        self.assertEqual(['entry.js', 'font#1%20.otf', 'project-config.json'], self.scan('fetch(name)'))
        self.write('index.html', '<base href="https://example.invalid/"><script src="entry.js"></script>')
        with self.assertRaisesRegex(VisualPlanError, 'base href'):
            validate_dependencies(self.root)

    def test_dev_parser_derives_exact_integrities_without_new_pins(self):
        import prepare_windows_runtime as prepare
        lock_path = Path(__file__).resolve().parents[1] / 'windows-npm.lock.json'
        original = prepare.read(lock_path)
        with patch.object(prepare.subprocess, 'run') as run:
            prepare.dev_parser(lock_path, self.root / 'cache', self.root / 'parser', offline=True)
        derived = prepare.read(self.root / 'parser/package-lock.json')
        for name, package in derived['packages'].items():
            if name:
                self.assertEqual(original['packages'][name], package)
        self.assertEqual({'acorn', 'esbuild'}, set(derived['packages']['']['dependencies']))
        self.assertIn('--offline', run.call_args_list[0].args[0])
        self.assertIn('transformSync', run.call_args_list[1].args[0][2])

    def test_opaque_executable_urls_and_import_maps_are_rejected(self):
        for source in ('import("data:text/javascript,import \'https://example.invalid/x\'")',
                       'import("blob:https://example.invalid/id")'):
            with self.subTest(source=source), self.assertRaisesRegex(VisualPlanError, 'Opaque executable'):
                self.scan(source)
        for source in ('<script src="data:text/javascript,alert(1)"></script>',
                       '<link rel="stylesheet preload" as="style" href="data:text/css,@import url(https://example.invalid/x)">',
                       '<link rel="preload" as="SCRIPT" href="data:text/javascript,alert(1)">',
                       '<script type="importmap">{"imports":{"./local.js":"https://example.invalid/x"}}</script>'):
            self.write('index.html', source)
            with self.subTest(source=source), self.assertRaises(VisualPlanError):
                validate_dependencies(self.root)
        self.write('index.html', '<img src="data:image/png;base64,AA==">')
        self.assertEqual(['index.html'], validate_dependencies(self.root))


if __name__ == "__main__":
    unittest.main()
