"""Execute the actual management apply failure path with temporary files.

External systemd, database and source observers are controlled substitutes.
This is NOT a real service lifecycle/VM acceptance test.
"""
from contextlib import ExitStack, nullcontext, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import release_management_plan as p


class ApplyRecoveryIntegration(unittest.TestCase):
    def scenario(self, fault):
        with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
            root=Path(d).resolve(); source=root/'src'; (source/'bridge_m4').mkdir(parents=True)
            (source/'bridge_m4/example.py').write_bytes(b'candidate\n')
            installed=root/'installed';installed.mkdir();target=installed/'example.py';target.write_bytes(b'original\n')
            manifest=installed/'install.json'
            old={'schemaVersion':1,'files':{str(target):{'sha256':p.sha(target.read_bytes()),'mode':0o644}}}
            manifest.write_bytes(p.canonical(old))
            row={'source':'bridge_m4/example.py','target':str(target),'before':old['files'][str(target)],
                 'after':{'sha256':p.sha(b'candidate\n'),'mode':0o644}}
            plan={'changes':[row],'deploymentProfile':None};calls=[];phase={'rollback':False,'wrote':False,'startFailed':False,'initialStopped':False}
            states={name:{'LoadState':'loaded','ActiveState':'active','MainPID':'10' if name.endswith('.service') else '0',
                          'ControlPID':'0','InvocationID':'test','NRestarts':'0'} for name in (*p.MANAGEMENT,*p.TIMERS)}
            dae={'LoadState':'loaded','ActiveState':'active','MainPID':'123','ControlPID':'0','InvocationID':'unchanged','NRestarts':'0'}
            journal={};saved={};counts={'restore':0,'health':0,'commit':0}
            def control(action,*names):
                for name in names:
                    calls.append((action,name,phase['rollback']))
                    if name not in states:raise AssertionError('unexpected service control')
                    if action=='stop':
                        if fault=='cleanup-live' and phase['rollback'] and name==p.MANAGEMENT[1]:
                            raise RuntimeError('stop unavailable')
                        states[name].update(ActiveState='inactive',MainPID='0',ControlPID='0')
                        if fault=='cleanup-error-but-stopped' and phase['rollback'] and name==p.MANAGEMENT[0]:
                            raise RuntimeError('command failed after stop')
                    elif action=='start':
                        if fault=='first-start' and phase['wrote'] and not phase['rollback'] and not phase['startFailed']:
                            phase['startFailed']=True;raise RuntimeError('first start failed')
                        states[name].update(ActiveState='active',MainPID='10' if name.endswith('.service') else '0')
                    else:raise AssertionError('unexpected action')
            def show(name):return copy.deepcopy(dae if name=='dae.service' else states[name])
            def begin(paths):
                saved.update({n:Path(n).read_bytes() for n in paths if Path(n).exists()})
                journal.update(phase='APPLYING',generation='fixture',files=[])
                (root/'fixture').mkdir()
            def write(path,body,mode):
                path.write_bytes(body);path.chmod(mode);phase['wrote']=True
                if fault=='file-write' and path==target:
                    phase['rollback']=True;raise OSError('injected write failure')
            def restore():
                counts['restore']+=1;phase['rollback']=True
                for name,body in saved.items():Path(name).write_bytes(body)
                journal['phase']='RESTORED'
            def verify_management():
                counts['health']+=1
                if counts['health']==2 and fault!='first-start' and not phase['rollback']:
                    phase['rollback']=True;raise RuntimeError('POST_WRITE_HEALTH_FAILED')
            tx=types.ModuleType('scripts.m4_install_transaction')
            tx.ROOT=root;tx.sync=lambda path:None;tx.exclusive=lambda:nullcontext();tx.begin=begin;tx.write=write
            tx.load=lambda:journal;tx.journal=lambda value:journal.update(value);tx.restore=restore
            tx.commit=lambda:counts.__setitem__('commit',counts['commit']+1)
            modules={}
            def module(name,**members):
                value=types.ModuleType(name);value.__dict__.update(members);modules[name]=value;return value
            module('scripts.release_geodata_update',exclusive=lambda:nullcontext())
            modules[tx.__name__]=tx
            module('bridge_m4.authority',manifest=lambda **kw:json.loads(manifest.read_text()),policy=lambda:{})
            def fixture_database(directory):
                f=directory/'database-check-test.sqlite';f.write_bytes(b'database')
                return p.sha(b'database')
            module('scripts.release_replace',database_snapshot=lambda directory: fixture_database(directory),source_identity=lambda:'source',verify_management=verify_management)
            module('bridge_m4.deployment_profile',lifecycle_units=lambda units,profile:units,load=lambda:None)
            module('scripts.release_health',check=lambda:None)
            stack.enter_context(patch.dict(sys.modules,modules))
            import scripts
            stack.enter_context(patch.object(scripts,'m4_install_transaction',tx,create=True))
            stack.enter_context(patch.object(p,'INSTALL',manifest))
            stack.enter_context(patch.object(p,'runtime_plan',return_value=plan))
            stack.enter_context(patch.object(p,'upgrade_guard'))
            stack.enter_context(patch.object(p,'validate_extensions'))
            stack.enter_context(patch.object(p,'LAYOUT',installed/'layout.json'))
            stack.enter_context(patch('scripts.management_payload.dependencies'))
            stack.enter_context(patch.object(p,'control',side_effect=control))
            stack.enter_context(patch.object(p,'unit',side_effect=show))
            stack.enter_context(patch.object(p.os,'geteuid',return_value=0))
            is_dir=Path.is_dir
            stack.enter_context(patch.object(Path,'is_dir',lambda path: True if str(path)=='/run/systemd/system' else is_dir(path)))
            output=io.StringIO();error=None
            with redirect_stdout(output):
                try:p.apply_plan(plan,p.sha(p.canonical(plan)),root=source)
                except Exception as exc:error=exc
            self.assertIsNotNone(error)
            self.assertEqual(counts['commit'],0)
            self.assertFalse(any(name in {'dae.service','daed-api.service'} for _,name,_ in calls))
            return {'calls':calls,'restore':counts['restore'],'body':target.read_bytes(),
                    'manifest':json.loads(manifest.read_text()),'old':old,'error':error,
                    'output':output.getvalue(),'journal':dict(journal),'states':copy.deepcopy(states)}
    def test_post_write_failure_restores_original_files(self):
        r=self.scenario('post-write')
        self.assertEqual(r['body'],b'original\n');self.assertEqual(r['manifest'],r['old'])
        self.assertEqual(r['restore'],1);self.assertEqual(str(r['error']),'POST_WRITE_HEALTH_FAILED')
        self.assertIn('ROLLED_BACK',r['output'])
    def test_cleanup_stop_failure_does_not_skip_safe_restore(self):
        r=self.scenario('cleanup-error-but-stopped')
        self.assertEqual(r['body'],b'original\n');self.assertEqual(r['restore'],1)
        self.assertIn('commandWarnings',r['output'])
    def test_first_start_failure_does_not_skip_other_starts_and_rolls_back(self):
        r=self.scenario('first-start')
        forward=[name for action,name,rollback in r['calls'] if action=='start' and not rollback]
        self.assertEqual(forward,list((*p.MANAGEMENT,*p.TIMERS)))
        self.assertEqual(r['body'],b'original\n');self.assertEqual(r['restore'],1)
    def test_unreleased_process_prevents_writing_old_files_under_live_code(self):
        r=self.scenario('cleanup-live')
        self.assertEqual(r['restore'],0);self.assertEqual(r['body'],b'candidate\n')
        self.assertIsInstance(r['error'],p.RecoveryFailure)
        self.assertFalse(r['error'].report['complete']);self.assertEqual(r['journal']['phase'],'APPLYING')
    def test_injected_write_failure_restores_temp_files_without_commit(self):
        r=self.scenario('file-write')
        self.assertEqual(r['restore'],1);self.assertEqual(r['body'],b'original\n')
        self.assertEqual(r['manifest'],r['old'])


if __name__=='__main__':unittest.main(verbosity=2)
