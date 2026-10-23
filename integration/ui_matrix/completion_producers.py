"""Five fixed producers. No CLI accepts arbitrary completed-case lists."""
import json
from pathlib import Path
from . import evidence_scope as s
from . import completion as c

METADATA = ('general.interfaces-and-independent-identity', 'account.name',
 'account.avatar', 'account.username', 'configs.rename', 'dnss.rename', 'routings.rename')
SUBSCRIPTION = ('subscription.tag','subscription.link-update-preserves-group-nameFilterRegex',
 'subscription.cron-enable-expression-disable')
PATHS = tuple('group.'+p for p in ('fixed.0','fixed.1','random','min','min_moving_avg','min_avg10')) + (
 'membership.node.update','membership.group.remove-node','node.manual-all-latency') + tuple(
 'routing.'+p for p in ('direct-fallback','must-direct-fallback','block-fallback','proxy-fallback',
 'cidr-direct','port-protocol-proxy','domain-proxy','order-direct-before-block','order-block-before-direct')) + tuple(
 'global.dial-sniff.'+p for p in ('ip','domain','domain-plus','domain-double-plus','short-sniff','long-sniff')) + (
 'global.checkTolerance.800ms','global.checkTolerance.20ms','global.bandwidth.512000','global.bandwidth.4000000')
REPORTS = {'continue_global':'global-continuation.json', 'continue_dns':'dns-continuation.json',
 'extension_profile_probe':'extension-profile-probe.json', 'continue_nodes':'node-continuation.json',
 'continue_metadata':'metadata-continuation.json','continue_subscription':'subscription-continuation.json',
 'path_environment':'path-continuation.json','baseline':'baseline-observations.json'}


def classified(row):
    """Do not upgrade legacy null/CONFIG_CHAIN_ONLY into a completed runtime."""
    result = row.get('result')
    s.require(result in c.RESULTS, 'COMPLETION_UNCLASSIFIED_CASE:'+str(row.get('id')))
    restored = row.get('baselineRestored') is True or row.get('restored') is True
    s.require(restored, 'COMPLETION_BASELINE_NOT_RESTORED')
    out = {'id':row['id'], 'result':result, 'restored':True, 'witness':row['witness']}
    if result == 'FAIL':
        # A caught fixture/infrastructure exception is not an upstream finding.
        for k in ('owner','sourceEvidence','reason'):
            s.require(k in row, 'COMPLETION_UNREVIEWED_FAILURE')
            out[k] = row[k]
        if 'failureOwners' in row: out['failureOwners'] = row['failureOwners']
    return out


def produce(name, *, root=s.SOURCE, evidence=s.EVIDENCE):
    _, folder = s.current(root, evidence)
    refs = []
    def stage(stage):
        r = c.receipt(stage, root=root, evidence=evidence)
        refs.append(c.reference(folder,'executed-'+stage+'.json'))
        for ref in r['reports']: refs.append(ref)
        return r
    def report(stage_name):
        execution = stage(stage_name)
        filename = REPORTS[stage_name]
        s.require(any(x['file'] == filename for x in execution['reports']), 'COMPLETION_REPORT_NOT_EXECUTED')
        value,_ = c.load(folder,filename)
        values = value['rows'] if type(value) is dict and 'rows' in value else [value] if type(value) is dict else value
        prefix = '/rows' if type(value) is dict and 'rows' in value else None if type(value) is dict else ''
        return [dict(row, witness={**c.reference(folder,filename), 'pointer':'' if prefix is None else prefix+'/'+str(i)})
                for i,row in enumerate(values)]
    if name == 'baseline-ready':
        rows = report('baseline')
        required = ['health','official-identity','unique-dae','source-and-config','fixture-topology','no-transaction']
    elif name == 'nodes-complete':
        from .continue_nodes import cases
        required = [case['id'] for case in cases()]
        rows = report('continue_nodes')
    elif name == 'metadata-subscription-complete':
        required = list(METADATA+SUBSCRIPTION)
        rows = report('continue_metadata')+report('continue_subscription')
    elif name == 'paths-complete':
        required = list(PATHS)
        rows = report('path_environment')
        env,_ = c.load(folder,'path-cleanup-verified.json')
        s.require(env.get('cleanupVerified') is True, 'COMPLETION_PATH_CLEANUP_UNPROVEN')
        refs.append(c.reference(folder,'path-cleanup-verified.json'))
    elif name == 'queue-complete':
        # The queue excludes encrypted_dns, its consumer, avoiding a cycle.
        required = list(c.QUEUE_STAGES)
        rows = []
        for item in required:
            execution = stage(item)
            s.require(execution.get('classificationComplete') is True and
                      execution.get('baselineRestored') is True,
                      'COMPLETION_QUEUE_STAGE_NOT_CLASSIFIED:'+item)
            row = {'id':item,'result':'CONFIG_PASS' if execution['acceptancePassed'] else 'FAIL','restored':True,
                'witness':{**c.reference(folder,'executed-'+item+'.json'),'pointer':''}}
            if row['result'] == 'FAIL':
                row.update(owner='upstream aggregate', failureOwners=execution['failureOwners'], reason='Classified upstream findings retained; see hashed stage reports',
                    sourceEvidence=execution['reports'])
            rows.append(row)
    else: raise RuntimeError('COMPLETION_STAGE')
    return c.certify(name,required,[classified(r) for r in rows],refs,root=root,evidence=evidence)


def stage_cases(stage):
    """Source-defined case plan, independent of generated report content."""
    if stage == 'baseline':
        expected = ['health','official-identity','unique-dae','source-and-config','fixture-topology','no-transaction']
    elif stage == 'continue_nodes':
        from .continue_nodes import cases
        expected = [x['id'] for x in cases()]
    elif stage == 'continue_global':
        from .continue_global import CASES
        expected = [k+':'+json.dumps(v,sort_keys=True) for k,v in CASES]
    elif stage == 'continue_metadata': expected = list(METADATA)
    elif stage == 'continue_subscription': expected = list(SUBSCRIPTION)
    elif stage == 'path_environment': expected = list(PATHS)
    elif stage == 'extension_profile_probe': expected = ['extension.new-official-profile']
    elif stage == 'continue_dns':
        expected = ['dns.'+x for x in ('upstream-udp-request-fallback',
            'upstream-tcp-request-fallback','request-order-first-match',
            'response-reroute','response-order-first-match')]
    else: raise RuntimeError('COMPLETION_STAGE_PLAN')
    return expected


def completion_cases(name):
    if name == 'baseline-ready': return stage_cases('baseline')
    if name == 'nodes-complete': return stage_cases('continue_nodes')
    if name == 'metadata-subscription-complete': return list(METADATA+SUBSCRIPTION)
    if name == 'paths-complete': return list(PATHS)
    if name == 'queue-complete': return list(c.QUEUE_STAGES)
    raise RuntimeError('COMPLETION_STAGE')


def execution_summary(stage, folder):
    """Strict predeclared case coverage; rc=0 alone never certifies a queue."""
    expected = stage_cases(stage)
    value,_ = c.load(folder,REPORTS[stage])
    rows = value['rows'] if type(value) is dict and 'rows' in value else [value] if type(value) is dict else value
    if len(rows) != len(expected) or {r['id'] for r in rows} != set(expected):
        return {'classificationComplete':False,'baselineRestored':False}
    restored = all(r.get('baselineRestored') is True or r.get('restored') is True for r in rows)
    classified_all = all(r.get('result') in c.RESULTS and (r['result'] != 'FAIL' or
        (r.get('owner') in ('official daed','official Web','official DAE') and r.get('sourceEvidence') and r.get('reason'))) for r in rows)
    return {'classificationComplete':bool(classified_all), 'baselineRestored':restored,
        'requiredCases':expected, 'planSha256':s.sha(c.encoded(expected)),
        'acceptancePassed':classified_all and all(r['result'] != 'FAIL' for r in rows),
        'failureOwners':sorted({r['owner'] for r in rows if r.get('result') == 'FAIL' and 'owner' in r})}
