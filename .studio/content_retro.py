"""Offline publication analytics. Only retrospective directories are mutable."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
import uuid

import content_adapters
import content_analysis
from storage import scoped_path
import visual_memory as memory
import work_memory

VARIABLES = ('开头写法', '第一画面', '最强素材位置', '片长', '画幅', '标题封面', '结构', '其他')
ATTRIBUTIONS = ('选题', '封面标题', '开头', '第一画面', '文案衔接', '结构位置', '画面', '声音', '推流人群', '画幅与平台', '无法判断')
DESTINATIONS = ('选题参考', 'Plan 或分镜', '画面复盘', '资产', 'Script 开头与衔接', '仅本片')
START, END = '<!-- content-generated:start -->', '<!-- content-generated:end -->'

METRIC_NAMES = {
    'average_watch_seconds': '平均播放时长（秒）', 'total_watch_seconds': '总观看时长（秒）',
    'bounce_2s': '2 秒跳出率', 'completion_5s': '5 秒完播率', 'loss_2_to_5': '2–5 秒相对流失',
    'conditional_watch_seconds': '5 秒后观众平均观看时长（秒）',
    'conditional_watch_interval': '取整区间（左闭右开，秒）', 'average_leave_point': '平均离开点',
    'cover_click_rate': '封面点击率', 'completion_rate': '完播率', 'average_watch_ratio': '平均播放占比',
}


def metric_rows(metrics):
    return [(METRIC_NAMES.get(key, key), value if value is not None else
             '未定义' if key in ('loss_2_to_5', 'conditional_watch_seconds', 'conditional_watch_interval', 'average_leave_point') else '未提供')
            for key, value in metrics.items()]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(api, path, value):
    api.atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def number(value, name):
    if isinstance(value, bool):
        raise ValueError('Invalid ' + name)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Invalid ' + name)
    return result


def duration(path):
    result = subprocess.run([os.environ.get('HYPERFRAMES_FFPROBE_PATH', 'ffprobe'), '-v', 'error',
        '-show_entries', 'format=duration', '-of', 'json', str(path)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError('ffprobe failed: ' + result.stderr.strip())
    seconds = number(json.loads(result.stdout)['format']['duration'], 'duration')
    if seconds <= 0:
        raise ValueError('Duration must be positive')
    return seconds


def publication_dir(api, variant, target):
    return scoped_path(variant, 'retro/content/' + api.validate_id(target, 'publication'))


def publication(api, variant, target):
    directory = publication_dir(api, variant, target)
    record = read(scoped_path(directory, 'publication.json'))
    if record['id'] != target or record['variant'] != variant.name or record['work'] != variant.parent.parent.name:
        raise ValueError('Publication identity mismatch')
    return directory, record


def publication_paths(api, root):
    """Enumerate only registered Work locations, including archive date buckets."""
    base = api.configured_work_root(root) or root
    works = scoped_path(base, 'works')
    candidates = [path for path, _ in api.work_paths(root)]
    for work in candidates:
        scoped_path(works, work.relative_to(works).as_posix())
        if work.name.startswith('.pending-') or not (work / 'WORK.md').is_file() or api.work_workflow(work) != 'hyperframes_video':
            continue
        for variant in api.variant_paths(work):
            scoped_path(work, variant.relative_to(work).as_posix())
            for path in sorted(scoped_path(variant, 'retro/content').glob('*/publication.json')):
                scoped_path(variant, path.relative_to(variant).as_posix())
                if not path.parent.name.startswith('.pending-'):
                    yield work, variant, path


def comparison_publication(api, root, reference, platform, account):
    parts = reference.split('/')
    if len(parts) not in (1, 3):
        raise ValueError('Comparison must be publication ID or Work/Variant/publication')
    for part in parts:
        api.validate_id(part, 'comparison')
    matches = []
    for work, variant, path in publication_paths(api, root):
        if reference not in (path.parent.name, '/'.join((work.name, variant.name, path.parent.name))):
            continue
        _, pub = publication(api, variant, path.parent.name)
        if pub['platform'] == platform and pub['account'] == account:
            matches.append((variant, path.parent, pub))
    if len(matches) != 1:
        raise ValueError('Comparison missing or ambiguous within platform/account; use Work/Variant/publication')
    return matches[0]


def source(api, variant, final, draft):
    if final:
        manifest = read(scoped_path(variant, 'final/manifest.json'))
        if api.file_sha256(scoped_path(variant, 'final/final.mp4')) != manifest['final_sha256']:
            raise ValueError('Final hash changed')
        draft = manifest['source_preview']
    scoped_path(variant, 'previews/' + api.validate_id(draft, 'preview'))
    preview, metadata = api.checked_preview(variant, draft)
    return preview, {'type': 'Final' if final else 'Draft' if draft.startswith('draft-') else '预览',
                     'id': draft, 'snapshot_sha256': metadata['snapshot_sha256'],
                     'kind': metadata.get('kind', 'executable'),
                     **({'final_sha256': manifest['final_sha256']} if final else {})}


def timings(value, seconds, script, *, explicit=False):
    # One documented JSON format; section maps may wrap rows as sections.
    global_characters = value.get('characters', []) if isinstance(value, dict) else []
    rows = value.get('sections', value.get('timings', [])) if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError('Timings must be a list or {sections, characters}')
    anchors = set(re.findall(r'<!--\s*(P\d+)\s*-->', script))
    result = []
    for row in rows:
        anchor = row.get('anchor', row.get('anchor_id'))
        scene = row.get('scene', row.get('scene_id'))
        start, end = number(row['start'], 'start'), number(row['end'], 'end')
        if anchor not in anchors or not isinstance(scene, str) or not scene.strip():
            raise ValueError('Unknown Script Anchor or missing Scene')
        if not 0 <= start < end <= seconds + .001:
            raise ValueError('Timing out of duration bounds')
        chars = row.get('characters', [c for c in global_characters if start <= c['start'] < end])
        checked = []
        for char in chars:
            cs, ce = number(char['start'], 'character start'), number(char['end'], 'character end')
            text = char.get('char', char.get('text'))
            if not isinstance(text, str) or not start <= cs < ce <= end + .001:
                raise ValueError('Invalid character timing')
            checked.append({'char': text, 'start': cs, 'end': ce})
        result.append({'scene': scene, 'anchor': anchor, 'start': start, 'end': end,
                       'characters': sorted(checked, key=lambda c: c['start'])})
    result.sort(key=lambda row: row['start'])
    if any(a['end'] > b['start'] for a, b in zip(result, result[1:])):
        raise ValueError('Overlapping timing intervals')
    if explicit and (not result or abs(result[-1]['end'] - seconds) > 1):
        raise ValueError('Timing endpoint differs from duration by more than 1 second')
    return result


def frozen_context(preview, seconds, explicit):
    script = scoped_path(preview, 'SCRIPT.md').read_text(encoding='utf-8')
    # Never consult live Variant inputs or arbitrary engineering scripts.
    for relative in ('section_map.json', 'source-snapshot/section_map.json'):
        path = scoped_path(preview, relative)
        if path.is_file():
            return timings(read(path), seconds, script), relative, memory.digest(path)
    if explicit:
        return timings(read(explicit), seconds, script, explicit=True), 'explicit', memory.digest(explicit)
    return [], '未对齐', None


def variables(args):
    if args.no_variable:
        if args.variable or args.compare:
            raise ValueError('--no-variable cannot be combined with variables or comparison')
        return [{'variable': '无', 'value': '无', 'compare': None}]
    if not args.variable:
        raise ValueError('本期实验变量必填；没有改动请使用 --no-variable')
    rows = []
    for item in args.variable:
        key, sep, value = item.partition('=')
        name, _, description = key.partition(':')
        if not sep or name not in VARIABLES or not value.strip() or (name == '其他' and not description.strip()):
            raise ValueError('Invalid experiment variable; 其他 requires 其他:说明=取值')
        if name != '其他' and description:
            raise ValueError('Only 其他 accepts a description')
        rows.append({'variable': name, 'description': description, 'value': value.strip(), 'compare': args.compare})
    return rows


def link(api, root, args):
    work, variant, state = work_memory.context(api, root, args)
    preview, origin = source(api, variant, args.final, args.draft)
    file = Path(args.file).resolve(strict=True)
    seconds, file_hash = duration(file), api.file_sha256(file)
    account = state.get('account') or args.account
    if not isinstance(account, str) or not account.strip():
        raise ValueError('Unbound Variant requires --account')
    if state.get('account') and args.account and args.account != state['account']:
        raise ValueError('Account differs from Variant binding')
    published = datetime.fromisoformat(args.published_at.replace('Z', '+00:00')).isoformat()
    for name in ('platform', 'title', 'ratio'):
        if not getattr(args, name).strip():
            raise ValueError('Missing ' + name)
    experiments = variables(args)
    if args.compare:
        other_variant, _, control = comparison_publication(api, root, args.compare, args.platform, account)
        if other_variant == variant and control['id'] == args.publication_id:
            raise ValueError('Publication cannot compare to itself')
    table, timing_source, timing_hash = frozen_context(preview, seconds, Path(args.timings) if args.timings else None)
    record = {'id': args.publication_id, 'work': work.name, 'variant': variant.name,
              'platform': args.platform, 'account': account, 'file': str(file), 'file_sha256': file_hash,
              'duration': seconds, 'source': origin, 'title': args.title, 'cover_text': args.cover_text,
              'published_at': published, 'ratio': args.ratio, 'line': memory.line_id(state),
              'variables': experiments, 'timings': table, 'timing_source': timing_source,
              'timing_sha256': timing_hash, 'updated_at': api.now(), 'history': []}
    directory = publication_dir(api, variant, args.publication_id)
    with api.naming_lock(root):
        source(api, variant, args.final, args.draft)
        if directory.exists():
            old = read(scoped_path(directory, 'publication.json'))
            identity = ('file_sha256', 'duration', 'source', 'timings', 'timing_sha256', 'platform', 'account', 'published_at')
            if any(old[k] != record[k] for k in identity):
                raise ValueError('Publication identity changed; use a new publication ID')
            record['history'] = [*old.get('history', []), {'changed_at': api.now(), 'previous': {k: v for k,v in old.items() if k != 'history'}}]
            write(api, scoped_path(directory, 'publication.json'), record)
        else:
            directory.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory.parent) as temp:
                stage = Path(temp) / 'publication'; stage.mkdir()
                write(api, stage / 'publication.json', record)
                stage.rename(directory)
    return {'path': str(directory / 'publication.json'), **record}


def imports(api, directory):
    pub = read(scoped_path(directory, 'publication.json'))
    allowed = {digest(pub)}
    history = pub.get('history', [])
    for index, revision in enumerate(history):
        allowed.add(digest({**revision['previous'], 'history': history[:index]}))
    result = []
    for path in sorted(scoped_path(directory, 'imports').glob('*/import.json')):
        scoped_path(directory, path.relative_to(directory).as_posix())
        if path.parent.name.startswith('.pending-'):
            continue
        meta = read(path)
        if meta['publication'] != pub['id'] or meta['publication_sha256'] not in allowed or meta['id'] != path.parent.name:
            raise ValueError('Import belongs to another publication or revision')
        normalized_path = scoped_path(path.parent, 'normalized.json')
        if memory.digest(normalized_path) != meta['normalized_sha256']:
            raise ValueError('Normalized import changed')
        for item in meta['files']:
            if memory.digest(scoped_path(path.parent, item['path'])) != item['sha256']:
                raise ValueError('Imported original changed')
        result.append({**meta, 'normalized': read(normalized_path)})
    return sorted(result, key=lambda row: (row['imported_at'], row['id']))


def import_data(api, root, args):
    _, variant, _ = work_memory.context(api, root, args)
    directory, pub = publication(api, variant, args.publication_id)
    cutoff = date.fromisoformat(args.cutoff)
    days = (cutoff - datetime.fromisoformat(pub['published_at']).date()).days
    if days < 0:
        raise ValueError('Cutoff precedes publication')
    files = [Path(p).resolve(strict=True) for p in (args.file or [])]
    if args.dir:
        files += sorted(Path(args.dir).resolve(strict=True).glob('*.xlsx'))
    if len(files) != 5 or len(set(files)) != 5:
        raise ValueError('Exactly five distinct xlsx exports are required')
    parent = scoped_path(directory, 'imports'); parent.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=parent) as temp:
        stage = Path(temp) / 'import'; stage.mkdir()
        copied, originals = [], []
        for index, file in enumerate(files):
            target = stage / f'{index+1}-{file.name}'
            sha = api.file_sha256(file)
            shutil.copy2(file, target)
            if api.file_sha256(target) != sha:
                raise ValueError('Export changed during copying')
            copied.append(target)
            originals.append({'path': target.name, 'original_name': file.name, 'sha256': sha})
        normalized = content_adapters.normalize(copied, cutoff_date=args.cutoff, imported_at=stamp)
        expected = {'attraction', 'engagement', 'audience', 'daily_plays', 'traffic'}
        if set(normalized.get('datasets', [])) != expected:
            raise ValueError('Exports must contain all five dataset types')
        segments = normalized['segments']
        if not segments or abs(max(s['end'] for s in segments) - pub['duration']) > 1:
            raise ValueError('Export endpoint differs from publication duration by more than 1 second')
        write(api, stage / 'normalized.json', normalized)
        iid = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '-' + uuid.uuid4().hex[:12]
        meta = {'id': iid, 'publication': pub['id'], 'publication_sha256': digest(pub),
                'imported_at': stamp, 'cutoff_date': args.cutoff, 'stage': args.stage or 'unmarked',
                'days_after_publication': days, 'normalized_sha256': memory.digest(stage / 'normalized.json'), 'files': originals}
        write(api, stage / 'import.json', meta)
        with api.naming_lock(root):
            if digest(read(scoped_path(directory, 'publication.json'))) != digest(pub):
                raise ValueError('Publication changed during import; retry')
            stage.rename(scoped_path(parent, iid))
    return meta


def evidence(api, variant, pub):
    preview, metadata = api.checked_preview(variant, pub['source']['id'])
    if pub['timing_source'] not in ('explicit', '未对齐'):
        if memory.digest(scoped_path(preview, pub['timing_source'])) != pub['timing_sha256']:
            raise ValueError('Frozen timing evidence changed')
    if metadata['snapshot_sha256'] != pub['source']['snapshot_sha256']:
        raise ValueError('Publication snapshot changed')
    result = []
    # Reuse only reports whose immutable binding names this exact snapshot.
    paths = []
    for relative in ('diagnose.json', 'source-snapshot/diagnose.json', 'critic/measurements.json'):
        path = scoped_path(preview, relative)
        if path.is_file():
            paths.append(path)
    retro = scoped_path(variant, 'retro/' + pub['source']['id'])
    if scoped_path(retro, 'binding.json').is_file():
        binding = read(scoped_path(retro, 'binding.json'))
        if binding.get('snapshot_sha256') == pub['source']['snapshot_sha256']:
            import critic
            directory = scoped_path(retro, 'evidence')
            if critic.hashes(directory) != binding['files']:
                raise ValueError('Retrospective evidence changed')
            paths.append(scoped_path(directory, 'measurements.json'))
    for path in paths:
        report = read(path)
        if report.get('snapshot_sha256') != pub['source']['snapshot_sha256']:
            continue
        events = report.get('events', []) + report.get('samples', [])
        events += report.get('rhythm', {}).get('events', [])
        for row in events:
            start = row.get('start', row.get('time'))
            if start is not None:
                entry = {**row, 'start': start, 'end': row.get('end', start + .001), 'evidence': str(path)}
                if row.get('screenshot'):
                    entry['frame'] = str(scoped_path(path.parent, 'images/' + row['screenshot']))
                result.append(entry)
    return result


def report(api, variant, pub, imported):
    result = content_analysis.analyze(imported['normalized'], pub['timings'], evidence=evidence(api, variant, pub))
    for key, value in imported['normalized']['points'].items():
        result['metrics'].setdefault(key, value)
    return result


def cell(value):
    if value is None:
        return '未提供'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |',
                      *['| ' + ' | '.join(cell(x) for x in row) + ' |' for row in rows]])


def open_content(api, root, args):
    _, variant, _ = work_memory.context(api, root, args)
    directory, pub = publication(api, variant, args.publication_id)
    history = imports(api, directory)
    selected = next((item for item in history if item['id'] == args.import_id), None) if args.import_id else (history[-1] if history else None)
    if selected is None:
        raise ValueError('No matching import')
    analysis = report(api, variant, pub, selected)
    comparison = None
    compare_id = next((v.get('compare') for v in pub['variables'] if v.get('compare')), None)
    if compare_id:
        other_variant, other_dir, other = comparison_publication(api, root, compare_id, pub['platform'], pub['account'])
        other_imports = imports(api, other_dir)
        if other_imports:
            comparison = {'id': compare_id, 'metrics': report(api, other_variant, other, other_imports[-1])['metrics']}
    generated = {'publication_sha256': digest(pub), 'publication_file_sha256': pub['file_sha256'],
                 'import_id': selected['id'], 'import_sha256': selected['normalized_sha256'],
                 'cutoff_date': selected['cutoff_date'], 'stage': selected['stage'],
                 'variables': pub['variables'], 'analysis': analysis,
                 'points': selected['normalized']['points'], 'daily': selected['normalized']['daily'],
                 'traffic_sources': selected['normalized']['traffic_sources'],
                 'provenance': selected['normalized']['provenance'], 'warnings': selected['normalized']['warnings'],
                 'traffic_changes': content_analysis.traffic_changes([item['normalized'] for item in history])}
    body = '# 内容复盘：' + pub['title'] + '\n\n'
    body += '## 核心指标\n\n' + table(['指标', '值'], metric_rows(analysis['metrics'])) + '\n\n'
    body += '\n'.join(analysis['limitations']) + '\n\n'
    if compare_id:
        body += '## 对照核心指标\n\n'
        if comparison:
            body += table(['指标', pub['id'], compare_id], [(key, value, comparison['metrics'].get(key)) for key,value in analysis['metrics'].items()]) + '\n\n'
        else:
            body += '对照发布尚无导入。\n\n'
    body += '```json\n' + json.dumps(generated, ensure_ascii=False, indent=2, allow_nan=False) + '\n```\n'
    block = START + '\n' + body + END
    target = scoped_path(directory, 'CONTENT.md')
    with api.naming_lock(root):
        text = target.read_text(encoding='utf-8') if target.exists() else (Path(__file__).with_name('templates') / 'CONTENT_RETRO.template.md').read_text(encoding='utf-8')
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
            raise ValueError('CONTENT.md generated markers missing or ambiguous; preserve user text')
        begin, rest = text.split(START)
        _, end = rest.split(END)
        api.atomic_write(target, begin + block + end)
    return {'path': str(target), **generated}


def check_text(text, line):
    findings = []
    section = None
    headers = None
    seen_tables = set()
    required = {'信号', '位置', '归因层', '去向'}
    for raw in text.splitlines():
        if raw.startswith('## '):
            section, headers = raw[3:].strip(), None
        if section not in ('找问题', '找优秀') or not raw.startswith('|'):
            continue
        values = [part.strip() for part in raw.strip('|').split('|')]
        if headers is None:
            headers = values
            seen_tables.add(section)
            if section == '找问题' and not required.issubset(headers):
                findings.append('找问题缺少字段')
            if section == '找优秀' and '用户标记' not in headers:
                findings.append('找优秀缺少用户标记字段')
            continue
        if all(re.fullmatch(r'[-: ]*', part) for part in values) or not any(values):
            continue
        if len(values) != len(headers):
            findings.append(section + '列数不一致'); continue
        row = dict(zip(headers, values))
        if section == '找问题':
            if any(not row.get(k) for k in required):
                findings.append('找问题字段不完整')
            if row.get('归因层') not in ATTRIBUTIONS:
                findings.append('非法归因层：' + row.get('归因层', ''))
            if row.get('去向') not in DESTINATIONS:
                findings.append('非法去向：' + row.get('去向', ''))
            if row.get('去向') == 'Script 开头与衔接' and not (line in {'explainer', 'english'} or line.startswith('showcase/')):
                findings.append('数学产品线不支持 Script 开头与衔接')
        elif row.get('用户标记') != '是':
            findings.append('找优秀仅接收用户标记')
    if not {'找问题', '找优秀'}.issubset(seen_tables):
        findings.append('缺少找问题 / 找优秀字段')
    return findings


def summary(api, root):
    base = api.configured_work_root(root) or root
    publications, excluded, groups = [], [], {}
    for work, variant, path in publication_paths(api, root):
        _, pub = publication(api, variant, path.parent.name)
        history = imports(api, path.parent)
        for item in history:
            if item['stage'] != 'long-tail':
                excluded.append({'work': work.name, 'variant': variant.name, 'publication': pub['id'], 'import': item['id'], 'stage': item['stage']})
        tail = [item for item in history if item['stage'] == 'long-tail']
        if not tail:
            continue
        selected = tail[-1]
        analysis = report(api, variant, pub, selected)
        band = '≤60s' if pub['duration'] <= 60 else '60–180s' if pub['duration'] <= 180 else '>180s'
        row = {'work': work.name, 'variant': variant.name, 'publication': pub['id'], 'title': pub['title'],
               'platform': pub['platform'], 'account': pub['account'], 'duration_group': band, 'line': pub['line'],
               'import': selected['id'], 'cutoff_date': selected['cutoff_date'],
               'metrics': analysis['metrics'], 'opening': analysis['opening'], 'variables': pub['variables'],
               'traffic_sources': selected['normalized']['traffic_sources'],
               'traffic_changes': content_analysis.traffic_changes([i['normalized'] for i in history])}
        publications.append(row)
        groups.setdefault((pub['platform'], pub['account'], band), []).append(row)
    distributions = []
    for key, rows in sorted(groups.items()):
        group = {'platform': key[0], 'account': key[1], 'duration_group': key[2], 'count': len(rows),
                 'publications': [dict(work=r['work'], variant=r['variant'], id=r['publication']) for r in rows]}
        if len(rows) >= 5:
            stats = {}
            for metric in rows[0]['metrics']:
                values = [r['metrics'][metric] for r in rows if isinstance(r['metrics'].get(metric), (int, float))]
                if values:
                    stats[metric] = {'count': len(values), 'min': min(values), 'median': statistics.median(values), 'max': max(values)}
            group['distribution'] = stats
            group['deviations'] = [{'work': r['work'], 'variant': r['variant'], 'id': r['publication'],
                'from_median': {k: r['metrics'][k] - s['median'] for k,s in stats.items() if isinstance(r['metrics'].get(k), (int,float))}} for r in rows]
        else:
            group['limitation'] = '少于 5 条长尾发布，只列单片，不报偏离'
        distributions.append(group)
    opening_rows, topic_rows, experiments = [], [], []
    for row in publications:
        identity = {key: row[key] for key in ('work', 'variant', 'publication', 'platform', 'account', 'line', 'duration_group')}
        opening_rows.append({**identity, **row['opening'], 'metrics': row['metrics']})
        sources = {r['source']: r.get('share') for r in row['traffic_sources']}
        topic_rows.append({**identity, 'topic': row['title'], 'metrics': row['metrics'],
                           '搜索': sources.get('搜索'), '个人主页': sources.get('个人主页')})
        experiments.extend({**identity, **v, 'metrics': row['metrics']} for v in row['variables'])
    experiments.sort(key=lambda row: (row['variable'], row['account'], row['publication']))
    result = {'parameters': dict(content_analysis.PARAMETERS),
              'limitations': ['无逐秒留存曲线；条件平均离开点不是离开分布。', '平均播放占比仅在同片长组内比较。'],
              'groups': distributions, 'publications': publications, 'excluded_imports': excluded,
              'opening_samples': opening_rows, 'topics': topic_rows, 'experiments': experiments}
    markdown = '# 内容复盘汇总\n\n只计数，不判断质量。基线仅计长尾期；缺来源为未列出。\n\n'
    markdown += '## 单片指标\n\n'
    for row in publications:
        markdown += '### ' + row['account'] + ' / ' + row['publication'] + '\n\n' + table(['指标', '值'], metric_rows(row['metrics'])) + '\n\n'
    markdown += '## 开头样本表\n\n' + table(['发布', '账号', '开头窗口', '指标'], [(r['publication'],r['account'],json.dumps({k:v for k,v in r.items() if k.startswith('text_')},ensure_ascii=False),r['metrics']) for r in opening_rows]) + '\n\n'
    markdown += '## 选题表\n\n' + table(['发布','主题','产品线','搜索','个人主页','指标'], [(r['publication'],r['topic'],r['line'],r['搜索'],r['个人主页'],r['metrics']) for r in topic_rows]) + '\n\n'
    markdown += '## 实验变量表\n\n' + table(['变量','本期取值','发布','对照','指标'], [(r['variable'],r['value'],r['publication'],r.get('compare'),r['metrics']) for r in experiments]) + '\n\n'
    markdown += '## 分布与导入记录\n\n```json\n' + json.dumps(result,ensure_ascii=False,indent=2) + '\n```\n'
    directory = scoped_path(base, 'content-summary')
    with api.naming_lock(root):
        directory.mkdir(exist_ok=True)
        write(api, scoped_path(directory, 'summary.json'), result)
        api.atomic_write(scoped_path(directory, 'SUMMARY.md'), markdown)
    return {'path': str(directory / 'SUMMARY.md'), **result}


def run(api, root, args):
    try:
        operation = args.content_operation
        if operation == 'summary':
            result = summary(api, root)
        elif operation == 'link':
            result = link(api, root, args)
        elif operation == 'import':
            result = import_data(api, root, args)
        elif operation == 'open':
            result = open_content(api, root, args)
        else:
            _, variant, _ = work_memory.context(api, root, args)
            directory, pub = publication(api, variant, args.publication_id)
            result = {'findings': check_text(scoped_path(directory, 'CONTENT.md').read_text(encoding='utf-8'), pub['line']), 'advisory_only': True}
        api.print_result(root, args, result)
    except (ValueError, KeyError, OSError, TypeError) as error:
        raise api.HarnessError(str(error)) from error


def add_commands(commands, api):
    group = commands.add_parser('content', help='Offline publication analytics and content retrospective')
    children = group.add_subparsers(dest='content_operation', required=True)
    for operation in ('link', 'import', 'open', 'check', 'summary'):
        p = children.add_parser(operation)
        p.set_defaults(handler=lambda root, args: run(api, root, args))
        if operation != 'summary':
            p.add_argument('publication_id')
        if operation == 'link':
            selection = p.add_mutually_exclusive_group(required=True)
            selection.add_argument('--final', action='store_true'); selection.add_argument('--draft')
            p.add_argument('--file', required=True); p.add_argument('--platform', required=True)
            p.add_argument('--account'); p.add_argument('--title', required=True)
            p.add_argument('--cover-text', required=True); p.add_argument('--published-at', required=True)
            p.add_argument('--ratio', required=True); p.add_argument('--timings')
            p.add_argument('--variable', action='append'); p.add_argument('--no-variable', action='store_true')
            p.add_argument('--compare')
        elif operation == 'import':
            p.add_argument('--file', action='append'); p.add_argument('--dir')
            p.add_argument('--cutoff', required=True); p.add_argument('--stage', choices=('long-tail','early'))
        elif operation == 'open':
            p.add_argument('--import', dest='import_id')
