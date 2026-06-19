import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestRelationTypeForwardExtraction(unittest.TestCase):
    """Validate forward-only relation extraction rules."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=['Luật', 'Nghị định', 'Thông tư', 'Quyết định']
        )

    def test_extracts_forward_relation(self) -> None:
        """A forward relation is valide when the reference appears before the boundary."""
        content = 'Bãi bỏ Luật Đất đai năm 2024. Nghị định số 12/2015/NĐ-CP ngày 12 tháng 02 năm 2015'
        reference_start = content.index('Luật')
        references = [{
            'luat': {
                'information': 'Luật Đất đai năm 2024',
                'position_start': reference_start,
                'position_end': reference_start + len('Luật Đất đai năm 2024'),
            }
        }]

        relation_types = self.extractor.extract_relation_types(content=content, references=references)

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'bai_bo')
        self.assertEqual(relation_types[0]['position_start'], 0)
        self.assertEqual(relation_types[0]['position_end'], 6)
        self.assertEqual(relation_types[0]['relation_value'], 'Bãi bỏ')


if __name__ == '__main__':
    unittest.main()
