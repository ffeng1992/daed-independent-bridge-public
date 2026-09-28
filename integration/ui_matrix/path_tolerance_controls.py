"""Compare selection hysteresis using two locally delayed proxy endpoints."""
import json
import time

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import candidate_value
from integration.ui_matrix.path_fixture import DELAYS
from scripts.release_setup import need


def delays(first, second):
    temporary = DELAYS.with_suffix('.new')
    temporary.write_text(json.dumps({'18082': first, '18083': second}))
    temporary.replace(DELAYS)


def run(matrix):
    need(not DELAYS.exists(), 'DELAY_FIXTURE_ALREADY_PRESENT')
    profile = None
    try:
        for tolerance, expected in [('800ms', 18082), ('20ms', 18083)]:
            row = {'id': 'global.checkTolerance.' + tolerance, 'result': None}
            matrix.results.append(row); matrix.save()
            try:
                delays(1.0, 2.0)
                matrix.api('mutation($id:ID!){groupSetPolicy(id:$id,policy:min,policyParams:[])}', {'id': matrix.group})
                selected = next(c for c in matrix.fixture_source['metadata']['configs'] if c['selected'])
                values = {k: v for k, v in selected['global'].items() if k != 'soMarkFromDaeSet'}
                values.update(checkTolerance=tolerance, checkInterval='2s')
                profile = matrix.api('mutation($g:globalInput!){createConfig(name:"Matrix check tolerance",global:$g){id}}', {'g': values})['createConfig']['id']
                matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': profile})
                source, proof = collect(matrix.reader)
                actual = next(c['global'] for c in source['metadata']['configs'] if c['id'] == profile)
                need(actual['checkTolerance'] == tolerance, 'TOLERANCE_READBACK_CHANGED')
                need(matrix.api('{general{dae{modified}}}')['general']['dae']['modified'] is True, 'MODIFIED_NOT_SET')
                applied, candidate = matrix.apply()
                candidate_value(candidate, 'check_tolerance', tolerance)
                row.update(readback=actual, doubleSnapshot=proof, applied=applied, candidate=candidate)
                time.sleep(20)
                first = [matrix.request('tolerance-initial-' + tolerance + '-' + str(i)) for i in range(3)]
                need(all(p['proxy'] and p['proxy'][-1]['proxy'] == 18082 for p in first), 'INITIAL_FAST_NODE_NOT_SELECTED')
                # The new node improves latency by 600 ms: below 800 ms but
                # above 20 ms. This is an actual delayed HTTP proxy path.
                delays(1.0, .4)
                time.sleep(20)
                second = [matrix.request('tolerance-changed-' + tolerance + '-' + str(i)) for i in range(3)]
                row.update(initialPaths=first, changedPaths=second,
                           initialDelaySeconds={'18082': 1.0, '18083': 2.0},
                           changedDelaySeconds={'18082': 1.0, '18083': .4})
                need(all(p['proxy'] and p['proxy'][-1]['proxy'] == expected for p in second),
                     'ACTUAL_SELECTION_HYSTERESIS_MISMATCH')
                row.update(result='RUNTIME_PASS', scope='Actual group selection under controlled HTTP proxy delays, no netem claim')
            except Exception as exc:
                row.update(result='FAIL', errorType=type(exc).__name__, reason=str(exc).replace(matrix.token, '[REDACTED]'))
            finally:
                DELAYS.unlink(missing_ok=True)
                matrix.api('mutation($id:ID!){selectConfig(id:$id)}', {'id': matrix.config})
                if profile:
                    matrix.api('mutation($id:ID!){removeConfig(id:$id)}', {'id': profile}); profile = None
                matrix.api('mutation($id:ID!){groupSetPolicy(id:$id,policy:fixed,policyParams:[{key:"",val:"0"}])}', {'id': matrix.group})
                restored, proof = collect(matrix.reader)
                need(restored == matrix.fixture_source, 'TOLERANCE_FIXTURE_NOT_RESTORED')
                applied, _ = matrix.apply()
                row.update(fixtureRestored=True, fixtureProof=proof, fixtureRestore=applied)
                matrix.save()
            print(row['id'] + ': ' + row['result'], flush=True)
    finally:
        DELAYS.unlink(missing_ok=True)
