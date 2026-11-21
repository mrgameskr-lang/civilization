import unittest

from civsim import peace62
from tests.test_depot_publication62 import read_forks, read_grid


class PublishedServiceTests(unittest.TestCase):
    def test_direct_enrollment_changes_work_even_when_meals_do_not_change(self):
        cases = read_forks("phase6b2",peace62)
        self.assertEqual(set(cases),{(0,1),(0,3)})
        normal, held = (cases[0,3][k] for k in ("ordinary","held"))
        self.assertEqual((normal["service"]["enrolled"],held["service"]["enrolled"]), (46,0))
        self.assertEqual(normal["eaten_by_region"],held["eaten_by_region"])
        self.assertEqual(normal["produced"]["food"]-held["produced"]["food"],-51)
        self.assertEqual(cases[0,1]["ordinary"]["service"]["available"],0)

    def test_both_service_policies_share_all_opening_worlds_and_preserve_the_cap(self):
        for sample in ("dev","holdout"):
            base = {r["seed"]:r["initial_sha256"] for r in read_grid("phase6b1",sample,"AB")}
            for r in read_grid("phase6b2",sample,"CD"):
                self.assertEqual(r["initial_sha256"],base[r["seed"]])
                self.assertEqual(int(r["aid_budget_overrun"]),0)
