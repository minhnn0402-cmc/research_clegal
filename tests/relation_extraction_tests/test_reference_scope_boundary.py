import unittest

from src.domain.extractors.base_extractor import BaseExtractor


class TestReferenceScopeBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"]
        )
        self.doc_types = ["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"]
        self.clause_types = ["điểm", "khoản", "điều"]
        self.law_titles = [
            "Luật Dược",
            "Luật Thuế thu nhập doanh nghiệp",
        ]

    def test_does_not_scan_ancestors_when_clause_content_has_no_clause_reference(self) -> None:
        data = [
            {
                "com_type": "dieu",
                "com_key": "dieu_1",
                "com_title": (
                    "Điều 1. Sửa đổi, bổ sung một số điều của Luật Dược "
                    "số 105/2016/QH13"
                ),
            },
            {
                "com_type": "khoan",
                "com_key": "khoan_1",
                "com_title": "Cơ quan quản lý có trách nhiệm tổ chức thực hiện.",
            },
        ]

        context = self.extractor._build_clause_context(
            content=data[1]["com_title"],
            doc_types=self.doc_types,
            clause_type="khoan",
            clause_key="khoan_1",
            data=data,
            child_to_parent={"khoan_1": "dieu_1"},
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            cls_title="Nghị định sửa đổi, bổ sung một số điều của Luật Dược",
        )

        self.assertEqual(context.ancestor_context, {})
        self.assertIsNone(context.ancestor_doc_reference)
        self.assertEqual(context.ancestor_doc_references, [])

    def test_does_not_use_cls_title_when_clause_reference_has_no_article(self) -> None:
        references = self.extractor.extract_references(
            content="Sửa đổi, bổ sung điểm b khoản 3 như sau:",
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            clause_type="khoan",
            clause_key="khoan_1",
            data=[
                {
                    "com_type": "dieu",
                    "com_key": "dieu_1",
                    "com_title": "Điều 1. Sửa đổi, bổ sung một số điểm, khoản",
                },
                {
                    "com_type": "khoan",
                    "com_key": "khoan_1",
                    "com_title": "Sửa đổi, bổ sung điểm b khoản 3 như sau:",
                },
            ],
            child_to_parent={"khoan_1": "dieu_1"},
            cls_title=(
                "Nghị định sửa đổi, bổ sung một số điều của Luật Dược "
                "số 105/2016/QH13"
            ),
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["diem"]["information"], "điểm b")
        self.assertEqual(references[0]["khoan"]["information"], "khoản 3")
        self.assertNotIn("luat", references[0])


if __name__ == "__main__":
    unittest.main()
