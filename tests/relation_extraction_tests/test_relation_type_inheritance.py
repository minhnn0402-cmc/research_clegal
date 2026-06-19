import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestRelationTypeInheritance(unittest.TestCase):
    """Validate parent/grandparent inheritance and default fallback."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=['Luật', 'Nghị định', 'Thông tư', 'Quyết định']
        )

    @staticmethod
    def _build_reference(content: str, text: str, key: str = 'luat') -> list[dict]:
        reference_start = content.index(text)
        return [{
            key: {
                'information': text,
                'position_start': reference_start,
                'position_end': reference_start + len(text),
            }
        }]

    def test_inherits_relation_from_parent_when_content_has_no_direct_match(self) -> None:
        content = 'Khoản 1 Điều 9 của Luật Đất đai.'
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=self._build_reference(content, 'Luật Đất đai'),
            parent_content='Sửa đổi, bổ sung một số điều luật liên quan bao gồm:',
            grandparent_content=None,
        )

        self.assertEqual(len(relation_types), 1)
        self.assertEqual(relation_types[0]['relation_type'], 'sua_doi_bo_sung')
        self.assertEqual(relation_types[0]['position_start'], -1)
        self.assertEqual(relation_types[0]['position_end'], -1)
        self.assertEqual(relation_types[0]['relation_value'], 'Sửa đổi, bổ sung')


if __name__ == '__main__':
    unittest.main()
