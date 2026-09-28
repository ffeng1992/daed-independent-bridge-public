"""Continue field evidence in the previously provisioned, network-isolated VM.

This records partial evidence explicitly. A successful config chain alone never
becomes a runtime pass. No production endpoint or credential is accepted.
"""
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from bridge_m1.collect import HTTPReader
from bridge_m4.collect import collect
from scripts.release_setup import client, need

EVIDENCE = Path('/evidence/global-continuation.json')
# Values exercise the visible controls; network-observation fixtures are separate.
CASES = [
    ('tproxyPort', 12346), ('logLevel', 'debug'),
    ('disableWaitingNetwork', False), ('enableLocalTcpFastRedirect', True),
    ('mptcp', True), ('lanInterface', ['lan1']), ('wanInterface', ['wan0']),
    ('autoConfigKernelParameter', False),
    ('tcpCheckUrl', ['http://127.0.0.1:18080/health']),
    ('tcpCheckHttpMethod', 'GET'), ('udpCheckDns', ['127.0.0.1:15354']),
    ('bootstrapResolver', '127.0.0.1:15354'), ('fallbackResolver', '127.0.0.1:15354'),
    ('checkInterval', '5s'), ('checkTolerance', '150ms'),
    ('dialMode', 'ip'), ('dialMode', 'domain+'), ('dialMode', 'domain++'),
    ('allowInsecure', True), ('sniffingTimeout', '250ms'),
    ('tlsImplementation', 'utls'), ('utlsImitate', 'firefox_auto'),
    ('bandwidthMaxTx', '10 mbps'), ('bandwidthMaxRx', '10 mbps'),
]

def observe_listener(pid, port, proc=Path('/proc'), run=subprocess.run):
    """Inspect the actual DAE threads, not a host-visible named netns mount.

    systemd may put the named mount in the service's private mount namespace.
    Thread namespace handles remain an authoritative read-only entry point.
    """
    if type(pid) is not int or pid <= 0 or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('INVALID_LISTENER_IDENTITY')
    namespaces = {}
    for task in sorted((proc / str(pid) / 'task').iterdir(), key=lambda p: int(p.name)):
        handle = task / 'ns/net'
        identity = os.readlink(handle)
        if identity in namespaces:
            continue
        command = ['nsenter', '--net=' + str(handle), 'ss', '-H', '-lnutp']
        result = run(command, check=True, capture_output=True, text=True)
        namespaces[identity] = {'command': command, 'output': result.stdout}
    protocols = set()
    for evidence in namespaces.values():
        for line in evidence['output'].splitlines():
            columns = line.split()
            if len(columns) >= 5 and columns[4].rsplit(':', 1)[-1] == str(port) and f'pid={pid},' in line:
                protocols.add(columns[0])
    need({'tcp', 'udp'} <= protocols, 'TPROXY_OWNED_LISTENER_MISSING')
    return {'MainPID': pid, 'port': port, 'namespaces': namespaces}


def candidate_value(candidate, field, expected):
    """Verify the emitted value, excluding comments and other sections."""
    from bridge_m4.extensions import masked, statements
    clean = masked(candidate)
    header = re.match(r'\s*global\s*\{', clean)
    need(header is not None, 'CANDIDATE_GLOBAL_MISSING')
    depth = 1
    end = None
    for index in range(header.end(), len(clean)):
        if clean[index] == '{': depth += 1
        elif clean[index] == '}': depth -= 1
        if depth == 0:
            end = index + 1
            break
    need(end is not None, 'CANDIDATE_GLOBAL_UNCLOSED')
    section = candidate[:end]
    fields = {key: section[start:stop].split(':', 1)[1].strip()
              for key, start, stop, kind in statements(section, 'global') if kind == ':'}
    need(field in fields, 'CANDIDATE_FIELD_MISSING')
    raw = fields[field]
    # Scalars emitted by this bridge use JSON strings, integers or booleans.
    actual = json.loads(raw)
    wanted = ','.join(expected) if type(expected) is list else expected
    need(type(actual) is type(wanted) and actual == wanted, 'CANDIDATE_VALUE_CHANGED')
    return actual

class Matrix:
    def __init__(self):
        from integration.packaging.onboarding import USERNAME, PASSWORD
        self.token = ''
        self.token = self.api('query($u:String!,$p:String!){token(username:$u,password:$p)}', {'u':USERNAME, 'p':PASSWORD})['token']
        self.reader = HTTPReader('http://127.0.0.1:2024/graphql', self.token)
        self.source, _ = collect(self.reader)
        self.original = next(c for c in self.source['metadata']['configs'] if c['selected'])
        self.records = json.loads(EVIDENCE.read_text()) if EVIDENCE.exists() else []

    def api(self, query, variables=None):
        headers = {'Content-Type':'application/json'}
        if self.token: headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request('http://127.0.0.1:2023/graphql',
            data=json.dumps({'query':query,'variables':variables or {}}).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=240) as response: value=json.load(response)
        if value.get('errors'):
            # Preserve backend diagnosis, never request variables/authorization.
            from scripts.redact import redact
            from integration.packaging.onboarding import PASSWORD
            message = redact(json.dumps([error.get('message', '') for error in value['errors']]))
            for secret in (self.token, PASSWORD, 'SyntheticOnly314159'):
                if secret: message = message.replace(secret, '[REDACTED]')
            # Error capture must not mask the upstream error if this standalone
            # fixture process lacks the adapter's vendored GraphQL parser.
            # The caller's case ID identifies the operation without logging
            # query variables or requiring another dependency in the error path.
            raise RuntimeError('GRAPHQL_REJECTED:' + message)
        return value['data']

    def save(self):
        temporary=EVIDENCE.with_suffix('.new')
        temporary.write_text(json.dumps(self.records, indent=2)+'\n')
        temporary.replace(EVIDENCE)

    def apply(self):
        result=client('import json;from bridge_m4.runtime import Runtime;r=Runtime();p=r.preview(json.load(sys.stdin));v=r.validate(p["previewId"]);print(json.dumps({"preview":p,"validation":v}))',self.token)
        p=result['preview']; need(result['validation']['validated'],'VALIDATE_FAILED')
        deadline=time.monotonic()+120
        receipt=Path('/var/lib/bridge-m4-attestation/receipt.json')
        while time.monotonic()<deadline:
            if receipt.exists() and json.loads(receipt.read_text())['sourceSha256']==p['sourceFingerprint']:break
            time.sleep(1)
        else:raise RuntimeError('RECEIPT_NOT_CURRENT')
        self.api('mutation{run(dry:false)}')
        status=client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().status()))',{})
        need(status['state']=='running' and status['identityVerified'] and status['configSha256']==p['candidateSha256'],'APPLY_IDENTITY_FAILED')
        need(self.api('{general{dae{modified}}}')['general']['dae']['modified'] is False,'MODIFIED_AFTER_APPLY')
        candidate=Path('/var/lib/bridge-m4-client/previews',p['previewId'],'candidate.dae').read_text()
        return {'preview':p,'validation':result['validation'],'status':status},candidate

    def field(self, key, value):
        identity=key+':'+json.dumps(value,sort_keys=True)
        if any(r['id']==identity and r.get('baselineRestored') is True for r in self.records):return
        record={'id':identity,'field':key,'value':value,'stage':'create','result':None}
        self.records.append(record);self.save()
        ident=None
        try:
            values={k:v for k,v in self.original['global'].items() if k!='soMarkFromDaeSet'}
            values[key]=value
            # Hysteria2 capacity values are a pair, not a generic TCP shaper.
            if key in ('bandwidthMaxTx','bandwidthMaxRx'):
                values.update(bandwidthMaxTx='10 mbps',bandwidthMaxRx='10 mbps')
            ident=self.api('mutation($g:globalInput!){createConfig(name:"Matrix temporary",global:$g){id}}',{'g':values})['createConfig']['id']
            # Use the same official update operation as the edit form.
            self.api('mutation($id:ID!,$g:globalInput!){updateConfig(id:$id,global:$g){id}}',{'id':ident,'g':values})
            self.api('mutation($id:ID!){selectConfig(id:$id)}',{'id':ident})
            source,proof=collect(self.reader)
            actual=next(c['global'][key] for c in source['metadata']['configs'] if c['id']==ident)
            record.update(stage='readback',readback=actual,doubleSnapshot=proof)
            need(actual==value,'VALUE_CHANGED')
            need(self.api('{general{dae{modified}}}')['general']['dae']['modified'] is True,'MODIFIED_NOT_SET')
            record['stage']='validate-apply';self.save()
            applied,candidate=self.apply()
            from bridge_m4.convert import FIELDS
            dae=next(f['dae'] for f in FIELDS if f['graphql']==key)
            emitted = candidate_value(candidate, dae, value)
            # Persist synthetic candidate evidence, including every unchanged field.
            record.update(daeField=dae,applied=applied,candidate=candidate,candidateValue=emitted,configChainPassed=True)
            if key=='enableLocalTcpFastRedirect':
                record.update(result='FAIL',reason='UPSTREAM_DEPRECATED_NO_RUNTIME_IMPLEMENTATION')
            elif key=='tproxyPort':
                evidence=observe_listener(applied['status']['MainPID'],value)
                record.update(result='RUNTIME_PASS',runtimeEvidence=evidence)
            else:
                record.update(runtimeEvidence='PENDING_SEMANTIC_RUNTIME_OBSERVATION')
            record['stage']='restore'
        except Exception as exc:
            record.update(result='FAIL',errorType=type(exc).__name__,reason=str(exc).replace(self.token,'[REDACTED]'))
        finally:
            self.api('mutation($id:ID!){selectConfig(id:$id)}',{'id':self.original['id']})
            if ident:self.api('mutation($id:ID!){removeConfig(id:$id)}',{'id':ident})
            restored,_=collect(self.reader)
            need(restored==self.source,'BASELINE_SOURCE_CHANGED')
            evidence,_=self.apply()
            record['baselineRestore']=evidence;record['baselineRestored']=True
            self.save()
            print(identity+': '+str(record['result'] or 'CONFIG_CHAIN_ONLY'),flush=True)


def main():
    interfaces=sorted(p.name for p in Path('/sys/class/net').iterdir())
    Path('/evidence/interfaces.json').write_text(json.dumps(interfaces)+'\n')
    # A running official DAE creates its documented host-side dae0 device.
    need(interfaces==['client0','client1','dae0','lan0','lan1','lo','wan0','wanpeer'],'ISOLATED_INTERFACE_SET')
    m=Matrix()
    m.apply()  # Establish current baseline after resuming a purged lifecycle VM.
    for key,value in CASES:m.field(key,value)

if __name__=='__main__':main()
