import copy
import unittest
from tests.m4.test_convert import example
from bridge_m4.convert import normalize,emit,cursor
from bridge_m4.extensions import split,CompatibilityError

class EmptyGroupTests(unittest.TestCase):
    def fixture(self):
        s,e=example()
        g=copy.deepcopy(s['metadata']['groups'][0])
        g.update(id=cursor('99'),name='empty_fixture',nodes=[],subscriptions=[])
        s['metadata']['groups'].append(g)
        _,record=split('group {\n check_interval: "45s"\n}\n','group')
        e['records']['group']={'99':record}
        return s,e,g

    def test_unreferenced_preserved_not_emitted(self):
        s,e,g=self.fixture();before=copy.deepcopy((s,e));ir=normalize(s,e)
        self.assertNotIn(b'empty_fixture {',emit(ir))
        self.assertEqual((s,e),before)
        self.assertEqual(ir.source,s);self.assertEqual(ir.extensions,e)
        self.assertEqual(next(x for x in ir.groups if x['name']==g['name'])['members'],[])

    def test_selected_reference_fails_with_group_name(self):
        s,e,g=self.fixture();r=next(x for x in s['metadata']['routings'] if x['selected'])
        r['referenceGroups'].append(g['name'])
        with self.assertRaises(CompatibilityError) as raised:normalize(s,e)
        self.assertEqual(raised.exception.code,'EMPTY_REFERENCED_GROUP')
        self.assertEqual(raised.exception.path,'groups.empty_fixture.nodes')

    def test_populate_empty_delete(self):
        s,e,g=self.fixture();g['nodes']=[{'id':s['nodes'][0]['id']}]
        self.assertIn(b'empty_fixture {',emit(normalize(s,e)))
        g['nodes']=[];self.assertNotIn(b'empty_fixture {',emit(normalize(s,e)))
        s['metadata']['groups'].remove(g)
        self.assertNotIn(b'empty_fixture {',emit(normalize(s,e)))

    def test_unselected_routing_reference_does_not_block(self):
        s,e,g=self.fixture();r=copy.deepcopy(s['metadata']['routings'][0])
        r.update(id=cursor('99'),selected=False,referenceGroups=[g['name']])
        s['metadata']['routings'].append(r)
        self.assertNotIn(b'empty_fixture {',emit(normalize(s,e)))
