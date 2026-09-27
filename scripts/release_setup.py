"""First-install settings and official API initialization; never edits an existing DB."""
import base64
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import subprocess
import sys
import time
import urllib.request
CFG=Path('/etc/daed-independent-bridge')


def need(value,code):
    if not value:raise RuntimeError(code)


def settings(path):
    if path:
        value=json.loads(Path(path).read_text())
    else:
        need(sys.stdin.isatty(),'FIRST_INSTALL_SETTINGS_REQUIRED')
        value={k:input(label+': ').strip() for k,label in (
            ('lanAddress','LAN IPv4 address'),('lanNetwork','LAN IPv4 CIDR allowed to query DNS'),('lanInterface','LAN interface'),
            ('upstream','DNS upstream IPv4:port'),('dnsName','Health DNS name with an A record'),
            ('webAddress','Bridge Web listen IPv4'))}
    need(set(value)=={'lanAddress','lanNetwork','lanInterface','upstream','dnsName','webAddress'},'INSTALL_SETTINGS_SCHEMA')
    for key in ('lanAddress','webAddress'):value[key]=str(ipaddress.IPv4Address(value[key]))
    network=ipaddress.IPv4Network(value['lanNetwork'],strict=True)
    need(ipaddress.IPv4Address(value['lanAddress']) in network,'LAN_ADDRESS_OUTSIDE_NETWORK')
    host,port=value['upstream'].rsplit(':',1);ipaddress.IPv4Address(host)
    need(port.isdecimal() and 0<int(port)<65536,'DNS_UPSTREAM')
    need(re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',value['lanInterface']) is not None,'LAN_INTERFACE')
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',value['dnsName']) is not None,'HEALTH_DNS_NAME')
    value['providers']={'direct':value['upstream']}
    return value


def write(path,body,mode=0o600,gid=0):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
    os.chown(path,0,gid)


def api(query,variables=None,token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request('http://127.0.0.1:2024/graphql',
        data=json.dumps({'query':query,'variables':variables or {}}).encode(),headers=headers)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    value=json.load(opener.open(request,timeout=20))
    need(not value.get('errors') and type(value.get('data')) is dict,'DAED_API_SETUP_FAILED')
    return value['data']


def wait(fn,seconds=90):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError,RuntimeError):pass
        time.sleep(1)
    raise RuntimeError('SETUP_TIMEOUT')


def client(code,value):
    prefix='import sys;sys.path[:0]=["/opt/bridge","/opt/bridge/vendor"];'
    p=subprocess.run(['/usr/sbin/runuser','-u','independent-bridge','--','/usr/bin/python3','-I','-c',prefix+code],
                     input=json.dumps(value).encode(),capture_output=True,timeout=150)
    need(p.returncode==0,'BRIDGE_CLIENT_SETUP_FAILED')
    return json.loads(p.stdout) if p.stdout else None


def configure(value):
    gid=pwd.getpwnam('independent-bridge').pw_gid
    write(CFG/'release.json',json.dumps(value).encode())
    write(CFG/'health.json',json.dumps({k:value[k] for k in ('lanAddress','dnsName')}).encode())
    origin='https://'+value['webAddress']+':8443'
    write(CFG/'web.json',json.dumps({'address':value['webAddress'],'port':8443,'origin':origin}).encode(),0o640,gid)
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','365',
                    '-subj','/CN='+value['webAddress'],'-addext','subjectAltName=IP:'+value['webAddress'],
                    '-keyout',str(CFG/'tls.key'),'-out',str(CFG/'tls.crt')],check=True,capture_output=True)
    for name in ('tls.key','tls.crt'):
        (CFG/name).chmod(0o640);os.chown(CFG/name,0,gid)
    key=base64.b64encode(secrets.token_bytes(32)).decode()
    upstream=value['upstream']
    lan='''setLocal(%s)
setACL({%s})
setServerPolicy(firstAvailable)
setServFailWhenNoServer(true)
controlSocket("127.0.0.1:5199")
setKey(%s)
newServer({address="127.0.0.1:5353",name="DAE",order=1})
newServer({address=%s,name="DIRECT",order=2})
getServer(0):setDown()
getServer(1):setUp()
''' % (json.dumps(value['lanAddress']+':53'),json.dumps(value['lanNetwork'])+',"127.0.0.0/8"',json.dumps(key),json.dumps(upstream))
    write(CFG/'lan-dns.conf',lan.encode(),0o640,grp.getgrnam('_dnsdist').gr_gid)
    from bridge_m4.release_policy import generate
    write(CFG/'policy-dns.conf',generate('fallback: direct',value['providers'],Path('/opt/bridge-official/assets/geosite.dat')),0o644)


def initialize():
    value=json.loads((CFG/'release.json').read_text())
    wait(lambda:api('{__typename}'))
    need(api('{numberUsers}')['numberUsers']==0,'EXISTING_DAED_ACCOUNT_REFUSED')
    password=secrets.token_urlsafe(32)
    token=api('mutation($u:String!,$p:String!){createUser(username:$u,password:$p)}',{'u':'admin','p':password})['createUser']
    write(CFG/'initial-admin.json',json.dumps({'username':'admin','password':password}).encode())
    write(CFG/'attestor.token',token.encode())
    # A new official daed DB has no config rows. Send only explicit network
    # settings; createConfig applies upstream defaults, which are subsequently
    # read back through the normal GraphQL double-snapshot conversion.
    global_fields=dict(lanInterface=[value['lanInterface']],wanInterface=[],
        bootstrapResolver=value['upstream'],fallbackResolver=value['upstream'],
        autoConfigKernelParameter=True,disableWaitingNetwork=True)
    config=api('mutation($g:globalInput!){createConfig(name:"Independent bridge",global:$g){id}}',{'g':global_fields},token)['createConfig']['id']
    dns=api('mutation($s:String!){createDns(name:"Independent DNS",dns:$s){id}}',{'s':"bind: 'tcp+udp://127.0.0.1:5353'\nupstream { policy: 'tcp+udp://127.0.0.1:5534' }\nrouting { request { fallback: policy } response { fallback: accept } }"},token)['createDns']['id']
    routing=api('mutation($s:String!){createRouting(name:"Independent direct initial policy",routing:$s){id}}',{'s':'fallback: direct'},token)['createRouting']['id']
    for kind,ident in (('Config',config),('Dns',dns),('Routing',routing)):
        api('mutation($id:ID!){select'+kind+'(id:$id)}',{'id':ident},token)
    from bridge_m4.collect import collect
    from bridge_m1.collect import HTTPReader
    from bridge_m4.convert import bind_new_profiles
    source,proof=collect(HTTPReader('http://127.0.0.1:2024/graphql',token))
    ext=bind_new_profiles(source,{'schemaVersion':1,'classification':'REGENERATED_INDEPENDENT_BRIDGE_INPUT',
        'daedVersion':'v2.1.1','sourceSha256':'0'*64,'databaseSha256':'0'*64,'records':{'global':{},'dns':{},'group':{}}})
    client('import json;from bridge_m4.store import ExtensionStore;ExtensionStore("/var/lib/bridge-m4-client/extensions").commit(json.load(sys.stdin))',ext)


def apply_initial():
    wait(lambda:Path('/var/lib/bridge-m4-attestation/receipt.json').exists())
    token=(CFG/'attestor.token').read_text().strip()
    value=client('import json;from bridge_m4.runtime import Runtime;r=Runtime();t=json.load(sys.stdin);p=r.preview(t);r.validate(p["previewId"]);print(json.dumps(r.apply(t,p["previewId"])))',token)
    need(value.get('result',{}).get('result') in {'APPLIED','ALREADY_APPLIED'},'INITIAL_APPLY_FAILED')
