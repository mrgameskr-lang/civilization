import unittest
from copy import deepcopy

from civsim.civic_followup64 import run as pr18
from civsim.posting_engine65 import run, audit_households, fork_affiliation
from civsim.storage import canonical_line


class AdministrativeEconomyTests(unittest.TestCase):
    def test_historical_control_uses_the_complete_pr18_records(self):
        for consult,pledges in ((True,False),(False,True)):
            historical=pr18(0,2,consult=consult,pledges=pledges)
            actual=run(0,2,policy="A",consult=consult,pledges=pledges)
            for expected,observed in zip(historical,actual,strict=True):
                self.assertEqual(observed,expected)

    def test_nonnegative_household_meals_and_census_follow_the_prior_year(self):
        records=[r[0] for r in pr18(0,2)]
        audit_households(records[0])
        audit_households(records[1],previous=records[0])
        damaged=deepcopy(records[1])
        damaged["regions"][0]["consumption"]["food_eaten"]+=1
        with self.assertRaises(ValueError):
            audit_households(damaged,previous=records[0])
        discontinuous=deepcopy(records[0])
        discontinuous["regions"][0]["closing"]["stock"]["food"]+=1
        with self.assertRaises(ValueError):
            audit_households(records[1],previous=discontinuous)

    def test_paper_register_adds_no_residents_supplies_or_costs_to_economy(self):
        baseline=run(0,4,policy="A_fixed")
        optional=run(0,4,policy="B")
        for (old,_,unused),(economy,civic,book) in zip(baseline,optional,strict=True):
            self.assertIsNone(unused)
            self.assertIsNone(civic)
            self.assertIsNotNone(book)
            self.assertEqual(canonical_line(economy),canonical_line(old))
            self.assertEqual(economy["service"]["mode"],"fixed")

    def test_invalid_controls_are_rejected_and_empty_horizons_do_no_work(self):
        for policy in ("A","A_fixed","B"):
            self.assertEqual(list(run(0,0,policy=policy)),[])
        for options in (dict(policy="unknown"),dict(policy="B",pledges=True)):
            with self.assertRaises(ValueError):
                list(run(0,1,**options))

    def test_hold_rejects_unissued_change_without_modifying_frozen_economic_record(self):
        economy,_,_=next(run(0,1,policy="A_fixed"))
        original=canonical_line(economy)
        opening={}
        with self.assertRaises(ValueError):
            fork_affiliation(opening,economy,hold=(0,0,1))
        self.assertEqual(canonical_line(economy),original)
        self.assertEqual(opening,{})

    def test_actual_paper_change_can_be_held_on_one_identical_paid_year(self):
        from civsim.postings65 import advance_postings
        fixed=run(0,2,policy="A_fixed")
        first,_,_=next(fixed)
        _,opening=advance_postings({},first["service"],year=1)
        second,_,_=next(fixed)
        old_economy=canonical_line(second)
        old_opening=opening.copy()
        invoice=second["service"]["moves"][0]
        target=(invoice["home"],invoice["home"],invoice["station"])
        normal,held=fork_affiliation(opening,second,hold=target)
        self.assertNotEqual(normal["closing"],held["closing"])
        self.assertEqual(sum(row["held"] for row in held["assignments"]),1)
        self.assertEqual(opening,old_opening)
        self.assertEqual(canonical_line(second),old_economy)
