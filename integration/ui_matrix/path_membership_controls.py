"""Unfinished edit/removal controls observed through the existing local proxy."""
import json
from urllib.parse import urlsplit
from bridge_m4.collect import collect
from scripts.release_setup import need


def run(matrix):
    baseline = next(g for g in matrix.fixture_source['metadata']['groups'] if g['id'] == matrix.group)
    selected = baseline['nodes'][0]['id']
    node = next(n for n in matrix.fixture_source['nodes'] if n['id'] == selected)
    original_port = urlsplit(node['link']).port
    other_port = 18083 if original_port == 18082 else 18082
    for kind in ('node.update', 'group.remove-node'):
        row = {'id': 'membership.' + kind, 'result': None}
        matrix.results.append(row); matrix.save()
        try:
            if kind == 'node.update':
                link = node['link'].replace(':' + str(original_port) + '#', ':' + str(other_port) + '#')
                need(link != node['link'], 'TEST_URI_NOT_CHANGED')
                matrix.api('mutation($id:ID!,$s:String!){updateNode(id:$id,newLink:$s){id}}', {'id': selected, 's': link})
            else:
                matrix.api('mutation($id:ID!,$ids:[ID!]!){groupDelNodes(id:$id,nodeIDs:$ids)}', {'id': matrix.group, 'ids': [selected]})
            source, proof = collect(matrix.reader)
            group = next(g for g in source['metadata']['groups'] if g['id'] == matrix.group)
            if kind == 'node.update':
                need(next(n['link'] for n in source['nodes'] if n['id'] == selected) == link, 'UPDATED_LINK_READBACK')
            else:
                need([n['id'] for n in group['nodes']] == [n['id'] for n in baseline['nodes'] if n['id'] != selected], 'REMOVED_MEMBER_STILL_BOUND')
            need(matrix.api('{general{dae{modified}}}')['general']['dae']['modified'] is True, 'MODIFIED_NOT_SET')
            applied, candidate = matrix.apply()
            if kind == 'node.update': need(json.dumps(link) in candidate, 'UPDATED_URI_NOT_EMITTED')
            path = matrix.request('membership-' + kind)
            need(path['proxy'] and path['proxy'][-1]['proxy'] == other_port, 'UPDATED_PATH_NOT_OBSERVED')
            row.update(result='RUNTIME_PASS', readback=group, doubleSnapshot=proof,
                       applied=applied, candidate=candidate, path=path)
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]'))
        finally:
            if kind == 'node.update':
                matrix.api('mutation($id:ID!,$s:String!){updateNode(id:$id,newLink:$s){id}}', {'id': selected, 's': node['link']})
            else:
                matrix.api('mutation($id:ID!,$ids:[ID!]!){groupAddNodes(id:$id,nodeIDs:$ids)}', {'id': matrix.group, 'ids': [selected]})
            source, proof = collect(matrix.reader)
            need(source == matrix.fixture_source, 'MEMBERSHIP_FIXTURE_NOT_RESTORED')
            applied, _ = matrix.apply()
            row.update(fixtureRestored=True, fixtureProof=proof, fixtureRestore=applied)
            matrix.save()
        print(row['id'] + ': ' + row['result'], flush=True)
