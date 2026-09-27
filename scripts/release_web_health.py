"""Read actual official dashboard assets and authenticated GraphQL via its origin."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import ssl
import urllib.request

CFG=Path('/etc/daed-independent-bridge')

def need(ok,code):
    if not ok:raise RuntimeError(code)


def unique_dataplane(daed_pid,dae_pid):
    seen=set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():continue
        try:
            name=Path(os.readlink(proc/'exe')).name
            if name=='dae' or name.startswith(('dae-linux','daed')):seen.add(int(proc.name))
        except FileNotFoundError:continue
    need(seen=={int(daed_pid),int(dae_pid)},'DAE_DATAPLANE_NOT_UNIQUE')
    listeners=[]
    for name in ('tcp','tcp6'):
        for line in Path('/proc/net',name).read_text().splitlines()[1:]:
            parts=line.split()
            if parts[3]=='0A' and parts[1].endswith(':07E8'):listeners.append(parts[1])
    need(listeners==['0100007F:07E8'],'DAED_BACKEND_NOT_LOOPBACK_ONLY')


def check_dashboard():
    config=json.loads((CFG/'web.json').read_text())
    origin='http://'+str(ipaddress.IPv4Address(config['address']))+':2023'
    pin=json.loads(Path('/opt/bridge/upstream.lock.json').read_text())['webFrontend']
    context=ssl.create_default_context(cafile=str(CFG/'tls.crt'))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
    def get(path):
        with opener.open(origin+path,timeout=20) as response:
            need(response.status==200,'DAED_WEB_HTTP');return response.read()
    for name in ('index.html',next(x['path'] for x in pin['files'] if x['path'].startswith('assets/index-') and x['path'].endswith('.js'))):
        expected=next(x['sha256'] for x in pin['files'] if x['path']==name)
        need(hashlib.sha256(get('/' if name=='index.html' else '/'+name)).hexdigest()==expected,'DAED_WEB_OFFICIAL_ASSET_HASH')
    token=(CFG/'attestor.token').read_text().strip()
    query=json.dumps({'query':'{ configs { id selected } groups { id } }'}).encode()
    def graphql(url):
        request=urllib.request.Request(url,data=query,headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
        with opener.open(request,timeout=20) as response:value=json.load(response)
        need(not value.get('errors') and type(value.get('data')) is dict and
             type(value['data'].get('configs')) is list and type(value['data'].get('groups')) is list,'DAED_WEB_GRAPHQL')
        return value['data']
    need(graphql(origin+'/graphql')==graphql('http://127.0.0.1:2024/graphql'),'DAED_WEB_BACKEND_MISMATCH')
    return {'daedWebHTTP':True,'daedWebOfficialVersion':pin['version'],'daedWebGraphQL':True}
