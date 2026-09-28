"""Subscription link/tag/cron/filter continuation using a loopback fixture."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import Matrix
from scripts.release_setup import need


def main():
    need(Path('/evidence/nodes-complete').is_file(), 'PREVIOUS_BATCH_INCOMPLETE')
    path = Path('/evidence/subscription-continuation.json')
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

    def save():
        path.write_text(json.dumps({'rows': rows, 'requests': requests}, indent=2) + '\n')

    def check(ident, action):
        row = {'id': ident, 'result': None}; rows.append(row); save()
        try:
            row['evidence'] = action()
            row['result'] = 'RUNTIME_PASS'
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]'))
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
            value = matrix.api('mutation($id:ID!){updateSubscriptionCron(id:$id,cronExp:"* * * * *",cronEnable:true){cronExp cronEnable}}', {'id': sid})['updateSubscriptionCron']
            need(value == {'cronExp': '* * * * *', 'cronEnable': True}, 'CRON_READBACK_CHANGED')
            deadline = time.monotonic() + 90
            while len(requests) == before and time.monotonic() < deadline: time.sleep(1)
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
