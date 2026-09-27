"""Fixed executable entry; no command-line or environment forwarding."""
import os
import sys
from .validation import DAE_ENV
from bridge_m2.security import check
from .authority import controller,policy

def main():
    check(len(sys.argv)==1,'ARGUMENTS_REJECTED')
    p=policy();control=controller(p);control.service.verify_unit()
    active=control.pointer();check(active is not None,'NO_CURRENT_BUNDLE');control.version(active)
    os.execve('/opt/bridge-service/dae',['/opt/bridge-service/dae','run','-c',str(control.candidate(active))],DAE_ENV)
if __name__=='__main__':main()
