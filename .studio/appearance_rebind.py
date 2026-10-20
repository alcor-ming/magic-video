"""Explicit, recoverable updates of one editable Variant's frozen appearance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import appearance
from component_harness import package_write_lock
from work_requests import safe

KNOWN_RUNTIMES = {"97fcc24496ec1fddf5e86747125bcb5afc56495f3defc0ca666f8245f06695bb",
                  "b6b0a69411f48d9f777a7e8fdf342a89e866b51d7d734d760b431ee9524908f0",
                  "9c4519762a2c926f99b9baf473fa02fcdf978443c22b252965b87c1c7e0429af",
                  "deb8ea501f19f0b5ebaf5c7a2b126f700127fc739e0a497b928cb82ddc620676",
                  "e80354186ac34db5d94a79febf4d1f4d84763f142f2b72465ff7150a0c35ff9b",
                  "51c9496479b3111f876a412cbf7133be7b7e203e517ea6d00390e92f8a622d9b",
                  "afd9b56dfc6340605385f11383d9e97d9ffd7e96e4e800d5a10daebe00891d81",
                  "77cf4869f89604a42b1e7cfa3f09fda7c4b5ad4d593f7a6aece18a3e02f29abe"}
KNOWN_BROLL_RUNTIMES = {"0682adbdfb929555e5a190dfffb2f474f20569f0c8a94d8b46c8389cfcf123b9"}
KNOWN_FIGURE_RUNTIMES = {"e962423082e665b21ffef628e1da6faa77eb99a3dd9b55c6e4b70d721eb6dfc5"}
FILES = ("ANIMATION_PLAN.md", "variant.yaml")
KNOWN_CUE_RUNTIMES = {"c5b93f0bec6b8b675d59a9fc5cc4bd14492f86144245ae907b9cae25c05b9be8"}


def journal_path(variant):
    return safe(variant, ".runtime/appearance-rebind.json")


def tree_identity(directory):
    if not directory.exists():
        return None
    entries = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_file() and path.stat().st_nlink != 1:
            raise appearance.AppearanceError("Rebind cannot copy linked project files")
        if path.is_file():
            entries[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise appearance.AppearanceError("Rebind requires regular project files")
    return appearance.digest(entries)


def sync_checks(variant, api):
    project = safe(variant, "project")
    path = safe(project, "appearance-lock.json")
    target = api.read_json(variant / "variant.yaml").get("appearance_lock")
    appearance._check_lock(target)
    frozen = api.read_json(path)
    appearance.verify(project, frozen)
    if frozen == target:
        return {"status": "unchanged"}
    if "capabilities" not in frozen or "capabilities" not in target:
        raise appearance.AppearanceError("Check sync requires capability-based appearance locks")
    expected = deepcopy(frozen)
    old_checks = frozen["capabilities"]["checks"]
    new_checks = target["capabilities"]["checks"]
    expected["capabilities"]["checks"] = new_checks
    expected["capabilities_sha256"] = appearance.digest(expected["capabilities"])
    expected["sha256"] = appearance.digest({key: value for key, value in expected.items() if key != "sha256"})
    if expected != target or not set(old_checks).issubset(new_checks):
        raise appearance.AppearanceError("Check sync only permits added checks; other frozen appearance differences require inspection")
    studio = api.studio_record(variant, "current")
    if studio.exists():
        record = api.read_json(studio)
        if not record.get("stopped_at") and not api.storage.process_stopped(record.get("pid")):
            raise appearance.AppearanceError("Stop this Variant's current Studio before syncing checks")
    if path.stat().st_nlink != 1:
        raise appearance.AppearanceError("Check sync cannot replace a linked appearance lock")
    history = safe(variant, f".runtime/appearance-history/{uuid.uuid4().hex}")
    history.mkdir(parents=True)
    shutil.copy2(path, history / "appearance-lock.json")
    api.write_json(path, target)
    return {"status": "checks-synced", "history": str(history),
            "before_sha256": frozen["sha256"], "after_sha256": target["sha256"]}


def recover(variant, api, *, sync=False):
    marker = journal_path(variant)
    if not marker.exists():
        return sync_checks(variant, api) if sync else {"status": "no-pending-rebind"}
    if sync:
        raise appearance.AppearanceError("Appearance recovery pending; run appearance recover without --sync-checks first")
    record = api.read_json(marker)
    identity = record.get("id", "")
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise appearance.AppearanceError("Invalid rebind recovery identity")
    history = safe(variant, f".runtime/appearance-history/{identity}")
    project = safe(variant, "project")
    if record.get("phase") == "committed":
        if tree_identity(project) != record["new_project"] or any(api.file_sha256(variant / name) != record["new_files"][name] for name in FILES):
            raise appearance.AppearanceError("Committed rebind changed; preserve history and inspect before recovery")
        marker.unlink()
        return {"status": "committed", "history": str(history)}
    for name in FILES:
        if api.file_sha256(variant / name) not in (record["old_files"][name], record["new_files"][name]):
            raise appearance.AppearanceError(f"Recovery would overwrite a later edit: {name}")
    current = tree_identity(project)
    if current not in (None, record["old_project"], record["new_project"]):
        raise appearance.AppearanceError("Recovery would overwrite later project edits")
    old = history / "old-project"
    if old.exists():
        if tree_identity(old) != record["old_project"]:
            raise appearance.AppearanceError("Rebind recovery backup changed")
        if project.exists():
            project.rename(history / "interrupted-project")
        old.rename(project)
    elif record["old_project"] is None and project.exists():
        project.rename(history / "interrupted-project")
    elif current != record["old_project"]:
        raise appearance.AppearanceError("Missing rebind recovery backup")
    for name in FILES:
        backup = history / name
        if api.file_sha256(backup) != record["old_files"][name]:
            raise appearance.AppearanceError("Rebind metadata backup changed")
        api.atomic_write(variant / name, backup.read_bytes().decode("utf-8"))
    marker.unlink()
    return {"status": "restored", "history": str(history)}


def rebind(root, work, variant, state, args, api):
    if journal_path(variant).exists():
        raise appearance.AppearanceError("Appearance recovery pending; run appearance recover for this Work/Variant")
    import lines
    current = state.get("appearance_lock")
    account = api.account_service(root).get("account", args.account) if args.account else state.get("account_settings", {})
    overrides = api.appearance_options(root, args)
    modern = "capabilities" in state or "capabilities" in (current or {})
    if not modern and current and current.get("mode") != "showcase" and ("submodule" in overrides or overrides.get("mode", account.get("mode")) == "showcase"):
        raise appearance.AppearanceError("Showcase mode requires a new Variant with an explicit submodule")
    if not modern and current and current.get("mode") == "showcase":
        if overrides.get("submodule", current["submodule"]) != current["submodule"] or overrides.get("mode", "showcase") != "showcase":
            raise appearance.AppearanceError("Showcase submodule and mode are frozen; create a new Variant")
        overrides["submodule"] = current["submodule"]
        overrides.setdefault("mode", "showcase")
    effective_mode = overrides.get("mode", account.get("mode") if args.account else (current or {}).get("mode", account.get("mode")))
    if not modern and getattr(args, "captions", None) is not None:
        appearance.check_mode(effective_mode)
    legacy_motion = None
    if current and not args.account:
        choices = {**current["selection"], **{key: current[key] for key in ("mode", "ratio", "width", "height", "fps", "seed") if key in current},
                   "parameters": deepcopy(current["overrides"]["explicit"])}
        if not modern and "mode" in overrides and overrides["mode"] != current.get("mode") and "captions" not in overrides:
            choices["captions"] = overrides["mode"] == "explainer"
        if choices["ratio"] not in appearance.RATIOS:
            choices["ratio"] = "source"
        if "ratio" in overrides and overrides["ratio"] != choices["ratio"]:
            for dimension in ("width", "height"):
                if dimension not in overrides:
                    choices.pop(dimension, None)
        # Frozen account Motion slots carry forward unchanged; a rebind may only switch them off.
        legacy_motion = choices.pop("motion")
        if "motion" in overrides:
            if not isinstance(overrides["motion"], dict):
                raise appearance.AppearanceError("Motion selections must be an object")
            if any(value is not None for value in overrides["motion"].values()):
                raise appearance.AppearanceError(appearance.MOTION_RETIRED)
            legacy_motion = {**legacy_motion, **overrides.pop("motion")}
        if "parameters" in overrides:
            if not isinstance(overrides["parameters"], dict):
                raise appearance.AppearanceError("Appearance parameters must be an object")
            parameters = choices["parameters"]
            for scope, values in overrides["parameters"].items():
                if not isinstance(values, dict):
                    raise appearance.AppearanceError("Appearance parameter scopes must be objects")
                if scope == "motion":
                    for slot, settings in values.items():
                        if not isinstance(settings, dict):
                            raise appearance.AppearanceError("Motion parameters must be objects")
                        parameters.setdefault("motion", {}).setdefault(slot, {}).update(settings)
                else:
                    parameters.setdefault(scope, {}).update(values)
            overrides["parameters"] = parameters
        choices.update(overrides)
        overrides = choices
    if "capabilities" in state or current and "capabilities" in current:
        overrides["capabilities"] = lines.capabilities(state)
        overrides.pop("mode", None)
        overrides.setdefault("captions", state.get("captions", False))
    if (current or {}).get('card_fonts'):
        overrides['card_fonts'] = current['card_fonts']
    lock = appearance.resolve(root, account, overrides, legacy_motion=legacy_motion)
    project = safe(variant, "project")
    runtime_updates = {}
    for name, known in (("appearance.js", KNOWN_RUNTIMES), ("cues.js", KNOWN_CUE_RUNTIMES), ("broll.js", KNOWN_BROLL_RUNTIMES), ("figures.js", KNOWN_FIGURE_RUNTIMES)):
        runtime = safe(project, "runtime/" + name)
        source = Path(appearance.__file__).parent / "runtime" / name
        if runtime.exists() and runtime.read_bytes() != source.read_bytes():
            if api.file_sha256(runtime) not in known:
                raise appearance.AppearanceError("Unknown or user-modified appearance runtime; refusing overwrite")
            runtime_updates[name] = source
    upgrade = bool(runtime_updates)
    if upgrade and not args.upgrade_runtime:
        raise appearance.AppearanceError("Known old runtime requires explicit --upgrade-runtime on this editable Variant")
    if current and project.exists():
        appearance.verify(project, current)
    changes = {key: {"before": current.get(key) if current else None, "after": value}
               for key, value in lock.items() if key != "sha256" and (not current or current.get(key) != value)}
    report = {"work": work.name, "variant": variant.name, "changes": changes, "runtime_upgrade": upgrade,
              "before_sha256": current.get("sha256") if current else None, "after_sha256": lock["sha256"]}
    if not changes and not upgrade:
        return {**report, "status": "unchanged"}
    if not args.apply:
        return {**report, "status": "preview"}
    studio = api.studio_record(variant, "current")
    if studio.exists() and not api.read_json(studio).get("stopped_at"):
        process = api.read_json(studio).get("pid")
        if not api.storage.process_stopped(process):
            raise appearance.AppearanceError("Stop this Variant's current Studio before rebinding")
    if (variant / ".runtime/final-promotion/prepared.json").exists():
        raise appearance.AppearanceError("Final promotion recovery must finish before rebinding")
    old_project = tree_identity(project)
    old_files = {name: api.file_sha256(safe(variant, name)) for name in FILES}
    identity = uuid.uuid4().hex
    history = safe(variant, f".runtime/appearance-history/{identity}")
    history.mkdir(parents=True)
    candidate = history / "new-project"
    try:
        if project.exists():
            shutil.copytree(project, candidate)
        else:
            candidate.mkdir()
        for name, source in runtime_updates.items():
            shutil.copyfile(source, candidate / "runtime" / name)
        appearance.materialize(root, candidate, lock)
        for name in FILES:
            shutil.copy2(variant / name, history / name)
        new_state = {**state, "theme": lock["selection"]["theme"], "background": lock["selection"]["background"],
                     "motion": lock["selection"]["motion"], "appearance_lock": lock, **({"mode": lock["mode"]} if "mode" in lock else {}), "ratio": lock["ratio"],
                     "profile": None, "account": account.get("id", state.get("account")), "account_settings": account,
                     "account_revision": account.get("revision"), "revision": state.get("revision", 1) + 1,
                     "plan_revision": state.get("plan_revision", 1) + 1, "accepted_visual_plan": None,
                     "accepted_preview": None, "accepted_plan_revision": None, "accepted_script_revision": None,
                     "current_final": None, "status": "waiting_user", "wait_for": "plan_approval",
                     "next_action": "Review the Plan and Draft with the rebound appearance"}
        for key in ("theme_revision", "theme_settings"):
            new_state.pop(key, None)
        new_state.setdefault("appearance_history", [])
        new_state["appearance_history"] = [*new_state["appearance_history"], {"id": identity, "before_sha256": report["before_sha256"],
            "after_sha256": lock["sha256"], "at": api.now(), "accepted_visual_plan": state.get("accepted_visual_plan"),
            "accepted_preview": state.get("accepted_preview"), "current_final": state.get("current_final")}]
        plan = api.read_frontmatter(variant / "ANIMATION_PLAN.md")
        plan.update(theme=new_state["theme"], ratio=new_state["ratio"], profile=None,
                    status="draft", revision=new_state["plan_revision"])
        plan.update(api.plan_metadata(variant, new_state))
        plan.pop("visual_plan", None)
        plan_lines = (variant / "ANIMATION_PLAN.md").read_bytes().splitlines(keepends=True)
        end = next(i for i, line in enumerate(plan_lines[1:], 1) if line.strip() == b"---")
        body = b"".join(plan_lines[end + 1:]).decode("utf-8")
        body = api.plan_metadata_body(body, plan)
        newline = "\r\n" if plan_lines[0].endswith(b"\r\n") else "\n"
        contents = {"variant.yaml": json.dumps(new_state, ensure_ascii=False, indent=2) + "\n",
                    "ANIMATION_PLAN.md": "---" + newline + json.dumps(plan, ensure_ascii=False) + newline + "---" + newline + body}
        if tree_identity(project) != old_project or any(api.file_sha256(variant / name) != old_files[name] for name in FILES):
            raise appearance.AppearanceError("Variant changed during rebind preparation; retry from stable inputs")
        record = {"id": identity, "phase": "prepared", "old_project": old_project, "new_project": tree_identity(candidate),
                  "old_files": old_files, "new_files": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in contents.items()}}
        api.write_json(journal_path(variant), record)
        if project.exists():
            project.rename(history / "old-project")
        candidate.rename(project)
        for name, text in contents.items():
            api.atomic_write(variant / name, text)
        api.write_json(journal_path(variant), {**record, "phase": "committed"})
        journal_path(variant).unlink()
    except Exception:
        if journal_path(variant).exists():
            recover(variant, api)
        raise
    return {**report, "status": "rebound", "history": str(history)}


def command(root, args, api):
    if not args.work_override or not args.variant_override:
        raise appearance.AppearanceError("Appearance updates require explicit --work and --variant")
    with api.naming_lock(root):
        work, _ = api.selected_work(root, args)
        api.require_workflow(work, "hyperframes_video")
        variant, state = api.selected_variant(root, work, args)
        with package_write_lock(safe(variant, ".runtime/component-install.lock")):
            result = recover(variant, api, sync=args.sync_checks) if args.appearance_command == "recover" else rebind(root, work, variant, state, args, api)
    print(json.dumps(result, ensure_ascii=False, indent=2))
