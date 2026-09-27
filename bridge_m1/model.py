"""GraphQL snapshot -> typed IR. No DAE text generation here."""
import base64
from dataclasses import asdict, dataclass, field
import re
from urllib.parse import unquote, urlsplit

from .common import ROOT, VERSION, DAED_VERSION, alias, canonical, digest, load_json, require, fail
from .collect import normalize_source, unique
from .syntax import Parser, Routing, Rule, text, document_ip

FIELDS = load_json((ROOT / 'contracts/global-fields.json').read_bytes())['fields']


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    alias: str
    subscription_id: str | None
    tag: str | None
    uri_fragment: str
    cipher: str
    password: str = field(repr=False)
    host: str = ''
    port: int = 0


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    alias: str
    policy: str
    members: tuple[str, ...]
    bindings: tuple[dict, ...]


@dataclass(frozen=True)
class IR:
    schema_version: int
    source: dict
    converter_version: str
    source_fingerprint: str
    nodes: tuple[Node, ...]
    groups: tuple[Group, ...]
    subscriptions: tuple[dict, ...]
    dns: object
    routing: Routing
    globals: tuple[dict, ...]
    profile_metadata: dict
    unsupported: tuple[dict, ...]


def node_ir(raw):
    identity = raw['id']
    require(raw['protocol'] in ('ss','shadowsocks'), 'UNSUPPORTED_PROTOCOL', 'node', identity, 'protocol', 'Only Shadowsocks is supported.')
    try:
        u = urlsplit(raw['link'])
        require(u.scheme == 'ss' and u.username is not None and u.password is None and not u.query and u.path in ('', '/'), 'UNSUPPORTED_NODE_URI', 'node', identity, 'link')
        encoded = unquote(u.username)
        decoded = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode()
        cipher, password = decoded.split(':', 1)
        require(cipher in ('aes-128-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305'), 'UNSUPPORTED_CIPHER', 'node', identity, 'cipher')
        require(password and len(password) <= 256, 'UNSUPPORTED_CREDENTIAL', 'node', identity, 'password')
        host, port = document_ip(u.hostname), u.port
        require(port is not None and 1 <= port <= 65535, 'UNSUPPORTED_NODE_URI', 'node', identity, 'port')
        address = (f'[{host}]' if ':' in host else host) + ':' + str(port)
        require(raw['address'] == address, 'NODE_ADDRESS_MISMATCH', 'node', identity, 'address')
        text(raw['name'])
        if raw['tag'] is not None:
            text(raw['tag'])
        # URI fragment is display metadata only; source is retained in normalized snapshot.
        return Node(identity, raw['name'], alias('n', identity), raw['subscriptionID'], raw['tag'], unquote(u.fragment), cipher, password, host, port)
    except (ValueError, UnicodeError, TypeError):
        fail('UNSUPPORTED_NODE_URI', 'node', identity, 'link', 'Malformed or unsupported Shadowsocks URI.')


def globals_ir(source):
    result = []
    require(set(source) == {f['graphql'] for f in FIELDS}, 'UNSUPPORTED_FIELD', 'global', '', 'global')
    def entry(key, value, mapping='exact', emitted=True):
        result.append({'key': key, 'value': value, 'mapping': mapping, 'emitted': emitted})
    # Strict supported values; every non-covered value fails instead of becoming a default.
    enums = {'logLevel': {'error','warn','info','debug','trace'}, 'dialMode': {'ip','domain','domain+','domain++'},
             'tcpCheckHttpMethod': {'HEAD','GET'}, 'tlsImplementation': {'tls'}, 'utlsImitate': {'chrome_auto'}}
    fixed_false = {'enableLocalTcpFastRedirect','autoConfigFirewallRule','tlsFragment'}
    durations = {'checkInterval','checkTolerance','sniffingTimeout','udphopInterval'}
    for f in FIELDS:
        name, key, val = f['graphql'], f['dae'], source[f['graphql']]
        if name == 'soMarkFromDaeSet':
            entry(key, val, 'exact-presence-metadata', False); continue
        if name == 'soMarkFromDae':
            require(0 <= val <= 4294967295 and (source['soMarkFromDaeSet'] or val == 0), 'MARK_AMBIGUOUS', 'global', '', name)
            entry(key, val, 'exact' if source['soMarkFromDaeSet'] else 'documented-unset', source['soMarkFromDaeSet']); continue
        if name in fixed_false:
            require(val is False, 'UNSUPPORTED_VALUE', 'global', '', name, 'Only the documented inactive value is supported.')
        if name in enums:
            require(val in enums[name], 'UNSUPPORTED_VALUE', 'global', '', name)
        if name in durations:
            require(re.fullmatch(r'(?:0|(?:[0-9]+(?:\.[0-9]+)?(?:ns|us|µs|ms|s|m|h))+)', val) is not None, 'UNSUPPORTED_DURATION', 'global', '', name)
        if name in ('tproxyPort','pprofPort'):
            require(0 <= val <= 65535 and (name != 'tproxyPort' or val > 0), 'UNSUPPORTED_VALUE', 'global', '', name)
        if name in ('bandwidthMaxTx','bandwidthMaxRx'):
            require(val == '0', 'UNSUPPORTED_VALUE', 'global', '', name)
        if name in ('tlsFragmentLength','tlsFragmentInterval'):
            require(val == {'tlsFragmentLength':'50-100','tlsFragmentInterval':'10-20'}[name], 'UNSUPPORTED_VALUE', 'global', '', name)
        if name in ('bootstrapResolver','fallbackResolver'):
            # Avoid implicitly invoking a built-in public resolver when an empty value is ambiguous.
            require(re.fullmatch(r'(192\.0\.2|198\.51\.100|203\.0\.113)\.[0-9]{1,3}:[0-9]{1,5}', val) is not None, 'EXPLICIT_RESOLVER_REQUIRED', 'global', '', name)
            host, port = val.rsplit(':',1); document_ip(host)
            require(1 <= int(port) <= 65535, 'UNSUPPORTED_VALUE', 'global', '', name)
        if name in ('lanInterface','wanInterface'):
            require(all(re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,14}', x) for x in val) and len(set(val)) == len(val), 'UNSUPPORTED_INTERFACE', 'global', '', name)
            # Empty is represented as the documented empty interface default, never WAN auto.
            if not val:
                entry(key, [], 'documented-empty-interface-default', False); continue
        if name == 'tcpCheckUrl':
            require(val == ['http://probe.invalid'], 'UNSUPPORTED_VALUE', 'global', '', name, 'M1 permits only the explicit synthetic probe URL.')
        if name == 'udpCheckDns':
            require(val == ['192.0.2.53:53'], 'UNSUPPORTED_VALUE', 'global', '', name)
        entry(key, val)
    for key, value in [('disable_thp', False), ('auto_sniff_punt', False), ('bpf_conn_state_map_size', 262144)]:
        entry(key, value, 'documented-target-policy')
    return tuple(result)


def normalize(snapshot, source_kind='offline-snapshot', version=DAED_VERSION):
    require(version == DAED_VERSION, 'VERSION_MISMATCH', 'source', '', 'version')
    require(source_kind in ('offline-snapshot','graphql'), 'SOURCE_KIND_INVALID')
    source = normalize_source(snapshot)
    data = source['metadata']
    selected = {}
    for key in ('configs','dnss','routings'):
        require(len(data[key]) == 1 and data[key][0]['selected'] is True, 'SELECTION_UNSUPPORTED', key, '', 'selected', 'M1 requires exactly one selected profile and no extra profiles.')
        selected[key] = data[key][0]
    nodes = tuple(node_ir(n) for n in source['nodes'])
    node_by_id = {n.id: n for n in nodes}
    sub_ids = {s['id'] for s in data['subscriptions']}
    groups = []
    names = set()
    for raw in data['groups']:
        gid = raw['id']; name = text(raw['name'])
        require(name and name not in names | {'direct','block','must_direct','must_rules'}, 'NAME_CONFLICT', 'group', gid, 'name')
        names.add(name)
        require(raw['policy'] in ('min','random') and raw['policyParams'] == [], 'UNSUPPORTED_POLICY', 'group', gid, 'policy')
        unique(raw['nodes'], 'group-member')
        members = {x['id'] for x in raw['nodes']}
        bindings = []; seen_subs = set()
        for binding in raw['subscriptions']:
            sid = binding['subscription']['id']
            require(sid in sub_ids and sid not in seen_subs, 'REFERENCE_MISSING', 'group', gid, 'subscriptions')
            seen_subs.add(sid)
            require(binding['nameFilterRegex'] in (None, ''), 'UNSUPPORTED_FILTER', 'group', gid, 'subscriptions.nameFilterRegex', 'Regex subscription selection is outside M1.')
            ids = unique(binding['matchedNodes'], 'subscription-member')
            require(len(ids) == binding['matchedCount'], 'MEMBERSHIP_INVALID', 'group', gid, 'subscriptions.matchedCount')
            actual = {n.id for n in nodes if n.subscription_id == sid}
            require(ids == actual, 'NODE_OWNERSHIP_INVALID', 'group', gid, 'subscriptions.matchedNodes', 'Unfiltered subscription membership must exactly match its node partition.')
            members |= ids
            bindings.append({'subscriptionId': sid, 'members': sorted(ids), 'nameFilterRegex': binding['nameFilterRegex']})
        require(members, 'EMPTY_GROUP', 'group', gid, 'nodes')
        require(members <= set(node_by_id), 'REFERENCE_MISSING', 'group', gid, 'nodes')
        groups.append(Group(gid, name, alias('g', gid), raw['policy'], tuple(sorted(node_by_id[i].alias for i in members)), tuple(bindings)))
    by_name = {g.name: g.alias for g in groups}
    raw_route = selected['routings']
    route = Parser(raw_route['routing']['string'], 'routing', raw_route['id']).routing('route')
    targets = {r.outbound for r in route.rules} | {route.fallback}
    needed = targets - {'direct','block'}
    require(needed <= set(by_name), 'REFERENCE_MISSING', 'routing', raw_route['id'], 'outbound')
    require(len(raw_route['referenceGroups']) == len(set(raw_route['referenceGroups'])) and set(raw_route['referenceGroups']) in (needed,targets), 'REFERENCE_MISMATCH', 'routing', raw_route['id'], 'referenceGroups')
    route = Routing(tuple(Rule(r.match, by_name.get(r.outbound, r.outbound)) for r in route.rules), by_name.get(route.fallback, route.fallback))
    raw_dns = selected['dnss']
    dns = Parser(raw_dns['dns']['string'], 'dns', raw_dns['id']).dns()
    aliases = [n.alias for n in nodes] + [g.alias for g in groups]
    require(len(aliases) == len(set(aliases)), 'ALIAS_CONFLICT')
    fingerprint = digest(canonical(source))
    ir = IR(1, {'kind': source_kind, 'daedVersion': version, 'versionEvidence': 'caller-declared-pin-not-live-binary-attestation',
                'targetDaeVersion': 'v2.1.1', 'synthetic': True}, VERSION, fingerprint, nodes, tuple(groups),
            tuple(data['subscriptions']), dns, route, globals_ir(selected['configs']['global']),
            {key: {'id': v['id'], 'name': v['name'], 'selected': v['selected']} for key,v in selected.items()}, ())
    return source, ir
