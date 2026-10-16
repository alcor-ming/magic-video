"""Local visual memories and revision-frozen reference evidence; no provider calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import lines
from storage import scoped_path

SAMPLE_DEFAULTS = {'samples.max_references': 3, 'samples.frames_per_reference': 6}
STATES = ('有效', '已巩固', '已退役')
PROBLEM_FIELDS = ('现象', 'Scene', '时间', '发现阶段', '返工代价', '归因层', '去向', '已知缺陷 ID')
EXCELLENT_FIELDS = ('条目', '留存粒度', '分类', 'Scene', '理由', '去向', '机制 ID', '手写重复')
ENUMS = {
    '发现阶段': ('Plan', 'Draft 诊断', 'critic', '用户审查', 'Final 后'),
    '返工代价': ('单 Scene', '多片段', '重做 Draft', '重置 Work'),
    '归因层': ('制作执行', '规则', '诊断', '资产能力', 'critic', '用户审查遗漏'),
    '去向': ('作品修复', '规则提案', '诊断提案', 'Asset Brief', '已知缺陷条目', '仅本片'),
    '留存粒度': ('整片样片', '样片段', '组件或动作', '做法'),
    '分类': ('积木', '动作配方或规则', '内容资产', '仅属于本片'),
    '手写重复': ('是', '否'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w·.-]+', value) or value in ('.', '..'):
        raise ValueError('Invalid memory ID')
    return value


def line_id(state):
    return (lines.frozen(state) or lines.select(state))['id']


def library(root, kind):
    return scoped_path(root, 'sample-library' if kind == 'sample' else 'known-defects')


def index_path(root, kind, line):
    if line not in lines.catalogue('lines')['lines']:
        raise ValueError('Unknown product line: ' + str(line))
    return scoped_path(library(root, kind), 'index/' + line.replace('/', '--') + '.json')


def entries(root, kind, line=None):
    paths = [index_path(root, kind, line)] if line else [index_path(root, kind, item) for item in lines.catalogue('lines')['lines']]
    result = []
    for path in paths:
        if path.is_file():
            rows = read(path)
            if not isinstance(rows, list):
                raise ValueError('Invalid memory index')
            result.extend(rows)
    ids = [item['id'] for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate memory ID')
    return result


def get(root, kind, item_id):
    identity(item_id)
    found = [item for item in entries(root, kind) if item['id'] == item_id]
    if not found:
        raise ValueError('Unknown memory: ' + item_id)
    return found[0]


def verify_frames(base, frames):
    if not frames:
        raise ValueError('Memory has no evidence frames')
    for frame in frames:
        path = scoped_path(base, frame['path'])
        if path.suffix != '.png' or not path.is_file() or path.stat().st_nlink != 1 or digest(path) != frame['sha256']:
            raise ValueError('Memory evidence changed: ' + frame['path'])


def store_entry(root, kind, record, source, frames):
    identity(record['id'])
    if any(item['id'] == record['id'] for item in entries(root, kind)):
        raise ValueError('Memory ID already exists')
    base = library(root, kind)
    key = hashlib.sha256(record['id'].encode()).hexdigest()
    destination = scoped_path(base, 'evidence/' + key)
    if destination.exists():
        raise ValueError('Memory evidence destination already exists')
    verify_frames(source, frames)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'frames'
        stage.mkdir()
        copied = []
        for number, frame in enumerate(frames):
            name = f'{number:04d}.png'
            shutil.copyfile(scoped_path(source, frame['path']), stage / name)
            copied.append({**frame, 'path': f'evidence/{key}/{name}'})
        # Validate copied bytes before making the entry discoverable.
        for frame in copied:
            if digest(stage / Path(frame['path']).name) != frame['sha256']:
                raise ValueError('Evidence changed during copying')
        stage.rename(destination)
        record = {**record, 'status': '有效', 'frames': copied, 'thumbnail': copied[0]['path']}
        path = index_path(root, kind, record['line'])
        try:
            write(path, [*(read(path) if path.is_file() else []), record])
        except Exception:
            shutil.rmtree(destination)
            raise
    return record


def change_status(root, kind, item_id, status, target):
    item = get(root, kind, item_id)
    if status not in STATES or not isinstance(target, str) or not target.strip():
        raise ValueError('Status requires a reason or consolidation target')
    if status == '已巩固' and not re.fullmatch(r'(mechanism|asset|rule):\S+', target):
        raise ValueError('Consolidation target must be mechanism:ID, asset:ref or rule:location')
    path = index_path(root, kind, item['line'])
    rows = read(path)
    for row in rows:
        if row['id'] == item_id:
            row.update(status=status, into=target)
    write(path, rows)
    return get(root, kind, item_id)


def references(text):
    # The optional showcase concept row uses the same syntax as the Brief row.
    match = re.search(r'^\*\*参考机制[：:]\*\*\s*([^\n]*)', text, re.M)
    return [value for value in re.split(r'[,，、\s]+', match[1].strip() if match else '') if value]


def resolve(root, text, line, effective, *, card=None):
    compatible = {line}
    if card is not None:
        compatible.update([card.get('mode'), *card.get('compatibility', {}).get('supersedes', [])])
    seeds = {item['id']: item for item in lines.catalogue('mechanisms')['mechanisms']}
    samples = {item['id']: item for item in entries(root, 'sample')}
    refs, findings, selected, seed_items = references(text), [], [], []
    if line.startswith('explainer') and not 1 <= len(refs) <= 3:
        findings.append({'kind': 'reference_count', 'expected': '1–3'})
    seen = set()
    for raw in refs:
        cross = raw.startswith('跨线:')
        item_id = raw.removeprefix('跨线:')
        if item_id in seen:
            findings.append({'kind': 'duplicate_reference', 'id': item_id})
            continue
        seen.add(item_id)
        if item_id in samples:
            item = samples[item_id]
            if item['line'] != line and not cross:
                findings.append({'kind': 'mechanism_line_mismatch', 'id': item_id})
            if item['status'] != '有效':
                findings.append({'kind': 'sample_retired' if item['status'] == '已退役' else 'sample_consolidated',
                                 'id': item_id, 'into': item.get('into'), 'severity': 'warning'})
            version = item.get('runtime_version')
            for change in lines.catalogue('behavior-changes')['changes']:
                if line in change['lines'] and version_key(version) is not None and version_key(version) < version_key(change['version']):
                    findings.append({'kind': 'sample_predates_behavior', 'id': item_id, **change, 'severity': 'warning'})
            selected.append(item)
        elif item_id in seeds:
            item = seeds[item_id]
            if not compatible.intersection(item['lines']) and not cross:
                findings.append({'kind': 'mechanism_line_mismatch', 'id': item_id})
            seed_items.append(item)
        else:
            findings.append({'kind': 'unknown_mechanism', 'id': item_id})
    if len(selected) > effective['samples.max_references']['value']:
        findings.append({'kind': 'sample_reference_limit', 'maximum': effective['samples.max_references']['value']})
    return selected, seed_items, findings


def version_key(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value or '')
    return tuple(map(int, match.groups())) if match else None


def reference_input(text, effective):
    return {'references': references(text), 'settings': {key: effective[key] for key in SAMPLE_DEFAULTS}}


def freeze(root, variant, revision, text, state, effective):
    scoped_path(root, variant.relative_to(root).as_posix())
    destination = scoped_path(variant, f'reference-memory/{revision}')
    expected = reference_input(text, effective)
    if destination.exists():
        manifest = frozen(destination)
        if manifest['input'] != expected:
            raise ValueError('Reference inputs changed; refresh a new Plan revision')
        return digest(destination / 'references.json')
    selected, seeds, findings = resolve(root, text, line_id(state), effective, card=lines.frozen(state) or lines.select(state))
    if any(item.get('severity') != 'warning' for item in findings):
        raise ValueError(json.dumps(findings, ensure_ascii=False))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=destination.parent) as temp:
        stage = Path(temp) / 'references'
        stage.mkdir()
        records = []
        for number, item in enumerate(selected):
            verify_frames(library(root, 'sample'), item['frames'])
            frames = item['frames']
            count = min(len(frames), effective['samples.frames_per_reference']['value'])
            chosen = [frames[round(i * (len(frames) - 1) / (count - 1))] for i in range(count)] if count > 1 else frames[:1]
            copied = []
            for offset, frame in enumerate(chosen):
                name = f'{number:03d}-{offset:03d}.png'
                shutil.copyfile(scoped_path(library(root, 'sample'), frame['path']), stage / name)
                copied.append({**frame, 'path': name})
            record = {key: deepcopy(item.get(key)) for key in ('id', 'line', 'reason', 'mechanism_id', 'source', 'runtime_version', 'assets')}
            record['frames'] = copied
            verify_frames(stage, copied)
            records.append(record)
        write(stage / 'references.json', {'revision': revision, 'input': expected, 'references': records, 'seeds': seeds, 'findings': findings})
        stage.rename(destination)
    return digest(destination / 'references.json')


def frozen(directory, expected_hash=None):
    path = scoped_path(directory, 'references.json')
    if expected_hash and digest(path) != expected_hash:
        raise ValueError('Frozen reference manifest changed')
    manifest = read(path)
    for item in manifest['references']:
        verify_frames(directory, item['frames'])
    return manifest


def located(variant, revision, expected_hash):
    """The Plan revision's freeze, else the newest identical earlier freeze a revision bump left behind."""
    directory = scoped_path(variant, f'reference-memory/{revision}')
    base = directory.parent
    if directory.is_dir() or not expected_hash or not base.is_dir():
        return directory
    earlier = sorted((int(path.name) for path in base.iterdir() if path.name.isdigit() and int(path.name) < int(revision)), reverse=True)
    for number in earlier:
        candidate = scoped_path(variant, f'reference-memory/{number}')
        manifest = candidate / 'references.json'
        if manifest.is_file() and not manifest.is_symlink() and digest(manifest) == expected_hash:
            return candidate
    return directory


def carry(variant, source_revision, revision, expected_hash):
    """Re-freeze unchanged reference evidence under a CLI-owned Plan revision bump."""
    destination = scoped_path(variant, f'reference-memory/{revision}')
    if destination.exists():
        frozen(destination, expected_hash)
        return None
    source = located(variant, source_revision, expected_hash)
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=destination.parent) as temp:
        stage = Path(temp) / 'references'
        copy_frozen(source, stage, expected_hash)
        stage.rename(destination)
    return destination


def copy_frozen(source, destination, expected_hash):
    manifest = frozen(source, expected_hash)
    destination.mkdir()
    shutil.copyfile(source / 'references.json', destination / 'references.json')
    for item in manifest['references']:
        for frame in item['frames']:
            shutil.copyfile(scoped_path(source, frame['path']), scoped_path(destination, frame['path']))
    frozen(destination, expected_hash)
    return manifest


def parse_retro(text):
    sections, current, header = {'找问题': [], '找优秀': []}, None, None
    findings = []
    for raw in text.splitlines():
        if raw.startswith('## '):
            current = raw[3:].strip()
            header = None
        elif current in sections and raw.strip().startswith('|'):
            cells = [part.strip().replace('&#124;', '|') for part in re.split(r'(?<!\\)\|', raw.strip().strip('|'))]
            if all(re.fullmatch(r':?-+:?', cell) for cell in cells):
                continue
            if header is None:
                header = cells
                fields = PROBLEM_FIELDS if current == '找问题' else EXCELLENT_FIELDS
                if tuple(header) != fields:
                    findings.append({'kind': 'retro_fields', 'section': current, 'expected': fields})
                continue
            if len(cells) != len(header):
                findings.append({'kind': 'retro_row', 'section': current})
                continue
            item = dict(zip(header, cells))
            for field, value in item.items():
                if not value and field not in ('已知缺陷 ID', '机制 ID'):
                    findings.append({'kind': 'retro_missing', 'field': field})
                elif field in ENUMS and (current == '找问题' or field != '去向') and value not in ENUMS[field]:
                    findings.append({'kind': 'retro_enum', 'field': field, 'value': value})
            sections[current].append(item)
    for section, fields in (('找问题', PROBLEM_FIELDS), ('找优秀', EXCELLENT_FIELDS)):
        if not re.search(r'^## ' + section + r'\s*$', text, re.M) or '| ' + fields[0] + ' |' not in text:
            findings.append({'kind': 'retro_missing_table', 'section': section})
    return sections, findings
