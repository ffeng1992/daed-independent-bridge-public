import tempfile
from pathlib import Path
import unittest
from bridge_m4.kernel_observations import observe

class Observations(unittest.TestCase):
    def test_only_owned_sockets_not_host_counters(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)/'42';(base/'fd').mkdir(parents=True);(base/'net').mkdir()
            (base/'stat').write_text('42 (synthetic) '+' '.join(['0']*19+['123']))
            (base/'fd'/'3').symlink_to('socket:[100]')
            row=lambda inode,state:'0: a b '+state+' 0 0 0 0 0 '+inode+'\n'
            for name in ('tcp','tcp6','udp','udp6'):
                (base/'net'/name).write_text('header\n'+(row('100','01')+row('200','01') if name=='tcp' else ''))
            v=observe(42,Path(t))
            self.assertEqual(v['ownedEstablishedTcpSockets'],1)
            self.assertEqual(v['ownedUdpSockets'],0)
            self.assertFalse(v['equivalentRuntimeMetrics'])
            self.assertNotIn('uploadTotal',v)
    def test_missing_proc_is_not_zero_success(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):observe(42,Path(t))
    def test_pid_injection_refused(self):
        for value in ('../42',0,-1,True):
            with self.assertRaises(ValueError):observe(value)
