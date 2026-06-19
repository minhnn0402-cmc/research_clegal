"""Unit tests for the load-bearing pure functions of the harness.

Run: PYTHONPATH=. python -m unittest experiment.test_harness
"""

import unittest

from experiment.architectures.base import dedupe
from experiment.llm_client import extract_json, strip_thinking
from experiment.stats import mcnemar_test, wilson_interval


class TestWilson(unittest.TestCase):
    def test_perfect_precision_small_n_has_wide_lower_bound(self):
        ci = wilson_interval(10, 10)
        self.assertEqual(ci.point, 1.0)
        self.assertLess(ci.low, 1.0)        # not falsely certain
        self.assertAlmostEqual(ci.high, 1.0, places=4)

    def test_half(self):
        ci = wilson_interval(50, 100)
        self.assertAlmostEqual(ci.point, 0.5, places=3)
        self.assertLess(ci.low, 0.5)
        self.assertGreater(ci.high, 0.5)

    def test_zero_total(self):
        ci = wilson_interval(0, 0)
        self.assertEqual((ci.point, ci.low, ci.high), (0.0, 0.0, 0.0))


class TestMcNemar(unittest.TestCase):
    def test_no_discordance_is_not_significant(self):
        chi2, p = mcnemar_test(0, 0)
        self.assertEqual(chi2, 0.0)
        self.assertEqual(p, 1.0)

    def test_strong_one_sided_difference_is_significant(self):
        # System B fixes 40 items, breaks 2 -> clearly significant.
        chi2, p = mcnemar_test(2, 40)
        self.assertLess(p, 0.001)

    def test_symmetric_difference_not_significant(self):
        _, p = mcnemar_test(20, 20)
        self.assertGreater(p, 0.05)


class TestExtractJson(unittest.TestCase):
    def test_strips_think_block(self):
        self.assertEqual(strip_thinking("<think>reasoning</think>  answer"), "answer")

    def test_plain_object(self):
        self.assertEqual(extract_json('{"verdict":"NO"}'), {"verdict": "NO"})

    def test_object_after_thinking(self):
        raw = '<think>long reasoning...</think>\n{"verdict":"YES"}'
        self.assertEqual(extract_json(raw), {"verdict": "YES"})

    def test_fenced_json(self):
        raw = 'Here:\n```json\n{"relations": []}\n```\n'
        self.assertEqual(extract_json(raw), {"relations": []})

    def test_trailing_junk_after_object(self):
        self.assertEqual(extract_json('{"verdict":"NO"} trailing text'), {"verdict": "NO"})

    def test_unparseable_returns_none(self):
        self.assertIsNone(extract_json("no json at all"))


class TestDedupe(unittest.TestCase):
    def test_drops_exact_duplicates_and_empty_refs(self):
        items = [
            {"relation": "can_cu", "reference": "Luật A"},
            {"relation": "can_cu", "reference": "Luật A"},
            {"relation": "can_cu", "reference": ""},
            {"relation": "dan_chieu", "reference": "Luật A"},
        ]
        out = dedupe(items)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], {"relation": "can_cu", "reference": "Luật A"})


if __name__ == "__main__":
    unittest.main()
