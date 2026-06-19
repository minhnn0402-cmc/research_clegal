import unittest

from src.domain.graph import RelationEvent
from src.services.graph_reconciliation_service import GraphReconciliationService


class FakeRepository:
    def __init__(self, endpoint_rows=None, variant_nodes=None, existing_nodes=None):
        self.endpoint_rows = endpoint_rows
        self.variant_nodes = variant_nodes or {}
        self.existing_nodes = set(existing_nodes or [])

    def fetch_relationship_keys_for_sources(self, doc_ids):
        return {
            ("cls_graph", 10, 20, "huong_dan"),
            ("tvpl", 10, 30, "dan_chieu"),
        }

    def fetch_relationship_endpoint_keys_for_sources(self, doc_ids):
        if self.endpoint_rows is None:
            raise AttributeError("endpoint fetch is intentionally unavailable")
        return self.endpoint_rows

    def fetch_existing_node_keys(self, node_refs):
        return {ref for ref in node_refs if ref in self.existing_nodes}

    def fetch_dieu_khoan_variant_node_keys(self, node_refs):
        return {
            ref: variant
            for ref, variant in self.variant_nodes.items()
            if ref in node_refs
        }


class TestGraphReconciliationService(unittest.TestCase):
    def test_reports_missing_and_extra_relationships(self):
        expected = [
            RelationEvent(10, 20, "huong_dan", "cls_graph", "document"),
            RelationEvent(10, 40, "bai_bo", "cls_graph", "document"),
            RelationEvent(10, None, "dan_chieu", "cls_graph", "document"),
        ]

        class LegacyRepository:
            def fetch_relationship_keys_for_sources(self, doc_ids):
                return {
                    ("cls_graph", 10, 20, "huong_dan"),
                    ("tvpl", 10, 30, "dan_chieu"),
                }

        report = GraphReconciliationService(LegacyRepository()).compare([10], expected)

        self.assertEqual(report["expected"], 2)
        self.assertEqual(report["actual"], 2)
        self.assertEqual(report["missing"], [("cls_graph", 10, 40, "bai_bo")])
        self.assertEqual(report["extra"], [("tvpl", 10, 30, "dan_chieu")])
        self.assertEqual(report["comparison_level"], "document")

    def test_endpoint_reconciliation_canonicalizes_unique_clause_variant(self):
        expected = [
            RelationEvent(
                10,
                20,
                "sua_doi",
                "cls_graph",
                "clause",
                id_relations={"dieu_1#10": ["dieu_16#20"]},
            )
        ]
        actual = [
            {
                "source": "cls_graph",
                "source_doc_id": 10,
                "source_node_id": "dieu_1#10",
                "target_doc_id": 20,
                "target_node_id": "dieu_16_dk_1#20",
                "relation_type": "sua_doi",
            }
        ]
        repo = FakeRepository(
            endpoint_rows=actual,
            existing_nodes={("DIEU_KHOAN", "dieu_1#10"), ("DIEU_KHOAN", "dieu_16_dk_1#20")},
            variant_nodes={
                ("DIEU_KHOAN", "dieu_16#20"): ("DIEU_KHOAN", "dieu_16_dk_1#20")
            },
        )

        report = GraphReconciliationService(repo).compare([10], expected)

        self.assertEqual(report["comparison_level"], "endpoint")
        self.assertEqual(report["expected"], 1)
        self.assertEqual(report["actual"], 1)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["extra"], [])
        self.assertEqual(report["canonicalized_expected_endpoints"], 1)

    def test_endpoint_reconciliation_detects_wrong_clause_in_same_target_document(self):
        expected = [
            RelationEvent(
                10,
                20,
                "sua_doi",
                "cls_graph",
                "clause",
                id_relations={"dieu_1#10": ["dieu_16_dk_1#20"]},
            )
        ]
        actual = [
            {
                "source": "cls_graph",
                "source_doc_id": 10,
                "source_node_id": "dieu_1#10",
                "target_doc_id": 20,
                "target_node_id": "dieu_17#20",
                "relation_type": "sua_doi",
            }
        ]

        report = GraphReconciliationService(FakeRepository(endpoint_rows=actual)).compare([10], expected)

        self.assertEqual(report["comparison_level"], "endpoint")
        self.assertEqual(report["expected"], 1)
        self.assertEqual(report["actual"], 1)
        self.assertEqual(report["matched"], 0)
        self.assertEqual(report["missing"][0]["target_node_id"], "dieu_16_dk_1#20")
        self.assertEqual(report["extra"][0]["target_node_id"], "dieu_17#20")
        self.assertEqual(report["missing"][0]["target_doc_id"], 20)
        self.assertEqual(report["extra"][0]["target_doc_id"], 20)

    def test_repository_fetch_relationship_keys_normalizes_rows(self):
        import importlib.util
        import sys
        import types
        from pathlib import Path

        neo4j_stub = types.ModuleType("neo4j")
        neo4j_stub.GraphDatabase = object
        neo4j_stub.Driver = object
        neo4j_stub.Session = object
        neo4j_stub.Transaction = object
        neo4j_exceptions_stub = types.ModuleType("neo4j.exceptions")
        neo4j_exceptions_stub.Neo4jError = Exception
        sys.modules.setdefault("neo4j", neo4j_stub)
        sys.modules.setdefault("neo4j.exceptions", neo4j_exceptions_stub)

        module_path = Path("src/repositories/neo4j_repository.py")
        spec = importlib.util.spec_from_file_location("neo4j_repository_under_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        Neo4jRepository = module.Neo4jRepository

        class FakeNeo4jRepository(Neo4jRepository):
            def __init__(self):
                self.query = None
                self.parameters = None

            def execute_query(self, query, parameters=None):
                self.query = query
                self.parameters = parameters
                return [
                    {
                        "source": "cls_graph",
                        "source_doc_id": 10,
                        "target_doc_id": 20,
                        "relation_type": "huong_dan",
                    }
                ]

        repo = FakeNeo4jRepository()

        result = repo.fetch_relationship_keys_for_sources([10])

        self.assertEqual(result, [("cls_graph", 10, 20, "huong_dan")])
        self.assertEqual(repo.parameters, {"doc_ids": [10]})
        self.assertIn("MATCH (a)-[r]->(b)", repo.query)
        self.assertIn("r.nguon_cap_nhat IS NOT NULL", repo.query)
        self.assertIn("type(r) <> 'bao_gom'", repo.query)
        self.assertIn("type(r) <> 'bao_gom_sau_bo_sung'", repo.query)
        self.assertIn("WHEN r.nguon_cap_nhat = 'cmcai' THEN 'cls_graph'", repo.query)
        self.assertIn("WHEN r.nguon_cap_nhat = 'tvpl' THEN 'tvpl'", repo.query)
        self.assertNotIn("nguon_quan_he", repo.query)
        self.assertNotIn("pham_vi", repo.query)

    def test_repository_fetch_relationship_endpoint_keys_includes_raw_node_ids(self):
        import importlib.util
        import sys
        import types
        from pathlib import Path

        neo4j_stub = types.ModuleType("neo4j")
        neo4j_stub.GraphDatabase = object
        neo4j_stub.Driver = object
        neo4j_stub.Session = object
        neo4j_stub.Transaction = object
        neo4j_exceptions_stub = types.ModuleType("neo4j.exceptions")
        neo4j_exceptions_stub.Neo4jError = Exception
        sys.modules.setdefault("neo4j", neo4j_stub)
        sys.modules.setdefault("neo4j.exceptions", neo4j_exceptions_stub)

        module_path = Path("src/repositories/neo4j_repository.py")
        spec = importlib.util.spec_from_file_location("neo4j_repository_under_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        Neo4jRepository = module.Neo4jRepository

        class FakeNeo4jRepository(Neo4jRepository):
            def __init__(self):
                self.query = None
                self.parameters = None

            def execute_query(self, query, parameters=None):
                self.query = query
                self.parameters = parameters
                return [
                    {
                        "source": "cls_graph",
                        "source_doc_id": 10,
                        "source_node_id": "dieu_1#10",
                        "target_doc_id": 20,
                        "target_node_id": "dieu_16_dk_1#20",
                        "relation_type": "sua_doi",
                    }
                ]

        repo = FakeNeo4jRepository()

        result = repo.fetch_relationship_endpoint_keys_for_sources([10])

        self.assertEqual(
            result,
            [
                {
                    "source": "cls_graph",
                    "source_doc_id": 10,
                    "source_node_id": "dieu_1#10",
                    "target_doc_id": 20,
                    "target_node_id": "dieu_16_dk_1#20",
                    "relation_type": "sua_doi",
                }
            ],
        )
        self.assertEqual(repo.parameters, {"doc_ids": [10]})
        self.assertIn("toString(a.ID) AS source_node_id", repo.query)
        self.assertIn("toString(b.ID) AS target_node_id", repo.query)
        self.assertIn("r.nguon_cap_nhat IS NOT NULL", repo.query)
        self.assertIn("type(r) <> 'bao_gom'", repo.query)
        self.assertIn("type(r) <> 'bao_gom_sau_bo_sung'", repo.query)
        self.assertIn("WHEN r.nguon_cap_nhat = 'cmcai' THEN 'cls_graph'", repo.query)
        self.assertIn("WHEN r.nguon_cap_nhat = 'tvpl' THEN 'tvpl'", repo.query)
        self.assertNotIn("nguon_quan_he", repo.query)
        self.assertNotIn("pham_vi", repo.query)


if __name__ == "__main__":
    unittest.main()
