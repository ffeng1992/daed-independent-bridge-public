"""Nonroot CLI; stages only and never invokes the helper or a service manager."""
import json
import sys
from pathlib import Path
from .bundle import stage
from .security import Denied

try:
    if len(sys.argv)!=4:raise Denied('ARGUMENTS')
    # Receipt is public read-only metadata supplied by the trusted experiment operator.
    print(stage(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),None if sys.argv[3]=='none' else sys.argv[3]))
except Exception:
    print('{"error":"STAGING_REJECTED"}',file=sys.stderr)
    raise SystemExit(1)
