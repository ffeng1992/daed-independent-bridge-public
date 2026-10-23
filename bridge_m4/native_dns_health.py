"""Read-only PID-owned IPv4 TCP/UDP DNS listener checks for native DAE DNS."""
import os
from pathlib import Path
import socket


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def owned_protocols(tables, inodes, address, port=53):
    wanted = socket.inet_aton(address)[::-1].hex().upper()
    found = set()
    for protocol, text in tables:
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            local, state, inode = parts[1], parts[3], parts[9]
            host, local_port = local.rsplit(':', 1)
            if (host in {'00000000', wanted} and int(local_port, 16) == port and
                    inode in inodes and
                    ((protocol == 'tcp' and state == '0A') or
                     (protocol == 'udp' and state in {'01', '07'}))):
                found.add(protocol)
    return found


def check(status, address, *, proc=Path('/proc')):
    pid = status.get('MainPID')
    require(type(pid) is int and pid > 0 and status.get('identityVerified') is True,
            'NATIVE_DNS_DAE_IDENTITY')
    base = Path(proc) / str(pid)
    # starttime remains stable while CPU/state counters do not.
    started = (base / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    inodes = set()
    for fd in (base / 'fd').iterdir():
        try:
            target = os.readlink(fd)
        except FileNotFoundError:
            continue
        if target.startswith('socket:[') and target.endswith(']'):
            inodes.add(target[8:-1])
    seen, tables = set(), []
    tasks = list((base / 'task').iterdir())
    require(len(tasks) <= 256, 'NATIVE_DNS_TASK_LIMIT')
    for task in tasks:
        namespace = os.readlink(task / 'ns/net')
        if namespace in seen:
            continue
        seen.add(namespace)
        for protocol in ('tcp', 'udp'):
            with (task / 'net' / protocol).open() as stream:
                text = stream.read(4 * 1024 * 1024 + 1)
            require(len(text) <= 4 * 1024 * 1024, 'NATIVE_DNS_SOCKET_LIMIT')
            tables.append((protocol, text))
    require(owned_protocols(tables, inodes, address) == {'tcp', 'udp'}, 'NATIVE_DNS_OWNED_LISTENER')
    require((base / 'stat').read_text().rsplit(')', 1)[1].split()[19] == started,
            'NATIVE_DNS_PROCESS_CHANGED')


def address(status, *, proc=Path('/proc')):
    """Discover the single non-loopback IPv4 listener owned by verified DAE.

    This is observation, not DNS reconfiguration. Ambiguous layouts are refused.
    """
    import ipaddress
    pid = status.get('MainPID')
    require(type(pid) is int and pid > 0 and status.get('identityVerified') is True,
            'NATIVE_DNS_DAE_IDENTITY')
    base = proc / str(pid)
    inodes = set()
    for fd in (base / 'fd').iterdir():
        try:
            link = os.readlink(fd)
        except FileNotFoundError:
            continue
        if link.startswith('socket:[') and link.endswith(']'):
            inodes.add(link[8:-1])
    candidates, seen = set(), set()
    for task in (base / 'task').iterdir():
        namespace = os.readlink(task / 'ns/net')
        if namespace in seen:
            continue
        seen.add(namespace)
        with (task / 'net/tcp').open() as stream:
            text = stream.read(4 * 1024 * 1024 + 1)
        require(len(text) <= 4 * 1024 * 1024, 'NATIVE_DNS_SOCKET_LIMIT')
        for line in text.splitlines()[1:]:
            row = line.split()
            if len(row) < 10 or row[3] != '0A' or row[9] not in inodes:
                continue
            host, port = row[1].split(':')
            if int(port, 16) != 53:
                continue
            ip = ipaddress.IPv4Address(bytes.fromhex(host)[::-1])
            if not ip.is_loopback and not ip.is_unspecified:
                candidates.add(str(ip))
    require(len(candidates) == 1, 'NATIVE_DNS_ADDRESS_AMBIGUOUS')
    found = next(iter(candidates))
    check(status, found, proc=proc)
    return found
