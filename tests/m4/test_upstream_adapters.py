"""Pinned v0.3.1 equivalence and synthetic contract evolution only."""
import copy
import unittest

from bridge_m1.common import digest
from bridge_m2.bundle import FILES
from bridge_m4.extensions import CompatibilityError, convert_record, merge, split, validate_record
from bridge_m4.runtime_bundle import artifacts, fingerprints, make, receipt, verify_bundle
from bridge_m4.upstream_contracts import (
    CONFIG, LEGACY_RECORD, LOCK, BRIDGE_FORMAT, DAE_TARGET,
    DAED_ARTIFACT, DAE_ARTIFACT, WEB_ARTIFACT,
    contract_diagnostics, extension_fields,
)
from tests.m4.test_runtime_bundle import fixture


class PinnedAdapterTests(unittest.TestCase):
    def test_artifacts_and_fingerprints_equal_released_v031(self):
        source, extensions, proof = fixture()
        files = artifacts(source, proof, extensions)
        pins = fingerprints(source, extensions)
        self.assertEqual(digest(files['candidate.dae']), '2e9e1fdf4418a2a581505fab651b38a72893f3f8eeb1b2108312e4c3553206be')
        self.assertEqual(digest(files['manifest.json']), '9a2954fe0d86fb5496e5cde8b43dbd1e5c668f2e45573cf1a7c1afb3c9c11d0b')
        self.assertEqual(pins, {
            'extensionsSha256': '992f88fd65beb2a4b8037d29643c2e5cb0862e1f36a774ba8c785001061eaf4b',
            'graphqlSha256': '55d746924599323d6d7f4ce32428f062a98688fd53f6f77c7d36e5e450ea9640',
            'sourceSha256': '2f667d13720383365ff0b12f59ebdfc50a47f1cb7daceaf8a50762745ef935db',
        })
        r = receipt(source, extensions, 100)
        ident, bundle = make({key: files[key] for key in FILES}, r, None, 101)
        self.assertEqual(ident, 'ae4802e205000b143905680958bc14152edb6a922c5f3b627365e2badb8bc2f5')
        self.assertEqual(verify_bundle(bundle, ident, r, 102)['sourceSha256'], pins['sourceSha256'])

    def test_four_distinct_version_domains(self):
        self.assertEqual(CONFIG['source']['daed'], LOCK['components']['daed']['version'])
        self.assertEqual(CONFIG['source']['coreCommit'], LOCK['components']['daed']['embedded_dae_commit'])
        self.assertEqual(CONFIG['target']['commit'], LOCK['components']['dae']['commit'])
        self.assertEqual(DAE_TARGET, 'dae-v2.1.1-linux-x86_64')
        self.assertEqual(BRIDGE_FORMAT, '0.2-m4-empty-groups')
        self.assertEqual(DAED_ARTIFACT['sha256'], LOCK['components']['daed']['sha256'])
        self.assertEqual(DAE_ARTIFACT['sha256'], LOCK['components']['dae']['sha256'])
        self.assertEqual(WEB_ARTIFACT['version'], LOCK['webFrontend']['version'])

    def test_legacy_record_uses_sealed_contract_after_synthetic_evolution(self):
        text = 'global {\n disable_thp: false\n}\n'
        view, old = split(text, 'global')
        evolved = copy.deepcopy(CONFIG)
        evolved['target']['models']['Global']['future_feature'] = {
            'type': 'bool', 'default': 'true', 'required': False, 'repeatable': False}
        self.assertEqual(validate_record(old, 'global', contract=evolved), view)
        with self.assertRaisesRegex(CompatibilityError, 'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            merge(view, old, contract=evolved)
        with self.assertRaisesRegex(CompatibilityError, 'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            convert_record(old, 'global', {}, contract=evolved)
        converted = convert_record(old, 'global', {'future_feature': 'new-field-absent'}, contract=evolved)
        self.assertEqual(converted['schemaVersion'], 2)
        self.assertEqual(converted['fields']['future_feature'], {'present': False})
        self.assertEqual(converted['fields']['disable_thp'], {'present': True, 'value': False})
        self.assertEqual(validate_record(converted, 'global', contract=evolved), view)
        self.assertEqual(old['schemaVersion'], 1)  # no in-place rewrite

    def test_presence_and_type_remain_distinct(self):
        for raw, expected in (('', {'present': False}), ('false', {'present': True, 'value': False}),
                              ('true', {'present': True, 'value': True})):
            _, record = split('global {\n' + (' disable_thp: '+raw+'\n' if raw else '') + '}\n', 'global')
            self.assertEqual(record['fields']['disable_thp'], expected)
        for raw in ('null', '0', '""'):
            with self.subTest(raw=raw), self.assertRaisesRegex(CompatibilityError, 'INVALID_EXTENSION_TYPE'):
                split('global {\n disable_thp: '+raw+'\n}', 'global')
        _, record = split('dns {\n optimistic_stale_reply_ttl: 0\n}\n', 'dns')
        self.assertEqual(record['fields']['optimistic_stale_reply_ttl'], {'present': True, 'value': 0})

    def test_synthetic_drift_diagnostics_are_classified_not_accepted(self):
        evolved = copy.deepcopy(LEGACY_RECORD)
        source = evolved['source']['models']['Global']
        target = evolved['target']['models']['Global']
        source['new_source'] = {'type':'string','default':None}
        source['disable_thp'] = copy.deepcopy(target['disable_thp'])  # bridge -> daed
        target['new_target'] = {'type':'bool','default':'false'}
        target.pop('bpf_conn_state_map_size')
        target['auto_sniff_punt']['type'] = 'string'
        target['auto_sniff_punt']['default'] = 'unset'
        found = {(x['side'],x['path'],x['code']) for x in contract_diagnostics(LEGACY_RECORD, evolved)}
        for expected in (
            ('source','Global.new_source','FIELD_ADDED'),
            ('target','Global.new_target','FIELD_ADDED'),
            ('target','Global.bpf_conn_state_map_size','FIELD_REMOVED'),
            ('target','Global.auto_sniff_punt','FIELD_TYPE_CHANGED'),
            ('target','Global.auto_sniff_punt','FIELD_DEFAULT_CHANGED'),
            ('ownership','Global.disable_thp','FIELD_OWNERSHIP_CHANGED'),
        ): self.assertIn(expected, found)
        self.assertNotIn('disable_thp', extension_fields('global', evolved))

    def test_type_or_ownership_change_cannot_be_silent_conversion(self):
        _, record = split('global {\n disable_thp: false\n}\n','global')
        evolved = copy.deepcopy(CONFIG)
        evolved['target']['models']['Global']['disable_thp']['type'] = 'string'
        with self.assertRaisesRegex(CompatibilityError,'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            convert_record(record,'global',{},contract=evolved)
        evolved = copy.deepcopy(CONFIG)
        evolved['source']['models']['Global']['disable_thp'] = evolved['target']['models']['Global']['disable_thp']
        with self.assertRaisesRegex(CompatibilityError,'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            convert_record(record,'global',{},contract=evolved)
        evolved = copy.deepcopy(CONFIG)
        evolved['target']['models']['Global']['auto_sniff_punt']['default'] = 'false'
        with self.assertRaisesRegex(CompatibilityError,'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            convert_record(record,'global',{},contract=evolved)
        evolved = copy.deepcopy(CONFIG)
        evolved['source']['models']['Global']['log_level']['default'] = 'debug'
        self.assertEqual(validate_record(record,'global',contract=evolved),
                         'global {\n}\n')
        with self.assertRaisesRegex(CompatibilityError,'EXTENSION_CONTRACT_CONVERSION_REQUIRED'):
            merge('global {\n}\n',record,contract=evolved)

    def test_omitted_default_and_explicit_null_are_distinct_drift(self):
        evolved = copy.deepcopy(LEGACY_RECORD)
        field = evolved['target']['models']['Global']['disable_thp']
        field.pop('default', None)
        without_default = copy.deepcopy(evolved)
        field['default'] = None
        self.assertIn(
            {'side':'target','path':'Global.disable_thp','code':'FIELD_DEFAULT_CHANGED'},
            contract_diagnostics(without_default, evolved),
        )


if __name__ == '__main__':
    unittest.main()
