import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from integration.ui_matrix.continue_global import observe_listener, candidate_value


class MatrixListener(unittest.TestCase):
    def fixture(self, root):
        for tid, ns in ((42, 1), (43, 2), (44, 2)):
            path = root / '42' / 'task' / str(tid) / 'ns'
            path.mkdir(parents=True)
            (path / 'net').symlink_to(f'net:[{ns}]')

    def test_actual_thread_namespaces_and_pid_owned_tcp_udp(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            def run(command, **kwargs):
                calls.append(command)
                output = ''
                if '/43/' in command[1]:
                    output = '\n'.join(f'{p} UNCONN 0 0 *:12346 *:* users:(("dae",pid=42,fd=9))' for p in ('tcp', 'udp'))
                return SimpleNamespace(stdout=output)
            result = observe_listener(42, 12346, root, run)
            self.assertEqual(len(calls), 2)
            self.assertEqual(set(result['namespaces']), {'net:[1]', 'net:[2]'})
            self.assertTrue(all(c[0] == 'nsenter' for c in calls))

    def test_wrong_owner_or_partial_protocol_is_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            for owner, protocols in ((99, ('tcp', 'udp')), (42, ('tcp',))):
                output = '\n'.join(f'{p} UNCONN 0 0 *:12346 *:* users:(("dae",pid={owner},fd=9))' for p in protocols)
                with self.assertRaisesRegex(Exception, 'TPROXY_OWNED_LISTENER_MISSING'):
                    observe_listener(42, 12346, root, lambda *a, **k: SimpleNamespace(stdout=output))

    def test_probe_failure_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            def run(command, **kwargs):
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                observe_listener(42, 12346, root, run)

    def test_invalid_identity(self):
        for pid, port in ((True, 12346), (0, 12346), (42, 65536)):
            with self.assertRaisesRegex(ValueError, 'INVALID_LISTENER_IDENTITY'):
                observe_listener(pid, port)

    def test_candidate_exact_value_not_just_field_presence(self):
        text = '# synthetic provenance\nglobal {\n tproxy_port: 12346\n lan_interface: "lan1,lan2"\n mptcp: false\n}\nnode {}\n'
        self.assertEqual(candidate_value(text, 'tproxy_port', 12346), 12346)
        self.assertEqual(candidate_value(text, 'lan_interface', ['lan1', 'lan2']), 'lan1,lan2')
        self.assertIs(candidate_value(text, 'mptcp', False), False)
        for field, value in (('tproxy_port', 12345), ('lan_interface', ['lan2', 'lan1']), ('mptcp', 0)):
            with self.assertRaisesRegex(Exception, 'CANDIDATE_VALUE_CHANGED'):
                candidate_value(text, field, value)

    def test_candidate_comment_or_other_section_not_evidence(self):
        text = '# mptcp: true\nglobal { log_level: "mptcp: true"\n}\ngroup { mptcp: true\n}\n'
        with self.assertRaisesRegex(Exception, 'CANDIDATE_FIELD_MISSING'):
            candidate_value(text, 'mptcp', True)
