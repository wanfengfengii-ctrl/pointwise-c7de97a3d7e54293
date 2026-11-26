import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from control.delivery import ReplyUnavailable
from session.http_api import build_server


def keyboard(keyboard_id, part='piano', low=48, high=72, shift=0):
    return {'keyboard_id': keyboard_id, 'part': part, 'low': low, 'high': high, 'transposition': shift}


def event(seq, action, pitch, request_id):
    return {'seq': seq, 'action': action, 'pitch': pitch, 'request_id': request_id}


class DeliveryGate:
    def __init__(self):
        self.reached = Event()
        self.resume = Event()


class TransportControls:
    def __init__(self):
        self.lock = Lock()
        self.gates = {}
        self.dropped_replies = set()

    def hold(self, session_id, request_id):
        gate = DeliveryGate()
        with self.lock:
            self.gates[session_id, request_id] = gate
        return gate

    def drop_reply(self, session_id, request_id):
        with self.lock:
            self.dropped_replies.add((session_id, request_id))

    def send(self, intent, accept):
        identity = intent.session_id, intent.request_id
        with self.lock:
            gate = self.gates.pop(identity, None)
            drop_reply = identity in self.dropped_replies
            self.dropped_replies.discard(identity)
        if gate is not None:
            gate.reached.set()
            if not gate.resume.wait(10):
                raise TimeoutError('Timed out waiting to release the actual sound delivery')
        outcome = accept(intent)
        if drop_reply:
            if outcome is None:
                raise AssertionError('There is no committed sound outcome to withhold')
            raise ReplyUnavailable()
        return outcome


class RehearsalTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rehearsal-')
        self.addCleanup(temporary.cleanup)
        self.database = str(Path(temporary.name) / 'rehearsal.sqlite3')
        self.server = None
        self.addCleanup(self.stop_server)
        self.start_server()

    def start_server(self):
        self.transport = TransportControls()
        self.server = build_server(self.database, transport=self.transport.send)
        self.worker = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.worker.start()
        self.base_url = f'http://127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        if self.server is not None:
            self.server.shutdown()
            self.worker.join(timeout=5)
            self.server.server_close()
            self.server = None
            self.assertFalse(self.worker.is_alive())

    def restart(self):
        self.stop_server()
        self.start_server()

    def request(self, method, path, body=None, *, status=200):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        request = Request(self.base_url + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            result = json.load(response)
            self.assertEqual(response.status, status, result)
            return result

    def layout(self, layout_id='weekend', keyboards=None, *, status=201):
        if keyboards is None:
            keyboards = [keyboard('A'), keyboard('B', 'organ', shift=1)]
        return self.request('POST', '/layouts', {'layout_id': layout_id, 'keyboards': keyboards}, status=status)

    def open(self, layout_id='weekend', *, status=201):
        return self.request('POST', '/sessions', {'layout_id': layout_id}, status=status)

    def open_default(self):
        self.layout()
        return self.open()['session_id']

    def press(self, session_id, request_id, key, keyboard_id='A', *, status=200):
        return self.request('POST', '/keys/press', {
            'session_id': session_id, 'keyboard_id': keyboard_id, 'request_id': request_id, 'key': key,
        }, status=status)

    def release(self, session_id, request_id, press_id, keyboard_id='A', *, status=200):
        return self.request('POST', '/keys/release', {
            'session_id': session_id, 'keyboard_id': keyboard_id, 'request_id': request_id, 'press_id': press_id,
        }, status=status)

    def transpose(self, session_id, shift, keyboard_id='A', *, status=200):
        return self.request('POST', '/transpositions', {
            'session_id': session_id, 'keyboard_id': keyboard_id, 'transposition': shift,
        }, status=status)

    def sound(self, session_id, *, status=200):
        return self.request('GET', f'/sessions/{quote(session_id, safe="")}/sound', status=status)

    def operation(self, session_id, request_id, *, status=200):
        query = urlencode({'session_id': session_id})
        return self.request('GET', f'/operations/{quote(request_id, safe="")}?{query}', status=status)

    def close_session(self, session_id, *, status=200):
        return self.request('POST', f'/sessions/{quote(session_id, safe="")}/close', {}, status=status)

    @contextmanager
    def delay_press(self, session_id, request_id, key, keyboard_id='A'):
        gate = self.transport.hold(session_id, request_id)
        with ThreadPoolExecutor(max_workers=1) as executor:
            press = executor.submit(self.press, session_id, request_id, key, keyboard_id)
            try:
                self.assertTrue(gate.reached.wait(5), 'Press did not reach the delivery boundary')
                yield gate, press
            finally:
                gate.resume.set()
