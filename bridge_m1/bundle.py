"""Create new local output directories only. No publication or overwrite operation."""
from dataclasses import asdict
from pathlib import Path

from .common import ROOT, VERSION, canonical, digest, require
from .emit import emit
from .model import normalize


def artifacts(snapshot, kind='offline-snapshot', version='v2.1.1', collection=None):
    source, ir = normalize(snapshot, kind, version)
    candidate = emit(ir)
    report = {'schemaVersion': 1, 'status': 'converted', 'converterVersion': VERSION,
              'sourceSha256': ir.source_fingerprint, 'candidateSha256': digest(candidate),
              'validation': 'not-run', 'runtimeCompatibility': 'NOT_TESTED', 'synthetic': True,
              'diagnostics': [], 'mapping': [{'field': g['key'], 'classification': g['mapping'], 'emitted': g['emitted']} for g in ir.globals],
              'collection': collection or {'method': 'offline-snapshot', 'transactional': False, 'liveStabilityVerified': False}}
    payloads = {'candidate.dae': candidate, 'source-snapshot.json': canonical(source),
                'normalized-ir.json': canonical(asdict(ir)), 'conversion-report.json': canonical(report)}
    manifest = {'schemaVersion': 1, 'converterVersion': VERSION, 'target': 'dae-v2.1.1-linux-x86_64',
                'files': {name: {'sha256': digest(body), 'size': len(body)} for name,body in sorted(payloads.items())}}
    payloads['manifest.json'] = canonical(manifest)
    payloads['SHA256SUMS'] = ''.join(digest(body) + '  ' + name + '\n' for name,body in sorted(payloads.items())).encode()
    return payloads


def write_new(payloads, output):
    # Only project-local out/ is writable. Resolve BEFORE creation, reject symlink ancestors.
    output = Path(output).absolute()
    base = ROOT / 'out'
    require(base.resolve() == base and output.resolve().is_relative_to(base) and output != base, 'OUTPUT_PATH_REJECTED')
    for p in [output, *output.parents]:
        require(not p.is_symlink(), 'OUTPUT_PATH_REJECTED')
    require(not output.exists() and output.parent.exists(), 'OUTPUT_EXISTS_OR_PARENT_MISSING')
    output.mkdir(mode=0o700)  # exclusive; never overwrite an existing candidate
    for name, body in payloads.items():
        require(name in {'candidate.dae','source-snapshot.json','normalized-ir.json','conversion-report.json','manifest.json','SHA256SUMS'}, 'OUTPUT_PATH_REJECTED')
        with (output / name).open('xb') as handle:
            handle.write(body)
        (output / name).chmod(0o600)
