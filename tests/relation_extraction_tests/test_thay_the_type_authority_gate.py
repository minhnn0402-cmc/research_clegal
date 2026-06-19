"""Unit tests for _is_same_type_and_authority (§4 gate for thay_the / bai_bo)."""
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


def _ref(doc_key: str, information: str) -> dict:
    """Minimal reference dict with the given primary document component."""
    return {doc_key: {"information": information}}


class TestIsSameTypeAndAuthority(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    # ── Acceptance: same type + same authority → True ─────────────────────

    def test_same_nghidinh_cp_returns_true(self) -> None:
        """24/2014/NĐ-CP vs 15/2018/NĐ-CP → same nghidinh, same CP authority."""
        ref = _ref("nghidinh", "15/2018/NĐ-CP")
        self.assertTrue(self.extractor._is_same_type_and_authority("24/2014/NĐ-CP", ref))

    def test_same_thongtu_nhnn_returns_true(self) -> None:
        """83/2025/TT-NHNN vs 13/2018/TT-NHNN → same thongtu, same NHNN (§6 case)."""
        ref = _ref("thongtu", "13/2018/TT-NHNN")
        self.assertTrue(self.extractor._is_same_type_and_authority("83/2025/TT-NHNN", ref))

    def test_same_quyetdinh_ttg_returns_true(self) -> None:
        """12/2020/QĐ-TTg vs 88/2018/QĐ-TTg → same quyetdinh, same TTg authority."""
        ref = _ref("quyetdinh", "88/2018/QĐ-TTg")
        self.assertTrue(self.extractor._is_same_type_and_authority("12/2020/QĐ-TTg", ref))

    # ── Acceptance: 24/2014/NĐ-CP vs 123/BTP → False ─────────────────────

    def test_different_authority_nghidinh_vs_btp_returns_false(self) -> None:
        """24/2014/NĐ-CP vs 123/BTP → unparseable target type, different authority suffix."""
        ref = _ref("quyetdinh", "123/BTP")
        self.assertFalse(self.extractor._is_same_type_and_authority("24/2014/NĐ-CP", ref))

    # ── Acceptance: 24/2014/NĐ-CP vs 45/2017/VPQH → False ───────────────

    def test_different_type_nghidinh_vs_vpqh_returns_false(self) -> None:
        """24/2014/NĐ-CP vs 45/2017/VPQH → target type unresolved, different authority."""
        ref = _ref("quyetdinh", "45/2017/VPQH")
        self.assertFalse(self.extractor._is_same_type_and_authority("24/2014/NĐ-CP", ref))

    # ── Same type, different authority → False ───────────────────────────

    def test_same_type_different_authority_returns_false(self) -> None:
        """TT-BYT vs TT-BTC → same thongtu type but different ministry."""
        ref = _ref("thongtu", "12/2020/TT-BTC")
        self.assertFalse(self.extractor._is_same_type_and_authority("45/2019/TT-BYT", ref))

    # ── Acceptance: unparseable target → False (cautious) ────────────────

    def test_clause_only_reference_returns_false(self) -> None:
        """Reference with only clause-level keys → no primary document → False."""
        ref = {"dieu": {"information": "3"}}
        self.assertFalse(self.extractor._is_same_type_and_authority("24/2014/NĐ-CP", ref))

    def test_empty_information_in_reference_returns_false(self) -> None:
        """Reference with empty information → cannot extract identifier → False."""
        ref = {"nghidinh": {"information": ""}}
        self.assertFalse(self.extractor._is_same_type_and_authority("24/2014/NĐ-CP", ref))

    # ── None / empty source → False ──────────────────────────────────────

    def test_none_source_returns_false(self) -> None:
        """None source → False (cautious; no anatomy derivable)."""
        ref = _ref("nghidinh", "15/2018/NĐ-CP")
        self.assertFalse(self.extractor._is_same_type_and_authority(None, ref))

    # ── None authority_suffix on either side → False ─────────────────────

    def test_title_only_sources_without_authority_suffix_returns_false(self) -> None:
        """Both sides have doc_type=luat but no authority_suffix → False (cautious)."""
        ref = _ref("luat", "Luật Bảo hiểm xã hội")
        self.assertFalse(
            self.extractor._is_same_type_and_authority("Luật An toàn thực phẩm", ref)
        )
