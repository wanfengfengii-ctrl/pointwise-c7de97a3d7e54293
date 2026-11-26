from tests.support import RehearsalTest, event


class RecoveryTests(RehearsalTest):
    def test_strike_reply(self):
        session = self.open_default()
        self.transport.drop_reply(session, 'pC')
        response = self.press(session, 'pC', 61, status=202)
        self.assertEqual(response['status'], 'pending')
        self.assertNotIn('pitch', response)
        self.assertEqual(self.operation(session, 'pC'), response)
        self.assertEqual(self.sound(session)['operations'], {'pC': 61})
        start = event(1, 'start', 61, 'pC')
        self.assertEqual(self.sound(session)['events'], [start])
        self.transpose(session, 2)
        self.restart()
        self.assertEqual(self.operation(session, 'pC'), response)
        self.assertEqual(self.press(session, 'pC', 62, status=409)['error'], 'request_conflict')
        received = self.press(session, 'pC', 61)
        self.assertEqual(received['pitch'], 61)
        self.assertEqual(self.operation(session, 'pC'), received)
        self.assertEqual(self.press(session, 'pC', 62, status=409)['error'], 'request_conflict')
        self.assertEqual(self.sound(session)['events'], [start])
        self.assertEqual(self.release(session, 'rC', 'pC')['pitch'], 61)
        self.assertEqual(self.sound(session)['events'], [start, event(2, 'stop', 61, 'rC')])

    def test_release_reply(self):
        session = self.open_default()
        self.press(session, 'pA', 60)
        self.press(session, 'pB', 59, 'B')
        self.transport.drop_reply(session, 'rA')
        self.assertEqual(self.release(session, 'rA', 'pA', status=202)['status'], 'pending')
        self.assertEqual(self.sound(session)['operations']['rA'], 60)
        self.restart()
        self.assertEqual(self.release(session, 'rA', 'pA')['pitch'], 60)
        self.assertEqual(self.release(session, 'rA', 'pB', status=409)['error'], 'request_conflict')
        self.assertEqual(self.sound(session)['pitches'], [60])
        self.assertEqual(self.sound(session)['events'], [event(1, 'start', 60, 'pA')])
        self.release(session, 'rB', 'pB', 'B')
        self.assertEqual(self.sound(session)['events'][-1], event(2, 'stop', 60, 'rB'))

    def test_release_waits_for_press(self):
        session = self.open_default()
        with self.delay_press(session, 'pA', 60) as (gate, pending_press):
            pending = self.release(session, 'rA', 'pA', status=202)
            self.assertEqual(self.operation(session, 'rA'), pending)
            self.assertEqual(self.sound(session)['events'], [])
            self.transpose(session, 2)
            gate.resume.set()
            self.assertEqual(pending_press.result(timeout=10)['pitch'], 62)
        self.assertEqual(self.release(session, 'rA', 'pA')['pitch'], 62)
        self.assertEqual(self.sound(session)['events'], [event(1, 'start', 62, 'pA'), event(2, 'stop', 62, 'rA')])
