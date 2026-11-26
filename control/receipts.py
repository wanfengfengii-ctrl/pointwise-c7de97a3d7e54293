from control.request_book import OperationResult, completed_results, get_request, store_result
from session.storage import BusinessError, read_transaction, write_transaction
from sound.output import SoundOutcome


def complete_operation(database, request, outcome: SoundOutcome):
    expected = (request.session_id, request.request_id, request.keyboard_id, request.action,
                request.key, request.press_id)
    if outcome.identity() != expected:
        raise RuntimeError('Received a sound outcome for a different intent')
    status = 'rejected' if outcome.error is not None else 'completed'
    result = OperationResult(request, status, outcome.pitch, outcome.error)
    with write_transaction(database) as connection:
        return store_result(connection, result)


def lookup_operation(database, session_id, request_id):
    with read_transaction(database) as connection:
        result = get_request(connection, session_id, request_id)
        if result is None:
            raise BusinessError(404, 'operation_not_found', 'No operation with this identity')
        return result


def list_completed_operations(connection, session_id):
    return [result.to_dict() for result in completed_results(connection, session_id)]
