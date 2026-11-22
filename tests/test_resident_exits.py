"""Reconcile recorded resident changes and the registered subset at each home."""
from copy import deepcopy
import unittest

from civsim.resident_exits import audit_resident_exits


def example():
    census = {"id":4,"owner":2,"opening":{"population":100},"closing":{"population":89},
              "demography":{"opening_population":100,"births":7,"deaths":13,"population_before_migration":94,
                            "emigrants":9,"immigrants":4,"closing_population":89}}
    # 50 open - 5 released + 2 entered = 47. Deaths=floor(47*13/100)=6.
    # Emigrants=floor(41*9/94)=3. Both are already counted in the residents.
    roll = {"id":4,"owner":2,"population":100,"opening_roster":50,"released":5,"enrolled":2,"serving":47,
            "service_deaths":6,"service_emigrants":3,"closing_roster":38}
    return census, roll


class ResidentExitTests(unittest.TestCase):
    def test_each_realized_exit_has_its_own_integer_receipt(self):
        c,r=example()
        inputs=deepcopy((c,r))
        self.assertEqual(audit_resident_exits([c],[r]),[{
            "home":4,"owner":2,"population_open":100,"births":7,"deaths":13,"emigrants":9,"immigrants":4,
            "population_close":89,"roster_open":50,"released":5,"enrolled":2,"serving":47,"roster_deaths":6,
            "roster_emigrants":3,"roster_close":38,
        }])
        self.assertEqual((c,r),inputs)

    def test_unsupported_removal_and_swapped_causes_fail_with_same_closing_total(self):
        c,r=example()
        for changes in [
            {"service_deaths":5,"service_emigrants":4},
            {"service_deaths":7,"closing_roster":37},
            {"service_emigrants":4,"closing_roster":37},
            {"closing_roster":37}, {"serving":46}, {"released":51},
            {"service_deaths":True}, {"population":99}, {"owner":3},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                audit_resident_exits([c],[{**r,**changes}])

    def test_zero_supply_and_incomplete_household_meals_cannot_delete_extra_entries(self):
        c,r=example()
        base=audit_resident_exits([c],[r])
        c["consumption"]={"food_need":100,"food_eaten":0,"food_unmet":100}
        c["closing"]["stock"]={"food":0,"ore":0,"tools":0}
        r["ration_food"]=0
        self.assertEqual(audit_resident_exits([c],[r]),base)
        with self.assertRaises(ValueError):
            audit_resident_exits([c],[{**r,"closing_roster":0}])

    def test_zero_denominators_and_new_residents_do_not_create_register_entries(self):
        c={"id":1,"owner":0,"opening":{"population":0},"closing":{"population":5},
           "demography":dict(opening_population=0,births=0,deaths=0,population_before_migration=0,
                             emigrants=0,immigrants=5,closing_population=5)}
        r=dict(id=1,owner=0,population=0,opening_roster=0,released=0,enrolled=0,serving=0,
               service_deaths=0,service_emigrants=0,closing_roster=0)
        row,=audit_resident_exits([c],[r])
        self.assertEqual((row["population_close"],row["roster_close"]),(5,0))
        c["opening"]["population"]=1
        c["demography"].update(opening_population=1,deaths=1)
        r.update(population=1,opening_roster=1,serving=1,service_deaths=1)
        row,=audit_resident_exits([c],[r])
        self.assertEqual((row["roster_deaths"],row["roster_emigrants"],row["roster_close"]),(1,0,0))

    def test_coverage_identity_and_census_tampering(self):
        c,r=example()
        for cs,rs in (([c,c],[r]),([c],[r,r]),([c],[]),([],[r])):
            with self.assertRaises(ValueError): audit_resident_exits(cs,rs)
        for key in ("births","deaths","emigrants","immigrants","population_before_migration","closing_population"):
            altered=deepcopy(c)
            altered["demography"][key]+=1
            with self.subTest(key=key),self.assertRaises(ValueError):
                audit_resident_exits([altered],[r])
        for side in ("opening","closing"):
            altered=deepcopy(c)
            altered[side]["owner"]=True
            with self.assertRaises(ValueError): audit_resident_exits([altered],[r])

    def test_complete_fixed_economic_year_and_real_source_tampering(self):
        from civsim.posting_engine65 import run

        record,_,_=next(run(0,1,policy="A_fixed"))
        census,roll=record["regions"],record["service"]["regions"]
        checked=audit_resident_exits(census,roll)
        self.assertEqual(len(checked),len(census))
        self.assertEqual(checked,audit_resident_exits(list(reversed(census)),list(reversed(roll))))
        self.assertEqual(sum(x["population_close"] for x in checked),
                         sum(x["closing"]["population"] for x in record["countries"]))
        changed=deepcopy(roll)
        r=next(row for row in changed if row["service_deaths"]>0)
        r["service_deaths"]-=1
        r["service_emigrants"]+=1
        with self.assertRaises(ValueError): audit_resident_exits(census,changed)
