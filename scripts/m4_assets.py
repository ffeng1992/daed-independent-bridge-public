"""Offline extraction of locked official DAE routing data, never arbitrary paths."""
import hashlib
import io
import zipfile


def official_assets(raw, lock):
    def require(ok, code):
        if not ok:raise ValueError(code)
    require(hashlib.sha256(raw).hexdigest()==lock['sha256'],'OFFICIAL_ARCHIVE_HASH')
    pins={p['path']:p for p in lock['archive_members']}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=[m for m in archive.infolist() if not m.is_dir()]
        require(len(members)==len(pins) and {m.filename for m in members}==set(pins),'OFFICIAL_MEMBER_SET')
        result={}
        for member in members:
            body=archive.read(member);pin=pins[member.filename]
            require(len(body)==pin['size'] and hashlib.sha256(body).hexdigest()==pin['sha256'],'OFFICIAL_MEMBER_HASH')
            if member.filename in ('geoip.dat','geosite.dat'):result[member.filename]=body
        require(set(result)=={'geoip.dat','geosite.dat'},'OFFICIAL_ASSETS_MISSING')
        return result
