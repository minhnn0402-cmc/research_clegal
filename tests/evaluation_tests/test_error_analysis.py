import unittest

from evaluation.error_analysis import summarize_errors


class TestErrorAnalysis(unittest.TestCase):
    def test_summarize_errors_buckets_counts_and_samples(self) -> None:
        rows = [
            {
                "clause_type": "khoan",
                "content": "Bãi bỏ điểm đ khoản 2 Điều 5 Luật Đất đai.",
                "tp": [{"relation": "dan_chieu", "reference": "Luật Đất đai"}],
                "fp": [{"relation": "dan_chieu", "reference": "Nghị định số 12/2024/NĐ-CP"}],
                "fn": [{"relation": "ngung_hieu_luc", "reference": "Thông tư số 01/2024/TT-BTP"}],
            }
        ]

        summary = summarize_errors(rows, sample_limit=2)

        self.assertEqual(summary["overall"], {"tp": 1, "fp": 1, "fn": 1})
        self.assertEqual(summary["by_relation"]["dan_chieu"]["tp"], 1)
        self.assertEqual(summary["by_relation"]["dan_chieu"]["fp"], 1)
        self.assertEqual(summary["by_relation"]["ngung_hieu_luc"]["fn"], 1)
        self.assertEqual(summary["by_clause_type"]["khoan"], {"tp": 1, "fp": 1, "fn": 1})
        self.assertEqual(
            summary["samples"]["by_relation"]["dan_chieu"]["fp"][0]["reference"],
            "Nghị định số 12/2024/NĐ-CP",
        )
        self.assertEqual(
            summary["samples"]["by_relation"]["dan_chieu"]["fp"][0]["content"],
            "Bãi bỏ điểm đ khoản 2 Điều 5 Luật Đất đai.",
        )
        self.assertEqual(
            summary["samples"]["by_clause_type"]["khoan"]["fn"][0]["relation"],
            "ngung_hieu_luc",
        )
        self.assertEqual(
            summary["samples"]["by_clause_type"]["khoan"]["fn"][0]["reference"],
            "Thông tư số 01/2024/TT-BTP",
        )


if __name__ == "__main__":
    unittest.main()
