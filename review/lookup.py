from review.archive import get_archive
from review.live_notes import build_live_notes
from review.timeline import build_timeline
from session.session_book import get_session
from session.storage import read_transaction


def listen_session(database, session_id):
    with read_transaction(database) as connection:
        session = get_session(connection, session_id)
        if session.status == 'closed':
            return get_archive(connection, session_id).sound
        notes = build_live_notes(connection, session_id)
        return {
            'session_id': session_id, 'status': session.status, 'pitches': notes.pitches,
            'operations': notes.operations,
            'events': [entry.to_dict() for entry in build_timeline(connection, session_id)],
        }
