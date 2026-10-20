import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from bridge_m4.official_web import configuration
from scripts.release_frontend import unpack

class FrontendTests(unittest.TestCase):
    def test_fixed_frontend_install_paths(self):
        from scripts.m4_install_transaction import allowed
        self.assertTrue(allowed('/opt/bridge-daed-web/index.html'))
        self.assertTrue(allowed('/opt/bridge-daed-web-entry/connect.js'))
        self.assertFalse(allowed('/opt/bridge-daed-web-other/index.html'))

    def test_runtime_manifest_accepts_frontend_and_checks_hash(self):
        # Execute the actual manifest function against an in-memory filesystem;
        # unrelated controller/schema dependencies are unnecessary for this check.
        import ast
        from unittest.mock import Mock
        source=(Path(__file__).resolve().parents[2]/'bridge_m4/authority.py').read_text()
        function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='manifest')
        def check(ok,code):
            if not ok:raise RuntimeError(code)
        for name in ('/opt/bridge-daed-web/index.html','/opt/bridge-daed-web-entry/connect.js'):
            body=b'official fixture'
            record={'schemaVersion':1,'files':{name:{'sha256':hashlib.sha256(body).hexdigest(),'mode':0o444}}}
            for actual,expected in ((body,True),(b'changed',False)):
                scope={'Path':Path,'MANIFEST':Path('/etc/daed-independent-bridge/install.json'),
                       'directory':Mock(return_value=123),'os':Mock(),'check':check,
                       'load_json':json.loads,'digest':lambda b:hashlib.sha256(b).hexdigest(),
                       'read_at':Mock(side_effect=[json.dumps(record).encode(),actual])}
                exec(compile(ast.Module(body=[function],type_ignores=[]),'authority.py','exec'),scope)
                if expected:self.assertEqual(scope['manifest'](),record)
                else:
                    with self.assertRaisesRegex(RuntimeError,'INSTALL_FILE_IDENTITY'):scope['manifest']()

    def fixture(self,changes=None):
        files={'index.html':b'<html>official synthetic</html>','assets/app.js':b'official synthetic'}
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as archive:
            for n,b in (changes or files).items():
                m=tarfile.TarInfo('web/'+n);m.size=len(b);archive.addfile(m,io.BytesIO(b))
        raw=buf.getvalue()
        pin={'sha256':hashlib.sha256(raw).hexdigest(),'archivePrefix':'web/',
             'files':[{'path':n,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()]}
        return raw,pin,files
    def test_exact_unmodified_assets(self):
        raw,pin,files=self.fixture();self.assertEqual(unpack(raw,pin),files)
    def test_archive_member_and_path_failure(self):
        raw,pin,_=self.fixture()
        with self.assertRaisesRegex(RuntimeError,'ARCHIVE_HASH'):unpack(raw+b'x',pin)
        for changes in ({'index.html':b'changed'}, {'../escape':b'x'}):
            raw,_,_=self.fixture(changes);pin['sha256']=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(RuntimeError):unpack(raw,pin)
    def test_proxy_is_fixed_loopback_and_frontend_tls(self):
        config=configuration('192.0.2.1')
        self.assertIn('listen 192.0.2.1:2023;',config)
        self.assertIn('index index.html;',config)
        self.assertIn('root /opt/bridge-daed-web-entry;',config)
        self.assertIn('try_files /index.html =404;',config)
        self.assertIn('location = /dashboard/',config)
        self.assertIn('location /official/',config)
        self.assertIn('X-Frame-Options SAMEORIGIN',config)
        self.assertIn("frame-ancestors 'self'",config)
        self.assertIn('proxy_pass http://127.0.0.1:2025/graphql;',config)
        self.assertIn('proxy_read_timeout 180s;',config)
        self.assertNotIn('listen 192.0.2.1:2024',config)
        self.assertNotIn('8444',config)
        for address in ('0; shutdown','example.invalid','192.0.2.1\nroot /;'):
            with self.assertRaises(ValueError):configuration(address)
    def test_existing_cache_and_dashboard_assets_are_preserved(self):
        config=configuration('192.0.2.1',True)
        self.assertIn('root /run/bridge-daed-web/static-cache;',config)
        self.assertIn('gzip_static on;',config)
        self.assertIn('location @original_asset',config)
        self.assertIn('rewrite ^/dashboard(/assets/.*)$ $1 last;',config)
        self.assertNotIn('sub_filter',config)

    def test_official_default_endpoint_without_launcher(self):
        root=Path(__file__).resolve().parents[2]
        self.assertFalse((root/'deployment/release/daed-web/connect.js').exists())
        self.assertTrue((root/'deployment/release/daed-web-entry/connect.js').is_file())
        unit=(root/'deployment/m4/units/daed-api.service').read_text()
        self.assertIn('--api-only',unit);self.assertIn('--listen 127.0.0.1:2024',unit)
    def test_existing_version_stop_skips_missing_web_only(self):
        from scripts import release_lifecycle as lifecycle
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch.object(Path,'exists',return_value=False),patch.object(lifecycle,'ctl',return_value=SimpleNamespace(stdout=b'ActiveState=inactive\nMainPID=0\n')) as calls:
            lifecycle.stop()
        self.assertFalse(any('daed-web.service' in c.args for c in calls.call_args_list))
        self.assertTrue(any('dae.service' in c.args for c in calls.call_args_list))

class EntryTests(unittest.TestCase):
    def exercise(self, token='synthetic-browser-token', response=None, status=200, failure=False, actions=None):
        import subprocess
        script=r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(process.argv[1]);
const values=new Map(Object.entries(input.token===null?{}:{token:input.token,endpointURL:'https://obsolete.invalid/graphql'}));
const requests=[],historyPaths=[],handlers={},frameHandlers={};
const location={origin:'http://192.0.2.1:2023',hash:'#/setup'};
const frame={hidden:true,contentWindow:{location:{pathname:'about:blank',hash:''}}};
Object.defineProperty(frame,'src',{set(v){this.target=v;const [path,hash]=v.split('#');this.contentWindow.location={origin:location.origin,pathname:path,hash:'#'+hash};},get(){return this.target;}});
frame.addEventListener=(key,fn)=>frameHandlers[key]=fn;
const elements={status:{},message:{},dashboard:frame,retry:{addEventListener(){}}};
const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
const context={document:{getElementById:id=>elements[id]},window:{addEventListener:(k,f)=>handlers[k]=f},
 localStorage:storage,location,history:{replaceState(_a,_b,path){historyPaths.push(path);location.hash=path.slice(path.indexOf('#'));}},
 AbortController,setTimeout,clearTimeout,fetch:async(url,options)=>{
 requests.push({url,authorizationBearer:options.headers.Authorization.startsWith('Bearer '),query:JSON.parse(options.body).query});
 if(input.failure)throw Error('synthetic offline');
 return {status:input.status,ok:input.status===200,json:async()=>input.response};
 }};
(async()=>{await vm.runInNewContext(fs.readFileSync('deployment/release/daed-web-entry/connect.js','utf8'),context);
 for(const action of input.actions||[]){
 if(action==='login')values.set('token','synthetic-new-login');
 if(action==='logout')values.delete('token');
 if(action==='login'||action==='logout'){handlers.storage({key:'token',storageArea:storage});await new Promise(r=>setTimeout(r,0));}
 if(action==='old-bookmark'){location.hash='#/setup';handlers.hashchange();}
 }
 console.log(JSON.stringify({frame:frame.target,history:historyPaths,requests,tokenPresent:!!values.get('token'),endpoint:values.get('endpointURL'),retry:elements.retry.hidden===false,frameHidden:frame.hidden}));})();
'''
        raw=subprocess.check_output(['node','-e',script,json.dumps({'token':token,'response':response,'status':status,'failure':failure,'actions':actions})],cwd=Path(__file__).resolve().parents[2],timeout=10)
        return json.loads(raw)

    def test_valid_session_ignores_obsolete_setup_route(self):
        value=self.exercise(response={'data':{'user':{'username':'synthetic'}}})
        self.assertEqual(value['frame'],'/official/#/')
        self.assertTrue(value['tokenPresent'])
        self.assertEqual(value['endpoint'],'http://192.0.2.1:2023/graphql')
        self.assertEqual(value['requests'][0]['url'],'/graphql')
        self.assertTrue(value['requests'][0]['authorizationBearer'])
        self.assertEqual(value['requests'][0]['query'],'{ user { username } }')

    def test_missing_session_uses_official_login_without_api_call(self):
        value=self.exercise(token=None)
        self.assertEqual(value['frame'],'/official/#/setup')
        self.assertEqual(value['requests'],[])

    def test_real_storage_event_after_official_login_leaves_remounted_setup(self):
        value=self.exercise(token=None,response={'data':{'user':{'username':'synthetic'}}},actions=['login'])
        self.assertEqual(value['frame'],'/official/#/')
        self.assertEqual(len(value['requests']),1)
        self.assertTrue(value['tokenPresent'])

    def test_clicking_old_bookmark_with_valid_session_stays_home(self):
        value=self.exercise(response={'data':{'user':{'username':'synthetic'}}},actions=['old-bookmark'])
        self.assertEqual(value['frame'],'/official/#/')
        self.assertEqual(len(value['requests']),1)

    def test_official_logout_returns_to_official_setup(self):
        value=self.exercise(response={'data':{'user':{'username':'synthetic'}}},actions=['logout'])
        self.assertEqual(value['frame'],'/official/#/setup')
        self.assertFalse(value['tokenPresent'])

    def test_expired_or_rejected_token_cannot_enter_dashboard(self):
        for code in (200,401,403):
            with self.subTest(code=code):
                value=self.exercise(response={'errors':[{'message':'access denied'}]},status=code)
                self.assertEqual(value['frame'],'/official/#/setup')
                self.assertFalse(value['tokenPresent'])

    def test_network_failure_never_clears_token_or_enters_dashboard(self):
        value=self.exercise(failure=True)
        self.assertTrue(value['tokenPresent']);self.assertTrue(value['retry'])
        self.assertIsNone(value.get('frame'))
        self.assertTrue(value['frameHidden'])

    def test_unknown_server_error_does_not_logout_or_bypass_auth(self):
        for response in ({'errors':[{'message':'database unavailable'}]},{'data':{'user':None}},{'data':{'user':{'id':'wrong schema'}}}):
            with self.subTest(response=response):
                value=self.exercise(response=response)
                self.assertTrue(value['tokenPresent']);self.assertTrue(value['retry'])
                self.assertIsNone(value.get('frame'))
                self.assertTrue(value['frameHidden'])

    def test_entry_is_packaged_separately_from_original_assets(self):
        import shutil
        import tempfile
        from scripts import release_frontend
        from unittest.mock import patch
        source=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'official').mkdir()
            (root/'upstream.lock.json').write_text(json.dumps({'webFrontend':{'license':{'sha256':hashlib.sha256(b'license').hexdigest()}}}))
            (root/'official/daed-web-LICENSE').write_bytes(b'license')
            (root/'official/daed-web.tar.gz').write_bytes(b'archive')
            shutil.copytree(source/'deployment/release/daed-web-entry',root/'deployment/release/daed-web-entry')
            with patch.object(release_frontend,'unpack',return_value={'index.html':b'official'}):
                files=release_frontend.payload(root)
        self.assertEqual(files['/opt/bridge-daed-web/index.html'],(b'official',0o444))
        for name in ('index.html','connect.js'):
            self.assertEqual(files['/opt/bridge-daed-web-entry/'+name],((source/'deployment/release/daed-web-entry'/name).read_bytes(),0o444))
