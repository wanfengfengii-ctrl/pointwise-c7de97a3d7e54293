from dataclasses import dataclass

from arrangement.ranges import KeyRange, validate_key_range, validate_transposition
from session.storage import BusinessError, require_text


@dataclass(frozen=True)
class KeyboardPart:
    keyboard_id: str
    part: str
    keys: KeyRange
    transposition: int

    def to_dict(self):
        return {
            'keyboard_id': self.keyboard_id,
            'part': self.part,
            'low': self.keys.low,
            'high': self.keys.high,
            'transposition': self.transposition,
        }


def build_roster(keyboards):
    if not isinstance(keyboards, list) or not keyboards:
        raise BusinessError(422, 'invalid_roster', 'Supply at least one keyboard configuration')
    roster = {}
    for item in keyboards:
        if not isinstance(item, dict):
            raise BusinessError(422, 'invalid_roster', 'Each keyboard configuration must be an object')
        keyboard_id = require_text(item.get('keyboard_id'), 'keyboard_id')
        if keyboard_id in roster:
            raise BusinessError(422, 'duplicate_keyboard', 'Keyboard identifiers must be unique within a layout')
        part = require_text(item.get('part'), 'part')
        keys = validate_key_range(item.get('low'), item.get('high'))
        shift = validate_transposition(keys, item.get('transposition'))
        roster[keyboard_id] = KeyboardPart(keyboard_id, part, keys, shift)
    return roster


def require_keyboard(roster, keyboard_id):
    keyboard = roster.get(keyboard_id)
    if keyboard is None:
        raise BusinessError(404, 'keyboard_not_found', 'Keyboard is absent from this session')
    return keyboard
