"""Unit tests for _bai_bo_allowed (§5 level/year gate, B3)."""
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


def _ref(doc_key: str, information: str) -> dict:
    return {doc_key: {"information": information}}


class TestBaiBoAllowed(unittest.TestCase):
    """Direct unit tests for _bai_bo_allowed — isolated §5 level/year logic."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    # ── Acceptance: both normative, level and year valid ──────────────────

    def test_nghidinh_cp_2020_over_thongtu_2016_returns_true(self) -> None:
        """NĐ-CP 2020 (level 100) → TT 2016 (level 80): level 100≥80, year 2020≥2016 → True."""
        ref = _ref("thongtu", "09/2016/TT-BTC")
        self.assertTrue(self.extractor._bai_bo_allowed("125/2020/NĐ-CP", ref))

    def test_same_level_same_year_both_normative_returns_true(self) -> None:
        """Same level (80) and same year (2020), both normative → True (≥ is satisfied)."""
        ref = _ref("thongtu", "09/2020/TT-BTC")
        self.assertTrue(self.extractor._bai_bo_allowed("13/2020/TT-NHNN", ref))

    # ── Both normative year check failures ───────────────────────────────

    def test_both_normative_source_year_older_returns_false(self) -> None:
        """TT-NHNN 2016 → TT-BTC 2020: year 2016 < 2020 → False."""
        ref = _ref("thongtu", "13/2020/TT-BTC")
        self.assertFalse(self.extractor._bai_bo_allowed("09/2016/TT-NHNN", ref))

    # ── Level check failures ─────────────────────────────────────────────

    def test_source_level_below_target_returns_false(self) -> None:
        """TT (level 80) → NĐ-CP (level 100): level 80 < 100 → False."""
        ref = _ref("nghidinh", "24/2018/NĐ-CP")
        self.assertFalse(self.extractor._bai_bo_allowed("09/2020/TT-BTC", ref))

    # ── Non-normative target: year check skipped ─────────────────────────

    def test_normative_src_non_normative_tgt_level_valid_returns_true(self) -> None:
        """NĐ-CP 2020 (normative, 100) → admin-BKHCN (non-normative, 80): level only → True."""
        ref = _ref("quyetdinh", "518/BKHCN")
        self.assertTrue(self.extractor._bai_bo_allowed("24/2020/NĐ-CP", ref))

    def test_both_non_normative_equal_level_returns_true(self) -> None:
        """Both non-normative (no year), equal level (80) → True (no year check)."""
        ref = _ref("quyetdinh", "123/BTC")
        self.assertTrue(self.extractor._bai_bo_allowed("518/BKHCN", ref))

    # ── Cautious: unknown / missing anatomy ──────────────────────────────

    def test_unknown_target_level_returns_false(self) -> None:
        """Empty target information → level=None → cannot determine level → False."""
        ref = _ref("thongtu", "")
        self.assertFalse(self.extractor._bai_bo_allowed("24/2020/NĐ-CP", ref))

    def test_none_source_returns_false(self) -> None:
        """None source → False (cautious)."""
        ref = _ref("nghidinh", "09/2016/NĐ-CP")
        self.assertFalse(self.extractor._bai_bo_allowed(None, ref))

    def test_clause_only_reference_returns_false(self) -> None:
        """Clause-only reference (no primary document) → False."""
        ref = {"dieu": {"information": "3"}}
        self.assertFalse(self.extractor._bai_bo_allowed("24/2020/NĐ-CP", ref))
