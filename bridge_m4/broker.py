"""Socket-activated production candidate broker; fixed service and action grammar."""
import os
import socket
import struct
from bridge_m2.control import ENV,request
from bridge_m2.security import check,canonical,Denied
from bridge_m2.broker import SOCKET
from .authority import policy,controller

SAFE_ERRORS={'UNMANAGED_SERVICE_ACTIVE','UNIT_IDENTITY_MISMATCH','INSTALL_FILE_IDENTITY','MANUAL_INTERVENTION_REQUIRED','RECOVERY_REQUIRED','NO_PENDING_RECOVERY','BUSY','OLD_SOURCE','SOURCE_EXPIRED','BUNDLE_EXPIRED','VALIDATE_FAILED','CURRENT_CONFLICT','SERVICE_NOT_RUNNING','RECEIPT_SHAPE'}

def serve():
    check(os.environ.get('LISTEN_PID')==str(os.getpid()) and os.environ.get('LISTEN_FDS')=='1','SOCKET_ACTIVATION_REQUIRED')
    server=socket.socket(fileno=3)
    check(server.family==socket.AF_UNIX and server.type==socket.SOCK_STREAM and server.getsockname()==str(SOCKET) and server.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN)==1,'SOCKET_AUTHORITY')
    os.environ.clear();os.environ.update(ENV)
    while True:
        connection,_=server.accept()
        with connection:
            connection.settimeout(3)
            try:
                p=policy()
                _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                check(uid==p['bridgeUid'],'PEER_REJECTED')
                raw=bytearray()
                while b'\n' not in raw and len(raw)<=4096:
                    chunk=connection.recv(4097-len(raw))
                    if not chunk:break
                    raw.extend(chunk)
                check(len(raw)<=4096 and raw.endswith(b'\n'),'FRAME_REJECTED')
                result=controller(p).execute(request(bytes(raw)))
            except Exception as exc:
                from .diagnostics import failure
                failure("broker",exc)
                code=str(exc) if isinstance(exc,Denied) and str(exc) in SAFE_ERRORS else 'REQUEST_FAILED'
                result={'state':'rollback-needed','error':code}
            try:connection.sendall(canonical(result))
            except OSError:pass

if __name__=='__main__':serve()
