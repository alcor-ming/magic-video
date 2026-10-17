"""Mechanical audit of formal speech alignment against its own audio.

Hard errors refuse adoption: hand-entered timing, missing tool provenance and evenly divided
durations. Suspects are listed for the per-character check: the executor handles only these rows.
"""
from array import array
from pathlib import Path
import statistics
import wave

TOOL_METHODS = {'forced-alignment', 'asr'}
ACCEPTED_METHODS = TOOL_METHODS | {'provider-native'}
FRAME_SECONDS = 0.01
SILENCE_RATIO = 0.02        # frame RMS below 2% of the loudest frame counts as silence
UNIFORM_MIN_CHARS = 12
UNIFORM_MAX_CV = 0.05
SILENT_CHAR_SHARE = 0.8
UNCLAIMED_SPEECH = 0.6
SHORT_CHAR, LONG_CHAR = 0.02, 1.0


def evidence_errors(evidence):
    method = evidence.get('method')
    if method == 'manual-measured':
        return ['Hand-measured timing is no longer accepted; produce the alignment with the alignment tool']
    if method not in ACCEPTED_METHODS:
        return ['Alignment method must be forced-alignment, asr or provider-native']
    engine = evidence.get('engine')
    if method in TOOL_METHODS and (not isinstance(engine, str) or not engine.strip()):
        return ['Tool alignment must record its engine (name and version)']
    return []


def envelope(path):
    """10 ms RMS frames; pure Python so the audit runs without managed numeric packages."""
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
        raw = audio.readframes(frames)
    if width == 1:
        samples = [value - 128 for value in raw]
    elif width in (2, 4):
        samples = array('h' if width == 2 else 'i')
        samples.frombytes(raw)
        if samples.itemsize != width:
            raise ValueError('Unsupported PCM sample width')
    elif width == 3:
        samples = [int.from_bytes(raw[i:i + 3], 'little', signed=True) for i in range(0, len(raw), 3)]
    else:
        raise ValueError('Unsupported PCM sample width')
    step = max(1, rate // 8000)  # decimate to ~8 kHz; loudness, not pitch, is measured
    size = max(1, int(rate * FRAME_SECONDS))
    out = []
    for start in range(0, frames, size):
        chunk = samples[start * channels:(start + size) * channels:channels * step]
        out.append((sum(v * v for v in chunk) / len(chunk)) ** 0.5 if chunk else 0.0)
    return out


def audit(characters, audio_path=None, duration=None):
    spoken = [(index, c) for index, c in enumerate(characters) if c['char'].isalnum()]
    timed = [(index, c) for index, c in spoken if c.get('aligned')]
    errors, suspects = [], []
    lengths = [c['end'] - c['start'] for _, c in timed]
    cv = statistics.pstdev(lengths) / statistics.mean(lengths) if len(lengths) > 1 and statistics.mean(lengths) > 0 else None
    contiguous = all(abs(b['start'] - a['end']) <= 0.001 for (_, a), (_, b) in zip(timed, timed[1:]))
    if len(timed) >= UNIFORM_MIN_CHARS and cv is not None and cv < UNIFORM_MAX_CV and contiguous:
        errors.append('Character durations are evenly divided; measure the audio instead of splitting time')
    for index, c in timed:
        length = c['end'] - c['start']
        if length < SHORT_CHAR or length > LONG_CHAR:
            suspects.append({'index': index, 'char': c['char'], 'start': c['start'], 'end': c['end'],
                             'reason': 'too-short' if length < SHORT_CHAR else 'too-long'})
    silent_share = None
    if audio_path is not None:
        frames = envelope(Path(audio_path))
        peak = max(frames, default=0.0)
        voiced = [value > peak * SILENCE_RATIO for value in frames] if peak > 0 else [False] * len(frames)

        def silent(start, end):
            first, last = int(start / FRAME_SECONDS), max(int(start / FRAME_SECONDS) + 1, int(end / FRAME_SECONDS))
            window = voiced[first:last]
            return 1.0 if not window else 1 - sum(window) / len(window)
        shares = []
        for index, c in timed:
            share = silent(c['start'], c['end'])
            shares.append(share)
            if share >= SILENT_CHAR_SHARE:
                suspects.append({'index': index, 'char': c['char'], 'start': c['start'], 'end': c['end'], 'reason': 'silent'})
        silent_share = round(statistics.mean(shares), 4) if shares else None
        covered = [False] * len(voiced)
        for _, c in timed:
            for frame in range(int(c['start'] / FRAME_SECONDS), min(len(covered), int(c['end'] / FRAME_SECONDS) + 1)):
                covered[frame] = True
        run = None
        for frame, (speech, claimed) in enumerate(zip(voiced + [False], covered + [True])):
            if speech and not claimed:
                run = frame if run is None else run
            elif run is not None:
                if (frame - run) * FRAME_SECONDS >= UNCLAIMED_SPEECH:
                    suspects.append({'index': None, 'char': None, 'start': round(run * FRAME_SECONDS, 3),
                                     'end': round(frame * FRAME_SECONDS, 3), 'reason': 'unclaimed-speech'})
                run = None
    suspects.sort(key=lambda row: (row['start'], row['index'] is None))
    return {'ok': not errors, 'errors': errors, 'suspects': suspects,
            'stats': {'spoken': len(spoken), 'aligned': len(timed), 'duration_cv': None if cv is None else round(cv, 4),
                      'mean_silent_share': silent_share, 'audio_duration': duration}}
