"""Bounded LAN path and group witnesses; only the existing synthetic VM."""
import json
import subprocess
import time
from pathlib import Path

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import Matrix
from scripts.release_setup import need
from integration.ui_matrix.path_event_log import read as read_events


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def events():
    return read_events()


class Paths(Matrix):
    def __init__(self):
        super().__init__()
        self.path = Path('/evidence/path-continuation.json')
        self.results = []
        self.nodes = []
        self.group = self.config = self.routing = None
        self.original_routing = next(r for r in self.source['metadata']['routings'] if r['selected'])
        resume = Path('/evidence/path-completed-cases.json')
        if resume.exists():
            previous = json.loads(resume.read_text())
            need(previous['source'] == self.source, 'RESUME_SOURCE_BASELINE_CHANGED')
            for row in previous['rows']:
                need(row['result'] == 'RUNTIME_PASS' and row.get('baselineRestored') is True,
                     'RESUME_CASE_NOT_COMPLETE')
                need(row['id'] in {'group.fixed.0', 'group.fixed.1', 'group.random'},
                     'UNEXPECTED_RESUME_CASE')
                self.results.append(dict(row, preservedPriorEvidence=True))
            need(len({r['id'] for r in self.results}) == len(self.results), 'DUPLICATE_RESUME_CASE')

    def save(self):
        self.path.write_text(json.dumps(self.results, indent=2) + '\n')

    def setup(self):
        for port in (18082, 18083):
            link = f'http://synthetic-user:SyntheticOnly314159@127.0.0.1:{port}#matrix-{port}'
            response = self.api('mutation($a:[ImportArgument!]!){importNodes(rollbackError:true,args:$a){node{id} error}}',
                                {'a': [{'link': link}]})['importNodes'][0]
            need(not response['error'] and response['node'], 'FIXTURE_NODE_REJECTED')
            self.nodes.append(response['node']['id'])
        self.group = self.api('mutation{createGroup(name:"matrix_path",policy:fixed,policyParams:[{key:"",val:"0"}]){id}}')['createGroup']['id']
        self.api('mutation($id:ID!,$ids:[ID!]!){groupAddNodes(id:$id,nodeIDs:$ids)}', {'id': self.group, 'ids': list(reversed(self.nodes))})
        values = {k: v for k, v in self.original['global'].items() if k != 'soMarkFromDaeSet'}
        values.update(tcpCheckUrl=['http://198.51.100.2:18080/health'], tcpCheckHttpMethod='GET',
                      checkInterval='2s', checkTolerance='20ms', disableWaitingNetwork=True)
        self.config = self.api('mutation($g:globalInput!){createConfig(name:"Matrix path",global:$g){id}}', {'g': values})['createConfig']['id']
        self.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': self.config})
        self.routing = self.api('mutation{createRouting(name:"Matrix paths",routing:"fallback: matrix_path"){id}}')['createRouting']['id']
        self.api('mutation($id:ID!){selectRouting(id:$id)}', {'id': self.routing})
        self.fixture_source, _ = collect(self.reader)
        self.apply()

    def request(self, path, port=18080, blocked=False, host=None):
        before = len(events())
        command = ['ip', 'netns', 'exec', 'matrix-client', 'curl', '--noproxy', '*',
                                  '--max-time', '5', '--silent', '--show-error',
                                  f'http://198.51.100.2:{port}/{path}']
        if host: command.extend(['-H', 'Host: ' + host])
        process = subprocess.run(command, capture_output=True, text=True)
        time.sleep(0.1)
        evidence = events()[before:]
        matching = [e for e in evidence if e['kind'] == 'endpoint' and e['path'] == '/' + path]
        if blocked:
            need(process.returncode != 0 and not matching, 'BLOCK_RULE_DID_NOT_BLOCK')
        else:
            need(process.returncode == 0 and process.stdout == 'MATRIX_PATH_OK' and matching, 'LAN_PATH_FAILED')
        return {'curlRC': process.returncode, 'endpoint': matching,
                'proxy': [e for e in evidence if e['kind'] == 'proxy-request' and e['path'] == '/' + path]}

    def policy(self, policy, index=None):
        ident = 'group.' + policy + ('.' + str(index) if index is not None else '')
        if any(r['id'] == ident and r.get('preservedPriorEvidence') for r in self.results):
            print(ident + ': COMPLETE_EVIDENCE_REUSED', flush=True)
            return
        row = {'id': ident, 'result': None}
        self.results.append(row); self.save()
        try:
            params = [{'key': '', 'val': str(index)}] if index is not None else []
            self.api('mutation($id:ID!,$p:Policy!,$v:[PolicyParam!]){groupSetPolicy(id:$id,policy:$p,policyParams:$v)}',
                     {'id': self.group, 'p': policy, 'v': params})
            source, proof = collect(self.reader)
            group = next(g for g in source['metadata']['groups'] if g['id'] == self.group)
            need(group['policy'] == policy and group['policyParams'] == params, 'POLICY_READBACK_CHANGED')
            applied, candidate = self.apply()
            row.update(readback=group, doubleSnapshot=proof, candidate=candidate, applied=applied)
            observation_start = time.time()
            time.sleep(25 if policy in ('min', 'min_avg10', 'min_moving_avg') else 2)
            count = 16 if policy == 'random' else 3
            row['paths'] = [self.request(ident + '-' + str(i)) for i in range(count)]
            ports = {p['proxy'][-1]['proxy'] for p in row['paths'] if p['proxy']}
            need(len(ports) > 0 and ports <= {18082, 18083}, 'PROXY_ATTRIBUTION_MISSING')
            if policy == 'fixed':
                node_id = group['nodes'][index]['id']
                node = next(n for n in source['nodes'] if n['id'] == node_id)
                expected = int(node['link'].split('@')[1].split('#')[0].rsplit(':', 1)[1])
                need(ports == {expected}, 'FIXED_NODE_IDENTITY_MISMATCH')
            elif policy == 'random':
                need(ports == {18082, 18083}, 'RANDOM_PATH_DIVERSITY_NOT_OBSERVED')
            else:
                need(ports == {18082}, 'LATENCY_POLICY_DID_NOT_SELECT_FAST_NODE')
            row['healthRequests'] = [e for e in events() if e['time'] >= observation_start and e.get('path') == '/health']
            row['result'] = 'RUNTIME_PASS'
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(self.token, '[REDACTED]'))
        finally:
            self.api('mutation($id:ID!){groupSetPolicy(id:$id,policy:fixed,policyParams:[{key:"",val:"0"}])}', {'id': self.group})
            source, proof = collect(self.reader)
            need(source == self.fixture_source, 'POLICY_FIXTURE_NOT_RESTORED')
            restored, _ = self.apply()
            row.update(fixtureRestored=True, fixtureRestore=restored, fixtureProof=proof)
        self.save(); print(ident + ': ' + row['result'], flush=True)

    def route(self, ident, text, expected, host=None, dns_warmup=False):
        row = {'id': 'routing.' + ident, 'result': None}
        self.results.append(row); self.save()
        try:
            self.api('mutation($id:ID!,$r:String!){updateRouting(id:$id,routing:$r){id}}',
                     {'id': self.routing, 'r': text})
            source, proof = collect(self.reader)
            value = next(r for r in source['metadata']['routings'] if r['id'] == self.routing)
            need(value['routing']['string'] == text, 'ROUTING_READBACK_CHANGED')
            need(self.api('{general{dae{modified}}}')['general']['dae']['modified'] is
                 (text != 'fallback: matrix_path'), 'MODIFIED_STATE_MISMATCH')
            applied, candidate = self.apply()
            row.update(readback=value, doubleSnapshot=proof, applied=applied, candidate=candidate)
            if dns_warmup:
                from dnslib import DNSRecord, QTYPE
                answer = DNSRecord.parse(DNSRecord.question('path.matrix.invalid').send(
                    '127.0.0.1', 5353, timeout=10))
                row['dnsWarmup'] = {'rcode': answer.header.rcode,
                                    'addresses': [str(r.rdata) for r in answer.rr if r.rtype == QTYPE.A]}
                self.save()
                need(row['dnsWarmup'] == {'rcode': 0, 'addresses': ['198.51.100.2']},
                     'DOMAIN_ROUTING_DNS_PRECONDITION_FAILED')
            row['path'] = self.request('routing-' + ident, blocked=expected == 'block', host=host)
            if expected == 'proxy': need(bool(row['path']['proxy']), 'EXPECTED_PROXY_NOT_OBSERVED')
            else: need(not row['path']['proxy'], 'UNEXPECTED_PROXY_PATH')
            row['result'] = 'RUNTIME_PASS'
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(self.token, '[REDACTED]'))
        finally:
            self.api('mutation($id:ID!){updateRouting(id:$id,routing:"fallback: matrix_path"){id}}', {'id': self.routing})
            source, proof = collect(self.reader)
            need(source == self.fixture_source, 'ROUTING_FIXTURE_NOT_RESTORED')
            restored, _ = self.apply()
            row.update(fixtureRestored=True, fixtureProof=proof, fixtureRestore=restored)
            self.save()
        print(row['id'] + ': ' + row['result'], flush=True)

    def latency(self):
        row = {'id': 'node.manual-all-latency', 'result': None}
        self.results.append(row); self.save()
        try:
            before = len(events())
            values = self.api('mutation{testNodeLatencies{id latencyMs alive testedAt message}}')['testNodeLatencies']
            observed = self.api('{nodeLatencies{id latencyMs alive testedAt message}}')['nodeLatencies']
            selected = [value for value in values if value['id'] in self.nodes]
            row.update(response=values, readback=observed, endpointEvents=events()[before:])
            need({value['id'] for value in selected} == set(self.nodes), 'LATENCY_NODE_IDENTITY_MISSING')
            need(all(value['alive'] is True and type(value['latencyMs']) in (int, float)
                     and value['latencyMs'] > 0 and value['testedAt'] for value in selected),
                 'LATENCY_NOT_REAL_NONEMPTY_RESULT')
            need(all(value in observed for value in selected), 'LATENCY_READBACK_CHANGED')
            need(any(event['kind'] == 'proxy-request' for event in row['endpointEvents']),
                 'LATENCY_PROXY_PROBE_NOT_OBSERVED')
            row.update(result='RUNTIME_PASS', scope='ACTUAL_API_PROBE_AND_READBACK_NOT_BROWSER_DISPLAY')
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(self.token, '[REDACTED]'))
        source, _ = collect(self.reader)
        need(source == self.fixture_source, 'LATENCY_CHANGED_CONFIGURATION')
        self.save(); print(row['id'] + ': ' + row['result'], flush=True)

    def restore(self):
        self.api('mutation($id:ID!){selectRouting(id:$id)}', {'id': self.original_routing['id']})
        self.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': self.original['id']})
        for kind, ident in [('Routing', self.routing), ('Config', self.config), ('Group', self.group)]:
            if ident: self.api('mutation($id:ID!){remove' + kind + '(id:$id)}', {'id': ident})
        if self.nodes: self.api('mutation($ids:[ID!]!){removeNodes(ids:$ids)}', {'ids': self.nodes})
        source, proof = collect(self.reader)
        need(source == self.source, 'PATH_BASELINE_NOT_RESTORED')
        applied, _ = self.apply()
        for row in self.results:
            if row.get('preservedPriorEvidence'):
                continue
            row.update(baselineRestored=True, baselineRestore=applied, baselineProof=proof)
        self.save()


def main(repair=False, udp_health_only=False, long_sniff_only=False):
    need(Path('/evidence/nodes-complete').is_file(), 'PREVIOUS_BATCH_INCOMPLETE')
    need(Path('/evidence/path-fixture-ready').is_file(), 'PATH_FIXTURE_NOT_READY')
    output = Path('/evidence/long-sniff-witness.json' if long_sniff_only else '/evidence/udp-health-witness.json' if udp_health_only else '/evidence/path-witness-repair.json' if repair else '/evidence/path-continuation.json')
    need(not output.exists(), 'EXISTING_PATH_EVIDENCE_DO_NOT_RERUN')
    matrix = Paths()
    if long_sniff_only:
        prior = json.loads(Path('/evidence/path-continuation.json').read_text())
        original = next(r for r in prior if r['id'] == 'global.dial-sniff.long-sniff')
        need(original.get('reason') == 'DIAL_CONFIG_CHANGED' and original.get('baselineRestored'),
             'LONG_SNIFF_NOT_AN_INCOMPLETE_DURATION_FIXTURE')
        matrix.results = []; matrix.path = output
        try:
            matrix.setup()
            from integration.ui_matrix.path_dial_controls import run as dial_controls
            dial_controls(matrix, pending={'global.dial-sniff.long-sniff'})
        finally:
            matrix.restore()
        return
    if udp_health_only:
        prior = json.loads(Path('/evidence/path-continuation.json').read_text())
        need(all(row.get('baselineRestored') is True for row in prior), 'PREVIOUS_BASELINE_NOT_RESTORED')
        need(any(row.get('reason') == 'ACTUAL_UDP_HEALTH_PROBE_MISSING' for row in prior), 'UDP_WITNESS_NOT_INCOMPLETE')
        matrix.results = []; matrix.path = output
        try:
            matrix.setup()
            from integration.ui_matrix.path_bandwidth_controls import run as bandwidth_controls
            bandwidth_controls(matrix, udp_health_only=True)
        finally:
            matrix.restore()
        return
    if repair:
        prior = json.loads(Path('/evidence/path-continuation.json').read_text())
        need(all(row.get('baselineRestored') is True for row in prior), 'PREVIOUS_BASELINE_NOT_RESTORED')
        pending = {row['id'] for row in prior if row['result'] == 'FAIL' and
                   ((row['id'].startswith('global.dial-sniff.') and row.get('reason') == 'DIAL_REQUEST_FAILED') or
                    (row['id'] == 'routing.domain-proxy' and row.get('reason') == 'LAN_PATH_FAILED'))}
        need(pending, 'NO_INCOMPLETE_WITNESS_TO_REPAIR')
        matrix.results = []
        matrix.path = output
        try:
            matrix.setup()
            from integration.ui_matrix.path_dial_controls import run as dial_controls
            dial_controls(matrix, pending=pending)
        finally:
            matrix.restore()
        return
    try:
        matrix.setup()
        for policy, index in [('fixed', 0), ('fixed', 1), ('random', None), ('min', None),
                              ('min_moving_avg', None), ('min_avg10', None)]:
            matrix.policy(policy, index)
        from integration.ui_matrix.path_membership_controls import run as membership_controls
        membership_controls(matrix)
        matrix.latency()
        for ident, text, expected, host in [
            ('direct-fallback', 'fallback: direct', 'direct', None),
            ('must-direct-fallback', 'fallback: must_direct', 'direct', None),
            ('block-fallback', 'fallback: block', 'block', None),
            ('proxy-fallback', 'fallback: matrix_path', 'proxy', None),
            ('cidr-direct', "dip('198.51.100.2/32') -> direct\nfallback: block", 'direct', None),
            ('port-protocol-proxy', 'l4proto(tcp) && dport(18080) -> matrix_path\nfallback: block', 'proxy', None),
            ('domain-proxy', "domain(full: 'path.matrix.invalid') -> matrix_path\nfallback: block", 'proxy', 'path.matrix.invalid'),
            ('order-direct-before-block', "dip('198.51.100.2/32') -> direct\ndip('198.51.100.0/24') -> block\nfallback: block", 'direct', None),
            ('order-block-before-direct', "dip('198.51.100.2/32') -> block\ndip('198.51.100.0/24') -> direct\nfallback: direct", 'block', None),
        ]:
            matrix.route(ident, text, expected, host)
        from integration.ui_matrix.path_dial_controls import run as dial_controls
        dial_controls(matrix)
        from integration.ui_matrix.path_tolerance_controls import run as tolerance_controls
        tolerance_controls(matrix)
        from integration.ui_matrix.path_bandwidth_controls import run as bandwidth_controls
        bandwidth_controls(matrix)
    finally:
        matrix.restore()


if __name__ == '__main__':
    import sys
    need(sys.argv[1:] in ([], ['--repair-incomplete-witnesses'], ['--udp-health-only'], ['--long-sniff-only']), 'INVALID_TEST_ARGUMENTS')
    main(repair='--repair-incomplete-witnesses' in sys.argv, udp_health_only='--udp-health-only' in sys.argv, long_sniff_only='--long-sniff-only' in sys.argv)
