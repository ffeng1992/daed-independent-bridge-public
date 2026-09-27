"""Nonprivileged staging and independent M1 provenance verification."""
import os
import time
from pathlib import Path
from bridge_m1.bundle import artifacts
from bridge_m1.common import VERSION, canonical, digest, load_json
from .security import check, read_set, syncdir, write_file

FILES = {'candidate.dae', 'source-snapshot.json', 'normalized-ir.json', 'conversion-report.json', 'manifest.json'}
INBOX = Path('/var/lib/daed-independent-bridge/inbox')


def verify(payload):
    check(set(payload) == FILES, 'ARTIFACT_SET')
    manifest = load_json(payload['manifest.json'])
    check(set(manifest) == {'schemaVersion','converterVersion','target','files'}, 'MANIFEST_SHAPE')
    check(manifest['schemaVersion'] == 1 and manifest['converterVersion'] == VERSION and manifest['target'] == 'dae-v2.1.1-linux-x86_64', 'VERSION')
    check(set(manifest['files']) == FILES - {'manifest.json'}, 'MANIFEST_FILES')
    for name, pin in manifest['files'].items():
        check(pin == {'sha256':digest(payload[name]), 'size':len(payload[name])}, 'ARTIFACT_HASH')
    source = load_json(payload['source-snapshot.json'])
    ir = load_json(payload['normalized-ir.json'])
    report = load_json(payload['conversion-report.json'])
    fp = digest(canonical(source))
    check(ir['source_fingerprint'] == report['sourceSha256'] == fp, 'SOURCE_FINGERPRINT')
    check(ir['converter_version'] == report['converterVersion'] == VERSION, 'VERSION')
    # Reconstruct transport pages from the complete normalized source, then rerun M1.
    pages = []
    for sid in [None] + [s['id'] for s in source['metadata']['subscriptions']]:
        nodes = [n for n in source['nodes'] if n['subscriptionID'] == sid]
        chunks = [nodes[i:i+200] for i in range(0,len(nodes),200)] or [[]]
        for i, chunk in enumerate(chunks):
            pages.append({'subscriptionId':sid,'response':{'data':{'nodes':{'totalCount':len(nodes),'edges':chunk,
                          'pageInfo':{'startCursor':chunk[0]['id'] if chunk else None,'endCursor':chunk[-1]['id'] if chunk else None,'hasNextPage':i+1 < len(chunks)}}}}})
    snapshot = {'schemaVersion':1,'synthetic':True,'consistency':{'stable':True,'transactional':False},
                'metadata':{'data':source['metadata']},'nodePages':pages}
    expected = artifacts(snapshot, ir['source']['kind'], ir['source']['daedVersion'], report['collection'])
    check(all(payload[n] == expected[n] for n in FILES), 'RENDER_MISMATCH')
    return fp


def make(payload, receipt, current, now):
    fp = verify(payload)
    check(set(receipt) == {'sourceSha256','observedAt','expiresAt'}, 'RECEIPT_SHAPE')
    check(fp == receipt['sourceSha256'], 'OLD_SOURCE')
    check(type(now) is int and type(receipt['observedAt']) is int and type(receipt['expiresAt']) is int, 'TIME_SHAPE')
    check(receipt['observedAt'] <= now < receipt['expiresAt'] <= receipt['observedAt'] + 300, 'SOURCE_EXPIRED')
    envelope = {'schemaVersion':1,'createdAt':now,'expiresAt':receipt['expiresAt'],'sourceSha256':fp,
                'expectedCurrent':current,'converterVersion':VERSION,'files':{n:digest(b) for n,b in sorted(payload.items())}}
    result = dict(payload, **{'bundle.json':canonical(envelope)})
    return digest(result['bundle.json']), result


def verify_bundle(payload, identity, receipt, now):
    check(set(payload) == FILES | {'bundle.json'}, 'BUNDLE_FILES')
    envelope = load_json(payload['bundle.json'])
    check(digest(payload['bundle.json']) == identity, 'BUNDLE_ID')
    expected_id, expected = make({n:payload[n] for n in FILES}, receipt, envelope['expectedCurrent'], envelope['createdAt'])
    check(expected_id == identity and expected == payload, 'BUNDLE_SHAPE')
    check(envelope['createdAt'] <= now < envelope['expiresAt'], 'BUNDLE_EXPIRED')
    return envelope


def stage(candidate, receipt, current, inbox=INBOX):
    check(os.geteuid() != 0, 'BRIDGE_MUST_NOT_BE_ROOT')
    uid,gid = os.geteuid(),os.getegid()
    # M1 also writes SHA256SUMS: verify the five semantic artifacts and optional sums.
    names = FILES | {'SHA256SUMS'}
    all_files = read_set(candidate,uid,gid,names)
    sums = ''.join(digest(all_files[n])+'  '+n+'\n' for n in sorted(FILES)).encode()
    check(all_files['SHA256SUMS'] == sums, 'SUMS')
    identity, payload = make({n:all_files[n] for n in FILES},receipt,current,int(time.time()))
    target = inbox/identity
    target.mkdir(mode=0o700)
    for name,body in payload.items():write_file(target/name,body,0o400)
    syncdir(target);syncdir(inbox)
    return identity
