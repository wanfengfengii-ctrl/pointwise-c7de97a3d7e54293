from dataclasses import dataclass

from session.storage import BusinessError

PITCH_MIN = 0
PITCH_MAX = 127


@dataclass(frozen=True)
class KeyRange:
    low: int
    high: int


def validate_key_range(low, high):
    if type(low) is not int or type(high) is not int:
        raise BusinessError(422, 'invalid_range', 'Key range endpoints must be integers')
    if not PITCH_MIN <= low <= high <= PITCH_MAX:
        raise BusinessError(422, 'invalid_range', 'Key range must be ordered and within 0–127')
    return KeyRange(low, high)


def require_key_in_range(keys, key):
    if type(key) is not int or not keys.low <= key <= keys.high:
        raise BusinessError(422, 'invalid_key', 'Key must be an integer in the configured range')
    return key


def validate_transposition(keys, shift):
    if type(shift) is not int:
        raise BusinessError(422, 'invalid_transposition', 'Transposition must be an integer')
    if not PITCH_MIN <= keys.low + shift <= keys.high + shift <= PITCH_MAX:
        raise BusinessError(422, 'invalid_transposition', 'Transposed key range must stay within 0–127')
    return shift
