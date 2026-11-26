from dataclasses import dataclass

from sound.output import read_committed_results
from sound.voices import active_pitches


@dataclass(frozen=True)
class LiveSound:
    pitches: list[int]
    operations: dict[str, int]


def build_live_notes(connection, session_id):
    pitches = active_pitches(connection, session_id)
    operations = {
        result.request_id: result.pitch for result in read_committed_results(connection, session_id)
        if result.pitch is not None
    }
    return LiveSound(pitches, operations)
