"""Design-card catalogue and its small reference mechanism catalogue.

Product lines are the ``type: design`` cards discovered across the built-in and
user roots; material cards never enter a selection list. ``lines.yaml`` keeps
only mechanisms and behaviour changes; it no longer holds a second copy of
modifiable defaults. Retired identities stay locatable for reading, but creation
goes through :func:`designs.require` and rejects them with reselect guidance.
"""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path

import designs

# A mechanism/behaviour entry names one line; uninstalled personal cards stay
# valid references even when the current catalog only holds the built-in cards.
LINE_REFERENCE = re.compile(r'[a-z][a-z0-9-]*(?:/[a-z0-9-]+)?')

# Retired identity -> (successor design, legacy appearance mode, legacy settings).
HISTORICAL_META = {
    'explainer': ('stage-full', 'explainer', {'direction_approval': True, 'critic.provider': 'external', 'critic.model': '', 'critic.max_rounds': 1}),
    'explainer/math-rap': ('math', 'explainer', {'direction_approval': True, 'critic.provider': 'external', 'critic.model': '', 'critic.max_rounds': 1}),
    'showcase/science': ('collage', 'showcase', {'direction_approval': True, 'critic.provider': 'off', 'critic.model': '', 'critic.max_rounds': 1}),
}


def _read(name: str) -> dict:
    # JSON is the repository's dependency-free YAML subset.
    return json.loads(Path(__file__).with_name(name + '.yaml').read_text(encoding='utf-8'))


def historical() -> dict:
    found = designs.design_catalog()
    out = {}
    for identity, (successor, mode, settings_defaults) in HISTORICAL_META.items():
        if successor not in found:
            continue
        card = deepcopy(found[successor])
        card.update(id=identity, version=1, mode=mode, settings_defaults=settings_defaults)
        card['capabilities'] = designs.legacy_capabilities(mode)
        if identity == 'explainer/math-rap':
            card['capabilities']['checks'].append('math')
            card['capabilities']['research_template'] = 'MATH_RESEARCH.template.md'
        out[identity] = card
    return out


def catalogue(name):
    if name == 'lines':
        return {'version': 2, 'lines': {**designs.design_catalog(), **historical()}}
    return _read(name)


def designs_catalogue():
    return designs.design_catalog()


def _identity(state):
    if isinstance(state, dict) and state.get('design'):
        return state['design']
    if isinstance(state, dict) and state.get('mode') == 'showcase':
        suffix = state.get('submodule')
        if not suffix:
            lock = state.get('appearance_lock')
            suffix = lock.get('submodule') if isinstance(lock, dict) else None
        return 'showcase/' + suffix if suffix else 'showcase'
    return designs.identify(state)


def select(state):
    """Resolve a line for reading. Retired ids map to their successor view."""
    identity = _identity(state)
    if identity is None:
        raise ValueError('No design selected; ' + designs.reselect_hint())
    if identity in HISTORICAL_META:
        value = historical().get(identity)
        if value is None:
            raise ValueError('Historical design requires the personal package: ' + identity)
        return deepcopy(value)
    if identity == 'showcase':
        raise ValueError("Product line 'showcase' is retired; reselect a design")
    return deepcopy(designs.require(identity))


def _legacy_math(state):
    identity = _identity(state)
    if identity in ('math', 'explainer/math-rap'):
        return True
    binding = state.get('series_binding') if isinstance(state, dict) else None
    has_math_binding = isinstance(binding, dict) and (
        binding.get('design') == 'math' or binding.get('spec') == 'math-rap' or binding.get('mode') == 'math')
    if not has_math_binding:
        return False
    return identity is None or identity not in designs.DESIGN_IDS or identity == 'math'


def capabilities(state):
    """Resolve live/frozen card capabilities, keeping old mode records read-only."""
    if state.get('design_snapshot') is not None or state.get('design_live') and state.get('line'):
        card = frozen(state)
        if 'capabilities' in card:
            return designs.capabilities(card)
        caps = designs.capabilities(card)
    elif 'capabilities' in state:
        return designs.capabilities(state)
    else:
        lock = state.get('appearance_lock') or {}
        if 'capabilities' in lock:
            return designs.capabilities(lock)
        caps = designs.legacy_capabilities(state.get('mode', 'explainer'))
    if _legacy_math(state):
        for check in ['math'] + (['math-complete'] if _identity(state) == 'math' else []):
            if check not in caps['checks']:
                caps['checks'].append(check)
        caps['research_template'] = 'MATH_RESEARCH.template.md'
    return caps


def has_check(state, check):
    if (not any(state.get(key) for key in ('capabilities', 'design_snapshot', 'design_live'))
            and not (state.get('appearance_lock') or {}).get('capabilities')
            and state.get('mode') not in (None, *designs.MODES)):
        return check == 'math' and _legacy_math(state)
    return check in capabilities(state)['checks']


def is_math(state):
    return has_check(state, 'math')


def frozen(state):
    line = state.get('line') if isinstance(state, dict) else None
    if line is None:
        return None
    if state.get('design_snapshot') is not None or state.get('design_sha256') is not None:
        card = state['design_snapshot']
        if (not isinstance(card, dict) or line != {key: card.get(key) for key in ('id', 'version')}
                or card_digest(card) != state.get('design_sha256')):
            raise ValueError('Frozen design snapshot changed')
        return deepcopy(card)
    if state.get('design_live'):
        return designs.require(line['id'])
    known = catalogue('lines')['lines']
    if not isinstance(line, dict) or line.get('id') not in known or type(line.get('version')) is not int:
        raise ValueError('Invalid frozen product line')
    if set(line) != {'id', 'version'} or line['version'] != known[line['id']]['version']:
        raise ValueError('Unsupported frozen product line version')
    return deepcopy(known[line['id']])


def card_digest(card):
    return hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bind(state):
    """Freeze a design (or locate a historical line) as an {id, version} binding."""
    identity = state if isinstance(state, str) else _identity(state)
    known = catalogue('lines')['lines']
    if identity in known and identity not in designs.DESIGN_IDS:
        card = known[identity]
        return {'id': card['id'], 'version': card['version']}
    card = designs.require(identity)
    return {'id': card['id'], 'version': card['version']}


def validate_catalogues():
    found = designs.design_catalog()
    for identity, card in found.items():
        fields = card.get('fields')
        if not isinstance(fields, list) or not set(fields) <= set(designs.FIELDS):
            raise ValueError('Invalid design field declaration: ' + identity)
        for paths in card['stages'].values():
            if any(not ((Path(__file__).resolve().parents[1] if path.startswith('.studio/') else designs.card_path(identity)) / path).is_file() for path in paths):
                raise ValueError('Missing design rule file: ' + identity)
    ids = set()
    for item in catalogue('mechanisms')['mechanisms']:
        if (set(item) != {'id', 'mechanism', 'lines', 'transfer', 'source'} or item['id'] in ids or not item['lines']
                or not isinstance(item['lines'], list)
                or any(not isinstance(name, str) or not LINE_REFERENCE.fullmatch(name) for name in item['lines'])):
            raise ValueError('Invalid reference mechanism')
        if any(not isinstance(item[key], str) or not item[key].strip() for key in ('id', 'mechanism', 'transfer', 'source')) or not item['source'].startswith('https://'):
            raise ValueError('Invalid reference mechanism fields')
        ids.add(item['id'])
    for change in catalogue('behavior-changes')['changes']:
        if (set(change) != {'version', 'lines', 'summary'}
                or not re.fullmatch(r'\d+\.\d+\.\d+', change['version'])
                or not change['lines'] or not isinstance(change['lines'], list)
                or any(not isinstance(name, str) or not LINE_REFERENCE.fullmatch(name) for name in change['lines'])
                or not isinstance(change['summary'], str) or not change['summary'].strip()):
            raise ValueError('Invalid behavior change')
    return found
