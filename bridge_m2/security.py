"""Bounded, descriptor-relative file reads; errors never contain source values."""
import os
import stat
from pathlib import Path
from bridge_m1.common import canonical, digest, load_json


class Denied(Exception):
    pass


def check(ok, code):
    if not ok:
        raise Denied(code)


def directory(path, uid, gid, mode=0o700):
    path = Path(path).absolute()
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        s = os.fstat(fd)
        check(s.st_uid == uid and s.st_gid == gid and stat.S_IMODE(s.st_mode) == mode, 'DIRECTORY_AUTHORITY')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_at(fd, name, uid, gid, mode=0o600, limit=4 * 1024 * 1024):
    check('/' not in name and name not in ('.', '..'), 'PATH_REJECTED')
    filefd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(filefd)
        check(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'FILE_TYPE')
        check(before.st_uid == uid and before.st_gid == gid and stat.S_IMODE(before.st_mode) == mode, 'FILE_AUTHORITY')
        check(before.st_size <= limit, 'SIZE_LIMIT')
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(filefd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        after = os.fstat(filefd)
        linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
        check(identity(before) == identity(after) == identity(linked) and len(data) == before.st_size, 'SOURCE_RACE')
        return bytes(data)
    finally:
        os.close(filefd)


def read_set(path, uid, gid, names, mode=0o600):
    fd = directory(path, uid, gid)
    try:
        check(set(os.listdir(fd)) == set(names), 'FILE_SET')
        return {n: read_at(fd, n, uid, gid, mode) for n in sorted(names)}
    finally:
        os.close(fd)


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def write_file(path, body, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(body)
            stream.flush()
            os.fsync(fd)
    finally: os.close(fd)


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.unlink(missing_ok=True)
    write_file(temp, canonical(value))
    os.replace(temp, path)
    syncdir(path.parent)
