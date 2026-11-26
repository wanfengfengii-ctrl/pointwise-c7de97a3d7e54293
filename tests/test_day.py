import json
import unittest
from pathlib import Path

from tests.support import RehearsalTest

SAMPLE_DIRECTORY = Path(__file__).resolve().parent.parent / 'samples'


class DayTests(RehearsalTest):
    def test_weekend_rehearsal(self):
        scenario = json.loads((SAMPLE_DIRECTORY / 'weekend.json').read_text(encoding='utf-8'))
        expected = json.loads((SAMPLE_DIRECTORY / 'weekend-expected.json').read_text(encoding='utf-8'))
        layout = scenario['layout']
        self.assertEqual(self.request('POST', '/layouts', layout, status=201), layout)
        opened = self.open(layout['layout_id'])
        session = opened['session_id']
        self.assertEqual(opened['keyboards'], layout['keyboards'])
        initial = self.sound(session)
        self.assertEqual(initial['pitches'], [])
        self.assertEqual(initial['events'], [])
        self.assertEqual(initial['operations'], {})
        pitches = {}
        checkpoints = {}
        for step in scenario['play']:
            operation = step['operation']
            body = {key: value for key, value in step.items() if key != 'operation'}
            body['session_id'] = session
            if operation == 'transpose':
                result = self.request('POST', '/transpositions', body)
                self.assertEqual(result['transposition'], step['transposition'])
            else:
                result = self.request('POST', f'/keys/{operation}', body)
                self.assertEqual(result['status'], 'completed')
                request_id = step['request_id']
                pitches[request_id] = result['pitch']
                checkpoints[request_id] = self.sound(session)['pitches']
        live = self.sound(session)
        actual = {'pitches_by_request': pitches, 'checkpoints': checkpoints, 'events': live['events']}
        self.assertEqual(actual, expected['play'])
        self.assertEqual(live['operations'], expected['play']['pitches_by_request'])
        closed = self.close_session(session)
        self.restart()
        archived = self.sound(session)
        old_receipt = self.operation(session, scenario['lookup_request'])
        rejected = self.request('POST', '/keys/press', {**scenario['after_close'], 'session_id': session}, status=409)
        self.assertEqual(archived, closed['sound'])
        self.assertEqual(self.close_session(session), closed)
        self.assertEqual(old_receipt['status'], 'completed')
        self.operation(session, scenario['after_close']['request_id'], status=404)
        downstream = {
            'status': archived['status'], 'pitches': archived['pitches'], 'events': archived['events'],
            'pitches_by_request': archived['operations'], 'receipt_pitch': old_receipt['pitch'],
            'rejection': rejected['error'],
        }
        self.assertEqual(downstream, expected['after_reopen'])
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v7', 'input': scenario, 'expected': expected['play'], 'actual': actual,
            'downstream_expected': expected['after_reopen'], 'downstream_actual': downstream,
            'code_paths': ['session/http_api.py', 'control/delivery.py', 'sound/strike.py', 'sound/release.py',
                           'sound/output.py', 'session/closing.py', 'review/archive.py', 'review/lookup.py'],
            'oracle': 'Hand-calculated integer transposition and source counts, followed by the four expected transitions',
        }, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
