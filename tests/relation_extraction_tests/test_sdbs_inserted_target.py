import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


class TestSuaDoiBoSungInsertedTarget(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_bo_sung_diem_targets_inserted_point_not_after_anchor(self) -> None:
        content = (
            "Bổ sung điểm d vào sau điểm c khoản 1 Điều 34 của Luật Khám bệnh, "
            "chữa bệnh số 15/2023/QH15 như sau:“d) Có hành vi thông báo, tiết lộ "
            "giới tính thai nhi để phá thai.”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="113/2025/QH15",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Sửa đổi, bổ sung một số điều của các luật có liên quan đến công tác dân số",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "bo_sung"
        ]

        self.assertEqual(
            sdbs_refs,
            ["điểm d khoản 1 Điều 34 Luật Khám bệnh, chữa bệnh số 15/2023/QH15"],
        )

    def test_multi_inserted_points_share_same_anchor_document(self) -> None:
        content = (
            "c) Bổ sung điểm e1 và điểm e2 vào sau điểm e khoản 2 Điều 12 như sau:"
            "“e1) Trung tâm nghiên cứu và phát triển công nghệ chiến lược;"
            "e2) Doanh nghiệp sản xuất sản phẩm công nghệ cao;”;"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="133/2025/QH21",
            title="",
            clause_type="diem",
            content=content,
            parent_content=(
                "7. Sửa đổi, bổ sung một số điều của Luật Thuế thu nhập doanh nghiệp "
                "số 67/2025/QH15 và Luật số 116/2025/QH15 như sau:"
            ),
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "bo_sung"
        ]

        self.assertIn(
            "điểm e1 khoản 2 Điều 12 Luật Thuế thu nhập doanh nghiệp số 67/2025/QH15",
            sdbs_refs,
        )
        self.assertIn(
            "điểm e2 khoản 2 Điều 12 Luật Thuế thu nhập doanh nghiệp số 67/2025/QH15",
            sdbs_refs,
        )
        self.assertNotIn(
            "điểm e2 khoản 2 Điều 12 Luật số 116/2025/QH15",
            sdbs_refs,
        )
        self.assertNotIn(
            "điểm e khoản 2 Điều 12 Luật Thuế thu nhập doanh nghiệp số 67/2025/QH15",
            sdbs_refs,
        )

    def test_inserted_khoan_uses_first_concrete_parent_target(self) -> None:
        content = (
            "d) Bổ sung khoản 1a vào sau khoản 1 Điều 13 như sau:"
            "“1a. Thu nhập từ hoạt động đổi mới sáng tạo được ưu đãi theo quy định "
            "của pháp luật.”;"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="133/2025/QH15",
            title="",
            clause_type="diem",
            content=content,
            parent_content=(
                "7. Sửa đổi, bổ sung một số điều của Luật Thuế thu nhập doanh nghiệp "
                "số 67/2025/QH15 và Luật số 116/2025/QH15 như sau:"
            ),
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "bo_sung"
        ]

        self.assertIn(
            "khoản 1a Điều 13 Luật Thuế thu nhập doanh nghiệp số 67/2025/QH15",
            sdbs_refs,
        )
        self.assertNotIn(
            "khoản 1a Điều 13 Luật số 116/2025/QH15",
            sdbs_refs,
        )

    def test_inserted_article_after_anchor_targets_existing_article(self) -> None:
        content = (
            "b) Bổ sung Điều 51a vào sau Điều 51:"
            "“Bộ trưởng, Thủ trưởng cơ quan ngang Bộ quyết định xuất cấp hàng "
            "dự trữ quốc gia phục vụ công tác phòng thủ dân sự theo thẩm quyền "
            "quy định của pháp luật về dự trữ quốc gia”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="145/2025/QH15",
            title="Luật Dự trữ quốc gia",
            clause_type="diem",
            content=content,
            parent_content=(
                "1. Sửa đổi, bổ sung Luật Phòng thủ dân sự số 18/2023/QH15 "
                "đã được sửa đổi, bổ sung một số điều theo Luật số 98/2025/QH15 "
                "như sau:"
            ),
            grandparent_content=(
                "Điều 34. Sửa đổi, bổ sung một số điều, khoản của các luật "
                "có liên quan đến dự trữ quốc gia"
            ),
            idx=34,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "bo_sung"
        ]

        self.assertIn(
            "Điều 51a Luật Phòng thủ dân sự số 18/2023/QH15",
            sdbs_refs,
        )
        self.assertNotIn(
            "Điều 51 Luật Phòng thủ dân sự số 18/2023/QH15",
            sdbs_refs,
        )

    def test_amendment_history_laws_do_not_become_sdbs_targets(self) -> None:
        content = (
            "2. Sửa đổi, bổ sung một số điều, khoản, điểm của Luật Nhà ở "
            "số 27/2023/QH15 đã được sửa đổi, bổ sung một số điều theo "
            "Luật số 43/2024/QH15, Luật số 47/2024/QH15, Luật số 84/2025/QH15, "
            "Luật số 90/2025/QH15 và Luật số 93/2025/QH15 như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="113/2025/QH15",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Điều 1. Sửa đổi, bổ sung một số điều của các luật có liên quan đến công tác dân số",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "sua_doi_bo_sung"
        ]

        self.assertIn("Luật Nhà ở số 27/2023/QH15", sdbs_refs)
        self.assertNotIn("Luật số 93/2025/QH15", sdbs_refs)

    def test_phrase_level_bo_cum_tu_keeps_later_tai_clause_as_sdbs(self) -> None:
        content = (
            "4. Bỏ cụm từ “hóa đơn” tại phần Tên, Căn cứ ban hành, Chương 1, "
            "điểm b khoản 2 Điều 41, khoản 2 Điều 45; cụm từ "
            "“trong lĩnh vực hóa đơn là 01 năm” tại khoản 1 Điều 4 "
            "Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013 của Chính phủ "
            "quy định xử phạt vi phạm hành chính trong lĩnh vực quản lý giá, phí, "
            "lệ phí, hóa đơn."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="125/2020/NĐ-CP",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Điều 44. Hiệu lực thi hành",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "sua_doi"
        ]

        self.assertEqual(
            sdbs_refs,
            [
                "điểm b khoản 2 Điều 41 Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013",
                "khoản 2 Điều 45 Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013",
                "khoản 1 Điều 4 Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013",
            ],
        )
        self.assertNotIn("dan_chieu", {item["relation"] for item in predictions})

    def test_phrase_level_bo_cum_tu_can_cross_semicolon_before_first_target(self) -> None:
        content = (
            "5. Bỏ cụm từ “hóa đơn” tại phần Tên, Căn cứ ban hành; khoản 2, 3 Điều 4; "
            "cụm từ “đình chỉ quyền tự in hóa đơn, quyền khởi tạo hóa đơn điện tử; "
            "đình chỉ in hóa đơn”, “hủy các hóa đơn; thực hiện thủ tục phát hành hóa đơn "
            "theo quy định” tại khoản 1 Điều 1 Nghị định số 49/2016/NĐ-CP ngày 27 tháng 5 "
            "năm 2016 của Chính phủ sửa đổi, bổ sung một số điều của Nghị định số "
            "109/2013/NĐ-CP ngày 24 tháng 9 năm 2013 của Chính phủ quy định xử phạt "
            "vi phạm hành chính trong lĩnh vực quản lý giá, phí, lệ phí, hóa đơn."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="125/2020/NĐ-CP",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Điều 44. Hiệu lực thi hành",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "sua_doi"
        ]

        self.assertEqual(
            sdbs_refs,
            [
                "khoản 2 Điều 4 Nghị định số 49/2016/NĐ-CP ngày 27 tháng 5 năm 2016",
                "khoản 3 Điều 4 Nghị định số 49/2016/NĐ-CP ngày 27 tháng 5 năm 2016",
                "khoản 1 Điều 1 Nghị định số 49/2016/NĐ-CP ngày 27 tháng 5 năm 2016",
            ],
        )


class TestSprint23ActionRelationExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def _extract_diem(
        self,
        *,
        so_hieu: str,
        title: str,
        content: str,
        parent_content: str,
        grandparent_content: str,
    ) -> list:
        return extract_single_clause(
            extractor=self.extractor,
            so_hieu=so_hieu,
            title=title,
            clause_type="diem",
            content=content,
            parent_content=parent_content,
            grandparent_content=grandparent_content,
            idx=1,
            law_titles=self.law_titles,
        )

    def test_chapter_scoped_expiry_collapsed_to_document_is_sua_doi_bo_sung(self) -> None:
        predictions = self._extract_diem(
            so_hieu="125/2020/NĐ-CP",
            title="Nghị định quy định xử phạt vi phạm hành chính về thuế, hóa đơn",
            parent_content=(
                "3. Kể từ ngày Nghị định này có hiệu lực thi hành, quy định tại các "
                "Nghị định, Thông tư sau đây hết hiệu lực thi hành:"
            ),
            grandparent_content="Điều 44. Hiệu lực thi hành",
            content=(
                "a) Chương I và Chương III Nghị định số 129/2013/NĐ-CP ngày 16 tháng "
                "10 năm 2013 của Chính phủ quy định về xử phạt vi phạm hành chính về "
                "thuế và cưỡng chế thi hành quyết định hành chính thuế;"
            ),
        )

        self.assertIn(
            {
                "reference": "Nghị định số 129/2013/NĐ-CP ngày 16 tháng 10 năm 2013",
                "relation": "sua_doi_bo_sung",
            },
            predictions,
        )
        self.assertNotIn("bai_bo", {item["relation"] for item in predictions})

    def test_clause_scoped_same_decree_expiry_is_thay_the_without_chapter_targets(self) -> None:
        predictions = self._extract_diem(
            so_hieu="125/2020/NĐ-CP",
            title="Nghị định quy định xử phạt vi phạm hành chính về thuế, hóa đơn",
            parent_content=(
                "3. Kể từ ngày Nghị định này có hiệu lực thi hành, quy định tại các "
                "Nghị định, Thông tư sau đây hết hiệu lực thi hành:"
            ),
            grandparent_content="Điều 44. Hiệu lực thi hành",
            content=(
                "b) Khoản 2 Điều 4 Chương 1, Chương 4, Điều 44 Chương 5 Nghị định số "
                "109/2013/NĐ-CP ngày 24 tháng 9 năm 2013 của Chính phủ quy định xử "
                "phạt vi phạm hành chính trong lĩnh vực quản lý giá, phí, lệ phí, hóa đơn;"
            ),
        )

        thay_the_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "thay_the"
        ]

        self.assertEqual(
            thay_the_refs,
            [
                "khoản 2 Điều 4 Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013",
                "Điều 44 Nghị định số 109/2013/NĐ-CP ngày 24 tháng 9 năm 2013",
            ],
        )
        self.assertTrue(all("Chương" not in ref for ref in thay_the_refs))

    def test_thong_tu_title_match_expiry_point_a_is_thay_the(self) -> None:
        predictions = self._extract_diem(
            so_hieu="83/2025/TT-NHNN",
            title=(
                "Thông tư quy định về hệ thống kiểm soát nội bộ của ngân hàng thương "
                "mại, chi nhánh ngân hàng nước ngoài do Thống đốc Ngân hàng Nhà nước "
                "Việt Nam ban hành"
            ),
            parent_content=(
                "6. Kể từ ngày 01 tháng 07 năm 2026, Thông tư này bãi bỏ các quy định "
                "sau đây:"
            ),
            grandparent_content="Điều X. Hiệu lực thi hành",
            content=(
                "a) Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018 của Thống đốc "
                "Ngân hàng Nhà nước Việt Nam quy định về hệ thống kiểm soát nội bộ của "
                "ngân hàng thương mại, chi nhánh ngân hàng nước ngoài;"
            ),
        )

        self.assertIn(
            {
                "reference": "Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018",
                "relation": "thay_the",
            },
            predictions,
        )

    def test_sdbs_document_list_crosses_semicolon_in_same_sentence(self) -> None:
        content = (
            "3. Sửa đổi, bổ sung một số điều của Nghị định số 06/2021/NĐ-CP "
            "ngày 26 tháng 01 năm 2021 của Chính phủ hướng dẫn về quản lý chất lượng, "
            "thi công xây dựng và bảo trì công trình xây dựng; Nghị định số "
            "175/2024/NĐ-CP ngày 30 tháng 12 năm 2024 của Chính phủ quy định chi tiết "
            "một số điều và biện pháp thi hành Luật Xây dựng về quản lý hoạt động xây dựng; "
            "Nghị định số 123/2025/NĐ-CP ngày 11 tháng 6 năm 2025 của Chính phủ "
            "quy định chi tiết về thiết kế kỹ thuật tổng thể và cơ chế đặc thù cho "
            "một số dự án đường sắt."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="67/2026/NĐ-CP",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Điều 1. Phạm vi điều chỉnh\r\nNghị định này quy định về các nội dung sau:",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "sua_doi_bo_sung"
        ]

        self.assertEqual(
            sdbs_refs,
            [
                "Nghị định số 06/2021/NĐ-CP ngày 26 tháng 01 năm 2021",
                "Nghị định số 175/2024/NĐ-CP ngày 30 tháng 12 năm 2024",
                "Nghị định số 123/2025/NĐ-CP ngày 11 tháng 6 năm 2025",
            ],
        )

    def test_alphanumeric_khoan_targets_are_preserved(self) -> None:
        content = (
            "c) Sửa đổi, bổ sung khoản 1a Điều 42 như sau:"
            "“1a. Các nhà đầu tư sau đây không phải chứng minh khả năng thu xếp vốn chủ sở hữu.”;"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="133/2025/QH18",
            title="",
            clause_type="diem",
            content=content,
            parent_content=(
                "7. Sửa đổi, bổ sung một số điều của Luật Đầu tư theo phương thức đối tác "
                "công tư số 64/2020/QH14 như sau:"
            ),
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        sdbs_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "sua_doi"
        ]

        self.assertIn(
            "khoản 1a Điều 42 Luật Đầu tư theo phương thức đối tác công tư số 64/2020/QH14",
            sdbs_refs,
        )
        self.assertNotIn(
            "khoản 1 Điều 42 Luật Đầu tư theo phương thức đối tác công tư số 64/2020/QH14",
            sdbs_refs,
        )

    def test_inherited_parent_document_for_91_2014_alphanumeric_khoan_targets(self) -> None:
        parent_content = (
            "Điều 1. Sửa đổi, bổ sung Nghị định số 218/2013/NĐ-CP ngày "
            "26 tháng 12 năm 2013 của Chính phủ quy định chi tiết và hướng dẫn "
            "thi hành Luật Thuế thu nhập doanh nghiệp như sau:"
        )
        cases = [
            (
                "7. Bổ sung Khoản 5a Điều 19 như sau:"
                "“5a. Đối với dự án đầu tư được cấp phép đầu tư mà trong Hồ sơ "
                "đăng ký đầu tư lần đầu gửi cơ quan cấp phép đầu tư đã đăng ký "
                "số vốn đầu tư.”",
                "khoản 5a Điều 19 Nghị định số 218/2013/NĐ-CP ngày 26 tháng 12 năm 2013",
            ),
            (
                "8. Bổ sung Khoản 5b Điều 19 như sau:"
                "“5b. Doanh nghiệp còn thời gian hưởng ưu đãi thuế theo điều kiện "
                "về tỷ lệ xuất khẩu thì được lựa chọn ưu đãi.”",
                "khoản 5b Điều 19 Nghị định số 218/2013/NĐ-CP ngày 26 tháng 12 năm 2013",
            ),
        ]

        for content, expected_reference in cases:
            with self.subTest(expected_reference=expected_reference):
                predictions = extract_single_clause(
                    extractor=self.extractor,
                    so_hieu="91/2014/NĐ-CP",
                    title="Nghị định sửa đổi các Nghị định quy định về thuế",
                    clause_type="khoan",
                    content=content,
                    parent_content=parent_content,
                    grandparent_content="",
                    idx=1,
                    law_titles=self.law_titles,
                )
                sdbs_refs = [
                    item["reference"]
                    for item in predictions
                    if item["relation"] == "bo_sung"
                ]

                self.assertEqual(sdbs_refs, [expected_reference])


if __name__ == "__main__":
    unittest.main()
