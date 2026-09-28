"""Local-only TCP path witnesses for the existing disposable matrix VM."""
import base64
import json
import select
import socket
import socketserver
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from integration.ui_matrix.path_event_log import append

LOG = Path('/evidence/path-events.jsonl')
AUTH = 'Basic ' + base64.b64encode(b'synthetic-user:SyntheticOnly314159').decode()
# The fixture cannot connect to arbitrary addresses or the production network.
TARGETS = {('198.51.100.2', 18080), ('198.51.100.2', 18081)}
DOMAIN_TARGETS = {'path.matrix.invalid': '198.51.100.2'}
DELAYS = Path('/evidence/path-proxy-delays.json')


def client_hello_program(delay):
    if type(delay) not in (int, float) or not 0 <= delay <= 1:
        raise ValueError('INVALID_FIXTURE_DELAY')
    return ('import json,socket,ssl,time\n'
            'incoming,outgoing=ssl.MemoryBIO(),ssl.MemoryBIO()\n'
            'context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n'
            'client=context.wrap_bio(incoming,outgoing,server_hostname="path.matrix.invalid")\n'
            'try:client.do_handshake()\n'
            'except ssl.SSLWantReadError:pass\n'
            'hello=outgoing.read()\n'
            'if len(hello)<100:raise RuntimeError("CLIENT_HELLO_MISSING")\n'
            's=socket.create_connection(("198.51.100.2",18080),5)\n'
            f'time.sleep({delay!r})\n'
            's.sendall(hello)\n'
            'time.sleep(1)\n'
            'print(json.dumps({"clientHelloBytes":len(hello),"localPort":s.getsockname()[1]}))\n'
            's.close()\n')


def delay_for(port):
    if not DELAYS.exists():
        return 0.005 if port == 18082 else 0.12
    values = json.loads(DELAYS.read_text())
    if set(values) != {'18082', '18083'} or any(type(v) not in (int, float) or not 0 <= v <= 2 for v in values.values()):
        raise ValueError('FIXTURE_DELAY_SCHEMA')
    return values[str(port)]


def record(kind, **values):
    append({'time': time.time(), 'kind': kind, **values})


def header(connection):
    connection.settimeout(10)
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = connection.recv(1)
        if not chunk or len(data) >= 16384:
            raise ValueError('FIXTURE_INVALID_HEADER')
        data += chunk
    return data.decode('iso-8859-1')


def relay(left, right):
    sockets = [left, right]
    while sockets:
        ready, _, _ = select.select(sockets, [], [], 10)
        if not ready:
            return
        for source in ready:
            data = source.recv(65536)
            if not data:
                return
            (right if source is left else left).sendall(data)


class Proxy(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            lines = header(self.request).split('\r\n')
            method, target, _ = lines[0].split()
            fields = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            fields = {key.lower(): value for key, value in fields.items()}
            if method not in {'CONNECT', 'GET', 'HEAD'} or fields.get('proxy-authorization') != AUTH:
                self.request.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n')
                record('proxy-rejected', proxy=self.server.server_address[1], method=method)
                return
            if method == 'CONNECT':
                host, port = target.rsplit(':', 1)
                forwarded = None
            else:
                # The pinned official HTTP dialer uses absolute-form requests
                # for plaintext HTTP and CONNECT for arbitrary TCP. Both are
                # genuine proxy paths; never forward authentication upstream.
                parsed = urlsplit(target)
                if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError('FIXTURE_INVALID_ABSOLUTE_TARGET')
                host, port = parsed.hostname, parsed.port or 80
                path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
                forwarded = f'{method} {path} HTTP/1.1\r\n'
                forwarded += '\r\n'.join(line for line in lines[1:] if line and
                                          not line.lower().startswith(('proxy-authorization:', 'proxy-connection:')))
                forwarded += '\r\n\r\n'
            # A domain-mode DAE legitimately preserves the sniffed Host name.
            # Resolve only this fixture-owned name, never external DNS.
            address = (DOMAIN_TARGETS.get(host, host), int(port))
            if address not in TARGETS:
                raise ValueError('FIXTURE_TARGET_NOT_ALLOWED')
            record('proxy-connect', proxy=self.server.server_address[1], target=target,
                   method=method, peer=self.client_address[0], peerPort=self.client_address[1], authenticationMatched=True)
            delay = delay_for(self.server.server_address[1])
            time.sleep(delay)
            with socket.create_connection(address, timeout=5) as upstream:
                record('proxy-upstream-connected', proxy=self.server.server_address[1],
                       method=method, target=target)
                if forwarded is None:
                    self.request.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    request_header = header(self.request)
                else:
                    request_header = forwarded
                request_method, path, _ = request_header.split('\r\n')[0].split()
                record('proxy-request', proxy=self.server.server_address[1], method=request_method, path=path,
                       target=target, peerPort=self.client_address[1])
                upstream.sendall(request_header.encode('iso-8859-1'))
                relay(self.request, upstream)
        except (OSError, ValueError) as exc:
            record('proxy-error', proxy=self.server.server_address[1], error=type(exc).__name__,
                   reason=str(exc))


class Endpoint(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            line = header(self.request).split('\r\n')[0]
            method, path, _ = line.split()
            record('endpoint', method=method, path=path, peer=self.client_address[0],
                   port=self.server.server_address[1])
            body = b'MATRIX_PATH_OK'
            self.request.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: ' +
                                 str(len(body)).encode() + b'\r\n\r\n' + (b'' if method == 'HEAD' else body))
        except (OSError, ValueError) as exc:
            record('endpoint-error', error=type(exc).__name__)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    import sys
    if not Path('/evidence/baseline-ready').is_file():
        raise RuntimeError('DISPOSABLE_VM_REQUIRED')
    if sys.argv[1:] == ['proxy']:
        addresses = [('127.0.0.1', port) for port in (18082, 18083)]
        handler = Proxy
    elif sys.argv[1:] == ['endpoint']:
        addresses = [('198.51.100.2', port) for port in (18080, 18081)]
        handler = Endpoint
    else:
        raise RuntimeError('FIXTURE_ROLE_REQUIRED')
    for address in addresses:
        server = Server(address, handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


if __name__ == '__main__':
    main()
