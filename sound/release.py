from dataclasses import dataclass

from session.lifecycle import require_active_session
from sound.output import SoundOutcome, append_output_event, get_committed_result, save_committed_result
from sound.voices import active_voices, end_voice, get_voice, has_active_source


@dataclass(frozen=True)
class ReleaseIntent:
    session_id: str
    request_id: str
    keyboard_id: str
    press_id: str


def commit_release(connection, intent):
    prior = get_committed_result(connection, intent.session_id, intent.request_id)
    if prior is not None:
        prior.require_intent(intent.keyboard_id, 'release', press_id=intent.press_id)
        return prior
    require_active_session(connection, intent.session_id)
    voice = get_voice(connection, intent.session_id, intent.press_id)
    if voice is None:
        return None
    if voice.keyboard_id != intent.keyboard_id or not voice.active:
        outcome = SoundOutcome(intent.session_id, intent.request_id, intent.keyboard_id, 'release',
                               press_id=intent.press_id, error='invalid_reference')
        return save_committed_result(connection, outcome)
    end_voice(connection, voice)
    if not has_active_source(connection, intent.session_id, voice.pitch):
        append_output_event(connection, intent.session_id, 'stop', voice.pitch, intent.request_id)
    outcome = SoundOutcome(intent.session_id, intent.request_id, intent.keyboard_id, 'release',
                           press_id=intent.press_id, pitch=voice.pitch)
    return save_committed_result(connection, outcome)


def silence_session(connection, session_id):
    voices = active_voices(connection, session_id)
    for voice in voices:
        end_voice(connection, voice)
    for pitch in sorted({voice.pitch for voice in voices}):
        append_output_event(connection, session_id, 'stop', pitch, None)
