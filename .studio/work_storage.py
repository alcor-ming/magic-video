"""On-demand Work capacity and tiered reclamation."""
import csv
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from storage import scoped_path, process_stopped, StorageError


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


def tree_stats(path: Path, *, png_only: bool = False) -> dict:
    """One lstat traversal; links/reparse points invalidate the entire item."""
    totals = dict(bytes=0, files=0, max_mtime_ns=0)

    def visit(entry):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('contains link')
        if stat.S_ISDIR(info.st_mode):
            totals['max_mtime_ns'] = max(totals['max_mtime_ns'], info.st_mtime_ns)
            for child in sorted(entry.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            if not png_only or entry.suffix.lower() == '.png':
                totals['bytes'] += info.st_size
                totals['files'] += 1
                totals['max_mtime_ns'] = max(totals['max_mtime_ns'], info.st_mtime_ns)
        else:
            raise ValueError('not a regular file or directory')

    visit(path)
    return totals


def published(root: Path, work: Path) -> bool:
    config = json.loads(os.environ.get('HYPERFRAMES_AI_RESOLVED_CONFIG', '{}'))
    path = Path(config.get('export_root', root / 'exports')) / 'publish-log.csv'
    if not path.is_file():
        return False
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return any(row.get('Work') == work.name and (row.get('链接', '').strip() or row.get('状态') == '已发')
                   for row in csv.DictReader(handle))


def studio_records(api, variant: Path) -> list:
    return [(path, api.read_json(scoped_path(variant, path.relative_to(variant).as_posix())))
            for path in sorted((variant / '.runtime').glob('studio-*.json'))]


def protected_previews(api, variant: Path) -> set:
    protected = set()

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('accepted_preview', 'accepted_visual_plan', 'source_preview') and isinstance(child, str):
                    protected.add(child)
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for path in [variant / 'variant.yaml', variant / 'final/manifest.json',
                 *sorted((variant / 'final/history').glob('*/manifest.json'))]:
        path = scoped_path(variant, path.relative_to(variant).as_posix())
        if path.is_file():
            collect(api.read_json(path))
    previews = sorted((variant / 'previews').glob('*'))
    # Registration numbers each purpose separately (draft-vNNN, plan-vNNN).
    latest = {}
    for path in previews:
        match = re.fullmatch(r'(.+)-v(\d+)', path.name)
        if match and (match[1] not in latest or int(match[2]) > latest[match[1]][0]):
            latest[match[1]] = (int(match[2]), path.name)
    protected.update(name for _, name in latest.values())
    for _, record in studio_records(api, variant):
        if record.get('pid') is not None and not process_stopped(record['pid']) and record.get('target'):
            protected.add(record['target'])
    pending = list(protected)
    while pending:
        name = pending.pop()
        path = scoped_path(variant, 'previews/' + api.validate_id(name, 'preview'))
        if (path / 'preview.md').is_file():
            scoped_path(variant, (path / 'preview.md').relative_to(variant).as_posix())
            source = api.preview_metadata(path).get('source_plan')
            if source and source not in protected:
                protected.add(source)
                pending.append(source)
    return protected


def assert_protected(work: Path, item: dict, tier: int, protected=()) -> None:
    relative = item['path']
    path = Path(relative)
    if path.is_absolute() or not path.parts or '..' in path.parts or path.as_posix() != relative:
        raise ValueError('Invalid storage item path')
    parts = path.parts
    if tier in (1, 2):
        if any(part in {'final', 'project', 'materials', 'retro', 'WORK.md'} for part in parts):
            raise ValueError('Storage item overlaps protected content: ' + relative)
        if len(parts) >= 4 and parts[0] == 'variants' and parts[2] == 'previews' and parts[3] in protected:
            raise ValueError('Storage item overlaps protected preview: ' + relative)
    else:
        keep = [Path('WORK.md'), Path('.runtime/archive.json'), Path('.runtime/storage.json')]
        if len(parts) >= 2 and parts[0] == 'variants':
            keep += [Path('variants') / parts[1] / name for name in ('variant.yaml', 'retro')]
        if path == Path('variants') or any(path == target or path.is_relative_to(target) or target.is_relative_to(path)
                                           for target in keep):
            raise ValueError('Storage item overlaps tier 3 retained content: ' + relative)



def tier_items(api, root: Path, work: Path, tier: int, *, variant: Path | None = None,
               completed: Path | None = None) -> tuple[list, list]:
    items, excluded = [], []
    scoped_path(work.parent, work.name)

    def exclude(path, reason, variant_id=None):
        excluded.append(dict(work=work.name, variant=variant_id, path=path.relative_to(work).as_posix(), reason=reason))

    def add(path, kind, reason, variant_id=None, protected=()):
        relative = path.relative_to(work).as_posix()
        try:
            # Check ancestors too: traversal of the item alone cannot detect a linked parent.
            for parent in (path, *path.parents):
                if parent == work:
                    break
                info = parent.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('contains link')
            stats = tree_stats(path, png_only=kind == 'critic_frames')
        except (OSError, ValueError) as error:
            exclude(path, str(error), variant_id)
            return
        item = dict(work=work.name, variant=variant_id, kind=kind, path=relative, **stats, reason=reason)
        assert_protected(work, item, tier, protected)
        if kind != 'critic_frames' or stats['files']:
            items.append(item)

    if tier == 3:
        archive = scoped_path(work, '.runtime/archive.json')
        if not archive.is_file() or api.read_json(archive).get('outcome') != 'abandoned' or published(root, work):
            raise ValueError('Tier 3 requires an abandoned, unpublished Work')
        for path in sorted(work.iterdir()):
            if path.name == 'WORK.md':
                continue
            if path.name == '.runtime' and not path.is_symlink():
                for child in sorted(path.iterdir()):
                    if child.name not in ('archive.json', 'storage.json'):
                        add(child, 'abandoned', 'abandoned Work')
            elif path.name == 'variants' and not path.is_symlink():
                for child in sorted(path.iterdir()):
                    if child.is_dir() and not child.is_symlink():
                        for entry in sorted(child.iterdir()):
                            if entry.name not in ('variant.yaml', 'retro'):
                                add(entry, 'abandoned', 'abandoned Work', child.name)
                    else:
                        add(child, 'abandoned', 'abandoned Work', child.name)
            else:
                add(path, 'abandoned', 'abandoned Work')
        return items, excluded
    if tier == 2 and not published(root, work):
        exclude(work, 'not published')
        return items, excluded
    for current in [variant] if variant is not None else api.variant_paths(work):
        if current.is_symlink():
            exclude(current, 'contains link', current.name)
            continue
        scoped_path(work, current.relative_to(work).as_posix())
        runtime = scoped_path(current, '.runtime')
        protected = protected_previews(api, current)
        records = studio_records(api, current)
        if tier == 2:
            for preview in sorted((current / 'previews').glob('*')):
                if preview.name in protected:
                    exclude(preview, 'protected preview', current.name)
                elif preview.is_dir():
                    add(preview, 'unaccepted_preview', 'published, unaccepted preview', current.name, protected)
            ledger_path = scoped_path(current, 'critic/ledger.json')
            if ledger_path.is_file():
                for entry in api.read_json(ledger_path)['rounds']:
                    package = current / 'critic' / api.validate_id(entry['package'], 'critic package')
                    if 'verdict' in entry:
                        add(package, 'critic_frames', 'recorded critic verdict', current.name, protected)
                    else:
                        exclude(package, 'critic verdict not recorded', current.name)
            continue
        receipt = scoped_path(current, '.runtime/finalize.json')
        if (not receipt.is_file() or api.read_json(receipt).get('state') != 'complete'
                or not scoped_path(current, 'final/final.mp4').is_file()
                or not scoped_path(current, 'final/manifest.json').is_file()
                or (runtime / 'final-promotion/prepared.json').exists()
                or (runtime / 'appearance-rebind.json').exists()):
            exclude(current, 'final lifecycle not complete or recovery pending', current.name)
            continue
        try:
            candidates = api.reclaim_final_candidates(current, completed, apply=False)
        except StorageError as error:
            if 'link' not in str(error).lower():
                raise
            exclude(runtime / 'final-candidates.json', 'contains link', current.name)
            candidates = []
        for name in candidates:
            add(runtime / name, 'final_candidate', 'eligible registered Final candidate', current.name, protected)
        reviews = []
        for review in sorted(runtime.glob('studio-review-*')):
            if not re.fullmatch(r'studio-review-[0-9a-fA-F]{32}', review.name) or not review.is_dir():
                continue
            related = [record for _, record in records if record.get('project')
                       and Path(record['project']).is_relative_to(review)]
            if (api.browser_profile_in_use(review) or api.browser_profile_in_use(review / '.runtime/studio-browser')
                    or any(record.get('pid') is not None and not process_stopped(record['pid']) for record in related)):
                exclude(review, 'Studio or browser in use', current.name)
                continue
            before = len(items)
            add(review, 'studio_review', 'stopped Studio review copy', current.name, protected)
            if len(items) > before:
                reviews.append(review)
        caches, reasons, errors = api.reclaim_browser_caches(current, apply=False)
        for cache in caches:
            path = Path(cache['path'])
            if not any(path.is_relative_to(review) for review in reviews):
                add(path, 'browser_cache', 'eligible private browser cache', current.name, protected)
        for reason in reasons + errors:
            exclude(runtime, 'contains link' if 'link' in reason.lower() else reason, current.name)
        alive = any(record.get('pid') is not None and not process_stopped(record['pid']) for _, record in records)
        for run in sorted((runtime / 'diagnose-frames').glob('*')):
            if run.is_dir():
                if alive:
                    exclude(run, 'Studio in use', current.name)
                else:
                    add(run, 'diagnose_frames', 'stopped diagnostic run', current.name, protected)
        residue = runtime / 'final-promotion'
        if residue.exists() and not (residue / 'prepared.json').exists():
            add(residue, 'promotion_residue', 'no prepared promotion', current.name, protected)
    return items, excluded


def plan_digest(items: list) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def remove_item(api, work: Path, item: dict, *, records=()) -> None:
    """Caller holds naming_lock and has just revalidated eligibility and stats."""
    path = scoped_path(work, item['path'])
    if item['kind'] == 'critic_frames':
        variant = scoped_path(work, 'variants/' + api.validate_id(item['variant'], 'variant'))
        ledger_path = scoped_path(variant, 'critic/ledger.json')
        ledger = api.read_json(ledger_path)
        for entry in ledger['rounds']:
            if entry['package'] == path.name:
                entry['frames_reclaimed_at'] = api.now()
        # Mark first so an interrupted deletion never makes retro reuse missing evidence.
        api.write_json(ledger_path, ledger)
        for frame in sorted(path.rglob('*')):
            if frame.is_file() and frame.suffix.lower() == '.png':
                scoped_path(work, frame.relative_to(work).as_posix()).unlink()
    else:
        record_paths = [record_path for record_path, record in records
                        if item['kind'] == 'studio_review' and record_path.name != 'studio-current.json'
                        and record.get('project') and Path(record['project']).is_relative_to(path)]
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        for record_path in record_paths:
            scoped_path(work, record_path.relative_to(work).as_posix()).unlink()
        if item['kind'] == 'final_candidate':
            registry_path = work / 'variants' / item['variant'] / '.runtime/final-candidates.json'
            registry = api.read_json(registry_path)
            for entry in registry['entries']:
                if registry_path.parent / entry['path'] == path:
                    entry.update(state='removed', removed_at=api.now())
            api.write_json(registry_path, registry)


def apply_items(api, root: Path, work: Path, tier: int, items: list | None, *,
                variant: Path | None = None, completed: Path | None = None) -> dict:
    """Under naming_lock, enumerate each Variant once, then recheck only the item being deleted."""
    if items is None and variant is None:
        raise ValueError('Automatic reclamation requires a Variant')
    automatic = items is None
    scopes = [None] if tier == 3 else [variant.name] if variant is not None else sorted({item['variant'] for item in items})
    eligible, excluded, errors, record_paths = {}, {}, {}, {}
    for identity in scopes:
        try:
            current_variant = None if identity is None else scoped_path(work, 'variants/' + api.validate_id(identity, 'variant'))
            selected, omitted = tier_items(api, root, work, tier, variant=current_variant, completed=completed)
            eligible.update(((entry['variant'], entry['kind'], entry['path']), entry) for entry in selected)
            excluded.update(((entry['variant'], entry['path']), entry['reason']) for entry in omitted)
            if current_variant is not None and any(entry['kind'] in {'studio_review', 'diagnose_frames', 'browser_cache'}
                                                   for entry in selected):
                records = studio_records(api, current_variant)
                all_records = [record_path for record_path, _ in records]
                review_records = {}
                runtime = current_variant / '.runtime'
                for record_path, record in records:
                    if record.get('project'):
                        project = Path(record['project'])
                        if project.is_relative_to(runtime) and project != runtime:
                            review = runtime / project.relative_to(runtime).parts[0]
                            review_records.setdefault(review, []).append(record_path)
                for entry in selected:
                    if entry['kind'] == 'studio_review':
                        record_paths[entry['path']] = review_records.get(work / entry['path'], [])
                    elif entry['kind'] in {'diagnose_frames', 'browser_cache'}:
                        record_paths[entry['path']] = all_records
        except (OSError, ValueError, api.HarnessError) as error:
            if variant is not None:
                raise
            errors[identity] = str(error)
    if automatic:
        items = list(eligible.values())
    removed, skipped = [], []
    for item in items:
        assert_protected(work, item, tier)
        try:
            path = scoped_path(work, item['path'])
            identity = None if tier == 3 else item['variant']
            current = eligible.get((item['variant'], item['kind'], item['path']))
            if identity in errors:
                reason = errors[identity]
            elif current is None:
                reason = excluded.get((item['variant'], item['path']), 'no longer eligible')
            else:
                kind = item['kind']
                reason = None
                records = [(record_path, api.read_json(scoped_path(work, record_path.relative_to(work).as_posix())))
                           for record_path in record_paths.get(item['path'], ()) if record_path.is_file()]
                if kind == 'studio_review':
                    related = [record for _, record in records if record.get('project')
                               and Path(record['project']).is_relative_to(path)]
                    if (api.browser_profile_in_use(path) or api.browser_profile_in_use(path / '.runtime/studio-browser')
                            or any(record.get('pid') is not None and not process_stopped(record['pid']) for record in related)):
                        reason = 'Studio or browser in use'
                elif kind == 'diagnose_frames':
                    profiles = {work / 'variants' / item['variant'] / '.runtime/studio-browser'}
                    for _, record in records:
                        if record.get('browser_profile'):
                            profiles.add(Path(record['browser_profile']))
                        if record.get('project'):
                            profiles.add(Path(record['project']).parent / '.runtime/studio-browser')
                    if any(record.get('pid') is not None and not process_stopped(record['pid']) for _, record in records):
                        reason = 'Studio in use'
                    elif any(api.browser_profile_in_use(profile) for profile in profiles):
                        reason = 'browser in use'
                elif kind == 'browser_cache':
                    profile = next(parent for parent in path.parents if parent.name == 'studio-browser')
                    if (api.browser_profile_in_use(profile) or any(('pid' in record or 'target' in record)
                            and not record.get('stopped_at') and not process_stopped(record.get('pid')) for _, record in records)):
                        reason = 'Studio or browser in use'
                elif kind == 'critic_frames':
                    ledger = api.read_json(scoped_path(work, 'variants/' + item['variant'] + '/critic/ledger.json'))
                    if not any(entry['package'] == path.name and 'verdict' in entry for entry in ledger['rounds']):
                        reason = 'critic verdict not recorded'
                elif kind == 'promotion_residue' and (path / 'prepared.json').exists():
                    reason = 'promotion recovery pending'
                if reason is not None:
                    skipped.append({**item, 'reason': reason})
                    continue
                # final_candidate membership above comes from the one reclaim_final_candidates call in tier_items.
                stats = tree_stats(path, png_only=kind == 'critic_frames')
                if any(stats[key] != item[key] for key in ('bytes', 'files', 'max_mtime_ns')):
                    reason = 'bytes/files/max_mtime_ns changed'
                else:
                    remove_item(api, work, current, records=records)
                    removed.append(current)
                    continue
        except (OSError, ValueError, api.HarnessError) as error:
            if variant is not None:
                raise
            reason = str(error)
        skipped.append({**item, 'reason': reason})
    return dict(removed=removed, skipped=skipped, bytes=sum(item['bytes'] for item in removed))
