"""One-time RC2 video Work identity migration; never run on import."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


VIDEO = "hyperframes_video"
JOURNAL = "rc2-migration.json"
COMPLETED = "rc2-migration-completed.json"


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _store(root: Path, api: Any) -> Path:
    return api.works_root(root).parent.resolve()


def _relative(store: Path, path: Path) -> str:
    path = path.resolve()
    if not path.is_relative_to(store):
        raise MigrationError(f"Migration path escapes WorkStore: {path}")
    return path.relative_to(store).as_posix()


class MigrationError(RuntimeError):
    pass


def _work_text(path: Path, api: Any, changes: dict[str, Any]) -> str:
    metadata = api.read_frontmatter(path)
    metadata.update(changes)
    body = api.document_body(path)
    heading = metadata.pop("_heading", None)
    if heading is not None:
        body = re.sub(r"(?m)^# .*$", lambda _: f"# {heading}", body, count=1)
    return "---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n" + body


def _pending_dependencies(store: Path, old_id: str) -> list[str]:
    blockers = []
    for request in sorted((store / "requests").glob("*/r*/request.json")):
        data = json.loads(_text(request))
        if data.get("work") != old_id:
            continue
        decisions = request.parent.parent / "decisions"
        accepted = {item.get("delivery_id") for path in decisions.glob("*.json")
                    if (item := json.loads(_text(path))).get("revision") == data.get("revision")
                    and item.get("decision") == "accepted"}
        deliveries = [path for path in (request.parent.parent / "deliveries").glob("*/delivery.json")
                      if json.loads(_text(path)).get("revision") == data.get("revision")]
        pending = [path for path in deliveries
                   if json.loads(_text(path)).get("delivery_id") not in accepted]
        if not deliveries and not accepted:
            blockers.append(str(request))
        blockers.extend(str(path) for path in pending)
    for marker in sorted((store / "review").glob("*/.runtime/review.json")):
        data = json.loads(_text(marker))
        if data.get("work") != old_id:
            continue
        request_id, revision, delivery_id = data.get("request_id"), data.get("revision"), data.get("delivery_id")
        decisions = store / "requests" / str(request_id) / "decisions"
        accepted = any(json.loads(_text(item)).get("revision") == revision
                       and json.loads(_text(item)).get("delivery_id") == delivery_id
                       and json.loads(_text(item)).get("decision") == "accepted"
                       for item in decisions.glob("*.json"))
        if not accepted:
            blockers.append(str(marker))
    return blockers


def _historical_session_copy(path: Path, data: dict[str, Any], expected_ids: tuple[str, str], api: Any) -> bool:
    if not re.fullmatch(r"studio-s\d{2}-session\.json", path.name):
        return False
    target = data["target"]
    if not re.fullmatch(r"(?:plan|draft)-v\d+", target):
        return False
    try:
        current = api.read_json(path.with_name(f"studio-{target}.json"))
    except (OSError, UnicodeError, api.HarnessError):
        return False
    old_id, new_id = expected_ids
    old_root = str(path.parents[3].with_name(old_id)) + os.sep
    new_root = str(path.parents[3].with_name(new_id)) + os.sep
    relocated = (old_id != new_id and data["work"] == old_id and current.get("work") == new_id
                 and data["project"].startswith(old_root)
                 and current.get("project") == new_root + data["project"][len(old_root):])
    return (set(current) == set(data)
            and all(current[key] == value for key, value in data.items()
                    if key not in {"opened_at", "work", "project"})
            and ((current.get("work") == data["work"] and current.get("project") == data["project"])
                 or relocated))


def _studio_records(work: Path, api: Any, expected_ids: tuple[str, str] | None = None) -> tuple[list[Path], list[str]]:
    files, blockers = [], []
    expected_ids = expected_ids or (work.name, work.name)
    qa_fields = {
        "studio-initial.json": {"url", "errors", "dnt", "frames", "buttons"},
        "studio-qa.json": {"errors", "dnt", "initial", "samples", "emphasis", "playing",
                           "paused", "pausedLater", "lint"},
    }
    for path in sorted(work.glob("variants/*/.runtime/studio-*.json")):
        try:
            data = api.read_json(path)
        except (OSError, UnicodeError, api.HarnessError):
            blockers.append(str(path))
            continue
        if set(data) == qa_fields.get(path.name):
            continue
        pid = data.get("pid")
        session = (type(pid) is int and 0 < pid <= 0xFFFFFFFF
                   and isinstance(data.get("work"), str) and data["work"] in expected_ids
                   and data.get("variant") == path.parents[1].name
                   and isinstance(data.get("target"), str)
                   and all(isinstance(data.get(key), str) and data[key]
                           for key in ("project", "kind", "cli_sha256"))
                   and type(data.get("port")) is int and 0 < data["port"] <= 65535
                   and ("stopped_at" not in data or isinstance(data["stopped_at"], str)
                        and bool(data["stopped_at"])))
        if not session or not data.get("stopped_at") and not api.storage.process_stopped(pid):
            blockers.append(str(path))
        elif data["target"] == path.stem.removeprefix("studio-"):
            files.append(path)
        elif _historical_session_copy(path, data, expected_ids, api):
            continue
        else:
            blockers.append(str(path))
    return files, blockers


def build_plan(root: Path, api: Any, *, title_overrides: dict[str, str] | None = None,
               purpose_overrides: dict[str, str] | None = None,
               only_ids: list[str] | None = None) -> dict[str, Any]:
    """Inventory retained Works only. No directory, pointer or metadata writes."""
    store = _store(root, api)
    overrides = title_overrides or {}
    purposes = purpose_overrides or {}
    if any(value not in {"standard", "ip", "test"} for value in purposes.values()):
        raise MigrationError("Purpose override must be standard, ip, or test")
    rows = api.list_work_rows(root, validate_identity=False)
    all_ids = {row["id"] for row in rows}
    paths: dict[str, Path] = {}
    duplicate_ids = set()
    candidates = [path for path, _ in api.work_paths(root)]
    for path in candidates:
        if path.name in paths:
            duplicate_ids.add(path.name)
        paths[path.name] = path
    state = api.identity_state(root)
    aliases = state["aliases"]
    video_rows = [row for row in rows if row["workflow"] == VIDEO]
    selected = set(only_ids) if only_ids is not None else {row["id"] for row in video_rows}
    unknown = selected - {row["id"] for row in video_rows}
    if unknown:
        raise MigrationError("Unknown retained video Work: " + ", ".join(sorted(unknown)))
    targets = []
    blockers = [f"Duplicate physical Work ID: {item}" for item in sorted(duplicate_ids & selected)]
    try:
        api.work_successor.validate(rows, state, api)
    except api.HarnessError as exc:
        blockers.append(str(exc))
    used_numbers = {series: int(value) for series, value in state["series_highwater"].items()}
    for key in state["series_aliases"]:
        series, separator, number = key.rpartition(":")
        if separator and number.isdigit():
            used_numbers[series] = max(used_numbers.get(series, 0), int(number))
    occupied = {}
    conflicts = {}
    for row in rows:
        if row["workflow"] != VIDEO or row.get("purpose") == "test" or not row.get("series_number"):
            continue
        key = (row.get("series"), int(row["series_number"]))
        if (key in occupied and occupied[key] != row["id"]
                and f"{key[0]}:{key[1]}" not in state["successions"]):
            conflicts.setdefault(key[0], []).append(f"Series number conflict: {key}: {occupied[key]}, {row['id']}")
        occupied[key] = row["id"]
        used_numbers[key[0]] = max(used_numbers.get(key[0], 0), key[1])
    video_rows.sort(key=lambda row: (api.work_id_number(row["id"], VIDEO) or 10**18, row["id"]))
    pending_by_series = {}
    for row in video_rows:
        old_id = row["id"]
        old_path = paths[old_id]
        metadata = api.read_frontmatter(old_path / "WORK.md")
        purpose = purposes.get(old_id, metadata.get("purpose"))
        series = metadata.get("series")
        if old_id not in selected:
            if purpose != "test" and series and not metadata.get("series_number"):
                pending_by_series.setdefault(series, old_id)
            continue
        number = api.work_id_number(old_id, VIDEO)
        issues = []
        if series in pending_by_series and purpose != "test":
            issues.append(f"Earlier unselected Work in series must migrate first: {pending_by_series[series]}")
        issues.extend(conflicts.get(series, []))
        if number is None:
            issues.append("Unparseable legacy video ID; manual identity decision required")
        if metadata.get("id") != old_id:
            issues.append(f"WORK.md id differs from directory: {metadata.get('id')!r}")
        if old_id in aliases:
            issues.append(f"Physical Work ID collides with alias: {old_id}")
        old_title = str(metadata.get("title", ""))
        heading_match = re.match(r"\s*# ([^\r\n]*)", api.document_body(old_path / "WORK.md"))
        heading = heading_match.group(1) if heading_match else None
        match = re.fullmatch(r"(\d{3,})-(.+)", old_title)
        if old_id in overrides:
            new_title = overrides[old_id].strip()
        elif match and number is not None and int(match.group(1)) == number:
            new_title = match.group(2).strip()
        else:
            new_title = old_title.strip()
            if match:
                issues.append("Title number does not match old Work ID; supply title override")
        if not new_title or any(char in new_title for char in "\r\n"):
            issues.append("Semantic title must be one non-empty line")
        if heading is None:
            issues.append("WORK.md H1 is missing; repair it before migration")
        elif heading != old_title and old_id not in overrides:
            issues.append("WORK.md H1 differs from metadata title; supply title override")
        canonical = bool(re.fullmatch(r"work-hyperframes_video-\d{3,}-.+", old_id))
        new_id = old_id if canonical or number is None else f"work-{VIDEO}-{number:03d}-{api.work_slug(new_title)}"
        if new_id != old_id and (new_id in all_ids or new_id in aliases):
            issues.append(f"Target ID or alias already exists: {new_id}")
        if new_id != old_id and any(old_id in record["chain"] for record in state["successions"].values()):
            issues.append("Succession history identities are immutable; do not rerun legacy identity migration")
        new_path = old_path.with_name(new_id)
        if new_id != old_id and (new_path.exists() or new_path.is_symlink()):
            issues.append(f"Target path already exists: {new_path}")
        if purpose not in {"standard", "ip", "test"}:
            issues.append("Legacy video purpose missing or invalid; supply purpose override")
        assigned = metadata.get("series_number")
        if purpose != "test":
            if not series:
                issues.append("Production video Work has no series")
            elif not assigned:
                assigned = used_numbers.get(series, 0) + 1
                used_numbers[series] = assigned
        else:
            assigned = None
        if old_id != new_id:
            issues.extend(_pending_dependencies(store, old_id))
            _, studio_blockers = _studio_records(old_path, api)
            issues.extend(studio_blockers)
        missing_accounts = [variant["id"] for variant in row["variants"]
                            if purpose != "test" and not variant.get("account")]
        unknown_revisions = [variant["id"] for variant in row["variants"]
                             if purpose != "test" and variant.get("account") and not variant.get("account_revision")]
        targets.append({"old_id": old_id, "new_id": new_id,
                        "old_path": _relative(store, old_path), "new_path": _relative(store, new_path),
                        "purpose": purpose, "series": series, "series_number": assigned,
                        "number_assigned": purpose != "test" and not metadata.get("series_number") and assigned is not None,
                        "old_title": old_title, "new_title": new_title,
                        "old_heading": heading,
                        "missing_accounts": missing_accounts, "unknown_account_revisions": unknown_revisions,
                        "variants": row["variants"], "issues": issues})
        blockers.extend(f"{old_id}: {issue}" for issue in issues)
    rename = {item["old_id"]: item["new_id"] for item in targets if item["old_id"] != item["new_id"]}
    operations = []
    for row in rows:
        path = paths[row["id"]]
        file = path / "WORK.md"
        metadata = api.read_frontmatter(file)
        changes = {}
        target = next((item for item in targets if item["old_id"] == row["id"]), None)
        if target:
            if metadata.get("purpose") != target["purpose"] and target["purpose"] in {"standard", "ip", "test"}:
                changes["purpose"] = target["purpose"]
            if target["old_id"] != target["new_id"]:
                changes["id"] = target["new_id"]
            if target["new_title"] != target["old_title"]:
                changes["title"] = target["new_title"]
            if target["new_title"] != target["old_heading"]:
                changes["_heading"] = target["new_title"]
            if target["purpose"] != "test" and metadata.get("series_number") != target["series_number"]:
                changes["series_number"] = target["series_number"]
        source = metadata.get("source_work")
        if source in rename:
            changes["source_work"] = rename[source]
        if changes:
            if any(row["id"] in record["chain"][:-1] for record in state["successions"].values()):
                blockers.append(f"Succession predecessor is read-only: {row['id']}")
            desired = _work_text(file, api, changes.copy())
            operations.append({"kind": "work", "path": _relative(store, file), "changes": changes,
                               "before": _hash(file), "after": _digest(desired)})
    pointer = api.pointer_path(root, "current-work")
    if pointer.is_file() and pointer.read_text(encoding="utf-8").strip() in rename:
        desired = rename[pointer.read_text(encoding="utf-8").strip()] + "\n"
        operations.append({"kind": "pointer", "path": _relative(store, pointer),
                           "new": desired, "before": _hash(pointer), "after": _digest(desired)})
    for context in sorted((api.runtime_root(root) / 'contexts').glob('*.json')):
        data = api.read_json(context)
        if data.get('work') in rename:
            data['work'] = rename[data['work']]
            desired = json.dumps(data, ensure_ascii=False) + '\n'
            operations.append({'kind': 'pointer', 'path': _relative(store, context),
                               'new': desired, 'before': _hash(context), 'after': _digest(desired)})
    for target in targets:
        if target["old_id"] == target["new_id"]:
            continue
        work = store / target["old_path"]
        files, _ = _studio_records(work, api)
        for file in files:
            data = api.read_json(file)
            data["work"] = target["new_id"]
            for field in ("project",):
                if isinstance(data.get(field), str) and data[field].startswith(str(work) + os.sep):
                    data[field] = str(store / target["new_path"]) + data[field][len(str(work)):]
            desired = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            operations.append({"kind": "studio", "path": _relative(store, file), "new": desired,
                               "before": _hash(file), "after": _digest(desired)})
    new_state = json.loads(json.dumps(state))
    new_state["aliases"].update(rename)
    new_state["video_highwater"] = max([int(state["video_highwater"]),
                                         *[api.work_id_number(row["id"], VIDEO) or 0 for row in video_rows]])
    for series, number in used_numbers.items():
        new_state["series_highwater"][series] = number
    identity = api.identity_path(root)
    return {"schema": 1, "store": str(store), "overrides": overrides, "purpose_overrides": purposes,
            "only_ids": sorted(selected) if only_ids is not None else None,
            "identity_before": _hash(identity), "identity_after": new_state,
            "targets": targets, "operations": operations, "blockers": blockers}


def _operation_path(store: Path, op: dict[str, Any], targets: list[dict[str, Any]]) -> Path:
    relative = op["path"]
    for target in targets:
        old = target["old_path"] + "/"
        if relative.startswith(old):
            return store / target["new_path"] / relative[len(old):]
    return store / relative


def apply_plan(root: Path, plan: dict[str, Any], api: Any) -> dict[str, Any]:
    """Apply an exact dry-run map under the naming lock; rerun to finish a journal."""
    store = _store(root, api)
    if not isinstance(plan, dict) or plan.get("store") != str(store) or plan.get("schema") != 1:
        raise MigrationError("Migration plan targets another WorkStore or schema")
    journal = api.runtime_root(root) / JOURNAL
    completed = api.runtime_root(root) / COMPLETED
    plan_hash = _digest(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    with api.naming_lock(root):
        if not journal.is_file() and completed.is_file() and api.read_json(completed).get("plan_sha256") == plan_hash:
            return {"migrated": 0, "numbered": 0, "applied": False}
        if journal.is_file():
            saved = api.read_json(journal)
            if saved != plan:
                raise MigrationError(f"Different RC2 migration is pending: {journal}")
        else:
            fresh = build_plan(root, api, title_overrides=plan.get("overrides"),
                               purpose_overrides=plan.get("purpose_overrides"), only_ids=plan.get("only_ids"))
            if fresh != plan:
                raise MigrationError("RC2 migration input changed since dry-run; regenerate the map")
            if plan["blockers"]:
                raise MigrationError("RC2 migration blocked: " + "; ".join(plan["blockers"]))
            api.write_json(journal, plan)
        targets = plan["targets"]
        for target in targets:
            if target["old_id"] == target["new_id"]:
                continue
            work = store / target["old_path"]
            if not work.is_dir():
                work = store / target["new_path"]
            _, live = _studio_records(work, api, (target["old_id"], target["new_id"]))
            blockers = _pending_dependencies(store, target["old_id"]) + live
            if blockers:
                raise MigrationError("RC2 migration has active dependencies: " + "; ".join(blockers))
        for op in plan["operations"]:
            new_path = _operation_path(store, op, targets)
            path = new_path if new_path.is_file() else store / op["path"]
            if _hash(path) not in (op["before"], op["after"]):
                raise MigrationError(f"RC2 reference changed during migration: {path}")
        identity = api.identity_path(root)
        desired = json.dumps(plan["identity_after"], ensure_ascii=False, indent=2) + "\n"
        if _hash(identity) not in (plan["identity_before"], _digest(desired)):
            raise MigrationError(f"RC2 identity changed during migration: {identity}")
        for target in targets:
            old, new = store / target["old_path"], store / target["new_path"]
            if old != new:
                if old.is_dir() and not new.exists() and not new.is_symlink():
                    os.replace(old, new)
                elif not new.is_dir() or old.exists():
                    raise MigrationError(f"Ambiguous RC2 directory state: {old}, {new}")
        for op in plan["operations"]:
            path = _operation_path(store, op, targets)
            current = _hash(path)
            if current == op["after"]:
                continue
            if current != op["before"]:
                raise MigrationError(f"RC2 reference changed during migration: {path}")
            if op["kind"] == "work":
                content = _work_text(path, api, op["changes"].copy())
            else:
                content = op["new"]
            if _digest(content) != op["after"]:
                raise MigrationError(f"RC2 rewrite mismatch: {path}")
            api.atomic_write(path, content)
        if _hash(identity) != _digest(desired):
            if _hash(identity) != plan["identity_before"]:
                raise MigrationError(f"RC2 identity changed during migration: {identity}")
            api.atomic_write(identity, desired)
        api.write_json(completed, {"plan_sha256": plan_hash})
        journal.unlink()
    return {"migrated": sum(item["old_id"] != item["new_id"] for item in targets),
            "numbered": sum(item["number_assigned"] for item in targets), "applied": True}
