"""Unit tests for Stage-3 listing and scope-conflict handling."""

import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestRelationTypeScopeConflict(unittest.TestCase):
    """Validate listing-style extraction and scope-level conflict resolution."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=['Luật', 'Nghị định', 'Thông tư', 'Quyết định']
        )

    def test_resolves_action_conflict_scope_to_sua_doi_bo_sung(self) -> None:
        """If one scope contains action hints from multiple groups, default to sửa đổi bổ sung."""
        content = 'Điều 23. Bãi bỏ, thay thế một số cụm từ tại Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013 của Chính phủ'
        reference_start = content.index('Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013')
        references = [{
            'nghidinh': {
                'information': 'Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013',
                'position_start': reference_start,
                'position_end': reference_start + len('Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013'),
            }
        }]

        relation_types = self.extractor.extract_relation_types(content=content, references=references)

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'sua_doi_bo_sung')

    def test_maps_combined_detail_and_guidance_phrase_to_huong_dan(self) -> None:
        """The combined 'quy định chi tiết và hướng dẫn thi hành' phrase maps to quy định chi tiết."""
        content = 'Điều 1. Phạm vi điều chỉnh\nThông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024 (sau đây gọi là Luật Dược), bao gồm:'
        reference_start = content.index('Luật Dược ngày 06 tháng 4 năm 2016')
        references = [{
            'luat': {
                'information': 'Luật Dược ngày 06 tháng 4 năm 2016',
                'position_start': reference_start,
                'position_end': reference_start + len('Luật Dược ngày 06 tháng 4 năm 2016'),
            }
        }]

        relation_types = self.extractor.extract_relation_types(content=content, references=references)

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'quy_dinh_chi_tiet')


if __name__ == '__main__':
    unittest.main()
