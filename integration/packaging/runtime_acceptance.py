"""Bounded synthetic CRUD and AST control acceptance inside disposable Debian."""
import base64
import json
from pathlib import Path
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from scripts.release_setup import CFG, need, connect


def run(checks):
    from integration.packaging import onboarding
    token=''
    def api(q,v=None):
        h={'Content-Type':'application/json'}
        if token:h['Authorization']='Bearer '+token
        req=urllib.request.Request('http://'+json.loads((CFG/'web.json').read_text())['address']+':2023/graphql',data=json.dumps({'query':q,'variables':v or {}}).encode(),headers=h)
        with urllib.request.urlopen(req,timeout=240) as response:value=json.load(response)
        if value.get('errors'):
            from graphql import parse
            from scripts.redact import redact
            names=[x.name.value for d in parse(q).definitions if hasattr(d,'selection_set') for x in d.selection_set.selections if hasattr(x,'name')]
            message=redact(json.dumps([e.get('message','') for e in value['errors']]))
            for secret in (token,onboarding.PASSWORD,'Synthetic-314159','Synthetic-271828'):
                if secret:message=message.replace(secret,'[REDACTED]')
            raise RuntimeError('RUNTIME_GRAPHQL_REJECTED:'+','.join(names)+':'+message)
        return value['data']
    def passed(name):
        checks.append({'case':name,'passed':True});print(name+': PASS',flush=True)
    token=api('query($u:String!,$p:String!){token(username:$u,password:$p)}',{'u':onboarding.USERNAME,'p':onboarding.PASSWORD})['token']
    fresh='Synthetic-271828'
    token=api('mutation($old:String!,$new:String!){updatePassword(currentPassword:$old,newPassword:$new)}',{'old':onboarding.PASSWORD,'new':fresh})['updatePassword']
    onboarding.PASSWORD=fresh
    token=api('query($u:String!,$p:String!){token(username:$u,password:$p)}',{'u':onboarding.USERNAME,'p':fresh})['token']
    connect(token);passed('official-password-update-and-login')
    link='ss://'+base64.urlsafe_b64encode(b'aes-128-gcm:SyntheticOnly').decode().rstrip('=')+'@192.0.2.99:8388#Synthetic'
    n=api('mutation($a:[ImportArgument!]!){importNodes(rollbackError:true,args:$a){node{id} error}}',{'a':[{'link':link}]})['importNodes'][0]
    need(not n.get('error') and n.get('node'),'NODE_IMPORT');node=n['node']['id']
    api('mutation($id:ID!,$s:String!){updateNode(id:$id,newLink:$s){id}}',{'id':node,'s':link+'-edited'})
    class Subscription(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write((link+'-subscription\n').encode())
        def log_message(self,*_):pass
    server=HTTPServer(('127.0.0.1',18081),Subscription);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        sub=api('mutation{importSubscription(rollbackError:true,arg:{link:"http://127.0.0.1:18081/synthetic",tag:"synthetic"}){sub{id} nodeImportResult{error}}}')['importSubscription']
        need(sub.get('sub') and all(not x.get('error') for x in sub['nodeImportResult']),'SUB_IMPORT');sid=sub['sub']['id']
        api('mutation($id:ID!){updateSubscription(id:$id){id}}',{'id':sid})
        group=api('mutation{createGroup(name:"synthetic-crud",policy:min){id}}')['createGroup']['id']
        api('mutation($id:ID!){renameGroup(id:$id,name:"synthetic-renamed")}',{'id':group})
        for operation,key,ident in [('groupAddNodes','nodeIDs',node),('groupDelNodes','nodeIDs',node),('groupAddSubscriptions','subscriptionIDs',sid),('groupDelSubscriptions','subscriptionIDs',sid)]:
            api('mutation($id:ID!,$ids:[ID!]!){'+operation+'(id:$id,'+key+':$ids)}',{'id':group,'ids':[ident]});passed(operation)
        api('mutation($id:ID!){groupSetPolicy(id:$id,policy:random)}',{'id':group});passed('group-policy-change')
        api('mutation($id:ID!){removeGroup(id:$id)}',{'id':group});passed('group-create-rename-delete')
        api('mutation($ids:[ID!]!){removeSubscriptions(ids:$ids)}',{'ids':[sid]});passed('subscription-import-update-delete')
        api('mutation($ids:[ID!]!){removeNodes(ids:$ids)}',{'ids':[node]});passed('node-create-edit-delete')
    finally:server.shutdown();server.server_close()
    from bridge_m4.collect import collect
    from bridge_m1.collect import HTTPReader
    source,_=collect(HTTPReader('http://127.0.0.1:2024/graphql',token))
    glob=next(x['global'] for x in source['metadata']['configs'] if x['selected'])
    glob=dict(glob,logLevel='debug')
    cid=api('mutation($g:globalInput!){createConfig(name:"Runtime edited",global:$g){id}}',{'g':glob})['createConfig']['id']
    api('mutation($id:ID!,$g:globalInput!){updateConfig(id:$id,global:$g){id}}',{'id':cid,'g':dict(glob,logLevel='info')})
    dns=next(x['dns']['string'] for x in source['metadata']['dnss'] if x['selected'])
    did=api('mutation($s:String!){createDns(name:"Runtime DNS",dns:$s){id}}',{'s':dns})['createDns']['id']
    api('mutation($id:ID!,$s:String!){updateDns(id:$id,dns:$s){id}}',{'id':did,'s':dns+'\n'})
    rid=api('mutation{createRouting(name:"Runtime routing",routing:"fallback: direct"){id}}')['createRouting']['id']
    api('mutation($id:ID!,$s:String!){updateRouting(id:$id,routing:$s){id}}',{'id':rid,'s':'dip(192.0.2.0/24) -> direct\nfallback: direct'})
    for kind,ident in [('Config',cid),('Dns',did),('Routing',rid)]:
        api('mutation($id:ID!){select'+kind+'(id:$id)}',{'id':ident});passed(kind.lower()+'-create-update-select')
    need(api('{general{dae{modified}}}')['general']['dae']['modified'] is True,'MODIFIED_NOT_SET');passed('modified-after-edit')
    # Reuse the authorized bridge connection; collect receipt naturally before Run.
    from scripts.release_setup import client
    preview=client('import json;from bridge_m4.runtime import Runtime;r=Runtime();t=json.load(sys.stdin);p=r.preview(t);v=r.validate(p["previewId"]);print(json.dumps({"preview":p,"validate":v}))',token)
    need(preview['validate']['validated'],'VALIDATE');passed('preview-and-official-validate')
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        p=Path('/var/lib/bridge-m4-attestation/receipt.json')
        if p.exists() and json.loads(p.read_text())['sourceSha256']==preview['preview']['sourceFingerprint']:break
        time.sleep(1)
    else:raise RuntimeError('RECEIPT_NOT_CURRENT')
    before=client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().status()))',{})
    api('mutation{run(dry:false)}');passed('AST-run-independent-DAE')
    after=client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().status()))',{})
    need(after['activeBundle']!=before['activeBundle'] and after['configSha256']==preview['preview']['candidateSha256'] and after['identityVerified'],'APPLY_IDENTITY')
    need(api('{general{dae{modified running version}}}')['general']['dae']=={'modified':False,'running':True,'version':'v2.1.1'},'RUNTIME_AFTER_APPLY');passed('bundle-config-modified-after-apply')
    api('mutation{run(dry:true)}')
    need(api('{general{dae{running version}}}')['general']['dae']=={'running':False,'version':'v2.1.1'},'STOP');passed('AST-stop-independent-DAE')
    # Real UI use: a profile can change while the independent DAE is stopped.
    api('mutation($id:ID!,$g:globalInput!){updateConfig(id:$id,global:$g){id}}',{'id':cid,'g':dict(glob,logLevel='debug')})
    need(api('{general{dae{modified}}}')['general']['dae']['modified'],'STOPPED_EDIT_NOT_VISIBLE')
    deadline=time.monotonic()+90
    changed=client('import json;from bridge_m4.runtime import Runtime;r=Runtime();print(json.dumps(r.preview(json.load(sys.stdin))))',token)
    while time.monotonic()<deadline:
        if json.loads(Path('/var/lib/bridge-m4-attestation/receipt.json').read_text())['sourceSha256']==changed['sourceFingerprint']:break
        time.sleep(1)
    else:raise RuntimeError('CHANGED_RECEIPT_NOT_CURRENT')
    api('mutation{run(dry:false)}')
    need(api('{general{dae{running modified}}}')['general']['dae']=={'running':True,'modified':False},'RESTART_CHANGED')
    passed('AST-run-after-stopped-config-change')
    from scripts.release_web_health import unique_dataplane,check_dashboard
    from bridge_m4.attestor import identity
    state=client('import json;from bridge_m4.runtime import Runtime;print(json.dumps(Runtime().status()))',{})
    unique_dataplane(identity()['MainPID'],state['MainPID']);check_dashboard();passed('api-only-single-data-plane-official-web')
    pin=json.loads(Path('/opt/bridge/upstream.lock.json').read_text())['webFrontend']
    import hashlib
    need(all(hashlib.sha256((Path('/opt/bridge-daed-web')/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in pin['files']),'OFFICIAL_WEB_CHANGED');passed('official-483-assets-unchanged')
    if Path('/evidence/browser-enabled').exists():
        Path('/evidence/browser-ready').write_text(json.dumps({'username':onboarding.USERNAME,'password':'SYNTHETIC_FROM_TEST_SOURCE','webPort':12023}))
        deadline=time.monotonic()+1800
        while not Path('/evidence/browser-complete').exists():
            need(time.monotonic()<deadline,'BROWSER_ACCEPTANCE_TIMEOUT');time.sleep(1)
        passed('real-browser-acceptance')
