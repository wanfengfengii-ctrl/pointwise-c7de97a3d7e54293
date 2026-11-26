"""Independent monitor desk storage, cut enrollment, and position replay."""
import json

from sound.monitor_feed import CUT_FORMAT, STEP_FORMAT
from session.storage import BusinessError, read_transaction, write_transaction


def create_monitor_board_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS monitor_board_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            session_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 0),
            closed INTEGER NOT NULL CHECK (closed IN (0, 1)),
            pitches_json TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS monitor_board_sources (
            source_id TEXT PRIMARY KEY NOT NULL,
            pitch INTEGER NOT NULL CHECK (pitch BETWEEN 0 AND 127)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS monitor_board_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position INTEGER NOT NULL CHECK (position >= 0),
            action TEXT NOT NULL CHECK (action IN ('start', 'stop')),
            pitch INTEGER NOT NULL CHECK (pitch BETWEEN 0 AND 127)
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS monitor_switch_receipts (
            request_id TEXT PRIMARY KEY NOT NULL,
            ticket_key TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            response_json TEXT NOT NULL
        )
    ''')


def _invalid_ticket(message):
    return BusinessError(422, 'invalid_ticket', message)


def _invalid_packet(message):
    return BusinessError(422, 'invalid_packet', message)


def _text(value, field, error):
    if not isinstance(value, str) or not value.strip():
        raise error(f'{field} must be a non-blank string')
    return value


def _pitch_list(value, error):
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise error('pitches must be a list of integer MIDI pitches')
    if any(not 0 <= item <= 127 for item in value):
        raise error('pitches must lie between 0 and 127')
    if value != sorted(set(value)):
        raise error('pitches must be ascending and without duplicates')
    return value


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def validate_cut_ticket(ticket):
    if not isinstance(ticket, dict):
        raise _invalid_ticket('ticket must be a JSON object')
    session_id = _text(ticket.get('session_id'), 'session_id', _invalid_ticket)
    ticket_id = _text(ticket.get('ticket_id'), 'ticket_id', _invalid_ticket)
    keyboard_id = _text(ticket.get('keyboard_id'), 'keyboard_id', _invalid_ticket)
    position = ticket.get('position')
    if type(position) is not int or position < 0:
        raise _invalid_ticket('position must be a non-negative integer')
    closed = ticket.get('closed')
    if not isinstance(closed, bool):
        raise _invalid_ticket('closed must be a boolean')
    pitches = _pitch_list(ticket.get('pitches'), _invalid_ticket)
    payload = ticket.get('payload')
    if not isinstance(payload, dict):
        raise _invalid_ticket('payload must be a JSON object')
    if payload.get('format') != CUT_FORMAT:
        raise _invalid_ticket('Unsupported monitor cut payload format')
    for field, expected in (
        ('session_id', session_id), ('ticket_id', ticket_id),
        ('keyboard_id', keyboard_id), ('position', position), ('closed', closed),
    ):
        if payload.get(field) != expected:
            raise _invalid_ticket(f'payload.{field} does not match the ticket')

    raw_sources = payload.get('sources')
    if not isinstance(raw_sources, list):
        raise _invalid_ticket('payload.sources must be a list')
    sources = []
    source_ids = set()
    for source in raw_sources:
        if not isinstance(source, dict):
            raise _invalid_ticket('Each cut source must be an object')
        source_id = _text(source.get('source_id'), 'source_id', _invalid_ticket)
        if source_id in source_ids:
            raise _invalid_ticket('Cut source identifiers must be unique')
        source_ids.add(source_id)
        pitch = source.get('pitch')
        if type(pitch) is not int or not 0 <= pitch <= 127:
            raise _invalid_ticket('Cut source pitch must be an integer from 0 to 127')
        sources.append({'source_id': source_id, 'pitch': pitch})
    if sorted({source['pitch'] for source in sources}) != pitches:
        raise _invalid_ticket('Cut sources do not prove the declared pitches')
    if closed and (sources or pitches):
        raise _invalid_ticket('A closed cut must be silent')
    return ticket


def validate_step_envelope(packet):
    if not isinstance(packet, dict):
        raise _invalid_packet('packet must be a JSON object')
    session_id = _text(packet.get('session_id'), 'session_id', _invalid_packet)
    after = packet.get('after')
    through = packet.get('through')
    if type(after) is not int or type(through) is not int:
        raise _invalid_packet('after and through must be integers')
    if not 0 <= after < through:
        raise _invalid_packet('Require 0 <= after < through')
    scope = packet.get('scope')
    if scope is not None:
        _text(scope, 'scope', _invalid_packet)
    payload = packet.get('payload')
    if not isinstance(payload, dict):
        raise _invalid_packet('payload must be a JSON object')
    return packet


def _state_row(connection):
    return connection.execute('SELECT * FROM monitor_board_state WHERE id = 1').fetchone()


def _event_rows(connection):
    return connection.execute('''
        SELECT position, action, pitch FROM monitor_board_events ORDER BY id
    ''').fetchall()


def sound_view(connection):
    row = _state_row(connection)
    if row is None:
        raise BusinessError(404, 'monitor_sound_not_found', 'Open a monitor switch before requesting sound')
    return {
        'session_id': row['session_id'],
        'keyboard_id': row['keyboard_id'],
        'position': row['position'],
        'closed': bool(row['closed']),
        'pitches': json.loads(row['pitches_json']),
        'events': [
            {'position': event['position'], 'action': event['action'], 'pitch': event['pitch']}
            for event in _event_rows(connection)
        ],
    }


def get_sound(database):
    with read_transaction(database) as connection:
        return sound_view(connection)


def get_receipt(database, request_id):
    request_id = _text(request_id, 'request_id',
                       lambda message: BusinessError(422, 'invalid_field', message))
    with read_transaction(database) as connection:
        row = connection.execute('''
            SELECT response_json FROM monitor_switch_receipts WHERE request_id = ?
        ''', (request_id,)).fetchone()
    if row is None:
        raise BusinessError(404, 'switch_not_found', 'No monitor switch outcome with this request_id')
    return json.loads(row['response_json'])


def _current_pitches(connection):
    rows = connection.execute('SELECT DISTINCT pitch FROM monitor_board_sources ORDER BY pitch').fetchall()
    return [row['pitch'] for row in rows]


def _append_cut_changes(connection, position, old_pitches, new_pitches):
    old_set = set(old_pitches)
    new_set = set(new_pitches)
    for pitch in sorted(old_set - new_set):
        connection.execute('''
            INSERT INTO monitor_board_events (position, action, pitch) VALUES (?, 'stop', ?)
        ''', (position, pitch))
    for pitch in sorted(new_set - old_set):
        connection.execute('''
            INSERT INTO monitor_board_events (position, action, pitch) VALUES (?, 'start', ?)
        ''', (position, pitch))


def _replace_state(connection, ticket):
    old_pitches = _current_pitches(connection)
    _append_cut_changes(connection, ticket['position'], old_pitches, ticket['pitches'])
    connection.execute('DELETE FROM monitor_board_sources')
    for source in ticket['payload']['sources']:
        connection.execute('INSERT INTO monitor_board_sources (source_id, pitch) VALUES (?, ?)',
                           (source['source_id'], source['pitch']))
    connection.execute('''
        INSERT INTO monitor_board_state (id, session_id, keyboard_id, position, closed, pitches_json)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            session_id = excluded.session_id,
            keyboard_id = excluded.keyboard_id,
            position = excluded.position,
            closed = excluded.closed,
            pitches_json = excluded.pitches_json
    ''', (ticket['session_id'], ticket['keyboard_id'], ticket['position'],
          1 if ticket['closed'] else 0, json.dumps(ticket['pitches'])))


def _success_body(request_id, ticket):
    return {
        'request_id': request_id,
        'ticket_id': ticket['ticket_id'],
        'session_id': ticket['session_id'],
        'keyboard_id': ticket['keyboard_id'],
        'position': ticket['position'],
        'pitches': ticket['pitches'],
        'closed': ticket['closed'],
    }


def submit_switch(database, body):
    if not isinstance(body, dict):
        raise BusinessError(400, 'invalid_json', 'Request body must be a JSON object')
    request_id = _text(body.get('request_id'), 'request_id',
                       lambda message: BusinessError(422, 'invalid_field', message))
    raw_ticket = body.get('ticket')
    ticket_key = canonical_json(raw_ticket)

    with write_transaction(database) as connection:
        existing = connection.execute('''
            SELECT ticket_key, status_code, response_json
            FROM monitor_switch_receipts WHERE request_id = ?
        ''', (request_id,)).fetchone()
        if existing is not None:
            if existing['ticket_key'] != ticket_key:
                raise BusinessError(409, 'request_conflict',
                                    'This request_id already belongs to another monitor ticket')
            return existing['status_code'], json.loads(existing['response_json'])

        ticket = validate_cut_ticket(raw_ticket)
        state = _state_row(connection)
        if state is not None and state['session_id'] != ticket['session_id']:
            raise BusinessError(409, 'session_conflict',
                                'This monitor desk is already following another rehearsal session')

        if state is not None and ticket['position'] < state['position']:
            response = {
                'error': 'stale_cut',
                'message': 'The cut position is behind the monitor desk consumed position',
            }
            connection.execute('''
                INSERT INTO monitor_switch_receipts
                    (request_id, ticket_key, status_code, response_json)
                VALUES (?, ?, 409, ?)
            ''', (request_id, ticket_key, json.dumps(response, ensure_ascii=False, sort_keys=True)))
            return 409, response

        _replace_state(connection, ticket)
        response = _success_body(request_id, ticket)
        connection.execute('''
            INSERT INTO monitor_switch_receipts
                (request_id, ticket_key, status_code, response_json)
            VALUES (?, ?, 200, ?)
        ''', (request_id, ticket_key, json.dumps(response, ensure_ascii=False, sort_keys=True)))
        return 200, response


def _validate_step_payload(packet):
    payload = packet['payload']
    if payload.get('format') != STEP_FORMAT:
        raise _invalid_packet('Unsupported monitor step payload format')
    for field in ('session_id', 'after', 'through'):
        if payload.get(field) != packet.get(field):
            raise _invalid_packet(f'payload.{field} does not match the packet')
    keyboard_id = packet.get('scope')
    if payload.get('keyboard_id') != keyboard_id:
        raise _invalid_packet('payload.keyboard_id does not match packet.scope')
    positions = payload.get('positions')
    if not isinstance(positions, list):
        raise _invalid_packet('payload.positions must be a list')
    interval_length = packet['through'] - packet['after']
    if interval_length != len(positions):
        raise _invalid_packet('payload.positions must cover every position in the interval')
    for index, record in enumerate(positions):
        expected_position = packet['after'] + 1 + index
        if not isinstance(record, dict) or record.get('position') != expected_position:
            raise _invalid_packet('payload.positions must cover the interval in order')
        kind = record.get('kind')
        if kind not in ('unchanged', 'press', 'release', 'close'):
            raise _invalid_packet('Unknown step record kind')
        if record.get('keyboard_id') is not None and record.get('keyboard_id') != keyboard_id:
            raise _invalid_packet('Step record is bound to another keyboard')
        if kind in ('press', 'release'):
            source_id = _text(record.get('source_id'), 'source_id', _invalid_packet)
            pitch = record.get('pitch')
            if type(pitch) is not int or not 0 <= pitch <= 127:
                raise _invalid_packet('Step pitch must be an integer from 0 to 127')
        if kind == 'close' and record.get('position') != packet['through']:
            raise _invalid_packet('A close record must be at the final packet position')
    return payload


def _has_pitch_source(connection, pitch):
    return connection.execute('''
        SELECT 1 FROM monitor_board_sources WHERE pitch = ? LIMIT 1
    ''', (pitch,)).fetchone() is not None


def _apply_step_record(connection, state, record):
    position = record['position']
    kind = record['kind']
    if kind == 'unchanged':
        return
    if kind == 'press':
        source_id = record['source_id']
        pitch = record['pitch']
        existing = connection.execute('''
            SELECT pitch FROM monitor_board_sources WHERE source_id = ?
        ''', (source_id,)).fetchone()
        if existing is not None:
            raise _invalid_packet('A press source cannot start twice in new evidence')
        was_sounding = _has_pitch_source(connection, pitch)
        connection.execute('INSERT INTO monitor_board_sources (source_id, pitch) VALUES (?, ?)',
                           (source_id, pitch))
        if not was_sounding:
            connection.execute('''
                INSERT INTO monitor_board_events (position, action, pitch)
                VALUES (?, 'start', ?)
            ''', (position, pitch))
    elif kind == 'release':
        source_id = record['source_id']
        pitch = record['pitch']
        source = connection.execute('''
            SELECT pitch FROM monitor_board_sources WHERE source_id = ?
        ''', (source_id,)).fetchone()
        if source is None or source['pitch'] != pitch:
            raise _invalid_packet('Release evidence does not match an active monitor source')
        connection.execute('DELETE FROM monitor_board_sources WHERE source_id = ?', (source_id,))
        if not _has_pitch_source(connection, pitch):
            connection.execute('''
                INSERT INTO monitor_board_events (position, action, pitch)
                VALUES (?, 'stop', ?)
            ''', (position, pitch))
    elif kind == 'close':
        source_rows = connection.execute('SELECT source_id, pitch FROM monitor_board_sources').fetchall()
        active_sources = sorted(
            ({'source_id': row['source_id'], 'pitch': row['pitch']} for row in source_rows),
            key=lambda source: (source['pitch'], source['source_id']),
        )
        if record.get('sources') != active_sources:
            raise _invalid_packet('Close evidence does not match active monitor sources')
        pitches = _current_pitches(connection)
        for pitch in pitches:
            connection.execute('''
                INSERT INTO monitor_board_events (position, action, pitch)
                VALUES (?, 'stop', ?)
            ''', (position, pitch))
        connection.execute('DELETE FROM monitor_board_sources')
        connection.execute('UPDATE monitor_board_state SET closed = 1 WHERE id = 1')


def submit_steps(database, body):
    if not isinstance(body, dict) or 'packet' not in body:
        raise BusinessError(422, 'invalid_packet', 'Send a monitor packet in the packet field')
    packet = validate_step_envelope(body.get('packet'))
    _validate_step_payload(packet)

    with write_transaction(database) as connection:
        state = _state_row(connection)
        if state is None:
            raise BusinessError(409, 'monitor_not_open', 'Open a monitor switch before submitting steps')
        if packet['session_id'] != state['session_id']:
            raise BusinessError(409, 'session_conflict',
                                'Packet session does not match the monitor desk session')
        if packet['scope'] is not None and packet['scope'] != state['keyboard_id']:
            raise BusinessError(409, 'scope_mismatch',
                                'This packet is bound to another keyboard')

        current_position = state['position']

        if packet['after'] > current_position:
            return 202, sound_view(connection)
        if packet['through'] <= current_position:
            return 200, sound_view(connection)

        records = {record['position']: record for record in packet['payload']['positions']}
        for position in range(current_position + 1, packet['through'] + 1):
            record = records.get(position)
            if record is None:
                raise _invalid_packet('Packet does not prove the next required position')
            _apply_step_record(connection, state, record)
            connection.execute('UPDATE monitor_board_state SET position = ? WHERE id = 1', (position,))

        pitches = _current_pitches(connection)
        closed = bool(connection.execute('SELECT closed FROM monitor_board_state WHERE id=1').fetchone()['closed'])
        connection.execute('UPDATE monitor_board_state SET pitches_json = ? WHERE id = 1',
                           (json.dumps(pitches),))
        expected_state = packet['payload'].get('state_after')
        if isinstance(expected_state, dict):
            if expected_state.get('position') != packet['through']:
                raise _invalid_packet('Packet state_after position does not match through')
            if expected_state.get('pitches') is not None and expected_state['pitches'] != pitches:
                raise _invalid_packet('Packet state_after pitches do not match its source evidence')
            if isinstance(expected_state.get('closed'), bool) and expected_state['closed'] != closed:
                raise _invalid_packet('Packet state_after closed does not match its close evidence')
        return 200, sound_view(connection)
