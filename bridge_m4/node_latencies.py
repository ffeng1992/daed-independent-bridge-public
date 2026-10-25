"""Bounded, in-memory results of official per-node measurements, never estimates.

The official all-node query refreshes before filtering. Never call it here.
A timed-out official call may survive client disconnect: open the circuit until
management restart instead of submitting further unknowable upstream work.
"""
import datetime
import hashlib
import json
import re
import threading
import time


class ProbeError(Exception):
    pass


class NodeLatencies:
    TTL = 600
    INTERVAL = 30
    COOLDOWN = 120
    BATCH = 2
    PROBE_TIMEOUT = 12
    INVENTORY_BUDGET = 2

    def __init__(self, transport, *, clock=time.monotonic, wall=time.time):
        self.transport, self.clock, self.wall = transport, clock, wall
        self.lock = threading.Lock()
        self.records, self.identities = {}, {}
        self.owner = None
        self.busy = False
        self.next_refresh = 0
        self.failures = 0
        self.circuit_open = False
        self.error = None
        self.attempts = 0

    def call(self, query, variables, authorization, timeout):
        raw = json.dumps({'query': query, 'variables': variables}).encode()
        result = json.loads(self.transport(raw, authorization, timeout))
        if result.get('errors'):
            # Upstream messages/variables may contain credentials; retain a hash,
            # never echo them into logs or a GraphQL toast.
            digest = hashlib.sha256(json.dumps(result['errors'], sort_keys=True).encode()).hexdigest()
            raise ProbeError('OFFICIAL_GRAPHQL_ERROR_' + digest)
        return result['data']

    def inventory(self, authorization):
        deadline = self.clock() + self.INVENTORY_BUDGET
        def call(query, variables=None):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise TimeoutError('NODE_INVENTORY_TIMEOUT')
            return self.call(query, variables or {}, authorization, remaining)
        metadata = call('{subscriptions{id} groups{nodes{id} subscriptions{matchedNodes{id}}}}')
        subscriptions = metadata['subscriptions']
        priority = []
        for group in metadata['groups']:
            priority.extend(n['id'] for n in group['nodes'])
            for binding in group['subscriptions']:
                priority.extend(n['id'] for n in binding['matchedNodes'])
        if not isinstance(subscriptions, list) or len(subscriptions) > 100:
            raise ProbeError('NODE_INVENTORY_SCHEMA')
        identities = {}
        for sid in [None] + sorted(s['id'] for s in subscriptions):
            after = None
            seen = set()
            total = None
            count = 0
            for _ in range(200):
                data = call('query($sid:ID,$after:ID){nodes(subscriptionId:$sid,first:100,after:$after){totalCount edges{id link subscriptionID} pageInfo{endCursor hasNextPage}}}', {'sid': sid, 'after': after})['nodes']
                if total is None:
                    total = data['totalCount']
                if type(total) is not int or not 0 <= total <= 10000 or data['totalCount'] != total:
                    raise ProbeError('NODE_INVENTORY_CHANGED')
                rows = data['edges']
                if not isinstance(rows, list) or not rows and total:
                    raise ProbeError('NODE_INVENTORY_PAGE')
                for row in rows:
                    ident = row['id']
                    if type(ident) is not str or not ident or ident in identities or row['subscriptionID'] != sid or type(row['link']) is not str:
                        raise ProbeError('NODE_INVENTORY_IDENTITY')
                    identities[ident] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                if len(identities) > 10000:
                    raise ProbeError('NODE_INVENTORY_LIMIT')
                count += len(rows)
                info = data['pageInfo']
                if type(info['hasNextPage']) is not bool:
                    raise ProbeError('NODE_INVENTORY_SCHEMA')
                if not info['hasNextPage']:
                    if count != total:
                        raise ProbeError('NODE_INVENTORY_PAGE')
                    break
                after = info['endCursor']
                if not rows or after != rows[-1]['id'] or after in seen:
                    raise ProbeError('NODE_INVENTORY_CURSOR')
                seen.add(after)
            else:
                raise ProbeError('NODE_INVENTORY_LIMIT')
        order = list(dict.fromkeys(priority + sorted(identities)))
        return {k: identities[k] for k in order if k in identities}

    def remember_manual(self, authorization, principal, before, rows):
        """Reuse completed official measurements only for unchanged identities.

        No probe or fabricated result is produced here. Partial selections are
        not cacheable; the original mutation response remains untouched.
        """
        after = self.inventory(authorization)
        if after != before:
            raise ProbeError('NODE_INVENTORY_CHANGED')
        selected = {r['id']: before[r['id']] for r in rows if type(r) is dict and r.get('id') in before}
        checked = self.validate_rows(rows, selected)
        owner = hashlib.sha256(principal.encode()).hexdigest()
        with self.lock:
            if self.owner != owner:
                self.records.clear()
            self.owner, self.identities = owner, after
            for ident, row, stamp in checked:
                self.records[ident] = (after[ident], row, self.clock(), stamp)
            self.next_refresh = max(self.next_refresh, self.clock() + self.INTERVAL)

    def read(self, authorization, principal, ids=None):
        try:
            identities = self.inventory(authorization)
        except Exception as exc:
            return [], {'state': 'unavailable', 'reason': 'NODE_INVENTORY_' + type(exc).__name__, 'cachedResults': 0}
        owner = hashlib.sha256(principal.encode()).hexdigest()
        with self.lock:
            if self.owner != owner:
                self.records.clear()
                self.owner = owner
            self.identities = identities
            self.records = {k: v for k, v in self.records.items()
                            if identities.get(k) == v[0] and self.clock() - v[2] < self.TTL
                            and 0 <= self.wall() - v[3] < self.TTL}
            selected = set(ids) if ids is not None else set(identities)
            rows = [dict(self.records[k][1]) for k in sorted(self.records) if k in selected]
            if identities and not self.busy and not self.circuit_open and self.clock() >= self.next_refresh:
                order = list(identities)
                # Prefer unmeasured/oldest nodes, preserving a bounded batch.
                order.sort(key=lambda k: self.records.get(k, (None, None, -1))[2])
                batch = order[:self.BATCH]
                self.busy = True
                self.attempts += 1
                threading.Thread(target=self.refresh, args=(authorization, owner, {k: identities[k] for k in batch}), daemon=True, name='official-node-latency').start()
            return rows, self.status_locked()

    def status_locked(self):
        return {'state': 'unavailable' if self.circuit_open or self.error else ('refreshing' if self.busy else 'ready'),
                'reason': self.error, 'inFlight': int(self.busy), 'attempts': self.attempts,
                'circuitOpen': self.circuit_open, 'cachedResults': len(self.records),
                'maxAgeSeconds': self.TTL, 'source': 'official-testNodeLatencies'}

    def refresh(self, authorization, owner, identities):
        try:
            rows = self.call('mutation($ids:[ID!]!){testNodeLatencies(ids:$ids){id latencyMs alive testedAt message}}', {'ids': list(identities)}, authorization, self.PROBE_TIMEOUT)['testNodeLatencies']
            checked = self.validate_rows(rows, identities)
            with self.lock:
                if self.owner == owner:
                    for ident, row, stamp in checked:
                        if self.identities.get(ident) == identities[ident]:
                            self.records[ident] = (identities[ident], row, self.clock(), stamp)
                    self.error = None
                    self.failures = 0
                    self.next_refresh = self.clock() + self.INTERVAL
        except Exception as exc:
            with self.lock:
                self.failures += 1
                self.error = str(exc) if isinstance(exc, ProbeError) else type(exc).__name__
                # Any transport exception leaves upstream completion uncertain.
                # A known completed GraphQL/schema rejection gets one cooled retry.
                self.circuit_open = not isinstance(exc, ProbeError) or self.failures >= 2
                self.next_refresh = self.clock() + self.COOLDOWN
                print(json.dumps({'component': 'official-node-latencies', 'state': 'unavailable', 'reason': self.error,
                                  'circuitOpen': self.circuit_open, 'attempts': self.attempts}), flush=True)
        finally:
            with self.lock:
                self.busy = False

    def validate_rows(self, rows, identities):
        if not isinstance(rows, list):
            raise ProbeError('OFFICIAL_LATENCY_SCHEMA')
        checked, seen = [], set()
        for row in rows:
            if type(row) is not dict or set(row) != {'id', 'latencyMs', 'alive', 'testedAt', 'message'}:
                raise ProbeError('OFFICIAL_LATENCY_SCHEMA')
            ident = row['id']
            if ident not in identities or ident in seen or type(row['alive']) is not bool or (row['latencyMs'] is not None and (type(row['latencyMs']) is not int or row['latencyMs'] < 0)):
                raise ProbeError('OFFICIAL_LATENCY_SCHEMA')
            if type(row['testedAt']) is not str or (row['message'] is not None and type(row['message']) is not str):
                raise ProbeError('OFFICIAL_LATENCY_SCHEMA')
            try:
                dt = datetime.datetime.fromisoformat(row['testedAt'].replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    raise ValueError()
                stamp = dt.timestamp()
            except ValueError:
                raise ProbeError('OFFICIAL_LATENCY_TIMESTAMP') from None
            if not 0 <= self.wall() - stamp < self.TTL:
                raise ProbeError('OFFICIAL_LATENCY_STALE')
            safe = dict(row)
            if safe['message']:
                safe['message'] = re.sub(r'\S+://\S+', '[redacted URL]', safe['message'])
            checked.append((ident, safe, stamp)); seen.add(ident)
        if seen != set(identities):
            raise ProbeError('OFFICIAL_LATENCY_INCOMPLETE')
        return checked
