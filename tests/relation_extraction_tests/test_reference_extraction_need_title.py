"""Unit tests for document reference extraction that requires title context.

These tests verify that when a clause contains internal references (like "khoản 2 Điều 1") 
but no explicit document reference from the clause and its parents, the system correctly uses the document's title 
(cls_title) to resolve the target document, especially for amending documents.
"""

import unittest
from src.domain.extractors.relations_extractor import RelationsExtractor

class TestReferenceExtractionNeedTitle(unittest.TestCase):
    """
    Validate that cls_title is correctly used to enrich internal references
    within a hierarchical document structure.
    """

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị định', 'Thông tư', 'Nghị quyết', 'Quyết định']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.doc_clause_types = {
            'doc_types': self.doc_types,
            'clause_types': self.clause_types
        }
        self.extractor = RelationsExtractor(doc_clause_types=self.doc_clause_types)
        
        # Amending document title that refers to another target document
        self.cls_title = (
            "Thông tư sửa đổi, bổ sung một số điều của "
            "Thông tư số 50/2024/TT-NHNN của Thống đốc Ngân hàng Nhà nước Việt Nam "
            "quy định về an toàn, bảo mật cho việc cung cấp dịch vụ trực tuyến trong ngành ngân hàng."
        )
        self.cls_so_hieu = "12/2025/TT-NHNN"

    def test_extract_reference_from_khoan_with_title(self):
        """
        Case 1: 
        Parent: Điều 1. Sửa đổi, bổ sung một số điểm, khoản của Điều 1
        Child: 2. Sửa đổi, bổ sung khoản 2 Điều 1 như sau:
        """
        data = [
            {
                "com_type": "dieu",
                "com_key": "dieu_1",
                "com_title": "Điều 1. Sửa đổi, bổ sung một số điểm, khoản của Điều 1"
            },
            {
                "com_type": "khoan",
                "com_key": "khoan_2_dieu_1",
                "com_title": "2. Sửa đổi, bổ sung khoản 2 Điều 1 như sau:"
            }
        ]
        
        results = self.extractor.extract_relations(
            data=data,
            cls_so_hieu=self.cls_so_hieu,
            cls_title=self.cls_title
        )
        
        self.assertGreater(len(results), 0, "No relations extracted for Case 1")
        
        # Verify relations for Khoản 2 (child)
        khoan_2_results = [r for r in results if r['clause_key'] == 'khoan_2_dieu_1']
        self.assertGreater(len(khoan_2_results), 0, "Khoản 2 should have relations")
        
        found_target = False
        for rel in khoan_2_results[0]['relations']:
            if rel['relation'] == 'sua_doi':
                for tail in rel['tail']:
                    # Target doc from title
                    if 'thongtu' in tail and '50/2024/TT-NHNN' in tail['thongtu']['information'].upper():
                        # Specific target clause in target doc
                        if 'khoan' in tail and 'khoản 2' in tail['khoan']['information'].lower() and \
                           'dieu' in tail and 'điều 1' in tail['dieu']['information'].lower():
                            found_target = True
                            break
        
        self.assertTrue(found_target, "Khoản 2 should link to 'khoản 2 Điều 1' of 'Thông tư 50/2024/TT-NHNN'")

    def test_extract_reference_from_khoan_with_title_case_2(self):
        """
        Case 2:
        Parent: Điều 4. Sửa đổi, bổ sung một số điểm, khoản của Điều 7
        Child: 2. Sửa đổi, bổ sung điểm g khoản 6 Điều 7 như sau:
        """
        data = [
            {
                "com_type": "dieu",
                "com_key": "dieu_4",
                "com_title": "Điều 4. Sửa đổi, bổ sung một số điểm, khoản của Điều 7"
            },
            {
                "com_type": "khoan",
                "com_key": "khoan_2_dieu_4",
                "com_title": "2. Sửa đổi, bổ sung điểm g khoản 6 Điều 7 như sau: \"g) Đối với khách hàng...\""
            }
        ]
        
        results = self.extractor.extract_relations(
            data=data,
            cls_so_hieu=self.cls_so_hieu,
            cls_title=self.cls_title
        )
        
        self.assertGreater(len(results), 0, "No relations extracted for Case 2")
        
        # Verify relations for Khoản 2 of Điều 4
        khoan_2_results = [r for r in results if r['clause_key'] == 'khoan_2_dieu_4']
        self.assertGreater(len(khoan_2_results), 0, "Khoản 2 (under Điều 4) should have relations")
        
        found_target = False
        for rel in khoan_2_results[0]['relations']:
            if rel['relation'] == 'sua_doi':
                for tail in rel['tail']:
                    if 'thongtu' in tail and '50/2024/TT-NHNN' in tail['thongtu']['information'].upper():
                        if 'diem' in tail and 'điểm g' in tail['diem']['information'].lower() and \
                           'khoan' in tail and 'khoản 6' in tail['khoan']['information'].lower() and \
                           'dieu' in tail and 'điều 7' in tail['dieu']['information'].lower():
                            found_target = True
                            break
        
        self.assertTrue(found_target, "Khoản 2 should link to 'điểm g khoản 6 Điều 7' of 'Thông tư 50/2024/TT-NHNN'")

if __name__ == '__main__':
    unittest.main()
