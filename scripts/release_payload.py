"""Release-only DNS units; production profile bytes remain untouched."""
UNITS=('bridge-lan-dns.service','bridge-policy-dns.service',
       'independent-dns-sync.service','independent-policy-sync.service')

def payload(root):
    files={'/etc/systemd/system/'+n:((root/'deployment/release/units'/n).read_bytes(),0o644) for n in UNITS}
    for n in ('independent-dns-sync.timer','independent-policy-sync.timer'):
        files['/etc/systemd/system/'+n]=((root/'deployment/m4/units'/n).read_bytes(),0o644)
    return files
