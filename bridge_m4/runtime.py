"""Nonprivileged preview, validation, extension edits and fixed broker requests."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from bridge_m1.collect import HTTPReader
from bridge_m1.common import canonical, digest
from bridge_m2.control import ENV
from bridge_m2.security import check, write_file, read_at, directory, atomic_json
from bridge_m2.submit import submit
from .collect import collect
from .store import ExtensionStore
from .runtime_bundle import artifacts, fingerprints, stage

CLIENT=Path('/var/lib/bridge-m4-client')
EXTENSIONS=CLIENT/'extensions'
PUBLIC=Path('/var/lib/bridge-m4-attestation')
ENDPOINT='http://127.0.0.1:2024/graphql'
VALIDATOR=Path('/opt/bridge-official/dae')

class Runtime:
    def __init__(self,root=CLIENT,submitter=submit,collector=None,now=time.time):
        check(os.geteuid()!=0,'BRIDGE_MUST_NOT_BE_ROOT')
        self.root=Path(root);self.store=ExtensionStore(self.root/'extensions')
        self.submit=submitter;self.collector=collector or (lambda token:collect(HTTPReader(ENDPOINT,token)))
        self.now=now;self.lock=threading.RLock();self.pending=None
    def snapshot(self,token):
        generation,before=self.store.load()
        source,proof=self.collector(token)
        after,_=self.store.load();check(generation==after,'EXTENSION_CHANGED')
        from .convert import bind_new_profiles
        fingerprints(source,before['extensions']) # Validate the sealed extension schema before binding new official profiles.
        effective=bind_new_profiles(source,before['extensions'])
        return source,proof,effective,generation
    def preview(self,token):
        with self.lock:
            source,proof,extensions,generation=self.snapshot(token)
            payload=artifacts(source,proof,extensions)
            identity=digest(payload['manifest.json'])
            parent=self.root/'previews';parent.mkdir(mode=0o700,exist_ok=True)
            candidate=parent/identity
            if not candidate.exists():
                candidate.mkdir(mode=0o700)
                for name,body in payload.items():write_file(candidate/name,body)
            else:
                from bridge_m2.security import read_set
                check(read_set(candidate,os.geteuid(),os.getegid(),set(payload))==payload,'PREVIEW_CONFLICT')
            previous=self.pending
            baseline=previous['directory'] if previous else None
            last=self.root/'last-applied.json'
            if last.exists():
                fd=directory(self.root,os.geteuid(),os.getegid())
                try:saved=json.loads(read_at(fd,'last-applied.json',os.geteuid(),os.getegid()))
                finally:os.close(fd)
                preview_id=saved['previewId']
                check(type(preview_id) is str and len(preview_id)==64 and all(c in '0123456789abcdef' for c in preview_id),'PREVIEW_CONFLICT')
                baseline=parent/preview_id
            before_source={};before_extensions={}
            if baseline is not None:
                fd=directory(baseline,os.geteuid(),os.getegid())
                try:
                    before_source=json.loads(read_at(fd,'source-snapshot.json',os.geteuid(),os.getegid()))
                    before_extensions=json.loads(read_at(fd,'normalized-ir.json',os.geteuid(),os.getegid()))['extensions']
                finally:os.close(fd)
            from .preview_diff import summary
            differences={'daed':summary(before_source,source),'daeExtensions':summary(before_extensions,extensions),'baseline':'last-applied' if last.exists() else 'previous-preview' if previous else 'empty'}
            pins=fingerprints(source,extensions)
            self.pending={'id':identity,'generation':generation,'directory':candidate,'pins':pins,'validated':False}
            # No raw node links or complete configuration in browser summaries.
            return {'differences':differences,'previewId':identity,'sourceFingerprint':pins['sourceSha256'],'graphqlFingerprint':pins['graphqlSha256'],'extensionsSha256':pins['extensionsSha256'],'extensionGeneration':generation,'nodeCount':len(source['nodes']),'groupCount':len(source['metadata']['groups']),'collection':proof,'candidateSha256':digest(payload['candidate.dae']),'changedSincePreview':previous is None or previous['id']!=identity,'compatibilityDefaults':json.loads(payload['conversion-report.json'])['compatibilityDefaults']}
    def require_preview(self,identity):
        check(self.pending is not None and self.pending['id']==identity,'PREVIEW_CONFLICT')
        generation,_=self.store.load();check(generation==self.pending['generation'],'EXTENSION_CHANGED')
        return self.pending
    def validate(self,identity):
        with self.lock:
            pending=self.require_preview(identity)
            from .upstream_contracts import official_member_sha
            expected=official_member_sha('dae','dae-linux-x86_64')
            from .validation import validate
            validate(pending['directory']/'candidate.dae',expected)
            pending['validated']=True
            return {'validated':True,'binarySha256':expected,'candidateSha256':digest((pending['directory']/'candidate.dae').read_bytes()),'scope':'OFFICIAL_STATIC_VALIDATION'}
    def apply(self,token,identity):
        with self.lock:
            pending=self.require_preview(identity);check(pending['validated'],'VALIDATION_REQUIRED')
            source,_,extensions,generation=self.snapshot(token)
            check(generation==pending['generation'] and fingerprints(source,extensions)==pending['pins'],'SOURCE_CHANGED')
            status=self.status();check('error' not in status and status.get('state')!='rollback-needed','STATUS_REJECTED')
            last_path=self.root/'last-applied.json'
            if last_path.exists():
                fd=directory(self.root,os.geteuid(),os.getegid())
                try:last=json.loads(read_at(fd,'last-applied.json',os.geteuid(),os.getegid()))
                finally:os.close(fd)
                if last.get('previewId')==identity and last.get('bundleId')==status['activeBundle']:
                    result=self.submit('apply',last['bundleId'])
                    return {'bundleId':last['bundleId'],'result':result,'status':self.status(last['bundleId'])}
            fd=directory(PUBLIC,0,os.getegid(),0o750)
            try:trusted=json.loads(read_at(fd,'receipt.json',0,os.getegid(),0o640))
            finally:os.close(fd)
            bundle=stage(pending['directory'],trusted,status['activeBundle'])
            result=self.submit('apply',bundle)
            if result.get('result') in {'APPLIED','ALREADY_APPLIED'}:
                atomic_json(self.root/'last-applied.json',{'previewId':identity,'bundleId':bundle})
            # The helper independently validates again before its atomic publication.
            return {'bundleId':bundle,'result':result,'status':self.status(bundle)}
    def extensions(self):
        generation,value=self.store.load()
        return {'generation':generation,'records':{section:{ident:record['fields'] for ident,record in records.items()} for section,records in value['extensions']['records'].items()}}
    def bind_extensions(self,token):
        with self.lock:
            generation,_=self.store.load()
            source,_=self.collector(token)
            latest,_=self.store.load();check(latest==generation,'EXTENSION_CHANGED')
            bound,changed=self.store.bind_profiles(source,generation)
            if changed:self.pending=None
            return {'generation':bound,'changed':changed}
    def edit(self,value):
        check(type(value) is dict and set(value)=={'expected','section','profile','field','state'},'EXTENSION_REQUEST')
        with self.lock:
            generation=self.store.commit(**value);self.pending=None
            return {'generation':generation}
    def status(self,bundle=None):
        # Only a read may retry BUSY. Mutations remain single submissions.
        for attempt in range(6):
            result=self.submit('status',bundle)
            if result.get('error')!='BUSY' or attempt==5:return result
            time.sleep(0.1*(attempt+1))
    def action(self,action,bundle=None):
        check(action in {'status','start','stop','reload','recover'},'ACTION_REJECTED')
        return self.status(bundle) if action=='status' else self.submit(action,bundle)
