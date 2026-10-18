"""Release-only DNS units; production profile bytes remain untouched."""
UNITS=('daed-web.service','bridge-lan-dns.service','bridge-policy-dns.service',
       'independent-dns-sync.service','independent-policy-sync.service',
       'bridge-management-recovery.service','bridge-management-recovery.timer')

def payload(root):
    files={'/etc/systemd/system/'+n:((root/'deployment/release/units'/n).read_bytes(),0o644) for n in UNITS}
    files['/opt/bridge/scripts/management_recovery.py']=((root/'scripts/management_recovery.py').read_bytes(),0o644)
    files['/usr/local/bin/bridge-management-recovery']=(
        b'import sys\nsys.dont_write_bytecode=True\nsys.path[:0]=["/opt/bridge/vendor","/opt/bridge"]\nfrom scripts.management_recovery import entrypoint\nraise SystemExit(entrypoint())\n',0o755)
    for n in ('independent-dns-sync.timer','independent-policy-sync.timer'):
        files['/etc/systemd/system/'+n]=((root/'deployment/m4/units'/n).read_bytes(),0o644)
    from scripts.release_frontend import payload as frontend_payload
    files.update(frontend_payload(root))
    return files
