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
spec = importlib.util.spec_from_file_location("neo4j_repository_under_test", repo_path)
neo4j_repository_module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"neo4j": neo4j_module, "neo4j.exceptions": neo4j_exceptions}):
    spec.loader.exec_module(neo4j_repository_module)
Neo4jRepository = neo4j_repository_module.Neo4jRepository


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, parameters=None, **kwargs):
        self.query = query
        self.parameters = parameters or kwargs
        return self.rows

    def execute_read(self, work):
        return work(self)


class FakeDriver:
    def __init__(self, rows):
        self.session_obj = FakeSession(rows)
        self.database = None

    def session(self, database):
        self.database = database
        return self.session_obj


class TestNeo4jRepository(unittest.TestCase):
    def test_fetch_node_properties_returns_requested_properties_by_node_ref(self):
        driver = FakeDriver(
            [
                {
                    "label": "VAN_BAN",
                    "id": 20,
                    "props": {
                        "so_hieu": "1234/HN-VN",
                        "nam_ban_hanh": 2020,
                        "unused": "ignored",
                    },
                }
            ]
        )
        repo = Neo4jRepository(driver=driver, database="neo4j")

        result = repo.fetch_node_properties(
            [("VAN_BAN", 20)],
            ["so_hieu", "nam_ban_hanh", "missing_prop"],
        )

        self.assertEqual(driver.database, "neo4j")
        self.assertIn("properties(n) AS props", driver.session_obj.query)
        self.assertEqual(driver.session_obj.parameters["nodes"], [{"label": "VAN_BAN", "id": 20}])
        self.assertEqual(
            result,
            {
                ("VAN_BAN", 20): {
                    "so_hieu": "1234/HN-VN",
                    "nam_ban_hanh": 2020,
                    "missing_prop": None,
                }
            },
        )

    def test_fetch_dieu_khoan_variant_node_keys_returns_unique_variant_map(self):
        driver = FakeDriver(
            [
                {
                    "id": "dieu_16#20",
                    "variant_id": "dieu_16_dk_1#20",
                }
            ]
        )
        repo = Neo4jRepository(driver=driver, database="neo4j")

        result = repo.fetch_dieu_khoan_variant_node_keys(
            [
                ("DIEU_KHOAN", "dieu_16#20"),
                ("DIEU_KHOAN", "dieu_16_dk_1#20"),
                ("VAN_BAN", 20),
            ]
        )

        self.assertEqual(
            result,
            {("DIEU_KHOAN", "dieu_16#20"): ("DIEU_KHOAN", "dieu_16_dk_1#20")},
        )
        self.assertEqual(
            driver.session_obj.parameters["nodes"],
            [{"id": "dieu_16#20", "prefix": "dieu_16", "suffix": "20"}],
        )
        self.assertIn("n.ID STARTS WITH (node_ref.prefix + '_dk_')", driver.session_obj.query)
        self.assertIn("n.ID STARTS WITH (node_ref.prefix + '_bosung_')", driver.session_obj.query)
        self.assertIn("WHERE size(matches) = 1", driver.session_obj.query)

    def test_get_skeleton_node_ids_scopes_dieukhoan_lookup_to_source_documents(self):
        driver = FakeDriver([{"ID": "diem_a_khoan_1_dieu_2#20"}])
        repo = Neo4jRepository(driver=driver, database="neo4j")

        result = repo.get_skeleton_node_ids("DIEU_KHOAN", source_doc_ids=[168398])

        self.assertEqual(result, ["diem_a_khoan_1_dieu_2#20"])
        self.assertEqual(driver.session_obj.parameters["source_doc_ids"], [168398])
        self.assertIn("MATCH (source:VAN_BAN)", driver.session_obj.query)
        self.assertIn("source.ID IN $source_doc_ids", driver.session_obj.query)
        self.assertIn("bao_gom_sau_bo_sung*1..3", driver.session_obj.query)
        self.assertIn("UNWIND candidates AS candidate", driver.session_obj.query)
        self.assertIn("WITH candidate", driver.session_obj.query)
        self.assertNotIn("CALL {", driver.session_obj.query)
        self.assertNotIn("MATCH (n:DIEU_KHOAN) WHERE size(keys(n)) <= 1", driver.session_obj.query)


if __name__ == "__main__":
    unittest.main()
