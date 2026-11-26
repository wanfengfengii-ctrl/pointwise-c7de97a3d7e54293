from tests.support import RehearsalTest, event


class PlayTests(RehearsalTest):
    def test_unison(self):
        session = self.open_default()
        self.assertEqual(self.press(session, 'pA', 60)['pitch'], 60)
        self.assertEqual(self.press(session, 'pB', 59, 'B')['pitch'], 60)
        other = self.open()['session_id']
        self.press(other, 'pA', 60)
        self.assertEqual(self.release(other, 'wrong-session', 'pB', 'B', status=422)['error'], 'invalid_reference')
        self.assertEqual(self.release(session, 'wrong-keyboard', 'pA', 'B', status=422)['error'], 'invalid_reference')
        self.operation(session, 'wrong-keyboard', status=404)
        start = event(1, 'start', 60, 'pA')
        self.assertEqual(self.sound(session)['events'], [start])
        released = self.release(session, 'rA', 'pA')
        self.assertEqual(released['pitch'], 60)
        self.assertEqual(self.release(session, 'rA', 'pA'), released)
        self.assertEqual(self.release(session, 'wrong-type', 'rA', status=422)['error'], 'invalid_reference')
        self.assertEqual(self.release(session, 'again', 'pA', status=422)['error'], 'invalid_reference')
        self.assertEqual(self.operation(session, 'again')['status'], 'rejected')
        self.assertEqual(self.sound(session)['pitches'], [60])
        self.assertEqual(self.sound(session)['events'], [start])
        self.assertEqual(self.release(session, 'rB', 'pB', 'B')['pitch'], 60)
        self.assertEqual(self.sound(session), {
            'session_id': session, 'status': 'active', 'pitches': [],
            'operations': {'pA': 60, 'pB': 60, 'rA': 60, 'rB': 60},
            'events': [start, event(2, 'stop', 60, 'rB')],
        })
        self.assertEqual(self.sound(other)['pitches'], [60])
        self.assertEqual(self.sound(other)['events'], [start])

    def test_held_note(self):
        session = self.open_default()
        self.assertEqual(self.press(session, 'old', 60)['pitch'], 60)
        self.transpose(session, 2)
        self.assertEqual(self.sound(session)['pitches'], [60])
        self.assertEqual(self.release(session, 'up', 'old')['pitch'], 60)
        self.assertEqual(self.sound(session)['pitches'], [])
        self.assertEqual(self.sound(session)['events'][-1], event(2, 'stop', 60, 'up'))
        self.assertEqual(self.press(session, 'new', 60)['pitch'], 62)
        self.assertEqual(self.sound(session)['events'], [
            event(1, 'start', 60, 'old'), event(2, 'stop', 60, 'up'), event(3, 'start', 62, 'new'),
        ])

    def test_late_delivery(self):
        session = self.open_default()
        self.press(session, 'pA', 60)
        self.press(session, 'pB', 59, 'B')
        with self.delay_press(session, 'pC', 61) as (gate, pending_press):
            self.assertEqual(self.operation(session, 'pC')['status'], 'pending')
            self.assertEqual(self.sound(session)['pitches'], [60])
            self.assertEqual(self.transpose(session, 2)['transposition'], 2)
            gate.resume.set()
            self.assertEqual(pending_press.result(timeout=10)['pitch'], 63)
        self.assertEqual(self.operation(session, 'pC')['pitch'], 63)
        self.assertEqual(self.release(session, 'rA', 'pA')['pitch'], 60)
        self.assertEqual(self.sound(session)['pitches'], [60, 63])
        starts = [event(1, 'start', 60, 'pA'), event(2, 'start', 63, 'pC')]
        self.assertEqual(self.sound(session)['events'], starts)
        self.release(session, 'rB', 'pB', 'B')
        self.assertEqual(self.sound(session)['pitches'], [63])
        self.assertEqual(self.sound(session)['events'], starts + [event(3, 'stop', 60, 'rB')])

    def test_invalid_shift(self):
        session = self.open_default()
        for shift in (56, -49, True, 1.5):
            with self.subTest(shift=shift):
                result = self.transpose(session, shift, status=422)
                self.assertEqual(result['error'], 'invalid_transposition')
        self.assertEqual(self.transpose(session, 0, 'missing', status=404)['error'], 'keyboard_not_found')
        for key in (47, 73, False, 60.0):
            self.assertEqual(self.press(session, 'bad', key, status=422)['error'], 'invalid_key')
        self.operation(session, 'bad', status=404)
        self.assertEqual(self.sound(session)['events'], [])
        self.assertEqual(self.press(session, 'pA', 60)['pitch'], 60)
        self.assertEqual(self.sound(session)['events'], [event(1, 'start', 60, 'pA')])
        self.transpose(session, 55)
        self.assertEqual(self.press(session, 'top', 72)['pitch'], 127)
        self.transpose(session, -48)
        self.assertEqual(self.press(session, 'bottom', 48)['pitch'], 0)
