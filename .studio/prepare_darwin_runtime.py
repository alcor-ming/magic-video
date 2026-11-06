"""Freeze an explicit Apple Silicon runtime into a hashed, relocatable local asset.

Inputs are already installed, version-pinned tools. No downloads, system changes,
or production paths are performed here. The resulting lock is reviewed with the
source and deployed by release deploy; rebuild only when native inputs change.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_tree(source, target):
    """Materialize internal file aliases; reject external links and directory links."""
    source = source.resolve()
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if '__pycache__' in relative.parts or path.suffix in {'.pyc', '.pyo'}:
            continue
        if path.is_symlink() and (not path.is_file() or not path.resolve().is_relative_to(source)):
            raise ValueError('Unsafe runtime link: ' + str(path))
        if path.is_file():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def prepare(args):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('Native Apple Silicon runtime required')
    args.cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='darwin-runtime-', dir=args.cache) as temp:
        root = Path(temp)
        copy_tree(args.python_root, root / 'python')
        site = root / 'python/lib/python3.12/site-packages'
        # Use an isolated three-package environment; never copy an arbitrary development venv.
        allowed = ('PIL', 'pillow-', 'numpy', 'scipy')
        for entry in args.site_packages.iterdir():
            if entry.name.startswith(allowed):
                if entry.is_dir():
                    copy_tree(entry, site / entry.name)
                elif entry.is_file():
                    site.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(entry, site / entry.name)
        for source, name in ((args.node, 'node/node'), (args.ffmpeg, 'ffmpeg/bin/ffmpeg'),
                             (args.ffprobe, 'ffmpeg/bin/ffprobe')):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.resolve(), destination)
        copy_tree(args.npm, root / 'npm')
        with zipfile.ZipFile(args.browser_zip) as bundle:
            for item in bundle.infolist():
                parts = Path(item.filename).parts
                if (not parts or parts[0] != 'chrome-headless-shell-mac-arm64'
                        or '..' in parts or item.filename.startswith('/') or '\\' in item.filename
                        or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('Unsafe browser archive member: ' + item.filename)
                if item.is_dir():
                    continue
                destination = root / 'chromium' / Path(*parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(item))
                destination.chmod(0o755 if (item.external_attr >> 16) & 0o111 else 0o644)
        versions = {}
        for name, command in {
            'node': [root / 'node/node', '--version'],
            'chromium': [root / 'chromium/chrome-headless-shell', '--version'],
            'ffmpeg': [root / 'ffmpeg/bin/ffmpeg', '-version'],
            'ffprobe': [root / 'ffmpeg/bin/ffprobe', '-version'],
        }.items():
            out = subprocess.check_output(command, text=True).splitlines()[0]
            versions[name] = out.split()[2] if name in {'ffmpeg', 'ffprobe'} else out.split()[-1].lstrip('v')
        python = root / 'python/bin/python3'
        subprocess.run([python, '-B', '-c', 'import PIL,numpy,scipy,ssl,sys; '
                        'assert sys.version_info[:3] == (3,12,16); '
                        'assert (PIL.__version__,numpy.__version__,scipy.__version__) == ("12.3.0","2.4.2","1.17.1"); '
                        'print(PIL.__version__,numpy.__version__,scipy.__version__)'], check=True)
        subprocess.run([root / 'node/node', '-e', "for(const p of ['sharp','esbuild','onnxruntime-node','koffi'])require(p)"], cwd=root / 'npm', check=True)
        npm_lock = json.loads((args.npm / 'package-lock.json').read_text())
        versions.update(npm_lock['packages']['']['dependencies'])
        archive = args.cache / 'darwin-runtime.zip'
        temporary = archive.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in sorted(p for p in root.rglob('*') if p.is_file()):
                info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
                bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        os.replace(temporary, archive)
    required = ['python/bin/python3', 'node/node', 'chromium/chrome-headless-shell',
                'ffmpeg/bin/ffmpeg', 'ffmpeg/bin/ffprobe', 'npm/package-lock.json',
                'npm/node_modules/hyperframes/bin/hyperframes.mjs',
                'npm/node_modules/hyperframes/dist/hyperframes-player.global.js',
                'npm/node_modules/hyperframes/dist/hyperframe.runtime.iife.js',
                'npm/node_modules/gsap/dist/gsap.min.js', 'npm/node_modules/three/build/three.min.js',
                'npm/node_modules/acorn/dist/acorn.js', 'npm/node_modules/esbuild/lib/main.js',
                'npm/node_modules/@esbuild/darwin-arm64/bin/esbuild']
    lock = {'schema_version': 1, 'target': 'darwin-arm64', 'python': '3.12.16',
            'versions': versions, 'python_packages': {'pillow': '12.3.0', 'numpy': '2.4.2', 'scipy': '1.17.1'},
            'required_files': ['runtime/' + p for p in required],
            'assets': [{'kind': 'zip', 'file': archive.name, 'target': 'runtime', 'sha256': digest(archive)}],
            'browser_source': {'url': 'https://storage.googleapis.com/chrome-for-testing-public/152.0.7977.30/mac-arm64/chrome-headless-shell-mac-arm64.zip', 'sha256': digest(args.browser_zip)}}
    (ROOT / 'darwin-runtime.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    shutil.copyfile(args.npm / 'package-lock.json', ROOT / 'darwin-npm.lock.json')
    print(json.dumps({'archive': str(archive), 'sha256': digest(archive), 'versions': versions}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('python-root', 'site-packages', 'node', 'ffmpeg', 'ffprobe', 'npm', 'browser-zip', 'cache'):
        parser.add_argument('--' + name, type=Path, required=True)
    prepare(parser.parse_args())
