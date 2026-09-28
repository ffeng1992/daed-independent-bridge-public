"""Remaining dial/sniff controls using the existing reserved-address fixture."""
import subprocess
import time
from urllib.parse import urlsplit

from dnslib import A, QTYPE, RR
from dnslib.server import BaseResolver, DNSLogger, DNSServer

from bridge_m4.collect import collect
from bridge_m4.convert import FIELDS
from integration.ui_matrix.continue_global import candidate_value
from integration.ui_matrix.continue_paths import events
from integration.ui_matrix.path_fixture import client_hello_program
from scripts.release_setup import need


def target_authority(raw):
    # HTTP absolute-form and CONNECT express the same destination differently.
    # Keep the raw observed event, compare only its actual host and port.
    if raw.startswith('http://'):
        parsed = urlsplit(raw)
        need(parsed.hostname and not parsed.username and not parsed.password,
             'INVALID_OBSERVED_PROXY_TARGET')
        return parsed.hostname + ':' + str(parsed.port or 80)
    return raw


def run(matrix, pending=None):
    requests = []

    class Resolver(BaseResolver):
        def resolve(self, request, handler):
            requests.append({'at': time.time(), 'name': str(request.q.qname),
                             'type': QTYPE[request.q.qtype], 'transport': handler.protocol})
            response = request.reply()
            if str(request.q.qname) == 'path.matrix.invalid.' and request.q.qtype == QTYPE.A:
                response.add_answer(RR(request.q.qname, QTYPE.A, rdata=A('198.51.100.2'), ttl=60))
            return response

    servers = [DNSServer(Resolver(), address='127.0.0.1', port=15358, tcp=tcp,
                        logger=DNSLogger(log='-request,-reply,-truncated,-error'))
               for tcp in (False, True)]
    for server in servers:
        server.start_thread()
    profile = None
    try:
        if pending is not None and 'routing.domain-proxy' in pending:
            original_dns = next(d for d in matrix.fixture_source['metadata']['dnss'] if d['selected'])
            fixture_before = matrix.fixture_source
            dns_id = None
            try:
                dns_text = ('bind: "tcp+udp://127.0.0.1:5353"\n'
                            'upstream { witness: "udp://127.0.0.1:15358" }\n'
                            'routing { request { fallback: witness } response { fallback: accept } }')
                dns_id = matrix.api('mutation($d:String!){createDns(name:"Matrix domain witness",dns:$d){id}}',
                                    {'d': dns_text})['createDns']['id']
                matrix.api('mutation($id:ID!){selectDns(id:$id)}', {'id': dns_id})
                matrix.fixture_source, _ = collect(matrix.reader)
                matrix.route('domain-proxy', "domain(full: 'path.matrix.invalid') -> matrix_path\nfallback: block",
                             'proxy', 'path.matrix.invalid:18080', dns_warmup=True)
            finally:
                matrix.api('mutation($id:ID!){selectDns(id:$id)}', {'id': original_dns['id']})
                if dns_id:
                    matrix.api('mutation($id:ID!){removeDns(id:$id)}', {'id': dns_id})
                matrix.fixture_source = fixture_before
                restored, _ = collect(matrix.reader)
                need(restored == fixture_before, 'DOMAIN_DNS_FIXTURE_NOT_RESTORED')
                matrix.apply()
        for name, mode, timeout, delay, expected in [
                ('ip', 'ip', '800ms', 0, '198.51.100.2:18080'),
                ('domain', 'domain', '800ms', 0, 'path.matrix.invalid:18080'),
                ('domain-plus', 'domain+', '800ms', 0, 'path.matrix.invalid:18080'),
                ('domain-double-plus', 'domain++', '800ms', 0, 'path.matrix.invalid:18080'),
                ('short-sniff', 'domain+', '30ms', .3, '198.51.100.2:18080'),
                ('long-sniff', 'domain+', '1.5s', .3, 'path.matrix.invalid:18080')]:
            if pending is not None and 'global.dial-sniff.' + name not in pending:
                continue
            row = {'id': 'global.dial-sniff.' + name, 'result': None}
            matrix.results.append(row); matrix.save()
            try:
                selected = next(c for c in matrix.fixture_source['metadata']['configs'] if c['selected'])
                values = {k: v for k, v in selected['global'].items() if k != 'soMarkFromDaeSet'}
                changes = {'dialMode': mode, 'sniffingTimeout': timeout,
                           'bootstrapResolver': '127.0.0.1:15358'}
                values.update(changes)
                profile = matrix.api('mutation($g:globalInput!){createConfig(name:"Matrix dial witness",global:$g){id}}',
                                     {'g': values})['createConfig']['id']
                matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': profile})
                source, proof = collect(matrix.reader)
                actual = next(c['global'] for c in source['metadata']['configs'] if c['id'] == profile)
                need(all(actual[k] == v for k, v in changes.items()), 'DIAL_CONFIG_CHANGED')
                need(matrix.api('{general{dae{modified}}}')['general']['dae']['modified'] is True,
                     'MODIFIED_NOT_SET')
                applied, candidate = matrix.apply()
                for key, value in changes.items():
                    candidate_value(candidate, next(f['dae'] for f in FIELDS if f['graphql'] == key), value)
                row.update(readback=actual, doubleSnapshot=proof, applied=applied, candidate=candidate)
                observations = []
                # Domain mode warms unknown domains asynchronously. Bound the
                # follow-up requests; do not change resolver/target on failure.
                for attempt in range(4 if mode == 'domain' else 1):
                    before = len(events())
                    # Plain HTTP's Host can replace the outbound proxy URI's
                    # authority, independently of DAE's chosen dial address.
                    # A real ClientHello instead triggers CONNECT. Observe the
                    # selected target and actual TCP connection at the existing
                    # fixture; do not claim a TLS handshake with the HTTP sink.
                    program = client_hello_program(delay)
                    process = subprocess.run(['ip', 'netns', 'exec', 'matrix-client', 'python3', '-c', program],
                                             capture_output=True, text=True, timeout=12)
                    time.sleep(1)
                    observed = events()[before:]
                    proxied = [e for e in observed if e['kind'] == 'proxy-upstream-connected'
                               and e.get('method') == 'CONNECT']
                    observation = {'rc': process.returncode, 'events': observed,
                                   'stdout': process.stdout, 'stderr': process.stderr}
                    observations.append(observation)
                    row['observations'] = observations
                    matrix.save()
                    need(process.returncode == 0 and len(proxied) == 1, 'DIAL_REQUEST_FAILED')
                    observed_target = target_authority(proxied[0]['target'])
                    observation['targetAuthority'] = observed_target
                    if observed_target == expected:
                        break
                    time.sleep(2)
                row.update(observations=observations, bootstrapRequests=list(requests))
                need(observed_target == expected, 'DIAL_TARGET_OR_SNIFF_DEADLINE_MISMATCH')
                row.update(result='RUNTIME_PASS', scope='Actual CONNECT target, connected TCP fixture and delayed ClientHello sniffing; no TLS server handshake or reroute-policy equivalence claim')
            except Exception as exc:
                row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]'))
            finally:
                matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': matrix.config})
                if profile:
                    matrix.api('mutation($id:ID!){removeConfig(id:$id)}', {'id': profile}); profile = None
                restored, proof = collect(matrix.reader)
                need(restored == matrix.fixture_source, 'DIAL_FIXTURE_NOT_RESTORED')
                applied, _ = matrix.apply()
                row.update(fixtureRestored=True, fixtureProof=proof, fixtureRestore=applied)
                matrix.save()
            print(row['id'] + ': ' + row['result'], flush=True)
    finally:
        for server in servers:
            server.stop()
