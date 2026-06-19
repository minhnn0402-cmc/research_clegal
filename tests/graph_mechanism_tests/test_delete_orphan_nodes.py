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
spec = importlib.util.spec_from_file_location("neo4j_repository_under_test_orphans", repo_path)
neo4j_repository_module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"neo4j": neo4j_module, "neo4j.exceptions": neo4j_exceptions}):
    spec.loader.exec_module(neo4j_repository_module)
Neo4jRepository = neo4j_repository_module.Neo4jRepository
ORPHAN_NODE_TX_SIZE = neo4j_repository_module.ORPHAN_NODE_TX_SIZE


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


class TestDeleteOrphanNodes(unittest.TestCase):
    def test_returns_per_label_deleted_counts(self):
        driver = FakeDriver(counts=[7, 11])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        vb_count, dk_count = repo.delete_orphan_nodes()

        self.assertEqual((vb_count, dk_count), (7, 11))
        self.assertEqual(len(driver.recorder), 2)

    def test_matches_each_label_with_no_relationships_filter(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.delete_orphan_nodes()

        vb_query, dk_query = driver.recorder[0]["query"], driver.recorder[1]["query"]
        self.assertIn("MATCH (v:VAN_BAN)", vb_query)
        self.assertIn("WHERE NOT (v)--()", vb_query)
        self.assertIn("MATCH (d:DIEU_KHOAN)", dk_query)
        self.assertIn("WHERE NOT (d)--()", dk_query)

    def test_deletes_in_batched_transactions_with_default_size(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.delete_orphan_nodes()

        for call in driver.recorder:
            self.assertIn(f"IN TRANSACTIONS OF {ORPHAN_NODE_TX_SIZE} ROWS", call["query"])

    def test_respects_custom_batch_size(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.delete_orphan_nodes(batch_size=250)

        for call in driver.recorder:
            self.assertIn("IN TRANSACTIONS OF 250 ROWS", call["query"])

    def test_no_detach_needed_for_orphans(self):
        driver = FakeDriver(counts=[0, 0])
        repo = Neo4jRepository(driver=driver, database="neo4jtest")

        repo.delete_orphan_nodes()

        for call in driver.recorder:
            self.assertNotIn("DETACH", call["query"])


if __name__ == "__main__":
    unittest.main()
