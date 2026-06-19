"""Tests for authority hierarchy rules and normative/administrative type restrictions."""
import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor

logging.disable(logging.INFO)


def _ref(content: str, text: str, information: str, key: str) -> dict:
    start = content.index(text)
    return {key: {"information": information, "position_start": start, "position_end": start + len(text)}}


def _rel(content: str, text: str, relation_type: str) -> dict:
    start = content.index(text)
    return {"relation_type": relation_type, "position_start": start, "position_end": start + len(text)}


class TestNormativeAdministrativeCrossTypeBlock(unittest.TestCase):
    """Administrative documents must not have action relations with normative documents."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Công văn", "Chỉ thị", "Kế hoạch"]
        )

    def _match(self, content, references, relation_type, source_so_hieu):
        rels = [_rel(content, relation_type[:6] or relation_type, "bai_bo")]
        return self.extractor.match_relations(
            references=references,
            relation_types=[{"relation_type": "bai_bo", "position_start": 0, "position_end": 5,
                             "hint_group": "forward_hints", "direction": "FORWARD"}],
            content=content,
            source_so_hieu=source_so_hieu,
        )

    def test_congvan_cannot_bai_bo_luat(self):
        """Công văn (administrative) must not bai_bo Luật (normative)."""
        content = "Bãi bỏ Luật an toàn thực phẩm."
        refs = [_ref(content, "Luật an toàn thực phẩm", "Luật an toàn thực phẩm", "luat")]
        rels = [{"relation_type": "bai_bo", "position_start": 0, "position_end": 6,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="123/2024/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan bai_bo luat must be filtered")

    def test_congvan_cannot_thay_the_nghidinh(self):
        """Công văn must not thay_the Nghị định."""
        content = "Thay thế Nghị định số 10/2024/NĐ-CP."
        refs = [_ref(content, "Nghị định số 10/2024/NĐ-CP", "Nghị định số 10/2024/NĐ-CP", "nghidinh")]
        rels = [{"relation_type": "thay_the", "position_start": 0, "position_end": 9,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="05/2024/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan thay_the nghidinh must be filtered")

    def test_congvan_cannot_sua_doi_bo_sung_thongtu(self):
        """Công văn must not sua_doi_bo_sung Thông tư."""
        content = "Sửa đổi, bổ sung Thông tư số 20/2024/TT-BTC."
        refs = [_ref(content, "Thông tư số 20/2024/TT-BTC", "Thông tư số 20/2024/TT-BTC", "thongtu")]
        rels = [{"relation_type": "sua_doi_bo_sung", "position_start": 0, "position_end": 16,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="01/2024/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan sua_doi_bo_sung thongtu must be filtered")

    def test_chithi_cannot_bai_bo_nghidinh(self):
        """Chỉ thị (administrative) must not bai_bo Nghị định."""
        content = "Bãi bỏ Nghị định số 15/2024/NĐ-CP."
        refs = [_ref(content, "Nghị định số 15/2024/NĐ-CP", "Nghị định số 15/2024/NĐ-CP", "nghidinh")]
        rels = [{"relation_type": "bai_bo", "position_start": 0, "position_end": 6,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="02/CT-BTC",
        )
        self.assertEqual(matches, [], "chithi bai_bo nghidinh must be filtered")

    def test_normative_nghidinh_bai_bo_normative_thongtu_allowed(self):
        """Normative-to-normative action relations must NOT be filtered by admin/normative rule."""
        content = "Bãi bỏ Thông tư số 30/2023/TT-BTC."
        refs = [_ref(content, "Thông tư số 30/2023/TT-BTC", "Thông tư số 30/2023/TT-BTC", "thongtu")]
        rels = [{"relation_type": "bai_bo", "position_start": 0, "position_end": 6,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="20/2024/NĐ-CP",
        )
        self.assertGreater(len(matches), 0, "nghidinh bai_bo thongtu must be allowed")

    def test_dan_chieu_from_congvan_to_luat_allowed(self):
        """Non-action relations (dan_chieu) from admin to normative are allowed."""
        content = "Căn cứ Luật An toàn thực phẩm."
        refs = [_ref(content, "Luật An toàn thực phẩm", "Luật An toàn thực phẩm", "luat")]
        rels = [{"relation_type": "dan_chieu", "position_start": 0, "position_end": 7,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="05/2024/CV-BTC",
        )
        # dan_chieu is not an action relation, must be allowed
        self.assertGreater(len(matches), 0, "dan_chieu from congvan to luat must be allowed")

    def test_congvan_cannot_huong_dan_thongtu(self):
        """Công văn (administrative) must not huong_dan Thông tư (normative, same ministry)."""
        content = "Hướng dẫn Thông tư số 20/2024/TT-BTC."
        refs = [_ref(content, "Thông tư số 20/2024/TT-BTC", "Thông tư số 20/2024/TT-BTC", "thongtu")]
        rels = [{"relation_type": "huong_dan", "position_start": 0, "position_end": 9,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="50/2024/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan huong_dan thongtu must be filtered")

    def test_congvan_cannot_quy_dinh_chi_tiet_nghidinh(self):
        """Công văn (administrative) must not quy_dinh_chi_tiet Nghị định (normative)."""
        content = "Quy định chi tiết Nghị định số 10/2024/NĐ-CP."
        refs = [_ref(content, "Nghị định số 10/2024/NĐ-CP", "Nghị định số 10/2024/NĐ-CP", "nghidinh")]
        rels = [{"relation_type": "quy_dinh_chi_tiet", "position_start": 0, "position_end": 17,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="30/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan quy_dinh_chi_tiet nghidinh must be filtered")

    def test_congvan_cannot_keo_dai_hieu_luc_thongtu_same_ministry(self):
        """Công văn must not keo_dai_hieu_luc Thông tư from the same ministry (same authority rank)."""
        content = "Kéo dài hiệu lực Thông tư số 05/2023/TT-BTC."
        refs = [_ref(content, "Thông tư số 05/2023/TT-BTC", "Thông tư số 05/2023/TT-BTC", "thongtu")]
        rels = [{"relation_type": "keo_dai_hieu_luc", "position_start": 0, "position_end": 16,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="12/2024/CV-BTC",
        )
        self.assertEqual(matches, [], "congvan keo_dai_hieu_luc thongtu (same ministry) must be filtered")

    def test_admin_action_with_dan_chieu_signal_downgrades_to_dan_chieu(self):
        """When the action relation is blocked but a dan_chieu signal is present, emit dan_chieu."""
        content = (
            "lập danh mục văn bản, nội dung quy định chi tiết theo quy định tại "
            "điểm a khoản 2 Điều 23 của Nghị định số 78/2025/NĐ-CP."
        )
        refs = [_ref(content, "Nghị định số 78/2025/NĐ-CP", "78/2025/NĐ-CP", "nghidinh")]
        rels = [{"relation_type": "quy_dinh_chi_tiet", "position_start": 30, "position_end": 47,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="706/QĐ-BXD",
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["relation_type"], "dan_chieu",
                         "blocked quy_dinh_chi_tiet with dan_chieu signal must downgrade to dan_chieu")


class TestRegulatoryToAdministrativeBlock(unittest.TestCase):
    """Normative documents must not have action relations targeting administrative documents."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Công văn", "Chỉ thị"]
        )

    def _match(self, content, refs, relation_type, source_so_hieu):
        rels = [{"relation_type": relation_type, "position_start": 0, "position_end": 6,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        return self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu=source_so_hieu,
        )

    def test_thongtu_cannot_bai_bo_congvan(self):
        content = "Bãi bỏ Công văn số 50/CV-BTC."
        refs = [_ref(content, "Công văn số 50/CV-BTC", "50/CV-BTC", "congvan")]
        self.assertEqual(self._match(content, refs, "bai_bo", "10/2024/TT-BTC"), [],
                         "thongtu bai_bo congvan must be filtered")

    def test_nghidinh_cannot_sua_doi_bo_sung_chithi(self):
        content = "Sửa đổi, bổ sung Chỉ thị số 03/CT-BTC."
        refs = [_ref(content, "Chỉ thị số 03/CT-BTC", "03/CT-BTC", "chithi")]
        self.assertEqual(self._match(content, refs, "sua_doi_bo_sung", "20/2024/NĐ-CP"), [],
                         "nghidinh sua_doi_bo_sung chithi must be filtered")

    def test_thongtu_cannot_huong_dan_congvan(self):
        content = "Hướng dẫn Công văn số 12/CV-BTC."
        refs = [_ref(content, "Công văn số 12/CV-BTC", "12/CV-BTC", "congvan")]
        self.assertEqual(self._match(content, refs, "huong_dan", "10/2024/TT-BTC"), [],
                         "thongtu huong_dan congvan must be filtered")

    def test_nghidinh_cannot_quy_dinh_chi_tiet_congvan(self):
        content = "Quy định chi tiết Công văn số 50/CV-BXD."
        refs = [_ref(content, "Công văn số 50/CV-BXD", "50/CV-BXD", "congvan")]
        self.assertEqual(self._match(content, refs, "quy_dinh_chi_tiet", "20/2024/NĐ-CP"), [],
                         "nghidinh quy_dinh_chi_tiet congvan must be filtered")

    def test_thongtu_cannot_keo_dai_hieu_luc_congvan(self):
        content = "Kéo dài hiệu lực Công văn số 30/CV-BTC."
        refs = [_ref(content, "Công văn số 30/CV-BTC", "30/CV-BTC", "congvan")]
        self.assertEqual(self._match(content, refs, "keo_dai_hieu_luc", "05/2024/TT-BTC"), [],
                         "thongtu keo_dai_hieu_luc congvan must be filtered")


class TestAuthorityHierarchySameLevelGuidance(unittest.TestCase):
    """Same-level documents must not have huong_dan/quy_dinh_chi_tiet relations."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=["Thông tư", "Nghị định"]
        )

    def test_thongtu_cannot_huong_dan_another_thongtu(self):
        """Thông tư must not guide another Thông tư (same level)."""
        content = "Hướng dẫn Thông tư số 05/2023/TT-BTC."
        refs = [_ref(content, "Thông tư số 05/2023/TT-BTC", "Thông tư số 05/2023/TT-BTC", "thongtu")]
        rels = [{"relation_type": "huong_dan", "position_start": 0, "position_end": 9,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="10/2024/TT-BTC",
        )
        self.assertEqual(matches, [], "thongtu huong_dan thongtu must be filtered (same level)")

    def test_nghidinh_can_huong_dan_luat(self):
        """Nghị định (lower) can quy_dinh_chi_tiet Luật (higher) — that's allowed."""
        content = "Quy định chi tiết Luật Đầu tư."
        refs = [_ref(content, "Luật Đầu tư", "Luật Đầu tư", "luat")]
        rels = [{"relation_type": "quy_dinh_chi_tiet", "position_start": 0, "position_end": 17,
                 "hint_group": "forward_hints", "direction": "FORWARD"}]
        matches = self.extractor.match_relations(
            references=refs, relation_types=rels, content=content,
            source_so_hieu="31/2021/NĐ-CP",
        )
        self.assertGreater(len(matches), 0, "nghidinh quy_dinh_chi_tiet luat must be allowed")
