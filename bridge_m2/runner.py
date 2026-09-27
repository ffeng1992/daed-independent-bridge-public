"""Fixed unit launcher: bind argv to an immutable generation before exec."""
import os
from .helper import policy
from .control import BASE, Controller, Systemd, ENV
from .security import check, digest
from pathlib import Path

p=policy()
c=Controller(BASE,p,Systemd(p))
identity=c.pointer()
check(identity is not None,'NO_CURRENT')
c.version(identity)
binary=Path('/opt/bridge-service/dae')
check(digest(binary.read_bytes())==p['serviceBinarySha256'],'SERVICE_BINARY')
os.execve(binary,[str(binary),'run','-c',str(c.candidate(identity))],ENV)
