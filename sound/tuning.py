from arrangement.keyboard_roster import require_keyboard
from arrangement.ranges import validate_transposition
from session.lifecycle import rehearsal_turn, require_active_session
from session.storage import require_text, write_transaction


def create_tuning_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS tuning (
            session_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            shift INTEGER NOT NULL,
            PRIMARY KEY (session_id, keyboard_id),
            FOREIGN KEY (session_id, keyboard_id) REFERENCES session_keyboards(session_id, keyboard_id)
        )
    ''')


def initialize_tuning(connection, session_id, setup):
    connection.executemany('INSERT INTO tuning VALUES (?, ?, ?)', (
        (session_id, part.keyboard_id, part.transposition) for part in setup.keyboards
    ))


def change_transposition(database, turns, session_id, keyboard_id, shift):
    session_id = require_text(session_id, 'session_id')
    keyboard_id = require_text(keyboard_id, 'keyboard_id')
    with rehearsal_turn(turns, session_id), write_transaction(database) as connection:
        session = require_active_session(connection, session_id)
        part = require_keyboard(session.roster, keyboard_id)
        shift = validate_transposition(part.keys, shift)
        connection.execute('UPDATE tuning SET shift = ? WHERE session_id = ? AND keyboard_id = ?',
                           (shift, session_id, keyboard_id))
    return {'session_id': session_id, 'keyboard_id': keyboard_id, 'transposition': shift}


def effective_transposition(connection, session_id, keyboard_id):
    row = connection.execute('SELECT shift FROM tuning WHERE session_id = ? AND keyboard_id = ?',
                             (session_id, keyboard_id)).fetchone()
    if row is None:
        raise RuntimeError('An open session must have tuning for each configured keyboard')
    return row['shift']
