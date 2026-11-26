from arrangement.keyboard_roster import require_keyboard
from arrangement.ranges import require_key_in_range
from control.delivery import deliver_request
from control.request_book import KeyRequest, match_request, reserve_request
from session.lifecycle import rehearsal_turn, require_active_session
from session.storage import BusinessError, require_text, write_transaction


def submit_press(delivery, session_id, keyboard_id, request_id, key):
    session_id = require_text(session_id, 'session_id')
    keyboard_id = require_text(keyboard_id, 'keyboard_id')
    request_id = require_text(request_id, 'request_id')
    if type(key) is not int:
        raise BusinessError(422, 'invalid_key', 'Key must be an integer')
    request = KeyRequest(session_id, request_id, keyboard_id, 'press', key=key)
    with rehearsal_turn(delivery.turns, session_id), write_transaction(delivery.database) as connection:
        result = match_request(connection, request)
        if result is None:
            session = require_active_session(connection, session_id)
            part = require_keyboard(session.roster, keyboard_id)
            require_key_in_range(part.keys, key)
            result = reserve_request(connection, request)
    if result.status != 'pending':
        return result
    return deliver_request(delivery, request)
