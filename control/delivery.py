from dataclasses import dataclass
from typing import Callable

from control.receipts import complete_operation, lookup_operation
from control.request_book import pending_requests
from session.lifecycle import SessionTurns, rehearsal_turn
from session.storage import read_transaction, write_transaction
from sound.output import SoundOutcome
from sound.release import ReleaseIntent, commit_release
from sound.strike import PressIntent, commit_strike

Intent = PressIntent | ReleaseIntent
Accept = Callable[[Intent], SoundOutcome | None]


class ReplyUnavailable(Exception):
    """The caller needs to look up or resubmit the original request."""


def direct_delivery(intent, accept):
    return accept(intent)


@dataclass(frozen=True)
class Delivery:
    database: str
    turns: SessionTurns
    transport: Callable[[Intent, Accept], SoundOutcome | None] = direct_delivery


def _intent_for(request):
    if request.action == 'press':
        return PressIntent(request.session_id, request.request_id, request.keyboard_id, request.key)
    return ReleaseIntent(request.session_id, request.request_id, request.keyboard_id, request.press_id)


def deliver_request(delivery, request, *, local=False):
    existing = lookup_operation(delivery.database, request.session_id, request.request_id)
    if existing.status != 'pending':
        return existing

    def accept(intent):
        with rehearsal_turn(delivery.turns, intent.session_id), write_transaction(delivery.database) as connection:
            if isinstance(intent, PressIntent):
                return commit_strike(connection, intent)
            return commit_release(connection, intent)

    transport = direct_delivery if local else delivery.transport
    try:
        outcome = transport(_intent_for(request), accept)
    except ReplyUnavailable:
        outcome = None
    if outcome is None:
        return lookup_operation(delivery.database, request.session_id, request.request_id)
    return complete_operation(delivery.database, request, outcome)


def drain_pending(delivery, session_id):
    with read_transaction(delivery.database) as connection:
        requests = pending_requests(connection, session_id)
    # References are admitted only after their press has been reserved, so reservation order respects dependencies.
    for request in requests:
        result = deliver_request(delivery, request, local=True)
        if result.status == 'pending':
            raise RuntimeError('A reserved operation could not settle in reservation order')
