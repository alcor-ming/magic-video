"""Frozen private requests and exact, isolated candidate handoffs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


class RequestError(RuntimeError):
    pass


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RequestError(f"Cannot read {path}: {exc}") from exc


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def safe(root, relative):
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise RequestError(f"Unsafe relative path: {relative}")
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in (result, *result.parents) if p != root.parent):
        raise RequestError(f"Linked path is not allowed: {relative}")
    return result


def identity(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise RequestError(f"Invalid request/delivery ID: {value}")
    return value


def entries(root):
    if not root.is_dir() or root.is_symlink():
        raise RequestError(f"Expected a regular directory: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        safe(root, relative)
        if path.is_file():
            result[relative] = digest(path)
    return result


def verify(directory, manifest_name, key="files"):
    data = read(directory / manifest_name)
    actual = entries(directory)
    actual.pop(manifest_name, None)
    if actual != data[key]:
        raise RequestError(f"Frozen handoff changed: {directory}")
    return data


def review_identity(root):
    root = Path(root).resolve()
    marker = read(root / ".runtime" / "review.json")
    config = json.loads(os.environ.get("HYPERFRAMES_AI_RESOLVED_CONFIG", "{}"))
    direct = (config.get("review") is True and str(root) == config.get("work_root"))
    # Old Review copies retain their parent-relative identity; direct roots use resolved scope.
    production = root.parent.parent
    if not direct and (root.parent.name != "review" or not (production / "works").is_dir()):
        raise RequestError("Review requires an independent WorkStore under production/review/<id>")
    if marker.get("review_id") != root.name or marker.get("mode") != "review":
        raise RequestError("Review identity does not match this WorkStore")
    for name in ("active", "parked", "archive"):
        safe(root, f"works/{name}")
    safe(root, ".runtime")
    return marker


def project_review_root(project):
    if os.environ.get("HYPERFRAMES_AI_REVIEW") != "1":
        return None
    asset_review = os.environ.get("HYPERFRAMES_AI_ASSET_REVIEW_ROOT")
    if asset_review and Path(project).resolve().is_relative_to((Path(asset_review) / "sources").resolve()):
        from asset_store import authoring_project
        authoring_project(Path(os.environ["HYPERFRAMES_AI_ROOT"]), Path(project))
        return None
    for root in Path(project).resolve().parents:
        if (root / ".runtime" / "review.json").is_file():
            review_identity(root)
            if not Path(project).resolve().is_relative_to(root / "works"):
                raise RequestError("Candidate project must be inside a Review Work")
            return root
    raise RequestError("Candidate execution requires an isolated Review WorkStore")


def init_review(store, review_id):
    destination = safe(store, f"review/{identity(review_id)}")
    if destination.exists():
        raise RequestError("Review ID already exists; use a new ID")
    for location in ("active", "parked", "archive"):
        (destination / "works" / location).mkdir(parents=True)
    write(destination / ".runtime" / "review.json", {"mode": "review", "review_id": review_id, "ready": True})
    (destination / "AGENTS.md").write_text(
        "# Isolated Windows Review\n\n"
        "This root is test content, never production. Use the independent deployed root's work.cmd, "
        "root rules and Skills. Windows authors Scene/GSAP/Three/shader/media content here; "
        "only Harness or host/tool defects go to WSL. This overrides any older parent rule "
        "requiring WSL content rendering. Never edit production Work, assets, defaults, "
        "frozen vendor or accepted snapshots. No production Final, archive or platform drafts.\n",
        encoding="utf-8")
    review_identity(destination)
    return destination


def freeze(store, work, variant, request_id, brief, scenes, affected, context, preview=None):
    request = safe(store, f"requests/{identity(request_id)}")
    request.mkdir(parents=True, exist_ok=True)
    revisions = [int(p.name[1:]) for p in request.glob("r[0-9]*") if p.name[1:].isdigit()]
    revision = max(revisions, default=0) + 1
    destination = request / f"r{revision:03}"
    if not affected or not scenes:
        raise RequestError("Request requires affected --file paths and --scene IDs")
    project = variant / "project"
    if preview:
        project = variant / "previews" / identity(preview) / "source-snapshot"
    with tempfile.TemporaryDirectory(dir=request) as temporary:
        staging = Path(temporary) / "revision"
        staging.mkdir()
        shutil.copyfile(brief, staging / "REQUEST.md")
        baseline = {}
        for relative in sorted(set(affected + context)):
            source = safe(project, relative)
            baseline[relative] = digest(source) if source.is_file() else None
            if baseline[relative] is None and relative in context:
                raise RequestError(f"Missing context file: {relative}")
            if source.exists() and not source.is_file():
                raise RequestError(f"Request files must be individual regular files: {relative}")
            if source.is_file():
                target = safe(staging / "repro" / "project", relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if digest(target) != baseline[relative]:
                    raise RequestError(f"Request input changed while freezing: {relative}")
        shutil.copyfile(work / "WORK.md", staging / "WORK.md")
        state = read(variant / "variant.yaml") if (variant / "variant.yaml").is_file() else {}
        for name in ("variant.yaml", "SCRIPT.md", "RESEARCH.md", "ANIMATION_PLAN.md", "section_map.json"):
            reference = state.get("shared_inputs", {}).get(name)
            source = safe(work, reference) if reference is not None else variant / name
            if source.is_file():
                target = staging / "repro" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        if state.get("shared_inputs"):
            state.pop("shared_inputs")
            write(staging / "repro" / "variant.yaml", state)
        metadata = {"schema_version": 1, "request_id": request_id, "revision": revision,
                    "work": work.name, "variant": variant.name, "scenes": scenes, "preview": preview,
                    "affected_files": sorted(set(affected)), "baseline": baseline, "files": entries(staging)}
        write(staging / "request.json", metadata)
        staging.rename(destination)
    return destination


def export_request(revision, output):
    verify(revision, "request.json")
    if output.exists():
        raise RequestError("Export destination already exists")
    shutil.copytree(revision, output)
    verify(output, "request.json")
    return output


def deliver(revision, delivery_id, source, component=None, binding=None):
    from component_harness import validate_component_release
    request = verify(revision, "request.json")
    parent = revision.parent / "deliveries"
    parent.mkdir(exist_ok=True)
    destination = parent / identity(delivery_id)
    if destination.exists():
        raise RequestError("Delivery ID already exists; deliver a new immutable candidate")
    files = entries(source)
    if set(files) - set(request["affected_files"]):
        raise RequestError("Delivery changes files outside the frozen request scope")
    if any(name == "COMPONENT_LOCK.json" or name.startswith("vendor/components/") for name in files):
        raise RequestError("Component vendor/lock changes must use the component installer")
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        staging = Path(temporary) / "delivery"
        shutil.copytree(source, staging / "patch")
        if entries(staging / "patch") != files:
            raise RequestError("Patch changed while freezing delivery")
        data = {"schema_version": 1, "delivery_id": delivery_id, "request_id": request["request_id"],
                "revision": request["revision"], "request_sha256": digest(revision / "request.json"),
                "kind": "component" if component else "work-local", "patch": files}
        if component:
            if not binding:
                raise RequestError("Component delivery requires --binding")
            release = validate_component_release(component, allow_unapproved=True)
            shutil.copytree(component, staging / "component")
            shutil.copyfile(binding, staging / "binding.json")
            data["component_ref"] = release["component_ref"]
        data["files"] = entries(staging)
        write(staging / "delivery.json", data)
        staging.rename(destination)
    return destination


def checked_pair(revision, delivery):
    request = verify(revision, "request.json")
    candidate = verify(delivery, "delivery.json")
    if (candidate["request_id"], candidate["revision"], candidate["request_sha256"]) != (request["request_id"], request["revision"], digest(revision / "request.json")):
        raise RequestError("Delivery does not target this exact request revision")
    if set(candidate["patch"]) - set(request["affected_files"]):
        raise RequestError("Candidate patch exceeds the request scope")
    if entries(delivery / "patch") != candidate["patch"]:
        raise RequestError("Candidate patch manifest differs from its files")
    if candidate.get("kind") not in {"component", "work-local"}:
        raise RequestError("Unsupported delivery kind")
    return request, candidate


def check_patch_baseline(project, request, candidate):
    # Unaffected Scenes may keep changing while the request is in flight.
    for relative in candidate["patch"]:
        target = safe(project, relative)
        actual = digest(target) if target.is_file() else None
        if target.exists() and not target.is_file() or actual != request["baseline"].get(relative):
            raise RequestError(f"Affected file changed since request: {relative}")


def apply_patch_files(project, request, delivery, candidate):
    check_patch_baseline(project, request, candidate)
    for relative in candidate["patch"]:
        target = safe(project, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe(delivery / "patch", relative), target)


def review(store, revision, delivery, read_variant, write_variant):
    from component_harness import install_component
    request, candidate = checked_pair(revision, delivery)
    review_id = identity(f"{request['request_id']}-r{request['revision']:03}-{candidate['delivery_id']}")
    destination = safe(store, f"review/{review_id}")
    if destination.exists():
        marker = review_identity(destination)
        if not marker.get("ready") or marker.get("delivery_sha256") != digest(delivery / "delivery.json"):
            raise RequestError("Review directory belongs to another candidate")
        return destination
    destination.mkdir(parents=True)
    for location in ("active", "parked", "archive"):
        (destination / "works" / location).mkdir(parents=True)
    work = destination / "works" / "active" / request["work"]
    variant = work / "variants" / request["variant"]
    shutil.copytree(revision / "repro", variant)
    (variant / "project" / "compositions").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(revision / "WORK.md", work / "WORK.md")
    state = read_variant(variant / "variant.yaml")
    state.update(status="active", accepted_visual_plan=None, accepted_preview=None,
                 accepted_plan_revision=None, accepted_script_revision=None, wait_for="none")
    write_variant(variant, state)
    marker = {"mode": "review", "review_id": review_id, "request_id": request["request_id"],
              "revision": request["revision"], "delivery_id": candidate["delivery_id"],
              "delivery_sha256": digest(delivery / "delivery.json"), "work": request["work"], "variant": request["variant"]}
    write(destination / ".runtime" / "review.json", marker)
    apply_patch_files(variant / "project", request, delivery, candidate)
    if candidate["kind"] == "component":
        install_component(delivery / "component", variant / "project", delivery / "binding.json", review_root=destination)
    marker["project_files"] = entries(variant / "project")
    marker["ready"] = True
    write(destination / ".runtime" / "review.json", marker)
    return destination


def accept(store, revision, delivery, variant, approved_component=None):
    from component_harness import install_component, validate_component_release
    request, candidate = checked_pair(revision, delivery)
    if variant.name != request["variant"] or variant.parent.parent.name != request["work"]:
        raise RequestError("Accept target must match the frozen Work/Variant")
    project = variant / "project"
    if candidate["kind"] == "component":
        if not approved_component:
            raise RequestError("Public component requires a library-approved --approved-component")
        approved = validate_component_release(approved_component, expected_ref=candidate["component_ref"])
        original = validate_component_release(delivery / "component", allow_unapproved=True)
        old_meta, new_meta = dict(original["metadata"]), dict(approved["metadata"])
        old_meta.pop("status", None)
        new_meta.pop("status", None)
        old_files, new_files = entries(delivery / "component"), entries(approved_component)
        for name in ("COMPONENT.md", "HASHES.json"):
            old_files.pop(name, None)
            new_files.pop(name, None)
        if old_meta != new_meta or old_files != new_files:
            raise RequestError("Approved implementation differs from the reviewed candidate")
    receipt = revision.parent / "decisions" / f"{candidate['delivery_id']}.json"
    if receipt.exists():
        raise RequestError("Candidate already accepted; receipt retained")
    check_patch_baseline(project, request, candidate)
    review_id = identity(f"{request['request_id']}-r{request['revision']:03}-{candidate['delivery_id']}")
    review_root = safe(store, f"review/{review_id}")
    marker = review_identity(review_root)
    reviewed_project = review_root / "works" / "active" / request["work"] / "variants" / request["variant"] / "project"
    if (not marker.get("ready") or marker.get("delivery_sha256") != digest(delivery / "delivery.json")
            or marker.get("project_files") != entries(reviewed_project)):
        raise RequestError("Review input changed; freeze and review a new candidate before accepting")
    with tempfile.TemporaryDirectory(dir=variant) as temporary:
        staged = Path(temporary) / "project"
        if candidate["kind"] == "component":
            # Component validation needs the existing bindings and local Surface payloads.
            shutil.copytree(project, staged)
            apply_patch_files(staged, request, delivery, candidate)
            install_component(approved_component, staged, delivery / "binding.json")
            current = entries(project)
            changed = {path for path, value in entries(staged).items() if current.get(path) != value}
        else:
            shutil.copytree(delivery / "patch", staged)
            changed = set(candidate["patch"])
        check_patch_baseline(project, request, candidate)
        backup = Path(temporary) / "before"
        for relative in sorted(changed):
            target = safe(project, relative)
            if target.is_file():
                original = safe(backup, relative)
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, original)
        applied = []
        try:
            for relative in sorted(changed):
                target = safe(project, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(safe(staged, relative), target)
                applied.append(relative)
            write(receipt, {"decision": "accepted", "request_id": request["request_id"], "revision": request["revision"],
                            "delivery_id": candidate["delivery_id"], "delivery_sha256": digest(delivery / "delivery.json"),
                            "work": request["work"], "variant": request["variant"]})
        except Exception:
            for relative in reversed(applied):
                target = safe(project, relative)
                original = safe(backup, relative)
                if original.is_file():
                    os.replace(original, target)
                else:
                    target.unlink()
            raise
    return receipt
