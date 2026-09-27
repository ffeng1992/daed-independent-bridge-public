import argparse
import sys
from pathlib import Path

from .bundle import artifacts, write_new
from .collect import HTTPReader, collect, MAX_BYTES
from .common import ROOT, Rejected, canonical, load_json, require


def main(argv=None):
    parser = argparse.ArgumentParser(description='Synthetic-only read-only M1 converter; no daemon/control commands.')
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--snapshot', type=Path)
    src.add_argument('--graphql')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--source-version', required=True, choices=['v2.1.1'])
    parser.add_argument('--out', type=Path, required=True, help='New directory below project out/; parent must exist')
    args = parser.parse_args(argv)
    try:
        if args.snapshot:
            with args.snapshot.open('rb') as f:
                raw = f.read(MAX_BYTES + 1)
            require(len(raw) <= MAX_BYTES, 'INPUT_LIMIT')
            snapshot, evidence, kind = load_json(raw), None, 'offline-snapshot'
        else:
            require(args.token_file is not None, 'AUTH_FAILED')
            require(args.token_file.stat().st_size <= 8192, 'INPUT_LIMIT')
            token = args.token_file.read_text().strip()
            snapshot, evidence = collect(HTTPReader(args.graphql, token))
            kind = 'graphql'
        payloads = artifacts(snapshot, kind, args.source_version, evidence)
        write_new(payloads, args.out)
        sys.stdout.buffer.write(canonical({'status':'converted','files': sorted(payloads),'validation':'not-run'}))
        return 0
    except Rejected as exc:
        sys.stderr.buffer.write(canonical({'status':'rejected','diagnostics':[exc.diagnostic]}))
        return 2
    except (OSError, ValueError, TypeError):
        sys.stderr.buffer.write(canonical({'status':'rejected','diagnostics':[{'objectType':'io','objectId':None,'fieldPath':'$','reasonCode':'IO_ERROR','message':'Input/output failed; values suppressed.'}]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
