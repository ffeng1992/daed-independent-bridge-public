"""Read-only PID-owned socket evidence, explicitly NOT DAE logical session metrics.

DAE's userspace relay counters/UDP endpoint pool cannot be reconstructed from
these descriptors: multiplexing, DNS and transient sockets change the semantics.
"""
from pathlib import Path
import os
import time


def observe(pid, proc=Path('/proc')):
    if type(pid) is not int or pid <= 0:
        raise ValueError('DAE_PID_REQUIRED')
    base = proc / str(pid)
    before = (base/'stat').read_text().split(') ',1)[1].split()[19]
    inodes = set()
    for p in (base/'fd').iterdir():
        try:
            link = os.readlink(p)
        except FileNotFoundError:
            continue # A descriptor closed during the non-atomic observation.
        if link.startswith('socket:[') and link.endswith(']'):
            inodes.add(link[8:-1])
    counts = {}
    for protocol in ('tcp','tcp6','udp','udp6'):
        rows = (base/'net'/protocol).read_text().splitlines()[1:]
        counts[protocol] = sum(1 for row in rows if len(row.split()) >= 10 and
                               row.split()[9] in inodes and
                               (not protocol.startswith('tcp') or row.split()[3] == '01'))
    after = (base/'stat').read_text().split(') ',1)[1].split()[19]
    if before != after:
        raise RuntimeError('DAE_PROCESS_CHANGED')
    return {'observedAt':int(time.time()), 'MainPID':pid, 'processStartTicks':before,
            'source':'PID_FD_INODES_JOIN_PROC_NET', 'atomic':False,
            'ownedEstablishedTcpSockets':counts['tcp']+counts['tcp6'],
            'ownedUdpSockets':counts['udp']+counts['udp6'],
            'equivalentRuntimeMetrics':False}
