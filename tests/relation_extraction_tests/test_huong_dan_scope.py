import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


class TestHuongDanScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_huong_dan_thuc_hien_extracts_concrete_sources(self) -> None:
        content = (
            "Phạm vi điều chỉnh\r\n"
            "Thông tư này hướng dẫn thực hiện các chế độ bảo hiểm xã hội bắt buộc "
            "và thực hiện quản lý thu, đóng bảo hiểm xã hội đối với sĩ quan, hạ sĩ quan, "
            "chiến sĩ Công an nhân dân theo quy định của Luật Bảo hiểm xã hội và "
            "Nghị định số 157/2025/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="88/2025/TT-BCA",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        huong_dan_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "huong_dan"
        ]

        self.assertEqual(
            huong_dan_refs,
            [
                "Luật Bảo hiểm xã hội",
                "Nghị định số 157/2025/NĐ-CP",
            ],
        )

    def test_old_law_guiding_documents_are_not_current_huong_dan_targets(self) -> None:
        content = (
            "Các văn bản quy định chi tiết, hướng dẫn thi hành "
            "Luật Hóa chất số 06/2007/QH12 được tiếp tục áp dụng đến hết "
            "ngày 31 tháng 12 năm 2026 nếu không trái với quy định của Luật này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="69/2025/QH15",
            title="Luật Hóa chất",
            clause_type="khoan",
            content=content,
            parent_content="Điều 94. Quy định chuyển tiếp",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        detail_guidance_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] in {"huong_dan", "quy_dinh_chi_tiet"}
        ]

        self.assertEqual(detail_guidance_refs, [])

    def test_old_law_and_its_guiding_documents_tail_is_not_huong_dan(self) -> None:
        content = (
            "Luật Điện lực số 28/2004/QH11 đã được sửa đổi, bổ sung một số điều "
            "theo Luật số 24/2012/QH13, Luật số 28/2018/QH14, Luật số 03/2022/QH15, "
            "Luật số 16/2023/QH15 và Luật số 35/2024/QH15 và các văn bản quy định "
            "chi tiết, hướng dẫn thi hành hết hiệu lực từ ngày Luật này có hiệu lực thi hành."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="61/2024/QH15",
            title="Luật Điện lực",
            clause_type="khoan",
            content=content,
            parent_content="Điều 81. Hiệu lực thi hành",
            grandparent_content="",
            idx=5,
            law_titles=self.law_titles,
        )
        huong_dan_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "huong_dan"
        ]

        self.assertNotIn("Luật Điện lực số 28/2004/QH11", huong_dan_refs)


if __name__ == "__main__":
    unittest.main()
