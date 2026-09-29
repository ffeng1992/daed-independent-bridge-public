import json
import unittest
from unittest.mock import Mock, patch
from graphql import build_schema, GraphQLError
from bridge_m4.graphql_runtime import Adapter, Controls

SCHEMA='''type User {username: String!} type Config {id: ID!}
type Dae {running:Boolean! modified:Boolean! version:String!}
type RuntimeOverview {uploadRate:Float! udpSessions:Int!}
type General {dae:Dae! interfaces(up:Boolean):[String!]! runtimeOverview(windowSec:Int!,maxPoints:Int!):RuntimeOverview!}
type Query {user:User! token(username:String!,password:String!):String! numberUsers:Int! configs:[Config!]! general:General!}
type Mutation {run(dry:Boolean!):Int! updateConfig(id:ID!):Config!}'''

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.control=Mock();self.control.status.return_value={'state':'running'}
        self.control.dae.side_effect=lambda field,*_: {'running':True,'modified':False,'version':'v2.1.1'}[field]
        self.control.run.return_value=1
        def forward(raw,auth):
            self.calls.append((raw,auth));q=json.loads(raw)['query']
            if q=='{user{username}}':return b'{"data":{"user":{"username":"synthetic"}}}'
            if 'interfaces' in q:return b'{"data":{"general":{"interfaces":["synthetic0"]}}}'
            if 'runtimeOverview' in q:
                return b'{"data":{"general":{"runtimeOverview":{"uploadRate":0,"udpSessions":0}}}}'
            return b'{"data":{"numberUsers":1}}'
        self.forward=Mock(side_effect=forward)
        self.adapter=Adapter(build_schema(SCHEMA),self.control,self.forward)
    def runq(self,query,variables=None,name=None):
        return json.loads(self.adapter.handle(json.dumps({'query':query,'variables':variables,'operationName':name}).encode(),'Bearer synthetic'))
    def test_ordinary_bytes_unchanged(self):
        raw=b'{ "query":"{numberUsers}", "variables": {} }'
        self.adapter.handle(raw,'Bearer synthetic')
        self.assertEqual(self.calls,[(raw,'Bearer synthetic')])
    def test_alias_fragment_directive(self):
        r=self.runq('query X($show:Boolean!){general{...D}} fragment D on General {x:dae{running modified version @include(if:$show)}}',{'show':True})
        self.assertEqual(r['data']['general']['x'],{'running':True,'modified':False,'version':'v2.1.1'})
    def test_selected_operation_only(self):
        self.runq('query A{numberUsers} mutation B{run(dry:true)}',name='A')
        self.control.run.assert_not_called();self.assertEqual(len(self.calls),1)
    def test_skipped_run_no_control(self):
        self.runq('mutation{run(dry:true) @skip(if:true)}');self.control.run.assert_not_called()
    def test_run_never_forwarded(self):
        self.assertEqual(self.runq('mutation($dry:Boolean!){x:run(dry:$dry)}',{'dry':True})['data'],{'x':1})
        self.control.run.assert_called_once_with('synthetic',True)
        self.assertFalse(any('run(' in json.loads(b)['query'] for b,_ in self.calls))
    def test_unauthorized_no_runtime_disclosure(self):
        self.forward.side_effect=None;self.forward.return_value=b'{"errors":[{"message":"access denied"}]}'
        r=self.runq('{general{dae{running}}}')
        self.assertEqual(r['errors'][0]['message'],'access denied');self.control.status.assert_not_called()
    def test_invalid_run_no_side_effect(self):
        r=self.runq('mutation{run(dry:"true")}');self.assertIn('errors',r);self.control.run.assert_not_called()
    def test_missing_operation_no_side_effect(self):
        self.runq('query A{numberUsers} mutation B{run(dry:true)}');self.control.run.assert_not_called()
    def test_telemetry_forwarded_without_adapter_error(self):
        raw=b'{"query":"{general{runtimeOverview(windowSec:60,maxPoints:60){uploadRate udpSessions}}}"}'
        self.assertEqual(self.adapter.handle(raw,'Bearer synthetic'),
                         b'{"data":{"general":{"runtimeOverview":{"uploadRate":0,"udpSessions":0}}}}')
        self.assertEqual(self.calls,[(raw,'Bearer synthetic')])
        self.control.status.assert_not_called()
    def test_mixed_runtime_dae_and_overview(self):
        r=self.runq('{general{dae{running} runtimeOverview(windowSec:60,maxPoints:60){uploadRate udpSessions}}}')
        self.assertEqual(r['data']['general'],{'dae':{'running':True},
                                                'runtimeOverview':{'uploadRate':0,'udpSessions':0}})
        self.assertNotIn('errors',r)
    def test_mixed_general_preserves_interfaces(self):
        r=self.runq('query X($up:Boolean){general{interfaces(up:$up) dae{running}}}',{'up':True})
        self.assertEqual(r['data']['general'],{'interfaces':['synthetic0'],'dae':{'running':True}})
    def test_literal_run_word_is_ordinary(self):
        self.runq('query{token(username:"run",password:"synthetic-only")}',{})
        self.control.run.assert_not_called();self.assertEqual(len(self.calls),1)

class ControlsTests(unittest.TestCase):
    def test_empty_referenced_group_is_named_without_control_side_effects(self):
        from bridge_m4.extensions import CompatibilityError
        r=Mock();r.status.return_value={'state':'running','activeBundle':'old'}
        r.preview.side_effect=CompatibilityError('EMPTY_REFERENCED_GROUP','groups.empty_fixture.nodes')
        with self.assertRaises(GraphQLError) as raised:Controls(r).run('synthetic',False)
        self.assertEqual(raised.exception.extensions,{'code':'EMPTY_REFERENCED_GROUP','groupName':'empty_fixture','fieldPath':'groups.empty_fixture.nodes'})
        r.action.assert_not_called();r.apply.assert_not_called();r.validate.assert_not_called()

    def test_stop_confirmed(self):
        r=Mock();r.status.return_value={'state':'running','activeBundle':'synthetic'};r.action.return_value={'state':'stopped'}
        self.assertEqual(Controls(r).run('synthetic',True),1);r.action.assert_called_once_with('stop','synthetic')
    def test_stop_failure_not_success(self):
        r=Mock();r.status.return_value={'state':'running','activeBundle':'synthetic'};r.action.return_value={'error':'BUSY'}
        with self.assertRaises(GraphQLError):Controls(r).run('synthetic',True)
    def test_unchanged_stopped_bundle_starts(self):
        r=Mock();r.status.side_effect=[{'state':'stopped','activeBundle':'b','sourceFingerprint':'s'},{'state':'running','identityVerified':True},{'state':'running','identityVerified':True}]
        r.preview.return_value={'previewId':'p','sourceFingerprint':'s'};r.action.return_value={'state':'running'}
        self.assertEqual(Controls(r).run('synthetic',False),1)
        r.action.assert_called_once_with('start','b');r.apply.assert_not_called();r.validate.assert_called_once_with('p')
    def test_changed_stopped_bundle_resumes_verified_predecessor_before_apply(self):
        r=Mock();r.status.side_effect=[{'state':'stopped','activeBundle':'old','sourceFingerprint':'old-source'},{'state':'running','identityVerified':True},{'state':'running','identityVerified':True}]
        r.preview.return_value={'previewId':'p','sourceFingerprint':'new-source'}
        r.action.return_value={'state':'running','identityVerified':True};r.apply.return_value={'result':{'result':'APPLIED'}}
        self.assertEqual(Controls(r).run('synthetic',False),1)
        from unittest.mock import call
        relevant=[c for c in r.mock_calls if c[0] in ('validate','action','apply')]
        self.assertEqual(relevant,[call.validate('p'),call.action('start','old'),call.apply('synthetic','p')])
    def test_failed_predecessor_resume_never_applies(self):
        for result in ({'error':'BUSY'},{'state':'stopped'},{'state':'running','identityVerified':False}):
            r=Mock();r.status.return_value={'state':'stopped','activeBundle':'old','sourceFingerprint':'old-source'}
            r.preview.return_value={'previewId':'p','sourceFingerprint':'new-source'};r.action.return_value=result
            with self.assertRaises(GraphQLError):Controls(r).run('synthetic',False)
            r.apply.assert_not_called()
    def test_invalid_candidate_never_resumes_stopped_predecessor(self):
        r=Mock();r.status.return_value={'state':'stopped','activeBundle':'old'}
        r.preview.return_value={'previewId':'p','sourceFingerprint':'new-source'};r.validate.side_effect=RuntimeError('VALIDATE_FAILED')
        with self.assertRaises(GraphQLError):Controls(r).run('synthetic',False)
        r.action.assert_not_called();r.apply.assert_not_called()
    def test_receipt_failure_not_bypassed(self):
        r=Mock();r.status.return_value={'state':'running','activeBundle':'b'};r.preview.return_value={'previewId':'p','sourceFingerprint':'s'};r.apply.side_effect=RuntimeError('receipt')
        with self.assertRaises(GraphQLError):Controls(r).run('synthetic',False)
        r.action.assert_not_called()
    def test_modified_compares_joint_source_extension_fingerprint(self):
        r=Mock();r.snapshot.return_value=({'source':'synthetic'},None,{'extension':'synthetic'},None)
        s={'activeBundle':'b','sourceFingerprint':'same'}
        with patch('bridge_m4.runtime_bundle.fingerprints',return_value={'sourceSha256':'same'}) as pins:
            self.assertFalse(Controls(r).dae('modified',s,'synthetic'))
            pins.assert_called_once_with({'source':'synthetic'},{'extension':'synthetic'})
        with patch('bridge_m4.runtime_bundle.fingerprints',return_value={'sourceSha256':'changed'}):
            self.assertTrue(Controls(r).dae('modified',s,'synthetic'))
    def test_missing_active_fingerprint_fails_closed(self):
        r=Mock();r.snapshot.return_value=({},None,{},None)
        with self.assertRaises(GraphQLError):Controls(r).dae('modified',{'activeBundle':'b'},'synthetic')
    def test_stopped_version_uses_verified_official_install(self):
        lock={'components':{'dae':{'version':'v2.1.1','archive_members':[{'path':'dae-linux-x86_64','sha256':'pin'}]}}}
        with patch('bridge_m4.graphql_runtime.Path.read_text',return_value=json.dumps(lock)), \
             patch('bridge_m4.graphql_runtime.Path.read_bytes',return_value=b'synthetic'), \
             patch('bridge_m4.authority.manifest') as verified, \
             patch('bridge_m1.common.digest',return_value='pin'):
            self.assertEqual(Controls(Mock()).dae('version',{'state':'stopped','MainPID':0},''),'v2.1.1')
            verified.assert_called_once()
    def test_unknown_identity_not_running_false(self):
        with self.assertRaises(GraphQLError):Controls(Mock()).dae('running',{'state':'running','identityVerified':False},'synthetic')

if __name__=='__main__':unittest.main()
