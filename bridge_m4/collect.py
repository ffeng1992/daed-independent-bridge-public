"""M4 complete GraphQL snapshots; preserve ordered membership arrays."""
import copy
import time
from bridge_m1.collect import envelope, unique, EXPECTED_GLOBAL, SCHEMA
from bridge_m1.common import require, fail, canonical, digest, Rejected

def collect(reader, *, page_size=50, attempts=3, budget=60):
    require(1 <= page_size <= 200 and 1 <= attempts <= 3 and 0 < budget <= 60, 'LIMIT_INVALID')
    started = time.monotonic()
    def request(operation, variables):
        require(time.monotonic()-started < budget, 'TIMEOUT')
        result = envelope(reader(operation,variables))
        require(time.monotonic()-started < budget, 'TIMEOUT')
        return result
    def once():
        caps = request('GlobalCapabilities',{})
        require(set(caps)=={'__type'} and isinstance(caps['__type'],dict) and set(caps['__type'])=={'fields'}, 'SCHEMA_DRIFT')
        fields=caps['__type']['fields']
        require(isinstance(fields,list) and all(isinstance(f,dict) and set(f)=={'name'} for f in fields), 'SCHEMA_DRIFT')
        require(len(fields)==len(EXPECTED_GLOBAL) and {f['name'] for f in fields}==EXPECTED_GLOBAL, 'SCHEMA_DRIFT')
        data=request('SnapshotMetadata',{})
        require(set(data)=={'configs','dnss','routings','groups','subscriptions'}, 'SCHEMA_DRIFT')
        for kind,items in data.items():unique(items,kind)
        pages=[]; nodes=[]; ids=set()
        for sid in [None]+sorted(x['id'] for x in data['subscriptions']):
            after=None; cursors=set(); total=None; count=0
            for index in range(50):
                response=request('NodePage',{'subscriptionId':sid,'first':page_size,'after':after})
                require(set(response)=={'nodes'} and isinstance(response['nodes'],dict), 'FORMAT_ERROR')
                page=response['nodes']
                require(set(page)=={'totalCount','edges','pageInfo'}, 'FORMAT_ERROR')
                require(type(page['totalCount']) is int and 0 <= page['totalCount'] <= 10000,'NODE_LIMIT')
                if total is None:total=page['totalCount']
                require(total==page['totalCount'],'SOURCE_CHANGED')
                edges=page['edges']; seen=unique(edges,'node');info=page['pageInfo']
                require(isinstance(info,dict) and set(info)=={'startCursor','endCursor','hasNextPage'} and type(info['hasNextPage']) is bool,'FORMAT_ERROR')
                require(not ids & seen,'ID_CONFLICT');ids |= seen
                count+=len(edges)
                require(len(edges)<=page_size and count<=total,'PAGINATION_INVALID')
                require(bool(edges) or (index==0 and total==0),'PAGE_MISSING')
                require(info['startCursor']==(edges[0]['id'] if edges else None) and info['endCursor']==(edges[-1]['id'] if edges else None),'CURSOR_INVALID')
                for node in edges:require(node['subscriptionID']==sid,'NODE_OWNERSHIP_INVALID')
                nodes.extend(edges);pages.append({'subscriptionId':sid,'response':{'data':response}})
                if not info['hasNextPage']:
                    require(count==total,'PAGE_MISSING');break
                end=info['endCursor'];require(isinstance(end,str) and end and end not in cursors,'CURSOR_LOOP');cursors.add(end);after=end
            else:fail('PAGE_LIMIT')
        raw={'schemaVersion':1,'synthetic':False,'consistency':{'stable':False,'transactional':False},'metadata':{'data':data},'nodePages':pages}
        require(not list(SCHEMA.iter_errors(raw)),'SCHEMA_DRIFT')
        ordered=copy.deepcopy(data)
        for kind in ordered:ordered[kind].sort(key=lambda x:x['id'])
        # Only top-level collections are sets. fixed(n) membership order matters.
        return {'schemaVersion':1,'synthetic':False,'metadata':ordered,'nodes':sorted(nodes,key=lambda x:x['id'])},len(pages)
    for attempt in range(attempts):
        try:
            left,lp=once();right,rp=once()
        except Rejected as exc:
            if exc.diagnostic['reasonCode']=='SOURCE_CHANGED':continue
            raise
        lh=digest(canonical(left));rh=digest(canonical(right))
        if lh==rh:return right,{'method':'two-complete-normalized-fingerprints','beforeSha256':lh,'afterSha256':rh,'attempts':attempt+1,'pages':[lp,rp],'transactional':False}
    fail('SOURCE_CHANGED')
