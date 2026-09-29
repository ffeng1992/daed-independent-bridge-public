"""Private immutable extension generations with explicit CAS and presence."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from .extensions import need,validate_record,extension_specs,split,merge,scalar,render_value
from .upstream_contracts import CONFIG, LEGACY_RECORD, same_section_contract
from bridge_m1.common import canonical
from .runtime_models import model

class ExtensionStore:
    def __init__(self, root):
        self.root=Path(root)
        need(not self.root.is_symlink() and self.root.is_dir() and self.root.stat().st_uid==os.getuid() and stat.S_IMODE(self.root.stat().st_mode)==0o700,'UNSAFE_EXTENSION_DIRECTORY','$')
    def _read(self,name):
        fd=os.open(self.root/name,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            st=os.fstat(stream.fileno())
            need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o600,'UNSAFE_EXTENSION_FILE','$')
            return stream.read()
    def load(self):
        identity=self._read('current').decode().strip()
        need(len(identity)==64 and all(c in '0123456789abcdef' for c in identity),'INVALID_EXTENSION_POINTER','$')
        body=self._read(identity+'.json')
        need(hashlib.sha256(body).hexdigest()==identity,'EXTENSION_INTEGRITY_FAILED','$')
        value=json.loads(body)
        model(value['extensions'])
        for section,records in value['extensions']['records'].items():
            for record in records.values():validate_record(record,section)
        return identity,value
    def _publish(self,value):
        body=canonical(value);identity=hashlib.sha256(body).hexdigest()
        fd=os.open(self.root/(identity+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
        fd,path=tempfile.mkstemp(prefix='.current-',dir=self.root)
        try:
            with os.fdopen(fd,'w') as stream:stream.write(identity+'\n');stream.flush();os.fsync(stream.fileno())
            os.replace(path,self.root/'current')
            d=os.open(self.root,os.O_RDONLY)
            try:os.fsync(d)
            finally:os.close(d)
        finally:Path(path).unlink(missing_ok=True)
        return identity
    def commit(self,extensions=None,*,expected=None,section=None,profile=None,field=None,state=None):
        fd=os.open(self.root/'lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            st=os.fstat(lock.fileno());need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o600,'UNSAFE_EXTENSION_FILE','$')
            fcntl.flock(lock,fcntl.LOCK_EX)
            if expected is None:
                need(not (self.root/'current').exists() and extensions is not None,'EXTENSION_CAS_CONFLICT','$')
                model(extensions)
                for sec,records in extensions['records'].items():
                    for record in records.values():validate_record(record,sec)
                return self._publish({'parent':None,'extensions':extensions,'change':{'action':'import'}})
            ident,current=self.load();need(ident==expected,'EXTENSION_CAS_CONFLICT','$')
            need(section in ('global','dns','group') and profile in current['extensions']['records'][section],'UNKNOWN_PROFILE','$')
            specs=extension_specs(section);need(field in specs,'EXTENSION_OWNERSHIP_CONFLICT','$')
            need(isinstance(state,dict) and type(state.get('present')) is bool and set(state)==({'present','value'} if state['present'] else {'present'}),'INVALID_PRESENCE_STATE','$')
            record=current['extensions']['records'][section][profile];view=validate_record(record,section)
            if record['schemaVersion']==1:
                need(same_section_contract(section,LEGACY_RECORD,CONFIG),
                     'EXTENSION_CONTRACT_CONVERSION_REQUIRED',section)
            fields=json.loads(json.dumps(record['fields']));fields[field]=state
            lines=[]
            for key,entry in sorted(fields.items()):
                if entry['present']:
                    val=entry['value'];typ=specs[key]['type']
                    expected_type=bool if typ=='bool' else int if typ in ('uint32','int') else list if typ=='[]string' else str
                    need(type(val) is expected_type,'INVALID_EXTENSION_TYPE','$')
                    if typ=='[]string':need(all(type(v) is str and ',' not in v for v in val),'INVALID_EXTENSION_TYPE','$')
                    rendered=render_value(val)
                    need(scalar(rendered,specs[key],'$')==val,'INVALID_EXTENSION_TYPE','$')
                    lines.append('  '+key+': '+rendered+'\n')
            end=view.rfind('}');_,updated=split(view[:end].rstrip()+'\n'+''.join(lines)+view[end:],section)
            current['extensions']['records'][section][profile]=updated
            return self._publish({'parent':ident,'extensions':current['extensions'],'change':{'section':section,'profile':profile,'field':field,'state':state}})

    def bind_profiles(self, source, expected):
        """Persist only profiles proved present in a complete official snapshot."""
        from .convert import bind_new_profiles
        from .runtime_bundle import fingerprints
        fd=os.open(self.root/'lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            st=os.fstat(lock.fileno())
            need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
                 and stat.S_IMODE(st.st_mode)==0o600,'UNSAFE_EXTENSION_FILE','$')
            fcntl.flock(lock,fcntl.LOCK_EX)
            ident,current=self.load()
            need(ident==expected,'EXTENSION_CAS_CONFLICT','$')
            fingerprints(source,current['extensions'])
            bound=bind_new_profiles(source,current['extensions'])
            if bound==current['extensions']:
                return ident,False
            return self._publish({'parent':ident,'extensions':bound,
                                  'change':{'action':'bind-official-profiles'}}),True
