"""Stage emptiness evidence and scene margins without a browser or WorkStore."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
from stage_checks import frame_blank


class StageChecksTests(unittest.TestCase):
    scenes = [{'id': 'S01', 'start': 0, 'duration': 3},
              {'id': 'S02', 'start': 3, 'duration': 3}]

    def sample(self, time, visible=0, *, ready=True):
        return dict(time=time, ready=ready, stage_visible=visible)

    def empty(self, scene, start, end):
        return dict(kind='stage_empty', scene=scene, start=start, end=end)

    def test_consecutive_empty_samples_merge_in_time_order(self):
        samples = [self.sample(time) for time in [5, 4, 4.5]]
        original = copy.deepcopy(samples)
        report = frame_blank(samples, self.scenes)
        self.assertEqual({'findings': [self.empty('S02', 4, 5)], 'unverified': []}, report)
        self.assertEqual(original, samples)

    def test_edges_and_outside_scenes_are_excluded(self):
        samples = [self.sample(time) for time in [-1, .3, 2.7, 3.3, 5.7, 7]]
        self.assertEqual([], frame_blank(samples, self.scenes)['findings'])

    def test_missing_visibility_is_unverified(self):
        report = frame_blank([dict(time=4, ready=True)], self.scenes)
        self.assertEqual({'findings': [], 'unverified': [
            {'reason': 'stage_visibility_not_sampled', 'time': 4}]}, report)

    def test_visible_stage_has_no_finding(self):
        self.assertEqual({'findings': [], 'unverified': []},
                         frame_blank([self.sample(4, 1)], self.scenes))

    def test_nonempty_or_unobserved_samples_interrupt_spans(self):
        for middle in [self.sample(4.5, 1), self.sample(4.5, ready=False),
                       dict(time=4.5, ready=True)]:
            with self.subTest(middle=middle):
                report = frame_blank([self.sample(4), middle, self.sample(5)], self.scenes)
                self.assertEqual([self.empty('S02', 4, 4), self.empty('S02', 5, 5)],
                                 report['findings'])

    def test_not_ready_samples_are_ignored(self):
        samples = [self.sample(4, ready=False), dict(time=5, ready=False)]
        self.assertEqual({'findings': [], 'unverified': []}, frame_blank(samples, self.scenes))

    def test_inclusive_margins_and_scene_separation(self):
        samples = [self.sample(time) for time in [.5, 2.5, 3.5, 5.5]]
        self.assertEqual([self.empty('S01', .5, 2.5), self.empty('S02', 3.5, 5.5)],
                         frame_blank(samples, self.scenes)['findings'])

    def test_custom_margin_and_short_scene(self):
        self.assertEqual([self.empty('S01', .3, .3)],
                         frame_blank([self.sample(.3)], self.scenes, margin=.2)['findings'])
        self.assertEqual([], frame_blank([self.sample(.3)],
                         [dict(id='short', start=0, duration=.6)])['findings'])

    def test_sparse_foreground_reported_only_with_threshold(self):
        samples = [dict(self.sample(time, 4), stage_coverage=cover)
                   for time, cover in [(3.5, .30), (4, .08), (4.5, .12), (5, .25)]]
        self.assertEqual([], frame_blank(samples, self.scenes)['findings'])
        report = frame_blank(samples, self.scenes, coverage_min=.18)
        self.assertEqual([dict(kind='stage_sparse', scene='S02', start=4, end=4.5, coverage=.08)],
                         report['findings'])
        self.assertEqual([], report['unverified'])

    def test_empty_and_sparse_spans_do_not_merge(self):
        samples = [self.sample(4), dict(self.sample(4.5, 2), stage_coverage=.05)]
        self.assertEqual([self.empty('S02', 4, 4),
                          dict(kind='stage_sparse', scene='S02', start=4.5, end=4.5, coverage=.05)],
                         frame_blank(samples, self.scenes, coverage_min=.18)['findings'])

    def test_missing_coverage_is_unverified_when_threshold_declared(self):
        report = frame_blank([self.sample(4, 3)], self.scenes, coverage_min=.18)
        self.assertEqual({'findings': [], 'unverified': [
            {'reason': 'stage_coverage_not_sampled', 'time': 4}]}, report)

    def test_empty_inputs(self):
        self.assertEqual({'findings': [], 'unverified': []}, frame_blank([], self.scenes))
        self.assertEqual({'findings': [], 'unverified': []}, frame_blank([self.sample(4)], []))


if __name__ == '__main__':
    unittest.main()


class MissingTimeTest(unittest.TestCase):
    def test_sample_without_time_is_unverified_not_an_error(self):
        result = frame_blank([{'ready': False}, {'time': 1.0, 'ready': True, 'stage_visible': 3}],
                                          [{'id': 'S01', 'start': 0, 'duration': 4}])
        self.assertEqual([], result['findings'])
        self.assertIn({'reason': 'stage_sample_time_missing'}, result['unverified'])
