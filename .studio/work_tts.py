"""Explicit Variant speech generation and transactional adoption into the existing project."""
from html import escape
import json
import os
import re
import shutil
from pathlib import Path

import explainer
import storage
import tts
from component_harness import package_write_lock


def generation_config(state, explicit=None):
    local = json.loads(os.environ.get('HYPERFRAMES_AI_RESOLVED_CONFIG', '{}'))
    tools = local.get('tools', {})
    config = dict(explicit if explicit is not None else tools.get('tts', {}))
    values = state.get('design_values', {})
    defaults = {}
    voice = values.get('voice.ref')
    if voice:
        voices = tools.get('voices', {})
        if voice not in voices or not isinstance(voices[voice], dict):
            raise ValueError('TTS voice is not mapped in local tools.voices: ' + voice)
        defaults.update(voices[voice])
    if 'voice.duration_factor' in values:
        defaults['duration_factor'] = values['voice.duration_factor']
    config['options'] = ({**config.get('options', {}), **defaults} if explicit is None
                         else {**defaults, **config.get('options', {})})
    return tts.configuration(config)


def verify(variant, api):
    state = api.read_json(variant / 'variant.yaml')
    audio = state.get('audio')
    if not isinstance(audio, dict) or audio.get('source') != 'tts':
        return
    text = api.script_text(api.input_path(variant, 'SCRIPT.md'))
    if tts.digest(text.encode()) != audio.get('script_sha256'):
        raise ValueError('Narration changed; generate/adopt matching speech and rebuild timing')
    rows = tts.segments(api.script_text(api.input_path(variant, 'SCRIPT.md'), anchors=True))
    if tts.digest(tts.json_bytes(rows)) != audio.get('anchors_sha256'):
        raise ValueError('Narration anchors changed; adopt matching speech and rebuild timing')
    project = variant / 'project'
    path = storage.scoped_path(project, audio['path'])
    if api.file_sha256(path) != audio['sha256']:
        raise ValueError('Formal TTS audio changed')
    alignment = state.get('alignment', {})
    path = storage.scoped_path(project, alignment['path'])
    if api.file_sha256(path) != alignment['sha256']:
        raise ValueError('Formal TTS alignment changed')
    for name, expected in alignment.get('derived', {}).items():
        if api.file_sha256(storage.scoped_path(project, name)) != expected:
            raise ValueError('Formal TTS timing changed; adopt the measured alignment again')
    html = (project / 'index.html').read_text(encoding='utf-8')
    if voice_block(html, audio['path'], audio['duration']) != html:
        raise ValueError('Formal TTS voice track changed')


def voice_block(html, path, duration):
    start, end = '<!-- harness-voice:start -->', '<!-- harness-voice:end -->'
    block = (start + '\n<audio id="harness-voice" data-audio-role="voice" data-start="0" '
             f'data-duration="{duration}" data-track-index="5" src="{escape(path, quote=True)}"></audio>\n' + end)
    outside = html
    if start in html or end in html:
        if html.count(start) != 1 or html.count(end) != 1 or html.index(start) > html.index(end):
            raise ValueError('Invalid generated voice markers')
        before, tail = html.split(start)
        _, after = tail.split(end)
        outside = before + after
    if re.search(r'<audio\b[^>]*data-audio-role\s*=\s*[\"\']voice[\"\']', outside, re.I):
        raise ValueError('Project already has a manual voice track; remove it before TTS adoption')
    if start in html:
        return before + block + after
    at = explainer.BodyEnd(html).end
    if at is None:
        raise ValueError('TTS adoption requires project index.html with a closing body')
    return html[:at] + block + '\n' + html[at:]


def command(root, args, api):
    if not args.work_override or not args.variant_override:
        raise ValueError('TTS requires explicit --work and --variant')
    work, _ = api.selected_work(root, args)
    api.require_workflow(work, 'hyperframes_video')
    variant, state = api.selected_variant(root, work, args)
    script = api.input_path(variant, 'SCRIPT.md')
    if (api.script_confirmation(variant, state)
            and api.read_frontmatter(script).get('approval') not in {'approved', 'not_required'}):
        raise ValueError('SCRIPT.md still requires approval')
    text = api.script_text(script)
    script_hash = tts.digest(text.encode())
    rows = tts.segments(api.script_text(script, anchors=True))
    if args.tts_command in {'generate', 'import-batch'}:
        config = generation_config(state, api.read_json(Path(args.config)) if args.config else None)
        selected = tts.segments(api.script_text(script, anchors=True), getattr(args, 'anchor', None) or ())
        report = (tts.import_batch(variant, selected, config, script_hash, args.batch)
                  if args.tts_command == 'import-batch' else tts.generate(variant, selected, config, script_hash))
        if tts.digest(api.script_text(script).encode()) != script_hash:
            raise ValueError('Script changed during synthesis; candidate retained but not adopted')
        api.print_result(root, args, {key: report[key] for key in ('id', 'path', 'duration', 'status', 'alignment')})
        return
    with api.naming_lock(root), package_write_lock(storage.scoped_path(variant, '.runtime/component-install.lock')):
        state = api.read_json(variant / 'variant.yaml')
        report = tts.candidate(variant, args.candidate)
        if report['request']['script_sha256'] != script_hash or report['request']['segments'] != [
                {**row, 'options': stored['options']} for row, stored in zip(rows, report['request']['segments'])] or len(rows) != len(report['request']['segments']):
            raise ValueError('Formal speech must cover all current Script anchors; generate a full candidate')
        alignment_path = storage.scoped_path(work, args.alignment)
        if not alignment_path.is_file() or alignment_path.stat().st_nlink != 1:
            raise ValueError('Alignment must be a regular Work-local file')
        alignment_bytes = alignment_path.read_bytes()
        evidence = json.loads(alignment_bytes)
        if (not isinstance(evidence, dict) or evidence.get('audio_sha256') != report['files']['audio.wav']
                or evidence.get('method') not in {'asr', 'forced-alignment', 'manual-measured', 'provider-native'}):
            raise ValueError('Alignment must identify this candidate audio SHA-256 and its measured method')
        cues, sections = tts.aligned_sections(text, rows, alignment_bytes, report['duration'])
        cues['sources'].update(audio_sha256=evidence['audio_sha256'], method=evidence['method'])
        sections.update(audio_sha256=report['files']['audio.wav'], script_sha256=script_hash)
        project = storage.scoped_path(variant, 'project')
        voice_name = 'assets/voice/' + args.candidate + '.wav'
        voice = storage.scoped_path(project, voice_name)
        audio_bytes = (Path(report['path']) / 'audio.wav').read_bytes()
        if voice.exists() and (voice.stat().st_nlink != 1 or voice.read_bytes() != audio_bytes):
            raise ValueError('Refusing to replace different or linked voice media')
        index = storage.scoped_path(project, 'index.html')
        updated = voice_block(index.read_text(encoding='utf-8'), voice_name, report['duration'])
        names = {'runtime/cues.json': tts.json_bytes(cues), 'runtime/section_map.json': tts.json_bytes(sections),
                 'runtime/voice-alignment.json': alignment_bytes, voice_name: audio_bytes}
        runtime = storage.scoped_path(project, 'runtime/cues.js')
        if not runtime.exists():
            names['runtime/cues.js'] = (Path(api.__file__).parent / 'runtime/cues.js').read_bytes() if hasattr(api, '__file__') else (root / '.studio/runtime/cues.js').read_bytes()
        paths = [storage.scoped_path(project, name) for name in names]
        plan = variant / 'ANIMATION_PLAN.md'
        config_path = storage.scoped_path(project, 'project-config.json')
        paths += [index, config_path, plan, variant / 'variant.yaml']
        for path in paths:
            if path.exists() and (path.is_symlink() or path.stat().st_nlink != 1):
                raise ValueError('TTS adoption refuses linked files')
        before = {path: path.read_bytes() if path.exists() else None for path in paths}
        if tts.digest(api.script_text(script).encode()) != script_hash:
            raise ValueError('Script changed before speech adoption')
        carried = None
        try:
            for name, data in names.items():
                target = storage.scoped_path(project, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            api.atomic_write(index, updated)
            explainer.declare_files(project, [*names, 'runtime/cues.js'])
            state.update(audio={'source': 'tts', 'path': voice_name, 'sha256': report['files']['audio.wav'],
                                'duration': report['duration'], 'candidate': args.candidate, 'script_sha256': script_hash,
                                'anchors_sha256': tts.digest(tts.json_bytes(rows))},
                         alignment={'path': 'runtime/voice-alignment.json', 'sha256': tts.digest(alignment_bytes),
                                    'derived': {name: tts.digest(names[name]) for name in ('runtime/cues.json', 'runtime/section_map.json')}},
                         accepted_preview=None, current_final=None)
            original = api.read_frontmatter(plan)
            metadata = {**original, **api.plan_metadata(variant, state)}
            metadata['revision'] = max(metadata.get('revision', 1), state.get('plan_revision', 1)) + 1
            metadata['status'] = 'draft'
            state['plan_revision'] = metadata['revision']
            if metadata.get('reference_memory_sha256'):
                carried = api.visual_memory.carry(variant, original.get('revision', 1), metadata['revision'],
                                                  metadata['reference_memory_sha256'])
            api.atomic_write(plan, '---\n' + json.dumps(metadata, ensure_ascii=False) + '\n---\n'
                             + api.plan_metadata_body(api.document_body(plan), metadata))
            api.write_variant(variant, state)
            verify(variant, api)
        except Exception:
            if carried is not None:
                shutil.rmtree(carried)
            for path, data in before.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            raise
    api.print_result(root, args, {'status': 'aligned', 'candidate': args.candidate, 'audio': state['audio'],
                                  'section_map': str(project / 'runtime/section_map.json')})
