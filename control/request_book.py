from dataclasses import dataclass

from session.storage import BusinessError


@dataclass(frozen=True)
class KeyRequest:
    session_id: str
    request_id: str
    keyboard_id: str
    action: str
    key: int | None = None
    press_id: str | None = None


@dataclass(frozen=True)
class OperationResult:
    request: KeyRequest
    status: str
    pitch: int | None = None
    error: str | None = None

    def to_dict(self):
        request = self.request
        body = {
            'session_id': request.session_id, 'request_id': request.request_id,
            'keyboard_id': request.keyboard_id, 'action': request.action, 'status': self.status,
        }
        if request.action == 'press':
            body['key'] = request.key
        else:
            body['press_id'] = request.press_id
        if self.pitch is not None:
            body['pitch'] = self.pitch
        if self.error is not None:
            body['error'] = self.error
        return body


def create_request_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS key_requests (
            ordinal INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            keyboard_id TEXT NOT NULL,
            action TEXT NOT NULL,
            key INTEGER,
            press_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            pitch INTEGER,
            error TEXT,
            UNIQUE (session_id, request_id),
            FOREIGN KEY (session_id, keyboard_id) REFERENCES session_keyboards(session_id, keyboard_id),
            CHECK ((action = 'press' AND key IS NOT NULL AND press_id IS NULL)
                OR (action = 'release' AND key IS NULL AND press_id IS NOT NULL)),
            CHECK ((status = 'pending' AND pitch IS NULL AND error IS NULL)
                OR (status = 'completed' AND pitch IS NOT NULL AND error IS NULL)
                OR (status = 'rejected' AND pitch IS NULL AND error IS NOT NULL))
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS key_requests_by_status ON key_requests(session_id, status, ordinal)
    ''')


def _result(row):
    request = KeyRequest(row['session_id'], row['request_id'], row['keyboard_id'], row['action'],
                         row['key'], row['press_id'])
    return OperationResult(request, row['status'], row['pitch'], row['error'])


def get_request(connection, session_id, request_id):
    row = connection.execute('''
        SELECT * FROM key_requests WHERE session_id = ? AND request_id = ?
    ''', (session_id, request_id)).fetchone()
    return _result(row) if row is not None else None


def match_request(connection, request):
    existing = get_request(connection, request.session_id, request.request_id)
    if existing is not None and existing.request != request:
        raise BusinessError(409, 'request_conflict', 'This identifier already belongs to a different operation')
    return existing


def reserve_request(connection, request):
    connection.execute('''
        INSERT INTO key_requests (session_id, request_id, keyboard_id, action, key, press_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (request.session_id, request.request_id, request.keyboard_id, request.action, request.key, request.press_id))
    return OperationResult(request, 'pending')


def pending_requests(connection, session_id):
    rows = connection.execute('''
        SELECT * FROM key_requests WHERE session_id = ? AND status = 'pending' ORDER BY ordinal
    ''', (session_id,))
    return [_result(row).request for row in rows]


def store_result(connection, result):
    old_result = match_request(connection, result.request)
    if old_result is None:
        raise RuntimeError('Cannot store a result before reservation')
    if old_result.status != 'pending':
        if old_result != result:
            raise RuntimeError('A completed operation cannot change its result')
        return old_result
    connection.execute('''
        UPDATE key_requests SET status = ?, pitch = ?, error = ? WHERE session_id = ? AND request_id = ?
    ''', (result.status, result.pitch, result.error, result.request.session_id, result.request.request_id))
    return result


def completed_results(connection, session_id):
    rows = connection.execute('''
        SELECT * FROM key_requests WHERE session_id = ? AND status <> 'pending' ORDER BY ordinal
    ''', (session_id,))
    return [_result(row) for row in rows]
