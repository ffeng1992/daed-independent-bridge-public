"""Standalone nginx host for unmodified official daed static assets."""
import ipaddress
import json
import os
import gzip
import hashlib
import stat
import shutil
import sys
import re
from pathlib import Path

CFG=Path('/etc/daed-independent-bridge')
RUNTIME=Path('/run/bridge-daed-web')


def build_static_cache():
    """Build disposable gzip copies of pinned official assets; never edit sources."""
    seal=json.loads((CFG/'install.json').read_text())
    pending=RUNTIME/'static-cache-next'
    final=RUNTIME/'static-cache'
    if pending.exists():
        if pending.is_symlink(): raise RuntimeError('unsafe cache directory')
        shutil.rmtree(pending)
    pending.mkdir(mode=0o755)
    assets=pending/'assets';assets.mkdir(mode=0o755)
    total=0
    entry=Path('/opt/bridge-daed-web/index.html');entry_raw=entry.read_bytes()
    if hashlib.sha256(entry_raw).hexdigest()!=seal['files'][str(entry)]['sha256']:raise RuntimeError('unsealed entry HTML')
    refs=set(re.findall(r'(?:src|href)="(?:\./|/)assets/([^"/]+\.(?:js|css))"',entry_raw.decode()))
    if not refs:raise RuntimeError('no entry assets')
    for source in [Path('/opt/bridge-daed-web/assets')/name for name in sorted(refs)]:
        if source.suffix not in ['.js','.css']: continue
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_uid!=0 or before.st_size>16*1024*1024:
                raise RuntimeError('unsafe official asset')
            raw=stream.read(before.st_size+1);after=os.fstat(stream.fileno())
        identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_mode,value.st_uid,value.st_gid)
        if len(raw)!=before.st_size or identity(before)!=identity(after) or identity(after)!=identity(source.lstat()):
            raise RuntimeError('official asset changed during read')
        if hashlib.sha256(raw).hexdigest()!=seal['files'][str(source)]['sha256']:
            raise RuntimeError('official asset does not match seal')
        compressed=gzip.compress(raw,compresslevel=3,mtime=0)
        if gzip.decompress(compressed)!=raw: raise RuntimeError('gzip verification failed')
        total+=len(raw)+len(compressed)
        if total>32*1024*1024: raise RuntimeError('cache budget exceeded')
        for name,data in [(source.name,raw),(source.name+'.gz',compressed)]:
            out=assets/name
            fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
            with os.fdopen(fd,'wb') as stream: stream.write(data)
            os.utime(out,ns=(before.st_atime_ns,before.st_mtime_ns))
    if final.exists():
        if final.is_symlink(): raise RuntimeError('unsafe previous cache')
        shutil.rmtree(final)
    os.replace(pending,final)
    return total


def configuration(address,static_cache=False):
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
    fastcgi_temp_path /run/bridge-daed-web/fastcgi;
    uwsgi_temp_path /run/bridge-daed-web/uwsgi;
    scgi_temp_path /run/bridge-daed-web/scgi;
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    server {
        listen ADDRESS:2023;
        server_name _;
        root /opt/bridge-daed-web;
        index index.html;
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        add_header X-Frame-Options DENY always;
        location = / {
            root /opt/bridge-daed-web-entry;
            try_files /index.html =404;
            add_header Cache-Control "no-store" always;
        }
        location = /bridge-entry.js {
            alias /opt/bridge-daed-web-entry/connect.js;
            add_header Cache-Control "no-store" always;
        }
        # Serve upstream bytes unchanged and retain the existing asset cache.
        location /dashboard/assets/ { rewrite ^/dashboard(/assets/.*)$ $1 last; }
        location /dashboard/ { alias /opt/bridge-daed-web/; }
        location = /graphql {
            proxy_pass http://127.0.0.1:2025/graphql;
            proxy_http_version 1.1;
            proxy_set_header Host 127.0.0.1:2024;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            # Run performs collection, validation and controlled apply before replying.
            proxy_read_timeout 180s;
            client_max_body_size 16m;
        }
        location / { try_files $uri =404; }
    }
}
'''.replace('ADDRESS',address).replace('location / { try_files $uri =404; }', ('location /assets/ { root /run/bridge-daed-web/static-cache; gzip_static on; gzip_vary on; try_files $uri @original_asset; }\n        location @original_asset { root /opt/bridge-daed-web; try_files $uri =404; }\n        location / { try_files $uri =404; }') if static_cache else 'location / { try_files $uri =404; }')


def main():
    value=json.loads((CFG/'web.json').read_text())
    cached=False
    try:
        size=build_static_cache();cached=True
        print(json.dumps({'event':'static_cache_ready','bytes':size,'official_assets_unchanged':True}),file=sys.stderr,flush=True)
    except Exception as error:
        print(json.dumps({'event':'static_cache_fallback','error':type(error).__name__+': '+str(error)}),file=sys.stderr,flush=True)
    body=configuration(value['address'],cached)
    path=RUNTIME/'nginx.conf'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(body)
    os.execv('/usr/sbin/nginx',['/usr/sbin/nginx','-c',str(path),'-g','daemon off;'])
