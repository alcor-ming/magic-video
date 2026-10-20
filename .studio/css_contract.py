"""Static class-contract hints; findings are not visual acceptance."""
from pathlib import Path
import re

from work_requests import safe


_SKIPPED = {"vendor", "runtime", ".runtime", "library", "libraries", "lib", "node_modules"}
_SELECTOR = re.compile(r"\.([a-zA-Z_][\w-]*)", re.ASCII)
_USED = (
    re.compile(r'''\bclassName\s*(?:=|:)\s*(["'])(.*?)\1''', re.DOTALL),
    re.compile(r'''\b(?:el|make|create\w*|node)\s*\(\s*["'][a-zA-Z-]+["']\s*,\s*(["'])([^"']+)\1''', re.ASCII),
)
_CLASS_ADD = re.compile(r'''\bclassList\s*\.\s*add\s*\(((?:[^()"']|"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')*)\)''')
_ARGUMENT = re.compile(r'''(?:^|,)\s*(["'])(.*?)\1''', re.DOTALL)
_LITERAL = re.compile(r'''(["'`])(?:\\.|(?!\1)[^\\])*\1''', re.DOTALL)
_RULE = re.compile(r'''(?:^|(?<=[{}"'`]))\s*\.([a-zA-Z_][\w-]*)\s*\{([^{}]*)\}''', re.ASCII)
_HIDDEN = re.compile(r"(?:^|;)\s*visibility\s*:\s*hidden\s*(?:!important\s*)?(?:;|$)", re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b[^>]*>[\s\S]*?</script\s*>", re.IGNORECASE)
_STATIC = re.compile(r'''\bclass\s*=\s*(["'])(.*?)\1''', re.DOTALL)
_STYLE = re.compile(r"<style\b[^>]*>([\s\S]*?)</style\s*>", re.IGNORECASE)


def _used_classes(text):
    classes = set()
    for pattern in _USED:
        for match in pattern.finditer(text):
            classes.update(match[2].split())
    for call in _CLASS_ADD.finditer(text):
        for match in _ARGUMENT.finditer(call[1]):
            classes.update(match[2].split())
    return classes


def findings(project: Path, dependencies) -> list[dict]:
    """Find JS-created classes without contracts in dependency HTML/JS/MJS/CSS.

    Skip vendor/runtime/library/lib/node_modules consumers. Dependency files
    runtime/stage-rig.js and runtime/stage-kit*.js contribute definitions only.
    Return location-bearing hints, including css_scan_unverified on read errors.
    """
    units, result, defined = [], [], set()
    for name in sorted(set(map(str, dependencies))):
        path = Path(name)
        suffix = path.suffix.lower()
        if suffix not in {".html", ".js", ".mjs", ".css"}:
            continue
        runtime_definition = path.parent == Path("runtime") and (
            path.name == "stage-rig.js" or path.match("stage-kit*.js"))
        if not runtime_definition and any(part in _SKIPPED for part in path.parts[:-1]):
            continue
        try:
            text = safe(project, name).read_text(encoding="utf-8-sig", errors="ignore")
        except (ValueError, OSError) as error:
            result.append({"kind": "css_scan_unverified", "file": name, "detail": str(error)})
            continue
        if suffix == ".css" or runtime_definition:
            defined.update(_SELECTOR.findall(text))
            css = re.sub(r"/\*[\s\S]*?\*/", "", text)
            hidden = {match[1] for match in _RULE.finditer(css) if _HIDDEN.search(match[2])}
            result.extend({"kind": "hidden_container_hint", "file": name, "class": cls}
                          for cls in sorted(hidden))
        elif suffix in {".js", ".mjs"}:
            for literal in _LITERAL.finditer(text):
                defined.update(_SELECTOR.findall(literal[0]))
        elif suffix == ".html":
            # Inline <style> rules and <script> selector literals are contracts as well.
            for block in _STYLE.finditer(text):
                defined.update(_SELECTOR.findall(block[1]))
                css = re.sub(r"/\*[\s\S]*?\*/", "", block[1])
                result.extend({"kind": "hidden_container_hint", "file": name, "class": match[1]}
                              for match in _RULE.finditer(css) if _HIDDEN.search(match[2]))
            for block in _SCRIPT.finditer(text):
                for literal in _LITERAL.finditer(block[0]):
                    defined.update(_SELECTOR.findall(literal[0]))
        if not runtime_definition and suffix != ".css":
            units.append((name, suffix, text))
    for name, suffix, text in units:
        uncovered = sorted(_used_classes(text) - defined)
        if uncovered:
            result.append({"kind": "css_class_uncovered", "file": name, "classes": uncovered})
        if suffix == ".html":
            markup = _SCRIPT.sub("", text)
            static = {cls for match in _STATIC.finditer(markup) for cls in match[2].split()}
            uncovered_static = sorted(static - defined)
            if uncovered_static:
                result.append({"kind": "css_class_static_uncovered", "file": name,
                               "classes": uncovered_static})
    return result
