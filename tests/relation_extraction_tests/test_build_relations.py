"""Unit tests for relation payload building using realistic schemas."""

import json
import logging
import unittest
from pathlib import Path

from src.domain.extractors.relations_extractor import RelationsExtractor


logging.disable(logging.INFO)


class TestBuildRelations(unittest.TestCase):
    """Validate mapping from relation matches to grouped relations."""

    @classmethod
    def setUpClass(cls):
        test_data_path = Path(__file__).parent.parent / "test_data" / "tp_samples.json"
        with open(test_data_path, "r", encoding="utf-8") as f:
            cls.tp_samples = json.load(f)

    def setUp(self) -> None:
        self.extractor = RelationsExtractor(
            doc_clause_types={
                'doc_types': ['Luật', 'Nghị định', 'Thông tư', 'Quyết định'],
                'clause_types': ['điều', 'khoản', 'điểm'],
            },
            law_titles_for_regex=['luật lưu trữ'],
        )

    def test_build_relations_groups_matches_under_one_clause_entry(self) -> None:
        bai_bo_sample = self.tp_samples["bai_bo"][0]
        thay_the_sample = self.tp_samples["thay_the"][0]
        
        relation_matches = [
            {
                'relation_type': 'bai_bo',
                'reference': {
                    'nghidinh': {
                        'information': bai_bo_sample["tp_reference"],
                        'position_start': 10,
                        'position_end': 37,
                    }
                },
            },
            {
                'relation_type': 'thay_the',
                'reference': {
                    'luat': {
                        'information': thay_the_sample["tp_reference"],
                        'position_start': 48,
                        'position_end': 76,
                    },
                },
            },
        ]

        result = self.extractor._build_relations(
            relation_matches=relation_matches,
            clause_type='dieu',
            clause_key='dieu_1',
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['clause_key'], 'dieu_1')
        self.assertEqual(len(result[0]['relations']), 2)
        
        rel_types = [r['relation'] for r in result[0]['relations']]
        self.assertIn('bai_bo', rel_types)
        self.assertIn('thay_the', rel_types)

    def test_build_relations_preserves_full_reference_payload_in_tail(self) -> None:
        sample = self.tp_samples["sua_doi_bo_sung"][0]
        
        reference = {
            'luat': {
                'information': sample["tp_reference"],
                'position_start': 18,
                'position_end': 50,
                'type': 'luat',
            }
        }
        relation_matches = [{
            'relation_type': 'sua_doi_bo_sung',
            'reference': reference,
        }]

        result = self.extractor._build_relations(
            relation_matches=relation_matches,
            clause_type='khoan',
            clause_key='khoan_1_dieu_5',
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['relations'][0]['relation'], 'sua_doi_bo_sung')
        self.assertEqual(result[0]['relations'][0]['tail'], [reference])

    def test_build_relations_returns_empty_for_empty_matches(self) -> None:
        result = self.extractor._build_relations(
            relation_matches=[],
            clause_type='dieu',
            clause_key='dieu_1',
        )
        self.assertEqual(result, [])

    def test_build_relations_allows_null_key_for_vanban_nodes(self) -> None:
        hop_nhat_sample = self.tp_samples["hop_nhat"][0]
        
        relation_matches = [{
            'relation_type': 'hop_nhat',
            'reference': {
                'nghidinh': {
                    'information': hop_nhat_sample["tp_reference"],
                    'position_start': 5,
                    'position_end': 32,
                },
            },
        }]

        result = self.extractor._build_relations(
            relation_matches=relation_matches,
            clause_type='vanban',
            clause_key=None,
        )
        
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['clause_key'])
        self.assertEqual(result[0]['relations'][0]['relation'], 'hop_nhat')


if __name__ == '__main__':
    unittest.main()
