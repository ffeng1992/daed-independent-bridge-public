"""AST-routed management proxy. Upstream account/configuration CRUD stays upstream.

Traffic Overview is forwarded unchanged; it is not standalone DAE telemetry.
"""
import json
import threading
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from graphql import (GraphQLError, build_client_schema, execute_sync,
                     get_introspection_query, get_operation_ast, parse, print_ast,
                     validate, visit, Visitor)
from graphql.language import (DocumentNode, OperationDefinitionNode, SelectionSetNode,
                              FieldNode, FragmentDefinitionNode)

ENDPOINT = 'http://127.0.0.1:2024/graphql'
LIMIT = 16 * 1024 * 1024


def upstream(raw, authorization=''):
    headers = {'Content-Type': 'application/json'}
    if authorization:
        headers['Authorization'] = authorization
    request = urllib.request.Request(ENDPOINT, data=raw, headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30) as response:
        body = response.read(LIMIT + 1)
        if len(body) > LIMIT:
            raise RuntimeError('UPSTREAM_RESPONSE_LIMIT')
        return body


def request(query, authorization, forward=upstream):
    return json.loads(forward(json.dumps({'query': query}).encode(), authorization))


class Names(Visitor):
    def __init__(self):
        super().__init__(); self.variables = set(); self.fragments = set()
    def enter_variable(self, node, *_):
        self.variables.add(node.name.value)
    def enter_fragment_spread(self, node, *_):
        self.fragments.add(node.name.value)


def subtree(info):
    """Preserve aliases, arguments and fragment semantics; prune unused variables."""
    fields = tuple(info.field_nodes)
    op = OperationDefinitionNode(operation=info.operation.operation,
                                 selection_set=SelectionSetNode(selections=fields))
    names = Names(); visit(op, names)
    fragments = []
    todo = set(names.fragments)
    while todo:
        name = sorted(todo)[0]; todo.remove(name)
        if any(f.name.value == name for f in fragments):
            continue
        frag = info.fragments[name]; fragments.append(frag); visit(frag, names)
        todo |= names.fragments - {f.name.value for f in fragments}
    op.variable_definitions = tuple(v for v in info.operation.variable_definitions
                                    if v.variable.name.value in names.variables)
    return print_ast(DocumentNode(definitions=(op, *fragments)))


def touches_runtime(document, operation, schema):
    fragments = {d.name.value: d for d in document.definitions if isinstance(d, FragmentDefinitionNode)}
    def walk(selection, kind, seen):
        if not selection:
            return False
        for node in selection.selections:
            if isinstance(node, FieldNode):
                name = node.name.value
                if (kind == 'Mutation' and name == 'run') or (kind == 'General' and name == 'dae'):
                    return True
                from graphql import get_named_type
                typ = schema.get_type(kind)
                field = getattr(typ, 'fields', {}).get(name)
                if field and walk(node.selection_set, get_named_type(field.type).name, seen):
                    return True
            elif node.kind == 'fragment_spread':
                name = node.name.value
                if name not in seen:
                    frag = fragments[name]
                    if walk(frag.selection_set, frag.type_condition.name.value, seen | {name}):
                        return True
            elif walk(node.selection_set, node.type_condition.name.value if node.type_condition else kind, seen):
                return True
        return False
    return walk(operation.selection_set, 'Mutation' if operation.operation.value == 'mutation' else 'Query', set())


class Adapter:
    def __init__(self, schema, runtime, forward=upstream):
        self.schema, self.runtime, self.forward = schema, runtime, forward
        self.control_lock = threading.Lock()

    def handle(self, raw, authorization):
        value = json.loads(raw)
        # Ordinary documents are forwarded byte-for-byte, including variables.
        try:
            document = parse(value['query'])
        except GraphQLError:
            return self.forward(raw, authorization)
        operation = get_operation_ast(document, value.get('operationName'))
        if operation is None:
            return self.forward(raw, authorization)
        if not touches_runtime(document, operation, self.schema):
            from .graphql_config import preserve_create_false
            return preserve_create_false(raw, authorization, self.forward)
        errors = validate(self.schema, document)
        if errors:
            return json.dumps({'errors': [e.formatted for e in errors]}).encode()
        operation = get_operation_ast(document, value.get('operationName'))
        if operation is None:
            return json.dumps({'errors': [{'message': 'OPERATION_REQUIRED'}]}).encode()
        if not touches_runtime(document, operation, self.schema):
            return self.forward(raw, authorization)
        # Official identity is checked on every runtime request, before disclosure/control.
        auth = request('{user{username}}', authorization, self.forward)
        if auth.get('errors') or not (auth.get('data') or {}).get('user'):
            return json.dumps({'errors': [{'message': 'access denied'}]}).encode()
        context = {'authorization': authorization, 'status': None}
        def resolver(source, info, **args):
            kind, field = info.parent_type.name, info.field_name
            if kind == 'Mutation' and field == 'run':
                with self.control_lock:
                    return self.runtime.run(authorization.removeprefix('Bearer '), args['dry'])
            if kind == 'Query' and field == 'general':
                return {'_runtime_general': True}
            if kind == 'General' and field == 'dae':
                return {'_runtime_dae': True}
            if kind == 'Dae':
                if context['status'] is None:
                    context['status'] = self.runtime.status()
                return self.runtime.dae(field, context['status'], authorization.removeprefix('Bearer '))
            if kind in {'Query', 'Mutation'} or (kind == 'General' and source.get('_runtime_general')):
                query = subtree(info)
                # General subtrees need their original parent restored.
                if kind == 'General':
                    sub = parse(query); op = sub.definitions[0]
                    from graphql.language import NameNode
                    op.selection_set = SelectionSetNode(selections=(FieldNode(name=NameNode(value='general'), selection_set=op.selection_set),))
                    query = print_ast(sub)
                body = json.dumps({'query': query, 'variables': info.variable_values}).encode()
                from .graphql_config import preserve_create_false
                response = json.loads(preserve_create_false(body, authorization, self.forward))
                if response.get('errors'):
                    raise GraphQLError(response['errors'][0]['message'])
                data = response['data']
                if kind == 'General':
                    data = data['general']
                return data[info.path.key]
            if isinstance(source, dict):
                return source.get(info.path.key, source.get(field))
            return None
        result = execute_sync(self.schema, document, variable_values=value.get('variables'),
                              operation_name=value.get('operationName'), field_resolver=resolver)
        return json.dumps(result.formatted).encode()


class Controls:
    def __init__(self, runtime):
        self.runtime = runtime
    def status(self):
        s = self.runtime.status()
        if s.get('error') or s.get('state') == 'rollback-needed':
            raise GraphQLError('RUNTIME_IDENTITY_UNAVAILABLE')
        return s
    def dae(self, field, s, token):
        if field == 'running':
            if s['state'] == 'stopped' and s['MainPID'] == 0:
                return False
            if s['state'] != 'running' or not s.get('identityVerified'):
                raise GraphQLError('RUNTIME_IDENTITY_UNAVAILABLE')
            return True
        if field == 'version':
            pin = json.loads(Path('/opt/bridge/upstream.lock.json').read_text())['components']['dae']
            expected = next(x['sha256'] for x in pin['archive_members'] if x['path'] == 'dae-linux-x86_64')
            if s.get('state') == 'stopped' and s.get('MainPID') == 0:
                # Stopped has no /proc/PID/exe; verify the fixed official install.
                from .authority import manifest
                from bridge_m1.common import digest
                manifest()
                actual = digest(Path('/opt/bridge-official/dae').read_bytes())
            else:
                actual = s.get('executableSha256')
            if actual != expected:
                raise GraphQLError('RUNTIME_IDENTITY_UNAVAILABLE')
            return pin['version']
        if field == 'modified':
            from .runtime_bundle import fingerprints
            source, _, ext, _ = self.runtime.snapshot(token)
            if s.get('activeBundle') is None:
                return True
            if not s.get('sourceFingerprint'):
                raise GraphQLError('ACTIVE_SOURCE_FINGERPRINT_UNAVAILABLE')
            return fingerprints(source, ext)['sourceSha256'] != s['sourceFingerprint']
        raise GraphQLError('RUNTIME_FIELD_UNSUPPORTED')
    def run(self, token, dry):
        if type(dry) is not bool:
            raise GraphQLError('INVALID_RUN_ARGUMENT')
        try:
            s = self.status()
            if dry:
                result = self.runtime.action('stop', s['activeBundle'])
                if result.get('error') or result.get('state') != 'stopped':
                    raise RuntimeError('STOP_NOT_CONFIRMED')
            else:
                preview = self.runtime.preview(token)
                self.runtime.validate(preview['previewId'])
                if s.get('activeBundle') and s.get('sourceFingerprint') == preview['sourceFingerprint'] and s['state'] == 'stopped':
                    result = {'result': self.runtime.action('start', s['activeBundle'])}
                else:
                    # Existing helper apply deliberately requires a healthy predecessor.
                    # Resume only its verified active bundle after validating the new
                    # candidate; helper rollback semantics remain unchanged on failure.
                    if s.get('activeBundle') and s['state'] == 'stopped':
                        resumed = self.runtime.action('start', s['activeBundle'])
                        if resumed.get('error') or resumed.get('state') != 'running' or not resumed.get('identityVerified'):
                            raise RuntimeError('PREVIOUS_START_NOT_CONFIRMED')
                    result = self.runtime.apply(token, preview['previewId'])
                if result.get('result', {}).get('error'):
                    raise RuntimeError('APPLY_REJECTED')
                s = self.status()
                if s['state'] == 'stopped':
                    self.runtime.action('start', s['activeBundle'])
                s = self.status()
                if s['state'] != 'running' or not s.get('identityVerified'):
                    raise RuntimeError('START_NOT_CONFIRMED')
            return 1
        except Exception as exc:
            from .extensions import empty_group_diagnostic
            diagnostic=empty_group_diagnostic(exc)
            if diagnostic is not None:
                raise GraphQLError(diagnostic['error'], extensions={'code':diagnostic['error'], 'groupName':diagnostic['groupName'], 'fieldPath':diagnostic['fieldPath']}) from None
            raise GraphQLError('BRIDGE_CONTROL_FAILED', extensions={'code': 'BRIDGE_CONTROL_FAILED'}) from None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log GraphQL variables, tokens or upstream responses.
    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', '-1'))
            if self.path != '/graphql' or not 0 < n <= LIMIT or self.headers.get('Transfer-Encoding'):
                raise ValueError()
            if self.headers.get_content_type() != 'application/json':
                raise ValueError()
            raw = self.rfile.read(n)
            body = self.server.adapter.handle(raw, self.headers.get('Authorization', ''))
        except Exception:
            body = b'{"errors":[{"message":"RUNTIME_ADAPTER_REQUEST_FAILED"}]}'
        self.send_response(200); self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def setup(self):
        super().setup(); self.connection.settimeout(60)


def main():
    from .authority import manifest
    from .runtime import Runtime
    manifest()
    introspection = request(get_introspection_query(), '')
    schema = build_client_schema(introspection['data'])
    server = ThreadingHTTPServer(('127.0.0.1', 2025), Handler)
    server.daemon_threads = True
    server.adapter = Adapter(schema, Controls(Runtime()))
    server.serve_forever()

if __name__ == '__main__':
    main()
