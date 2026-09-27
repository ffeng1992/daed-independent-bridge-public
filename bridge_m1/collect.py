"""Fixed read-only operations, bounded HTTP and complete-snapshot comparison."""
import copy
import http.client
import ipaddress
import socket
import time
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .common import ROOT, canonical, digest, load_json, require, fail, Rejected

QUERIES = {name: (ROOT / 'contracts/queries' / filename).read_text() for name, filename in
           [('SnapshotMetadata', 'snapshot.graphql'), ('NodePage', 'nodes.graphql'), ('GlobalCapabilities', 'capabilities.graphql')]}
EXPECTED_GLOBAL = {f['graphql'] for f in load_json((ROOT / 'contracts/global-fields.json').read_bytes())['fields']}
SCHEMA = Draft202012Validator(load_json((ROOT / 'contracts/snapshot.schema.json').read_bytes()))
MAX_BYTES = 8 * 1024 * 1024


def envelope(value):
    require(isinstance(value, dict), 'FORMAT_ERROR')
    if value.get('errors'):
        # Never copy upstream messages, which can contain tokens or URI values.
        fail('UPSTREAM_GRAPHQL_ERROR', message='GraphQL returned errors; partial data is discarded.')
    require(set(value) == {'data'} and isinstance(value['data'], dict), 'FORMAT_ERROR')
    return value['data']


class HTTPReader:
    """No proxies/redirects/DNS hostnames; explicit literal loopback laboratory only."""
    def __init__(self, endpoint, token, timeout=10):
        try:
            u = urlsplit(endpoint)
            addr = ipaddress.ip_address(u.hostname or '')
            valid = addr.is_loopback and u.scheme == 'http' and u.path == '/graphql' and not (u.query or u.fragment or u.username or u.password)
            port = u.port
        except ValueError:
            valid = False
        require(valid and port is not None, 'ENDPOINT_REJECTED', 'transport', '', 'endpoint', 'Explicit HTTP loopback literal /graphql endpoint and port required.')
        require(isinstance(token, str) and token and '\n' not in token and '\r' not in token, 'AUTH_FAILED')
        require(0 < timeout <= 10, 'LIMIT_INVALID')
        self.host, self.port, self.token, self.timeout = str(addr), port, token, timeout

    def __call__(self, operation, variables):
        require(operation in QUERIES, 'QUERY_REJECTED')
        payload = canonical({'operationName': operation, 'query': QUERIES[operation], 'variables': variables})
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        deadline = time.monotonic() + self.timeout
        try:
            conn.request('POST', '/graphql', body=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
            response = conn.getresponse()
            if response.status in (401, 403):
                fail('AUTH_FAILED', 'transport', '', 'authorization', 'Authentication was rejected.')
            require(response.status == 200, 'HTTP_ERROR')
            require(response.getheader('Content-Type', '').split(';')[0].strip() == 'application/json', 'FORMAT_ERROR')
            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'TIMEOUT')
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                require(len(body) <= MAX_BYTES, 'RESPONSE_TOO_LARGE')
            result = load_json(body)
            envelope(result)
            return result
        except (TimeoutError, socket.timeout):
            fail('TIMEOUT', 'transport', '', '$', 'GraphQL read timed out.')
        except (OSError, http.client.HTTPException):
            fail('TRANSPORT_ERROR', 'transport', '', '$', 'GraphQL transport failed.')
        finally:
            conn.close()


def unique(items, kind):
    require(isinstance(items, list), 'FORMAT_ERROR', kind)
    seen = set()
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get('id'), str) and 0 < len(item['id']) <= 256, 'FORMAT_ERROR', kind)
        require(item['id'] not in seen, 'ID_CONFLICT', kind, item['id'], 'id', 'Duplicate object ID.')
        seen.add(item['id'])
    return seen


def validate_snapshot(snapshot):
    # Fixed path diagnostic avoids leaking malicious property names and values.
    errors = list(SCHEMA.iter_errors(snapshot))
    if errors:
        error = errors[0]
        path = '.'.join(str(x) for x in error.absolute_path) or '$'
        fail('UNSUPPORTED_FIELD' if error.validator == 'additionalProperties' else 'FORMAT_ERROR', 'snapshot', '', path, 'Snapshot shape has unknown, missing or invalid fields.')
    require(snapshot['synthetic'] is True, 'SYNTHETIC_ONLY')
    data = snapshot['metadata']['data']
    for kind in ('configs', 'dnss', 'routings', 'groups', 'subscriptions'):
        unique(data[kind], kind)
    expected = {None} | {s['id'] for s in data['subscriptions']}
    partitions = {}
    for page in snapshot['nodePages']:
        sid = page['subscriptionId']
        require(sid in expected, 'NODE_OWNERSHIP_INVALID', 'subscription', sid)
        partitions.setdefault(sid, []).append(envelope(page['response'])['nodes'])
    require(set(partitions) == expected, 'PAGE_MISSING', message='A node partition is missing.')
    all_ids = set()
    flattened = []
    for sid, pages in partitions.items():
        total, count, cursors, previous = None, 0, set(), None
        for index, page in enumerate(pages):
            require(index < 50, 'PAGE_LIMIT')
            if total is None:
                total = page['totalCount']
            require(total == page['totalCount'], 'SOURCE_CHANGED')
            require(total <= 10000, 'NODE_LIMIT')
            edges, info = page['edges'], page['pageInfo']
            ids = unique(edges, 'node')
            require(not ids & all_ids, 'ID_CONFLICT', 'node', '', 'id', 'Duplicate node ID across pages or partitions.')
            all_ids |= ids
            count += len(edges)
            require(len(edges) <= 200 and count <= total, 'PAGINATION_INVALID')
            require(bool(edges) or (index == 0 and total == 0 and len(pages) == 1), 'PAGE_MISSING')
            if edges:
                require(info['startCursor'] == edges[0]['id'] and info['endCursor'] == edges[-1]['id'], 'CURSOR_INVALID')
                require(info['endCursor'] not in cursors and info['endCursor'] != previous, 'CURSOR_LOOP')
                cursors.add(info['endCursor'])
                previous = info['endCursor']
            else:
                require(info['startCursor'] is None and info['endCursor'] is None, 'CURSOR_INVALID')
            require(info['hasNextPage'] == (index < len(pages) - 1), 'PAGE_MISSING')
            for node in edges:
                require(node['subscriptionID'] == sid, 'NODE_OWNERSHIP_INVALID', 'node', node['id'], 'subscriptionID')
            flattened.extend(edges)
        require(count == total, 'PAGE_MISSING', 'subscription', sid, 'nodes', 'Node count does not match totalCount.')
    return data, flattened


def normalize_source(snapshot):
    """Page transport boundaries are discarded only after completeness validation."""
    data, nodes = validate_snapshot(snapshot)
    data = copy.deepcopy(data)
    for key, objects in data.items():
        data[key] = sorted(objects, key=lambda obj: obj['id'])
    # Membership order is irrelevant ONLY for supported min/random. fixed is rejected later.
    for group in data['groups']:
        for key in ('nodes', 'subscriptions'):
            group[key].sort(key=lambda x: x['id'] if key == 'nodes' else x['subscription']['id'])
        for binding in group['subscriptions']:
            binding['matchedNodes'].sort(key=lambda x: x['id'])
    return {'schemaVersion': 1, 'synthetic': True, 'metadata': data, 'nodes': sorted(copy.deepcopy(nodes), key=lambda n: n['id'])}


def collect(reader, attempts=3, page_size=200, budget=60):
    require(1 <= attempts <= 3 and 1 <= page_size <= 200 and 0 < budget <= 60, 'LIMIT_INVALID')
    start = time.monotonic()
    def request(operation, variables):
        require(time.monotonic() - start < budget, 'TIMEOUT')
        result = reader(operation, variables)
        require(time.monotonic() - start < budget, 'TIMEOUT')
        return envelope(result)
    def once():
        caps = request('GlobalCapabilities', {})
        require(set(caps) == {'__type'} and isinstance(caps['__type'], dict) and set(caps['__type']) == {'fields'}, 'SCHEMA_DRIFT')
        fs = caps['__type'].get('fields')
        require(isinstance(fs, list) and all(isinstance(x, dict) and set(x) == {'name'} and isinstance(x['name'], str) for x in fs), 'SCHEMA_DRIFT')
        require(len(fs) == len(EXPECTED_GLOBAL) and {x['name'] for x in fs} == EXPECTED_GLOBAL, 'SCHEMA_DRIFT')
        metadata = request('SnapshotMetadata', {})
        require(isinstance(metadata.get('subscriptions'), list), 'FORMAT_ERROR')
        unique(metadata['subscriptions'], 'subscription')
        pages = []
        for sid in [None] + sorted(s['id'] for s in metadata['subscriptions']):
            after, cursors = None, set()
            for _ in range(50):
                response = request('NodePage', {'subscriptionId': sid, 'first': page_size, 'after': after})
                require(set(response) == {'nodes'} and isinstance(response['nodes'], dict), 'FORMAT_ERROR')
                page = response['nodes']
                require(isinstance(page.get('pageInfo'), dict) and type(page['pageInfo'].get('hasNextPage')) is bool, 'FORMAT_ERROR')
                pages.append({'subscriptionId': sid, 'response': {'data': response}})
                if not page['pageInfo']['hasNextPage']:
                    break
                end = page['pageInfo'].get('endCursor')
                require(isinstance(end, str) and end and end not in cursors and end != after, 'CURSOR_LOOP')
                cursors.add(end)
                after = end
            else:
                fail('PAGE_LIMIT')
        snap = {'schemaVersion': 1, 'synthetic': True, 'consistency': {'stable': False, 'transactional': False},
                'metadata': {'data': metadata}, 'nodePages': pages}
        normalize_source(snap)
        return snap
    for attempt in range(attempts):
        try:
            before, after = once(), once()
        except Rejected as exc:
            if exc.diagnostic['reasonCode'] == 'SOURCE_CHANGED':
                continue
            raise
        left, right = digest(canonical(normalize_source(before))), digest(canonical(normalize_source(after)))
        if left == right:
            after['consistency']['stable'] = True
            return after, {'method': 'two-complete-normalized-fingerprints', 'attempts': attempt + 1,
                           'beforeSha256': left, 'afterSha256': right, 'transactional': False}
    fail('SOURCE_CHANGED', message='Complete source snapshots kept changing; no candidate was generated.')
