"""Deterministic cover composition; the image and video remain independent inputs.

A layout recipe composes the account style (layout, font, colours, background), one character from
the account's library, the title and a one-line tagline. Recipes without a layout keep the legacy
title + Logo typography so frozen and unmigrated accounts still render.
"""
import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from tts import digest, json_bytes
from storage import scoped_path
from windows_runtime import validate_review_path


def verify(directory):
    directory = Path(directory)
    manifest_path = scoped_path(directory, 'manifest.json')
    if manifest_path.stat().st_nlink != 1:
        raise ValueError('Linked cover manifest')
    manifest = json.loads(manifest_path.read_bytes())
    if (manifest.get('id') != directory.name or digest(json_bytes(manifest.get('inputs'))) != directory.name
            or not isinstance(manifest.get('files'), dict) or not {'index.html', 'cover.png'} <= manifest['files'].keys()):
        raise ValueError('Frozen cover manifest changed')
    for name, expected in manifest['files'].items():
        path = scoped_path(directory, name)
        if path.stat().st_nlink != 1 or digest(path.read_bytes()) != expected:
            raise ValueError('Frozen cover changed')
    return {**manifest, 'path': str(directory)}


LAYOUTS = ('character-left', 'character-right', 'character-bottom')
RECIPE_KEYS = {'width', 'height', 'font', 'logo', 'background', 'color', 'background_color', 'font_size',
               'layout', 'character', 'tagline_font_size'}


def render(variant, title, recipe, *, tagline=None, node='node', browser=None):
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Cover requires a title')
    if not isinstance(recipe, dict) or set(recipe) - RECIPE_KEYS or 'font' not in recipe:
        raise ValueError('Cover requires an account recipe with an exact font')
    layout = recipe.get('layout')
    if layout is None:
        if 'logo' not in recipe or tagline is not None or 'character' in recipe:
            raise ValueError('Cover requires an account recipe with exact font and Logo')
    elif layout not in LAYOUTS:
        raise ValueError('Unknown cover layout; use ' + ', '.join(LAYOUTS))
    elif 'character' not in recipe:
        raise ValueError('Cover layout requires a character from the account library')
    elif not isinstance(tagline, str) or not tagline.strip():
        raise ValueError('Cover layout requires a one-line tagline')
    width, height = recipe.get('width'), recipe.get('height')
    if any(type(n) is not int or not 64 <= n <= 8192 for n in (width, height)):
        raise ValueError('Cover requires concrete width/height in 64..8192')
    font_size = recipe.get('font_size', min(width, height) * 0.085)
    if type(font_size) not in (int, float) or not math.isfinite(font_size) or not 8 <= font_size <= min(width, height):
        raise ValueError('Invalid cover font_size')
    colors = {key: recipe.get(key, default) for key, default in [('color', '#111111'), ('background_color', '#faf7ef')]}
    if any(not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value) for value in colors.values()):
        raise ValueError('Cover colors require six-digit hex values')
    assets = {}
    tagline_size = recipe.get('tagline_font_size', font_size * 0.45)
    if type(tagline_size) not in (int, float) or not math.isfinite(tagline_size) or not 8 <= tagline_size <= font_size:
        raise ValueError('Invalid cover tagline_font_size')
    for role in ('font', 'logo', 'background', 'character'):
        if role not in recipe: continue
        ref = recipe[role]
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('Cover assets require exact path/sha256 references')
        path = Path(ref['path']).absolute()
        validate_review_path(path)
        if not path.is_file() or path.stat().st_nlink != 1 or digest(path.read_bytes()) != ref['sha256']:
            raise ValueError('Cover asset missing or changed: ' + role)
        if path.suffix.lower() not in ({'.ttf', '.otf', '.woff', '.woff2'} if role == 'font' else {'.png', '.jpg', '.jpeg', '.webp', '.svg'}):
            raise ValueError('Unsupported cover asset format')
        assets[role] = path
    renderer = Path(__file__).with_suffix('.mjs')
    inputs = {'title': title, 'recipe': recipe, 'renderer_sha256': digest(renderer.read_bytes()),
              'template_sha256': digest(Path(__file__).read_bytes())}
    if layout is not None:
        inputs['tagline'] = tagline
    identity = digest(json_bytes(inputs))
    parent = scoped_path(Path(variant), 'covers')
    parent.mkdir(parents=True, exist_ok=True)
    target = scoped_path(parent, identity)
    if target.exists():
        manifest = verify(target)
        if (manifest.get('id') != identity or manifest.get('inputs') != inputs
                or set(manifest.get('files', {})) != {'index.html', 'cover.png', *[role + path.suffix.lower() for role, path in assets.items()]}):
            raise ValueError('Frozen cover manifest changed')
        for name, expected in manifest['files'].items():
            path = scoped_path(target, name)
            if path.stat().st_nlink != 1 or digest(path.read_bytes()) != expected:
                raise ValueError('Frozen cover changed')
        return {**manifest, 'path': str(target)}
    with tempfile.TemporaryDirectory(prefix='.cover-', dir=parent) as temporary:
        stage = Path(temporary)
        names = {}
        for role, path in assets.items():
            names[role] = role + path.suffix.lower()
            shutil.copyfile(path, stage / names[role])
            if digest((stage / names[role]).read_bytes()) != recipe[role]['sha256']:
                raise ValueError('Cover asset changed while copying')
        background = f'<img class="background" src="{names["background"]}" alt="">' if 'background' in names else ''
        logo = f'<img class="logo" src="{names["logo"]}" alt="">' if 'logo' in names else ''
        head = f'''<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:Cover;src:url("{names['font']}")}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden}}
body{{background:{colors['background_color']};color:{colors['color']};font-family:Cover}}
.background{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}'''
        if layout is None:
            source = head + f'''
main{{position:absolute;inset:8%;display:flex;flex-direction:column;justify-content:space-between}}
h1{{font-size:{font_size}px;line-height:1.5;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
.logo{{width:18%;max-height:18%;object-fit:contain;object-position:left}}
</style>{background}<main><h1>{html.escape(title)}</h1>{logo}</main>'''
        else:
            side = 'left' if layout == 'character-left' else 'right'
            other = 'right' if side == 'left' else 'left'
            frames = (f'.character{{{side}:0;bottom:0;width:44%;height:92%;object-position:{side} bottom}}'
                      f'.copy{{{other}:0;top:0;bottom:0;width:52%;justify-content:center}}'
                      f'.logo{{{other}:0;top:0}}') if layout != 'character-bottom' else (
                      '.character{left:0;right:0;bottom:0;width:100%;height:54%;object-position:center bottom}'
                      '.copy{left:0;right:0;top:0;height:40%;justify-content:flex-start}.logo{right:0;bottom:56%}')
            source = head + f'''
main{{position:absolute;inset:6%}}
.character{{position:absolute;object-fit:contain}}
.copy{{position:absolute;display:flex;flex-direction:column;gap:{round(font_size * 0.35, 2)}px;overflow:hidden}}
h1{{font-size:{font_size}px;line-height:1.25;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
.tagline{{font-size:{tagline_size}px;line-height:1.4;margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}
.logo{{position:absolute;width:14%;max-height:12%;object-fit:contain}}
{frames}
</style>{background}<main><img class="character" src="{names['character']}" alt=""><div class="copy"><h1>{html.escape(title)}</h1><p class="tagline">{html.escape(tagline)}</p></div>{logo}</main>'''
        (stage / 'index.html').write_text(source, encoding='utf-8')
        command = [node, str(renderer), str(stage.resolve()), str(width), str(height)]
        env = dict(os.environ)
        if browser: env['CHROME_PATH'] = browser
        subprocess.run(command, env=env, check=True, capture_output=True, timeout=120)
        manifest = {'id': identity, 'inputs': inputs, 'width': width, 'height': height,
                    'files': {p.name: digest(p.read_bytes()) for p in stage.iterdir() if p.is_file()}}
        (stage / 'manifest.json').write_bytes(json_bytes(manifest))
        stage.rename(target)
    return {**manifest, 'path': str(target)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', type=Path, required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--recipe', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.variant, args.title, json.loads(args.recipe.read_text())), ensure_ascii=False, indent=2))
