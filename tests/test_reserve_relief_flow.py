from copy import deepcopy
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.reserve_relief_flow import COLUMNS, PROVENANCE, _extra, _stage, aggregate, region_rows
from experiments.ordinary_relief_residual import _matched_rows, explain_residual, from_annual, positive_years, study_report


def archived():
    path = Path(__file__).resolve().parents[1] / 'examples/token-upkeep-v1/case/move_on.jsonl.gz'
    with gzip.open(path, 'rt', encoding='utf8') as stream:
        return json.loads(next(stream))


class ReserveReliefFlowTests(unittest.TestCase):
    def test_ordinary_receipts_custody_and_regional_ascription(self):
        record = archived()
        original = deepcopy(record)
        packed = region_rows(record)
        rows = [dict(zip(COLUMNS, x, strict=True)) for x in packed]
        self.assertEqual(len(rows), 32)
        self.assertEqual(set(COLUMNS), set(PROVENANCE))
        self.assertEqual(original, record)
        output = aggregate(packed)
        world = output['world']
        self.assertEqual(world['food_unmet'], sum(r['consumption']['food_unmet'] for r in record['regions']))
        self.assertEqual(world['ordinary_received_food'], record['government']['relief']['delivered'])
        self.assertEqual(world['ordinary_road_open'], sum(e['capacity'] for e in record['government']['relief']['roads']))
        self.assertEqual(world['ordinary_road_open'], sum(r['ordinary_road_open'] for r in rows)//2)
        self.assertEqual(world['emergency_received_food'], 0)
        self.assertEqual(world['deaths'], sum(r['demography']['deaths'] for r in record['regions']))
        self.assertEqual(world['food_unmet'], sum(world[k] for k in ('unmet_with_local_stock',
                         'unmet_with_other_domestic_stock_only', 'unmet_without_domestic_stock')))
        for row in rows:
            self.assertEqual(row['emergency_active_regions'], 0)
            self.assertEqual(row['ordinary_received_food'], row['ordinary_local_received']+row['ordinary_remote_received'])
            self.assertEqual(row['pre_extra_public'], row['post_ordinary_public'])

    def test_changed_ordinary_approval_and_road_receipts_rejected(self):
        record = archived()
        edge = record['government']['relief']['roads'][0]
        edge['remaining'] = edge['capacity']+1
        with self.assertRaises(ValueError):
            region_rows(record)

    def test_missing_regions_and_wrong_year_rejected(self):
        rows = region_rows(archived())
        with self.assertRaises(ValueError):
            aggregate(rows + [rows[0]])
        rows[-1][COLUMNS.index('year')] += 1
        with self.assertRaises(ValueError):
            aggregate(rows)

    def test_real_civilian_emergency_receipts_local_then_remote(self):
        from civsim.emergency_relief import execute_emergency_relief
        from tests.test_emergency_relief import setup

        args = setup(vault=(10, 0, 5), budgets=7, ordinary=2)
        args[-1][2] = 9
        extra, _ = execute_emergency_relief(*args, width=3)
        rows = {i:{**dict.fromkeys(COLUMNS, 0), 'region':i, 'owner':0, 'population':160,
                   'household_public_issue_food': args[-1][i]} for i in range(3)}
        original = deepcopy(extra)
        nodes = _stage(rows, args[4], 'ordinary')
        _extra(rows, nodes, extra)
        target = rows[2]
        self.assertEqual(target['pre_extra_gap_after_reserved'], 4)
        self.assertEqual((target['ordinary_received_food'],target['emergency_requested'],
                          target['emergency_approved'],target['emergency_received_food']), (2,4,4,4))
        self.assertEqual((target['emergency_local_received'],target['emergency_remote_received']), (3,1))
        self.assertEqual(rows[0]['emergency_freight_food'],2)
        self.assertEqual(extra,original)
        bad = deepcopy(extra)
        bad['applications'][0]['unfilled']['stock'] += 1
        clean = {i:{**dict.fromkeys(COLUMNS,0), 'region':i, 'owner':0, 'population':160,
                    'household_public_issue_food':args[-1][i]} for i in range(3)}
        old = _stage(clean,args[4],'ordinary')
        with self.assertRaisesRegex(ValueError,'emergency application'):
            _extra(clean,old,bad)

    def test_ordinary_residual_separates_observed_bounds_from_unknown(self):
        stocks = {0:0,1:3,2:2}
        # The 3-unit store can dispatch at least one via the open link. How much
        # would reach residents remains unknown. The other store is disconnected.
        result = explain_residual(10,8,0,stocks,[(0,1,1,1),(1,2,0,1)])
        self.assertEqual(result, {'spent_budget':2, 'insufficient_domestic_stock':3,
            'disconnected_stock':2,'cannot_fund_one_ration_and_freight':0,'unknown':3})
        result = explain_residual(2,2,0,{0:0,1:3},[(0,1,2,150)])
        self.assertEqual(result['cannot_fund_one_ration_and_freight'],2)
        self.assertEqual(explain_residual(2,2,0,{0:0,1:3},None)['unknown'],2)
        raw = archived()
        indexed = {r[COLUMNS.index('region')]:r[COLUMNS.index('ordinary_gap_not_dispatched')] for r in region_rows(raw)}
        for row in from_annual(raw):
            self.assertEqual(row['residual'],indexed[row['target']])
            self.assertEqual(row['residual'],sum(row['at_stage_close'].values()))

    def test_sparse_schedule_and_tamper_check(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'sample.gz'
            with gzip.open(path,'wt',encoding='utf8') as stream:
                stream.write(json.dumps({'seed':4,'arm':'C','columns':['region','year','ordinary_gap_not_dispatched','owner']})+'\n')
                for year in range(1,4):
                    stream.write(json.dumps([[i,year,2 if (i,year)==(7,2) else 0,i//4] for i in range(32)])+'\n')
            years,_ = positive_years(path,4,total_years=3)
            self.assertEqual(years,{2:{7:(1,2)}})
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                positive_years(path,4)
            with self.assertRaisesRegex(ValueError,'differs'):
                _matched_rows(4,2,years[2],[])
        parts=explain_residual(2,1,7,{7:1},[])
        item={'target':7,'owner':1,'residual':2,'food_budget_left':1,'complete_road_distances':True,'at_stage_close':parts}
        self.assertEqual(_matched_rows(4,2,years[2],[item])[0][:7],[4,2,1,7,2,1,True])
        item['at_stage_close']['unknown']+=1
        with self.assertRaisesRegex(ValueError,'reconcile'):
            _matched_rows(4,2,years[2],[item])

    def test_zero_residual_opens_no_simulation_or_process_pool(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'execution.json').write_text(json.dumps({'seeds':list(range(40)),'arms':['C']}),encoding='utf8')
            with patch('experiments.ordinary_relief_residual.positive_years',return_value=({},'a'*64)), \
                 patch('experiments.ordinary_relief_residual.ProcessPoolExecutor',side_effect=AssertionError('unneeded replay')):
                rec=study_report(root)
            self.assertEqual((rec['replayed_world_years'],rec['matched_positive_region_years'],rec['workers']),(0,0,0))
