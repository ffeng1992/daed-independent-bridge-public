"""First real-API probes of the locked Config form, using synthetic VM data."""
import json
import time
from pathlib import Path
import urllib.request

from scripts.release_setup import CFG, client, need


def run():
    from integration.packaging import onboarding
    token = ''
    records = []
    endpoint = 'http://' + json.loads((CFG / 'web.json').read_text())['address'] + ':2023/graphql'

    def api(query, variables=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(endpoint, data=json.dumps({'query': query, 'variables': variables or {}}).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.load(response)
        if result.get('errors'):
            # Synthetic inputs only; never serialize request variables or headers.
            raise RuntimeError('GRAPHQL_REJECTED:' + json.dumps([e['message'] for e in result['errors']]))
        return result['data']

    token = api('query($u:String!,$p:String!){token(username:$u,password:$p)}', {'u': onboarding.USERNAME, 'p': onboarding.PASSWORD})['token']
    from bridge_m4.collect import collect
    from bridge_m1.collect import HTTPReader
    reader = HTTPReader('http://127.0.0.1:2024/graphql', token)
    source, _ = collect(reader)
    original = next(x for x in source['metadata']['configs'] if x['selected'])
    baseline = dict(original['global'])
    # Keep the selected baseline immutable. Upstream updateConfig serializes
    # effective defaults and is not a lossless inverse of createConfig.
    ident = api('mutation($g:globalInput!){createConfig(name:"UI matrix probe",global:$g){id}}',
                {'g': baseline})['createConfig']['id']
    api('mutation($id:ID!){selectConfig(id:$id)}', {'id': ident})

    def update(values):
        api('mutation($id:ID!,$g:globalInput!){updateConfig(id:$id,global:$g){id}}', {'id': ident, 'g': values})

    def record(name, operation):
        try:
            evidence = operation()
            records.append({'case': name, 'passed': True, 'evidence': evidence})
        except Exception as exc:
            message = str(exc).replace(token, '[REDACTED]').replace(onboarding.PASSWORD, '[REDACTED]')
            records.append({'case': name, 'passed': False, 'errorType': type(exc).__name__, 'error': message})
        Path('/evidence/ui-global-probe.json').write_text(json.dumps(records, indent=2) + '\n')

    def apply_current(expected=None):
        result = client('import json;from bridge_m4.runtime import Runtime;r=Runtime();p=r.preview(json.load(sys.stdin));v=r.validate(p["previewId"]);print(json.dumps({"preview":p,"validation":v}))', token)
        preview = result['preview']
        candidate = Path('/var/lib/bridge-m4-client/previews', preview['previewId'], 'candidate.dae').read_text()
        if expected is not None:
            need(expected in candidate, 'EXPECTED_CONFIG_VALUE_MISSING')
        need(result['validation']['validated'], 'OFFICIAL_VALIDATE_FAILED')
        deadline = time.monotonic() + 90
        receipt = Path('/var/lib/bridge-m4-attestation/receipt.json')
        while time.monotonic() < deadline:
            if receipt.exists() and json.loads(receipt.read_text())['sourceSha256'] == preview['sourceFingerprint']:
                break
            time.sleep(1)
        else:
            raise RuntimeError('MATRIX_RECEIPT_NOT_CURRENT')
        api('mutation{run(dry:false)}')
        status = client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().status()))', {})
        need(status['state'] == 'running' and status['identityVerified'] and status['configSha256'] == preview['candidateSha256'], 'MATRIX_APPLY_IDENTITY')
        need(api('{general{dae{modified}}}')['general']['dae']['modified'] is False, 'MODIFIED_AFTER_APPLY')
        return {'preview': preview, 'validation': result['validation'], 'status': status}

    def form_payload():
        # Exact extra form-only keys from pinned ConfigFormModal onSubmit's
        # trailing ...data spread. No upstream source/assets are modified.
        values = {k: v for k, v in baseline.items() if k != 'soMarkFromDaeSet'}
        values.update(name='Synthetic LAN', logLevel='debug', logLevelNumber=3,
                      checkIntervalSeconds=30, checkToleranceMS=50, sniffingTimeoutMS=100,
                      checkInterval='30s', checkTolerance='50ms', sniffingTimeout='100ms')
        update(values)
        saved, proof = collect(reader)
        current = next(x['global'] for x in saved['metadata']['configs'] if x['id'] == ident)
        need(current['logLevel'] == 'debug', 'FORM_VALUE_NOT_SAVED')
        changed = {key: {'before': baseline[key], 'after': current[key]} for key in baseline if baseline[key] != current[key]}
        return {'readback': current, 'doubleSnapshot': proof, 'fullFormExtrasAccepted': True, 'changedFields': changed}

    def mark_payload():
        values = {k: v for k, v in baseline.items() if k != 'soMarkFromDaeSet'}
        values['soMarkFromDae'] = 123
        update(values)
        saved, proof = collect(reader)
        current = next(x['global'] for x in saved['metadata']['configs'] if x['id'] == ident)
        need(current['soMarkFromDae'] == 123, 'MARK_READBACK_CHANGED')
        preview = client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().preview(json.load(sys.stdin))))', token)
        # Root reads the synthetic test artifact only, never a production file.
        candidate = Path('/var/lib/bridge-m4-client/previews', preview['previewId'], 'candidate.dae').read_text()
        need('so_mark_from_dae: 123' in candidate, 'MARK_SILENTLY_OMITTED')
        return {'mark': current['soMarkFromDae'], 'presence': current['soMarkFromDaeSet'], 'doubleSnapshot': proof,
                'candidateSha256': preview['candidateSha256'], 'sourceFingerprint': preview['sourceFingerprint']}

    def create_false():
        created = api('mutation($g:globalInput!){createConfig(name:"UI explicit false",global:$g){id global{tproxyPortProtect}}}',
                      {'g': dict({k:v for k,v in baseline.items() if k != 'soMarkFromDaeSet'}, tproxyPortProtect=False)})['createConfig']
        try:
            saved, proof = collect(reader)
            value = next(x['global']['tproxyPortProtect'] for x in saved['metadata']['configs'] if x['id'] == created['id'])
            # Persist both sides even when the assertion fails.
            Path('/evidence/ui-create-false.json').write_text(json.dumps({
                'write': {'tproxyPortProtect': False}, 'mutationReadback': created['global'],
                'queryReadback': {'tproxyPortProtect': value}, 'doubleSnapshot': proof}, indent=2)+'\n')
            need(value is False, 'EXPLICIT_FALSE_CHANGED_TO_TRUE')
            api('mutation($id:ID!){selectConfig(id:$id)}', {'id': created['id']})
            need(api('{general{dae{modified}}}')['general']['dae']['modified'] is True, 'MODIFIED_BEFORE_APPLY')
            applied = apply_current('tproxy_port_protect: false')
            return {'tproxyPortProtect': value, 'applied': applied, 'configChainPassed': True,
                    'runtimeObservation': 'No independent port-protection behavior test in this probe.'}
        finally:
            api('mutation($id:ID!){selectConfig(id:$id)}', {'id': ident})
            api('mutation($id:ID!){removeConfig(id:$id)}', {'id': created['id']})

    try:
        record('official-ConfigForm-full-submit-payload', form_payload)
        update(baseline)
        record('official-ConfigForm-soMarkFromDae-preservation', mark_payload)
        record('official-createConfig-explicit-false', create_false)
    finally:
        api('mutation($id:ID!){selectConfig(id:$id)}', {'id': original['id']})
        api('mutation($id:ID!){removeConfig(id:$id)}', {'id': ident})
        restored, _ = collect(reader)
        need(next(x['global'] for x in restored['metadata']['configs'] if x['id'] == original['id']) == baseline, 'PROBE_BASELINE_RESTORE_FAILED')
        need(restored == source, 'PROBE_SOURCE_RESTORE_FAILED')
        record('probe-baseline-validate-apply-restored', apply_current)
    need(all(x['passed'] for x in records), 'UI_GLOBAL_PROBE_FAILED')
