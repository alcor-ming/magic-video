#!/usr/bin/env python3
"""Validate the thin Skill and repository Harness; profiles are legacy data."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
REQUIRED_PACKAGE = [
    "README.md",
    "SKILL.md",
    "CHANGELOG.md",
    "VERSION",
]
REQUIRED_HARNESS = [
    "AGENTS.md",
    "docs/PRD/production-session-interface.md",
    "work",
    "work-wsl.sh",
    ".studio/work_wsl.py",
    ".studio/math_chain.py",
    ".studio/math_kit.py",
    ".studio/math_build.py",
    ".studio/math_kit_assets.py",
    ".studio/math_kit_check.mjs",
    ".studio/runtime/math-kit.js",
    ".studio/runtime/math-kit.css",
    ".studio/runtime/math-project.js",
    ".studio/spec/math-kit.md",
    ".studio/math_audio.py",
    ".studio/review_bundle.py",
    ".studio/seek_check.py",
    ".studio/seek_check.cjs",
    ".studio/spec/showcase.md",
    ".studio/spec/showcase-science.md",
    ".studio/spec/math-rap.md",
    ".studio/templates/CLAUDE.template.md",
    ".studio/templates/SHOWCASE_PLAN.template.md",
    ".studio/templates/VISUAL_RETRO.template.md",
    ".studio/templates/MATH_RESEARCH.template.md",
    ".studio/spec/visual-design.md",
    ".studio/work.py",
    ".studio/lines.py",
    ".studio/lines.yaml",
    ".studio/settings.py",
    ".studio/settings.yaml",
    ".studio/mechanisms.yaml",
    ".studio/director_plan.py",
    ".studio/critic.py",
    ".studio/visual_memory.py",
    ".studio/work_memory.py",
    ".studio/behavior-changes.yaml",
    ".studio/explainer.py",
    ".studio/sfx_import.py",
    ".studio/workflow.md",
    ".studio/capabilities.yaml",
    ".studio/spec/creative.md",
    ".studio/spec/hyperframes.md",
    ".studio/spec/hyperframes-final.md",
    ".studio/spec/hyperframes-assets.md",
    ".studio/spec/broll-assets.md",
    ".studio/templates/BROLL_BRIEF.template.md",
    ".studio/spec/hyperframes-research.md",
    ".studio/spec/runtime-interfaces.md",
    ".studio/icon_sets.py",
    ".studio/spec/privacy.md",
    ".studio/recipes/talking-head.md",
    ".studio/recipes/pure-hyperframes.md",
    ".studio/templates/RESEARCH.template.md",
    ".studio/templates/ANIMATION_PLAN.template.md",
    ".studio/templates/WINDOWS_AGENTS.md",
    ".studio/runtime/appearance.js",
    ".studio/runtime/broll.js",
    ".studio/runtime/scene-binding.js",
    ".studio/runtime/cues.js",
    ".studio/runtime/captions.js",
    ".studio/runtime/figures.js",
    ".studio/runtime/rolls.js",
    ".studio/showcase_tools.py",
    ".studio/stage_art.py",
    ".studio/cast_art.py",
    ".studio/tts.py",
    ".studio/work_tts.py",
    ".studio/english_plan.py",
    ".studio/spec/english.md",
    ".studio/templates/MATH_PLAN.template.md",
    ".studio/templates/ENGLISH_PLAN.template.md",
]


def rule_link_errors(repo: Path) -> list[str]:
    """Windows template links resolve as deployed AGENTS.md, not in templates/."""
    errors = []
    paths = ["AGENTS.md", ".studio/workflow.md", ".studio/spec/creative.md",
             ".studio/spec/visual-design.md", ".studio/spec/privacy.md",
             ".studio/templates/WINDOWS_AGENTS.md", ".studio/templates/STUDIO_AGENTS.md"]
    paths += [str(path.relative_to(repo)) for path in (repo / '.studio/spec').glob('hyperframes*.md')]
    paths += ['.studio/spec/runtime-interfaces.md', '.studio/spec/showcase.md', '.studio/spec/math-rap.md',
              '.studio/templates/CLAUDE.template.md']
    for relative in paths:
        path = repo / relative
        if not path.is_file():
            continue
        base = repo if relative.endswith(("WINDOWS_AGENTS.md", "CLAUDE.template.md")) else repo / ".studio" if relative.endswith("STUDIO_AGENTS.md") else path.parent
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>").split("#", 1)[0]
            if not target or "://" in target:
                continue
            resolved = (base / target).resolve()
            if not resolved.is_relative_to(repo.resolve()) or not (resolved.is_file() or resolved.is_dir()):
                errors.append(f"invalid rule link: {relative}: {target}")
    return errors


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_PACKAGE:
        if not (ROOT / relative).is_file():
            errors.append(f"missing package file: {relative}")
    scopes = json.loads((REPO / '.studio/package-scopes.json').read_text(encoding='utf-8'))
    installed = {p.parent.name for p in (REPO / '.studio/designs').glob('*/design.json')}
    public = set(scopes['public_cards'])
    if installed not in (public, set()):
        errors.append('incomplete public/personal design catalog')
    for relative in REQUIRED_HARNESS:
        if (relative in scopes['personal_files']
                or relative.startswith(tuple(scopes['personal_prefixes']))):
            continue
        if not (REPO / relative).is_file():
            errors.append(f"missing harness file: {relative}")
    errors.extend(rule_link_errors(REPO))

    for path in sorted(ROOT.rglob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid json: {path.relative_to(ROOT)}: {exc}")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK: {ROOT.name} v{(ROOT / 'VERSION').read_text().strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
