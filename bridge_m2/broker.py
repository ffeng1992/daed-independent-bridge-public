"""Local authenticated Unix socket; callers cannot control child environment/paths."""
import os
from pathlib import Path
import socket
import struct
from .control import BASE, ENV, Controller, Systemd, request
from .helper import policy
from .security import check, canonical, Denied

SOCKET=Path('/run/bridge-control/helper.sock')


def serve():
    # systemd owns the listening socket across broker crashes. Never unlink it.
    check(os.environ.get('LISTEN_PID')==str(os.getpid()) and os.environ.get('LISTEN_FDS')=='1','SOCKET_ACTIVATION_REQUIRED')
    server=socket.socket(fileno=3)
    check(server.family==socket.AF_UNIX and server.type==socket.SOCK_STREAM
          and server.getsockname()==str(SOCKET) and server.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN)==1,'SOCKET_AUTHORITY')
    os.environ.clear();os.environ.update(ENV)
    while True:
        conn,_=server.accept()
        with conn:
            conn.settimeout(3)
            try:
                p=policy()
                _,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                check(uid==p['bridgeUid'],'PEER_REJECTED')
                raw=bytearray()
                while b'\n' not in raw and len(raw)<=4096:
                    chunk=conn.recv(4097-len(raw))
                    if not chunk:break
                    raw.extend(chunk)
                check(len(raw)<=4096 and raw.endswith(b'\n'),'FRAME_REJECTED')
                result=Controller(BASE,p,Systemd(p),policy_provider=policy).execute(request(bytes(raw)))
            except Exception as exc:
                code=str(exc) if isinstance(exc,Denied) and str(exc) in {'UNMANAGED_SERVICE_ACTIVE','UNIT_IDENTITY_MISMATCH','MANUAL_INTERVENTION_REQUIRED'} else 'REQUEST_FAILED'
                result={'state':'rollback-needed','error':code}
            try:conn.sendall(canonical(result))
            except OSError:pass

if __name__=='__main__':serve()
