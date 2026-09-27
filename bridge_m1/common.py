"""Small shared primitives; diagnostics never echo source values."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.1-m3'
DAED_VERSION = 'v2.1.1'


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('DUPLICATE_KEY', 'snapshot', '', '$', 'Duplicate JSON object key.')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: fail('FORMAT_ERROR', 'snapshot', '', '$', 'Nonfinite JSON number.'))
    except (ValueError, UnicodeError, RecursionError):
        fail('FORMAT_ERROR', 'snapshot', '', '$', 'Invalid JSON encoding or structure.')


class Rejected(Exception):
    def __init__(self, code, kind, identity, path, message):
        self.diagnostic = {'objectType': kind, 'objectId': 'id:' + digest(str(identity).encode())[:16],
                           'fieldPath': path, 'reasonCode': code, 'message': message}
        super().__init__(code)


def fail(code, kind='snapshot', identity='', path='$', message='Input is outside the M1 contract.'):
    raise Rejected(code, kind, identity, path, message)


def require(condition, code, kind='snapshot', identity='', path='$', message='Input is outside the M1 contract.'):
    if not condition:
        fail(code, kind, identity, path, message)


def alias(prefix, identity):
    return prefix + '_' + digest(identity.encode())  # full digest; collisions additionally checked
