import unittest

from training.common import (
    build_marked_text,
    choose_accept_threshold,
    choose_reject_threshold,
    relation_compatible,
    stable_split,
)


class TestTrainingCommon(unittest.TestCase):
    def test_relation_compatibility_groups(self):
        self.assertTrue(relation_compatible("sua_doi", "sua_doi_bo_sung"))
        self.assertTrue(relation_compatible("huong_dan", "quy_dinh_chi_tiet"))
        self.assertFalse(relation_compatible("bai_bo", "thay_the"))

    def test_document_split_is_stable(self):
        self.assertEqual(stable_split("10/2025/TT-BTC"), stable_split("10/2025/TT-BTC"))

    def test_marked_text_marks_action_and_reference(self):
        content = "Bãi bỏ Nghị định 10/2023/NĐ-CP."
        action = "Bãi bỏ"
        reference = "Nghị định 10/2023/NĐ-CP"
        record = {
            "so_hieu": "1/2025/TT-BTC",
            "title": "Test",
            "content": content,
            "parent_content": "",
            "grandparent_content": "",
            "action_span": [content.index(action), content.index(action) + len(action)],
            "reference_span": [
                content.index(reference),
                content.index(reference) + len(reference),
            ],
            "action_text": action,
            "proposed_relation": "bai_bo",
            "features": {},
        }
        text = build_marked_text(record)
        self.assertIn("[ACT]Bãi bỏ[/ACT]", text)
        self.assertIn("[REF]Nghị định 10/2023/NĐ-CP[/REF]", text)

    def test_thresholds_abstain_when_sample_is_too_small(self):
        accept = choose_accept_threshold([0.9, 0.8], [1, 1], 0.95, min_count=10)
        reject = choose_reject_threshold([0.1, 0.2], [0, 0], 0.95, min_count=10)
        self.assertGreater(accept["threshold"], 1.0)
        self.assertLess(reject["threshold"], 0.0)


if __name__ == "__main__":
    unittest.main()
