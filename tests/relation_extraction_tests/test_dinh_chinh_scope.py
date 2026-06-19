import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def _tails_for_relation(results, relation):
    tails = []
    for group in results or []:
        for relation_group in group.get("relations", []):
            if relation_group.get("relation") == relation:
                tails.extend(relation_group.get("tail", []))
    return tails


def _refs_for_relation(predictions, relation):
    return [
        item["reference"]
        for item in predictions or []
        if item.get("relation") == relation
    ]


class TestDinhChinhScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )
        cls.law_titles = config.law_titles_for_regex

    def test_dinh_chinh_stops_before_downstream_legal_basis(self) -> None:
        content = (
            "Đính chính một số nội dung của Thông tư số 01/2020/TT-BTTTT "
            "ngày 07 tháng 02 năm 2020 của Bộ trưởng Bộ Thông tin và Truyền thông "
            "quy định chi tiết và hướng dẫn thi hành một số điều của Luật xuất bản "
            "và Nghị định số 195/2013/NĐ-CP ngày 21 tháng 11 năm 2013."
        )
        results = self.extractor.extract_relations(
            data=[{"com_type": "dieu", "com_key": "dieu_1", "com_title": content}],
            cls_so_hieu="99/2025/QH15",
            cls_title="",
            cls_document_type="Quyết định",
        )

        tails = _tails_for_relation(results, "dinh_chinh")
        tail_text = " ".join(str(tail) for tail in tails)

        self.assertEqual(len(tails), 1)
        self.assertIn("Thông tư số 01/2020/TT-BTTTT", tail_text)
        self.assertNotIn("Luật xuất bản", tail_text)
        self.assertNotIn("Nghị định số 195/2013/NĐ-CP", tail_text)

    def test_dinh_chinh_intro_stops_before_legal_basis_even_with_nhu_sau(self) -> None:
        content = (
            "Đính chính một số nội dung của Thông tư số 01/2020/TT-BTTTT "
            "ngày 07 tháng 02 năm 2020 của Bộ trưởng Bộ Thông tin và Truyền thông "
            "quy định chi tiết và hướng dẫn thi hành một số điều của Luật xuất bản "
            "và Nghị định số 195/2013/NĐ-CP ngày 21 tháng 11 năm 2013 của Chính phủ "
            "quy định chi tiết một số điều và biện pháp thi hành Luật xuất bản "
            "(sau đây viết tắt là “Thông tư số 01/2020/TT-BTTTT”) như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="476/QĐ-BTTTT",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = _refs_for_relation(predictions, "dinh_chinh")

        self.assertEqual(
            refs,
            ["Thông tư số 01/2020/TT-BTTTT ngày 07 tháng 02 năm 2020"],
        )

    def test_dinh_chinh_preserves_nearest_clause_scope_after_tai(self) -> None:
        content = (
            "Tại điểm b, khoản 6, Điều 4 Quyết định số 04/2016/QĐ-UBND "
            "ngày 23/3/2016: Sửa cụm từ \"Mục d, Khoản 2\" thành "
            "\"Mục d, Khoản 7\"."
        )
        results = self.extractor.extract_relations(
            data=[
                {
                    "com_type": "dieu",
                    "com_key": "dieu_1",
                    "com_title": "Điều 1. Đính chính một số nội dung sau đây:",
                },
                {"com_type": "khoan", "com_key": "khoan_1_dieu_1", "com_title": content},
            ],
            cls_so_hieu="99/2025/QH15",
            cls_title="",
            cls_document_type="Quyết định",
        )

        tails = _tails_for_relation(results, "dinh_chinh")
        self.assertEqual(len(tails), 1)
        self.assertIn("điểm b", str(tails[0]).lower())
        self.assertIn("khoản 6", str(tails[0]))
        self.assertIn("Điều 4", str(tails[0]))

    def test_dinh_chinh_maps_muc_letter_to_diem_under_parent_document(self) -> None:
        content = (
            "Tại Mục b, Khoản 6, Điều 4: Sửa cụm từ “Mục d, Khoản 2” "
            "thành “Mục d, Khoản 7”"
        )
        parent_content = (
            "Đính chính một số nội dung của “Quy chế phối hợp trong công tác phòng ngừa, "
            "xử lý vi phạm pháp luật về đê điều trên địa bàn tỉnh Hải Dương” ban hành "
            "kèm theo Quyết định số 04/2016/QĐ-UBND ngày 23/3/2016 của UBND tỉnh Hải Dương như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="2227/QĐ-UBND",
            title="",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = _refs_for_relation(predictions, "dinh_chinh")

        self.assertEqual(
            refs,
            [
                "điểm b khoản 6 Điều 4 Quyết định số 04/2016/QĐ-UBND ngày 23/3/2016",
            ],
        )

    def test_dinh_chinh_child_scope_uses_corrected_parent_document(self) -> None:
        content = (
            "1. Tại khoản 5 Điều 1 (sửa đổi, bổ sung điểm b khoản 3 và khoản 6 "
            "Điều 14 Thông tư số 23/2014/TT-NHNN), đính chính cụm từ "
            "“khách hàng, chi nhánh ngân hàng nước ngoài” thành “khách hàng, "
            "ngân hàng, chi nhánh ngân hàng nước ngoài”."
        )
        parent_content = (
            "Điều 1. Đính chính lỗi kỹ thuật trình bày tại Thông tư số 16/2020/TT-NHNN "
            "ngày 04 tháng 12 năm 2020 của Thống đốc Ngân hàng Nhà nước Việt Nam "
            "sửa đổi, bổ sung một số điều của Thông tư số 23/2014/TT-NHNN "
            "ngày 19 tháng 8 năm 2014 của Thống đốc Ngân hàng Nhà nước Việt Nam "
            "hướng dẫn việc mở và sử dụng tài khoản thanh toán tại tổ chức cung ứng "
            "dịch vụ thanh toán như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="2158/QĐ-NHNN",
            title="",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = _refs_for_relation(predictions, "dinh_chinh")

        self.assertEqual(
            refs,
            [
                "khoản 5 Điều 1 Thông tư số 16/2020/TT-NHNN ngày 04 tháng 12 năm 2020",
            ],
        )

    def test_dinh_chinh_intro_document_context_applies_after_nhu_sau(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật tại Thông tư số 10/2022/TT-BKHĐT "
            "ngày 15 tháng 6 năm 2022 của Bộ trưởng Bộ Kế hoạch và Đầu tư "
            "quy định chi tiết việc cung cấp, đăng tải thông tin và lựa chọn nhà đầu tư "
            "trên Hệ thống mạng đấu thầu quốc gia như sau:\r\n\r\n"
            "Cụm từ “nhà đầu tư” tại khoản 3 Điều 31 và khoản 2.c Bảng số 01 "
            "Chương II Phụ lục 4 kèm theo Thông tư số 10/2022/TT-BKHĐT "
            "được sửa thành “đối tác”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="1373/QĐ-BKHĐT",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = _refs_for_relation(predictions, "dinh_chinh")

        self.assertIn("Thông tư số 10/2022/TT-BKHĐT ngày 15 tháng 6 năm 2022", refs)
        self.assertTrue(
            any(
                ref.startswith("khoản 3 Điều 31 Thông tư số 10/2022/TT-BKHĐT")
                for ref in refs
            )
        )

    def test_dinh_chinh_intro_document_context_ignores_replacement_quote_documents(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật trình bày văn bản tại Thông tư số "
            "16/2021/TT-BTNMT ngày 27 tháng 9 năm 2021 của Bộ trưởng Bộ Tài nguyên "
            "và Môi trường quy định xây dựng định mức kinh tế - kỹ thuật thuộc phạm vi "
            "quản lý nhà nước của Bộ Tài nguyên và Môi trường như sau:\r\n\r\n"
            "Khoản 1 Điều 24 đã ban hành “Thông tư này có hiệu lực thi hành kể từ "
            "ngày 15 tháng 11 năm 2021 và thay thế Thông tư số 04/2017/TT-BTNMT "
            "ngày 03 tháng 4 năm 2017 của Bộ trưởng Bộ Tài nguyên và Môi trường "
            "quy định xây dựng định mức kinh tế - kỹ thuật ngành tài nguyên và môi trường”\r\n\r\n"
            "Sửa thành “Thông tư này có hiệu lực thi hành kể từ ngày 15 tháng 11 năm 2021.”"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="2361/QĐ-BTNMT",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        refs = _refs_for_relation(predictions, "dinh_chinh")

        self.assertIn(
            "khoản 1 Điều 24 Thông tư số 16/2021/TT-BTNMT ngày 27 tháng 9 năm 2021",
            refs,
        )
        self.assertNotIn(
            "khoản 1 Điều 24 Thông tư số 04/2017/TT-BTNMT ngày 03 tháng 4 năm 2017",
            refs,
        )


if __name__ == "__main__":
    unittest.main()
