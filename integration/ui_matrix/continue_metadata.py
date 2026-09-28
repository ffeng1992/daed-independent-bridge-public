"""Remaining metadata controls against the same isolated official backend.

This does not rerun signup/password/lifecycle acceptance or claim that metadata
is a DAE option. Every change is restored through the official API.
"""
import json
import time
from pathlib import Path

from bridge_m4.collect import collect
from integration.ui_matrix.continue_global import Matrix
from scripts.release_setup import need


class Metadata(Matrix):
    def __init__(self):
        super().__init__()
        self.path = Path('/evidence/metadata-continuation.json')
        self.results = json.loads(self.path.read_text()) if self.path.exists() else []

    def check(self, ident, action):
        if any(row['id'] == ident and row.get('restored') for row in self.results):
            return
        row = {'id': ident, 'result': None, 'startedAt': int(time.time())}
        self.results.append(row)
        try:
            row['evidence'] = action()
            row['result'] = 'RUNTIME_PASS'
        except Exception as exc:
            row.update(result='FAIL', errorType=type(exc).__name__,
                       reason=str(exc).replace(self.token, '[REDACTED]'))
        finally:
            # Metadata has no permission to leave a changed configuration source.
            restored, proof = collect(self.reader)
            need(restored == self.source, 'METADATA_SOURCE_NOT_RESTORED')
            row.update(restored=True, sourceProof=proof)
            self.path.write_text(json.dumps(self.results, indent=2) + '\n')
            print(ident + ': ' + row['result'], flush=True)

    def account(self, field, value):
        from bridge_m1.collect import HTTPReader
        from integration.packaging.onboarding import PASSWORD

        def login(username):
            self.token = self.api('query($u:String!,$p:String!){token(username:$u,password:$p)}',
                                  {'u': username, 'p': PASSWORD})['token']
            need(type(self.token) is str and bool(self.token), 'RENAMED_LOGIN_FAILED')
            self.reader = HTTPReader('http://127.0.0.1:2024/graphql', self.token)

        before = self.api('{user{username name avatar}}')['user']
        mutation = 'update' + field[0].upper() + field[1:]
        nullable = '' if field != 'username' else '!'
        query = 'mutation($v:String' + nullable + '){' + mutation + '(' + field + ':$v)}'
        try:
            self.api(query, {'v': value})
            # Official tokens bind the username. A rename requires a new login
            # before either reading the account or restoring its original name.
            if field == 'username':
                login(value)
            after = self.api('{user{username name avatar}}')['user']
            need(after[field] == value, 'ACCOUNT_VALUE_CHANGED')
            need(all(after[k] == before[k] for k in before if k != field), 'ACCOUNT_ADJACENT_CHANGED')
            if field == 'username':
                need(after['username'] == value, 'RENAMED_LOGIN_IDENTITY_FAILED')
            return {'field': field, 'readbackMatches': True, 'unrelatedFieldsUnchanged': True}
        finally:
            self.api(query, {'v': before[field]})
            if field == 'username':
                login(before[field])
            need(self.api('{user{username name avatar}}')['user'] == before, 'ACCOUNT_NOT_RESTORED')

    def rename(self, kind, collection):
        original = next(row for row in self.source['metadata'][collection] if row['selected'])
        name = 'Matrix name \u6d4b\u8bd5'
        query = 'mutation($id:ID!,$n:String!){rename' + kind + '(id:$id,name:$n)}'
        try:
            self.api(query, {'id': original['id'], 'n': name})
            source, proof = collect(self.reader)
            changed = next(row for row in source['metadata'][collection] if row['id'] == original['id'])
            need(changed == dict(original, name=name), 'RENAME_CHANGED_CONTENT')
            return {'collection': collection, 'nameReadback': name, 'contentUnchanged': True,
                    'doubleSnapshot': proof}
        finally:
            self.api(query, {'id': original['id'], 'n': original['name']})

    def general(self):
        result = self.api('{general{dae{running modified version} interfaces(up:true){name ifindex ip}}}')['general']
        need(result['dae'] == {'running': True, 'modified': False, 'version': 'v2.1.1'}, 'GENERAL_IDENTITY')
        need(any(row['name'] == 'lan0' for row in result['interfaces']), 'GENERAL_INTERFACES_MISSING')
        return result


def main():
    need(Path('/evidence/baseline-ready').is_file(), 'VM_BASELINE_NOT_READY')
    need(Path('/evidence/nodes-complete').is_file(), 'PREVIOUS_BATCH_NOT_COMPLETE')
    need(Path('/sys/class/net/lan0').is_dir(), 'VM_LAN_MISSING')
    matrix = Metadata()
    matrix.check('general.interfaces-and-independent-identity', matrix.general)
    for field, value in [('name', 'Matrix \u7528\u6237'), ('avatar', 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS1cAAAAASUVORK5CYII='),
                         ('username', 'matrix-renamed')]:
        matrix.check('account.' + field, lambda f=field, v=value: matrix.account(f, v))
    for kind, collection in [('Config', 'configs'), ('Dns', 'dnss'), ('Routing', 'routings')]:
        matrix.check(collection + '.rename', lambda k=kind, c=collection: matrix.rename(k, c))


if __name__ == '__main__':
    main()
