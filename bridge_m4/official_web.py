"""Standalone nginx host for unmodified official daed static assets."""
import ipaddress
import json
import os
from pathlib import Path

CFG=Path('/etc/daed-independent-bridge')
RUNTIME=Path('/run/bridge-daed-web')


def configuration(address):
    address=str(ipaddress.IPv4Address(address))
    return '''pid /run/bridge-daed-web/nginx.pid;
error_log stderr warn;
worker_processes 1;
events { worker_connections 256; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log off;
    client_body_temp_path /run/bridge-daed-web/body;
    proxy_temp_path /run/bridge-daed-web/proxy;
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    server {
        listen ADDRESS:8444 ssl;
        server_name _;
        ssl_certificate /etc/daed-independent-bridge/tls.crt;
        ssl_certificate_key /etc/daed-independent-bridge/tls.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        root /opt/bridge-daed-web;
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        add_header X-Frame-Options DENY always;
        location = / { alias /opt/bridge-daed-web-entry/connect.html; default_type text/html; }
        location = /connect.js { alias /opt/bridge-daed-web-entry/connect.js; default_type application/javascript; }
        location = /graphql {
            proxy_pass http://127.0.0.1:2023/graphql;
            proxy_http_version 1.1;
            proxy_set_header Host 127.0.0.1:2023;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout 60s;
            client_max_body_size 16m;
        }
        location / { try_files $uri =404; }
    }
}
'''.replace('ADDRESS',address)


def main():
    value=json.loads((CFG/'web.json').read_text())
    body=configuration(value['address'])
    path=RUNTIME/'nginx.conf'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(body)
    os.execv('/usr/sbin/nginx',['/usr/sbin/nginx','-c',str(path),'-g','daemon off;'])
