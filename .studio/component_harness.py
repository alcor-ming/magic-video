#!/usr/bin/env python3
"""Small, dependency-free Component Release and Work installation contract."""

from __future__ import annotations

from contextlib import contextmanager

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET


PACKAGE_ALGORITHM = "component-package-sha256-v1"
ASSET_PACKAGE_ALGORITHM = "asset-package-sha256-v1"
OPTIONAL_SNAPSHOT_ITEMS = (
    "vendor", "component-bindings", "COMPONENT_LOCK.json", "scene-slots.json", "assets", "scenes", "shared",
    "runtime", "effects", "media", "shaders", "models", "textures", "hyperframes.json",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "appearance-lock.json",
)
REQUIRED_RELEASE_FILES = (
    "COMPONENT.md",
    "component.html",
    "contract.schema.json",
    "preview.fixture.json",
    "HASHES.json",
)
COMPONENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
COMPONENT_REF_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)?)@v([1-9][0-9]*)$")
SAFE_RELATIVE_RE = re.compile(r"^[^/]+(?:/[^/]+)*$")
SURFACE_KINDS = {
    "icon_node": {"none", "icon"},
    "active_media_card": {"none", "image", "video"},
}
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
VIDEO_SUFFIXES = {".m4v", ".mov", ".mp4", ".webm"}


class ComponentError(RuntimeError):
    """A failed-closed Component contract or installation operation."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComponentError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComponentError(f"Expected an object in {path}")
    return value


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ComponentError(f"Cannot read {path}: {exc}") from exc
    if not lines or lines[0] != "---":
        raise ComponentError(f"Missing JSON front matter in {path}")
    try:
        end = lines.index("---", 1)
        value = json.loads("\n".join(lines[1:end]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ComponentError(f"Invalid JSON front matter in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComponentError(f"Expected an object in {path} front matter")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _ensure_regular_tree(directory: Path) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ComponentError(f"Component package must be a regular directory: {directory}")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ComponentError(f"Component package cannot contain symlinks: {path}")


def _package_files(directory: Path) -> list[Path]:
    _ensure_regular_tree(directory)
    files = []
    for path in directory.rglob("*"):
        if path.is_file() and path.relative_to(directory).as_posix() != "HASHES.json":
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(directory).as_posix())


def package_entries(directory: Path) -> list[dict[str, str]]:
    """Return the canonical file digest list, excluding ``HASHES.json``."""

    entries = []
    for path in _package_files(directory):
        entries.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "sha256": file_sha256(path),
            }
        )
    return entries


def package_manifest_lines(directory: Path) -> str:
    return "".join(f"{item['sha256']}  {item['path']}\n" for item in package_entries(directory))


def component_package_sha256(directory: Path) -> str:
    """Calculate ``component-package-sha256-v1`` for a release directory."""

    return hashlib.sha256(package_manifest_lines(directory).encode("utf-8")).hexdigest()


# Short aliases keep callers from reimplementing the one canonical algorithm.
package_sha256 = component_package_sha256
package_hash = component_package_sha256
hash_package = component_package_sha256


def write_hashes(directory: Path) -> dict[str, Any]:
    metadata = _read_frontmatter(directory / "COMPONENT.md")
    component_id = metadata.get("component_id")
    version = metadata.get("version")
    if metadata.get("contract") == "component-contract-v2":
        component_id = f"{component_id}/{metadata.get('ratio')}"
    component_ref = f"{component_id}@v{version}" if component_id and version else None
    manifest = {
        "schema_version": 1,
        "algorithm": PACKAGE_ALGORITHM,
        "component_ref": component_ref,
        "files": package_entries(directory),
        "package_sha256": component_package_sha256(directory),
    }
    if metadata.get("contract") == "component-contract-v2":
        manifest.pop("schema_version")
        manifest["algorithm"] = ASSET_PACKAGE_ALGORITHM
        manifest["asset_ref"] = manifest.pop("component_ref")
    _atomic_json(directory / "HASHES.json", manifest)
    return manifest


def _validate_hashes(directory: Path, *, ratio_contract: bool = False) -> dict[str, Any]:
    hashes = _read_json(directory / "HASHES.json")
    expected_algorithm = ASSET_PACKAGE_ALGORITHM if ratio_contract else PACKAGE_ALGORITHM
    if hashes.get("algorithm") != expected_algorithm or (not ratio_contract and hashes.get("schema_version") != 1):
        raise ComponentError("HASHES.json has an unsupported schema or algorithm")
    actual_entries = package_entries(directory)
    if hashes.get("files") != actual_entries:
        raise ComponentError("HASHES.json file digest list does not match the package")
    actual_root = component_package_sha256(directory)
    if hashes.get("package_sha256") != actual_root:
        raise ComponentError("HASHES.json package hash does not match the package")
    return hashes


def parse_component_ref(value: str) -> tuple[str, int]:
    """Return the package path (including an optional ratio) and version."""
    match = COMPONENT_REF_RE.fullmatch(value)
    if not match:
        raise ComponentError(f"Invalid component ref: {value!r}")
    return match.group(1), int(match.group(2))


def _metadata_slots(metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    slots = metadata.get("slots")
    if not isinstance(slots, dict):
        raise ComponentError("COMPONENT.md must define structured slots")
    required = slots.get("required")
    optional = slots.get("optional", [])
    if not isinstance(required, list) or not isinstance(optional, list):
        raise ComponentError("COMPONENT.md slots.required/optional must be arrays")
    if not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in [*required, *optional]):
        raise ComponentError("COMPONENT.md slot entries must have names")
    names = [item["name"] for item in [*required, *optional]]
    if len(names) != len(set(names)):
        raise ComponentError("COMPONENT.md slot names must be unique")
    return required, optional


def _schema_slots(schema: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    slots = schema.get("slots")
    if not isinstance(slots, dict):
        raise ComponentError("contract.schema.json must define slots")
    required = slots.get("required")
    properties = slots.get("properties")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ComponentError("contract.schema.json slots.required must be an array of names")
    if not isinstance(properties, dict):
        raise ComponentError("contract.schema.json slots.properties must be an object")
    if len(required) != len(set(required)) or any(name not in properties for name in required):
        raise ComponentError("contract.schema.json required slots must have properties")
    return required, properties


def _surface_specs(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ComponentError(f"{label} must be a non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ComponentError(f"{label} entries must be objects")
        surface_id = item.get("surface_id")
        kind = item.get("kind")
        modes = item.get("modes")
        fallback = item.get("fallback")
        required = item.get("required")
        if not isinstance(surface_id, str) or not COMPONENT_ID_RE.fullmatch(surface_id):
            raise ComponentError(f"{label} has an invalid surface_id")
        if surface_id in result:
            raise ComponentError(f"{label} has duplicate surface_id: {surface_id}")
        if kind not in SURFACE_KINDS:
            raise ComponentError(f"{label} {surface_id} has an unsupported kind")
        if (
            not isinstance(modes, list)
            or not modes
            or not all(isinstance(mode, str) for mode in modes)
            or len(modes) != len(set(modes))
            or not set(modes) <= SURFACE_KINDS[kind]
        ):
            raise ComponentError(f"{label} {surface_id} has invalid modes")
        if not isinstance(required, bool) or not isinstance(fallback, str) or not fallback:
            raise ComponentError(f"{label} {surface_id} must define required and fallback")
        result[surface_id] = {
            "surface_id": surface_id,
            "kind": kind,
            "modes": modes,
            "required": required,
            "fallback": fallback,
        }
    return result


def _check_value(value: Any, rule: dict[str, Any], path: str) -> None:
    if value is None and rule.get("nullable"):
        return
    kind = rule.get("type")
    type_ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }.get(kind, True)
    if not type_ok:
        raise ComponentError(f"{path} must have type {kind}")
    choices = rule.get("enum")
    if isinstance(choices, list) and value not in choices:
        raise ComponentError(f"{path} is not one of its allowed values")
    if isinstance(value, str):
        pattern = rule.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            raise ComponentError(f"{path} does not match its contract pattern")
        if isinstance(rule.get("minLength"), int) and len(value) < rule["minLength"]:
            raise ComponentError(f"{path} is shorter than its contract")
        if isinstance(rule.get("maxLength"), int) and len(value) > rule["maxLength"]:
            raise ComponentError(f"{path} is longer than its contract")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(rule.get("minimum"), (int, float)) and value < rule["minimum"]:
            raise ComponentError(f"{path} is below its contract minimum")
        if isinstance(rule.get("maximum"), (int, float)) and value > rule["maximum"]:
            raise ComponentError(f"{path} is above its contract maximum")
    if isinstance(value, list):
        if isinstance(rule.get("minItems"), int) and len(value) < rule["minItems"]:
            raise ComponentError(f"{path} has fewer items than its contract")
        if isinstance(rule.get("maxItems"), int) and len(value) > rule["maxItems"]:
            raise ComponentError(f"{path} has more items than its contract")
        item_rule = rule.get("items")
        if isinstance(item_rule, dict):
            for index, item in enumerate(value):
                _check_value(item, item_rule, f"{path}[{index}]")
    if isinstance(value, dict):
        required = rule.get("required", [])
        properties = rule.get("properties", {})
        if isinstance(required, list):
            missing = sorted(name for name in required if name not in value)
            if missing:
                raise ComponentError(f"{path} is missing required fields: {missing}")
        if isinstance(properties, dict):
            if rule.get("additionalProperties") is False:
                unknown = sorted(set(value) - set(properties))
                if unknown:
                    raise ComponentError(f"{path} has unsupported fields: {unknown}")
            for name, child in value.items():
                child_rule = properties.get(name)
                if isinstance(child_rule, dict):
                    _check_value(child, child_rule, f"{path}.{name}")


def validate_component_release(directory: Path, expected_ref: str | None = None, *, allow_unapproved: bool = False) -> dict[str, Any]:
    """Validate one immutable Component Release and return its report."""

    directory = Path(directory)
    if (directory / "asset.json").is_file():
        from asset_contract import validate_asset
        return validate_asset(directory, expected_ref)
    _ensure_regular_tree(directory)
    missing = [name for name in REQUIRED_RELEASE_FILES if not (directory / name).is_file()]
    if missing:
        raise ComponentError(f"Component package is missing: {', '.join(missing)}")
    if not (directory / "baselines").is_dir():
        raise ComponentError("Component package is missing baselines/")

    metadata = _read_frontmatter(directory / "COMPONENT.md")
    if metadata.get("contract") not in {None, "component-contract-v1", "component-contract-v2"}:
        raise ComponentError("Unsupported Component contract")
    component_id = metadata.get("component_id")
    version = metadata.get("version")
    if not isinstance(component_id, str) or not COMPONENT_ID_RE.fullmatch(component_id):
        raise ComponentError("COMPONENT.md component_id is invalid")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ComponentError("COMPONENT.md version must be a positive integer")
    ratio_contract = metadata.get("contract") == "component-contract-v2"
    ratio = metadata.get("ratio") if ratio_contract else None
    if ratio_contract and ratio not in {"4x3", "16x9", "9x16"}:
        raise ComponentError("COMPONENT.md ratio must be 4x3, 16x9 or 9x16")
    component_ref = f"{component_id}/{ratio}@v{version}" if ratio_contract else f"{component_id}@v{version}"
    if expected_ref is not None and component_ref != expected_ref:
        raise ComponentError(f"Expected {expected_ref}, found {component_ref}")
    if metadata.get("status") != "library-approved" and not allow_unapproved:
        raise ComponentError("Component Release status must be library-approved")
    legacy_fields = ("profile", "subtemplate", "state_change", "entry_contract", "exit_contract",
                     "semantic_jobs", "anti_use_cases", "states", "visual_surfaces", "preview")
    for key in (*(("theme_tokens",) if ratio_contract else legacy_fields),
        "communication_goal",
        "semantic_roles",
        "information_shapes",
        "evidence_modes",
        "content_density",
        "duration_range",
        "motion_recipe",
        "asset_contract",
        "customization",
        "artifact",
    ):
        if key not in metadata:
            raise ComponentError(f"COMPONENT.md is missing structured field: {key}")
    required_meta, optional_meta = _metadata_slots(metadata)

    schema = _read_json(directory / "contract.schema.json")
    schema_version = 2 if ratio_contract else 1
    if schema.get("schema_version") != schema_version:
        raise ComponentError(f"contract.schema.json schema_version must be {schema_version}")
    if schema.get("component_ref") != component_ref:
        raise ComponentError("contract.schema.json component_ref does not match COMPONENT.md")
    if ratio_contract and schema.get("ratio") != ratio:
        raise ComponentError("contract.schema.json ratio does not match COMPONENT.md")
    if "layers" in metadata or "layers" in schema:
        raise ComponentError("Retired card projection contract is unsupported")
    if not ratio_contract and (schema.get("profile") != metadata.get("profile") or schema.get("subtemplate") != metadata.get("subtemplate")):
        raise ComponentError("contract.schema.json profile/subtemplate does not match COMPONENT.md")
    required_schema, properties = _schema_slots(schema)
    metadata_names = [item["name"] for item in [*required_meta, *optional_meta]]
    if required_schema != [item["name"] for item in required_meta] or set(properties) != set(metadata_names):
        raise ComponentError("COMPONENT.md and contract.schema.json slots disagree")
    surface_specs = _surface_specs(metadata["visual_surfaces"], "COMPONENT.md visual_surfaces") if "visual_surfaces" in metadata else {}
    schema_surface_specs = _surface_specs(schema["visual_surfaces"], "contract.schema.json visual_surfaces") if "visual_surfaces" in schema else {}
    if surface_specs != schema_surface_specs:
        raise ComponentError("COMPONENT.md and contract.schema.json visual_surfaces disagree")
    metadata_assets = metadata.get("asset_contract")
    schema_assets = schema.get("assets")
    if not isinstance(metadata_assets, dict) or not isinstance(schema_assets, dict):
        raise ComponentError("Component asset contracts must be objects")
    if metadata_assets.get("allowed_types") != schema_assets.get("allowed_types"):
        raise ComponentError("COMPONENT.md and contract.schema.json asset types disagree")
    metadata_scale = metadata.get("motion_recipe", {}).get("allowed_time_scale")
    schema_scale = schema.get("timing", {}).get("allowed_time_scale")
    if not isinstance(metadata_scale, dict) or not isinstance(schema_scale, dict):
        raise ComponentError("Component timeScale contracts must be objects")
    if {
        "minimum": metadata_scale.get("minimum", metadata_scale.get("min")),
        "maximum": metadata_scale.get("maximum", metadata_scale.get("max")),
    } != {
        "minimum": schema_scale.get("minimum", schema_scale.get("min")),
        "maximum": schema_scale.get("maximum", schema_scale.get("max")),
    }:
        raise ComponentError("COMPONENT.md and contract.schema.json timeScale ranges disagree")

    fixture = _read_json(directory / "preview.fixture.json")
    if fixture.get("schema_version") != schema_version or fixture.get("component_ref") != component_ref:
        raise ComponentError("preview.fixture.json does not target this Component Release")
    fixture_slots = fixture.get("slots")
    if not isinstance(fixture_slots, dict):
        raise ComponentError("preview.fixture.json slots must be an object")
    unknown = sorted(set(fixture_slots) - set(properties))
    missing_fixture = sorted(set(required_schema) - set(fixture_slots))
    if unknown or missing_fixture:
        raise ComponentError(f"preview.fixture.json slots mismatch: unknown={unknown}, missing={missing_fixture}")
    for name, value in fixture_slots.items():
        _check_value(value, properties[name], f"preview.fixture.json slots.{name}")
    fixture_surfaces = fixture.get("surfaces", {}) if ratio_contract else fixture.get("surfaces")
    if not isinstance(fixture_surfaces, dict) or set(fixture_surfaces) != set(surface_specs):
        raise ComponentError("preview.fixture.json surfaces must match the Component Surface contract")
    for surface_id, surface in fixture_surfaces.items():
        if not isinstance(surface, dict):
            raise ComponentError(f"preview.fixture.json surfaces.{surface_id} must be an object")
        spec = surface_specs[surface_id]
        if surface.get("kind") != spec["kind"] or surface.get("mode") not in spec["modes"]:
            raise ComponentError(f"preview.fixture.json surfaces.{surface_id} has invalid kind/mode")
        if surface["mode"] == "none":
            if surface.get("fallback") != spec["fallback"] or "path" in surface:
                raise ComponentError(f"preview.fixture.json surfaces.{surface_id} has invalid fallback")
        elif not isinstance(surface.get("path"), str):
            raise ComponentError(f"preview.fixture.json surfaces.{surface_id} requires a path")

    artifact = metadata["artifact"]
    if not isinstance(artifact, dict) or not isinstance(artifact.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
        raise ComponentError("COMPONENT.md artifact.sha256 is required")
    hashes = _validate_hashes(directory, ratio_contract=ratio_contract)
    if hashes.get("asset_ref" if ratio_contract else "component_ref") != component_ref:
        raise ComponentError("HASHES.json component_ref does not match COMPONENT.md")
    validate_surface_dom(directory / "component.html", surface_specs)
    validate_component_transport(directory / "component.html", component_id, metadata_names, surface_specs,
                                 require_root_id=not ratio_contract)
    if ratio_contract:
        _, parser = _parse_html(directory / "component.html")
        root = next(node["attrs"] for node in parser.nodes if node["attrs"].get("data-composition-id") == component_id)
        dimensions = {"4x3": ("1440", "1080"), "16x9": ("1920", "1080"), "9x16": ("1080", "1920")}[ratio]
        if (root.get("data-width"), root.get("data-height")) != dimensions:
            raise ComponentError("component.html dimensions do not match the ratio contract")
    return {
        "component_ref": component_ref,
        "component_id": component_id,
        "version": version,
        "profile": metadata.get("profile"),
        "subtemplate": metadata.get("subtemplate"),
        "ratio": ratio,
        "package_sha256": hashes["package_sha256"],
        "files": hashes["files"],
        "metadata": metadata,
        "schema": schema,
        "fixture": fixture,
        "surface_specs": surface_specs,
    }


def validate_component_acceptance(acceptance: dict, release: dict, *, runtime_root: Path | None = None) -> None:
    """Check the separate acceptance without rewriting hash-covered metadata."""
    if (not isinstance(acceptance, dict) or acceptance.get("schema_version") != 1
            or acceptance.get("status") != "accepted"
            or acceptance.get("component_ref") != release["component_ref"]
            or acceptance.get("package_sha256") != release["package_sha256"]
            or not acceptance.get("accepted_at") or not acceptance.get("note")):
        raise ComponentError(f"Asset acceptance does not match the exact package: {release['component_ref']}")
    if acceptance.get("review") and os.environ.get("HYPERFRAMES_AI_REVIEW") != "1":
        raise ComponentError("Review asset acceptance cannot be used in production")
    from asset_contract import asset_requires_runtime
    if not asset_requires_runtime(release["metadata"]):
        return
    root = runtime_root or Path(os.environ.get("HYPERFRAMES_AI_ROOT", Path(__file__).resolve().parents[1]))
    from root_deploy import runtime_lock_path
    try:
        lock_path = runtime_lock_path(root)
    except ValueError as error:
        raise ComponentError(str(error)) from error
    lock = _read_json(lock_path)
    runtime = acceptance.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("target") != lock.get("target"):
        raise ComponentError(f"Asset runtime target is incompatible: {release['component_ref']}")
    versions = runtime.get("versions")
    if not isinstance(versions, dict) or "hyperframes" not in versions:
        raise ComponentError("Asset acceptance requires the tested HyperFrames version")
    declared = release["metadata"].get("runtime", {})
    if not isinstance(declared, dict):
        raise ComponentError("Asset runtime compatibility must be an object")
    if declared.get("target", lock["target"]) != lock["target"]:
        raise ComponentError(f"Asset declared runtime target is incompatible: {release['component_ref']}")
    required = declared.get("versions", {})
    if not isinstance(required, dict) or not set(required) <= set(versions):
        raise ComponentError("Asset runtime versions must be an object")
    for name, tested in versions.items():
        if tested != lock.get("versions", {}).get(name):
            raise ComponentError(f"Asset runtime version is incompatible: {release['component_ref']} {name}")
    for name, allowed in required.items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if lock.get("versions", {}).get(name) not in allowed:
            raise ComponentError(f"Asset declared runtime version is incompatible: {release['component_ref']} {name}")


def _safe_relative(value: str, label: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or not SAFE_RELATIVE_RE.fullmatch(value):
        raise ComponentError(f"Invalid {label}: {value!r}")
    return path.as_posix()


def validate_binding(binding: dict[str, Any], release: dict[str, Any]) -> dict[str, Any]:
    kind = release["metadata"].get("asset_type")
    if kind in {"theme", "background", "motion", "module", "media", "character", "icon-set"} and isinstance(binding, dict) and binding.get("scope") == "dependency":
        if (binding != {"schema_version": 3, "component_ref": release["component_ref"], "scope": "dependency"}):
            raise ComponentError("Dependency Binding requires schema_version 3 and exact component_ref")
        return binding
    if kind in {"theme", "background", "motion", "icon-set"}:
        if (not isinstance(binding, dict) or binding.get("schema_version") != 3
                or binding.get("component_ref") != release["component_ref"]
                or set(binding) != {"schema_version", "component_ref", "usage"}
                or binding.get("usage") != {"role": kind, "required": True}
                or binding["usage"]["required"] is not True):
            raise ComponentError("Appearance Binding requires exact ref and kind usage")
        return binding
    if kind in {"module", "media", "character"}:
        if (not isinstance(binding, dict) or binding.get("schema_version") != 3
                or binding.get("component_ref") != release["component_ref"]):
            raise ComponentError("Asset Binding requires schema_version 3 and exact component_ref")
        if not isinstance(binding.get("scene"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", binding["scene"]):
            raise ComponentError("Binding scene is invalid")
        usage = binding.get("usage")
        roles = {"character"} if kind == "character" else {"subject", "evidence", "texture", "auxiliary"}
        if (not isinstance(usage, dict) or usage.get("role") not in roles
                or not isinstance(usage.get("required"), bool)):
            raise ComponentError("Asset Binding usage requires role and boolean required")
        if set(usage) - {"role", "required", "fit", "focal_point"}:
            raise ComponentError("Unsupported asset usage fields; layout and timing belong to the Scene")
        if "fit" in usage and usage["fit"] not in {"contain", "cover", "fill"}:
            raise ComponentError("Invalid asset usage fit")
        point = usage.get("focal_point", [0.5, 0.5])
        if (not isinstance(point, list) or len(point) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in point)):
            raise ComponentError("Asset focal_point requires two normalized coordinates")
        if set(binding) - {"schema_version", "component_ref", "scene", "usage"}:
            raise ComponentError("Unsupported asset Binding fields")
        return binding
    schema_version = release["schema"]["schema_version"]
    if not isinstance(binding, dict) or binding.get("schema_version") != schema_version:
        raise ComponentError(f"Binding schema_version must be {schema_version}")
    if binding.get("component_ref") != release["component_ref"]:
        raise ComponentError("Binding component_ref does not match the Component Release")
    scene = binding.get("scene")
    if not isinstance(scene, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", scene):
        raise ComponentError("Binding scene is invalid")
    slots = binding.get("slots")
    if not isinstance(slots, dict):
        raise ComponentError("Binding slots must be an object")
    required, properties = _schema_slots(release["schema"])
    missing = sorted(set(required) - set(slots))
    unknown = sorted(set(slots) - set(properties))
    if missing or unknown:
        raise ComponentError(f"Binding slots mismatch: unknown={unknown}, missing={missing}")
    for name, value in slots.items():
        _check_value(value, properties[name], f"Binding slots.{name}")
    placement = binding.get("placement")
    if not isinstance(placement, dict):
        raise ComponentError("Binding placement must be an object")
    for key in ("width", "height"):
        value = placement.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ComponentError(f"Binding placement.{key} must be positive")
    if release.get("ratio"):
        width, height = map(int, release["ratio"].split("x"))
        if abs(placement["width"] * height - placement["height"] * width) > 0.001:
            raise ComponentError("Binding placement does not match the Component ratio")
    timing = binding.get("timing")
    if not isinstance(timing, dict):
        raise ComponentError("Binding timing must be an object")
    required_timing = ("offset", "time_scale", "hero_hold", "handoff_hold")
    for key in required_timing:
        value = timing.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ComponentError(f"Binding timing.{key} must be a non-negative number")
    if "duration" in timing and (
        not isinstance(timing["duration"], (int, float))
        or isinstance(timing["duration"], bool)
        or timing["duration"] < 0
    ):
        raise ComponentError("Binding timing.duration must be a non-negative number")
    allowed_scale = release["metadata"].get("motion_recipe", {}).get("allowed_time_scale", {})
    if not isinstance(allowed_scale, dict):
        raise ComponentError("Component Release is missing its timeScale contract")
    minimum = allowed_scale.get("min", allowed_scale.get("minimum"))
    maximum = allowed_scale.get("max", allowed_scale.get("maximum"))
    if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)):
        raise ComponentError("Component Release has an invalid timeScale contract")
    if timing["time_scale"] < minimum or timing["time_scale"] > maximum:
        raise ComponentError("Binding timing.time_scale is outside the Component contract")
    surfaces = binding.get("surfaces")
    if not isinstance(surfaces, dict):
        raise ComponentError("Binding surfaces must be an object")
    specs = release["surface_specs"]
    missing_surfaces = sorted(surface_id for surface_id, spec in specs.items() if spec["required"] and surface_id not in surfaces)
    unknown_surfaces = sorted(set(surfaces) - set(specs))
    if missing_surfaces or unknown_surfaces:
        raise ComponentError(f"Binding surfaces mismatch: unknown={unknown_surfaces}, missing={missing_surfaces}")
    for surface_id, surface in surfaces.items():
        if not isinstance(surface, dict):
            raise ComponentError(f"Binding surfaces.{surface_id} must be an object")
        unknown_keys = sorted(set(surface) - {"kind", "mode", "fallback", "path"})
        if unknown_keys:
            raise ComponentError(f"Binding surfaces.{surface_id} has unsupported fields: {unknown_keys}")
        spec = specs[surface_id]
        if surface.get("kind") != spec["kind"] or surface.get("mode") not in spec["modes"]:
            raise ComponentError(f"Binding surfaces.{surface_id} does not match its kind/modes contract")
        mode = surface["mode"]
        if mode == "none":
            if surface.get("fallback") != spec["fallback"] or "path" in surface:
                raise ComponentError(f"Binding surfaces.{surface_id} none mode requires only its declared fallback")
        else:
            if "fallback" in surface:
                raise ComponentError(f"Binding surfaces.{surface_id} media mode cannot override fallback")
            _validate_local_asset_path(surface.get("path"), f"Binding surfaces.{surface_id}.path")
    assets = binding.get("assets")
    if not isinstance(assets, dict):
        raise ComponentError("Binding assets must be an object")
    _validate_asset_values(assets, "Binding assets")
    return binding


def _validate_local_asset_path(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise ComponentError(f"{path} must be a non-empty Work-relative path")
    candidate = Path(value)
    if (
        candidate.is_absolute()
        or value.startswith("/")
        or "\\" in value
        or ".." in candidate.parts
        or re.match(r"^[A-Za-z]:", value)
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    ):
        raise ComponentError(f"{path} must be a local Work-relative path")


def _validate_asset_values(value: Any, path: str, key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _validate_asset_values(child_value, f"{path}.{child_key}", str(child_key))
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            _validate_asset_values(child_value, f"{path}[{index}]", key)
    elif isinstance(value, str) and key not in {"type", "kind", "format", "role", "label"}:
        _validate_local_asset_path(value, path)


class _SurfaceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, Any]] = []
        self.template_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "template":
            self.template_depth += 1
        self.nodes.append({"tag": tag, "attrs": dict(attrs), "in_template": self.template_depth > 0})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "template":
            self.template_depth -= 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "template" and self.template_depth:
            self.template_depth -= 1


def _parse_html(path: Path) -> tuple[str, _SurfaceHTMLParser]:
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ComponentError(f"Cannot read HTML {path}: {exc}") from exc
    parser = _SurfaceHTMLParser()
    parser.feed(source)
    parser.close()
    return source, parser


def validate_surface_dom(html_path: Path, surface_specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Require one stable DOM anchor for every declared public Surface."""

    _, parser = _parse_html(Path(html_path))
    found: dict[str, dict[str, str | None]] = {}
    for node in parser.nodes:
        attrs = node["attrs"]
        surface_id = attrs.get("data-visual-surface")
        if surface_id is None:
            continue
        if not node["in_template"]:
            raise ComponentError(f"Component DOM Surface must be inside <template>: {surface_id}")
        if surface_id in found:
            raise ComponentError(f"Component DOM has duplicate Surface: {surface_id}")
        found[surface_id] = attrs
    if set(found) != set(surface_specs):
        raise ComponentError(
            f"Component DOM Surface mismatch: declared={sorted(surface_specs)}, found={sorted(found)}"
        )
    for surface_id, spec in surface_specs.items():
        attrs = found[surface_id]
        if attrs.get("data-surface-kind") != spec["kind"]:
            raise ComponentError(f"Component DOM Surface kind mismatch: {surface_id}")
        if attrs.get("data-surface-modes") != ",".join(spec["modes"]):
            raise ComponentError(f"Component DOM Surface modes mismatch: {surface_id}")
        if attrs.get("data-surface-fallback") != spec["fallback"]:
            raise ComponentError(f"Component DOM Surface fallback mismatch: {surface_id}")
    return {"surfaces": sorted(found)}


def validate_component_transport(
    html_path: Path,
    component_id: str,
    slot_names: list[str],
    surface_specs: dict[str, dict[str, Any]],
    *,
    require_root_id: bool = True,
) -> dict[str, Any]:
    source, parser = _parse_html(Path(html_path))
    roots = [node for node in parser.nodes if node["attrs"].get("data-composition-id") == component_id]
    if len(roots) != 1 or not roots[0]["in_template"] or (require_root_id and not roots[0]["attrs"].get("id")):
        raise ComponentError("component.html requires one matching composition root inside <template>")
    variables_raw = roots[0]["attrs"].get("data-composition-variables")
    try:
        variables = json.loads(variables_raw or "")
    except json.JSONDecodeError as exc:
        raise ComponentError("component.html has invalid data-composition-variables") from exc
    if not isinstance(variables, list) or not all(isinstance(item, dict) for item in variables):
        raise ComponentError("component.html data-composition-variables must be an array")
    variable_ids = [item.get("id") for item in variables]
    if not all(isinstance(value, str) for value in variable_ids) or len(variable_ids) != len(set(variable_ids)):
        raise ComponentError("component.html variables require unique string ids")
    expected = set(slot_names) | {"time_scale"}
    for surface_id in surface_specs:
        expected.update({f"{surface_id}_mode", f"{surface_id}_path"})
    if not expected <= set(variable_ids):
        raise ComponentError(f"component.html variables are missing: {sorted(expected - set(variable_ids))}")
    for item in variables:
        if not {"id", "type", "label", "default"} <= set(item):
            raise ComponentError(f"component.html variable is incomplete: {item.get('id', '<unknown>')}")
        if item.get("type") == "enum" and (
            not isinstance(item.get("options"), list)
            or not item["options"]
            or not all(
                isinstance(option, dict)
                and isinstance(option.get("value"), str)
                and isinstance(option.get("label"), str)
                for option in item["options"]
            )
        ):
            raise ComponentError(f"component.html enum variable has invalid options: {item.get('id')}")
    for node in parser.nodes:
        attrs = node["attrs"]
        if node["tag"] not in {"img", "video"}:
            continue
        fallback = attrs.get("src")
        if not isinstance(fallback, str) or not fallback:
            raise ComponentError("component.html media requires a fallback src")
        if fallback.startswith("data:"):
            continue
        relative = _safe_relative(fallback, "component media fallback")
        if not (Path(html_path).parent / relative).is_file():
            raise ComponentError(f"component.html media fallback is missing: {fallback}")
    if any("harness" in str(node["attrs"].get("class", "")).split() for node in parser.nodes):
        raise ComponentError("component.html cannot ship the prototype harness toolbar")
    if re.search(r"requestVideoFrameCallback|\.play\s*\(|\.pause\s*\(|\.currentTime\b", source):
        raise ComponentError("component.html cannot own a media playback clock")
    return {"composition_id": component_id, "variables": variable_ids}


def _resolve_work_asset(project: Path, value: str) -> Path:
    _validate_local_asset_path(value, "Surface path")
    root = Path(project).resolve()
    candidate = Path(project) / value
    cursor = Path(project)
    for part in Path(value).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ComponentError(f"Surface asset path cannot contain symlinks: {value}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ComponentError(f"Surface asset is missing: {value}") from exc
    if root not in resolved.parents or not resolved.is_file():
        raise ComponentError(f"Surface asset escapes the Work project: {value}")
    return resolved


def _svg_probe(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ComponentError(f"Invalid SVG Surface asset: {path}") from exc
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() == "script":
            raise ComponentError(f"SVG Surface asset cannot contain scripts: {path}")
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].lower()
            if local_name.startswith("on") or (
                local_name in {"href", "src"} and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
            ):
                raise ComponentError(f"SVG Surface asset contains active or remote content: {path}")
    return {
        "format": "svg",
        "width": root.attrib.get("width"),
        "height": root.attrib.get("height"),
        "viewBox": root.attrib.get("viewBox"),
    }


def _asset_probe(path: Path, mode: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    expected = IMAGE_SUFFIXES if mode in {"image", "icon"} else VIDEO_SUFFIXES
    if suffix not in expected:
        raise ComponentError(f"Surface asset type does not match {mode}: {path.name}")
    if suffix == ".svg":
        return _svg_probe(path)
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,codec_type,width,height,duration:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ComponentError(f"Cannot probe Surface asset {path}: {exc}") from exc
    if process.returncode != 0:
        raise ComponentError(f"ffprobe rejected Surface asset {path}: {process.stderr.strip()}")
    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ComponentError(f"ffprobe returned invalid JSON for {path}") from exc
    streams = report.get("streams") if isinstance(report, dict) else None
    if not isinstance(streams, list) or not any(item.get("codec_type") == "video" for item in streams if isinstance(item, dict)):
        raise ComponentError(f"Surface asset has no visual stream: {path}")
    return report


def validate_surface_payloads(
    project: Path,
    binding: dict[str, Any],
    release: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    validate_binding(binding, release)
    records: dict[str, dict[str, Any]] = {}
    for surface_id, surface in sorted(binding["surfaces"].items()):
        record: dict[str, Any] = {
            "surface_id": surface_id,
            "kind": surface["kind"],
            "mode": surface["mode"],
        }
        if surface["mode"] == "none":
            record["fallback"] = surface["fallback"]
        else:
            asset = _resolve_work_asset(Path(project), surface["path"])
            probe = _asset_probe(asset, surface["mode"])
            record.update(
                {
                    "path": surface["path"],
                    "sha256": file_sha256(asset),
                    "probe": probe,
                    "probe_sha256": hashlib.sha256(
                        json.dumps(probe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                }
            )
        records[surface_id] = record
    return records


def _load_binding(value: dict[str, Any] | Path) -> dict[str, Any]:
    if isinstance(value, Path):
        return _read_json(value)
    return value


def _same_tree(left: Path, right: Path) -> bool:
    left_files = {path.relative_to(left).as_posix() for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right).as_posix() for path in right.rglob("*") if path.is_file()}
    if left_files != right_files:
        return False
    return all(file_sha256(left / relative) == file_sha256(right / relative) for relative in left_files)


def _vendor_relative(component_id: str, version: int) -> str:
    return f"vendor/components/{component_id}/v{version}"


def _lock_components(lock: dict[str, Any]) -> list[dict[str, Any]]:
    if lock.get("schema_version") not in {1, 2}:
        raise ComponentError("COMPONENT_LOCK.json schema_version must be 1 or 2")
    if lock.get("algorithm") != PACKAGE_ALGORITHM:
        raise ComponentError("COMPONENT_LOCK.json algorithm must be component-package-sha256-v1")
    components = lock.get("components", [])
    if not isinstance(components, list) or not all(isinstance(item, dict) for item in components):
        raise ComponentError("COMPONENT_LOCK.json components must be an array")
    refs = [item.get("component_ref") for item in components]
    if len(refs) != len(set(refs)):
        raise ComponentError("COMPONENT_LOCK.json component_ref values must be unique")
    if lock["schema_version"] == 1 and any(item.get("asset_kind") for item in components):
        raise ComponentError("Generic assets require COMPONENT_LOCK.json schema_version 2")
    return components


def _lock_bindings(record: dict[str, Any]) -> list[dict[str, Any]]:
    bindings = record.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ComponentError(f"Lock record {record.get('component_ref', '<unknown>')} requires bindings[]")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in bindings:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise ComponentError("Lock bindings must contain path and sha256")
        path = _safe_relative(item["path"], "binding path")
        digest = item["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ComponentError(f"Invalid binding hash in lock: {path}")
        if path in seen:
            raise ComponentError(f"Duplicate binding path in lock: {path}")
        surfaces = item.get("surfaces")
        if not isinstance(surfaces, list) or not all(isinstance(surface, dict) for surface in surfaces):
            raise ComponentError(f"Lock binding requires surfaces[]: {path}")
        surface_ids = [surface.get("surface_id") for surface in surfaces]
        if not all(isinstance(surface_id, str) for surface_id in surface_ids) or surface_ids != sorted(set(surface_ids)):
            raise ComponentError(f"Lock binding surfaces must be unique and sorted: {path}")
        seen.add(path)
        normalized.append({"path": path, "sha256": digest, "surfaces": surfaces})
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        raise ComponentError("Lock bindings must be sorted by path")
    return normalized


def _lock_record(
    release: dict[str, Any],
    project: Path,
    binding_entries: list[dict[str, Any]],
    vendor_path: Path,
) -> dict[str, Any]:
    vendor_rel = vendor_path.relative_to(project).as_posix()
    install_files = [f"{vendor_rel}/{item['path']}" for item in release["files"]]
    install_files.append(f"{vendor_rel}/HASHES.json")
    return {
        "component_ref": release["component_ref"],
        "public_package_sha256": release["package_sha256"],
        "work_package_sha256": component_package_sha256(vendor_path),
        "vendor_path": vendor_rel,
        "bindings": sorted(binding_entries, key=lambda item: item["path"]),
        "install_files": sorted(install_files),
    }


@contextmanager
def package_write_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.is_file() and path.stat().st_nlink > 1:
        raise ComponentError("Asset write lock cannot be linked")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as error:
            raise ComponentError(f"Another asset writer is active: {path}") from error
        try:
            yield
        finally:
            release()


def install_component(
    release_directory: Path,
    project: Path,
    binding: dict[str, Any] | Path,
    *,
    binding_path: str | None = None,
    expected_ref: str | None = None,
    review_root: Path | None = None,
    acceptance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Vendor one validated release, bind one Scene, and update the Lock."""

    if review_root is not None:
        from work_requests import review_identity
        review_identity(review_root)
        if not Path(project).resolve().is_relative_to(Path(review_root).resolve() / "works"):
            raise ComponentError("Candidate installation requires an isolated Review project")
    allow_unapproved = review_root is not None or acceptance is not None
    release = validate_component_release(Path(release_directory), expected_ref=expected_ref, allow_unapproved=allow_unapproved)
    generic = release["metadata"].get("asset_type") in {"module", "media", "theme", "background", "motion", "character", "icon-set"}
    if generic and acceptance is None and not release.get("card_ref"):
        raise ComponentError("Asset installation requires exact asset acceptance")
    if acceptance is not None:
        validate_component_acceptance(acceptance, release)
    project = Path(project)
    if project.is_symlink() or not project.is_dir():
        raise ComponentError(f"Work project is not a regular directory: {project}")
    binding_data = _load_binding(binding)
    validate_binding(binding_data, release)
    surface_records = {} if generic else validate_surface_payloads(project, binding_data, release)
    scene = binding_data.get("scene", binding_data.get("scope", "appearance"))
    binding_rel = _safe_relative(binding_path or f"component-bindings/{scene}.{release['component_id']}.json", "binding path")
    target_binding = project / binding_rel
    package_id, version = parse_component_ref(release["component_ref"])
    vendor_path = project / _vendor_relative(package_id, version)
    lock_path = project / "COMPONENT_LOCK.json"
    from work_requests import safe
    for target in (target_binding, vendor_path, lock_path):
        safe(project, target.relative_to(project).as_posix())
        if target.is_file() and target.stat().st_nlink > 1:
            raise ComponentError(f"Installation target cannot be a hardlink: {target}")
    lock = _read_json(lock_path) if lock_path.is_file() else {"schema_version": 1, "algorithm": PACKAGE_ALGORITHM, "components": []}
    components = _lock_components(lock)
    vendor_path.parent.mkdir(parents=True, exist_ok=True)

    if vendor_path.exists():
        existing = validate_component_release(vendor_path, expected_ref=release["component_ref"], allow_unapproved=allow_unapproved)
        if existing["package_sha256"] != release["package_sha256"] or not _same_tree(Path(release_directory), vendor_path):
            raise ComponentError(f"Existing vendor copy differs: {vendor_path}")
    else:
        staging = vendor_path.parent / f".{vendor_path.name}.staging"
        if staging.exists():
            raise ComponentError(f"Refusing to reuse stale staging directory: {staging}")
        shutil.copytree(release_directory, staging)
        try:
            installed = validate_component_release(staging, expected_ref=release["component_ref"], allow_unapproved=allow_unapproved)
            if installed["package_sha256"] != release["package_sha256"] or not _same_tree(Path(release_directory), staging):
                raise ComponentError("Vendor copy changed during installation")
            os.replace(staging, vendor_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    if target_binding.exists():
        existing_binding = _read_json(target_binding)
        validate_binding(existing_binding, release)
        if existing_binding != binding_data:
            raise ComponentError(f"Existing binding differs: {target_binding}")
    else:
        _atomic_json(target_binding, binding_data)

    binding_entry = {
        "path": target_binding.relative_to(project).as_posix(),
        "sha256": file_sha256(target_binding),
        "surfaces": [surface_records[surface_id] for surface_id in sorted(surface_records)],
    }
    record = _lock_record(release, project, [binding_entry], vendor_path)
    if release.get("card_ref"):
        record["card_ref"] = release["card_ref"]
    if generic:
        record["asset_kind"] = release["metadata"]["asset_type"]
    if acceptance is not None:
        record["acceptance"] = acceptance
    if review_root is not None:
        record["review"] = review_identity(review_root)
    for index, existing in enumerate(components):
        if existing.get("component_ref") == record["component_ref"]:
            for key in ("public_package_sha256", "work_package_sha256", "vendor_path", "install_files"):
                if existing.get(key) != record[key]:
                    raise ComponentError(f"Existing lock record differs: {record['component_ref']}")
            bindings = _lock_bindings(existing)
            same_path = next((item for item in bindings if item["path"] == binding_entry["path"]), None)
            if same_path is not None and same_path != binding_entry:
                raise ComponentError(f"Existing binding hash differs: {binding_entry['path']}")
            if same_path is None:
                bindings.append(binding_entry)
            record = dict(existing)
            record["bindings"] = sorted(bindings, key=lambda item: item["path"])
            components[index] = record
            break
    else:
        components.append(record)
    components.sort(key=lambda item: str(item.get("component_ref", "")))
    lock["schema_version"] = 2 if generic or lock["schema_version"] == 2 else 1
    lock["algorithm"] = PACKAGE_ALGORITHM
    lock["components"] = components
    _atomic_json(lock_path, lock)
    return {"component": record, "lock_path": str(lock_path)}


def _binding_variable_values(binding: dict[str, Any]) -> dict[str, Any]:
    values = {name: value for name, value in binding["slots"].items() if value is not None}
    values["time_scale"] = binding["timing"]["time_scale"]
    for surface_id, surface in binding["surfaces"].items():
        values[f"{surface_id}_mode"] = surface["mode"]
        if "path" in surface:
            values[f"{surface_id}_path"] = surface["path"]
    return values


def validate_component_mounts(
    project: Path,
    release: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    index_path = Path(project) / "index.html"
    if release["metadata"].get("asset_type") in {"theme", "background", "motion", "icon-set"}:
        return {"mounts": []}
    if all(_read_json(Path(project) / item["path"]).get("scope") == "dependency"
           for item in _lock_bindings(record)):
        return {"mounts": []}
    if release["metadata"].get("asset_type") in {"module", "media", "character"}:
        from visual_plan import VisualPlanError, validate_dependencies
        entry = f"{record['vendor_path']}/{release['metadata']['entry']}"
        try:
            dependencies = validate_dependencies(Path(project))
        except VisualPlanError as error:
            raise ComponentError(str(error)) from error
        if entry not in dependencies:
            raise ComponentError(f"Asset entry is not referenced by the project: {entry}")
        return {"mounts": [{"entry": entry}]}
    if not index_path.is_file():
        return {"mounts": []}
    _, parser = _parse_html(index_path)
    mounts = [
        node["attrs"]
        for node in parser.nodes
        if node["attrs"].get("data-component-ref") == release["component_ref"]
    ]
    by_binding: dict[str, dict[str, str | None]] = {}
    for attrs in mounts:
        binding_path = attrs.get("data-component-binding")
        if not isinstance(binding_path, str) or binding_path in by_binding:
            raise ComponentError(f"Component mount has missing or duplicate binding: {binding_path}")
        by_binding[binding_path] = attrs
    expected_bindings = _lock_bindings(record)
    if set(by_binding) != {item["path"] for item in expected_bindings}:
        raise ComponentError("Component mounts do not match locked bindings")
    vendor_source = f"{record['vendor_path']}/component.html"
    for binding_record in expected_bindings:
        binding_path = binding_record["path"]
        binding = _read_json(Path(project) / binding_path)
        attrs = by_binding[binding_path]
        if attrs.get("data-composition-id") != release["component_id"]:
            raise ComponentError(f"Component mount composition id mismatch: {binding_path}")
        if attrs.get("data-composition-src") != vendor_source:
            raise ComponentError(f"Component mount source mismatch: {binding_path}")
        try:
            values = json.loads(attrs.get("data-variable-values") or "")
        except json.JSONDecodeError as exc:
            raise ComponentError(f"Component mount variables are invalid: {binding_path}") from exc
        if values != _binding_variable_values(binding):
            raise ComponentError(f"Component mount variables differ from Binding: {binding_path}")
        expected_scalars = {
            "data-start": binding["timing"]["offset"],
            "data-width": binding["placement"]["width"],
            "data-height": binding["placement"]["height"],
        }
        for attribute, expected in expected_scalars.items():
            try:
                actual = float(attrs.get(attribute) or "")
            except ValueError as exc:
                raise ComponentError(f"Component mount {attribute} is invalid: {binding_path}") from exc
            if actual != float(expected):
                raise ComponentError(f"Component mount {attribute} differs from Binding: {binding_path}")
    return {"mounts": sorted(by_binding)}


def _work_surface_record(project: Path, surface: dict[str, Any]) -> dict[str, Any]:
    surface_id = surface.get("surface_id")
    kind = surface.get("kind")
    modes = surface.get("modes")
    mode = surface.get("mode")
    fallback = surface.get("fallback")
    if not isinstance(surface_id, str) or not COMPONENT_ID_RE.fullmatch(surface_id):
        raise ComponentError("Work Surface has an invalid surface_id")
    if kind not in SURFACE_KINDS or not isinstance(modes, list) or not modes:
        raise ComponentError(f"Work Surface {surface_id} has an invalid kind/modes")
    if (
        not all(isinstance(item, str) for item in modes)
        or len(modes) != len(set(modes))
        or not set(modes) <= SURFACE_KINDS[kind]
        or mode not in modes
    ):
        raise ComponentError(f"Work Surface {surface_id} mode is outside its allowed modes")
    if not isinstance(fallback, str) or not fallback or not isinstance(surface.get("selector"), str):
        raise ComponentError(f"Work Surface {surface_id} requires selector and fallback")
    record: dict[str, Any] = {
        "surface_id": surface_id,
        "kind": kind,
        "modes": modes,
        "mode": mode,
        "fallback": fallback,
    }
    if mode == "none":
        if "path" in surface:
            raise ComponentError(f"Work Surface {surface_id} none mode cannot have a path")
    else:
        path = surface.get("path")
        if not isinstance(path, str):
            raise ComponentError(f"Work Surface {surface_id} requires a path")
        asset = _resolve_work_asset(project, path)
        probe = _asset_probe(asset, mode)
        record.update(
            {
                "path": path,
                "sha256": file_sha256(asset),
                "probe": probe,
                "probe_sha256": hashlib.sha256(
                    json.dumps(probe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            }
        )
    return record


def validate_work_surface_inventory(project: Path) -> dict[str, Any]:
    """Validate Work-local Surface inventory against each prototype host and local payload."""

    project = Path(project)
    inventory_path = project / "scene-slots.json"
    if not inventory_path.is_file():
        return {"surfaces": []}
    inventory = _read_json(inventory_path)
    scenes = inventory.get("scenes")
    if not isinstance(scenes, dict):
        raise ComponentError("scene-slots.json scenes must be an object")
    _, index_parser = _parse_html(project / "index.html")
    hosts = {node["attrs"].get("id"): node["attrs"] for node in index_parser.nodes if node["attrs"].get("id")}
    records: dict[str, dict[str, Any]] = {}
    for scene_id, scene in scenes.items():
        if not isinstance(scene, dict):
            raise ComponentError(f"scene-slots.json {scene_id} must be an object")
        surfaces = scene.get("surfaces", [])
        if not isinstance(surfaces, list) or not all(isinstance(item, dict) for item in surfaces):
            raise ComponentError(f"scene-slots.json {scene_id} surfaces must be an array")
        if not surfaces:
            continue
        prototype = scene.get("prototype")
        host_id = f"{str(scene_id).lower()}-{str(prototype).lower()}"
        host = hosts.get(host_id)
        if not host or not isinstance(host.get("data-composition-src"), str):
            raise ComponentError(f"Cannot resolve Surface host for {scene_id}/{prototype}")
        source_rel = _safe_relative(host["data-composition-src"], "composition source")
        source_path = _resolve_work_asset(project, source_rel)
        _, parser = _parse_html(source_path)
        anchors: dict[str, list[dict[str, str | None]]] = {}
        templates: dict[str, dict[str, str | None]] = {}
        for node in parser.nodes:
            attrs = node["attrs"]
            if attrs.get("data-visual-surface"):
                anchors.setdefault(str(attrs["data-visual-surface"]), []).append(attrs)
            if attrs.get("data-visual-surface-template"):
                templates[str(attrs["data-visual-surface-template"])] = attrs
        for surface in surfaces:
            record = _work_surface_record(project, surface)
            surface_id = record["surface_id"]
            if surface_id in records:
                raise ComponentError(f"Duplicate Work Surface id: {surface_id}")
            attrs_list = anchors.get(surface_id, [])
            if len(attrs_list) == 1:
                attrs = attrs_list[0]
            else:
                prefix = surface_id.rsplit(".", 1)[0]
                attrs = templates.get(prefix)
                sibling_count = sum(1 for item in surfaces if str(item.get("surface_id", "")).startswith(f"{prefix}."))
                if attrs is None or attrs.get("data-surface-count") != str(sibling_count):
                    raise ComponentError(f"Work Surface DOM anchor mismatch: {surface_id}")
            if (
                attrs.get("data-surface-kind") != record["kind"]
                or attrs.get("data-surface-modes") != ",".join(record["modes"])
                or attrs.get("data-surface-fallback") != record["fallback"]
            ):
                raise ComponentError(f"Work Surface DOM contract mismatch: {surface_id}")
            records[surface_id] = record
    return {"surfaces": [records[surface_id] for surface_id in sorted(records)]}


def validate_snapshot_closure(source: Path, snapshot: Path) -> dict[str, Any]:
    from storage import snapshot_files
    closure = snapshot_files(Path(source))
    if closure is not None:
        if closure != snapshot_files(Path(snapshot)):
            raise ComponentError("Snapshot dependency closure changed")
        for name in closure:
            original, frozen = Path(source) / name, Path(snapshot) / name
            if not frozen.is_file() or original.read_bytes() != frozen.read_bytes():
                raise ComponentError(f"Snapshot closure differs: {name}")
        if set(closure) != {path.relative_to(snapshot).as_posix() for path in Path(snapshot).rglob("*") if path.is_file()}:
            raise ComponentError("Snapshot contains files outside its declared closure")
        return {"closed": True, "items": list(closure)}
    names = ("index.html", "compositions", "DESIGN.md", "project-config.json") + OPTIONAL_SNAPSHOT_ITEMS
    checked: list[str] = []
    for name in names:
        original = Path(source) / name
        frozen = Path(snapshot) / name
        if not original.exists() and not original.is_symlink():
            continue
        if original.is_symlink() or frozen.is_symlink() or not frozen.exists():
            raise ComponentError(f"Snapshot closure is missing or linked: {name}")
        if original.is_dir():
            _ensure_regular_tree(original)
            _ensure_regular_tree(frozen)
            if not frozen.is_dir() or not _same_tree(original, frozen):
                raise ComponentError(f"Snapshot closure differs: {name}")
        elif not frozen.is_file() or original.read_bytes() != frozen.read_bytes():
            raise ComponentError(f"Snapshot closure differs: {name}")
        checked.append(name)
    return {"closed": True, "items": checked}


def verify_installation(project: Path, *, public_root: Path | None = None, component_ref: str | None = None,
                        check_mounts: bool = True) -> dict[str, Any]:
    """Verify Work vendor, bindings, and lock records without repairing them."""

    project = Path(project)
    from work_requests import project_review_root
    review_root = project_review_root(project)
    lock_path = project / "COMPONENT_LOCK.json"
    if not lock_path.is_file():
        raise ComponentError(f"Missing Component lock: {lock_path}")
    lock = _read_json(lock_path)
    components = _lock_components(lock)
    if not components:
        raise ComponentError("COMPONENT_LOCK.json contains no components")
    # Validate the entire dependency graph, including when checking just one ref.
    releases = {}
    roots = set()
    for record in components:
        ref = record.get("component_ref")
        vendor_path = project / _safe_relative(str(record.get("vendor_path", "")), "vendor path")
        if record.get("review") and review_root is None:
            raise ComponentError("Review candidate cannot be used in production")
        release = validate_component_release(vendor_path, expected_ref=ref,
                                             allow_unapproved=review_root is not None or record.get("acceptance") is not None)
        kind = release["metadata"].get("asset_type")
        acceptance = record.get("acceptance")
        if kind in {"module", "media", "theme", "background", "motion", "character", "icon-set"}:
            if record.get("asset_kind") != kind or (acceptance is None and not release.get("card_ref")):
                raise ComponentError("Asset lock requires matching kind and exact acceptance")
        if record.get("card_ref") != release.get("card_ref"):
            raise ComponentError("Card asset lock identity mismatch")
        if acceptance is not None:
            validate_component_acceptance(acceptance, release)
        if (release["package_sha256"] != record.get("work_package_sha256")
                or release["package_sha256"] != record.get("public_package_sha256")):
            raise ComponentError(f"Installed package hash mismatch: {ref}")
        releases[ref] = release
        for item in _lock_bindings(record):
            binding = _read_json(project / item["path"])
            validate_binding(binding, release)
            if file_sha256(project / item["path"]) != item["sha256"]:
                raise ComponentError(f"Binding hash mismatch: {ref} {item['path']}")
            if binding.get("scope") != "dependency":
                roots.add(ref)
    visited = set()
    active = set()

    def visit(ref):
        if ref in active:
            raise ComponentError("Installed asset dependency cycle")
        if ref in visited:
            return
        active.add(ref)
        for dependency in releases[ref]["metadata"].get("asset_dependencies", []):
            target = releases.get(dependency["ref"])
            if (target is None or target["metadata"].get("asset_type") != dependency["kind"]
                    or target["package_sha256"] != dependency["package_sha256"]):
                raise ComponentError(f"Installed asset dependency does not match exact package: {dependency['ref']}")
            visit(dependency["ref"])
        active.remove(ref)
        visited.add(ref)

    for ref in roots:
        visit(ref)
    if visited != set(releases):
        raise ComponentError("Dependency Binding is not reachable from a bound asset")
    checked = []
    for record in components:
        ref = record.get("component_ref")
        if not isinstance(ref, str):
            raise ComponentError("Lock record is missing component_ref")
        if component_ref is not None and ref != component_ref:
            continue
        vendor_rel = _safe_relative(str(record.get("vendor_path", "")), "vendor path")
        vendor_path = project / vendor_rel
        acceptance = record.get("acceptance")
        vendor = releases[ref]
        generic = vendor["metadata"].get("asset_type") in {"module", "media", "theme", "background", "motion", "character", "icon-set"}
        # v4.2: Work vendor copies validate on their own; never fall back to the
        # removed repository component library. ``public_root`` stays accepted
        # for callers that pin an explicit public tree but is no longer read here.
        checked_bindings = []
        for binding_record in _lock_bindings(record):
            binding_rel = binding_record["path"]
            binding_path = project / binding_rel
            binding = _read_json(binding_path)
            validate_binding(binding, vendor)
            binding_sha = file_sha256(binding_path)
            if binding_sha != binding_record["sha256"]:
                raise ComponentError(f"Binding hash mismatch: {ref} {binding_rel}")
            surface_records = {} if generic else validate_surface_payloads(project, binding, vendor)
            expected_surfaces = [surface_records[surface_id] for surface_id in sorted(surface_records)]
            if binding_record["surfaces"] != expected_surfaces:
                raise ComponentError(f"Surface payload record mismatch: {ref} {binding_rel}")
            checked_bindings.append(
                {"path": binding_rel, "sha256": binding_sha, "surfaces": expected_surfaces}
            )
        expected_files = set(record.get("install_files", []))
        actual_files = {
            path.relative_to(project).as_posix()
            for path in vendor_path.rglob("*")
            if path.is_file()
        }
        if actual_files != expected_files:
            raise ComponentError(f"Installed file list mismatch: {ref}")
        mounts = validate_component_mounts(project, vendor, record) if check_mounts else {"mounts": []}
        checked.append(
            {
                "component_ref": ref,
                "package_sha256": vendor["package_sha256"],
                "bindings": checked_bindings,
                "mounts": mounts["mounts"],
            }
        )
    if component_ref is not None and not checked:
        raise ComponentError(f"Component is not installed: {component_ref}")
    surfaces = validate_work_surface_inventory(project) if (project / "scene-slots.json").is_file() else {"surfaces": []}
    return {"algorithm": PACKAGE_ALGORITHM, "components": checked, "work_surfaces": surfaces["surfaces"]}


__all__ = [
    "PACKAGE_ALGORITHM",
    "OPTIONAL_SNAPSHOT_ITEMS",
    "ComponentError",
    "component_package_sha256",
    "file_sha256",
    "hash_package",
    "install_component",
    "package_entries",
    "package_hash",
    "package_manifest_lines",
    "parse_component_ref",
    "validate_binding",
    "validate_component_mounts",
    "validate_component_transport",
    "validate_component_release",
    "validate_component_acceptance",
    "validate_snapshot_closure",
    "validate_surface_dom",
    "validate_surface_payloads",
    "validate_work_surface_inventory",
    "verify_installation",
    "write_hashes",
]
