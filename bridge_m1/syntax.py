"""A deliberately small parser. Raw source bodies never reach the emitter."""
import ast
from dataclasses import asdict, dataclass
import ipaddress
import json
import re
from urllib.parse import urlsplit

from .common import require, fail


@dataclass(frozen=True)
class Match:
    function: str
    qualifier: str | None
    value: str


@dataclass(frozen=True)
class Rule:
    match: Match
    outbound: str


@dataclass(frozen=True)
class Routing:
    rules: tuple[Rule, ...]
    fallback: str


@dataclass(frozen=True)
class DNS:
    upstreams: tuple[tuple[str, str], ...]
    request: Routing
    response: Routing


TOKEN = re.compile(r'''\s+|\#[^\n]*|->|[{}():,]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s{}():,'"#]+''')


def text(value):
    require(isinstance(value, str) and all(ord(c) >= 32 for c in value), 'UNSAFE_SYNTAX')
    return value


def document_ip(value):
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        fail('SYNTHETIC_ONLY', message='Only documentation IP literals are supported in M1 synthetic fixtures.')
    nets = ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24', '2001:db8::/32')
    require(any(addr in ipaddress.ip_network(n) for n in nets if ipaddress.ip_network(n).version == addr.version), 'SYNTHETIC_ONLY')
    return str(addr)


def domain(value):
    text(value)
    try:
        value = value.encode('idna').decode('ascii').lower()
    except UnicodeError:
        fail('UNSUPPORTED_DOMAIN')
    require(len(value) <= 253 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')), 'UNSUPPORTED_DOMAIN')
    return value


def upstream_uri(value):
    try:
        u = urlsplit(value)
        require(u.scheme in ('udp', 'tcp', 'tcp+udp') and not (u.username or u.password or u.query or u.fragment or u.path), 'UNSUPPORTED_DNS')
        document_ip(u.hostname)
        require(u.port is not None and 1 <= u.port <= 65535, 'UNSUPPORTED_DNS')
        return value
    except (ValueError, TypeError):
        fail('UNSUPPORTED_DNS')


class Parser:
    def __init__(self, source, kind, identity):
        require(isinstance(source, str) and len(source) <= 65536, 'INPUT_LIMIT', kind, identity)
        self.tokens = []
        pos = 0
        for m in TOKEN.finditer(source):
            require(m.start() == pos, 'UNSAFE_SYNTAX', kind, identity, 'body')
            pos = m.end()
            t = m.group()
            if not t.isspace() and not t.startswith('#'):
                self.tokens.append(t)
        require(pos == len(source) and len(self.tokens) <= 10000, 'UNSAFE_SYNTAX', kind, identity, 'body')
        self.i, self.kind, self.identity = 0, kind, identity

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def pop(self, expected=None):
        value = self.peek()
        require(value is not None and (expected is None or value == expected), 'UNSUPPORTED_SYNTAX', self.kind, self.identity, 'body', 'Expression is outside the supported M1 grammar.')
        self.i += 1
        return value

    def value(self):
        token = self.pop()
        if token[0] in '\'"':
            try:
                token = json.loads(token) if token[0] == '"' else ast.literal_eval(token)
            except (ValueError, SyntaxError):
                fail('UNSAFE_SYNTAX', self.kind, self.identity, 'body')
        require(token not in ('{', '}', '(', ')', ':', ',', '->'), 'UNSAFE_SYNTAX', self.kind, self.identity, 'body')
        return text(token)

    def routing(self, mode, until=None):
        rules = []
        fallback = None
        while self.peek() is not None and self.peek() != until:
            require(fallback is None, 'UNSUPPORTED_SYNTAX', self.kind, self.identity, 'body', 'Fallback must occur once, at the end.')
            name = self.pop()
            if name == 'fallback':
                self.pop(':')
                fallback = self.value()
                continue
            supported = {'route': {'domain', 'dip'}, 'request': {'qname', 'qtype'}, 'response': {'qname', 'qtype', 'upstream'}}[mode]
            require(name in supported, 'UNSUPPORTED_MATCH', self.kind, self.identity, 'rules', 'Unsupported match function.')
            self.pop('(')
            first = self.value()
            qualifier = None
            if self.peek() == ':':
                self.pop(':')
                qualifier, value = first, self.value()
            else:
                value = first
            self.pop(')')
            if name in ('domain', 'qname'):
                require(qualifier in ('full', 'suffix'), 'UNSUPPORTED_MATCH', self.kind, self.identity, 'rules')
                value = domain(value)
            elif name == 'dip':
                require(qualifier is None, 'UNSUPPORTED_MATCH', self.kind, self.identity, 'rules')
                try:
                    value = str(ipaddress.ip_network(value, strict=True))
                except ValueError:
                    fail('UNSUPPORTED_CIDR', self.kind, self.identity, 'rules')
            elif name == 'qtype':
                require(qualifier is None and value in ('a', 'aaaa', 'cname', 'https'), 'UNSUPPORTED_MATCH', self.kind, self.identity, 'rules')
            else:
                require(qualifier is None, 'UNSUPPORTED_MATCH', self.kind, self.identity, 'rules')
            self.pop('->')
            rules.append(Rule(Match(name, qualifier, value), self.value()))
        require(fallback is not None and fallback != '', 'FALLBACK_REQUIRED', self.kind, self.identity, 'fallback')
        return Routing(tuple(rules), fallback)

    def dns(self):
        self.pop('upstream'); self.pop('{')
        upstreams = []
        while self.peek() != '}':
            name = self.value()
            require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) is not None and name not in ('accept', 'reject', 'asis'), 'UNSUPPORTED_DNS', self.kind, self.identity, 'upstream')
            self.pop(':')
            upstreams.append((name, upstream_uri(self.value())))
        self.pop('}')
        require(upstreams and len({x[0] for x in upstreams}) == len(upstreams), 'NAME_CONFLICT', self.kind, self.identity, 'upstream')
        self.pop('routing'); self.pop('{')
        self.pop('request'); self.pop('{')
        request = self.routing('request', '}'); self.pop('}')
        self.pop('response'); self.pop('{')
        response = self.routing('response', '}'); self.pop('}')
        self.pop('}')
        require(self.peek() is None, 'UNSUPPORTED_DNS', self.kind, self.identity, 'body')
        names = {n for n, _ in upstreams}
        for mode, block, builtins in [('request', request, {'asis', 'reject'}), ('response', response, {'accept', 'reject'})]:
            for target in [r.outbound for r in block.rules] + [block.fallback]:
                require(target in names | builtins, 'REFERENCE_MISSING', 'dns', self.identity, mode)
            for rule in block.rules:
                if rule.match.function == 'upstream':
                    require(rule.match.value in names, 'REFERENCE_MISSING', 'dns', self.identity, mode)
        return DNS(tuple(sorted(upstreams)), request, response)
