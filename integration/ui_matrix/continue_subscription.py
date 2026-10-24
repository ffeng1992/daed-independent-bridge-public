from integration.ui_matrix.completion import read as read_completion
"""Subscription link/tag/cron/filter continuation using a loopback fixture."""
from integration.ui_matrix.evidence_scope import scope_file
import json
import hashlib
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import Matrix
from scripts.release_setup import need


def cron_failure_classification(exc, observed, *, root=None):
    """Only classify the pinned, fully witnessed stale scheduler failure."""
    if type(exc) is not RuntimeError or str(exc) != 'CRON_DID_NOT_FETCH':
        return {}
    try:
        old = observed['before']
        expected = {'cronExp': '* * * * *', 'cronEnable': True}
        if (observed['mutation'] != expected or observed['readback'] != expected
                or old['cronExp'] == expected['cronExp']
                or observed['elapsedSeconds'] < 90 or observed['requests'] != []
                or observed['endedAt'] - observed['startedAt'] < 90):
            return {}
        message = ('Subscription ' + observed['tag'] +
                   ' update task enabled, with exp ' + old['cronExp'])
        witnesses = [r for r in observed['journal']
            if r.get('_SYSTEMD_UNIT') == 'daed-api.service'
            and r.get('_BOOT_ID') == observed['bootId']
            and r.get('_SYSTEMD_INVOCATION_ID') == observed['invocationId']
            and r.get('MESSAGE', '').endswith(message + '"')
            and observed['startedAt'] <= int(r['__REALTIME_TIMESTAMP']) / 1e6 <= observed['endedAt']]
        if not witnesses:
            return {}
        root = root or Path(__file__).resolve().parents[2]
        lock_bytes = (root/'upstream.lock.json').read_bytes()
        lock = json.loads(lock_bytes)['components']['daed']
        binary = next(x['sha256'] for x in lock['archive_members']
                      if x['path'] == 'daed-linux-x86_64/daed-linux-x86_64')
        if (lock['version'] != 'v2.1.1'
                or lock['commit'] != 'b3043aa7ce07c774c65e546112aa2c7a1c12edb5'
                or observed['executableSha256'] != binary):
            return {}
        doc = root/'docs/WEB-FIELD-MATRIX.md'; body = doc.read_bytes()
        section = body.decode().split('### action.updateSubscriptionCron\n',1)[1].split('\n### ',1)[0]
        if not all(x in section for x in ('Owner: official daed.', 'v2.1.1',
                'dc503088945812c11235b35362d2bfa1a4c3bdf0',
                'graphql/service/subscription/mutation_utils.go',
                'Scheduler is restarted before deferred transaction commit')):
            return {}
        return {'owner':'official daed',
            'classificationReason':'PINNED_STALE_SUBSCRIPTION_SCHEDULER',
            'sourceEvidence':{'file':'docs/WEB-FIELD-MATRIX.md',
                'sha256':hashlib.sha256(body).hexdigest(),
                'section':'### action.updateSubscriptionCron',
                'sectionSha256':hashlib.sha256(section.encode()).hexdigest(),
                'lockFile':'upstream.lock.json','lockSha256':hashlib.sha256(lock_bytes).hexdigest(),
                'officialVersion':lock['version'],'officialCommit':lock['commit'],
                'observationSha256':hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest()}}
    except (KeyError, TypeError, ValueError, IndexError, StopIteration, OSError):
        return {}


def journal_cursor():
    text = subprocess.run(['journalctl','-b','-u','daed-api.service','-n','0','--show-cursor','--no-pager'],
                          check=True,capture_output=True,text=True).stdout
    return text.split('-- cursor: ',1)[1].strip()


def main():
    need(bool(read_completion('nodes-complete')), 'PREVIOUS_BATCH_INCOMPLETE')
    path = scope_file(Path('/evidence/subscription-continuation.json'))
    need(not path.exists(), 'EXISTING_SUBSCRIPTION_EVIDENCE_DO_NOT_RERUN')
    matrix = Matrix()
    requests = []
    links = {
        '/a': ['http://127.0.0.1:18082#alpha', 'http://127.0.0.1:18083#beta'],
        '/b': ['http://127.0.0.1:18084#alpha-updated', 'http://127.0.0.1:18085#beta-updated'],
    }

    class Subscription(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({'time': time.time(), 'path': self.path})
            if self.path not in links:
                self.send_error(404); return
            self.send_response(200); self.end_headers()
            self.wfile.write(('\n'.join(links[self.path]) + '\n').encode())

        def log_message(self, *_):
            pass

    server = HTTPServer(('127.0.0.1', 18081), Subscription)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rows = []; sid = group = None
    cron_observation = {}

    def save():
        path.write_text(json.dumps({'rows': rows, 'requests': requests}, indent=2) + '\n')

    def check(ident, action):
        row = {'id': ident, 'result': None}; rows.append(row); save()
        try:
            row['evidence'] = action()
            row['result'] = 'RUNTIME_PASS'
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]'))
            if ident == 'subscription.cron-enable-expression-disable':
                row['cronObservation'] = cron_observation
                row.update(cron_failure_classification(exc, cron_observation))
        save(); print(ident + ': ' + row['result'], flush=True)

    def subscription():
        return next(s for s in matrix.api('{subscriptions{id link tag cronExp cronEnable nodes{edges{id name link}}}}')['subscriptions'] if s['id'] == sid)

    try:
        imported = matrix.api('mutation{importSubscription(rollbackError:true,arg:{link:"http://127.0.0.1:18081/a",tag:"matrix-original"}){sub{id} nodeImportResult{error}}}')['importSubscription']
        need(imported['sub'] and all(not n['error'] for n in imported['nodeImportResult']), 'SUBSCRIPTION_FIXTURE_IMPORT')
        sid = imported['sub']['id']
        group = matrix.api('mutation{createGroup(name:"matrix_subscription",policy:fixed,policyParams:[{key:"",val:"0"}]){id}}')['createGroup']['id']
        matrix.api('mutation($id:ID!,$ids:[ID!]!){groupAddSubscriptions(id:$id,subscriptionIDs:$ids,nameFilterRegex:"^alpha")}', {'id': group, 'ids': [sid]})

        def tag():
            matrix.api('mutation($id:ID!){tagSubscription(id:$id,tag:"matrix-tag-edited")}', {'id': sid})
            value = subscription(); need(value['tag'] == 'matrix-tag-edited', 'SUBSCRIPTION_TAG_CHANGED')
            return {'tag': value['tag']}
        check('subscription.tag', tag)

        def change_link():
            matrix.api('mutation($id:ID!){updateSubscriptionLink(id:$id,link:"http://127.0.0.1:18081/b"){id link}}', {'id': sid})
            need(subscription()['link'] == 'http://127.0.0.1:18081/b', 'SUBSCRIPTION_LINK_CHANGED')
            matrix.api('mutation($id:ID!){updateSubscription(id:$id){id}}', {'id': sid})
            current = subscription()
            need({n['link'] for n in current['nodes']['edges']} == set(links['/b']), 'SUBSCRIPTION_UPDATE_CONTENT_CHANGED')
            source, proof = collect(matrix.reader)
            value = next(g for g in source['metadata']['groups'] if g['id'] == group)
            binding = value['subscriptions'][0]
            need(binding['subscription']['id'] == sid and binding['matchedCount'] == 1, 'SUBSCRIPTION_BINDING_LOST')
            node_id = binding['matchedNodes'][0]['id']
            need(next(n['link'] for n in source['nodes'] if n['id'] == node_id) == links['/b'][0], 'NAME_FILTER_WRONG_NODE')
            applied, candidate = matrix.apply()
            need(json.dumps(links['/b'][0]) in candidate and json.dumps(links['/b'][1]) not in candidate, 'CANDIDATE_FILTER_MISMATCH')
            return {'doubleSnapshot': proof, 'binding': binding, 'candidate': candidate, 'applied': applied,
                    'note': 'Filter membership is proven; no remote protocol handshake claimed.'}
        check('subscription.link-update-preserves-group-nameFilterRegex', change_link)

        def cron():
            before = len(requests)
            prior = subscription()
            cursor = journal_cursor()
            unit = dict(x.split('=',1) for x in subprocess.run(
                ['systemctl','show','daed-api.service','--property=MainPID,InvocationID'],
                check=True,capture_output=True,text=True).stdout.splitlines())
            cron_observation.update(before={'cronExp':prior['cronExp'],'cronEnable':prior['cronEnable']},
                tag=prior['tag'],startedAt=time.time(),bootId=Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-',''),
                invocationId=unit['InvocationID'],executableSha256=hashlib.sha256(
                    Path('/proc/'+unit['MainPID']+'/exe').read_bytes()).hexdigest())
            started = time.monotonic()
            value = matrix.api('mutation($id:ID!){updateSubscriptionCron(id:$id,cronExp:"* * * * *",cronEnable:true){cronExp cronEnable}}', {'id': sid})['updateSubscriptionCron']
            need(value == {'cronExp': '* * * * *', 'cronEnable': True}, 'CRON_READBACK_CHANGED')
            cron_observation['mutation'] = value
            current = subscription()
            cron_observation['readback'] = {k:current[k] for k in ('cronExp','cronEnable')}
            deadline = time.monotonic() + 90
            while len(requests) == before and time.monotonic() < deadline: time.sleep(1)
            cron_observation.update(endedAt=time.time(),elapsedSeconds=time.monotonic()-started,
                requests=requests[before:],journal=[json.loads(line) for line in subprocess.run(
                    ['journalctl','-b','-u','daed-api.service','--after-cursor='+cursor,'-o','json','--no-pager'],
                    check=True,capture_output=True,text=True).stdout.splitlines() if line.startswith('{')])
            save()
            need(len(requests) > before and requests[-1]['path'] == '/b', 'CRON_DID_NOT_FETCH')
            observed = requests[before:]
            matrix.api('mutation($id:ID!){updateSubscriptionCron(id:$id,cronExp:"* * * * *",cronEnable:false){cronEnable}}', {'id': sid})
            time.sleep(2); count = len(requests)
            time.sleep(65)
            need(len(requests) == count and subscription()['cronEnable'] is False, 'CRON_DISABLE_DID_NOT_STOP')
            return {'enabledReadback': value, 'naturalFetch': observed, 'disabledNoFetchSeconds': 65}
        check('subscription.cron-enable-expression-disable', cron)
    finally:
        if group: matrix.api('mutation($id:ID!){removeGroup(id:$id)}', {'id': group})
        if sid: matrix.api('mutation($ids:[ID!]!){removeSubscriptions(ids:$ids)}', {'ids': [sid]})
        server.shutdown(); server.server_close()
        restored, proof = collect(matrix.reader)
        need(restored == matrix.source, 'SUBSCRIPTION_BASELINE_NOT_RESTORED')
        applied, _ = matrix.apply()
        for row in rows: row.update(baselineRestored=True, baselineProof=proof, baselineRestore=applied)
        save()


if __name__ == '__main__':
    main()
