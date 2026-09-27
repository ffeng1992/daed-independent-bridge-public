"""Generic ordered-domain portion of the existing local build_dns generator.

Site providers, private PTR suffixes, fixed groups and ingress hosts are omitted.
Unknown domain expressions fail closed. No database access or lifecycle control.
"""
import json
import re
from pathlib import Path


def need(ok):
    if not ok: raise ValueError('UNSUPPORTED_DNS_POLICY')


def fields(body):
    def var(i):
        n=0
        for shift in range(0,70,7):
            need(i<len(body));v=body[i];i+=1;n|=(v&127)<<shift
            if v<128:return n,i
        raise ValueError('INVALID_GEODATA')
    i=0
    while i<len(body):
        tag,i=var(i);typ=tag&7;k=tag>>3
        if typ==0:v,i=var(i)
        elif typ==2:n,i=var(i);need(i+n<=len(body));v=body[i:i+n];i+=n
        elif typ in (1,5):n=8 if typ==1 else 4;need(i+n<=len(body));v=body[i:i+n];i+=n
        else:raise ValueError('INVALID_GEODATA')
        yield k,v


def sites(geo,category):
    for key,value in fields(geo.read_bytes()):
        if key!=1:continue
        fs=list(fields(value));name=next((v.decode() for k,v in fs if k==1),'')
        if name.lower()!=category.lower():continue
        result=[]
        for k,v in fs:
            if k==2:
                f=dict(fields(v));result.append((f.get(1,0),f[2].decode()))
        need(bool(result));return result
    raise ValueError('GEOSITE_CATEGORY_MISSING')


def generate(routing,providers,geo):
    need(type(providers) is dict and 'direct' in providers)
    lines=['setLocal("127.0.0.1:5534")','setACL({"127.0.0.0/8"})','setServerPolicy(firstAvailable)','setServFailWhenNoServer(true)']
    for group,address in sorted(providers.items()):
        need(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*',group))
        # Addresses have already been validated as IPv4:port by installation.
        import ipaddress
        host,port=address.rsplit(':',1);ipaddress.IPv4Address(host);need(0<int(port)<65536)
        lines.append('newServer({address='+json.dumps(address)+',pool='+json.dumps(group)+'})')
    fallback=None
    def action(rule,group):
        need(group=='block' or group in providers)
        target='RCodeAction(DNSRCode.REFUSED)' if group=='block' else 'PoolAction('+json.dumps(group)+')'
        lines.append('addAction('+rule+','+target+')')
    for line in routing.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        f=re.fullmatch(r'fallback:\s*([A-Za-z_][A-Za-z0-9_.-]*)',line)
        if f:fallback=f[1];continue
        m=re.fullmatch(r'domain\((.*)\)\s*->\s*([A-Za-z_][A-Za-z0-9_.-]*)',line)
        if not m:
            need('domain(' not in line);continue  # Non-domain dataplane rules stay in DAE.
        expr,group=m.groups()
        parsed=re.fullmatch(r"(geosite|suffix|full|keyword|regex):\s*(\"(?:[^\"\\]|\\.)*\"|'[^']*'|[A-Za-z0-9_.-]+)",expr)
        need(parsed is not None)
        kind,value=parsed.groups()
        value=json.loads(value) if value.startswith('"') else value.strip("'")
        if kind=='geosite':
            for typ,name in sites(geo,value):
                need(typ in (0,1,2,3))
                rule=('QNameSuffixRule('+json.dumps(name)+')' if typ==2 else
                      'QNameRule('+json.dumps(name)+')' if typ==3 else
                      'RegexRule('+json.dumps(re.escape(name) if typ==0 else name)+')')
                action(rule,group)
        else:
            need(kind in ('suffix','full','keyword','regex'))
            rule={'suffix':'QNameSuffixRule','full':'QNameRule','keyword':'RegexRule','regex':'RegexRule'}[kind]
            action(rule+'('+json.dumps(re.escape(value) if kind=='keyword' else value)+')',group)
    need(fallback is not None);action('AllRule()',fallback)
    return ('\n'.join(lines)+'\n').encode()
