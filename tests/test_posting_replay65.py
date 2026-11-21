import unittest

from experiments.posting_replay65 import baseline, check_seed


class PostingCompatibilityTests(unittest.TestCase):
    def test_a_reconstructs_the_three_historical_streams(self):
        refs, _ = baseline()
        self.assertEqual(set(refs), set(range(40)))
        expected = refs[0][50]
        result = check_seed((0, {50: expected}))
        self.assertEqual(result, [{"seed": 0, "year": 50, **expected}])

    def test_a_forged_historical_digest_is_rejected(self):
        wrong = dict.fromkeys(("economic_years_sha256", "civic_years_sha256", "register_sha256"), "0"*64)
        with self.assertRaisesRegex(ValueError, "seed 0, year 1"):
            check_seed((0, {1: wrong}))
