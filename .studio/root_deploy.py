"""Managed-file root deployment; user content is never a package member."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

# Embedded CPython does not add this script's directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

STATE = ".studio/.runtime"
MANIFEST = f"{STATE}/deployment.json"
PENDING = f"{STATE}/deploy-pending.json"
CONFIG = f"{STATE}/local.json"
RUNTIME_LOCKS = {
    "windows-x64": "windows-runtime.lock.json",
    "darwin-arm64": "darwin-runtime.lock.json",
}


def runtime_lock_path(root: Path, *, target: str | None = None) -> Path:
    if target is None:
        release = root / ".release.json"
        if release.is_file():
            target = json.loads(release.read_text(encoding="utf-8")).get("target")
        else:
            # Development roots on WSL/Linux continue using the Windows lock.
            target = "darwin-arm64" if sys.platform == "darwin" else "windows-x64"
    if target not in RUNTIME_LOCKS:
        raise ValueError("Unsupported package identity")
    return root / RUNTIME_LOCKS[target]


def read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key: {key}")
            value[key] = item
        return value
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe(root, name):
    def linked(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 1024)

    for parent in (root, *root.parents):
        if linked(parent):
            raise ValueError(f"Links are not allowed: {parent}")
    parts = PurePosixPath(name).parts
    if not parts or name != "/".join(parts) or any(p in {".", ".."} or any(ord(c) < 32 or c in ':\\<>"|?*' for c in p) or p.endswith((" ", ".")) for p in parts) or name.startswith("/"):
        raise ValueError(f"Unsafe managed path: {name}")
    if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])", p.split(".")[0]) for p in parts):
        raise ValueError(f"Reserved Windows path: {name}")
    path = root
    for part in parts:
        path /= part
        if linked(path):
            raise ValueError(f"Links are not allowed: {path}")
    return path


def managed(files):
    if not isinstance(files, dict):
        raise ValueError("Manifest files must be an object")
    seen = set()
    for name, value in files.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Manifest entries must be strings")
        key = name.casefold()
        if key in seen or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"Invalid or case-colliding manifest entry: {name}")
        seen.add(key)
        if key.split("/")[0] in {"exports", "works", "assets", "asset-library", "sample-library", "known-defects", "retro-summary", "content-summary", "requests", "review", ".runtime", ".harness"} or key == STATE or key.startswith(STATE + "/"):
            raise ValueError(f"Package claims user/runtime content: {name}")


def verify_package(root):
    manifest = read(safe(root, ".release.json"))
    if manifest.get("target") not in RUNTIME_LOCKS or manifest.get("channel") not in {"candidate", "local", "stable"}:
        raise ValueError("Unsupported package identity")
    if not re.fullmatch(r"(?:harness-\d{4}\.\d{2}\.\d+|(?:candidate|local)-[A-Za-z0-9][A-Za-z0-9._-]*)", manifest.get("release", "")) or manifest.get("layout") != "root-v1":
        raise ValueError("Package requires a valid release identity and root-v1 layout")
    files = manifest["files"]
    managed(files)
    kind = manifest.get("package_kind", "full")
    if kind not in {"full", "tools"}:
        raise ValueError("Unsupported package kind")
    if kind == "tools":
        required = manifest["runtime_files"]
        managed(required)
        if not required or any(not name.startswith("runtime/") for name in required):
            raise ValueError("Tools package requires exact runtime files")
        if any(name.startswith("runtime/") for name in files):
            raise ValueError("Tools package cannot contain runtime files")
        if not isinstance(manifest.get("runtime_lock_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["runtime_lock_sha256"]) or files.get(runtime_lock_path(root, target=manifest["target"]).name) != manifest["runtime_lock_sha256"]:
            raise ValueError("Tools package runtime lock mismatch")
    if ".release.json" in {name.casefold() for name in files}:
        raise ValueError("Package cannot claim its own .release.json")
    for name, value in files.items():
        if digest(safe(root, name)) != value:
            raise ValueError(f"Package hash mismatch: {name}")
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        safe(root, name)
        if path.is_file() and name not in files and name != ".release.json":
            raise ValueError(f"Unmanifested package file: {name}")
    return manifest


def verify_root(root, *, retained=None, expected=None):
    if safe(root, PENDING).exists():
        raise ValueError("Interrupted deployment; run recover before work")
    state = read(safe(root, MANIFEST))
    managed(state["files"])
    if expected is not None:
        managed(expected)
    for name, value in state["files"].items():
        path = safe(root, name)
        if retained is not None and name not in retained:
            continue
        current = digest(path)
        if current != value and (expected is None or current != expected.get(name)):
            raise ValueError(f"Locally modified managed file: {name}")
    return state


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    if temp.exists() or temp.is_symlink():
        raise ValueError(f"Temporary path conflict: {temp}")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def inside(path, parent):
    return path == parent or parent in path.parents


def replace_file(source, destination, data=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".deploy-" + uuid.uuid4().hex)
    try:
        if source is not None:
            shutil.copy2(source, temporary)
        else:
            temporary.write_bytes(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def validate_config(root, config, candidate):
    for key in ("work_root", "asset_root"):
        if not Path(config[key]).is_absolute():
            raise ValueError(f"{key} must be absolute")
    work = Path(config["work_root"])
    if not (work / "works").is_dir():
        raise ValueError("Missing WorkStore directory: works")
    if candidate or config.get("review"):
        if config.get("review") is not True or not config.get("review_protected_roots"):
            raise ValueError("Candidate requires review=true and explicit review_protected_roots")
        paths = [work, Path(config["asset_root"]), Path(config["asset_review_root"])] + [Path(p) for p in config.get("asset_source_roots", [])]
        if not config.get("asset_source_roots"):
            raise ValueError("Candidate requires independent asset_source_roots")
        asset_review = Path(config["asset_review_root"])
        if Path(config["asset_root"]) != asset_review / "store" or any(not inside(Path(p), asset_review / "sources") for p in config["asset_source_roots"]):
            raise ValueError("Review assets require isolated asset_review_root/store and sources")
        for path in paths:
            if not path.is_absolute() or not inside(path, root) or not path.is_dir():
                raise ValueError(f"Review content must be an existing directory inside root: {path}")
            if path != root:
                safe(root, path.relative_to(root).as_posix())
            for item in path.rglob("*"):
                safe(root, item.relative_to(root).as_posix())
                if item.is_file() and item.stat().st_nlink > 1:
                    raise ValueError(f"Review requires real copies, not hardlinks: {item}")
            for protected in config["review_protected_roots"]:
                protected = Path(protected)
                if not protected.is_absolute() or inside(path.resolve(), protected.resolve()) or inside(protected.resolve(), path.resolve()):
                    raise ValueError(f"Review path overlaps protected production root: {path}")


def idle(root, *, target='windows-x64'):
    if target not in RUNTIME_LOCKS:
        raise ValueError("Unsupported package identity")
    if target == 'darwin-arm64':
        result = subprocess.run(['ps', '-axo', 'pid=,command='],
                                capture_output=True, encoding='utf-8', check=True)
        prefix = str(root).rstrip('/') + '/'
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            pid_text, command = line.strip().split(None, 1)
            pid = int(pid_text)
            executable = command.split(None, 1)[0].rsplit('/', 1)[-1]
            matched = re.fullmatch(
                r'(python|pythonw|node|ffmpeg|ffprobe|chrome|chrome-headless-shell|esbuild)(\.exe)?',
                executable, re.IGNORECASE)
            if matched and pid != os.getpid() and prefix in command:
                raise ValueError(f'Root process {pid} is active; close preview/render before updating')
        return
    if os.name != "nt":
        return
    script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|node|ffmpeg|ffprobe|chrome|chrome-headless-shell|esbuild)(\\.exe)?$' } | Select-Object ProcessId,CommandLine,ExecutablePath | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-Command", script], capture_output=True, encoding="utf-8", check=True)
    processes = json.loads(result.stdout or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    for process in processes:
        location = ((process.get("CommandLine") or "") + " " + (process.get("ExecutablePath") or "")).replace("/", "\\").casefold()
        # A host's bare working-directory argument does not consume installed tools.
        prefix = str(root).replace("/", "\\").casefold().rstrip("\\") + "\\"
        if process["ProcessId"] != os.getpid() and prefix in location:
            raise ValueError(f"Root process {process['ProcessId']} is active; close preview/render before updating")


def restore(root, transaction, check_only=False):
    config = safe(root, CONFIG)
    if not config.exists() and CONFIG not in transaction["before"]:
        raise ValueError("Recovery would discard a local configuration deletion")
    if config.exists() and digest(config) != transaction["config_sha256"]:
        raise ValueError("Recovery would discard a local configuration edit")
    backup = safe(root, transaction["backup"])
    for name, old_hash in transaction["before"].items():
        destination = safe(root, name)
        current = digest(destination) if destination.is_file() else None
        if current not in {old_hash, transaction["after"].get(name)}:
            raise ValueError(f"Recovery would discard a local edit: {name}")
        if old_hash is not None and digest(safe(backup, name)) != old_hash:
            raise ValueError(f"Corrupt recovery backup: {name}")
    if check_only:
        return
    for name, old_hash in transaction["before"].items():
        destination = safe(root, name)
        if old_hash is None:
            destination.unlink(missing_ok=True)
        else:
            replace_file(safe(backup, name), destination)
    safe(root, PENDING).unlink(missing_ok=True)


def prune_backups(root, keep=1):
    """Under command_lock; only completed, owned backups beyond the rollback chain."""
    if type(keep) is not int or keep < 1:
        raise ValueError("Keep at least one rollback backup")
    state = verify_root(root)
    protected = set()
    name = state.get("backup")
    for _ in range(keep):
        if not name:
            break
        backup = safe(root, name)
        protected.add(name)
        prior = safe(backup, MANIFEST)
        transaction = read(safe(backup, "transaction.json"))
        expected = transaction["before"].get(MANIFEST)
        if (digest(prior) if prior.is_file() else None) != expected:
            raise ValueError("Rollback chain is damaged; retain all backups")
        name = read(prior).get("backup") if prior.exists() else None
    parent = safe(root, f"{STATE}/deploy-backups")
    removed, retained = [], []
    if not parent.exists():
        return {"removed": removed, "retained": retained}
    for backup in sorted(parent.iterdir()):
        relative = backup.relative_to(root).as_posix()
        if relative in protected:
            continue
        try:
            safe(root, relative)
            if not re.fullmatch(r"[0-9a-f]{32}", backup.name):
                raise ValueError("Unknown backup")
            transaction = read(backup / "transaction.json")
            receipt = read(backup / "completed.json")
            if not isinstance(transaction, dict) or not isinstance(transaction.get("before"), dict):
                raise ValueError("Unknown backup transaction")
            if transaction.get("retention") != "managed-v1" or transaction["backup"] != relative or receipt != {"transaction_sha256": digest(backup / "transaction.json")}:
                raise ValueError("Unowned or incomplete backup")
            expected = {name: value for name, value in transaction["before"].items() if value is not None}
            expected.update({"transaction.json": digest(backup / "transaction.json"), "completed.json": digest(backup / "completed.json")})
            # Never recursively delete unknown contents or follow junctions.
            for path in backup.rglob("*"):
                name = path.relative_to(backup).as_posix()
                safe(backup, name)
                if path.is_file() and (name not in expected or digest(path) != expected[name]):
                    raise ValueError("Modified backup")
                if path.is_dir() and not any(item.startswith(name + "/") for item in expected):
                    raise ValueError("Unknown backup directory")
            if any(digest(safe(backup, name)) != value for name, value in expected.items()):
                raise ValueError("Incomplete backup")
            shutil.rmtree(backup)
            removed.append(relative)
        except (ValueError, OSError, KeyError, TypeError) as error:
            retained.append({"path": relative, "reason": str(error)})
    return {"removed": removed, "retained": retained}


def design_root(config):
    value = config.get("design_root")
    return Path(value) if isinstance(value, str) else Path(config["work_root"]) / "asset-library" / "designs"


def card_retirements(config, manifest):
    """User-root copies of cards this package now ships; refuse unless byte-identical to the package."""
    cards = ((manifest.get("personal_source") or {}).get("cards") or {}).get("ids", [])
    base = design_root(config)
    plan = []
    for card in cards:
        directory = base / card
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir() or getattr(directory.lstat(), "st_file_attributes", 0) & 1024:
            raise ValueError(f"User card path is not a plain directory: {directory}")
        prefix = f".studio/designs/{card}/"
        shipped = {name[len(prefix):]: value for name, value in manifest["files"].items() if name.startswith(prefix)}
        local = {}
        for path in directory.rglob("*"):
            relative = path.relative_to(directory).as_posix()
            if relative.split("/")[0] in {"study", ".git"}:
                continue
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 1024:
                raise ValueError(f"Links are not allowed in user card: {path}")
            if path.is_file():
                local[relative] = digest(path)
        differences = sorted(name for name in shipped.keys() | local.keys() if shipped.get(name) != local.get(name))
        if differences:
            raise ValueError(f"design_root/{card} differs from the deployed card; import it into the card repository "
                             f"or move it away first: {', '.join(differences[:10])}"
                             + (f" (+{len(differences) - 10} more)" if len(differences) > 10 else ""))
        plan.append((card, directory))
    return plan


def retire_cards(plan):
    """Move verified duplicates out of design_root so the catalog sees only the managed copy."""
    retired, failed = [], []
    for card, directory in plan:
        parent = directory.parent.parent / ("designs-retired-" + time.strftime("%Y%m%d"))
        target = parent / card
        suffix = 1
        while target.exists():
            suffix += 1
            target = parent / f"{card}-{suffix}"
        try:
            parent.mkdir(parents=True, exist_ok=True)
            os.replace(directory, target)
            retired.append({"card": card, "from": str(directory), "to": str(target)})
        except OSError as error:
            failed.append({"card": card, "from": str(directory), "error": str(error)})
    return {"retired": retired, "failed": failed}


def preflight(root, config_path=None, *, retained=None, expected=None, recover_pending=False):
    root = Path(root).absolute()
    safe(root.parent, root.name)
    recovered = False
    if safe(root, PENDING).exists():
        if not recover_pending:
            raise ValueError('Interrupted deployment; run recover')
        recover(root)
        recovered = True
    from windows_runtime import command_lock
    with command_lock(root):
        release = safe(root, '.release.json')
        idle(root, target=read(release).get('target') if release.exists() else 'windows-x64')
        prior = verify_root(root, retained=retained, expected=expected) if safe(root, MANIFEST).exists() else {'files': {}}
        config_file = safe(root, CONFIG)
        if not config_file.exists() and not config_path:
            raise ValueError('Initial deployment requires explicit local configuration')
        config = read(config_file if config_file.exists() else config_path)
        if config_file.exists() and config_path and read(config_path) != config:
            raise ValueError('Deployment cannot overwrite existing local configuration')
        validate_config(root, config, False)
        if 'acceptance_protected_roots' in config:
            from windows_runtime import validate_acceptance_root
            validate_acceptance_root(root, config, {'channel': 'local'})
        if retained is not None:
            for name in retained:
                path = safe(root, name)
                # Bytes already identical to the proposed file are adopted; anything else stays the user's.
                if path.exists() and name not in prior['files'] and not (
                        expected is not None and path.is_file() and digest(path) == expected.get(name)):
                    raise ValueError('Unmanaged file conflict: ' + name)
    return {'status': 'ready', 'recovered': recovered, 'managed_count': len(prior['files'])}


def deploy(package, root, config_path, keep=1):
    started = time.monotonic()
    if type(keep) is not int or keep < 1:
        raise ValueError("Keep at least one rollback backup")
    package = package.resolve()
    root = root.absolute()
    if inside(package, root) or inside(root, package):
        raise ValueError("Package and deployment root must be independent")
    safe(root.parent, root.name)
    manifest = verify_package(package)
    root.mkdir(parents=True, exist_ok=True)
    from windows_runtime import command_lock
    with command_lock(root):
        idle(root, target=manifest['target'])
        if safe(root, PENDING).exists():
            raise ValueError("Interrupted deployment; run recover")
        retained = set(manifest["files"]) | {".release.json"}
        if manifest.get("package_kind") == "tools":
            # Tools-only updates continue managing the installed runtime unchanged.
            retained.update(name for name in read(safe(root, MANIFEST))["files"] if name.startswith("runtime/"))
        prior = verify_root(root, retained=retained, expected=manifest['files']) if safe(root, MANIFEST).exists() else {"files": {}}
        config_file = safe(root, CONFIG)
        config = read(config_file if config_file.exists() else config_path)
        if config_file.exists() and config_path and read(config_path) != config:
            raise ValueError("Deployment cannot overwrite existing local configuration")
        validate_config(root, config, manifest["channel"] == "candidate")
        if 'acceptance_protected_roots' in config:
            from windows_runtime import validate_acceptance_root
            validate_acceptance_root(root, config, manifest)
        retirements = card_retirements(config, manifest)
        files = dict(manifest["files"])
        if manifest.get("package_kind") == "tools":
            required = manifest["runtime_files"]
            installed = {name: value for name, value in prior["files"].items() if name.startswith("runtime/")}
            if installed != required or prior["files"].get(runtime_lock_path(root, target=manifest["target"]).name) != manifest["runtime_lock_sha256"]:
                raise ValueError("Installed runtime differs; deploy a full package")
            files.update(required)
        files[".release.json"] = digest(package / ".release.json")
        for name in files:
            path = safe(root, name)
            if path.exists() and name not in prior["files"] and not (path.is_file() and digest(path) == files[name]):
                raise ValueError(f"Unmanaged file conflict: {name}")
        if files == prior['files'] and config_file.exists():
            return dict(prior, status='unchanged', changed_count=0, removed_count=0,
                        backup_bytes=0, written_bytes=0, elapsed_seconds=time.monotonic() - started,
                        cleanup={'unchanged': True}, user_cards=retire_cards(retirements))
        changed = {name for name, value in files.items() if prior["files"].get(name) != value}
        writes = {name: safe(package, name) for name in changed}
        extras = {}
        if not config_file.exists():
            extras[CONFIG] = (json.dumps(config, indent=2) + "\n").encode()
        if config.get("review"):
            marker = Path(config["work_root"]) / ".runtime/review.json"
            if not marker.exists():
                extras[marker.relative_to(root).as_posix()] = (json.dumps({"mode": "review", "review_id": marker.parent.parent.name, "ready": True}) + "\n").encode()
        retired = set(prior["files"]) - set(files)
        skill_roots = {"/".join(name.split("/")[:3]) for name in retired if name.startswith(".agents/skills/")}
        for skill in skill_roots:
            if any(name.startswith(skill + "/") for name in files):
                continue
            for path in safe(root, skill).rglob("*"):
                relative = path.relative_to(root).as_posix()
                safe(root, relative)
                if path.is_file() and relative not in prior["files"]:
                    raise ValueError(f"Unmanaged retired Skill content: {relative}; relocate explicitly before updating")
        preserved = []
        for name in sorted(retired):
            path = safe(root, name)
            if path.exists() and not path.is_file():
                raise ValueError(f"Retired managed path is not a regular file: {name}")
            if path.is_file() and digest(path) != prior["files"][name]:
                target = f"{STATE}/retired-files/{uuid.uuid4().hex}.bin"
                if safe(root, target).exists():
                    raise ValueError(f"Retirement preservation conflict: {target}")
                data = path.read_bytes()
                extras[target] = data
                preserved.append({"original": name, "preserved": target,
                                  "sha256": hashlib.sha256(data).hexdigest()})
        names = retired | changed | set(extras) | {MANIFEST}
        backup_name = f"{STATE}/deploy-backups/{uuid.uuid4().hex}"
        backup = safe(root, backup_name)
        before = {}
        for name in sorted(names):
            path = safe(root, name)
            before[name] = digest(path) if path.is_file() else None
            if path.exists():
                target = safe(backup, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        state = {"release": manifest["release"], "files": files, "backup": backup_name,
                 "retired_preserved": prior.get("retired_preserved", []) + preserved}
        extras[MANIFEST] = (json.dumps(state, indent=2) + "\n").encode()
        after = dict(files)
        after.update({name: hashlib.sha256(data).hexdigest() for name, data in extras.items()})
        transaction = {"backup": backup_name, "before": before, "after": after,
                       "retention": "managed-v1", "retired_preserved": preserved,
                       "preexisting_changes": [name for name in before if name in prior['files']
                                               and before[name] != prior['files'][name]],
                       "config_sha256": digest(config_file) if config_file.exists() else after[CONFIG]}
        write_json(backup / "transaction.json", transaction)
        write_json(safe(root, PENDING), transaction)
        try:
            for name in sorted(names - {MANIFEST}):
                target = safe(root, name)
                if name in writes or name in extras:
                    replace_file(writes.get(name), target, extras.get(name))
                else:
                    target.unlink(missing_ok=True)
            write_json(safe(root, MANIFEST), state)
            safe(root, PENDING).unlink()
            verify_root(root)
        except BaseException:
            if not safe(root, PENDING).exists():
                write_json(safe(root, PENDING), transaction)
            restore(root, transaction)
            raise
        # Only after the managed copy is complete; a rollback leaves retired cards where reported.
        result = dict(state, user_cards=retire_cards(retirements), changed_count=len(changed), removed_count=len(set(prior["files"]) - set(files)),
                      elapsed_seconds=time.monotonic() - started,
                      written_bytes=sum(path.stat().st_size for path in writes.values()) + sum(len(data) for data in extras.values()),
                      backup_bytes=sum(safe(backup, name).stat().st_size for name, value in before.items() if value is not None))
        try:
            write_json(backup / "completed.json", {"transaction_sha256": digest(backup / "transaction.json")})
            result["cleanup"] = prune_backups(root, keep)
        except (ValueError, OSError, KeyError, TypeError) as error:
            result["cleanup"] = {"deferred": str(error)}
        return result


def recover(root, rollback=False):
    if inside(Path(__file__).resolve(), root.resolve()):
        raise ValueError("Run recovery/rollback from an unpacked package outside the deployed root")
    from windows_runtime import command_lock
    with command_lock(root):
        release = safe(root, '.release.json')
        if rollback:
            idle(root, target=read(release).get('target'))
            state = verify_root(root)
            transaction = read(safe(root, state["backup"]) / "transaction.json")
            restore(root, transaction, check_only=True)
            write_json(safe(root, PENDING), transaction)
        else:
            transaction = read(safe(root, PENDING))
            old_release = safe(safe(root, transaction['backup']), '.release.json')
            if old_release.exists():
                release = old_release
            idle(root, target=read(release).get('target') if release.exists() else 'windows-x64')
        restore(root, transaction)
    modifications = sorted(set(transaction.get('preexisting_changes', []))
                           | {item["original"] for item in transaction.get("retired_preserved", [])})
    return {"restored": True, "restored_modified_files": modifications,
            "integrity": "restored_with_local_modifications" if modifications else "restored",
            "note": "Original local edits restored; verify-root remains strict. Review edits before using this release." if modifications else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-root", "status", "preflight", "deploy", "rollback", "recover"))
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--keep", type=int, default=1)
    parser.add_argument('--retained', type=Path, help='JSON list of proposed managed paths for preflight')
    parser.add_argument('--expected', type=Path, help='Proposed file hashes; accept only already-identical managed bytes')
    parser.add_argument('--recover-once', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = verify_package(args.package)
        elif args.root is None:
            raise ValueError("--root is required")
        elif args.command in {"verify-root", "status"}:
            result = verify_root(args.root.absolute())
        elif args.command == "deploy":
            result = deploy(args.package, args.root, args.config, args.keep)
        elif args.command == 'preflight':
            retained = read(args.retained) if args.retained else None
            if retained is not None and (not isinstance(retained, list) or any(not isinstance(name, str) for name in retained)):
                raise ValueError('Retained paths must be a JSON string list')
            result = preflight(args.root, args.config, retained=retained,
                               expected=read(args.expected) if args.expected else None, recover_pending=args.recover_once)
        else:
            result = recover(args.root.absolute(), args.command == "rollback")
        if "files" in result:
            result = {**{key: value for key, value in result.items() if key != "files"},
                      "root": str((args.root or args.package).absolute()), "managed_count": len(result["files"])}
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"root deployment: {error}\n")


if __name__ == "__main__":
    main()
