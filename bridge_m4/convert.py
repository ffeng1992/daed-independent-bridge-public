"""Private compatibility candidate, typed source -> IR -> immutable DAE text.

This converter is not authorized for M2 apply until its M4 contracts pass.
"""
import base64
import copy
from dataclasses import dataclass
import json
import re
from decimal import Decimal
from .extensions import need,merge,split,statements,validate_record,MODELS,render_value
from .document import parse
from bridge_m1.common import canonical,digest,ROOT

VERSION='0.2-m4-empty-groups'
FIELDS=json.loads((ROOT/'contracts/global-fields.json').read_text())['fields']
PROTOCOLS=json.loads((ROOT/'contracts/m4/protocol-models.json').read_text())['target']['entries']
SCHEMES={s for entry in PROTOCOLS for s in entry['schemes']}
PROTOCOL_LABELS=SCHEMES|{s for entry in PROTOCOLS for s in entry['protocolLabels']}

def cursor(ident):return base64.b64encode(('cursor'+ident).encode()).decode().rstrip('=')
def quote(value):return json.dumps(value,ensure_ascii=False)
def decode(raw):
    raw=raw.strip()
    if raw.startswith('"'):
        try:return json.loads(raw)
        except ValueError:need(False,'INVALID_SCALAR','global')
    if raw.startswith("'") and raw.endswith("'"):return raw[1:-1]
    return raw

def duration(value):
    if value in ('0','0s'):return Decimal(0)
    pattern=r'(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)'
    matches=list(re.finditer(pattern,value));need(''.join(m[0] for m in matches)==value,'INVALID_DURATION','global')
    units={'ns':Decimal('.000000001'),'us':Decimal('.000001'),'µs':Decimal('.000001'),'ms':Decimal('.001'),'s':Decimal(1),'m':Decimal(60),'h':Decimal(3600)}
    return sum((Decimal(m[1])*units[m[2]] for m in matches),Decimal(0))

def global_document(config,record):
    view=validate_record(record,'global');original={};spans={}
    for key,start,end,kind in statements(view,'global'):
        need(kind==':','INVALID_GLOBAL_FIELD','global.'+key)
        original[key]=decode(view[start:end].split(':',1)[1]);spans[key]=(start,end)
    specs=MODELS['source']['models']['Global']
    need(set(config['global'])=={f['graphql'] for f in FIELDS},'GLOBAL_SCHEMA_DRIFT','global')
    replacements=[];additions=[];changes=[]
    for field in FIELDS:
        key=field['dae'];actual=config['global'][field['graphql']];typ=specs[key]['type']
        if key=='so_mark_from_dae_set':continue
        mark_presence_change=False
        if key=='so_mark_from_dae':
            present=config['global']['soMarkFromDaeSet']
            need(type(present) is bool,'INVALID_SCALAR','global.so_mark_from_dae_set')
            if not present:
                if key in spans:
                    replacements.append((*spans[key],''));changes.append({'path':'global.'+key,'sourcePresent':True,'reason':'DAED_EXPLICIT_MARK_CLEARED'})
                continue
            mark_presence_change=key not in original
        if key in original:raw=original[key]
        else:
            default=specs[key]['default']
            raw=default if default is not None else ('false' if typ=='bool' else '0' if typ.startswith('uint') or typ=='time.Duration' else '')
        if typ=='bool':
            need(type(actual) is bool and raw in ('true','false'),'INVALID_SCALAR','global.'+key);expected=raw=='true'
        elif typ.startswith('uint'):
            need(type(actual) is int and 0<=actual<2**(16 if typ=='uint16' else 32),'INVALID_SCALAR','global.'+key)
            expected=int(raw,0) if raw.startswith('0x') else int(raw)
        elif typ=='[]string':
            need(isinstance(actual,list) and all(type(x) is str for x in actual),'INVALID_SCALAR','global.'+key);expected=[] if raw=='' else raw.split(',')
        elif typ=='time.Duration':
            need(type(actual) is str,'INVALID_SCALAR','global.'+key);expected=duration(raw)
        else:
            need(type(actual) is str,'INVALID_SCALAR','global.'+key);expected=raw
        comparable=duration(actual) if typ=='time.Duration' else actual
        if expected==comparable and not mark_presence_change:continue
        # Presence flag is official parser metadata, not a value to override.
        if key=='so_mark_from_dae_set' and key not in original:continue
        rendered=str(actual).lower() if type(actual) in (bool,int) else quote(','.join(actual) if type(actual) is list else actual)
        line='  '+key+': '+rendered+'\n'
        if key in spans:replacements.append((*spans[key],line))
        else:additions.append(line)
        changes.append({'path':'global.'+key,'sourcePresent':key in original,'reason':'DAED_MANAGED_VALUE_CHANGED'})
    for start,end,line in sorted(replacements,reverse=True):view=view[:start]+line+view[end:]
    if additions:
        end=view.rfind('}');view=view[:end]+''.join(additions)+view[end:]
    return parse(merge(view,record),'global'),changes

@dataclass(frozen=True)
class IR:
    source_sha256:str
    globals:object
    dns:object
    routing:object
    nodes:tuple
    groups:tuple
    source:dict
    extensions:dict
    compatibility_defaults:tuple
    def json(self):
        return {'converterVersion':VERSION,'sourceFingerprint':self.source_sha256,
                'classification':'REGENERATED_INDEPENDENT_BRIDGE_OUTPUT',
                'global':self.globals.json(),'dns':self.dns.json(),'routing':self.routing.json(),
                'nodes':[{**n,'active':any(n['alias'] in g['members'] for g in self.groups)} for n in self.nodes],'groups':list(self.groups),'source':self.source,
                'extensions':self.extensions,'compatibilityDefaults':list(self.compatibility_defaults),'unsupported':[]}

def bind_new_profiles(source,extensions):
    """Create absent extension states for new official GraphQL profiles.

    Existing imported records retain raw source presence. New global profiles
    record API-effective values explicitly (GraphQL does not expose raw absence).
    """
    result=copy.deepcopy(extensions)
    for kind,section in [('configs','global'),('dnss','dns'),('groups','group')]:
        records=result['records'].setdefault(section,{})
        for profile in source['metadata'][kind]:
            encoded=profile['id']
            try:decoded=base64.b64decode(encoded+'='*((-len(encoded))%4),validate=True).decode()
            except (ValueError,UnicodeError):need(False,'INVALID_PROFILE_ID','profile')
            need(bool(re.fullmatch(r'cursor[0-9]+',decoded)),'INVALID_PROFILE_ID','profile')
            identity=decoded[6:]
            if identity in records:continue
            if section=='global':
                text='global {\n'+''.join(' '+f['dae']+': '+render_value(profile['global'][f['graphql']])+'\n' for f in FIELDS if f['dae']!='so_mark_from_dae_set' and (f['dae']!='so_mark_from_dae' or profile['global']['soMarkFromDaeSet']))+'}\n'
            elif section=='dns':text='dns {\n'+profile['dns']['string']+'\n}\n'
            else:text='group {\n}\n'
            _,records[identity]=split(text,section)
    return result

def normalize(source,extensions):
    metadata=source['metadata']
    need(extensions['daedVersion']=='v2.1.1','VERSION_MISMATCH','extensions')
    selected={}
    for kind in ('configs','dnss','routings'):
        active=[o for o in metadata[kind] if o['selected']]
        need(len(active)==1,'INVALID_SELECTION',kind);selected[kind]=active[0]
    records={section:{cursor(i):record for i,record in items.items()} for section,items in extensions['records'].items()}
    config=selected['configs'];dns=selected['dnss'];routing=selected['routings']
    need(config['id'] in records['global'] and dns['id'] in records['dns'],'UNBOUND_PROFILE','profile')
    glob,known_changes=global_document(config,records['global'][config['id']])
    dns_text=merge('dns {\n'+dns['dns']['string']+'\n}',records['dns'][dns['id']])
    from .runtime_models import model,DEFAULTS
    runtime_model=model(extensions);effective=DEFAULTS[runtime_model]
    defaults=list(known_changes)
    if not records['global'][config['id']]['fields']['auto_sniff_punt']['present']:
        text=glob.render();end=text.rfind('}')
        value=effective['global.auto_sniff_punt']
        glob=parse(text[:end]+'  auto_sniff_punt: '+str(value).lower()+'\n'+text[end:],'global')
        defaults.append({'path':'global.auto_sniff_punt','sourcePresent':False,'emittedValue':value,'reason':'PINNED_SOURCE_RUNTIME_DEFAULT','sourceRuntimeModel':runtime_model})
    # Emit documented effective defaults without changing raw presence in IR.
    explicit={key for key,*_ in statements(dns_text,'dns')}
    for key in ('max_cache_size','optimistic_stale_reply_ttl'):
        value=effective['dns.'+key]
        if key not in explicit:
            end=dns_text.rfind('}');dns_text=dns_text[:end]+'  '+key+': '+str(value)+'\n'+dns_text[end:]
            defaults.append({'path':'dns.'+key,'sourcePresent':False,'emittedValue':value,'reason':'PINNED_SOURCE_RUNTIME_DEFAULT','sourceRuntimeModel':runtime_model})
    dnsdoc=parse(dns_text,'dns')
    routedoc=parse('routing {\n'+routing['routing']['string']+'\n}','routing')
    nodes={n['id']:n for n in source['nodes']};aliases={};outnodes=[]
    for ident,node in sorted(nodes.items()):
        need(node['protocol'] in PROTOCOL_LABELS,'UNSUPPORTED_TARGET_NODE_PROTOCOL','nodes.protocol')
        for layer in node['link'].split('->'):
            match=re.match(r'^([a-z0-9+.-]+)://',layer.strip())
            need(match is not None and match[1] in SCHEMES,'UNSUPPORTED_TARGET_URI_SCHEME','nodes.link')
        alias='n_'+digest(ident.encode())[:24]
        need(alias not in aliases.values(),'NODE_ALIAS_COLLISION','nodes.id');aliases[ident]=alias
        outnodes.append({'id':ident,'alias':alias,'link':node['link'],'protocol':node['protocol'],'subscriptionId':node['subscriptionID']})
    groups=[];names=set();subscriptions={s['id'] for s in metadata['subscriptions']}
    for group in metadata['groups']:
        name=group['name'];need(bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*',name)),'INVALID_GROUP_IDENTIFIER','groups.name')
        need(name not in names and name not in ('direct','block','must_rules'),'DUPLICATE_GROUP_NAME','groups.name');names.add(name)
        members=[]
        for binding in group['subscriptions']:
            sid=binding['subscription']['id'];need(sid in subscriptions,'MISSING_SUBSCRIPTION','groups.subscriptions')
            need(binding['matchedCount']==len(binding['matchedNodes']),'MATCH_COUNT_MISMATCH','groups.subscriptions')
            for n in binding['matchedNodes']:
                need(n['id'] in nodes and nodes[n['id']]['subscriptionID']==sid,'INVALID_SUBSCRIPTION_MEMBER','groups.subscriptions')
                members.append(n['id'])
        members += [n['id'] for n in group['nodes']]
        need(all(i in nodes for i in members),'MISSING_NODE','groups.nodes')
        # Preserve order and remove only identical node IDs, retaining all source bindings in IR.
        members=list(dict.fromkeys(members))
        # Retain empty groups in source/IR/extensions, but DAE cannot emit them.
        need(bool(members) or name not in routing['referenceGroups'],
             'EMPTY_REFERENCED_GROUP','groups.'+name+'.nodes')
        need(group['policy'] in ('fixed','random','min','min_moving_avg','min_avg10'),'UNREVIEWED_POLICY','groups.policy')
        params=group['policyParams']
        need(all(p['key']=='' or re.fullmatch(r'[a-z_]+',p['key']) for p in params),'INVALID_POLICY_PARAMETER','groups.policyParams')
        groups.append({'id':group['id'],'name':name,'members':[aliases[i] for i in members],'policy':group['policy'],'params':params,'overrides':records.get('group',{}).get(group['id'])})
    need(set(routing['referenceGroups']) <= names|{'direct','block','must_rules'},'MISSING_GROUP','routing.referenceGroups')
    return IR(digest(canonical(source)),glob,dnsdoc,routedoc,tuple(outnodes),tuple(groups),source,extensions,tuple(defaults))

def emit(ir):
    need(isinstance(ir,IR),'IR_REQUIRED','$')
    lines=['# REGENERATED_INDEPENDENT_BRIDGE_OUTPUT','# converter='+VERSION,'# source-sha256='+ir.source_sha256,ir.globals.render().rstrip(),'node {']
    active={member for group in ir.groups for member in group['members']}
    for node in ir.nodes:
        if node['alias'] in active:lines.append('  '+node['alias']+': '+quote(node['link']))
    lines+=['}','group {']
    for group in ir.groups:
        if not group['members']:continue
        policy=group['policy']
        if group['params']:policy+='('+', '.join((p['key']+': ' if p['key'] else '')+quote(p['val']) for p in group['params'])+')'
        lines += ['  '+group['name']+' {','    filter: name('+', '.join(quote(x) for x in group['members'])+')','    policy: '+policy]
        if group['overrides'] is not None:
            record=group['overrides'];validate_record(record,'group')
            for key,state in sorted(record['fields'].items()):
                if state['present']:lines.append('    '+key+': '+render_value(state['value']))
        lines.append('  }')
    lines+=['}',ir.dns.render().rstrip(),ir.routing.render().rstrip(),'']
    return '\n'.join(lines).encode()
