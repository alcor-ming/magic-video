"""Read-only, advisory text diagnostics for sampled Studio states."""

from difflib import SequenceMatcher
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import subprocess

from visual_plan import VisualPlanError, markdown_structure_lines, plan_scene_rows


def normalize(text):
    # Preserve signs, decimal points, percentages and units for semantic review.
    punctuation = set('，。！？；：、“”‘’（）【】《》〈〉「」『』,!?;:"\'()[]{}')
    return ''.join(char for char in text if not char.isspace() and char not in punctuation)


def plan_information(text):
    scenes = plan_scene_rows(text)
    return ({identity: value for row in scenes.values() for identity, value in row['screens'].items()},
            {sid: list(row['screens']) for sid, row in scenes.items()})


def rhythm_diagnostics(samples, scenes, *, plan='', cues=None, mode=None):
    """Locate gaps in observed layer 2-4 events, never issue an acceptance verdict."""
    from explainer import find_cue
    events, findings, unverified, declared = [], [], [], []
    samples = sorted(samples, key=lambda item: item['time'])
    candidates = {}
    for sample in samples:
        if not sample.get('ready'):
            unverified.append({'reason': 'rhythm_sample_unavailable', 'time': sample['time']})
            continue
        unverified.extend(sample.get('motion_unverified', []))
        for candidate in sample.get('rhythm_candidates', []):
            candidates.setdefault(candidate['id'], []).append((sample['time'], candidate))
    allowed = {'text_reveal', 'b_enter', 'a_return', 'enter', 'exit', 'bounce', 'squash', 'point', 'state',
               'pan_start', 'pan_end', 'zoom_start', 'zoom_end', 'camera_start', 'camera_end', 'camera_turn', 'tween', 'tween_end', 'set',
               'motion_reveal', 'motion_emphasis', 'motion_exit', 'motion_transition', 'broll_moment'}
    for observations in candidates.values():
        candidate = observations[0][1]
        if candidate.get('unverified'):
            unverified.append({'reason': candidate['unverified'], 'time': candidate['time'], 'targets': candidate.get('targets', [])})
            continue
        at, duration = candidate['time'], candidate['duration']
        if candidate['kind'] not in allowed or candidate['layer'] not in {'stage', 'overlay', 'text'}:
            continue
        before = next((value for time, value in observations
                       if abs(time - candidate.get('before', max(0, at - .001))) < .00001), None)
        after = next((value for time, value in observations
                      if abs(time - candidate.get('after', at + (duration / 2 if duration > 0 else .001))) < .00001), None)
        if not before or not after:
            unverified.append({'reason': 'rhythm_event_not_sampled', 'time': at, 'kind': candidate['kind']})
            continue
        key = 'state_signature' if candidate['kind'] == 'state' else 'signature'
        changed = before.get(key) != after.get(key)
        opening = at == 0 and candidate['kind'] in {'text_reveal', 'b_enter', 'enter'} and after['visible']
        if (changed and (before['visible'] or after['visible'])) or opening:
            hit = {**{key: candidate[key] for key in ('id', 'time', 'kind', 'layer', 'scene')},
                   'targets': candidate.get('targets', []), 'target_node': candidate.get('target_node')}
            if candidate['kind'].startswith('camera_') and before.get('geometry') and after.get('geometry'):
                hit['direction'] = [b - a for a, b in zip(before['geometry'], after['geometry'])]
            events.append(hit)
    # Adjacent camera segments continuing in the same direction are one movement.
    redundant = set()
    for end in events:
        if end['kind'] != 'camera_end' or not end.get('direction'):
            continue
        for start in events:
            if (start['kind'] != 'camera_start' or not end.get('target_node')
                    or start.get('target_node') != end.get('target_node')
                    or abs(start['time'] - end['time']) > .00001 or not start.get('direction')):
                continue
            a, b = start['direction'], end['direction']
            norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
            if norm and sum(x*y for x, y in zip(a, b)) / norm > .999:
                redundant.update([start['id'], end['id']])
    events = [event for event in events if event.get('id') not in redundant]
    # Visible text content is a layer-specific observation, not a pixel/tween count.
    previous = None
    for sample in samples:
        if not sample.get('ready'):
            previous = None
            continue
        text = sorted((item.get('scene') or '', item.get('selector') or '', item['text'])
                      for item in sample.get('texts', []) if item.get('layer') == 'text')
        if previous is not None and text != previous[1]:
            events.append({'time': sample['time'], 'kind': 'observed_text_change', 'layer': 'text',
                           'scene': None, 'sample_window': [previous[0], sample['time']]})
        previous = (sample['time'], text)
    bounds = {scene['id']: (scene['start'], scene['start'] + scene['duration']) for scene in scenes}
    for sid, row in (plan_scene_rows(plan) if plan else {}).items():
        if sid not in bounds:
            continue
        screens, scheduled = row.get('screens', {}), {}
        planned = {identity: value['实际表达'] for identity, value in screens.items()}
        for event in ([] if row.get('plan_format') == '3.7.0' else row.get('events', [])):
            target = str(event.get('target') or '').lstrip('#')
            location = {'scene': sid, 'target': target or None, 'cue': event['cue'], 'change': event.get('change', '')}
            try:
                query = {'token': event['cue']} if isinstance(event['cue'], str) else event['cue']
                start = find_cue(cues, query)
                end = find_cue(cues, {**query, 'edge': 'end'}) if isinstance(query, dict) and 'token' in query else start
                if not target:
                    unverified.append({**location, 'reason': 'rhythm_declaration_target_missing'})
                elif not any(hit['layer'] == {2: 'stage', 3: 'overlay', 4: 'text'}.get(event['layer'])
                             and hit.get('scene') in {None, sid} and start <= hit['time'] <= end
                             and target in hit.get('targets', []) for hit in events):
                    findings.append({**location, 'kind': 'rhythm_declared_not_observed', 'start': start, 'end': end})
            except (ValueError, TypeError, KeyError) as error:
                unverified.append({**location, 'reason': 'rhythm_declaration_cue_unresolved', 'detail': str(error)})
            if event.get('layer') != 4:
                continue
            identities = [target] if target in planned else []
            try:
                at = find_cue(cues, event['cue'])
                scheduled.update((identity, at) for identity in identities)
            except (ValueError, TypeError, KeyError):
                pass
        if not scheduled and row.get('plan_format') != '3.7.0':
            unverified.append({'reason': 'lay_out_and_wait_requires_information_cue_visibility_mapping', 'scene': sid})
        for sample in samples:
            if not sample.get('ready') or not bounds[sid][0] <= sample['time'] < bounds[sid][1]:
                continue
            visible_text = normalize(''.join(item['text'] for item in sample.get('texts', [])
                                            if item.get('scene') == sid and item.get('layer') == 'text'))
            early = [identity for identity, at in scheduled.items() if at - sample['time'] > 2
                     and normalize(planned[identity]) and normalize(planned[identity]) in visible_text]
            if len(early) > len(planned) / 2:
                findings.append({'kind': 'suspected_lay_out_and_wait', 'scene': sid, 'time': sample['time'],
                                 'information_ids': early, 'planned_cues': {key: scheduled[key] for key in early}})
                break
        for item in row.get('exceptions', []):
            try:
                if item.get('kind') not in {'pause', 'talking_head'} or not isinstance(item.get('reason'), str) or not item['reason'].strip():
                    raise ValueError('Exception requires pause/talking_head kind and reason')
                start, end = (find_cue(cues, item[key]) for key in ('start_cue', 'end_cue'))
                if not bounds[sid][0] <= start < end <= bounds[sid][1]:
                    raise ValueError('Exception is outside its Scene')
                if item['kind'] == 'talking_head' and mode != 'talking_head':
                    raise ValueError('真人 interval requires talking_head mode')
                declared.append({**item, 'scene': sid, 'start': start, 'end': end,
                                 'status': 'declared_not_verified', 'approval': 'not_inferred'})
            except (ValueError, TypeError, KeyError) as error:
                unverified.append({'reason': 'rhythm_exception_unresolved', 'scene': sid, 'detail': str(error)})
    spans = []
    for start, end in sorted(bounds.values()):
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(end, spans[-1][1])
        else:
            spans.append([start, end])
    for start, end in spans:
        if not any(sample.get('ready') and start <= sample['time'] < end for sample in samples):
            unverified.append({'reason': 'rhythm_interval_not_sampled', 'start': start, 'end': end})
            continue
        points = sorted({start, end, *(event['time'] for event in events if start <= event['time'] <= end),
                         *(point for item in declared for point in (item['start'], item['end']) if start <= point <= end)})
        for left, right in zip(points, points[1:]):
            if right - left <= 2 or any(item['start'] <= left and right <= item['end'] for item in declared):
                continue
            findings.append({'kind': 'rhythm_gap', 'start': left, 'end': right, 'duration': right - left,
                             'scenes': [sid for sid, (a, b) in bounds.items() if a < right and b > left],
                             'basis': 'observed_events_only', 'coverage': 'sampled_timeline_and_helpers', 'verdict': None})
    unverified.append({'reason': 'finite_sampling_between_samples_requires_review'})
    return {'events': sorted(events, key=lambda item: item['time']), 'findings': findings,
            'declared_exceptions': declared, 'unverified': unverified, 'advisory_only': True}


def still_diagnostics(samples, rhythm, thresholds):
    """Finite sampled pixel differences, with explicit exclusions and no pass/fail."""
    excluded = [{'start': item['start'], 'end': item['end'], 'reason': 'talking_head'}
                for item in rhythm['declared_exceptions'] if item['kind'] == 'talking_head']
    for sample in samples:
        for item in sample.get('rhythm_candidates', []):
            if item['kind'] in {'camera_start', 'camera_turn', 'pan_start', 'zoom_start'} and item.get('duration', 0) > 0:
                span = {'start': item['time'], 'end': item['time'] + item['duration'], 'reason': 'continuous_camera'}
                if span not in excluded:
                    excluded.append(span)
    spans, unmeasured = [], list(excluded)
    current = None
    for sample in sorted(samples, key=lambda value: value['time']):
        measurement = sample.get('still')
        if not measurement:
            if not sample.get('ready'):
                current = None
                unmeasured.append({'time': sample['time'], 'reason': 'sample_unavailable'})
            continue
        start, end = measurement['from'], sample['time']
        if not sample.get('ready') or any(item['start'] < end and item['end'] > start for item in excluded):
            current = None
            continue
        if measurement['mean_delta'] > thresholds['pixel_mean_delta']:
            current = None
            continue
        if current is None or abs(current['end'] - start) > .00001:
            current = {'start': start, 'end': end}
            spans.append(current)
        else:
            current['end'] = end
    result = []
    for span in spans:
        span['duration'] = span['end'] - span['start']
        if span['duration'] < thresholds['still_seconds']:
            continue
        pauses = [item for item in rhythm['declared_exceptions'] if item['kind'] == 'pause' and item['start'] <= span['start'] and item['end'] >= span['end']]
        result.append({**span, 'kind': 'pixel_still', 'declared_exception': bool(pauses), 'exceptions': pauses})
    return {'intervals': result, 'unmeasured': unmeasured, 'thresholds': thresholds,
            'basis': 'layer_2_4_mean_pixel_difference', 'advisory_only': True}


def carry_diagnostics(samples, boundaries, *, fps=60, declared=None):
    result = []
    samples = {round(item['time'], 6): item for item in samples}
    for boundary in boundaries:
        if boundary <= 0:
            continue
        first = math.ceil(boundary * fps - 1e-7) / fps
        previous = max(0, first - 1 / fps)
        before = samples.get(round(previous, 6), {})
        after = samples.get(round(first, 6), {})
        if (not before.get('ready') or not after.get('ready')
                or abs(before.get('actual_time', before.get('time', 0)) - previous) > .00001
                or abs(after.get('actual_time', after.get('time', 0)) - first) > .00001):
            result.append({'time': boundary, 'status': 'unmeasured', 'reason': 'boundary_sample_unavailable'})
            continue
        sides = []
        for sample in (before, after):
            side = {}
            for item in sample.get('carry', []):
                side.setdefault(item['id'], []).append(item['box'])
            sides.append(side)
        left, right = sides
        for identity in sorted(set(left) | set(right) | set((declared or {}).get(round(boundary, 6), []))):
            a, b = left.get(identity, []), right.get(identity, [])
            entry = {'time': boundary, 'sample_times': [previous, first], 'id': identity, 'before': a, 'after': b}
            if len(a) != 1 or len(b) != 1:
                entry.update(status='unpaired', reason='missing_or_duplicate_marker')
            else:
                entry.update(status='paired', delta=dict(zip(('x', 'y', 'width', 'height'), [round(y - x, 6) for x, y in zip(a[0], b[0])])))
            result.append(entry)
    return {'boundaries': result, 'units': 'composition_px', 'advisory_only': True}


def source_sections(script, research, information):
    sources = {}
    for name, text in [('SCRIPT.md', script), ('RESEARCH.md', research)]:
        text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.S)
        text = re.sub(r'<!-- scene-index:start -->.*?<!-- scene-index:end -->', '', text, flags=re.S)
        chunks = re.split(r'<!--\s*([A-Za-z]+\d+)\s*-->', text)
        if name == 'SCRIPT.md':
            sources[name] = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        for i in range(1, len(chunks), 2):
            identity = chunks[i]
            if name == 'SCRIPT.md' or any(identity in row.get('信息 ID / 来源', '') for row in information.values()):
                sources[f'{name}#{identity}'] = chunks[i + 1]
        if name == 'RESEARCH.md':
            # Only adopted, explicitly referenced research sections are candidates.
            headings = list(re.finditer(r'^#{1,6}\s+(.+)$', text, re.M))
            for index, heading in enumerate(headings):
                title = heading[1].strip()
                if any(title in row.get('信息 ID / 来源', '') for row in information.values()):
                    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
                    sources[f'{name}#{title}'] = text[heading.end():end]
    return sources


class StaticText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, text):
        if not self.skip and text.strip():
            self.values.append({'text': text.strip(), 'line': self.getpos()[0]})


def static_inventory(project, dependencies):
    entries = []
    for name in dependencies:
        path = project / name
        if path.suffix in {'.html', '.htm', '.svg'}:
            parser = StaticText()
            parser.feed(path.read_text(encoding='utf-8-sig'))
            entries.extend({'file': name, **entry} for entry in parser.values)
        elif path.suffix == '.json':
            try:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue

            def strings(value, pointer=''):
                if isinstance(value, str):
                    entries.append({'file': name, 'pointer': pointer, 'text': value})
                elif isinstance(value, dict):
                    for key, item in value.items():
                        strings(item, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        strings(item, pointer + '/' + str(index))
            strings(data)
    return entries


def explainer_diagnostics(project, dependencies, lock, plan=""):
    """Static five-layer hints supplement D1; they are never visual acceptance."""
    if not lock or "capabilities" not in lock and lock.get("mode") not in ("math", "english", "explainer", "showcase"):
        return {"findings": [], "unverified": []}
    from visual_plan import Composition
    from explainer import installed_assets
    from component_harness import ComponentError, validate_component_release
    from urllib.parse import unquote, urlsplit
    findings, unverified = [], []
    nodes = {}
    for name in dependencies:
        if Path(name).suffix.lower() in {".html", ".htm"}:
            nodes[name] = Composition((project / name).read_text(encoding="utf-8-sig")).nodes
    root = nodes.get("index.html", [])
    layers = [attrs.get("data-hf-layer") for _, attrs in root]
    import designs
    expected = set(designs.capabilities(lock)["layers"]["required"])
    for layer in sorted(expected - set(layers)):
        findings.append({"kind": "explainer_layer_missing", "file": "index.html", "layer": layer})
    captions = [(name, attrs) for name, entries in nodes.items() for _, attrs in entries
                if attrs.get("data-hf-layer") == "captions"]
    enabled = lock.get("selection", {}).get("captions", False)
    if len(captions) != int(enabled) or captions and captions[0][0] != "index.html":
        findings.append({"kind": "captions_lock_mismatch", "enabled": enabled, "hosts": len(captions)})
    for name, entries in nodes.items():
        if name == "index.html":
            continue
        if expected and any("data-composition-id" in attrs for _, attrs in entries):
            local = {attrs.get("data-hf-layer") for _, attrs in entries}
            for layer in sorted((expected - {"background"}) - local):
                findings.append({"kind": "explainer_layer_missing", "file": name, "layer": layer})
    try:
        assets = installed_assets(project)
    except (ValueError, OSError, ComponentError) as exc:
        assets = {}
        unverified.append({"reason": "asset_closure_invalid", "detail": str(exc)})
    allowed = {ref: (project / item["vendor_path"] / item["metadata"]["entry"]).resolve()
               for ref, item in assets.items() if item["metadata"].get("kind") == "media"
               and Path(item["metadata"]["entry"]).suffix.lower() == ".mp3"}
    for name, entries in nodes.items():
        for tag, attrs in entries:
            character = attrs.get("data-character-ref")
            if character and (
                    character not in assets or assets[character]["metadata"].get("kind") != "character"):
                findings.append({"kind": "character_asset_outside_closure", "file": name, "ref": character})
            if tag != "audio" or attrs.get("data-audio-role") == "voice":
                continue
            ref, src = attrs.get("data-asset-ref"), attrs.get("src", "")
            url = urlsplit(src)
            path = (project / name).parent / unquote(url.path)
            valid = not url.scheme and not url.netloc and path.resolve() in allowed.values()
            if ref:
                valid = valid and allowed.get(ref) == path.resolve()
            if not valid:
                findings.append({"kind": "sound_asset_outside_closure", "file": name, "ref": ref, "src": src})
    unverified.append({"reason": "dynamic_hosts_and_refs_require_browser_review"})
    return {"findings": findings, "unverified": unverified}


def checked_exceptions(entries, sources, scene_ids):
    if not isinstance(entries, list):
        raise VisualPlanError('Exceptions must be a JSON array of scene, text, source, reason objects')
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'scene', 'text', 'source', 'reason'}
                or any(not isinstance(entry.get(key), str) or not entry[key].strip()
                                              for key in ('scene', 'text', 'source', 'reason'))
                or entry['scene'] not in scene_ids or entry['source'] not in sources
                or not normalize(entry['text'])
                or normalize(entry['text']) not in normalize(sources[entry['source']])):
            raise VisualPlanError('Exception needs an exact source-backed fragment, existing Scene and confirmation reason')
    return entries


def copy_match(text, sources):
    best = None
    for source, original in sources.items():
        reference = normalize(original)
        if not reference:
            continue
        # ponytail: quadratic matching; chunk by source Anchor if large sources become slow.
        blocks = SequenceMatcher(None, reference, text, autojunk=False).get_matching_blocks()
        score = sum(block.size for block in blocks) / len(text)
        if best is None or score > best['coverage']:
            best = {'source': source, 'coverage': score, 'continuous': max(block.size for block in blocks) / len(text)}
    return best


def resolve_information(text, choices, information):
    """Assign text to one Plan block by exact string evidence only; ambiguity stays unresolved."""
    value = normalize(text)
    blocks = {info: information[info]['实际表达'] for info in choices if info in information}
    if not value or not blocks:
        return ''
    exact = [info for info, planned in blocks.items()
             if value == normalize(planned) or any(value == normalize(line) for line in planned.splitlines())]
    if exact:
        return exact[0] if len(exact) == 1 else ''
    contained = [info for info, planned in blocks.items() if value in normalize(planned)]
    return contained[0] if len(contained) == 1 else ''


def text_diagnostics(samples, script, research, plan, *, minimum=20, similarity=0.8, exceptions=None, scenes=None,
                     scene_ids=None, mode=None, capabilities=None):
    information, mapping = plan_information(plan)
    outside = {sid: ids for sid, ids in mapping.items() if scene_ids is not None and sid not in scene_ids}
    if scene_ids is not None:
        mapping = {sid: ids for sid, ids in mapping.items() if sid in scene_ids}
        selected = {info for ids in mapping.values() for info in ids}
        information = {info: row for info, row in information.items() if info in selected}
    sources = source_sections(script, research, information)
    exceptions = checked_exceptions(exceptions or [], sources, mapping)
    groups, findings, unverified, excluded, source_groups = {}, [], [], [], {}
    covered, failed = set(), set()
    for sample in sorted(samples, key=lambda item: item['time']):
        active = {scene['id'] for scene in scenes or []
                  if scene['start'] <= sample['time'] < scene['start'] + scene['duration']}
        if not sample.get('ready'):
            failed.update(active)
            failed.update(item.get('scene') for item in sample.get('texts', []))
            continue
        covered.update(active)
        for item in sample.get('texts', []):
            if ('text' in capabilities['layers']['required'] if capabilities is not None else mode in ('math', 'english', 'explainer')) and item.get('layer') != 'text' and not item.get('embedded'):
                continue
            scene, info = item.get('scene', ''), item.get('info', '')
            if scene in outside:
                continue
            if scene not in mapping:
                unverified.append({'reason': 'unmapped_scene', 'time': sample['time'], 'text': item['text']})
                continue
            covered.add(scene)
            text = item['text'].strip()
            if not text:
                continue
            choices = mapping[scene]
            if not info:
                info = resolve_information(text, choices, information)
            if info not in choices or info not in information:
                info = ''
            # Unresolved text keeps its element identity instead of merging into one Scene string.
            key = (scene, info, '' if info else item.get('selector', '') or text)
            group = groups.setdefault(key, {'parts': [], 'locations': [], 'times': []})
            # Deduplicate persistent and progressively revealed text across seek samples.
            if not any(normalize(text) in normalize(part) for part in group['parts']):
                group['parts'] = [part for part in group['parts'] if normalize(part) not in normalize(text)]
                group['parts'].append(text)
            location = item.get('selector', '')
            if location not in group['locations']:
                group['locations'].append(location)
            group['times'].extend([item['start'], item['end']] if item.get('embedded') else [sample['time']])
    for (scene, info, _), group in groups.items():
        parts = group['parts']
        if info:
            # Several DOM nodes may form one block; compare them in Plan order, not reveal order.
            expected = normalize(information[info]['实际表达'])
            parts = sorted(parts, key=lambda part: (expected.find(normalize(part)) % (len(expected) + 1)))
        text = ''.join(parts)
        normalized = normalize(text)
        location = {'scene': scene, 'info': info or None, 'text': text,
                    'selectors': group['locations'], 'start': min(group['times']), 'end': max(group['times'])}
        if not info:
            unverified.append({**location, 'reason': 'semantic_mapping_requires_review'})
        else:
            planned = information[info]['实际表达']
            expected = normalize(planned)
            if expected != normalized:
                remaining = iter(expected)
                # ponytail: half-length is a relative shortening hint; semantic equivalence needs review.
                truncated = bool(normalized) and len(normalized) < len(expected) and (
                    all(char in remaining for char in normalized) or len(normalized) <= len(expected) / 2)
                findings.append({**location, 'kind': 'plan_information_truncated' if truncated else 'plan_implementation_difference', 'planned': planned,
                                 'source': information[info].get('信息 ID / 来源', '')})
        for entry in exceptions:
            if entry['scene'] == scene and normalize(entry['text']) in normalized:
                normalized = normalized.replace(normalize(entry['text']), '')
                excluded.append(entry)
        if info and normalized:
            reference = information[info].get('信息 ID / 来源', '')
            anchors = re.findall(r'\b[A-Z]+\d+\b', reference)
            for anchor in anchors:
                if anchor == info:
                    continue
                key = next((key for key in sources if key.endswith('#' + anchor)), None)
                if key:
                    source_groups.setdefault(key, []).append((location, normalized))
        if len(normalized) < minimum:
            continue
        best = copy_match(normalized, sources)
        if best and best['coverage'] >= similarity:
            findings.append({**location, 'kind': 'suspected_copy', **best,
                             'semantic_review': 'Check negation, numbers, units, attribution and necessary quotation; no automatic verdict'})
    for source, members in source_groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda item: item[0]['start'])
        combined = ''.join(dict.fromkeys(text for _, text in ordered))
        if len(combined) < minimum or any(combined == text for _, text in ordered):
            continue
        best = copy_match(combined, {source: sources[source]})
        if best and best['coverage'] >= similarity:
            findings.append({'kind': 'suspected_split_copy', 'scenes': list(dict.fromkeys(item['scene'] for item, _ in ordered)),
                             'text': combined, 'members': [item for item, _ in ordered], **best,
                             'semantic_review': 'Source-anchor aggregation is a hint, not proof of one semantic unit'})
    unresolved = {scene for scene, info, _ in groups if not info}
    for scene, identities in mapping.items():
        for info in identities:
            if (scene, info, '') in groups:
                continue
            row = information.get(info)
            entry = {'scene': scene, 'info': info, 'source': row.get('信息 ID / 来源', '') if row else ''}
            if not row:
                unverified.append({**entry, 'reason': 'plan_information_undefined'})
            elif scene in unresolved:
                unverified.append({**entry, 'reason': 'plan_information_mapping_unresolved'})
            elif scene in covered and scene not in failed:
                findings.append({**entry, 'kind': 'plan_information_missing', 'planned': row['实际表达']})
            else:
                unverified.append({**entry, 'reason': 'plan_information_not_observed'})
    for info, row in information.items():
        if not any(info in identities for identities in mapping.values()):
            unverified.append({'info': info, 'reason': 'plan_information_not_observed', 'source': row.get('信息 ID / 来源', '')})
    unverified.append({'reason': 'external_or_unresolved_adopted_sources_require_review'})
    return {'findings': findings, 'unverified': unverified, 'confirmed_exceptions': excluded,
            'out_of_scope': [{'scene': sid, 'information_ids': ids, 'reason': 'outside_reference_scope'}
                             for sid, ids in outside.items()],
            'sources': list(sources), 'observed_groups': len(groups)}


def parameters(args):
    values = {'step': args.step, 'width': args.width, 'timeout_ms': args.timeout_ms}
    if (any(not math.isfinite(value) or value <= 0 for value in values.values())
            or not 160 <= args.width <= 4096 or not 100 <= args.timeout_ms <= 30000
            or args.minimum < 1 or not math.isfinite(args.similarity) or not 0 < args.similarity <= 1):
        raise VisualPlanError('Invalid diagnostic parameters: positive finite values, similarity <=1, width 160..4096, timeout 100..30000')
    return values


MAX_EXPLICIT_TIMES = 120


def sample_times(raw):
    """Parse --times; None when absent. Validation happens before any browser launch."""
    if raw is None:
        return None
    try:
        times = sorted({round(float(item), 6) for item in raw.split(',') if item.strip()})
    except ValueError:
        times = []
    if not times or len(times) > MAX_EXPLICIT_TIMES or any(not math.isfinite(time) or time < 0 for time in times):
        raise VisualPlanError(f'Invalid --times: 1..{MAX_EXPLICIT_TIMES} comma-separated non-negative seconds')
    return times


def sample_scope(scenes, span=None, times=None):
    """Limit sampling to a span or explicit times; None keeps the whole project.

    Return {'range': [start, end], 'times': [...] or None, 'scenes': overlapping scenes}.
    """
    if span is None and times is None:
        return None
    total = max((scene['start'] + scene['duration'] for scene in scenes), default=0)
    if span is not None:
        start, end = span
        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start or start >= total:
            raise VisualPlanError(f'Invalid --range: need 0 <= START < END and START before the project end {total:g}s')
        end = min(end, total)
    else:
        start, end = times[0], times[-1]
    if times is not None and any(time < start or time > end or time > total for time in times):
        raise VisualPlanError('--times must lie inside --range and the project duration')
    selected = [scene for scene in scenes if scene['start'] <= end and scene['start'] + scene['duration'] > start]
    if not selected:
        raise VisualPlanError('Sampling scope does not overlap any Scene')
    return {'range': [start, end], 'times': times, 'scenes': selected}


def sampling_summary(samples):
    """Count verified samples so an empty or stale run is never mistaken for a clean one."""
    ready = sum(1 for sample in samples if sample.get('ready'))
    summary = {'samples': len(samples), 'ready': ready}
    if not ready:
        summary['hint'] = 'No sample was verified: run preview stop, then preview open, and rerun this command once'
    return summary


def probe(request, node='node'):
    try:
        result = subprocess.run([node, str(Path(__file__).with_name('visual_probe.mjs'))],
                                input=json.dumps(request), capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=1800)
        if result.returncode:
            raise VisualPlanError(f'Studio sampling failed: {result.stderr[:1000]}')
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get('samples'), list):
            raise VisualPlanError('Studio sampling returned invalid evidence')
        return data
    except (OSError, subprocess.TimeoutExpired, ValueError, VisualPlanError) as error:
        return {'samples': [], 'timeline': [],
                'unverified': [{'reason': 'studio_sampling_unavailable', 'detail': str(error)}]}
