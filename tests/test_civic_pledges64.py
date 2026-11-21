from copy import deepcopy
import json
import unittest

from civsim.civic_diplomacy63 import CivicDiplomacy
from civsim.civic_pledges64 import CivicPledges, audit_pledge_pair
from tests.test_civic_diplomacy63 import direction


def trade(year,allowed=12,blocked=6,reverse=4):
    return [direction(0,1,year,trade_food=allowed,trade_value=allowed*8,trade_denied=blocked),
            direction(1,0,year,trade_food=reverse,trade_value=reverse*8)]


class CivicPledgeTests(unittest.TestCase):
    def setUp(self):
        self.civic=CivicDiplomacy(0,2,consult=True)
        self.engine=CivicPledges(0,2)
        self.first=self.engine.advance(1,self.civic.advance(1))

    def advance(self,year,observations):
        civic=self.civic.advance(year,observations)
        return civic[0,1],self.engine.advance(year,civic)[0,1]

    def test_two_signatures_same_kind_fixed_year_and_export_actor(self):
        civic,r=self.advance(2,trade(1))
        self.assertEqual(civic['proposal']['decision'],'accepted')
        self.assertEqual(r['agreement']['decision'],'signed')
        self.assertIsNone(r['settlement'])
        terms=r['closing']['pending']
        self.assertEqual((terms['kind'],terms['baseline_year'],terms['signed_year'],terms['economic_year'],
                          terms['due_year']),('trade',1,2,2,3))
        self.assertEqual([p['baseline'] for p in terms['parties']],[6,0])
        self.assertEqual([p['baseline_opportunities'] for p in terms['parties']],[18,4])
        self.assertTrue(all(s['sign'] for s in r['agreement']['signatures']))
        # A caller cannot edit the registered baseline through a returned dictionary.
        terms['parties'][0]['baseline']=200
        _,nextrow=self.advance(3,trade(2,blocked=7))
        self.assertEqual(nextrow['settlement']['parties'][0]['baseline'],6)
        self.assertEqual([s['status'] for s in nextrow['settlement']['parties']],['broken','kept'])

    def test_accepted_consultation_does_not_guarantee_a_pledge(self):
        civic,row=self.advance(2,trade(1,allowed=1,blocked=9))
        self.assertEqual(civic['proposal']['decision'],'accepted')
        self.assertEqual(row['agreement']['decision'],'no_agreement')
        self.assertEqual([s['sign'] for s in row['agreement']['signatures']],[False,True])
        self.assertIsNone(row['closing']['pending'])

    def test_broken_partner_actually_delays_signing_and_unknown_stays_unknown(self):
        _,signed=self.advance(2,trade(1))
        held=self.engine.fork(feedback=False)
        civic,r=self.advance(3,trade(2,blocked=7,reverse=0))
        alt=held.advance(3,[civic])[0,1]
        self.assertEqual(r['opening'],alt['opening'])
        self.assertEqual(r['settlement'],alt['settlement'])
        self.assertEqual([p['status'] for p in r['settlement']['parties']],['broken','unknown'])
        self.assertEqual(r['settlement']['status'],'broken')
        self.assertEqual((r['agreement']['decision'],alt['agreement']['decision']),('defer','signed'))
        self.assertIsNone(r['closing']['pending'])
        self.assertIsNotNone(alt['closing']['pending'])
        audit_pledge_pair(json.loads(json.dumps(r)),civic,signed)

    def test_kept_history_can_enable_a_signature(self):
        self.advance(2,trade(1))
        held=self.engine.fork(feedback=False)
        civic,r=self.advance(3,trade(2,allowed=1,blocked=5))
        self.assertEqual(r['settlement']['status'],'kept')
        self.assertEqual((r['agreement']['decision'],held.advance(3,[civic])[0,1]['agreement']['decision']),
                         ('signed','no_agreement'))

    def test_confirmed_outcome_expires_without_being_replaced_by_a_missing_year(self):
        self.advance(2,trade(1))
        _,bad=self.advance(3,trade(2,blocked=7,reverse=0))
        self.assertEqual(bad['agreement']['decision'],'defer')
        _,gap=self.advance(4,[])
        self.assertEqual(gap['opening']['history'],gap['closing']['history'])
        _,retried=self.advance(5,trade(4,blocked=7,reverse=0))
        sig=retried['agreement']['signatures'][1]
        self.assertEqual((sig['partner_last_known'],sig['partner_known_year'],sig['history_score']),('broken',3,0))
        self.assertEqual(retried['agreement']['decision'],'signed')

    def test_exit_and_entry_obligations_have_different_actors_and_denominators(self):
        for kind in ('exit','entry'):
            with self.subTest(kind=kind):
                c=CivicDiplomacy(0,2,consult=True)
                e=CivicPledges(0,2)
                e.advance(1,c.advance(1))
                d=direction(0,1,1,migrants=2,**{kind+'_denied':2})
                p=e.advance(2,c.advance(2,[d,direction(1,0,1,migrants=3)]))[0,1]['agreement']['terms']
                expected=[2,0] if kind=='exit' else [0,2]
                self.assertEqual((p['kind'],[s['baseline'] for s in p['parties']]),(kind,expected))
                # The same flow has 2 upstream exit denials. They never reach the entry screening stage.
                d=direction(0,1,2,migrants=2,exit_denied=2,entry_denied=3)
                r=e.advance(3,c.advance(3,[d,direction(1,0,2,migrants=3)]))[0,1]
                actor=r['settlement']['parties'][0 if kind=='exit' else 1]
                self.assertEqual(actor['actual_opportunities'],7 if kind=='exit' else 5)

    def test_incomplete_direction_unknown_and_no_terminating_year_leak(self):
        _,prior=self.advance(2,trade(1))
        civic,row=self.advance(3,[direction(0,1,2,migrants=20)])
        self.assertFalse(civic['observed'])
        self.assertEqual(row['settlement']['status'],'unknown')
        known,missing=row['settlement']['parties']
        self.assertEqual((known['actual'],known['reason']),(0,'no_opportunity'))
        self.assertEqual((missing['actual'],missing['reason']),(None,'missing_direction'))
        self.assertIsNone(row['closing']['pending'])
        audit_pledge_pair(row,civic,prior)

    def test_observed_party_can_break_a_due_pledge_despite_missing_opposite_direction(self):
        self.advance(2,trade(1))
        civic,row=self.advance(3,trade(2,blocked=9)[:1])
        self.assertFalse(civic['observed'])
        self.assertEqual([r['status'] for r in row['settlement']['parties']],['broken','unknown'])
        self.assertEqual(row['settlement']['status'],'broken')
        self.assertEqual(row['agreement']['decision'],'none')

    def test_no_agreement_from_declined_deferred_disabled_or_unobserved_record(self):
        enabled=self.engine
        disabled=enabled.fork(enabled=False)
        civic=self.civic.advance(2,[{**d,'closing_trust':300} for d in trade(1)])
        self.assertEqual(civic[0,1]['proposal']['decision'],'declined')
        self.assertIsNone(enabled.advance(2,civic)[0,1]['agreement']['terms'])
        disabled.advance(2,civic)
        accepted=self.civic.advance(3,trade(2))
        self.assertEqual(accepted[0,1]['proposal']['decision'],'accepted')
        self.assertEqual(disabled.advance(3,accepted)[0,1]['agreement']['decision'],'none')
        c=CivicDiplomacy(0,2,consult=False)
        e=CivicPledges(0,2)
        e.advance(1,c.advance(1))
        deferred=c.advance(2,trade(1))
        self.assertEqual(deferred[0,1]['proposal']['decision'],'defer')
        self.assertEqual(e.advance(2,deferred)[0,1]['agreement']['decision'],'none')

    def test_reject_wrong_period_duplicate_false_decision_tampering_and_retry(self):
        valid=self.civic.advance(2,trade(1))
        original=deepcopy(valid)
        damaged=deepcopy(valid)
        damaged[0,1]['proposal']['decision']='declined'
        for year,raw in ((3,valid),(2,[]),(2,list(valid.values())*2),(2,damaged)):
            with self.assertRaises(ValueError): self.engine.advance(year,raw)
            self.assertEqual(self.engine.year,1)
        row=self.engine.advance(2,valid)[0,1]
        self.assertEqual(valid,original)
        with self.assertRaises(ValueError): self.engine.advance(2,valid)
        bad=deepcopy(row)
        bad['closing']['pending']['parties'][0]['baseline']+=1
        with self.assertRaises(ValueError): audit_pledge_pair(bad,valid[0,1],self.first[0,1])
