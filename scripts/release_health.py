"""Read-only real service, authenticated Web and UDP/TCP DNS checks."""
import hashlib
import http.cookiejar
import ipaddress
import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

CFG=Path('/etc/daed-independent-bridge')


def need(value, code):
    if not value: raise RuntimeError(code)


def dns(address, port, qname, tcp):
    args=['/usr/bin/dig','@'+address,'-p',str(port),qname,'A','+time=3','+tries=1']
    if tcp: args.append('+tcp')
    r=subprocess.run(args,capture_output=True,text=True,timeout=5)
    need(r.returncode==0 and 'status: NOERROR,' in r.stdout and
         any(len(row.split())>=5 and row.split()[-2]=='A' for row in r.stdout.splitlines() if not row.startswith(';')),
         'DNS_QUERY_FAILED')


def web_status(config, token):
    origin=config['origin']
    ctx=ssl.create_default_context(cafile=str(CFG/'tls.crt'))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx),
                                      urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def query(path, data=None, csrf=None):
        headers={'Origin':origin}
        if data is not None: headers['Content-Type']='application/json'
        if csrf: headers['X-CSRF-Token']=csrf
        request=urllib.request.Request(origin+path,headers=headers,
                    data=None if data is None else json.dumps(data).encode())
        return json.load(opener.open(request,timeout=75))
    try:
        query('/api/status')
    except urllib.error.HTTPError as e:
        need(e.code==401 and json.load(e)=={'error':'UNAUTHORIZED'},'WEB_ANONYMOUS_DISCLOSURE')
    else: raise RuntimeError('WEB_ANONYMOUS_DISCLOSURE')
    challenge=query('/api/challenge')['csrf']
    session=query('/api/login',{'token':token},challenge)
    try: return query('/api/status')['data']
    finally: query('/api/logout',{},session['csrf'])


def check():
    sys.path[:0]=['/opt/bridge','/opt/bridge/vendor']
    from bridge_m4.attestor import identity
    from bridge_m4.authority import manifest
    from bridge_m4.dns_sync_runtime import read_status
    from bridge_m4.release_dns import Backends
    from bridge_m4.dns_sync import decide
    manifest();identity()  # includes official hash and literal --api-only argv
    status,expected=read_status()
    need(status.get('state')=='running' and status.get('identityVerified') is True,'DAE_IDENTITY')
    need(status.get('configSha256')==expected,'CONFIG_HASH')
    backends=Backends().states()
    decision=decide(status,expected,backends)
    need(decision['consistent'] and backends=={'DAE':'UP','DIRECT':'DOWN'},'DNS_SYNC_STATE')
    config=json.loads((CFG/'health.json').read_text())
    need(set(config)=={'lanAddress','dnsName'},'HEALTH_CONFIG_SCHEMA')
    address=str(ipaddress.IPv4Address(config['lanAddress']))
    name=config['dnsName']
    need(type(name) is str and 0<len(name)<=253 and all(c.isalnum() or c in '.-' for c in name),'DNS_NAME')
    for server,port in ((address,53),('127.0.0.1',5353)):
        for tcp in (False,True): dns(server,port,name,tcp)
    web=web_status(json.loads((CFG/'web.json').read_text()),(CFG/'attestor.token').read_text().strip())
    for field in ('state','identityVerified','activeBundle','configSha256','MainPID','InvocationID'):
        need(field in web and web[field]==status[field],'WEB_STATUS_IDENTITY')
    # Do not print any token, node, config contents, cookie or source snapshot.
    print(json.dumps({'passed':True,'daedApiOnly':True,'bridge':True,'dae':True,
                      'DNS':'UDP_TCP_PASS','DAE':'UP','DIRECT':'DOWN','consistent':True,
                      'webIdentityMatches':True}))
