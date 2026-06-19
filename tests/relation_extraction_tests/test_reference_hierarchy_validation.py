"""Unit tests for reference hierarchy validation in reference_resolution_service."""

import unittest

from src.services.extraction.reference_resolution_service import (
    _get_clause_key_set,
    _is_valid_reference_hierarchy,
)


def _tail(doc_type="luat", **clause_infos):
    """Build a minimal reference tail for testing."""
    tail = {doc_type: {"information": "Luật Các tổ chức tín dụng"}}
    for key, val in clause_infos.items():
        tail[key] = {"information": val}
    return tail


class TestGetClauseKeySet(unittest.TestCase):
    """_get_clause_key_set extracts only clause-type keys from a reference tail."""

    def test_empty_clause_keys_for_document_only_tail(self):
        tail = _tail()
        self.assertEqual(_get_clause_key_set(tail), frozenset())

    def test_dieu_only(self):
        tail = _tail(dieu="Điều 5")
        self.assertEqual(_get_clause_key_set(tail), frozenset({"dieu"}))

    def test_khoan_and_dieu(self):
        tail = _tail(khoan="khoản 1", dieu="Điều 5")
        self.assertEqual(_get_clause_key_set(tail), frozenset({"khoan", "dieu"}))

    def test_diem_khoan_dieu(self):
        tail = _tail(diem="điểm a", khoan="khoản 1", dieu="Điều 5")
        self.assertEqual(_get_clause_key_set(tail), frozenset({"diem", "khoan", "dieu"}))

    def test_doc_type_key_excluded(self):
        tail = _tail("nghidinh", dieu="Điều 3")
        result = _get_clause_key_set(tail)
        self.assertNotIn("nghidinh", result)
        self.assertIn("dieu", result)


class TestIsValidReferenceHierarchy(unittest.TestCase):
    """_is_valid_reference_hierarchy accepts only the five allowed hierarchy patterns."""

    def test_valid_document_only(self):
        self.assertTrue(_is_valid_reference_hierarchy(frozenset()))

    def test_valid_dieu_plus_vanban(self):
        self.assertTrue(_is_valid_reference_hierarchy(frozenset({"dieu"})))

    def test_valid_khoan_dieu(self):
        self.assertTrue(_is_valid_reference_hierarchy(frozenset({"khoan", "dieu"})))

    def test_valid_diem_dieu_special_case(self):
        self.assertTrue(_is_valid_reference_hierarchy(frozenset({"diem", "dieu"})))

    def test_valid_diem_khoan_dieu(self):
        self.assertTrue(_is_valid_reference_hierarchy(frozenset({"diem", "khoan", "dieu"})))

    def test_invalid_khoan_only(self):
        self.assertFalse(_is_valid_reference_hierarchy(frozenset({"khoan"})))

    def test_invalid_diem_khoan_missing_dieu(self):
        self.assertFalse(_is_valid_reference_hierarchy(frozenset({"diem", "khoan"})))

    def test_invalid_diem_only(self):
        self.assertFalse(_is_valid_reference_hierarchy(frozenset({"diem"})))


if __name__ == "__main__":
    unittest.main()
