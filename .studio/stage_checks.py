"""Sampled stage visibility clues, not a pass/fail verdict."""


def frame_blank(samples, scenes, *, margin=0.5, coverage_min=None):
    """Find empty or sparse stage spans inside scene middles, excluding edge margins.

    samples contain time, ready, stage_visible and optionally stage_coverage (share
    of the frame painted by foreground stage elements, scenery excluded); scenes
    contain id, start and duration. A sample is 'stage_empty' when nothing on the
    stage paints, and 'stage_sparse' when coverage_min is given and foreground
    coverage falls below it. Return {'findings': [...], 'unverified': [...]}
    without mutating inputs. Unavailable or unmeasured samples interrupt spans.
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
        elif (sample.get('ready') and coverage_min is not None and sample.get('stage_visible')
              and not _number(sample.get('stage_coverage'))):
            unverified.append({'reason': 'stage_coverage_not_sampled', 'time': sample['time']})

    def kind(sample):
        if not sample.get('ready'):
            return None
        if sample.get('stage_visible') == 0:
            return 'stage_empty'
        coverage = sample.get('stage_coverage')
        if coverage_min is not None and _number(coverage) and coverage < coverage_min:
            return 'stage_sparse'
        return None

    for scene in scenes:
        current = None
        start = scene['start'] + margin
        end = scene['start'] + scene['duration'] - margin
        for sample in ordered:
            time = sample['time']
            found = kind(sample) if start <= time <= end else None
            if found is None:
                current = None
                continue
            if current is None or current['kind'] != found:
                current = {'kind': found, 'scene': scene['id'], 'start': time, 'end': time}
                if found == 'stage_sparse':
                    current['coverage'] = sample['stage_coverage']
                findings.append(current)
            else:
                current['end'] = time
                if found == 'stage_sparse':
                    current['coverage'] = min(current['coverage'], sample['stage_coverage'])
    return {'findings': findings, 'unverified': unverified}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
