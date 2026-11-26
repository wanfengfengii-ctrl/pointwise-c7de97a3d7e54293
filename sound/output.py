from dataclasses import dataclass

from session.storage import BusinessError


@dataclass(frozen=True)
class SoundOutcome:
    session_id: str
    request_id: str
    keyboard_id: str
    action: str
    key: int | None = None
    press_id: str | None = None
    pitch: int | None = None
    error: str | None = None

    def identity(self):
        return self.session_id, self.request_id, self.keyboard_id, self.action, self.key, self.press_id

    def require_intent(self, keyboard_id, action, *, key=None, press_id=None):
        if (keyboard_id, action, key, press_id) != (self.keyboard_id, self.action, self.key, self.press_id):
            raise BusinessError(409, 'request_conflict', 'Committed sound operation belongs to a different intent')


@dataclass(frozen=True)
class OutputEvent:
    seq: int
    action: str
    pitch: int
    request_id: str | None


def create_output_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS sound_outcomes (
            ordinal INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            action TEXT NOT NULL,
            key INTEGER,
            press_id TEXT,
            pitch INTEGER CHECK (pitch BETWEEN 0 AND 127),
            error TEXT,
            UNIQUE (session_id, request_id),
            FOREIGN KEY (session_id, keyboard_id) REFERENCES session_keyboards(session_id, keyboard_id),
            CHECK ((pitch IS NULL) <> (error IS NULL))
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS sound_outcomes_in_order ON sound_outcomes(session_id, ordinal)
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS output_events (
            session_id TEXT NOT NULL REFERENCES sessions(session_id),
            seq INTEGER NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('start', 'stop')),
            pitch INTEGER NOT NULL CHECK (pitch BETWEEN 0 AND 127),
            request_id TEXT,
            PRIMARY KEY (session_id, seq)
        )
    ''')


def _outcome(row):
    return SoundOutcome(row['session_id'], row['request_id'], row['keyboard_id'], row['action'],
                        row['key'], row['press_id'], row['pitch'], row['error'])


def get_committed_result(connection, session_id, request_id):
    row = connection.execute('''
        SELECT * FROM sound_outcomes WHERE session_id = ? AND request_id = ?
    ''', (session_id, request_id)).fetchone()
    return _outcome(row) if row is not None else None


def save_committed_result(connection, outcome):
    connection.execute('''
        INSERT INTO sound_outcomes (session_id, request_id, keyboard_id, action, key, press_id, pitch, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (*outcome.identity(), outcome.pitch, outcome.error))
    return outcome


def append_output_event(connection, session_id, action, pitch, request_id):
    sequence = connection.execute('''
        SELECT COALESCE(MAX(seq), 0) + 1 FROM output_events WHERE session_id = ?
    ''', (session_id,)).fetchone()[0]
    connection.execute('INSERT INTO output_events VALUES (?, ?, ?, ?, ?)',
                       (session_id, sequence, action, pitch, request_id))


def read_output_events(connection, session_id):
    rows = connection.execute('''
        SELECT seq, action, pitch, request_id FROM output_events WHERE session_id = ? ORDER BY seq
    ''', (session_id,))
    return [OutputEvent(row['seq'], row['action'], row['pitch'], row['request_id']) for row in rows]


def read_committed_results(connection, session_id):
    rows = connection.execute('SELECT * FROM sound_outcomes WHERE session_id = ? ORDER BY ordinal', (session_id,))
    return [_outcome(row) for row in rows]
