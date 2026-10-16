#!/usr/bin/env python3
"""Local lifecycle CLI for HyperFrames AI works."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable
from types import SimpleNamespace
import unicodedata
import uuid
from urllib.parse import quote, unquote, urlsplit


try:
    from component_harness import (
        ComponentError,
        OPTIONAL_SNAPSHOT_ITEMS,
        install_component,
        parse_component_ref,
        validate_component_release,
        validate_snapshot_closure,
        validate_work_surface_inventory,
        verify_installation,
    )
except ModuleNotFoundError:  # Loading this file by path from repository tests.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from component_harness import (
        ComponentError,
        OPTIONAL_SNAPSHOT_ITEMS,
        install_component,
        parse_component_ref,
        validate_component_release,
        validate_snapshot_closure,
        validate_work_surface_inventory,
        verify_installation,
    )

from visual_plan import VisualPlanError, PLAN_FORMAT, plan_scene_rows, scene_projection, layout_projection, reference_projection, validate_dependencies, source_changes, serve
import icon_sets
import math_build
import work_requests
import studio_preview
import visual_diagnostics
import asset_store
import control_plane
import appearance
import explainer
import storage
import work_storage
import appearance_rebind
import research_catalog
import work_migration
import work_successor
import critic
import visual_memory
import work_memory
import work_context
import workflow_config
import content_retro
import lines
import designs
import settings as work_settings

WORKFLOWS = {"hyperframes_video"}
TEMPLATES = {"talking_head", "pure_hyperframes"}
PROFILES = {"optical_fluidity", "kami_editorial", "monochrome_atelier"}
RATIOS = {"16:9", "4:3", "9:16", "source"}
SUBJECT_POSITIONS = {"left", "center", "right"}
WAIT_REASONS = {
    "script_approval": ("waiting_user", "Wait for SCRIPT.md approval"),
    "recording": ("waiting_asset", "Wait for the talking-head recording"),
    "plan_approval": ("waiting_user", "Wait for ANIMATION_PLAN.md approval"),
    "draft_feedback": ("waiting_user", "Wait for Draft feedback or acceptance"),
    "voiceover": ("waiting_asset", "Wait for the final voiceover"),
    "external_asset": ("waiting_asset", "Wait for an external media asset"),
}
SNAPSHOT_ITEMS = ("index.html", "compositions", "DESIGN.md", "project-config.json")
ID_PATTERN = re.compile(r"^[\w.-]+$", re.UNICODE)
NUMBERED_TITLE_PATTERN = re.compile(r"^(\d{3})-(.+)$")
# works/<series>/<Work>/; the legacy flat containers stay readable until `migrate layout`.
LEGACY_WORK_CONTAINERS = ("active", "parked", "archive")
RESERVED_SERIES_IDS = {*LEGACY_WORK_CONTAINERS, "history"}
UNSORTED_SERIES_FOLDER = "_未归系列"
LEGACY_ARCHIVE_MARKER = ".runtime/legacy-archive.json"


class HarnessError(RuntimeError):
    pass


def repo_root() -> Path:
    override = os.environ.get("HYPERFRAMES_AI_ROOT")
    return Path(override).resolve() if override else Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def stale_naming_lock(lock: Path) -> bool:
    owner = lock / "owner.json"
    try:
        data = json.loads(owner.read_text(encoding="utf-8"))
        pid = int(data["pid"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    if data.get("host") != socket.gethostname() or data.get("platform") != sys.platform or pid <= 0:
        return False
    return storage.process_stopped(pid)


@contextmanager
def naming_lock(root: Path, timeout: float = 30.0, *, successor_recovery: bool = False) -> Iterable[None]:
    """Use one atomic directory lock that Windows and WSL can both observe."""
    lock = runtime_root(root) / "naming.lock.d"
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if stale_naming_lock(lock):
                (lock / "owner.json").unlink(missing_ok=True)
                try:
                    lock.rmdir()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                owner = lock / "owner.json"
                detail = owner.read_text(encoding="utf-8").strip() if owner.is_file() else "unknown owner"
                raise HarnessError(f"Timed out waiting for naming lock {lock}: {detail}")
            time.sleep(0.1)
    try:
        write_json(
            lock / "owner.json",
            {"pid": os.getpid(), "host": socket.gethostname(), "platform": sys.platform, "acquired_at": now()},
        )
        if not successor_recovery and (runtime_root(root) / work_successor.JOURNAL).exists():
            raise HarnessError("Succession recovery pending; retry the original successor command")
        yield
    finally:
        (lock / "owner.json").unlink(missing_ok=True)
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass


def write_json(path: Path, data: dict[str, Any]) -> None:
    # JSON is valid YAML 1.2 and keeps the CLI dependency-free.
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"Cannot read structured file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"Expected an object in {path}")
    return data


def read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise HarnessError(f"Cannot read {path}: {exc}") from exc
    if not lines or lines[0] != "---":
        raise HarnessError(f"Missing JSON front matter in {path}")
    try:
        end = lines.index("---", 1)
        data = json.loads("\n".join(lines[1:end]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HarnessError(f"Invalid JSON front matter in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessError(f"Expected an object in {path} front matter")
    return data


def document_body(path: Path) -> str:
    read_frontmatter(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return "".join(lines[end + 1:])


def script_text(path: Path, *, anchors: bool = False) -> str:
    """Extract narration only; planning indexes never reach reading or alignment input."""
    body = document_body(path)
    start, end = "<!-- scene-index:start -->", "<!-- scene-index:end -->"
    if start in body or end in body:
        if body.count(start) != 1 or body.count(end) != 1 or body.index(start) > body.index(end):
            raise HarnessError("SCRIPT.md needs one paired scene-index:start/end block")
        before, rest = body.split(start)
        _, after = rest.split(end)
        body = before + after
    if not anchors:
        body = re.sub(r"<!--\s*P\d+\s*-->[ \t]*\n?", "", body)
    return body.strip()


def command_script_text(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    require_workflow(work, "hyperframes_video")
    if not selected_variant_id(root, work, args) and (work / "shared" / "SCRIPT.md").is_file():
        print(script_text(work / "shared" / "SCRIPT.md", anchors=args.anchors))
    else:
        variant, _ = selected_variant(root, work, args)
        print(script_text(input_path(variant, "SCRIPT.md"), anchors=args.anchors))


def command_tts(root: Path, args: argparse.Namespace) -> None:
    import work_tts
    try:
        work_tts.command(root, args, SimpleNamespace(**globals()))
    except OSError as error:
        raise HarnessError('TTS input/output failed; check the selected local files and permissions') from error


def command_showcase(root: Path, args: argparse.Namespace) -> None:
    import showcase_tools
    if not args.work_override or not args.variant_override:
        raise HarnessError('Showcase tools require explicit --work and --variant')
    work, _ = selected_work(root, args)
    require_workflow(work, 'hyperframes_video')
    variant, state = selected_variant(root, work, args)
    output = storage.scoped_path(variant / 'project', args.output)
    if args.showcase_command == 'stage':
        report = showcase_tools.stage(output, overwrite=args.overwrite)
    else:
        source = storage.scoped_path(work, args.input)
        report = showcase_tools.cast(source, output, kind=args.kind, overwrite=args.overwrite,
                                     target_height=args.target_height, border=args.border,
                                     pose_scale=args.pose_scale)
    print_result(root, args, report)


def command_explainer_build(root: Path, args: argparse.Namespace) -> None:
    from component_harness import package_write_lock
    if not args.work_override or not args.variant_override:
        raise HarnessError("Explainer build requires explicit --work and --variant")
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    project = variant / "project"
    with naming_lock(root), package_write_lock(work_requests.safe(variant, ".runtime/component-install.lock")):
        state = read_json(variant / "variant.yaml")
        lock = state.get("appearance_lock")
        # Independent design cards need no Theme/Background assets.
        if lock:
            if "capabilities" not in lock and lock.get("mode") not in appearance.MODES:
                raise HarnessError("Build requires a frozen supported appearance lock")
            appearance.verify(project, lock, check_mounts=False)
        else:
            card = lines.frozen(state) if state.get('design_snapshot') or state.get('design_live') else None
            if not card or not designs.capabilities(card):
                raise HarnessError("Build requires a supported design")
            explainer.installed_assets(project, check_mounts=False)
        script = input_path(variant, "SCRIPT.md")
        if script_confirmation(variant, state) and read_frontmatter(script).get("approval") not in {"approved", "not_required"}:
            raise HarnessError("SCRIPT.md still requires approval")
        text = script_text(script)
        cue_path = storage.scoped_path(project, "runtime/cues.json")
        if args.command == "cues":
            try:
                alignment = Path(args.alignment).read_bytes()
            except OSError as exc:
                raise HarnessError(f"Cannot read alignment: {exc}") from exc
            data = explainer.build_cues(text, alignment)
            config_path = storage.scoped_path(project, "project-config.json")
            runtime = storage.scoped_path(project, "runtime/cues.js")
            before = {path: path.read_text(encoding="utf-8") if path.exists() else None
                      for path in (cue_path, config_path)}
            if not runtime.exists():
                before[runtime] = None
            try:
                write_json(cue_path, data)
                if not runtime.exists():
                    atomic_write(runtime, (Path(__file__).parent / "runtime/cues.js").read_text(encoding="utf-8"))
                explainer.declare_files(project, ["runtime/cues.json", "runtime/cues.js"])
            except Exception:
                for path, original in before.items():
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, original)
                raise
            print(json.dumps({"path": str(cue_path), "mismatches": data["mismatches"]}, ensure_ascii=False))
            return
        cues = explainer.validate_cues(explainer.read_json(cue_path))
        if cues.get("sources", {}).get("script_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise HarnessError("Narration changed; rebuild cues before sound")
        plan_path = input_path(variant, "ANIMATION_PLAN.md")
        if read_frontmatter(plan_path).get("status") != "approved" and plan_confirmation(root, variant, state):
            raise HarnessError("ANIMATION_PLAN.md must be approved before sound build")
        plan_scene_rows(plan_path.read_text(encoding="utf-8"))
        blocks = re.findall(r"^```sound[ \t]*\n(.*?)^```[ \t]*$", document_body(plan_path), re.M | re.S)
        sound_path = storage.scoped_path(project, "sound.json")
        if len(blocks) != 1:
            raise HarnessError("Approved Plan requires one sound JSON block")
        try:
            sound = json.loads(blocks[0])
        except ValueError as exc:
            raise HarnessError(f"Invalid Plan sound JSON: {exc}") from exc
        if (isinstance(sound, dict) and sound.get('sfx')
                and state.get('design_values', {}).get('sfx.enabled') is False):
            raise HarnessError('SFX are disabled in the frozen configuration; reselect with sfx.enabled=true before building this sound Plan')
        assets = explainer.installed_assets(project, check_mounts=False)
        for asset in assets.values():
            asset["path"] = str(storage.scoped_path(project, f'{asset["vendor_path"]}/{asset["metadata"]["entry"]}'))
        elements, tracks = explainer.sound_elements(sound, cues, assets)
        index = storage.scoped_path(project, "index.html")
        updated = explainer.insert_sound(index.read_text(encoding="utf-8"), elements)
        config_path = storage.scoped_path(project, "project-config.json")
        before = {path: path.read_text(encoding="utf-8") if path.exists() else None
                  for path in (sound_path, index, config_path)}
        try:
            write_json(sound_path, sound)
            atomic_write(index, updated)
            explainer.declare_files(project, ["sound.json", "runtime/cues.json"])
            if lock:
                appearance.verify(project, lock)
            else:
                explainer.installed_assets(project)
        except Exception:
            for path, original in before.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, original)
            raise
        print(json.dumps({"path": str(sound_path), "tracks": tracks}, ensure_ascii=False))


def command_import_sfx(root: Path, args: argparse.Namespace) -> None:
    from sfx_import import import_sfx
    print(json.dumps(import_sfx(Path(args.package), Path(args.source)), ensure_ascii=False, indent=2))


def input_path(directory: Path, name: str) -> Path:
    return control_plane.input_path(SimpleNamespace(**globals()), directory, name)


def account_service(root: Path) -> control_plane.AccountService:
    return control_plane.AccountService(SimpleNamespace(**globals()), root)


def command_config(root: Path, args: argparse.Namespace) -> None:
    service = account_service(root)
    if args.operation == "put":
        if args.file == "-":
            try:
                data = json.loads(sys.stdin.read())
            except ValueError as error:
                raise HarnessError(f"Invalid JSON on stdin: {error}") from error
        else:
            data = read_json(Path(args.file))
        record = service.put(args.command, args.identity, data)
    elif args.operation == "get":
        record = service.get(args.command, args.identity)
        if args.command == "series":
            record = {**record, "works": [row["id"] for row in list_work_rows(root)
                                         if read_frontmatter(locate_work(root, row["id"])[0] / "WORK.md").get("series") == args.identity]}
        elif args.command == "account":
            record = {**record, "variants": [
                {"work": row["id"], "series": row["series"], "series_number": row["series_number"], **variant}
                for row in list_work_rows(root) if row["workflow"] == "hyperframes_video"
                for variant in row["variants"] if variant["account"] == args.identity]}
    else:
        record = [read_json(path) for path in sorted((service.directory / args.command).glob("*.json"))]
    print(json.dumps(record, ensure_ascii=False, indent=2))


def command_series_rules(root: Path, args: argparse.Namespace) -> None:
    service = account_service(root)
    if args.rules_operation == "put":
        try:
            # "-" reads stdin so agents need no draft file in the WorkStore.
            content = sys.stdin.read() if args.file == "-" else Path(args.file).expanduser().read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise HarnessError(f"Cannot read series rules file: {error}") from error
        record = service.put_rules(args.identity, content)
    elif args.rules_operation == "delete":
        record = service.delete_rules(args.identity)
    else:
        record = service.get_rules(args.identity)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def command_series_delete(root: Path, args: argparse.Namespace) -> None:
    with naming_lock(root):
        record = account_service(root).delete_series(args.identity, list_work_rows(root))
    print(json.dumps(record, ensure_ascii=False, indent=2))


def series_rules_reference(root: Path, series: Any) -> dict[str, Any] | None:
    if not isinstance(series, str) or not series:
        return None
    try:
        record = account_service(root).get_rules(series)
    except HarnessError as error:
        return {"series": series, "error": str(error)}
    return {key: record[key] for key in ("series", "path", "exists")}


def appearance_options(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    path = getattr(args, "appearance_file", None)
    explicit = read_json(Path(path)) if path else {}
    for key in ("theme", "background", "mode", "submodule", "ratio", "fps", "seed"):
        value = getattr(args, key, None)
        if value is not None:
            if key in {'theme', 'background'} and '/' in value and '@' not in value:
                _, report = asset_store.card_asset_reference(root, value)
                if report['kind'] != key:
                    raise HarnessError(f"Expected a {key} asset")
                value = {field: report[field] for field in ('ref', 'kind', 'package_sha256')}
            elif key == "background" or key == "theme" and "@v" in value:
                package, _ = asset_store.resolve_component(root, value)
                report = validate_component_release(package, allow_unapproved=True)
                if report["metadata"].get("asset_type") != key:
                    raise HarnessError(f"Expected a {key} asset")
                value = {"ref": report["component_ref"], "kind": key, "package_sha256": report["package_sha256"]}
            explicit[key] = value
    if getattr(args, "captions", None) is not None:
        explicit["captions"] = args.captions == "on"
    return explicit


def command_appearance_resolve(root: Path, args: argparse.Namespace) -> None:
    service = account_service(root)
    account = service.get("account", args.account) if args.account else {}
    print_result(root, args, appearance.resolve(root, account, appearance_options(root, args)))


def command_appearance_update(root: Path, args: argparse.Namespace) -> None:
    appearance_rebind.command(root, args, SimpleNamespace(**globals()))


def previous_adoption(root: Path, series: str | None, work: Path | None = None) -> dict | None:
    if not series or series == 'test':
        return None
    current_number = read_frontmatter(work / 'WORK.md').get('series_number') if work else None
    rows = [row for row in list_work_rows(root) if row.get('workflow') == 'hyperframes_video'
            and row.get('series') == series and (not work or row['id'] != work.name)
            and (current_number is None or (row.get('series_number') or 0) < current_number)]
    if not rows:
        return None
    latest = max(row.get('series_number') or 0 for row in rows)
    choices = {}
    for row in rows:
        if (row.get('series_number') or 0) != latest:
            continue
        prior_work, _ = locate_work(root, row['id'])
        for variant in row.get('variants', []):
            state = read_json(prior_work / 'variants' / variant['id'] / 'variant.yaml')
            identity = state.get('design') or (state.get('line') or {}).get('id')
            account = state.get('account')
            if identity and (account is not None or state.get('account_selection') == 'none'):
                key = (identity, state.get('design_version'), state.get('design_sha256'), account, state.get('account_revision'))
                choices[key] = {'work': row['id'], 'state': state}
    if len(choices) > 1:
        raise HarnessError('Previous series Work has multiple account/design choices; select --design and --account or --no-account')
    return next(iter(choices.values())) if choices else None


def selected_design(root: Path, args: argparse.Namespace, work: Path | None, account: dict,
                    series_settings: dict, prior: dict | None = None) -> dict:
    explicit = getattr(args, 'design', None) or getattr(args, 'mode', None)
    if explicit:
        return designs.require(explicit)
    if prior:
        return designs.require(designs.identify(prior['state']))
    identity = series_settings.get('design') or account.get('design')
    if not identity and series_settings.get('spec') == 'math-rap':
        identity = 'math'
    if not identity and series_settings.get('mode') in designs.DESIGN_IDS:
        identity = series_settings['mode']
    if identity:
        return designs.require(identity)
    raise HarnessError('No design selected; choose --design before creating a Variant')


def adopted_settings(root: Path, args: argparse.Namespace, work: Path | None = None) -> dict[str, Any]:
    service = account_service(root)
    series_settings = {}
    purpose = read_frontmatter(work / "WORK.md").get("purpose", "standard") if work else args.purpose or "standard"
    series = read_frontmatter(work / 'WORK.md').get('series') if work else getattr(args, 'series', None)
    no_account = getattr(args, 'no_account', False)
    needs_default = not (getattr(args, 'design', None) or getattr(args, 'mode', None)) or (not args.account and not no_account)
    prior = (getattr(args, '_selection_prior', None) or previous_adoption(root, series, work)) if needs_default and purpose != 'test' else None
    account = service.get('account', args.account) if args.account else {}
    if not args.account and not no_account and prior:
        args.account = prior['state'].get('account')
        no_account = prior['state'].get('account_selection') == 'none'
        account = prior['state'].get('account_settings', {})
    if (getattr(args, "workflow", None) == "hyperframes_video" or work and work_workflow(work) == "hyperframes_video"):
        appearance.check_mode(account.get("mode"), "Account")
        series = read_frontmatter(work / "WORK.md").get("series") if work else getattr(args, "series", None)
        if series and series != "test":
            series_settings = service.get("series", series)
            appearance.check_mode(series_settings.get("mode"), "Series")
    if (getattr(args, "workflow", None) == "hyperframes_video" or work and work_workflow(work) == "hyperframes_video") and purpose != "test" and not account and not no_account:
        raise HarnessError("Account is not selected; choose --account or explicitly --no-account")
    if purpose == "test" and account:
        raise HarnessError("test Work binds batches, not accounts")
    if purpose != "test" and args.batch:
        raise HarnessError("Only test Work accepts a batch")
    if work and purpose == "test":
        batch = args.batch or args.variant_id
        if any(read_json(path / "variant.yaml").get("batch") == batch for path in variant_paths(work)
               if not (getattr(args, '_selection_prior', None) and path.name == args.variant_id)):
            raise HarnessError("A batch already has a Variant; revise that Variant")
    try:
        card = selected_design(root, args, work, account, series_settings, prior)
    except designs.DesignError as error:
        raise HarnessError(str(error)) from error
    explicit = appearance_options(root, args)
    explicit.pop("mode", None)
    if "capabilities" not in card and card.get("mode") == "showcase":
        explicit.setdefault("submodule", "pdoom")
    elif "submodule" in explicit:
        raise HarnessError("submodule is only supported by showcase designs")
    variant_overrides = dict(getattr(args, '_variant_overrides', {}))
    if getattr(args, 'overrides', None):
        variant_overrides = read_json(Path(args.overrides))
        designs.layer_values(variant_overrides, 'variant')
    if "captions" in explicit:
        variant_overrides["captions"] = {"enabled": explicit["captions"]}
    for key in ("ratio", "width", "height", "fps", "seed"):
        if explicit.get(key) is not None:
            variant_overrides[key] = explicit[key]
    work_meta = read_frontmatter(work / "WORK.md") if work else {}
    try:
        resolved = designs.resolve(card["id"], card=card, series=series_settings.get("overrides"),
                                   work=work_meta.get("overrides"), account=account.get("overrides"),
                                   variant=variant_overrides)
    except designs.DesignError as error:
        raise HarnessError(str(error)) from error
    values, sources = resolved["values"], resolved["sources"]
    if values.get("captions.enabled") is not None:
        account = {**account, "captions": values["captions.enabled"]}
    series_binding = ({"series_binding": {key: series_settings.get(key) for key in ("id", "revision", "mode", "spec", "design") if series_settings.get(key) is not None}}
                      if series_settings.get("mode") or series_settings.get("spec") or series_settings.get("design") else {})
    design_binding = {"design": card["id"], "design_version": card["version"], "design_sources": sources,
                      "variant_overrides": variant_overrides,
                      "design_live": True, "design_values": values,
                      **({"capabilities": designs.capabilities(card)} if "capabilities" in card else {}),
                      "account_selection": 'none' if no_account else 'selected' if args.account else 'unset',
                      "selection_source_work": prior['work'] if prior else None,
                      "captions": values.get("captions.enabled", False),
                      "sfx": {"enabled": values.get("sfx.enabled"), "policy": values.get("sfx.policy")},
                      "cover": {"enabled": values.get("cover.enabled")}}
    appearance_overrides = {key: value for key, value in (account.get("overrides") or {}).items()
                            if key in ("theme", "background", "motion")}
    appearance_account = {key: value for key, value in account.items() if key != "overrides"}
    if appearance_overrides:
        appearance_account["overrides"] = appearance_overrides
    if (appearance.is_asset_appearance({**appearance_account, **explicit})
            or ("capabilities" in card and not isinstance(explicit.get("theme", appearance_account.get("theme")), str))
            or card.get("mode") == "showcase"):
        for key in ("ratio", "fps", "seed"):
            if values.get(key) is not None:
                explicit.setdefault(key, values[key])
        if "capabilities" in card:
            explicit["capabilities"] = designs.capabilities(card)
        else:
            explicit["mode"] = card["mode"]
        explicit.setdefault("captions", values.get("captions.enabled", False))
        if card.get('fonts'):
            explicit['card_fonts'] = designs.font_manifest(card, designs.card_path(card['id']))
        lock = appearance.resolve(root, appearance_account, explicit)
        for item in lock['assets']:
            reference = item['ref'].rsplit('@v', 1)[0]
            if '/' in reference and reference.split('/')[0] != card['id'] and reference not in card.get('references', []):
                raise HarnessError('Declare this asset in the selected card references: ' + reference)
        return {"theme": lock["selection"]["theme"], "background": lock["selection"]["background"],
                "motion": lock["selection"]["motion"], **({"mode": lock["mode"]} if "mode" in lock else {}), "ratio": lock["ratio"],
                **{key: lock[key] for key in ("fps", "seed", "width", "height")},
                "appearance_lock": lock, "account": args.account, "account_revision": account.get("revision"),
                "account_settings": account, "batch": args.batch, "revision": 1,
                **series_binding, **design_binding}
    if "capabilities" in card and any(value == "required" for value in designs.capabilities(card)["bindings"].values()):
        raise HarnessError("Required bindings need exact appearance assets")
    if set(explicit) - {"theme", "ratio"}:
        raise HarnessError("Appearance parameters require exact Theme and Background assets")
    settings = {key: explicit.get(key, account.get(key)) for key in ("theme", "ratio")}
    settings['ratio'] = values.get('ratio', settings['ratio'])
    if "mode" in card:
        settings["mode"] = card["mode"]
    for key in ("fps", "seed", "width", "height"):
        if values.get(key) is not None:
            settings[key] = values[key]
    if settings["ratio"] == "source":
        raise HarnessError("source ratio requires exact Theme and Background assets and concrete 16:9 or 9:16 dimensions")
    if settings["theme"]:
        settings["ratio"] = settings["ratio"] or "16:9"
    theme = service.appearance(settings)
    return {**settings, "account": args.account, "account_revision": account.get("revision"),
            "account_settings": account, "theme_revision": theme.get("revision"), "theme_settings": theme,
            "batch": args.batch, "revision": 1, **series_binding, **design_binding}


def plan_with_card(text, state):
    """Parse against the selected/Draft card without changing accepted document bytes."""
    if not state.get('design_snapshot'):
        return text
    match = re.match(r'\A---\s*\n(.*?)\n---(?:\n|$)', text, re.S)
    if not match:
        return text
    metadata = json.loads(match[1])
    metadata.update({key: state[key] for key in ('line', 'design_snapshot', 'design_sha256')})
    metadata.pop('design_live', None)
    return '---\n' + json.dumps(metadata, ensure_ascii=False) + '\n---\n' + text[match.end():]


def plan_metadata(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    """CLI-owned identity and frozen settings; missing inputs remain explicit nulls."""
    lock = state.get("appearance_lock") or {}
    selection = lock.get("selection", {})
    inputs = {}
    for name in ("SCRIPT.md", "RESEARCH.md"):
        target = input_path(path, name)
        inputs[name] = {"path": state.get("shared_inputs", {}).get(name, f"variants/{state['id']}/{name}"),
                        "revision": read_frontmatter(target).get("revision")}
    work = path.parent.parent
    return {"plan_format": '3.7.0' if state.get('line') and ('capabilities' in state or state.get('mode') != 'showcase') else PLAN_FORMAT,
            **({'line': state['line']} if state.get('line') else {}),
            **({'design_live': True} if state.get('design_live') else {}),
            **({'capabilities': lines.capabilities(state)} if 'capabilities' in state else {}),
            **({key: state[key] for key in ('design_snapshot', 'design_sha256')} if state.get('design_snapshot') else {}),
            "work": read_frontmatter(work / 'WORK.md')['id'], "variant": state["id"],
            "revision": state.get("plan_revision", 1), "inputs": inputs,
            **{key: state.get(key) for key in ("template", "profile", "subject_position")},
            "script_revision": inputs["SCRIPT.md"]["revision"], "research_revision": inputs["RESEARCH.md"]["revision"],
            **{key: lock.get(key, state.get(key)) for key in ("ratio", "fps")},
            **({"mode": lock.get("mode", state.get("mode"))} if lock.get("mode", state.get("mode")) is not None else {}),
            **{key: selection.get(key, state.get(key)) for key in ("theme", "background", "motion", "captions")},
            "appearance_lock_sha256": lock.get("sha256"), "audio": state.get("audio"),
            "alignment": state.get("alignment"),
            **({"submodule": lock["submodule"]} if "submodule" in lock else {}),
            **({"series_binding": state["series_binding"]} if "series_binding" in state else {})}


def plan_metadata_body(body: str, metadata: dict[str, Any]) -> str:
    body = re.sub(r'<!-- plan-metadata:start -->.*?<!-- plan-metadata:end -->\s*', '', body, flags=re.S).lstrip('\r\n')
    keys = ('plan_format', 'work', 'variant', 'revision', 'inputs', 'ratio', 'fps', 'theme', 'background', 'motion', 'mode', 'captions', 'audio', 'alignment')
    rows = ['<!-- plan-metadata:start -->', '| CLI 元信息 | 当前值 |', '|---|---|']
    rows += [f"| {key} | {json.dumps(metadata.get(key), ensure_ascii=False).replace('|', '&#124;')} |" for key in keys if key != "mode" or key in metadata]
    return '\n'.join([*rows, '<!-- plan-metadata:end -->', '', body])


def command_plan_refresh(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    plan = variant / "ANIMATION_PLAN.md"
    plan_scene_rows(plan.read_text(encoding="utf-8"))
    original = read_frontmatter(plan)
    metadata = plan_metadata(variant, state)
    revisions = (state.get("plan_revision", 1), original.get("revision", 1),
                 metadata["script_revision"], metadata["research_revision"])
    if any(type(value) is not int or value < 1 for value in revisions):
        raise HarnessError("Plan and input revisions must be positive integers")
    changed = any(original.get(key) != value for key, value in metadata.items() if key != "revision")
    text = plan.read_text(encoding='utf-8')
    effective = effective_settings(root, state)
    reference_input = visual_memory.reference_input(text, effective)
    memory_needed = bool(visual_memory.references(text) or original.get('reference_memory_sha256'))
    old_memory = None
    if original.get('reference_memory_sha256'):
        old_memory = visual_memory.frozen(visual_memory.located(variant, original['revision'], original['reference_memory_sha256']),
                                          original['reference_memory_sha256'])
    changed = changed or (memory_needed and (old_memory is None or old_memory['input'] != reference_input))
    revision = max(state.get("plan_revision", 1), original.get("revision", 1)) + int(changed)
    if memory_needed:
        try:
            if old_memory is not None and revision == original['revision']:
                # Restore a freeze an earlier CLI revision bump skipped; unchanged inputs keep identical evidence.
                visual_memory.carry(variant, original['revision'], revision, original['reference_memory_sha256'])
            metadata['reference_memory_sha256'] = visual_memory.freeze(configured_work_root(root) or root, variant, revision, text, state, effective)
        except ValueError as error:
            raise HarnessError(str(error)) from error
    state.update(plan_revision=revision, script_revision=metadata["script_revision"])
    metadata = {**original, **metadata, "revision": revision}
    # Frozen acceptance stays as the comparison baseline, not approval of new inputs.
    if changed:
        state.update(accepted_preview=None, current_final=None)
    atomic_write(plan, "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n"
                 + plan_metadata_body(document_body(plan), metadata))
    write_variant(variant, state)
    print(json.dumps({"work": work.name, "variant": state["id"], "revision": revision,
                      "changed": changed}, ensure_ascii=False))


def command_plan_check(root: Path, args: argparse.Namespace) -> None:
    import math_chain
    import seek_check
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    project = variant / "project"
    import work_tts
    work_tts.verify(variant, SimpleNamespace(**globals()))
    text = plan_with_card((variant / "ANIMATION_PLAN.md").read_text(encoding="utf-8"), state)
    rows = plan_scene_rows(text)
    dependencies = validate_dependencies(project)
    findings = seek_check.findings(project, dependencies)
    _, _, reference_findings = visual_memory.resolve(configured_work_root(root) or root, text,
        visual_memory.line_id(state), effective_settings(root, state), card=lines.frozen(state) or lines.select(state))
    findings.extend(reference_findings)
    if read_frontmatter(variant / 'ANIMATION_PLAN.md').get('plan_format') == '3.7.0':
        script = input_path(variant, 'SCRIPT.md').read_text(encoding='utf-8')
        script_scenes = set(re.findall(r'^\|\s*(S[0-9]+[A-Z]*)\s*\|', script, re.M))
        if script_scenes != set(rows):
            findings.append({'kind': 'script_scene_mismatch', 'script': sorted(script_scenes), 'plan': list(rows)})
        if read_frontmatter(variant / 'ANIMATION_PLAN.md').get('line') != state.get('line'):
            findings.append({'kind': 'line_binding_mismatch'})
    if lines.has_check(state, 'english'):
        import english_plan
        cue_path = project / 'runtime/cues.json'
        findings.extend(english_plan.check(text, read_json(cue_path) if cue_path.is_file() else None))
    diagnostic = visual_diagnostics.explainer_diagnostics(project, dependencies, state.get("appearance_lock"), text)
    findings.extend(diagnostic["findings"])
    if lines.has_check(state, 'css-contract'):
        import css_contract
        findings.extend(css_contract.findings(project, dependencies))
    if lines.is_math(state):
        cues = explainer.validate_cues(read_json(project / "runtime/cues.json"))
        scenes = scene_projection(project, text)
        try:
            findings.extend(math_chain.plan_findings(text, cues, max(s["start"] + s["duration"] for s in scenes), scenes=scenes))
        except ValueError as error:
            raise HarnessError(str(error)) from error
    print_result(root, args, {"status": "diagnostic_only", "findings": findings, "unverified": diagnostic["unverified"]})


def command_beats_build(root: Path, args: argparse.Namespace) -> None:
    import math_audio
    if not args.work_override or not args.variant_override:
        raise HarnessError("Beat extraction requires explicit --work and --variant")
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    with naming_lock(root):
        audio = storage.scoped_path(work, args.audio)
        if not audio.is_file() or audio.stat().st_nlink != 1:
            raise HarnessError("Formal audio must be an unlinked Work-local file")
        path = storage.scoped_path(variant, "project/runtime/cues.json")
        cues = explainer.validate_cues(read_json(path))
        cli = runtime_path(args.hyperframes_cli, "HYPERFRAMES_CLI")
        try:
            grid = math_audio.extract(audio, cli, args.beats_per_bar, args.first_downbeat)
        except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
            raise HarnessError(str(error)) from error
        cues["beat_grid"] = grid
        write_json(path, explainer.validate_cues(cues))
    print_result(root, args, {"path": str(path), "audio_sha256": grid["audio_sha256"], "beats": len(grid["times"])})


def command_review_package(root: Path, args: argparse.Namespace) -> None:
    import review_bundle
    if not args.work_override or not args.variant_override:
        raise HarnessError("Review package requires explicit --work and --variant")
    work, _ = selected_work(root, args, allow_archive=True)
    require_workflow(work, "hyperframes_video")
    variant, _ = selected_variant(root, work, args)
    declaration = read_json(storage.scoped_path(work, args.manifest))
    with naming_lock(root):
        result = review_bundle.build(configured_work_root(root) or root, work, variant, args.review_id, declaration)
    print_result(root, args, {"path": str(result)})


def adopt_variant(path: Path, settings: dict[str, Any], *, shared: bool = False, branch: str | None = None) -> None:
    state = read_json(path / "variant.yaml")
    state.update({key: value for key, value in settings.items() if value is not None})
    if settings.get('design') and (path / 'ANIMATION_PLAN.md').is_file():
        state['line'] = {'id': settings['design'], 'version': settings['design_version']}
    if settings.get("theme") or settings.get("appearance_lock"):
        state["profile"] = None
    work = path.parent.parent
    if settings.get("design") or settings.get("mode") in {"showcase", "math", "english"}:
        plan = path / "ANIMATION_PLAN.md"
        original = read_frontmatter(plan)
        card = lines.frozen(state)
        directory = storage.scoped_path(path, state['design_files']['path']) / 'card' if state.get('design_files') else None
        body = designs.template_path(card, card['plan_template'], directory=directory).read_text(encoding="utf-8").split("\n---", 1)[1].lstrip("\r\n")
        atomic_write(plan, "---\n" + json.dumps(original, ensure_ascii=False) + "\n---\n" + body)
    if shared:
        refs = {}
        for name in ("SCRIPT.md", "RESEARCH.md"):
            target = work / "shared" / name
            if not target.exists():
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(path / name, target)
            refs[name] = target.relative_to(work).as_posix()
            (path / name).unlink(missing_ok=True)
        state["shared_inputs"] = refs
    if branch:
        state["content_branch"] = {"source_variant": branch, "input_sha256": {
            name: file_sha256(path / name) for name in ("SCRIPT.md", "RESEARCH.md")}}
    write_variant(path, state)
    plan = path / "ANIMATION_PLAN.md"
    if plan.is_file():
        metadata = {**read_frontmatter(plan), **plan_metadata(path, state)}
        atomic_write(plan, "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + plan_metadata_body(document_body(plan), metadata))


def create_adopted_variant(root: Path, work: Path, variant_id: str, settings: dict[str, Any], *,
                           shared: bool = False, branch: str | None = None, **options: Any) -> Path:
    destination = work / "variants" / validate_id(variant_id, "variant id")
    if destination.exists():
        raise HarnessError(f"Variant already exists: {variant_id}")
    staging_id = f".pending-{uuid.uuid4().hex}"
    staging = work / "variants" / staging_id
    try:
        if "appearance_lock" in settings and options.get("ratio") not in RATIOS:
            options["ratio"] = "source"
        create_variant(root, work, staging_id, **options)
        if "appearance_lock" in settings:
            appearance.materialize(root, staging / "project", settings["appearance_lock"])
        adopt_variant(staging, {**settings, "id": variant_id}, shared=shared, branch=branch)
        staging.rename(destination)
    except Exception:
        if staging.is_dir():
            shutil.rmtree(staging)
        raise
    return destination


def animation_plan_contains_component_ref(path: Path, component_ref: str) -> bool:
    """Check the approved Plan body for the exact requested Component ref."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        end = lines.index("---", 1)
    except (OSError, ValueError) as exc:
        raise HarnessError(f"Cannot read Animation Plan body {path}: {exc}") from exc
    pattern = re.compile(rf"(?<![A-Za-z0-9_.-]){re.escape(component_ref)}(?![A-Za-z0-9_.-])")
    return any(pattern.search(line) for line in lines[end + 1 :])


def work_workflow(work: Path) -> str:
    if work.is_symlink():
        raise HarnessError("Linked Work is isolated")
    value = read_frontmatter(work / "WORK.md").get("workflow")
    if value not in WORKFLOWS:
        raise HarnessError(f"Unknown workflow: {value}")
    return str(value)


def require_workflow(work: Path, expected: str) -> None:
    actual = work_workflow(work)
    if actual != expected:
        raise HarnessError(f"Command requires workflow {expected}; current Work uses {actual}")


def template_text(root: Path, name: str, values: dict[str, str], *, card=None) -> str:
    path = designs.template_path(card, name, root=root,
                                 directory=designs.card_path(card['id']) if card else None)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"Cannot read template {path}: {exc}") from exc
    for token, value in values.items():
        text = text.replace(f"__{token}__", value)
    if re.search(r"__[A-Z_]+__", text):
        raise HarnessError(f"Unresolved placeholder in {path}")
    return text


def json_string_content(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def validate_id(value: str, label: str) -> str:
    if not value or value in {".", ".."} or not ID_PATTERN.fullmatch(value):
        raise HarnessError(f"Invalid {label}: {value!r}")
    return value


def title_number(title: str) -> int | None:
    match = NUMBERED_TITLE_PATTERN.match(title)
    return int(match.group(1)) if match else None


def work_id_number(work_id: str, workflow: str) -> int | None:
    suffix = r"(?:-[\w.-]+)?" if workflow == "hyperframes_video" else ""
    match = re.fullmatch(rf"work-{re.escape(workflow)}-(\d{{3,}}){suffix}", work_id)
    return int(match.group(1)) if match else None


def semantic_title(value: str, *, video: bool = False) -> str:
    title = unicodedata.normalize("NFKC", value).strip()
    return title if video else NUMBERED_TITLE_PATTERN.sub(r"\2", title).strip(" -")


def work_slug(title: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", title, flags=re.UNICODE).strip(".-_")[:40].rstrip(".-_")
    return slug or "untitled"


def identity_path(root: Path) -> Path:
    return runtime_root(root) / "work-identity.json"


def identity_state(root: Path) -> dict[str, Any]:
    path = identity_path(root)
    state = read_json(path) if path.is_file() else {}
    if not isinstance(state, dict):
        raise HarnessError(f"Invalid Work identity state: {path}")
    for key in ("series_highwater", "aliases", "series_aliases", "successions"):
        if not isinstance(state.get(key, {}), dict):
            raise HarnessError(f"Invalid Work identity {key}: {path}")
    if not isinstance(state.get("video_highwater", 0), int) or state.get("video_highwater", 0) < 0:
        raise HarnessError(f"Invalid video highwater: {path}")
    if any(not isinstance(value, int) or value < 0 for value in state.get("series_highwater", {}).values()):
        raise HarnessError(f"Invalid series highwater: {path}")
    return {"video_highwater": state.get("video_highwater", 0),
            "series_highwater": state.get("series_highwater", {}),
            "aliases": state.get("aliases", {}),
            "series_aliases": state.get("series_aliases", {}),
            "successions": state.get("successions", {})}


def write_identity(root: Path, state: dict[str, Any]) -> None:
    write_json(identity_path(root), state)


def video_number(root: Path, rows: list[dict[str, Any]], state: dict[str, Any]) -> int:
    observed = [work_id_number(row["id"], "hyperframes_video") or 0 for row in rows
                if row["workflow"] == "hyperframes_video"]
    return max(int(state["video_highwater"]), *observed, 0) + 1


def series_number(root: Path, rows: list[dict[str, Any]], state: dict[str, Any], series: str) -> int:
    observed = [int(row.get("series_number") or 0) for row in rows if row.get("series") == series]
    return max(int(state["series_highwater"].get(series, 0)), *observed, 0) + 1


def work_root_config_path(root: Path) -> Path:
    return root / ".studio" / ".runtime" / "work-root"


def configured_work_root(root: Path) -> Path | None:
    path = work_root_config_path(root)
    if os.environ.get("HYPERFRAMES_AI_WORK_ROOT"):
        value = os.environ["HYPERFRAMES_AI_WORK_ROOT"]
    elif os.environ.get("HYPERFRAMES_AI_CONFIG"):
        path = Path(os.environ["HYPERFRAMES_AI_CONFIG"])
        value = read_json(path).get("work_root", "")
    else:
        if not path.is_file():
            return None
        value = path.read_text(encoding="utf-8").strip()
    candidate = Path(value).expanduser() if value else None
    if candidate is None or not candidate.is_absolute():
        raise HarnessError(f"Invalid WorkStore root in {path}: {value!r}")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise HarnessError(f"Configured WorkStore root is unavailable: {resolved}")
    return resolved


def works_root(root: Path) -> Path:
    return (configured_work_root(root) or root) / "works"


def runtime_root(root: Path) -> Path:
    configured = configured_work_root(root)
    return configured / ".runtime" if configured else root / ".studio" / ".runtime"


def ensure_roots(root: Path) -> None:
    works_root(root).mkdir(parents=True, exist_ok=True)
    runtime_root(root).mkdir(parents=True, exist_ok=True)


def pointer_path(root: Path, name: str) -> Path:
    return runtime_root(root) / name


def read_pointer(root: Path, name: str) -> str | None:
    key = {'current-work': 'work', 'current-variant': 'variant'}[name]
    value = work_context.read(runtime_root(root))[key]
    return validate_id(value, name) if value else None


def write_current(root: Path, work_id: str | None, variant_id: str | None) -> None:
    if work_id is not None:
        validate_id(work_id, 'current-work')
    if variant_id is not None:
        validate_id(variant_id, 'current-variant')
    work_context.write(runtime_root(root), work_id, variant_id)


def write_pointer(root: Path, name: str, value: str) -> None:
    current = work_context.read(runtime_root(root))
    if name == 'current-work':
        write_current(root, value, current['variant'] if current['work'] == value else None)
    else:
        write_current(root, current['work'], value)


def clear_pointer(root: Path, name: str) -> None:
    current = work_context.read(runtime_root(root))
    write_current(root, None if name == 'current-work' else current['work'], None)


def series_folder(root: Path, series: Any) -> Path:
    """Physical home of a Work: works/<series>/, or the unsorted folder without a series."""
    if not isinstance(series, str) or not series:
        return works_root(root) / UNSORTED_SERIES_FOLDER
    validate_id(series, "series")
    if series in RESERVED_SERIES_IDS or series.startswith(("_", ".")):
        raise HarnessError(f"Series identity {series!r} is reserved")
    return works_root(root) / series


def work_paths(root: Path) -> list[tuple[Path, str]]:
    """Every Work directory with its physical container kind: series, or legacy active/parked/archive."""
    base = works_root(root)
    containers: list[tuple[Path, str]] = []
    for child in sorted(base.iterdir()) if base.is_dir() else []:
        if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == "archive":
            containers.extend((month, "archive") for month in sorted(child.iterdir(), reverse=True)
                              if month.is_dir() and not month.is_symlink())
        else:
            containers.append((child, child.name if child.name in LEGACY_WORK_CONTAINERS else "series"))
    paths: list[tuple[Path, str]] = []
    for container, physical in containers:
        for path in sorted(container.iterdir()):
            if (path.is_dir() and not path.name.startswith(".pending-")
                    and (physical != "archive" or (path / "WORK.md").is_file())):
                paths.append((path, physical))
    return paths


def variant_lifecycle(work: Path, state: dict[str, Any]) -> str:
    # Old soft archives have no per-Variant field; keep them archived until reopened.
    return state.get("lifecycle") or ("archived" if (work / ".runtime/archive.json").is_file() else "active")


def ensure_mutable_work(root: Path, work: Path) -> None:
    require_workflow(work, "hyperframes_video")
    if read_frontmatter(work / 'WORK.md').get('retirement'):
        raise HarnessError('Work is retired; historical material remains readable')
    if any(work.name in record["chain"][:-1] for record in identity_state(root)["successions"].values()):
        raise HarnessError("Succession predecessor must remain archived")
    if work.parent.parent.name == "archive" or (work / LEGACY_ARCHIVE_MARKER).is_file():
        raise HarnessError("Legacy physical archive remains read-only; create a new Work for further production")


def sync_work_lifecycle(root: Path, work: Path) -> None:
    variants = variant_paths(work)
    if variants and all(variant_lifecycle(work, read_json(path / "variant.yaml")) == "archived" for path in variants):
        if not (work / ".runtime/archive.json").is_file():
            move_to_archive(root, work, "variants_archived")
    else:
        (work / ".runtime/archive.json").unlink(missing_ok=True)


def materialize_legacy_lifecycle(work: Path) -> None:
    # Persist siblings before removing an old Work-only archive marker.
    for path in variant_paths(work):
        state = read_json(path / "variant.yaml")
        if "lifecycle" not in state:
            state["lifecycle"] = variant_lifecycle(work, state)
            write_variant(path, state)


def work_location(work: Path, physical: str) -> str:
    if (work / ".runtime/archive.json").is_file() or physical == "archive" or (work / LEGACY_ARCHIVE_MARKER).is_file():
        return "archive"
    if (work / ".runtime/parked.json").is_file():
        return "parked"
    # Old parked directories stay at their original path after v3.8 resume.
    if physical == "parked" and not (work / ".runtime/resumed.json").is_file():
        return "parked"
    return "active"


def locate_work(root: Path, work_id: str) -> tuple[Path, str]:
    validate_id(work_id, "work id")
    work_id = identity_state(root)["aliases"].get(work_id, work_id)
    validate_id(work_id, "work id")
    matches = [(path, physical) for path, physical in work_paths(root) if path.name == work_id]
    if len(matches) > 1:
        raise HarnessError(f"Work {work_id} exists in several folders: " + ", ".join(str(path) for path, _ in matches))
    if matches:
        path, physical = matches[0]
        return path, work_location(path, physical)
    raise HarnessError(f"Unknown work: {work_id}")


def physical_container(root: Path, work: Path) -> str:
    base = works_root(root).absolute()
    if work.parent.parent.name == "archive" and work.parent.parent.parent.absolute() == base:
        return "archive"
    if work.parent.name in LEGACY_WORK_CONTAINERS and work.parent.parent.absolute() == base:
        return work.parent.name
    return "series"


def relocation_plan(root: Path, work: Path, series: Any) -> dict[str, Any] | None:
    """Plan moving a Work into works/<series>/; None when it is already there.

    Studio records and cover recipes are read back by absolute path, so they are rewritten;
    a possibly live Studio process blocks the move.
    """
    target = series_folder(root, series) / work.name
    if target.absolute() == work.absolute():
        return None
    if target.exists():
        raise HarnessError(f"Target folder already exists: {target}")
    prefixes = [work.resolve(), (works_root(root) / "active" / work.name).resolve()]
    def moved(value: str) -> str | None:
        prefix = next((p for p in prefixes if Path(value).is_relative_to(p)), None)
        return None if prefix is None else str(target.resolve() / Path(value).relative_to(prefix))
    records = []
    for variant in variant_paths(work):
        state = read_json(variant / "variant.yaml")
        recipe = state.get("cover_recipe")
        if isinstance(recipe, dict):
            # Cover assets outside the Work (asset library) keep their paths.
            refs = {role: moved(ref["path"]) for role, ref in recipe.items()
                    if isinstance(ref, dict) and isinstance(ref.get("path"), str)}
            if any(refs.values()):
                recipe = {**recipe, **{role: {**recipe[role], "path": path} for role, path in refs.items() if path}}
                records.append((variant.relative_to(work).as_posix() + "/variant.yaml", {**state, "cover_recipe": recipe}))
        for path in sorted((variant / ".runtime").glob("studio-*.json")):
            record = read_json(path)
            changed = {}
            for key in ("project", "browser_profile"):
                value = record.get(key)
                if not isinstance(value, str) or not value:
                    continue
                changed[key] = moved(value)
                if changed[key] is None:
                    # Windows-written records (D:\...) are unreadable from WSL; liveness is unknowable there too.
                    raise HarnessError(f"Studio record {path.name} of {work.name}/{variant.name} names a path outside this "
                                       f"Work as seen by this runtime ({value}); run the move from the runtime that wrote it")
            if changed:
                if not record.get("stopped_at") and not storage.process_stopped(record.get("pid")):
                    raise HarnessError(f"Studio for {work.name}/{variant.name} may still be running; "
                                       "run preview studio stop before moving the Work")
                records.append((path.relative_to(work).as_posix(), {**record, **changed}))
    return {"work": work, "target": target, "physical": physical_container(root, work), "rewrites": records}


def apply_relocation(root: Path, plan: dict[str, Any]) -> Path:
    """Idempotent: records and markers are written inside the Work before the single rename."""
    work, target = plan["work"], plan["target"]
    for relative, record in plan["rewrites"]:
        write_json(work / relative, record)
    if plan["physical"] == "archive":
        write_json(work / LEGACY_ARCHIVE_MARKER, {"migrated_from": work.parent.relative_to(works_root(root)).as_posix(),
                                                  "migrated_at": now()})
    elif (plan["physical"] == "parked" and not (work / ".runtime/resumed.json").is_file()
          and not (work / ".runtime/parked.json").is_file()):
        write_json(work / ".runtime/parked.json", {"parked_at": now(), "stable_path": True, "migrated_from": "parked"})
    target.parent.mkdir(parents=True, exist_ok=True)
    work.rename(target)
    return target


LEGACY_WORK_PATH = re.compile(r"works/(?:active|parked|archive/[^/\"'\s]+)/(work-[^/\"'\s]+)")
# Frozen snapshots, caches and evidence keep their recorded paths; only working files are reported.
FROZEN_WORK_PARTS = {"previews", ".runtime", "final", "history", "tts-segments", "covers", "vendor", "exports",
                     "handoff", "node_modules", ".git"}
CONTENT_ADDRESSED_PART = re.compile(r"[0-9a-f]{64}")


def legacy_path_references(work: Path) -> list[dict[str, Any]]:
    """Working text files that still name a pre-layout Work path; reported for the agent, never rewritten."""
    found = []
    for path in sorted(work.rglob("*")):
        relative = path.relative_to(work)
        if (FROZEN_WORK_PARTS.intersection(relative.parts) or any(map(CONTENT_ADDRESSED_PART.fullmatch, relative.parts))
                or path.is_symlink() or not path.is_file()
                or path.suffix.lower() not in {".json", ".md", ".txt", ".yaml", ".yml", ".py", ".html", ".ps1", ".sh", ".cmd"}
                or path.stat().st_size > 2 * 1024 * 1024):
            continue
        try:
            text = path.read_text(encoding="utf-8").replace("\\\\", "/").replace("\\", "/")
        except (OSError, UnicodeDecodeError):
            continue
        names = sorted(set(LEGACY_WORK_PATH.findall(text)))
        if names:
            found.append({"file": relative.as_posix(), "works": names})
    return found


def list_work_rows(root: Path, *, validate_identity: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    def row_for(path: Path, physical: str) -> dict[str, Any]:
        row = {"id": path.name, "title": path.name, "created_at": "", "workflow": "unknown",
               "purpose": "standard", "series": None, "series_number": None,
               "location": work_location(path, physical), "path": str(path), "variants": [],
               "status": None, "wait_for": None, "next_action": None,
               "current": read_pointer(root, "current-work") == path.name,
               "archived_variants": 0, "variant_count": 0,
               "usage": {"bytes": None, "reason": "尚未盘点；运行 work storage inspect"}}
        try:
            if path.is_symlink():
                raise HarnessError("Linked Work is isolated")
            metadata = read_frontmatter(path / "WORK.md")
            row.update({key: metadata[key] for key in ("title", "created_at", "workflow", "purpose", "series", "series_number") if key in metadata})
            require_workflow(path, "hyperframes_video")
            for variant in variant_paths(path):
                if variant.is_symlink():
                    raise HarnessError(f"Linked Variant is isolated: {variant.name}")
                state = read_json(variant / "variant.yaml")
                manifest = variant / "final/manifest.json"
                final = read_json(manifest) if manifest.is_file() else {}
                history = []
                for video in sorted((variant / "final/history").glob("*/final.mp4")):
                    receipt_path = video.parent / "manifest.json"
                    receipt = read_json(receipt_path) if receipt_path.is_file() else {}
                    history.append({"path": str(video), "manifest": str(receipt_path) if receipt else None,
                                    "source_preview": receipt.get("source_preview"),
                                    "provenance": "recorded" if receipt else "unknown"})
                for video in sorted((variant / "final/history").glob("*.mp4")):
                    history.append({"path": str(video), "manifest": None, "source_preview": None, "provenance": "unknown"})
                row["variants"].append({"id": variant.name, "name": state.get("name") or variant.name,
                    "account": state.get("account"), "account_revision": state.get("account_revision"),
                    "ratio": state.get("ratio"), "mode": state.get("mode"),
                    "design": state.get("design") or (state.get("line") or {}).get("id"),
                    "production_supported": ("capabilities" in state or state.get("mode", "explainer") in appearance.MODES),
                    "status": state.get("status"), "wait_for": state.get("wait_for"),
                    "next_action": state.get("next_action"), "lifecycle": variant_lifecycle(path, state),
                    "current": row["current"] and read_pointer(root, "current-variant") == variant.name,
                    "path": str(variant), "project": str(variant / "project"),
                    "final": str(variant / "final/final.mp4") if (variant / "final/final.mp4").is_file() else None,
                    "latest_export": final.get("finalized_at"), "source_preview": final.get("source_preview"),
                    "history": history})
            row["variant_count"] = len(row["variants"])
            row["archived_variants"] = sum(item["lifecycle"] == "archived" for item in row["variants"])
            if len(row["variants"]) == 1:
                row.update({key: row["variants"][0][key] for key in ("status", "wait_for", "next_action")})
            usage = path / ".runtime/storage.json"
            if usage.is_file():
                row["usage"] = read_json(usage)
        except (HarnessError, OSError, ValueError, TypeError) as exc:
            row["error"] = str(exc)
        # Bad metadata is displayed as an isolated row, never fed into sort/number arithmetic.
        for key in ("title", "created_at", "workflow", "purpose"):
            if not isinstance(row[key], str):
                row["error"] = f"Invalid {key} metadata"
                row[key] = path.name if key == "title" else "unknown"
        if row["series"] is not None and not isinstance(row["series"], str):
            row["error"], row["series"] = "Invalid series metadata", None
        if row["series_number"] is not None and type(row["series_number"]) is not int:
            row["error"], row["series_number"] = "Invalid series number metadata", None
        return row
    for path, physical in work_paths(root):
        rows.append(row_for(path, physical))
    counts = Counter(row["id"] for row in rows)
    for row in rows:
        if counts[row["id"]] > 1:
            row["error"] = "Work ID exists in several folders; run work migrate layout"
    if validate_identity:
        work_successor.validate(rows, identity_state(root), SimpleNamespace(**globals()))
    location_order = {"active": 0, "parked": 1, "archive": 2}
    rows.sort(
        key=lambda row: (
            location_order[row["location"]],
            row["workflow"],
            row.get("series") or "",
            row.get("series_number") if isinstance(row.get("series_number"), int) else title_number(row["title"]) or 0,
            row["created_at"],
            row["id"],
        )
    )
    return rows


def selected_work(root: Path, args: argparse.Namespace, *, allow_archive: bool = False) -> tuple[Path, str]:
    work_id = args.work_override or read_pointer(root, "current-work")
    if not work_id:
        available = ", ".join(row["id"] for row in list_work_rows(root)) or "none"
        raise HarnessError(f"No current work. Available: {available}")
    path, location = locate_work(root, work_id)
    require_workflow(path, "hyperframes_video")
    readonly_preview = getattr(args, "preview_command", None) in {"context", "stop", "list", "diff"}
    if location == "archive" and not allow_archive and not readonly_preview:
        raise HarnessError(f"Work is archived; run 'work reopen {work_id}' first")
    return path, location


def variant_paths(work: Path) -> list[Path]:
    variants = work / "variants"
    if not variants.is_dir():
        return []
    return [path for path in sorted(variants.iterdir()) if path.is_dir() and not path.name.startswith(".pending-")]


def selected_variant_id(root: Path, work: Path, args: argparse.Namespace) -> str | None:
    require_workflow(work, "hyperframes_video")
    variant_id = args.variant_override
    if variant_id and not (work / "variants" / validate_id(variant_id, "variant id")).is_dir():
        raise HarnessError(f"Unknown variant: {variant_id}")
    if not variant_id and read_pointer(root, "current-work") == work.name:
        variant_id = read_pointer(root, "current-variant")
    if not variant_id or not (work / "variants" / variant_id).is_dir():
        candidates = variant_paths(work)
        variant_id = candidates[0].name if len(candidates) == 1 else None
    return variant_id


def final_recovery_pending(path: Path) -> bool:
    receipt_path = path / '.runtime/finalize.json'
    return (path / '.runtime/final-promotion/prepared.json').exists() or (
        receipt_path.is_file() and read_json(receipt_path).get('state') == 'promoted')


def selected_variant(root: Path, work: Path, args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    variant_id = selected_variant_id(root, work, args)
    if not variant_id:
        available = ", ".join(path.name for path in variant_paths(work)) or "none"
        raise HarnessError(f"No current variant. Select --variant. Available: {available}")
    validate_id(variant_id, "variant id")
    path = storage.scoped_path(work, f"variants/{variant_id}")
    if not path.is_dir():
        raise HarnessError(f"Unknown variant: {variant_id}")
    if appearance_rebind.journal_path(path).exists() and getattr(args, "appearance_command", None) != "recover":
        raise HarnessError("Appearance recovery pending; run appearance recover with this exact --work and --variant")
    state = read_json(path / "variant.yaml")
    if state.get('design_live'):
        refresh_card_values(state, designs.require(state['design']))
    command = getattr(args, "command", None)
    history_only = command in {None, "status", "storage", "archive", "request"} or (
        command == "preview" and getattr(args, "preview_command", None) in {"context", "stop", "list", "diff"})
    if "capabilities" not in state and state.get("mode", "explainer") not in appearance.MODES and not history_only:
        raise HarnessError("This Variant uses an unsupported production mode; explicitly adopt its content in a new supported Variant")
    readonly = command in {None, "status", "archive", "reopen", "finalize", "storage", "request"} or (
        command == "preview" and (getattr(args, "preview_command", None) in {"context", "stop", "list", "diff"}
                                 or getattr(args, "preview_command", None) == "open" and getattr(args, "preview_id", "current") != "current"))
    if (state.get('retirement') or read_frontmatter(work / 'WORK.md').get('retirement')) and (
            not readonly or command in {'reopen', 'finalize'}):
        raise HarnessError('This item is retired; historical material remains readable')
    if final_recovery_pending(path) and not readonly:
        raise HarnessError("Final recovery pending; run finalize before changing production inputs")
    if not readonly and variant_lifecycle(work, state) == "archived":
        raise HarnessError(f"Variant is archived; run 'work reopen {work.name} --variant-id {path.name}' first")
    return path, state


def focus_work(root: Path, work: Path, args: argparse.Namespace) -> None:
    variant_id = selected_variant_id(root, work, args)
    write_current(root, work.name, variant_id)


def write_variant(path: Path, data: dict[str, Any]) -> None:
    write_json(path / "variant.yaml", data)


def create_video_variant(
    root: Path,
    work: Path,
    variant_id: str,
    *,
    template: str,
    profile: str | None,
    ratio: str,
    subject_position: str | None,
    design: str | None = None,
    copy_script_from: Path | None = None,
) -> Path:
    validate_id(variant_id, "variant id")
    if template not in TEMPLATES:
        raise HarnessError(f"Unknown template: {template}")
    if profile is not None and profile not in PROFILES:
        raise HarnessError(f"Unknown profile: {profile}")
    if ratio not in RATIOS:
        raise HarnessError(f"Unknown ratio: {ratio}")
    if subject_position is not None and subject_position not in SUBJECT_POSITIONS:
        raise HarnessError(f"Unknown subject position: {subject_position}")

    path = work / "variants" / variant_id
    if path.exists():
        raise HarnessError(f"Variant already exists: {variant_id}")
    path.mkdir(parents=True)
    (path / "project").mkdir()

    source_research = copy_script_from.parent / "RESEARCH.md" if copy_script_from else None
    script_revision = read_frontmatter(copy_script_from).get("revision", 1) if copy_script_from else 1
    research_revision = read_frontmatter(source_research).get("revision", 1) if source_research and source_research.is_file() else 1
    values = {
        "VARIANT_ID": json_string_content(variant_id),
        "TEMPLATE": json_string_content(template),
        "PROFILE": json_string_content(profile or ""),
        "RATIO": json_string_content(ratio),
        "SUBJECT_POSITION": json.dumps(subject_position),
        "SCRIPT_REVISION": json.dumps(script_revision),
        "RESEARCH_REVISION": json.dumps(research_revision),
    }
    atomic_write(path / "variant.yaml", template_text(root, "VARIANT.template.yaml", values))
    state = read_json(path / 'variant.yaml')
    if design:
        state['line'] = lines.bind(design)
    write_variant(path, state)
    if copy_script_from:
        shutil.copy2(copy_script_from, path / "SCRIPT.md")
    else:
        atomic_write(path / "SCRIPT.md", template_text(root, "SCRIPT.template.md", {}))
    if source_research and source_research.is_file():
        shutil.copy2(source_research, path / "RESEARCH.md")
    else:
        research_template = designs.capabilities(designs.require(design))["research_template"] if design else "RESEARCH.template.md"
        atomic_write(path / "RESEARCH.md", template_text(root, research_template, values, card={'id': design} if design else None))
    atomic_write(
        path / "ANIMATION_PLAN.md",
        template_text(root, "ANIMATION_PLAN.template.md", values),
    )
    metadata = {**read_frontmatter(path / "ANIMATION_PLAN.md"), **plan_metadata(path, read_json(path / "variant.yaml"))}
    atomic_write(path / "ANIMATION_PLAN.md", "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + plan_metadata_body(document_body(path / "ANIMATION_PLAN.md"), metadata))
    return path


def create_variant(
    root: Path,
    work: Path,
    variant_id: str,
    *,
    workflow: str,
    template: str | None = None,
    profile: str | None = None,
    ratio: str | None = None,
    subject_position: str | None = None,
    design: str | None = None,
    copy_script_from: Path | None = None,
) -> Path:
    if workflow != "hyperframes_video":
        raise HarnessError(f"Unknown workflow: {workflow}")
    return create_video_variant(
        root,
        work,
        variant_id,
        template=template or "pure_hyperframes",
        profile=profile,
        ratio=ratio or "16:9",
        subject_position=subject_position,
        design=design,
        copy_script_from=copy_script_from,
    )


def command_new(root: Path, args: argparse.Namespace) -> None:
    if os.environ.get("HYPERFRAMES_AI_REVIEW") == "1":
        args.purpose = "test"
    if args.workflow == "hyperframes_video" and not args.purpose:
        raise HarnessError("Video Work requires --purpose standard, ip, or test")
    series = "test" if args.purpose == "test" else args.series
    if args.purpose == "test" and args.series not in (None, "test"):
        raise HarnessError("test Work must use the test series")
    if args.workflow == "hyperframes_video" and args.purpose != "test" and not series:
        raise HarnessError("Production video Work requires --series")
    ensure_roots(root)
    with naming_lock(root):
        if series and series != "test":
            series_settings = account_service(root).get("series", series)
            if args.workflow == "hyperframes_video":
                appearance.check_mode(series_settings.get("mode"), "Series")
        create_initial_variant = (args.purpose == "test"
                                  or args.account is not None or getattr(args, "no_account", False)
                                  or getattr(args, 'design', None) is not None or getattr(args, "variant_id", None) is not None)
        if not create_initial_variant and any(getattr(args, key, None) is not None for key in (
            "batch", "theme", "background", "appearance_file", "fps", "seed", "mode", "design", "captions", "template", "profile", "ratio", "subject_position"
        )):
            raise HarnessError("Variant settings require --account; omit them to prepare shared Work content")
        settings = adopted_settings(root, args) if create_initial_variant else {}
        variant_id = validate_id(getattr(args, "variant_id", None) or "variant1", "variant id")
        rows = list_work_rows(root)
        identity = identity_state(root)
        existing_ids = {row["id"] for row in rows}
        number = video_number(root, rows, identity)
        title_text = semantic_title(args.title, video=args.workflow == "hyperframes_video")
        if args.workflow == "hyperframes_video" and (not title_text or any(char in title_text for char in "\r\n")):
            raise HarnessError("Work title must be non-empty on one line")
        if args.workflow == "hyperframes_video" and args.purpose == "test" and not args.separate:
            existing = [row["id"] for row in rows if row["workflow"] == "hyperframes_video"
                        and row["purpose"] == "test" and row["title"] == title_text]
            if existing:
                raise HarnessError("Experiment already exists: " + ", ".join(existing) + "; use --separate for a new comparison")
        assigned_series_number = (series_number(root, rows, identity, series)
                                  if args.workflow == "hyperframes_video" and args.purpose != "test" else None)
        folder = series_folder(root, series)
        folder.mkdir(parents=True, exist_ok=True)
        while True:
            work_id = f"work-{args.workflow}-{number:03d}"
            if args.workflow == "hyperframes_video":
                work_id += f"-{work_slug(title_text)}"
            if work_id not in existing_ids:
                work = folder / work_id
                try:
                    staging = work.with_name(f".pending-{uuid.uuid4().hex}")
                    staging.mkdir()
                    break
                except FileExistsError:
                    pass
            number += 1

        try:
            title = title_text
            atomic_write(staging / "WORK.md", template_text(root, "WORK.template.md", {
                "WORK_ID": json_string_content(work_id), "TITLE": json_string_content(title),
                "CREATED_AT": now(), "WORKFLOW": json_string_content(args.workflow),
            }))
            atomic_write(staging / "source.md", "# Source\n\n")
            (staging / "materials").mkdir()
            options = dict(workflow=args.workflow, template=args.template, profile=args.profile,
                           ratio=settings.get("ratio"), subject_position=args.subject_position,
                           design=settings.get("design"))
            if args.workflow == "hyperframes_video":
                metadata = read_frontmatter(staging / "WORK.md")
                metadata.update(purpose=args.purpose, series=series, series_number=assigned_series_number, shared_source=True,
                                source_work=args.source_work, source_variant=args.source_variant, source_version=args.source_version)
                if series and series != 'test':
                    metadata.update(series_workflow=series_settings.get('workflow', {}),
                                    series_stages=series_settings.get('stages', {}))
                atomic_write(staging / "WORK.md", "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + document_body(staging / "WORK.md"))
                (staging / "shared").mkdir()
                (staging / "variants").mkdir()
                atomic_write(staging / "shared" / "SCRIPT.md", template_text(root, "SCRIPT.template.md", {}))
                research_template = lines.capabilities(settings)["research_template"]
                atomic_write(staging / "shared" / "RESEARCH.md", template_text(root, research_template, {"SCRIPT_REVISION": "1"}, card={'id': settings['design']} if settings.get('design') else None))
                if args.purpose == "test":
                    settings["batch"] = args.batch or variant_id
                if create_initial_variant:
                    create_adopted_variant(root, staging, variant_id, settings, shared=True, **options)
            if args.workflow == "hyperframes_video":
                identity["video_highwater"] = number
                if assigned_series_number is not None:
                    identity["series_highwater"][series] = assigned_series_number
                write_identity(root, identity)
            staging.rename(work)
        except Exception:
            if staging.is_dir():
                shutil.rmtree(staging)
            raise
        if not args.detached:
            write_current(root, work_id, variant_id if create_initial_variant else None)
    print(work_id)


def command_current(root: Path, args: argparse.Namespace) -> None:
    work_id = read_pointer(root, "current-work")
    variant_id = read_pointer(root, "current-variant")
    if not work_id:
        raise HarnessError("No current work")
    work, location = locate_work(root, work_id)
    print(json.dumps({"work": work_id, "variant": variant_id, "location": location, "path": str(work)}, ensure_ascii=False))


def command_list(root: Path, args: argparse.Namespace) -> None:
    ensure_roots(root)
    rows = list_work_rows(root)
    if getattr(args, "archived", False):
        rows = [row for row in rows if row["location"] == "archive"]
    elif not getattr(args, "all", False):
        rows = [row for row in rows if row["location"] != "archive"]
    if args.tree:
        print("\n".join(tree_lines(root, rows)))
    else:
        print_result(root, args, rows)


def display_name(root: Path, row: dict[str, Any]) -> str:
    if row["workflow"] != "hyperframes_video" or row["purpose"] == "test":
        return row["title"]
    if not row["series"] or not row["series_number"]:
        return row["title"]
    try:
        series_name = account_service(root).get("series", row["series"])["name"]
    except HarnessError:
        series_name = row["series"]
    return f"{series_name} {row['series_number']:03d} · {row['title']}"


def experiment_suffix(row: dict[str, Any]) -> str:
    number = work_id_number(row["id"], "hyperframes_video")
    return f"{number:03d}" if number is not None else row["id"][-6:]


def variant_account_label(row: dict[str, Any], variant: dict[str, Any]) -> str:
    if row["workflow"] != "hyperframes_video":
        return variant["account"] or "版本"
    if row["purpose"] == "test":
        return "实验"
    if not variant["account"]:
        return "历史未绑定"
    revision = variant["account_revision"]
    return f"{variant['account']} · r{revision}" if revision is not None else f"{variant['account']} · 历史版本未知"


def tree_lines(root: Path, rows: list[dict[str, Any]]) -> list[str]:
    lines = []
    experiment_names = [row["title"] for row in rows if row["purpose"] == "test"]
    groups = (
        ("生产系列", lambda row: row["workflow"] == "hyperframes_video" and row["purpose"] != "test" and row["location"] != "archive" and not row.get("error")),
        ("临时实验", lambda row: row["workflow"] == "hyperframes_video" and row["purpose"] == "test" and row["location"] != "archive" and not row.get("error")),
        ("历史归档", lambda row: row["workflow"] == "hyperframes_video" and row["location"] == "archive" and not row.get("error")),
        ("隔离对象（已退役或无法读取）", lambda row: row.get("error")),
    )
    for heading, include in groups:
        members = [row for row in rows if include(row)]
        if not members:
            continue
        lines.append(heading)
        if heading in {"生产系列", "历史归档"}:
            members.sort(key=lambda row: (row["series"] or "", row["series_number"] or 0, row["id"]))
        previous_series = None
        for row in members:
            grouped = heading in {"生产系列", "历史归档"}
            if grouped and row["series"] != previous_series:
                try:
                    series_label = account_service(root).get("series", row["series"])["name"]
                except HarnessError:
                    series_label = row["series"] or "未登记系列"
                lines.append(f"  {series_label}")
                previous_series = row["series"]
            indent = "    " if grouped else "  "
            label = f"{row['series_number']:03d} · {row['title']}" if row["series_number"] else row["title"]
            if row["purpose"] == "test" and experiment_names.count(row["title"]) > 1:
                label += f" · {experiment_suffix(row)}"
            if row["location"] == "parked":
                label += " (停放)"
            focus = " ★" if row["current"] else ""
            lines.append(f"{indent}{label}{focus} [{row['id']}] {row['archived_variants']}/{row['variant_count']} 已归档 · {row['path']}")
            if row.get("error"):
                lines.append(f"{indent}  隔离：{row['error']}")
            usage = row["usage"]
            lines.append(f"{indent}  占用：{usage.get('bytes')} bytes（盘点记录）" if usage.get("bytes") is not None
                         else f"{indent}  占用未知：{usage.get('reason', '盘点不可用')}")
            for variant in row["variants"]:
                lines.append(f"{indent}  {variant_account_label(row, variant)} · {variant['name']} "
                             f"[{variant['id']}] {'★ ' if variant['current'] else ''}{variant['ratio']} · {variant['lifecycle']} · {variant['status'] or 'unknown'}/{variant['wait_for']} · 最近导出 {variant['latest_export'] or '未导出'}")
                lines.append(f"{indent}    工程：{variant['project']}")
                if variant['final']:
                    lines.append(f"{indent}    成片：{variant['final']}")
                for item in variant['history']:
                    lines.append(f"{indent}    历史：{item['path']} · {item['source_preview'] or '历史来源未知'}")
    return lines


def refresh_browser(root: Path) -> None:
    store = works_root(root).parent
    rows = list_work_rows(root)
    output = ["# 浏览目录", "", "★ 当前焦点；容量为按需盘点记录，非实时扫描。每个系列对应 works/<系列ID>/ 文件夹，系列规则是其中的 AGENTS.md。", ""]
    def link(label: str, path: str | Path) -> str:
        relative = Path(path).relative_to(store).as_posix()
        return "[" + label.replace("[", "\\[").replace("]", "\\]").replace("\n", " ") + "](" + quote(relative, safe="/") + ")"
    def series_label(series: Any) -> str:
        if series == "test":
            return "临时实验"
        if not series:
            return "未归系列"
        try:
            return account_service(root).get("series", series)["name"]
        except HarnessError:
            return series
    states = {"active": "制作中", "parked": "停放", "archive": "已归档"}
    order = {"active": 0, "parked": 1, "archive": 2}
    healthy = [row for row in rows if not row.get("error")]
    for series in sorted({row["series"] for row in healthy}, key=lambda value: (value in (None, "test"), value == "test", value or "")):
        members = sorted((row for row in healthy if row["series"] == series),
                         key=lambda row: (order[row["location"]], row["series_number"] or 0, row["created_at"], row["id"]))
        try:
            folder = series_folder(root, series)
        except HarnessError:
            folder = None
        heading = f"## {series_label(series)}"
        if folder is not None and folder.is_dir():
            heading += " · " + link("文件夹", folder)
        if folder is not None and (folder / "AGENTS.md").is_file():
            heading += " · " + link("系列规则", folder / "AGENTS.md")
        output.extend([heading, ""])
        for row in members:
            label = display_name(root, row)
            if row["purpose"] == "test" and sum(r["purpose"] == "test" and r["title"] == row["title"] for r in rows) > 1:
                label += f" · {experiment_suffix(row)}"
            focus = " ★" if row["current"] else ""
            usage = row["usage"]
            capacity = f"{usage['bytes']} bytes（盘点记录）" if usage.get("bytes") is not None else f"占用未知：{usage.get('reason') or '盘点不可用'}"
            output.append(f"- {link(label, row['path'])}{focus} · {states[row['location']]} · {row['archived_variants']}/{row['variant_count']} 已归档 · {capacity}")
            if not row["variants"]:
                output.append("  - 尚未创建制作版本")
            for variant in row["variants"]:
                label = f"{variant_account_label(row, variant)} · {variant['name']} · {variant['ratio']}" + (" ★" if variant["current"] else "")
                output.append(f"  - {link(label, variant['path'])} · {variant['lifecycle']} · {variant['status']}/{variant['wait_for']} · 最近导出 {variant['latest_export'] or '未导出'}")
                output.append("    - " + link("工程", variant["project"]))
                if variant["final"]:
                    output.append("    - " + link("最新成片", variant["final"]))
                for history in variant["history"]:
                    output.append("    - " + link(history["source_preview"] or "历史来源未知", history["path"]))
        output.append("")
    isolated = [row for row in rows if row.get("error")]
    if isolated:
        output.extend(["## 隔离对象", ""])
        for row in isolated:
            output.append(f"- {link(row['title'], row['path'])} · 隔离：{row['error']}")
        output.append("")
    atomic_write(store / "浏览目录.md", "\n".join(output))


def command_storage(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    candidates, errors = [], []
    for variant in variant_paths(work):
        try:
            names = reclaim_final_candidates(variant, apply=False)
            candidates.extend({"variant": variant.name, "path": str(variant / ".runtime" / name),
                               "bytes": (variant / ".runtime" / name).stat().st_size} for name in names)
        except (HarnessError, storage.StorageError, OSError) as exc:
            errors.append(str(exc))
    removed = []
    if args.storage_command == "cleanup" and args.apply:
        # Revalidate under the same WorkStore lock immediately before each deletion.
        for variant in variant_paths(work):
            try:
                removed.extend(str(variant / ".runtime" / name) for name in reclaim_final_candidates(variant))
            except (HarnessError, storage.StorageError, OSError) as exc:
                errors.append(str(exc))
    usage = work_storage.measure(work)
    usage.update(measured_at=now(), reclaimable_bytes=sum(item["bytes"] for item in candidates) if not errors else None,
                 reclaimable=candidates, cleanup_errors=errors, removed=removed)
    write_json(work / ".runtime/storage.json", usage)
    print_result(root, args, usage)


def command_browser_rebuild(root: Path, args: argparse.Namespace) -> None:
    refresh_browser(root)
    print(str(works_root(root).parent / "浏览目录.md"))


def command_migrate_layout(root: Path, args: argparse.Namespace) -> None:
    """Idempotent move to works/<series>/<Work>/; only empty legacy containers are removed."""
    with naming_lock(root):
        plans, works, errors, references = [], [], [], []
        for path, _ in work_paths(root):
            found = legacy_path_references(path)
            if found:
                others = sorted({name for item in found for name in item["works"]} - {path.name})
                references.append({"work": path.name, "files": [item["file"] for item in found], "other_works": others})
            try:
                plan = relocation_plan(root, path, read_frontmatter(path / "WORK.md").get("series"))
            except (HarnessError, OSError, ValueError) as error:
                errors.append({"work": path.name, "path": str(path), "error": str(error)})
                continue
            if plan:
                plans.append(plan)
                works.append({"work": path.name, "from": str(path), "to": str(plan["target"]),
                              "rewritten_files": [name for name, _ in plan["rewrites"]], "legacy_container": plan["physical"]})
        service, rules = account_service(root), []
        for config in sorted((runtime_root(root) / "control-plane" / "series").glob("*.json")):
            try:
                path, _, legacy = service.rules_paths(config.stem)
                if legacy.is_file():
                    if path.exists():
                        raise HarnessError(f"Series rules exist in both {legacy} and {path}; keep one")
                    rules.append({"series": config.stem, "from": str(legacy), "to": str(path)})
            except (HarnessError, OSError, ValueError) as error:
                errors.append({"series": config.stem, "error": str(error)})
        targets = Counter(item["to"] for item in works)
        errors += [{"path": target, "error": "Several Works would move to the same folder"} for target, count in targets.items() if count > 1]
        # Stale absolute paths in working files do not block the move; agents fix them when next used.
        report = {"applied": False, "works": works, "rules": rules, "errors": errors, "stale_path_references": references}
        if args.apply:
            if errors:
                raise HarnessError("Layout migration has errors; resolve them first: " + json.dumps(errors, ensure_ascii=False))
            for plan in plans:
                apply_relocation(root, plan)
            for item in rules:
                service.adopt_legacy_rules(item["series"])
            base = works_root(root)
            for container in [*(base / "archive").glob("*"), *(base / name for name in LEGACY_WORK_CONTAINERS)]:
                if container.is_dir() and not container.is_symlink() and not any(container.iterdir()):
                    container.rmdir()
            report["applied"] = True
    if args.apply:
        refresh_browser(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def command_migrate(root: Path, args: argparse.Namespace) -> None:
    api = sys.modules.get(__name__) or SimpleNamespace(**globals())
    if args.migrate_command == "dry-run":
        def overrides(path: str | None) -> dict[str, str]:
            if not path:
                return {}
            value = read_json(Path(path))
            if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str)
                                                      for key, item in value.items()):
                raise HarnessError(f"Migration overrides must be a JSON string map: {path}")
            return value

        plan = work_migration.build_plan(root, api,
                                         title_overrides=overrides(args.title_overrides),
                                         purpose_overrides=overrides(args.purpose_overrides),
                                         only_ids=args.only or None)
        content = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            output = Path(args.output).expanduser()
            if output.is_symlink() or output.resolve().is_relative_to(works_root(root).parent.resolve()):
                raise HarnessError("Migration mapping output must be a new file outside WorkStore")
            try:
                with output.open("x", encoding="utf-8") as handle:
                    handle.write(content)
            except OSError as exc:
                raise HarnessError(f"Cannot create migration mapping {output}: {exc}") from exc
        else:
            print(content, end="")
    else:
        plan = read_json(Path(args.mapping))
        result = work_migration.apply_plan(root, plan, api)
        args.migration_applied = result["applied"]
        print(json.dumps(result, ensure_ascii=False))


def command_find(root: Path, args: argparse.Namespace) -> None:
    rows, identity = list_work_rows(root), identity_state(root)
    key = work_successor.series_key(args.series, args.number)
    row = work_successor.current(rows, identity, key, SimpleNamespace(**globals()))
    chain = identity["successions"].get(key)
    if getattr(args, "history", False):
        ids = chain["chain"] if chain else [row["id"]] if row else []
        if not ids:
            raise HarnessError("No Work for this series number")
        by_id = {item["id"]: item for item in rows}
        print(json.dumps([{"work": work_id, "location": by_id.get(work_id, {}).get("location", "missing"),
                           "current": bool(row and row["id"] == work_id),
                           "successor": ids[index + 1] if index + 1 < len(ids) else None,
                           "request": chain["requests"].get(work_id) if chain else None}
                          for index, work_id in enumerate(ids)], ensure_ascii=False, indent=2))
        return
    if row is None:
        raise HarnessError("No current Work for this series number; historical number remains occupied")
    matches = [row]
    moved_from = ({"series": args.series, "series_number": args.number}
                  if row["series"] != args.series or row["series_number"] != args.number else None)
    result = []
    for row in matches:
        variants = [variant for variant in row["variants"] if not args.account or variant["account"] == args.account]
        result.extend({"work": row["id"], "series": row["series"], "series_number": row["series_number"],
                       "location": row["location"], "moved_from": moved_from, "variant": variant} for variant in variants)
        if not row["variants"] and not args.account:
            result.append({"work": row["id"], "series": row["series"], "series_number": row["series_number"],
                           "location": row["location"], "moved_from": moved_from, "variant": None})
    if not result:
        raise HarnessError("No Variant for this account and series number")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_successor(root: Path, args: argparse.Namespace) -> None:
    work_successor.command(root, args, SimpleNamespace(**globals()))


def command_series_move(root: Path, args: argparse.Namespace) -> None:
    account_service(root).get("series", args.identity)
    with naming_lock(root):
        work, _ = selected_work(root, args, allow_archive=True)
        if any(work.name in record["chain"][:-1] for record in identity_state(root)["successions"].values()):
            raise HarnessError("Succession predecessor must remain archived and read-only")
        metadata_path = work / "WORK.md"
        metadata = read_frontmatter(metadata_path)
        if metadata.get("workflow") != "hyperframes_video" or metadata.get("purpose", "standard") == "test":
            raise HarnessError("Only production video Works can move between series")
        old_series, old_number = metadata.get("series"), metadata.get("series_number")
        plan = relocation_plan(root, work, args.identity)
        if old_series == args.identity:
            # Re-running finishes an interrupted move; the folder follows the recorded series.
            path = apply_relocation(root, plan) if plan else work
            print(json.dumps({"work": work.name, "series": old_series, "series_number": old_number, "path": str(path)}, ensure_ascii=False))
            return
        rows, identity = list_work_rows(root), identity_state(root)
        new_number = series_number(root, rows, identity, args.identity)
        if old_series and old_number:
            key = f"{old_series}:{old_number}"
            if key in identity["series_aliases"] and identity["series_aliases"][key] != work.name:
                raise HarnessError("Historical series number already points to another Work")
            identity["series_aliases"][key] = work.name
        metadata.update(series=args.identity, series_number=new_number)
        identity["series_highwater"][args.identity] = new_number
        write_identity(root, identity)
        atomic_write(metadata_path, "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + document_body(metadata_path))
        path = apply_relocation(root, plan) if plan else work
    print(json.dumps({"work": work.name, "series": args.identity, "series_number": new_number, "path": str(path)}, ensure_ascii=False))


def command_variant_name(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    name = checked_variant_name(args.name)
    state["name"] = name
    write_variant(variant, state)
    print(name)


def checked_variant_name(value: str) -> str:
    name = unicodedata.normalize("NFKC", value).strip()
    if not name or any(char in name for char in "\r\n") or len(name) > 40:
        raise HarnessError("Variant name must contain 1-40 characters on one line")
    return name


def command_root_show(root: Path, args: argparse.Namespace) -> None:
    configured = configured_work_root(root)
    active = configured or root
    print(
        json.dumps(
            {
                "configured": configured is not None,
                "work_root": str(active),
                "works": str(active / "works"),
                "runtime": str(runtime_root(root)),
            },
            ensure_ascii=False,
        )
    )


def command_root_set(root: Path, args: argparse.Namespace) -> None:
    default_config = os.environ.get("HYPERFRAMES_AI_DEFAULT_CONFIG")
    if os.environ.get("HYPERFRAMES_AI_REVIEW") == "1":
        raise HarnessError("Review cannot change production defaults")
    if os.environ.get("HYPERFRAMES_AI_WORK_ROOT") and not default_config:
        raise HarnessError("An explicit environment WorkRoot cannot change persistent configuration")
    target = Path(args.path).expanduser()
    if not target.is_absolute() or target.is_symlink():
        raise HarnessError("WorkStore root must be an existing absolute directory, not a symlink")
    target = target.resolve()
    required = [target / "works"]
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise HarnessError("WorkStore root is missing required directories: " + ", ".join(missing))
    try:
        (target / ".runtime").mkdir(exist_ok=True)
    except OSError as exc:
        raise HarnessError(f"WorkStore runtime directory is unavailable: {exc}") from exc
    if default_config or os.environ.get("HYPERFRAMES_AI_CONFIG"):
        config_path = Path(default_config or os.environ["HYPERFRAMES_AI_CONFIG"])
        config = read_json(config_path) if config_path.is_file() else {}
        config["work_root"] = str(target)
        write_json(config_path, config)
    else:
        atomic_write(work_root_config_path(root), str(target) + "\n")
    if default_config:
        print(json.dumps({"work_root": str(target), "scope": "next-command"}))
    else:
        command_root_show(root, args)


def command_name(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    new_title = semantic_title(args.title, video=work_workflow(work) == "hyperframes_video")
    if not new_title or any(char in new_title for char in "\r\n") or len(new_title) > 40:
        raise HarnessError("Work name must contain 1-40 characters on one line")

    ensure_roots(root)
    with naming_lock(root):
        metadata_path = work / "WORK.md"
        metadata = read_frontmatter(metadata_path)
        title = new_title

        lines = metadata_path.read_text(encoding="utf-8").splitlines()
        frontmatter_end = lines.index("---", 1)
        metadata["title"] = title
        body = lines[frontmatter_end + 1 :]
        for index, line in enumerate(body):
            if line.startswith("# "):
                body[index] = f"# {title}"
                break
        atomic_write(
            metadata_path,
            "---\n"
            + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            + "\n---\n"
            + "\n".join(body)
            + "\n",
        )
    print(title)


def command_use(root: Path, args: argparse.Namespace) -> None:
    work, location = locate_work(root, args.work_id)
    if location == "archive":
        raise HarnessError(f"Work is archived; run 'work reopen {args.work_id}' first")
    focus_work(root, work, args)
    print(work.name)


def card_change_report(state):
    import design_snapshot
    receipt = state.get('design_draft_files')
    if not receipt:
        return None
    try:
        result = design_snapshot.changes(receipt)
        return result if result['message'] else None
    except (ValueError, OSError) as error:
        return {'message': '无法比较当前卡片：' + str(error)}


def refresh_card_values(state, card):
    values = designs.layer_values(card['defaults'], 'Design')
    sources = {key: 'design' for key in values}
    for key, source in state.get('design_sources', {}).items():
        if source != 'design':
            if key not in card['fields']:
                raise HarnessError('Updated card no longer supports override: ' + key)
            values[key] = state['design_values'][key]
            sources[key] = source
    state.update(design_values=values, design_sources=sources)
    if "capabilities" in state:
        state["capabilities"] = designs.capabilities(card)


def adopt_card_files(state, receipt):
    card = receipt['design']
    refresh_card_values(state, card)
    state.update(design_snapshot=card, design_sha256=lines.card_digest(card),
                 design_files=receipt, design_live=False,
                 line={key: card[key] for key in ('id', 'version')}, design_version=card['version'])


def command_variant_design_update(root, args):
    import design_snapshot
    work, _ = selected_work(root, args)
    variant, state = selected_variant(root, work, args)
    ensure_mutable_work(root, work)
    if not state.get('design_files'):
        raise HarnessError('This Variant has no v4.2 Draft card snapshot; legacy snapshots remain unchanged')
    changes = design_snapshot.changes(state['design_files'])
    receipt = design_snapshot.freeze(variant, state['design'])
    adopt_card_files(state, receipt)
    write_variant(variant, state)
    preview_args = build_parser().parse_args(['--work', work.name, '--variant', variant.name, 'preview', 'open', 'current'])
    preview = command_preview_open(root, preview_args, emit=False)
    print_result(root, args, {**changes, 'variant': variant.name,
                             'preview': preview,
                             'project_assets': 'preserved; reinstall listed assets explicitly'})


def command_status(root: Path, args: argparse.Namespace) -> None:
    work, location = selected_work(root, args, allow_archive=True)
    variant_id = selected_variant_id(root, work, args)
    variant, state = selected_variant(root, work, args) if variant_id else (None, None)
    output = {
        "work": read_frontmatter(work / "WORK.md"),
        "location": location,
        "path": str(work),
        "variant": ({**state, "lifecycle": variant_lifecycle(work, state)} if state else None),
        "variant_path": str(variant) if variant else None,
        "variants": [path.name for path in variant_paths(work)],
        "summary": next(row for row in list_work_rows(root) if row["id"] == work.name),
        "message": "尚未创建制作版本" if not variant_paths(work) else None,
    }
    rules = series_rules_reference(root, output["work"].get("series"))
    if rules:
        output["series_rules"] = rules
    change = card_change_report(state or {})
    if change:
        output['design_changes'] = change
    print_result(root, args, output)


def print_result(root: Path, args: argparse.Namespace, result, *, report=False) -> None:
    """Keep machine output exact; persist large human output outside Work content."""
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if getattr(args, 'json', False) or (not report and len(encoded) <= 2000):
        print(encoded)
        return
    path = runtime_root(root) / 'reports' / f'{args.command}-{uuid.uuid4().hex}.json'
    write_json(path, result)

    def brief(value, depth=0):
        if isinstance(value, list):
            return {'count': len(value), 'first': [brief(item, depth + 1) for item in value[:3]]}
        if isinstance(value, dict):
            if depth >= 2:
                return {key: item for key, item in value.items()
                        if key in {'kind', 'reason', 'scene', 'time', 'start', 'end', 'target', 'ref', 'component_ref', 'path',
                                   'asset_layer', 'lifecycle', 'recommendation', 'available', 'purpose', 'communication_goal', 'use'}}
            return {key: brief(item, depth + 1) for key, item in value.items()
                    if key not in {'samples', 'timeline', 'input_sha256', 'snapshot_sha256'}}
        return value[:240] + '...' if isinstance(value, str) and len(value) > 240 else value

    print(json.dumps({'summary': brief(result), 'report_path': str(path)}, ensure_ascii=False, indent=2))


def command_design(root, args):
    operation = args.design_command
    if operation == 'source-add':
        import design_sources
        result = design_sources.source_add(args.url, args.commit, root=root)
    elif operation == 'new':
        result = {'path': str(designs.new(args.id, from_card=args.from_card, kind=args.type, root=root))}
    elif operation == 'validate':
        result = designs.validate(args.id, root=root)
        print_result(root, args, result)
        if not result['ok']:
            raise HarnessError('Design validation failed')
        return
    elif operation == 'localize':
        result = designs.localize(args.id, args.reference, root=root)
    elif operation == 'compare':
        if getattr(args, 'since', None):
            if args.asset or args.commit:
                raise HarnessError('--since cannot combine with an asset or --commit')
            result = designs.compare_since(args.id, args.since, root=root)
        else:
            result = designs.compare(args.id, args.asset, root=root, commit=args.commit)
    elif operation == 'root':
        result = designs.root_report(root=root)
    elif operation == 'preview':
        import design_examples
        import tempfile
        designs.require(args.id, root=root)
        result = designs.validate(args.id, root=root)
        if not result['ok']:
            print_result(root, args, result)
            raise HarnessError('Fix design validation before preview')
        output = Path(args.output).absolute() if args.output else runtime_root(root) / 'design-previews' / args.id / uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='design-preview-') as temporary:
            project = design_examples.build(args.id, Path(temporary) / 'project', repo=root)
            subprocess.run([os.environ.get('HYPERFRAMES_NODE', 'node'),
                            str(Path(__file__).with_name('design_preview.mjs')), str(project), str(output)], check=True)
        result = {'design': args.id, 'evidence': str(output), 'checks': ['cold', 'repeat', 'backward']}
    else:
        result = []
        cards, problems = designs.catalog_report(root=root)
        for identity, card in cards.items():
            directory = designs.card_path(identity, root=root)
            borrowed = designs._read_borrowed(directory)
            assets = [{'id': identity + '/' + path.name,
                       'state': 'localized' if path.name in borrowed else 'owned'}
                      for path in sorted((directory / 'assets').glob('*')) if (path / 'asset.json').is_file()]
            assets += [{'id': ref, 'state': 'reference'} for ref in card.get('references', [])]
            result.append({'id': identity, 'version': card['version'], 'type': card['type'],
                           'origin': 'builtin' if directory.parent == designs.builtin_root(root) else 'user',
                           'path': str(directory), 'assets': assets})
        # Unavailable cards stay visible with their reason instead of hiding the whole catalog.
        result.extend({'id': item['card'], 'path': item['path'], 'error': item['error']} for item in problems)
    print_result(root, args, result)


def command_component_trace(root: Path, args: argparse.Namespace) -> None:
    """Report sources and frozen copies separately; reads only, never repairs or rebinds."""
    import asset_trace
    if not (args.design or args.account or args.work_override):
        raise HarnessError('Select --design, --account and/or --work [--variant] to trace')
    result = {'scope': 'read-only; source availability and frozen Work copies are reported separately'}
    try:
        if args.design:
            result['design'] = asset_trace.design_report(root, args.design)
        if args.account:
            account = account_service(root).get('account', args.account)
            result['account'] = asset_trace.account_report(root, args.account, account, args.design)
        if args.work_override:
            work, location = locate_work(root, args.work_override)
            require_workflow(work, 'hyperframes_video')
            variants = ([storage.scoped_path(work, 'variants/' + validate_id(args.variant_override, 'variant id'))]
                        if args.variant_override else variant_paths(work))
            if any(not path.is_dir() for path in variants):
                raise HarnessError(f'Unknown variant: {args.variant_override}')
            result['work'] = {'work': work.name, 'location': location,
                              'variants': [asset_trace.variant_report(root, path) for path in variants]}
    except (ComponentError, designs.DesignError) as error:
        raise HarnessError(str(error)) from error
    print_result(root, args, result)


def command_component_retired(root, args):
    raise HarnessError('v4.2 起资产位于设计卡内；使用 design 与 component list/interface/install/verify')


def command_component_validate(root: Path, args: argparse.Namespace) -> None:
    if args.candidate:
        source = Path(args.component).expanduser()
        if not source.is_absolute():
            source = root / source
        acceptance = None
    else:
        source, acceptance = asset_store.resolve_component(root, args.component)
    if "@" not in args.component and (source / 'asset.json').is_file():
        from asset_contract import validate_card_asset
        print_result(root, args, validate_card_asset(source))
        return
    release = validate_component_release(source, allow_unapproved=args.candidate or acceptance is not None)
    print_result(root, args, {key: release.get(key) for key in ("component_ref", "ratio", "profile", "subtemplate", "package_sha256", "files")})


def command_component_interface(root: Path, args: argparse.Namespace) -> None:
    card = asset_store.component_interface(root, args.component, candidate=args.candidate)
    if not getattr(args, 'json', False):
        card['interface'] = dict(card['interface'])
        for key in ('usage', 'example'):
            value = card['interface'].get(key)
            if isinstance(value, str) and len(value) > 1200:
                card['interface'][key] = value[:1200] + '\n[truncated; use full_result]'
                card['full_result'] = [*card['detail']['argv'], '--json']
    print(json.dumps(card, ensure_ascii=False, indent=2))


def print_asset_list(args: argparse.Namespace, result: dict) -> None:
    if getattr(args, 'json', False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    fields = ('component_ref', 'source_ref', 'asset_type', 'status', 'lifecycle', 'asset_layer', 'ratio', 'ratios',
              'ratio_source', 'purpose', 'communication_goal', 'path', 'source_directory', 'entry',
              'installable', 'usable_by', 'check_scope', 'conflict', 'detail', 'next_step')
    rows = [{key: row[key] for key in fields if key in row} for row in result['assets'][:20]]
    for row in rows:
        for key in ('purpose', 'communication_goal'):
            value = row.get(key)
            if isinstance(value, str) and len(value) > 160:
                row[key] = value[:160] + '…'
    full = ['component', 'list']
    for key in ('query', 'kind', 'ratio', 'tag', 'design', 'broll_role', 'recommendation', 'asset_layer', 'research_root'):
        value = getattr(args, key, None)
        if value:
            full.extend(['--' + key.replace('_', '-'), str(value)])
    for key in ('include_references', 'audit', 'rebuild'):
        if getattr(args, key, False):
            full.append('--' + key.replace('_', '-'))
    output = {'assets': rows, 'total': len(result['assets']), 'shown': len(rows),
              'truncated': len(rows) < len(result['assets']), 'full_result': [*full, '--json'],
              'filters': result['filters']}
    for key in ('errors', 'warnings', 'conflicts'):
        output[key] = result.get(key, [])[:20]
        output[key + '_total'] = len(result.get(key, []))
    if result.get('message'):
        output['message'] = result['message']
    if 'research' in result:
        output['research_total'] = len(result['research'])
    print(json.dumps(output, ensure_ascii=False, indent=2))


def command_icons(root: Path, args: argparse.Namespace) -> None:
    if args.icon_command == 'import':
        result = icon_sets.import_lucide(Path(args.package), Path(args.source), asset_version=args.asset_version)
    elif args.icon_command == 'search':
        inventory = asset_store.discover_components(root, kind='icon-set')
        packages = [asset_store.resolve_component(root, item['component_ref'])[0]
                    for item in inventory['assets'] if item['available']]
        if not packages:
            raise HarnessError('No card icon set found; import icons into a card assets directory')
        result = icon_sets.search_icons(packages, args.query)
    else:
        if args.project:
            project = asset_store.authoring_project(root, Path(args.project))
        else:
            if not args.work_override or not args.variant_override:
                raise HarnessError('Icon use requires explicit --work/--variant or --project')
            work, _ = selected_work(root, args)
            require_workflow(work, 'hyperframes_video')
            variant, _ = selected_variant(root, work, args)
            project = variant / 'project'
        result = icon_sets.use_icon(icon_sets.project_packages(project), args.reference,
                                    project, args.output)
    print_result(root, args, result)


def command_math_source(root: Path, args: argparse.Namespace) -> None:
    from math_kit_assets import export_math_kit
    print_result(root, args, export_math_kit(root, Path(args.target)))


def command_math(root: Path, args: argparse.Namespace) -> None:
    from component_harness import package_write_lock
    variant = None
    if args.project:
        project = asset_store.authoring_project(root, Path(args.project))
        if not args.plan:
            raise HarnessError('Standalone math requires --plan within the registered AssetSource')
        plan_path = Path(args.plan).expanduser().absolute()
        asset_store.authoring_project(root, plan_path.parent)
        storage.scoped_path(plan_path.parent, plan_path.name)
    else:
        if not args.work_override or not args.variant_override or args.plan:
            raise HarnessError('Math requires explicit --work/--variant, or --project/--plan')
        work, _ = selected_work(root, args)
        require_workflow(work, 'hyperframes_video')
        variant, _ = selected_variant(root, work, args)
        project = variant / 'project'
        plan_path = storage.scoped_path(variant, 'ANIMATION_PLAN.md')
    with package_write_lock(work_requests.safe(project.parent, '.runtime/component-install.lock')):
        plan_bytes = plan_path.read_bytes()
        plan = plan_bytes.decode('utf-8')
        plan_scene_rows(plan)
        metadata = read_frontmatter(plan_path)
        state_bytes = (variant / 'variant.yaml').read_bytes() if variant else None
        state = json.loads(state_bytes) if state_bytes is not None else metadata
        if variant and args.purpose == 'plan':
            assert_preview_ready(variant, state, purpose='plan', kind='reference')
        elif metadata.get('status') != 'approved' and (not variant or plan_confirmation(root, variant, state)):
            raise HarnessError('ANIMATION_PLAN.md must be approved before math build')
        lock = state.get('appearance_lock') if variant else read_json(project / 'appearance-lock.json')
        if (not lock or not lines.is_math(state)
                or metadata.get('series_binding') != state.get('series_binding')):
            raise HarnessError('Math build requires a frozen mathematics binding')
        appearance.verify(project, lock, check_mounts=False)
        expected = {plan_path: plan_bytes}
        if variant:
            expected[variant / 'variant.yaml'] = state_bytes
        result = math_build.build(project, plan, root, lock['ratio'], browser=args.browser,
                                  expected_before=expected, scene_ids=args.scene)
    print_result(root, args, result)


def command_component_store(root: Path, args: argparse.Namespace) -> None:
    action = args.component_command
    if action == "root":
        result = asset_store.configure_asset_store(root, Path(args.path)) if args.path else {"asset_root": str(asset_store.asset_store_root(root))}
    elif action == "list":
        result = asset_store.discover_components(root, args.query, kind=args.kind, ratio=args.ratio, tag=args.tag,
            recommendation=args.recommendation, rebuild=args.rebuild, research_root=args.research_root, audit=args.audit,
            asset_layer=args.asset_layer, include_references=args.include_references, broll_role=args.broll_role,
            design=args.design)
        print_asset_list(args, result)
        return
    else:
        store = asset_store.asset_store_root(root)
        from component_harness import package_write_lock
        # ponytail: one short store-write lock; split by asset only if contention matters.
        with package_write_lock(asset_store._target(store, ".asset-write.lock")):
            if action == "source-add":
                result = asset_store.register_source(store, Path(args.path))
            elif action == "import":
                result = asset_store.import_component(store, Path(args.path))
            elif action == "pack":
                result = asset_store.pack_source(store, Path(args.path))
            else:
                result = asset_store.accept_component(store, args.component_ref, args.sha256, args.note, runtime_root=root)
        try:
            discovery = asset_store.discover_components(root)
            result = {**result, "discovery_sync": {"synchronized": not discovery["errors"], "errors": discovery["errors"]}}
        except (ComponentError, OSError, ValueError) as exc:
            result = {**result, "discovery_sync": {"synchronized": False, "error": str(exc)}}
    print_result(root, args, result)


def command_asset_maintenance(root: Path, args: argparse.Namespace) -> None:
    import asset_maintenance as maintenance
    if args.maintenance_action == 'apply':
        plan = read_json(maintenance.absolute(args.plan))
        operation = maintenance.migrate_apply if args.component_command == 'migrate' else maintenance.archive_apply
        result = operation(plan)
    else:
        if args.component_command == 'migrate':
            classifications = read_json(Path(args.classification)) if args.classification else {}
            plan = maintenance.migrate_plan(args.source, args.target, classifications)
        else:
            plan = maintenance.archive_plan(args.target, args.item)
        result = maintenance.save_plan(args.output, plan)
    print_result(root, args, result)


def command_component_install(root: Path, args: argparse.Namespace) -> None:
    if args.project:
        project = asset_store.authoring_project(root, Path(args.project))
    else:
        work, _ = selected_work(root, args)
        require_workflow(work, "hyperframes_video")
        variant, state = selected_variant(root, work, args)
        plan_path = variant / "ANIMATION_PLAN.md"
        plan = read_frontmatter(plan_path)
        if args.purpose == "plan":
            assert_preview_ready(variant, state, purpose="plan", kind="reference")
        elif plan.get("status") != "approved" and plan_confirmation(root, variant, state):
            raise HarnessError("ANIMATION_PLAN.md must be approved before Component installation")
        plan_scene_rows(plan_path.read_text(encoding="utf-8"))
        if not animation_plan_contains_component_ref(plan_path, args.component_ref):
            raise HarnessError(f"ANIMATION_PLAN.md does not approve Component {args.component_ref}")
        project = variant / "project"
    card_ref = args.component_ref if "@" not in args.component_ref else None
    if card_ref:
        from asset_contract import validate_card_asset_reference
        owner, _ = validate_card_asset_reference(card_ref)
        if not args.project:
            card = lines.frozen(state)
            if owner != card["id"] and card_ref not in card.get("references", []):
                raise HarnessError("Declare this asset in the selected card references before installing")
    source, acceptance = asset_store.resolve_component(root, args.source or args.component_ref)
    if card_ref and args.source:
        declared_source, _ = asset_store.resolve_component(root, card_ref)
        if source.resolve() != declared_source.resolve():
            raise HarnessError('Card source identity does not match the requested card asset')
    if not card_ref:
        validate_component_release(source, expected_ref=args.component_ref, allow_unapproved=acceptance is not None)
    if not args.binding_file:
        raise HarnessError("Component installation requires --binding-file/--binding")
    binding_path = Path(args.binding_file).expanduser()
    if not binding_path.is_absolute():
        binding_path = root / binding_path
    binding = binding_path.resolve()
    if not binding.is_file():
        raise HarnessError(f"Binding file is missing: {binding}")
    from component_harness import package_write_lock
    with package_write_lock(work_requests.safe(project.parent, ".runtime/component-install.lock")):
        if card_ref:
            from asset_contract import freeze_source
            with tempfile.TemporaryDirectory(prefix="card-install-") as temporary:
                frozen = Path(temporary) / "asset"
                release = freeze_source(source, frozen, card_ref=card_ref)
                data = json.loads(binding.read_text(encoding="utf-8"))
                if data.get("component_ref") == card_ref:
                    data["component_ref"] = release["component_ref"]
                result = install_component(frozen, project, data, binding_path=args.destination_binding,
                                           expected_ref=release["component_ref"])
        else:
            result = install_component(source, project, binding, binding_path=args.destination_binding,
                                       expected_ref=args.component_ref, acceptance=acceptance)
    result.update({"project": str(project)})
    if not args.project:
        result.update({"work": work.name, "variant": variant.name})
    print_result(root, args, result)


def command_component_verify(root: Path, args: argparse.Namespace) -> None:
    if args.project:
        project = asset_store.authoring_project(root, Path(args.project))
        print_result(root, args, verify_installation(project, component_ref=args.component_ref))
        return
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, _ = selected_variant(root, work, args)
    result = verify_installation(variant / "project", component_ref=args.component_ref)
    result.update({"work": work.name, "variant": variant.name})
    print_result(root, args, result)


def command_variant_add(root: Path, args: argparse.Namespace) -> None:
    with naming_lock(root):
        _command_variant_add(root, args)


def _command_variant_add(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    ensure_mutable_work(root, work)
    materialize_legacy_lifecycle(work)
    workflow = work_workflow(work)
    if args.variant_id is None:
        numbers = [int(path.name[7:]) for path in variant_paths(work) if re.fullmatch(r'variant[0-9]+', path.name)]
        args.variant_id = 'variant' + str(max(numbers, default=0) + 1)
    name = checked_variant_name(args.name) if workflow == "hyperframes_video" and args.name is not None else None
    settings = adopted_settings(root, args, work)
    source = None
    if args.copy_from:
        if workflow != "hyperframes_video":
            raise HarnessError("--from is only available for hyperframes_video")
        source_path = work / "variants" / validate_id(args.copy_from, "source variant")
        if not source_path.is_dir():
            raise HarnessError(f"Unknown source variant: {args.copy_from}")
        source = input_path(source_path, "SCRIPT.md")
    elif workflow == "hyperframes_video" and (work / "shared" / "SCRIPT.md").is_file():
        source = work / "shared" / "SCRIPT.md"
    options = dict(workflow=workflow, template=args.template, profile=args.profile,
                   ratio=settings.get("ratio"), subject_position=args.subject_position,
                   design=settings.get("design"), copy_script_from=source)
    if workflow == "hyperframes_video":
        metadata = read_frontmatter(work / "WORK.md")
        if metadata.get("purpose") == "test":
            settings["batch"] = args.batch or args.variant_id
        path = create_adopted_variant(root, work, args.variant_id, settings,
                                      shared=not args.copy_from,
                                      branch=args.copy_from, **options)
        if name is not None:
            state = read_json(path / "variant.yaml")
            state["name"] = name
            write_variant(path, state)
    else:
        path = create_variant(root, work, args.variant_id, **options)
    sync_work_lifecycle(root, work)
    if not args.work_override:
        write_pointer(root, "current-variant", path.name)
    print(path.name)


def command_variant_use(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    variant_id = validate_id(args.variant_id, "variant id")
    if not (work / "variants" / variant_id).is_dir():
        raise HarnessError(f"Unknown variant: {variant_id}")
    write_current(root, work.name, variant_id)
    print(variant_id)


def command_variant_reselect(root: Path, args: argparse.Namespace) -> None:
    if not args.work_override or not args.variant_override:
        raise HarnessError('Reselect requires explicit --work and --variant')
    work, _ = selected_work(root, args)
    require_workflow(work, 'hyperframes_video')
    variant, state = selected_variant(root, work, args)
    before_bytes = (variant / 'variant.yaml').read_bytes()
    if json.loads(before_bytes.decode('utf-8-sig')) != state:
        raise HarnessError('Variant changed during selection; retry from stable inputs')
    studio = studio_record(variant, 'current')
    if studio.exists():
        running = read_json(studio)
        if not running.get('stopped_at') and not storage.process_stopped(running.get('pid')):
            raise HarnessError('Stop this Variant Studio before reselecting its configuration')
    args._selection_prior = {'work': work.name, 'state': state}
    args._variant_overrides = state.get('variant_overrides', {})
    args.variant_id = variant.name
    settings = adopted_settings(root, args, work)
    # A reselect updates metadata only; authored sources and frozen outputs remain intact.
    keys = set(settings) | {'appearance_lock', 'theme', 'background', 'motion', 'profile',
                            'theme_revision', 'theme_settings', 'design_snapshot', 'design_sha256', 'design_files', 'design_draft_files'}
    keys -= {'revision', 'selection_source_work'}
    changes = {key: {'before': state.get(key), 'after': settings.get(key)}
               for key in sorted(keys) if state.get(key) != settings.get(key)}
    report = {'work': work.name, 'variant': variant.name, 'changes': changes}
    if not changes or not args.apply:
        print_result(root, args, {**report, 'status': 'preview' if changes else 'unchanged'})
        return
    updated = {key: value for key, value in state.items() if key not in keys}
    updated.update({key: settings[key] for key in keys if key in settings})
    digest = hashlib.sha256(before_bytes).hexdigest()
    backup = storage.scoped_path(variant, '.runtime/configuration-history/' + digest + '/variant.yaml')
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if backup.read_bytes() != before_bytes:
            raise HarnessError('Configuration history changed; preserve it for inspection')
    else:
        with backup.open('xb') as stream:
            stream.write(before_bytes)
    updated['configuration_history'] = [*state.get('configuration_history', []), {
        'at': now(), 'revision': state.get('revision', 1),
        'source_snapshot': backup.relative_to(variant).as_posix(), 'source_sha256': digest,
        'configuration': {key: state[key] for key in keys if key in state},
        'accepted_preview': state.get('accepted_preview'), 'current_final': state.get('current_final')}]
    updated.update(revision=state.get('revision', 1) + 1,
                   plan_revision=state.get('plan_revision', 1) + 1,
                   line={'id': settings['design'], 'version': settings['design_version']},
                   accepted_visual_plan=None, accepted_preview=None, accepted_plan_revision=None,
                   current_preview=None, current_final=None, current_cover=None, accepted_cover=None,
                   status='waiting_user', wait_for='plan_approval',
                   next_action='Refresh and review Plan, rebuild Draft against the selected configuration')
    for key in ('cover_recipe', 'cover_id', 'cover_issue'):
        updated.pop(key, None)
    if getattr(args, '_migration_record', None):
        updated['design_migration'] = args._migration_record
    if (variant / 'variant.yaml').read_bytes() != before_bytes:
        raise HarnessError('Variant changed during selection; no adoption written')
    write_variant(variant, updated)
    print_result(root, args, {**report, 'status': 'reselected', 'revision': updated['revision']})


def command_design_migrate(root: Path, args: argparse.Namespace) -> None:
    if not args.work_override:
        raise HarnessError('Migration requires an explicit --work')
    work, _ = selected_work(root, args, allow_archive=True)
    paths = variant_paths(work)
    if args.migrate_command == 'design' and not paths:
        print_result(root, args, {'status': 'no-variants', 'work': work.name, 'created': []})
        return
    if paths and not args.variant_override:
        raise HarnessError('Select an explicit --variant; sibling versions remain unchanged')
    target = storage.scoped_path(work, 'variants/' + validate_id(args.variant_override, 'variant id')) if paths else work
    source = target / ('variant.yaml' if paths else 'WORK.md')
    state = read_json(source) if paths else read_frontmatter(source)
    digest = file_sha256(source)
    if args.apply and digest != args.source_sha256:
        raise HarnessError('Migration source changed; supply its exact --source-sha256')
    studio = studio_record(target, 'current')
    if studio.exists():
        record = read_json(studio)
        if not record.get('stopped_at') and not storage.process_stopped(record.get('pid')):
            raise HarnessError('Stop the selected item before migration or retirement')
    original = state.get('design') or (state.get('line') or {}).get('id') or state.get('mode') or state.get('workflow')
    report = {'work': work.name, 'variant': target.name if paths else None,
              'original': original, 'source_sha256': digest, 'content_policy': 'preserve all authored files and history',
              'contexts': 'remain bound to the same historical identity'}
    if args.migrate_command == 'retire':
        if not args.note.strip():
            raise HarnessError('Retirement requires a reason')
        if args.apply and paths and final_recovery_pending(target):
            raise HarnessError('Final recovery pending; run finalize before retirement')
        if args.apply and not state.get('retirement'):
            state['retirement'] = {**report, 'note': args.note, 'at': now()}
            if paths:
                state['lifecycle'] = 'archived'
                write_variant(target, state)
            else:
                atomic_write(source, '---\n' + json.dumps(state, ensure_ascii=False) + '\n---\n' + document_body(source))
        print_result(root, args, {**report, 'status': 'retired' if args.apply else 'preview'})
        return
    card = designs.require(args.design)
    if card['version'] != args.design_version:
        raise HarnessError('Requested design version is not the installed exact card')
    report.update(target_design={'id': card['id'], 'version': card['version'], 'sha256': lines.card_digest(card)},
                  unknown_sources=[key for key in ('captions', 'sfx', 'cover', 'ratio', 'fps', 'seed')
                                   if key in state and not any(path == key or path.startswith(key + '.')
                                                              for path in state.get('design_sources', {}))])
    package = target / 'project/package.json'
    package_data = read_json(package) if package.is_file() else {}
    dependencies = {**package_data.get('dependencies', {}), **package_data.get('devDependencies', {})}
    if (work_workflow(work) != 'hyperframes_video' or original == 'remotion'
            or any(name == 'remotion' or name.startswith('@remotion/') for name in dependencies)):
        print_result(root, args, {**report, 'status': 'needs-native-adaptation',
                                 'applied': False, 'reason': 'Preserve this source; adapt its renderer before adopting a HyperFrames design'})
        return
    if not args.account and not args.no_account:
        raise HarnessError('Migration requires an explicit account choice or --no-account')
    if not args.overrides:
        raise HarnessError('Migration requires explicit --overrides JSON ({} adopts defaults); old resolved values are not promoted')
    args._migration_record = report
    command_variant_reselect(root, args)


def command_variant_list(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    rows = []
    for path in variant_paths(work):
        state = read_json(path / "variant.yaml")
        rows.append({"id": path.name, "name": state.get("name") or path.name,
                     "lifecycle": variant_lifecycle(work, state), "ratio": state.get("ratio"),
                     "account": state.get("account"), "account_revision": state.get("account_revision"),
                     "status": state.get("status"), "wait_for": state.get("wait_for")})
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def command_wait(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    variant, state = selected_variant(root, work, args)
    status, action = WAIT_REASONS[args.reason]
    state.update(status=status, wait_for=args.reason, next_action=args.next_action or action)
    write_variant(variant, state)
    print(f"{variant.name}: {status}/{args.reason}")


def restore_parked_work(root: Path, work: Path) -> Path:
    marker = work / ".runtime/parked.json"
    saved = read_json(marker) if marker.is_file() else {}
    if not saved.get("stable_path"):
        updates = []
        old_prefix = works_root(root) / "active" / work.name
        for variant in variant_paths(work):
            for path in (variant / ".runtime").glob("studio-*.json"):
                record = read_json(path)
                project = Path(record.get("project", ""))
                if work.parent.name == "parked" and project.is_relative_to(old_prefix):
                    if not storage.process_stopped(record.get("pid")):
                        raise HarnessError("Legacy parked Studio still has a live or unknown process; stop it before resume")
                    record["project"] = str(work / project.relative_to(old_prefix))
                    updates.append((path, record))
        for path, record in updates:
            write_json(path, record)
        # Legacy park changed wait fields. Restore from its durable original record;
        # leave paths stable and keep the record on error so retry is idempotent.
        for variant in variant_paths(work):
            prior = saved.get("variants", {}).get(variant.name)
            if prior:
                state = read_json(variant / "variant.yaml")
                state.update({key: prior[key] for key in ("status", "wait_for", "next_action") if key in prior})
                write_variant(variant, state)
    if work.parent.name == "parked":
        write_json(work / ".runtime/resumed.json", {"stable_path": True, "resumed_at": now()})
    marker.unlink(missing_ok=True)
    return work


def command_resume(root: Path, args: argparse.Namespace) -> None:
    work, location = selected_work(root, args)
    if location == "parked":
        restore_parked_work(root, work)
    # Resume a paused Work, not a completed Variant or a waiting production step.
    print(f"{work.name}: active; waiting items preserved")


def command_park(root: Path, args: argparse.Namespace) -> None:
    work, location = selected_work(root, args)
    if location != "parked":
        write_json(work / ".runtime/parked.json", {"parked_at": now(), "stable_path": True})
    print(work.name)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_items(project: Path) -> tuple[str, ...]:
    """Keep legacy snapshots unchanged while freezing installed Components when present."""

    closure = storage.snapshot_files(project)
    if closure is not None:
        return closure
    return SNAPSHOT_ITEMS + tuple(
        name for name in OPTIONAL_SNAPSHOT_ITEMS if (project / name).exists() or (project / name).is_symlink()
    )


def assert_snapshot_source(project: Path) -> None:
    items = snapshot_items(project)
    required = ("index.html", "DESIGN.md", "project-config.json") if storage.snapshot_files(project) is not None else SNAPSHOT_ITEMS
    missing = [name for name in required if not (project / name).exists()]
    if missing:
        raise HarnessError(f"Project snapshot is incomplete: {', '.join(missing)}")
    for name in items:
        source = project / name
        if source.is_symlink():
            raise HarnessError(f"Snapshot source cannot be a symlink: {source}")
        if source.is_dir():
            for directory, names, files in os.walk(source):
                directory_path = Path(directory)
                for child in [*names, *files]:
                    if (directory_path / child).is_symlink():
                        raise HarnessError(f"Snapshot source cannot contain symlinks: {directory_path / child}")


def snapshot_digest(project: Path, kind: str = "executable") -> str:
    digest = hashlib.sha256()
    names = () if kind == "reference" else validate_dependencies(project, layout=True) if kind == "layout" else snapshot_items(project)
    if kind == "reference" and (not project.is_dir() or project.is_symlink() or any(project.iterdir())):
        raise HarnessError("Reference Plan has no source sample; its snapshot must be empty")
    for name in names:
        source = project / name
        paths = [source]
        if source.is_dir():
            paths.extend(sorted(path for path in source.rglob("*") if path.is_file()))
        for path in paths:
            if path.is_file():
                relative = path.relative_to(project).as_posix().encode()
                digest.update(len(relative).to_bytes(4, "big"))
                digest.update(relative)
                digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def snapshot_tree_manifest(project: Path) -> dict[str, str]:
    """Hash every frozen file when comparing legacy receipt mirrors."""

    if not project.is_dir() or project.is_symlink():
        raise HarnessError(f"Snapshot directory is unavailable: {project}")
    manifest: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if path.is_symlink():
            raise HarnessError(f"Snapshot cannot contain symlinks: {path}")
        if path.is_file():
            manifest[path.relative_to(project).as_posix()] = file_sha256(path)
    return manifest


def copy_snapshot(project: Path, destination: Path, kind: str = "executable") -> None:
    destination.mkdir(parents=True)
    if kind == "reference":
        return
    for name in validate_dependencies(project, layout=True) if kind == "layout" else snapshot_items(project):
        source = project / name
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def workflow_for(variant: Path, state: dict) -> dict:
    return workflow_config.resolve(read_frontmatter(variant.parent.parent / 'WORK.md'), state)


def confirmed_input(variant: Path, state: dict, stage: str) -> bool:
    path = input_path(variant, 'SCRIPT.md') if stage == 'script' else variant / 'ANIMATION_PLAN.md'
    owner = read_frontmatter(variant.parent.parent / 'WORK.md') if stage == 'script' else state
    key = path.relative_to(variant.parent.parent).as_posix()
    record = owner.get('confirmations', {}).get(key)
    return bool(record and record.get('sha256') == file_sha256(path)
                and record.get('revision') == read_frontmatter(path).get('revision'))


def script_confirmation(variant: Path, state: dict) -> bool:
    return workflow_for(variant, state)['values']['human_confirmation']['script'] and not confirmed_input(variant, state, 'script')


def plan_confirmation(root: Path, variant: Path, state: dict) -> bool:
    configured = workflow_for(variant, state)['values']['human_confirmation']['plan'] and not confirmed_input(variant, state, 'plan')
    return configured if state.get('design_snapshot') or state.get('design_live') else configured and effective_settings(root, state)['direction_approval']['value']


def assert_preview_ready(variant: Path, state: dict[str, Any], *, purpose: str = "draft", kind: str = "executable", direction_approval: bool = True) -> None:
    script = read_frontmatter(input_path(variant, "SCRIPT.md"))
    plan = read_frontmatter(variant / "ANIMATION_PLAN.md")
    if plan.get('plan_format') == '3.7.0' and plan.get('line') != state.get('line'):
        raise HarnessError('Plan line differs from the frozen Variant line')
    gates = workflow_for(variant, state)['values']['human_confirmation']
    if script_confirmation(variant, state) and script.get("approval") == "pending":
        raise HarnessError("SCRIPT.md still requires approval")
    if script.get("revision") != state.get("script_revision"):
        raise HarnessError("SCRIPT.md revision does not match variant.yaml")
    if purpose != "plan" and direction_approval and gates['plan'] and plan.get("status") != "approved":
        raise HarnessError("ANIMATION_PLAN.md is not approved")
    if plan.get("revision") != state.get("plan_revision"):
        raise HarnessError("ANIMATION_PLAN.md revision does not match variant.yaml")
    if plan.get("script_revision") != state.get("script_revision"):
        raise HarnessError("ANIMATION_PLAN.md targets a different Script revision")
    if purpose == "plan" and plan.get("research_revision") is None:
        raise HarnessError("Visual Plan requires the current Research revision")
    if plan.get("research_revision") is not None:
        research = read_frontmatter(input_path(variant, "RESEARCH.md"))
        if research.get("status") != "ready":
            raise HarnessError("RESEARCH.md is not ready")
        if research.get("revision") != plan.get("research_revision"):
            raise HarnessError("ANIMATION_PLAN.md targets a different Research revision")
        if research.get("script_revision") != state.get("script_revision"):
            raise HarnessError("RESEARCH.md targets a different Script revision")


def preview_metadata(path: Path) -> dict[str, Any]:
    metadata = read_frontmatter(path / "preview.md")
    if metadata.get('module_texts_sha256'):
        inventory = path / 'module-texts.json'
        if not inventory.is_file() or file_sha256(inventory) != metadata['module_texts_sha256']:
            raise HarnessError('Frozen module text inventory changed or is missing')
    return metadata


def assert_full_draft(metadata: dict[str, Any]) -> None:
    if (metadata.get("purpose", "draft") != "draft"
            or metadata.get("scope", "full") != "full"
            or metadata.get("media_readiness", "complete") != "complete"):
        raise HarnessError("Only a full, media-complete Draft can be accepted or finalized")


PREVIEW_DOCUMENTS = ("SCRIPT.md", "RESEARCH.md", "ANIMATION_PLAN.md")


def preview_input_hashes(directory: Path) -> dict[str, str]:
    if any(not input_path(directory, name).is_file() for name in PREVIEW_DOCUMENTS):
        raise HarnessError("Preview requires frozen SCRIPT.md, RESEARCH.md and ANIMATION_PLAN.md inputs")
    return {name: file_sha256(input_path(directory, name)) for name in PREVIEW_DOCUMENTS}


def document_content(path: Path, ignored: tuple[str, ...] = ()) -> tuple[dict[str, Any], str]:
    metadata = read_frontmatter(path)
    return {key: value for key, value in metadata.items() if key not in ignored}, document_body(path)


def plan_intent(path: Path) -> tuple[dict[str, Any], str]:
    metadata, body = document_content(path, ("status", "visual_plan", "revision", "script_revision", "research_revision"))
    if "inputs" in metadata:
        if not isinstance(metadata["inputs"], dict) or any(not isinstance(item, dict) for item in metadata["inputs"].values()):
            raise HarnessError("Plan inputs must map document names to metadata objects")
        metadata["inputs"] = {name: {key: value for key, value in item.items() if key != "revision"}
                              for name, item in metadata["inputs"].items()}
    body = re.sub(r'<!-- plan-metadata:start -->.*?<!-- plan-metadata:end -->\s*', '', body, flags=re.S)
    return metadata, body.strip()


def same_preview_inputs(preview: Path, variant: Path) -> bool:
    return all(document_content(preview / name, ("status", "visual_plan") if name == "ANIMATION_PLAN.md" else ())
               == document_content(input_path(variant, name), ("status", "visual_plan") if name == "ANIMATION_PLAN.md" else ())
               for name in PREVIEW_DOCUMENTS)


def assert_preview_inputs(preview: Path, metadata: dict[str, Any], current: Path | None = None) -> None:
    frozen_lock = metadata.get("adopted_settings", {}).get("appearance_lock")
    if frozen_lock is not None and metadata.get("kind", "executable") == "executable":
        appearance.verify(preview / "source-snapshot", frozen_lock)
    if "input_sha256" not in metadata:
        return  # Legacy previews cannot prove compatibility, but retain their original lifecycle.
    if preview_input_hashes(preview) != metadata["input_sha256"]:
        raise HarnessError("Frozen preview inputs changed")
    if current is not None and not same_preview_inputs(preview, current):
        raise HarnessError("Preview inputs changed; register the current content before accepting or finalizing")
    if current is not None and "adopted_settings" in metadata:
        state = read_json(current / "variant.yaml")
        if metadata["adopted_settings"] != {key: state.get(key) for key in metadata["adopted_settings"]}:
            raise HarnessError("Adopted Variant settings changed; register and accept a new Draft")


def assert_plan_baseline(variant: Path, state: dict[str, Any], baseline: Path, project: Path) -> None:
    metadata = preview_metadata(baseline)
    if snapshot_digest(baseline / "source-snapshot", metadata.get("kind", "executable")) != metadata.get("snapshot_sha256"):
        raise HarnessError("Accepted Visual Plan snapshot changed")
    assert_preview_inputs(baseline, metadata)
    same_revision = all(metadata.get(key) == state.get(key) for key in ("script_revision", "plan_revision"))
    if same_revision and ("input_sha256" not in metadata or same_preview_inputs(baseline, variant)):
        return
    feedback = variant / ".runtime" / "feedback.json"
    if "input_sha256" in metadata and feedback.is_file():
        for entry in read_json(feedback).get("entries", []):
            if (entry.get("from") == baseline.name and entry.get("compatible") is True
                    and entry.get("baseline_inputs") == metadata["input_sha256"]
                    and entry.get("baseline_snapshot") == metadata["snapshot_sha256"]
                    and entry.get("current_inputs") == preview_input_hashes(variant)
                    and entry.get("current_snapshot") == snapshot_digest(project)):
                return
    raise HarnessError("Draft requires the current Visual Plan to be accepted or a scoped --compatible check")


def preview_source(variant: Path, metadata: dict[str, Any]) -> Path:
    source = (variant / metadata.get("sample_dir", "project")).resolve()
    if not source.is_relative_to(variant.resolve()) or any(source.is_relative_to((variant / name).resolve()) for name in ("previews", "final", ".runtime")):
        raise HarnessError("Sample directory must be Variant-local and outside frozen/runtime directories")
    return source


def command_preview_register(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    change = card_change_report(state)
    if change:
        print(change['message'], file=sys.stderr)
    purpose = args.purpose
    kind = args.kind
    layout = kind == "layout"
    reference = kind == "reference"
    scene = args.scope == "scene"
    if scene and (kind != "executable" or purpose != "plan" or len(args.scene) != 1):
        raise HarnessError("Scene reference requires --kind executable --purpose plan and exactly one --scene")
    if reference and purpose != "plan":
        raise HarnessError("Reference-only registration requires --purpose plan")
    if layout and (purpose != "plan" or not args.sample_dir or not args.scene):
        raise HarnessError("Layout requires --purpose plan, --sample-dir and --scene")
    if not layout and not scene and (args.sample_dir or args.scene):
        raise HarnessError("--sample-dir and --scene require --kind layout")
    effective = getattr(args, '_effective_settings', None) or effective_settings(root, state)
    direction_approval = plan_confirmation(root, variant, state)
    assert_preview_ready(variant, state, purpose=purpose, kind=kind, direction_approval=direction_approval)
    draft = Path(args.draft_file).expanduser().resolve() if args.draft_file else None
    studio_draft = purpose == "draft" and draft is None
    if draft is not None and (not draft.is_file() or draft.stat().st_size == 0):
        raise HarnessError(f"Draft file is missing or empty: {draft}")
    if purpose == "plan" and draft is not None:
        raise HarnessError("Visual Plan uses executable source, not a replacement MP4")
    project = preview_source(variant, {"sample_dir": args.sample_dir}) if args.sample_dir else variant / "project"
    if state.get("appearance_lock") is not None and kind == "executable":
        appearance.verify(project, state["appearance_lock"])
    if kind == "executable":
        assert_snapshot_source(project)
    if kind == "executable" and (project / "COMPONENT_LOCK.json").is_file():
        verify_installation(project)
    elif kind == "executable" and (project / "scene-slots.json").is_file():
        validate_work_surface_inventory(project)
    import work_tts
    work_tts.verify(variant, SimpleNamespace(**globals()))
    plan_text = plan_with_card((variant / "ANIMATION_PLAN.md").read_text(encoding="utf-8"), state)
    plan_meta = read_frontmatter(variant / 'ANIMATION_PLAN.md')
    reference_hash = plan_meta.get('reference_memory_sha256')
    reference_dir = visual_memory.located(variant, plan_meta.get('revision', 1), reference_hash)
    if any('·' in ref for ref in visual_memory.references(plan_text)) and not reference_hash:
        raise HarnessError('Reference Plan requires plan refresh before registration')
    if reference_hash:
        try:
            manifest = visual_memory.frozen(reference_dir, reference_hash)
            if manifest['input']['references'] != visual_memory.references(plan_text):
                raise ValueError('References changed; run plan refresh')
        except ValueError as error:
            raise HarnessError(str(error)) from error
    visual = purpose == "plan" or studio_draft or bool(state.get("accepted_visual_plan"))
    scenes = reference_projection(plan_text) if reference else layout_projection(project, plan_text, args.scene) if layout else scene_projection(project, plan_text, args.scene if scene else None) if visual else None
    if not reference and visual:
        closure = validate_dependencies(project, layout=layout)
        if not layout:
            math_build.verify_generated(project, plan_text, args.scene if scene else None, closure=closure)
    draft_digest = file_sha256(draft) if draft else None
    source_digest = hashlib.sha256().hexdigest() if reference else snapshot_digest(project, kind)
    plan_digest = file_sha256(variant / "ANIMATION_PLAN.md") if visual else None
    input_hashes = preview_input_hashes(variant) if all(input_path(variant, name).is_file() for name in PREVIEW_DOCUMENTS) else None
    if studio_draft:
        input_hashes = preview_input_hashes(variant)
    if purpose == "draft" and direction_approval and state.get("accepted_visual_plan"):
        assert_plan_baseline(variant, state, variant / "previews" / validate_id(state["accepted_visual_plan"], "Visual Plan"), project)
    if draft_digest:
        assert_draft_source(variant, draft_digest, source_digest)
    if purpose == 'draft':
        if getattr(args, 'cover_title', None) is not None:
            state['cover_title'] = args.cover_title
        prepare_draft_cover(variant, state)
    if purpose == 'draft' and state.get('design_live'):
        import design_snapshot
        adopt_card_files(state, design_snapshot.freeze(variant, state['design']))
    previews = variant / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    existing = sorted(path for path in previews.glob(f"{purpose}-v[0-9][0-9][0-9]") if path.is_dir())
    for path in existing:
        metadata = preview_metadata(path)
        if (
            metadata.get("draft_sha256") == draft_digest
            and (purpose != "draft" or metadata.get("design_files") == state.get("design_files"))
            and metadata.get("snapshot_sha256") == source_digest
            and metadata.get("script_revision") == state.get("script_revision")
            and metadata.get("plan_revision") == state.get("plan_revision")
            and metadata.get("plan_sha256") == plan_digest
            and metadata.get("input_sha256") == input_hashes
            and ("adopted_settings" not in metadata or metadata["adopted_settings"] == {
                key: state.get(key) for key in metadata["adopted_settings"]})
            and metadata.get("kind", "executable") == kind
            and metadata.get("scope", "full") == args.scope
            and metadata.get("media_readiness", "complete") == args.media_readiness
            and (not (layout or scene) or (metadata.get("sample_scenes") == args.scene and metadata.get("sample_dir") == project.relative_to(variant.resolve()).as_posix()))
        ):
            assert_preview_inputs(path, metadata)
            if snapshot_digest(path / "source-snapshot", kind) != metadata.get("snapshot_sha256"):
                raise HarnessError("Preview snapshot changed")
            if metadata.get('reference_memory_sha256'):
                visual_memory.frozen(path / 'reference-memory', metadata['reference_memory_sha256'])
            print(path.name)
            return
    version = max((int(path.name.removeprefix(f"{purpose}-v")) for path in existing), default=0) + 1
    draft_id = f"{purpose}-v{version:03d}"
    staging = previews / f".{draft_id}.staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        if draft:
            shutil.copy2(draft, staging / "draft.mp4")
            if file_sha256(staging / "draft.mp4") != draft_digest:
                raise HarnessError("Draft changed during registration")
        copy_snapshot(project, staging / "source-snapshot", kind)
        if kind == "executable":
            validate_snapshot_closure(project, staging / "source-snapshot")
        if snapshot_digest(staging / "source-snapshot", kind) != source_digest:
            raise HarnessError("Project changed during registration")
        if not reference and visual:
            validate_dependencies(staging / "source-snapshot", layout=layout)
        metadata = {
            "id": draft_id,
            "purpose": purpose,
            "kind": kind,
            "scope": args.scope,
            "media_readiness": args.media_readiness,
            "approval_purpose": "direction" if purpose == "plan" else "full-version",
            "registered_at": now(),
            "runtime_version": "3.7.1",
            "runtime_sha256": file_sha256(Path(__file__)),
            "draft_sha256": draft_digest,
            "snapshot_sha256": source_digest,
            "script_revision": state.get("script_revision"),
            "plan_revision": state.get("plan_revision"),
            "plan_sha256": plan_digest,
            "adopted_settings": {key: state.get(key) for key in (
                "template", "profile", "theme", "theme_revision", "theme_settings", "mode", "ratio", "subject_position", "account", "account_revision", "account_settings", "batch",
                "background", "motion", "appearance_lock", "series_binding", "line",
                "design", "design_snapshot", "design_sha256", "design_values", "design_sources")},
        }
        if purpose == 'draft':
            import module_texts
            metadata['module_texts_version'] = 1
            if module_texts.needs_inventory(staging / 'source-snapshot'):
                inventory = module_texts.collect(staging / 'source-snapshot',
                    scenes or scene_projection(project, plan_text), state.get('appearance_lock') or {})
                write_json(staging / 'module-texts.json', inventory)
                metadata['module_texts_sha256'] = file_sha256(staging / 'module-texts.json')
                metadata['embedded_text_scenes'] = sorted({item['scene'] for item in inventory['items'] if item.get('embedded')})
        if purpose == 'draft' and state.get('design_files'):
            import design_snapshot
            receipt = state['design_files']
            frozen_card = storage.scoped_path(variant, receipt['path'])
            design_snapshot.verify(frozen_card, receipt)
            shutil.copytree(frozen_card, staging / 'design-snapshot')
            design_snapshot.verify(staging / 'design-snapshot', receipt)
            metadata['design_files'] = receipt
        if reference_hash:
            visual_memory.copy_frozen(reference_dir, staging / 'reference-memory', reference_hash)
            metadata['reference_memory_sha256'] = reference_hash
        if input_hashes is not None:
            metadata["input_sha256"] = input_hashes
        if studio_draft:
            metadata["review_mode"] = "studio"
        if layout:
            metadata.update(sample_dir=project.relative_to(variant.resolve()).as_posix(), sample_scenes=args.scene,
                            demonstrated="Sample layout, colors, typography and text hierarchy",
                            unverified="Other scenes, motion, reading speed, media and rendering")
        if scene:
            metadata.update(sample_dir=project.relative_to(variant.resolve()).as_posix(), sample_scenes=args.scene,
                            demonstrated="Direction in the selected executable Scene only",
                            unverified="Other Scenes, full assembly and final media")
        if reference:
            metadata.update(sample_scenes=[], demonstrated="Existing accepted asset previews referenced per Scene in Plan",
                            unverified="Current Work assembly, media, timing and rendering")
        if os.environ.get("HYPERFRAMES_AI_REVIEW") == "1":
            metadata["review"] = work_requests.review_identity(configured_work_root(root) or root)
        for name in PREVIEW_DOCUMENTS:
            if input_path(variant, name).is_file():
                shutil.copy2(input_path(variant, name), staging / name)
        assert_preview_inputs(staging, metadata)
        if visual:
            write_json(staging / "visual-plan.json", {"id": draft_id, "scenes": scenes})
        if state.get("accepted_visual_plan"):
            baseline = variant / "previews" / validate_id(state["accepted_visual_plan"], "Visual Plan")
            baseline_metadata = preview_metadata(baseline)
            assert_preview_inputs(baseline, baseline_metadata)
            metadata["source_plan"] = baseline.name
            metadata["source_plan_sha256"] = baseline_metadata["snapshot_sha256"]
            if snapshot_digest(baseline / "source-snapshot", baseline_metadata.get("kind", "executable")) != metadata["source_plan_sha256"]:
                raise HarnessError("Accepted Visual Plan snapshot changed")
            metadata["changed_files"] = source_changes(baseline / "source-snapshot", staging / "source-snapshot")
        atomic_write(
            staging / "preview.md",
            "---\n" + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n---\n\n# Preview\n",
        )
        os.replace(staging, previews / draft_id)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if purpose == 'draft' and state.get('design_files'):
        state['design_draft_files'] = state['design_files']
    state.update(status="waiting_user", wait_for="plan_approval" if purpose == "plan" else "draft_feedback", next_action=f"Review {draft_id}")
    write_variant(variant, state)
    if (purpose == 'draft' and read_frontmatter(work / 'WORK.md').get('purpose') != 'test'
            and os.environ.get('HYPERFRAMES_AI_REVIEW') != '1'
            and not workflow_for(variant, state)['values']['human_confirmation']['draft']
            and not metadata.get('embedded_text_scenes')):
        auto_args = argparse.Namespace(**vars(args))
        auto_args.draft_id, auto_args._automatic = draft_id, True
        command_preview_accept(root, auto_args)
    print(draft_id)


def command_preview_accept(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    if read_frontmatter(work / "WORK.md").get("purpose") == "test":
        raise HarnessError("test Work does not grant production acceptance")
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    draft_id = validate_id(args.draft_id, "draft id")
    preview = variant / "previews" / draft_id
    if draft_id.startswith("plan-v"):
        metadata = preview_metadata(preview)
        assert_preview_inputs(preview, metadata)
        kind = metadata.get("kind", "executable")
        assert_preview_ready(variant, state, purpose="plan", kind=kind)
        if metadata.get("purpose") != "plan" or not (preview / "visual-plan.json").is_file():
            raise HarnessError("Incomplete Visual Plan")
        if kind == "executable":
            assert_snapshot_source(preview / "source-snapshot")
            if metadata.get("scope") == "scene":
                scenes = scene_projection(preview / "source-snapshot", plan_with_card((preview / "ANIMATION_PLAN.md").read_text(encoding="utf-8"), metadata.get("adopted_settings", {})), metadata.get("sample_scenes"))
                if read_json(preview / "visual-plan.json") != {"id": draft_id, "scenes": scenes}:
                    raise HarnessError("Scene reference projection changed")
        if snapshot_digest(preview / "source-snapshot", kind) != metadata.get("snapshot_sha256"):
            raise HarnessError("Visual Plan snapshot changed")
        if kind == "layout":
            frozen_plan = preview / "ANIMATION_PLAN.md"
            if file_sha256(frozen_plan) != metadata.get("plan_sha256"):
                raise HarnessError("Frozen Animation Plan changed")
            scenes = layout_projection(preview / "source-snapshot", plan_with_card(frozen_plan.read_text(encoding="utf-8"), metadata.get("adopted_settings", {})), metadata["sample_scenes"])
            if read_json(preview / "visual-plan.json") != {"id": draft_id, "scenes": scenes}:
                raise HarnessError("Layout sample projection changed")
        if kind == "reference" and read_json(preview / "visual-plan.json") != {
                "id": draft_id, "scenes": reference_projection(plan_with_card((preview / "ANIMATION_PLAN.md").read_text(encoding="utf-8"), metadata.get("adopted_settings", {})))}:
            raise HarnessError("Reference Plan projection changed")
        for field in ("script_revision", "plan_revision"):
            if metadata.get(field) != state.get(field):
                raise HarnessError(f"Visual Plan has a stale {field}")
        assert_preview_inputs(preview, metadata, variant)
        if kind != "reference" and snapshot_digest(preview_source(variant, metadata), kind) != metadata.get("snapshot_sha256"):
            raise HarnessError("Project changed; register the current Visual Plan before accepting")
        if state.get("accepted_visual_plan") == draft_id:
            current = read_frontmatter(variant / "ANIMATION_PLAN.md")
            original = read_frontmatter(preview / "ANIMATION_PLAN.md")
            for value in (current, original):
                value.pop("status", None)
                value.pop("visual_plan", None)
            current_body = (variant / "ANIMATION_PLAN.md").read_text(encoding="utf-8").split("\n---", 1)[1]
            original_body = (preview / "ANIMATION_PLAN.md").read_text(encoding="utf-8").split("\n---", 1)[1]
            if current != original or current_body != original_body:
                raise HarnessError("Animation Plan changed; register the current Visual Plan before accepting")
            print(draft_id)
            return
        if metadata.get("plan_sha256") != file_sha256(variant / "ANIMATION_PLAN.md"):
            raise HarnessError("Animation Plan changed; register the current Visual Plan before accepting")
        plan_path = variant / "ANIMATION_PLAN.md"
        text = plan_path.read_text(encoding="utf-8")
        end = text.index("\n---", 3)
        plan = read_frontmatter(plan_path)
        plan.update(status="approved", visual_plan=draft_id)
        atomic_write(plan_path, "---\n" + json.dumps(plan, ensure_ascii=False) + text[end:])
        state.update(accepted_visual_plan=draft_id, accepted_preview=None, accepted_plan_revision=None,
                     accepted_script_revision=None, status="active", wait_for="none",
                     next_action="Build each Scene from its confirmed Plan and exact assets; samples apply only to their listed Scenes")
        write_variant(variant, state)
        print(draft_id)
        return
    if not preview.is_dir() or not (preview / "source-snapshot").is_dir():
        raise HarnessError(f"Incomplete preview: {draft_id}")
    metadata = preview_metadata(preview)
    assert_full_draft(metadata)
    assert_preview_inputs(preview, metadata, variant)
    if metadata.get("review_mode") == "studio":
        if workflow_for(variant, state)['values']['human_confirmation']['draft']:
            record = bound_studio(variant, draft_id)
            if (record.get("snapshot_sha256") != metadata.get("snapshot_sha256")
                    or snapshot_digest(Path(record["project"])) != metadata.get("snapshot_sha256")):
                raise HarnessError("Studio review source changed; register and review the current Draft")
        if snapshot_digest(variant / "project") != metadata.get("snapshot_sha256"):
            raise HarnessError("Project changed; register the current Draft before accepting")
    elif not (preview / "draft.mp4").is_file() or file_sha256(preview / "draft.mp4") != metadata.get("draft_sha256"):
        raise HarnessError("Draft media changed or missing")
    if snapshot_digest(preview / "source-snapshot") != metadata.get("snapshot_sha256"):
        raise HarnessError("Draft snapshot changed")
    effective = effective_settings(root, state)
    direction_approval = plan_confirmation(root, variant, state)
    if metadata.get("script_revision") != state.get("script_revision"):
        raise HarnessError("Preview targets a different Script revision")
    if metadata.get("plan_revision") != state.get("plan_revision"):
        raise HarnessError("Preview targets a different Plan revision")
    if state.get('line') or metadata.get("source_plan") or metadata.get("review_mode") == "studio":
        assert_preview_ready(variant, state, direction_approval=direction_approval)
    embedded_confirmations = []
    if metadata.get('module_texts_version') == 1:
        import module_texts
        if module_texts.needs_inventory(preview / 'source-snapshot'):
            inventory_path = preview / 'module-texts.json'
            if not inventory_path.is_file() or file_sha256(inventory_path) != metadata.get('module_texts_sha256'):
                raise HarnessError('Frozen module text inventory changed or is missing')
            try:
                embedded_confirmations = module_texts.confirmation(read_json(inventory_path),
                    getattr(args, 'confirm_embedded', None) or [], automatic=getattr(args, '_automatic', False))
            except ValueError as error:
                raise HarnessError(str(error)) from error
    if not direction_approval:
        plan_path = variant / 'ANIMATION_PLAN.md'
        text = plan_path.read_text(encoding='utf-8')
        plan = read_frontmatter(plan_path)
        if plan.get('revision') != metadata['plan_revision']:
            raise HarnessError('Draft must approve the exact Plan revision')
        plan['status'] = 'approved'
        atomic_write(plan_path, '---\n' + json.dumps(plan, ensure_ascii=False) + text[text.index('\n---', 3):])
    if state.get('line'):
        state['draft_acceptance'] = {'draft_id': draft_id, 'snapshot_sha256': metadata['snapshot_sha256'],
                                     'plan_revision': metadata['plan_revision'], 'settings': effective,
                                     'direction_approval': direction_approval,
                                     'embedded_text_confirmations': embedded_confirmations,
                                     'module_texts_sha256': metadata.get('module_texts_sha256')}
    if embedded_confirmations:
        write_json(preview / 'embedded-text-acceptance.json', {'snapshot_sha256': metadata['snapshot_sha256'],
            'module_texts_sha256': metadata['module_texts_sha256'], 'scenes': embedded_confirmations, 'at': now()})
    state.update(
        accepted_preview=draft_id,
        accepted_cover=state.get('cover_id') if state.get('current_cover') else None,
        accepted_script_revision=metadata.get("script_revision"),
        accepted_plan_revision=metadata.get("plan_revision"),
        status="active",
        wait_for="none",
        next_action="Prepare the final render from the accepted snapshot",
    )
    write_variant(variant, state)
    if not getattr(args, '_automatic', False):
        print(draft_id)


def runtime_path(value: str | None, variable: str) -> Path:
    configured = os.environ.get(variable)
    if not value and not configured:
        raise HarnessError(f"Runtime is not configured: {variable}")
    result = Path(value or configured).expanduser().resolve()
    if configured and result != Path(configured).expanduser().resolve():
        raise HarnessError(f"Runtime override must match the pinned session: {variable}")
    return result


def assert_draft_source(variant: Path, output_hash: str, source_hash: str) -> None:
    records = [read_json(path) for path in (variant / ".runtime").glob("render*/render.json")]
    latest = variant / ".runtime" / "render.json"
    if latest.is_file():
        records.append(read_json(latest))
    records += [preview_metadata(path.parent) for path in (variant / "previews").glob("draft-v*/preview.md")]
    matching = [row for row in records if row.get("output_sha256", row.get("draft_sha256")) == output_hash]
    if matching and not any(row.get("snapshot_sha256") == source_hash for row in matching):
        raise HarnessError("Draft output belongs to different source; render the changed project before registration")


def checked_preview(variant: Path, preview_id: str) -> tuple[Path, dict[str, Any]]:
    preview = variant / "previews" / validate_id(preview_id, "preview")
    metadata = preview_metadata(preview)
    assert_preview_inputs(preview, metadata)
    kind = metadata.get("kind", "executable")
    if snapshot_digest(preview / "source-snapshot", kind) != metadata.get("snapshot_sha256"):
        raise HarnessError("Preview snapshot changed")
    if metadata.get("plan_sha256") and file_sha256(preview / "ANIMATION_PLAN.md") != metadata["plan_sha256"]:
        raise HarnessError("Frozen Animation Plan changed")
    if metadata.get('reference_memory_sha256'):
        try:
            visual_memory.frozen(storage.scoped_path(preview, 'reference-memory'), metadata['reference_memory_sha256'])
        except (ValueError, OSError) as error:
            raise HarnessError(str(error)) from error
    if metadata.get('design_files'):
        import design_snapshot
        design_snapshot.verify(preview / 'design-snapshot', metadata['design_files'])
    if (preview / "visual-plan.json").is_file():
        plan_text = plan_with_card((preview / "ANIMATION_PLAN.md").read_text(encoding="utf-8"), metadata.get("adopted_settings", {}))
        scenes = reference_projection(plan_text) if kind == "reference" else layout_projection(preview / "source-snapshot", plan_text, metadata["sample_scenes"]) if kind == "layout" else scene_projection(preview / "source-snapshot", plan_text, metadata.get("sample_scenes") if metadata.get("scope") == "scene" else None)
        if read_json(preview / "visual-plan.json") != {"id": preview.name, "scenes": scenes}:
            raise HarnessError("Visual Plan projection changed; it must be generated from the frozen sources")
    return preview, metadata


def studio_record(variant: Path, target: str) -> Path:
    return variant / ".runtime" / f"studio-{validate_id(target, 'preview')}.json"


def bound_studio(variant: Path, target: str) -> dict[str, Any]:
    path = studio_record(variant, target)
    if not path.is_file():
        raise HarnessError("No Studio process record; use preview open for this exact target first")
    record = read_json(path)
    project = Path(record["project"]).resolve()
    expected = variant / "project" if target == "current" else variant / ".runtime" / record["review_directory"] / target
    if (record.get("target") != target or record.get("work") != variant.parent.parent.name
            or record.get("variant") != variant.name or project != expected.resolve()
            or target != "current" and not project.is_relative_to((variant / ".runtime").resolve())):
        raise HarnessError("Studio process record does not match this Work/Variant/target")
    return record


def command_preview_open(root: Path, args: argparse.Namespace, *, emit=True):
    with naming_lock(root):
        return _command_preview_open(root, args, emit=emit)


def _command_preview_open(root: Path, args: argparse.Namespace, *, emit=True):
    work, location = selected_work(root, args, allow_archive=True)
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    change = card_change_report(state)
    if change:
        print(change['message'], file=sys.stderr)
    target = validate_id(args.preview_id, "preview")
    if target == "current" and (args.legacy or location == "archive"):
        raise HarnessError("Current project is editable; choose a registered preview for historical review")
    if target == "current":
        project, kind, metadata = variant / "project", "executable", {}
        if state.get("appearance_lock") is not None:
            appearance.verify(project, state["appearance_lock"])
    else:
        preview, metadata = checked_preview(variant, target)
        kind = metadata.get("kind", "executable")
        if kind == "reference":
            raise HarnessError(f"This Plan has no new sample; use the accepted asset Preview references in {preview / 'ANIMATION_PLAN.md'}")
        if args.legacy:
            if not (preview / "visual-plan.json").is_file():
                raise HarnessError("Legacy review needs visual-plan.json; use Studio or the registered MP4")
            serve(preview, None if kind == "layout" else runtime_path(args.hyperframes_dist, "HYPERFRAMES_DIST"), args.port,
                  metadata.get("review"), layout=kind == "layout")
            return
        project = None
        if studio_record(variant, target).is_file():
            previous = bound_studio(variant, target)
            if previous.get("snapshot_sha256") != metadata["snapshot_sha256"]:
                raise HarnessError("Studio review source differs from the registered snapshot")
            project = Path(previous["project"])
            if project.is_symlink() or any(path.is_symlink() for path in project.rglob("*")):
                raise HarnessError("Studio review copy cannot contain symlinks")
            # Layout copies have deterministic Studio metadata added after copying.
            expected = previous.get("opened_source_sha256") if kind == "layout" else metadata["snapshot_sha256"]
            try:
                intact = snapshot_digest(project, kind) == expected
            except VisualPlanError:
                intact = False
            if not intact:
                project = None
        if project is None:
            project = variant / ".runtime" / f"studio-review-{uuid.uuid4().hex}" / target
            if kind == "executable":
                assert_snapshot_source(preview / "source-snapshot")
            copy_snapshot(preview / "source-snapshot", project, kind)
            if snapshot_digest(project, kind) != metadata["snapshot_sha256"]:
                raise HarnessError("Studio review copy differs from the registered snapshot")
            if kind == "layout":
                studio_preview.adapt_layout(project)
    if not (project / "index.html").is_file():
        raise HarnessError(f"Studio project has no index.html: {project}")
    if project.is_symlink() or any(path.is_symlink() for path in project.rglob("*")):
        raise HarnessError("Editable Studio projects cannot contain symlinks to frozen or external files")
    validate_dependencies(project, layout=kind == "layout")
    if (project / "COMPONENT_LOCK.json").is_file():
        verify_installation(project)
    opened_digest = snapshot_digest(project, kind)
    if target != "current":
        # Studio stamps IDs only when source files are writable; keep cache directories writable.
        for path in project.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
    cli = runtime_path(args.hyperframes_cli, "HYPERFRAMES_CLI")
    session = studio_preview.start(cli, project.resolve(), args.port, no_open=args.no_open, layout=kind == "layout")
    previous = read_json(studio_record(variant, target)) if studio_record(variant, target).is_file() else {}
    record = {"work": work.name, "variant": variant.name, "target": target, "project": str(project.resolve()),
              "kind": kind, "port": session["port"], "url": session["studioUrl"], "pid": session.get("pid"),
              "snapshot_sha256": metadata.get("snapshot_sha256"), "cli_sha256": file_sha256(cli),
              "opened_source_sha256": previous.get("opened_source_sha256", opened_digest) if target == "current" else opened_digest,
              "opened_at": now()}
    if os.environ.get("HYPERFRAMES_AI_RESOLVED_CONFIG"):
        config = json.loads(os.environ["HYPERFRAMES_AI_RESOLVED_CONFIG"])
        record["tool_root"] = str(root)
        record["tool_release"] = os.environ.get("HYPERFRAMES_AI_VERSION")
        record["content_roots"] = {key: config.get(key) for key in ("work_root", "asset_root", "asset_source_roots", "review")}
    if session.get("browser_profile"):
        record["browser_profile"] = session["browser_profile"]
    if target != "current":
        record["review_directory"] = project.parent.name
    write_json(studio_record(variant, target), record)
    if emit:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def command_preview_studio(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    require_workflow(work, "hyperframes_video")
    variant, _ = selected_variant(root, work, args)
    record = bound_studio(variant, args.preview_id)
    cli = runtime_path(args.hyperframes_cli, "HYPERFRAMES_CLI")
    if file_sha256(cli) != record["cli_sha256"]:
        raise HarnessError("Studio runtime changed; close the old process and reopen this target")
    project = Path(record["project"])
    if args.preview_command == "stop":
        result = studio_preview.stop(cli, project, record["port"])
        write_json(studio_record(variant, args.preview_id), {**record, "stopped_at": now()})
    else:
        result = studio_preview.context(cli, project, record["port"], args.fields, args.detail)
        result["work"] = {key: record[key] for key in ("work", "variant", "target", "url")}
        result["source_changed"] = snapshot_digest(project, record["kind"]) != record["opened_source_sha256"]
        render = variant / ".runtime" / "render.json"
        if args.preview_id == "current" and render.is_file():
            result["render_matches_source"] = read_json(render).get("snapshot_sha256") == snapshot_digest(project)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_preview_diagnose(root: Path, args: argparse.Namespace) -> None:
    if not args.work_override or not args.variant_override:
        raise HarnessError('Diagnostics require explicit --work and --variant; no Current fallback')
    parameters = visual_diagnostics.parameters(args)
    work, _ = selected_work(root, args, allow_archive=True)
    require_workflow(work, 'hyperframes_video')
    variant, state = selected_variant(root, work, args)
    target = validate_id(args.preview_id, 'preview')
    record = bound_studio(variant, target)
    project = Path(record['project'])
    try:
        url = urlsplit(record['url'])
        valid_url = (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}
                     and url.port == record['port'] and unquote(url.fragment) == f'project/{project.name}')
    except ValueError:
        valid_url = False
    if not valid_url:
        raise HarnessError('Diagnostic URL does not match the bound Studio project and port; reopen this target')
    if record['kind'] != 'executable':
        raise HarnessError('Diagnostics require an executable Studio Plan or Draft, not a static/reference Plan')
    documents = variant
    sample_scenes = None
    if target != 'current':
        documents, metadata = checked_preview(variant, target)
        if metadata.get('purpose') not in {'plan', 'draft'} or metadata.get('kind', 'executable') != 'executable':
            raise HarnessError('Diagnostics target must be current or a registered executable Plan or Draft')
        if metadata.get('scope') == 'scene':
            sample_scenes = metadata.get('sample_scenes')
        if snapshot_digest(project) != metadata['snapshot_sha256']:
            raise HarnessError('Studio review copy changed; diagnose current or register the edited version')
    if project.is_symlink() or any(path.is_symlink() for path in project.rglob('*')):
        raise HarnessError('Diagnostic project cannot contain external/frozen symlinks')
    before = {'input_sha256': preview_input_hashes(documents), 'snapshot_sha256': snapshot_digest(project)}
    contents = {name: input_path(documents, name).read_text(encoding='utf-8-sig') for name in PREVIEW_DOCUMENTS}
    card_state = preview_metadata(documents).get('adopted_settings', state) if (documents / 'preview.md').is_file() else state
    contents['ANIMATION_PLAN.md'] = plan_with_card(contents['ANIMATION_PLAN.md'], card_state)
    scenes = scene_projection(project, contents['ANIMATION_PLAN.md'], sample_scenes)
    dependencies = validate_dependencies(project)
    math_build.verify_generated(project, contents['ANIMATION_PLAN.md'], sample_scenes, closure=dependencies)
    inventory = visual_diagnostics.static_inventory(project, dependencies)
    exceptions = []
    if args.exceptions:
        try:
            exceptions = json.loads(Path(args.exceptions).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as error:
            raise HarnessError(f'Cannot read confirmed exceptions: {error}') from error
    # Validate confirmation input before launching a browser.
    information, mapping = visual_diagnostics.plan_information(contents['ANIMATION_PLAN.md'])
    if sample_scenes is not None:
        mapping = {sid: ids for sid, ids in mapping.items() if sid in sample_scenes}
    visual_diagnostics.checked_exceptions(exceptions, visual_diagnostics.source_sections(
        contents['SCRIPT.md'], contents['RESEARCH.md'], information), mapping)
    cli = runtime_path(args.hyperframes_cli, 'HYPERFRAMES_CLI')
    if file_sha256(cli) != record['cli_sha256']:
        raise HarnessError('Studio runtime changed; reopen this exact target')
    studio_preview.context(cli, project, record['port'], 'server')
    browser = args.browser or os.environ.get('HYPERFRAMES_BROWSER_PATH') or str(studio_preview.browser_path())
    request = {'cli': str(cli), 'url': record['url'], 'browser': browser,
               'scenes': scenes, 'parameters': parameters}
    plan_meta = read_frontmatter(input_path(documents, 'ANIMATION_PLAN.md'))
    line = lines.frozen(card_state)
    if line or getattr(args, '_evidence_dir', None):
        line = line or lines.select(state)
        request.update(measurements=True, fps=plan_meta.get('fps') or 60)
        if getattr(args, '_evidence_dir', None):
            request['evidence_dir'] = str(args._evidence_dir)
    declared, carry_unverified = {}, []
    if line:
        declared = {}
        cue_path = project / 'runtime/cues.json'
        cues = read_json(cue_path) if cue_path.is_file() else None
        for row in plan_scene_rows(contents['ANIMATION_PLAN.md']).values():
            for segment in row.get('segments', []):
                if not segment['carry']:
                    continue
                try:
                    from visual_plan import plan_cue
                    at = explainer.find_cue(cues, plan_cue(segment['cue']))
                    declared.setdefault(round(at, 6), []).extend(segment['carry'])
                except (ValueError, TypeError, KeyError):
                    carry_unverified.append({'reason': 'carry_cue_unresolved', 'segment': segment['id']})
        request['boundaries'] = list(declared)
    sampled = visual_diagnostics.probe(request, os.environ.get('HYPERFRAMES_NODE', 'node'))
    lock_path = project / 'appearance-lock.json'
    diagnostic_lock = read_json(lock_path) if lock_path.is_file() else {}
    import module_texts
    declared_texts = {json.dumps([item.get('scene'), item.get('asset'), item['id']]): item
                      for sample in sampled['samples'] for item in sample.get('module_texts', [])}
    font_unverified = []
    if module_texts.needs_inventory(project):
        try:
            inventory_result = module_texts.collect(project, scenes, diagnostic_lock)
            for item in inventory_result['items']:
                declared_texts[json.dumps([item.get('scene'), item.get('asset'), item['id']])] = item
            if (inventory_result.get('dom_fonts') or {}).get('coverage') is False:
                font_unverified.append({'reason':'card_font_coverage_failed', **inventory_result['dom_fonts']})
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            font_unverified.append({'reason':'module_text_inventory_unverified', 'detail':str(error)})
    text_samples = [*sampled['samples'], *({'time': item['start'], 'ready': True, 'texts': [item]} for item in declared_texts.values())]
    text = visual_diagnostics.text_diagnostics(text_samples, contents['SCRIPT.md'], contents['RESEARCH.md'],
                                               contents['ANIMATION_PLAN.md'], minimum=args.minimum,
                                               similarity=args.similarity, exceptions=exceptions, scenes=scenes,
                                               scene_ids=sample_scenes, mode=diagnostic_lock.get('mode'),
                                               capabilities=diagnostic_lock.get('capabilities'))
    observed = visual_diagnostics.normalize(''.join(
        item['text'] for sample in sampled['samples'] if sample.get('ready') for item in sample.get('texts', [])))
    static_unverified = [entry for entry in inventory if visual_diagnostics.normalize(entry['text']) not in observed]
    try:
        after = {'input_sha256': preview_input_hashes(documents), 'snapshot_sha256': snapshot_digest(project)}
    except (HarnessError, VisualPlanError, OSError):
        after = None
    report = {'status': 'diagnostic_only' if before == after else 'stale',
              'work': work.name, 'variant': variant.name, 'target': target, **before,
              'parameters': {**parameters, 'minimum': args.minimum, 'similarity': args.similarity},
              'd1': text, 'module_texts': {**module_texts.diagnostics(list(declared_texts.values())), 'unverified': font_unverified},
              'timeline': sampled.get('timeline', []),
              'rhythm': visual_diagnostics.rhythm_diagnostics(sampled['samples'], scenes,
                  plan=contents['ANIMATION_PLAN.md'],
                  cues=read_json(project / 'runtime/cues.json') if (project / 'runtime/cues.json').is_file() else None,
                  mode='talking_head' if state.get('template') == 'talking_head' else diagnostic_lock.get('mode')),
              'samples': sampled['samples'], 'viewport': sampled.get('viewport'),
              'unverified': sampled.get('unverified', []) + carry_unverified + [
                  {'reason': 'finite_sampling_not_full_playback_or_quality_acceptance'},
                  {'reason': 'script_generated_text_between_samples_not_verified',
                   'files': [name for name in dependencies if Path(name).suffix in {'.js', '.mjs'}]},
                  {'reason': 'static_candidates_not_observed_not_screen_text', 'entries': static_unverified}],
              'cross_version_differences': []}
    if line:
        report['fps'] = sampled.get('fps') or plan_meta.get('fps') or 60
        report['still'] = visual_diagnostics.still_diagnostics(sampled['samples'], report['rhythm'], line['thresholds'])
        report['boundaries'] = sorted(set(sampled.get('boundaries', [])) | declared.keys())
        report['carry'] = visual_diagnostics.carry_diagnostics(sampled['samples'], report['boundaries'], fps=report['fps'], declared=declared)
    if diagnostic_lock:
        report['explainer'] = visual_diagnostics.explainer_diagnostics(
            project, dependencies, diagnostic_lock, contents['ANIMATION_PLAN.md'])
    import seek_check
    report['engineering'] = {'findings': seek_check.findings(project, dependencies)}
    if lines.has_check(diagnostic_lock, 'css-contract'):
        import css_contract
        report['css_contract'] = {'findings': css_contract.findings(project, dependencies)}
    if lines.has_check(diagnostic_lock, 'frame-blank'):
        import stage_checks
        report['stage'] = stage_checks.frame_blank(
            sampled['samples'], scenes,
            coverage_min=((line or {}).get('thresholds') or {}).get('stage_coverage_min'))
    if lines.is_math(read_frontmatter(input_path(documents, 'ANIMATION_PLAN.md'))):
        import math_chain
        try:
            report['math'] = {'findings': math_chain.plan_findings(contents['ANIMATION_PLAN.md'],
                explainer.validate_cues(read_json(project / 'runtime/cues.json')),
                max(s['start'] + s['duration'] for s in scenes), scenes=scenes)}
        except ValueError as error:
            raise HarnessError(str(error)) from error
    if lines.has_check(diagnostic_lock, 'english'):
        import english_plan
        cue_path = project / 'runtime/cues.json'
        report['english'] = {'findings': english_plan.check(contents['ANIMATION_PLAN.md'],
            read_json(cue_path) if cue_path.is_file() else None, scenes=scenes)}
    icon_unverified = [{'reason': 'icon_provenance_unverified', 'time': sample['time'],
                        'target': message.removeprefix('SVG image provenance could not be sampled: ')}
                       for sample in sampled['samples'] for message in sample.get('unverified', [])
                       if isinstance(message, str) and message.startswith('SVG image provenance could not be sampled: ')]
    try:
        report['icons'] = {'findings': icon_sets.audit_icons(
            [item for sample in sampled['samples'] for item in sample.get('icons', [])],
            icon_sets.project_packages(project)), 'unverified': icon_unverified}
    except ComponentError as error:
        report['icons'] = {'findings': [], 'unverified': icon_unverified + [{'reason': 'icon_closure_invalid', 'detail': str(error)}]}
    if target != 'current':
        for name, frozen in contents.items():
            current_path = input_path(variant, name)
            if not current_path.is_file() or current_path.read_text(encoding='utf-8-sig') != frozen:
                report['cross_version_differences'].append(name)
    if before != after:
        report['unverified'].append({'reason': 'inputs_changed_during_diagnosis'})
    print_result(root, args, report, report=True)


def command_preview_diff(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=not bool(args.note))
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    preview = variant / "previews" / validate_id(args.preview_id, "preview")
    metadata = preview_metadata(preview)
    assert_preview_inputs(preview, metadata)
    kind = metadata.get("kind", "executable")
    if snapshot_digest(preview / "source-snapshot", kind) != metadata.get("snapshot_sha256"):
        raise HarnessError("Preview snapshot changed")
    with tempfile.TemporaryDirectory() as temp:
        candidate = Path(temp) / "source"
        source = variant / "project" if args.compatible or kind == "reference" else preview_source(variant, metadata)
        source_kind = "executable" if args.compatible or kind == "reference" else kind
        if source_kind == "executable":
            assert_snapshot_source(source)
        copy_snapshot(source, candidate, source_kind)
        changed = source_changes(preview / "source-snapshot", candidate)
    projection = preview / "visual-plan.json"
    scenes = read_json(projection)["scenes"] if projection.is_file() else []
    if args.compatible:
        if preview.name != state.get("accepted_visual_plan") or not args.note or not args.scene:
            raise HarnessError("--compatible requires the accepted Visual Plan, --scene and a checked --note")
        if "input_sha256" not in metadata:
            raise HarnessError("Legacy preview has no frozen inputs for compatibility")
        assert_preview_ready(variant, state)
        if plan_intent(preview / "ANIMATION_PLAN.md") != plan_intent(variant / "ANIMATION_PLAN.md"):
            raise HarnessError("Animation Plan intent changed; confirm the affected Plan instead of --compatible")
        if script_text(preview / "SCRIPT.md", anchors=True) != script_text(input_path(variant, "SCRIPT.md"), anchors=True):
            raise HarnessError("Narration changed; confirm the affected Plan instead of --compatible")
        for name in PREVIEW_DOCUMENTS:
            before, after = read_frontmatter(preview / name), read_frontmatter(input_path(variant, name))
            changed_content = document_content(preview / name, ("revision", "status", "visual_plan")) != document_content(input_path(variant, name), ("revision", "status", "visual_plan"))
            if changed_content and (not isinstance(after.get("revision"), int) or after["revision"] <= before.get("revision", 0)):
                raise HarnessError(f"{name} changed without an increased revision")
        scenes = scene_projection(source, (variant / "ANIMATION_PLAN.md").read_text(encoding="utf-8"))
        outside = [s["id"] for s in scenes if s["source"] in changed
                   and (preview / "source-snapshot" / s["source"]).is_file() and s["id"] not in args.scene]
        if outside:
            raise HarnessError(f"Changed Scene files outside checked scope: {', '.join(outside)}")
    if set(args.scene) - {s["id"] for s in scenes}:
        raise HarnessError("Feedback Scene must exist in this preview")
    selected = [s for s in scenes if s["id"] in args.scene]
    if args.range and kind in {"layout", "reference"}:
        raise HarnessError("Static layout feedback has no time range; use --scene")
    if args.range and (not selected or not min(s["start"] for s in selected) <= args.range[0] <= args.range[1]
                       or args.range[1] > max(s["start"] + s["duration"] for s in selected)):
        raise HarnessError("Feedback range needs a Scene and must lie within the preview")
    if args.note and not args.scene:
        raise HarnessError("Feedback note requires --scene")
    affected = [s["id"] for s in scenes if s["source"] in changed]
    shared = [p for p in changed if p not in {s["source"] for s in scenes}]
    result = {"from": preview.name, "changed_files": changed, "affected_scenes": affected,
              "shared_changes": shared, "requested_scenes": args.scene, "range": args.range,
              "note": args.note or "Shared changes require checking dependent Scenes and handoffs"}
    if args.compatible:
        result.update(compatible=True, baseline_inputs=metadata["input_sha256"], baseline_snapshot=metadata["snapshot_sha256"],
                      current_inputs=preview_input_hashes(variant), current_snapshot=snapshot_digest(source))
    if args.note:
        feedback_path = variant / ".runtime" / "feedback.json"
        feedback = read_json(feedback_path) if feedback_path.exists() else {"entries": []}
        feedback["entries"].append({**result, "recorded_at": now()})
        write_json(feedback_path, feedback)
    print_result(root, args, result)


def measured_process(command: list[str], evidence: Path | None, operation: str, **kwargs: Any) -> subprocess.CompletedProcess:
    if evidence is None:
        return subprocess.run(command, **kwargs)
    telemetry = read_json(evidence) if evidence.is_file() else {"schema_version": 1, "calls": []}
    call = {"operation": operation, "started_at": now(), "state": "running", "launch_attempts": 1,
            "completed_process_calls": 0, "elapsed_seconds": None, "returncode": None,
            "wrapper_retries": 0, "tool_retries": None, "cache_hits": None, "tokens": None, "cost": None}
    telemetry["calls"].append(call)
    write_json(evidence, telemetry)
    started = time.perf_counter()
    try:
        result = subprocess.run(command, **kwargs)
        call.update(completed_process_calls=1, returncode=result.returncode,
                    state="succeeded" if result.returncode == 0 else "failed")
        return result
    except BaseException:
        call["state"] = "interrupted-or-launch-failed"
        raise
    finally:
        call["elapsed_seconds"] = time.perf_counter() - started
        write_json(evidence, telemetry)


def command_preview_render(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    if (not args.final or read_frontmatter(work / "WORK.md").get("purpose") == "test"
            or os.environ.get("HYPERFRAMES_AI_REVIEW") == "1"):
        raise HarnessError("Draft and test video export is forbidden; use Studio")
    require_workflow(work, "hyperframes_video")
    variant, state = selected_variant(root, work, args)
    review = os.environ.get("HYPERFRAMES_AI_REVIEW") == "1"
    assert_preview_ready(variant, state, purpose="plan" if review else "draft")
    if args.fps <= 0:
        raise HarnessError("Render fps must be positive")
    preview_id = validate_id(args.preview_id, "preview")
    expected = state.get("accepted_preview" if args.final else "accepted_visual_plan")
    if preview_id != expected and not review:
        raise HarnessError("Render must start from the accepted Draft (Final) or Visual Plan (Draft)")
    baseline = variant / "previews" / preview_id
    metadata = preview_metadata(baseline)
    if args.final:
        assert_full_draft(metadata)
    assert_preview_inputs(baseline, metadata, variant if args.final else None)
    if args.final or review:
        for field in ("script_revision", "plan_revision"):
            if metadata.get(field) != state.get(field):
                raise HarnessError(f"Render baseline has a stale {field}")
    if snapshot_digest(baseline / "source-snapshot", metadata.get("kind", "executable")) != metadata.get("snapshot_sha256"):
        raise HarnessError("Render baseline snapshot changed")
    source = baseline / "source-snapshot" if args.final or (review and metadata.get("kind", "executable") == "executable") else variant / "project"
    if args.refined_project:
        source = Path(args.refined_project).expanduser().resolve()
        if not source.is_relative_to(variant.resolve()) or source.is_relative_to((variant / "previews").resolve()):
            raise HarnessError("Refined project must be Work-local and outside frozen previews")
    if not args.final and not review:
        assert_plan_baseline(variant, state, baseline, source)
    assert_snapshot_source(source)
    validate_dependencies(source)
    cli = runtime_path(args.hyperframes_cli, "HYPERFRAMES_CLI")
    if not cli.is_file():
        raise HarnessError(f"HyperFrames CLI is missing: {cli}")
    for key in ("HYPERFRAMES_NODE", "HYPERFRAMES_BROWSER_PATH", "HYPERFRAMES_FFMPEG_PATH", "HYPERFRAMES_FFPROBE_PATH"):
        if os.environ.get(key) and not Path(os.environ[key]).is_file():
            raise HarnessError(f"Pinned render dependency is missing: {key}; repair the installation, not the Work")
    output = Path(args.output).expanduser().resolve()
    if review and not output.is_relative_to(variant.resolve()):
        raise HarnessError("Review test renders must stay inside the Review Variant")
    if output.exists():
        raise HarnessError("Render output already exists; choose a new path")
    if output.is_relative_to((variant / "previews").resolve()) or output.is_relative_to((variant / "final").resolve()):
        raise HarnessError("Render outside frozen previews and Final; finalize performs promotion")
    render_id = f"render-{uuid.uuid4().hex[:12]}"
    render_dir = variant / ".runtime" / render_id
    frozen = render_dir / "source-snapshot"
    copy_snapshot(source, frozen)
    validate_snapshot_closure(source, frozen)
    validate_dependencies(frozen)
    source_hash = snapshot_digest(frozen)
    if args.final and source_hash != metadata.get("snapshot_sha256"):
        raise HarnessError("Final source differs from the accepted Draft; register and accept a new Draft")
    command = [os.environ.get("HYPERFRAMES_NODE", "node"), str(cli), "render", "--output", str(output), "--fps", str(args.fps), "--quality", "high" if args.final else "draft"]
    if args.software_gl:
        command.append("--no-browser-gpu")
    result = measured_process(command, render_dir / "telemetry.json", "hyperframes-render",
                              cwd=frozen, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    atomic_write(render_dir / "render.log", result.stdout)
    print(result.stdout, end="")
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise HarnessError(f"HyperFrames render failed ({result.returncode}); diagnostic source retained at {render_dir}")
    if re.search(r"PAGEERROR|sub_timeline_readiness_timeout|Error creating WebGL context", result.stdout):
        raise HarnessError(f"HyperFrames reported a runtime failure despite producing a file; inspect {render_dir / 'render.log'}")
    if snapshot_digest(frozen) != source_hash:
        raise HarnessError("Render source changed during rendering")
    record = {"purpose": "review-test" if review else "final" if args.final else "draft", "source_preview": preview_id,
              "parent_snapshot_sha256": metadata["snapshot_sha256"], "snapshot_sha256": source_hash,
              "source_snapshot": str(frozen.relative_to(variant)), "changed_files": source_changes(baseline / "source-snapshot", frozen),
              "output_sha256": file_sha256(output), "fps": args.fps, "quality": "high" if args.final else "draft",
              "software_gl": args.software_gl, "hyperframes_cli_sha256": file_sha256(cli),
              "script_revision": state["script_revision"], "plan_revision": state["plan_revision"], "rendered_at": now()}
    record["telemetry"] = str((render_dir / "telemetry.json").relative_to(variant))
    if os.environ.get("HYPERFRAMES_AI_RESOLVED_CONFIG"):
        config = json.loads(os.environ["HYPERFRAMES_AI_RESOLVED_CONFIG"])
        record["tool_root"] = str(root)
        record["tool_release"] = os.environ.get("HYPERFRAMES_AI_VERSION")
        record["content_roots"] = {key: config.get(key) for key in ("work_root", "asset_root", "asset_source_roots", "review")}
    if review:
        record["review"] = work_requests.review_identity(configured_work_root(root) or root)
    write_json(render_dir / "render.json", record)
    write_json(variant / ".runtime" / "render.json", record)
    print(str(output))


def move_to_archive(root: Path, work: Path, outcome: str) -> Path:
    write_json(work / ".runtime" / "archive.json", {"outcome": outcome, "archived_at": now(), "soft": True})
    return work


def clear_current_if(root: Path, work_id: str) -> None:
    if read_pointer(root, "current-work") == work_id:
        write_current(root, None, None)


def command_finalize(root: Path, args: argparse.Namespace) -> None:
    _command_finalize(root, args)


def reclaim_final_candidates(variant: Path, completed: Path | None = None, *, apply: bool = True) -> list[str]:
    """Run only under naming_lock; candidates are registered after successful promotion."""
    variant = storage.scoped_path(variant.parent.parent, "variants/" + variant.name)
    runtime = storage.scoped_path(variant, ".runtime")
    registry_path = storage.scoped_path(runtime, "final-candidates.json")
    registry = read_json(registry_path) if registry_path.is_file() else {"schema_version": 1, "entries": []}
    if not isinstance(registry.get("entries"), list) or not all(isinstance(entry, dict) for entry in registry["entries"]):
        raise HarnessError("Invalid Final candidate cleanup registry; retaining temporary files")
    if completed is not None:
        relative = completed.relative_to(runtime).as_posix()
        storage.scoped_path(runtime, relative)
        registry["entries"].append({"path": relative, "state": "succeeded", "rebuildable": True,
                                    "sha256": file_sha256(completed), "registered_at": now()})
        write_json(registry_path, registry)
    final = storage.scoped_path(variant, "final/final.mp4")
    manifest_path = storage.scoped_path(variant, "final/manifest.json")
    if not final.is_file() or not manifest_path.is_file():
        return []
    manifest = read_json(manifest_path)
    digest = file_sha256(final)
    if manifest.get("final_sha256") != digest:
        return []
    if (runtime / "final-promotion/prepared.json").exists():
        return []
    for path in runtime.glob("studio-*.json"):
        storage.scoped_path(runtime, path.relative_to(runtime).as_posix())
        session = read_json(path)
        if session.get("pid") is None or not storage.process_stopped(session["pid"]):
            return []
    manifests = [manifest]
    valid_hashes = {digest}
    for path in (variant / "final/history").glob("*/manifest.json"):
        storage.scoped_path(variant, path.relative_to(variant).as_posix())
        item = read_json(path)
        manifests.append(item)
        video = storage.scoped_path(variant, (path.parent / "final.mp4").relative_to(variant).as_posix())
        if video.is_file() and file_sha256(video) == item.get("final_sha256"):
            valid_hashes.add(item["final_sha256"])
        else:
            raise HarnessError(f"Historical Final is missing or changed; retaining candidates: {video}")
    references = set()
    receipts = [item.get("render", {}) for item in manifests]
    receipts += [read_json(path) for path in runtime.glob("render*/render.json")]
    if (runtime / "render.json").is_file():
        receipts.append(read_json(runtime / "render.json"))
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise HarnessError("Invalid render reference; retaining temporary files")
        source = receipt.get("source_snapshot")
        if source:
            resolved = storage.scoped_path(variant, source)
            if resolved.is_relative_to(runtime):
                references.add(resolved.relative_to(runtime).as_posix())
    removed = []
    for entry in registry["entries"]:
        if entry.get("state") != "succeeded" or entry.get("sha256") not in valid_hashes or entry.get("rebuildable") is not True:
            continue
        candidate = storage.scoped_path(runtime, entry["path"])
        if (candidate.name != "candidate.mp4" or not candidate.parent.name.startswith("finalize-")
                or candidate.parent.parent != runtime or (candidate.parent / "failure.json").exists()
                or not candidate.is_file() or file_sha256(candidate) != entry.get("sha256")):
            continue
        if entry.get("pid") is not None and not storage.process_stopped(entry["pid"]):
            continue
        if any(candidate == storage.scoped_path(runtime, ref) or candidate.is_relative_to(storage.scoped_path(runtime, ref))
               or storage.scoped_path(runtime, ref).is_relative_to(candidate) for ref in references):
            continue
        qa_path = candidate.parent / "qa.json"
        if not qa_path.is_file():
            continue
        qa = read_json(qa_path)
        if qa.get("passed") is not True or qa.get("sha256") != entry.get("sha256"):
            continue
        reclaimed = storage.reclaim(runtime, [entry], references) if apply else [entry["path"]]
        if reclaimed:
            if apply:
                entry.update(state="removed", removed_at=now())
            removed.extend(reclaimed)
    if removed and apply:
        write_json(registry_path, registry)
    return removed


def complete_final_lifecycle(root: Path, work: Path, variant: Path) -> None:
    manifest = read_json(variant / "final/manifest.json")
    receipt = read_json(variant / ".runtime/finalize.json")
    if (receipt.get("final_sha256") != manifest.get("final_sha256")
            or file_sha256(variant / "final/final.mp4") != manifest.get("final_sha256")
            or receipt.get("manifest_sha256") != file_sha256(variant / "final/manifest.json")):
        raise HarnessError("Final recovery receipt does not match the committed video and manifest")
    state = read_json(variant / "variant.yaml")
    state.update(current_final="final.mp4", status="active", wait_for="none", next_action="Revise or archive explicitly")
    write_variant(variant, state)
    import exports
    config = json.loads(os.environ.get('HYPERFRAMES_AI_RESOLVED_CONFIG', '{}'))
    files = {'video': variant / 'final/final.mp4'}
    if state.get('current_cover'):
        files['cover'] = storage.scoped_path(variant, state['current_cover'])
        import cover
        cover.verify(files['cover'].parent)
    try:
        delivery = exports.publish(Path(config.get('export_root', root / 'exports')), work, variant, files,
            series=read_frontmatter(work / 'WORK.md').get('series'), revision=state.get('revision', 1),
            review=os.environ.get('HYPERFRAMES_AI_REVIEW') == '1'
                   or read_frontmatter(work / 'WORK.md').get('purpose') == 'test')
    except (OSError, ValueError) as error:
        write_json(variant / '.runtime/finalize.json', {**receipt, 'state': 'promoted', 'export_error': str(error)})
        raise HarnessError('Video is ready; export copy failed. Retry finalize to copy without rendering: ' + str(error)) from error
    write_json(variant / ".runtime/finalize.json", {**receipt, "state": "complete", "export": delivery})


def preserve_final_history(final_dir: Path) -> None:
    video, manifest = final_dir / "final.mp4", final_dir / "manifest.json"
    if not video.is_file():
        return
    # The receipt is the identity: identical encoded bytes can belong to different Drafts.
    identity = file_sha256(manifest) if manifest.is_file() else "unknown-" + file_sha256(video)
    destination = final_dir / "history" / identity
    if destination.exists():
        if (not (destination / "final.mp4").is_file()
                or file_sha256(destination / "final.mp4") != file_sha256(video)
                or manifest.is_file() and (not (destination / "manifest.json").is_file()
                    or file_sha256(destination / "manifest.json") != identity)):
            raise HarnessError("Historical Final receipt conflict; retaining current Final")
        return
    temporary = destination.with_name(".pending-" + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    try:
        shutil.copy2(video, temporary / "final.mp4")
        if manifest.is_file():
            shutil.copy2(manifest, temporary / "manifest.json")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _command_finalize(root: Path, args: argparse.Namespace) -> None:
    work, location = selected_work(root, args, allow_archive=True)
    if read_frontmatter(work / "WORK.md").get("purpose") == "test":
        raise HarnessError("test Work cannot Finalize or export video")
    variant, state = selected_variant(root, work, args)
    ensure_mutable_work(root, work)
    recover_final_promotion(variant)
    state = read_json(variant / "variant.yaml")
    receipt_path = variant / ".runtime/finalize.json"
    prepared = variant / ".runtime/final-promotion/prepared.json"
    receipt = read_json(receipt_path) if receipt_path.is_file() else {}
    if receipt.get("state") == "promoted" and not prepared.exists():
        if args.final_file and (not Path(args.final_file).is_file()
                               or file_sha256(Path(args.final_file)) != receipt.get("final_sha256")):
            raise HarnessError("Final recovery pending for a different candidate; run finalize without a file, then reopen to export again")
        complete_final_lifecycle(root, work, variant)
        print(str(variant / "final/final.mp4"))
        return
    if receipt.get('state') == 'complete' and not prepared.exists():
        manifest = read_json(variant / 'final/manifest.json')
        same_input = (manifest.get('source_preview') == state.get('accepted_preview')
                      and manifest.get('script_revision') == state.get('script_revision')
                      and manifest.get('plan_revision') == state.get('plan_revision'))
        same_file = not args.final_file or (Path(args.final_file).is_file()
                    and file_sha256(Path(args.final_file)) == receipt.get('final_sha256'))
        if same_input and same_file:
            accepted_path = variant / 'previews' / validate_id(state['accepted_preview'], 'accepted preview')
            assert_preview_inputs(accepted_path, preview_metadata(accepted_path), variant)
            complete_final_lifecycle(root, work, variant)
            print(str(variant / 'final/final.mp4'))
            return
    if variant_lifecycle(work, state) == "archived":
        current = variant / "final/final.mp4"
        if args.final_file and receipt.get("state") == "complete" and current.is_file() and (
                Path(args.final_file).is_file() and file_sha256(Path(args.final_file)) == file_sha256(current)):
            print(str(current))
            return
        raise HarnessError("Reopen this Variant before Finalize")

    if not args.final_file:
        if location == "archive":
            raise HarnessError("Reopen before Finalize")
        accepted = state.get("accepted_preview")
        if not accepted:
            raise HarnessError("No accepted preview")
        job = variant / ".runtime" / f"finalize-{uuid.uuid4().hex[:12]}"
        job.mkdir(parents=True)
        render_args = argparse.Namespace(**vars(args))
        render_args.preview_id, render_args.final = accepted, True
        render_args.output, render_args.refined_project = str(job / "candidate.mp4"), None
        try:
            command_preview_render(root, render_args)
            qa = encoded_video_qa(Path(render_args.output), evidence=job / "telemetry.json")
            write_json(job / "qa.json", qa)
            promote_args = argparse.Namespace(**vars(args))
            promote_args.final_file, promote_args.qa_passed = render_args.output, True
            command_finalize_video(root, promote_args, work, location)
        except (HarnessError, OSError) as exc:
            write_json(job / "failure.json", {"error": str(exc), "at": now()})
            raise HarnessError(f"Finalize failed; inspect failure/recovery evidence at {job}: {exc}") from exc
        try:
            eligible = reclaim_final_candidates(variant, Path(render_args.output), apply=False)
            write_json(job / "cleanup.json", {"reclaimable": eligible, "removed": []})
        except (OSError, HarnessError, storage.StorageError) as exc:
            print(f"Final is complete; temporary cleanup deferred: {exc}", file=sys.stderr)
        return
    command_finalize_video(root, args, work, location)


def encoded_video_qa(candidate: Path, *, evidence: Path | None = None) -> dict[str, Any]:
    probe = os.environ.get("HYPERFRAMES_FFPROBE_PATH", "ffprobe")
    decoder = os.environ.get("HYPERFRAMES_FFMPEG_PATH", "ffmpeg")
    result = measured_process([probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(candidate)],
                              evidence, "ffprobe-qa", check=False, capture_output=True, text=True)
    try:
        metadata = json.loads(result.stdout)
        videos = [stream for stream in metadata["streams"] if stream.get("codec_type") == "video"]
        valid = (result.returncode == 0 and len(videos) == 1 and videos[0].get("width", 0) > 0
                 and videos[0].get("height", 0) > 0 and float(metadata["format"]["duration"]) > 0)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise HarnessError("Encoded output QA failed: invalid video stream or duration")
    decoded = measured_process([decoder, "-v", "error", "-xerror", "-i", str(candidate), "-f", "null", "-"],
                               evidence, "ffmpeg-decode-qa", check=False, capture_output=True, text=True)
    if decoded.returncode or decoded.stderr.strip():
        raise HarnessError(f"Encoded output QA failed during full decode: {decoded.stderr}")
    return {"passed": True, "sha256": file_sha256(candidate), "probe": metadata, "full_decode": True}


FINAL_PROMOTION_FILES = ("final/final.mp4", "final/manifest.json", "variant.yaml", ".runtime/finalize.json", ".runtime/qa/final.json")


def recover_final_promotion(variant: Path) -> None:
    journal = variant / ".runtime/final-promotion"
    if not (journal / "prepared.json").is_file():
        return
    originals = read_json(journal / "prepared.json")
    for name in FINAL_PROMOTION_FILES:
        target = variant / name
        if originals[name]:
            temporary = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}")
            shutil.copy2(journal / name, temporary)
            os.replace(temporary, target)
        else:
            target.unlink(missing_ok=True)
    os.replace(journal / "prepared.json", journal / "restored.json")


def command_finalize_video(
    root: Path, args: argparse.Namespace, work: Path, location: str,
) -> None:
    variant, _ = selected_variant(root, work, args)
    journal = variant / ".runtime" / "final-promotion"
    files = FINAL_PROMOTION_FILES
    recover_final_promotion(variant)
    if journal.exists():
        shutil.rmtree(journal)
    journal.mkdir(parents=True)
    originals = {}
    for name in files:
        source = variant / name
        originals[name] = source.is_file()
        if source.is_file():
            backup = journal / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
    write_json(journal / "prepared.json", originals)
    try:
        _command_finalize_video(root, args, work, location)
        os.replace(journal / "prepared.json", journal / "committed.json")
    except BaseException:
        try:
            recover_final_promotion(variant)
        except OSError as recovery_error:
            raise HarnessError(f"Final promotion recovery pending at {journal}: {recovery_error}") from recovery_error
        raise
    else:
        try:
            shutil.rmtree(journal)
        except OSError:
            pass  # Committed recovery evidence is harmless and cleaned on the next operation.
    complete_final_lifecycle(root, work, variant)
    print(str(variant / "final/final.mp4"))


def _command_finalize_video(
    root: Path,
    args: argparse.Namespace,
    work: Path,
    location: str,
) -> None:
    candidate = Path(args.final_file).expanduser().resolve()
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise HarnessError(f"Final file is missing or empty: {candidate}")
    candidate_digest = file_sha256(candidate)
    variant, state = selected_variant(root, work, args)
    final_dir = variant / "final"
    final_file = final_dir / "final.mp4"
    manifest_path = final_dir / "manifest.json"

    if not args.qa_passed:
        raise HarnessError("Final QA must pass before finalize; use --qa-passed after the required checks")
    accepted = state.get("accepted_preview")
    if not accepted:
        raise HarnessError("No accepted preview")
    if state.get("accepted_script_revision") != state.get("script_revision"):
        raise HarnessError("Accepted preview targets a different Script revision")
    if state.get("accepted_plan_revision") != state.get("plan_revision"):
        raise HarnessError("Accepted preview targets a different Plan revision")
    accepted_path = variant / "previews" / validate_id(str(accepted), "accepted preview")
    if not (accepted_path / "source-snapshot").is_dir():
        raise HarnessError("Accepted preview source snapshot is missing")
    assert_preview_ready(variant, state)
    accepted_metadata = preview_metadata(accepted_path)
    assert_full_draft(accepted_metadata)
    assert_preview_inputs(accepted_path, accepted_metadata, variant)
    accepted_source = accepted_path / "source-snapshot"
    recorded_snapshot_digest = accepted_metadata.get("snapshot_sha256")
    current_snapshot_digest = snapshot_digest(accepted_source)

    render_record = None
    frozen = None
    legacy_compatibility = None
    if state.get("accepted_visual_plan") or accepted_metadata.get("review_mode") == "studio":
        render_record = read_json(variant / ".runtime" / "render.json")
        if (render_record.get("purpose") != "final" or render_record.get("source_preview") != accepted
                or render_record.get("output_sha256") != candidate_digest
                or render_record.get("parent_snapshot_sha256") != recorded_snapshot_digest
                or render_record.get("script_revision") != state.get("script_revision")
                or render_record.get("plan_revision") != state.get("plan_revision")):
            raise HarnessError("Final needs a matching preview render --final result from the accepted Draft")
        frozen = (variant / str(render_record.get("source_snapshot", ""))).resolve()
        if not frozen.is_relative_to((variant / ".runtime").resolve()) or not frozen.is_dir():
            raise HarnessError("Final render source snapshot changed or escaped the Work")
        frozen_snapshot_digest = snapshot_digest(frozen)
        if accepted_metadata.get("review_mode") == "studio" and (
                render_record.get("snapshot_sha256") != recorded_snapshot_digest
                or current_snapshot_digest != recorded_snapshot_digest):
            raise HarnessError("Final source differs from the accepted Studio Draft")
        if current_snapshot_digest == recorded_snapshot_digest:
            if frozen_snapshot_digest != render_record.get("snapshot_sha256"):
                raise HarnessError("Final render source snapshot changed or escaped the Work")
        else:
            if (render_record.get("snapshot_sha256") != recorded_snapshot_digest
                    or render_record.get("changed_files") != []):
                raise HarnessError("Accepted Draft snapshot changed")
            accepted_tree = snapshot_tree_manifest(accepted_source)
            frozen_tree = snapshot_tree_manifest(frozen)
            if accepted_tree != frozen_tree:
                raise HarnessError("Accepted Draft snapshot changed; legacy final-render snapshot differs")
            legacy_compatibility = {
                "schema_version": 1,
                "accepted_preview": accepted,
                "recorded_snapshot_sha256": recorded_snapshot_digest,
                "current_snapshot_sha256": current_snapshot_digest,
                "mirror_snapshot": str(frozen.relative_to(variant)),
                "mirror_current_snapshot_sha256": frozen_snapshot_digest,
                "verified_file_count": len(accepted_tree),
                "basis": "byte-identical accepted and final-render snapshots with an unchanged render receipt",
                "verified_at": now(),
            }
    elif current_snapshot_digest != recorded_snapshot_digest:
        raise HarnessError("Accepted Draft snapshot changed")

    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / "history").mkdir(exist_ok=True)
    current_digest = file_sha256(final_file) if final_file.is_file() else None
    previous = read_json(manifest_path) if manifest_path.is_file() else {}
    changed = (current_digest != candidate_digest or previous.get("source_preview") != accepted
               or previous.get("script_revision") != state.get("script_revision")
               or previous.get("plan_revision") != state.get("plan_revision"))
    if changed:
        preserve_final_history(final_dir)
    if current_digest != candidate_digest:
        staging = final_dir / f".final.staging-{uuid.uuid4().hex}.mp4"
        try:
            shutil.copy2(candidate, staging)
            if file_sha256(staging) != candidate_digest:
                raise HarnessError("Final staging digest mismatch")
            os.replace(staging, final_file)
        finally:
            staging.unlink(missing_ok=True)

    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    registered = (
        manifest.get("schema_version") == 1
        and manifest.get("workflow") == "hyperframes_video"
        and manifest.get("artifacts") == [{"path": "final.mp4", "role": "video", "sha256": candidate_digest}]
        and manifest.get("final_sha256") == candidate_digest
        and manifest.get("source_preview") == accepted
        and manifest.get("script_revision") == state.get("script_revision")
        and manifest.get("plan_revision") == state.get("plan_revision")
        and manifest.get("qa") == "passed"
    )
    if not registered:
        manifest = {
            "schema_version": 1,
            "workflow": "hyperframes_video",
            "artifacts": [{"path": "final.mp4", "role": "video", "sha256": candidate_digest}],
            "final_sha256": candidate_digest,
            "source_preview": accepted,
            "script_revision": state.get("script_revision"),
            "plan_revision": state.get("plan_revision"),
            "finalized_at": now(),
            "qa": "passed",
        }
        if render_record:
            manifest["render"] = render_record
        write_json(manifest_path, manifest)
        write_json(
            variant / ".runtime" / "qa" / "final.json",
            {"passed": True, "final_sha256": candidate_digest, "recorded_at": now()},
        )
    if legacy_compatibility:
        compatibility_path = variant / ".runtime" / "qa" / "legacy-snapshot-compatibility.json"
        compatibility_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(compatibility_path, legacy_compatibility)
    write_json(variant / ".runtime/finalize.json", {
        "state": "promoted", "final_sha256": candidate_digest,
        "manifest_sha256": file_sha256(manifest_path),
    })


def finish_pending_final(root: Path, work: Path, variant: Path) -> None:
    if (variant / ".runtime/final-promotion/prepared.json").exists():
        raise HarnessError("Final promotion recovery pending; retry finalize first")
    path = variant / ".runtime/finalize.json"
    if path.is_file() and read_json(path).get("state") == "promoted":
        complete_final_lifecycle(root, work, variant)


def lifecycle_target(root: Path, work: Path, args: argparse.Namespace) -> Path | None:
    explicit = getattr(args, "variant_id", None) or args.variant_override
    if explicit:
        target = work / "variants" / validate_id(explicit, "variant id")
        if not target.is_dir():
            raise HarnessError(f"Unknown variant: {explicit}")
        return target
    paths = variant_paths(work)
    if len(paths) > 1:
        raise HarnessError("Select --variant-id for a multi-Variant Work; siblings are not changed")
    return paths[0] if paths else None


def command_archive(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args, allow_archive=True)
    ensure_mutable_work(root, work)
    variant = lifecycle_target(root, work, args)
    if variant:
        finish_pending_final(root, work, variant)
        materialize_legacy_lifecycle(work)
        state = read_json(variant / "variant.yaml")
        state.update(lifecycle="archived", archive_outcome=args.outcome, archived_at=now())
        write_variant(variant, state)
        sync_work_lifecycle(root, work)
    else:
        move_to_archive(root, work, args.outcome)
    print(str(work))


def command_reopen(root: Path, args: argparse.Namespace) -> None:
    work, _ = locate_work(root, args.work_id)
    ensure_mutable_work(root, work)
    variant = lifecycle_target(root, work, args)
    if variant and read_json(variant / 'variant.yaml').get('retirement'):
        raise HarnessError('A retired Variant cannot be reopened')
    if variant:
        finish_pending_final(root, work, variant)
    materialize_legacy_lifecycle(work)
    if variant:
        state = read_json(variant / "variant.yaml")
        state.update(lifecycle="active")
        write_variant(variant, state)
        args.variant_override = variant.name
    sync_work_lifecycle(root, work)
    if (work / ".runtime/parked.json").exists() or work.parent.name == "parked":
        restore_parked_work(root, work)
    focus_work(root, work, args)
    print(str(work))


def add_variant_options(parser: argparse.ArgumentParser) -> None:
    accounts = parser.add_mutually_exclusive_group()
    accounts.add_argument('--account')
    accounts.add_argument('--no-account', action='store_true', help='Explicitly skip the account layer')
    parser.add_argument("--batch")
    parser.add_argument("--theme")
    parser.add_argument("--background", help="accepted background id@vN")
    parser.add_argument("--appearance-file", help="JSON selections, motion slots and parameter overrides")
    parser.add_argument('--overrides', help='JSON Variant presentation overrides; replaces this layer, {} clears it')
    parser.add_argument("--fps", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--design", help="Design card id: " + ", ".join(designs.DESIGN_IDS))
    parser.add_argument("--mode", help="Legacy design alias; retired identities reselect")
    parser.add_argument("--submodule", help="Showcase submodule; fixed to pdoom for the pdoom design")
    parser.add_argument("--captions", choices=("on", "off"), help="Variant captions frozen in the appearance lock")
    parser.add_argument("--template", choices=sorted(TEMPLATES))
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--ratio", choices=sorted(RATIOS))
    parser.add_argument("--subject-position", choices=sorted(SUBJECT_POSITIONS))


def command_review_init(root: Path, args: argparse.Namespace) -> None:
    print(work_requests.init_review(configured_work_root(root) or root, args.review_id))


def command_request(root: Path, args: argparse.Namespace) -> None:
    store = configured_work_root(root) or root
    action = args.request_command
    if action == "freeze":
        work, _ = selected_work(root, args, allow_archive=True)
        variant, _ = selected_variant(root, work, args)
        with naming_lock(root):
            result = work_requests.freeze(store, work, variant, args.request_id, Path(args.brief), args.scene,
                                          args.file, args.context_file, args.preview)
    else:
        revision = Path(args.revision).expanduser().resolve()
        if action == "export":
            result = work_requests.export_request(revision, Path(args.output).expanduser().resolve())
        elif action == "deliver":
            result = work_requests.deliver(revision, args.delivery_id, Path(args.source).expanduser().resolve(),
                                          Path(args.component).resolve() if args.component else None,
                                          Path(args.binding).resolve() if args.binding else None)
        else:
            delivery = Path(args.delivery).expanduser().resolve()
            if action == "review":
                result = work_requests.review(store, revision, delivery, read_json, write_variant)
            elif action == "feedback":
                request, candidate = work_requests.checked_pair(revision, delivery)
                result = revision.parent / "feedback" / f"{uuid.uuid4().hex}.json"
                write_json(result, {"request_id": request["request_id"], "revision": request["revision"],
                                    "delivery_id": candidate["delivery_id"], "delivery_sha256": file_sha256(delivery / "delivery.json"),
                                    "note": args.note, "recorded_at": now()})
            else:
                if not revision.is_relative_to(store / "requests"):
                    raise HarnessError("Accept the handoff in the production WorkStore requests directory")
                work, _ = selected_work(root, args)
                variant, _ = selected_variant(root, work, args)
                result = work_requests.accept(store, revision, delivery, variant,
                                              Path(args.approved_component).resolve() if args.approved_component else None)
    print(str(result))


def critic_memory(root, preview, metadata, staging):
    storage.scoped_path(configured_work_root(root) or root, preview.relative_to(configured_work_root(root) or root).as_posix())
    reference_hash = metadata.get('reference_memory_sha256')
    if reference_hash:
        manifest = visual_memory.copy_frozen(preview / 'reference-memory', staging / 'reference-memory', reference_hash)
        references = manifest['references']
        seeds = manifest['seeds']
    else:
        references = []
        ids = {ref.removeprefix('跨线:') for ref in visual_memory.references((preview / 'ANIMATION_PLAN.md').read_text(encoding='utf-8'))}
        seeds = [item for item in lines.catalogue('mechanisms')['mechanisms'] if item['id'] in ids]
    state = metadata.get('adopted_settings', {})
    line = visual_memory.line_id(state)
    base = configured_work_root(root) or root
    defects = [item for item in visual_memory.entries(base, 'defect', line) if item['status'] == '有效']
    copied = []
    for index, item in enumerate(defects):
        visual_memory.verify_frames(visual_memory.library(base, 'defect'), item['frames'])
        frames = []
        for offset, frame in enumerate(item['frames']):
            name = f'defect-{index:03d}-{offset:03d}.png'
            shutil.copyfile(storage.scoped_path(visual_memory.library(base, 'defect'), frame['path']), staging / name)
            frames.append({**frame, 'path': name})
        visual_memory.verify_frames(staging, frames)
        copied.append({**item, 'frames': frames})
    checks = (lines.frozen(state) or lines.select(state))['critic_checks']
    visual_memory.write(staging / 'memory.json', {'references': references, 'reference_frame_root': 'reference-memory',
        'seeds': seeds, 'profile_checks': checks, 'known_defects': copied,
        'unverified': [] if reference_hash else ['historical_draft_references_not_frozen']})
    return {'reference_ids': [item['id'] for item in references], 'defect_ids': [item['id'] for item in defects]}


def command_critic_round(root, args):
    from contextlib import redirect_stdout
    import io
    if not args.work_override or not args.variant_override:
        raise HarnessError('Critic requires explicit --work and --variant')
    work, _ = selected_work(root, args)
    require_workflow(work, 'hyperframes_video')
    variant, state = selected_variant(root, work, args)
    if args.automatic and not workflow_for(variant, state)['values']['draft_review']['enabled']:
        print_result(root, args, {'status': 'disabled', 'advisory_only': True})
        return
    effective = effective_settings(root, state)
    ledger_path = variant / 'critic' / 'ledger.json'
    ledger = read_json(ledger_path) if ledger_path.is_file() else {'rounds': []}
    prior = critic.pending_issues(ledger['rounds'])
    automatic = len(ledger['rounds']) < effective['critic.max_rounds']['value']
    if args.automatic and not automatic:
        print_result(root, args, {'status': 'round_limit', 'message': 'Automatic limit reached; a manual critic round remains available'})
        return
    target = args.preview_id
    if target is None:
        register = SimpleNamespace(**{**vars(args), 'purpose': 'draft', 'kind': 'executable', 'scope': 'full',
            'scene': [], 'sample_dir': None, 'draft_file': None, 'media_readiness': 'complete', '_effective_settings': effective})
        with redirect_stdout(io.StringIO()) as output:
            command_preview_register(root, register)
        target = output.getvalue().strip()
    preview, metadata = checked_preview(variant, validate_id(target, 'Draft'))
    assert_full_draft(metadata)
    if metadata.get('kind', 'executable') != 'executable':
        raise HarnessError('Critic requires an executable Draft')
    assert_preview_inputs(preview, metadata)
    opener = SimpleNamespace(**{**vars(args), 'preview_id': target, 'legacy': False, 'no_open': True,
                               'hyperframes_dist': None, 'port': 0})
    with redirect_stdout(io.StringIO()):
        command_preview_open(root, opener)
    directory = variant / 'critic'
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory) as temp:
        staging = Path(temp) / 'bundle'
        staging.mkdir()
        diagnostic = SimpleNamespace(**{**vars(args), 'preview_id': target, 'json': True, '_evidence_dir': staging / 'images',
            'minimum': 20, 'similarity': .8, 'exceptions': None})
        with redirect_stdout(io.StringIO()) as output:
            command_preview_diagnose(root, diagnostic)
        report = json.loads(output.getvalue())
        number = len(ledger['rounds']) + 1
        name = f'round-{number:03d}'
        entry = {'round': number, 'draft_id': target, 'snapshot_sha256': metadata['snapshot_sha256'],
                 'input_sha256': metadata.get('input_sha256'), 'settings': effective, 'package': name,
                 'previous_issues': prior, 'created_at': now(),
                 'historical_issue_ids': [item['id'] for row in ledger['rounds'] for item in row.get('verdict', {}).get('new_issues', [])]}
        rows = plan_scene_rows((preview / 'ANIMATION_PLAN.md').read_text(encoding='utf-8'))
        direction = {sid: {'brief': row.get('brief', {}), 'segments': row.get('segments', []), 'exceptions': row['exceptions']} for sid, row in rows.items()}
        try:
            entry.update(critic_memory(root, preview, metadata, staging))
            if metadata.get('reference_memory_sha256'):
                frozen_settings = visual_memory.frozen(preview / 'reference-memory', metadata['reference_memory_sha256'])['input']['settings']
                entry['settings'] = {**effective, **frozen_settings}
            entry['files'] = critic.package(staging, report, direction, prior, entry)
        except ValueError as error:
            raise HarnessError(str(error)) from error
        with naming_lock(root):
            current = read_json(ledger_path) if ledger_path.is_file() else {'rounds': []}
            if current != ledger:
                raise HarnessError('Critic ledger changed during sampling; retry the round')
            _, final_metadata = checked_preview(variant, target)
            if final_metadata != metadata:
                raise HarnessError('Draft changed during critic round')
            staging.rename(directory / name)
            ledger['rounds'].append(entry)
            try:
                write_json(ledger_path, ledger)
            except Exception:
                shutil.rmtree(directory / name)
                raise
    result = {'round': number, 'draft_id': target, 'package': str(directory / name), 'settings': entry['settings'],
              'visual_review': 'unverified',
              'human_checks': ['Inspect image evidence or supply verified image-capable review', 'Watch motion and listen to audio'],
              'automatic_critic': effective['critic.provider']['value'] != 'off' and (automatic or not args.automatic)}
    if effective['critic.provider']['value'] != 'off':
        result['prompt'] = str(directory / name / 'PROMPT.md')
    print_result(root, args, result)


def command_critic_record(root, args):
    if not args.work_override or not args.variant_override:
        raise HarnessError('Critic requires explicit --work and --variant')
    work, _ = selected_work(root, args)
    require_workflow(work, 'hyperframes_video')
    variant, _ = selected_variant(root, work, args)
    with naming_lock(root):
        path = variant / 'critic' / 'ledger.json'
        ledger = read_json(path)
        value = read_json(Path(args.file))
        if not ledger['rounds']:
            raise HarnessError('No critic round to record')
        entry = ledger['rounds'][-1]
        if 'verdict' in entry:
            raise HarnessError('This round already has a verdict')
        try:
            package_path = storage.scoped_path(variant, 'critic/' + validate_id(entry['package'], 'critic package'))
            if critic.hashes(package_path) != entry['files']:
                raise ValueError('Critic evidence package changed')
            _, metadata = checked_preview(variant, entry['draft_id'])
            if metadata['snapshot_sha256'] != entry['snapshot_sha256'] or metadata.get('input_sha256') != entry['input_sha256']:
                raise ValueError('Critic Draft changed')
            entry['verdict'] = critic.validate_verdict(value, entry)
        except ValueError as error:
            raise HarnessError(str(error)) from error
        write_json(path, ledger)
    print_result(root, args, {'round': entry['round'], 'recorded': True, 'advisory_only': True})


def effective_settings(root, state):
    path = runtime_root(root) / 'settings.json'
    try:
        return work_settings.effective(state, read_json(path) if path.is_file() else {})
    except ValueError as error:
        raise HarnessError(str(error)) from error


def command_settings(root, args):
    variant, state = None, {}
    if args.layer == 'variant' or args.work_override or args.variant_override:
        work, _ = selected_work(root, args)
        require_workflow(work, 'hyperframes_video')
        variant, state = selected_variant(root, work, args)
    path = runtime_root(root) / 'settings.json'
    if args.settings_command != 'show':
        if args.layer == 'variant' and not state.get('line') and not args.key.startswith('samples.'):
            raise HarnessError('Legacy Variant settings are unchanged; no implicit migration')
        with naming_lock(root):
            if args.layer == 'variant':
                state = read_json(variant / 'variant.yaml')
            values = dict(state.get('settings', {})) if args.layer == 'variant' else read_json(path) if path.is_file() else {}
            try:
                if args.key not in lines.catalogue('settings')['keys']:
                    raise ValueError('Unknown setting: ' + args.key)
                if args.settings_command == 'set':
                    try:
                        value = json.loads(args.value)
                    except ValueError:
                        value = args.value
                    work_settings.validate({args.key: value}, args.layer)
                    values[args.key] = value
                else:
                    values.pop(args.key, None)
                work_settings.validate(values, args.layer, legacy=True)
            except ValueError as error:
                raise HarnessError(str(error)) from error
            if args.layer == 'variant':
                state['settings'] = values
                write_variant(variant, state)
            else:
                write_json(path, values)
    result = {'schema': lines.catalogue('settings'), 'line': state.get('line'),
              'values': effective_settings(root, state) if variant else {},
              'user': read_json(path) if path.is_file() else {}}
    print_result(root, args, result)


def cover_recipe(state: dict, explicit: dict | None = None) -> dict:
    if not state.get('account') and explicit is None and not state.get('cover_recipe'):
        raise HarnessError('Cover requires an account recipe or an explicit task recipe')
    values = state.get('design_values', {})
    recipe = {key.removeprefix('cover.'): value for key, value in values.items()
              if key.startswith('cover.') and key.removeprefix('cover.') in
              {'width', 'height', 'font', 'logo', 'background_image', 'font_size', 'color', 'background_color'}}
    if 'background_image' in recipe:
        recipe['background'] = recipe.pop('background_image')
    return {**recipe, **state.get('cover_recipe', {}), **(explicit or {})}


def render_variant_cover(variant: Path, state: dict, title: str, explicit=None, browser=None) -> dict:
    import cover
    recipe = cover_recipe(state, explicit)
    result = cover.render(variant, title, recipe, node=os.environ.get('HYPERFRAMES_NODE', 'node'), browser=browser)
    state.update(current_cover=(Path(result['path']) / 'cover.png').relative_to(variant).as_posix(),
                 cover_title=title, cover_recipe=recipe, cover_id=result['id'])
    state.pop('cover_issue', None)
    write_variant(variant, state)
    return result


def prepare_draft_cover(variant: Path, state: dict) -> None:
    # Historical Variants do not acquire a new cover task from today's defaults.
    if not (state.get('design_snapshot') or state.get('design_live')) or not state.get('design_values', {}).get('cover.enabled', True):
        return
    try:
        title = state.get('cover_title')
        if not title:
            raise HarnessError('Cover title is not adopted; use cover render --title with the chosen packaging text')
        render_variant_cover(variant, state, title)
    except (HarnessError, ValueError, OSError, subprocess.SubprocessError) as error:
        state['cover_issue'] = str(error)
        for key in ('current_cover', 'cover_id', 'accepted_cover'):
            state.pop(key, None)
        write_variant(variant, state)
        print('Cover incomplete: ' + str(error), file=sys.stderr)


def command_cover(root: Path, args: argparse.Namespace) -> None:
    import cover
    work, _ = selected_work(root, args)
    variant, state = selected_variant(root, work, args)
    ensure_mutable_work(root, work)
    if args.cover_command == 'render':
        explicit = read_json(Path(args.recipe)) if args.recipe else None
        result = render_variant_cover(variant, state, args.title, explicit, args.browser)
        print_result(root, args, result)
    else:
        import exports
        if not state.get('current_cover'):
            raise HarnessError('No rendered cover; run cover render first')
        cover.verify(storage.scoped_path(variant, state['current_cover']).parent)
        config = json.loads(os.environ.get('HYPERFRAMES_AI_RESOLVED_CONFIG', '{}'))
        report = exports.publish(Path(config.get('export_root', root / 'exports')), work, variant,
            {'cover': storage.scoped_path(variant, state['current_cover'])},
            series=read_frontmatter(work / 'WORK.md').get('series'), revision=state.get('revision', 1),
            review=os.environ.get('HYPERFRAMES_AI_REVIEW') == '1' or read_frontmatter(work / 'WORK.md').get('purpose') == 'test')
        print_result(root, args, report)


def command_workflow(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    variant, state = selected_variant(root, work, args)
    metadata = read_frontmatter(work / 'WORK.md')
    if args.workflow_command == 'put':
        ensure_mutable_work(root, work)
        values = read_json(Path(args.file))
        workflow_config.validate(values, args.layer)
        if args.layer == 'variant':
            state['workflow_settings'] = values
            write_variant(variant, state)
        else:
            metadata['workflow_settings'] = values
            atomic_write(work / 'WORK.md', '---\n' + json.dumps(metadata, ensure_ascii=False) + '\n---\n'
                         + document_body(work / 'WORK.md'))
    report = workflow_config.resolve(metadata, state)
    if args.workflow_command == 'stage':
        report['stage'] = args.stage
        card = lines.frozen(state) or lines.select(state)
        report['files'] = workflow_config.recipes(card, args.stage,
            metadata.get('series_stages', {}), {args.stage: args.skill} if args.skill is not None else {})
        if state.get('design_live') or state.get('design_files'):
            prefix = '.studio/designs/' + card['id'] + '/'
            own = set(card.get('stages', {}).get(args.stage, []))
            base = (storage.scoped_path(variant, state['design_files']['path']) / 'card'
                    if state.get('design_files') else designs.card_path(card['id']))
            report['files'] = [str(storage.scoped_path(base, name.removeprefix(prefix)))
                               if name.startswith(prefix) or name in own and not name.startswith('.studio/')
                               else name for name in report['files']]
    print_result(root, args, report)


def command_workflow_advance(root: Path, args: argparse.Namespace) -> None:
    work, _ = selected_work(root, args)
    require_workflow(work, 'hyperframes_video')
    variant, state = selected_variant(root, work, args)
    if args.stage == 'draft':
        if not args.draft:
            raise HarnessError('Draft advancement requires --draft with the reviewed snapshot ID')
        _, metadata = checked_preview(variant, args.draft)
        if metadata.get('snapshot_sha256') != args.sha256:
            raise HarnessError('Draft changed; advance the exact reviewed snapshot')
        args.draft_id = args.draft
        command_preview_accept(root, args)
        return
    path = input_path(variant, 'SCRIPT.md') if args.stage == 'script' else variant / 'ANIMATION_PLAN.md'
    digest = file_sha256(path)
    if digest != args.sha256:
        raise HarnessError('Input changed; advance the exact reviewed file SHA-256')
    if args.stage == 'plan':
        if read_frontmatter(path).get('revision') != state.get('plan_revision'):
            raise HarnessError('Refresh the current Plan revision before advancing')
    owner = read_frontmatter(work / 'WORK.md') if args.stage == 'script' else state
    key = path.relative_to(work).as_posix()
    records = owner.setdefault('confirmations', {})
    record = {'sha256': digest, 'revision': read_frontmatter(path).get('revision')}
    unchanged = records.get(key) == record
    if not unchanged:
        records[key] = record
        if args.stage == 'script':
            atomic_write(work / 'WORK.md', '---\n' + json.dumps(owner, ensure_ascii=False) + '\n---\n' + document_body(work / 'WORK.md'))
        else:
            write_variant(variant, owner)
    print_result(root, args, {'stage': args.stage, **record, 'status': 'unchanged' if unchanged else 'advanced'})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="work", description="Local creative Work lifecycle")
    parser.add_argument('--context', default=os.environ.get('HYPERFRAMES_CONTEXT', 'default'),
                        help='Named Work/Variant context for this agent session')
    parser.add_argument("--work", dest="work_override", help="temporarily select a Work")
    parser.add_argument("--variant", dest="variant_override", help="temporarily select a Variant")
    commands = parser.add_subparsers(dest="command", required=True)
    work_memory.add_commands(commands, SimpleNamespace(**globals()))
    content_retro.add_commands(commands, SimpleNamespace(**globals()))
    critic_parser = commands.add_parser('critic', help='Freeze and sample a Draft; record advisory visual review')
    critic_commands = critic_parser.add_subparsers(dest='critic_command', required=True)
    critic_round = critic_commands.add_parser('round')
    critic_round.add_argument('preview_id', nargs='?')
    critic_round.add_argument('--automatic', action='store_true', help='Respect the automatic round limit')
    critic_round.add_argument('--hyperframes-cli')
    critic_round.add_argument('--browser')
    critic_round.add_argument('--step', type=float, default=.5)
    critic_round.add_argument('--width', type=int, default=960)
    critic_round.add_argument('--timeout-ms', type=int, default=5000)
    critic_round.set_defaults(handler=command_critic_round)
    critic_record = critic_commands.add_parser('record')
    critic_record.add_argument('--file', required=True, help='Verdict JSON for the latest round')
    critic_record.set_defaults(handler=command_critic_record)
    switches = commands.add_parser('settings', help='Product-line defaults and per-command user/Variant switches')
    switch_commands = switches.add_subparsers(dest='settings_command', required=True)
    for operation in ('show', 'set', 'unset'):
        switch = switch_commands.add_parser(operation)
        switch.add_argument('--layer', choices=('user', 'variant'), default='variant')
        if operation != 'show':
            switch.add_argument('key')
        if operation == 'set':
            switch.add_argument('value', help='JSON boolean/integer or string')
        switch.set_defaults(handler=command_settings)

    cover = commands.add_parser('cover', help='Render or independently export the frozen account cover recipe')
    cover_commands = cover.add_subparsers(dest='cover_command', required=True)
    cover_render = cover_commands.add_parser('render')
    cover_render.add_argument('--title', required=True)
    cover_render.add_argument('--recipe', help='Explicit recipe field overrides for this Variant')
    cover_render.add_argument('--browser')
    cover_render.set_defaults(handler=command_cover)
    cover_commands.add_parser('export').set_defaults(handler=command_cover)
    flow = commands.add_parser('workflow', help='Independent human gates and stage-scoped guidance')
    flow_commands = flow.add_subparsers(dest='workflow_command', required=True)
    advance = flow_commands.add_parser('advance', help='Advancing confirms only the exact reviewed input')
    advance.add_argument('stage', choices=('script', 'plan', 'draft'))
    advance.add_argument('--sha256', required=True)
    advance.add_argument('--draft')
    advance.set_defaults(handler=command_workflow_advance)
    flow_commands.add_parser('show').set_defaults(handler=command_workflow)
    flow_put = flow_commands.add_parser('put')
    flow_put.add_argument('--layer', choices=('work', 'variant'), required=True)
    flow_put.add_argument('--file', required=True)
    flow_put.set_defaults(handler=command_workflow)
    stage = flow_commands.add_parser('stage')
    stage.add_argument('stage', choices=workflow_config.STAGES)
    stage.add_argument('--skill', action='append', help='Explicit guidance files for this stage invocation')
    stage.set_defaults(handler=command_workflow)
    new = commands.add_parser("new")
    new.add_argument("title")
    new.add_argument("--purpose", choices=("standard", "ip", "test"))
    new.add_argument("--series")
    new.add_argument("--source-work")
    new.add_argument("--source-variant")
    new.add_argument("--source-version")
    new.add_argument("--variant-id", help="ID for an optional initial video Variant (requires --account for production)")
    new.add_argument("--workflow", choices=sorted(WORKFLOWS), required=True)
    new.add_argument("--detached", action="store_true", help="create without changing the foreground Current Work")
    new.add_argument("--separate", action="store_true", help="Create a separate test Work with the same name")
    add_variant_options(new)
    new.set_defaults(handler=command_new)

    commands.add_parser("current").set_defaults(handler=command_current)
    listing = commands.add_parser("list")
    listing.add_argument("--tree", action="store_true")
    listing_scope = listing.add_mutually_exclusive_group()
    listing_scope.add_argument("--all", action="store_true")
    listing_scope.add_argument("--archived", action="store_true")
    listing.set_defaults(handler=command_list)
    browser = commands.add_parser("browser", help="Rebuild the disposable WorkStore directory")
    browser.add_argument("action", choices=("rebuild",))
    browser.set_defaults(handler=command_browser_rebuild)
    storage_parser = commands.add_parser("storage", help="On-demand Work capacity and conservative candidate cleanup")
    storage_commands = storage_parser.add_subparsers(dest="storage_command", required=True)
    for operation in ("inspect", "cleanup"):
        storage_command = storage_commands.add_parser(operation)
        storage_command.add_argument("--apply", action="store_true", help="Actually reclaim eligible candidates (cleanup only)")
        storage_command.set_defaults(handler=command_storage)
    find = commands.add_parser("find", help="Find video Variants by series number")
    find.add_argument("--series", required=True)
    find.add_argument("--number", type=int, required=True)
    find.add_argument("--account")
    find.add_argument("--history", action="store_true", help="Show the retained succession chain")
    find.set_defaults(handler=command_find)
    successor = commands.add_parser("successor", help="Adopt an archived accepted video into a new Work at the same series number")
    successor.add_argument("source_work")
    successor.add_argument("--source-variant", required=True)
    successor.add_argument("--source-version", required=True)
    successor.add_argument("--account", required=True)
    successor.add_argument("--variant-id", default="main")
    successor.add_argument("--title")
    successor.add_argument("--detached", action="store_true")
    successor.set_defaults(handler=command_successor)
    migrate = commands.add_parser("migrate", help="One-time RC2 video identity migration")
    migrations = migrate.add_subparsers(dest="migrate_command", required=True)
    design_migrate = migrations.add_parser('design', help='Explicitly map one historical Variant without renaming content')
    add_variant_options(design_migrate)
    design_migrate.add_argument('--design-version', required=True, type=int)
    design_migrate.add_argument('--source-sha256')
    design_migrate.add_argument('--apply', action='store_true')
    design_migrate.set_defaults(handler=command_design_migrate)
    retire = migrations.add_parser('retire', help='Stop new production while preserving all historical files')
    retire.add_argument('--note', required=True)
    retire.add_argument('--source-sha256')
    retire.add_argument('--apply', action='store_true')
    retire.set_defaults(handler=command_design_migrate)
    dry_run = migrations.add_parser("dry-run")
    dry_run.add_argument("--title-overrides", help="JSON map of old Work ID to semantic title")
    dry_run.add_argument("--purpose-overrides", help="JSON map of old Work ID to explicit purpose")
    dry_run.add_argument("--only", action="append", help="Migrate a safe Work subset; repeat for multiple IDs")
    dry_run.add_argument("--output", help="Write the exact mapping for later apply")
    dry_run.set_defaults(handler=command_migrate)
    apply = migrations.add_parser("apply")
    apply.add_argument("--mapping", required=True, help="Mapping produced by migrate dry-run")
    apply.set_defaults(handler=command_migrate)
    layout = migrations.add_parser("layout", help="Move Works into works/<series>/ and series rules into the series folder; dry-run unless --apply")
    layout.add_argument("--apply", action="store_true")
    layout.set_defaults(handler=command_migrate_layout)
    research_catalog.register_cli(commands)
    appearance_parser = commands.add_parser("appearance", help="Resolve or explicitly rebind exact appearance assets")
    appearance_commands = appearance_parser.add_subparsers(dest="appearance_command", required=True)
    resolve = appearance_commands.add_parser("resolve")
    add_variant_options(resolve)
    resolve.set_defaults(handler=command_appearance_resolve)
    rebind = appearance_commands.add_parser("rebind", help="Preview an exact Variant update; --apply commits it")
    add_variant_options(rebind)
    rebind.add_argument("--apply", action="store_true")
    rebind.add_argument("--upgrade-runtime", action="store_true", help="Upgrade a known old runtime in the editable project only")
    rebind.set_defaults(handler=command_appearance_update)
    recover = appearance_commands.add_parser("recover", help="Recover a pending update of the explicit Work/Variant")
    recover.add_argument("--sync-checks", action="store_true", help="Repair added-check-only lock drift from Variant, preserving appearance and acceptance")
    recover.set_defaults(handler=command_appearance_update)
    for kind in ("account", "series", "theme"):
        config_parser = commands.add_parser(kind)
        operations = config_parser.add_subparsers(dest="operation", required=True)
        for operation in ("put", "get", "list"):
            operation_parser = operations.add_parser(operation)
            if operation != "list":
                operation_parser.add_argument("identity")
            if operation == "put":
                operation_parser.add_argument("--file", required=True, help="JSON file, or - for stdin")
            operation_parser.set_defaults(handler=command_config)
        if kind == "series":
            rules = operations.add_parser("rules", help="Read or replace the series AGENTS.md rules by series identity")
            rules_operations = rules.add_subparsers(dest="rules_operation", required=True)
            rules_show = rules_operations.add_parser("show")
            rules_show.add_argument("identity")
            rules_put = rules_operations.add_parser("put")
            rules_put.add_argument("identity")
            rules_put.add_argument("--file", required=True, help="Rules Markdown file, or - for stdin")
            rules_operations.add_parser("delete", help="Remove the current rules; the text is kept in rules history").add_argument("identity")
            rules.set_defaults(handler=command_series_rules)
            delete = operations.add_parser("delete", help="Retire a series that no Work references; config, history and rules are archived")
            delete.add_argument("identity")
            delete.set_defaults(handler=command_series_delete)
            move = operations.add_parser("move", help="Move the selected production video Work to another series")
            move.add_argument("identity")
            move.set_defaults(handler=command_series_move)
    root_command = commands.add_parser("root", help="Show or set the external WorkStore root")
    root_commands = root_command.add_subparsers(dest="root_command", required=True)
    root_commands.add_parser("show").set_defaults(handler=command_root_show)
    root_set = root_commands.add_parser("set")
    root_set.add_argument("path")
    root_set.set_defaults(handler=command_root_set)
    name = commands.add_parser("name")
    name.add_argument("title")
    name.set_defaults(handler=command_name)
    use = commands.add_parser("use")
    use.add_argument("work_id")
    use.set_defaults(handler=command_use)
    commands.add_parser("status").set_defaults(handler=command_status)
    plan = commands.add_parser("plan")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    plan_commands.add_parser("refresh", help="Refresh CLI metadata without approving changed content").set_defaults(handler=command_plan_refresh)
    plan_commands.add_parser("check", help="Report mode-aware engineering and mathematical Plan findings").set_defaults(handler=command_plan_check)

    math_command = commands.add_parser('math', help='Build Plan-owned mathematical diagrams')
    math_commands = math_command.add_subparsers(dest='math_command', required=True)
    math_builder = math_commands.add_parser('build')
    math_builder.add_argument('--project', help='Editable sample inside a registered AssetSource')
    math_builder.add_argument('--plan', help='Standalone sample Plan path')
    math_builder.add_argument('--purpose', choices=('plan', 'draft'), default='draft', help='Build a direction reference before Plan approval, or an approved Draft')
    math_builder.add_argument('--scene', action='append', help='Build exactly one Plan Scene reference; HTML must contain only this Scene')
    math_builder.add_argument('--browser', help='Chromium executable for glyph and geometry checks')
    math_builder.set_defaults(handler=command_math)

    showcase = commands.add_parser('showcase', help='Optional independent stage and white-background cast tools')
    showcase_commands = showcase.add_subparsers(dest='showcase_command', required=True)
    for operation in ('stage', 'cast'):
        tool = showcase_commands.add_parser(operation)
        tool.add_argument('--output', required=True, help='Generated directory relative to this Variant project')
        tool.add_argument('--overwrite', action='store_true', help='Replace only intact tool-owned generated output')
        if operation == 'cast':
            tool.add_argument('--input', required=True, help='Source image relative to this Work')
            tool.add_argument('--kind', choices=('sheet', 'pose'), default='sheet')
            tool.add_argument('--target-height', type=int, default=640)
            tool.add_argument('--border', type=int, default=9)
            tool.add_argument('--pose-scale', type=float, default=1.18)
        tool.set_defaults(handler=command_showcase)

    speech = commands.add_parser('tts', help='Generate speech candidates and adopt measured aligned formal audio')
    speech_commands = speech.add_subparsers(dest='tts_command', required=True)
    generate = speech_commands.add_parser('generate')
    generate.add_argument('--config', help='TTS provider configuration JSON; default Volcengine')
    generate.add_argument('--anchor', action='append', help='Generate only these Script anchors; omission generates all')
    generate.set_defaults(handler=command_tts)
    batch = speech_commands.add_parser('import-batch', help='Validate external batch results and build a complete speech candidate')
    batch.add_argument('batch', help='Batch manifest JSON with all current Script anchors')
    batch.add_argument('--config', help='Exact TTS provider configuration used for the batch')
    batch.set_defaults(handler=command_tts)
    adopt = speech_commands.add_parser('adopt')
    adopt.add_argument('candidate', help='Full candidate SHA-256 returned by generate')
    adopt.add_argument('--alignment', required=True, help='Measured characters[] JSON relative to this Work')
    adopt.set_defaults(handler=command_tts)

    script = commands.add_parser("script")
    script_commands = script.add_subparsers(dest="script_command", required=True)
    script_output = script_commands.add_parser("text", help="Narration for reading, counts, TTS or alignment")
    script_output.add_argument("--anchors", action="store_true", help="Keep stable paragraph Anchor comments")
    script_output.set_defaults(handler=command_script_text)
    for name in ("cues", "sound"):
        group = commands.add_parser(name)
        build = group.add_subparsers(dest=f"{name}_command", required=True).add_parser("build")
        if name == "cues":
            build.add_argument("--alignment", required=True)
        build.set_defaults(handler=command_explainer_build)

    beats = commands.add_parser("beats", help="Extract the formal audio beat grid with pinned upstream tools")
    beat_build = beats.add_subparsers(dest="beats_command", required=True).add_parser("build")
    beat_build.add_argument("--audio", required=True, help="Formal audio path relative to this Work")
    beat_build.add_argument("--beats-per-bar", type=int, required=True)
    beat_build.add_argument("--first-downbeat", type=int, required=True, help="Zero-based index of the first downbeat; preceding beats are pickup")
    beat_build.add_argument("--hyperframes-cli")
    beat_build.set_defaults(handler=command_beats_build)

    review = commands.add_parser("review", help="Create an isolated Harness test WorkStore")
    reviews = review.add_subparsers(dest="review_command", required=True)
    review_init = reviews.add_parser("init")
    review_init.add_argument("review_id")
    review_init.set_defaults(handler=command_review_init)
    review_package = reviews.add_parser("package", help="Copy declared Work-local evidence into a read-only Review package")
    review_package.add_argument("review_id")
    review_package.add_argument("--manifest", required=True, help="Work-relative review declaration JSON")
    review_package.set_defaults(handler=command_review_package)

    request = commands.add_parser("request", help="Freeze private input, deliver and review exact candidates")
    requests = request.add_subparsers(dest="request_command", required=True)
    freeze = requests.add_parser("freeze")
    freeze.add_argument("request_id")
    freeze.add_argument("--brief", required=True)
    freeze.add_argument("--scene", action="append", required=True)
    freeze.add_argument("--file", action="append", required=True, help="Affected project-relative file; may be new")
    freeze.add_argument("--context-file", action="append", default=[], help="Read-only project-relative reproduction input")
    freeze.add_argument("--preview", help="Use this frozen preview rather than the working project")
    freeze.set_defaults(handler=command_request)
    export = requests.add_parser("export")
    export.add_argument("revision")
    export.add_argument("--output", required=True)
    export.set_defaults(handler=command_request)
    deliver = requests.add_parser("deliver")
    deliver.add_argument("revision")
    deliver.add_argument("delivery_id")
    deliver.add_argument("--source", required=True, help="Patch directory containing only affected project-relative files")
    deliver.add_argument("--component", help="Optional immutable component package")
    deliver.add_argument("--binding", help="Reviewed Scene Binding for the component")
    deliver.set_defaults(handler=command_request)
    for name in ("review", "feedback", "accept"):
        command = requests.add_parser(name)
        command.add_argument("revision")
        command.add_argument("--delivery", required=True)
        if name == "feedback":
            command.add_argument("--note", required=True)
        if name == "accept":
            command.add_argument("--approved-component")
        command.set_defaults(handler=command_request)

    design = commands.add_parser('design', help='Create and validate design cards and material cards')
    design_commands = design.add_subparsers(dest='design_command', required=True)
    source_add = design_commands.add_parser('source-add', help='Cache a pinned HTTPS repository outside cards')
    source_add.add_argument('url')
    source_add.add_argument('--commit', required=True)
    source_add.set_defaults(handler=command_design)
    for operation in ('new', 'validate', 'preview', 'list', 'localize', 'compare', 'root'):
        command = design_commands.add_parser(operation)
        if operation not in ('list', 'root'):
            command.add_argument('id', **({'nargs': '?'} if operation == 'validate' else {}))
        if operation == 'new':
            command.add_argument('--from', dest='from_card')
            command.add_argument('--type', choices=('design', 'material'), default='design')
        elif operation == 'localize':
            command.add_argument('reference')
        elif operation == 'compare':
            command.add_argument('asset', nargs='?')
            command.add_argument('--commit', help='Compare files against an already cached upstream commit')
            command.add_argument('--since', help='List files changed since a Git revision of design_root; user cards only')
        elif operation == 'preview':
            command.add_argument('--output', help='Screenshot and seek-check evidence directory')
        command.set_defaults(handler=command_design)

    component = commands.add_parser("component", help="Inspect card assets and install Work-owned copies")
    component_commands = component.add_subparsers(dest="component_command", required=True)
    math_source = component_commands.add_parser('math-kit-source', help='Export editable math-kit source; never accept')
    math_source.add_argument('target')
    math_source.set_defaults(handler=command_math_source)
    interface = component_commands.add_parser('interface', help='Read card asset details or an explicit legacy reference')
    interface.add_argument('component', help='Card/asset identity, exact legacy version, or explicit listed source path')
    interface.add_argument('--candidate', action='store_true', help='Read an explicit candidate package or editable source path; never authorize installation')
    interface.set_defaults(handler=command_component_interface)
    sfx = component_commands.add_parser("import-sfx", help="Import local seed SFX into an editable card asset directory")
    sfx.add_argument("--from", dest="package", required=True)
    sfx.add_argument("--source", required=True)
    sfx.set_defaults(handler=command_import_sfx)
    component_validate = component_commands.add_parser("validate")
    component_validate.add_argument("component")
    component_validate.add_argument("--candidate", action="store_true", help="Validate a package path without declaring it accepted or production-ready")
    component_validate.set_defaults(handler=command_component_validate)
    component_root = component_commands.add_parser("root", help="Show or configure the independent AssetStore")
    component_root.add_argument("path", nargs="?")
    component_root.set_defaults(handler=command_component_store)
    for name in ("source-add", "import", "pack"):
        command = component_commands.add_parser(name)
        command.add_argument("path")
        command.set_defaults(handler=command_component_store)
    component_list = component_commands.add_parser("list", help="Discover card assets from their metadata")
    component_list.add_argument("--query", default="")
    component_list.add_argument("--kind", choices=("component", "module", "media", "audio", "character", "theme", "background", "motion", "icon-set", "scene-source", "recipe"), help='Explicit scene-source or recipe includes references without --include-references')
    component_list.add_argument("--audit", action="store_true", help="Audit without writing cache, index or report, including with --rebuild; use --json for all diagnostics")
    component_list.add_argument("--ratio", help='Declared ratio (e.g. 9:16, legacy 9x16) or unknown; evidence-backed selection fills missing declarations only')
    component_list.add_argument("--tag")
    component_list.add_argument("--broll-role", choices=("hook", "concept", "transition"))
    component_list.add_argument("--recommendation", choices=("recommended", "historical", "pending"))
    component_list.add_argument('--asset-layer', choices=('building-block', 'scene-template', 'content', 'reference', 'unclassified'))
    component_list.add_argument('--include-references', action='store_true', help='Include declared cross-card references')
    component_list.add_argument('--design', help="Only what this card's Variants can use: its own assets and declared references")
    component_list.add_argument("--rebuild", action="store_true", help="Refresh card discovery")
    component_list.add_argument("--research-root", type=Path, help="Include explicitly registered reference documents")
    component_list.set_defaults(handler=command_component_store)
    trace = component_commands.add_parser('trace', help='Read-only card/reference/account/Work asset relations; '
                                          'missing sources are not frozen-copy damage')
    trace.add_argument('--design', help='Card whose own assets and declared references are checked')
    trace.add_argument('--account', help='Account whose exact Theme/Background/Motion references are checked')
    trace.set_defaults(handler=command_component_trace)
    for name in ('migrate', 'archive'):
        maintenance = component_commands.add_parser(name, help='Explicit asset maintenance; no default production target')
        operations = maintenance.add_subparsers(dest='maintenance_action', required=True)
        preview = operations.add_parser('plan')
        preview.add_argument('--to', dest='target', required=True)
        preview.add_argument('--output', required=True)
        if name == 'migrate':
            preview.add_argument('--from', dest='source', required=True)
            preview.add_argument('--classification', help='Exact ref to asset_layer/recommendation selection JSON')
        else:
            preview.add_argument('--item', action='append', required=True, help='Owned path relative to the explicit store')
        preview.set_defaults(handler=command_asset_maintenance)
        apply = operations.add_parser('apply')
        apply.add_argument('--plan', required=True)
        apply.set_defaults(handler=command_asset_maintenance)
    icons = commands.add_parser('icons', help='Local versioned icon sets; no online provider')
    icon_commands = icons.add_subparsers(dest='icon_command', required=True)
    icon_import = icon_commands.add_parser('import', help='Import a local Lucide package into editable source; never accept')
    icon_import.add_argument('--from', dest='package', required=True)
    icon_import.add_argument('--source', required=True)
    icon_import.add_argument('--asset-version', type=int, default=1)
    icon_search = icon_commands.add_parser('search')
    icon_search.add_argument('query', nargs='?', default='')
    icon_use = icon_commands.add_parser('use', help='Copy from an installed, frozen icon set into the project')
    icon_use.add_argument('reference')
    icon_use.add_argument('--project')
    icon_use.add_argument('--output', required=True)
    for command in (icon_import, icon_search, icon_use):
        command.set_defaults(handler=command_icons)
    component_accept = component_commands.add_parser("accept", help="Accept an exact locally reviewed asset version")
    component_accept.add_argument("component_ref")
    component_accept.add_argument("--sha256", required=True)
    component_accept.add_argument("--note", required=True)
    component_accept.set_defaults(handler=command_component_store)
    component_install = component_commands.add_parser("install")
    component_install.add_argument("--project", help="Standalone sample inside a registered AssetSource; never a Work")
    component_install.add_argument("component_ref")
    component_install.add_argument("--source", help="Component package path or component ref")
    component_install.add_argument(
        "--binding-file",
        "--binding",
        dest="binding_file",
        required=True,
        help="Required reviewed Scene Binding JSON; no component-id inference is performed",
    )
    component_install.add_argument("--destination-binding")
    component_install.add_argument("--purpose", choices=("plan", "draft"), default="draft")
    component_install.set_defaults(handler=command_component_install)
    component_verify = component_commands.add_parser("verify")
    component_verify.add_argument("--project", help="Verify a standalone AssetSource sample")
    component_verify.add_argument("component_ref", nargs="?")
    component_verify.set_defaults(handler=command_component_verify)

    retired_components = {"source-add", "pack", "import", "accept", "root"}
    component_commands.metavar = '{' + ','.join(name for name in component_commands.choices
                                               if name not in retired_components) + '}'
    component_commands._choices_actions[:] = [item for item in component_commands._choices_actions
                                              if item.dest not in retired_components]
    for name in retired_components:
        component_commands.choices[name].set_defaults(handler=command_component_retired)

    variant = commands.add_parser("variant")
    variant_commands = variant.add_subparsers(dest="variant_command", required=True)
    variant_add = variant_commands.add_parser("add")
    variant_add.add_argument("variant_id", nargs="?", help="Independent result id; default next variantN")
    variant_add.add_argument("--from", dest="copy_from")
    variant_add.add_argument("--name")
    add_variant_options(variant_add)
    variant_add.set_defaults(handler=command_variant_add)
    reselect = variant_commands.add_parser('reselect', help='Preview or adopt a new frozen configuration for this Variant')
    add_variant_options(reselect)
    reselect.add_argument('--apply', action='store_true')
    reselect.set_defaults(handler=command_variant_reselect)
    variant_use = variant_commands.add_parser("use")
    variant_use.add_argument("variant_id")
    variant_use.set_defaults(handler=command_variant_use)
    variant_commands.add_parser("design-update", help="Copy current card; preserve authored project assets").set_defaults(handler=command_variant_design_update)
    variant_commands.add_parser("list").set_defaults(handler=command_variant_list)
    variant_name = variant_commands.add_parser("name")
    variant_name.add_argument("name")
    variant_name.set_defaults(handler=command_variant_name)

    wait = commands.add_parser("wait")
    wait.add_argument("reason", choices=sorted(WAIT_REASONS))
    wait.add_argument("--next-action")
    wait.set_defaults(handler=command_wait)
    resume = commands.add_parser("resume")
    resume.add_argument("--next-action")
    resume.set_defaults(handler=command_resume)
    commands.add_parser("park").set_defaults(handler=command_park)

    preview = commands.add_parser("preview")
    preview_commands = preview.add_subparsers(dest="preview_command", required=True)
    preview_register = preview_commands.add_parser("register")
    preview_register.add_argument("draft_file", nargs="?", help="Optional legacy MP4; omit to freeze an executable Draft for Studio review")
    preview_register.add_argument("--purpose", choices=("plan", "draft"), default="draft")
    preview_register.add_argument('--cover-title', help='Exact adopted packaging text for the Draft cover')
    preview_register.add_argument("--kind", choices=("reference", "layout", "executable"), default="executable")
    preview_register.add_argument("--scope", choices=("full", "scene"), default="full", help="Single executable Scene direction reference or full project")
    preview_register.add_argument("--media-readiness", choices=("complete", "planned_placeholders"), default="complete", help="Declare planned media placeholders; these versions cannot authorize Final")
    preview_register.add_argument("--sample-dir", help="Variant-local layout or single Scene project containing index.html")
    preview_register.add_argument("--scene", action="append", default=[])
    preview_register.set_defaults(handler=command_preview_register)
    preview_accept = preview_commands.add_parser("accept")
    preview_accept.add_argument("draft_id")
    preview_accept.add_argument("--confirm-embedded", action="append", metavar="SCENE", help="Record human confirmation of embedded text for this Scene; repeat per Scene")
    preview_accept.set_defaults(handler=command_preview_accept)
    preview_open = preview_commands.add_parser("open")
    preview_open.add_argument("preview_id", nargs="?", default="current", help="Editable current project or a registered version reviewed in isolation")
    preview_open.add_argument("--legacy", action="store_true", help="Explicit historical custom viewer, never the default Studio route")
    preview_open.add_argument("--no-open", action="store_true", help="Return the actual Studio URL without launching a browser")
    preview_open.add_argument("--hyperframes-cli", help="Pinned official CLI (defaults to the bound runtime)")
    preview_open.add_argument("--hyperframes-dist", help="Player bundles for --legacy only")
    preview_open.add_argument("--port", type=int, default=0)
    preview_open.set_defaults(handler=command_preview_open)
    diagnose = preview_commands.add_parser('diagnose', help='Read-only D1 hints for an already opened Studio target; never QA PASS')
    diagnose.add_argument('preview_id', help='current or an exact registered executable Plan/Draft ID; requires explicit --work/--variant')
    diagnose.add_argument('--hyperframes-cli')
    diagnose.add_argument('--browser', help='Chrome/Chromium executable (defaults to bundled HYPERFRAMES_BROWSER_PATH; no download)')
    diagnose.add_argument('--minimum', type=int, default=20, help='Minimum normalized text characters (default: 20)')
    diagnose.add_argument('--similarity', type=float, default=0.8, help='Ordered/continuous copy coverage hint threshold (default: 0.8)')
    diagnose.add_argument('--step', type=float, default=0.5, help='Base sample interval in seconds (default: 0.5)')
    diagnose.add_argument('--width', type=int, default=960, help='Target sampled display width (160..4096; default: 960)')
    diagnose.add_argument('--timeout-ms', type=int, default=5000, help='Readiness timeout per sample (100..30000; default: 5000)')
    diagnose.add_argument('--exceptions', help='JSON array of confirmed {scene,text,source,reason}; source e.g. SCRIPT.md#P001; no automatic exemptions')
    diagnose.set_defaults(handler=command_preview_diagnose)
    for name in ("context", "stop"):
        studio_command = preview_commands.add_parser(name)
        studio_command.add_argument("preview_id", nargs="?", default="current")
        studio_command.add_argument("--hyperframes-cli")
        if name == "context":
            studio_command.add_argument("--fields", default="selection", help="Comma-separated selection, lint, server, capabilities")
            studio_command.add_argument("--detail", choices=("compact", "full"), default="compact")
        studio_command.set_defaults(handler=command_preview_studio)
    preview_diff = preview_commands.add_parser("diff")
    preview_diff.add_argument("preview_id")
    preview_diff.add_argument("--scene", action="append", default=[])
    preview_diff.add_argument("--range", nargs=2, type=float, metavar=("START", "END"))
    preview_diff.add_argument("--note", help="Record this scoped feedback in existing Work runtime notes")
    preview_diff.add_argument("--compatible", action="store_true", help="Record checked local equivalent edits, not a new acceptance")
    preview_diff.set_defaults(handler=command_preview_diff)
    preview_render = preview_commands.add_parser("render")
    preview_render.add_argument("preview_id")
    preview_render.add_argument("--hyperframes-cli")
    preview_render.add_argument("--output", required=True)
    preview_render.add_argument("--final", action="store_true")
    preview_render.add_argument("--refined-project")
    preview_render.add_argument("--fps", type=int, default=60)
    preview_render.add_argument("--software-gl", action="store_true", help="Use HyperFrames software WebGL on hosts without a hardware context")
    preview_render.set_defaults(handler=command_preview_render)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("final_file", nargs="?")
    finalize.add_argument("--hyperframes-cli")
    finalize.add_argument("--fps", type=int, default=60)
    finalize.add_argument("--software-gl", action="store_true")
    finalize.add_argument("--qa-passed", action="store_true")
    finalize.set_defaults(handler=command_finalize)
    archive = commands.add_parser("archive")
    archive.add_argument("--variant-id")
    archive.add_argument("--outcome", default="stored", choices=("stored", "abandoned", "superseded", "completed"))
    archive.set_defaults(handler=command_archive)
    reopen = commands.add_parser("reopen")
    reopen.add_argument("work_id")
    reopen.add_argument("--variant-id")
    reopen.set_defaults(handler=command_reopen)
    def json_option(command):
        command.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                             help='Print the complete JSON result instead of a summary')
        for action in command._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    json_option(child)
    json_option(parser)
    return parser


# Store-wide changes that move, delete or re-identify Works, or retarget the store, need every other operation idle.
def store_exclusive(args: argparse.Namespace) -> bool:
    return (args.command in {'migrate', 'successor', 'browser'}
            or args.command == 'root' and args.root_command == 'set'
            or args.command == 'storage' and args.storage_command == 'cleanup'
            or args.command == 'series' and args.operation in {'move', 'delete'})


@contextmanager
def operation_lock(root: Path, args: argparse.Namespace):
    """Parallel Works: the store lock is shared except for store-wide changes; writers exclude per Work/Variant."""
    from windows_runtime import file_lock
    if (args.command in {'list', 'current', 'find', 'status'}
            or args.command == 'preview' and args.preview_command in {'diagnose', 'list', 'diff', 'context'}
            or args.command == 'component' and args.component_command in {'list', 'interface', 'validate', 'verify', 'trace'}):
        yield
        return
    variant_commands = {'preview', 'finalize', 'tts', 'math', 'showcase', 'cues', 'sound',
                        'beats', 'plan', 'critic', 'wait', 'cover', 'appearance'}
    if args.command == 'request' and args.request_command in {'freeze', 'accept'}:
        variant_commands.add('request')
    if (args.command == 'component' and args.component_command == 'install'
            or args.command == 'icons' and args.icon_command == 'use' and args.work_override):
        variant_commands.add(args.command)
    work_commands = variant_commands | {'name', 'archive', 'reopen', 'park', 'resume', 'variant', 'script', 'status', 'workflow'}
    if getattr(args, 'project', None):
        work_commands.discard(args.command)
    # Catalogs, assets and request packages are outside any Work: they exclude only one another.
    catalog = args.command not in work_commands | {'new'} and not (
        args.command in {'series', 'account', 'theme'} and args.operation in {'put', 'get', 'list'})
    with ExitStack() as locks:
        exclusive = store_exclusive(args)
        locks.enter_context(file_lock(runtime_root(root) / 'operations.lock', shared=not exclusive))
        if catalog and not exclusive:
            locks.enter_context(file_lock(runtime_root(root) / 'catalog.lock'))
        if args.command in work_commands:
            if args.command == 'reopen':
                work, _ = locate_work(root, args.work_id)
            else:
                work, _ = selected_work(root, args, allow_archive=True)
            variant_operation = args.command in variant_commands
            locks.enter_context(file_lock(work / '.runtime/operation.lock', shared=variant_operation))
            if variant_operation:
                variant, _ = selected_variant(root, work, args)
                locks.enter_context(file_lock(variant / '.runtime/operation.lock',
                                              shared=args.command == 'request' and args.request_command == 'freeze'))
        yield


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_root = (root or repo_root()).resolve()
    try:
        with work_context.command(runtime_root(target_root), args.context):
            return execute_command(target_root, args)
    except (HarnessError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


def execute_command(target_root: Path, args: argparse.Namespace) -> int:
    try:
        store = configured_work_root(target_root) or target_root
        review = os.environ.get("HYPERFRAMES_AI_REVIEW") == "1"
        release_file = Path(__file__).resolve().parents[1] / ".release.json"
        if not release_file.is_file():
            release_file = target_root / ".release.json"
        if release_file.is_file() and read_json(release_file).get("channel") == "candidate" and not review:
            if (args.command not in {"status", "current", "review"}
                    and not (args.command == "root" and args.root_command == "show")):
                raise HarnessError("Candidate Harness requires an isolated Review root")
        migration_journal = runtime_root(target_root) / work_migration.JOURNAL
        if migration_journal.is_file() and not (args.command == "migrate" and args.migrate_command == "apply"):
            raise HarnessError(f"RC2 migration is incomplete; resume with migrate apply: {migration_journal}")
        successor_journal = runtime_root(target_root) / work_successor.JOURNAL
        if successor_journal.exists() and args.command != "successor":
            raise HarnessError("Succession recovery pending; retry the original successor command")
        if review or (store / ".runtime" / "review.json").exists():
            identity = work_requests.review_identity(store)
            if not review:
                raise HarnessError("Review WorkStore requires an isolated root configuration")
            if identity.get("work") and (args.command == "new" or args.work_override not in (None, identity["work"])
                                         or args.variant_override not in (None, identity["variant"])
                                         or args.command == "use" and args.work_id != identity["work"]):
                raise HarnessError("Request Review is pinned to its exact Work/Variant")
            if (args.command in {"finalize", "archive", "reopen", "park", "review", "migrate", "successor"}
                    or args.command == "root" and args.root_command == "set"
                    or args.command == "preview" and (args.preview_command == "accept" or getattr(args, "final", False))
                    or args.command == "component" and args.component_command in {"install", "accept"}
                    and not os.environ.get("HYPERFRAMES_AI_ASSET_REVIEW_ROOT")
                    or args.command == "request" and args.request_command not in {"freeze", "export", "feedback"}):
                raise HarnessError("Review forbids production acceptance, installation and lifecycle promotion")
        with operation_lock(target_root, args):
            args.handler(target_root, args)
        if (args.command in {"new", "successor", "name", "wait", "resume", "park", "archive", "reopen", "finalize", "storage", "use"}
                or args.command == "variant" and args.variant_command in {"add", "name", "use"}
                or args.command == "series" and args.operation in {"put", "move"}
                or args.command == "account" and args.operation == "put"
                or args.command == "preview" and args.preview_command == "accept"
                or args.command == "migrate" and args.migrate_command == "apply" and args.migration_applied):
            try:
                refresh_browser(target_root)
            except (HarnessError, OSError) as exc:
                print(f"warning: browser directory not refreshed: {exc}", file=sys.stderr)
    except (HarnessError, ComponentError, VisualPlanError, appearance.AppearanceError, explainer.ExplainerError, storage.StorageError,
            work_requests.RequestError, work_migration.MigrationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
