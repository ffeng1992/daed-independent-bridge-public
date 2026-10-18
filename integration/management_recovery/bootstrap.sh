#!/bin/sh
set -eu
trap 'systemctl poweroff' EXIT

ROOT=/opt/bridge
RESULT=/evidence/management-recovery-result.json
export PYTHONDONTWRITEBYTECODE=1

install -d -m 0755 /opt/bridge/scripts /opt/bridge/bridge_m4
install -m 0644 /mnt/project/scripts/management_recovery.py /opt/bridge/scripts/management_recovery.py
printf '' > /opt/bridge/scripts/__init__.py
printf '' > /opt/bridge/bridge_m4/__init__.py
cat > /opt/bridge/bridge_m4/authority.py <<'PY'
from pathlib import Path
def manifest():
    if not Path('/run/identity-ok').exists():
        raise RuntimeError('INSTALL_FILE_IDENTITY')
PY
cat > /usr/local/bin/bridge-management-recovery <<'PY'
import sys
sys.dont_write_bytecode=True
sys.path[:0]=["/opt/bridge/vendor","/opt/bridge"]
from scripts.management_recovery import entrypoint
raise SystemExit(entrypoint())
PY
chmod 0755 /usr/local/bin/bridge-management-recovery

cat > /usr/local/bin/fake-management-endpoint <<'PY'
#!/usr/bin/python3
import argparse,json,signal,ssl,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);p.add_argument('--tls',action='store_true');a=p.parse_args()
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  body=(json.dumps({'csrf':'synthetic'}) if self.server.server_port==8443 else 'official web').encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_POST(self):
  n=int(self.headers.get('Content-Length','0'));self.rfile.read(n);body=b'{"data":{"numberUsers":1}}';self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
s=ThreadingHTTPServer(('127.0.0.1',a.port),H)
if a.tls:
 c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);c.load_cert_chain('/etc/daed-independent-bridge/tls.crt','/etc/daed-independent-bridge/tls.key');s.socket=c.wrap_socket(s.socket,server_side=True)
def hang(*_):
 s.server_close()
 while True: time.sleep(60)
signal.signal(signal.SIGUSR1,hang);s.serve_forever()
PY
chmod 0755 /usr/local/bin/fake-management-endpoint

getent group independent-bridge >/dev/null || groupadd --system independent-bridge
getent passwd independent-bridge >/dev/null || useradd --system --gid independent-bridge --home-dir /nonexistent --shell /usr/sbin/nologin independent-bridge
install -d -m 0755 /etc/daed-independent-bridge /var/lib/daed-independent-bridge /var/lib/bridge-m4-attestation /var/lib/primary-rollback
install -d -o independent-bridge -g independent-bridge -m 0750 /var/lib/bridge-m4-client
install -d -o independent-bridge -g independent-bridge -m 0770 /var/lib/bridge-m4-client/management-recovery
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 -keyout /etc/daed-independent-bridge/tls.key -out /etc/daed-independent-bridge/tls.crt >/dev/null 2>&1
printf '{"address":"127.0.0.1","origin":"https://127.0.0.1:8443"}\n' > /etc/daed-independent-bridge/web.json
printf '{"schemaVersion":1,"sourceSha256":"synthetic","expiresAt":"2000-01-01T00:00:00Z"}\n' > /var/lib/bridge-m4-attestation/receipt.json
printf '{"phase":"HEALTHY","rollbackNeeded":false}\n' > /var/lib/daed-independent-bridge/transaction.json
touch /var/lib/daed-independent-bridge/apply.lock
touch /run/identity-ok

unit() {
 name=$1; port=$2; extra=${3:-}
 cat > "/etc/systemd/system/$name" <<EOF
[Unit]
Description=Synthetic $name
[Service]
ExecStart=/usr/local/bin/fake-management-endpoint --port $port $extra
Restart=no
EOF
}
unit daed-api.service 2024
unit bridge-graphql.service 2025
sed -i '/Description=/a Requires=daed-api.service\nAfter=daed-api.service' /etc/systemd/system/bridge-graphql.service
cat > /etc/systemd/system/bridge-attestor.service <<'EOF'
[Unit]
Requires=daed-api.service
After=daed-api.service
[Service]
ExecStart=/bin/sleep infinity
Restart=no
EOF
unit daed-web.service 2023
sed -i '/Description=/a Requires=daed-api.service bridge-graphql.service\nAfter=daed-api.service bridge-graphql.service' /etc/systemd/system/daed-web.service
unit independent-bridge.service 8443 --tls
install -m 0644 /mnt/project/deployment/release/units/bridge-management-recovery.service /etc/systemd/system/
systemctl daemon-reload
systemctl start daed-api bridge-graphql bridge-attestor daed-web independent-bridge

cat > /tmp/accept.py <<'PY'
import json,subprocess,time
from pathlib import Path
S=('daed-api.service','bridge-graphql.service','bridge-attestor.service','daed-web.service','independent-bridge.service')
out={}; checks=0
def sh(*a,ok=True):return subprocess.run(a,text=True,capture_output=True,check=ok)
def active(n):return sh('systemctl','is-active',n,ok=False).stdout.strip()=='active'
def invoke(n=2):
 global checks
 for _ in range(n):
  sh('systemctl','start','bridge-management-recovery.service');checks+=1
def reset():
 Path('/var/lib/daed-independent-bridge/management-recovery.json').unlink(missing_ok=True)
 Path('/etc/daed-independent-bridge/management-recovery.pause').unlink(missing_ok=True)
 control=Path('/var/lib/bridge-m4-client/management-recovery')
 (control/'pause.json').unlink(missing_ok=True);(control/'resume.json').unlink(missing_ok=True)
 Path('/var/lib/primary-rollback/rollback-required.json').unlink(missing_ok=True)
 Path('/run/identity-ok').touch()
 sh('systemctl','reset-failed',*S,ok=False)
 sh('systemctl','start',*S)
def record(name,value):
 out[name]=bool(value)
 if not value:raise RuntimeError(name)
reset();before={n:sh('systemctl','show',n,'-p','InvocationID','--value').stdout.strip() for n in S};invoke(1);record('healthy_no_restart',before=={n:sh('systemctl','show',n,'-p','InvocationID','--value').stdout.strip() for n in S})
state=json.loads(Path('/var/lib/daed-independent-bridge/management-recovery.json').read_text());record('structured_state',state['lastCheckResult']=='HEALTHY' and len(state['services'])==5 and type(state['history']) is list)
reset();sh('systemctl','stop','daed-web');invoke();record('normal_stop',active('daed-web.service'))
reset();sh('systemctl','kill','--signal=KILL','bridge-graphql');time.sleep(.5);invoke();record('process_crash',active('bridge-graphql.service'))
reset();pid=int(sh('systemctl','show','independent-bridge','-p','MainPID','--value').stdout);sh('kill','-USR1',str(pid));time.sleep(.5);invoke();record('http_hang',active('independent-bridge.service'))
reset();sh('systemctl','stop','daed-api');record('api_cascade',not active('bridge-graphql.service') and not active('bridge-attestor.service') and not active('daed-web.service'));invoke();record('dependency_recovery',all(active(n) for n in S))
reset();cap='/tmp/management-before.json';sh('/usr/bin/python3','-I','/usr/local/bin/bridge-management-recovery','--capture',cap);sh('systemctl','stop','daed-api');sh('/usr/bin/python3','-I','/usr/local/bin/bridge-management-recovery','--restore',cap);record('rollback_restore',all(active(n) for n in S))
reset();sh('/usr/bin/python3','-I','/usr/local/bin/bridge-management-recovery','--pause');sh('systemctl','stop','daed-web');invoke(3);record('maintenance_pause',not active('daed-web.service'))
reset();control=Path('/var/lib/bridge-m4-client/management-recovery');control.mkdir(mode=0o770,exist_ok=True);(control/'pause.json').write_text('{"schemaVersion":1}\n');sh('systemctl','stop','daed-web');invoke(3);record('bridge_web_pause',not active('daed-web.service'));(control/'resume.json').write_text('{"schemaVersion":1}\n');invoke(2);record('bridge_web_resume',active('daed-web.service') and not (control/'pause.json').exists() and not (control/'resume.json').exists())
reset();Path('/var/lib/primary-rollback/rollback-required.json').write_text('{}');sh('systemctl','stop','daed-web');invoke(3);record('rollback_needed',not active('daed-web.service'))
reset();Path('/run/identity-ok').unlink();sh('systemctl','stop','daed-web');invoke(3);record('identity_mismatch',not active('daed-web.service'))
reset();original=Path('/etc/systemd/system/daed-web.service').read_text();Path('/etc/systemd/system/daed-web.service').write_text('[Service]\nExecStart=/bin/false\nRestart=no\n');sh('systemctl','daemon-reload');sh('systemctl','stop','daed-web',ok=False);invoke(5);state=json.loads(Path('/var/lib/daed-independent-bridge/management-recovery.json').read_text());record('rate_limit',len(state['services']['daed-web.service']['attempts'])==2);Path('/etc/systemd/system/daed-web.service').write_text(original);sh('systemctl','daemon-reload')
reset();sh('systemctl','stop','independent-bridge');invoke();record('checker_independent',active('independent-bridge.service'))
out.update(passed=all(out.values()),checks=checks,scenarios=14)
Path('/evidence/management-recovery-result.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n')
PY
touch /evidence/bootstrap-ready
while test ! -e /evidence/network-detached; do sleep 1; done
if ! python3 /tmp/accept.py; then
 systemctl status bridge-management-recovery.service --no-pager || true
 journalctl -u bridge-management-recovery.service -n 80 --no-pager || true
 exit 1
fi
