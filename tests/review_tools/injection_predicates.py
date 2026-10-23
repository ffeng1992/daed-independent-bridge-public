"""Review-only gate; never writes product state or controls units."""
def eligible(o, expected):
    j=o['native'];t=o['install']
    checks={
      'newAttempt':j.get('attemptId')!=expected['oldAttempt'] and bool(j.get('attemptId')),
      'phase':j.get('phase')=='QUIESCING','scope':j.get('recoveryScope')=='triggers-only',
      'beforeTimers':type(j.get('beforeTimers')) is dict and bool(j['beforeTimers']),
      'beforeUnitsAbsent':'beforeUnits' not in j,
      'generation':j.get('previousGeneration')==expected['generation']==t.get('generation'),
      'installNotWriting':t.get('phase') in ('COMMITTED','RESTORED'),
      'manifest':o['manifest']==expected['manifest'],
      'process':o['processMatches'] is True,
      'locks':o['ownsReleaseLock'] is True,
      'timerStopped':any(v.get('ActiveState')=='active' and o['timers'].get(n,{}).get('ActiveState')=='inactive' for n,v in j.get('beforeTimers',{}).items()),
    }
    return all(checks.values()),checks


def expected_from(before):
    value = {'oldAttempt':before['native']['attemptId'],
             'generation':before['install']['generation'], 'manifest':before['manifest']}
    if not all(type(v) is str and v for v in value.values()):
        raise ValueError('INJECTION_EXPECTED_IDENTITY')
    return value
