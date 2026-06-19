import unittest

from src.domain.graph.relation_event import RelationEvent


class TestRelationEvent(unittest.TestCase):
    def test_dedup_key_uses_source_target_relation_scope_and_source(self):
        event = RelationEvent(
            source_doc_id=100,
            target_doc_id=200,
            relation_type="sua_doi_bo_sung",
            source="cls_graph",
            scope="document",
            evidence="Dieu 1 sua doi Luat A",
        )

        self.assertEqual(
            event.dedup_key(),
            ("cls_graph", 100, 200, "sua_doi_bo_sung", "document"),
        )

    def test_to_neo4j_props_uses_direct_edge_whitelist(self):
        event = RelationEvent(
            source_doc_id=100,
            target_doc_id=200,
            relation_type="quy_dinh_chi_tiet",
            source="tvpl",
            scope="document",
            evidence="TVPL: văn bản hướng dẫn Luật Đất đai",
            confidence=0.7,
            resolution_status="resolved",
        )

        props = event.to_neo4j_props()

        self.assertEqual(props, {"nguon_cap_nhat": "cmcai"})


if __name__ == "__main__":
    unittest.main()
