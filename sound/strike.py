from dataclasses import dataclass

from session.lifecycle import require_active_session
from sound.output import SoundOutcome, append_output_event, get_committed_result, save_committed_result
from sound.tuning import effective_transposition
from sound.voices import Voice, add_voice, has_active_source


@dataclass(frozen=True)
class PressIntent:
    session_id: str
    request_id: str
    keyboard_id: str
    key: int


def commit_strike(connection, intent):
    prior = get_committed_result(connection, intent.session_id, intent.request_id)
    if prior is not None:
        prior.require_intent(intent.keyboard_id, 'press', key=intent.key)
        return prior
    require_active_session(connection, intent.session_id)
    shift = effective_transposition(connection, intent.session_id, intent.keyboard_id)
    pitch = intent.key + shift
    already_sounding = has_active_source(connection, intent.session_id, pitch)
    add_voice(connection, Voice(intent.session_id, intent.request_id, intent.keyboard_id, pitch))
    if not already_sounding:
        append_output_event(connection, intent.session_id, 'start', pitch, intent.request_id)
    outcome = SoundOutcome(intent.session_id, intent.request_id, intent.keyboard_id, 'press',
                           key=intent.key, pitch=pitch)
    return save_committed_result(connection, outcome)
