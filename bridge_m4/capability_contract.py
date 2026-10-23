"""Explicit allowances for reviewed, unconsumed GraphQL capability fields."""
import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / 'contracts/m4/graphql-capabilities.json'


def verify(fields, expected, *, policy_path=POLICY):
    from bridge_m1.common import require
    require(type(fields) is list and all(type(x) is dict and set(x) == {'name'} and
            type(x['name']) is str for x in fields), 'SCHEMA_DRIFT')
    names = [x['name'] for x in fields]
    require(len(names) == len(set(names)), 'SCHEMA_DRIFT')
    rules = json.loads(Path(policy_path).read_text())
    require(type(rules) is dict and set(rules) == {'schemaVersion', 'reviewedUnconsumed'} and
            type(rules['schemaVersion']) is int and rules['schemaVersion'] == 1 and
            type(rules['reviewedUnconsumed']) is dict, 'CAPABILITY_CONTRACT')
    allowed = rules['reviewedUnconsumed']
    require(not set(allowed) & set(expected) and
            all(type(k) is str and type(v) is str and bool(v.strip()) for k,v in allowed.items()),
            'CAPABILITY_CONTRACT')
    require(set(expected) <= set(names) and set(names) <= set(expected) | set(allowed), 'SCHEMA_DRIFT')
