import unittest

from src.services.graph_relation_source import GraphRelationSource


class TestGraphRelationSource(unittest.TestCase):
    def test_cls_graph_wins_and_tvpl_supplements_missing_relation(self):
        doc = {
            "cls_ID": 10,
            "cls_info": {
                "title": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                "trich_yeu": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                "so_hieu": "01/2026/TT-BTC",
                "loai_van_ban": "Thông tư",
            },
            "cls_graph": {
                "success": [
                    {
                        "source_key": None,
                        "source_type": "vanban",
                        "success": [
                            {
                                "relationship": "quy_dinh_chi_tiet",
                                "target_doc_id": 20,
                                "description": "cls_graph primary",
                            }
                        ],
                    }
                ]
            },
            "cls_luoc_do": {
                "van_ban_duoc_quy_dinh_chi_tiet": [
                    {"id": 20, "source": "tvpl", "description": "tvpl duplicate"}
                ],
                "van_ban_duoc_huong_dan": [
                    {
                        "id": 30,
                        "source": "tvpl",
                        "description": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                    }
                ],
            },
        }

        events = GraphRelationSource().collect_document_events(doc)
        keys = [event.dedup_key() for event in events]

        self.assertIn(("cls_graph", 10, 20, "quy_dinh_chi_tiet", "document"), keys)
        self.assertIn(("tvpl", 10, 30, "huong_dan", "document"), keys)
        self.assertNotIn(("tvpl", 10, 20, "quy_dinh_chi_tiet", "document"), keys)

    def test_cls_graph_bai_bo_suppresses_conflicting_tvpl_thay_the(self):
        doc = {
            "cls_ID": 10,
            "cls_graph": {
                "success": [
                    {
                        "source_key": None,
                        "source_type": "vanban",
                        "success": [
                            {
                                "relationship": "bai_bo",
                                "target_doc_id": 20,
                            }
                        ],
                    }
                ]
            },
            "cls_luoc_do": {
                "van_ban_bi_thay_the": [
                    {"id": 20, "source": "tvpl", "description": "tvpl conflict"}
                ],
            },
        }

        keys = [event.dedup_key() for event in GraphRelationSource().collect_document_events(doc)]

        self.assertIn(("cls_graph", 10, 20, "bai_bo", "document"), keys)
        self.assertNotIn(("tvpl", 10, 20, "thay_the", "document"), keys)

    def test_inferred_relations_preserve_clause_scope_and_id_relations(self):
        doc = {
            "cls_ID": 10,
            "cls_graph": {
                "inferred_relations": [
                    {
                        "relation": "sua_doi_bo_sung",
                        "collection": [
                            {
                                "target_doc_id": 20,
                                "relation": "bai_bo",
                                "description": "mot phan",
                                "id_relations": {"dieu_1#10": ["dieu_2#20"]},
                            }
                        ],
                    }
                ]
            },
        }

        events = GraphRelationSource().collect_document_events(doc)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].dedup_key(), ("cls_graph", 10, 20, "sua_doi_bo_sung", "clause"))
        self.assertEqual(events[0].id_relations, {"dieu_1#10": ["dieu_2#20"]})
        self.assertEqual(events[0].evidence, "mot phan")

    def test_status_event_with_target_clause_is_clause_scope(self):
        doc = {
            "cls_ID": 10,
            "cls_graph": {
                "success": [
                    {
                        "source_key": None,
                        "source_type": "vanban",
                        "success": [
                            {
                                "relationship": "bai_bo",
                                "target_doc_id": 20,
                                "target_key": "dieu_3",
                                "description": "Bãi bỏ Điều 3 Nghị định số 103/2024/NĐ-CP",
                            }
                        ],
                    }
                ]
            },
        }

        events = GraphRelationSource().collect_document_events(doc)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].dedup_key(), ("cls_graph", 10, 20, "bai_bo", "clause"))
        self.assertEqual(events[0].id_relations, {"10": ["dieu_3#20"]})
        self.assertEqual(events[0].evidence, "Bãi bỏ Điều 3 Nghị định số 103/2024/NĐ-CP")

if __name__ == "__main__":
    unittest.main()
