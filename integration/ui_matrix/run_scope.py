"""Explicit run initialization and fixed-stage execution. No implicit old markers.

Run this INSIDE an already provisioned disposable matrix VM. This launcher does
not provision a network, start official services or perform production work.
Stage bodies retain their existing fixture safety checks. Child output is not
classified as PASS by this launcher; its exact return code is retained.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from . import completion

from . import evidence_scope as scope

STAGES = frozenset((
    'continue_global', 'continue_dns', 'continue_duplicates',
    'continue_kernel_controls', 'continue_metadata', 'continue_nodes',
    'continue_paths', 'continue_subscription', 'continue_tls_controls',
    'extension_profile_probe', 'bridge_blockers', 'encrypted_dns',
    'extension_preservation', 'remaining_actions', 'path_environment', 'baseline',
))


def execute(stage, arguments, run_id, *, source=scope.SOURCE,
            evidence=scope.EVIDENCE, runner=subprocess.run):
    scope.require(stage in STAGES, 'MATRIX_STAGE_NOT_ALLOWED')
    scope.require(type(run_id) is str and len(run_id) == 32 and
                  all(c in '0123456789abcdef' for c in run_id), 'MATRIX_RUN_ID')
    scope.require(all(type(a) is str and '\x00' not in a for a in arguments), 'MATRIX_STAGE_ARGUMENTS')
    # No arbitrary module, command, interpreter or credential is accepted.
    with scope.run_lock(evidence):
        value, folder = scope.current(source, evidence)
        scope.require(value['runId'] == run_id, 'MATRIX_RUN_REPLACED')
        env = dict(os.environ, BRIDGE_MATRIX_RUN_ID=run_id,
                   PYTHONOPTIMIZE=str(sys.flags.optimize), PYTHONDONTWRITEBYTECODE='1')
        command = [sys.executable, '-B', '-m',
                   'integration.ui_matrix.' + stage, *arguments]
        started = time.time()
        result = runner(command, cwd=source, env=env, check=False)
        # Do not trust a completed child after source/boot/run binding drift.
        after, _ = scope.current(source, evidence)
        scope.require(after == value, 'MATRIX_RUN_CONTEXT_CHANGED')
        from .completion_producers import REPORTS, execution_summary
        reports = []
        report_name = REPORTS.get(stage)
        if report_name and (folder/report_name).is_file():
            reports.append(completion.reference(folder,report_name))
        summary = execution_summary(stage,folder) if stage in REPORTS and reports and result.returncode == 0 else {'classificationComplete':False,'baselineRestored':False}
        completion.atomic_once(folder, 'executed-'+stage+'.json', {**summary,
            'scope':value,'stage':stage,'command':command,
            'startedAt':started,'endedAt':time.time(),'returncode':result.returncode,
            'completed':True,'reports':reports})
        return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    done = sub.add_parser('complete', help='Certify fixed reports, never create an empty marker')
    done.add_argument('stage', choices=sorted(completion.PREDECESSORS))
    sub.add_parser('init', help='Create a fresh run; never import old global evidence')
    run = sub.add_parser('run')
    run.add_argument('--run-id', required=True)
    run.add_argument('stage', choices=sorted(STAGES))
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.action == 'complete':
        from .completion_producers import produce
        print(json.dumps(produce(args.stage), sort_keys=True))
        return 0
    if args.action == 'init':
        value = scope.start_run()
        print(json.dumps({'scope': value, 'directory': str(scope.EVIDENCE/'runs'/value['runId']),
                          'evidenceResult': 'NOT_RUN'}, sort_keys=True))
        return 0
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    return execute(args.stage, arguments, args.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
