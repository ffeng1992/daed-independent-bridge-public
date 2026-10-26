import datetime
import json
import threading
import time
import unittest
from unittest.mock import Mock
from graphql import build_schema
from bridge_m4.graphql_runtime import Adapter
from bridge_m4.node_latencies import NodeLatencies, ProbeError

SCHEMA = '''scalar Time
 type User {username:String!}
 type NodeLatency {id:ID! latencyMs:Int alive:Boolean! testedAt:Time! message:String}
 type Query {user:User! numberUsers:Int! nodeLatencies(ids:[ID!]):[NodeLatency!]!}
 type Mutation {testNodeLatencies(ids:[ID!]):[NodeLatency!]!}'''


class LatenciesTests(unittest.TestCase):
    def setUp(self):
        self.now = float(int(time.time()))
        self.clock = 1000.
        self.nodes = [{'id':'a','link':'ss://synthetic-secret','subscriptionID':None},
                      {'id':'b','link':'ss://synthetic-two','subscriptionID':None}]
        self.calls = []
        self.block = None
        self.failure = None
        self.probe = NodeLatencies(self.transport, clock=lambda:self.clock, wall=lambda:self.now)
        self.probe.INTERVAL = 10
    def rows(self, ids):
        return [{'id':i,'latencyMs':13 + n,'alive':True,
                 'testedAt':datetime.datetime.fromtimestamp(self.now, datetime.timezone.utc).isoformat(),
                 'message':None} for n,i in enumerate(ids)]
    def transport(self, raw, auth, timeout):
        request=json.loads(raw);query=request['query'];self.calls.append((request,auth,timeout))
        if query.startswith('{subscriptions{id}'):data={'subscriptions':[],'groups':[]}
        elif 'nodes(' in query:
            data={'nodes':{'totalCount':len(self.nodes),'edges':self.nodes,
                          'pageInfo':{'hasNextPage':False,'endCursor':self.nodes[-1]['id'] if self.nodes else None}}}
        elif 'testNodeLatencies' in query:
            if self.block:self.block.wait(2)
            if self.failure:raise self.failure
            data={'testNodeLatencies':self.rows(request['variables']['ids'])}
        else:raise ValueError('unexpected query')
        return json.dumps({'data':data}).encode()
    def settle(self):
        deadline=time.monotonic()+3
        while self.probe.busy and time.monotonic()<deadline:time.sleep(.002)
        self.assertFalse(self.probe.busy)
    def read(self,ids=None):return self.probe.read('Bearer synthetic','user',ids)
    def seeded(self):
        self.read();self.settle()
        return self.read()[0]
    def test_manual_results_are_immediately_readable_without_second_probe(self):
        before = self.probe.inventory('Bearer synthetic')
        self.probe.remember_manual('Bearer synthetic', 'user', before, self.rows(['a','b']))
        rows, state = self.read()
        self.assertEqual(rows, self.rows(['a','b']))
        self.assertEqual(state['attempts'], 0)

    def test_manual_changed_identity_and_partial_results_not_cached(self):
        before = self.probe.inventory('Bearer synthetic')
        self.nodes[0]['link'] = 'ss://changed'
        with self.assertRaisesRegex(ProbeError, 'NODE_INVENTORY_CHANGED'):
            self.probe.remember_manual('Bearer synthetic', 'user', before, self.rows(['a']))
        self.assertEqual(self.probe.records, {})
        before = self.probe.inventory('Bearer synthetic')
        with self.assertRaisesRegex(ProbeError, 'OFFICIAL_LATENCY_SCHEMA'):
            self.probe.remember_manual('Bearer synthetic', 'user', before, [{'id':'a'}])
        self.assertEqual(self.probe.records, {})

    def test_unknown_initially_empty_and_official_results_exact(self):
        self.block=threading.Event()
        result,state=self.read();self.assertEqual(result,[]);self.assertEqual(state['inFlight'],1)
        self.block.set();self.settle();self.assertEqual(self.read()[0],self.rows(['a','b']))
    def test_home_does_not_wait_for_probe(self):
        self.block=threading.Event();start=time.monotonic();self.read()
        self.assertLess(time.monotonic()-start,.2);self.block.set();self.settle()
    def test_single_background_task_under_repeated_reads(self):
        self.block=threading.Event()
        for _ in range(20):self.read()
        self.assertEqual(self.probe.attempts,1)
        self.block.set();self.settle()
    def test_small_batch_and_timeout(self):
        self.seeded();calls=[c for c in self.calls if 'testNodeLatencies' in c[0]['query']]
        self.assertEqual(len(calls),1);self.assertLessEqual(len(calls[0][0]['variables']['ids']),2)
        self.assertEqual(calls[0][2],12)
        self.assertFalse(any('query' in c[0]['query'].lower() and 'nodeLatencies' in c[0]['query'] for c in self.calls))
    def test_timeout_circuit_never_accumulates_upstream_jobs(self):
        self.failure=TimeoutError();self.read();self.settle()
        for _ in range(20):self.clock+=10000;self.read()
        self.assertEqual(self.probe.attempts,1);self.assertTrue(self.probe.circuit_open)
        self.assertEqual(self.read()[1]['state'],'unavailable')
    def test_known_completed_error_has_cooldown_and_bounded_retries(self):
        self.failure=ProbeError('OFFICIAL_TEST_FAILURE');self.read();self.settle()
        self.read();self.assertEqual(self.probe.attempts,1)
        self.clock+=121;self.read();self.settle()
        self.clock+=10000;self.read();self.assertEqual(self.probe.attempts,2)
    def test_refresh_frequency_limited(self):
        self.seeded();self.clock+=9;self.read();self.assertEqual(self.probe.attempts,1)
        self.clock+=2;self.read();self.settle();self.assertEqual(self.probe.attempts,2)
    def test_expired_measurements_not_returned(self):
        self.seeded();self.probe.circuit_open=True;self.clock+=601
        self.assertEqual(self.read()[0],[])
    def test_original_tested_at_age_also_checked(self):
        self.seeded();self.now+=601
        self.assertEqual(self.read()[0],[]);self.settle()
    def test_reused_id_with_changed_link_not_old_latency(self):
        self.seeded();self.nodes[0]['link']='ss://changed-secret'
        self.assertEqual([r['id'] for r in self.read()[0]],['b'])
    def test_deleted_node_removed(self):
        self.seeded();self.nodes=self.nodes[1:]
        self.assertEqual([r['id'] for r in self.read()[0]],['b'])
    def test_new_node_unknown_not_failed(self):
        self.seeded();self.nodes.append({'id':'c','link':'ss://new','subscriptionID':None})
        self.assertNotIn('c',[r['id'] for r in self.read()[0]])
    def test_requested_ids_filter_and_unknown_omitted(self):
        self.seeded();self.assertEqual([r['id'] for r in self.read(['b','missing'])[0]],['b'])
    def test_inventory_failure_closed_no_cached_disclosure(self):
        self.seeded();self.probe.inventory=Mock(side_effect=TimeoutError())
        rows,status=self.read();self.assertEqual(rows,[]);self.assertEqual(status['state'],'unavailable')
    def test_different_authenticated_principal_no_old_results(self):
        self.seeded();rows,_=self.probe.read('Bearer other','other')
        self.assertEqual(rows,[])
    def test_invalid_and_stale_official_results_rejected(self):
        for key,value in [('latencyMs',False),('alive',None),('testedAt','invalid'),('testedAt','2000-01-01T00:00:00Z')]:
            rows=self.rows(['a']);rows[0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ProbeError):self.probe.validate_rows(rows,{'a':'hash'})
        with self.assertRaises(ProbeError):self.probe.validate_rows([],{'a':'hash'})
    def test_real_failed_measurement_not_changed_to_success(self):
        row=self.rows(['a'])[0];row.update(latencyMs=None,alive=False,message='timeout')
        self.assertEqual(self.probe.validate_rows([row],{'a':'hash'})[0][1],row)
    def test_result_message_does_not_expose_node_link(self):
        rows=self.rows(['a']);rows[0]['message']='cannot connect ss://synthetic-secret'
        safe=self.probe.validate_rows(rows,{'a':'hash'})[0][1]
        self.assertNotIn('synthetic-secret',json.dumps(safe))
    def test_subscription_pagination_and_identity(self):
        calls=[]
        def transport(raw,auth,timeout):
            q=json.loads(raw);calls.append(q)
            if q['query'].startswith('{subscriptions{id}'):data={'subscriptions':[{'id':'sub'}],'groups':[]}
            else:
                sid=q['variables']['sid'];after=q['variables']['after']
                rows=[] if sid is None else [{'id':'b' if after else 'a','link':'ss://synthetic','subscriptionID':sid}]
                data={'nodes':{'totalCount':0 if sid is None else 2,'edges':rows,'pageInfo':{'hasNextPage':sid is not None and after is None,'endCursor':rows[-1]['id'] if rows else None}}}
            return json.dumps({'data':data}).encode()
        self.probe.transport=transport;self.assertEqual(set(self.probe.inventory('token')),{'a','b'})
        self.assertEqual(len(calls),4)
    def test_inventory_missing_page_rejected(self):
        original=self.transport
        def missing(raw,auth,timeout):
            r=json.loads(original(raw,auth,timeout))
            if 'nodes' in r['data']:r['data']['nodes']['totalCount']=3
            return json.dumps(r).encode()
        self.probe.transport=missing
        with self.assertRaises(ProbeError):self.probe.inventory('synthetic')


class ASTTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.cache=Mock();self.cache.read.return_value=([{'id':'a','latencyMs':17,'alive':True,'testedAt':'2026-01-01T00:00:00Z','message':None}],{'state':'ready'})
        self.runtime=Mock()
        def forward(raw,auth):
            self.calls.append((raw,auth));q=json.loads(raw)['query']
            if q=='{user{username}}':return b'{"data":{"user":{"username":"synthetic"}}}'
            if 'numberUsers' in q:return b'{"data":{"n":1}}' if 'n:' in q or 'n: ' in q else b'{"data":{"numberUsers":1}}'
            return b'{"data":{"testNodeLatencies":[]}}'
        self.forward=Mock(side_effect=forward)
        self.adapter=Adapter(build_schema(SCHEMA),self.runtime,self.forward,self.cache)
    def runq(self,q,variables=None,name=None):
        return json.loads(self.adapter.handle(json.dumps({'query':q,'variables':variables,'operationName':name}).encode(),'Bearer synthetic'))
    def test_alias_variable_fragment_and_mixed_query(self):
        result=self.runq('query X($ids:[ID!],$yes:Boolean!){n:numberUsers a:nodeLatencies(ids:$ids) @include(if:$yes){...L} b:nodeLatencies(ids:[]){id}} fragment L on NodeLatency{id ms:latencyMs alive testedAt}',{'ids':['a'],'yes':True})
        self.assertEqual(result['data']['a'][0]['ms'],17);self.assertEqual(result['data']['n'],1)
        self.assertEqual(result['data']['b'],[]);self.cache.read.assert_called_once()
        self.assertFalse(any('nodeLatencies' in json.loads(raw)['query'] for raw,_ in self.calls))
    def test_skipped_field_never_starts_probe(self):
        self.runq('{nodeLatencies @skip(if:true){id}}');self.cache.read.assert_not_called()
    def test_unauthenticated_no_cached_disclosure_or_probe(self):
        self.forward.side_effect=None;self.forward.return_value=b'{"errors":[{"message":"access denied"}]}'
        result=self.runq('{nodeLatencies{id}}');self.assertIn('errors',result);self.cache.read.assert_not_called()
    def test_invalid_schema_never_probes(self):
        self.assertIn('errors',self.runq('{nodeLatencies{nonexistent}}'));self.cache.read.assert_not_called()
    def test_selected_operation_does_not_intercept_other_documents(self):
        raw=json.dumps({'query':'query A{numberUsers} query B{nodeLatencies{id}}','operationName':'A'}).encode()
        self.adapter.handle(raw,'Bearer synthetic');self.assertEqual(self.calls,[(raw,'Bearer synthetic')])
    def test_complete_manual_alias_is_observed_once_without_changing_response(self):
        self.cache.inventory.return_value = {'a':'identity'}
        raw = b'{"query":"mutation($ids:[ID!]){manual:testNodeLatencies(ids:$ids){id latencyMs alive testedAt message}}","variables":{"ids":["a"]}}'
        body = b'{"data":{"manual":[]}}'
        def forward(value, auth):
            self.calls.append((value,auth))
            if json.loads(value)['query'] == '{user{username}}':
                return b'{"data":{"user":{"username":"synthetic"}}}'
            return body
        self.adapter.forward = forward
        self.assertEqual(self.adapter.handle(raw,'Bearer synthetic'), body)
        self.assertEqual(sum(r == raw for r,a in self.calls), 1)
        self.cache.remember_manual.assert_called_once_with('Bearer synthetic','synthetic',{'a':'identity'},[])

    def test_manual_official_probe_bytes_and_auth_unchanged(self):
        raw=b'{"query":"mutation($ids:[ID!]){testNodeLatencies(ids:$ids){id}}","variables":{"ids":["a"]}}'
        result=self.adapter.handle(raw,'Bearer synthetic');self.assertEqual(self.calls,[(raw,'Bearer synthetic')]);self.assertIn(b'testNodeLatencies',result)
    def test_unknown_measurements_no_graphql_error(self):
        self.cache.read.return_value=([],{'state':'unavailable','reason':'TimeoutError'})
        result=self.runq('{nodeLatencies{id alive}}');self.assertNotIn('errors',result)
        self.assertEqual(result['data']['nodeLatencies'],[]);self.assertEqual(result['extensions']['bridgeNodeLatencies']['state'],'unavailable')

class HTTPTimeoutTests(unittest.TestCase):
    def test_real_http_probe_timeout_does_not_block_reads_or_add_jobs(self):
        import urllib.request
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        release=threading.Event();jobs=[];timings=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if 'testNodeLatencies' in value['query']:
                    jobs.append(1);release.wait(2);return
                if value['query'].startswith('{subscriptions{id}'):
                    data={'subscriptions':[],'groups':[]}
                else:
                    data={'nodes':{'totalCount':1,'edges':[{'id':'a','link':'ss://synthetic','subscriptionID':None}],
                                   'pageInfo':{'endCursor':'a','hasNextPage':False}}}
                body=json.dumps({'data':data}).encode();self.send_response(200)
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def transport(raw,auth,timeout):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port),data=raw,headers={'Authorization':auth})
            started=time.monotonic()
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=timeout) as response:return response.read()
            finally:
                timings.append({'operation':'probe' if b'testNodeLatencies' in raw else 'inventory', 'seconds':time.monotonic()-started})
        probe=NodeLatencies(transport);probe.PROBE_TIMEOUT=.05
        try:
            import resource
            from pathlib import Path
            def scheduling():
                p=Path('/proc/self/schedstat')
                return p.read_text().strip() if p.exists() else None
            usage=resource.getrusage(resource.RUSAGE_SELF);sched=scheduling()
            cpu=time.process_time();start=time.monotonic()
            rows,_=probe.read('Bearer synthetic','synthetic')
            elapsed=time.monotonic()-start
            after=resource.getrusage(resource.RUSAGE_SELF)
            print('HTTP_TIMEOUT_TIMING '+json.dumps({'readSeconds':elapsed,'cpuSeconds':time.process_time()-cpu,
                'transport':list(timings),'schedstatBefore':sched,'schedstatAfter':scheduling(),
                'voluntarySwitches':after.ru_nvcsw-usage.ru_nvcsw,'involuntarySwitches':after.ru_nivcsw-usage.ru_nivcsw}),flush=True)
            self.assertLess(elapsed,.2);self.assertEqual(rows,[])
            deadline=time.monotonic()+2
            while probe.busy and time.monotonic()<deadline:time.sleep(.01)
            self.assertFalse(probe.busy);self.assertTrue(probe.circuit_open)
            for _ in range(5):
                rows,status=probe.read('Bearer synthetic','synthetic');self.assertEqual(rows,[])
                self.assertEqual(status['state'],'unavailable')
            self.assertEqual(len(jobs),1)
        finally:
            release.set();server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
