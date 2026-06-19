import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


class TestQuyDinhChiTietTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_mixed_clause_ranges_inherit_law_anchor_across_semicolon(self) -> None:
        content = (
            "Nghị định này quy định chi tiết điểm d khoản 26 Điều 2, khoản 4 và 5 Điều 60 "
            "của Luật Dược số 105/2016/QH13; khoản 4, khoản 5, điểm a và c khoản 18, "
            "khoản 43 Điều 1 của Luật số 44/2024/QH15 sửa đổi, bổ sung một số điều "
            "của Luật Dược số 105/2016/QH13 (sau đây gọi chung là Luật Dược)"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="163/2025/NĐ-CP",
            title="",
            clause_type="khoan",
            content=content,
            parent_content="Phạm vi điều chỉnh và đối tượng áp dụng",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertEqual(
            qdct_refs,
            [
                "điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13",
                "khoản 4 Điều 60 Luật Dược số 105/2016/QH13",
                "khoản 5 Điều 60 Luật Dược số 105/2016/QH13",
                "khoản 4 Điều 1 Luật số 44/2024/QH15",
                "khoản 5 Điều 1 Luật số 44/2024/QH15",
                "điểm a khoản 18 Điều 1 Luật số 44/2024/QH15",
                "điểm c khoản 18 Điều 1 Luật số 44/2024/QH15",
                "khoản 43 Điều 1 Luật số 44/2024/QH15",
            ],
        )

    def test_pham_vi_dieu_chinh_heading_does_not_mask_quy_dinh_chi_tiet(self) -> None:
        content = (
            "Điều 1. Phạm vi điều chỉnh Nghị định này quy định chi tiết và "
            "biện pháp thi hành một số điều của Luật Bảo hiểm xã hội số 41/2024/QH15."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="157/2025/NĐ-CP",
            title="Nghị định quy định chi tiết Luật Bảo hiểm xã hội",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertIn("Luật Bảo hiểm xã hội số 41/2024/QH15", qdct_refs)

    def test_detail_target_excludes_amendment_history_laws(self) -> None:
        content = (
            "1. Quy định chi tiết Điều 27 Luật Đường sắt số 95/2025/QH15 "
            "được sửa đổi, bổ sung bởi khoản 3 Điều 50 Luật Đầu tư số "
            "143/2025/QH15 và khoản 1 Điều 55 Luật Quy hoạch số 112/2025/QH15 "
            "(sau đây gọi là Luật Đường sắt số 95/2025/QH15) về thiết kế "
            "kỹ thuật tổng thể."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="67/2026/NĐ-CP",
            title=(
                "Nghị định quy định chi tiết và biện pháp thi hành về thiết kế "
                "kỹ thuật tổng thể của dự án đầu tư xây dựng tuyến đường sắt "
                "quốc gia, tuyến đường sắt địa phương"
            ),
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 1. Phạm vi điều chỉnh\r\n"
                "Nghị định này quy định về các nội dung sau:"
            ),
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertEqual(
            qdct_refs,
            ["Điều 27 Luật Đường sắt số 95/2025/QH15"],
        )
        self.assertNotIn("Luật Quy hoạch số 112/2025/QH15", qdct_refs)

    def test_detail_bao_gom_list_inherits_document_to_parenthesized_clauses(self) -> None:
        content = (
            "Thông tư này quy định chi tiết một số điều của Luật Giám định tư pháp "
            "số 105/2025/QH15 về việc giám định tư pháp trong lĩnh vực nội vụ, bao gồm:\r\n"
            "1. Tiêu chuẩn giám định viên tư pháp (khoản 2 Điều 10);\r\n"
            "2. Tổ chức giám định tư pháp theo vụ việc (khoản 3 Điều 18);\r\n"
            "3. Trình tự, thủ tục tiếp nhận trưng cầu, thực hiện giám định tư pháp; "
            "danh mục lĩnh vực chuyên môn, chuyên ngành giám định (khoản 5 Điều 28);\r\n"
            "4. Thời hạn giám định tư pháp (khoản 2 Điều 30);\r\n"
            "5. Thành phần hồ sơ và chế độ lưu trữ hồ sơ giám định tư pháp "
            "(khoản 2 Điều 37)."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="5/2026/TT-BNV",
            title="Thông tư quy định giám định tư pháp trong lĩnh vực nội vụ",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertEqual(
            qdct_refs,
            [
                "khoản 2 Điều 10 Luật Giám định tư pháp số 105/2025/QH15",
                "khoản 3 Điều 18 Luật Giám định tư pháp số 105/2025/QH15",
                "khoản 5 Điều 28 Luật Giám định tư pháp số 105/2025/QH15",
                "khoản 2 Điều 30 Luật Giám định tư pháp số 105/2025/QH15",
                "khoản 2 Điều 37 Luật Giám định tư pháp số 105/2025/QH15",
            ],
        )

    def test_nested_detail_guidance_titles_are_not_current_relations(self) -> None:
        cases = [
            {
                "so_hieu": "154/2013/NĐ-CP",
                "title": "Nghị định quy định về khu công nghệ thông tin tập trung",
                "content": (
                    "Các quy định tại Chương III Nghị định số 71/2007/NĐ-CP "
                    "ngày 03 tháng 5 năm 2007 của Chính phủ quy định chi tiết "
                    "và hướng dẫn thực hiện một số điều của Luật công nghệ thông tin "
                    "về công nghiệp công nghệ thông tin hết hiệu lực kể từ ngày "
                    "Nghị định này có hiệu lực thi hành."
                ),
            },
            {
                "so_hieu": "278/2025/NĐ-CP",
                "title": (
                    "Nghị định quy định về kết nối, chia sẻ dữ liệu bắt buộc "
                    "giữa các cơ quan thuộc hệ thống chính trị"
                ),
                "content": (
                    "Sửa đổi khoản 1, khoản 2 Điều 14 Nghị định số 165/2025/NĐ-CP "
                    "ngày 30 tháng 6 năm 2025 của Chính phủ quy định chi tiết một số "
                    "điều và biện pháp thi hành Luật Dữ liệu như sau:"
                ),
            },
        ]

        for case in cases:
            with self.subTest(so_hieu=case["so_hieu"]):
                predictions = extract_single_clause(
                    extractor=self.extractor,
                    so_hieu=case["so_hieu"],
                    title=case["title"],
                    clause_type="dieu",
                    content=case["content"],
                    parent_content="",
                    grandparent_content="",
                    idx=1,
                    law_titles=self.law_titles,
                )
                relation_refs = {
                    (item["relation"], item["reference"])
                    for item in predictions
                    if item["relation"] in {"quy_dinh_chi_tiet", "huong_dan"}
                }

                self.assertEqual(relation_refs, set())

    def test_quoted_amendment_detail_scope_does_not_expand_across_semicolon(self) -> None:
        content = (
            "1. Sửa đổi, bổ sung Điều 1 như sau:\r\n\r\n"
            "“1. Quy định chi tiết thi hành điểm a khoản 2 và điểm b khoản 3 Điều 8; "
            "khoản 7 Điều 10 của Luật Bảo vệ môi trường."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="07/2025/TT-BTNMT",
            title="",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 1. Sửa đổi, bổ sung một số điều của Thông tư số 02/2022/TT-BTNMT "
                "quy định chi tiết thi hành một số điều của Luật Bảo vệ môi trường"
            ),
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertNotIn(
            "điểm a khoản 2 Điều 8 Luật Bảo vệ môi trường",
            qdct_refs,
        )
        self.assertNotIn(
            "điểm b khoản 3 Điều 8 Luật Bảo vệ môi trường",
            qdct_refs,
        )
        self.assertNotIn(
            "khoản 7 Điều 10 Luật Bảo vệ môi trường",
            qdct_refs,
        )

    def test_alias_parentheses_are_not_detail_targets(self) -> None:
        content = (
            "Điều 1. Phạm vi điều chỉnh\r\n"
            "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của "
            "Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số "
            "điều của Luật Dược ngày 21 tháng 11 năm 2024 (sau đây gọi là Luật Dược), bao gồm:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư quy định về đăng ký thuốc cổ truyền",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertEqual(
            qdct_refs,
            [
                "Luật Dược ngày 06 tháng 4 năm 2016",
                "Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024",
            ],
        )

    def test_detail_parent_can_promote_child_theo_quy_dinh_refs(self) -> None:
        content = (
            "1. Thông báo, cập nhật, công khai danh sách Người có chứng chỉ hành nghề dược "
            "theo quy định tại điểm g khoản 2 Điều 42 của Luật Dược; danh sách các nhà thuốc "
            "trong chuỗi nhà thuốc và việc luân chuyển người chịu trách nhiệm chuyên môn về "
            "dược giữa các nhà thuốc trong chuỗi nhà thuốc theo quy định tại điểm g khoản 2 "
            "Điều 47a của Luật Dược."
        )
        parent_content = (
            "Điều 1. Phạm vi điều chỉnh\r\n"
            "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược "
            "ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số điều của Luật Dược "
            "ngày 21 tháng 11 năm 2024 (sau đây viết tắt là Luật Dược) và Nghị định số "
            "163/2025/NĐ-CP ngày 29 tháng 6 năm 2025 của Chính phủ quy định chi tiết một "
            "số điều và biện pháp để tổ chức, hướng dẫn thi hành Luật Dược, bao gồm:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="31/2025/TT-BYT",
            title="Thông tư quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            qdct_refs,
            [
                "điểm g khoản 2 Điều 42 Luật Dược",
                "điểm g khoản 2 Điều 47a Luật Dược",
            ],
        )
        self.assertEqual(dan_chieu_refs, [])

    def test_compound_clause_references_inherit_detail_relation_from_parent(self) -> None:
        content = (
            "3. Bán thuốc thuộc Danh mục thuốc hạn chế bán lẻ theo quy định tại "
            "khoản 2 Điều 34 và điểm k khoản 2 Điều 42 của Luật Dược."
        )
        parent_content = (
            "Điều 1. Phạm vi điều chỉnh\r\n"
            "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của "
            "Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số "
            "điều của Luật Dược ngày 21 tháng 11 năm 2024 (sau đây viết tắt là "
            "Luật Dược) và Nghị định số 163/2025/NĐ-CP ngày 29 tháng 6 năm 2025 "
            "của Chính phủ quy định chi tiết một số điều và biện pháp để tổ chức, "
            "hướng dẫn thi hành Luật Dược (sau đây viết tắt là Nghị định số "
            "163/2025/NĐ-CP), bao gồm:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="31/2025/TT-BYT",
            title="Thông tư quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertEqual(
            qdct_refs,
            [
                "khoản 2 Điều 34 Luật Dược",
                "điểm k khoản 2 Điều 42 Luật Dược",
            ],
        )

    def test_numeric_diem_reference_combines_with_resolution_target(self) -> None:
        content = (
            "Điều 14. Phạm vi điều chỉnh\r\n"
            "Nghị định này quy định chi tiết và hướng dẫn thi hành một số điều của "
            "Luật Bảo hiểm xã hội về bảo hiểm xã hội bắt buộc và chế độ đối với "
            "người lao động không đủ điều kiện hưởng lương hưu và chưa đủ tuổi hưởng "
            "trợ cấp hưu trí xã hội; điểm 13 của Nghị quyết số 142/2024/QH15 "
            "ngày 29 tháng 6 năm 2024."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="158/2025/NĐ-CP",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        qdct_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "quy_dinh_chi_tiet"
        ]

        self.assertIn(
            "điểm 13 Nghị quyết số 142/2024/QH15 ngày 29 tháng 6 năm 2024",
            qdct_refs,
        )


if __name__ == "__main__":
    unittest.main()
