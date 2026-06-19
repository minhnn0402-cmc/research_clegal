"""Layer 3: golden regression inventory coverage.

This suite makes sure every handoff edge case is represented in data and has a
clear automation status. It prevents silent loss of cases when the fixture grows.
"""

from __future__ import annotations

import logging
import unittest
from collections import Counter

from tests.graph_regression_tests.helpers import load_cases


logging.disable(logging.INFO)


EXPECTED_EDGE_IDS = {f"EC-{index:02d}" for index in range(1, 31)}
EXPECTED_STATUS_COUNTS = {"active": 30}
EXPECTED_LAYER_COUNTS = {"unit": 15, "resolver": 6, "golden": 5, "integration": 4}
ALLOWED_STATUSES = {"active", "needs_policy", "manual"}
ALLOWED_LAYERS = {"unit", "resolver", "golden", "integration", "manual"}


class TestGoldenRegressionCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()

    def test_all_handoff_edge_cases_are_represented(self) -> None:
        matrix = self.cases["coverage_matrix"]
        actual_ids = {case["id"] for case in matrix if case["id"].startswith("EC-")}
        self.assertEqual(actual_ids, EXPECTED_EDGE_IDS)

    def test_coverage_distribution_is_explicit(self) -> None:
        """Manual/needs_policy cases are tracked inventory, not behavior assertions."""
        matrix = self.cases["coverage_matrix"]
        self.assertEqual(
            dict(Counter(case["status"] for case in matrix)),
            EXPECTED_STATUS_COUNTS,
        )
        self.assertEqual(
            dict(Counter(case["layer"] for case in matrix)),
            EXPECTED_LAYER_COUNTS,
        )

    def test_every_case_has_status_layer_and_priority(self) -> None:
        for case in self.cases["coverage_matrix"]:
            with self.subTest(case_id=case["id"]):
                self.assertIn(case["status"], ALLOWED_STATUSES)
                self.assertIn(case["layer"], ALLOWED_LAYERS)
                self.assertIn(case["priority"], {"P0", "P1", "P2"})
                self.assertTrue(case.get("title"))

    def test_active_cases_point_to_executable_data_bucket(self) -> None:
        executable_buckets = {
            "reference_component_cases",
            "internal_reference_cases",
            "relation_type_cases",
            "relation_extraction_cases",
            "es_resolver_cases",
            "law_dataframe_cases",
            "title_only_policy_cases",
            "build_graph_cases",
            "processor_runtime_cases",
            "runtime_cases",
            "inferred_relation_cases",
            "ui_relation_source_cases",
        }
        bucket_ids = {
            item["id"]
            for bucket in executable_buckets
            for item in self.cases.get(bucket, [])
            if item.get("status") == "active"
        }

        for case in self.cases["coverage_matrix"]:
            if case["status"] != "active":
                continue
            with self.subTest(case_id=case["id"]):
                executable_ids = set(case.get("executable_case_ids", []))
                self.assertTrue(
                    executable_ids,
                    f"{case['id']} is active but has no executable_case_ids",
                )
                self.assertTrue(
                    executable_ids <= bucket_ids,
                    f"{case['id']} points to missing executable cases: {executable_ids - bucket_ids}",
                )

    def test_not_automated_inventory_does_not_duplicate_active_cases(self) -> None:
        active_case_ids = {
            case["id"]
            for case in self.cases["coverage_matrix"]
            if case["status"] == "active"
        }
        tracked_ids = {
            case["id"].split("-", 2)[0] + "-" + case["id"].split("-", 2)[1]
            for case in self.cases.get("tracked_not_automated_cases", [])
        }

        self.assertFalse(
            active_case_ids & tracked_ids,
            f"Manual/needs_policy list duplicates active cases: {active_case_ids & tracked_ids}",
        )


if __name__ == "__main__":
    unittest.main()
