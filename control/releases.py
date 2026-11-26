from control.delivery import deliver_request
from control.request_book import KeyRequest, get_request, match_request, reserve_request
from session.lifecycle import rehearsal_turn, require_active_session
from session.storage import BusinessError, require_text, write_transaction


def validate_press_reference(connection, request):
    source = get_request(connection, request.session_id, request.press_id)
    if source is None or source.request.action != 'press' or source.request.keyboard_id != request.keyboard_id:
        raise BusinessError(422, 'invalid_reference', 'Release must refer to a press on this session and keyboard')
    return source.request


def submit_release(delivery, session_id, keyboard_id, request_id, press_id):
    session_id = require_text(session_id, 'session_id')
    keyboard_id = require_text(keyboard_id, 'keyboard_id')
    request_id = require_text(request_id, 'request_id')
    press_id = require_text(press_id, 'press_id')
    request = KeyRequest(session_id, request_id, keyboard_id, 'release', press_id=press_id)
    with rehearsal_turn(delivery.turns, session_id), write_transaction(delivery.database) as connection:
        result = match_request(connection, request)
        if result is None:
            require_active_session(connection, session_id)
            validate_press_reference(connection, request)
            result = reserve_request(connection, request)
    if result.status != 'pending':
        return result
    return deliver_request(delivery, request)
