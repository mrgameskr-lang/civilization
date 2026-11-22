from copy import deepcopy
import csv
import gzip
import json
from pathlib import Path
import unittest

from civsim.civic_diplomacy63 import CivicDiplomacy, audit_civic_pair


def direction(s,t,year=1,**changes):
    row=dict(seed=0,arm='D',year=year,source=s,target=t,trade_food=0,trade_ore=0,trade_tools=0,
             trade_value=0,trade_denied=0,migrants=0,exit_denied=0,entry_denied=0,breach=0,
             closing_tension=100,closing_trust=550)
    return {**row,**changes}


def issue(year=1):
    return [direction(0,1,year,trade_food=10,trade_value=80,trade_denied=10),
            direction(1,0,year,trade_tools=2,trade_value=24)]


class CivicDiplomacyTests(unittest.TestCase):
    def start(self,consult=True):
        w=CivicDiplomacy(0,nations=3,consult=consult)
        self.assertEqual(set(w.advance(1)),{(0,1),(0,2),(1,2)})
        return w

    def test_lag_independent_consent_and_no_change_to_observed_events(self):
        w=self.start()
        disabled=w.fork(consult=False)
        rows=issue()
        frozen=deepcopy(rows)
        enabled=w.advance(2,reversed(rows))[0,1]
        held=disabled.advance(2,rows)[0,1]
        self.assertEqual(rows,frozen)
        self.assertEqual((enabled['event'],enabled['observed'],enabled['evidence_year']),('start',True,1))
        self.assertEqual(enabled['evidence'],frozen)
        self.assertEqual((enabled['proposal']['requester'],enabled['proposal']['responder'],
                          enabled['proposal']['decision']),(1,0,'accepted'))
        self.assertEqual(held['proposal']['decision'],'defer')
        self.assertTrue(enabled['closing']['consulting'])
        self.assertFalse(held['closing']['consulting'])
        self.assertEqual((enabled['closing']['active'],enabled['signal']),(held['closing']['active'],held['signal']))
        self.assertEqual(enabled['event'],held['event'])

    def test_refusal_and_quiet_pair_even_when_trust_is_low(self):
        w=self.start()
        stress=[{**r,'closing_trust':250} for r in issue()]
        neutral=[direction(0,2,closing_trust=100,closing_tension=800),direction(2,0,closing_trust=100,closing_tension=800)]
        t=w.advance(2,stress+neutral)
        self.assertEqual(t[0,1]['proposal']['decision'],'declined')
        self.assertEqual(t[0,2]['event'],'none')
        self.assertFalse(t[0,2]['closing']['active'])
        self.assertFalse(t[0,1]['closing']['consulting'])

    def test_missing_and_partial_evidence_freezes_existing_dispute_then_two_clean_years(self):
        w=self.start()
        opened=w.advance(2,issue())[0,1]
        quiet=w.advance(3,[direction(0,1,2),direction(1,0,2)])[0,1]
        self.assertEqual((quiet['event'],quiet['closing']['quiet_years']),('continue',1))
        row=direction(0,1,3,exit_denied=8)
        partial=w.advance(4,[row])[0,1]
        self.assertEqual((partial['event'],partial['observed'],partial['evidence']),('unobserved',False,[row]))
        self.assertEqual(partial['closing'],quiet['closing'])
        blank=w.advance(5)[0,1]
        self.assertEqual((blank['evidence_year'],blank['evidence']),(None,[]))
        self.assertEqual(blank['closing'],partial['closing'])
        ended=w.advance(6,[direction(0,1,5),direction(1,0,5)])[0,1]
        self.assertEqual((ended['event'],ended['closing']['active']),('ease',False))
        for prev,nextrow in zip([opened,quiet,partial,blank],[quiet,partial,blank,ended]):
            audit_civic_pair(json.loads(json.dumps(nextrow)),previous_row=prev)

    def test_invalid_clock_bad_source_or_inconsistent_bilateral_record_rolls_back(self):
        w=self.start()
        for rows in ([direction(0,1,2)], [direction(0,1),direction(0,1)], [direction(0,1,seed=1)],
                     [direction(0,1,arm='C')], [direction(0,1,trade_denied=-1)], [direction(0,0)],
                     [direction(0,3)],[direction(0,1),direction(1,0,closing_trust=555)]):
            with self.subTest(rows=rows),self.assertRaises(ValueError): w.advance(2,rows)
            self.assertEqual(w.year,1)
        with self.assertRaises(ValueError): w.advance(3,issue())
        record=w.advance(2,issue())[0,1]
        with self.assertRaises(ValueError): w.advance(2,issue())
        bad=deepcopy(record)
        bad['proposal']['decision']='declined'
        with self.assertRaises(ValueError): audit_civic_pair(bad)
        foreign=deepcopy(record)
        foreign['a']=1
        with self.assertRaises(ValueError): audit_civic_pair(record,previous_row=foreign)

    def test_individual_denial_rate_floor_and_prior_agreement_failure(self):
        w=self.start()
        small=[direction(0,1,trade_food=20,trade_value=80,trade_denied=1),
               direction(1,0)]
        self.assertEqual(w.advance(2,small)[0,1]['event'],'none')
        mobility=[direction(0,1,2,migrants=3,entry_denied=1),direction(1,0,2)]
        self.assertEqual(w.advance(3,mobility)[0,1]['event'],'start')
        fresh=self.start()
        agreement=[direction(0,1,trade_food=200,trade_value=800,trade_denied=1,breach=1),direction(1,0)]
        self.assertEqual(fresh.advance(2,agreement)[0,1]['event'],'start')

    def test_csv_strings_and_input_order_are_deterministic(self):
        p=Path(__file__).resolve().parents[1]/'examples/phase6b2/study/dev/foreign-years.csv.gz'
        with gzip.open(p,'rt',encoding='utf8',newline='') as f:
            first=[]
            for r in csv.DictReader(f):
                if r['arm']=='D' and r['seed']=='0':
                    if r['year']!='1': break
                    first.append(r)
        l,r=CivicDiplomacy(0),CivicDiplomacy(0)
        l.advance(1)
        r.advance(1)
        self.assertGreater(len(first),0)
        self.assertEqual(l.advance(2,first),r.advance(2,reversed(first)))
