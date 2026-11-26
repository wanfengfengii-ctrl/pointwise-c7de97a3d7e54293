from dataclasses import dataclass

from arrangement.keyboard_roster import KeyboardPart
from arrangement.layouts import get_layout


@dataclass(frozen=True)
class SessionSetup:
    layout_id: str
    keyboards: tuple[KeyboardPart, ...]


def prepare_session_setup(connection, layout_id):
    layout = get_layout(connection, layout_id)
    return SessionSetup(layout.layout_id, tuple(layout.roster.values()))
