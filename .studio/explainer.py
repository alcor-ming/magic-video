"""Frozen narration cues and sound tracks for explainer projects."""

from difflib import SequenceMatcher
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

from component_harness import _atomic_json, verify_installation, _lock_components
from storage import scoped_path


class ExplainerError(ValueError):
    pass


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ExplainerError(f"Cannot read {path.name}: {exc}") from exc


def number(value, label, *, minimum=0, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value) or value < minimum
            or maximum is not None and value > maximum):
        raise ExplainerError(f"Invalid {label}")
    return value


def build_cues(text, alignment_bytes):
    if not isinstance(text, str) or not text.strip():
        raise ExplainerError("Narration must not be empty")
    try:
        source = json.loads(alignment_bytes)
    except (ValueError, UnicodeError) as exc:
        raise ExplainerError("Alignment must be JSON characters[]") from exc
    records = source.get("characters") if isinstance(source, dict) else None
    if not isinstance(records, list) or not records:
        raise ExplainerError("Alignment needs characters[]")
    previous, normalized = 0, []
    for record in records:
        char = record.get("text", record.get("char")) if isinstance(record, dict) else None
        if not isinstance(char, str) or len(char) != 1:
            raise ExplainerError("Alignment entries require one text/char character")
        aligned = record.get("aligned", record.get("start") is not None and record.get("end") is not None)
        if type(aligned) is not bool:
            raise ExplainerError("Alignment aligned must be boolean")
        start = end = None
        if aligned:
            start = number(record.get("start"), "character start", minimum=previous)
            end = number(record.get("end"), "character end", minimum=start)
            previous = start
        normalized.append({"char": char, "start": start, "end": end, "aligned": aligned})
    records = normalized
    transcript = "".join(item["char"] for item in records)
    characters = [{"char": char, "start": None, "end": None, "aligned": False} for char in text]
    mismatches = []
    # ponytail: quadratic matching; split by approved anchors if long-form narration becomes slow.
    for kind, a, b, c, d in SequenceMatcher(None, text, transcript, autojunk=False).get_opcodes():
        if kind == "equal":
            for index, record in zip(range(a, b), records[c:d]):
                characters[index].update(start=record["start"], end=record["end"], aligned=record["aligned"])
        else:
            mismatches.append({"kind": kind, "script_range": [a, b], "alignment_range": [c, d],
                               "script": text[a:b], "alignment": transcript[c:d]})
    intervals = []
    for char in characters:
        if not char["aligned"] or char["char"].isspace() or char["end"] == char["start"]:
            continue
        if intervals and char["start"] - intervals[-1][1] < 0.35:
            intervals[-1][1] = max(intervals[-1][1], char["end"])
        else:
            intervals.append([char["start"], char["end"]])
    return {"schema_version": 1, "text": text, "characters": characters,
            "sources": {"script_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "alignment_sha256": hashlib.sha256(alignment_bytes).hexdigest()},
            "mismatches": mismatches, "speech_intervals": intervals}


def find_cue(cues, query):
    query = {"token": query} if isinstance(query, str) else query
    if isinstance(query, dict) and ({'bar', 'beat'} & query.keys()):
        if set(query) != {'bar', 'beat'}:
            raise ExplainerError('invalid_beat_query')
        if 'beat_grid' not in cues:
            raise ExplainerError('missing_beat_grid')
        from beat_grid import find_beat
        try:
            return find_beat(cues['beat_grid'], query['bar'], query['beat'])
        except ValueError as exc:
            raise ExplainerError(str(exc)) from exc
    if (not isinstance(query, dict) or set(query) - {"token", "nth", "within", "edge"}
            or not isinstance(query.get("token"), str) or not query["token"]):
        raise ExplainerError("Invalid cue query")
    token, edge = query["token"], query.get("edge", "start")
    if edge not in ("start", "end"):
        raise ExplainerError("Invalid cue edge")
    nth = query.get("nth")
    if nth is not None and (type(nth) is not int or nth < 1):
        raise ExplainerError("Invalid cue nth")
    window = query.get("within")
    if window is not None:
        if not isinstance(window, list) or len(window) != 2:
            raise ExplainerError("Invalid cue window")
        number(window[0], "cue window start")
        number(window[1], "cue window end", minimum=window[0])
    text, chars = cues["text"], cues["characters"]
    matches = []
    offset = text.find(token)
    while offset >= 0:
        span = chars[offset:offset + len(token)]
        aligned = all(char["aligned"] for char in span)
        known = [char for char in span if char["aligned"]]
        if window is None or not known or known[0]["start"] >= window[0] and known[-1]["end"] <= window[1]:
            matches.append((span, aligned))
        offset = text.find(token, offset + 1)
    if not matches or nth is not None and nth > len(matches):
        raise ExplainerError("cue_not_found")
    if nth is None and len(matches) > 1:
        raise ExplainerError("cue_ambiguous")
    span, aligned = matches[(nth or 1) - 1]
    if not aligned:
        raise ExplainerError("cue_unaligned")
    return span[0]["start"] if edge == "start" else span[-1]["end"]


def validate_cues(data):
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("text"), str) or not isinstance(data.get("characters"), list)):
        raise ExplainerError("invalid_cues")
    if 'beat_grid' in data:
        from beat_grid import validate_beat_grid
        try:
            validate_beat_grid(data['beat_grid'])
        except ValueError as exc:
            raise ExplainerError(str(exc)) from exc
    previous = 0
    for char in data["characters"]:
        if (not isinstance(char, dict) or not isinstance(char.get("char"), str) or len(char["char"]) != 1
                or type(char.get("aligned")) is not bool):
            raise ExplainerError("invalid_cues")
        if char["aligned"]:
            previous = number(char.get("start"), "cue start", minimum=previous)
            number(char.get("end"), "cue end", minimum=previous)
        elif char.get("start") is not None or char.get("end") is not None:
            raise ExplainerError("Unaligned cues must not have interpolated times")
    if "".join(char["char"] for char in data["characters"]) != data["text"]:
        raise ExplainerError("Cue text differs from characters")
    if not isinstance(data.get("speech_intervals"), list):
        raise ExplainerError("Invalid speech intervals")
    previous = 0
    for interval in data["speech_intervals"]:
        if not isinstance(interval, list) or len(interval) != 2:
            raise ExplainerError("Invalid speech interval")
        start = number(interval[0], "speech start", minimum=previous)
        previous = number(interval[1], "speech end", minimum=start)
    return data


def declare_files(project, names):
    path = scoped_path(project, "project-config.json")
    config = read_json(path) if path.exists() else {}
    entries = config.get("snapshot_dependencies", []) if isinstance(config, dict) else None
    if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
        raise ExplainerError("Invalid snapshot_dependencies")
    for name in names:
        if not scoped_path(project, name).is_file():
            raise ExplainerError(f"Missing frozen dependency: {name}")
    config["snapshot_dependencies"] = sorted(set(entries) | set(names))
    _atomic_json(path, config)


def installed_assets(project, *, check_mounts=True):
    """Trust only verified local packages, never resolve mutable AssetStore state."""
    path = scoped_path(project, "COMPONENT_LOCK.json")
    if not path.is_file():
        return {}
    verify_installation(project, check_mounts=check_mounts)
    result = {}
    for record in _lock_components(read_json(path)):
        vendor = record["vendor_path"]
        metadata_path = scoped_path(project, f"{vendor}/asset.json")
        if metadata_path.is_file():
            result[record["component_ref"]] = {"vendor_path": vendor, "metadata": read_json(metadata_path)}
    return result


def sound_elements(plan, cues, assets):
    if not isinstance(plan, dict) or set(plan) - {"bgm", "sfx"} or not isinstance(plan.get("sfx", []), list):
        raise ExplainerError("Invalid sound table")
    output, tracks = [], []

    def asset_for(item):
        ref = item.get("ref")
        if not isinstance(ref, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*@v[1-9][0-9]*", ref):
            raise ExplainerError("Invalid sound ref")
        asset = assets.get(ref)
        if asset is None or asset["metadata"].get("kind") != "media" or Path(asset["metadata"].get("entry", "")).suffix.lower() != ".mp3":
            raise ExplainerError("sound_asset_outside_closure")
        return asset

    def audio(item, identity, start, duration, group=None):
        asset = asset_for(item)
        gain = number(item.get("gain", 1), "sound gain", maximum=1)
        attrs = {"id": identity, "src": f'{asset["vendor_path"]}/{asset["metadata"]["entry"]}',
                 "data-asset-ref": item["ref"], "data-start": start, "data-duration": duration,
                 "data-volume": gain, "data-track-index": 6 if group else 7}
        if group:
            attrs["data-audio-group"] = group
        output.append("<audio " + " ".join(f'{key}="{escape(str(value), quote=True)}"' for key, value in attrs.items())
                      + (" loop" if group else "") + "></audio>")
        tracks.append(attrs)

    bgm = plan.get("bgm")
    if bgm is not None:
        if not isinstance(bgm, dict) or set(bgm) != {"ref", "start_cue", "end_cue", "gain"}:
            raise ExplainerError("BGM needs ref, start_cue, end_cue and gain")
        start, end = find_cue(cues, bgm["start_cue"]), find_cue(cues, bgm["end_cue"])
        if end <= start:
            raise ExplainerError("BGM end must follow start")
        points = {0: 1}
        for a, b in cues["speech_intervals"]:
            if b <= start or a >= end:
                continue
            a, b = max(start, a), min(end, b)
            points[max(0, a - 0.08)] = 1
            points[a] = 0.25
            points[b] = 0.25
            if b < end:
                points[min(end, b + 0.12)] = 1
        if len(points) > 512:
            raise ExplainerError("BGM automation exceeds upstream 512-point limit")
        automation = {"version": 1, "lanes": [{"target": "volume", "points": [
            {"t": time, "v": value} for time, value in sorted(points.items())]}]}
        output.append('<hf-audio-group id="harness-bgm" data-start="0" data-volume="1" data-automation="'
                      + escape(json.dumps(automation, separators=(",", ":")), quote=True) + '"></hf-audio-group>')
        audio(bgm, "harness-bgm-track", start, end - start, "harness-bgm")
    for index, item in enumerate(plan.get("sfx", [])):
        if (not isinstance(item, dict) or set(item) != {"ref", "cue", "event", "tier", "gain"}
                or not all(isinstance(item[key], str) and item[key].strip() for key in ("event", "tier"))):
            raise ExplainerError("SFX needs ref, cue, visible event, tier and gain")
        asset = asset_for(item)
        metadata = asset["metadata"]
        hit = number(metadata.get("hit_offset", 0), "hit_offset")
        start = find_cue(cues, item["cue"]) - hit
        if start < 0:
            raise ExplainerError("sound_negative_preroll")
        from asset_contract import _check_audio
        duration = _check_audio(Path(asset["path"]))["duration"] if "path" in asset else metadata.get("audio", {}).get("duration")
        number(duration, "SFX duration", minimum=0.000001)
        audio(item, f"harness-sfx-{index}", start, duration)
    return "\n".join(output), tracks


class BodyEnd(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.offsets = [0]
        for line in text.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.end = None
        self.feed(text)

    def handle_endtag(self, tag):
        if tag == "body":
            line, col = self.getpos()
            self.end = self.offsets[line - 1] + col


def insert_sound(text, elements):
    start, end = "<!-- harness-sound:start -->", "<!-- harness-sound:end -->"
    block = start + "\n" + elements + "\n" + end
    if start in text or end in text:
        if text.count(start) != 1 or text.count(end) != 1 or text.index(end) < text.index(start):
            raise ExplainerError("Invalid generated sound markers")
        before, tail = text.split(start)
        _, after = tail.split(end)
        return before + block + after
    position = BodyEnd(text).end
    if position is None:
        raise ExplainerError("Sound build requires a closing body element")
    return text[:position] + block + "\n" + text[position:]
