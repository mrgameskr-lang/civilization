import unittest
from collections import Counter, defaultdict

from experiments.election_diagnostics5d import (
    CARETAKER, MUTUAL, Opening, VARIANTS, _attribute, _trajectory, allocate, choose_leader,
)
from experiments.election_feedback5d import _worker_settings
from civsim import competition, competition_rules
from civsim.fiscal_policy import decide
from tests.test_competition_rules import fixture, single_issue
from tests.test_political_rules import goods


class ElectionDiagnosticTests(unittest.TestCase):
    def test_economic_worker_uses_matching_audit_settings_and_restores_reference(self):
        original = competition_rules._preference
        with _worker_settings(next(v for v in VARIANTS if v.name=="term2")):
            self.assertEqual((competition.TERM,competition_rules.TERM),(2,2))
        with _worker_settings(next(v for v in VARIANTS if v.name=="seats5")):
            self.assertEqual((competition.SEATS,competition_rules.SEATS),(5,5))
        with _worker_settings(next(v for v in VARIANTS if v.name=="exchange_platform")):
            self.assertEqual(competition_rules.PLATFORMS["mutualists"]["road"],4)
        with _worker_settings(next(v for v in VARIANTS if v.name=="no_performance")):
            self.assertEqual(competition_rules._preference({"signals":dict.fromkeys(("relief","road","soil","reserve","defer"),0)},
                                                          "mutualists")[1],0)
        self.assertIs(competition_rules._preference,original)
        self.assertEqual((competition.TERM,competition.SEATS,competition_rules.PLATFORMS["mutualists"]["road"]),(4,21,1))

    def test_indivisible_seats_ties_and_no_turnout(self):
        self.assertEqual(allocate((40,30,30,0),5),(2,2,1,0))
        self.assertEqual(allocate((1,1,1,0),21),(7,7,7,0))
        self.assertEqual(choose_leader((1,1,1,0),(7,7,7,0),2),2)
        self.assertEqual(choose_leader((0,0,0,0),(0,0,0,0),3),3)

    def test_same_voters_remove_retrospective_adjustment_and_change_one_platform(self):
        w,_ = fixture()
        states = single_issue(w,"reserve")
        plan = decide(0,w.regions,[],{r.id:goods(10) for r in w.regions},{},{},"integrated")
        region = Opening(states,plan)
        old = VARIANTS[0]
        changed = next(v for v in VARIANTS if v.name=="exchange_platform")
        self.assertEqual(region.ballot(old,CARETAKER)[0][MUTUAL],200_000)
        self.assertEqual(region.ballot(changed,CARETAKER)[0][MUTUAL],0)
        for s in states.values():
            g = s["groups"]["consumer"]
            g["support"]=0
        region = Opening(states,plan)
        actual=region.ballot(old,MUTUAL)
        count=defaultdict(Counter)
        _attribute(count,region,actual,MUTUAL)
        self.assertEqual((count["all"]["participation"],count["all"]["signal_only_mutual"],
                          count["all"]["actual_mutual"]),(200_000,200_000,0))

    def test_reference_reconstructs_actual_decisions_and_treatment_calendar(self):
        r = _trajectory((0,9))
        world = r["variants"]
        self.assertEqual(world["reference"]["changed_policy_from_observed"],0)
        self.assertEqual(world["reference"]["changed_government_from_observed"],0)
        self.assertEqual([world[v]["elections"] for v in ("reference","term2","term8")],[16,32,8])
        for v in VARIANTS:
            c = world[v.name]
            self.assertEqual(c["country_years"],72)
            self.assertEqual(sum(c[k] for k in c if k.startswith("awarded_")),(c["elections"]-c["zero"])*v.seats)
