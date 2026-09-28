/* Read-only AST inventory of the pinned original frontend. No frontend build. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function inventory(ts, root, tree, lock, contracts) {
  if (tree.sha !== lock.webFrontend.sourceCommit) throw Error('SOURCE_COMMIT_MISMATCH');
  const blobs = new Map(tree.tree.filter(x => x.type === 'blob').map(x => [x.path, x.sha]));
  const records = { sourceCommit: tree.sha, sourceFiles: {}, forms: [], controls: [],
    graphqlDocuments: [], graphqlTypes: {}, protocols: [], globalMapping: [], hookCalls: [], links: [] };
  const digest = (algorithm, bytes) => crypto.createHash(algorithm).update(bytes).digest('hex');
  for (const [name, oid] of [...blobs].sort()) {
    const bytes = fs.readFileSync(path.join(root, name));
    if (digest('sha1', Buffer.concat([Buffer.from(`blob ${bytes.length}\0`), bytes])) !== oid)
      throw Error('SOURCE_BLOB_MISMATCH:' + name);
    if (!name.startsWith('apps/web/src/') || !/\.tsx?$/.test(name) ||
        name.includes('/mocks/') || name.includes('/components/ui/')) continue;
    records.sourceFiles[name] = digest('sha256', bytes);
    const sf = ts.createSourceFile(name, bytes.toString(), ts.ScriptTarget.Latest, true,
      name.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    if (sf.parseDiagnostics.length) throw Error('SOURCE_PARSE_FAILED:' + name);
    const loc = n => ({file:name, line:sf.getLineAndCharacterOfPosition(n.getStart(sf)).line+1});
    const literal = n => n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) ? n.text : null;
    const property = n => n && (ts.isIdentifier(n) || ts.isStringLiteral(n)) ? n.text : null;
    function visit(n) {
      const text=literal(n);
      if (!name.includes('/schemas/gql/') && text !== null && ['query ', 'query\n', 'mutation ', 'mutation\n', 'subscription '].some(prefix => text.trimStart().startsWith(prefix))) {
        let owner=n.parent;
        while(owner && !ts.isFunctionDeclaration(owner)) owner=owner.parent;
        records.graphqlDocuments.push({...loc(n), owner:owner?.name?.text||null, document:text});
      }
      if (ts.isCallExpression(n)) {
        const target = n.expression.getText(sf);
        if (/^use\w+(Mutation|Query)$/.test(target) && !name.includes('/apis/'))
          records.hookCalls.push({...loc(n), hook:target});
        if ((target === 'z.object' || target.endsWith('.extend')) && n.arguments[0] && ts.isObjectLiteralExpression(n.arguments[0])) {
          let ancestor=n.parent;
          while (ancestor && !ts.isVariableDeclaration(ancestor)) ancestor=ancestor.parent;
          records.forms.push({...loc(n), name:ancestor ? ancestor.name.getText(sf) : null,
            fields:n.arguments[0].properties.map(p => ({name:property(p.name), expression:p.getText(sf)}))});
        }
      }
      if (ts.isTypeAliasDeclaration(n) && ts.isTypeLiteralNode(n.type) && name.endsWith('/schemas/gql/graphql.ts'))
        records.graphqlTypes[n.name.text] = n.type.members.map(p => ({name:property(p.name), type:p.type?.getText(sf)}));
      if (ts.isVariableDeclaration(n) && n.initializer && ts.isObjectLiteralExpression(n.initializer)) {
        const props = new Map(n.initializer.properties.filter(ts.isPropertyAssignment).map(p => [property(p.name),p.initializer]));
        if (props.has('generateLink') && props.has('id')) records.protocols.push({...loc(n),
          id:literal(props.get('id')), schema:props.get('schema')?.getText(sf),
          component:props.get('FormComponent')?.getText(sf) || props.get('component')?.getText(sf) || null,
          fields: props.get('fields') && ts.isArrayLiteralExpression(props.get('fields')) ? props.get('fields').elements.map(field => {
            if (!ts.isObjectLiteralExpression(field)) throw Error('DYNAMIC_PROTOCOL_FIELD:' + name);
            const p = new Map(field.properties.filter(ts.isPropertyAssignment).map(x => [property(x.name),x.initializer]));
            return {name:literal(p.get('name')),type:literal(p.get('type')),options:p.get('options')?.getText(sf)||null};
          }) : []});
      }
      if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) {
        const links=n.attributes.properties.filter(p => ts.isJsxAttribute(p) && ['href','to'].includes(p.name.getText(sf)));
        if(links.length) records.links.push({...loc(n),component:n.tagName.getText(sf),
          destinations:links.map(p=>({attribute:p.name.getText(sf),expression:p.initializer?.getText(sf)||null}))});
        const events = n.attributes.properties.filter(p => ts.isJsxAttribute(p) && p.name.getText(sf).startsWith('on'));
        if (events.length) {
          const fields=new Set();
          function bindings(x) {
            if (ts.isCallExpression(x) && ['setValue','register'].includes(x.expression.getText(sf)) && literal(x.arguments[0]) !== null)
              fields.add(literal(x.arguments[0]));
            if (ts.isCallExpression(x) && x.expression.getText(sf)==='handleChange' && literal(x.arguments[1]) !== null)
              fields.add(literal(x.arguments[1]));
            if (ts.isCallExpression(x) && ['setFormData','setPasswordFormData'].includes(x.expression.getText(sf)) && x.arguments[0] && ts.isObjectLiteralExpression(x.arguments[0]))
              x.arguments[0].properties.filter(ts.isPropertyAssignment).forEach(p => fields.add(property(p.name)));
            ts.forEachChild(x,bindings);
          }
          events.forEach(bindings);
          records.controls.push({...loc(n), component:n.tagName.getText(sf), fields:[...fields].sort(),
            events:events.map(p => ({event:p.name.getText(sf),expression:p.initializer?.getText(sf)||null}))});
        }
      }
      ts.forEachChild(n,visit);
    }
    visit(sf);
  }
  const config=records.forms.find(x => x.file.endsWith('/ConfigFormModal.tsx') && x.name==='schema');
  if (!config) throw Error('CONFIG_SCHEMA_MISSING');
  const renames={logLevelNumber:'logLevel',checkIntervalSeconds:'checkInterval',checkToleranceMS:'checkTolerance',sniffingTimeoutMS:'sniffingTimeout'};
  for (const field of config.fields) {
    const graphql=renames[field.name]||field.name;
    const mapping=contracts.fields.find(x => x.graphql===graphql);
    const visible=records.controls.filter(x => x.file===config.file && x.fields.includes(field.name));
    records.globalMapping.push({control:field.name,graphql,dae:mapping?.dae||null,
      category:field.name==='name'?'DAED_CONFIGURATION_METADATA':'DATA_PLANE_SETTING',
      visibleBindings:visible.map(x => ({line:x.line,component:x.component})),
      contract:field.name==='name'?'METADATA':mapping?'PRESENT':'FAIL',result:'UNTESTED'});
  }
  // This is an extraction index, not a claim that all callbacks are distinct
  // user controls or that static mappings passed runtime acceptance.
  records.coverageStatus='SOURCE_INDEX_REQUIRES_LOGICAL_CONTROL_RECONCILIATION';
  records.protocolFields=records.protocols.map(p => ({protocol:p.id,
    fields:[...new Set([...p.fields.map(x => x.name), ...records.controls.filter(c => p.component && c.file.endsWith('/'+p.component+'.tsx')).flatMap(c => c.fields)])].sort()}));
  return records;
}

if (require.main === module) {
  const [compiler, source, treePath, repo] = process.argv.slice(2);
  if (!repo) throw Error('Usage: node inventory.cjs TYPESCRIPT_JS SOURCE TREE_JSON REPOSITORY');
  const result=inventory(require(path.resolve(compiler)),source,JSON.parse(fs.readFileSync(treePath)),
    JSON.parse(fs.readFileSync(path.join(repo,'upstream.lock.json'))),
    JSON.parse(fs.readFileSync(path.join(repo,'contracts/global-fields.json'))));
  process.stdout.write(JSON.stringify(result,null,2)+'\n');
}
module.exports={inventory};
