"""Tests for 'Việc X thực hiện theo quy định tại [ref]' → dan_chieu conversion
and the year-in-number is_regulatory rule.

The conversion happens in RelationTypeExtraction.extract_relation_types (Phase 1).
Tests for the conversion use that method directly with synthetic reference positions.
"""
import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor
from src.domain.extractors.base_extractor_flow.relation_type_extraction import RelationTypeExtraction

logging.disable(logging.INFO)


def _make_extractor():
    return BaseExtractor(doc_clause_types=["Luật", "Nghị định", "Thông tư", "Quyết định"])


def _ref(content, text, information, key):
    start = content.index(text)
    return {key: {"information": information, "position_start": start,
                  "position_end": start + len(text)}}


class TestViecThucHienTheoDanChieu(unittest.TestCase):
    """'Việc [action] thực hiện theo quy định tại [ref]' must yield dan_chieu.

    The conversion takes place in extract_relation_types; we test at that level.
    """

    def setUp(self):
        self.rte = RelationTypeExtraction()

    def _extract_types(self, content, references):
        return self.rte.extract_relation_types(content=content, references=references)

    def test_viec_sua_doi_bo_sung_thuc_hien_theo_yields_dan_chieu(self):
        """Core regression: action types must be converted when 'thực hiện theo quy định tại' present."""
        content = (
            "Việc sửa đổi, bổ sung, thay thế, bãi bỏ văn bản QPPL "
            "thực hiện theo quy định tại Điều 8 của Luật Ban hành văn bản quy phạm pháp luật."
        )
        start = content.index("Luật")
        refs = [{"luat": {"information": "Luật Ban hành văn bản quy phạm pháp luật",
                          "position_start": start, "position_end": start + 42}}]
        result = self._extract_types(content, refs)
        relation_types = {r["relation_type"] for r in result}
        self.assertNotIn("sua_doi_bo_sung", relation_types,
                         "sua_doi_bo_sung must be converted to dan_chieu")
        self.assertNotIn("thay_the", relation_types)
        self.assertNotIn("bai_bo", relation_types)
        self.assertIn("dan_chieu", relation_types, "dan_chieu must be the surviving type")

    def test_viec_bai_bo_thuc_hien_theo_yields_dan_chieu(self):
        content = (
            "Việc bãi bỏ các thủ tục hành chính thực hiện theo quy định tại "
            "Điều 4 của Nghị định số 78/2025/NĐ-CP."
        )
        start = content.index("Nghị định")
        refs = [{"nghidinh": {"information": "78/2025/NĐ-CP",
                              "position_start": start, "position_end": start + 13}}]
        result = self._extract_types(content, refs)
        relation_types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", relation_types)
        self.assertIn("dan_chieu", relation_types)

    def test_viec_thay_the_thuc_hien_theo_quy_dinh_cua(self):
        """'theo quy định của' (not 'tại') also triggers conversion."""
        content = (
            "Việc thay thế các quyết định cũ thực hiện theo quy định của "
            "Luật Ban hành văn bản quy phạm pháp luật."
        )
        start = content.index("Luật")
        refs = [{"luat": {"information": "Luật Ban hành văn bản quy phạm pháp luật",
                          "position_start": start, "position_end": start + 42}}]
        result = self._extract_types(content, refs)
        relation_types = {r["relation_type"] for r in result}
        self.assertNotIn("thay_the", relation_types)
        self.assertIn("dan_chieu", relation_types)

    def test_direct_sua_doi_without_thuc_hien_theo_keeps_action_type(self):
        """Without 'thực hiện theo', action type is preserved."""
        content = "Sửa đổi, bổ sung Nghị định số 78/2025/NĐ-CP như sau: ..."
        start = content.index("Nghị")
        refs = [{"nghidinh": {"information": "78/2025/NĐ-CP",
                              "position_start": start, "position_end": start + 13}}]
        result = self._extract_types(content, refs)
        relation_types = {r["relation_type"] for r in result}
        self.assertTrue(
            relation_types & {"sua_doi_bo_sung", "sua_doi", "bo_sung"},
            f"An action relation must be kept; got {relation_types}",
        )


class TestIsRegulatoryYearRule(unittest.TestCase):
    """Documents with year in number = normative; without year = administrative."""

    def setUp(self):
        from src.domain.extractors.base_extractor import BaseExtractor
        self.m = BaseExtractor(doc_clause_types=[])

    def _info(self, identifier, doc_type_key=None):
        return self.m._build_authority_policy_doc_info(identifier, doc_type_key)

    def test_nghidinh_with_year_is_regulatory(self):
        self.assertTrue(self._info("78/2025/NĐ-CP", "nghidinh")["is_regulatory"])

    def test_nghidinh_without_year_is_not_regulatory(self):
        self.assertFalse(self._info("42/CP", "nghidinh")["is_regulatory"])

    def test_quyetdinh_with_year_is_regulatory(self):
        info = self._info(
            "Quyết định số 45/QĐ-BTC ngày 09 tháng 01 năm 2019", "quyetdinh"
        )
        self.assertTrue(info["is_regulatory"])

    def test_quyetdinh_without_year_is_not_regulatory(self):
        self.assertFalse(self._info("706/QĐ-BXD", "quyetdinh")["is_regulatory"])

    def test_luat_always_regulatory_without_year(self):
        self.assertTrue(self._info("Luật An toàn thực phẩm", "luat")["is_regulatory"])

    def test_congvan_with_year_is_not_regulatory(self):
        self.assertFalse(self._info("123/2024/CV-BTC", "congvan")["is_regulatory"])

    def test_thongtu_with_year_is_regulatory(self):
        self.assertTrue(self._info("10/2024/TT-BTC", "thongtu")["is_regulatory"])

    def test_thongtu_without_year_is_not_regulatory(self):
        self.assertFalse(self._info("10/TT-BTC", "thongtu")["is_regulatory"])


class TestCrossDimensionHierarchyFilter(unittest.TestCase):
    """Non-normative QĐ (no year) must not act on inherently-normative Luật."""

    def setUp(self):
        self.ext = _make_extractor()

    def _match(self, content, ref, rel_type, source_so_hieu):
        return self.ext.match_relations(
            references=[ref],
            relation_types=[_rel(content, rel_type[:3] if len(rel_type) > 3 else rel_type,
                                 rel_type)],
            content=content,
            source_so_hieu=source_so_hieu,
        )

    def test_qd_without_year_cannot_bai_bo_luat_by_title(self):
        """Non-normative QĐ (no year) must not bai_bo a Luật referenced by title."""
        content = "Bãi bỏ Luật An toàn thực phẩm."
        ref = _ref(content, "Luật An toàn thực phẩm", "Luật An toàn thực phẩm", "luat")
        rels = [{"relation_type": "bai_bo", "hint_group": "forward_hints",
                 "direction": "FORWARD", "position_start": 0, "position_end": 6}]
        matches = self.ext.match_relations(
            references=[ref], relation_types=rels, content=content,
            source_so_hieu="706/QĐ-BXD",
        )
        self.assertEqual(matches, [], "QĐ without year must not bai_bo Luật by title")

    def test_nghidinh_with_year_can_bai_bo_thongtu(self):
        """Normative Nghị định (with year) CAN bai_bo a Thông tư."""
        content = "Bãi bỏ Thông tư số 10/2020/TT-BTC."
        ref = _ref(content, "Thông tư số 10/2020/TT-BTC",
                   "Thông tư số 10/2020/TT-BTC", "thongtu")
        rels = [{"relation_type": "bai_bo", "hint_group": "forward_hints",
                 "direction": "FORWARD", "position_start": 0, "position_end": 6}]
        matches = self.ext.match_relations(
            references=[ref], relation_types=rels, content=content,
            source_so_hieu="20/2024/NĐ-CP",
        )
        self.assertGreater(len(matches), 0, "Nghị định must be able to bai_bo Thông tư")

    def test_qd_without_year_can_dan_chieu_luat(self):
        """dan_chieu from any source to any target is always allowed."""
        content = "Theo quy định tại Luật An toàn thực phẩm."
        ref = _ref(content, "Luật An toàn thực phẩm", "Luật An toàn thực phẩm", "luat")
        rels = [{"relation_type": "dan_chieu", "hint_group": "forward_hints",
                 "direction": "FORWARD", "position_start": 0, "position_end": 4}]
        matches = self.ext.match_relations(
            references=[ref], relation_types=rels, content=content,
            source_so_hieu="706/QĐ-BXD",
        )
        self.assertGreater(len(matches), 0, "dan_chieu must always be allowed")
