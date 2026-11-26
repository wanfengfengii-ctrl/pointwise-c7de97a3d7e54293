import sqlite3
from contextlib import closing

from tests.support import RehearsalTest, event


class ReviewTests(RehearsalTest):
    def test_reopen_history(self):
        session = self.open_default()
        p_a = self.press(session, 'pA', 60)
        self.transpose(session, 2)
        self.press(session, 'pB', 60)
        r_a = self.release(session, 'rA', 'pA')
        self.release(session, 'rB', 'pB')
        expected = [event(1, 'start', 60, 'pA'), event(2, 'start', 62, 'pB'),
                    event(3, 'stop', 60, 'rA'), event(4, 'stop', 62, 'rB')]
        self.assertEqual(self.sound(session)['events'], expected)
        closed = self.close_session(session)
        self.restart()
        view = self.sound(session)
        self.assertEqual(view, closed['sound'])
        self.assertEqual(view['events'], expected)
        self.assertEqual(view['operations'], {'pA': 60, 'pB': 62, 'rA': 60, 'rB': 62})
        self.assertEqual(view['pitches'], [])
        self.assertEqual(self.operation(session, 'pA'), p_a)
        self.assertEqual(self.operation(session, 'rA'), r_a)
        self.assertEqual(self.close_session(session), closed)

    def test_closed_session(self):
        session = self.open_default()
        original = self.press(session, 'pA', 60)
        closed = self.close_session(session)
        self.restart()
        self.assertEqual(self.press(session, 'new', 60, status=409)['error'], 'session_closed')
        self.assertEqual(self.release(session, 'new-release', 'pA', status=409)['error'], 'session_closed')
        self.assertEqual(self.transpose(session, 2, status=409)['error'], 'session_closed')
        self.assertEqual(self.operation(session, 'new', status=404)['error'], 'operation_not_found')
        self.assertEqual(self.operation(session, 'new-release', status=404)['error'], 'operation_not_found')
        self.assertEqual(self.press(session, 'pA', 61, status=409)['error'], 'request_conflict')
        self.assertEqual(self.press(session, 'pA', 60), original)
        self.assertEqual(self.operation(session, 'pA'), original)
        self.assertEqual(self.sound(session), closed['sound'])
        self.assertEqual(self.sound('missing', status=404)['error'], 'session_not_found')
        self.assertEqual(self.operation('missing', 'pA', status=404)['error'], 'operation_not_found')
        self.assertEqual(self.close_session('missing', status=404)['error'], 'session_not_found')
        other = self.open()['session_id']
        self.assertEqual(self.sound(other)['events'], [])
        self.operation(other, 'pA', status=404)

    def test_close_held(self):
        session = self.open_default()
        self.press(session, 'high', 63)
        self.press(session, 'pA', 60)
        self.press(session, 'pB', 59, 'B')
        closed = self.close_session(session)
        self.assertEqual(closed['sound']['events'], [
            event(1, 'start', 63, 'high'), event(2, 'start', 60, 'pA'),
            event(3, 'stop', 60, None), event(4, 'stop', 63, None),
        ])
        self.assertEqual(closed['sound']['pitches'], [])
        self.assertEqual(self.close_session(session), closed)

    def test_close_retry(self):
        session = self.open_default()
        self.transport.drop_reply(session, 'pA')
        self.press(session, 'pA', 60, status=202)
        # Reject a real INSERT in the final transaction after silence_session has written its changes.
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('''
                CREATE TRIGGER refuse_archive BEFORE INSERT ON session_archives
                BEGIN SELECT RAISE(ABORT, 'archive temporarily unavailable'); END
            ''')
        self.assertEqual(self.close_session(session, status=500)['error'], 'internal_error')
        self.assertEqual(self.operation(session, 'pA')['pitch'], 60)
        self.assertEqual(self.sound(session), {
            'session_id': session, 'status': 'active', 'pitches': [60],
            'operations': {'pA': 60}, 'events': [event(1, 'start', 60, 'pA')],
        })
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM session_archives').fetchone()[0], 0)
            connection.execute('DROP TRIGGER refuse_archive')
        self.restart()
        closed = self.close_session(session)
        self.assertEqual(closed['sound']['events'], [event(1, 'start', 60, 'pA'), event(2, 'stop', 60, None)])
        self.assertEqual(self.close_session(session), closed)

    def test_close_drains_dependencies_before_sealing(self):
        session = self.open_default()
        with self.delay_press(session, 'pA', 60) as (gate, pending_press):
            self.release(session, 'rA', 'pA', status=202)
            closed = self.close_session(session)
            self.assertEqual(closed['sound']['events'], [event(1, 'start', 60, 'pA'), event(2, 'stop', 60, 'rA')])
            self.assertEqual([item['status'] for item in closed['operations']], ['completed', 'completed'])
            self.assertEqual(self.operation(session, 'rA')['pitch'], 60)
            gate.resume.set()
            self.assertEqual(pending_press.result(timeout=10), self.operation(session, 'pA'))
        self.assertEqual(self.close_session(session), closed)
