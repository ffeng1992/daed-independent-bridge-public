"""Root-only disposable helper; JSON stdin is the sole request surface."""
import json
import os
import sys
from pathlib import Path
from .control import BASE, ENV, Controller, Systemd, request
from .security import check, directory, read_at, load_json, Denied


def policy():
    check(os.geteuid()==0,'ROOT_HELPER_REQUIRED')
    # This milestone is deliberately non-deployable outside the disposable harness.
    check(Path('/run/bridge-disposable').is_file() and Path('/run/systemd/system').is_dir(),'DISPOSABLE_ONLY')
    fd=directory(BASE,0,0,0o711)
    try:return load_json(read_at(fd,'policy.json',0,0))
    finally:os.close(fd)


def main():
    check(len(sys.argv)==1,'ARGUMENTS_REJECTED')
    check(all(k in ENV for k in os.environ),'ENVIRONMENT_REJECTED')
    p=policy()
    value=request(sys.stdin.buffer.read(4097))
    try:result=Controller(BASE,p,Systemd(p),policy_provider=policy).execute(value)
    except Denied as exc:
        # Only this fixed, non-secret domain error is exposed; all other exceptions remain redacted.
        if str(exc) not in {'UNMANAGED_SERVICE_ACTIVE','UNIT_IDENTITY_MISMATCH','MANUAL_INTERVENTION_REQUIRED'}:raise
        print(json.dumps({'state':'rollback-needed','error':str(exc)}));return 1
    print(json.dumps(result,sort_keys=True))
    if value['action']!='status' and result.get('result') in {'ROLLED_BACK','MANUAL_INTERVENTION_REQUIRED'}:return 2
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print('{"state":"rollback-needed","error":"REQUEST_FAILED"}')
        sys.exit(1)
