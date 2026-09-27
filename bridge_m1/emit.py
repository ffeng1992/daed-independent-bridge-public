"""Typed IR -> deterministic DAE text. Never accepts GraphQL dictionaries."""
import base64
import json

from .common import require
from .model import IR


def quoted(value):
    # All emitted string values have already been validated or constructed from IR.
    return json.dumps(value, ensure_ascii=False)


def scalar(value):
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return quoted(','.join(value))
    return quoted(value)


def route_lines(block, indent):
    lines = []
    for rule in block.rules:  # input rule order is semantic, never sorted
        m = rule.match
        arg = ((m.qualifier + ': ') if m.qualifier else '') + quoted(m.value)
        lines.append(indent + m.function + '(' + arg + ') -> ' + rule.outbound)
    lines.append(indent + 'fallback: ' + block.fallback)
    return lines


def emit(ir):
    require(isinstance(ir, IR) and not ir.unsupported, 'IR_REQUIRED')
    lines = [f'# daed-independent-bridge converter={ir.converter_version}',
             f'# source-sha256={ir.source_fingerprint}', '# synthetic-only; static-validation-only; not published', 'global {']
    for value in ir.globals:
        if value['emitted']:
            lines.append('    ' + value['key'] + ': ' + scalar(value['value']))
    lines += ['}', '', 'node {']
    for node in ir.nodes:
        credentials = base64.urlsafe_b64encode((node.cipher + ':' + node.password).encode()).decode().rstrip('=')
        host = '[' + node.host + ']' if ':' in node.host else node.host
        uri = 'ss://' + credentials + '@' + host + ':' + str(node.port)
        lines.append('    ' + node.alias + ': ' + quoted(uri))
    lines += ['}', '', 'group {']
    for group in ir.groups:
        lines += ['    ' + group.alias + ' {', '        filter: name(' + ', '.join(quoted(x) for x in group.members) + ')',
                  '        policy: ' + group.policy, '    }']
    lines += ['}', '', 'dns {', '    upstream {']
    for name, uri in ir.dns.upstreams:
        lines.append('        ' + name + ': ' + quoted(uri))
    lines += ['    }', '    routing {', '        request {']
    lines += route_lines(ir.dns.request, '            ')
    lines += ['        }', '        response {'] + route_lines(ir.dns.response, '            ')
    lines += ['        }', '    }', '}', '', 'routing {']
    lines += route_lines(ir.routing, '    ')
    lines += ['}', '']
    return '\n'.join(lines).encode('utf-8')
