"""Private compatibility evidence; not an M2-authorized apply bundle."""
from .convert import normalize,emit,VERSION
from .extensions import need
from bridge_m1.common import canonical,digest

def artifacts(source,proof,extensions):
    fingerprint=digest(canonical(source))
    need(proof['beforeSha256']==proof['afterSha256']==fingerprint,'SOURCE_FINGERPRINT_MISMATCH','$')
    ir=normalize(source,extensions)
    report={'schemaVersion':1,'converterVersion':VERSION,'sourceFingerprint':fingerprint,
            'collection':proof,'classification':'REGENERATED_INDEPENDENT_BRIDGE_OUTPUT',
            'compatibilityDefaults':list(ir.compatibility_defaults),
            'nodeCount':len(ir.nodes),'activeNodeCount':len({m for g in ir.groups for m in g['members']}),
            'groupCount':len(ir.groups),'unsupported':[],
            'officialValidate':'REQUIRED_SEPARATE_EVIDENCE','applyAuthorized':False}
    files={'candidate.dae':emit(ir),'source-snapshot.json':canonical(source),
           'normalized-ir.json':canonical(ir.json()),'conversion-report.json':canonical(report)}
    manifest={'schemaVersion':1,'converterVersion':VERSION,'sourceFingerprint':fingerprint,
              'extensionsSha256':digest(canonical(extensions)),'scope':'M4_COMPATIBILITY_PREVIEW_NOT_APPLY',
              'files':{name:digest(body) for name,body in sorted(files.items())}}
    files['manifest.json']=canonical(manifest)
    files['SHA256SUMS']=''.join(digest(body)+'  '+name+'\n' for name,body in sorted(files.items())).encode()
    return files
