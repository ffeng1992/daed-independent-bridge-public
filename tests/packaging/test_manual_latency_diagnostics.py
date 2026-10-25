"""Synthetic official HTTP only. Never contacts production or starts real probes."""
import contextlib
import datetime
import hashlib
import io
import json
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from graphql import build_schema
from bridge_m4.graphql_runtime import Adapter, Handler, upstream
from bridge_m4.node_latencies import NodeLatencies

SCHEMA = '''type User {username:String!}
type L {id:ID! latencyMs:Int alive:Boolean! testedAt:String! message:String}
type Query {user:User! numberUsers:Int!}
type Mutation {testNodeLatencies(ids:[ID!]):[L!]!}'''
SECRET = 'synthetic-do-not-log-node-or-token'


def accept_manual_once(adapter, raw, authorization, cache, principal):
    """Acceptance helper: failure stops; inspect in-process cache, never query nodeLatencies.

    The HTTP GraphQL read is intentionally NOT used: it may start a probe.
    Call only in the isolated harness that owns the cache. No production API is added.
    """
    body = adapter.handle(raw, authorization)
    result = json.loads(body)
    if result.get('errors'):
        raise RuntimeError('MANUAL_MEASUREMENT_FAILED')
    rows = result['data']['manual']
    ids = json.loads(raw)['variables']['ids']
    checked = cache.validate_rows(rows, {i:'synthetic-identity' for i in ids})
    if len(checked) != len(ids):
        raise RuntimeError('MANUAL_MEASUREMENT_INCOMPLETE')
    owner = hashlib.sha256(principal.encode()).hexdigest()
    with cache.lock:
        if owner != cache.owner:
            raise RuntimeError('CACHE_OWNER_MISMATCH')
        saved = [cache.records[i] for i in ids]
        if any(cache.clock()-r[2] >= cache.TTL or not 0 <= cache.wall()-r[3] < cache.TTL for r in saved):
            raise RuntimeError('CACHE_RESULT_EXPIRED')
        if [r[1] for r in saved] != rows:
            raise RuntimeError('CACHE_RESULT_MISMATCH')
    return body


class ManualDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.mode='ok';self.probes=[];self.raws=[];self.completed=threading.Event()
        owner=self
        class Official(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']));q=json.loads(raw)['query']
                if q=='{user{username}}':body=b'{"data":{"user":{"username":"synthetic"}}}'
                else:
                    owner.probes.append(q);owner.raws.append(raw)
                    if owner.mode=='timeout':time.sleep(.12);owner.completed.set()
                    if owner.mode=='invalid':body=b'not-json-'+SECRET.encode()
                    elif owner.mode=='wrong-shape':body=b'{"data":{"manual":null}}'
                    elif owner.mode=='error':body=json.dumps({'errors':[{'message':SECRET}]}).encode()
                    else:body=json.dumps({'data':{'manual':owner.rows()}}).encode()
                try:
                    self.send_response(200);self.end_headers();self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Official)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cache=NodeLatencies(lambda *a: self.fail('cache inspection must not issue transport requests'))
        self.cache.inventory=lambda _: {SECRET:'synthetic-identity'}
        def forward(raw,auth):
            # Only synthetic server and short test timeout; production stays 30 seconds.
            with patch('bridge_m4.graphql_runtime.ENDPOINT','http://127.0.0.1:%d/graphql'%self.server.server_port):
                return upstream(raw,auth,timeout=.04 if self.mode=='timeout' else 2)
        self.adapter=Adapter(build_schema(SCHEMA),None,forward,self.cache)
        self.raw=json.dumps({'query':'mutation M($ids:[ID!],$go:Boolean!){manual:testNodeLatencies(ids:$ids) @include(if:$go){id latencyMs alive testedAt message}}','operationName':'M','variables':{'ids':[SECRET],'go':True}}).encode()
        self.logs=io.StringIO();self.capture=contextlib.redirect_stdout(self.logs);self.capture.__enter__()
        self.no_read=patch.object(self.cache,'read',side_effect=AssertionError('nodeLatencies read forbidden'));self.no_read.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.no_read.stop();self.capture.__exit__(None,None,None)
    def rows(self):
        return [{'id':SECRET,'latencyMs':17,'alive':True,'testedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'message':None}]
    def diagnostic(self):
        events=[json.loads(x) for x in self.logs.getvalue().splitlines()]
        self.assertEqual(len(events),1);d=events[0]
        self.assertNotIn(SECRET,self.logs.getvalue());self.assertEqual(d['nodeCount'],1)
        self.assertEqual(d['operation'],'testNodeLatencies');self.assertEqual(len(d['requestId']),32)
        self.assertGreaterEqual(d['elapsedMs'],0);self.assertLessEqual(d['startedAt'],d['endedAt'])
        self.assertEqual(len(self.probes),1);self.assertEqual(self.raws,[self.raw]);return d
    def test_normal_complete_and_cache_only_acceptance(self):
        body=accept_manual_once(self.adapter,self.raw,SECRET,self.cache,'synthetic')
        self.assertEqual(json.loads(body)['data']['manual'][0]['latencyMs'],17)
        d=self.diagnostic();self.assertEqual(d['category'],'UPSTREAM_RESULT');self.assertTrue(d['cacheRecorded'])
    def test_official_graphql_error_stops_acceptance_no_cache(self):
        self.mode='error'
        with self.assertRaisesRegex(RuntimeError,'MANUAL_MEASUREMENT_FAILED'):
            accept_manual_once(self.adapter,self.raw,SECRET,self.cache,'synthetic')
        d=self.diagnostic();self.assertEqual(d['category'],'UPSTREAM_GRAPHQL_ERROR');self.assertEqual(self.cache.records,{})
    def test_timeout_unknown_no_retry_no_cache(self):
        self.mode='timeout'
        with self.assertRaises(TimeoutError):accept_manual_once(self.adapter,self.raw,SECRET,self.cache,'synthetic')
        d=self.diagnostic();self.assertEqual(d['category'],'UPSTREAM_TIMEOUT');self.assertEqual(d['officialCompletion'],'UNKNOWN')
        self.assertEqual(self.cache.records,{});self.assertTrue(self.completed.wait(1));self.assertEqual(len(self.probes),1)
    def test_invalid_response_passes_original_bytes_but_no_cache(self):
        self.mode='invalid';body=self.adapter.handle(self.raw,SECRET)
        self.assertTrue(body.startswith(b'not-json'));d=self.diagnostic();self.assertEqual(d['category'],'INVALID_UPSTREAM_RESPONSE');self.assertFalse(d['cacheRecorded']);self.assertEqual(self.cache.records,{})
    def test_wrong_response_shape_no_cache(self):
        self.mode='wrong-shape';self.adapter.handle(self.raw,SECRET)
        d=self.diagnostic();self.assertEqual(d['category'],'INVALID_UPSTREAM_RESPONSE');self.assertEqual(self.cache.records,{})
    def test_bridge_cache_processing_error_is_distinct(self):
        with patch.object(self.cache,'remember_manual',side_effect=RuntimeError(SECRET)):
            body=self.adapter.handle(self.raw,SECRET)
        self.assertIn('data',json.loads(body));d=self.diagnostic();self.assertEqual(d['category'],'BRIDGE_PROCESSING_ERROR');self.assertEqual(self.cache.records,{})
    def test_partial_official_rows_rejected_not_cached(self):
        with patch.object(self,'rows',return_value=[{'id':SECRET}]):
            self.adapter.handle(self.raw,SECRET)
        d=self.diagnostic();self.assertEqual(d['category'],'INVALID_UPSTREAM_RESPONSE');self.assertEqual(self.cache.records,{})
    def test_unsupported_internal_exception_never_logs_message(self):
        self.adapter.forward=lambda *_: (_ for _ in ()).throw(RuntimeError(SECRET))
        with self.assertRaises(RuntimeError):self.adapter.handle(self.raw,SECRET)
        d=json.loads(self.logs.getvalue());self.assertEqual(d['category'],'BRIDGE_PROCESSING_ERROR')
        self.assertEqual(d['officialCompletion'],'UNKNOWN');self.assertNotIn(SECRET,self.logs.getvalue())
    def test_other_selected_operation_is_not_observed(self):
        from bridge_m4.manual_latency_diagnostics import manual_fields
        raw=json.dumps({'query':'query Q{numberUsers} mutation M{testNodeLatencies(ids:[]){id}}','operationName':'Q'}).encode()
        self.assertIsNone(manual_fields(self.adapter.schema,raw))
    def test_skipped_manual_no_diagnostic_no_measurement(self):
        v=json.loads(self.raw);v['variables']['go']=False
        # Preserve forwarding: the synthetic server does not implement skip, so
        # inspect the diagnostic selector directly rather than fake upstream semantics.
        from bridge_m4.manual_latency_diagnostics import manual_fields
        self.assertIsNone(manual_fields(self.adapter.schema,json.dumps(v).encode()));self.assertEqual(self.logs.getvalue(),'')
    def test_log_sink_failure_preserves_response_and_single_measurement(self):
        with patch('bridge_m4.manual_latency_diagnostics.emit',side_effect=RuntimeError(SECRET)):
            body=self.adapter.handle(self.raw,SECRET)
        self.assertIn('data',json.loads(body));self.assertEqual(len(self.probes),1)
    def test_production_default_timeout_unchanged(self):
        import inspect
        self.assertEqual(inspect.signature(upstream).parameters['timeout'].default,30)

class HTTPHandlerDiagnosticsTests(unittest.TestCase):
    # Reuse only the local synthetic upstream fixture, not inherited test methods.
    setUp = ManualDiagnosticsTests.setUp
    rows = ManualDiagnosticsTests.rows
    diagnostic = ManualDiagnosticsTests.diagnostic

    def tearDown(self):
        if hasattr(self, 'bridge'):
            self.bridge.shutdown(); self.bridge.server_close(); self.bridge_thread.join()
        ManualDiagnosticsTests.tearDown(self)

    def call_http(self):
        self.bridge = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.bridge.adapter = self.adapter
        self.bridge_thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.bridge_thread.start()
        req = urllib.request.Request('http://127.0.0.1:%d/graphql' % self.bridge.server_port,
                                     data=self.raw, headers={'Content-Type':'application/json', 'Authorization':SECRET})
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.headers, response.read()

    def assert_http(self, category, expected_error=None):
        status, headers, body = self.call_http()
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        if expected_error:
            self.assertEqual(json.loads(body), {'errors':[{'message':expected_error}]})
        d = self.diagnostic()
        self.assertEqual(d['category'], category)
        start = datetime.datetime.fromisoformat(d['startedAt'])
        end = datetime.datetime.fromisoformat(d['endedAt'])
        self.assertGreaterEqual(end, start)
        self.assertEqual(len(bytes.fromhex(d['requestId'])), 16)
        if category != 'UPSTREAM_RESULT':
            self.assertFalse(d['cacheRecorded']); self.assertEqual(self.cache.records, {})
        return body, d

    def test_http_success(self):
        body, d = self.assert_http('UPSTREAM_RESULT')
        self.assertEqual(json.loads(body)['data']['manual'][0]['latencyMs'], 17)
        self.assertTrue(d['cacheRecorded'])
        self.assertEqual(d['officialCompletion'], 'RESPONSE_RECEIVED')

    def test_http_graphql_error(self):
        self.mode = 'error'
        body, d = self.assert_http('UPSTREAM_GRAPHQL_ERROR')
        # Original upstream error body is forwarded, never copied into logs.
        self.assertEqual(json.loads(body)['errors'][0]['message'], SECRET)
        self.assertEqual(d['officialCompletion'], 'RESPONSE_RECEIVED')

    def test_http_timeout(self):
        self.mode = 'timeout'
        _, d = self.assert_http('UPSTREAM_TIMEOUT', 'RUNTIME_ADAPTER_REQUEST_FAILED')
        self.assertEqual(d['officialCompletion'], 'UNKNOWN')
        self.assertTrue(self.completed.wait(1))
        self.assertEqual(len(self.probes), 1)

    def test_http_invalid_response(self):
        self.mode = 'invalid'
        body, d = self.assert_http('INVALID_UPSTREAM_RESPONSE')
        self.assertEqual(body, b'not-json-' + SECRET.encode())
        self.assertEqual(d['officialCompletion'], 'UNKNOWN')

    def test_http_bridge_internal_exception(self):
        # Raise after the one actual upstream response, inside Bridge cache handling.
        with patch.object(self.cache, 'remember_manual', side_effect=RuntimeError(SECRET)):
            body, d = self.assert_http('BRIDGE_PROCESSING_ERROR')
        self.assertIn('data', json.loads(body))  # Existing optional-cache behavior preserved.
        self.assertEqual(d['officialCompletion'], 'RESPONSE_RECEIVED')

    def test_http_bridge_forward_exception(self):
        original = self.adapter.forward
        def forward(raw, auth):
            if raw == self.raw:
                raise RuntimeError(SECRET)
            return original(raw, auth)
        self.adapter.forward = forward
        status, _, body = self.call_http()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'errors':[{'message':'RUNTIME_ADAPTER_REQUEST_FAILED'}]})
        events = [json.loads(x) for x in self.logs.getvalue().splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['category'], 'BRIDGE_PROCESSING_ERROR')
        self.assertEqual(events[0]['officialCompletion'], 'UNKNOWN')
        self.assertNotIn(SECRET, self.logs.getvalue())
        self.assertEqual(self.probes, []); self.assertEqual(self.cache.records, {})


if __name__=='__main__':unittest.main()
