"""Render SFX from editable SuperCollider/jsfxr recipes or the earshot sound bank into verified WAV and MP3 assets."""
from pathlib import Path
import argparse
import json
import math
import os
import re
import subprocess
import tempfile

from tts import digest, json_bytes, wav_info
from sfx_import import hit_offset
from windows_runtime import validate_review_path
from component_harness import package_write_lock


EARSHOT_ID = re.compile(r'[a-z0-9_]+/[a-z0-9_]+')
EARSHOT_KEYS = {'id', 'seed', 'duration', 'apex', 'pitch', 'peak_db'}


def earshot_parameters(parameters):
    """Bank id plus the knobs earshot edits in the recipe itself; nothing is resampled."""
    if not isinstance(parameters, dict) or set(parameters) - EARSHOT_KEYS or not isinstance(parameters.get('id'), str):
        raise ValueError('earshot SFX needs a bank id and only seed/duration/apex/pitch/peak_db')
    if not EARSHOT_ID.fullmatch(parameters['id']):
        raise ValueError('earshot id must be <category>/<member>; list them with earshot sfx list')
    for key, low, high in [('duration', 0.02, 30), ('apex', 0, 30), ('peak_db', -60, 0)]:
        value = parameters.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high):
            raise ValueError('Invalid SFX ' + key)
    if 'seed' in parameters and (type(parameters['seed']) is not int or not 0 <= parameters['seed'] <= 2147483647):
        raise ValueError('SFX seed must be a nonnegative 31-bit integer')
    if 'pitch' in parameters and (not isinstance(parameters['pitch'], (str, int, float)) or isinstance(parameters['pitch'], bool)):
        raise ValueError('Invalid SFX pitch')
    return dict(parameters)


def render_earshot(params, wav, stage, earshot):
    flags = {'seed': '--seed', 'duration': '--dur', 'apex': '--apex', 'pitch': '--pitch', 'peak_db': '--peak'}
    command = [earshot, 'sfx', 'render', params['id'], '-o', str(wav), '--json']
    for key, flag in flags.items():
        if key in params:
            command += [flag, str(params[key])]
    result = subprocess.run(command, cwd=stage, stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    (stage / 'render.log').write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError('earshot SFX rendering failed: ' + result.stderr.decode(errors='replace')[-1200:])
    meta = json.loads(result.stdout)['meta']
    listing = subprocess.run([earshot, 'sfx', 'list', '--json', '--category', params['id'].split('/')[0]],
                             cwd=stage, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    if listing.returncode:
        raise ValueError('earshot sfx list failed: ' + listing.stderr.decode(errors='replace')[-600:])
    return 'earshot bank ' + json.loads(listing.stdout)['version'], meta


def generate(source, parameters, output, *, engine='supercollider', sclang='sclang', node='node', ffmpeg='ffmpeg',
             earshot='earshot'):
    if engine == 'earshot':
        return generate_earshot(parameters, output, earshot=earshot, ffmpeg=ffmpeg)
    if engine not in {'supercollider', 'jsfxr'}:
        raise ValueError('Unknown SFX engine')
    allowed = {'kind', 'seed', 'gain'} | ({'duration'} if engine == 'supercollider' else set())
    if not isinstance(parameters, dict) or set(parameters) - allowed:
        raise ValueError('Unknown SFX parameter')
    params = {**({'duration': 0.8} if engine == 'supercollider' else {}), 'seed': 1, 'gain': 0.5, **parameters}
    if params.get('kind') not in {'click', 'whoosh', 'riser', 'fall', 'impact'}:
        raise ValueError('Unknown SFX kind')
    for key, low, high in [('duration', 0.08, 30), ('gain', 0, 1)]:
        if key not in params:
            continue
        value = params[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid SFX ' + key)
    if type(params['seed']) is not int or not 0 <= params['seed'] <= 2147483647:
        raise ValueError('SFX seed must be a nonnegative 31-bit integer')
    source = Path(source) if source is not None else Path(__file__).with_name('sfx') / ('render.scd' if engine == 'supercollider' else 'jsfxr.mjs')
    source_bytes = source.read_bytes()
    output = Path(output).absolute()
    validate_review_path(output)
    if output.exists():
        raise ValueError('SFX output already exists; choose a new candidate')
    output.parent.mkdir(parents=True, exist_ok=True)
    with package_write_lock(output.parent / ('.' + output.name + '.lock')), tempfile.TemporaryDirectory(prefix='.sfx-', dir=output.parent) as temporary:
        if output.exists():
            raise ValueError('SFX output already exists; choose a new candidate')
        stage = Path(temporary)
        recipe = stage / ('source.scd' if engine == 'supercollider' else 'source.mjs')
        recipe.write_bytes(source_bytes)
        wav = stage / 'audio.wav'
        if engine == 'supercollider':
            version = subprocess.run([sclang, '-v'], check=True, capture_output=True, text=True).stdout.strip()
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'HYPERFRAMES_SFX_OUTPUT': str(wav),
                   'XDG_CONFIG_HOME': str(stage / 'config'), 'XDG_DATA_HOME': str(stage / 'data')}
            env.update({'HYPERFRAMES_SFX_' + key.upper(): str(value) for key, value in params.items()})
            result = subprocess.run([sclang, '-D', str(recipe)], env=env, cwd=stage,
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        else:
            parameter_file = stage / 'parameters.json'
            parameter_file.write_bytes(json_bytes(params))
            result = subprocess.run([node, str(source.resolve()), '--parameters', str(parameter_file),
                                     '--output', str(wav)], capture_output=True, timeout=120)
        (stage / 'render.log').write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(engine + ' SFX rendering failed: ' + result.stderr.decode(errors='replace')[-1200:])
        if engine == 'jsfxr':
            generated = json.loads((stage / 'audio.wav.json').read_text())
            if generated['wav_sha256'] != digest(wav.read_bytes()) or generated['parameters'] != params:
                raise ValueError('jsfxr result does not match the request')
            version = generated['engine_version']
        info = wav_info(wav)
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(wav), '-codec:a', 'libmp3lame',
                        '-q:a', '2', str(stage / 'audio.mp3')], check=True, capture_output=True, timeout=60)
        offset, estimated = hit_offset(wav)
        if params['gain'] == 0:
            offset, estimated = 0, False
        elif not estimated:
            raise ValueError('SFX has no measurable audible onset')
        manifest = {'engine': engine, 'engine_version': version, 'source_sha256': digest(source_bytes), 'parameters': params,
                    'files': {name: digest((stage / name).read_bytes()) for name in (recipe.name, 'audio.wav', 'audio.mp3')},
                    **info, 'hit_offset': offset, 'tail_seconds': info['duration'] - offset,
                    'listening': 'unverified', 'bgm': False}
        (stage / 'manifest.json').write_bytes(json_bytes(manifest))
        (stage / 'asset.json').write_bytes(json_bytes({'schema_version': 2, 'id': params['kind'] + '-generated',
            'version': 1, 'kind': 'media', 'entry': 'audio.mp3', 'contract_version': 1,
            'parameters': {}, 'compatibility': {}, 'purpose': params['kind'] + ' synthesized SFX',
            'description': params['kind'] + ' synthesized SFX', 'tags': [params['kind']],
            'license': 'CREDITS.md', 'hit_offset': offset, 'hit_offset_estimated': estimated}))
        (stage / 'CREDITS.md').write_text('Generated with ' + engine + '. Recipe source SHA-256: '
            + digest(source_bytes) + '\nRedistribution must follow the supplied recipe\'s license.\n')
        stage.rename(output)
    return {**manifest, 'path': str(output)}


def generate_earshot(parameters, output, *, earshot='earshot', ffmpeg='ffmpeg'):
    params = earshot_parameters(parameters)
    output = Path(output).absolute()
    validate_review_path(output)
    if output.exists():
        raise ValueError('SFX output already exists; choose a new candidate')
    output.parent.mkdir(parents=True, exist_ok=True)
    with package_write_lock(output.parent / ('.' + output.name + '.lock')), tempfile.TemporaryDirectory(prefix='.sfx-', dir=output.parent) as temporary:
        if output.exists():
            raise ValueError('SFX output already exists; choose a new candidate')
        stage = Path(temporary)
        wav = stage / 'audio.wav'
        version, meta = render_earshot(params, wav, stage, earshot)
        info = wav_info(wav)
        subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(wav), '-codec:a', 'libmp3lame',
                        '-q:a', '2', str(stage / 'audio.mp3')], check=True, capture_output=True, timeout=60)
        # The loudest 5 ms is where a whoosh passes, a riser lands or an impact hits: align that to the cue.
        offset = meta['peak_s']
        if type(offset) not in (int, float) or not 0 <= offset <= info['duration']:
            raise ValueError('earshot reported no usable peak time')
        category = params['id'].split('/')[0]
        manifest = {'engine': 'earshot', 'engine_version': version, 'parameters': {**params, 'seed': meta['seed']},
                    'files': {name: digest((stage / name).read_bytes()) for name in ('audio.wav', 'audio.mp3')},
                    **info, 'hit_offset': offset, 'tail_seconds': info['duration'] - offset,
                    'audit': meta.get('checks'), 'listening': 'unverified', 'bgm': False}
        (stage / 'manifest.json').write_bytes(json_bytes(manifest))
        identity = category.replace('_', '-') + '-generated'
        (stage / 'asset.json').write_bytes(json_bytes({'schema_version': 2, 'id': identity,
            'version': 1, 'kind': 'media', 'entry': 'audio.mp3', 'contract_version': 1,
            'parameters': {}, 'compatibility': {}, 'purpose': params['id'] + ' earshot SFX',
            'description': params['id'] + ' rendered from the earshot sound bank', 'tags': [category],
            'license': 'CREDITS.md', 'hit_offset': offset, 'hit_offset_estimated': True, 'audio_role': 'sfx'}))
        (stage / 'CREDITS.md').write_text('Rendered with earshot (MIT, https://github.com/Leonxlnx/earshot), '
            + version + ', sound ' + params['id'] + '. The bank stores synthesis recipes, not recordings.\n')
        stage.rename(output)
    return {**manifest, 'path': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=None)
    parser.add_argument('--engine', choices=['supercollider', 'jsfxr', 'earshot'], default='supercollider')
    parser.add_argument('--parameters', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.source, json.loads(args.parameters.read_text()), args.output, engine=args.engine), indent=2))
