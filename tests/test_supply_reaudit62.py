import unittest
from copy import deepcopy

from civsim.diplomacy61 import fork61, start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.supply62 import audit62, start62, step62


class PublicReauditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geography = regionalize(generate_world(0))
        cls.records = {}
        for arm in ('A','B'):
            sim = start62(deepcopy(cls.geography))
            for year in range(1,6):
                row = step62(sim,year,arm)
                for category,stage in (('private',row['domestic']),('relief',row['government']['relief'])):
                    if any(s['legs'] for s in stage['shipments']):
                        cls.records.setdefault((arm,category),row)

    def test_domestic_cart_path_and_fee_reconstructed_from_geography(self):
        for arm in ('A','B'):
            for category in ('private','relief'):
                source=self.records[arm,category]
                audit62(source,geography=self.geography)
                for field,value in (('tile_path',[999999]),('distance',10000),('leg_fee',0)):
                    damaged=deepcopy(source)
                    stage=damaged['domestic'] if category=='private' else damaged['government']['relief']
                    s=next(s for s in stage['shipments'] if s['legs'])
                    if field=='leg_fee':
                        s['legs'][0]['cost_food']=value
                    else:
                        s[field]=value
                    with self.subTest(arm=arm,stage=category,field=field),self.assertRaises(ValueError):
                        audit62(damaged,geography=self.geography)

    def test_control_accepts_only_ordinary_capped_old_records(self):
        for mode in 'ABCDEF':
            row=step61(start61(deepcopy(self.geography)),1,mode)
            if mode=='F':
                audit62(row,geography=self.geography)
            else:
                with self.subTest(mode=mode),self.assertRaises(ValueError): audit62(row,geography=self.geography)
        _,changed=fork61(start61(deepcopy(self.geography)),1,'E',capped=True)
        self.assertEqual(changed['diplomacy']['phase61']['arm'],'F')
        with self.assertRaises(ValueError): audit62(changed,geography=self.geography)
