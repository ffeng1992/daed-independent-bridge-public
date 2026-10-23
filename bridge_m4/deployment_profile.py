"""Explicit DNS ownership; never infer retirement from an old failure alone."""
from pathlib import Path
import subprocess
from .advisory import read_json

LAYOUT = Path('/etc/daed-independent-bridge/layout.json')
POLICY_UNITS = ('bridge-policy-dns.service', 'dae-policy-dns.service')
DNS_UNITS = frozenset(('bridge-policy-dns.service', 'bridge-lan-dns.service',
    'independent-dns-sync.service', 'independent-dns-sync.timer',
    'independent-policy-sync.service', 'independent-policy-sync.timer'))


def require(value, code):
    if not value:
        raise RuntimeError(code)


def validate(value):
    require(type(value) is dict and set(value) ==
            {'schemaVersion', 'layoutVersion', 'dnsOwnership', 'policyDnsUnits'}, 'LAYOUT_SCHEMA')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and
            type(value['layoutVersion']) is int and value['layoutVersion'] == 1, 'LAYOUT_VERSION')
    ownership, units = value['dnsOwnership'], value['policyDnsUnits']
    require(ownership in {'native-dae', 'bridge-managed', 'external-policy'} and
            type(units) is list and all(type(n) is str and n in POLICY_UNITS for n in units) and
            len(set(units)) == len(units), 'LAYOUT_SCHEMA')
    require((ownership == 'native-dae' and units == []) or
            (ownership == 'bridge-managed' and units == ['bridge-policy-dns.service']) or
            (ownership == 'external-policy' and units == ['dae-policy-dns.service']), 'LAYOUT_DNS_CONSUMERS')
    return value


def load(path=LAYOUT):
    try:
        return validate(read_json(path, owner=0, mode=0o644, limit=4096))
    except FileNotFoundError:
        # Preserve old behavior until a reviewed deployment classification exists.
        return None


_UNSET = object()

def native(profile=_UNSET):
    value = load() if profile is _UNSET else profile
    return bool(value and value['dnsOwnership'] == 'native-dae')


def show(unit):
    require(unit in POLICY_UNITS, 'GEODATA_POLICY_DNS_UNIT_REJECTED')
    result = subprocess.run(['/usr/bin/systemctl', 'show', unit, '--all',
                             '--property=LoadState,ActiveState,MainPID,ControlPID,UnitFileState'],
                            capture_output=True, text=True, timeout=5, check=True)
    observed = {}
    for line in result.stdout.splitlines():
        require('=' in line, 'GEODATA_POLICY_DNS_STATE_UNKNOWN')
        key, value = line.split('=', 1)
        require(key not in observed, 'GEODATA_POLICY_DNS_STATE_UNKNOWN')
        observed[key] = value
    require(set(observed) == {'LoadState', 'ActiveState', 'MainPID',
                              'ControlPID', 'UnitFileState'},
            'GEODATA_POLICY_DNS_STATE_UNKNOWN')
    return observed


def retired_policy_dns(observed):
    """An explicitly unselected service is absent or inactive and not enabled.

    A missing UnitFileState is not evidence of a missing unit. systemd's
    not-found belongs to LoadState; an empty UnitFileState is valid ONLY with
    explicit not-found, inactive and both process IDs equal to zero.
    This predicate is shared with native lifecycle preflight.
    """
    if type(observed) is not dict:
        return False
    if observed.get('MainPID') != '0' or observed.get('ControlPID') != '0':
        return False
    loaded = observed.get('LoadState')
    if loaded == 'not-found':
        return (observed.get('ActiveState') == 'inactive' and
                observed.get('UnitFileState') == '')
    return (loaded in {'loaded', 'masked'} and
            observed.get('ActiveState') in {'inactive', 'failed'} and
            observed.get('UnitFileState') in {'disabled', 'masked', 'static'})


def selected_policy_dns(profile, states):
    """True only for a healthy configured consumer, not an unrelated stale failed unit."""
    require(type(states) is dict and all(type(states.get(name)) is dict
            for name in POLICY_UNITS), 'GEODATA_POLICY_DNS_STATE_UNKNOWN')
    if profile is None:
        active = False
        for name in POLICY_UNITS:
            observed = states[name]
            require(observed.get('LoadState') in {'loaded', 'masked', 'not-found'},
                    'GEODATA_POLICY_DNS_STATE_UNKNOWN')
            if observed['LoadState'] == 'not-found':
                require(retired_policy_dns(observed), 'GEODATA_POLICY_DNS_STATE_UNKNOWN')
            state = observed.get('ActiveState')
            require(state in {'active', 'inactive', 'failed', 'activating', 'deactivating'},
                    'GEODATA_POLICY_DNS_STATE_UNKNOWN')
            require(state in {'active', 'inactive'}, 'GEODATA_POLICY_DNS_NOT_HEALTHY')
            active = active or state == 'active'
        return active
    validate(profile)
    selected = set(profile['policyDnsUnits'])
    for name in POLICY_UNITS:
        observed = states[name]
        if name in selected:
            require(observed.get('LoadState') == 'loaded' and
                    observed.get('ActiveState') == 'active' and
                    str(observed.get('MainPID', '')).isascii() and
                    str(observed.get('MainPID', '')).isdigit() and int(observed['MainPID']) > 0,
                    'GEODATA_POLICY_DNS_NOT_HEALTHY')
        else:
            require(retired_policy_dns(observed), 'LAYOUT_UNDECLARED_DNS_CONSUMER')
    return bool(selected)


def policy_dns_active():
    return selected_policy_dns(load(), {unit: show(unit) for unit in POLICY_UNITS})


def lifecycle_units(units, profile):
    """Select only owned units; never start an explicitly retired DNS timer."""
    if profile and profile['dnsOwnership'] == 'native-dae':
        return tuple(name for name in units if name not in DNS_UNITS)
    return tuple(units)
