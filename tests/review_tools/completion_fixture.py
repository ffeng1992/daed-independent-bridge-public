"""Synthetic report fixture only. Does not prove matrix/runtime acceptance."""
from integration.ui_matrix import completion as c, completion_producers as p

def publish_baseline_and_nodes(source,evidence,binding,folder):
    for stage,name in [('baseline','baseline-ready'),('continue_nodes','nodes-complete')]:
        if (folder/name).exists():continue
        rows=[{'id':i,'result':'CONFIG_PASS','restored':True} for i in p.stage_cases(stage)]
        c.atomic_once(folder,p.REPORTS[stage],rows)
        summary=p.execution_summary(stage,folder)
        c.atomic_once(folder,'executed-'+stage+'.json',dict(summary,scope=binding,stage=stage,
            returncode=0,completed=True,reports=[c.reference(folder,p.REPORTS[stage])]))
        p.produce(name,root=source,evidence=evidence)
