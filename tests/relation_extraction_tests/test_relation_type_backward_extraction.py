import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestRelationTypeBackwardExtraction(unittest.TestCase):
    """Validate active and passive backward relation rules."""
            
    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=['Luật', 'Nghị định', 'Thông tư', 'Quyết định']
        )

    def test_extracts_backward_active_relation_when_hint_follows_reference(self) -> None:
        """An active backward relation should target the preceding reference."""
        content = (
            'Nghị định số 80/2011/NĐ-CP hết hiệu lực kể từ ngày '
            'Nghị định này có hiệu lực thi hành.'
        )
        reference_start = content.index('Nghị định số 80/2011/NĐ-CP')
        references = [{
            'nghidinh': {
                'information': 'Nghị định số 80/2011/NĐ-CP',
                'position_start': reference_start,
                'position_end': reference_start + len('Nghị định số 80/2011/NĐ-CP'),
            }
        }]

        relation_types = self.extractor.extract_relation_types(content=content, references=references)

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'thay_the')
        self.assertEqual(
            content[relation_types[0]['position_start']:relation_types[0]['position_end']],
            'hết hiệu lực kể từ ngày Nghị định này có hiệu lực thi hành',
        )

    def test_extracts_backward_passive_relation_in_listing_form(self) -> None:
        """A passive listing relation should apply to the reference that appears before it."""
        content = 'Điều 13 của Luật Đất đai được sửa đổi, bổ sung như sau:'
        dieu_start = content.index('Điều 13')
        luat_start = content.index('Luật Đất đai')
        references = [{
            'dieu': {
                'information': 'Điều 13',
                'position_start': dieu_start,
                'position_end': dieu_start + len('Điều 13'),
            },
            'luat': {
                'information': 'Luật Đất đai',
                'position_start': luat_start,
                'position_end': luat_start + len('Luật Đất đai'),
            },
        }]

        relation_types = self.extractor.extract_relation_types(content=content, references=references)

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'sua_doi_bo_sung')
        self.assertEqual(
            content[relation_types[0]['position_start']:relation_types[0]['position_end']],
            'được sửa đổi, bổ sung',
        )


if __name__ == '__main__':
    unittest.main()
