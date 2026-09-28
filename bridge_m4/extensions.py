"""Lossless separation of pinned target-only fields; no implicit defaults.

This module parses section boundaries and scalar extension fields, not DAE's
routing expression grammar. Official validate remains mandatory downstream.
"""
import hashlib
import json
import re
from pathlib import Path

MODELS = json.loads((Path(__file__).resolve().parents[1] / 'contracts/m4/config-models.json').read_text())
SECTIONS = {'global': 'Global', 'dns': 'Dns', 'group': 'Group'}

class CompatibilityError(ValueError):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__(code + ':' + path)  # Never include source values.

def empty_group_diagnostic(exc):
    """Expose only this authenticated configuration error, never arbitrary values."""
    if not isinstance(exc, CompatibilityError) or exc.code != 'EMPTY_REFERENCED_GROUP':
        return None
    match = re.fullmatch(r'groups\.([A-Za-z_][A-Za-z0-9_.-]*)\.nodes', exc.path)
    if match is None:
        return None
    return {'error': exc.code, 'groupName': match[1], 'fieldPath': exc.path}

def need(condition, code, path):
    if not condition:
        raise CompatibilityError(code, path)

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()

def extension_specs(section):
    name = SECTIONS[section]
    if section == 'group':
        return {key: spec for key, spec in MODELS['target']['models'][name].items() if key not in ('filter','policy')}
    return {key: spec for key, spec in MODELS['target']['models'][name].items()
            if key not in MODELS['source']['models'][name]}

def masked(text):
    """Preserve offsets/newlines while masking comments and quoted strings."""
    out = list(text); quote = None; escaped = False; comment = False
    for i, char in enumerate(text):
        if comment:
            if char == '\n': comment = False
            else: out[i] = ' '
        elif quote:
            if char != '\n': out[i] = ' '
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == quote: quote = None
        elif char in ('"', "'", '`'):
            quote = char; out[i] = ' '
        elif char == '#':
            comment = True; out[i] = ' '
    need(quote is None, 'INVALID_CONFIG_SYNTAX', '$')
    return ''.join(out)

def statements(text, section):
    """Return ordered top-level statements with exact source spans."""
    clean = masked(text)
    header = re.match(r'\s*' + re.escape(section) + r'\s*\{', clean)
    need(header is not None, 'INVALID_SECTION', section)
    start = header.end(); depth = 0; parens = 0; spans = []; closed = False
    for i in range(start, len(clean)):
        c = clean[i]
        if c == '{': depth += 1
        elif c == '}':
            if depth == 0:
                need(parens == 0 and not clean[i+1:].strip(), 'INVALID_CONFIG_SYNTAX', section)
                if clean[start:i].strip(): spans.append((start, i))
                closed = True; break
            depth -= 1
            if depth == 0 and parens == 0:
                spans.append((start, i+1)); start = i+1
        elif c == '(': parens += 1
        elif c == ')':
            parens -= 1
            need(parens >= 0, 'INVALID_CONFIG_SYNTAX', section)
        elif c == '\n' and depth == 0 and parens == 0:
            if clean[start:i].strip(): spans.append((start, i+1))
            start = i+1
    need(closed, 'INVALID_CONFIG_SYNTAX', section)
    result = []; seen = set()
    for start, end in spans:
        m = re.match(r'\s*([a-z][a-z0-9_]*)\s*(:|\{)', clean[start:end])
        need(m is not None, 'INVALID_FIELD_SYNTAX', section)
        key = m[1]
        need(key not in seen, 'DUPLICATE_FIELD', section+'.'+key)
        seen.add(key); result.append((key, start, end, m[2]))
    return result

def scalar(raw, spec, path):
    # Official serialization quotes scalar values. Decode before type checking.
    raw=raw.strip()
    if raw.startswith('"'):
        try:
            value,end=json.JSONDecoder().raw_decode(raw)
        except ValueError:raise CompatibilityError('INVALID_EXTENSION_TYPE',path) from None
        need(type(value) is str and not masked(raw[end:]).strip(),'INVALID_EXTENSION_TYPE',path)
        raw=value
    elif raw.startswith("'"):
        match=re.fullmatch(r"'([^'\\]*)'\s*(?:#[^\n]*)?",raw)
        need(match is not None,'INVALID_EXTENSION_TYPE',path);raw=match[1]
    else:raw=masked(raw).strip()
    typ=spec['type']
    if typ=='bool':
        need(raw in ('true','false'),'INVALID_EXTENSION_TYPE',path);return raw=='true'
    if typ in ('string','time.Duration','[]string'):
        need('\x00' not in raw and '\n' not in raw,'INVALID_EXTENSION_TYPE',path)
        if typ=='time.Duration':need(bool(re.fullmatch(r'(?:0|(?:[0-9]+(?:\.[0-9]+)?(?:ns|us|µs|ms|s|m|h))+)',raw)),'INVALID_EXTENSION_TYPE',path)
        return ([] if not raw else raw.split(',')) if typ=='[]string' else raw
    need(bool(re.fullmatch(r'\d+',raw)),'INVALID_EXTENSION_TYPE',path)
    value=int(raw);maximum=2**32-1 if typ=='uint32' else 2**63-1
    need(value<=maximum,'INVALID_EXTENSION_TYPE',path);return value

def render_value(value):
    if type(value) in (bool,int):return str(value).lower()
    return json.dumps(','.join(value) if type(value) is list else value,ensure_ascii=False)

def split(text, section):
    """Move target-only fields into an explicit, presence-aware sidecar.

    Exact original bytes are retained for audit/reconstruction. The daed view
    differs only by the removed spans, all of which remain in this record.
    """
    need(section in SECTIONS, 'INVALID_SECTION', '$')
    specs = extension_specs(section); target = MODELS['target']['models'][SECTIONS[section]]
    entries = {key: {'present': False} for key in sorted(specs)}
    removed = []; spans = statements(text, section)
    for key, start, end, kind in spans:
        need(key in target, 'UNSUPPORTED_TARGET_FIELD', section+'.'+key)
        need(not (section=='global' and key=='so_mark_from_dae_set'), 'INTERNAL_METADATA_NOT_CONFIG_FIELD', section+'.'+key)
        if key in specs:
            need(kind == ':', 'INVALID_EXTENSION_TYPE', section+'.'+key)
            value = scalar(text[start:end].split(':', 1)[1], specs[key], section+'.'+key)
            entries[key] = {'present': True, 'value': value}
            removed.append((start, end))
    view = text
    for start, end in reversed(removed): view = view[:start] + view[end:]
    return view, {'schemaVersion': 1, 'section': section, 'sourceText': text,
                  'sourceSha256': sha(text), 'daedViewSha256': sha(view),
                  'explicitSourceFields': [s[0] for s in spans], 'fields': entries}

def validate_record(record, section):
    need(isinstance(record, dict) and set(record) == {'schemaVersion','section','sourceText','sourceSha256','daedViewSha256','explicitSourceFields','fields'}, 'INVALID_EXTENSION_RECORD', section)
    need(record['schemaVersion'] == 1 and record['section'] == section, 'INVALID_EXTENSION_RECORD', section)
    need(isinstance(record['sourceText'], str) and sha(record['sourceText']) == record['sourceSha256'], 'EXTENSION_INTEGRITY_FAILED', section)
    view, original = split(record['sourceText'], section)
    need(original == record, 'EXTENSION_INTEGRITY_FAILED', section)
    return view

def merge(daed_text, record):
    """Merge a freshly collected daed document; extensions cannot shadow fields."""
    section = record['section']; validate_record(record, section)
    known_view, found = split(daed_text, section)
    need(all(not x['present'] for x in found['fields'].values()), 'EXTENSION_OWNERSHIP_CONFLICT', section)
    clean = masked(known_view); end = clean.rfind('}')
    additions = []
    for key, entry in sorted(record['fields'].items()):
        if entry['present']:
            value = entry['value']; rendered = render_value(value)
            additions.append('  '+key+': '+rendered+'\n')
    return known_view[:end].rstrip()+'\n'+''.join(additions)+known_view[end:]
