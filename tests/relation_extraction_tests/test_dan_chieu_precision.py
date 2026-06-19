import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def _flat_relations(
    extractor,
    law_titles,
    *,
    so_hieu,
    clause_type,
    content,
    parent_content="",
    grandparent_content="",
    title="",
    cls_document_type="",
):
    return extract_single_clause(
        extractor=extractor,
        so_hieu=so_hieu,
        title=title,
        clause_type=clause_type,
        content=content,
        parent_content=parent_content,
        grandparent_content=grandparent_content,
        idx=1,
        law_titles=law_titles,
        cls_document_type=cls_document_type,
    )


def _flatten_extracted_relation_groups(groups):
    flattened = []
    for group in groups or []:
        for relation_group in group.get("relations", []):
            for tail in relation_group.get("tail", []):
                flattened.append(
                    {
                        "clause_key": group.get("clause_key"),
                        "relation": relation_group.get("relation"),
                        "reference": " ".join(
                            value.get("information", "")
                            for value in tail.values()
                            if isinstance(value, dict)
                        ),
                    }
                )
    return flattened


class TestDanChieuPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_scope_heading_huong_dan_does_not_emit_dan_chieu(self) -> None:
        content = (
            "Phạm vi điều chỉnh\r\n"
            "Thông tư này hướng dẫn thực hiện các chế độ bảo hiểm xã hội bắt buộc "
            "và thực hiện quản lý thu, đóng bảo hiểm xã hội đối với sĩ quan, hạ sĩ quan, "
            "chiến sĩ Công an nhân dân theo quy định của Luật Bảo hiểm xã hội và "
            "Nghị định số 157/2025/NĐ-CP."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="88/2025/TT-BCA",
            clause_type="dieu",
            content=content,
        )

        self.assertNotIn("dan_chieu", {item["relation"] for item in predictions})

    def test_theo_internal_multi_point_refs_are_kept_as_dan_chieu(self) -> None:
        data = [
            {
                "com_key": "dieu_18",
                "com_type": "dieu",
                "com_title": "Điều 18. Yêu cầu giải quyết khiếu nại, tố cáo",
            },
            {
                "com_key": "khoan_2_dieu_18",
                "com_type": "khoan",
                "com_title": "2. Các căn cứ yêu cầu giải quyết.",
            },
            {
                "com_key": "diem_a_khoan_2_dieu_18",
                "com_type": "diem",
                "com_title": "a) Căn cứ thứ nhất.",
            },
            {
                "com_key": "diem_b_khoan_2_dieu_18",
                "com_type": "diem",
                "com_title": "b) Căn cứ thứ hai.",
            },
            {
                "com_key": "diem_c_khoan_2_dieu_18",
                "com_type": "diem",
                "com_title": (
                    "c) Viện kiểm sát có căn cứ xác định việc Tòa án có dấu hiệu "
                    "vi phạm pháp luật trong khi giải quyết.\n"
                    "Trong thời hạn 15 ngày, kể từ ngày nhận được yêu cầu của "
                    "Viện kiểm sát theo hướng dẫn tại các điểm a, b và c khoản 2 "
                    "Điều này, Tòa án được yêu cầu phải xem xét, giải quyết."
                ),
                "com_content": (
                    "c) Viện kiểm sát có căn cứ xác định việc Tòa án có dấu hiệu "
                    "vi phạm pháp luật trong khi giải quyết.\n"
                    "Trong thời hạn 15 ngày, kể từ ngày nhận được yêu cầu của "
                    "Viện kiểm sát theo hướng dẫn tại các điểm a, b và c khoản 2 "
                    "Điều này, Tòa án được yêu cầu phải xem xét, giải quyết."
                ),
            },
        ]

        predictions = _flatten_extracted_relation_groups(
            self.extractor.extract_relations(
                data=data,
                cls_so_hieu="03/2012/TTLT-VKSNDTC-TANDTC",
                cls_title="",
                cls_document_type="Thông tư liên tịch",
            )
        )
        references = {
            item["reference"]
            for item in predictions
            if item["clause_key"] == "diem_c_khoan_2_dieu_18"
            and item["relation"] == "dan_chieu"
        }

        self.assertEqual(
            references,
            {
                "điểm a khoản 2 Điều 18 Thông tư liên tịch 03/2012/TTLT-VKSNDTC-TANDTC",
                "điểm b khoản 2 Điều 18 Thông tư liên tịch 03/2012/TTLT-VKSNDTC-TANDTC",
                "điểm c khoản 2 Điều 18 Thông tư liên tịch 03/2012/TTLT-VKSNDTC-TANDTC",
            },
        )

    def test_effective_date_document_self_refs_stay_filtered(self) -> None:
        data = [
            {
                "com_key": "dieu_20",
                "com_type": "dieu",
                "com_title": (
                    "Điều 20. Hiệu lực thi hành\n"
                    "Thông tư liên tịch này có hiệu lực thi hành kể từ ngày "
                    "15 tháng 9 năm 2012.\n"
                    "Những hướng dẫn trước đây về những vấn đề được hướng dẫn "
                    "trong Thông tư liên tịch này hết hiệu lực thi hành."
                ),
                "com_content": (
                    "Điều 20. Hiệu lực thi hành\n"
                    "Thông tư liên tịch này có hiệu lực thi hành kể từ ngày "
                    "15 tháng 9 năm 2012.\n"
                    "Những hướng dẫn trước đây về những vấn đề được hướng dẫn "
                    "trong Thông tư liên tịch này hết hiệu lực thi hành."
                ),
            }
        ]

        predictions = _flatten_extracted_relation_groups(
            self.extractor.extract_relations(
                data=data,
                cls_so_hieu="03/2012/TTLT-VKSNDTC-TANDTC",
                cls_title="",
                cls_document_type="Thông tư liên tịch",
            )
        )

        self.assertNotIn("dan_chieu", {item["relation"] for item in predictions})

    def test_dinh_chinh_correction_sentence_does_not_emit_dan_chieu(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật tại Thông tư số 10/2022/TT-BKHĐT "
            "ngày 15 tháng 6 năm 2022 của Bộ trưởng Bộ Kế hoạch và Đầu tư quy định chi tiết "
            "việc cung cấp, đăng tải thông tin và lựa chọn nhà đầu tư trên Hệ thống mạng đấu thầu "
            "quốc gia như sau:\r\n\r\n"
            "Cụm từ “nhà đầu tư” tại khoản 3 Điều 31 và khoản 2.c Bảng số 01 Chương II "
            "Phụ lục 4 kèm theo Thông tư số 10/2022/TT-BKHĐT được sửa thành “đối tác”."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="1373/QĐ-BKHĐT",
            clause_type="dieu",
            content=content,
        )

        self.assertNotIn("dan_chieu", {item["relation"] for item in predictions})

    def test_object_scope_keeps_internal_articles_separate_from_external_docs(self) -> None:
        content = (
            "3. Các quy định tại Điều 30, Điều 31, Điều 32 của Nghị định này áp dụng đối với "
            "đối tượng áp dụng tương ứng quy định tại Nghị định số 06/2021/NĐ-CP ngày 26 tháng 01 năm 2021, "
            "Nghị định số 175/2024/NĐ-CP ngày 30 tháng 12 năm 2024 và "
            "Nghị định số 123/2025/NĐ-CP ngày 11 tháng 6 năm 2025."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="67/2026/NĐ-CP",
            clause_type="khoan",
            content=content,
            parent_content="Điều 2. Đối tượng áp dụng",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            [
                "Nghị định số 06/2021/NĐ-CP ngày 26 tháng 01 năm 2021",
                "Nghị định số 175/2024/NĐ-CP ngày 30 tháng 12 năm 2024",
                "Nghị định số 123/2025/NĐ-CP ngày 11 tháng 6 năm 2025",
                "Điều 30 Nghị định 67/2026/NĐ-CP",
                "Điều 31 Nghị định 67/2026/NĐ-CP",
                "Điều 32 Nghị định 67/2026/NĐ-CP",
            ],
        )

    def test_preserves_concrete_legal_basis_dan_chieu(self) -> None:
        content = (
            "Quỹ hòa nhập cộng đồng của trại giam được thành lập theo quy định tại "
            "Điều 34 Luật Thi hành án hình sự năm 2019 để hỗ trợ cho phạm nhân khi "
            "chấp hành xong hình phạt tù tái hòa nhập cộng đồng."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="49/2020/NĐ-CP",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            ["Điều 34 Luật Thi hành án hình sự năm 2019"],
        )

    def test_procedural_dinh_chi_thi_hanh_an_keeps_legal_basis_as_dan_chieu(self) -> None:
        content = (
            "2. Viện kiểm sát nơi Tòa án đã ra quyết định thi hành án kiểm sát việc "
            "Tòa án ra quyết định đình chỉ thi hành án theo quy định tại khoản 4 "
            "Điều 23, khoản 5 Điều 25, khoản 7 Điều 37, khoản 5 Điều 59, khoản 5 "
            "Điều 85, khoản 5 Điều 97, khoản 6 Điều 107, khoản 6 Điều 112, khoản 6 "
            "Điều 125 và khoản 7 Điều 129 Luật Thi hành án hình sự."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="",
            clause_type="khoan",
            content=content,
        )
        relation_types = {item["relation"] for item in predictions}
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertNotIn("dinh_chi", relation_types)
        self.assertEqual(
            dan_chieu_refs,
            [
                "khoản 4 Điều 23 Luật Thi hành án hình sự",
                "khoản 5 Điều 25 Luật Thi hành án hình sự",
                "khoản 7 Điều 37 Luật Thi hành án hình sự",
                "khoản 5 Điều 59 Luật Thi hành án hình sự",
                "khoản 5 Điều 85 Luật Thi hành án hình sự",
                "khoản 5 Điều 97 Luật Thi hành án hình sự",
                "khoản 6 Điều 107 Luật Thi hành án hình sự",
                "khoản 6 Điều 112 Luật Thi hành án hình sự",
                "khoản 6 Điều 125 Luật Thi hành án hình sự",
                "khoản 7 Điều 129 Luật Thi hành án hình sự",
            ],
        )

    def test_explicit_tai_khoan_child_keeps_dan_chieu_under_detail_parent(self) -> None:
        content = (
            "1. Quy định về dữ liệu lâm sàng để bảo đảm an toàn, hiệu quả trong hồ sơ "
            "đăng ký thuốc cổ truyền và tiêu chí để xác định trường hợp miễn thử, miễn "
            "một số giai đoạn thử thuốc cổ truyền trên lâm sàng tại Việt Nam và thuốc "
            "cổ truyền phải yêu cầu thử lâm sàng giai đoạn 4 tại khoản 2, khoản 3 "
            "Điều 72 và khoản 4 Điều 89 Luật Dược."
        )
        parent_content = (
            "Điều 1. Phạm vi điều chỉnh\r\n"
            "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của "
            "Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số "
            "điều của Luật Dược ngày 21 tháng 11 năm 2024 (sau đây gọi là Luật Dược), bao gồm:"
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2025/TT-BYT",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            [
                "khoản 2 Điều 72 Luật Dược",
                "khoản 3 Điều 72 Luật Dược",
                "khoản 4 Điều 89 Luật Dược",
            ],
        )
        self.assertNotIn("quy_dinh_chi_tiet", {item["relation"] for item in predictions})

    def test_theo_quy_dinh_without_cua_still_extracts_dan_chieu_document(self) -> None:
        content = (
            "Kế hoạch dự trữ quốc gia, dự toán ngân sách nhà nước chi cho dự trữ quốc gia "
            "năm 2026 thực hiện theo quy định Luật Dự trữ quốc gia số 22/2012/QH13 "
            "đã được sửa đổi, bổ sung một số điều theo Luật số 21/2017/QH14 và "
            "Luật số 56/2024/QH15 và quy định của pháp luật khác có liên quan."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="145/2025/QH15",
            clause_type="khoan",
            content=content,
            parent_content="Điều khoản chuyển tiếp",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            ["Luật Dự trữ quốc gia số 22/2012/QH13"],
        )

    def test_benchmark_context_infers_document_type_for_luat_nay(self) -> None:
        content = (
            "1. Hệ thống thông tin đã được xác định cấp độ theo quy định của "
            "Luật An toàn thông tin mạng số 86/2015/QH13 thì phải bảo đảm "
            "điều kiện, tiêu chuẩn, biện pháp bảo vệ an ninh mạng tương ứng "
            "với cấp độ theo quy định của Luật này."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="116/2025/QH15",
            title="Luật An ninh mạng",
            clause_type="khoan",
            content=content,
            parent_content="Điều 26. Điều khoản chuyển tiếp",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Luật 116/2025/QH15", dan_chieu_refs)

    def test_effective_date_luat_nay_does_not_emit_dan_chieu(self) -> None:
        content = (
            "1. Luật này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2025. "
            "Luật Công đoàn số 12/2012/QH13 hết hiệu lực từ ngày Luật này "
            "có hiệu lực thi hành."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="50/2024/QH15",
            title="Luật Công đoàn",
            clause_type="khoan",
            content=content,
            parent_content="Điều 37. Hiệu lực thi hành",
            cls_document_type="Luật",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertNotIn("Luật 50/2024/QH15", dan_chieu_refs)

    def test_listed_internal_articles_resolve_all_items(self) -> None:
        content = (
            "3. Các quy định tại Điều 30, Điều 31, Điều 32 của Nghị định này "
            "áp dụng đối với đối tượng áp dụng tương ứng quy định tại "
            "Nghị định số 06/2021/NĐ-CP ngày 26 tháng 01 năm 2021."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="67/2026/NĐ-CP",
            title="Nghị định quy định một số nội dung về xây dựng",
            clause_type="khoan",
            content=content,
            parent_content="Điều 2. Đối tượng áp dụng",
            cls_document_type="Nghị định",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Điều 30 Nghị định 67/2026/NĐ-CP", dan_chieu_refs)
        self.assertIn("Điều 31 Nghị định 67/2026/NĐ-CP", dan_chieu_refs)
        self.assertIn("Điều 32 Nghị định 67/2026/NĐ-CP", dan_chieu_refs)

    def test_document_level_internal_reference_does_not_need_parent_map(self) -> None:
        content = (
            "Điều 1. Ban hành kèm theo Nghị định này một số điều khoản sửa đổi "
            "bổ sung Điều lệ quản lý đầu tư và xây dựng."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="92/CP",
            title="Nghị định sửa đổi bổ sung Điều lệ quản lý đầu tư và xây dựng",
            clause_type="dieu",
            content=content,
            cls_document_type="Nghị định",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Nghị định 92/CP", dan_chieu_refs)

    def test_internal_clause_reference_allows_doc_type_without_cua(self) -> None:
        content = (
            "a) Không nộp hồ sơ khai thuế sau 90 ngày, trừ trường hợp "
            "quy định tại Khoản 6 Điều 7 Nghị định này."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="129/2013/NĐ-CP",
            title="Nghị định xử phạt vi phạm hành chính về thuế",
            clause_type="diem",
            content=content,
            parent_content="1. Phạt tiền 1 lần tính trên số thuế trốn.",
            grandparent_content="Điều 11. Xử phạt đối với hành vi trốn thuế",
            cls_document_type="Nghị định",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("khoản 6 Điều 7 Nghị định 129/2013/NĐ-CP", dan_chieu_refs)

    def test_duoc_quy_dinh_tai_extracts_dan_chieu_document_list(self) -> None:
        content = (
            "đ) Công tác xây dựng công trình chiếu sáng đô thị phải tuân thủ "
            "các quy định được quy định tại Nghị định số 72/2012/NĐ-CP "
            "ngày 24/9/2012 và Quyết định số 21/2021/QĐ-UBND ngày 08/12/2021."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="03/2025/QĐ-UBND",
            title="Quyết định ban hành quy định về quản lý chiếu sáng đô thị",
            clause_type="khoan",
            content=content,
            parent_content="Điều 3. Nguyên tắc quản lý vận hành chiếu sáng đô thị",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Nghị định số 72/2012/NĐ-CP ngày 24/9/2012", dan_chieu_refs)
        self.assertIn("Quyết định số 21/2021/QĐ-UBND ngày 08/12/2021", dan_chieu_refs)

    def test_theo_quy_dinh_tai_chuong_extracts_document_dan_chieu(self) -> None:
        content = (
            "a) Tiêu chuẩn nguyên liệu: thực hiện theo quy định tại Chương II "
            "Thông tư số 38/2021/TT-BYT ngày 31 tháng 12 năm 2021 của Bộ trưởng "
            "Bộ Y tế quy định về chất lượng dược liệu, vị thuốc cổ truyền, thuốc cổ truyền."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư quy định về đăng ký thuốc cổ truyền",
            clause_type="diem",
            content=content,
            parent_content="1. Thành phần hồ sơ đăng ký thuốc cổ truyền",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            ["Thông tư số 38/2021/TT-BYT ngày 31 tháng 12 năm 2021"],
        )

    def test_de_nghi_tai_cong_van_does_not_emit_dan_chieu(self) -> None:
        content = (
            "Trên cơ sở đề nghị của Bộ Nông nghiệp và Phát triển nông thôn "
            "tại Công văn số 5397/BNN-KHCN ngày 08 tháng 8 năm 2023; "
            "Theo đề nghị của Tổng cục trưởng Tổng cục Tiêu chuẩn Đo lường Chất lượng."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="2770/QĐ-BKHCN",
            clause_type="vanban",
            content=content,
        )

        self.assertNotIn("dan_chieu", {item["relation"] for item in predictions})

    def test_tren_co_so_cong_van_keeps_real_dan_chieu(self) -> None:
        content = (
            "Trên cơ sở Công văn số 10/HĐND-TH ngày 15/01/2020 của Thường trực "
            "Hội đồng nhân dân tỉnh về việc đính chính Nghị quyết số 23/2019/NQ-HĐND "
            "ngày 20/12/2019 của Hội đồng nhân dân tỉnh, Ủy ban Nhân dân tỉnh "
            "đính chính một số nội dung tại Quyết định số 80/2019/QĐ-UBND."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="497/UBND-NĐ",
            clause_type="vanban",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Công văn số 10/HĐND-TH ngày 15/01/2020", dan_chieu_refs)

    def test_theo_de_nghi_tai_cong_van_keeps_dan_chieu(self) -> None:
        content = (
            "Theo đề nghị của Sở Xây dựng tại Công văn số 4867/SXD-KTXD "
            "ngày 12/7/2021."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="2612/QĐ-UBND",
            clause_type="vanban",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("Công văn số 4867/SXD-KTXD ngày 12/7/2021", dan_chieu_refs)

    def test_self_document_clause_does_not_inherit_previous_external_doc(self) -> None:
        content = (
            "Các khoản thu khác gồm: phí và lệ phí theo quy định của Luật Phí và lệ phí; "
            "thực hiện các nội dung quản lý thu theo quy định tại khoản 7 Điều 39 "
            "của Luật này."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="108/2025/QH15",
            title="Luật Quản lý thuế",
            clause_type="khoan",
            content=content,
            cls_document_type="Luật",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn("khoản 7 Điều 39 Luật 108/2025/QH15", dan_chieu_refs)
        self.assertNotIn("khoản 7 Điều 39 Luật Phí và lệ phí", dan_chieu_refs)

    def test_transition_effective_reference_keeps_dan_chieu(self) -> None:
        content = (
            "7. Điều 11 Nghị định số 108/2014/NĐ-CP ngày 20 tháng 11 năm 2014 "
            "của Chính phủ về chính sách tinh giản biên chế tiếp tục có hiệu lực "
            "thi hành cho đến khi có quy định mới của Chính phủ."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2023/NĐ-CP",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn(
            "Điều 11 Nghị định số 108/2014/NĐ-CP ngày 20 tháng 11 năm 2014",
            dan_chieu_refs,
        )

    def test_parenthetical_short_alias_does_not_duplicate_dan_chieu(self) -> None:
        content = (
            "a) Tiêu chuẩn nguyên liệu: thực hiện theo quy định tại Chương II "
            "Thông tư số 38/2021/TT-BYT ngày 31 tháng 12 năm 2021 của Bộ trưởng "
            "Bộ Y tế quy định về chất lượng dược liệu (sau đây gọi là "
            "Thông tư số 38/2021/TT-BYT) và các yêu cầu cụ thể sau đây."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2025/TT-BYT",
            clause_type="diem",
            content=content,
            parent_content="2. Tài liệu về tiêu chuẩn chất lượng",
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            ["Thông tư số 38/2021/TT-BYT ngày 31 tháng 12 năm 2021"],
        )

    def test_singular_quy_dinh_tai_keeps_base_doc_before_amendment_history(self) -> None:
        content = (
            "5. Mẫu nhãn thuốc cổ truyền dự kiến lưu hành tại Việt Nam thực hiện "
            "theo quy định tại Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018 "
            "của Bộ trưởng Bộ Y tế quy định ghi nhãn thuốc được sửa đổi, bổ sung "
            "tại Thông tư số 23/2023/TT-BYT ngày 30 tháng 11 năm 2023 "
            "(sau đây gọi là Thông tư số 01/2018/TT-BYT) và các quy định sau đây."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2025/TT-BYT",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertIn(
            "Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018",
            dan_chieu_refs,
        )

    def test_theo_cac_quy_dinh_tai_keeps_semicolon_document_list(self) -> None:
        content = (
            "1. Các hồ sơ đăng ký lưu hành thuốc cổ truyền nộp trước ngày Thông tư này "
            "có hiệu lực thi hành được tiếp tục thực hiện theo các quy định tại "
            "Thông tư số 21/2018/TT-BYT ngày 12 tháng 9 năm 2018 của Bộ trưởng Bộ Y tế; "
            "Thông tư số 39/2021/TT-BYT ngày 31 tháng 12 năm 2021 của Bộ trưởng Bộ Y tế "
            "sửa đổi, bổ sung một số điều của Thông tư số 21/2018/TT-BYT và "
            "Thông tư số 54/2024/TT-BYT ngày 31 tháng 12 năm 2024 của Bộ trưởng Bộ Y tế, "
            "trừ trường hợp cơ sở có văn bản đề nghị thực hiện theo các quy định tại Thông tư này."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="29/2025/TT-BYT",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            [
                "Thông tư số 21/2018/TT-BYT ngày 12 tháng 9 năm 2018",
                "Thông tư số 39/2021/TT-BYT ngày 31 tháng 12 năm 2021",
                "Thông tư số 54/2024/TT-BYT ngày 31 tháng 12 năm 2024",
                "Thông tư 29/2025/TT-BYT",
            ],
        )

    def test_amendment_law_count_title_keeps_clause_reference(self) -> None:
        content = (
            "Do quá 03 năm chưa triển khai thực hiện theo quy định tại khoản 1 "
            "Điều 6 Luật sửa đổi, bổ sung một số điều của 37 Luật có liên quan "
            "đến quy hoạch. (Danh mục 01 kèm theo)"
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="06/2021/NQ-HĐND",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            [
                "khoản 1 Điều 6 Luật sửa đổi, bổ sung một số điều của 37 Luật có liên quan đến quy hoạch",
            ],
        )

    def test_numbered_project_repeal_drops_attached_resolution_citations(self) -> None:
        content = (
            "1. Hủy bỏ 15 dự án ban hành kèm theo Nghị quyết số 14/2018/NQ-HĐND "
            "ngày 19 tháng 7 năm 2018 của Hội đồng nhân dân tỉnh sửa đổi, bổ sung "
            "Danh mục dự án ban hành kèm theo Nghị quyết số 30/2017/NQ-HĐND "
            "ngày 08 tháng 12 năm 2017 của Hội đồng nhân dân tỉnh. "
            "Do quá 03 năm chưa triển khai thực hiện theo quy định tại khoản 1 "
            "Điều 6 Luật sửa đổi, bổ sung một số điều của 37 Luật có liên quan "
            "đến quy hoạch."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="06/2021/NQ-HĐND",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            [
                "khoản 1 Điều 6 Luật sửa đổi, bổ sung một số điều của 37 Luật có liên quan đến quy hoạch",
            ],
        )

    def test_tiep_tuc_thuc_hien_theo_quy_dinh_cua_luat_keeps_dan_chieu(self) -> None:
        content = (
            "1. Chiến lược, chương trình, đề án, dự án, nhiệm vụ công nghệ thông tin "
            "đã được phê duyệt và đang triển khai trước ngày Luật này có hiệu lực "
            "thi hành thì được tiếp tục thực hiện theo quy định của "
            "Luật Công nghệ thông tin số 67/2006/QH11 và các văn bản quy phạm "
            "pháp luật quy định chi tiết Luật Công nghệ thông tin số 67/2006/QH11 "
            "cho đến khi kết thúc."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="148/2025/QH15",
            clause_type="khoan",
            content=content,
        )
        dan_chieu_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        ]

        self.assertEqual(
            dan_chieu_refs,
            ["Luật Công nghệ thông tin số 67/2006/QH11"],
        )

    def test_colon_scope_keeps_repeated_law_clause_dan_chieu(self) -> None:
        content = (
            "b) Hỗ trợ theo quy định tại khoản 2, Điều 43, Luật Thủ đô: "
            "Các dự án đầu tư đáp ứng quy định tại khoản 1, Điều 43, Luật Thủ đô "
            "thì được hưởng các ưu đãi quy định tại khoản 2, Điều 43, Luật Thủ đô."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="49/2025/NQ-HĐND",
            title="Nghị quyết quy định chính sách hỗ trợ bảo tồn, phát triển làng nghề",
            cls_document_type="Nghị quyết",
            clause_type="diem",
            parent_content="2. Nội dung, mức hỗ trợ",
            grandparent_content="Điều 7. Chính sách hỗ trợ bảo tồn, phát triển làng nghề",
            content=content,
        )
        dan_chieu_refs = {
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        }

        self.assertIn("khoản 1 Điều 43 Luật Thủ đô", dan_chieu_refs)
        self.assertIn("khoản 2 Điều 43 Luật Thủ đô", dan_chieu_refs)

    def test_khoan_nay_resolves_to_current_clause_context(self) -> None:
        content = (
            "b) Thời gian miễn thuế, giảm thuế đối với thu nhập của doanh nghiệp "
            "thực hiện dự án đầu tư mới quy định tại khoản này được tính từ năm "
            "đầu tiên có thu nhập chịu thuế từ dự án đầu tư."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="49/2025/NQ-HĐND",
            title="Nghị quyết quy định chính sách hỗ trợ bảo tồn, phát triển làng nghề",
            cls_document_type="Nghị quyết",
            clause_type="diem",
            parent_content="2. Nội dung, mức hỗ trợ",
            grandparent_content="Điều 7. Chính sách hỗ trợ bảo tồn, phát triển làng nghề",
            content=content,
        )
        dan_chieu_refs = {
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        }

        self.assertIn("khoản 2 Điều 7 Nghị quyết 49/2025/NQ-HĐND", dan_chieu_refs)

    def test_effective_exception_self_reference_does_not_emit_dan_chieu(self) -> None:
        content = (
            "3. Nghị định số 141/2013/NĐ-CP hết hiệu lực thi hành kể từ ngày "
            "Nghị định này có hiệu lực, trừ trường hợp quy định tại Điều 14 "
            "Nghị định này."
        )

        predictions = _flat_relations(
            self.extractor,
            self.law_titles,
            so_hieu="91/2026/NĐ-CP",
            title="Nghị định hướng dẫn Luật Giáo dục đại học",
            cls_document_type="Nghị định",
            clause_type="khoan",
            parent_content="Điều 20. Hiệu lực thi hành",
            content=content,
        )
        dan_chieu_refs = {
            item["reference"]
            for item in predictions
            if item["relation"] == "dan_chieu"
        }

        self.assertNotIn("Điều 14 Nghị định 91/2026/NĐ-CP", dan_chieu_refs)


if __name__ == "__main__":
    unittest.main()
