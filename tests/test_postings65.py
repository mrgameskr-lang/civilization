"""Conservation of nominal affiliations as an overlay on a fixed peacetime register."""
from copy import deepcopy
from types import SimpleNamespace
import json
import unittest

from civsim.postings65 import advance_postings, audit_postings, start_postings


def fixed(owners=(0,0,0), old=(0,0,0), intake=(10,0,0), out=(0,0,0),
          deaths=(0,0,0), emigrants=(0,0,0), invoices=()):
    rows = []
    for i, owner in enumerate(owners):
        serving = old[i]-out[i]+intake[i]
        rows.append(dict(id=i, owner=owner, population=200, opening_roster=old[i],
                         enrolled=intake[i], released=out[i], serving=serving,
                         service_deaths=deaths[i], service_emigrants=emigrants[i],
                         closing_roster=serving-deaths[i]-emigrants[i]))
    trips = [dict(home=h, station=p, people=n, owner=owners[h],
                  road_load=2*n, travel_food=(2*n*d+99)//100, distance=d)
             for h,p,n,d in invoices]
    return dict(mode='fixed',stage='closed',regions=rows,moves=trips)


def book(rows):
    return {(r['home'],r['post']):r['count'] for r in rows}


class PostingBookTests(unittest.TestCase):
    def test_closed_invoice_supports_only_nominal_affiliation_and_is_never_spent_twice(self):
        source=fixed(invoices=[(0,1,6,4),(0,2,3,2)])
        original=deepcopy(source)
        opening=start_postings([SimpleNamespace(id=i) for i in range(3)])
        trace,closing=advance_postings(opening,source,year=1)
        self.assertEqual(closing,{(0,0):1,(0,1):6,(0,2):3})
        self.assertEqual(source,original)
        self.assertEqual(opening,{})
        self.assertEqual([r['assigned'] for r in trace['assignments']],[6,3])
        self.assertEqual(book(trace['enrolled']),{(0,0):10})
        self.assertEqual(book(trace['during']),closing)
        audit_postings(json.loads(json.dumps(trace)),source)

    def test_postings_persist_when_home_ration_expires_or_no_new_invoice_exists(self):
        s1=fixed(invoices=[(0,2,6,2)])
        t1,closing=advance_postings({},s1,year=1)
        s2=fixed(old=(10,0,0), intake=(0,0,0))
        s2['regions'][0]['ration_food']=0
        t2,b2=advance_postings(closing,s2,year=2)
        self.assertEqual(b2,closing)
        self.assertEqual(t2['assignments'],[])
        audit_postings(t2,s2,previous=t1)

    def test_carry_cannot_be_reassigned_away_from_post_to_fill_a_new_invoice(self):
        s=fixed(old=(10,0,0),intake=(0,0,0),invoices=[(0,2,7,1)])
        opening={(0,0):2,(0,1):8}
        t,b=advance_postings(opening,s,year=9)
        self.assertEqual(b,{(0,1):8,(0,2):2})
        pick,=t['assignments']
        self.assertEqual((pick['invoice_people'],pick['eligible'],pick['assigned']), (7,2,2))
        self.assertEqual(opening,{(0,0):2,(0,1):8})

    def test_release_and_vital_exits_are_apportioned_once_to_home_cohorts(self):
        s=fixed(old=(10,0,0),intake=(0,0,0),out=(2,0,0),deaths=(2,0,0),emigrants=(2,0,0))
        t,b=advance_postings({(0,1):5,(0,2):5},s,year=2)
        self.assertEqual(b,{(0,1):2,(0,2):2})
        for k in ('released','deaths','emigrants'):
            self.assertEqual(book(t[k]),{(0,1):1,(0,2):1})
        audit_postings(t,s)

    def test_hold_mentions_one_invoice_only_and_retains_home_address(self):
        s=fixed(invoices=[(0,1,4,1),(0,2,2,2)])
        normal,_=advance_postings({},s,year=1)
        alt,b=advance_postings({},s,year=1,hold=(0,0,1))
        self.assertEqual((b, alt['assignments'][0]['held']),({(0,0):8,(0,2):2},True))
        self.assertEqual(alt['assignments'][1]['assigned'],normal['assignments'][1]['assigned'])
        with self.assertRaises(ValueError):
            advance_postings({},s,year=1,hold=(0,0,0))
        with self.assertRaises(ValueError):
            advance_postings({},s,year=1,hold=(1,1,2))

    def test_only_fixed_closed_domestic_source_and_true_opening_are_allowed(self):
        for corrupt in ('mode','stage','foreign','fee','load','carry','duplicate','zero',
                        'overdrawn','missing-home','wrong-year','roster'):
            with self.subTest(corrupt=corrupt):
                s=fixed(invoices=[(0,1,3,1)])
                old={}
                if corrupt=='mode': s['mode']='adaptive'
                if corrupt=='stage': s['stage']='planned'
                if corrupt=='foreign': s['regions'][1]['owner']=1
                if corrupt=='fee': s['moves'][0]['travel_food']=0
                if corrupt=='load': s['moves'][0]['road_load']=3
                if corrupt=='carry': old={(0,1):1}
                if corrupt=='duplicate': s['moves']*=2
                if corrupt=='zero': old={(0,0):0}
                if corrupt=='overdrawn': s['moves'][0].update(people=11,road_load=22)
                if corrupt=='missing-home': s['regions'][1]['id']=0
                if corrupt=='wrong-year': old={(0,1):2}; s['regions'][0].update(opening_roster=2,serving=12,closing_roster=12)
                if corrupt=='roster': s['regions'][0]['closing_roster']+=1
                with self.assertRaises(ValueError):
                    advance_postings(old,s,year=1)

    def test_tamper_duplicate_census_receipts_skipped_year_and_rewritten_carry(self):
        s1=fixed(invoices=[(0,1,3,1)])
        t1,b1=advance_postings({},s1,year=1)
        s2=fixed(old=(10,0,0), intake=(0,0,0))
        t2,_=advance_postings(b1,s2,year=2)
        for corrupt in ('year','carry','ledger','duplicate','invoice'):
            with self.subTest(corrupt=corrupt):
                prior,t=deepcopy(t1),deepcopy(t2)
                if corrupt=='year': t['year']+=1
                if corrupt=='carry': prior['closing'][0]['count']-=1
                if corrupt=='ledger': t['during'][0]['count']+=1
                if corrupt=='duplicate': t['closing'].append(t['closing'][0])
                if corrupt=='invoice': t['assignments']=t1['assignments']
                with self.assertRaises(ValueError):
                    audit_postings(t,s2,previous=prior)
