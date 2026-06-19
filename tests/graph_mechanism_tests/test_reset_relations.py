import unittest
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch


neo4j_module = types.ModuleType("neo4j")
neo4j_module.GraphDatabase = object
neo4j_module.Driver = object
neo4j_module.Session = object
neo4j_module.Transaction = object
neo4j_exceptions = types.ModuleType("neo4j.exceptions")
neo4j_exceptions.Neo4jError = Exception

repo_path = Path(__file__).resolve().parents[2] / "src" / "repositories" / "neo4j_repository.py"
spec = importlib.util.spec_from_file_location("neo4j_repository_under_test_reset", repo_path)
neo4j_repository_module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"neo4j": neo4j_module, "neo4j.exceptions": neo4j_exceptions}):
    spec.loader.exec_module(neo4j_repository_module)
Neo4jRepository = neo4j_repository_module.Neo4jRepository
RESET_REL_TX_SIZE = neo4j_repository_module.RESET_REL_TX_SIZE


class FakeResult:
    def __init__(self, deleted_count):
        self._deleted_count = deleted_count

    def single(self):
        return {"deleted_count": self._deleted_count}


class FakeSession:
    def __init__(self, recorder, counts):
        self.recorder = recorder
        self.counts = counts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **parameters):
        self.recorder.append({"query": query, "parameters": parameters})
        count = self.counts.pop(0) if self.counts else 0
        return FakeResult(count)


class FakeDriver:
    def __init__(self, counts):
        self.recorder = []
        self.counts = list(counts)
        self.database = None

    def session(self, database):
        self.database = database
        return FakeSession(self.recorder, self.counts)


class TestResetOutgoingRelationshipsByIds(unittest.TestCase):
    def test_preserves_bao_gom_and_bao_gom_sau_bo_sung(self):
        driver = FakeDriver(counts=[3, 5])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        vb_count, dk_count = repo.reset_outgoing_relationships_by_ids([101], batch_size=500)

        self.assertEqual((vb_count, dk_count), (3, 5))
        self.assertEqual(len(driver.recorder), 2)
        for call in driver.recorder:
            self.assertIn("NOT type(r) IN $preserved", call["query"])
            self.assertEqual(
                set(call["parameters"]["preserved"]),
                {"bao_gom", "bao_gom_sau_bo_sung"},
            )

    def test_traverses_only_bao_gom_to_reach_clause_depth(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.reset_outgoing_relationships_by_ids([101], batch_size=500)

        dieu_khoan_query = driver.recorder[1]["query"]
        self.assertIn("[:bao_gom*]", dieu_khoan_query)
        self.assertNotIn("bao_gom_sau_bo_sung*", dieu_khoan_query)

    def test_no_detach_or_node_deletion(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.reset_outgoing_relationships_by_ids([101], batch_size=500)

        for call in driver.recorder:
            self.assertNotIn("DETACH", call["query"])
            self.assertNotIn("DELETE v", call["query"])
            self.assertNotIn("DELETE d", call["query"])

    def test_deletes_relationships_in_batched_transactions(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.reset_outgoing_relationships_by_ids([101], batch_size=500)

        expected_fragment = (
            f"CALL {{ WITH r DELETE r }} IN TRANSACTIONS OF {RESET_REL_TX_SIZE} ROWS"
        )
        for call in driver.recorder:
            self.assertIn(expected_fragment, call["query"])

    def test_only_outgoing_relationships_are_matched(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.reset_outgoing_relationships_by_ids([101], batch_size=500)

        vb_query, dk_query = driver.recorder[0]["query"], driver.recorder[1]["query"]
        self.assertIn("MATCH (v)-[r]->()", vb_query)
        self.assertIn("MATCH (d)-[r]->()", dk_query)
        for call in driver.recorder:
            self.assertNotIn("<-[r]-", call["query"])
            self.assertNotIn("(v)<-", call["query"])
            self.assertNotIn("(d)<-", call["query"])

    def test_scopes_match_to_in_scope_ids_leaving_out_of_scope_incoming_rels_intact(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.reset_outgoing_relationships_by_ids([101, 102], batch_size=500)

        self.assertEqual(len(driver.recorder), 2)
        for call in driver.recorder:
            self.assertIn("MATCH (v:VAN_BAN)", call["query"])
            self.assertIn("WHERE v.ID IN $ids", call["query"])
            self.assertEqual(call["parameters"]["ids"], [101, 102])

    def test_chunks_doc_ids_by_batch_size(self):
        driver = FakeDriver(counts=[1, 2, 3, 4])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        vb_count, dk_count = repo.reset_outgoing_relationships_by_ids(
            [101, 102, 103], batch_size=2
        )

        self.assertEqual(len(driver.recorder), 4)
        self.assertEqual(driver.recorder[0]["parameters"]["ids"], [101, 102])
        self.assertEqual(driver.recorder[2]["parameters"]["ids"], [103])
        self.assertEqual((vb_count, dk_count), (1 + 3, 2 + 4))


if __name__ == "__main__":
    unittest.main()
