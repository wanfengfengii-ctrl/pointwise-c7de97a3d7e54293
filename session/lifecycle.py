from contextlib import contextmanager
from threading import Lock, RLock

from session.session_book import get_session
from session.storage import BusinessError


class SessionTurns:
    def __init__(self):
        self.guard = Lock()
        self.entries = {}


@contextmanager
def rehearsal_turn(turns, session_id):
    with turns.guard:
        entry = turns.entries.get(session_id)
        if entry is None:
            entry = [RLock(), 0]
            turns.entries[session_id] = entry
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with turns.guard:
            entry[1] -= 1
            if entry[1] == 0:
                del turns.entries[session_id]


def require_active_session(connection, session_id):
    session = get_session(connection, session_id)
    if session.status == 'closed':
        raise BusinessError(409, 'session_closed', 'This session is closed to new operations')
    return session
