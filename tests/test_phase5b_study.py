import csv
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.government import fiscal_snapshot, start_government, step_government
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5b import PoliticalMeasures, band, choice_key, run_study


def read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class PoliticsStudyTests(unittest.TestCase):
    def test_bands_and_economic_targets(self):
        self.assertEqual([band(i) for i in (0, 99, 100, 999, 1000)], [0, 0, 100, 900, 900])
        self.assertEqual(choice_key({"action":"road","target_edge":[1,2],"target_region":None}),
                         choice_key({"action":"road","target_edge":(1,2),"target_region":None}))

    def test_people_not_groups_weight_support_and_persistence(self):
        def state(n, support, action, age):
            return dict(members=n,support=support,discontent=1000-support,pressure=50,
                        demand=action,age=age,benefit=12,burden=30)
        m=PoliticalMeasures()
        g={"farm":state(9,900,"soil",3),"industry":state(1,100,"none",0),"consumer":state(0,500,"none",0)}
        counts=m.observe(g,10)
        self.assertEqual(counts["support_x_members"],8200)
        self.assertEqual(counts["persistent_demand_member_years"],9)
        _,hist,demand=m.snapshot({})
        self.assertEqual(sum(r["member_years"] for r in hist if r["index"]=="support"),10)
        soil=next(r for r in demand if r["group"]=="farm" and r["demand"]=="soil")
        self.assertEqual((soil["age_x_members"],soil["max_age"]),(27,3))

    def test_archived_projection_replay_group_weights_and_postings(self):
        with TemporaryDirectory() as tmp:
            out, replay = Path(tmp,"dev"), Path(tmp,"again")
            run_study(out, sample="dev", seeds=1, horizons=(1,3), workers=1)
            rows = read(out/"runs.csv")
            self.assertEqual({(r["arm"],r["year"]) for r in rows},
                             {(a,y) for a in ("off","on") for y in ("1","3")})
            self.assertEqual(len({r["initial_political_sha256"] for r in rows}),1)
            baseline = start_government(regionalize(generate_world(0)))
            world_hash = hashlib.sha256(canonical_line(fiscal_snapshot(baseline))).hexdigest()
            digest = hashlib.sha256()
            for y in range(1,4):
                digest.update(canonical_line(step_government(baseline,y,"integrated")))
            end = next(r for r in rows if r["arm"]=="off" and r["year"]=="3")
            self.assertEqual((end["initial_fiscal_sha256"], end["fiscal_sha256"]), (world_hash,digest.hexdigest()))
            self.assertEqual(int(end["actual_switches"]),0)
            groups = [r for r in read(out/"groups.csv") if r["arm"]=="off" and r["year"]=="3"]
            self.assertEqual(sum(int(r["member_years"]) for r in groups),int(end["food_need"]))
            regions = [r for r in read(out/"regions.csv") if r["arm"]=="off" and r["year"]=="3"]
            for k in ("road_built","soil_projects","relief_food","food_deficit","final_population"):
                self.assertEqual(sum(int(r[k]) for r in regions),int(end[k]))
            hist = [r for r in read(out/"distributions.csv") if r["arm"]=="off" and r["year"]=="3" and r["index"]=="support"]
            self.assertEqual(sum(int(r["member_years"]) for r in hist),int(end["member_years"]))
            with self.assertRaises(FileExistsError):
                run_study(out,sample="dev",seeds=1,horizons=(1,),workers=1)
            meta = run_study(replay,sample="dev",seeds=1,horizons=(1,3),workers=1,verify=out)
            self.assertEqual(meta["replayed_checkpoints"],4)
            self.assertEqual((out/"runs.csv").read_bytes(),(replay/"runs.csv").read_bytes())
