"""Nonprivileged local client. Fixed socket, strict request, no subprocess API."""
import json
import socket
import sys
from .broker import SOCKET
from .control import request
from .security import canonical, check


def submit(action,identity=None):
    data=canonical(dict(action=action,**({'bundleId':identity} if identity is not None else {})));request(data)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(60);client.connect(str(SOCKET));client.sendall(data)
        response=bytearray()
        while not response.endswith(b'\n') and len(response)<65536:
            chunk=client.recv(4096)
            if not chunk:break
            response.extend(chunk)
    check(response.endswith(b'\n'),'RESPONSE_FRAME')
    return json.loads(response)

if __name__=='__main__':
    try:
        check(len(sys.argv) in {2,3},'ARGUMENTS')
        result=submit(*sys.argv[1:]);print(json.dumps(result))
        if 'error' in result or (sys.argv[1]!='status' and result.get('result') in {'ROLLED_BACK','MANUAL_INTERVENTION_REQUIRED'}):raise SystemExit(1)
    except Exception:
        print('{"error":"REQUEST_FAILED"}');raise SystemExit(1)
