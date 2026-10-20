"""Import one downloaded open-library music track as an editable BGM AssetSource entry, never accept it.

BGM is never synthesized: the track comes from an existing open music library and keeps its license,
attribution and NC/SA flags so non-commercial material stays filterable.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

from asset_contract import ID, _check_audio, _check_link
from component_harness import ComponentError, _atomic_json


AUDIO = {".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a"}


def license_flags(license_name: str) -> tuple[bool, bool]:
    """(non_commercial, share_alike) from a CC-style name; no-derivatives and unknown text are refused."""
    if not isinstance(license_name, str) or not license_name.strip():
        raise ComponentError("BGM requires the track's license")
    tokens = set(re.findall(r"[A-Za-z0-9]+", license_name.upper()))
    if tokens & {"ND", "NODERIVS", "NODERIVATIVES"}:
        raise ComponentError("No-derivatives licenses cannot be mixed into a video")
    return bool(tokens & {"NC", "NONCOMMERCIAL"}), bool(tokens & {"SA", "SHAREALIKE"})


def import_bgm(file: Path, source: Path, identity: str, *, library: str, source_url: str, license_name: str,
               attribution: str, title: str, moods=()) -> dict:
    file, source = Path(file).absolute(), Path(source).absolute()
    if not ID.fullmatch(identity):
        raise ComponentError("BGM id must be lowercase words joined by hyphens")
    if not file.is_file() or file.is_symlink() or file.suffix.lower() not in AUDIO:
        raise ComponentError("BGM file must be a local " + "/".join(sorted(AUDIO)) + " file")
    for key, value in (("library", library), ("source URL", source_url), ("attribution", attribution), ("title", title)):
        if not isinstance(value, str) or not value.strip():
            raise ComponentError(f"BGM requires the {key}")
    if any(not isinstance(mood, str) or not ID.fullmatch(mood) for mood in moods):
        raise ComponentError("BGM moods must be lowercase hyphenated words")
    non_commercial, share_alike = license_flags(license_name)
    for parent in (source, *source.parents):
        if parent.exists():
            _check_link(parent)
            break
    target = source / identity
    if target.exists() or target.is_symlink():
        raise ComponentError(f"BGM destination already exists: {identity}")
    source.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bgm-", dir=source) as temporary:
        stage = Path(temporary) / identity
        stage.mkdir()
        media = stage / "audio.mp3"
        if file.suffix.lower() == ".mp3":
            shutil.copyfile(file, media)
        else:
            result = subprocess.run([os.environ.get("HYPERFRAMES_FFMPEG_PATH", "ffmpeg"), "-nostdin", "-v", "error", "-i", str(file),
                                     "-vn", "-codec:a", "libmp3lame", "-q:a", "2", str(media)], capture_output=True, timeout=300)
            if result.returncode:
                raise ComponentError("BGM transcoding failed: " + result.stderr.decode(errors="replace")[-600:])
        duration = _check_audio(media)["duration"]
        rights = {"library": library.strip(), "license": license_name.strip(), "attribution": attribution.strip(),
                  "non_commercial": non_commercial, "share_alike": share_alike}
        (stage / "CREDITS.md").write_text(
            f"# {title.strip()}\n\n- Library: {rights['library']}\n- Source: {source_url.strip()}\n"
            f"- License: {rights['license']}\n- Attribution: {rights['attribution']}\n", encoding="utf-8")
        _atomic_json(stage / "asset.json", {"schema_version": 2, "id": identity, "version": 1, "kind": "media",
            "entry": media.name, "contract_version": 1, "parameters": {}, "compatibility": {},
            "purpose": "BGM: " + title.strip(), "description": f"{title.strip()} ({rights['library']}, {duration:.1f}s)",
            "tags": ["bgm", *moods], "license": "CREDITS.md", "source_url": source_url.strip(),
            "rights": rights, "audio_role": "bgm"})
        stage.rename(target)
    return {"path": str(target), "id": identity, "duration": duration, "rights": rights, "accepted": False}
