"""Unit tests for combining clause chains with document references."""

import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestClauseDocumentCombination(unittest.TestCase):
    """Validate final clause-document reference combination behavior."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị định']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = ['luật đất đai']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def test_extract_references_combines_each_clause_chain_with_document(self) -> None:
        """A single document mention should be paired with every valid clause chain in scope."""
        references = self.extractor.extract_references(
            content='a) Bãi bỏ điểm c khoản 1 Điều 4 và Điều 7, Điều 8 của Nghị định số 59/2006/NĐ-CP',
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )

        self.assertEqual(len(references), 3)
        self.assertEqual(references[0]['diem']['information'], 'điểm c')
        self.assertEqual(references[0]['khoan']['information'], 'khoản 1')
        self.assertEqual(references[0]['dieu']['information'], 'Điều 4')
        self.assertEqual(references[0]['nghidinh']['information'], 'Nghị định số 59/2006/NĐ-CP')
        self.assertEqual(references[1]['dieu']['information'], 'Điều 7')
        self.assertEqual(references[1]['nghidinh']['information'], 'Nghị định số 59/2006/NĐ-CP')
        self.assertEqual(references[2]['dieu']['information'], 'Điều 8')
        self.assertEqual(references[2]['nghidinh']['information'], 'Nghị định số 59/2006/NĐ-CP')

    def test_extract_references_keeps_trailing_document_standalone_when_no_clause_targets_it(self) -> None:
        """A later document should stay standalone if the clause chain belongs to an earlier one."""
        references = self.extractor.extract_references(
            content='Bãi bỏ khoản 1 Điều 5 của Luật Đất đai, Nghị định số 12/2024/NĐ-CP',
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )

        self.assertEqual(len(references), 2)
        self.assertEqual(references[0]['khoan']['information'], 'khoản 1')
        self.assertEqual(references[0]['dieu']['information'], 'Điều 5')
        self.assertEqual(references[0]['luat']['information'], 'Luật Đất đai')
        self.assertNotIn('nghidinh', references[0])
        self.assertEqual(
            references[1],
            {
                'nghidinh': {
                    'information': 'Nghị định số 12/2024/NĐ-CP',
                    'position_start': 40,
                    'position_end': 66,
                }
            },
        )

    def test_extract_references_maps_multiple_clause_chains_to_matching_documents(self) -> None:
        """Each clause chain should attach to its own nearest document in the same scope."""
        references = self.extractor.extract_references(
            content=(
                'Sửa đổi, bổ sung khoản 1 Điều 5 Luật Đất đai ngày 23 tháng 1 năm 2013, '
                'điểm a khoản 4 Điều 1 Nghị định số 35/2005/NĐ-CP ngày 17 tháng 3 năm 2005 '
                'của Chính phủ về việc xử lý kỷ luật cán bộ, công chức'
            ),
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )

        self.assertEqual(len(references), 2)
        self.assertEqual(references[0]['khoan']['information'], 'khoản 1')
        self.assertEqual(references[0]['dieu']['information'], 'Điều 5')
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Đất đai ngày 23 tháng 1 năm 2013',
        )
        self.assertEqual(references[1]['diem']['information'], 'điểm a')
        self.assertEqual(references[1]['khoan']['information'], 'khoản 4')
        self.assertEqual(references[1]['dieu']['information'], 'Điều 1')
        self.assertEqual(
            references[1]['nghidinh']['information'],
            'Nghị định số 35/2005/NĐ-CP ngày 17 tháng 3 năm 2005',
        )
        

if __name__ == '__main__':
    unittest.main()
