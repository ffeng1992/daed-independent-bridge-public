"""Actual Hysteria2 bandwidth/UDP probes, using an unmodified test server."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from dnslib import A, QTYPE, RR
from dnslib.server import BaseResolver, DNSServer, DNSLogger

from bridge_m4.collect import collect
from integration.ui_matrix.bandwidth_endpoint import BODY, DIGEST
from integration.ui_matrix.continue_global import candidate_value
from scripts.release_setup import need

SERVER = Path('/opt/matrix-test-tools/hysteria')
# Official test-only asset: https://github.com/HyNetworks/hysteria/releases/tag/app/v2.12.3
SERVER_SHA = '8c7a68a906998b747a0db87586e364f995fbfddb95693ae6e2fdb68a6e920d3e'
SECRET = 'SyntheticBandwidth314159'


def run(matrix, *, udp_health_only=False):
    need(hashlib.sha256(SERVER.read_bytes()).hexdigest() == SERVER_SHA, 'TEST_SERVER_IDENTITY_CHANGED')
    auth_events, dns_events = [], []

    class Auth(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 4096:
                self.send_error(400); return
            value = json.loads(self.rfile.read(length))
            matched = value.get('auth') == SECRET
            auth_events.append({'at': time.time(), 'authenticationMatched': matched, 'tx': value.get('tx')})
            body = json.dumps({'ok': matched, 'id': 'matrix-only'}).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    class Resolver(BaseResolver):
        def resolve(self, request, handler):
            dns_events.append({'at': time.time(), 'name': str(request.q.qname),
                               'type': QTYPE[request.q.qtype], 'transport': handler.protocol})
            response = request.reply()
            if request.q.qtype == QTYPE.A:
                response.add_answer(RR(request.q.qname, QTYPE.A, rdata=A('198.51.100.2'), ttl=0))
            return response

    auth = ThreadingHTTPServer(('127.0.0.1', 19501), Auth)
    threading.Thread(target=auth.serve_forever, daemon=True).start()
    dns = DNSServer(Resolver(), address='127.0.0.1', port=15359,
                    logger=DNSLogger(log='-request,-reply,-truncated,-error'))
    dns.start_thread()
    node = group = profile = None
    processes, logs, rows = [], [], []
    with tempfile.TemporaryDirectory(prefix='matrix-bandwidth-') as temp:
        directory = Path(temp)
        try:
            cert, key = directory / 'cert.pem', directory / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(key), '-out', str(cert), '-days', '1',
                            '-subj', '/CN=bandwidth.matrix.invalid'], check=True, capture_output=True)
            key.chmod(0o600)
            config = {'listen': '127.0.0.1:19500', 'tls': {'cert': str(cert), 'key': str(key)},
                      'auth': {'type': 'http', 'http': {'url': 'http://127.0.0.1:19501/'}},
                      'acl': {'inline': ['direct(198.51.100.2, tcp/18086)',
                                         'direct(127.0.0.1, udp/15359)', 'reject(all)']}}
            config_path = directory / 'server.json'
            config_path.write_text(json.dumps(config))
            for name, command in [('hysteria', [str(SERVER), 'server', '--disable-update-check', '-c', str(config_path)]),
                                  ('bandwidth-endpoint', ['ip', 'netns', 'exec', 'matrix-endpoint', 'python3', '-m',
                                                          'integration.ui_matrix.bandwidth_endpoint'])]:
                log_name = name + ('-udp-health' if udp_health_only else '') + '-fixture.log'
                log = (Path('/evidence') / log_name).open('xb'); logs.append(log)
                processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
            time.sleep(1)
            need(all(p.poll() is None for p in processes), 'BANDWIDTH_FIXTURE_START_FAILED')
            link = 'hysteria2://' + SECRET + '@127.0.0.1:19500?sni=bandwidth.matrix.invalid&insecure=1#MatrixBandwidth'
            imported = matrix.api('mutation($a:[ImportArgument!]!){importNodes(rollbackError:true,args:$a){node{id} error}}',
                                  {'a': [{'link': link}]})['importNodes'][0]
            need(not imported['error'] and imported['node'], 'BANDWIDTH_NODE_REJECTED')
            node = imported['node']['id']
            group_query = ('mutation{createGroup(name:"matrix_bandwidth",policy:min,policyParams:[]){id}}' if udp_health_only else
                           'mutation{createGroup(name:"matrix_bandwidth",policy:fixed,policyParams:[{key:"",val:"0"}]){id}}')
            group = matrix.api(group_query)['createGroup']['id']
            matrix.api('mutation($id:ID!,$ids:[ID!]!){groupAddNodes(id:$id,nodeIDs:$ids)}', {'id': group, 'ids': [node]})
            matrix.api('mutation($id:ID!){updateRouting(id:$id,routing:"fallback: matrix_bandwidth"){id}}', {'id': matrix.routing})
            bandwidth_source, _ = collect(matrix.reader)
            bodyfile = directory / 'payload.bin'; bodyfile.write_bytes(BODY)
            rates = [('4 mbps', 4000000)] if udp_health_only else [('512 kbps', 512000), ('4 mbps', 4000000)]
            for rate, bits in rates:
                row = {'id': 'global.udpCheckDns' if udp_health_only else 'global.bandwidth.' + str(bits), 'result': None}
                rows.append(row); matrix.results.append(row); matrix.save()
                try:
                    selected = next(c for c in matrix.fixture_source['metadata']['configs'] if c['selected'])
                    values = {k: v for k, v in selected['global'].items() if k != 'soMarkFromDaeSet'}
                    changes = {'bandwidthMaxTx': rate, 'bandwidthMaxRx': rate,
                               'tcpCheckUrl': ['http://198.51.100.2:18086/health'],
                               'udpCheckDns': ['127.0.0.1:15359'], 'checkInterval': '2s'}
                    values.update(changes)
                    profile = matrix.api('mutation($g:globalInput!){createConfig(name:"Matrix bandwidth",global:$g){id}}', {'g': values})['createConfig']['id']
                    matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': profile})
                    source, proof = collect(matrix.reader)
                    actual = next(c['global'] for c in source['metadata']['configs'] if c['id'] == profile)
                    need(all(actual[k] == v for k, v in changes.items()), 'BANDWIDTH_READBACK_CHANGED')
                    need(matrix.api('{general{dae{modified}}}')['general']['dae']['modified'] is True, 'MODIFIED_NOT_SET')
                    start = time.time(); applied, candidate = matrix.apply()
                    candidate_value(candidate, 'bandwidth_max_tx', rate)
                    candidate_value(candidate, 'bandwidth_max_rx', rate)
                    candidate_value(candidate, 'udp_check_dns', changes['udpCheckDns'])
                    row.update(readback=actual, doubleSnapshot=proof, applied=applied, candidate=candidate)
                    measurements = {}
                    if udp_health_only:
                        # Fixed selection deliberately has no alive set and sleeps
                        # its health checker. Use the already existing min policy
                        # and server; do not repeat completed bandwidth transfers.
                        time.sleep(12)
                    for direction in (() if udp_health_only else ('download', 'upload')):
                        response = directory / ('response-' + direction)
                        command = ['ip', 'netns', 'exec', 'matrix-client', 'curl', '--noproxy', '*',
                                   '--silent', '--show-error', '--max-time', '60', '--output', str(response),
                                   '--write-out', '%{http_code} %{time_total}', 'http://198.51.100.2:18086/' + direction]
                        if direction == 'upload': command += ['--data-binary', '@' + str(bodyfile)]
                        process = subprocess.run(command, capture_output=True, text=True, timeout=65)
                        need(process.returncode == 0, 'BANDWIDTH_TRANSFER_FAILED:' + direction)
                        status, elapsed = process.stdout.split(); elapsed = float(elapsed)
                        need(status == '200' and elapsed > 0, 'BANDWIDTH_HTTP_FAILED')
                        if direction == 'download':
                            need(hashlib.sha256(response.read_bytes()).hexdigest() == DIGEST, 'DOWNLOAD_CONTENT_CHANGED')
                        else:
                            need(json.loads(response.read_text()) == {'bytes': len(BODY), 'sha256': DIGEST}, 'UPLOAD_CONTENT_CHANGED')
                        measurements[direction] = {'bytes': len(BODY), 'seconds': elapsed,
                                                   'bitsPerSecond': len(BODY) * 8 / elapsed, 'sha256': DIGEST}
                    row.update(measurements=measurements, auth=[e for e in auth_events if e['at'] >= start],
                               dns=[e for e in dns_events if e['at'] >= start], serverSHA=SERVER_SHA)
                    need(any(e['authenticationMatched'] and e['tx'] == bits // 8 for e in row['auth']),
                         'ACTUAL_BANDWIDTH_NEGOTIATION_MISMATCH')
                    need(row['dns'], 'ACTUAL_UDP_HEALTH_PROBE_MISSING')
                    row.update(result='RUNTIME_PASS', scope=('Actual official DAE UDP health queries through the existing Hysteria fixture; no bandwidth rerun' if udp_health_only else 'Actual protocol bandwidth negotiation, transfer hashes and measured timing; cross-rate effect reviewed separately'))
                except Exception as exc:
                    row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]').replace(SECRET, '[REDACTED]'))
                finally:
                    matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': matrix.config})
                    if profile:
                        matrix.api('mutation($id:ID!){removeConfig(id:$id)}', {'id': profile}); profile = None
                    restored, restore_proof = collect(matrix.reader)
                    need(restored == bandwidth_source, 'BANDWIDTH_CASE_NOT_RESTORED')
                    restored_apply, _ = matrix.apply()
                    row.update(caseRestored=True, caseRestoreProof=restore_proof, caseRestore=restored_apply)
                    matrix.save()
                print(row['id'] + ': ' + row['result'], flush=True)
        finally:
            try:
                matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': matrix.config})
                if profile: matrix.api('mutation($id:ID!){removeConfig(id:$id)}', {'id': profile})
                matrix.api('mutation($id:ID!){updateRouting(id:$id,routing:"fallback: matrix_path"){id}}', {'id': matrix.routing})
                if group: matrix.api('mutation($id:ID!){removeGroup(id:$id)}', {'id': group})
                if node: matrix.api('mutation($ids:[ID!]!){removeNodes(ids:$ids)}', {'ids': [node]})
                restored, proof = collect(matrix.reader)
                need(restored == matrix.fixture_source, 'BANDWIDTH_FIXTURE_NOT_RESTORED')
                restored_apply, _ = matrix.apply()
                for row in rows: row.update(fixtureRestored=True, fixtureProof=proof, fixtureRestore=restored_apply)
                matrix.save()
            finally:
                for process in processes:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                for log in logs: log.close()
                auth.shutdown(); auth.server_close(); dns.stop()
