"""Scoped snapshot dependencies and conservative owned-job cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import sys

from visual_plan import Composition, validate_dependencies


class StorageError(ValueError):
    pass


def process_stopped(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if sys.platform == "win32":
        if pid > 0xFFFFFFFF:
            return False
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE, never process mutation.
        if not handle:
            return ctypes.get_last_error() == 87  # Nonexistent PID; access-denied remains unknown.
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        pass
    return False


def scoped_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise StorageError("Expected a relative dependency path")
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise StorageError("Dependency escaped its root")
    if any(item.is_symlink() for item in (path, *path.parents) if item.is_relative_to(root)):
        raise StorageError("Linked dependencies are not allowed")
    return path


def snapshot_files(project: Path) -> tuple[str, ...] | None:
    """Explicit dynamic entries supplement the existing literal-reference parser."""
    config = project / "project-config.json"
    if not config.is_file():
        return None
    try:
        metadata = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None  # Historical snapshots did not require a structured config.
    if not isinstance(metadata, dict):
        return None
    entries = metadata.get("snapshot_dependencies")
    if entries is None:
        return None
    if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
        raise StorageError("snapshot_dependencies must be a list of local files")
    files = {"DESIGN.md", "project-config.json"}
    for entry in ("index.html", *entries):
        scoped_path(project, entry)
        files.update(validate_dependencies(project, entry=entry,
                                            check_path=lambda path: scoped_path(project, path.relative_to(project).as_posix())))
    if (project / "appearance-lock.json").exists():
        from component_harness import OPTIONAL_SNAPSHOT_ITEMS
        for name in OPTIONAL_SNAPSHOT_ITEMS:
            item = scoped_path(project, name)
            if item.is_file():
                files.add(name)
            elif item.is_dir():
                files.update(child.relative_to(project).as_posix() for child in item.rglob("*") if child.is_file())
    for name in files:
        path = scoped_path(project, name)
        if not path.is_file():
            raise StorageError(f"Missing dependency: {name}")
        if any(part in {"node_modules", ".cache", ".git"} for part in path.relative_to(project).parts):
            raise StorageError("Snapshot cannot depend on install or build caches")
        if path.suffix == ".html" and any("srcset" in attrs or "imagesrcset" in attrs
                                         for _, attrs in Composition(path.read_text(encoding="utf-8")).nodes):
            raise StorageError("Snapshot closure does not support responsive srcset; use explicit local src")
    return tuple(sorted(files))


def reclaim(runtime: Path, records: list[dict], references: set[str]) -> list[str]:
    """Caller holds the Work runtime lock; unknown or failed jobs are retained."""
    removed = []
    for record in records:
        if record.get("state") != "succeeded" or record.get("rebuildable") is not True:
            continue
        relative = record.get("path")
        path = scoped_path(runtime, relative)
        if any(path == scoped_path(runtime, ref) or scoped_path(runtime, ref).is_relative_to(path)
               or path.is_relative_to(scoped_path(runtime, ref)) for ref in references):
            continue
        pid = record.get("pid")
        if pid is not None and not process_stopped(pid):
            continue
        if path.is_dir():
            if any(child.is_symlink() for child in path.rglob("*")):
                raise StorageError("Cleanup tree contains a link")
            remove_tree(path)
        elif path.is_file():
            path.unlink()
        else:
            continue
        removed.append(relative)
    return removed


def remove_tree(path: Path) -> None:
    """Delete a reclaimable tree. Windows refuses to delete read-only entries (copies of frozen drafts)."""
    for directory, folders, files in os.walk(path):
        for name in folders + files:
            entry = os.path.join(directory, name)
            if not os.path.islink(entry):
                os.chmod(entry, stat.S_IMODE(os.lstat(entry).st_mode) | stat.S_IWRITE)
    os.chmod(path, stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IWRITE)
    shutil.rmtree(path)
