import unittest

from src.domain.graph import RelationEvent
from src.services.graph_target_resolver import GraphTargetResolver


class FakeRepository:
    def verify_node_exists(self, node_id, label="VAN_BAN"):
        return node_id == 20


class TestGraphTargetResolver(unittest.TestCase):
    def test_strict_mode_rejects_missing_target(self):
        event = RelationEvent(10, 99, "huong_dan", "cls_graph", "document")
        resolver = GraphTargetResolver(FakeRepository(), mode="strict")

        result = resolver.resolve(event)

        self.assertEqual(result.resolution_status, "missing_target")
        self.assertEqual(result.target_doc_id, None)
        self.assertIn("99", result.resolution_reason)

    def test_permissive_mode_keeps_missing_target_as_skeleton(self):
        event = RelationEvent(10, 99, "huong_dan", "cls_graph", "document")
        resolver = GraphTargetResolver(FakeRepository(), mode="permissive")

        result = resolver.resolve(event)

        self.assertEqual(result.resolution_status, "skeleton_target")
        self.assertEqual(result.target_doc_id, 99)

    def test_existing_target_is_resolved(self):
        event = RelationEvent(10, 20, "huong_dan", "cls_graph", "document")
        resolver = GraphTargetResolver(FakeRepository(), mode="strict")

        result = resolver.resolve(event)

        self.assertEqual(result.resolution_status, "resolved")
        self.assertEqual(result.target_doc_id, 20)


if __name__ == "__main__":
    unittest.main()
