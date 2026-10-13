"""Archived video succession, using the existing identity file and naming lock."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import uuid


JOURNAL = "work-successor.json"


def series_key(series, number):
    return f"{series}:{number}"


def validate(rows, identity, api):
    groups = {}
    by_id = {}
    for row in rows:
        if row["id"] in by_id:
            raise api.HarnessError(f"Duplicate physical Work ID: {row['id']}")
        by_id[row["id"]] = row
        if row["workflow"] == "hyperframes_video" and row["purpose"] != "test" and row["series_number"]:
            key = series_key(row["series"], row["series_number"])
            groups.setdefault(key, []).append(row["id"])
    for key, record in identity["successions"].items():
        chain = record.get("chain") if isinstance(record, dict) else None
        requests = record.get("requests") if isinstance(record, dict) else None
        if (not isinstance(chain, list) or len(chain) < 2
                or not all(isinstance(item, str) for item in chain) or len(set(chain)) != len(chain)
                or not isinstance(requests, dict) or set(requests) != set(chain[:-1])):
            raise api.HarnessError(f"Invalid succession chain: {key}")
        for index, work_id in enumerate(chain):
            api.validate_id(work_id, "succession Work")
            row = by_id.get(work_id)
            if row and (row["workflow"] != "hyperframes_video" or row["purpose"] == "test"
                        or series_key(row["series"], row["series_number"]) != key
                        and identity["series_aliases"].get(key) != work_id):
                raise api.HarnessError(f"Succession series changed: {work_id}")
            if index < len(chain) - 1:
                request = requests[work_id]
                if not isinstance(request, dict) or request.get("target") != chain[index + 1]:
                    raise api.HarnessError(f"Invalid succession link: {work_id}")
                if row and row["location"] != "archive":
                    raise api.HarnessError(f"Succession predecessor must remain archived: {work_id}")
        if not set(groups.get(key, [])) <= set(chain):
            raise api.HarnessError(f"Unrelated duplicate series number: {key}")
    for key, ids in groups.items():
        if len(ids) > 1 and key not in identity["successions"]:
            raise api.HarnessError(f"Unrelated duplicate series number: {key}")


def current(rows, identity, key, api, seen=None):
    seen = set() if seen is None else seen
    if key in seen:
        raise api.HarnessError("Series alias cycle")
    seen.add(key)
    record = identity["successions"].get(key)
    if record:
        target = record["chain"][-1]
        row = next((row for row in rows if row["id"] == target), None)
    else:
        row = next((row for row in rows if series_key(row["series"], row["series_number"]) == key
                    and row["workflow"] == "hyperframes_video" and row["purpose"] != "test"), None)
        if row is None:
            target = identity["series_aliases"].get(key)
            row = next((row for row in rows if row["id"] == target), None)
    if row is not None:
        actual = series_key(row["series"], row["series_number"])
        if actual != key:
            return current(rows, identity, actual, api, seen)
    return row


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _recover(root, journal, request, api):
    record = api.read_json(journal)
    if record.get("request") != request:
        raise api.HarnessError("Succession recovery pending; retry the original successor command")
    staging_name, target_name = record.get("staging", ""), record.get("target", "")
    api.validate_id(staging_name, "succession staging")
    api.validate_id(target_name, "succession target")
    if not staging_name.startswith(".pending-") or not target_name.startswith("work-hyperframes_video-"):
        raise api.HarnessError("Invalid succession recovery paths")
    # Journals from before the series layout have no parent and staged under works/active.
    folder = record.get("parent", "active")
    api.validate_id(folder, "succession folder")
    parent = api.works_root(root) / folder
    staging, target = parent / staging_name, parent / target_name
    state = api.identity_state(root)
    if _fingerprint(state) not in (record["identity_before"], _fingerprint(record["identity_after"])):
        raise api.HarnessError("Identity changed during succession; retain recovery journal")
    source = target if target.exists() else staging
    if api.snapshot_tree_manifest(source) != record["files"]:
        raise api.HarnessError("Succession candidate changed; retain recovery journal")
    if target.exists() and staging.exists():
        raise api.HarnessError("Both succession staging and target exist")
    if not target.exists():
        staging.rename(target)
    api.write_identity(root, record["identity_after"])
    journal.unlink()
    return target


def _accepted_source(work, variant_id, version, api):
    variant = api.storage.scoped_path(work, f"variants/{api.validate_id(variant_id, 'source Variant')}")
    state = api.read_json(variant / "variant.yaml")
    preview = api.storage.scoped_path(variant, f"previews/{api.validate_id(version, 'source version')}")
    metadata = api.preview_metadata(preview)
    api.assert_full_draft(metadata)
    accepted = state.get("accepted_preview") == version
    for path in [variant / "final" / "manifest.json", *(variant / "final" / "history").glob("*/manifest.json")]:
        if path.is_file():
            manifest = api.read_json(path)
            accepted |= (manifest.get("source_preview") == version
                         and manifest.get("workflow") == "hyperframes_video" and manifest.get("qa") == "passed")
    if not accepted:
        raise api.HarnessError("Source version is not an accepted Draft")
    api.assert_preview_inputs(preview, metadata)
    snapshot = api.storage.scoped_path(preview, "source-snapshot")
    api.assert_snapshot_source(snapshot)
    if api.snapshot_digest(snapshot) != metadata.get("snapshot_sha256"):
        raise api.HarnessError("Accepted source snapshot changed")
    # Frozen documents, not the archived Variant's possibly newer working files.
    for name in api.PREVIEW_DOCUMENTS:
        path = api.storage.scoped_path(preview, name)
        if not path.is_file():
            raise api.HarnessError(f"Accepted source lacks frozen {name}; cannot infer its content")
    api.validate_dependencies(snapshot)
    api.snapshot_tree_manifest(preview)
    return preview, metadata


def command(root, args, api):
    api.ensure_roots(root)
    with api.naming_lock(root, successor_recovery=True):
        source, location = api.locate_work(root, args.source_work)
        source_meta = api.read_frontmatter(source / "WORK.md")
        if (location != "archive" or source_meta.get("workflow") != "hyperframes_video"
                or source_meta.get("purpose") not in {"standard", "ip"}
                or not source_meta.get("series") or not source_meta.get("series_number")):
            raise api.HarnessError("Successor requires an archived production video Work with a series number")
        title = api.semantic_title(args.title or source_meta["title"], video=True)
        if not title or any(char in title for char in "\r\n"):
            raise api.HarnessError("Work title must be non-empty on one line")
        request = {"source": source.name, "source_variant": api.validate_id(args.source_variant, "source Variant"),
                   "source_version": api.validate_id(args.source_version, "source version"),
                   "account": api.validate_id(args.account, "account"),
                   "variant_id": api.validate_id(args.variant_id, "Variant"), "title": title}
        journal = api.runtime_root(root) / JOURNAL
        if journal.exists():
            target = _recover(root, journal, request, api)
        else:
            rows, identity = api.list_work_rows(root), api.identity_state(root)
            key = series_key(source_meta["series"], source_meta["series_number"])
            chain = identity["successions"].get(key, {"chain": [source.name], "requests": {}})
            previous = chain["requests"].get(source.name)
            if previous:
                if {key: value for key, value in previous.items() if key != "target"} != request:
                    raise api.HarnessError("Source already has another successor request")
                target, _ = api.locate_work(root, previous["target"])
            else:
                row = current(rows, identity, key, api)
                if row is None or row["id"] != source.name or chain["chain"][-1] != source.name:
                    raise api.HarnessError("Source is not the current succession endpoint")
                preview, metadata = _accepted_source(source, args.source_variant, args.source_version, api)
                source_files = api.snapshot_tree_manifest(preview)
                args.workflow, args.purpose, args.batch = "hyperframes_video", source_meta["purpose"], None
                args.series = source_meta["series"]
                settings = api.adopted_settings(root, args)
                number = api.video_number(root, rows, identity)
                work_id = f"work-hyperframes_video-{number:03d}-{api.work_slug(title)}"
                target = api.series_folder(root, source_meta["series"]) / work_id
                if target.exists() or work_id in identity["aliases"]:
                    raise api.HarnessError("Successor identity already exists")
                staging = target.with_name(f".pending-{uuid.uuid4().hex}")
                staging.parent.mkdir(parents=True, exist_ok=True)
                staging.mkdir()
                try:
                    api.atomic_write(staging / "WORK.md", api.template_text(root, "WORK.template.md", {
                        "WORK_ID": api.json_string_content(work_id), "TITLE": api.json_string_content(title),
                        "CREATED_AT": api.now(), "WORKFLOW": "hyperframes_video", "REQUIRED_VARIANTS": "[]"}))
                    work_meta = api.read_frontmatter(staging / "WORK.md")
                    work_meta.update(purpose=source_meta["purpose"], series=source_meta["series"],
                                     series_number=source_meta["series_number"], shared_source=True,
                                     source_work=source.name, source_variant=args.source_variant, source_version=args.source_version,
                                     predecessor=source.name)
                    api.atomic_write(staging / "WORK.md", "---\n" + json.dumps(work_meta, ensure_ascii=False)
                                     + "\n---\n" + api.document_body(staging / "WORK.md"))
                    shared = staging / "shared"
                    shared.mkdir()
                    for name in ("SCRIPT.md", "RESEARCH.md"):
                        shutil.copy2(preview / name, shared / name)
                    # Keep adopted media/project and the old Plan as source evidence, not new acceptance or account settings.
                    evidence = staging / "materials" / "predecessor"
                    evidence.mkdir(parents=True)
                    api.copy_snapshot(preview / "source-snapshot", evidence / "source-snapshot")
                    api.validate_snapshot_closure(preview / "source-snapshot", evidence / "source-snapshot")
                    for name in (*api.PREVIEW_DOCUMENTS, "preview.md"):
                        shutil.copy2(preview / name, evidence / name)
                    source_note = source / "source.md"
                    if source_note.is_file():
                        api.storage.scoped_path(source, "source.md")
                        shutil.copy2(source_note, staging / "source.md")
                    else:
                        api.atomic_write(staging / "source.md", "# Source\n\n")
                    api.write_json(evidence / "provenance.json", {**request, "snapshot_sha256": metadata["snapshot_sha256"],
                                   "files": api.snapshot_tree_manifest(evidence)})
                    api.create_adopted_variant(root, staging, args.variant_id, settings, shared=True,
                                               workflow="hyperframes_video", ratio=settings.get("ratio"),
                                               copy_script_from=shared / "SCRIPT.md")
                    if api.snapshot_tree_manifest(preview) != source_files:
                        raise api.HarnessError("Accepted source changed during adoption")
                    before = _fingerprint(identity)
                    chain["chain"].append(work_id)
                    chain["requests"][source.name] = {**request, "target": work_id}
                    identity["successions"][key] = chain
                    identity["video_highwater"] = number
                    api.write_json(journal, {"request": request, "staging": staging.name, "target": work_id,
                                            "parent": target.parent.name,
                                            "identity_before": before, "identity_after": identity,
                                            "files": api.snapshot_tree_manifest(staging)})
                    target = _recover(root, journal, request, api)
                except BaseException:
                    if not journal.exists() and staging.exists():
                        shutil.rmtree(staging)
                    raise
        if not args.detached:
            api.write_current(root, target.name, args.variant_id)
    print(target.name)
