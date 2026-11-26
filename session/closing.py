from control.delivery import drain_pending
from control.request_book import pending_requests
from review.archive import get_archive, seal_archive
from session.lifecycle import rehearsal_turn
from session.session_book import get_session, mark_session_closed
from session.storage import write_transaction
from sound.release import silence_session


def close_session(delivery, session_id):
    with rehearsal_turn(delivery.turns, session_id):
        while True:
            drain_pending(delivery, session_id)
            with write_transaction(delivery.database) as connection:
                session = get_session(connection, session_id)
                if session.status == 'closed':
                    return get_archive(connection, session_id).close_result()
                # Another local worker may have committed a reservation before this write began.
                if pending_requests(connection, session_id):
                    continue
                silence_session(connection, session_id)
                archive = seal_archive(connection, session_id)
                mark_session_closed(connection, session_id)
                return archive.close_result()
