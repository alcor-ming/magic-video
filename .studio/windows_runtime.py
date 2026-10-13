"""Run a physical Windows root with one resolved configuration per command."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

# Embedded CPython does not add the launcher's directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def paths_overlap(left: Path, right: Path) -> bool:
    left_parts = tuple(part.casefold() for part in left.resolve().parts)
    right_parts = tuple(part.casefold() for part in right.resolve().parts)
    return left_parts[:len(right_parts)] == right_parts or right_parts[:len(left_parts)] == left_parts


def validate_review_path(root: Path) -> None:
    for path in (root, *root.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Review cannot use linked paths: {path}")


def validate_review_tree(root: Path) -> None:
    validate_review_path(root)
    if not root.is_dir():
        raise ValueError(f"Review requires an existing directory: {root}")
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            info = path.lstat()
            if (path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
                raise ValueError(f"Review requires real copies, not links: {path}")


def runtime_paths(root: Path) -> dict[str, Path]:
    npm = root / "runtime" / "npm" / "node_modules"
    return {
        "HYPERFRAMES_NODE": root / "runtime/node/node.exe",
        "HYPERFRAMES_CLI": npm / "hyperframes/bin/hyperframes.mjs",
        "HYPERFRAMES_DIST": npm / "hyperframes/dist",
        "HYPERFRAMES_BROWSER_PATH": root / "runtime/chromium/chrome-headless-shell.exe",
        "HYPERFRAMES_FFMPEG_PATH": root / "runtime/ffmpeg/bin/ffmpeg.exe",
        "HYPERFRAMES_FFPROBE_PATH": root / "runtime/ffmpeg/bin/ffprobe.exe",
        "GSAP_FILE": npm / "gsap/dist/gsap.min.js",
        "THREE_FILE": npm / "three/build/three.min.js",
    }



@contextmanager
def file_lock(path: Path, *, shared: bool = False):
    """Native shared reads / exclusive writes; closing the handle releases the lock."""
    validate_review_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError('Lock file cannot be hardlinked')
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            import msvcrt
            class OVERLAPPED(ctypes.Structure):
                _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                            ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            lock = kernel.LockFileEx
            unlock = kernel.UnlockFileEx
            lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
            unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
            lock.restype = unlock.restype = wintypes.BOOL
            overlapped = OVERLAPPED()
            native = msvcrt.get_osfhandle(handle.fileno())
            if not lock(native, 1 | (0 if shared else 2), 0, 1, 0, ctypes.byref(overlapped)):
                raise ValueError('Object is busy: ' + str(path)) from ctypes.WinError(ctypes.get_last_error())
        else:
            import fcntl
            try:
                fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('Object is busy: ' + str(path)) from error
        try:
            yield
        finally:
            if os.name == 'nt':
                if not unlock(native, 0, 1, 0, ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def command_lock(root: Path, *, shared: bool = False):
    with file_lock(root / '.studio/.runtime/tool.lock', shared=shared):
        yield


def resolved_config(root: Path) -> dict:
    root = root.resolve()
    config_path = root / ".studio/.runtime/local.json"
    validate_review_path(config_path)
    config = read_json(config_path)
    for key in ("work_root", "asset_root"):
        value = config.get(key, str(Path(config["work_root"]) / "asset-library/store") if key == "asset_root" else None)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"Root configuration requires absolute {key}")
        config[key] = str(Path(value).resolve())
    design_root = config.get("design_root", str(Path(config["work_root"]) / "asset-library/designs"))
    if not isinstance(design_root, str) or not Path(design_root).is_absolute():
        raise ValueError("Root configuration requires absolute design_root")
    directory = Path(design_root)
    validate_review_path(directory)
    directory = directory.resolve()
    work_root = Path(config["work_root"])
    if (any(paths_overlap(directory, root / name) for name in (".studio", "runtime", ".agents"))
            or paths_overlap(directory, work_root) and not directory.is_relative_to(work_root / "asset-library")
            or paths_overlap(directory, Path(config["asset_root"]))):
        raise ValueError("design_root must be outside tool, Work and legacy AssetStore directories")
    config["design_root"] = str(directory)
    if not (work_root / "works").is_dir():
        raise ValueError("WorkStore missing works")
    # Retain explicit legacy settings without consulting a retired AssetStore.
    sources = config.get("asset_source_roots", [])
    if not isinstance(sources, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in sources):
        raise ValueError("Asset source roots must be an array of absolute directories")
    config["asset_source_roots"] = [str(Path(p).resolve()) for p in sources]
    if type(config.get("review", False)) is not bool:
        raise ValueError("review must be a boolean")
    manifest = read_json(root / ".release.json")
    if manifest.get("channel") == "candidate" and config.get("review") is not True:
        raise ValueError("Candidate root requires isolated Review configuration")
    if config.get("review"):
        asset_review = Path(config.get("asset_review_root", ""))
        protected = config.get("review_protected_roots")
        if (not asset_review.is_absolute() or not isinstance(protected, list) or not protected
                or not all(isinstance(p, str) and Path(p).is_absolute() for p in protected)):
            raise ValueError("Review requires explicit isolated assets and protected production roots")
        allowed = [Path(config["work_root"]), Path(config["asset_root"]), Path(config["design_root"]), asset_review,
                   *[Path(p) for p in config["asset_source_roots"]]]
        for path in [root, *allowed]:
            validate_review_path(path)
            if not path.resolve().is_relative_to(root) or any(paths_overlap(path, Path(p)) for p in protected):
                raise ValueError(f"Review path escapes the independent root or overlaps production: {path}")
        if Path(config["asset_root"]) != (asset_review / "store").resolve():
            raise ValueError("Review AssetStore must be asset_review_root/store")
        if any(not Path(p).is_relative_to(asset_review / "sources") for p in config["asset_source_roots"]):
            raise ValueError("Review sources must be isolated source copies")
    if "acceptance_protected_roots" in config:
        validate_acceptance_root(root, config, manifest)
    return config


def validate_acceptance_root(root: Path, config: dict, manifest: dict) -> None:
    """Normal local delivery is allowed only after proving physical isolation."""
    protected = config.get("acceptance_protected_roots")
    if (manifest.get("channel") != "local" or config.get("review")
            or not isinstance(protected, list) or not protected
            or any(not isinstance(p, str) or not Path(p).is_absolute() for p in protected)):
        raise ValueError("Acceptance requires a local package and explicit protected roots")
    if any(os.environ.get(key) for key in ("HYPERFRAMES_AI_SESSION", "SESSION_DIR")):
        raise ValueError("Acceptance refuses inherited session configuration")
    paths = [root, Path(config["work_root"]), Path(config["asset_root"]), Path(config["design_root"]),
             *[Path(p) for p in config["asset_source_roots"]],
             Path(config.get("export_root", root / "exports")), root / ".studio/.runtime/cache"]
    for path in paths:
        validate_review_path(path)
        if (not path.is_absolute() or not path.resolve().is_relative_to(root.resolve())
                or any(paths_overlap(path, Path(p)) for p in protected)):
            raise ValueError(f"Acceptance path escapes isolated root or overlaps a protected root: {path}")
    validate_review_tree(root)


def environment(root: Path, config: dict | None = None) -> dict[str, str]:
    root = root.resolve()
    config = resolved_config(root) if config is None else config
    config_path = root / ".studio/.runtime/local.json"
    manifest = read_json(root / ".release.json")
    cache = root / ".studio/.runtime/cache"
    validate_review_path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("HYPERFRAMES_AI_")}
    env.update({key: str(value) for key, value in runtime_paths(root).items()})
    env.update({
        "HYPERFRAMES_AI_HOME": str(root / ".studio/.runtime"),
        "HYPERFRAMES_AI_ROOT": str(root),
        "HYPERFRAMES_AI_CONFIG": str(config_path),
        "HYPERFRAMES_AI_ASSET_CONFIG": str(config_path),
        "HYPERFRAMES_AI_DEFAULT_CONFIG": str(config_path),
        "HYPERFRAMES_AI_RESOLVED_CONFIG": json.dumps(config),
        "HYPERFRAMES_AI_REVIEW": "1" if config.get("review") else "0",
        "HYPERFRAMES_AI_VERSION": manifest["release"],
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
        "TMP": str(cache), "TEMP": str(cache),
        "HYPERFRAMES_EXTRACT_CACHE_DIR": str(cache / "frames"),
        "PUPPETEER_CACHE_DIR": str(cache / "browser"),
        "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    })
    env["PATH"] = os.pathsep.join([str(root / "runtime/node"), str(root / "runtime/ffmpeg/bin"), env.get("PATH", "")])
    # Every Node child uses this physical root, not a caller's preload from another installation.
    env["NODE_OPTIONS"] = "--require " + json.dumps(str(root / ".studio/windows_node.cjs"), ensure_ascii=False)
    env["FFMPEG_PATH"] = env["HYPERFRAMES_FFMPEG_PATH"]
    env["FFPROBE_PATH"] = env["HYPERFRAMES_FFPROBE_PATH"]
    for key in ("work_root", "asset_root"):
        env[f"HYPERFRAMES_AI_{key.upper()}"] = config[key]
    if config.get("review"):
        env["HYPERFRAMES_AI_REVIEW_ROOT"] = config["work_root"]
        env["HYPERFRAMES_AI_ASSET_REVIEW_ROOT"] = config["asset_review_root"]
        env["HYPERFRAMES_AI_REVIEW_PROTECTED_ROOTS"] = json.dumps(config["review_protected_roots"])
    return env


def doctor(root: Path, env: dict[str, str]) -> dict:
    lock = read_json(root / "windows-runtime.lock.json")
    config = json.loads(env["HYPERFRAMES_AI_RESOLVED_CONFIG"])
    result = {"release": read_json(root / ".release.json")["release"], "backend": "windows-native",
              "invocation": "wsl-forwarded" if env.get("HYPERFRAMES_INVOCATION") == "wsl-forwarded" else "windows-native",
              "review": env["HYPERFRAMES_AI_REVIEW"] == "1", "runtime": str(root),
              "rules_root": str(root / "AGENTS.md"),
              "skills_root": str(root / ".agents/skills"), "runtime_lock": str(root / "windows-runtime.lock.json"),
              "release_manifest_sha256": hashlib.sha256((root / ".release.json").read_bytes()).hexdigest(),
              "config": env["HYPERFRAMES_AI_CONFIG"], "asset_config": env["HYPERFRAMES_AI_ASSET_CONFIG"],
              "work_root": config.get("work_root", "not-configured"),
              "asset_root": config.get("asset_root", "not-configured"),
              "design_root": config.get("design_root", "not-configured"),
              "asset_source_roots": config.get("asset_source_roots", []),
              "asset_review_root": config.get("asset_review_root"), "cache_root": env["TEMP"], "checks": {}}
    commands = {"node": [env["HYPERFRAMES_NODE"], "--version"],
                "hyperframes": [env["HYPERFRAMES_NODE"], env["HYPERFRAMES_CLI"], "--version"],
                "chromium": [env["HYPERFRAMES_BROWSER_PATH"], "--version"],
                "ffmpeg": [env["FFMPEG_PATH"], "-version"], "ffprobe": [env["FFPROBE_PATH"], "-version"]}
    for key, path in runtime_paths(root).items():
        result["checks"][key] = "available" if path.exists() else "not-installed"
    for relative in lock.get("required_files", []):
        result["checks"][relative] = "available" if (root / relative).is_file() else "not-installed"
    npm = root / "runtime/npm/node_modules"
    commands["native-modules"] = [env["HYPERFRAMES_NODE"], "-e",
        "const {createRequire}=require('node:module');const r=createRequire(process.argv[1]);"
        "for(const p of ['sharp','esbuild','onnxruntime-node'])r(p);console.log('available');",
        str(npm / "hyperframes/package.json")]
    commands["encoders"] = [env["FFMPEG_PATH"], "-hide_banner", "-encoders"]
    for name, command in commands.items():
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            result["checks"][name] = {"status": "available" if completed.returncode == 0 else "failed",
                                      "output": (completed.stdout or completed.stderr).splitlines()[:2]}
            expected = lock.get("versions", {}).get(name)
            if expected and expected not in completed.stdout + completed.stderr:
                result["checks"][name]["status"] = "version-mismatch"
            if name == "encoders":
                found = [codec for codec in ("libx264", "aac") if codec in completed.stdout]
                result["checks"][name] = {"status": "available" if len(found) == 2 and completed.returncode == 0 else "failed", "output": found}
        except (OSError, subprocess.TimeoutExpired) as error:
            result["checks"][name] = {"status": "unavailable", "error": str(error)}
    result["gpu"] = "pending-native-render-verification"
    result["fonts"] = "system-fonts; validate actual Work line breaks and glyph coverage"
    if config.get("asset_root"):
        from asset_store import ComponentError, discover_components
        inherited = os.environ.copy()
        try:
            # In-process audit must use the same resolved context as Work subprocesses.
            os.environ.clear()
            os.environ.update(env)
            audit = discover_components(root, audit=True, config=config)["audit"]
            result["asset_audit"] = {key: audit[key] for key in ("warning_count", "error_count")}
        except (ComponentError, OSError, ValueError) as error:
            result["asset_audit"] = {"status": "unavailable", "error": str(error)}
        finally:
            os.environ.clear()
            os.environ.update(inherited)
    else:
        result["asset_audit"] = {"status": "not-configured"}
    try:
        import designs
        result["design_root_vcs"] = designs.root_report(root, config=config)
    except Exception as error:  # doctor must keep reporting the rest
        result["design_root_vcs"] = {"status": "unavailable", "error": str(error)}
    return result



def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    with command_lock(root, shared=True):
        if (root / ".studio/.runtime/deploy-pending.json").exists():
            raise ValueError("An update is incomplete; recover it with the verified package installer before running tools")
        env = environment(root)
        if argv == ["doctor"]:
            result = doctor(root, env)
            print(json.dumps(result, indent=2))
            return int(any(value == "not-installed" or isinstance(value, dict) and value["status"] != "available"
                           for value in result["checks"].values()))
        return subprocess.call([sys.executable, "-B", str(root / ".studio/work.py"), *(argv or ["--help"])], env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f"work: {error}", file=sys.stderr)
        raise SystemExit(1)
