"""Unit tests for _extract_document_number_anatomy and _extract_year_from_identifier."""
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


class TestExtractYearFromIdentifier(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    def test_year_extracted_from_nghidinh(self) -> None:
        self.assertEqual(self.extractor._extract_year_from_identifier("24/2014/NĐ-CP"), 2014)

    def test_no_year_in_admin_doc(self) -> None:
        self.assertIsNone(self.extractor._extract_year_from_identifier("518/BKHCN"))

    def test_year_extracted_from_vpqh_identifier(self) -> None:
        self.assertEqual(self.extractor._extract_year_from_identifier("45/2017/VPQH"), 2017)

    def test_no_year_in_title_only(self) -> None:
        self.assertIsNone(self.extractor._extract_year_from_identifier("Luật An toàn thực phẩm"))

    def test_year_extracted_from_thongtu(self) -> None:
        self.assertEqual(self.extractor._extract_year_from_identifier("83/2025/TT-NHNN"), 2025)

    def test_none_identifier_returns_none(self) -> None:
        self.assertIsNone(self.extractor._extract_year_from_identifier(None))


class TestExtractDocumentNumberAnatomy(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = BaseExtractor(doc_clause_types=[])

    # ── §4 acceptance case 1: cùng loại + cơ quan ─────────────────────────
    def test_nghidinh_cp_full(self) -> None:
        """24/2014/NĐ-CP → nghidinh, CP, year=2014, normative."""
        result = self.extractor._extract_document_number_anatomy("24/2014/NĐ-CP")
        self.assertEqual(result["doc_type"], "nghidinh")
        self.assertEqual(result["authority_suffix"], "CP")
        self.assertEqual(result["year"], 2014)
        self.assertTrue(result["is_normative"])

    def test_nghidinh_cp_level(self) -> None:
        """24/2014/NĐ-CP → level 100 (CP authority rank)."""
        result = self.extractor._extract_document_number_anatomy("24/2014/NĐ-CP")
        self.assertEqual(result["level"], 100)

    # ── §4 acceptance case 2: admin doc, no year ──────────────────────────
    def test_admin_doc_bkhcn_no_year(self) -> None:
        """518/BKHCN → no year, not normative, authority_suffix BKHCN."""
        result = self.extractor._extract_document_number_anatomy("518/BKHCN")
        self.assertIsNone(result["year"])
        self.assertFalse(result["is_normative"])
        self.assertEqual(result["authority_suffix"], "BKHCN")

    def test_admin_doc_bkhcn_level(self) -> None:
        """518/BKHCN → level 80 (central ministry authority rank)."""
        result = self.extractor._extract_document_number_anatomy("518/BKHCN")
        self.assertEqual(result["level"], 80)

    # ── §4 acceptance case 3: year present, unknown authority ─────────────
    def test_identifier_with_vpqh_unknown_authority(self) -> None:
        """45/2017/VPQH → year=2017, authority_suffix=VPQH."""
        result = self.extractor._extract_document_number_anatomy("45/2017/VPQH")
        self.assertEqual(result["year"], 2017)
        self.assertEqual(result["authority_suffix"], "VPQH")

    # ── §4 acceptance case 4: title-only Luật → normative ─────────────────
    def test_title_only_luat_is_normative(self) -> None:
        """'Luật An toàn thực phẩm' → luat, year=None, normative=True."""
        result = self.extractor._extract_document_number_anatomy("Luật An toan thực phẩm")
        self.assertEqual(result["doc_type"], "luat")
        self.assertIsNone(result["year"])
        self.assertTrue(result["is_normative"])

    def test_title_only_luat_level(self) -> None:
        """'Luật X' → level 130 (type_rank fallback)."""
        result = self.extractor._extract_document_number_anatomy("Luật An toan thực phẩm")
        self.assertEqual(result["level"], 130)

    def test_title_only_bo_luat(self) -> None:
        """'Bộ luật Dân sự' → boluat, normative=True."""
        result = self.extractor._extract_document_number_anatomy("Bộ luật Dân sự")
        self.assertEqual(result["doc_type"], "boluat")
        self.assertTrue(result["is_normative"])

    # ── §5 hỗ trợ: thông tư NHNN ──────────────────────────────────────────
    def test_thongtu_nhnn(self) -> None:
        """83/2025/TT-NHNN → thongtu, NHNN, year=2025, normative."""
        result = self.extractor._extract_document_number_anatomy("83/2025/TT-NHNN")
        self.assertEqual(result["doc_type"], "thongtu")
        self.assertEqual(result["authority_suffix"], "NHNN")
        self.assertEqual(result["year"], 2025)
        self.assertTrue(result["is_normative"])

    # ── title-only không có authority_suffix ─────────────────────────────
    def test_title_only_has_no_authority_suffix(self) -> None:
        """Title-only reference has no authority suffix (no serial number)."""
        result = self.extractor._extract_document_number_anatomy("Luật An toan thực phẩm")
        self.assertIsNone(result["authority_suffix"])

    # ── None/empty identifier ─────────────────────────────────────────────
    def test_none_identifier(self) -> None:
        """None identifier returns safe defaults."""
        result = self.extractor._extract_document_number_anatomy(None)
        self.assertIsNone(result["doc_type"])
        self.assertIsNone(result["year"])
        self.assertFalse(result["is_normative"])
