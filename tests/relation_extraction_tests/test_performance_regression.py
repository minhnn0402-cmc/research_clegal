import json
import os
import unittest
import sys
from pathlib import Path

# Ensure project root is in sys.path for imports
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import the refactored evaluation pipeline
from evaluation.evaluate import evaluate_pipeline


BASELINE_PATH = _PROJECT_ROOT / "evaluation" / "datasets" / "approved_relation_baseline.json"


def _load_approved_baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _assert_not_below_baseline(current: float, baseline: float, label: str, errors: list[str]):
    if current < (baseline - 0.001):
        errors.append(
            f"Regression in {label}: Current F1 {current:.3f} < approved baseline {baseline:.3f}"
        )


class TestPerformanceRegression(unittest.TestCase):
    """
    Performance Regression Testing.
    Ensures F1 scores do not decrease when code is updated.
    """

    @classmethod
    def setUpClass(cls):
        # Paths to dataset and temporary report
        cls.dataset_path = _PROJECT_ROOT / "evaluation" / "datasets" / "relation_pairs.csv"
        cls.output_report = _PROJECT_ROOT / "evaluation" / "reports" / "regression_test.json"
        cls.approved_baseline = _load_approved_baseline()
        cls.TARGET_OVERALL_F1 = cls.approved_baseline["metadata"]["target_overall_f1"]

    def test_f1_score_thresholds(self):
        """Verify F1 scores do not regress below the approved baseline."""
        print(f"\nRunning full evaluation pipeline on: {self.dataset_path.name}...")
        
        results = evaluate_pipeline(
            dataset_path=str(self.dataset_path),
            output_path=str(self.output_report)
        )
        
        current_stats = results.get("by_relation_type", {})
        overall_f1 = results.get("overall", {}).get("f1", 0.0)
        approved_overall_f1 = self.approved_baseline["overall"]["f1"]
        approved_relation_f1 = self.approved_baseline["by_relation_type"]
        
        errors = []
        print("\n--- F1 PERFORMANCE CHECK RESULTS ---")
        print(
            f"{'overall':<20}: Current {overall_f1:.3f} | "
            f"Approved baseline {approved_overall_f1:.3f} | "
            f"Target {self.TARGET_OVERALL_F1:.3f} -> "
            f"{'PASS' if overall_f1 >= (approved_overall_f1 - 0.001) else 'FAIL'}"
        )
        _assert_not_below_baseline(
            current=overall_f1,
            baseline=approved_overall_f1,
            label="overall benchmark",
            errors=errors,
        )

        for relation, benchmark_f1 in approved_relation_f1.items():
            # Extract f1 from results, default to 0.0 if not found
            current_f1 = current_stats.get(relation, {}).get("f1", 0.0)
            
            # Allow for minor rounding differences
            status = "PASS" if current_f1 >= (benchmark_f1 - 0.001) else "FAIL"
            print(f"{relation:<20}: Current {current_f1:.3f} | Approved baseline {benchmark_f1:.3f} -> {status}")
            _assert_not_below_baseline(
                current=current_f1,
                baseline=benchmark_f1,
                label=f"'{relation}'",
                errors=errors,
            )

        if overall_f1 < self.TARGET_OVERALL_F1:
            print(
                f"Target gap remains: Current overall F1 {overall_f1:.3f} < "
                f"target {self.TARGET_OVERALL_F1:.3f}"
            )
            if os.getenv("CLS_ENFORCE_TARGET_097") == "1":
                errors.append(
                    f"Target gate failed: Current overall F1 {overall_f1:.3f} < "
                    f"target {self.TARGET_OVERALL_F1:.3f}"
                )
        
        if errors:
            self.fail(f"\nDetected performance regression in {len(errors)} relation types:\n" + "\n".join(errors))

if __name__ == "__main__":
    unittest.main()
