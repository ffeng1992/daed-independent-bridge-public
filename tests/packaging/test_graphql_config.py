"""Regression for the explicit false loss observed with the locked real daemon."""
import json
from pathlib import Path
import unittest
from graphql import build_schema, graphql_sync, GraphQLError
from bridge_m4.graphql_config import preserve_create_false

SCHEMA = '''input globalInput {tproxyPortProtect:Boolean logLevel:String soMarkFromDae:Int}
type Global {tproxyPortProtect:Boolean! logLevel:String!}
type Config {id:ID! name:String global:Global!}
type Query {numberUsers:Int!}
type Mutation {createConfig(name:String,global:globalInput):Config!
updateConfig(id:ID!,global:globalInput!):Config!}'''


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.schema = build_schema(SCHEMA)
        self.saved = {}; self.calls = []; self.update_failure = False; self.ignore_update = False

    def forward(self, raw, auth):
        self.calls.append((raw, auth)); body = json.loads(raw)
        def resolve(source, info, **args):
            if info.field_name == 'createConfig':
                if auth != 'Bearer synthetic':
                    raise GraphQLError('access denied')
                ident = str(len(self.saved)+1)
                value = {'id': ident, 'name': args.get('name'), 'global': {
                    'tproxyPortProtect': True, 'logLevel': 'info'}}
                # Pinned upstream Create uses IgnoreZero:true, observed in VM.
                value['global'].update({k:v for k,v in (args.get('global') or {}).items() if v})
                self.saved[ident] = value
                return value
            if info.field_name == 'updateConfig':
                if self.update_failure:
                    raise GraphQLError('synthetic write failed')
                if not self.ignore_update:
                    self.saved[args['id']]['global'].update(args['global'])
                return self.saved[args['id']]
            if info.field_name == 'numberUsers':
                return 1
            return source.get(info.field_name)
        result = graphql_sync(self.schema, body['query'], variable_values=body.get('variables'),
                              operation_name=body.get('operationName'), field_resolver=resolve)
        return json.dumps(result.formatted).encode()

    def call(self, query, variables=None, name=None, auth='Bearer synthetic'):
        raw = json.dumps({'query':query, 'variables':variables, 'operationName':name}).encode()
        return json.loads(preserve_create_false(raw, auth, self.forward))

    def test_real_failure_fixture_and_old_forwarding_reproduce(self):
        fixture = json.loads((Path(__file__).parents[1]/'fixtures/ui_matrix/create-config-false.json').read_text())
        self.assertIs(fixture['write']['tproxyPortProtect'], False)
        self.assertIs(fixture['queryReadback']['tproxyPortProtect'], True)
        result = json.loads(self.forward(b'{"query":"mutation{createConfig(global:{tproxyPortProtect:false}){global{tproxyPortProtect}}}"}', 'Bearer synthetic'))
        self.assertEqual(result['data']['createConfig']['global'], fixture['mutationReadback'])

    def test_false_preserved_and_internal_fields_not_returned(self):
        result = self.call('mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id global{tproxyPortProtect}}}')
        self.assertEqual(result, {'data':{'createConfig':{'id':'1','global':{'tproxyPortProtect':False}}}})
        self.assertEqual(len(self.calls), 2)

    def test_adapter_routes_real_create_mutation_through_compatibility(self):
        from bridge_m4.graphql_runtime import Adapter
        from unittest.mock import Mock
        runtime = Mock()
        raw = b'{"query":"mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id global{tproxyPortProtect}}}"}'
        result = json.loads(Adapter(self.schema, runtime, self.forward).handle(raw, 'Bearer synthetic'))
        self.assertIs(result['data']['createConfig']['global']['tproxyPortProtect'], False)
        self.assertEqual(runtime.mock_calls, [])

    def test_invalid_create_still_uses_official_validation(self):
        result = self.call('mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0,logLevel:12}){id}}')
        self.assertIn('errors', result)
        self.assertEqual(self.saved, {})
        self.assertEqual(len(self.calls), 1)

    def test_id_only_official_form_still_corrects_persistence(self):
        result = self.call('mutation($g:globalInput){createConfig(global:$g){id}}', {'g':{'tproxyPortProtect':False,'soMarkFromDae':0}})
        self.assertEqual(result, {'data':{'createConfig':{'id':'1'}}})
        self.assertIs(self.saved['1']['global']['tproxyPortProtect'], False)

    def test_alias_fragments_and_selection_variables(self):
        result = self.call('mutation X($g:globalInput,$show:Boolean!){...M} fragment M on Mutation{made:createConfig(global:$g){...C}} fragment C on Config{id global @include(if:$show){p:tproxyPortProtect}}', {'g':{'tproxyPortProtect':False,'soMarkFromDae':0},'show':True}, 'X')
        self.assertEqual(result['data']['made'], {'id':'1','global':{'p':False}})

    def test_variable_default(self):
        result = self.call('mutation($g:globalInput={tproxyPortProtect:false,soMarkFromDae:0}){createConfig(global:$g){id}}')
        self.assertNotIn('errors', result)
        self.assertIs(self.saved['1']['global']['tproxyPortProtect'], False)

    def test_skip_does_not_create_or_update(self):
        self.assertEqual(self.call('mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}) @skip(if:true){id}}'), {'data':{}})
        self.assertEqual(self.saved, {}); self.assertEqual(len(self.calls), 1)

    def test_selected_query_does_not_touch_other_operation(self):
        self.assertEqual(self.call('query Q{numberUsers} mutation M{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id}}', name='Q'), {'data':{'numberUsers':1}})
        self.assertEqual(self.saved, {})

    def test_auth_failure_does_not_update(self):
        result = self.call('mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id}}', auth='')
        self.assertEqual(result['errors'][0]['message'], 'access denied')
        self.assertEqual(self.saved, {}); self.assertEqual(len(self.calls), 1)

    def test_ordinary_request_byte_identity(self):
        for value in ({'tproxyPortProtect':True}, {}, None):
            raw = json.dumps({'query':'mutation($g:globalInput){createConfig(global:$g){id}}','variables':{'g':value}}, indent=2).encode()
            self.calls.clear()
            preserve_create_false(raw, 'Bearer synthetic', self.forward)
            self.assertEqual(self.calls, [(raw,'Bearer synthetic')])

    def test_update_failure_not_success_and_never_deletes(self):
        for mode in ('update_failure','ignore_update'):
            with self.subTest(mode=mode):
                self.setUp(); setattr(self, mode, True)
                result = self.call('mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id}}')
                self.assertEqual(result['errors'][0]['message'], 'CONFIG_CREATE_VALUE_NOT_PRESERVED')
                self.assertIsNone(result['data']['createConfig'])
                self.assertEqual(len(self.saved), 1)

    def test_missing_created_identity_fails_closed(self):
        raw = b'{"query":"mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id}}"}'
        result = json.loads(preserve_create_false(raw, 'Bearer synthetic',
                            lambda *_: b'{"data":{"createConfig":{"id":"1"}}}'))
        self.assertEqual(result['errors'][0]['message'], 'CONFIG_CREATE_IDENTITY_MISSING')
        self.assertIsNone(result['data']['createConfig'])

    def test_partial_false_create_never_changes_automatic_mark_to_zero(self):
        result = self.call('mutation{createConfig(global:{tproxyPortProtect:false}){id}}')
        self.assertEqual(result['errors'][0]['message'], 'CONFIG_CREATE_EXPLICIT_MARK_REQUIRED')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.saved, {})

    def test_skipped_partial_create_is_transparent(self):
        result = self.call('mutation($skip:Boolean!){...M @skip(if:$skip)} fragment M on Mutation{createConfig(global:{tproxyPortProtect:false}){id}}', {'skip':True})
        self.assertEqual(result, {'data':{}})
        self.assertEqual(self.saved, {})
        self.assertEqual(len(self.calls), 1)

    def test_internal_alias_collision_and_duplicate_fragment(self):
        result = self.call('mutation{...M ...M} fragment M on Mutation{createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){_bridge_created_id:id}}')
        self.assertEqual(result, {'data':{'createConfig':{'_bridge_created_id':'1'}}})
        self.assertEqual(len(self.calls), 2)

    def test_multiple_config_creations(self):
        result = self.call('mutation{a:createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id} b:createConfig(global:{tproxyPortProtect:false,soMarkFromDae:0}){id}}')
        self.assertEqual(result, {'data':{'a':{'id':'1'},'b':{'id':'2'}}})
        self.assertTrue(all(v['global']['tproxyPortProtect'] is False for v in self.saved.values()))


if __name__ == '__main__':
    unittest.main()
