"""Sampled stage visibility clues, not a pass/fail verdict."""


def frame_blank(samples, scenes, *, margin=0.5):
    """Find empty stage spans inside scene middles, excluding edge margins.

    samples contain time, ready and stage_visible; scenes contain id, start
    and duration. Return {'findings': [...], 'unverified': [...]} without
    mutating inputs. Unavailable or unmeasured samples interrupt empty spans.
    """
    findings, unverified = [], []
    usable = []
    for sample in samples:
        if isinstance(sample.get('time'), (int, float)) and not isinstance(sample.get('time'), bool):
            usable.append(sample)
        else:
            unverified.append({'reason': 'stage_sample_time_missing'})
    ordered = sorted(usable, key=lambda sample: sample['time'])
    for sample in ordered:
        if sample.get('ready') and 'stage_visible' not in sample:
            unverified.append({'reason': 'stage_visibility_not_sampled', 'time': sample['time']})
    for scene in scenes:
        current = None
        start = scene['start'] + margin
        end = scene['start'] + scene['duration'] - margin
        for sample in ordered:
            time = sample['time']
            if (not start <= time <= end or not sample.get('ready') or
                    sample.get('stage_visible') != 0):
                current = None
                continue
            if current is None:
                current = {'kind': 'stage_empty', 'scene': scene['id'], 'start': time, 'end': time}
                findings.append(current)
            else:
                current['end'] = time
    return {'findings': findings, 'unverified': unverified}
