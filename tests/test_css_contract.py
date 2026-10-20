"""Dependency-scoped CSS contract diagnostics in isolated projects."""
from pathlib import Path
import tempfile
import unittest

from css_contract import findings


class CSSContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)

    def scan(self, files, dependencies=None):
        for name, text in files.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return findings(self.project, list(files) if dependencies is None else dependencies)

    def test_uncovered_factory_class(self):
        self.assertEqual(self.scan({"a.js": 'el("div","gate-panel",root)', "style.css": ""}), [
            {"kind": "css_class_uncovered", "file": "a.js", "classes": ["gate-panel"]}])

    def test_css_definition(self):
        self.assertEqual(self.scan({"a.js": 'el("div","gate-panel",root)',
                                    "style.css": ".gate-panel{}"}), [])

    def test_js_selector_definition(self):
        self.assertEqual(self.scan({"a.js": "el('div','fig-arm',root); querySelector('.fig-arm')"}), [])

    def test_hidden_container(self):
        self.assertEqual(self.scan({"style.css": ".scene{visibility:hidden}"}), [
            {"kind": "hidden_container_hint", "file": "style.css", "class": "scene"}])

    def test_creation_forms_and_sorted_deduplication(self):
        text = '''obj.className = "z a"; const o = {className: 'b'};
                  obj.classList.add("c", 'd', variable);
                  K.el('div','e',root); kit.make('span','f',root);
                  createThing('div','g',root); node('p','h',root);
                  el('div','a',root);'''
        self.assertEqual(self.scan({"a.mjs": text}), [
            {"kind": "css_class_uncovered", "file": "a.mjs",
             "classes": ["a", "b", "c", "d", "e", "f", "g", "h", "z"]}])

    def test_static_html_is_only_a_hint_and_scripts_are_not_markup(self):
        text = '''<div class="static covered"></div><script>
                  el('div','dynamic',root); const html = '<b class="script-markup">';
                  </script>'''
        self.assertEqual(self.scan({"index.html": text, "style.css": ".covered{}"}), [
            {"kind": "css_class_uncovered", "file": "index.html", "classes": ["dynamic"]},
            {"kind": "css_class_static_uncovered", "file": "index.html", "classes": ["static"]}])

    def test_runtime_dependencies_define_but_do_not_consume(self):
        self.assertEqual(self.scan({
            "a.js": 'el("div", "rig kit", root)',
            "runtime/stage-rig.js": "const css = '.rig{visibility:hidden}'; el('div','ignored',root)",
            "runtime/stage-kit-extra.js": "const css = `.kit{}`; node('div','also-ignored',root)",
        }), [{"kind": "hidden_container_hint", "file": "runtime/stage-rig.js", "class": "rig"}])

    def test_dependency_scope_and_skipped_directories(self):
        files = {"a.js": 'el("div", "missing", root)', "unlisted.css": ".missing{}",
                 "runtime/stage-rig.js": "'.missing{}'"}
        ignored = [f"{directory}/nested/ignored.js" for directory in
                   ("vendor", "runtime", ".runtime", "library", "libraries", "lib", "node_modules")]
        files.update({name: "el('div','ignored',root); querySelector('.missing')" for name in ignored})
        self.assertEqual(self.scan(files, ["a.js", "ignore.txt", *ignored]), [
            {"kind": "css_class_uncovered", "file": "a.js", "classes": ["missing"]}])

    def test_hidden_rules_ignore_comments_and_compound_selectors(self):
        self.assertEqual(self.scan({"style.css": '''/* .comment{visibility:hidden} */
            .parent .child{visibility:hidden}.compound.other{visibility:hidden}
            .visible{visibility:visible}.scene{color:red; VISIBILITY: hidden !important;}
            .scene{visibility:hidden}'''}), [
            {"kind": "hidden_container_hint", "file": "style.css", "class": "scene"}])

    def test_all_js_literal_selectors_define_classes(self):
        self.assertEqual(self.scan({"a.js": "el('div','one two three',root)",
                                    "b.mjs": '''closest('.one'); gsap.to(".two"); const s = `.three`;'''}), [])

    def test_read_failure_is_unverified_and_other_files_are_scanned(self):
        result = self.scan({"a.js": 'el("div", "missing", root)'}, ["missing.css", "a.js"])
        self.assertEqual(result[0]["kind"], "css_scan_unverified")
        self.assertEqual(result[0]["file"], "missing.css")
        self.assertTrue(result[0]["detail"])
        self.assertEqual(result[1], {"kind": "css_class_uncovered", "file": "a.js", "classes": ["missing"]})

    def test_bom_and_invalid_utf8_are_tolerated(self):
        (self.project / "a.js").write_bytes(b'\xef\xbb\xbfel("div", "covered", root);\xff')
        (self.project / "style.css").write_bytes(b'\xef\xbb\xbf.covered{}\xff')
        self.assertEqual(findings(self.project, ["a.js", "style.css"]), [])


if __name__ == "__main__":
    unittest.main()


class InlineHtmlTest(unittest.TestCase):
    def test_inline_style_and_script_are_contracts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.html').write_text('<style>.gate-panel{position:absolute}.scene{visibility:hidden}</style>'
                                             '<script>el("div","gate-panel",root); document.querySelector(".fig-arm"); el("div","fig-arm",root)</script>',
                                             encoding='utf-8')
            result = findings(root, ["index.html"])
            self.assertEqual([], [item for item in result if item['kind'] == 'css_class_uncovered'])
            self.assertIn({'kind': 'hidden_container_hint', 'file': 'index.html', 'class': 'scene'}, result)
