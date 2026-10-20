"""Synthetic vocabulary, trustworthy timing and deliberate recall pauses."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.studio'))
import english_plan
from visual_plan import VisualPlanError, plan_scene_rows


def lesson():
    return {'words': [{'word': 'cat', 'sense': '猫（动物）', 'spelling': 'cat',
                      'pronunciation': {'source': 'Synthetic pronunciation reference', 'language': 'en-US'},
                      'example': {'text': 'My cat is my boss.', 'meaning': '我的猫是我的老板。', 'fictional': True}}],
            'cues': [{'word': 'cat', 'cue': 'cat', 'target': 'I01', 'action': 'pronounce'}],
            'recall': [{'word': 'cat', 'task': 'spelling', 'prompt': 'Recall spelling', 'answer': 'cat',
                        'target': 'I01', 'start_cue': '试', 'end_cue': '答'}]}


CARD = Path(__file__).resolve().parents[1] / '.studio/designs/english/design.json'


def plan(value=None):
    version = json.loads(CARD.read_text())['version'] if CARD.is_file() else 1
    return ('---\n{"plan_format":"3.7.0","mode":"english","line":{"id":"english","version":%d}}\n---\n' % version
            + '## S01\n```english-plan\n' + json.dumps(value if value is not None else lesson()) + '\n```\n'
            '### I01 · P001\n```screen\ncat\n猫\n```\n')


def cues():
    text = 'cat试答'
    return {'schema_version': 1, 'text': text,
            'characters': [{'char': char, 'aligned': True, 'start': i, 'end': i + .5}
                           for i, char in enumerate(text)], 'speech_intervals': [[0, 4.5]]}


NEEDS_CARD = unittest.skipUnless(CARD.is_file(),
                                 'Needs the english card; checked in personal assembly')


class EnglishPlanTest(unittest.TestCase):
    @NEEDS_CARD
    def test_lesson_projects_without_storyboard_and_preserves_recall_pause(self):
        text = plan()
        row = plan_scene_rows(text)['S01']
        self.assertEqual([], row['segments'])
        self.assertEqual(['english_pronounce', 'english_hide', 'english_answer'],
                         [event['change'] for event in row['events']])
        self.assertEqual('pause', row['exceptions'][0]['kind'])
        self.assertEqual([], english_plan.check(text, cues(), [{'id': 'S01', 'start': 0, 'duration': 5}]))
        self.assertEqual('english_timing_unverified', english_plan.check(text)[0]['code'])

    def test_blank_spelling_source_and_mnemonic_cannot_claim_completion(self):
        cases = [('spelling', 'cta', 'spelling_mismatch'), ('sense', '<sense>', 'invalid_english_word'),
                 ('pronunciation', {'source': '', 'language': 'en-US'}, 'pronunciation_source'),
                 ('mnemonic', {'kind': 'etymology', 'text': 'sounds similar'}, 'invalid_english_mnemonic')]
        for key, value, message in cases:
            data = lesson()
            data['words'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                english_plan.parse_plan(plan(data))
        with self.assertRaisesRegex(ValueError, 'invalid_english_plan'):
            english_plan.parse_plan(plan({'words': [], 'cues': [], 'recall': []}))

    def test_keyword_blocks_hook_the_stressed_syllable_of_the_dictionary_split(self):
        data = lesson()
        data['words'][0].update(word='diligent', spelling='diligent')
        data['cues'][0]['cue'] = data['recall'][0]['answer'] = data['recall'][0]['word'] = 'diligent'
        data['cues'][0]['word'] = 'diligent'
        syllables = [{'letters': 'dil', 'ipa': 'ˈdɪl', 'stressed': True}, {'letters': 'i', 'ipa': 'ɪ', 'stressed': False},
                     {'letters': 'gent', 'ipa': 'dʒənt', 'stressed': False}]
        blocks = [{'letters': 'di', 'zh': '地', 'pinyin': 'di'}, {'letters': 'li', 'zh': '里', 'pinyin': 'li'},
                  {'letters': 'gent', 'zh': '耕田', 'pinyin': 'geng tian'}]
        mnemonic = data['words'][0]['mnemonic'] = {'kind': 'homophone', 'text': '宽松联想，非词源',
                                                   'syllables': syllables, 'blocks': blocks}
        english_plan.parse_plan(plan(data))
        # A keyword may cover only part of the word, as long as it hooks the stressed syllable.
        mnemonic['blocks'] = [{'letters': 'dili', 'zh': '地里', 'pinyin': 'di li'}, {'letters': 'gent'}]
        english_plan.parse_plan(plan(data))
        mnemonic['kind'] = 'morphology'
        mnemonic['blocks'] = [{'letters': 'dili', 'zh': '珍视'}, {'letters': 'gent', 'zh': '…的'}]
        english_plan.parse_plan(plan(data))
        mnemonic['kind'] = 'homophone'
        for change, message in (
                ({'blocks': [{'letters': 'dili'}, {'letters': 'gent', 'zh': '耕田', 'pinyin': 'geng tian'}]},
                 'misses_stressed_syllable'),
                ({'blocks': blocks[:2]}, 'english_mnemonic_spelling_mismatch'),
                ({'syllables': syllables[:2]}, 'english_mnemonic_spelling_mismatch'),
                ({'syllables': [{**item, 'stressed': False} for item in syllables]}, 'invalid_english_mnemonic_syllables'),
                ({'syllables': None}, 'invalid_english_mnemonic_syllables'),
                ({'blocks': [{**blocks[0], 'pinyin': ''}, *blocks[1:]]}, 'invalid_english_mnemonic_blocks'),
                ({'blocks': [{'letters': 'di', 'zh': '地'}, *blocks[1:]]}, 'invalid_english_mnemonic_blocks'),
                ({'blocks': [{'letters': 'diligent'}]}, 'invalid_english_mnemonic_blocks')):
            broken = {**mnemonic, 'syllables': syllables, 'blocks': blocks, **change}
            broken = {key: value for key, value in broken.items() if value is not None}
            case = {**data, 'words': [{**data['words'][0], 'mnemonic': broken}]}
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                english_plan.parse_plan(plan(case))

    def test_keyword_emphasis_waits_for_the_real_pronunciation(self):
        data = lesson()
        data['cues'].insert(0, {'word': 'cat', 'cue': '试', 'target': 'I01', 'action': 'emphasize'})
        with self.assertRaisesRegex(ValueError, 'english_mnemonic_before_pronunciation'):
            english_plan.parse_plan(plan(data))
        data['cues'].append(data['cues'].pop(0))
        english_plan.parse_plan(plan(data))

    @NEEDS_CARD
    def test_declared_targets_and_recall_answers_are_checked(self):
        data = lesson()
        data['cues'][0]['target'] = 'I99'
        with self.assertRaisesRegex(VisualPlanError, 'english_unknown_screen'):
            plan_scene_rows(plan(data))
        data = lesson()
        data['recall'][0]['answer'] = 'cta'
        with self.assertRaisesRegex(ValueError, 'english_recall_spelling_mismatch'):
            english_plan.parse_plan(plan(data))
        data = lesson()
        data['recall'] = []
        self.assertEqual([], english_plan.check(plan(data), cues()))
        self.assertEqual([], plan_scene_rows(plan(data))['S01']['exceptions'])
        data = lesson()
        data['cues'][0]['cue'] = 'dog'
        with self.assertRaisesRegex(ValueError, 'english_pronunciation_cue_mismatch'):
            english_plan.parse_plan(plan(data))

    def test_cues_need_real_alignment_and_positive_recall_interval(self):
        data = cues()
        data['characters'][0].update(aligned=False, start=None, end=None)
        self.assertEqual('english_unresolved_cue', english_plan.check(plan(), data)[0]['code'])
        data = lesson()
        data['recall'][0]['end_cue'] = '试'
        self.assertEqual('english_recall_interval', english_plan.check(plan(data), cues())[0]['code'])
        bounds = [{'id': 'S01', 'start': 0, 'duration': 2}]
        self.assertEqual('english_unresolved_cue', english_plan.check(plan(), cues(), bounds)[0]['code'])
        data = lesson()
        data['cues'][0]['cue'] = {'token': 'cat', 'within': [0, 3]}
        self.assertEqual([], english_plan.check(plan(data), cues()))
        data['cues'][0]['cue']['within'] = [0, float('nan')]
        with self.assertRaisesRegex(ValueError, 'invalid_english_cue'):
            english_plan.parse_plan(plan(data))

    @NEEDS_CARD
    def test_later_scene_can_hold_recall_without_fixed_ab_or_word_quota(self):
        first, second = lesson(), lesson()
        first['recall'] = []
        second['cues'][0].update(action='reveal', target='I02')
        second['recall'][0]['target'] = 'I02'
        text = plan(first) + '\n## S02\n```english-plan\n' + json.dumps(second) + '\n```\n### I02 · P002\n```screen\ncat\n```\n'
        self.assertEqual({'S01', 'S02'}, set(plan_scene_rows(text)))
        second['words'][0]['sense'] = 'Different sense'
        with self.assertRaisesRegex(ValueError, 'english_word_definition_changed'):
            english_plan.parse_plan(plan(first) + '\n## S02\n```english-plan\n' + json.dumps(second) + '\n```\n')


if __name__ == '__main__':
    unittest.main()
