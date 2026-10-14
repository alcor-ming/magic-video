"""Design cards (built-in and user roots): identity, defaults and the five-layer chain.

A card owns its identity (id/version/compatibility), a ``type`` (``design`` or
``material``) and an in-card asset library at ``assets/``.  Built-in cards live
next to this module; user cards live under the configured ``design_root`` (or
``<work_root>/asset-library/designs``).  Both roots are discovered with one
validator and an id conflict is refused rather than shadowed.  Material cards
never appear in design selection lists.  Appearance is resolved separately
through the chain design -> series -> Work -> account -> Variant.  BGM is
intentionally not a supported field this pass, so writing it is reported as an
unknown field.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import windows_runtime

REPO = Path(__file__).resolve().parents[1]
CARD_DIR = Path(__file__).with_name("designs")
ASSET_DIRECTORY = "assets"
DESIGN = "design"
MATERIAL = "material"
TYPES = (DESIGN, MATERIAL)
MODES = ("explainer", "showcase", "math", "english")

CONFIG_ENV = "HYPERFRAMES_AI_CONFIG"
ASSET_CONFIG_ENV = "HYPERFRAMES_AI_ASSET_CONFIG"
RESOLVED_CONFIG_ENV = "HYPERFRAMES_AI_RESOLVED_CONFIG"
LOCK_NAME = "windows-npm.lock.json"

IDENTITY = re.compile(r"[a-z][a-z0-9-]*")
ASSET_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REFERENCE = re.compile(r"(?P<card>[a-z][a-z0-9-]*)/(?P<asset>[a-z0-9]+(?:-[a-z0-9]+)*)")

# Explicit retired identities -> unique reselect target (None means "any design").
RETIRED = {
    "explainer": "stage-full",
    "explainer/math-rap": "math",
    "showcase": "pdoom",
    "showcase/pdoom": "pdoom",
    "showcase/science": "collage",
    "science": "collage",
    "card": None,
    "text-led": None,
    "animation-led": None,
}
# Backwards compatible generic hint; use reselect_hint() for the live list.
RESELECT = "reselect a design"

_REQUIRED = {"id", "version", "compatibility", "plan_template", "brief",
             "stages", "thresholds", "critic_checks", "defaults", "fields", "assets", "exemptions"}
_NEW_REQUIRED = _REQUIRED | {"type", "runtime"}
_MATERIAL_REQUIRED = {"id", "version", "type", "assets", "runtime"}
_RUNTIME_KEYS = {"gsap", "plugins"}
LAYERS = ("background", "stage", "overlay", "text")
CHECKS = {"math": "math_chain.py", "math-complete": "visual_plan.py",
          "english": "english_plan.py", "director": "director_plan.py",
          "reference-count": "director_plan.py",
          "css-contract": "css_contract.py", "frame-blank": "stage_checks.py"}


def legacy_capabilities(mode: str) -> dict:
    """Read old cards/Locks without changing their serialized bytes or digest."""
    if mode not in MODES:
        raise DesignError(f"Unsupported legacy mode: {mode}")
    required = [] if mode == "showcase" else list(LAYERS)
    return {"layers": {"required": required, "optional": []}, "rolls": True,
            "bindings": {"theme": "none" if mode == "showcase" else "required",
                         "background": "none" if mode == "showcase" else "required",
                         "motion": "none" if mode == "showcase" else "optional"},
            "checks": {"math": ["math", "math-complete"], "english": ["english"],
                       "explainer": ["director", "reference-count"],
                       "showcase": ["director"]}[mode],
            "research_template": "MATH_RESEARCH.template.md" if mode == "math" else "RESEARCH.template.md"}


def capabilities(value: dict) -> dict:
    declaration = value.get("capabilities")
    if declaration is None:
        return legacy_capabilities(value.get("mode"))
    validate_capabilities(declaration)
    return deepcopy(declaration)


def validate_capabilities(value: object) -> None:
    required = {"layers", "rolls", "bindings", "checks", "research_template"}
    if not isinstance(value, dict) or set(value) != required:
        raise DesignError("capabilities requires layers, rolls, bindings, checks and research_template")
    layers = value["layers"]
    if not isinstance(layers, dict) or set(layers) != {"required", "optional"}:
        raise DesignError("Invalid capabilities.layers")
    for group in layers.values():
        if (not isinstance(group, list) or any(item not in LAYERS for item in group)
                or len(group) != len(set(group))):
            raise DesignError("Invalid capabilities.layers entries")
    if set(layers["required"]) & set(layers["optional"]):
        raise DesignError("Required and optional layers overlap")
    if type(value["rolls"]) is not bool:
        raise DesignError("capabilities.rolls must be boolean")
    bindings = value["bindings"]
    if (not isinstance(bindings, dict) or set(bindings) != {"theme", "background", "motion"}
            or any(item not in ("required", "optional", "none") for item in bindings.values())):
        raise DesignError("Invalid capabilities.bindings")
    checks = value["checks"]
    if (not isinstance(checks, list) or any(not isinstance(item, str) or item not in CHECKS for item in checks)
            or len(checks) != len(set(checks))):
        raise DesignError("Unknown capabilities check")
    template = value["research_template"]
    if (not isinstance(template, str) or not template or Path(template).name != template
            or template in (".", "..")):
        raise DesignError("Invalid research_template reference")

# Leaf schema shared by the card `defaults` and every layer `overrides`.
SCHEMA = {
    "captions": {"enabled": {"type": "boolean"}},
    "sfx": {"enabled": {"type": "boolean"}, "policy": {"type": "string"}},
    "cover": {"enabled": {"type": "boolean"}, "template": {"type": "resource"},
              "theme": {"type": "resource"}, "background": {"type": "resource"},
              "width": {"type": "integer", "minimum": 64}, "height": {"type": "integer", "minimum": 64},
              "font": {"type": "file"}, "logo": {"type": "file"}, "background_image": {"type": "file"},
              "font_size": {"type": "number", "positive": True},
              "color": {"type": "string"}, "background_color": {"type": "string"}},
    "voice": {"ref": {"type": "string", "nullable": True},
              "duration_factor": {"type": "number", "positive": True}},
    "ratio": {"type": "string"},
    "width": {"type": "integer"},
    "height": {"type": "integer"},
    "fps": {"type": "integer", "minimum": 1},
    "seed": {"type": "integer"},
}


def _is_group(spec: dict) -> bool:
    return bool(spec) and all(isinstance(item, dict) and "type" in item for item in spec.values())


FIELDS = tuple(f"{group}.{leaf}" if _is_group(spec) else group
               for group, spec in SCHEMA.items()
               for leaf in (spec if _is_group(spec) else ("",)))


class DesignError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Root and configuration resolution
# --------------------------------------------------------------------------- #

def repository(root=None) -> Path:
    """The repository/production root a call is anchored on; defaults to this checkout."""
    return Path(root) if root is not None else REPO


def load_config(root=None, config=None) -> dict:
    """Resolve configuration: explicit mapping, resolved snapshot, then assets.json."""
    if config is not None:
        if not isinstance(config, dict):
            raise DesignError("Configuration must be an object")
        return config
    snapshot = os.environ.get(RESOLVED_CONFIG_ENV)
    if snapshot:
        try:
            data = json.loads(snapshot)
        except ValueError as exc:
            raise DesignError(f"Invalid resolved configuration: {exc}") from exc
        if not isinstance(data, dict):
            raise DesignError("Resolved configuration must be an object")
        return data
    base = repository(root)
    value = os.environ.get(ASSET_CONFIG_ENV) or os.environ.get(CONFIG_ENV)
    path = Path(value) if value else base / ".studio/.runtime/assets.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DesignError(f"Invalid configuration {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DesignError(f"Invalid configuration {path}: object required")
    return data


def builtin_root(root=None) -> Path:
    """The read-only card root shipped with the tools."""
    return CARD_DIR if root is None else repository(root) / ".studio" / "designs"


def _tool_paths(root: Path) -> list[Path]:
    if os.environ.get(RESOLVED_CONFIG_ENV):
        return [root / name for name in (".studio", "runtime", ".agents")]
    return [root]


def _guard_user_root(root: Path, directory: Path, config: dict) -> None:
    protected = _tool_paths(root)
    home = os.environ.get("HYPERFRAMES_AI_HOME")
    if home:
        protected.append(Path(home))
    if any(windows_runtime.paths_overlap(directory, path) for path in protected):
        raise DesignError("design_root must be outside the harness, runtime and tool directories")
    work_root = os.environ.get("HYPERFRAMES_AI_WORK_ROOT") or config.get("work_root")
    if isinstance(work_root, str) and work_root:
        work = Path(work_root)
        if (windows_runtime.paths_overlap(directory, work)
                and not directory.resolve().is_relative_to((work / "asset-library").resolve())):
            raise DesignError("design_root must sit under the WorkStore asset-library")
    try:
        windows_runtime.validate_review_path(directory)
    except ValueError as error:
        raise DesignError(str(error)) from error
    for protected_root in config.get('review_protected_roots', []) + config.get('acceptance_protected_roots', []):
        if windows_runtime.paths_overlap(directory, Path(protected_root)):
            raise DesignError('design_root overlaps a protected root')
    if config.get('review') and not directory.resolve().is_relative_to(root.resolve()):
        raise DesignError('Review design_root escapes isolated root')


def user_root(root=None, config=None, *, create=False):
    """The writable user card root, or None when it is unconfigured/missing."""
    base = repository(root)
    data = load_config(base, config)
    value = data.get("design_root")
    if value is None:
        work_root = os.environ.get("HYPERFRAMES_AI_WORK_ROOT") or data.get("work_root")
        if work_root is None:
            return None
        if not isinstance(work_root, str) or not Path(work_root).is_absolute():
            raise DesignError("work_root requires an absolute path")
        directory = Path(work_root) / "asset-library" / "designs"
    else:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise DesignError("design_root requires an absolute path")
        directory = Path(value)
    _guard_user_root(base, directory, data)
    if create and not directory.is_dir():
        directory.mkdir(parents=True)
    return directory if directory.is_dir() else None


def card_roots(root=None, config=None) -> tuple:
    """Existing built-in and user card roots, built-in first."""
    roots: list[Path] = []
    builtin = builtin_root(root)
    if builtin.is_dir():
        roots.append(builtin)
    user = user_root(root, config)
    if user is not None and user not in roots:
        roots.append(user)
    return tuple(roots)


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #

def _check_identity(value) -> str:
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise DesignError(f"Invalid design identity: {value!r}")
    return value


def _check_asset_id(value) -> str:
    if not isinstance(value, str) or not ASSET_ID.fullmatch(value):
        raise DesignError(f"Invalid asset identity: {value!r}")
    return value


def _parse_reference(value) -> tuple:
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise DesignError(f"Invalid reference target: {value!r}; expected <card>/<asset>")
    return match.group("card"), match.group("asset")


def _scan(root, problems=None) -> dict:
    """Card directories by identity; with ``problems`` each bad entry is reported, not raised."""
    found: dict[str, Path] = {}
    if root is None or not root.is_dir():
        return found
    if root.is_symlink():
        raise DesignError(f"Linked design root: {root}")
    for path in sorted(root.glob("*/design.json")):
        try:
            identity = _check_identity(path.parent.name)
            if path.is_symlink() or path.parent.is_symlink():
                raise DesignError(f"Linked design card: {identity}")
        except DesignError as error:
            if problems is None:
                raise
            problems.append({"card": path.parent.name, "path": str(path.parent), "error": str(error)})
            continue
        found[identity] = path
    return found


def _locate(root=None, config=None) -> tuple:
    """Located cards plus per-identity problems; a conflict only disables its own identity."""
    located: dict[str, tuple] = {}
    problems: list[dict] = []
    for source, directory in (("builtin", builtin_root(root)), ("user", user_root(root, config))):
        for identity, path in _scan(directory, problems).items():
            if identity in located:
                problems.append({"card": identity, "path": str(path.parent),
                                 "paths": [str(located[identity][0]), str(path.parent)],
                                 "error": f"Duplicate design id {identity!r}: {located[identity][0]} and {path.parent}"})
                continue
            located[identity] = (path.parent, source)
    for problem in problems:
        located.pop(problem["card"], None)
    return located, problems


def _located(root=None, config=None) -> dict:
    located, problems = _locate(root, config)
    if problems:
        raise DesignError(problems[0]["error"])
    return located


def reselect_hint(root=None, config=None, target=None) -> str:
    try:
        ids = design_ids(root, config)
    except DesignError:
        ids = ()
    if target and target in ids:
        return f"reselect {target}"
    if ids:
        return "reselect a design: " + ", ".join(ids)
    return RESELECT


def card_path(identity, root=None, config=None) -> Path:
    """Absolute directory of one card; refuses unknown ids and root conflicts."""
    identity = _check_identity(identity)
    located, problems = _locate(root, config)
    for problem in problems:
        if problem["card"] == identity:
            raise DesignError(problem["error"])
    if identity not in located:
        raise DesignError(f"Unknown design {identity!r}; {reselect_hint(root, config)}")
    return located[identity][0]


def _read_card(card_dir: Path, identity: str) -> dict:
    path = card_dir / "design.json"
    if card_dir.is_symlink() or path.is_symlink():
        raise DesignError(f"Linked design card: {identity}")
    try:
        if path.stat().st_nlink > 1:
            raise DesignError(f"Linked design card: {identity}")
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DesignError(f"Unknown design {identity!r}") from exc
    except OSError as exc:
        raise DesignError(f"Invalid design card {identity!r}: {exc}") from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DesignError(f"Invalid design card {identity!r}: {exc}") from exc


def _read(identity: str) -> dict:
    """Read one card from the default roots (patchable seam for callers)."""
    return _read_card(card_path(identity), identity)


def assets_dir(identity, root=None, config=None) -> Path:
    """Absolute in-card asset library directory for one card."""
    card = get(identity, root, config)
    directory = (card.get("assets") or {}).get("directory", ASSET_DIRECTORY)
    return card_path(identity, root, config) / directory


def card_asset_path(card, asset, root=None, config=None) -> Path:
    """Absolute directory of one in-card asset, refusing traversal and links."""
    base = assets_dir(card, root, config)
    return _safe_child(base, _check_asset_id(asset))


def _safe_child(base: Path, name: str) -> Path:
    import work_requests
    try:
        return work_requests.safe(base, name)
    except work_requests.RequestError as exc:
        raise DesignError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _leaf(value: object, spec: dict, path: str) -> object:
    kind = spec["type"]
    if kind == "boolean":
        if type(value) is not bool:
            raise DesignError(f"{path} must be a boolean")
    elif kind == "string":
        if not isinstance(value, str):
            raise DesignError(f"{path} must be a string")
    elif kind == "integer":
        if type(value) is not int or isinstance(value, bool):
            raise DesignError(f"{path} must be an integer")
        if "minimum" in spec and value < spec["minimum"]:
            raise DesignError(f"{path} must be at least {spec['minimum']}")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DesignError(f"{path} must be a finite number")
        if spec.get("positive") and value <= 0:
            raise DesignError(f"{path} must be a positive finite number")
    elif kind == "file":
        if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
                or not isinstance(value['path'], str) or not value['path']
                or not isinstance(value['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['sha256'])):
            raise DesignError(f'{path} requires an exact path/sha256 file reference')
    elif kind == "resource":
        if value is None:
            return None
        if (not isinstance(value, dict) or set(value) != {"ref", "kind", "package_sha256"}
                or not isinstance(value.get("ref"), str) or not isinstance(value.get("kind"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("package_sha256")))):
            raise DesignError(f"{path} requires an exact ref/kind/package_sha256 reference")
    else:  # pragma: no cover - schema guard
        raise DesignError(f"Unknown field type for {path}")
    return deepcopy(value)


def layer_values(layer: object, source: str) -> dict:
    """Validate one overrides layer and flatten it to dotted leaves."""
    if layer is None:
        return {}
    if not isinstance(layer, dict):
        raise DesignError(f"{source} overrides must be an object")
    values: dict[str, object] = {}
    for group, value in layer.items():
        spec = SCHEMA.get(group)
        if spec is None:
            raise DesignError(f"Unknown override field: {group}")
        if _is_group(spec):
            if not isinstance(value, dict):
                raise DesignError(f"{group} overrides must be an object")
            for leaf, leaf_value in value.items():
                leaf_spec = spec.get(leaf)
                if leaf_spec is None:
                    raise DesignError(f"Unknown override field: {group}.{leaf}")
                values[f"{group}.{leaf}"] = _leaf(leaf_value, leaf_spec, f"{group}.{leaf}")
        else:  # pragma: no cover - every schema group is nested
            values[group] = _leaf(value, spec, group)
    return values


def _validate_assets(identity: str, value) -> None:
    if not isinstance(value, dict):
        raise DesignError(f"Invalid asset declaration: {identity}")
    directory = value.get("directory", ASSET_DIRECTORY)
    if directory != ASSET_DIRECTORY:
        raise DesignError(f"Invalid asset directory declaration: {identity}")


def _validate_references(identity: str, value) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise DesignError(f"Invalid references declaration: {identity}")
    for target in value:
        _parse_reference(target)


def _validate_runtime(identity: str, value) -> None:
    if not isinstance(value, dict):
        raise DesignError(f"Invalid runtime declaration: {identity}")
    gsap = value.get("gsap")
    if gsap is not None and (not isinstance(gsap, str) or not gsap.strip()):
        raise DesignError(f"Invalid gsap runtime version: {identity}")
    plugins = value.get("plugins", [])
    if not isinstance(plugins, list) or any(not isinstance(item, str) or not item.strip() for item in plugins):
        raise DesignError(f"Invalid runtime plugins: {identity}")


def _validate_design_body(identity: str, card: dict) -> None:
    caps = capabilities(card)
    if caps["rolls"] and not isinstance(card.get("subjects"), dict):
        raise DesignError(f"rolls requires subjects: {identity}")
    fields = card.get("fields")
    if not isinstance(fields, list) or any(field not in FIELDS for field in fields):
        raise DesignError(f"Invalid design field declaration: {identity}")
    layer_values(card.get("defaults"), "Design")
    if not isinstance(card.get("compatibility"), dict):
        raise DesignError(f"Invalid compatibility declaration: {identity}")


def _validate_card(identity: str, card: object, *, strict: bool = False) -> dict:
    if (not isinstance(card, dict) or card.get("id") != identity
            or type(card.get("version")) is not int or card["version"] < 1):
        raise DesignError(f"Invalid design card: {identity}")
    if card.get("author_model"):
        raise DesignError(f"Design cards declare no author model: {identity}")
    kind = card.get("type")
    if kind is None:
        # Legacy cards and already-adopted frozen snapshots keep the old contract.
        if strict:
            raise DesignError(f"Design card requires a type: {identity}")
        if _REQUIRED - set(card) or card.get("mode") not in MODES:
            raise DesignError(f"Invalid design card fields: {identity}")
        _validate_design_body(identity, card)
        return card
    if kind not in TYPES:
        raise DesignError(f"Invalid design card type: {identity}")
    required = _MATERIAL_REQUIRED if kind == MATERIAL else _NEW_REQUIRED
    if required - set(card):
        raise DesignError(f"Invalid {kind} card fields: {identity}")
    _validate_assets(identity, card.get("assets"))
    _validate_references(identity, card.get("references"))
    _validate_runtime(identity, card.get("runtime"))
    if kind == MATERIAL:
        return card
    _validate_design_body(identity, card)
    return card


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

def catalog(root=None, config=None) -> dict:
    """All cards (design + material) discovered across both roots."""
    located = _located(root, config)
    found = {}
    for identity in sorted(located):
        card_dir, _source = located[identity]
        found[identity] = _validate_card(identity, _read_card(card_dir, identity), strict=True)
    return found


def catalog_report(root=None, config=None) -> tuple:
    """Valid cards plus per-card problems, so one bad or conflicting card hides only itself."""
    located, problems = _locate(root, config)
    found = {}
    for identity in sorted(located):
        card_dir, _source = located[identity]
        try:
            found[identity] = _validate_card(identity, _read_card(card_dir, identity), strict=True)
        except DesignError as error:
            problems.append({"card": identity, "path": str(card_dir), "error": str(error)})
    return found, problems


def design_catalog(root=None, config=None) -> dict:
    """Selectable design cards; material cards are excluded."""
    return {key: value for key, value in catalog(root, config).items()
            if value.get("type") == DESIGN}


def design_ids(root=None, config=None) -> tuple:
    """Dynamic design ids derived from the catalog; never a hardcoded tuple."""
    return tuple(sorted(design_catalog(root, config)))


class _DynamicIds:
    """Tuple-like view over the live design catalog (no hardcoded card names)."""

    def _values(self) -> tuple:
        try:
            return design_ids()
        except DesignError:
            return ()

    def __iter__(self):
        return iter(self._values())

    def __contains__(self, value) -> bool:
        return value in self._values()

    def __len__(self) -> int:
        return len(self._values())

    def __getitem__(self, index):
        return self._values()[index]

    def __eq__(self, other) -> bool:
        try:
            return self._values() == tuple(other)
        except TypeError:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self._values())

    def __repr__(self) -> str:
        return repr(self._values())


DESIGN_IDS = _DynamicIds()


def get(identity, root=None, config=None) -> dict:
    if isinstance(identity, str) and identity in RETIRED:
        return require(identity, root, config)
    if root is None and config is None:
        card = _read(identity)
    else:
        card = _read_card(card_path(identity, root, config), identity)
    return deepcopy(_validate_card(identity, card, strict=True))


def require(identity, root=None, config=None) -> dict:
    if isinstance(identity, str) and identity in RETIRED:
        target = RETIRED[identity]
        raise DesignError(f"Product line {identity!r} is retired; {reselect_hint(root, config, target)}")
    card = get(identity, root, config)
    if card.get("type") == MATERIAL:
        raise DesignError(f"{identity!r} is a material card; {reselect_hint(root, config)}")
    return card


def identify(state: object) -> str | None:
    """The selected design id, or None. No implicit explainer default."""
    if not isinstance(state, dict):
        return None
    if isinstance(state.get("design"), str):
        return state["design"]
    line = state.get("line")
    if isinstance(line, dict) and isinstance(line.get("id"), str):
        return line["id"]
    if isinstance(state.get("mode"), str):
        return state["mode"]
    return None


def require_choice(state: object, root=None, config=None) -> dict:
    identity = identify(state)
    if identity is None:
        raise DesignError("No design selected; " + reselect_hint(root, config))
    return require(identity, root, config)


def defaults(identity: str, root=None, config=None) -> dict:
    return layer_values(require(identity, root, config)["defaults"], "Design")


def resolve(identity: str, *, series=None, work=None, account=None, variant=None, card=None,
            root=None, config=None) -> dict:
    """Merge the five layers with per-field source tracking."""
    card = require(identity, root, config) if card is None else _validate_card(identity, deepcopy(card))
    allowed = set(card["fields"])
    values = layer_values(card["defaults"], "Design")
    sources = {path: "design" for path in values}
    for name, layer in (("series", series), ("work", work), ("account", account), ("variant", variant)):
        for path, value in layer_values(layer, name).items():
            if path not in allowed:
                raise DesignError(f"{card['id']} does not declare override field: {path}")
            values[path], sources[path] = value, name
    return {"design": card["id"], "version": card["version"], "values": values, "sources": sources}


# --------------------------------------------------------------------------- #
# Host runtime
# --------------------------------------------------------------------------- #

def _version_tuple(value):
    if not isinstance(value, str):
        return None
    parts = value.strip().lstrip("v").split(".")
    if not 1 <= len(parts) <= 3 or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _pad_version(value):
    return value + (0,) * (3 - len(value))


def version_satisfies(version, spec) -> bool:
    """Minimal semver range check (exact, ^, ~, >=, >) without new dependencies."""
    parsed = _version_tuple(version)
    if parsed is None or not isinstance(spec, str):
        return False
    current = _pad_version(parsed)
    spec = spec.strip()
    for operator in (">=", ">", "<=", "<"):
        if spec.startswith(operator):
            boundary = _version_tuple(spec[len(operator):])
            if boundary is None:
                return False
            boundary = _pad_version(boundary)
            return {"<=": current <= boundary, "<": current < boundary,
                    ">=": current >= boundary, ">": current > boundary}[operator]
    if spec.startswith("^") or spec.startswith("~"):
        raw = _version_tuple(spec[1:])
        if raw is None:
            return False
        base = _pad_version(raw)
        if spec[0] == "~":
            upper = (base[0], base[1] + 1, 0)
        elif base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return base <= current < upper
    exact = _version_tuple(spec)
    if exact is None:
        return False
    if len(exact) == 3:
        return current == exact
    base = _pad_version(exact)
    upper = (base[0] + 1, 0, 0) if len(exact) == 1 else (base[0], base[1] + 1, 0)
    return base <= current < upper


def host_gsap(root=None):
    """The GSAP version pinned by the host lock file, or None."""
    path = repository(root) / LOCK_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    packages = data.get("packages") if isinstance(data, dict) else None
    entry = packages.get("node_modules/gsap") if isinstance(packages, dict) else None
    version = entry.get("version") if isinstance(entry, dict) else None
    return version if _version_tuple(version) else None


def host_plugin_files(runtime_root=None):
    """Names of host-provided GSAP runtime files, or None when the host is absent."""
    dist = windows_runtime.runtime_paths(repository(runtime_root))["GSAP_FILE"].parent
    if not dist.is_dir():
        return None
    return {item.name for item in dist.glob("*.js")}


def _plugin_names(plugin: str) -> tuple:
    return (f"{plugin}.min.js", f"{plugin}Plugin.min.js", f"{plugin}.js", f"{plugin}Plugin.js")


def _host_plugin_available(available, plugin: str) -> bool:
    return any(name in available for name in _plugin_names(plugin))


# --------------------------------------------------------------------------- #
# Authoring helpers (used by the design CLI; no CLI wiring lives here)
# --------------------------------------------------------------------------- #

_NONDETERMINISM = (
    (re.compile(r"repeat\s*:\s*-\s*1"), "repeat: -1"),
    (re.compile(r"\bdelayedCall\b"), "delayedCall"),
    (re.compile(r"\bgsap\s*\.\s*ticker\b"), "gsap.ticker"),
    (re.compile(r"\bMath\s*\.\s*random\b"), "Math.random"),
    (re.compile(r"\bDate\s*\.\s*now\b"), "Date.now"),
    (re.compile(r"\brequestAnimationFrame\b"), "requestAnimationFrame"),
)
_SCAN_SUFFIXES = {".js", ".mjs", ".cjs", ".html", ".htm"}


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _is_gsap_file(name: str) -> bool:
    lowered = name.casefold()
    return lowered.endswith(".js") and (
        lowered.startswith("gsap") or lowered.endswith("plugin.min.js") or lowered.startswith("customease"))


def _tree_files(directory: Path) -> dict:
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise DesignError(f"Linked asset file: {relative}")
        if path.is_file():
            if path.stat().st_nlink > 1:
                raise DesignError(f"Linked asset file: {relative}")
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _tree_digest(files: dict) -> str:
    payload = json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False)
    temporary = handle.name
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, path)
    finally:
        handle.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


def _asset_contract_errors(directory: Path) -> tuple:
    """(errors, warnings) for one in-card asset, reusing the asset contract."""
    if not (directory / "asset.json").is_file():
        return [f"missing asset.json: {directory.name}"], []
    try:
        import asset_contract
        asset_contract._inputs(directory)
    except Exception as exc:  # the contract is the source of truth; never crash validate
        message = str(exc)
        if "Dependency scanner requires installed" in message or "Dependency parser unavailable" in message:
            return [f"asset closure unverified: {message}"], []
        return [message], []
    return [], []


def _skeleton(identity: str, kind: str) -> dict:
    if kind == MATERIAL:
        return {"id": identity, "version": 1, "type": MATERIAL,
                "assets": {"directory": ASSET_DIRECTORY},
                "runtime": {"gsap": "^3.14", "plugins": []}}
    return {
        "id": identity, "version": 1, "type": DESIGN,
        "capabilities": legacy_capabilities("explainer"),
        "compatibility": {"supersedes": [], "retired_entrypoints": True},
        "plan_template": "ANIMATION_PLAN.template.md",
        "brief": {"required": [], "optional": []},
        "subjects": {"A": {"primary": "", "secondary": ""}, "B": {"primary": "", "secondary": ""}},
        "stages": {"plan": [".studio/spec/visual-design.md"],
                   "draft": [".studio/spec/visual-design.md", ".studio/spec/hyperframes.md"],
                   "script": [".studio/spec/hyperframes.md"],
                   "research": [".studio/spec/hyperframes.md"],
                   "export": [".studio/spec/hyperframes.md"]},
        "thresholds": {"event_gap_seconds": 2, "still_seconds": 0.6, "pixel_mean_delta": 0.5},
        "critic_checks": [],
        "defaults": {"captions": {"enabled": True}, "sfx": {"enabled": True}, "cover": {"enabled": True}},
        "fields": ["captions.enabled", "sfx.enabled", "cover.enabled"],
        "assets": {"directory": ASSET_DIRECTORY},
        "references": [],
        "runtime": {"gsap": "^3.14", "plugins": []},
        "exemptions": [],
    }


def new(identity, *, from_card=None, kind=DESIGN, root=None, config=None) -> Path:
    """Create a user card skeleton, or copy one, into the configured user root."""
    identity = _check_identity(identity)
    if kind not in TYPES:
        raise DesignError(f"Invalid card type: {kind!r}")
    directory = user_root(root, config, create=True)
    if directory is None:
        raise DesignError("No user design root configured; set design_root before creating a card")
    destination = directory / identity
    located, problems = _locate(root, config)
    if identity in located or any(problem["card"] == identity for problem in problems):
        raise DesignError(f"Design card already exists: {identity}")
    if destination.exists():
        raise DesignError(f"Design card already exists: {destination}")
    final = destination
    with tempfile.TemporaryDirectory(prefix='.new-card-', dir=directory) as temporary:
        destination = Path(temporary) / identity
        if from_card is not None:
            source = card_path(from_card, root, config)
            source_card = _validate_card(from_card, _read_card(source, from_card), strict=True)
            if source_card.get("type") != kind:
                raise DesignError(f"{from_card!r} is a {source_card.get('type')} card, not {kind}")
            windows_runtime.validate_review_tree(source)
            shutil.copytree(source, destination)
            card = _read_card(destination, identity)
            card["id"] = identity
            card["version"] = 1
            card["stages"] = {stage: [name.replace(f".studio/designs/{from_card}/", "") for name in names]
                              for stage, names in card.get("stages", {}).items()} if kind == DESIGN else card.get("stages", {})
            if kind == MATERIAL:
                card.pop("stages", None)
            _atomic_write(destination / "design.json",
                          json.dumps(card, ensure_ascii=False, indent=2) + "\n")
            manifest = destination / "example-manifest.json"
            if manifest.is_file():
                value = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(value, dict) and value.get("design") == from_card:
                    value["design"] = identity
                    for item in value.get("files", []):
                        item["source"] = item["source"].replace(f".studio/designs/{from_card}/", "")
                    _atomic_write(manifest, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        else:
            card = _skeleton(identity, kind)
            destination.mkdir(parents=True)
            _atomic_write(destination / "design.json",
                          json.dumps(card, ensure_ascii=False, indent=2) + "\n")
            (destination / ASSET_DIRECTORY).mkdir()
            if kind == DESIGN:
                (destination / "stages").mkdir()
                (destination / "example").mkdir()
                _atomic_write(destination / "example" / "README.md",
                              "# Editable example\n\nCreate index.html, style.css and scene.js, then declare their hashes and provenance\nin ../example-manifest.json. Use design new --from for an existing runnable example.\n")
                _atomic_write(destination / "GUIDE.md",
                              f"# {identity}\n\nDescribe the look, subject and default switches here.\n")
        _validate_card(identity, _read_card(destination, identity), strict=True)
        destination.rename(final)
    return final


def _user_card_dir(identity, root=None, config=None) -> Path:
    directory = card_path(identity, root, config)
    user = user_root(root, config)
    if user is None or not directory.resolve().is_relative_to(user.resolve()):
        raise DesignError(f"{identity!r} is a built-in card; copy it into the user root before editing")
    return directory


def _read_borrowed(card_dir: Path) -> dict:
    path = card_dir / "borrowed.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DesignError(f"Invalid borrowed.json: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("assets"), dict):
        raise DesignError("Invalid borrowed.json")
    return value["assets"]


def _write_borrowed(card_dir: Path, assets: dict) -> None:
    payload = {"schema_version": 1, "assets": assets}
    _atomic_write(card_dir / "borrowed.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def localize(card, ref, *, root=None, config=None) -> dict:
    """Copy one referenced asset into the card's own library and record its source."""
    card = _check_identity(card)
    source_card, source_asset = _parse_reference(ref)
    directory = _user_card_dir(card, root, config)
    data = get(card, root, config)
    references = data.get("references") or []
    if ref not in references:
        raise DesignError(f"{card} declares no reference {ref!r}")
    source = card_asset_path(source_card, source_asset, root, config)
    if not source.is_dir():
        raise DesignError(f"Referenced asset is missing: {source_card}/{source_asset}")
    destination = _safe_child(directory / (data.get("assets") or {}).get("directory", ASSET_DIRECTORY), source_asset)
    if destination.exists():
        raise DesignError(f"{card} already owns asset {ref!r}")
    windows_runtime.validate_review_tree(directory)
    windows_runtime.validate_review_tree(source)
    files = _tree_files(source)
    metadata = json.loads((source / "asset.json").read_text(encoding="utf-8"))
    borrowed = _read_borrowed(directory)
    raw = _read_card(directory, card)
    borrowed_path = directory / "borrowed.json"
    original_borrowed = borrowed_path.read_text(encoding="utf-8") if borrowed_path.exists() else None
    manifest_path = directory / 'example-manifest.json'
    original_manifest = manifest_path.read_text(encoding='utf-8') if manifest_path.exists() else None
    manifest = json.loads(original_manifest) if original_manifest else None
    if manifest is not None:
        prefix = f'.studio/designs/{source_card}/assets/{source_asset}/'
        for item in manifest['files']:
            if item['source'].startswith(prefix):
                item['source'] = f'assets/{source_asset}/' + item['source'][len(prefix):]
    shutil.copytree(source, destination)
    digest = _tree_digest(files)
    if _tree_digest(_tree_files(destination)) != digest:
        shutil.rmtree(destination, ignore_errors=True)
        raise DesignError("Referenced asset changed while copying")
    borrowed[source_asset] = {"card": source_card, "asset": source_asset, "sha256": digest,
                     "license": metadata.get("license") or metadata.get("rights"),
                     "attribution": metadata.get("attribution") or metadata.get("source_url") or metadata.get("origin")}
    raw["references"] = [value for value in references if value != ref]
    try:
        _write_borrowed(directory, borrowed)
        if manifest is not None:
            _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _atomic_write(directory / "design.json", json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        if original_manifest is not None:
            _atomic_write(manifest_path, original_manifest)
        if original_borrowed is None:
            borrowed_path.unlink(missing_ok=True)
        else:
            _atomic_write(borrowed_path, original_borrowed)
        shutil.rmtree(destination)
        raise
    return {"card": card, "asset": source_asset, "source": f"{source_card}/{source_asset}",
            "sha256": digest, "destination": str(destination)}


def compare(card, asset=None, *, root=None, config=None, commit=None) -> dict:
    """File-level comparison between localized assets and their current source."""
    card = _check_identity(card)
    directory = card_path(card, root, config)
    borrowed = _read_borrowed(directory)
    if asset is not None:
        asset = _check_asset_id(asset)
        if asset not in borrowed:
            raise DesignError(f"{card} has no localized asset {asset!r}; run localize first")
        names = [asset]
    else:
        names = sorted(borrowed)
    result = {}
    for name in names:
        info = borrowed[name]
        if isinstance(info, dict) and isinstance(info.get('source'), dict) and info['source'].get('kind') == 'external':
            import design_sources
            result[name] = design_sources.compare(info['source'], commit, root=root, config=config)
            local_dir = card_asset_path(card, name, root, config)
            result[name]['local_changed'] = _tree_digest(_tree_files(local_dir)) != info.get('sha256')
            continue
        if commit is not None:
            raise DesignError('--commit applies only to external borrowed sources')
        if not isinstance(info, dict) or not isinstance(info.get("card"), str) or not isinstance(info.get("asset"), str):
            raise DesignError(f"Invalid borrowed record for {name!r}")
        source = f"{info['card']}/{info['asset']}"
        source_now, error = {}, None
        try:
            source_dir = card_asset_path(info["card"], info["asset"], root, config)
            if source_dir.is_dir():
                source_now = _tree_files(source_dir)
            else:
                error = f"source asset is missing: {source}"
        except DesignError as exc:
            error = str(exc)
        try:
            local_dir = card_asset_path(card, name, root, config)
            local_now = _tree_files(local_dir) if local_dir.is_dir() else {}
        except DesignError as exc:
            local_now, error = {}, error or str(exc)
        source_sha = _tree_digest(source_now) if not error else None
        local_sha = _tree_digest(local_now)
        paths = sorted(set(source_now) | set(local_now))
        result[name] = {
            "source": source,
            "recorded": info.get("sha256"),
            "source_sha256": source_sha,
            "local_sha256": local_sha,
            "source_available": error is None,
            "error": error,
            "source_changed": error is not None or source_sha != info.get("sha256"),
            "local_changed": local_sha != info.get("sha256"),
            "files": {path: {"source": source_now.get(path), "local": local_now.get(path)}
                      for path in paths if source_now.get(path) != local_now.get(path)},
        }
    return result


def validate(identity=None, *, root=None, config=None, runtime_root=None) -> dict:
    """Structural, reference, host-runtime and determinism checks for cards."""
    try:
        found = catalog(root, config)
    except DesignError as exc:
        return {"ok": False, "cards": {}, "errors": 1, "warnings": 0, "messages": [str(exc)]}
    identities = [_check_identity(identity)] if identity is not None else sorted(found)
    try:
        tracked_user = user_root(root, config)
    except DesignError:
        tracked_user = None
    tracked_root = tracked_user if tracked_user is not None and vcs_state(tracked_user)["vcs"] == "git" else None
    cards = {}
    for name in identities:
        try:
            card = found.get(name) or get(name, root, config)
        except DesignError as exc:
            cards[name] = {"type": None, "errors": [str(exc)], "warnings": [], "references": {}}
            continue
        errors, warnings, references = _validate_one(name, card, found, root, config, runtime_root, tracked_root)
        cards[name] = {"type": card.get("type"), "errors": errors,
                       "warnings": warnings, "references": references}
    return {"ok": all(not item["errors"] for item in cards.values()),
            "cards": cards,
            "errors": sum(len(item["errors"]) for item in cards.values()),
            "warnings": sum(len(item["warnings"]) for item in cards.values()),
            "messages": []}


def template_path(card, name, *, root=None, config=None, directory=None):
    if not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..'):
        raise DesignError('Invalid card template name')
    if directory is None and card:
        try:
            directory = card_path(card['id'], root, config)
        except DesignError:
            pass  # Legacy frozen cards can still use the installed tool template.
    if directory is not None:
        own = _safe_child(Path(directory), name)
        if own.is_file():
            return own
    return repository(root) / '.studio/templates' / name


def _validate_one(name, card, found, root, config, runtime_root, tracked_root=None):
    errors: list[str] = []
    warnings: list[str] = []
    references = {}
    card_dir = card_path(name, root, config)
    if tracked_root is not None and card_dir.resolve().is_relative_to(tracked_root.resolve()) \
            and not (card_dir / "CHANGELOG.md").is_file():
        warnings.append(f"{name}: missing CHANGELOG.md for a version-controlled card")
    if card.get("type") == DESIGN:
        caps = capabilities(card)
        for check in caps["checks"]:
            if not (Path(__file__).parent / CHECKS[check]).is_file():
                errors.append(f"Missing check implementation: {check}")
        if not template_path(card, caps['research_template'], directory=card_dir).is_file():
            errors.append("Missing research_template: " + caps["research_template"])
    try:
        for info in _read_borrowed(card_dir).values():
            if isinstance(info, dict) and 'source' in info:
                import design_sources
                design_sources.validate_record(info['source'])
    except DesignError as error:
        errors.append(str(error))
    try:
        font_manifest(card, card_dir)
    except (DesignError, OSError) as error:
        errors.append(str(error))
    for asset_dir in sorted((card_dir / ASSET_DIRECTORY).glob('*')):
        if asset_dir.is_dir():
            contract_errors, contract_warnings = _asset_contract_errors(asset_dir)
            errors.extend(f'{name}/{asset_dir.name}: {message}' for message in contract_errors)
            warnings.extend(f'{name}/{asset_dir.name}: {message}' for message in contract_warnings)
    for target in card.get("references", []):
        ref = target
        try:
            source_card, source_asset = _parse_reference(target)
        except DesignError as exc:
            references[ref] = {"target": target, "status": "broken", "error": str(exc)}
            errors.append(f"{name}.{ref}: {exc}")
            continue
        if source_card not in found:
            references[ref] = {"target": target, "status": "broken",
                               "error": f"source card {source_card!r} is not installed"}
            errors.append(f"{name}.{ref}: source card {source_card!r} is not installed")
            continue
        try:
            directory = card_asset_path(source_card, source_asset, root, config)
        except DesignError as exc:
            references[ref] = {"target": target, "status": "broken", "error": str(exc)}
            errors.append(f"{name}.{ref}: {exc}")
            continue
        if not directory.is_dir():
            references[ref] = {"target": target, "status": "broken", "error": "asset is missing"}
            errors.append(f"{name}.{ref}: asset is missing")
            continue
        contract_errors, contract_warnings = _asset_contract_errors(directory)
        errors.extend(f"{name}.{ref}: {message}" for message in contract_errors)
        warnings.extend(f"{name}.{ref}: {message}" for message in contract_warnings)
        status = "broken" if contract_errors else "unverified" if contract_warnings else "ok"
        problem = (contract_errors or contract_warnings)
        references[ref] = {"target": target, "status": status,
                           "error": problem[0] if problem else None}
    runtime = card.get("runtime") or {}
    spec = runtime.get("gsap")
    if spec is not None:
        version = host_gsap(root)
        if version is None:
            warnings.append("host GSAP version is not locked by " + LOCK_NAME)
        elif not version_satisfies(version, spec):
            errors.append(f"gsap {spec} is not satisfied by host {version}")
    plugins = runtime.get("plugins") or []
    if plugins:
        available = host_plugin_files(runtime_root if runtime_root is not None else root)
        if available is None:
            warnings.append("host GSAP runtime is not installed; plugins cannot be verified")
        else:
            for plugin in plugins:
                if not _host_plugin_available(available, plugin):
                    errors.append(f"host runtime does not provide plugin {plugin!r}")
    for path in sorted(card_dir.rglob("*")):
        if path.is_symlink():
            errors.append(f"linked card file: {path.relative_to(card_dir).as_posix()}")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(card_dir).as_posix()
        if _is_gsap_file(path.name):
            errors.append(f"card ships a GSAP file: {relative}")
        if path.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        stripped = _strip_comments(text)
        for line_number, line in enumerate(stripped.splitlines(), start=1):
            for pattern, label in _NONDETERMINISM:
                if pattern.search(line):
                    warnings.append(f"{relative}:{line_number} uses {label}")
    return errors, warnings, references


def font_manifest(card, directory):
    """Resolve card-owned font files once; frozen Locks carry their exact bytes."""
    fonts = card.get('fonts', [])
    if not isinstance(fonts, list):
        raise DesignError('Card fonts must be an array')
    result = []
    for font in fonts:
        if (not isinstance(font, dict) or set(font) - {'family', 'path', 'license', 'weight', 'style'}
                or not {'family', 'path', 'license'} <= set(font)
                or not isinstance(font['family'], str) or not font['family'].strip()):
            raise DesignError('Card font requires family, path and license')
        if font.get('style', 'normal') not in ('normal', 'italic', 'oblique'):
            raise DesignError('Invalid card font style')
        weight = font.get('weight', 400)
        if type(weight) is not int or not 1 <= weight <= 1000:
            raise DesignError('Card font weight must be 1..1000')
        item = {**font, 'weight': weight, 'style': font.get('style', 'normal')}
        for key in ('path', 'license'):
            source = _safe_child(directory, font[key])
            if not source.is_file() or source.stat().st_nlink > 1:
                raise DesignError('Missing or linked card font resource: ' + font[key])
            if key == 'path' and source.suffix.lower() not in ('.ttf', '.otf', '.woff', '.woff2'):
                raise DesignError('Unsupported card font file')
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            item[key + '_source'] = font[key]
            item[key + '_sha256'] = sha
            item[key] = 'runtime/card-fonts/' + sha + (source.suffix.lower() or '.txt')
        result.append(item)
    return {'card': card['id'], 'fonts': result}


def install_fonts(project, manifest):
    for font in manifest['fonts']:
        for key in ('path', 'license'):
            target = _safe_child(project, font[key])
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != font[key + '_sha256']:
                    raise DesignError('Installed card font changed: ' + font[key])
                continue
            source = _safe_child(card_path(manifest['card']), font[key + '_source'])
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != font[key + '_sha256']:
                raise DesignError('Card font changed before installation')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def vcs_state(directory) -> dict:
    """Read-only Git state of a directory; never runs a writing git command."""
    state = {"path": str(directory), "vcs": "none", "toplevel": None, "nested": False, "branch": None,
             "dirty": None, "untracked": None, "remote": None, "ahead": None, "behind": None, "error": None}
    def run(*args):
        return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True,
                              timeout=10, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    try:
        top = run("rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired) as error:
        return {**state, "vcs": "unknown", "error": str(error)}
    if top.returncode != 0:
        return state
    toplevel = Path(top.stdout.strip())
    state.update(vcs="git", toplevel=str(toplevel), nested=toplevel.resolve() == Path(directory).resolve())
    try:
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        state["branch"] = branch.stdout.strip() if branch.returncode == 0 else None
        status = run("status", "--porcelain=v1", "--untracked-files=normal", "--", ".")
        if status.returncode == 0:
            lines = [line for line in status.stdout.splitlines() if line.strip()]
            state["untracked"] = sum(1 for line in lines if line.startswith("??"))
            state["dirty"] = len(lines) - state["untracked"]
        upstream = run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if upstream.returncode == 0:
            state["remote"] = upstream.stdout.strip()
            counts = run("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
            if counts.returncode == 0:
                ahead, behind = counts.stdout.split()
                state.update(ahead=int(ahead), behind=int(behind))
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        state["error"] = str(error)
    return state


def root_report(root=None, config=None) -> dict:
    """Where user cards live and its version-control state; read-only."""
    data = load_config(root, config)
    report = {"design_root": None, "configured": isinstance(data.get("design_root"), str), "exists": False, "vcs": None, "error": None}
    try:
        directory = user_root(root, config)
    except DesignError as error:
        return {**report, "error": str(error)}
    if directory is None:
        return report
    report.update(design_root=str(directory), exists=True, vcs=vcs_state(directory))
    return report


def compare_since(card, rev, *, root=None, config=None) -> dict:
    """Files of one user card changed since a Git revision of the design_root working tree; read-only."""
    card = _check_identity(card)
    directory = card_path(card, root, config)
    user = user_root(root, config)
    if user is None or not directory.resolve().is_relative_to(user.resolve()):
        raise DesignError(f"{card} is not a user card; --since applies to cards under design_root")
    state = vcs_state(user)
    if state["vcs"] != "git":
        raise DesignError("design_root is not a Git working tree")
    toplevel = Path(state["toplevel"])
    relative = directory.resolve().relative_to(toplevel.resolve()).as_posix()

    def run(*args):
        return subprocess.run(["git", "-C", str(toplevel), *args], capture_output=True, text=True,
                              timeout=10, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if run("rev-parse", "--verify", "--quiet", rev + "^{commit}").returncode != 0:
        raise DesignError(f"Unknown revision: {rev}")
    diff = run("diff", "--name-status", rev, "--", relative)
    if diff.returncode != 0:
        raise DesignError(diff.stderr.strip() or "git diff failed")
    files = []
    for line in diff.stdout.splitlines():
        status, _, path = line.partition("\t")
        if path:
            files.append({"status": status.strip(), "path": path})
    untracked = run("ls-files", "--others", "--exclude-standard", "--", relative)
    files.extend({"status": "??", "path": path} for path in untracked.stdout.splitlines() if path)
    shown = run("show", f"{rev}:{relative}/design.json")
    since_version = None
    if shown.returncode == 0:
        try:
            since_version = json.loads(shown.stdout).get("version")
        except ValueError:
            since_version = None
    current_version = _read_card(directory, card).get("version")
    bumped = since_version is None or (isinstance(current_version, int) and isinstance(since_version, int)
                                       and current_version > since_version)
    changelog = (directory / "CHANGELOG.md").is_file()
    warning = None
    if files and not bumped:
        warning = f"{card} changed since {rev} but design.json.version is still {current_version}"
    return {"card": card, "since": rev, "files": files,
            "version": {"since": since_version, "current": current_version, "bumped": bumped},
            "changelog": changelog, "warning": warning}
