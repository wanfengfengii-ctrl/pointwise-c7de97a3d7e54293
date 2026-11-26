import json
from dataclasses import dataclass

from control.receipts import list_completed_operations
from review.live_notes import build_live_notes
from review.timeline import build_timeline


@dataclass(frozen=True)
class SessionArchive:
    session_id: str
    sound: dict
    operations: list[dict]

    def close_result(self):
        return {'session_id': self.session_id, 'status': 'closed', 'sound': self.sound, 'operations': self.operations}


def create_archive_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS session_archives (
            session_id TEXT PRIMARY KEY NOT NULL REFERENCES sessions(session_id),
            sound_json TEXT NOT NULL,
            operations_json TEXT NOT NULL
        )
    ''')


def seal_archive(connection, session_id):
    notes = build_live_notes(connection, session_id)
    if notes.pitches:
        raise RuntimeError('A session must be silent before sealing')
    sound = {
        'session_id': session_id, 'status': 'closed', 'pitches': notes.pitches,
        'operations': notes.operations,
        'events': [entry.to_dict() for entry in build_timeline(connection, session_id)],
    }
    archive = SessionArchive(session_id, sound, list_completed_operations(connection, session_id))
    connection.execute('INSERT INTO session_archives VALUES (?, ?, ?)',
                       (session_id, json.dumps(archive.sound), json.dumps(archive.operations)))
    return archive


def get_archive(connection, session_id):
    row = connection.execute('SELECT * FROM session_archives WHERE session_id = ?', (session_id,)).fetchone()
    if row is None:
        raise RuntimeError('A closed session must have an archive')
    return SessionArchive(session_id, json.loads(row['sound_json']), json.loads(row['operations_json']))
