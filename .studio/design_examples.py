"""Materialize an editable design example from an explicit, hash-pinned resource list.

GSAP and its plugins are host runtime dependencies: the card declares them in
``design.json.runtime`` and this builder copies the host npm files at build time
instead of freezing a private copy into the card.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import designs
from component_harness import package_write_lock
from storage import scoped_path
from windows_runtime import runtime_paths, validate_review_path, validate_review_tree

REPO = Path(__file__).resolve().parents[1]
IDENTITY = re.compile(r'[a-z][a-z0-9-]*')
_PLUGIN_NAMES = ('{0}.min.js', '{0}Plugin.min.js', '{0}.js', '{0}Plugin.js')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def card_dir(identity, repo=REPO, config=None):
    if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
        raise ValueError('Invalid example identity')
    matches = [root / identity for root in designs.card_roots(repo, config)
               if any((root / identity / name).is_file() for name in ('design.json', 'example-manifest.json'))]
    if not matches:
        raise ValueError('Unknown design card: ' + identity)
    if len(matches) > 1:
        raise ValueError('Duplicate design card: ' + identity)
    return matches[0]


def source_path(identity, name, repo=REPO, config=None):
    parts = Path(name).parts
    if parts[:2] == ('.studio', 'designs') and len(parts) > 3:
        return scoped_path(card_dir(parts[2], repo, config), '/'.join(parts[3:]))
    if name.startswith('.studio/') or name == 'LICENSE':
        return scoped_path(repo, name)
    return scoped_path(card_dir(identity, repo, config), name)


def manifest(identity, repo=REPO, config=None):
    path = card_dir(identity, repo, config) / 'example-manifest.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('design') != identity or type(value.get('version')) is not int
            or value['version'] < 1 or not isinstance(value.get('files'), list)):
        raise ValueError('Invalid example manifest')
    targets = set()
    for item in value['files']:
        if (not isinstance(item, dict) or set(item) != {'source', 'target', 'sha256', 'origin', 'version', 'license', 'purpose', 'packages'}
                or any(not isinstance(item[k], str) or not item[k].strip()
                       for k in ('source', 'target', 'sha256', 'origin', 'version', 'license', 'purpose'))
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])
                or not isinstance(item['packages'], list) or not item['packages']
                or not set(item['packages']) <= {'public', 'personal'}):
            raise ValueError('Incomplete example resource provenance')
        source = source_path(identity, item['source'], repo, config)
        target = item['target']
        scoped_path(repo, target)
        if target in targets or target == 'resource-manifest.json':
            raise ValueError('Duplicate or reserved example target')
        targets.add(target)
        if not source.is_file() or source.stat().st_nlink != 1 or sha256(source) != item['sha256']:
            raise ValueError('Example resource missing or changed: ' + item['source'])
    if not {'index.html', 'scene.js', 'style.css'} <= targets:
        raise ValueError('Example requires an editable HTML/CSS/JS project')
    return value


def runtime_manifest(identity, repo=REPO, config=None, runtime_root=None):
    """Host-provided runtime files required by the card's runtime declaration."""
    try:
        card = designs.get(identity, root=repo, config=config)
    except designs.DesignError:
        return []
    runtime = card.get('runtime') or {}
    directory = runtime_paths(Path(runtime_root) if runtime_root is not None else Path(repo))['GSAP_FILE'].parent
    names = []
    if runtime.get('gsap'):
        names.append('gsap.min.js')
    for plugin in runtime.get('plugins') or []:
        for candidate in (name.format(plugin) for name in _PLUGIN_NAMES):
            if (directory / candidate).is_file():
                names.append(candidate)
                break
        else:
            raise ValueError('Host runtime does not provide plugin: ' + plugin)
    entries = []
    version = designs.host_gsap(repo)
    for name in dict.fromkeys(names):
        source = directory / name
        if not source.is_file():
            raise ValueError('Host runtime does not provide: ' + name)
        entries.append(({"target": 'runtime/' + name, "sha256": sha256(source),
                         "package": 'gsap', "version": version}, source))
    if runtime.get('three'):
        source = runtime_paths(Path(runtime_root) if runtime_root is not None else Path(repo))['THREE_FILE']
        if not source.is_file():
            raise ValueError('Host runtime does not provide: three.min.js')
        entries.append(({"target": 'runtime/three.min.js', "sha256": sha256(source),
                         "package": 'three', "version": designs.host_three(repo)}, source))
    return entries


def verify(directory, expected=None):
    directory = Path(directory).absolute()
    validate_review_path(directory)
    validate_review_tree(directory)
    receipt = scoped_path(directory, 'resource-manifest.json')
    if receipt.stat().st_nlink != 1:
        raise ValueError('Linked example manifest')
    value = json.loads(receipt.read_text(encoding='utf-8'))
    if expected is not None and value != expected:
        raise ValueError('Example manifest changed')
    runtime = value.get('runtime', [])
    targets = {item['target'] for item in [*value['files'], *runtime]}
    found = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if found != {'resource-manifest.json', *targets}:
        raise ValueError('Example file set changed')
    for item in [*value['files'], *runtime]:
        path = scoped_path(directory, item['target'])
        if path.stat().st_nlink != 1 or sha256(path) != item['sha256']:
            raise ValueError('Example resource changed: ' + item['target'])
    return value


def build(identity, destination, *, repo=REPO, config=None, runtime_root=None):
    value = manifest(identity, repo, config)
    host = runtime_manifest(identity, repo, config, runtime_root)
    expected = {**value, 'runtime': [entry for entry, _source in host]}
    destination = Path(destination).absolute()
    validate_review_path(destination)
    if destination.exists():
        verify(destination, expected)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with package_write_lock(destination.parent / ('.' + destination.name + '.lock')), tempfile.TemporaryDirectory(prefix='.design-example-', dir=destination.parent) as temporary:
        if destination.exists():
            verify(destination, expected)
            return destination
        stage = Path(temporary) / 'project'
        stage.mkdir()
        for item in value['files']:
            target = scoped_path(stage, item['target'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path(identity, item['source'], repo, config), target)
            if sha256(target) != item['sha256']:
                raise ValueError('Example source changed while copying')
        for entry, source in host:
            target = scoped_path(stage, entry['target'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if sha256(target) != entry['sha256']:
                raise ValueError('Host runtime changed while copying')
        (stage / 'resource-manifest.json').write_text(json.dumps(expected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        verify(stage, expected)
        stage.rename(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path)
    args = parser.parse_args()
    print(build(args.design, args.output, runtime_root=args.runtime_root))
