import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.civic_diplomacy63 import CivicDiplomacy
from civsim.civic_followup64 import run as followup
from civsim.civic_observer63 import run as original
from civsim.storage import canonical_line
from experiments.verify_civic_off64 import PAIRS, ROOT, check_pairs, compare_release, crosscheck_study, extension_line, load_references, publish_receipt


class HistoricalCompatibilityTests(unittest.TestCase):
    def test_all_archived_seeds_checkpoints_and_both_observation_modes(self):
        refs, hashes = load_references()
        self.assertEqual(set(refs), set(range(40)))
        self.assertEqual(sum(len(refs[s]["consult"]) for s in refs), 120)
        self.assertEqual(len(hashes), 5)
        self.assertEqual(refs[0]["consult"][50]["economy"],
                         "a5d465c3ac64c1720fd551ffb9490d8a88b5c8f349f002c254649d6ce512b75b")
        self.assertNotEqual(refs[20]["consult"][100]["civic"], refs[20]["observe"][100]["civic"])

    def test_pair_set_and_timing_must_match_original_civilian_register(self):
        model = CivicDiplomacy(5, consult=True)
        first = model.advance(1)
        check_pairs(5, 1, True, first, None, ())
        second = model.advance(2)
        check_pairs(5, 2, True, second, first, ())
        with self.assertRaises(ValueError):
            check_pairs(5, 2, True, second, first, ({"source": 0, "target": 1},))
        damaged = deepcopy(second)
        damaged[(0, 1)]["opening"]["active"] = True
        with self.assertRaises(ValueError):
            check_pairs(5, 2, True, damaged, first, ())
        damaged.pop((0, 1))
        with self.assertRaises(ValueError):
            check_pairs(5, 2, True, damaged, first, ())

    def test_receipt_refuses_to_overwrite_and_preserves_original(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"nested"/"report.json"
            publish_receipt(path, {"old":True})
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):
                publish_receipt(path, {"new":True})
            self.assertEqual(path.read_bytes(),before)

    def test_disabled_live_entry_returns_exact_previous_economy_and_consultation(self):
        for legacy,extended in zip(original(0,2,"consult"),followup(0,2,consult=True,pledges=False),strict=True):
            old_ledger,old_pairs=legacy
            new_ledger,new_pairs,extra=extended
            self.assertIsNone(extra)
            self.assertEqual(canonical_line(new_ledger),canonical_line(old_ledger))
            self.assertEqual(canonical_line(list(new_pairs.values())),canonical_line(list(old_pairs.values())))

    def test_enabled_archive_bytes_are_in_numeric_pair_order(self):
        rows={p:{"a":p[0],"b":p[1]} for p in reversed(PAIRS)}
        expected=canonical_line({"mode":"consult_on","year":2,"pairs":[{"a":a,"b":b} for a,b in PAIRS]})
        self.assertEqual(extension_line(2,rows),expected)
        rows.pop((0,1))
        with self.assertRaises(ValueError):
            extension_line(2,rows)

    def test_study_comparison_rejects_substituting_an_old_digest_for_enabled_register(self):
        refs,_=load_references()
        point={"year":50,**refs[0]["consult"][50]}
        case={"seed":0,"mode":"consult","pledges":False,"matched":[point]}
        folder=ROOT/"phase6c1-followup"/"pledges"
        self.assertEqual(crosscheck_study([case],folder)["disabled_register_checkpoints"],1)
        case["pledges"]=True
        point["pledge_years_sha256"]=point["civic"]
        with self.assertRaisesRegex(ValueError,"live serialized"):
            crosscheck_study([case],folder)

    def test_repeat_does_not_exclude_a_nested_scientific_change(self):
        with TemporaryDirectory() as tmp:
            first,second,out=(Path(tmp)/name for name in ("first","second","out"))
            publish_receipt(first, {"wall_seconds":1,"paths":[{"matched":[1]}]})
            publish_receipt(second, {"wall_seconds":2,"paths":[{"matched":[2]}]})
            with self.assertRaisesRegex(ValueError,"other than elapsed time"):
                compare_release(first,second,out)
            self.assertFalse(out.exists())
