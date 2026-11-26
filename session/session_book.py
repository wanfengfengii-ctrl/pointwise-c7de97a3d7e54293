from dataclasses import dataclass

from arrangement.keyboard_roster import KeyboardPart
from arrangement.ranges import KeyRange
from session.storage import BusinessError


@dataclass(frozen=True)
class Session:
    session_id: str
    layout_id: str
    status: str
    roster: dict[str, KeyboardPart]


def create_session_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            number INTEGER PRIMARY KEY,
            session_id TEXT UNIQUE NOT NULL,
            layout_id TEXT NOT NULL REFERENCES layouts(layout_id),
            status TEXT NOT NULL CHECK (status IN ('active', 'closed'))
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS session_keyboards (
            session_id TEXT NOT NULL REFERENCES sessions(session_id),
            keyboard_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            part TEXT NOT NULL,
            low_key INTEGER NOT NULL,
            high_key INTEGER NOT NULL,
            initial_shift INTEGER NOT NULL,
            PRIMARY KEY (session_id, keyboard_id),
            UNIQUE (session_id, position)
        )
    ''')


def record_open_session(connection, setup):
    number = connection.execute('SELECT COALESCE(MAX(number), 0) + 1 FROM sessions').fetchone()[0]
    session_id = f's{number}'
    connection.execute('''
        INSERT INTO sessions (number, session_id, layout_id, status) VALUES (?, ?, ?, 'active')
    ''', (number, session_id, setup.layout_id))
    connection.executemany('''
        INSERT INTO session_keyboards
        (session_id, keyboard_id, position, part, low_key, high_key, initial_shift)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        (session_id, part.keyboard_id, position, part.part, part.keys.low, part.keys.high, part.transposition)
        for position, part in enumerate(setup.keyboards)
    ))
    return Session(session_id, setup.layout_id, 'active', {part.keyboard_id: part for part in setup.keyboards})


def get_session(connection, session_id):
    row = connection.execute('SELECT layout_id, status FROM sessions WHERE session_id = ?', (session_id,)).fetchone()
    if row is None:
        raise BusinessError(404, 'session_not_found', 'No session with this identifier')
    keyboards = connection.execute('''
        SELECT keyboard_id, part, low_key, high_key, initial_shift FROM session_keyboards
        WHERE session_id = ? ORDER BY position
    ''', (session_id,))
    roster = {
        part['keyboard_id']: KeyboardPart(
            part['keyboard_id'], part['part'], KeyRange(part['low_key'], part['high_key']), part['initial_shift']
        )
        for part in keyboards
    }
    return Session(session_id, row['layout_id'], row['status'], roster)


def mark_session_closed(connection, session_id):
    connection.execute("UPDATE sessions SET status = 'closed' WHERE session_id = ?", (session_id,))
