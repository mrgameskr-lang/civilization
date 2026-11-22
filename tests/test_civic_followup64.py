import json
import subprocess
import sys
import unittest

from civsim.civic_followup64 import run
from civsim.civic_observer63 import run as original


class FollowupInterfaceTests(unittest.TestCase):
    def test_command_names_the_schema_and_the_absent_register(self):
        command = [sys.executable,"-B","-m","civsim.civic_followup64","--seed","0","--years","1"]
        output = subprocess.check_output(command)
        self.assertEqual(json.loads(output),{"schema":"civil-pledges/1","seed":0,"year":1,
                                              "consult":True,"pledges_enabled":False,"pledges":None})

    def test_disabled_uses_the_original_register_in_both_modes(self):
        for consult,mode in ((True,"consult"),(False,"observe")):
            with self.subTest(mode=mode):
                for old, new in zip(original(0,2,mode),run(0,2,consult=consult),strict=True):
                    self.assertEqual(old,new[:2])
                    self.assertIsNone(new[2])

    def test_enabling_promises_only_adds_a_civil_register(self):
        for old,new in zip(original(0,4,"consult"),run(0,4,pledges=True),strict=True):
            self.assertEqual(old,new[:2])
            self.assertEqual(set(new[2]),set(new[1]))
            self.assertTrue(all(row["year"]==new[0]["year"] for row in new[2].values()))

    def test_no_consultation_still_preserves_all_pairs(self):
        for _,civic,pledges in run(0,2,consult=False,pledges=True):
            self.assertEqual(set(pledges),set(civic))
            self.assertTrue(all(not row["consult"] for row in civic.values()))

    def test_invalid_flags_or_horizon_do_not_run(self):
        for args in (dict(pledges=1),dict(consult=None)):
            with self.assertRaises(ValueError):
                list(run(0,1,**args))
        with self.assertRaises(ValueError):
            list(run(0,-1))
        self.assertEqual(list(run(0,0)),[])
