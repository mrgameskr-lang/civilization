from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.phase6b import run_study as run_public
from experiments.phase6b2 import run_study
from tests.test_phase6b_study import rows


class ResidentServiceStudyTests(unittest.TestCase):
    def test_six_contrasts_register_and_separate_paths(self):
        with TemporaryDirectory() as temp:
            base,out=Path(temp,"public"),Path(temp,"service")
            options=dict(sample="dev",seeds=1,horizons=(1,3),workers=1)
            run_public(base,**options)
            run_study(out,reference=base,**options)
            runs=rows(out/"runs.csv")
            paired=rows(out/"paired.csv")
            self.assertEqual({r["contrast"] for r in paired},{"B-A","C-B","D-C","D-B","C-A","D-A"})
            self.assertEqual(len(runs),4)
            pop={(r["arm"],r["year"]):int(r["closing_population"]) for r in rows(base/"runs.csv")+runs}
            for r in paired:
                a,b=r["contrast"].split("-")
                self.assertEqual(int(r["closing_population"]),pop[a,r["year"]]-pop[b,r["year"]])
            national=rows(out/"country-years.csv.gz")
            for r in national:
                self.assertEqual(int(r["working_age"]),sum(int(r[k]) for k in (
                    "withheld_workers","project_workers","production_workers","construction_workers","soil_workers","service_serving")))
                self.assertEqual(int(r["service_serving"]),int(r["service_available"])+int(r["service_unavailable"]))
                self.assertEqual(int(r["service_serving"])-int(r["service_deaths"])-int(r["service_emigrants"]),int(r["closing_service_roster"]))
            meta=run_study(Path(temp,"repeat"),reference=base,verify=out,**options)
            self.assertEqual((meta["replayed_checkpoints"],meta["b1_reference_checkpoints"]),(4,4))
