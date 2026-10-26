"""Work CLI visual retrospective, sample and known-defect commands."""
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

import critic
import explainer
import visual_memory as memory
from storage import scoped_path
from visual_plan import plan_scene_rows, scene_projection


def context(api, root, args):
    if not args.work_override or not args.variant_override:
        raise ValueError('Memory commands require explicit --work and --variant')
    work, _ = api.selected_work(root, args, allow_archive=True)
    scoped_path(api.configured_work_root(root) or root, work.relative_to(api.configured_work_root(root) or root).as_posix())
    scoped_path(work, 'variants/' + api.validate_id(args.variant_override, 'Variant'))
    api.require_workflow(work, 'hyperframes_video')
    variant, state = api.selected_variant(root, work, args)
    return work, variant, state


def draft(api, variant, target):
    scoped_path(variant, 'previews/' + api.validate_id(target, 'Draft'))
    preview, metadata = api.checked_preview(variant, target)
    api.assert_full_draft(metadata)
    api.assert_preview_inputs(preview, metadata)
    if metadata.get('kind', 'executable') != 'executable':
        raise ValueError('Retrospective requires an executable Draft snapshot')
    if api.snapshot_digest(preview / 'source-snapshot') != metadata['snapshot_sha256']:
        raise ValueError('Draft snapshot changed')
    return preview, metadata


def checked_retro(api, variant, target):
    directory = scoped_path(variant, f'retro/{api.validate_id(target, "Draft")}')
    binding = memory.read(scoped_path(directory, 'binding.json'))
    _, metadata = draft(api, variant, target)
    if binding['draft_id'] != target or binding['snapshot_sha256'] != metadata['snapshot_sha256']:
        raise ValueError('Retrospective targets another snapshot')
    if critic.hashes(scoped_path(directory, 'evidence')) != binding['files']:
        raise ValueError('Retrospective evidence changed')
    return directory, binding


def open_retro(api, root, args):
    work, variant, state = context(api, root, args)
    preview, metadata = draft(api, variant, args.draft_id)
    directory = scoped_path(variant, f'retro/{args.draft_id}')
    if directory.exists():
        checked_retro(api, variant, args.draft_id)
        return {'path': str(directory / 'VISUAL.md'), 'reused': True}
    parent = scoped_path(variant, 'retro')
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pending-', dir=parent) as temp:
        stage = Path(temp) / 'retro'
        stage.mkdir()
        evidence = stage / 'evidence'
        ledger_path = scoped_path(variant, 'critic/ledger.json')
        ledger = memory.read(ledger_path) if ledger_path.is_file() else {'rounds': []}
        previous = next((item for item in reversed(ledger['rounds']) if item['draft_id'] == args.draft_id
                         and 'frames_reclaimed_at' not in item
                         and item['snapshot_sha256'] == metadata['snapshot_sha256']), None)
        if previous:
            source = scoped_path(variant / 'critic', previous['package'])
            if critic.hashes(source) != previous['files']:
                raise ValueError('Critic evidence changed')
            if any(Path(name).suffix.lower() not in ('.png', '.json', '.md', '.html') for name in previous['files']):
                raise ValueError('Unsupported evidence file; no video copying')
            shutil.copytree(source, evidence)
            if critic.hashes(evidence) != previous['files']:
                raise ValueError('Critic evidence changed during copying')
        else:
            evidence.mkdir()
            opener = SimpleNamespace(**{**vars(args), 'preview_id': args.draft_id, 'legacy': False,
                'no_open': True, 'hyperframes_dist': None, 'port': 0})
            with redirect_stdout(io.StringIO()):
                api.command_preview_open(root, opener)
            diagnostic = SimpleNamespace(**{**vars(args), 'preview_id': args.draft_id, 'json': True,
                '_evidence_dir': evidence / 'images', 'minimum': 20, 'similarity': .8, 'exceptions': None})
            with redirect_stdout(io.StringIO()) as output:
                api.command_preview_diagnose(root, diagnostic)
            report = json.loads(output.getvalue())
            rows = plan_scene_rows((preview / 'ANIMATION_PLAN.md').read_text(encoding='utf-8'))
            direction = {sid: {'brief': row.get('brief', {}), 'segments': row.get('segments', [])} for sid, row in rows.items()}
            critic.package(evidence, report, direction, [], {'settings': {'critic.provider': {'value': 'off'}}})
        report = memory.read(evidence / 'measurements.json')
        if report.get('snapshot_sha256') != metadata['snapshot_sha256'] or report.get('target') != args.draft_id or report.get('status') != 'diagnostic_only':
            raise ValueError('Evidence does not match Draft snapshot')
        binding = {'work': work.name, 'variant': variant.name, 'draft_id': args.draft_id,
                   'snapshot_sha256': metadata['snapshot_sha256'], 'line': memory.line_id(metadata.get('adopted_settings', state)),
                   'runtime_version': metadata.get('runtime_version'), 'runtime_sha256': metadata.get('runtime_sha256'),
                   'assets': metadata.get('adopted_settings', {}).get('appearance_lock', {}).get('assets', []) if metadata.get('adopted_settings', {}).get('appearance_lock') else [],
                   'files': critic.hashes(evidence)}
        memory.write(stage / 'binding.json', binding)
        template = Path(__file__).with_name('templates') / 'VISUAL_RETRO.template.md'
        (stage / 'VISUAL.md').write_text(template.read_text(encoding='utf-8').replace('__DRAFT__', args.draft_id).replace('__SHA256__', metadata['snapshot_sha256']), encoding='utf-8')
        with api.naming_lock(root):
            draft(api, variant, args.draft_id)
            if directory.exists():
                raise ValueError('Retrospective created concurrently; reopen it')
            stage.rename(directory)
    return {'path': str(directory / 'VISUAL.md'), 'reused': False}


def segment_frames(api, variant, target, segment):
    directory, binding = checked_retro(api, variant, target)
    preview, metadata = draft(api, variant, target)
    text = (preview / 'ANIMATION_PLAN.md').read_text(encoding='utf-8')
    rows = plan_scene_rows(text)
    scenes = {row['id']: row for row in scene_projection(preview / 'source-snapshot', text)}
    scene_id = segment.split('·')[0]
    if scene_id not in scenes:
        raise ValueError('Unknown sample Scene')
    scene = scenes[scene_id]
    start, end = scene['start'], scene['start'] + scene['duration']
    role = None
    if '·' in segment:
        segments = rows[scene_id].get('segments', [])
        position = next((i for i, item in enumerate(segments) if item['id'] == segment), None)
        if position is None:
            raise ValueError('Unknown storyboard segment')
        cues = memory.read(preview / 'source-snapshot/runtime/cues.json')
        start = explainer.find_cue(cues, segments[position]['cue'])
        if position + 1 < len(segments):
            end = explainer.find_cue(cues, segments[position + 1]['cue'])
        role = segments[position]['role']
    if not scene['start'] <= start < end <= scene['start'] + scene['duration']:
        raise ValueError('Sample segment lies outside its Scene')
    report = memory.read(directory / 'evidence/measurements.json')
    frames = []
    for item in sorted(report['samples'], key=lambda item: item['time']):
        if item.get('ready') and item.get('screenshot') and start <= item['time'] < end:
            name = 'images/' + item['screenshot']
            path = scoped_path(directory / 'evidence', name)
            frames.append({'path': name, 'time': item['time'], 'sha256': memory.digest(path)})
    return directory, binding, frames, role


def sample_command(api, root, args):
    base = api.configured_work_root(root) or root
    op = args.memory_operation
    if op == 'add':
        work, variant, _ = context(api, root, args)
        if not re.fullmatch(r'S[0-9]+[A-Z]*(?:·[AB][1-9][0-9]*)?', args.segment):
            raise ValueError('Invalid sample segment ID')
        memory.identity(args.sample_id)
        if '·' in args.sample_id:
            raise ValueError('Sample ID cannot contain segment separator')
        directory, binding, frames, role = segment_frames(api, variant, args.draft_id, args.segment)
        if not args.reason.strip():
            raise ValueError('Sample requires a borrowing dimension')
        for existing in memory.entries(base, 'sample'):
            if existing['sample_id'] == args.sample_id and existing['source'] != {key: binding[key] for key in ('work', 'variant', 'draft_id', 'snapshot_sha256')}:
                raise ValueError('One sample ID must refer to one whole Draft')
        record = {'id': args.sample_id + '·' + args.segment, 'sample_id': args.sample_id, 'segment': args.segment,
                  'line': binding['line'], 'role': role, 'reason': args.reason, 'mechanism_id': args.mechanism,
                  'source': {key: binding[key] for key in ('work', 'variant', 'draft_id', 'snapshot_sha256')},
                  'runtime_version': binding['runtime_version'], 'runtime_sha256': binding['runtime_sha256'],
                  'assets': binding['assets']}
        with api.naming_lock(root):
            return memory.store_entry(base, 'sample', record, directory / 'evidence', frames)
    if op == 'list':
        line = args.line
        if not line and not args.all_lines:
            _, _, state = context(api, root, args)
            line = memory.line_id(state)
        return {'samples': sorted(memory.entries(base, 'sample', None if args.all_lines else line),
                                  key=lambda item: (memory.STATES.index(item['status']), item['id']))}
    if op == 'show':
        if args.plan_revision is not None:
            _, variant, _ = context(api, root, args)
            directory = scoped_path(variant, f'reference-memory/{args.plan_revision}')
            metadata = api.read_frontmatter(variant / 'ANIMATION_PLAN.md')
            expected = metadata.get('reference_memory_sha256') if metadata.get('revision') == args.plan_revision else None
            manifest = memory.frozen(directory, expected)
            record = next((r for r in manifest['references'] if r['id'] == args.id), None)
            if record is None:
                raise ValueError('Sample is not in this Plan revision')
        else:
            record = memory.get(base, 'sample', args.id)
            directory = memory.library(base, 'sample')
            memory.verify_frames(directory, record['frames'])
        return {**record, 'frames': [{**f, 'path': str(scoped_path(directory, f['path']))} for f in record['frames']]}
    with api.naming_lock(root):
        return memory.change_status(base, 'sample', args.id, '已退役' if op == 'retire' else '已巩固', args.reason if op == 'retire' else args.into)


def defect_command(api, root, args):
    base = api.configured_work_root(root) or root
    op = args.memory_operation
    if op == 'list':
        line = args.line
        if not line:
            _, _, state = context(api, root, args)
            line = memory.line_id(state)
        return {'defects': memory.entries(base, 'defect', line)}
    if op == 'retire':
        with api.naming_lock(root):
            return memory.change_status(base, 'defect', args.id, '已退役', args.blocked_by)
    _, variant, _ = context(api, root, args)
    directory, binding = checked_retro(api, variant, args.draft_id)
    records, findings = memory.parse_retro((directory / 'VISUAL.md').read_text(encoding='utf-8'))
    if findings or not any(item['已知缺陷 ID'] == args.id for item in records['找问题']):
        raise ValueError('Defect must be linked from a valid retrospective problem row')
    if not args.description.strip():
        raise ValueError('Defect requires a description')
    frames = [{'path': path, 'sha256': memory.digest(scoped_path(directory / 'evidence', path))} for path in args.frame]
    record = {'id': args.id, 'line': binding['line'], 'description': args.description,
              'source': {key: binding[key] for key in ('work', 'variant', 'draft_id', 'snapshot_sha256')},
              'retro': f'retro/{args.draft_id}/VISUAL.md'}
    with api.naming_lock(root):
        return memory.store_entry(base, 'defect', record, directory / 'evidence', frames)


def summary(api, root):
    base = api.configured_work_root(root) or root
    assets, problems, references = {}, Counter(), set()
    candidates, warnings = [], []
    # Known Work roots only; never crawl tools, assets or arbitrary root content.
    works = scoped_path(base, 'works')
    paths = [path for path, _ in api.work_paths(root)]
    for work in paths:
        scoped_path(works, work.relative_to(works).as_posix())
        if work.name.startswith('.pending-') or not work.is_dir() or not (work / 'WORK.md').is_file():
            continue
        if api.work_workflow(work) != 'hyperframes_video':
            continue
        scoped_path(work, 'variants')
        for variant in api.variant_paths(work):
            scoped_path(work, variant.relative_to(work).as_posix())
            state = api.read_json(variant / 'variant.yaml')
            line = memory.line_id(state)
            seen_assets = set()
            for item in (state.get('appearance_lock') or {}).get('assets', []):
                key = (line, item['ref'], item['version'])
                if key in seen_assets:
                    continue
                seen_assets.add(key)
                value = assets.setdefault(key, {'line': line, 'ref': item['ref'], 'version': item['version'], 'count': 0, 'last_used': None})
                value['count'] += 1
                used = state.get('updated_at') or state.get('created_at')
                if used and (value['last_used'] is None or used > value['last_used']):
                    value['last_used'] = used
            for path in sorted(scoped_path(variant, 'retro').glob('*/VISUAL.md')):
                scoped_path(variant, path.relative_to(variant).as_posix())
                record, binding = checked_retro(api, variant, path.parent.name)
                data, findings = memory.parse_retro(path.read_text(encoding='utf-8'))
                if findings:
                    warnings.append({'path': str(path), 'findings': findings})
                    continue
                for item in data['找问题']:
                    problems[(binding['line'], item['归因层'], item['去向'], item['已知缺陷 ID'] or None)] += 1
                for item in data['找优秀']:
                    if item['留存粒度'] == '组件或动作' or item['手写重复'] == '是':
                        candidates.append({'work': work.name, 'variant': variant.name, 'draft': path.parent.name, **item})
            dirs = [*scoped_path(variant, 'reference-memory').glob('*/references.json'),
                    *scoped_path(variant, 'previews').glob('draft-*/reference-memory/references.json')]
            for path in dirs:
                scoped_path(variant, path.relative_to(variant).as_posix())
                manifest = memory.frozen(path.parent)
                for item in manifest['references']:
                    references.add((work.name, variant.name, manifest['revision'], item['id']))
    sample_counts = Counter(item[3] for item in references)
    mechanism_counts = Counter(item.get('mechanism_id') or '未关联' for item in memory.entries(base, 'sample'))
    result = {'assets': sorted(assets.values(), key=lambda r: (r['line'], r['ref'], r['version'])),
              'defects': [{'line': k[0], 'attribution': k[1], 'destination': k[2], 'defect_id': k[3], 'count': n} for k, n in problems.items()],
              'asset_candidates': candidates, 'handwritten_repetitions': sum(c['手写重复'] == '是' for c in candidates),
              'sample_references': dict(sorted(sample_counts.items())), 'mechanism_samples': dict(sorted(mechanism_counts.items())), 'warnings': warnings}
    directory = scoped_path(base, 'retro-summary')
    with api.naming_lock(root):
        memory.write(directory / 'summary.json', result)
        api.atomic_write(scoped_path(directory, 'SUMMARY.md'), '# 画面复盘汇总\n\n只计数，不推断质量或自动立项。\n\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n')
    return {'path': str(directory / 'SUMMARY.md'), **result}


def run(api, root, args):
    try:
        if args.command == 'sample':
            result = sample_command(api, root, args)
        elif args.command == 'defect':
            result = defect_command(api, root, args)
        elif args.memory_operation == 'summary':
            result = summary(api, root)
        elif args.memory_operation == 'open':
            result = open_retro(api, root, args)
        else:
            _, variant, _ = context(api, root, args)
            directory, _ = checked_retro(api, variant, args.draft_id)
            _, findings = memory.parse_retro((directory / 'VISUAL.md').read_text(encoding='utf-8'))
            result = {'findings': findings, 'advisory_only': True}
        api.print_result(root, args, result)
    except (ValueError, KeyError, OSError) as error:
        raise api.HarnessError(str(error)) from error


def add_commands(commands, api):
    for kind, operations in [('retro', ('open', 'check', 'summary')), ('sample', ('add', 'list', 'show', 'retire', 'consolidate')), ('defect', ('add', 'list', 'retire'))]:
        group = commands.add_parser(kind)
        children = group.add_subparsers(dest='memory_operation', required=True)
        for operation in operations:
            p = children.add_parser(operation)
            p.set_defaults(handler=lambda root, args: run(api, root, args))
            if kind == 'retro' and operation != 'summary':
                p.add_argument('draft_id')
            if kind == 'retro' and operation == 'open':
                p.add_argument('--hyperframes-cli'); p.add_argument('--browser')
                p.add_argument('--step', type=float, default=.5); p.add_argument('--width', type=int, default=960)
                p.add_argument('--timeout-ms', type=int, default=5000)
            if kind in ('sample', 'defect') and operation == 'list':
                p.add_argument('--line')
                if kind == 'sample':
                    p.add_argument('--all-lines', action='store_true')
            if kind in ('sample', 'defect') and operation in ('show', 'retire', 'consolidate'):
                p.add_argument('id')
            if kind == 'sample' and operation == 'show':
                p.add_argument('--plan-revision', type=int)
            if kind == 'sample' and operation == 'retire':
                p.add_argument('--reason', required=True)
            if operation == 'consolidate':
                p.add_argument('--into', required=True)
            if kind == 'defect' and operation == 'retire':
                p.add_argument('--blocked-by', required=True, help='Rule or diagnostic that now prevents the defect')
            if operation == 'add':
                p.add_argument('sample_id' if kind == 'sample' else 'id')
                p.add_argument('--draft', dest='draft_id', required=True)
                if kind == 'sample':
                    p.add_argument('--segment', required=True); p.add_argument('--reason', required=True)
                    p.add_argument('--mechanism')
                else:
                    p.add_argument('--description', required=True)
                    p.add_argument('--frame', action='append', required=True, help='Relative PNG path within retro evidence')
