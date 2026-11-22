import json
import unittest
from hashlib import sha256

from civsim.model import generate_world
from civsim.peace62 import start62, step62
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.repeat_posting_register65 import FIELDS, ROOT, YEARS, match, replay


class IndependentRegisterReplayTests(unittest.TestCase):
    def test_live_digests_match_the_stored_register_and_separate_fixed_economy(self):
        sample=ROOT/"examples/phase6c1-m1/seed0-eight-years.jsonl"
        checks=replay(0,(1,2))
        historical=start62(regionalize(generate_world(0)))
        economy,affiliations=sha256(),sha256()
        with sample.open("rb") as f:
            header=json.loads(next(f))
            self.assertEqual((header["seed"],header["policy"]),(0,"B"))
            for year,row in enumerate(checks,1):
                raw=json.loads(next(f))
                ledger=canonical_line(step62(historical,year,"C"))
                self.assertEqual(raw["economic_sha256"],sha256(ledger).hexdigest())
                economy.update(ledger)
                affiliations.update(canonical_line(raw["register"]))
                self.assertEqual((row["year"],row[FIELDS[0]],row[FIELDS[1]]),
                                 (year,economy.hexdigest(),affiliations.hexdigest()))

    def test_a_mismatch_in_either_stream_or_sample_coverage_is_rejected(self):
        official=[{"seed":s,"year":y,FIELDS[0]:"a"*64,FIELDS[1]:"b"*64}
                  for s in range(20) for y in YEARS]
        match(list(reversed(official)),official,0)
        for f in FIELDS:
            damaged=[{**official[0],f:"0"*64},*official[1:]]
            with self.subTest(f=f),self.assertRaisesRegex(ValueError,"checkpoint differs"):
                match(damaged,official,0)
        for malformed in (official[:-1],[*official,official[0]]):
            with self.assertRaises(ValueError):
                match(malformed,official,0)
