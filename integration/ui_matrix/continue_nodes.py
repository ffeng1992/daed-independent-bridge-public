from integration.ui_matrix.completion import read as read_completion
"""Synthetic official-API node field evidence, in the existing disposable VM.

URI fixtures follow the pinned original form generators. This is API evidence,
not a claim of browser clicks or successful remote-protocol handshakes.
"""
from integration.ui_matrix.evidence_scope import scope_file
import base64
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import Matrix
from scripts.release_setup import need

UUID = '11111111-2222-4333-8444-555555555555'
HOST = '192.0.2.99'
SECRET = 'SyntheticOnly314159'


def b64(value, url=False):
    encoded = (base64.urlsafe_b64encode if url else base64.b64encode)(value.encode()).decode()
    return encoded.rstrip('=') if url else encoded


def uri(scheme, user, password=None, query=None, port=19443, name='Matrix synthetic'):
    auth = quote(user, safe='')
    if password is not None: auth += ':' + quote(password, safe='')
    params = {k: str(v).lower() if type(v) is bool else v for k, v in (query or {}).items()}
    return f'{scheme}://{auth}@{HOST}:{port}' + ('?' + urlencode(params, quote_via=quote) if params else '') + '#' + quote(name, safe='')


def cases():
    values = []
    def add(ident, link, fields, expected_ignored=()):
        values.append({'id': ident, 'link': link, 'fields': fields.split(), 'sourceIgnored': list(expected_ignored)})
    add('ss-basic', f'ss://{b64("aes-128-gcm:"+SECRET)}@{HOST}:18388/#Matrix',
        'ss.method ss.password ss.server ss.port ss.name')
    for kind, plugin, fields in [
        ('websocket', 'v2ray-plugin;tls;host=matrix.invalid;path=/fixture;impl=chained', 'ss.plugin ss.tls ss.mode ss.host ss.path ss.impl'),
        ('simpleobfs', 'simple-obfs;obfs=http;obfs-host=matrix.invalid;obfs-path=/fixture;impl=chained', 'ss.plugin ss.obfs ss.host ss.path ss.impl')]:
        add('ss-'+kind, f'ss://{b64("aes-128-gcm:"+SECRET)}@{HOST}:18388/?plugin={quote(plugin,safe="")}#Matrix', fields, ['ss.impl'])
    raw=f'{HOST}:18389:origin:aes-128-cfb:http_simple:{b64(SECRET,True)}/?remarks={b64("Matrix",True)}&protoparam={b64("123:synthetic",True)}&obfsparam={b64("matrix.invalid",True)}'
    add('ssr', 'ssr://'+b64(raw), 'ssr.server ssr.port ssr.proto ssr.method ssr.obfs ssr.password ssr.name ssr.protoParam ssr.obfsParam')
    add('trojan', uri('trojan',SECRET,query={'allowInsecure':True,'sni':'matrix.invalid'}), 'trojan.name trojan.server trojan.port trojan.password trojan.peer trojan.allowInsecure trojan.method')
    add('trojan-go', uri('trojan-go',SECRET,query={'type':'ws','encryption':'ss;aes-128-gcm;SyntheticSS','host':'matrix.invalid','path':'/fixture','sni':'matrix.invalid'}), 'trojan.method trojan.ssCipher trojan.ssPassword trojan.obfs trojan.host trojan.path')
    add('tuic', uri('tuic',UUID,SECRET,{'congestion_control':'cubic','alpn':'h3','sni':'matrix.invalid','allow_insecure':True,'disable_sni':False,'udp_relay_mode':'quic'}), 'tuic.name tuic.server tuic.port tuic.uuid tuic.password tuic.congestion_control tuic.alpn tuic.sni tuic.allowInsecure tuic.disable_sni tuic.udp_relay_mode')
    add('juicity', uri('juicity',UUID,SECRET,{'congestion_control':'cubic','pinned_certchain_sha256':'ab'*32,'sni':'matrix.invalid','allow_insecure':True}), 'juicity.name juicity.server juicity.port juicity.uuid juicity.password juicity.congestion_control juicity.pinned_certchain_sha256 juicity.sni juicity.allowInsecure')
    add('hysteria2', uri('hysteria2',SECRET,query={'sni':'matrix.invalid','ports':'19443-19445','insecure':1,'pinSHA256':'ab'*32}), 'hysteria2.name hysteria2.server hysteria2.port hysteria2.auth hysteria2.sni hysteria2.ports hysteria2.allowInsecure hysteria2.pinSHA256', ['hysteria2.ports'])
    add('anytls', uri('anytls',SECRET,query={'sni':'matrix.invalid','insecure':1}), 'anytls.name anytls.server anytls.port anytls.auth anytls.sni anytls.allowInsecure')
    for scheme in ('http','https','socks5'):
        prefix='http' if scheme=='https' else scheme
        add(scheme, uri(scheme,'synthetic-user',SECRET,port=18082), ' '.join(prefix+'.'+f for f in ('host','port','username','password','name')) + (' http.protocol' if prefix=='http' else ''))
    body={'protocol':'vmess','ps':'Matrix','add':HOST,'port':19444,'id':UUID,'aid':0,'net':'ws','type':'','host':'matrix.invalid','path':'/fixture','tls':'tls','allowInsecure':True,'alpn':'http/1.1','sni':'matrix.invalid','scy':'chacha20-poly1305','v':'2'}
    add('vmess-ws','vmess://'+b64(json.dumps(body,separators=(',',':'))), 'v2ray.protocol v2ray.ps v2ray.add v2ray.port v2ray.id v2ray.aid v2ray.net v2ray.type v2ray.host v2ray.path v2ray.tls v2ray.allowInsecure v2ray.alpn v2ray.sni v2ray.scy', ['v2ray.scy'])
    add('vless-grpc',uri('vless',UUID,query={'type':'grpc','security':'tls','host':'matrix.invalid','headerType':'none','sni':'matrix.invalid','flow':'','allowInsecure':True,'serviceName':'fixture','mode':'multi','authority':'authority.invalid','alpn':'h2','ech':'AAECAw=='}), 'v2ray.protocol v2ray.net v2ray.tls v2ray.host v2ray.type v2ray.sni v2ray.flow v2ray.allowInsecure v2ray.path v2ray.grpcMode v2ray.grpcAuthority v2ray.alpn v2ray.ech', ['v2ray.allowInsecure','v2ray.grpcMode','v2ray.grpcAuthority','v2ray.ech'])
    add('vless-reality',uri('vless',UUID,query={'type':'tcp','security':'reality','headerType':'none','sni':'matrix.invalid','flow':'xtls-rprx-vision','fp':'firefox','pbk':base64.urlsafe_b64encode(bytes(range(1,33))).decode().rstrip('='),'sid':'1234abcd','spx':'/fixture','pqv':'synthetic-pqv'}), 'v2ray.flow v2ray.fp v2ray.pbk v2ray.sid v2ray.spx v2ray.pqv', ['v2ray.pqv'])
    add('vless-xhttp',uri('vless',UUID,query={'type':'xhttp','security':'none','host':'matrix.invalid','path':'/fixture','mode':'packet-up','extra':'{"scMaxEachPostBytes":4096}'}), 'v2ray.net v2ray.xhttpMode v2ray.xhttpExtra', ['v2ray.net','v2ray.xhttpMode','v2ray.xhttpExtra'])
    return values


def config_classification(case):
    """Called only after the real API/readback/validate/apply chain passed.

    URI preservation is CONFIG_PASS, never a remote-protocol runtime claim.
    Known ignored fields retain their existing pinned source findings.
    """
    ignored = case['sourceIgnored']
    if not ignored:
        return {'result':'CONFIG_PASS', 'runtimeEvidence':'NOT_CLAIMED_CONFIG_CHAIN_ONLY'}
    import hashlib
    doc = Path(__file__).resolve().parents[2]/'docs/WEB-FIELD-MATRIX.md'
    body = doc.read_bytes(); text = body.decode()
    sections = []; owners = set()
    for field in ignored:
        heading = '### node.'+field+'\n'
        need(heading in text, 'PINNED_IGNORED_FIELD_EVIDENCE_MISSING')
        section = text.split(heading,1)[1].split('\n### ',1)[0]
        owner = next((o for o in ('official DAE','official daed')
                      if section.lstrip().startswith('Owner: '+o+'. Locked version:')), None)
        need(owner is not None and 'Source evidence:' in section
             and ('https://github.com/' in section or
                  ('official wing `dc503088945812c11235b35362d2bfa1a4c3bdf0`' in section
                   and '`db/node_utils.go`' in section)), 'PINNED_IGNORED_FIELD_EVIDENCE_INVALID')
        owners.add(owner)
        sections.append({'field':field,'section':heading.strip(),
            'owner':owner,'sectionSha256':hashlib.sha256(section.encode()).hexdigest()})
    need(len(owners)==1, 'PINNED_IGNORED_FIELD_MIXED_OWNERS')
    return {'result':'FAIL','owner':next(iter(owners)),
        'reason':'PINNED_TARGET_PARSER_IGNORES_VISIBLE_FIELD','failedFields':ignored,
        'runtimeEvidence':'NOT_CLAIMED_PINNED_SOURCE_FINDING',
        'sourceEvidence':{'file':'docs/WEB-FIELD-MATRIX.md',
            'sha256':hashlib.sha256(body).hexdigest(),'sections':sections}}


def import_rejection_classification(case, stage, exc):
    """Classify only the witnessed pinned xhttp import rejection; retain FAIL."""
    expected = 'GRAPHQL_REJECTED:["create vle[REDACTED_URI] unexpected field: network: xhttp"]'
    if (case != next(c for c in cases() if c['id'] == 'vless-xhttp')
            or stage != 'import' or type(exc) is not RuntimeError
            or str(exc) != expected):
        return {}
    root = Path(__file__).resolve().parents[2]
    lock_bytes = (root/'upstream.lock.json').read_bytes()
    lock = json.loads(lock_bytes)['components']['daed']
    need(lock['version'] == 'v2.1.1' and
         lock['commit'] == 'b3043aa7ce07c774c65e546112aa2c7a1c12edb5',
         'PINNED_IMPORT_REJECTION_VERSION_MISMATCH')
    finding = config_classification(case)
    need(finding['owner'] == 'official daed' and all(
        section['owner'] == 'official daed'
        for section in finding['sourceEvidence']['sections']),
        'PINNED_IMPORT_REJECTION_OWNER_MISMATCH')
    import hashlib
    return {'owner':'official daed', 'failedFields':case['sourceIgnored'],
        'runtimeEvidence':'NOT_CLAIMED_OFFICIAL_IMPORT_REJECTED',
        'classificationReason':'PINNED_OFFICIAL_XHTTP_IMPORT_REJECTION',
        'sourceEvidence':{**finding['sourceEvidence'],
            'lockFile':'upstream.lock.json',
            'lockSha256':hashlib.sha256(lock_bytes).hexdigest(),
            'officialVersion':lock['version'],'officialCommit':lock['commit'],
            'operation':'importNodes','observedError':str(exc)}}


class Nodes(Matrix):
    def __init__(self):
        super().__init__()
        self.path=scope_file(Path('/evidence/node-continuation.json'))
        self.records=json.loads(self.path.read_text()) if self.path.exists() else []

    def save(self):
        temp=self.path.with_suffix('.new')
        temp.write_text(json.dumps(self.records,indent=2)+'\n');temp.replace(self.path)

    def node(self, case):
        if any(r['id']==case['id'] and r.get('baselineRestored') is True and r.get('result') in {'PASS','CONFIG_PASS','RUNTIME_PASS'} for r in self.records):return
        record={**case,'result':None,'stage':'import'}
        self.records.append(record);self.save();node=None;group=None
        try:
            response=self.api('mutation($args:[ImportArgument!]!){importNodes(rollbackError:true,args:$args){node{id} error}}',{'args':[{'link':case['link'],'tag':'matrix-synthetic'}]})['importNodes'][0]
            need(not response.get('error') and response.get('node'),'OFFICIAL_IMPORT_REJECTED')
            node=response['node']['id'];record['nodeID']=node
            source,proof=collect(self.reader)
            observed=next(n for n in source['nodes'] if n['id']==node)
            record.update(readback=observed,doubleSnapshot=proof)
            need(observed['link']==case['link'],'OFFICIAL_NODE_URI_CHANGED')
            group=self.api('mutation{createGroup(name:"matrix_protocol",policy:fixed,policyParams:[{key:"",val:"0"}]){id}}')['createGroup']['id']
            self.api('mutation($id:ID!,$ids:[ID!]!){groupAddNodes(id:$id,nodeIDs:$ids)}',{'id':group,'ids':[node]})
            need(self.api('{general{dae{modified}}}')['general']['dae']['modified'] is True,'MODIFIED_NOT_SET')
            record['stage']='validate-apply';self.save()
            applied,candidate=self.apply()
            need(json.dumps(case['link'],ensure_ascii=False) in candidate,'CANDIDATE_URI_CHANGED')
            record.update(candidate=candidate,applied=applied,configChainPassed=True,
                          **config_classification(case))
        except Exception as exc:
            record.update(result='FAIL',errorType=type(exc).__name__,reason=str(exc).replace(self.token,'[REDACTED]'))
            record.update(import_rejection_classification(case, record['stage'], exc))
        finally:
            # Keep the original result even if a later cleanup/apply fails.
            # Restoration is an independent gate, never evidence of success.
            self.save()
            if group:self.api('mutation($id:ID!){removeGroup(id:$id)}',{'id':group})
            if node:self.api('mutation($ids:[ID!]!){removeNodes(ids:$ids)}',{'ids':[node]})
            restored,_=collect(self.reader)
            need(restored==self.source,'BASELINE_SOURCE_CHANGED')
            evidence,_=self.apply()
            record.update(baselineRestored=True,baselineRestore=evidence,stage='restored');self.save()
            print(case['id']+': '+str(record['result'] or 'CONFIG_CHAIN_ONLY'),flush=True)


def main():
    need(bool(read_completion('baseline-ready')),'VM_BASELINE_NOT_READY')
    need(Path('/sys/class/net/lan0').is_dir(),'VM_LAN_MISSING')
    matrix=Nodes()
    for case in cases():matrix.node(case)

if __name__=='__main__':main()
