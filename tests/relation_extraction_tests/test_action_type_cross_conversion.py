"""Unit tests for _extract_target_title_from_context (§6 B2) and
_refine_action_relation_type (§4+§5+§6 central decision, B3).
"""
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


def _ref(doc_key: str, information: str, position_end: int = None) -> dict:
    """Minimal reference dict; position_end is required for Pattern 2."""
    entry = {"information": information}
    if position_end is not None:
        entry["position_end"] = position_end
    return {doc_key: entry}


class TestExtractTargetTitleFromContext(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    # ── Pattern 1: tiêu đề nằm trong reference (Luật/Bộ luật) ───────────

    def test_luat_title_extracted_from_information(self) -> None:
        """Pattern 1: Luật reference → information IS the title."""
        content = "thay thế Luật An toàn thực phẩm ngày 15 tháng 6 năm 2010."
        luat_start = content.index("Luật")
        ref = _ref("luat", "Luật An toàn thực phẩm",
                   position_end=luat_start + len("Luật An toàn thực phẩm"))
        result = self.extractor._extract_target_title_from_context(content, ref)
        self.assertEqual(result, "Luật An toàn thực phẩm")

    def test_boluat_title_extracted_from_information(self) -> None:
        """Pattern 1: Bộ luật reference → information IS the title."""
        content = "bãi bỏ Bộ luật Dân sự năm 2005."
        start = content.index("Bộ luật")
        ref = _ref("boluat", "Bộ luật Dân sự",
                   position_end=start + len("Bộ luật Dân sự"))
        result = self.extractor._extract_target_title_from_context(content, ref)
        self.assertEqual(result, "Bộ luật Dân sự")

    def test_luat_bare_type_without_title_returns_none(self) -> None:
        """Pattern 1: information = 'Luật' (no title after type word) → None."""
        ref = _ref("luat", "Luật")
        result = self.extractor._extract_target_title_from_context("bất kỳ nội dung", ref)
        self.assertIsNone(result)

    # ── Pattern 2: mô tả nằm sau reference trong content ────────────────

    def test_pattern2_acceptance_thongtu_nhnn(self) -> None:
        """Pattern 2 acceptance: 13/2018/TT-NHNN with full description."""
        content = (
            "a) Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018 của Thống đốc "
            "Ngân hàng Nhà nước Việt Nam quy định về hệ thống kiểm soát nội bộ của "
            "ngân hàng thương mại, chi nhánh ngân hàng nước ngoài;"
        )
        position_end = content.index("13/2018/TT-NHNN") + len("13/2018/TT-NHNN")
        ref = _ref("thongtu", "13/2018/TT-NHNN", position_end=position_end)
        result = self.extractor._extract_target_title_from_context(content, ref)
        self.assertIsNotNone(result)
        self.assertIn(
            "quy định về hệ thống kiểm soát nội bộ của ngân hàng thương mại, "
            "chi nhánh ngân hàng nước ngoài",
            result,
        )

    def test_pattern2_no_description_after_date_returns_none(self) -> None:
        """Pattern 2: only serial + date, no description text → None."""
        content = "bãi bỏ Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018;"
        position_end = content.index("13/2018/TT-NHNN") + len("13/2018/TT-NHNN")
        ref = _ref("thongtu", "13/2018/TT-NHNN", position_end=position_end)
        result = self.extractor._extract_target_title_from_context(content, ref)
        self.assertIsNone(result)

    def test_pattern2_no_date_no_description_returns_none(self) -> None:
        """Pattern 2: serial immediately followed by ';', no date, no description → None."""
        content = "bãi bỏ Thông tư số 13/2018/TT-NHNN;"
        position_end = content.index("13/2018/TT-NHNN") + len("13/2018/TT-NHNN")
        ref = _ref("thongtu", "13/2018/TT-NHNN", position_end=position_end)
        result = self.extractor._extract_target_title_from_context(content, ref)
        self.assertIsNone(result)

    def test_pattern2_missing_position_end_returns_none(self) -> None:
        """Pattern 2: reference has no position_end → cannot locate reference in content → None."""
        ref = {"thongtu": {"information": "13/2018/TT-NHNN"}}
        result = self.extractor._extract_target_title_from_context(
            "bất kỳ nội dung nào đó", ref
        )
        self.assertIsNone(result)

    # ── Không có primary document ────────────────────────────────────────

    def test_clause_only_reference_returns_none(self) -> None:
        """No primary document component (only clause keys) → None."""
        ref = {"dieu": {"information": "3"}}
        result = self.extractor._extract_target_title_from_context("nội dung", ref)
        self.assertIsNone(result)


class TestRefineActionRelationType(unittest.TestCase):
    """B3 — _refine_action_relation_type: central §4+§5+§6 decision tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    # ── §4 thay_the path ─────────────────────────────────────────────────

    def test_thay_the_same_type_authority_stays_thay_the(self) -> None:
        """thay_the + same nghidinh-CP → thay_the (§4 pass)."""
        ref = _ref("nghidinh", "15/2018/NĐ-CP")
        result = self.extractor._refine_action_relation_type("thay_the", "24/2014/NĐ-CP", ref)
        self.assertEqual(result, "thay_the")

    def test_thay_the_different_type_bai_bo_allowed_becomes_bai_bo(self) -> None:
        """thay_the: NĐ-CP 2020 → TT-NHNN 2016 (different type), level/year OK → bai_bo."""
        ref = _ref("thongtu", "13/2016/TT-NHNN")
        result = self.extractor._refine_action_relation_type("thay_the", "125/2020/NĐ-CP", ref)
        self.assertEqual(result, "bai_bo")

    def test_thay_the_lower_source_level_same_normative_group_demotes_to_dan_chieu(self) -> None:
        """thay_the: TT (level 80) → NĐ-CP (level 100), bai_bo not allowed, both normative → dan_chieu."""
        ref = _ref("nghidinh", "24/2018/NĐ-CP")
        result = self.extractor._refine_action_relation_type("thay_the", "09/2020/TT-BTC", ref)
        self.assertEqual(result, "dan_chieu")

    def test_thay_the_normative_to_unresolvable_target_drops(self) -> None:
        """thay_the: normative → empty-info (unresolvable, non-normative level=None) → DROP."""
        ref = {"thongtu": {"information": ""}}
        result = self.extractor._refine_action_relation_type("thay_the", "24/2020/NĐ-CP", ref)
        self.assertEqual(result, "DROP")

    # ── §6 case B: bai_bo → thay_the ────────────────────────────────────

    def test_bai_bo_same_type_authority_high_similarity_becomes_thay_the(self) -> None:
        """bai_bo: same TT-NHNN + title_sim=0.9 ≥ 0.8 → thay_the (§6 case B)."""
        ref = _ref("thongtu", "13/2018/TT-NHNN")
        result = self.extractor._refine_action_relation_type(
            "bai_bo", "83/2025/TT-NHNN", ref, title_sim=0.9
        )
        self.assertEqual(result, "thay_the")

    def test_bai_bo_same_type_authority_low_similarity_stays_bai_bo(self) -> None:
        """bai_bo: same TT-NHNN but title_sim=0.5 < 0.8 → bai_bo (§6 case B not triggered)."""
        ref = _ref("thongtu", "13/2018/TT-NHNN")
        result = self.extractor._refine_action_relation_type(
            "bai_bo", "83/2025/TT-NHNN", ref, title_sim=0.5
        )
        self.assertEqual(result, "bai_bo")

    # ── §5 bai_bo path ───────────────────────────────────────────────────

    def test_bai_bo_level_year_valid_stays_bai_bo(self) -> None:
        """bai_bo: NĐ-CP 2020 → TT-NHNN 2016, level/year valid → bai_bo (§5 pass)."""
        ref = _ref("thongtu", "09/2016/TT-NHNN")
        result = self.extractor._refine_action_relation_type("bai_bo", "125/2020/NĐ-CP", ref)
        self.assertEqual(result, "bai_bo")

    def test_bai_bo_older_source_same_normative_group_demotes_to_dan_chieu(self) -> None:
        """bai_bo: TT-NHNN 2016 → TT-BTC 2020, source year < target → dan_chieu."""
        ref = _ref("thongtu", "13/2020/TT-BTC")
        result = self.extractor._refine_action_relation_type("bai_bo", "09/2016/TT-NHNN", ref)
        self.assertEqual(result, "dan_chieu")

    # ── Non-action types pass through unchanged ──────────────────────────

    def test_non_action_type_can_cu_passes_through(self) -> None:
        """Non-action type (can_cu) passes through unchanged."""
        ref = _ref("nghidinh", "24/2018/NĐ-CP")
        result = self.extractor._refine_action_relation_type("can_cu", "09/2020/TT-BTC", ref)
        self.assertEqual(result, "can_cu")

    def test_non_action_type_dan_chieu_passes_through(self) -> None:
        """Non-action type (dan_chieu) passes through unchanged."""
        ref = _ref("thongtu", "13/2018/TT-NHNN")
        result = self.extractor._refine_action_relation_type("dan_chieu", "09/2020/TT-BTC", ref)
        self.assertEqual(result, "dan_chieu")
