"""Musical beat grid: pinned upstream beat detection and bar/beat lookup; never guess meter or downbeats."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def validate_beat_grid(grid):
    if (not isinstance(grid, dict) or set(grid) != {
            'schema_version', 'audio_sha256', 'beats_per_bar', 'first_downbeat', 'times'}
            or type(grid['schema_version']) is not int or grid['schema_version'] != 1
            or not isinstance(grid['audio_sha256'], str)
            or not re.fullmatch(r'[0-9a-fA-F]{64}', grid['audio_sha256'])
            or type(grid['beats_per_bar']) is not int or not 1 <= grid['beats_per_bar'] <= 9007199254740991
            or not isinstance(grid['times'], list) or not grid['times']
            or type(grid['first_downbeat']) is not int
            or not 0 <= grid['first_downbeat'] < len(grid['times'])):
        raise ValueError('invalid_beat_grid')
    previous = -1
    for time in grid['times']:
        if type(time) not in (int, float) or not math.isfinite(time) or time < 0 or time <= previous:
            raise ValueError('invalid_beat_grid')
        previous = time
    return grid


def make_beat_grid(times, audio_sha256, beats_per_bar, first_downbeat):
    return validate_beat_grid(dict(schema_version=1, audio_sha256=audio_sha256,
                                   beats_per_bar=beats_per_bar, first_downbeat=first_downbeat, times=times))


def find_beat(grid, bar, beat):
    validate_beat_grid(grid)
    if (type(bar) is not int or not 1 <= bar <= 9007199254740991
            or type(beat) is not int or not 1 <= beat <= grid['beats_per_bar']):
        raise ValueError('invalid_beat_query')
    index = grid['first_downbeat'] + (bar - 1) * grid['beats_per_bar'] + beat - 1
    if index >= len(grid['times']):
        raise ValueError('beat_not_found')
    return grid['times'][index]


def extract(audio, cli, beats_per_bar, first_downbeat):
    package = cli.parent.parent / "package.json"
    if json.loads(package.read_text(encoding="utf-8")).get("version") != "0.8.150":
        raise ValueError("Beat extraction requires pinned HyperFrames 0.8.150")
    browser = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if not browser or not Path(browser).is_file():
        raise ValueError("Beat extraction requires the installed browser; no automatic download")
    with audio.open("rb") as handle:
        audio_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    with tempfile.TemporaryDirectory(prefix="hf-beats-") as directory:
        project = Path(directory)
        name = "audio" + audio.suffix.lower()
        shutil.copyfile(audio, project / name)
        (project / "index.html").write_text(f'<!doctype html><audio data-timeline-role="music" src="{name}"></audio>', encoding="utf-8")
        process = subprocess.run([os.environ.get("HYPERFRAMES_NODE", "node"), str(cli), "beats", str(project), "--json"],
                                 capture_output=True, text=True, timeout=180,
                                 env={**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"})
        if process.returncode:
            raise ValueError(f"Pinned beat extraction failed: {process.stderr or process.stdout}")
        data = json.loads((project / "beats" / (name + ".json")).read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
                or data.get("audio") != name or not isinstance(data.get("beats"), list)
                or not all(isinstance(beat, dict) and "time" in beat for beat in data["beats"])):
            raise ValueError("Unexpected upstream beat file")
        with (project / name).open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != audio_hash:
                raise ValueError("Audio changed during beat extraction")
        with audio.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != audio_hash:
                raise ValueError("Audio changed during beat extraction")
        return make_beat_grid([beat["time"] for beat in data["beats"]], audio_hash, beats_per_bar, first_downbeat)
