"""Regression tests for ancestor reference inheritance in the extractor."""

import logging
import unittest

from src.domain.builders.hierarchy_builder import HierarchyBuilder
from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestAncestorReferenceInheritance(unittest.TestCase):
    """Validate ancestor backfilling for missing điều/khoản/document context."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị định', 'Thông tư']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = ['luật khoa học, công nghệ và đổi mới sáng tạo']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def _build_hierarchy(self, data):
        _, child_to_parent = HierarchyBuilder.build_hierarchy(data_parsing=data)
        return child_to_parent

    def test_diem_inherits_document_from_ancestors(self) -> None:
        """A scope with điểm should inherit document from ancestors."""
        data = [
            {
                'com_type': 'dieu',
                'com_key': 'dieu_25',
                'com_title': 'Điều 25. Sửa đổi, bổ sung, bãi bỏ một số điều, khoản của các luật có liên quan\n',
            },
            {
                'com_type': 'khoan',
                'com_key': 'khoan_2_dieu_25',
                'com_title': '2. Sửa đổi, bổ sung một số điều của Luật Khoa học, công nghệ và đổi mới sáng tạo số 93/2025/QH15 như sau:\n',
            },
            {
                'com_type': 'diem',
                'com_key': 'diem_b_khoan_2_dieu_25',
                'com_title': 'Bãi bỏ khoản 1 Điều 71',
            },
        ]

        references = self.extractor.extract_references(
            content=data[-1]['com_title'],
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            clause_type='diem',
            clause_key='diem_b_khoan_2_dieu_25',
            data=data,
            child_to_parent=self._build_hierarchy(data),
        )

        self.assertEqual(len(references), 1)
        reference = references[0]
        self.assertEqual(reference['khoan']['information'], 'khoản 1')
        self.assertEqual(reference['dieu']['information'], 'Điều 71')
        self.assertEqual(reference['luat']['information'], 'Luật Khoa học, công nghệ và đổi mới sáng tạo số 93/2025/QH15')


if __name__ == '__main__':
    unittest.main()
