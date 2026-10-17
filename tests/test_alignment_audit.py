import io
import math
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import alignment_audit as audit


def tone_wav(path, spans, total, rate=16000):
    """Speech-like tone inside spans, digital silence elsewhere."""
    frames = bytearray()
    for n in range(int(total * rate)):
        t = n / rate
        value = int(8000 * math.sin(2 * math.pi * 220 * t)) if any(a <= t < b for a, b in spans) else 0
        frames += value.to_bytes(2, 'little', signed=True)
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(bytes(frames))


def chars(times, text=None):
    text = text or 'abcdefghijklmnopqrstuvwxyz'[:len(times)]
    return [{'char': c, 'aligned': True, 'start': a, 'end': b} for c, (a, b) in zip(text, times)]


class AlignmentAuditTest(unittest.TestCase):
    def test_evidence_must_come_from_a_tool_or_provider(self):
        self.assertIn('no longer accepted', audit.evidence_errors({'method': 'manual-measured'})[0])
        self.assertTrue(audit.evidence_errors({'method': 'forced-alignment'}))
        self.assertTrue(audit.evidence_errors({'method': 'guess'}))
        self.assertEqual([], audit.evidence_errors({'method': 'forced-alignment', 'engine': 'aligner 1.0'}))
        self.assertEqual([], audit.evidence_errors({'method': 'provider-native'}))

    def test_evenly_divided_timing_is_refused(self):
        even = chars([(i * 0.2, (i + 1) * 0.2) for i in range(12)])
        self.assertIn('evenly divided', audit.audit(even)['errors'][0])
        varied = chars([(i * 0.2, i * 0.2 + 0.1 + 0.08 * (i % 3)) for i in range(12)])
        self.assertTrue(audit.audit(varied)['ok'])

    def test_silent_characters_and_unclaimed_speech_become_suspects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.wav'
            tone_wav(path, [(0.0, 0.5), (1.0, 2.0)], 2.5)
            # a, b sit on speech; c sits in the 0.5-1.0 gap; nothing claims 1.2-2.0.
            report = audit.audit(chars([(0.0, 0.2), (0.25, 0.45), (0.6, 0.9), (1.0, 1.2)]), path, 2.5)
            self.assertTrue(report['ok'])
            reasons = [(row['reason'], row['char']) for row in report['suspects']]
            self.assertIn(('silent', 'c'), reasons)
            self.assertIn(('unclaimed-speech', None), reasons)
            self.assertNotIn(('silent', 'a'), reasons)
            clean = audit.audit(chars([(0.0, 0.2), (0.25, 0.45), (1.0, 1.5), (1.5, 2.0)]), path, 2.5)
            self.assertEqual([], clean['suspects'])

    def test_odd_lengths_are_suspects_without_audio(self):
        report = audit.audit(chars([(0.0, 0.01), (0.1, 1.5), (1.6, 1.8)]))
        self.assertEqual([('too-short', 'a'), ('too-long', 'b')], [(r['reason'], r['char']) for r in report['suspects']])


if __name__ == '__main__':
    unittest.main()
