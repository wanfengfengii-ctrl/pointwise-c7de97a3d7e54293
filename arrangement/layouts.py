from dataclasses import dataclass

from arrangement.keyboard_roster import KeyboardPart, build_roster
from arrangement.ranges import KeyRange
from session.storage import BusinessError, require_text, write_transaction


@dataclass(frozen=True)
class Layout:
    layout_id: str
    roster: dict[str, KeyboardPart]

    def to_dict(self):
        return {'layout_id': self.layout_id, 'keyboards': [part.to_dict() for part in self.roster.values()]}


def create_layout_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS layouts (
            layout_id TEXT PRIMARY KEY NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS layout_keyboards (
            layout_id TEXT NOT NULL REFERENCES layouts(layout_id),
            keyboard_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            part TEXT NOT NULL,
            low_key INTEGER NOT NULL,
            high_key INTEGER NOT NULL,
            initial_shift INTEGER NOT NULL,
            PRIMARY KEY (layout_id, keyboard_id),
            UNIQUE (layout_id, position)
        )
    ''')


def register_layout(database, layout_id, keyboards):
    layout_id = require_text(layout_id, 'layout_id')
    roster = build_roster(keyboards)
    with write_transaction(database) as connection:
        if connection.execute('SELECT 1 FROM layouts WHERE layout_id = ?', (layout_id,)).fetchone():
            raise BusinessError(409, 'layout_exists', 'This layout is already registered')
        connection.execute('INSERT INTO layouts VALUES (?)', (layout_id,))
        connection.executemany('''
            INSERT INTO layout_keyboards
            (layout_id, keyboard_id, position, part, low_key, high_key, initial_shift)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            (layout_id, part.keyboard_id, position, part.part, part.keys.low, part.keys.high, part.transposition)
            for position, part in enumerate(roster.values())
        ))
    return Layout(layout_id, roster)


def get_layout(connection, layout_id):
    if connection.execute('SELECT 1 FROM layouts WHERE layout_id = ?', (layout_id,)).fetchone() is None:
        raise BusinessError(404, 'layout_not_found', 'No layout with this identifier')
    rows = connection.execute('''
        SELECT keyboard_id, part, low_key, high_key, initial_shift
        FROM layout_keyboards WHERE layout_id = ? ORDER BY position
    ''', (layout_id,))
    roster = {
        row['keyboard_id']: KeyboardPart(
            row['keyboard_id'], row['part'], KeyRange(row['low_key'], row['high_key']), row['initial_shift']
        )
        for row in rows
    }
    return Layout(layout_id, roster)
