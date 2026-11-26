import argparse
import json
import selectors
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@contextmanager
def server(module, database):
    command = [sys.executable, '-B', '-m', module, '--database', str(database), '--port', '0']
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=10):
                    raise RuntimeError(f'{module} did not report a listening port')
                announcement = process.stdout.readline().strip()
            host, separator, port = announcement.rpartition('127.0.0.1:')
            if not separator or not port.isdecimal() or not 0 < int(port) <= 65535:
                raise RuntimeError(f'{module} did not start: {announcement!r}')
            yield f'http://127.0.0.1:{port}'
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def http(base, path, body=None, *, status=200, discard=False):
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = Request(base + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        if discard and response.status == status:
            return None
        result = json.load(response)
        assert response.status == status, (path, status, response.status, result)
        return result


def register(base):
    sample = Path(__file__).with_name('samples') / 'weekend.json'
    layout = json.loads(sample.read_text(encoding='utf-8'))['layout']
    http(base, '/layouts', layout, status=201)
    return layout['layout_id']


def open_rehearsal(base, layout):
    result = http(base, '/sessions', {'layout_id': layout}, status=201)
    return result['session_id']


def key(base, session, keyboard, request, action, **fields):
    return http(base, f'/keys/{action}', {
        'session_id': session, 'keyboard_id': keyboard, 'request_id': request, **fields,
    })


def v1_probe(base, layout):
    comparisons = []
    for actions in (('release', 'press'), ('press', 'release')):
        session = open_rehearsal(base, layout)
        key(base, session, 'A', 'a', 'press', key=60)
        key(base, session, 'B', 'b', 'press', key=59)
        for action in actions:
            if action == 'release':
                key(base, session, 'B', 'up', action, press_id='b')
            else:
                key(base, session, 'B', 'b2', action, key=59)
        view = http(base, f'/sessions/{quote(session, safe="")}/sound')
        assert view.pop('session_id') == session
        assert view['pitches'] == [60], view
        assert view['operations'] == {'a': 60, 'b': 60, 'up': 60, 'b2': 60}, view
        assert view['events'] == [{'seq': 1, 'action': 'start', 'pitch': 60, 'request_id': 'a'}], view
        comparisons.append(view)
    assert comparisons[0] == comparisons[1], comparisons
    print(json.dumps({'main_mix_in_both_orders': comparisons[0]}, sort_keys=True))


def feature(base, layout, directory):
    session = open_rehearsal(base, layout)
    main_path = f'/sessions/{quote(session, safe="")}'
    first_db = directory / 'monitor-first.sqlite3'
    second_db = directory / 'monitor-second.sqlite3'

    def cut(ticket_id, keyboard_id):
        return http(base, main_path + '/monitor/cuts', {'ticket_id': ticket_id, 'keyboard_id': keyboard_id})

    def steps(keyboard_id, after, through):
        query = urlencode({'keyboard_id': keyboard_id, 'after': after, 'through': through})
        return http(base, main_path + '/monitor/steps?' + query)

    def sound(terminal):
        return http(terminal, '/monitor/sound')

    def state(terminal, keyboard, position, pitches):
        result = sound(terminal)
        assert (result['session_id'], result['keyboard_id'], result['position'], result['pitches']) == (
            session, keyboard, position, pitches,
        ), result
        return result

    def switch(terminal, name, ticket, **options):
        return http(terminal, '/monitor/switches', {'request_id': name, 'ticket': ticket}, **options)

    def play(terminal, packet, **options):
        return http(terminal, '/monitor/steps', {'packet': packet}, **options)

    def events(view):
        return [(item['position'], item['action'], item['pitch']) for item in view['events']]

    key(base, session, 'A', 'a', 'press', key=60)
    key(base, session, 'B', 'b', 'press', key=59)
    cut_a, cut_b = cut('a-at-2', 'A'), cut('b-at-2', 'B')
    with server('sound.monitor_http', first_db) as first, server('sound.monitor_http', second_db) as second:
        for terminal in (first, second):
            switch(terminal, 'listen-a', cut_a)
            assert events(state(terminal, 'A', 2, [60])) == [(2, 'start', 60)]

        key(base, session, 'A', 'up-a', 'release', press_id='a')
        key(base, session, 'B', 'high', 'press', key=63)
        old = steps('A', 2, 4)
        switch(first, 'listen-b', cut_b, discard=True)
        before = state(first, 'B', 2, [60])
        assert events(before) == [(2, 'start', 60)], before
        if old['scope'] is None:
            play(first, old)
        else:
            assert old['scope'] == 'A', old
            play(first, old, status=409)
            assert sound(first) == before
        current = steps('B', 2, 4)
        play(first, current)
        after = state(first, 'B', 4, [60, 64])
        assert events(after) == [(2, 'start', 60), (4, 'start', 64)], after
        play(first, current)
        assert sound(first) == after

        play(second, old)
        passed = state(second, 'A', 4, [])
        assert events(passed) == [(2, 'start', 60), (3, 'stop', 60)], passed
        declined = switch(second, 'too-late', cut_b, status=409)
        assert declined['error'] == 'stale_cut' and sound(second) == passed
        switch(second, 'fresh', cut('b-at-4', 'B'))
        state(second, 'B', 4, [60, 64])

        key(base, session, 'A', 'a2', 'press', key=60)
        main_events = http(base, main_path + '/sound')['events']
        key(base, session, 'B', 'up-b', 'release', press_id='b')
        key(base, session, 'B', 'b2', 'press', key=59)
        assert http(base, main_path + '/sound')['events'] == main_events
        late = steps('B', 6, 7)
        play(first, late, status=202)
        assert sound(first) == after
        play(first, steps('B', 4, 6))
        assert events(state(first, 'B', 6, [64]))[-1] == (6, 'stop', 60)
        play(first, late)
        assert events(state(first, 'B', 7, [60, 64])) == [
            (2, 'start', 60), (4, 'start', 64), (6, 'stop', 60), (7, 'start', 60),
        ]
        http(base, main_path + '/close', {})
        assert cut('b-at-2', 'B') == cut_b
        play(first, steps('B', 7, 8))
        final = state(first, 'B', 8, [])
        assert final['closed'] is True
        assert set(events(final)[-2:]) == {(8, 'stop', 60), (8, 'stop', 64)}, final

    with server('sound.monitor_http', first_db) as reopened:
        receipt = http(reopened, '/monitor/switches/listen-b')
        assert all(receipt[field] == value for field, value in {
            'request_id': 'listen-b', 'ticket_id': 'b-at-2', 'session_id': session,
            'keyboard_id': 'B', 'position': 2, 'pitches': [60], 'closed': False,
        }.items()), receipt
        assert switch(reopened, 'listen-b', cut_b) == receipt
        switch(reopened, 'listen-b', cut_a, status=409)
        assert sound(reopened) == final
    print(json.dumps({'switch_first': after, 'old_packet_first': passed, 'stale_cut': declined,
                      'receipt_after_reopen': receipt, 'final_sound': final}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description='Run the rehearsal monitor exercise')
    parser.add_argument('mode', choices=('baseline', 'feature', 'verify'))
    args = parser.parse_args()
    if args.mode == 'verify':
        subprocess.run([sys.executable, '-B', 'check_project.py'], check=True)
    with TemporaryDirectory(prefix='rehearsal-monitor-') as name:
        directory = Path(name)
        with server('session.http_api', directory / 'main.sqlite3') as base:
            layout = register(base)
            if args.mode == 'baseline':
                v1_probe(base, layout)
            else:
                feature(base, layout, directory)


if __name__ == '__main__':
    main()
