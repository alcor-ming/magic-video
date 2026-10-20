"""Declared teaching content and real speech cues, without judging teaching quality."""

import math
import re

from visual_plan import parse_scene_blocks


def _text(value):
    return (isinstance(value, str) and bool(value.strip())
            and not re.search(r'<[^>]+>|__\w+__', value)
            and value.strip().lower() not in {'todo', 'tbd', '待填写'})


def _cue(value):
    if isinstance(value, str):
        return _text(value)
    return (isinstance(value, dict) and _text(value.get('token'))
            and not set(value) - {'token', 'nth', 'within', 'edge'}
            and ('nth' not in value or type(value['nth']) is int and value['nth'] > 0)
            and ('edge' not in value or value['edge'] in ('start', 'end'))
            and ('within' not in value or isinstance(value['within'], list)
                 and len(value['within']) == 2
                 and all(type(n) in (int, float) and math.isfinite(n) for n in value['within'])
                 and 0 <= value['within'][0] <= value['within'][1]))


def parse_plan(text):
    plans = parse_scene_blocks(text, 'english-plan')
    from visual_plan import markdown_structure_lines
    count = sum(bool(re.fullmatch(r' {0,3}(?:`{3,}|~{3,})english-plan\s*', line[0]))
                for line in markdown_structure_lines(text))
    if count != len(plans):
        raise ValueError('english_plan_outside_scene')
    definitions, pronounced = {}, set()
    for scene, plan in plans.items():
        def fail(code):
            raise ValueError(f'{scene}: {code}')

        if (not isinstance(plan, dict) or set(plan) != {'words', 'cues', 'recall'}
                or any(not isinstance(plan[key], list) for key in plan)
                or not plan['words'] or not plan['cues']):
            fail('invalid_english_plan')
        words = {}
        for item in plan['words']:
            required = {'word', 'sense', 'pronunciation', 'spelling'}
            if (not isinstance(item, dict) or not required <= item.keys()
                    or set(item) - required - {'mnemonic', 'example'}
                    or not all(_text(item[key]) for key in ('word', 'sense', 'spelling'))):
                fail('invalid_english_word')
            word = item['word']
            if word in words:
                fail('duplicate_english_word')
            if item['spelling'] != word:
                fail('english_spelling_mismatch')
            pronunciation = item['pronunciation']
            if (not isinstance(pronunciation, dict) or set(pronunciation) != {'source', 'language'}
                    or not _text(pronunciation['source'])
                    or not isinstance(pronunciation['language'], str)
                    or not re.fullmatch(r'en(?:-[A-Za-z]{2,8})*', pronunciation['language'])):
                fail('invalid_english_pronunciation_source')
            if 'mnemonic' in item:
                mnemonic = item['mnemonic']
                if (not isinstance(mnemonic, dict) or set(mnemonic) != {'kind', 'text'}
                        or mnemonic['kind'] not in ('homophone', 'association', 'spelling')
                        or not _text(mnemonic['text'])):
                    fail('invalid_english_mnemonic')
            if 'example' in item:
                example = item['example']
                if (not isinstance(example, dict) or set(example) != {'text', 'meaning', 'fictional'}
                        or not _text(example['text']) or not _text(example['meaning'])
                        or type(example['fictional']) is not bool):
                    fail('invalid_english_example')
            definition = {key: item[key] for key in required}
            if word in definitions and definitions[word] != definition:
                fail('english_word_definition_changed')
            definitions[word] = definition
            words[word] = item
        for event in plan['cues']:
            if (not isinstance(event, dict) or set(event) != {'word', 'cue', 'target', 'action'}
                    or not isinstance(event['word'], str) or event['word'] not in words
                    or not _cue(event['cue']) or not _text(event['target'])
                    or event['action'] not in ('pronounce', 'reveal', 'emphasize', 'hide', 'answer')):
                fail('invalid_english_cue')
            if event['action'] == 'pronounce':
                token = event['cue'] if isinstance(event['cue'], str) else event['cue']['token']
                if not re.search(r'(?<![A-Za-z])' + re.escape(event['word']) + r'(?![A-Za-z])', token, re.I):
                    fail('english_pronunciation_cue_mismatch')
                pronounced.add(event['word'])
        for recall in plan['recall']:
            if (not isinstance(recall, dict)
                    or set(recall) != {'word', 'task', 'prompt', 'answer', 'target', 'start_cue', 'end_cue'}
                    or not isinstance(recall['word'], str) or recall['word'] not in words
                    or recall['task'] not in ('spelling', 'meaning')
                    or not all(_text(recall[key]) for key in ('prompt', 'answer', 'target'))
                    or not all(_cue(recall[key]) for key in ('start_cue', 'end_cue'))):
                fail('invalid_english_recall')
            if recall['task'] == 'spelling' and recall['answer'] != recall['word']:
                fail('english_recall_spelling_mismatch')
    if set(definitions) - pronounced:
        raise ValueError('english_missing_pronunciation_cue: ' + ', '.join(sorted(set(definitions) - pronounced)))
    return plans


def check(text, cues=None, scenes=None):
    """Return findings; absent audio evidence stays explicitly unverified."""
    from explainer import find_cue, validate_cues
    plans = parse_plan(text)
    if cues is None:
        return [{'code': 'english_timing_unverified', 'scene': sid,
                 'message': 'Formal speech alignment is required'} for sid in plans]
    validate_cues(cues)
    bounds = {scene['id']: (scene['start'], scene['start'] + scene['duration']) for scene in scenes or []}
    findings = []
    for sid, plan in plans.items():
        def report(code, message):
            findings.append({'code': code, 'scene': sid, 'message': message})

        def resolve(query, endpoint=False):
            at = find_cue(cues, query)
            if scenes is not None and (sid not in bounds or at < bounds[sid][0]
                                       or at > bounds[sid][1] or at == bounds[sid][1] and not endpoint):
                raise ValueError('cue_outside_scene')
            return at

        previous = -1
        for event in plan['cues']:
            try:
                at = resolve(event['cue'])
                if at < previous:
                    report('english_cue_order', event['word'])
                previous = at
            except ValueError as error:
                report('english_unresolved_cue', str(error))
        for recall in plan['recall']:
            try:
                start, end = resolve(recall['start_cue']), resolve(recall['end_cue'], endpoint=True)
                if end <= start:
                    report('english_recall_interval', recall['word'])
            except ValueError as error:
                report('english_unresolved_cue', str(error))
    return findings
