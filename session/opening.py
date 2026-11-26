from arrangement.session_setup import prepare_session_setup
from session.session_book import record_open_session
from session.storage import require_text, write_transaction
from sound.tuning import effective_transposition, initialize_tuning


def open_session(database, layout_id):
    layout_id = require_text(layout_id, 'layout_id')
    with write_transaction(database) as connection:
        setup = prepare_session_setup(connection, layout_id)
        session = record_open_session(connection, setup)
        initialize_tuning(connection, session.session_id, setup)
        keyboards = []
        for part in setup.keyboards:
            keyboard = part.to_dict()
            keyboard['transposition'] = effective_transposition(connection, session.session_id, part.keyboard_id)
            keyboards.append(keyboard)
        return {
            'session_id': session.session_id,
            'layout_id': layout_id,
            'status': session.status,
            'keyboards': keyboards,
        }
