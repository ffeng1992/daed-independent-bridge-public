"""M4 operational bundles: exact rerender and joint source/extension provenance."""
import os
import time
from pathlib import Path
from bridge_m1.common import canonical, digest, load_json
from bridge_m2.bundle import FILES, INBOX
from bridge_m2.security import check, read_set, write_file, syncdir
from .artifacts import artifacts as preview
from .convert import VERSION
from .extensions import validate_record
from .runtime_models import model

TARGET = 'dae-v2.1.1-linux-x86_64'

def fingerprints(source, extensions):
    check(type(extensions) is dict,'EXTENSION_SCHEMA')
    version=extensions.get('schemaVersion')
    check(type(version) is int and version in (1,2),'EXTENSION_VERSION')
    keys={'schemaVersion','classification','daedVersion','sourceSha256','databaseSha256','records'}
    if version==2:keys.add('sourceRuntimeModel')
    check(set(extensions)==keys,'EXTENSION_SCHEMA')
    check(extensions['daedVersion']=='v2.1.1','EXTENSION_VERSION')
    model(extensions)
    check(extensions['classification']=='REGENERATED_INDEPENDENT_BRIDGE_INPUT', 'EXTENSION_SCHEMA')
    for key in ('sourceSha256','databaseSha256'):
        check(type(extensions[key]) is str and len(extensions[key])==64 and all(c in '0123456789abcdef' for c in extensions[key]),'EXTENSION_SCHEMA')
    records=extensions['records']
    check(type(records) is dict and {'global','dns'}<=set(records)<= {'global','dns','group'},'EXTENSION_SCHEMA')
    for section, profiles in records.items():
        check(type(profiles) is dict,'EXTENSION_SCHEMA')
        for ident,record in profiles.items():
            check(type(ident) is str and ident.isascii() and ident.isdecimal(),'EXTENSION_SCHEMA')
            validate_record(record,section)
    source_sha=digest(canonical(source)); extension_sha=digest(canonical(extensions))
    joint=digest(canonical({'schemaVersion':1,'converterVersion':VERSION,'graphqlSha256':source_sha,'extensionsSha256':extension_sha}))
    return {'sourceSha256':joint,'graphqlSha256':source_sha,'extensionsSha256':extension_sha}

def artifacts(source, proof, extensions):
    pins=fingerprints(source,extensions)
    files=preview(source,proof,extensions)
    ir=load_json(files['normalized-ir.json']); report=load_json(files['conversion-report.json'])
    ir['graphqlFingerprint']=ir['sourceFingerprint'];ir['sourceFingerprint']=pins['sourceSha256']
    ir['extensionsSha256']=pins['extensionsSha256']
    report.update(sourceFingerprint=pins['sourceSha256'],graphqlFingerprint=pins['graphqlSha256'],extensionsSha256=pins['extensionsSha256'])
    report['applyAuthorized']=False # authority requires a fresh independently trusted receipt
    report['scope']='M4_RUNTIME_CANDIDATE'
    candidate=files['candidate.dae'].decode()
    candidate=candidate.replace('# source-sha256='+pins['graphqlSha256']+'\n','# source-sha256='+pins['sourceSha256']+'\n# graphql-sha256='+pins['graphqlSha256']+'\n# extensions-sha256='+pins['extensionsSha256']+'\n',1)
    files={'candidate.dae':candidate.encode(),'source-snapshot.json':canonical(source),'normalized-ir.json':canonical(ir),'conversion-report.json':canonical(report)}
    manifest={'schemaVersion':1,'converterVersion':VERSION,'target':TARGET,'scope':'M4_RUNTIME_CANDIDATE',**pins,'files':{n:{'sha256':digest(b),'size':len(b)} for n,b in sorted(files.items())}}
    files['manifest.json']=canonical(manifest)
    files['SHA256SUMS']=''.join(digest(files[n])+'  '+n+'\n' for n in sorted(FILES)).encode()
    return files

def verify(payload):
    check(set(payload)==FILES,'ARTIFACT_SET')
    ir=load_json(payload['normalized-ir.json']);source=load_json(payload['source-snapshot.json']);report=load_json(payload['conversion-report.json'])
    check(type(ir) is dict and 'extensions' in ir and type(report) is dict and 'collection' in report,'ARTIFACT_SCHEMA')
    expected=artifacts(source,report['collection'],ir['extensions'])
    check(all(payload[n]==expected[n] for n in FILES),'RENDER_MISMATCH')
    return fingerprints(source,ir['extensions'])

def receipt(source, extensions, observed_at, ttl=180):
    check(type(observed_at) is int and type(ttl) is int and 1<=ttl<=300,'TIME_SHAPE')
    return {'schemaVersion':1,'converterVersion':VERSION,**fingerprints(source,extensions),'observedAt':observed_at,'expiresAt':observed_at+ttl}

def make(payload, trusted_receipt, current, now):
    pins=verify(payload)
    check(type(trusted_receipt) is dict and set(trusted_receipt)=={'schemaVersion','converterVersion','sourceSha256','graphqlSha256','extensionsSha256','observedAt','expiresAt'},'RECEIPT_SHAPE')
    check(trusted_receipt['schemaVersion']==1 and type(trusted_receipt['schemaVersion']) is int and trusted_receipt['converterVersion']==VERSION,'RECEIPT_VERSION')
    check(all(trusted_receipt[k]==v for k,v in pins.items()),'OLD_SOURCE')
    check(type(now) is int and all(type(trusted_receipt[k]) is int for k in ('observedAt','expiresAt')),'TIME_SHAPE')
    check(trusted_receipt['observedAt']<=now<trusted_receipt['expiresAt']<=trusted_receipt['observedAt']+300,'SOURCE_EXPIRED')
    check(current is None or (type(current) is str and len(current)==64 and all(c in '0123456789abcdef' for c in current)),'CURRENT_ID')
    envelope={'schemaVersion':1,'createdAt':now,'expiresAt':trusted_receipt['expiresAt'],**pins,'expectedCurrent':current,'converterVersion':VERSION,'files':{n:digest(b) for n,b in sorted(payload.items())}}
    result=dict(payload,**{'bundle.json':canonical(envelope)})
    return digest(result['bundle.json']),result

def verify_bundle(payload,identity,trusted_receipt,now):
    check(set(payload)==FILES|{'bundle.json'},'BUNDLE_FILES')
    check(digest(payload['bundle.json'])==identity,'BUNDLE_ID')
    envelope=load_json(payload['bundle.json'])
    check(type(envelope) is dict and {'createdAt','expiresAt','expectedCurrent'}<=set(envelope),'BUNDLE_SHAPE')
    expected_id,expected=make({n:payload[n] for n in FILES},trusted_receipt,envelope['expectedCurrent'],envelope['createdAt'])
    check(expected_id==identity and expected==payload,'BUNDLE_SHAPE')
    check(type(now) is int and envelope['createdAt']<=now<envelope['expiresAt'],'BUNDLE_EXPIRED')
    return envelope

def stage(candidate,trusted_receipt,current,inbox=INBOX):
    check(os.geteuid()!=0,'BRIDGE_MUST_NOT_BE_ROOT')
    files=read_set(candidate,os.geteuid(),os.getegid(),FILES|{'SHA256SUMS'})
    check(files['SHA256SUMS']==''.join(digest(files[n])+'  '+n+'\n' for n in sorted(FILES)).encode(),'SUMS')
    identity,payload=make({n:files[n] for n in FILES},trusted_receipt,current,int(time.time()))
    target=Path(inbox)/identity;target.mkdir(mode=0o700)
    for name,body in payload.items():write_file(target/name,body,0o400)
    syncdir(target);syncdir(inbox)
    return identity
