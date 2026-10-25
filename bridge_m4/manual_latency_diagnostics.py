"""Value-free observation of the existing manual official probe; never probes."""
import datetime
import json
import time
import uuid
import urllib.error
from graphql import parse, validate, get_operation_ast
from graphql.execution.collect_fields import collect_fields
from graphql.execution.values import get_variable_values, get_argument_values
from graphql.language import FragmentDefinitionNode


def manual_fields(schema, raw):
    """Resolve only the selected, valid operation, including directives/aliases."""
    try:
        value = json.loads(raw)
        document = parse(value['query'])
        operation = get_operation_ast(document, value.get('operationName'))
        if operation is None or operation.operation.value != 'mutation' or validate(schema, document):
            return None
        variables = get_variable_values(schema, operation.variable_definitions or (), value.get('variables') or {})
        if not isinstance(variables, dict):
            return None
        fragments = {d.name.value: d for d in document.definitions if isinstance(d, FragmentDefinitionNode)}
        fields = collect_fields(schema, fragments, variables, schema.mutation_type, operation.selection_set)
        selected = {}
        for key, nodes in fields.items():
            if nodes[0].name.value == 'testNodeLatencies':
                args = get_argument_values(schema.mutation_type.fields['testNodeLatencies'], nodes[0], variables)
                ids = args.get('ids')
                selected[key] = len(ids) if isinstance(ids, list) else None
        return selected or None
    except Exception:
        return None  # Diagnostics never change GraphQL validation/forwarding.


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


class Observation:
    def __init__(self, fields):
        self.fields = fields
        self.start = time.monotonic()
        self.value = {'component': 'manual-node-latency', 'requestId': uuid.uuid4().hex,
                      'operation': 'testNodeLatencies',
                      'nodeCount': sum(fields.values()) if all(v is not None for v in fields.values()) else None,
                      'startedAt': stamp(), 'officialCompletion': 'UNKNOWN',
                      'category': 'BRIDGE_PROCESSING_ERROR', 'cacheRecorded': False}

    def forward(self, raw, authorization, forward):
        try:
            body = forward(raw, authorization)  # unchanged bytes/auth/default timeout; exactly once
        except Exception as exc:
            timeout = isinstance(exc, TimeoutError) or (isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError))
            if timeout:
                self.value.update(category='UPSTREAM_TIMEOUT', errorCategory='TIMEOUT')
            elif isinstance(exc, urllib.error.HTTPError):
                self.value.update(category='UPSTREAM_HTTP_ERROR', errorCategory='HTTP_ERROR',
                                  officialCompletion='RESPONSE_RECEIVED', upstreamHttpStatus=exc.code)
            elif isinstance(exc, (OSError, urllib.error.URLError)):
                self.value.update(category='UPSTREAM_TRANSPORT_ERROR', errorCategory='TRANSPORT_ERROR')
            else:
                self.bridge_error()
            raise
        try:
            result = json.loads(body)
            if type(result) is not dict:
                raise ValueError()
            if result.get('errors'):
                if not isinstance(result['errors'], list):
                    raise ValueError()
                self.value.update(category='UPSTREAM_GRAPHQL_ERROR', officialCompletion='RESPONSE_RECEIVED', errorCategory='GRAPHQL_ERROR')
            elif type(result.get('data')) is dict and all(
                    isinstance(result['data'].get(key), list) and
                    all(type(row) is dict for row in result['data'][key]) for key in self.fields):
                self.value.update(category='UPSTREAM_RESULT', officialCompletion='RESPONSE_RECEIVED')
            else:
                raise ValueError()
        except Exception:
            self.value.update(category='INVALID_UPSTREAM_RESPONSE', errorCategory='RESPONSE_SCHEMA')
        return body

    def bridge_error(self):
        self.value.update(category='BRIDGE_PROCESSING_ERROR', errorCategory='BRIDGE_PROCESSING')

    def finish(self):
        try:
            self.value.update(endedAt=stamp(), elapsedMs=round((time.monotonic()-self.start)*1000, 3))
            emit(self.value)
        except Exception:
            pass  # A log sink failure cannot alter the request or start a retry.
