import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.components_extractor import extract_document_components
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


class TestDocumentNumberNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_nghi_quyet_suffix_allows_space_after_hyphen(self) -> None:
        content = (
            "Thống nhất kéo dài thời gian thực hiện Nghị quyết số 18/2022/NQ- HĐND "
            "ngày 07 tháng 9 năm 2022 của Hội đồng nhân dân tỉnh và "
            "Nghị quyết số 25/2022/NQ-HĐND ngày 08 tháng 12 năm 2022."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="38/2024/NQ-HĐND",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "keo_dai_hieu_luc"
        ]

        self.assertEqual(
            refs,
            [
                "Nghị quyết số 18/2022/NQ-HĐND ngày 07 tháng 9 năm 2022",
                "Nghị quyết số 25/2022/NQ-HĐND ngày 08 tháng 12 năm 2022",
            ],
        )

    def test_chi_thi_full_number_with_year_and_suffix(self) -> None:
        components = extract_document_components(
            "Chỉ thị số 01/2006/CT-CA ngày 04/01/2006",
            "chithi",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "01/2006/ct-ca")
        self.assertEqual(components["loai_van_ban"], "Chỉ thị")
        self.assertEqual(components["ngay"], "04")
        self.assertEqual(components["thang"], "01")
        self.assertEqual(components["nam"], 2006)

    def test_nghi_quyet_decimal_number_preserved_for_id_lookup(self) -> None:
        components = extract_document_components(
            "Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026",
            "nghiquyet",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "66.13/2026/nq-cp")
        self.assertEqual(components["loai_van_ban"], "Nghị quyết")
        self.assertEqual(components["ngay"], "27")
        self.assertEqual(components["thang"], "01")
        self.assertEqual(components["nam"], 2026)

    def test_nghi_dinh_missing_hyphen_in_ndcp_keeps_full_number(self) -> None:
        components = extract_document_components(
            "Nghị định số 42/2022/NĐCP ngày 24/6/2022",
            "nghidinh",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "42/2022/nđ-cp")
        self.assertEqual(components["ngay"], "24")
        self.assertEqual(components["thang"], "06")
        self.assertEqual(components["nam"], 2022)

    def test_thong_tu_allows_spaces_around_slash(self) -> None:
        components = extract_document_components(
            "Thông tư số 01 /2018/TT-VPCP",
            "thongtu",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "01/2018/tt-vpcp")

    def test_thong_tu_lien_tich_text_reclassifies_from_thong_tu_key(self) -> None:
        components = extract_document_components(
            "Thông tư Liên tịch số 14/2015/TTLT-BNNPTNT",
            "thongtu",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "14/2015/ttlt-bnnptnt")
        self.assertEqual(components["loai_van_ban"], "Thông tư liên tịch")

    def test_law_title_fallback_handles_titles_not_in_regex_list(self) -> None:
        components = extract_document_components(
            "Luật Thuỷ sản ngày 26 tháng 11 năm 2003",
            "luat",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["tieu_de"], "luật thuỷ sản")
        self.assertEqual(components["so_hieu"], "")
        self.assertEqual(components["ngay"], "26")
        self.assertEqual(components["thang"], "11")
        self.assertEqual(components["nam"], 2003)

    def test_quyet_dinh_incomplete_suffix_keeps_number_and_year(self) -> None:
        components = extract_document_components(
            "Quyết định số 195/1999/QĐ",
            "quyetdinh",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "195/1999/qđ")

    def test_thong_tu_incomplete_suffix_keeps_number_and_year(self) -> None:
        components = extract_document_components(
            "Thông tư số 86/2002/TT",
            "thongtu",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "86/2002/tt")

    def test_nghi_quyet_hyphenated_year_keeps_leading_number(self) -> None:
        components = extract_document_components(
            "Nghị quyết số 19-2016/NQ-CP ngày 28/4/2016",
            "nghiquyet",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "19/2016/nq-cp")

    def test_nghi_quyet_allows_no_space_after_so(self) -> None:
        components = extract_document_components(
            "Nghị quyết số111/2008/NQ-HĐND ngày 30/7/2008",
            "nghiquyet",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "111/2008/nq-hđnd")

    def test_old_thong_tu_authority_code_formats_are_preserved(self) -> None:
        cases = [
            ("Thông tư số 89-TC/TCT ngày 09 tháng 11 năm 1993", "89-tc/tct"),
            ("Thông tư số 06/TC-TCDN ngày 24/02/1997", "06/tc-tcdn"),
            ("Thông tư 108/TC", "108/tc"),
            ("Thông tư số 105/TCĐT ngày 08/12/1994", "105/tcđt"),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                components = extract_document_components(text, "thongtu", self.law_titles)
                self.assertIsNotNone(components)
                self.assertEqual(components["so_hieu"], expected)

    def test_old_nghi_quyet_without_nq_suffix_is_preserved(self) -> None:
        cases = [
            ("Nghị quyết của Chính phủ số 27/CP ngày 28 tháng 3 năm 1997", "27/cp"),
            ("Nghị quyết số 128/NQ", "128/nq"),
            ("Nghị quyết số 26-NQ", "26-nq"),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                components = extract_document_components(text, "nghiquyet", self.law_titles)
                self.assertIsNotNone(components)
                self.assertEqual(components["so_hieu"], expected)

    def test_old_chi_thi_without_ct_suffix_is_preserved(self) -> None:
        components = extract_document_components(
            "Chỉ thị số 115-TTg",
            "chithi",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "115-ttg")

    def test_phap_lenh_title_fallback_stops_before_promulgation_order(self) -> None:
        components = extract_document_components(
            "Pháp lệnh Ngân hàng, Hợp tác xã tín dụng và Công ty tài chính công bố theo lệnh số 37/LCT-HĐNN8",
            "phaplenh",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(
            components["tieu_de"],
            "pháp lệnh ngân hàng, hợp tác xã tín dụng và công ty tài chính",
        )

    def test_thong_tu_lien_tich_incomplete_ttl_suffix_normalizes_to_ttlt(self) -> None:
        components = extract_document_components(
            "Thông tư liên tịch số 02/2009/TTL",
            "thongtulientich",
            self.law_titles,
        )

        self.assertIsNotNone(components)
        self.assertEqual(components["so_hieu"], "02/2009/ttlt")


if __name__ == "__main__":
    unittest.main()
