"""Bounded reserved-network transfer endpoint for bandwidth field evidence."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path

BODY = b'matrix-only-0123' * 32768
DIGEST = hashlib.sha256(BODY).hexdigest()


class Endpoint(BaseHTTPRequestHandler):
    def answer(self, status, body):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        if self.path == '/download':
            self.answer(200, BODY)
        elif self.path == '/health':
            self.answer(200, b'OK')
        else:
            self.answer(404, b'')

    do_HEAD = do_GET

    def do_POST(self):
        if self.path != '/upload' or self.headers.get('Content-Length') != str(len(BODY)):
            self.answer(400, b''); return
        body = self.rfile.read(len(BODY))
        digest = hashlib.sha256(body).hexdigest()
        self.answer(200 if digest == DIGEST else 400,
                    json.dumps({'bytes': len(body), 'sha256': digest}).encode())

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    if not Path('/evidence/path-fixture-ready').is_file():
        raise SystemExit('EXISTING_ISOLATED_PATH_FIXTURE_REQUIRED')
    ThreadingHTTPServer(('198.51.100.2', 18086), Endpoint).serve_forever()
