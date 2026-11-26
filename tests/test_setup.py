from tests.support import RehearsalTest, event, keyboard


class SetupTests(RehearsalTest):
    def test_open(self):
        parts = [keyboard('A'), keyboard('B', 'organ', shift=1)]
        self.assertEqual(self.layout(keyboards=parts), {'layout_id': 'weekend', 'keyboards': parts})
        opened = self.open()
        session = opened['session_id']
        self.assertEqual(opened, {'session_id': session, 'layout_id': 'weekend', 'status': 'active', 'keyboards': parts})
        self.assertEqual(self.sound(session), {
            'session_id': session, 'status': 'active', 'pitches': [], 'operations': {}, 'events': [],
        })
        self.assertEqual(self.press(session, 'a', 60)['pitch'], 60)
        self.assertEqual(self.press(session, 'b', 60, 'B')['pitch'], 61)

    def test_invalid_layout(self):
        invalid = [keyboard('A'), keyboard('B', low=72, high=48)]
        self.assertEqual(self.layout('partial', invalid, status=422)['error'], 'invalid_range')
        self.assertEqual(self.open('partial', status=404)['error'], 'layout_not_found')
        duplicate = [keyboard('A'), keyboard('A', shift=1)]
        self.assertEqual(self.layout('duplicates', duplicate, status=422)['error'], 'duplicate_keyboard')
        self.assertEqual(self.open('duplicates', status=404)['error'], 'layout_not_found')
        self.assertEqual(self.layout('bad-shift', [keyboard('A', shift=-49)], status=422)['error'],
                         'invalid_transposition')
        self.assertEqual(self.open('bad-shift', status=404)['error'], 'layout_not_found')
        self.assertEqual(self.sound('s1', status=404)['error'], 'session_not_found')
        self.layout('partial', [keyboard('A'), keyboard('B')])
        self.assertEqual(self.open('partial')['session_id'], 's1')

    def test_repeat_initialize(self):
        parts = [keyboard('C', 'celesta', low=31, high=40, shift=-1)]
        self.layout('custom', parts)
        session = self.open('custom')['session_id']
        original = self.press(session, 'early', 33, 'C')
        self.assertEqual(original['pitch'], 32)
        self.transpose(session, 4, 'C')
        before = self.sound(session)
        self.restart()
        self.assertEqual(self.sound(session), before)
        self.assertEqual(self.operation(session, 'early'), original)
        self.assertEqual(self.press(session, 'later', 36, 'C')['pitch'], 40)
        self.assertEqual(self.sound(session)['events'], [event(1, 'start', 32, 'early'), event(2, 'start', 40, 'later')])
        self.assertEqual(self.open('custom')['keyboards'], parts)
        self.assertEqual(self.open('weekend', status=404)['error'], 'layout_not_found')
