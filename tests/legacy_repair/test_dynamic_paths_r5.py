"""Execute the real path entry and save methods against temporary evidence.

Only Matrix/network/DAE operations are substitutes. Prerequisites and prior rows
are explicitly synthetic test fixtures, NOT completion evidence for a real run.
No /evidence, network namespace, systemd or production file is touched.
"""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from integration.ui_matrix import evidence_scope as scope, completion
from tests.review_tools.completion_fixture import publish_baseline_and_nodes

SOURCE_ROOT = Path(__file__).resolve().parents[2]
TARGET = SOURCE_ROOT / 'integration/ui_matrix/continue_paths.py'
if not TARGET.is_file():
    TARGET = SOURCE_ROOT.parent / 'patched_reference/integration/ui_matrix/continue_paths.py'
MODES = (
    ({}, 'path-continuation.json'),
    ({'repair': True}, 'path-witness-repair.json'),
    ({'udp_health_only': True}, 'udp-health-witness.json'),
    ({'long_sniff_only': True}, 'long-sniff-witness.json'),
)
PRIOR = [
    {'id': 'global.dial-sniff.long-sniff', 'reason': 'DIAL_CONFIG_CHANGED',
     'baselineRestored': True, 'result': 'FAIL'},
    {'id': 'global.udpCheckDns', 'reason': 'ACTUAL_UDP_HEALTH_PROBE_MISSING',
     'baselineRestored': True, 'result': 'FAIL'},
    {'id': 'routing.domain-proxy', 'reason': 'LAN_PATH_FAILED',
     'baselineRestored': True, 'result': 'FAIL'},
]


def require(value, code):
    if not value:
        raise RuntimeError(code)


class DynamicPathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / 'source'; self.source.mkdir()
        (self.source / 'upstream.lock.json').write_text('{}')
        self.evidence = self.base / 'evidence'; self.evidence.mkdir()
        self.environment = patch.dict(os.environ)
        self.environment.start(); self.addCleanup(self.environment.stop)
        os.environ.pop('BRIDGE_MATRIX_RUN_ID', None)
        self.new_run()
        self.instances = []; self.calls = []; self.failure = None
        self.imports = {}
        for name in ('path_dial_controls', 'path_bandwidth_controls',
                     'path_membership_controls', 'path_tolerance_controls'):
            module = types.ModuleType('integration.ui_matrix.' + name)
            def run(matrix, _name=name, **kwargs):
                self.calls.append((_name, matrix.path, kwargs))
                matrix.results.append({'scope': 'SYNTHETIC_CONTROL_ONLY', 'called': _name})
                if self.failure:
                    raise RuntimeError(self.failure)
            module.run = run
            self.imports[module.__name__] = module
        self.modules = patch.dict(sys.modules, self.imports)
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.ns = self.load_real_entry(TARGET.read_text())

    def new_run(self):
        binding = scope.start_run(self.source, self.evidence)
        self.binding = binding
        self.folder = self.evidence / 'runs' / binding['runId']
        os.environ['BRIDGE_MATRIX_RUN_ID'] = binding['runId']

    def local_path(self, value):
        path = Path(value)
        if path == Path('/evidence') or Path('/evidence') in path.parents:
            return self.evidence / path.relative_to('/evidence')
        raise AssertionError('unexpected filesystem path: ' + str(path))

    def scoped(self, path):
        return scope.scope_file(path, root=self.source, evidence=self.evidence)

    def load_real_entry(self, text):
        # Compile unchanged AST nodes from the actual candidate. Use the real
        # __init__, save and entire main function, not a rewritten guard fragment.
        tree = ast.parse(text)
        real_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Paths')
        real_class = copy.deepcopy(real_class)
        real_class.body = [n for n in real_class.body if isinstance(n, ast.FunctionDef)
                           and n.name in {'__init__', 'save'}]
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        owner = self
        class Matrix:
            def __init__(self):
                self.source = {'metadata': {'routings': [{'id': 'synthetic', 'selected': True}]}}
        namespace = {'__name__': '_candidate_path_entry', 'Path': self.local_path,
                     'scope_file': self.scoped, 'read_completion': lambda name: completion.read(name,root=self.source,evidence=self.evidence), 'Matrix': Matrix, 'need': require, 'json': json}
        exec(compile(ast.Module(body=[real_class, main], type_ignores=[]), str(TARGET), 'exec'), namespace)
        cls = namespace['Paths']; original_init = cls.__init__
        def init(instance):
            original_init(instance); owner.instances.append(instance)
        def setup(instance):
            owner.calls.append(('setup', instance.path, {}))
        def operation(instance, *args, **kwargs):
            owner.calls.append(('path-control', instance.path, {}))
            instance.results.append({'scope': 'SYNTHETIC_CONTROL_ONLY'})
        def restore(instance):
            owner.calls.append(('restore', instance.path, {})); instance.save()
        cls.__init__ = init; cls.setup = setup; cls.restore = restore
        cls.policy = operation; cls.latency = operation; cls.route = operation
        return namespace

    def prerequisites(self):
        publish_baseline_and_nodes(self.source,self.evidence,self.binding,self.folder)
        (self.folder/'path-fixture-ready').write_text('SYNTHETIC_UNIT_TEST_PREREQUISITE_ONLY\n')

    def prior(self):
        (self.folder / 'path-continuation.json').write_text(json.dumps(PRIOR))

    def stale_globals(self):
        names = {name for _, name in MODES} | {'path-completed-cases.json'}
        for name in names:
            (self.evidence / name).write_text('STALE_GLOBAL_MUST_NOT_BE_READ_OR_REPLACED\n')
        return {name: (self.evidence / name).read_bytes() for name in names}

    def invoke(self, **kwargs):
        return self.ns['main'](**kwargs)

    def test_default_old_global_does_not_block_or_get_rewritten(self):
        before = self.stale_globals(); self.prerequisites()
        self.invoke()
        self.assertEqual(self.instances[0].path, self.folder / 'path-continuation.json')
        self.assertTrue((self.folder / 'path-continuation.json').is_file())
        for name, raw in before.items():
            self.assertEqual((self.evidence / name).read_bytes(), raw)

    def test_repair_branch_output_and_restore_stay_in_current_run(self):
        self.check_branch({'repair': True}, 'path-witness-repair.json')

    def test_udp_branch_output_and_restore_stay_in_current_run(self):
        self.check_branch({'udp_health_only': True}, 'udp-health-witness.json')

    def test_long_sniff_branch_output_and_restore_stay_in_current_run(self):
        self.check_branch({'long_sniff_only': True}, 'long-sniff-witness.json')

    def check_branch(self, kwargs, output):
        before = self.stale_globals(); self.prerequisites(); self.prior()
        self.invoke(**kwargs)
        expected = self.folder / output
        self.assertEqual(self.instances[0].path, expected)
        self.assertTrue(expected.is_file())
        self.assertTrue(all(path == expected for _, path, _ in self.calls))
        for name, raw in before.items():
            self.assertEqual((self.evidence / name).read_bytes(), raw)

    def test_same_run_existing_output_blocks_every_branch_before_setup(self):
        self.prerequisites(); self.prior()
        for kwargs, output in MODES:
            if not (self.folder / output).exists():
                (self.folder / output).write_text('CURRENT_RUN_EXISTING')
            before = (self.folder / output).read_bytes()
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(RuntimeError, 'DO_NOT_RERUN'):
                self.invoke(**kwargs)
            self.assertEqual((self.folder / output).read_bytes(), before)
        self.assertEqual(self.instances, []); self.assertEqual(self.calls, [])

    def test_prior_global_result_cannot_satisfy_repair_input(self):
        self.prerequisites()
        (self.evidence / 'path-continuation.json').write_text(json.dumps(PRIOR))
        with self.assertRaises(FileNotFoundError):
            self.invoke(repair=True)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.folder / 'path-witness-repair.json').exists())

    def test_old_global_completion_marker_is_not_a_current_prerequisite(self):
        for name in ('nodes-complete', 'path-fixture-ready'):
            (self.evidence / name).write_text('OLD_COMPLETION')
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertEqual(self.instances, [])

    def test_old_global_fixture_ready_is_not_current_fixture(self):
        publish_baseline_and_nodes(self.source,self.evidence,self.binding,self.folder)
        (self.evidence / 'path-fixture-ready').write_text('OLD_COMPLETION')
        with self.assertRaisesRegex(RuntimeError, 'PATH_FIXTURE_NOT_READY'):
            self.invoke()
        self.assertEqual(self.instances, [])

    def test_new_run_does_not_consume_old_run_outputs_or_markers(self):
        self.prerequisites(); self.invoke()
        previous = self.folder; raw = (previous / 'path-continuation.json').read_bytes()
        self.new_run()
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertFalse((self.folder / 'path-continuation.json').exists())
        self.assertEqual((previous / 'path-continuation.json').read_bytes(), raw)

    def test_changed_run_pin_rejected_before_entry_side_effects(self):
        self.prerequisites(); os.environ['BRIDGE_MATRIX_RUN_ID'] = 'f' * 32
        with self.assertRaisesRegex(RuntimeError, 'RUN_REPLACED'):
            self.invoke()
        self.assertEqual(self.instances, [])

    def test_deployment_change_rejected_before_entry_side_effects(self):
        self.prerequisites(); (self.source / 'deployment').mkdir()
        (self.source / 'deployment/new.timer').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'CONTEXT_CHANGED'):
            self.invoke()
        self.assertEqual(self.instances, [])

    def test_output_symlink_rejected_in_every_branch(self):
        self.prerequisites()
        outside = self.base / 'outside'; outside.write_text('KEEP')
        for kwargs, name in MODES:
            target = self.folder / name; target.symlink_to(outside)
            try:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(RuntimeError, 'EVIDENCE_LINK'):
                    self.invoke(**kwargs)
            finally:
                target.unlink()
        self.assertEqual(outside.read_text(), 'KEEP')
        self.assertEqual(self.instances, [])

    def test_failed_branch_restoration_output_remains_scoped_not_global(self):
        before = self.stale_globals(); self.prerequisites(); self.prior()
        self.failure = 'SYNTHETIC_CONTROL_FAILURE'
        with self.assertRaisesRegex(RuntimeError, 'SYNTHETIC_CONTROL_FAILURE'):
            self.invoke(udp_health_only=True)
        self.assertEqual(self.calls[-1][0], 'restore')
        self.assertEqual(self.calls[-1][1], self.folder / 'udp-health-witness.json')
        self.assertTrue((self.folder / 'udp-health-witness.json').is_file())
        for name, raw in before.items():
            self.assertEqual((self.evidence / name).read_bytes(), raw)

    def test_actual_import_does_not_resolve_scope_or_contact_services(self):
        # Compile the full source with import-only dependency doubles. Resolving
        # the evidence namespace at module import would raise this assertion.
        namespace = {'__name__': '_candidate_import_only'}
        modules = {}
        for name in ('bridge_m4.collect', 'integration.ui_matrix.continue_global',
                     'scripts.release_setup', 'integration.ui_matrix.path_event_log',
                     'integration.ui_matrix.evidence_scope'):
            modules[name] = types.ModuleType(name)
        def forbidden(*args, **kwargs):
            raise AssertionError('dependency used during module import')
        modules['bridge_m4.collect'].collect = forbidden
        modules['integration.ui_matrix.continue_global'].Matrix = object
        modules['scripts.release_setup'].need = forbidden
        modules['integration.ui_matrix.path_event_log'].read = forbidden
        modules['integration.ui_matrix.evidence_scope'].scope_file = forbidden
        with patch.dict(sys.modules, modules):
            exec(compile(TARGET.read_text(), str(TARGET), 'exec'), namespace)
        self.assertTrue(callable(namespace['main']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
