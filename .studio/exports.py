"""Copy successful delivery files onto the export shelf, laid out the way uploads happen.

``<export_root>/<account>/<series>/<series>_E012_<account>_v01.mp4`` with the cover under the same name. A version
is one upload package: when the video or the cover changes, every file of the episode moves to the next version
together. Delivered names never change and nothing is overwritten or deleted; the previous version moves, under
its own name, into ``_superseded/`` beside the current one. ``publish-log.csv`` lists one row per episode for
finding and tracking uploads; the tool keeps its descriptive columns current and never touches the user's status,
date, link, notes or any column the user adds. ``.exports.json`` is the machine index with every copy's hash.
"""
from pathlib import Path
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile

from component_harness import package_write_lock
from storage import scoped_path
from windows_runtime import validate_review_path


NO_ACCOUNT = '_no-account'
NO_SERIES = '_no-series'
SUPERSEDED = '_superseded'
INDEX = '.exports.json'
LOG = 'publish-log.csv'
TOOL_COLUMNS = ('编号', '账号', '系列', '期数', '版本', '视频', '封面', 'Work', 'Variant')
USER_COLUMNS = ('状态', '发布日期', '链接', '备注')
PENDING, REPUBLISH, PUBLISHED = '待发', '待重发', '已发'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def component(value):
    if (not isinstance(value, str) or value in {'', '.', '..'}
            or re.search(r'[\x00-\x1f/\\:<>"|?*]', value) or value.endswith((' ', '.'))
            or re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', value)):
        raise ValueError('Invalid export directory component')
    return value


def shelf_target(work_name, variant_name, *, series=None, number=None, account=None, label=None):
    """(account folder, series folder, file stem); the stem names the episode when the Work has a series number.

    ``label`` is the account id, plus the Variant when one Work has two Variants of that account.
    """
    work_name, variant_name = component(work_name), component(variant_name)
    account_folder = component(account) if account is not None else NO_ACCOUNT
    series_folder = component(series) if series is not None else NO_SERIES
    if series is None or number is None:
        return account_folder, series_folder, f'{work_name}_{variant_name}'
    if type(number) is not int or number < 1:
        raise ValueError('Series exports need a positive series number')
    return account_folder, series_folder, f'{series}_E{number:03d}_{component(label or account or variant_name)}'


def _empty_index():
    return {'schema_version': 3, 'episodes': {}}


def _read_index(path):
    if not path.exists():
        return _empty_index()
    if path.stat().st_nlink != 1:
        raise ValueError('Linked export index')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 3 or not isinstance(data.get('episodes'), dict):
        raise ValueError('Invalid export index')
    return data


def _write_atomic(folder, path, text, encoding='utf-8'):
    # An interrupted write must not reserve a shared temporary name forever.
    stream = tempfile.NamedTemporaryFile(mode='w', encoding=encoding, dir=folder, newline='',
                                         prefix='.exports-', suffix='.pending', delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_verified(source, target, digest):
    """Copy through ``.partial`` and link into place; an existing target must already hold these bytes."""
    temporary = target.with_name(target.name + '.partial')
    if target.exists():
        if (temporary.exists() and target.stat().st_nlink == 2
                and os.path.samefile(temporary, target) and sha256(target) == digest):
            temporary.unlink()
        if target.stat().st_nlink != 1 or sha256(target) != digest:
            raise ValueError('Existing export differs; refusing to overwrite')
        return
    if temporary.exists():
        if temporary.stat().st_nlink != 1 or sha256(temporary) != digest:
            raise ValueError('Incomplete export copy requires inspection')
    else:
        try:
            with source.open('rb') as incoming, temporary.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    if sha256(temporary) != digest:
        temporary.unlink()
        raise ValueError('Source changed while copying export')
    # Lock excludes another publisher; exclusive linking also protects existing user files.
    try:
        os.link(temporary, target)
    except FileExistsError:
        raise ValueError('Export destination appeared; refusing to overwrite') from None
    temporary.unlink()


def _retire(root, item):
    """Move a superseded copy, under its own name, into ``_superseded/`` beside it."""
    current = scoped_path(root, item['file'])
    kept = scoped_path(root, str(Path(item['file']).parent / SUPERSEDED / Path(item['file']).name))
    if kept.exists():
        if kept.stat().st_nlink != 1 or sha256(kept) != item['sha256']:
            raise ValueError('Superseded export differs; refusing to overwrite')
        if current.exists():
            raise ValueError('Superseded export exists twice; inspect: ' + item['file'])
    elif current.exists():
        if current.stat().st_nlink != 1 or sha256(current) != item['sha256']:
            raise ValueError('Existing export differs; refusing to overwrite')
        kept.parent.mkdir(exist_ok=True)
        os.rename(current, kept)
    else:
        raise ValueError('Current export is missing; restore it before exporting again: ' + item['file'])
    item.update(file=kept.relative_to(root).as_posix(), current=False)


def _sync_log(root, data):
    """Rewrite the tool columns of ``publish-log.csv`` from the index, keeping every user-owned cell."""
    path = scoped_path(root, LOG)
    rows, extra = {}, []
    if path.exists():
        if path.stat().st_nlink != 1:
            raise ValueError('Linked publish log')
        reader = csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig')))
        extra = [name for name in reader.fieldnames or () if name and name not in TOOL_COLUMNS + USER_COLUMNS]
        rows = {row['编号']: row for row in reader if row.get('编号')}
    output = []
    for key, episode in data['episodes'].items():
        current = {item['role']: item['file'] if item.get('indexed') else Path(item['file']).name
                   for item in episode['files'] if item['current']}
        row = rows.pop(episode['stem'], {})
        status = row.get('状态') or PENDING
        if row.get('版本') not in (None, '', str(episode['version'])) and status == PUBLISHED:
            status = REPUBLISH
        row.update({'编号': episode['stem'], '账号': episode['account_name'], '系列': episode['series_name'],
                    '期数': episode['number'] or '', '版本': episode['version'], '视频': current.get('video', ''),
                    '封面': current.get('cover', ''), 'Work': episode['work'], 'Variant': episode['variant'],
                    '状态': status})
        output.append(row)
    output.extend(rows.values())  # rows the tool does not know stay as the user left them
    output.sort(key=lambda row: (row.get('账号') or '', row.get('系列') or '',
                                 int(row['期数']) if str(row.get('期数') or '').isdigit() else 0, row.get('编号') or ''))
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=[*TOOL_COLUMNS, *USER_COLUMNS, *extra], extrasaction='ignore')
    writer.writeheader()
    writer.writerows(output)
    _write_atomic(root, path, text.getvalue(), encoding='utf-8-sig')


def place(export_root, target, sources, record, mode='copy'):
    """Make ``sources`` ({role: path}) the current package of one episode; returns the receipt.

    ``target`` is (account folder, series folder, stem); ``record`` carries the Work, Variant, revision and the
    display names for the publish log.
    """
    root = Path(export_root).absolute()
    validate_review_path(root)
    account_folder, series_folder, stem = (component(part) for part in target)
    hashes = {role: sha256(path) for role, path in sources.items()}
    root.mkdir(parents=True, exist_ok=True)
    folder = scoped_path(root, f'{account_folder}/{series_folder}')
    with package_write_lock(scoped_path(root, '.export.lock')):
        index_path = scoped_path(root, INDEX)
        data = _read_index(index_path)
        key = f'{account_folder}/{series_folder}/{stem}'
        episode = data['episodes'].setdefault(key, {'stem': stem, 'version': 0, 'files': []})
        current = {item['role']: item for item in episode['files'] if item['current']}
        changed = any(current.get(role, {}).get('sha256') != hashes[role] for role in sources)
        if mode == 'index':
            folder = next(iter(sources.values())).parent
            if changed or any(not item.get('indexed') for item in current.values()):
                version = episode['version'] + int(changed)
                if changed:
                    for item in current.values():
                        item['current'] = False
                else:
                    episode['files'] = [item for item in episode['files'] if not item['current']]
                for role in sorted(sources):
                    episode['files'].append({'role': role,
                                             'file': Path(os.path.relpath(sources[role], root.parent)).as_posix(),
                                             'sha256': hashes[role], 'current': True, 'version': version,
                                             'indexed': True,
                                             **{name: record[name] for name in ('work', 'variant', 'revision')}})
                episode.update(version=version, **{name: record[name] for name in
                                                   ('work', 'variant', 'account_name', 'series_name', 'number')})
                _write_atomic(root, index_path, json.dumps(data, ensure_ascii=False, indent=2))
        elif changed:
            # Unchanged roles of the episode carry forward so one version is one complete upload package.
            carried = {role: scoped_path(root, item['file']) for role, item in current.items() if role not in sources}
            for role, path in carried.items():
                if not path.is_file() or path.stat().st_nlink != 1 or sha256(path) != current[role]['sha256']:
                    raise ValueError('Existing export differs; refusing to overwrite')
            package = {**carried, **sources}
            digests = {**{role: current[role]['sha256'] for role in carried}, **hashes}
            version = episode['version'] + 1
            folder.mkdir(parents=True, exist_ok=True)
            copies = {role: scoped_path(folder, f'{stem}_v{version:02d}{path.suffix.lower()}')
                      for role, path in package.items()}
            for role in sorted(package):
                _copy_verified(package[role], copies[role], digests[role])
            for role in sorted(current):
                _retire(root, current[role])
            for role in sorted(package):
                episode['files'].append({'role': role, 'file': copies[role].relative_to(root).as_posix(),
                                         'sha256': digests[role], 'current': True, 'version': version,
                                         **{name: record[name] for name in ('work', 'variant', 'revision')},
                                         **({'migrated': True} if record.get('migrated') else {})})
            episode.update(version=version, **{name: record[name] for name in
                                               ('work', 'variant', 'account_name', 'series_name', 'number')})
            _write_atomic(root, index_path, json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for role in sources:
                _copy_verified(sources[role], scoped_path(root, current[role]['file']), hashes[role])
        log_error = None
        try:
            _sync_log(root, data)
        except OSError as error:
            # Exported files are in place; the log is rebuilt from the index on the next export.
            log_error = f'{LOG} not updated ({error}); close it in other programs and export again'
    files = {item['role']: Path(item['file']).name for item in episode['files'] if item['current']}
    receipt = {'directory': str(folder), 'name': stem, 'version': episode['version'], 'files': files,
               'log': str(scoped_path(root, LOG)), **{name: record[name] for name in ('work', 'variant', 'revision')}}
    return {**receipt, 'log_error': log_error} if log_error else receipt


def publish(export_root, work, variant, files, *, series=None, number=None, account=None, label=None,
            series_name=None, account_name=None, revision=1, review=False, mode='copy'):
    if mode not in ('copy', 'index'):
        raise ValueError('export_mode must be copy or index')
    if review:
        raise ValueError('Review/test-work cannot publish exports')
    if type(revision) is not int or revision < 1 or not isinstance(files, dict) or not files:
        raise ValueError('Export requires a positive revision and delivery files')
    if set(files) - {'video', 'cover'}:
        raise ValueError('Unknown export media role')
    root = Path(export_root).absolute()
    for path in (root, Path(work), Path(variant)):
        validate_review_path(path)
    work, variant = Path(work).resolve(), Path(variant).resolve()
    if not variant.is_relative_to(work):
        raise ValueError('Variant must belong to Work')
    sources = {}
    for role, source in files.items():
        source = Path(source).absolute()
        if not source.is_relative_to(variant):
            raise ValueError('Export source must belong to Variant')
        source = scoped_path(variant, source.relative_to(variant).as_posix())
        if not source.is_file() or source.stat().st_nlink != 1:
            raise ValueError('Export source must be an unlinked regular file')
        if source.suffix.lower() not in ({'.mp4'} if role == 'video' else {'.png', '.jpg', '.jpeg', '.webp'}):
            raise ValueError('Unexpected export media extension')
        sources[role] = source
    target = shelf_target(work.name, variant.name, series=series, number=number, account=account, label=label)
    shelf = (root / target[0] / target[1]).resolve()
    if shelf.is_relative_to(variant) or variant.is_relative_to(shelf):
        raise ValueError('Export shelf must be separate from Variant source')
    return place(root, target, sources, {'work': work.name, 'variant': variant.name, 'revision': revision,
                                         'account_name': account_name or account or '',
                                         'series_name': series_name or series or '', 'number': number}, mode=mode)


def reindex_copies(export_root, data, legacy, works, statuses, *, delete=False):
    """Inventory shelf copies against retained Work media, deleting only verified duplicates."""
    from datetime import datetime

    root = Path(export_root).absolute()
    hashes = {}
    for work_id, work in works.items():
        hashes[work_id] = set()
        for variant in sorted(work.glob('variants/*')):
            if not variant.is_dir():
                continue
            final = scoped_path(work, f'variants/{variant.name}/final')
            media = [final / 'final.mp4', *final.glob('history/*/final.mp4')]
            package = scoped_path(final, 'package.json')
            if package.is_file():
                media.extend(scoped_path(final, item['file'])
                             for item in json.loads(package.read_text(encoding='utf-8'))['covers'])
            for path in media:
                path = scoped_path(work, path.relative_to(work).as_posix())
                if path.is_file():
                    hashes[work_id].add(sha256(path))
    candidates = {}
    for key, episode in data['episodes'].items():
        for item in episode['files']:
            if not item.get('indexed'):
                path = scoped_path(root, item['file'])
                if path.is_file():
                    candidate = candidates.setdefault(path, {'owners': set(), 'works': set(), 'items': [], 'legacy': False})
                    candidate['owners'].add(key)
                    candidate['works'].add(episode['work'])
                    candidate['items'].append(item)
    for entry in legacy:
        owners = {key for key, episode in data['episodes'].items()
                  if (episode['work'], episode['variant']) == (entry['work'], entry['variant'])}
        for role, source in entry['files'].items():
            path = scoped_path(root, source.relative_to(root).as_posix())
            if path.is_file():
                candidate = candidates.setdefault(path, {'owners': set(), 'works': set(), 'items': [], 'legacy': False})
                candidate['owners'].update(owners)
                candidate['works'].add(entry['work'])
                candidate['legacy'] = True
                # Legacy media also gets a historical entry in the central index
                # when deleted, leaving the old layout's index intact.
                for key in owners:
                    if not any(item['file'] == path.relative_to(root).as_posix()
                               for item in data['episodes'][key]['files'] if not item.get('indexed')):
                        candidate['items'].append((key, {'role': role, 'file': path.relative_to(root).as_posix(),
                            'sha256': entry['hashes'][role], 'current': False,
                            'version': data['episodes'][key]['version'], 'work': entry['work'],
                            'variant': entry['variant'], 'revision': entry['revision']}))
    copies, empty_dirs = [], set()
    for path, candidate in sorted(candidates.items()):
        digest = sha256(path)
        deletable = (all(digest in hashes.get(work_id, set()) for work_id in candidate['works'])
                     and all(statuses[key] != 'cover_mismatch' for key in candidate['owners']))
        item = {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
                'sha256': digest, 'class': 'deletable' if deletable else 'unique', 'deleted': False}
        if (delete and deletable and candidate['owners']
                and all(statuses[key] in ('already_indexed', 'converted') for key in candidate['owners'])):
            checked = scoped_path(root, item['path'])
            if sha256(checked) == digest:
                checked.unlink()
                item['deleted'] = True
                stamp = datetime.now().astimezone().isoformat(timespec='seconds')
                for record in candidate['items']:
                    if isinstance(record, tuple):
                        key, record = record
                        data['episodes'][key]['files'].append(record)
                    record['deleted_at'] = stamp
                if candidate['legacy']:
                    empty_dirs.update(parent for parent in path.parents if parent != root and parent.is_relative_to(root))
                elif path.parent.name == SUPERSEDED:
                    empty_dirs.add(path.parent)
        copies.append(item)
    for folder in sorted(empty_dirs, key=lambda path: len(path.parts), reverse=True):
        folder = scoped_path(root, folder.relative_to(root).as_posix())
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    return copies


def legacy_entries(export_root):
    """Exports written by the old ``<series>/<Work>/<Variant>/`` shelf, oldest first, for migration."""
    root = Path(export_root).absolute()
    found = []
    for index in sorted(root.glob(f'*/*/*/{INDEX}')):
        variant_dir = index.parent
        work_dir, series_dir = variant_dir.parent, variant_dir.parent.parent
        if index.is_symlink() or index.stat().st_nlink != 1:
            raise ValueError('Linked export index: ' + str(index))
        entries = json.loads(index.read_text(encoding='utf-8'))
        if not isinstance(entries, list):
            raise ValueError('Invalid legacy export index: ' + str(index))
        for entry in sorted(entries, key=lambda item: item['sequence']):
            found.append({'series': None if series_dir.name == '未分系列' else series_dir.name, 'work': work_dir.name,
                          'variant': variant_dir.name, 'revision': entry['revision'], 'sequence': entry['sequence'],
                          'files': {role: variant_dir / name for role, name in entry['files'].items()},
                          'hashes': entry['hashes']})
    return found
