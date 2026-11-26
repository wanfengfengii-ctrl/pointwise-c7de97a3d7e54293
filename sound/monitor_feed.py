"""Home-rehearsal monitor cuts and position-scoped evidence packets."""
import json
import re

from arrangement.keyboard_roster import require_keyboard
from session.session_book import get_session
from session.storage import BusinessError, read_transaction, require_text, write_transaction

CUT_FORMAT = 'yutai-monitor-cut-v1'
STEP_FORMAT = 'yutai-monitor-steps-v1'


def create_monitor_feed_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS monitor_cut_tickets (
            session_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            ticket_json TEXT NOT NULL,
            PRIMARY KEY (session_id, ticket_id),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')


def _successful_operations(connection, session_id):
    return connection.execute('''
        SELECT ordinal, request_id, keyboard_id, action, press_id, pitch
        FROM sound_outcomes
        WHERE session_id = ? AND error IS NULL AND pitch IS NOT NULL
        ORDER BY ordinal
    ''', (session_id,)).fetchall()


def _apply_operation(sources, row):
    source_id = row['request_id'] if row['action'] == 'press' else row['press_id']
    if row['action'] == 'press':
        sources[source_id] = {'source_id': source_id, 'pitch': row['pitch']}
    else:
        sources.pop(source_id, None)


def _keyboard_sources_at(connection, session_id, keyboard_id, position, operations=None):
    operations = _successful_operations(connection, session_id) if operations is None else operations
    sources = {}
    for index, row in enumerate(operations, start=1):
        if index > position:
            break
        if row['keyboard_id'] == keyboard_id:
            _apply_operation(sources, row)
    return sources


def _sorted_sources(sources):
    return sorted(sources.values(), key=lambda source: (source['pitch'], source['source_id']))


def _pitches(sources):
    return sorted({source['pitch'] for source in sources.values()})


def issue_cut(database, session_id, ticket_id, keyboard_id):
    session_id = require_text(session_id, 'session_id')
    ticket_id = require_text(ticket_id, 'ticket_id')
    keyboard_id = require_text(keyboard_id, 'keyboard_id')

    with write_transaction(database) as connection:
        session = get_session(connection, session_id)
        require_keyboard(session.roster, keyboard_id)

        existing = connection.execute('''
            SELECT keyboard_id, ticket_json FROM monitor_cut_tickets
            WHERE session_id = ? AND ticket_id = ?
        ''', (session_id, ticket_id)).fetchone()
        if existing is not None:
            if existing['keyboard_id'] != keyboard_id:
                raise BusinessError(409, 'ticket_conflict',
                                    'This ticket identifier was issued for another keyboard')
            return json.loads(existing['ticket_json'])

        operations = _successful_operations(connection, session_id)
        operation_count = len(operations)
        closed = session.status == 'closed'
        position = operation_count + (1 if closed else 0)
        sources = _keyboard_sources_at(connection, session_id, keyboard_id, operation_count, operations)
        if closed:
            # The terminal position is the aggregate stop committed by close.
            sources = {}
        source_list = _sorted_sources(sources)
        pitches = _pitches(sources)
        ticket = {
            'session_id': session_id,
            'ticket_id': ticket_id,
            'keyboard_id': keyboard_id,
            'position': position,
            'closed': closed,
            'pitches': pitches,
            'payload': {
                'format': CUT_FORMAT,
                'session_id': session_id,
                'ticket_id': ticket_id,
                'keyboard_id': keyboard_id,
                'position': position,
                'closed': closed,
                'sources': source_list,
            },
        }
        connection.execute('''
            INSERT INTO monitor_cut_tickets (session_id, ticket_id, keyboard_id, ticket_json)
            VALUES (?, ?, ?, ?)
        ''', (session_id, ticket_id, keyboard_id, json.dumps(ticket, ensure_ascii=False, sort_keys=True)))
        return ticket


def parse_position_integer(value, field):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'[+-]?\d+', value):
        return int(value)
    raise BusinessError(422, 'invalid_range', f'{field} must be an integer')


def read_steps(database, session_id, keyboard_id, after, through):
    session_id = require_text(session_id, 'session_id')
    keyboard_id = require_text(keyboard_id, 'keyboard_id')

    with read_transaction(database) as connection:
        session = get_session(connection, session_id)
        require_keyboard(session.roster, keyboard_id)
        after = parse_position_integer(after, 'after')
        through = parse_position_integer(through, 'through')
        operations = _successful_operations(connection, session_id)
        operation_count = len(operations)
        closed = session.status == 'closed'
        committed_position = operation_count + (1 if closed else 0)

        if not (0 <= after < through <= committed_position):
            raise BusinessError(
                422, 'invalid_range',
                'Require 0 <= after < through <= the committed home position',
            )

        sources = _keyboard_sources_at(connection, session_id, keyboard_id, after, operations)
        positions = []
        final_closed = False

        for position in range(after + 1, through + 1):
            if position <= operation_count:
                row = operations[position - 1]
                if row['keyboard_id'] != keyboard_id:
                    record = {'position': position, 'kind': 'unchanged', 'keyboard_id': keyboard_id}
                elif row['action'] == 'press':
                    source_id = row['request_id']
                    sources[source_id] = {'source_id': source_id, 'pitch': row['pitch']}
                    record = {
                        'position': position,
                        'kind': 'press',
                        'keyboard_id': keyboard_id,
                        'source_id': source_id,
                        'request_id': row['request_id'],
                        'pitch': row['pitch'],
                        'pitches_after': _pitches(sources),
                    }
                else:
                    source_id = row['press_id']
                    sources.pop(source_id, None)
                    record = {
                        'position': position,
                        'kind': 'release',
                        'keyboard_id': keyboard_id,
                        'source_id': source_id,
                        'request_id': row['request_id'],
                        'press_id': source_id,
                        'pitch': row['pitch'],
                        'pitches_after': _pitches(sources),
                    }
            else:
                # The only position beyond the settled operation rows is close.
                source_list = _sorted_sources(sources)
                record = {
                    'position': position,
                    'kind': 'close',
                    'keyboard_id': keyboard_id,
                    'sources': source_list,
                    'pitches_after': [],
                    'closed': True,
                }
                sources = {}
                final_closed = True
            positions.append(record)

        final_sources = _sorted_sources(sources)
        payload = {
            'format': STEP_FORMAT,
            'session_id': session_id,
            'keyboard_id': keyboard_id,
            'after': after,
            'through': through,
            'positions': positions,
            'state_after': {
                'position': through,
                'closed': final_closed and through == committed_position and closed,
                'pitches': _pitches(sources),
                'sources': final_sources,
            },
        }
        return {
            'session_id': session_id,
            'after': after,
            'through': through,
            'scope': keyboard_id,
            'payload': payload,
        }
