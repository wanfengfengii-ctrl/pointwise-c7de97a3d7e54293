from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    session_id: str
    press_id: str
    keyboard_id: str
    pitch: int
    active: bool = True


def create_voice_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS voices (
            session_id TEXT NOT NULL,
            press_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            pitch INTEGER NOT NULL CHECK (pitch BETWEEN 0 AND 127),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            PRIMARY KEY (session_id, press_id),
            FOREIGN KEY (session_id, keyboard_id) REFERENCES session_keyboards(session_id, keyboard_id)
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS sounding_sources ON voices(session_id, pitch) WHERE active = 1
    ''')


def _voice(row):
    return Voice(row['session_id'], row['press_id'], row['keyboard_id'], row['pitch'], bool(row['active']))


def add_voice(connection, voice):
    connection.execute('INSERT INTO voices VALUES (?, ?, ?, ?, ?)',
                       (voice.session_id, voice.press_id, voice.keyboard_id, voice.pitch, voice.active))


def get_voice(connection, session_id, press_id):
    row = connection.execute('SELECT * FROM voices WHERE session_id = ? AND press_id = ?',
                             (session_id, press_id)).fetchone()
    return _voice(row) if row is not None else None


def end_voice(connection, voice):
    updated = connection.execute('''
        UPDATE voices SET active = 0 WHERE session_id = ? AND press_id = ? AND active = 1
    ''', (voice.session_id, voice.press_id))
    if updated.rowcount != 1:
        raise RuntimeError('An active source is required to end a voice')


def active_voices(connection, session_id):
    rows = connection.execute('''
        SELECT * FROM voices WHERE session_id = ? AND active = 1 ORDER BY pitch, press_id
    ''', (session_id,))
    return [_voice(row) for row in rows]


def has_active_source(connection, session_id, pitch):
    row = connection.execute('''
        SELECT 1 FROM voices WHERE session_id = ? AND pitch = ? AND active = 1 LIMIT 1
    ''', (session_id, pitch)).fetchone()
    return row is not None


def active_pitches(connection, session_id):
    rows = connection.execute('''
        SELECT DISTINCT pitch FROM voices WHERE session_id = ? AND active = 1 ORDER BY pitch
    ''', (session_id,))
    return [row['pitch'] for row in rows]
