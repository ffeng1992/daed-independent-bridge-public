"""Fail-closed completion certificates for the existing isolated matrix.

Certificates refer to executed receipts and immutable reports. They are not
handwritten prerequisites and do not turn a configuration pass into runtime.
"""
import fcntl
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path
from . import evidence_scope as s

PREDECESSORS = {
    'baseline-ready': (),
    'nodes-complete': ('baseline-ready',),
    'metadata-subscription-complete': ('nodes-complete',),
    'paths-complete': ('nodes-complete', 'metadata-subscription-complete'),
    'queue-complete': ('baseline-ready', 'nodes-complete',
                       'metadata-subscription-complete', 'paths-complete'),
}
# Defined before execution, never inferred from whatever reports happen to exist.
QUEUE_STAGES = ('continue_global', 'continue_nodes', 'continue_metadata',
    'continue_subscription', 'path_environment', 'extension_profile_probe', 'continue_dns')
RESULTS = frozenset(('CONFIG_PASS', 'RUNTIME_PASS', 'FAIL'))


def encoded(v):
    return (json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def load(folder, name):
    p = s.evidence_path(folder, name)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        s.require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                  st.st_size <= 32*1024*1024, 'COMPLETION_FILE_IDENTITY')
        raw = os.read(fd, st.st_size+1)
        after = os.fstat(fd)
        s.require((st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) ==
                  (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                  and len(raw) == st.st_size, 'COMPLETION_FILE_CHANGED')
        return json.loads(raw), s.sha(raw)
    finally:
        os.close(fd)


def atomic_once(folder, name, value):
    path = s.evidence_path(folder, name)
    tmp = s.evidence_path(folder, '.completion-'+uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(encoded(value)); out.flush(); os.fsync(out.fileno())
        # link is an atomic no-replace commit. The temporary link is removed
        # before readers acquire the same certificate lock.
        os.link(tmp, path, follow_symlinks=False)
    finally:
        tmp.unlink(missing_ok=True)
    directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def reference(folder, name):
    _, digest = load(folder, name)
    return {'file': name, 'sha256': digest}


def verify_reference(folder, ref):
    s.require(type(ref) is dict and set(ref) == {'file','sha256'}, 'COMPLETION_REFERENCE_SCHEMA')
    value, digest = load(folder, ref['file'])
    s.require(digest == ref['sha256'], 'COMPLETION_EVIDENCE_HASH_CHANGED')
    return value


def verify_rows(folder, required, rows):
    s.require(len(rows) == len(required) and {r['id'] for r in rows} == set(required), 'COMPLETION_CASES_MISSING')
    from .evidence_report import resolve
    for row in rows:
        s.require(row.get('result') in RESULTS and row.get('restored') is True,
                  'COMPLETION_UNCLASSIFIED_OR_NOT_RESTORED')
        witness = row['witness']
        observed = resolve(verify_reference(folder, {k:witness[k] for k in ('file','sha256')}), witness['pointer'])
        if witness['pointer'] == '' and 'stage' in observed and 'returncode' in observed:
            s.require(observed['stage'] == row['id'] and observed['returncode'] == 0 and
                      observed.get('classificationComplete') is True and
                      observed.get('baselineRestored') is True and
                      type(observed.get('acceptancePassed')) is bool and
                      ((row['result'] == 'CONFIG_PASS') == observed['acceptancePassed']),
                      'COMPLETION_QUEUE_NOT_COMPLETE')
        else:
            s.require(observed['id'] == row['id'] and observed['result'] == row['result'] and
                      (observed.get('baselineRestored') is True or observed.get('restored') is True),
                      'COMPLETION_WITNESS_MISMATCH')
        if row['result'] == 'FAIL' and witness['pointer'] == '' and 'stage' in observed and 'returncode' in observed:
            s.require(row.get('owner') == 'upstream aggregate' and
                      row['failureOwners'] == observed['failureOwners'] and
                      row['failureOwners'] and set(row['failureOwners']) <=
                      {'official daed','official Web','official DAE'}, 'COMPLETION_QUEUE_FAILURE_OWNER')
        elif row['result'] == 'FAIL':
            s.require(row.get('owner') in ('official daed','official Web','official DAE') and
                      row.get('sourceEvidence') and row.get('reason'), 'COMPLETION_UNREVIEWED_FAILURE')


def read(name, *, root=s.SOURCE, evidence=s.EVIDENCE):
    binding, folder = s.current(root, evidence)
    s.require(name in PREDECESSORS, 'COMPLETION_STAGE')
    value, _ = load(folder, name)
    s.require(type(value) is dict and value.get('schemaVersion') == 1 and
        value.get('scope') == binding and value.get('stage') == name and
        value.get('classificationComplete') is True and
        type(value.get('acceptancePassed')) is bool, 'COMPLETION_SCHEMA_OR_SCOPE')
    from .completion_producers import completion_cases
    s.require(value['requiredCases'] == completion_cases(name), 'COMPLETION_PLAN_CHANGED')
    s.require(set(value['predecessors']) == set(PREDECESSORS[name]), 'COMPLETION_PREDECESSORS')
    for previous, digest in value['predecessors'].items():
        prior = read(previous, root=root, evidence=evidence)
        _, actual = load(folder, previous)
        s.require(actual == digest and prior['classificationComplete'], 'COMPLETION_PREDECESSOR_CHANGED')
    for ref in value['evidence']: verify_reference(folder, ref)
    verify_rows(folder,value['requiredCases'],value['rows'])
    s.require(value['acceptancePassed'] == all(r['result'] != 'FAIL' for r in value['rows']), 'COMPLETION_ACCEPTANCE_CHANGED')
    s.require(value['planSha256'] == s.sha(encoded(value['requiredCases'])) and
              value['requiredCases'] and len(set(value['requiredCases'])) == len(value['requiredCases']), 'COMPLETION_PLAN')
    return value


def certify(name, required, rows, refs, *, root=s.SOURCE, evidence=s.EVIDENCE):
    """Only called by fixed stage producers, after child exit and cleanup."""
    s.require(name in PREDECESSORS and required and len(set(required)) == len(required), 'COMPLETION_PLAN')
    from .completion_producers import completion_cases
    s.require(required == completion_cases(name), 'COMPLETION_PLAN_CHANGED')
    binding, folder = s.current(root, evidence)
    lockpath = s.evidence_path(folder, '.completion.lock')
    fd = os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        s.require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                  st.st_uid == os.geteuid() and not st.st_mode & 0o077, 'COMPLETION_LOCK_IDENTITY')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_rows(folder,required,rows)
        s.require(refs, 'COMPLETION_EVIDENCE_REQUIRED')
        for ref in refs: verify_reference(folder, ref)
        predecessors = {}
        for previous in PREDECESSORS[name]:
            read(previous, root=root, evidence=evidence)
            predecessors[previous] = load(folder, previous)[1]
        s.require(s.current(root, evidence)[0] == binding, 'MATRIX_RUN_CONTEXT_CHANGED')
        value = {'schemaVersion':1, 'scope':binding, 'stage':name,
            'requiredCases':required, 'planSha256':s.sha(encoded(required)),
            'rows':rows, 'evidence':refs, 'predecessors':predecessors,
            'classificationComplete':True,
            'acceptancePassed':all(r['result'] != 'FAIL' for r in rows),
            'completedAt':time.time(), 'interpreter':sys.executable}
        atomic_once(folder, name, value)
        return value
    finally: os.close(fd)


def receipt(stage, *, root=s.SOURCE, evidence=s.EVIDENCE):
    binding, folder = s.current(root, evidence)
    value, _ = load(folder, 'executed-'+stage+'.json')
    s.require(type(value) is dict and type(value.get('reports')) is list and value['reports'], 'COMPLETION_EXECUTION_SCHEMA')
    s.require(value['scope'] == binding and value['stage'] == stage and
              type(value['returncode']) is int and value['returncode'] == 0 and
              value['completed'] is True, 'COMPLETION_EXECUTION_FAILED')
    for ref in value['reports']: verify_reference(folder, ref)
    return value
