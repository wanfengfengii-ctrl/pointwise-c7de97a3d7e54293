from dataclasses import dataclass

from sound.output import read_output_events


@dataclass(frozen=True)
class TimelineEntry:
    seq: int
    action: str
    pitch: int
    request_id: str | None

    def to_dict(self):
        return {'seq': self.seq, 'action': self.action, 'pitch': self.pitch, 'request_id': self.request_id}


def build_timeline(connection, session_id):
    return [TimelineEntry(event.seq, event.action, event.pitch, event.request_id)
            for event in read_output_events(connection, session_id)]
