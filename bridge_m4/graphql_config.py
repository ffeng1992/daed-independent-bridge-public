"""Narrow compatibility for the pinned upstream createConfig false-value loss.

The official create/update operations still own authorization and persistence.
No database access, input defaults, or upstream file changes are performed here.
"""
import copy
import json
from graphql import parse, print_ast, get_operation_ast, value_from_ast_untyped
from graphql.language import FieldNode, NameNode, SelectionSetNode


def preserve_create_false(raw, authorization, forward):
    value = json.loads(raw)
    document = parse(value['query'])
    operation = get_operation_ast(document, value.get('operationName'))
    if operation is None or operation.operation.value != 'mutation':
        return forward(raw, authorization)
    variables = {v.variable.name.value: value_from_ast_untyped(v.default_value)
                 for v in operation.variable_definitions if v.default_value is not None}
    variables.update(value.get('variables') or {})
    fragments = {d.name.value: d for d in document.definitions if d.kind == 'fragment_definition'}
    targets = []
    ambiguous = []

    def find(selection, seen):
        for node in selection.selections:
            directives = {d.name.value: {a.name.value: value_from_ast_untyped(a.value, variables)
                          for a in d.arguments} for d in node.directives}
            if directives.get('skip', {}).get('if') is True or directives.get('include', {}).get('if') is False:
                continue
            if isinstance(node, FieldNode):
                if node.name.value != 'createConfig':
                    continue
                args = {a.name.value: value_from_ast_untyped(a.value, variables) for a in node.arguments}
                glob = args.get('global')
                if isinstance(glob, dict) and glob.get('tproxyPortProtect') is False:
                    # Official update serializes every effective global value.
                    # It would turn an absent mark (automatic selection) into
                    # explicit zero. The full official form supplies the mark;
                    # partial API callers must state it instead of being changed.
                    if 'soMarkFromDae' not in glob or glob['soMarkFromDae'] is None:
                        ambiguous.append((node.alias or node.name).value)
                    if not any(node is existing for existing in targets):
                        targets.append(node)
            elif node.kind == 'inline_fragment':
                find(node.selection_set, seen)
            elif node.name.value not in seen and node.name.value in fragments:
                find(fragments[node.name.value].selection_set, seen | {node.name.value})
    find(operation.selection_set, set())
    if not targets:
        return forward(raw, authorization)
    if ambiguous:
        return json.dumps({'errors': [{'message': 'CONFIG_CREATE_EXPLICIT_MARK_REQUIRED',
            'path': [key], 'extensions': {'code': 'CONFIG_CREATE_EXPLICIT_MARK_REQUIRED',
            'field': 'global.soMarkFromDae'}} for key in sorted(set(ambiguous))]}).encode()

    # Choose an internal response key absent from every user-selected field.
    from graphql import Visitor, visit
    class Keys(Visitor):
        def __init__(self):
            super().__init__(); self.keys = set()
        def enter_field(self, node, *_):
            self.keys.add((node.alias or node.name).value)
    keys = Keys(); visit(document, keys)
    internal = '_bridge_created_id'
    while internal in keys.keys:
        internal += '_'
    originals = {}
    for field in targets:
        key = (field.alias or field.name).value
        originals.setdefault(key, []).append(copy.deepcopy(field))
        field.selection_set = SelectionSetNode(selections=(*field.selection_set.selections,
            FieldNode(name=NameNode(value='id'), alias=NameNode(value=internal))))
    payload = dict(value, query=print_ast(document))
    response = json.loads(forward(json.dumps(payload).encode(), authorization))
    data = response.get('data')
    if not isinstance(data, dict):
        return json.dumps(response).encode()
    for key, fields in originals.items():
        item = data.get(key)
        if key not in data or item is None:
            continue  # Skipped selection or an upstream error; never create locally.
        ident = item.pop(internal, None) if isinstance(item, dict) else None
        if not isinstance(ident, str) or not ident:
            response.setdefault('errors', []).append({'message': 'CONFIG_CREATE_IDENTITY_MISSING', 'path': [key]})
            data[key] = None
            continue
        # Apply the explicit false through official updateConfig. Keep the
        # caller's selection/aliases/fragments in the returned update response.
        from .graphql_runtime import Names
        update = parse('mutation { updateConfig(id:' + json.dumps(ident) +
                       ',global:{tproxyPortProtect:false}) { id } }').definitions[0]
        field = update.selection_set.selections[0]
        field.alias = NameNode(value=key)
        verification = parse('{ ' + internal + ': global { tproxyPortProtect } }').definitions[0].selection_set.selections[0]
        field.selection_set = SelectionSetNode(selections=(*tuple(s for f in fields for s in f.selection_set.selections), verification))
        names = Names(); visit(update, names)
        used = []; todo = set(names.fragments)
        while todo:
            name = sorted(todo)[0]; todo.remove(name)
            frag = fragments[name]; used.append(frag); visit(frag, names)
            todo |= names.fragments - {f.name.value for f in used}
        update.variable_definitions = tuple(v for v in operation.variable_definitions if v.variable.name.value in names.variables)
        from graphql.language import DocumentNode
        query = print_ast(DocumentNode(definitions=(update, *used)))
        result = json.loads(forward(json.dumps({'query': query, 'variables': variables}).encode(), authorization))
        saved = (result.get('data') or {}).get(key)
        verified = isinstance(saved, dict) and saved.pop(internal, None) == {'tproxyPortProtect': False}
        if result.get('errors') or not verified:
            response.setdefault('errors', []).append({'message': 'CONFIG_CREATE_VALUE_NOT_PRESERVED',
                'path': [key], 'extensions': {'code': 'CONFIG_CREATE_VALUE_NOT_PRESERVED', 'configId': ident}})
            data[key] = None
        else:
            data[key] = saved
    return json.dumps(response).encode()
