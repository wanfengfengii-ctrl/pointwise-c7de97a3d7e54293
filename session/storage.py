import sqlite3
from contextlib import closing, contextmanager


class BusinessError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise BusinessError(422, 'invalid_field', f'{field} must be a non-blank string')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise BusinessError(422, 'invalid_field', f'{field} must be valid Unicode') from exc
    return value


def connect_store(database):
    connection = sqlite3.connect(database, isolation_level=None, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


@contextmanager
def _transaction(database, begin):
    with closing(connect_store(database)) as connection:
        connection.execute(begin)
        with connection:
            yield connection


def read_transaction(database):
    return _transaction(database, 'BEGIN')


def write_transaction(database):
    return _transaction(database, 'BEGIN IMMEDIATE')


def initialize_store(database, schema_builders):
    with closing(connect_store(database)) as connection:
        connection.execute('PRAGMA journal_mode = WAL').fetchone()
    with write_transaction(database) as connection:
        for create_schema in schema_builders:
            create_schema(connection)
