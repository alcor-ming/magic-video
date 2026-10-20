"""Local, independently accepted Component packages; Work keeps its own copies."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

from component_harness import (
    ComponentError, _atomic_json, _read_json, _read_frontmatter,
    _safe_relative, _same_tree, file_sha256, parse_component_ref,
    validate_component_release, validate_component_acceptance,
)


def _config_path(root: Path) -> Path:
    value = os.environ.get("HYPERFRAMES_AI_ASSET_CONFIG") or os.environ.get("HYPERFRAMES_AI_CONFIG")
    return Path(value) if value else root / ".studio/.runtime/assets.json"


def _tool_paths(root: Path) -> list[Path]:
    if os.environ.get("HYPERFRAMES_AI_RESOLVED_CONFIG"):
        return [root / name for name in (".studio", "runtime", ".agents")]
    return [root]


def asset_store_root(root: Path) -> Path:
    config = _config_path(root)
    value = os.environ.get("HYPERFRAMES_AI_ASSET_ROOT")
    if not value and config.is_file():
        value = json.loads(config.read_text(encoding="utf-8-sig")).get("asset_root")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ComponentError("AssetStore is not configured; run component root <absolute-path>")
    store = Path(value).resolve()
    _guard_store(store)
    return store


def _guard_store(store: Path) -> None:
    if os.environ.get("HYPERFRAMES_AI_REVIEW") != "1":
        return
    review = os.environ.get("HYPERFRAMES_AI_ASSET_REVIEW_ROOT")
    if not review or store.resolve() != (Path(review) / "store").resolve():
        raise ComponentError("Review asset writes require the pinned isolated AssetStore")
    for value in json.loads(os.environ.get("HYPERFRAMES_AI_REVIEW_PROTECTED_ROOTS", "[]")):
        if store.resolve().is_relative_to(Path(value).resolve()):
            raise ComponentError("Review AssetStore cannot target production")


def _target(store: Path, relative: str) -> Path:
    from work_requests import RequestError, safe
    _guard_store(store)
    try:
        target = safe(store, relative)
    except RequestError as error:
        raise ComponentError(str(error)) from error
    if target.is_file() and target.stat().st_nlink > 1:
        raise ComponentError(f"AssetStore target cannot be a hardlink: {target}")
    return target


def _guard_source(source: Path) -> None:
    if os.environ.get("HYPERFRAMES_AI_REVIEW") != "1":
        return
    review = os.environ.get("HYPERFRAMES_AI_ASSET_REVIEW_ROOT")
    work = os.environ.get("HYPERFRAMES_AI_WORK_ROOT")
    roots = ([Path(review) / "sources"] if review else []) + ([Path(work) / "works"] if work else [])
    if not any(source.resolve().is_relative_to(path.resolve()) for path in roots):
        raise ComponentError("Review source must be an isolated source copy or Review Work-local directory")


def configure_asset_store(root: Path, directory: Path) -> dict:
    from windows_runtime import paths_overlap
    directory = Path(directory).expanduser()
    if not directory.is_absolute():
        raise ComponentError("AssetStore requires an absolute path")
    directory = directory.resolve()
    if os.environ.get("HYPERFRAMES_AI_REVIEW") == "1":
        raise ComponentError("Review cannot change its isolated asset root configuration")
    config_path = Path(os.environ.get("HYPERFRAMES_AI_DEFAULT_CONFIG") or _config_path(root))
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
    work_root = os.environ.get("HYPERFRAMES_AI_WORK_ROOT") or config.get("work_root")
    protected = _tool_paths(root)
    if os.environ.get("HYPERFRAMES_AI_HOME"):
        protected.append(Path(os.environ["HYPERFRAMES_AI_HOME"]))
    if ((directory / "works").exists() or _work_conflict(directory, work_root)
            or any(paths_overlap(directory, path) for path in protected)):
        raise ComponentError("AssetStore must be outside the Harness and WorkStore")
    directory.mkdir(parents=True, exist_ok=True)
    config["asset_root"] = str(directory)
    _atomic_json(config_path, config)
    return {"asset_root": str(directory), "config": str(config_path),
            "scope": "next-command"}


def _work_conflict(directory: Path, work_root: str | None) -> bool:
    from windows_runtime import paths_overlap
    if not work_root:
        return False
    work = Path(work_root).resolve()
    # The root deployment reserves one sibling library, never works/ or runtime data.
    return paths_overlap(directory, work) and not directory.resolve().is_relative_to(work / "asset-library")


def _sources(store: Path) -> list[str]:
    path = store / "sources.json"
    sources = _read_json(path).get("sources") if path.exists() else []
    if not isinstance(sources, list) or not all(isinstance(item, str) and Path(item).is_absolute() for item in sources):
        raise ComponentError("AssetStore sources must be an array of absolute directories")
    return sources


def _configured_sources(root: Path, store: Path) -> list[str]:
    config = _config_path(root)
    snapshot = os.environ.get("HYPERFRAMES_AI_RESOLVED_CONFIG")
    data = json.loads(snapshot) if snapshot else (_read_json(config) if config.is_file() else {})
    if "asset_source_roots" in data:
        sources = data["asset_source_roots"]
        if not isinstance(sources, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in sources):
            raise ComponentError("Configured asset_source_roots must be absolute directories")
        return sources
    return _sources(store)


def register_source(store: Path, directory: Path) -> dict:
    from windows_runtime import paths_overlap
    directory = Path(directory).expanduser().absolute()
    managed = _target(store, "sources")
    if directory.is_relative_to(store.resolve()):
        _target(store, directory.relative_to(store.resolve()).as_posix())
    directory = directory.resolve()
    _guard_source(directory)
    protected = [] if directory.is_relative_to(managed) else [store]
    if os.environ.get("HYPERFRAMES_AI_ROOT"):
        protected += _tool_paths(Path(os.environ["HYPERFRAMES_AI_ROOT"]))
    if os.environ.get("HYPERFRAMES_AI_HOME"):
        protected.append(Path(os.environ["HYPERFRAMES_AI_HOME"]))
    if (not directory.is_dir() or _work_conflict(directory, os.environ.get("HYPERFRAMES_AI_WORK_ROOT"))
            or any(paths_overlap(directory, path) for path in protected)):
        raise ComponentError("Asset source must be an existing directory outside AssetStore")
    path = _target(store, "sources.json")
    data = {"sources": _sources(store)}
    if str(directory) not in data["sources"]:
        data["sources"].append(str(directory))
        data["sources"].sort()
        _atomic_json(path, data)
    return data


def authoring_project(root: Path, project: Path) -> Path:
    import designs
    project = project.expanduser().absolute()
    user = designs.user_root(root)
    if user is not None:
        for identity in designs.catalog(root):
            card = designs.card_path(identity, root)
            if card.parent == user and project.is_relative_to(card / "example"):
                _guard_source(project)
                if not project.is_dir():
                    raise ComponentError("Card example project is missing")
                return project
    store = asset_store_root(root)
    managed = _target(store, "sources")
    project = project.expanduser().absolute()
    if project.is_relative_to(store):
        _target(store, project.relative_to(store).as_posix())
    project = project.resolve()
    sources = [*_configured_sources(root, store), str(managed)]
    if not project.is_dir() or not any(project.is_relative_to(Path(p).resolve()) for p in sources):
        raise ComponentError("Standalone sample must be inside a registered AssetSource")
    _guard_source(project)
    config = _read_json(_config_path(root))
    work_root = os.environ.get("HYPERFRAMES_AI_WORK_ROOT") or config.get("work_root")
    if any(project.is_relative_to(p.resolve()) for p in _tool_paths(root)) or (project.is_relative_to(store.resolve()) and not project.is_relative_to(managed)) or _work_conflict(project, work_root):
        raise ComponentError("Standalone samples cannot target Harness, AssetStore or a Work")
    return project


def _relative(ref: str) -> Path:
    identity, version = parse_component_ref(ref)
    return Path(identity) / f"v{version}"


def _validate_package(directory: Path, expected_ref: str | None = None) -> dict:
    if not (directory / "COMPONENT.md").is_file() and not (directory / "asset.json").is_file():
        raise ComponentError("Unsupported asset contract; a Component Release is required")
    report = validate_component_release(directory, expected_ref=expected_ref, allow_unapproved=True)
    kinds = {"component", "effect", "module", "media"}
    if (directory / "asset.json").is_file():
        kinds |= {"theme", "background", "motion", "character", "icon-set"}
    if report["metadata"].get("asset_type", "component") not in kinds:
        raise ComponentError("Unsupported asset type for the Component contract")
    return report


def _validate_dependencies(directory: Path, report: dict) -> None:
    if (directory / "asset.json").is_file():
        return  # validate_asset already checks the frozen recursive closure.
    from visual_plan import VisualPlanError, validate_dependencies
    try:
        validate_dependencies(directory, entry="component.html")
    except VisualPlanError as error:
        raise ComponentError(f"Asset dependency check failed: {error}") from error
    dependencies = report["metadata"].get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ComponentError("Asset dependencies must be an array of local path/sha256 records")
    for item in dependencies:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ComponentError("Asset dependency requires path and sha256")
        target = directory / _safe_relative(item["path"], "dependency path")
        if not target.is_file() or file_sha256(target) != item.get("sha256"):
            raise ComponentError(f"Asset dependency digest mismatch: {item['path']}")


def import_component(store: Path, source: Path) -> dict:
    source = Path(source).expanduser().resolve()
    _guard_source(source)
    return _import_package(store, source)


def pack_source(store: Path, source: Path) -> dict:
    from asset_contract import freeze_source
    source = Path(source).expanduser().resolve()
    _guard_source(source)
    _guard_store(store)
    store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asset-pack-", dir=store) as temporary:
        frozen = Path(temporary) / "package"
        freeze_source(source, frozen)
        return _import_package(store, frozen, original_source=source)


def _import_package(store: Path, source: Path, *, original_source: Path | None = None) -> dict:
    report = _validate_package(source)
    _accepted_closure(store, report["metadata"].get("asset_dependencies", []), visiting={report["component_ref"]})
    relative = _relative(report["component_ref"])
    destination = _target(store, (Path("candidates") / relative).as_posix())
    accepted = _target(store, (Path("packages") / relative).as_posix())
    for existing in (destination / "package", accepted):
        if existing.exists() and not _same_tree(source, existing):
            raise ComponentError(f"Asset identity/version already has different content: {report['component_ref']}")
    if destination.exists():
        return _read_json(destination / "candidate.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asset-import-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "candidate"
        shutil.copytree(source, staging / "package")
        if not _same_tree(source, staging / "package"):
            raise ComponentError("Asset changed during import")
        _validate_package(staging / "package", report["component_ref"])
        # Studio may edit review/, never package/ or the eventual accepted copy.
        shutil.copytree(staging / "package", staging / "review")
        data = {"component_ref": report["component_ref"], "package_sha256": report["package_sha256"],
                "source": str(original_source or source), "status": "candidate", "path": str(destination),
                "review": str(destination / "review")}
        _atomic_json(staging / "candidate.json", data)
        staging.rename(destination)
    return data


def accept_component(store: Path, ref: str, sha256: str, note: str, *, runtime_root: Path) -> dict:
    relative = _relative(ref)
    candidate = _target(store, (Path("candidates") / relative).as_posix())
    report = _validate_package(candidate / "package", ref)
    if sha256 != report["package_sha256"]:
        raise ComponentError("Acceptance must name the exact candidate package_sha256")
    if not note.strip():
        raise ComponentError("Acceptance requires a note recording the reviewed fixture and result")
    if not _same_tree(candidate / "package", candidate / "review"):
        raise ComponentError("Review copy changed; package changes as a new version before acceptance")
    _validate_dependencies(candidate / "package", report)
    _accepted_closure(store, report["metadata"].get("asset_dependencies", []), runtime_root=runtime_root,
                      visiting={ref})
    from asset_contract import asset_requires_runtime
    executable = asset_requires_runtime(report["metadata"])
    lock = _read_json(runtime_root / "windows-runtime.lock.json") if executable else {"target": "declarative", "versions": {}}
    declared_runtime = report["metadata"].get("runtime", {})
    declared_versions = declared_runtime.get("versions", {}) if isinstance(declared_runtime, dict) else None
    if not isinstance(declared_versions, dict):
        raise ComponentError("Asset runtime versions must be an object")
    required_versions = {"hyperframes", *declared_versions} if executable else set()
    entry = report["metadata"].get("entry", "component.html")
    source = (candidate / "package" / entry).read_text(encoding="utf-8") if executable else ""
    # ponytail: literal legacy use detection; indirect aliases need runtime.versions metadata.
    for name, marker in (("gsap", "gsap."), ("three", "THREE.")):
        if executable and (marker in source or any(name in item["path"].lower() for item in report["files"])):
            required_versions.add(name)
    if required_versions - set(lock["versions"]):
        raise ComponentError("Asset declares unsupported runtime dependencies")
    acceptance = {"schema_version": 1, "status": "accepted", "component_ref": ref,
                  "package_sha256": sha256, "accepted_at": datetime.now(timezone.utc).isoformat(),
                  "note": note.strip(), "source": _read_json(candidate / "candidate.json")["source"],
                  "runtime": {"target": lock["target"], "versions": {
                      name: lock["versions"][name] for name in sorted(required_versions)}}}
    if os.environ.get("HYPERFRAMES_AI_REVIEW") == "1":
        acceptance["review"] = {"work_root": os.environ["HYPERFRAMES_AI_WORK_ROOT"], "asset_root": str(store)}
    validate_component_acceptance(acceptance, report, runtime_root=runtime_root)
    destination = _target(store, (Path("packages") / relative).as_posix())
    record = _target(store, (Path("acceptances") / relative / "acceptance.json").as_posix())
    if destination.exists():
        if not _same_tree(candidate / "package", destination):
            raise ComponentError(f"Refusing to overwrite accepted asset: {ref}")
        if record.is_file():
            existing = _read_json(record)
            validate_component_acceptance(existing, report, runtime_root=runtime_root)
            return existing
        _atomic_json(record, acceptance)
        return acceptance
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asset-accept-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "package"
        shutil.copytree(candidate / "package", staging)
        if not _same_tree(candidate / "package", staging):
            raise ComponentError("Candidate changed during acceptance")
        _validate_package(staging, ref)
        staging.rename(destination)
    _atomic_json(record, acceptance)
    return acceptance


def _entries(directory: Path, match) -> list[Path]:
    """Every matching directory entry, including link loops that Path.rglob hides on Python 3.11."""
    return [Path(parent) / name for parent, _, names in os.walk(directory) for name in names if match(name)]


def _discover_references(directory: Path, seen: set | None = None) -> tuple[list[dict], list[dict]]:
    assets, warnings = [], []
    seen = set() if seen is None else seen
    required = ("source_ref", "title", "purpose", "tags", "workflow_role",
                "primary_category", "classification_status", "limits")
    candidates = {path: "scene-source" for path in _entries(directory, lambda name: name == "manifest.json")}
    candidates.update({path: "recipe" for path in _entries(directory, lambda name: name.endswith(".md") and name != "COMPONENT.md")})
    source_approvals = set()
    for acceptance in _entries(directory, lambda name: name == "ACCEPTANCE.json"):
        try:
            if not acceptance.resolve().is_relative_to(directory.resolve()):
                raise ComponentError("Approval path escapes source root")
            approval = _read_json(acceptance)
            if "component_ref" in approval and "package_sha256" in approval:
                continue  # A package receipt does not declare a scene source.
            if not any(approval.get(key) for key in ("source_ref", "workflow_role")) and "scene-source" not in (approval.get("kind"), approval.get("asset_type")):
                warnings.append({"path": str(acceptance.resolve()), "code": "unknown_source_approval"})
                continue
            manifest = acceptance.parent / "manifest.json"
            source_approvals.add(manifest.resolve())
            candidates.setdefault(manifest, "scene-source")
        except (ComponentError, OSError, RuntimeError) as error:
            warnings.append({"path": str(acceptance), "code": "invalid_source_approval", "error": str(error)})
    for path, kind in sorted(candidates.items()):
        try:
            # Strict for existing entries: a link loop resolves silently on Python 3.11 and would vanish behind is_file().
            inside = Path(os.path.realpath(path, strict=os.path.lexists(path))).is_relative_to(directory.resolve())
        except (OSError, RuntimeError):
            inside = False
        if not inside:
            warnings.append({"path": str(path), "code": "unsafe_reference_path"})
            continue
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            if kind == "recipe":
                lines = path.read_text(encoding="utf-8-sig").splitlines()
                if not lines or lines[0] != "---":
                    continue
                frontmatter = "\n".join(lines[1:lines.index("---", 1)] if "---" in lines[1:] else lines[1:])
                try:
                    metadata = json.loads(frontmatter)
                except ValueError as error:
                    if not any(f'"{key}"' in frontmatter or f"{key}:" in frontmatter
                               for key in ("source_ref", "workflow_role", "entry")):
                        continue
                    raise ComponentError(f"Invalid JSON reference front matter: {error}") from error
                if not isinstance(metadata, dict):
                    continue
                if "---" not in lines[1:] and any(key in metadata for key in ("source_ref", "workflow_role", "entry")):
                    raise ComponentError("Reference requires an object in closed JSON front matter")
            else:
                metadata = _read_json(path) if path.is_file() else {}
            if not any(key in metadata for key in ("source_ref", "workflow_role", "entry")) and not (
                    kind == "scene-source" and path in source_approvals):
                continue
            fields = required + (("entry",) if kind == "scene-source" else ())
            missing = [key for key in fields if key not in metadata or
                       (key not in ("tags", "limits") and
                        (not isinstance(metadata[key], str) or not metadata[key].strip()))]
            for key in ("tags", "limits"):
                if key == "limits" and isinstance(metadata.get(key), str):
                    continue
                if key in metadata and (not isinstance(metadata[key], list) or
                        not all(isinstance(value, str) for value in metadata[key])):
                    missing.append(key)
            if missing:
                warnings.append({"path": str(path), "code": "missing_discovery_fields", "fields": missing})
            invalid_entry = False
            if "entry" in metadata:
                try:
                    entry = path.parent / _safe_relative(metadata["entry"], "reference entry")
                    if not entry.resolve().is_relative_to(path.parent.resolve()):
                        raise ComponentError("Reference entry escapes its directory")
                    if not entry.is_file():
                        warnings.append({"path": str(path), "code": "missing_reference_file", "entry": metadata["entry"]})
                        invalid_entry = True
                except (ComponentError, OSError, RuntimeError, TypeError):
                    warnings.append({"path": str(path), "code": "unsafe_reference_path", "entry": metadata["entry"]})
                    invalid_entry = True
            if missing or invalid_entry:
                continue
            assets.append({**{key: metadata[key] for key in (*fields, "entry", "usage", "example", "examples", "ratio", "compatibility") if key in metadata},
                "component_ref": metadata["source_ref"], "package_sha256": None,
                "path": str(path), "origin": "source", "available": False, "installable": False,
                "reference_only": True, "status": "derivation-reference", "asset_type": kind,
                "communication_goal": metadata["purpose"], "verification": "self-described reference; not a package"})
        except (ComponentError, OSError, UnicodeError) as error:
            warnings.append({"path": str(path), "code": "invalid_discovery_metadata", "error": str(error)})
    return assets, warnings


def _selection_ratios(asset: dict, extra: dict, store: Path | None) -> list[dict]:
    """Optional selection evidence affects discovery, never installation authority."""
    warnings = []
    aliases = {"16x9": "16:9", "9x16": "9:16", "4x3": "4:3", "1x1": "1:1"}

    def ratios(value):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("Ratios must be an array")
        result = list(dict.fromkeys(aliases.get(item, item) for item in value))
        if any(item not in {"16:9", "9:16", "4:3", "1:1"} for item in result):
            raise ValueError("Unsupported ratio")
        return result

    compatibility = asset.get("compatibility", {})
    raw = compatibility.get("ratios", []) if isinstance(compatibility, dict) else None
    field = "compatibility.ratios"
    if raw == [] and asset.get("ratio") not in (None, "", "unknown"):
        raw, field = [asset["ratio"]], "ratio"
    valid = True
    try:
        declared = ratios(raw)
    except ValueError:
        declared, valid = [], False
        warnings.append({"path": asset["path"], "code": "invalid_declared_ratios"})
    effective = declared
    origin = "source" if asset["origin"] == "source" else "package"
    provenance = {"kind": origin, "path": asset["path"], "field": field} if declared else {"kind": "unknown"}
    if "ratios" in extra:
        try:
            supplement = ratios(extra["ratios"])
            evidence = extra.get("ratios_basis")
            if not supplement or not isinstance(evidence, str) or not evidence.strip():
                raise ValueError("Selection ratios require a non-empty ratios_basis")
            if declared and set(supplement) != set(declared):
                warnings.append({"path": str(store / "selection.json"), "component_ref": asset["component_ref"],
                                 "code": "conflicting_selection_ratios", "declared": declared, "selection": supplement})
            elif not declared and valid:
                effective = supplement
                provenance = {"kind": "selection", "path": str(store / "selection.json"), "evidence": evidence}
        except ValueError as error:
            warnings.append({"path": str(store / "selection.json"), "component_ref": asset["component_ref"],
                             "code": "invalid_selection_ratios", "error": str(error)})
    asset["ratios"], asset["ratio_source"] = effective, provenance
    # Keep the legacy ratio spelling in its original field; filter aliases equally.
    if not effective:
        asset["ratio"] = "unknown"
    elif asset.get("ratio") in (None, "", "unknown"):
        asset["ratio"] = effective[0] if len(effective) == 1 else "unknown"
    return warnings


def _validate_selection(selection):
    from asset_contract import validate_asset_layer
    if not isinstance(selection, dict) or any(not isinstance(value, dict) for value in selection.values()):
        raise ComponentError("Selection metadata must map exact asset refs to objects")
    for ref, value in selection.items():
        parse_component_ref(ref)
        for field in ("aliases", "tags", "examples", "limitations"):
            if field in value and (not isinstance(value[field], list) or not all(isinstance(item, str) for item in value[field])):
                raise ComponentError(f"Selection {field} must be an array of strings")
        if "recommendation" in value and value["recommendation"] not in ("recommended", "historical", "pending"):
            raise ComponentError("Selection recommendation must be recommended, historical or pending")
        if "asset_layer" in value:
            validate_asset_layer(value["asset_layer"])
    return selection


def _layer(metadata, extra=None):
    from asset_contract import DECLARATIVE, validate_asset_layer
    value = (extra or {}).get("asset_layer", metadata.get("asset_layer"))
    if value is not None:
        return validate_asset_layer(value)
    return "content" if metadata.get("kind", metadata.get("asset_type")) in DECLARATIVE | {"media"} else "unclassified"


def _retired_roots(store):
    path = store / "catalog-migration.json"
    if not path.exists():
        return set()
    data = _read_json(path)
    roots = data.get("retired_roots") if isinstance(data, dict) else None
    if not isinstance(roots, list) or not all(isinstance(item, str) and Path(item).is_absolute() for item in roots):
        raise ComponentError("catalog-migration.json requires absolute retired_roots")
    return {Path(item).resolve() for item in roots}


def legacy_discover_components(root: Path, query: str = "", *, kind=None, ratio=None, tag=None,
                               recommendation=None, rebuild=False, research_root=None, audit=False,
                               config=None, asset_layer=None, include_references=False, broll_role=None,
                               design=None) -> dict:
    from asset_contract import KINDS, validate_asset_layer
    if design is not None:
        raise ComponentError("Design scope applies to card discovery, not the legacy AssetStore")
    if asset_layer is not None and asset_layer != "unclassified":
        validate_asset_layer(asset_layer)
    if broll_role is not None and broll_role not in ("hook", "concept", "transition"):
        raise ComponentError("Invalid broll role filter")
    def declared_ratios(metadata):
        compatibility = metadata.get("compatibility", {})
        return compatibility.get("ratios", []) if isinstance(compatibility, dict) else []

    # v4.2: discovery lives in card asset libraries; no legacy repository root.
    roots = []
    if config is not None:
        if not isinstance(config.get("asset_root"), str) or not Path(config["asset_root"]).is_absolute():
            raise ComponentError("AssetStore requires an absolute path")
        sources = config.get("asset_source_roots", [])
        if not isinstance(sources, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in sources):
            raise ComponentError("Configured asset_source_roots must be absolute directories")
    try:
        store = asset_store_root(root) if config is None else Path(config["asset_root"]).resolve()
    except ComponentError:
        store = None
    if store:
        retired = _retired_roots(store)
        roots = [(directory, origin) for directory, origin in roots if directory.resolve() not in retired]
        roots += [(store / "packages", "accepted"), (store / "candidates", "candidate")]
        sources = _configured_sources(root, store) if config is None else config.get("asset_source_roots", [])
        roots += [(Path(path), "source") for path in sources if Path(path).resolve() not in retired and Path(path).resolve() != (store / "sources").resolve()]
        managed = _target(store, "sources")
        if managed.is_dir():
            roots.append((managed, "source"))
    assets, errors, warnings = [], [], []
    cache_path = _target(store, ".discovery-cache.json") if store and not audit else None
    try:
        cache = _read_json(cache_path) if cache_path and cache_path.is_file() and not rebuild else {}
    except (ComponentError, ValueError, OSError):
        cache = {}
    fresh, refreshed = {}, []

    def read(path):
        stat = path.stat()
        key = str(path.resolve())
        signature = [stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size]
        item = cache.get(key)
        if not isinstance(item, dict) or item.get("signature") != signature:
            item = {"signature": signature, "value": _read_frontmatter(path) if path.name == "COMPONENT.md" else _read_json(path)}
            refreshed.append(key)
        fresh[key] = item
        return item["value"]

    selection, selection_error = {}, None
    if store and (store / "selection.json").exists():
        try:
            selection = _validate_selection(read(store / "selection.json"))
        except (ComponentError, OSError, ValueError) as error:
            selection = {}
            selection_error = str(error)
            errors.append({"path": str(store / "selection.json"), "error": str(error), "unsynchronized": True})
    seen, reference_seen = set(), set()
    observed_hashes = {}
    for directory, origin in roots:
        if not directory.is_dir():
            if origin == "source":
                errors.append({"path": str(directory), "error": "Source is unavailable"})
            continue
        if origin == "source":
            references, reference_warnings = _discover_references(directory, reference_seen)
            assets.extend(references)
            warnings.extend(reference_warnings)
        for metadata_path in sorted([*directory.rglob("COMPONENT.md"), *directory.rglob("asset.json")]):
            try:
                inside = metadata_path.resolve().is_relative_to(directory.resolve())
            except (OSError, RuntimeError):
                inside = False
            if not inside:
                errors.append({"path": str(metadata_path), "error": "Metadata path escapes asset root"})
                continue
            if origin == "candidate" and "review" in metadata_path.relative_to(directory).parts:
                continue
            package = metadata_path.parent
            if package.resolve() in seen:
                continue
            seen.add(package.resolve())
            try:
                metadata = read(metadata_path)
                if metadata_path.name == "asset.json" and metadata.get("kind") not in KINDS:
                    raise ComponentError(f"Unsupported asset kind: {metadata.get('kind')!r}")
                if origin == "source" and metadata_path.name == "asset.json" and not (package / "HASHES.json").exists():
                    ref = f"{metadata['id']}@v{metadata['version']}"
                    parse_component_ref(ref)
                    assets.append({"component_ref": ref, "package_sha256": None, "path": str(package.resolve()),
                                   "origin": origin, "available": False, "status": "editable-source",
                                   "asset_type": metadata["kind"], "ratio": metadata.get("ratio"),
                                   "ratios": declared_ratios(metadata),
                                   "communication_goal": metadata.get("description", ""),
                                   "verification": "metadata-only; source is not accepted"})
                    assets[-1].update({key: metadata[key] for key in ("purpose", "tags", "entry", "compatibility", "hit_offset", "hit_offset_estimated", "asset_layer", "broll") if key in metadata})
                    continue
                if metadata_path.name == "asset.json":
                    metadata = {**metadata, "asset_type": metadata["kind"]}
                hashes = read(package / "HASHES.json")
                ref = hashes.get("component_ref", hashes.get("asset_ref"))
                if not isinstance(ref, str):
                    raise ComponentError("Asset manifest requires a string reference")
                parse_component_ref(ref)
                observed_hashes.setdefault(ref, set()).add(hashes["package_sha256"])
                if metadata_path.name == "asset.json" and ref != f"{metadata['id']}@v{metadata['version']}":
                    raise ComponentError("Asset metadata identity disagrees with manifest")
                if not isinstance(hashes.get("files"), list) or not hashes["files"]:
                    raise ComponentError("Asset manifest requires files")
                for entry in hashes["files"]:
                    dependency = package / _safe_relative(entry["path"], "manifest file")
                    if not dependency.resolve().is_relative_to(package.resolve()) or not dependency.is_file():
                        raise ComponentError(f"Manifest file missing or outside package: {entry['path']}")
                report = {"component_ref": ref, "metadata": metadata, "ratio": metadata.get("ratio"),
                          "package_sha256": hashes["package_sha256"]}
                metadata, ref = report["metadata"], report["component_ref"]
                available = origin == "legacy" and metadata.get("status") == "library-approved"
                acceptance = None
                if origin == "accepted":
                    acceptance = read(store / "acceptances" / _relative(ref) / "acceptance.json")
                    validate_component_acceptance(acceptance, report, runtime_root=root)
                    available = True
                assets.append({"component_ref": ref, "package_sha256": report["package_sha256"],
                               "path": str(package.resolve()), "origin": origin, "available": available,
                               "status": "accepted" if acceptance else "source" if origin == "source" else "candidate" if origin == "candidate" else metadata.get("status", "candidate"),
                               "asset_type": metadata.get("asset_type", "component"), "ratio": report["ratio"],
                               "ratios": declared_ratios(metadata),
                               "communication_goal": metadata.get("communication_goal", metadata.get("description", "")),
                               "information_shapes": metadata.get("information_shapes", []),
                               "anti_use_cases": metadata.get("anti_use_cases", []), "acceptance": acceptance,
                               "verification": "metadata-only; verified on use"})
                assets[-1].update({key: metadata[key] for key in ("purpose", "tags", "entry", "compatibility", "hit_offset", "hit_offset_estimated", "asset_layer", "broll") if key in metadata})
                if str(metadata.get("entry", "")).lower().endswith(".mp3"):
                    assets[-1]["media_type"] = "audio"
            except (ComponentError, OSError, ValueError, KeyError, TypeError) as error:
                errors.append({"path": str(package), "error": str(error)})
    hashes: dict[str, set[str]] = observed_hashes
    for asset in assets:
        if selection_error and not asset.get("reference_only"):
            asset["selection_error"] = selection_error
        if asset["package_sha256"]:
            hashes.setdefault(asset["component_ref"], set()).add(asset["package_sha256"])
    conflicts = [{"code": "conflicting_asset_identity", "component_ref": ref,
                  "path": str(store or root), "paths": sorted({asset["path"] for asset in assets if asset["component_ref"] == ref}),
                  "error": "Same identity/version has different package hashes"}
                 for ref, values in sorted(hashes.items()) if len(values) > 1]
    errors.extend(conflicts)
    for asset in assets:
        if not asset.get("reference_only") and len(hashes.get(asset["component_ref"], set())) > 1:
            asset.update(available=False, conflict="Same identity/version has different package hashes")
        extra = {} if asset.get("reference_only") else selection.get(asset["component_ref"], {})
        try:
            asset["asset_layer"] = "reference" if asset.get("reference_only") else _layer(asset, extra)
        except ComponentError as error:
            errors.append({"path": asset["path"], "error": str(error)})
            asset.update(asset_layer="unclassified", available=False)
        asset["lifecycle"] = "accepted" if asset.get("acceptance") else "source" if asset["origin"] == "source" else "candidate"
        if asset["asset_layer"] == "unclassified":
            warnings.append({"path": asset["path"], "component_ref": asset["component_ref"], "code": "unclassified_asset"})
        if asset["asset_layer"] == "reference":
            asset.update(reference_only=True, installable=False, available=False)
        if asset["origin"] == "accepted":
            missing = [key for key in ("purpose", "tags") if not extra.get(key, asset.get(key))]
            if missing:
                warnings.append({"path": str(store / "selection.json"), "code": "missing_selection_fields",
                                 "component_ref": asset["component_ref"], "fields": missing})
        asset.update({key: extra[key] for key in ("aliases", "tags", "purpose", "examples", "limitations", "replacement") if key in extra})
        state = extra.get("recommendation", "pending")
        asset["recommendation"] = state if state in {"recommended", "historical", "pending"} else "pending"
        warnings.extend(_selection_ratios(asset, extra, store))
        asset["check_scope"] = asset.get("verification", "metadata-only")
        asset["group"] = asset["origin"]
        asset["match_reasons"] = [key for key in ("component_ref", "title", "communication_goal", "purpose", "aliases", "tags", "information_shapes", "workflow_role", "primary_category", "limits")
                                  if query and query.casefold() in json.dumps(asset.get(key, ""), ensure_ascii=False).casefold()]
        asset["use"] = ("appearance binding with exact ref/hash" if asset["asset_type"] in {"theme", "background", "motion"}
                        else "component install with exact ref/hash") if asset["available"] else "reference only; not accepted for use"
        if asset.get("reference_only"):
            asset["use"] = "derivation reference only; not installable"
        _describe_action(asset)
    if store and not audit:
        index_path = _target(store, ".catalog-index.json")
        index = {"schema_version": 1, "assets": [{key: value for key, value in asset.items() if key != "match_reasons"} for asset in assets], "errors": errors, "warnings": warnings}
        try:
            try:
                previous = _read_json(index_path) if index_path.is_file() and not rebuild else None
            except (ComponentError, ValueError):
                previous = None
            if previous != index:
                _atomic_json(index_path, index)
        except (ComponentError, OSError, ValueError) as error:
            errors.append({"path": str(index_path), "error": str(error), "unsynchronized": True})
    if query:
        assets = [asset for asset in assets if asset["match_reasons"]]
    assets = [asset for asset in assets if (not kind or asset["asset_type"] == kind or asset.get("media_type") == kind)
              and (not asset_layer or asset["asset_layer"] == asset_layer)
              and (include_references or kind in {"scene-source", "recipe"} or asset_layer == "reference" or asset["asset_layer"] != "reference")
              and (not ratio or ratio.replace("x", ":") in asset["ratios"] or ratio == "unknown" and not asset["ratios"])
              and (not tag or tag in asset.get("tags", []))
              and (not broll_role or isinstance(asset.get("broll"), dict) and asset["broll"].get("role") == broll_role)
              and (not recommendation or asset["recommendation"] == recommendation)]
    assets.sort(key=lambda asset: (not asset["available"], {"recommended": 0, "pending": 1, "historical": 2}[asset["recommendation"]], asset["component_ref"], asset["path"]))
    if cache_path and fresh != cache:
        try:
            _atomic_json(cache_path, fresh)
        except (ComponentError, OSError) as error:
            errors.append({"path": str(cache_path), "error": str(error), "unsynchronized": True})
    warnings = list({json.dumps(item, sort_keys=True): item for item in warnings}.values())
    result = {"assets": assets, "errors": errors, "warnings": warnings, "conflicts": conflicts, "refreshed": refreshed,
              "filters": {"query": query, "kind": kind, "ratio": ratio, "tag": tag,
                          "asset_layer": asset_layer, "recommendation": recommendation, "broll_role": broll_role,
                          "include_references": include_references or kind in {"scene-source", "recipe"} or asset_layer == "reference"}}
    if not assets:
        result["message"] = "No matches for these filters; this is not a complete inventory. Reference entries are hidden unless explicitly requested."
    if audit:
        result["audit"] = {"warnings": warnings, "warning_count": len(warnings), "error_count": len(errors)}
    if research_root is not None:
        from research_catalog import query as research_query
        result["research"] = research_query(research_root, query)["documents"]
    return result


def _describe_action(asset: dict, *, candidate: bool = False) -> None:
    """Selection guidance is not installation authority; installers still verify."""
    reference = bool(asset.get("source_ref")) and asset["asset_type"] in {"scene-source", "recipe"}
    source = Path(asset["path"])
    asset["source_directory"] = str(source.parent if reference else source)
    asset["entry"] = asset.get("entry") or ("component.html" if asset["asset_type"] == "component" else None)
    asset["installable"] = bool(asset.get("available") and not asset.get("reference_only")
                                and not asset.get("conflict") and not asset.get("selection_error"))
    argv = ["component", "interface", asset["path"]]
    if not reference and (candidate or asset["origin"] in {"candidate", "source"}):
        argv.append("--candidate")
    asset["detail"] = {"argv": argv}
    if asset.get("conflict") or asset.get("selection_error"):
        action, instructions = "blocked", asset.get("conflict") or asset["selection_error"]
    elif asset["installable"]:
        action = "appearance-binding" if asset["asset_type"] in {"theme", "background", "motion"} else "install"
        instructions = ("Use the existing appearance binding with this exact ref and package_sha256." if action == "appearance-binding"
                        else "Use component install with this exact ref, a reviewed --binding-file and explicit --work/--variant or --project; verify package_sha256 on use.")
    elif reference and asset["asset_type"] == "scene-source":
        action, instructions = "derive-reference", "Read the declared source and entry for manual derivation in an authorized editable project; not installable."
    elif asset.get("origin") == REFERENCE_ORIGIN:
        action = "referenced-use"
        instructions = (f"Declared by {asset['referenced_by']}: from a Variant of that card, install or bind "
                        f"{asset['component_ref']} (read-only source copy); use design localize to edit.")
    elif asset.get("reference_only"):
        action, instructions = "reference-only", "Read this reference and its declared usage; not installable."
    else:
        action, instructions = "candidate", "Not accepted for installation. Use the existing validate --candidate / pack / review workflow; acceptance is a separate authorized action."
    asset["next_step"] = {"action": action, "instructions": instructions}


def _store_component_interface(root: Path, value: str, *, candidate: bool = False) -> dict:
    """Read an exact discovered object without invoking installation resolution."""
    inventory = legacy_discover_components(root, include_references=True, audit=True)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve()
    except (OSError, RuntimeError) as error:
        raise ComponentError(f"Unsafe detail path: {value}: {error}") from error
    matches = [row for row in inventory["assets"] if row["path"] == str(path)]
    if not matches and not candidate:
        matches = [row for row in inventory["assets"] if row["component_ref"] == value
                   and (row.get("source_ref") or row["origin"] == "accepted"
                        or row["origin"] == "legacy" and row["available"])]
    if len(matches) > 1:
        targets = [{key: row[key] for key in ("component_ref", "asset_type", "status", "path", "detail")} for row in matches]
        raise ComponentError("Ambiguous asset reference; select an exact detail target: " + json.dumps(targets, ensure_ascii=False))
    release = None
    if matches:
        card = dict(matches[0])
    elif candidate:
        release = _validate_package(path)
        metadata = release["metadata"]
        card = {"component_ref": release["component_ref"], "package_sha256": release["package_sha256"],
                "path": str(path), "origin": "candidate", "status": "candidate", "lifecycle": "candidate",
                "asset_type": metadata.get("kind", metadata.get("asset_type", "component")),
                "available": False, "acceptance": None, "entry": metadata.get("entry"),
                "asset_layer": _layer(metadata), "ratio": metadata.get("ratio", "unknown"),
                "compatibility": metadata.get("compatibility", {})}
        _selection_ratios(card, {}, None)
    else:
        diagnostics = [item for item in [*inventory["errors"], *inventory["warnings"]] if item["path"] == str(path)]
        raise ComponentError(f"No discoverable asset for exact target {value!r}; candidates require an explicit path. "
                             + json.dumps(diagnostics, ensure_ascii=False))
    source = Path(card["path"])
    reference = bool(card.get("source_ref")) and card["asset_type"] in {"scene-source", "recipe"}
    if reference and candidate:
        raise ComponentError("--candidate describes packages, not scene-source or recipe references")
    if reference:
        metadata = card
        card["declaration"] = str(source)
        card["check_scope"] = "reference metadata and entry path checked; not a package or runtime validation"
    elif card.get("status") == "editable-source":
        metadata = _read_json(source / "asset.json")
        if "entry" in metadata:
            try:
                entry = source / _safe_relative(metadata["entry"], "source entry")
                if not entry.resolve().is_relative_to(source.resolve()) or not entry.is_file():
                    raise ComponentError(f"Missing or unsafe source entry: {entry}")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise ComponentError(f"Invalid source entry: {error}") from error
        card["declaration"] = str(source / "asset.json")
        card["check_scope"] = "metadata-only; editable source is not a frozen or accepted package"
    else:
        release = release or _validate_package(source, card["component_ref"])
        metadata = release["metadata"]
        card["declaration"] = str(source / ("asset.json" if (source / "asset.json").is_file() else "COMPONENT.md"))
        if card.get("acceptance"):
            validate_component_acceptance(card["acceptance"], release, runtime_root=root)
        card["check_scope"] = "package contract and hashes checked; acceptance checked when present; no runtime or visual validation"
    if candidate:
        card.update(available=False, acceptance=None, lifecycle="source" if card.get("status") == "editable-source" else "candidate")
        if card.get("status") != "editable-source":
            card["status"] = "candidate"
    keys = ("communication_goal", "purpose", "usage", "example", "examples", "ratio", "compatibility", "layers",
            "slots", "parameters", "duration_range", "motion_recipe", "customization", "broll", "limits", "limitations")
    card["interface"] = {key: metadata[key] for key in keys if key in metadata}
    card["interface"].setdefault("layers", "not declared; verify the selected package before use")
    if release and release.get("fixture"):
        card["interface"]["example"] = release["fixture"]
    for key in ("usage", "example"):
        name = metadata.get(key)
        if isinstance(name, str):
            base = source.parent if reference else source
            try:
                attachment = base / _safe_relative(name, f"interface {key}")
                if not attachment.resolve().is_relative_to(base.resolve()):
                    raise ComponentError(f"Interface {key} escapes its directory")
                if not attachment.is_file():
                    raise ComponentError(f"Missing interface {key}: {attachment}")
                card["interface"][key] = attachment.read_text(encoding="utf-8-sig")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise ComponentError(f"Invalid interface {key}: {error}") from error
    card.setdefault("purpose", metadata.get("purpose", metadata.get("communication_goal", metadata.get("description", "not declared"))))
    card.setdefault("examples", metadata.get("examples", []))
    card.setdefault("limitations", metadata.get("limits", metadata.get("limitations", metadata.get("anti_use_cases", "not declared"))))
    card["diagnostics"] = [item for item in [*inventory["errors"], *inventory["warnings"]]
                           if item.get("component_ref") == card["component_ref"] or item["path"] in {card["path"], card["declaration"]}]
    _describe_action(card, candidate=candidate)
    return card


def _store_resolve_component(root: Path, value: str) -> tuple[Path, dict | None]:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    is_path = path.is_dir()
    ref = _validate_package(path)["component_ref"] if is_path else value
    parse_component_ref(ref)
    _selection_for_use(root)
    inventory = legacy_discover_components(root, include_references=True)
    if any(item["component_ref"] == ref and item.get("reference_only") and item.get("package_sha256") for item in inventory["assets"]):
        raise ComponentError(f"Reference assets cannot be installed: {ref}")
    matches = [item for item in inventory["assets"] if item["component_ref"] == ref and not item.get("reference_only")]
    if any(item.get("conflict") for item in matches):
        raise ComponentError(f"Conflicting identity/version across asset sources: {ref}")
    available = [item for item in matches if item["available"] and (not is_path or Path(item["path"]) == path.resolve())]
    if not available:
        detail = next((item["error"] for item in inventory["errors"] if item["path"] == str(path)), "")
        raise ComponentError(f"Asset is not accepted or compatible: {ref}" + (f": {detail}" if detail else ""))
    available.sort(key=lambda item: item["origin"] != "accepted")
    selected, acceptance = Path(available[0]["path"]), available[0]["acceptance"]
    report = _validate_package(selected, ref)
    if acceptance is not None:
        validate_component_acceptance(acceptance, report, runtime_root=root)
    return selected, acceptance


def _accepted_closure(store, references, *, runtime_root=None, visiting=None):
    from asset_contract import validate_reference
    if not isinstance(references, list):
        raise ComponentError("Asset references must be a list")
    visiting, resolved = set(visiting or ()), {}

    def visit(reference):
        validate_reference(reference)
        ref = reference["ref"]
        if ref in visiting:
            raise ComponentError(f"Cyclic asset dependency: {ref}")
        if ref in resolved:
            if any(reference[key] != resolved[ref][key] for key in ("kind", "package_sha256")):
                raise ComponentError(f"Conflicting exact asset references: {ref}")
            return
        relative = _relative(ref)
        package = _target(store, (Path("packages") / relative).as_posix())
        record = _target(store, (Path("acceptances") / relative / "acceptance.json").as_posix())
        if not package.is_dir() and not _target(store, (Path("candidates") / relative).as_posix()).exists():
            raise ComponentError(f"Legacy AssetStore package is missing: {ref} (store {store}); "
                                 "frozen Works keep their vendor copies, new bindings need the package restored "
                                 "or an explicit rebind to a card asset")
        if not record.is_file():
            raise ComponentError(f"Asset dependency is not accepted: {ref}")
        report = _validate_package(package, ref)
        if (report["metadata"].get("kind") != reference["kind"] or report["package_sha256"] != reference["package_sha256"]):
            raise ComponentError(f"Asset reference kind/hash mismatch: {ref}")
        acceptance = _read_json(record)
        validate_component_acceptance(acceptance, report, runtime_root=runtime_root)
        candidate = _target(store, (Path("candidates") / relative / "package").as_posix())
        if candidate.exists() and _validate_package(candidate, ref)["package_sha256"] != reference["package_sha256"]:
            raise ComponentError(f"Conflicting identity/version across asset sources: {ref}")
        visiting.add(ref)
        for dependency in report["metadata"].get("asset_dependencies", []):
            visit(dependency)
        visiting.remove(ref)
        resolved[ref] = {**reference, "path": str(package), "metadata": report["metadata"], "acceptance": acceptance}

    for reference in references:
        visit(reference)
    return list(resolved.values())


def _selection_for_use(root):
    try:
        store = asset_store_root(root)
    except ComponentError:
        return {}
    path = store / "selection.json"
    return _validate_selection(_read_json(path)) if path.exists() else {}


def card_asset_reference(root: Path, reference: str):
    from asset_contract import validate_card_asset, validate_card_asset_reference
    card, asset = validate_card_asset_reference(reference)
    source = _design_card_path(card, root) / 'assets' / asset
    report = validate_card_asset(source, expected_id=asset)
    return source, {"ref": f"{reference}@v{report['version']}", "kind": report['kind'],
                    "package_sha256": report['content_sha256'], "metadata": report['metadata'],
                    "card_ref": reference, "path": str(source), "acceptance": None}


def resolve_asset_closure(root: Path, references: list[dict]) -> list[dict]:
    """Resolve dependency-first accepted packages, never candidates or floating versions."""
    from asset_contract import validate_reference
    resolved, visiting = {}, set()
    def visit(reference):
        validate_reference(reference)
        ref = reference['ref']
        if ref in visiting:
            raise ComponentError('Cyclic asset dependency: ' + ref)
        if ref in resolved:
            if any(reference[key] != resolved[ref][key] for key in ('kind', 'package_sha256')):
                raise ComponentError('Conflicting exact asset references: ' + ref)
            return
        if '/' not in ref:
            try:
                store = asset_store_root(root)
            except ComponentError as error:
                raise ComponentError(f"Legacy asset reference {ref} needs the retired AssetStore, which is not "
                                     "configured; frozen Works keep their vendor copies, new bindings need asset_root "
                                     "restored or an explicit rebind to a card asset") from error
            for item in _accepted_closure(store, [reference], runtime_root=root):
                resolved[item['ref']] = item
            return
        source, item = card_asset_reference(root, ref.rsplit('@v', 1)[0])
        if any(reference[key] != item[key] for key in ('ref', 'kind', 'package_sha256')):
            raise ComponentError('Card asset reference changed: ' + ref)
        visiting.add(ref)
        for dependency in item['metadata'].get('asset_dependencies', []):
            visit(dependency)
        visiting.remove(ref)
        resolved[ref] = item
    for reference in references:
        visit(reference)
    closure = list(resolved.values())
    if all(item.get('card_ref') for item in closure):
        return closure
    selection = _selection_for_use(root)
    for item in closure:
        if _layer(item["metadata"], selection.get(item["ref"])) == "reference":
            raise ComponentError(f"Reference assets cannot be installed: {item['ref']}")
    resolved_refs = {item["ref"] for item in closure}
    for item in legacy_discover_components(root, include_references=True)["assets"]:
        if item["component_ref"] in resolved_refs and item.get("conflict"):
            raise ComponentError(f"Conflicting identity/version across asset sources: {item['component_ref']}")
    return closure


def resolve_asset(root: Path, reference: dict) -> tuple[Path, dict, dict]:
    closure = resolve_asset_closure(root, [reference])
    item = next(item for item in closure if item["ref"] == reference["ref"])
    path = Path(item["path"])
    return path, _validate_package(path, item["ref"]), item["acceptance"]


# --- v4.2 in-card asset library (D9/D10/D16) --------------------------------

CARD_ORIGIN = "card"
REFERENCE_ORIGIN = "reference"


def _design_catalog(root, config=None):
    """Valid cards and per-card problems; one bad card never hides the others."""
    import designs
    return designs.catalog_report(root=root, config=config)


def _design_card_path(identity, root, config=None):
    import designs
    return designs.card_path(identity, root=root, config=config)


def _declared_ratios(metadata):
    compatibility = metadata.get("compatibility", {})
    return compatibility.get("ratios", []) if isinstance(compatibility, dict) else []


def _card_asset_row(card_id, asset_id, asset_dir, report):
    metadata = report["metadata"]
    row = {
        "component_ref": f"{card_id}/{asset_id}", "card": card_id, "asset_id": asset_id,
        "package_sha256": report["content_sha256"], "path": str(asset_dir.resolve()),
        "origin": CARD_ORIGIN, "available": True, "status": "source",
        "asset_type": metadata.get("asset_type", "component"), "ratio": metadata.get("ratio"),
        "ratios": _declared_ratios(metadata),
        "communication_goal": metadata.get("communication_goal", metadata.get("description", "")),
        "information_shapes": metadata.get("information_shapes", []),
        "anti_use_cases": metadata.get("anti_use_cases", []), "acceptance": None,
        "verification": "card asset field contract checked; not accepted",
    }
    row.update({key: metadata[key] for key in ("purpose", "tags", "entry", "compatibility",
        "hit_offset", "hit_offset_estimated", "asset_layer", "broll") if key in metadata})
    if str(metadata.get("entry", "")).lower().endswith(".mp3"):
        row["media_type"] = "audio"
    return row


def _reference_row(card_id, reference, cards, root, config, problems=()):
    from asset_contract import validate_card_asset, validate_card_asset_reference
    source_card, asset_id = validate_card_asset_reference(reference)
    if source_card not in cards:
        reason = next((item["error"] for item in problems if item["card"] == source_card), None)
        if reason:
            raise ComponentError(f"Reference {reference} targets an unavailable card: {reason}")
        raise ComponentError(f"Reference {reference} targets a missing card: {source_card}")
    asset_dir = _design_card_path(source_card, root, config) / "assets" / asset_id
    if not (asset_dir / "asset.json").is_file():
        raise ComponentError(f"Reference {reference} targets a missing asset")
    report = validate_card_asset(asset_dir, expected_id=asset_id)
    row = _card_asset_row(source_card, asset_id, asset_dir, report)
    row.update(component_ref=reference, origin=REFERENCE_ORIGIN, available=False,
               reference_only=True, installable=False, status="reference",
               referenced_by=card_id, usable_by=[card_id], declaration=str(asset_dir / "asset.json"))
    return row


def _discover_card_components(root: Path, query: str = "", *, kind=None, ratio=None, tag=None,
                              recommendation=None, rebuild=False, research_root=None, audit=False,
                              config=None, asset_layer=None, include_references=False, broll_role=None,
                              design=None) -> dict:
    """Discover assets from design-card asset libraries.

    Identity is ``<card-id>/<asset-id>``; ``references`` in a card's
    ``design.json`` resolve read-only to the source card. No AssetStore or
    legacy repository root is read here.
    """
    from asset_contract import validate_asset_layer
    if asset_layer is not None and asset_layer != "unclassified":
        validate_asset_layer(asset_layer)
    if broll_role is not None and broll_role not in ("hook", "concept", "transition"):
        raise ComponentError("Invalid broll role filter")
    try:
        cards, problems = _design_catalog(root, config)
    except ComponentError:
        raise
    except Exception as error:
        raise ComponentError(f"Cannot read the design catalog: {error}") from error
    if design is not None and design not in cards:
        reason = next((item["error"] for item in problems if item["card"] == design), None)
        raise ComponentError(reason or f"Unknown design card: {design}")
    assets: list[dict] = []
    errors: list[dict] = [{"path": item["path"], "card": item["card"], "code": "card_unavailable",
                           "error": item["error"]} for item in problems]
    warnings: list[dict] = []
    seen: set = set()
    for card_id in sorted(cards):
        card = cards[card_id]
        if not isinstance(card, dict):
            errors.append({"path": str(card_id), "error": "Design card must be an object"})
            continue
        try:
            card_dir = _design_card_path(card_id, root, config)
        except (ComponentError, OSError, ValueError) as error:
            errors.append({"path": str(card_id), "error": f"Cannot locate card: {error}"})
            continue
        references = card.get("references") or []
        if not isinstance(references, list):
            errors.append({"path": str(card_dir / "design.json"), "error": "references must be a list"})
            references = []
        for reference in references:
            try:
                assets.append(_reference_row(card_id, reference, cards, root, config, problems))
            except ComponentError as error:
                errors.append({"path": str(card_dir / "design.json"), "component_ref": reference, "error": str(error)})
        assets_dir = card_dir / "assets"
        if not assets_dir.is_dir():
            continue
        for metadata_path in sorted(assets_dir.glob("*/asset.json")):
            asset_dir = metadata_path.parent
            asset_id = asset_dir.name
            try:
                if asset_dir.is_symlink() or not asset_dir.resolve().is_relative_to(assets_dir.resolve()):
                    raise ComponentError("Card asset path is unsafe")
                if asset_dir.resolve() in seen:
                    errors.append({"path": str(asset_dir), "error": "Duplicate card asset path"})
                    continue
                seen.add(asset_dir.resolve())
                from asset_contract import validate_card_asset
                report = validate_card_asset(asset_dir, expected_id=asset_id)
            except (ComponentError, OSError, ValueError, KeyError, TypeError) as error:
                errors.append({"path": str(asset_dir), "error": str(error)})
                continue
            assets.append(_card_asset_row(card_id, asset_id, asset_dir, report))
    # Selected-card scope is what install and appearance binding enforce: owner plus declaring cards.
    referencing: dict[str, list] = {}
    for asset in assets:
        if asset["origin"] == REFERENCE_ORIGIN:
            referencing.setdefault(asset["component_ref"], []).append(asset["referenced_by"])
    for asset in assets:
        if asset["origin"] == CARD_ORIGIN:
            asset["usable_by"] = [asset["card"], *sorted(referencing.get(asset["component_ref"], []))]
    for asset in assets:
        try:
            asset["asset_layer"] = "reference" if asset.get("reference_only") else _layer(asset)
        except ComponentError as error:
            errors.append({"path": asset["path"], "error": str(error)})
            asset.update(asset_layer="unclassified", available=False)
        asset["lifecycle"] = "card"
        asset["recommendation"] = asset.get("recommendation", "pending")
        asset["group"] = asset["origin"]
        asset["match_reasons"] = [key for key in ("component_ref", "title", "communication_goal", "purpose",
            "aliases", "tags", "information_shapes", "workflow_role", "primary_category", "limits")
            if query and query.casefold() in json.dumps(asset.get(key, ""), ensure_ascii=False).casefold()]
        if asset["origin"] == REFERENCE_ORIGIN:
            asset["use"] = (f"read-only reference declared by {asset['referenced_by']}; usable as "
                            f"{asset['component_ref']} only from Variants of {asset['referenced_by']}")
        elif asset["asset_type"] in {"theme", "background", "motion"}:
            asset["use"] = "appearance binding with exact card asset from Variants of: " + ", ".join(asset["usable_by"])
        else:
            asset["use"] = "card asset install with exact identity from Variants of: " + ", ".join(asset["usable_by"])
        _describe_action(asset)
    if query:
        assets = [asset for asset in assets if asset["match_reasons"]]
    if design is not None:
        assets = [asset for asset in assets if asset["origin"] == CARD_ORIGIN and asset["card"] == design
                  or asset["origin"] == REFERENCE_ORIGIN and asset["referenced_by"] == design]
    references_shown = include_references or design is not None
    assets = [asset for asset in assets if (not kind or asset["asset_type"] == kind or asset.get("media_type") == kind)
              and (not asset_layer or asset["asset_layer"] == asset_layer)
              and (references_shown or kind in {"scene-source", "recipe"} or asset_layer == "reference" or asset["asset_layer"] != "reference")
              and (not ratio or ratio.replace("x", ":") in asset["ratios"] or ratio == "unknown" and not asset["ratios"])
              and (not tag or tag in asset.get("tags", []))
              and (not broll_role or isinstance(asset.get("broll"), dict) and asset["broll"].get("role") == broll_role)
              and (not recommendation or asset["recommendation"] == recommendation)]
    assets.sort(key=lambda asset: (not asset["available"],
               {"recommended": 0, "pending": 1, "historical": 2}[asset["recommendation"]],
               asset["component_ref"], asset["path"]))
    warnings = list({json.dumps(item, sort_keys=True): item for item in warnings}.values())
    result = {"assets": assets, "errors": errors, "warnings": warnings, "conflicts": [], "refreshed": [],
              "filters": {"query": query, "kind": kind, "ratio": ratio, "tag": tag, "design": design,
                          "asset_layer": asset_layer, "recommendation": recommendation, "broll_role": broll_role,
                          "include_references": references_shown or kind in {"scene-source", "recipe"} or asset_layer == "reference"}}
    if not assets:
        result["message"] = ("No matches for these filters; this is not a complete inventory. "
                             "Reference entries are hidden unless explicitly requested.")
    if audit:
        result["audit"] = {"warnings": warnings, "warning_count": len(warnings), "error_count": len(errors)}
    if research_root is not None:
        from research_catalog import query as research_query
        result["research"] = research_query(research_root, query)["documents"]
    return result


def discover_components(root: Path, query: str = "", *, kind=None, ratio=None, tag=None,
                        recommendation=None, rebuild=False, research_root=None, audit=False,
                        config=None, asset_layer=None, include_references=False, broll_role=None,
                        design=None) -> dict:
    """Discover live card assets; legacy store discovery is an explicit compatibility API."""
    result = _discover_card_components(root, query, kind=kind, ratio=ratio, tag=tag,
        recommendation=recommendation, rebuild=rebuild, audit=audit, config=config,
        asset_layer=asset_layer, include_references=include_references, broll_role=broll_role, design=design)
    if research_root is not None:
        from research_catalog import query as research_query
        result["research"] = research_query(research_root, query)["documents"]
    return result


def _is_legacy_component_ref(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parse_component_ref(value)
    except ComponentError:
        return False
    return True


def _card_interface(root: Path, value: str):
    from asset_contract import validate_card_asset
    inventory = discover_components(root, include_references=True, audit=True)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        resolved = str(path.resolve())
    except (OSError, RuntimeError):
        resolved = None
    matches = [row for row in inventory["assets"] if row["path"] == resolved]
    matches = [row for row in matches if "card" in row]
    if not matches:
        matches = [row for row in inventory["assets"] if row["component_ref"] == value and "card" in row]
        owned = [row for row in matches if not row.get("reference_only")]
        if owned:
            matches = owned
    if not matches:
        return None
    if len(matches) > 1:
        raise ComponentError("Ambiguous card asset reference; select an exact target: "
                             + json.dumps([row["component_ref"] for row in matches], ensure_ascii=False))
    card = dict(matches[0])
    source = Path(card["path"])
    if card.get("reference_only"):
        raise ComponentError(f"Reference assets are read-only: {card['component_ref']}")
    report = validate_card_asset(source, expected_id=card["asset_id"])
    metadata = report["metadata"]
    card["declaration"] = str(source / "asset.json")
    card["check_scope"] = "card asset field contract checked; not accepted or frozen"
    keys = ("communication_goal", "purpose", "usage", "example", "examples", "ratio", "compatibility", "layers",
            "slots", "parameters", "duration_range", "motion_recipe", "customization", "broll", "limits", "limitations")
    card["interface"] = {key: metadata[key] for key in keys if key in metadata}
    card["interface"].setdefault("layers", "not declared; verify the selected card asset before use")
    for key in ("usage", "example"):
        name = metadata.get(key)
        if isinstance(name, str):
            try:
                attachment = source / _safe_relative(name, f"interface {key}")
                if not attachment.resolve().is_relative_to(source.resolve()):
                    raise ComponentError(f"Interface {key} escapes its directory")
                if not attachment.is_file():
                    raise ComponentError(f"Missing interface {key}: {attachment}")
                card["interface"][key] = attachment.read_text(encoding="utf-8-sig")
            except (OSError, RuntimeError, ValueError) as error:
                raise ComponentError(f"Invalid interface {key}: {error}") from error
    card.setdefault("purpose", metadata.get("purpose", metadata.get("communication_goal", metadata.get("description", "not declared"))))
    card.setdefault("examples", metadata.get("examples", []))
    card.setdefault("limitations", metadata.get("limits", metadata.get("limitations", metadata.get("anti_use_cases", "not declared"))))
    card["diagnostics"] = [item for item in [*inventory["errors"], *inventory["warnings"]]
                           if item.get("component_ref") == card["component_ref"]
                           or item.get("path") in {card["path"], card["declaration"]}]
    _describe_action(card)
    return card


def _is_card_asset_path(root: Path, path: Path, config=None) -> bool:
    """True when ``path`` is inside one catalog card's ``assets/`` directory."""
    try:
        cards, _ = _design_catalog(root, config)
    except (ComponentError, OSError, ValueError):
        return False
    for card_id in cards:
        try:
            assets_dir = (_design_card_path(card_id, root, config) / "assets").resolve()
            if path.resolve().is_relative_to(assets_dir):
                return True
        except (OSError, RuntimeError):
            continue
    return False


def component_interface(root: Path, value: str, *, candidate: bool = False) -> dict:
    """Read an exact card asset or accepted legacy object without installing."""
    if not candidate and not _is_legacy_component_ref(value):
        card = _card_interface(root, value)
        if card is not None:
            return card
    return _store_component_interface(root, value, candidate=candidate)


def resolve_component(root: Path, value: str) -> tuple[Path, dict | None]:
    """Resolve a card asset (identity or path) or an explicit legacy accepted ref."""
    from asset_contract import validate_card_asset
    if _is_legacy_component_ref(value):
        return _store_resolve_component(root, value)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    if path.is_dir() and (path / "asset.json").is_file() and _is_card_asset_path(root, path):
        validate_card_asset(path, expected_id=path.name)
        return path.resolve(), None
    inventory = discover_components(root, include_references=True, audit=True)
    matches = [row for row in inventory["assets"] if row["component_ref"] == value and "card" in row]
    if not matches:
        return _store_resolve_component(root, value)
    if matches[0].get("reference_only"):
        raise ComponentError(f"Reference assets cannot be installed: {value}")
    return Path(matches[0]["path"]), None
