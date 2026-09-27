"""Value-free semantic change summaries; credentials never reach the browser."""
from bridge_m1.common import canonical,digest
# Only fixed schema field names are displayed. Dynamic keys remain fingerprints.
SAFE_KEYS=set("metadata configs dnss routings groups subscriptions nodes global dns routing string selected id name fields records present value disable_thp auto_sniff_punt bpf_conn_state_map_size optimistic_stale_reply_ttl schemaVersion extensions".split())
from bridge_m1.collect import EXPECTED_GLOBAL
SAFE_KEYS.update(EXPECTED_GLOBAL)

def summary(before,after):
    changes=[]
    def walk(left,right,path):
        if type(left) is type(right) and left==right:return
        if type(left) is dict and type(right) is dict:
            # Object keys can be user-controlled IDs. Report their hash, not text.
            for key in sorted(set(left)|set(right)):
                part=key if key in SAFE_KEYS else 'key-sha256-'+digest(key.encode())[:16]
                location=path+'/'+part
                if key not in left:record('added',location,None,right[key])
                elif key not in right:record('removed',location,left[key],None)
                else:walk(left[key],right[key],location)
        elif type(left) is list and type(right) is list:
            # Array order is significant, including routing and fixed(n) membership.
            for index in range(max(len(left),len(right))):
                location=path+'/'+str(index)
                if index>=len(left):record('added',location,None,right[index])
                elif index>=len(right):record('removed',location,left[index],None)
                else:walk(left[index],right[index],location)
        else:record('changed',path,left,right)
    def record(kind,path,left,right):
        changes.append({'kind':kind,'fieldPath':path,'beforeSha256':None if kind=='added' else digest(canonical(left)),'afterSha256':None if kind=='removed' else digest(canonical(right))})
    walk(before,after,'$')
    return {'changed':bool(changes),'changeCount':len(changes),'changes':changes,'valuesDisclosed':False,'arrayOrderPreserved':True}
