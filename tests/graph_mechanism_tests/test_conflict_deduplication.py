"""Tests for conflicting-relation deduplication in post_processing."""
import unittest

from src.utils.post_processing import _filter_conflicting_relations


def _success_item(relationship: str, target_doc_id: int, target_key=None) -> dict:
    return {
        "relationship": relationship,
        "target_doc_id": target_doc_id,
        "target_key": target_key,
    }


class TestFilterConflictingRelations(unittest.TestCase):

    def test_sua_doi_bo_sung_wins_over_thay_the(self):
        items = [
            _success_item("sua_doi_bo_sung", 100),
            _success_item("thay_the", 100),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("sua_doi_bo_sung", rels)
        self.assertNotIn("thay_the", rels)

    def test_sua_doi_wins_over_bai_bo(self):
        items = [
            _success_item("sua_doi", 200),
            _success_item("bai_bo", 200),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("sua_doi", rels)
        self.assertNotIn("bai_bo", rels)

    def test_bo_sung_wins_over_huy_bo(self):
        items = [
            _success_item("bo_sung", 300),
            _success_item("huy_bo", 300),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("bo_sung", rels)
        self.assertNotIn("huy_bo", rels)

    def test_thay_the_wins_over_bai_bo(self):
        items = [
            _success_item("thay_the", 400),
            _success_item("bai_bo", 400),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("thay_the", rels)
        self.assertNotIn("bai_bo", rels)

    def test_bai_bo_wins_over_huy_bo(self):
        items = [
            _success_item("bai_bo", 500),
            _success_item("huy_bo", 500),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("bai_bo", rels)
        self.assertNotIn("huy_bo", rels)

    def test_same_group_both_kept(self):
        """sua_doi and bo_sung are in the same conflict group — both are kept."""
        items = [
            _success_item("sua_doi", 600),
            _success_item("bo_sung", 600),
        ]
        result = _filter_conflicting_relations(items)
        self.assertEqual(len(result), 2, "same-group relations must both survive")

    def test_non_action_relations_untouched(self):
        """dan_chieu alongside a strong action relation is always kept."""
        items = [
            _success_item("dan_chieu", 700),
            _success_item("bai_bo", 700),
            _success_item("huy_bo", 700),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("dan_chieu", rels, "dan_chieu must be kept")
        self.assertIn("bai_bo", rels, "bai_bo must be kept (higher priority)")
        self.assertNotIn("huy_bo", rels, "huy_bo must be removed")

    def test_no_conflict_different_targets(self):
        """Relations to different targets are independent."""
        items = [
            _success_item("thay_the", 800),
            _success_item("bai_bo", 900),
        ]
        result = _filter_conflicting_relations(items)
        self.assertEqual(len(result), 2, "different targets must not conflict")

    def test_empty_list(self):
        self.assertEqual(_filter_conflicting_relations([]), [])

    def test_single_item(self):
        items = [_success_item("bai_bo", 1000)]
        self.assertEqual(_filter_conflicting_relations(items), items)

    def test_sua_doi_bo_sung_wins_over_all(self):
        """sua_doi_bo_sung must evict thay_the, bai_bo, and huy_bo."""
        items = [
            _success_item("sua_doi_bo_sung", 1100),
            _success_item("thay_the", 1100),
            _success_item("bai_bo", 1100),
            _success_item("huy_bo", 1100),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertEqual(rels, {"sua_doi_bo_sung"})

    def test_clause_level_rels_with_target_key(self):
        """Clause-level rels (with target_key) are also deduplicated."""
        items = [
            _success_item("sua_doi", 1200, "khoan_1_dieu_5"),
            _success_item("bai_bo", 1200, "khoan_1_dieu_5"),
        ]
        result = _filter_conflicting_relations(items)
        rels = {r["relationship"] for r in result}
        self.assertIn("sua_doi", rels)
        self.assertNotIn("bai_bo", rels)

    def test_none_target_doc_id_untouched(self):
        """Items without target_doc_id are passed through unchanged."""
        items = [
            {"relationship": "bai_bo", "target_doc_id": None},
            {"relationship": "thay_the", "target_doc_id": None},
        ]
        result = _filter_conflicting_relations(items)
        self.assertEqual(len(result), 2)
