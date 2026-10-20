"""On-demand byte accounting. No content hashing, deletion or following links."""
import json
import os
from pathlib import Path
from storage import scoped_path


def measure(work: Path) -> dict:
    categories = dict(source_project=0, accepted_snapshots=0, other_previews=0, final_history=0, runtime_copies=0,
                      browser_profiles=0)
    errors, accepted = [], set()
    def failed(error):
        errors.append(str(error))
    for variant in (work / 'variants').glob('*'):
        if not variant.is_dir() or variant.is_symlink():
            continue
        records = [variant / 'variant.yaml', variant / 'final/manifest.json',
                   *(variant / 'final/history').glob('*/manifest.json')]
        for path in records:
            try:
                scoped_path(work, path.relative_to(work).as_posix())
                if not path.is_file():
                    continue
                value = json.loads(path.read_text(encoding='utf-8'))
                for key in ('accepted_preview', 'accepted_visual_plan', 'source_preview'):
                    if value.get(key):
                        accepted.add((variant.name, value[key]))
            except (OSError, ValueError, TypeError, AttributeError) as error:
                failed(error)
    for directory, folders, files in os.walk(work, followlinks=False, onerror=failed):
        parent = Path(directory)
        for name in list(folders):
            if (parent / name).is_symlink():
                errors.append(f"Linked directory not counted: {parent / name}")
                folders.remove(name)
        for name in files:
            path = parent / name
            try:
                if path.is_symlink():
                    errors.append(f"Linked file not counted: {path}")
                    continue
                parts = path.relative_to(work).parts
                category = ("browser_profiles" if "studio-browser" in parts else "runtime_copies" if ".runtime" in parts
                            else "final_history" if "final" in parts else "other_previews" if "previews" in parts else "source_project")
                if len(parts) > 4 and parts[0] == 'variants' and parts[2] == 'previews' and (parts[1], parts[3]) in accepted:
                    category = 'accepted_snapshots'
                categories[category] += path.stat().st_size
            except OSError as error:
                failed(error)
    return {"bytes": None if errors else sum(categories.values()), "categories": categories,
            "reason": "; ".join(errors) if errors else None, "errors": errors}


def tree_bytes(path: Path) -> int:
    """Bytes under one directory without following links; unreadable entries raise instead of undercounting."""
    def failed(error):
        raise error
    total = 0
    for directory, _, files in os.walk(path, followlinks=False, onerror=failed):
        for name in files:
            total += (Path(directory) / name).lstat().st_size
    return total
