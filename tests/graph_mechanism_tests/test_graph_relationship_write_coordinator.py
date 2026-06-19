import json
import shutil
import unittest
from pathlib import Path

from src.services.graph_relationship_write_coordinator import (
    GraphNodeAutoHealer,
    GraphRelationshipWriteCoordinator,
)


class FakeRepository:
    def __init__(self, existing_nodes=None, node_properties=None, variant_nodes=None):
        self.existing_nodes = set(existing_nodes or [])
        self.node_properties = node_properties or {}
        self.variant_nodes = variant_nodes or {}
        self.grouped_writes = []
        self.tvpl_writes = []
        self.node_writes = []

    def fetch_existing_node_keys(self, node_refs):
        return {ref for ref in node_refs if ref in self.existing_nodes}

    def fetch_dieu_khoan_variant_node_keys(self, node_refs):
        return {
            ref: variant
            for ref, variant in self.variant_nodes.items()
            if ref in node_refs
        }

    def bulk_create_multiple_relationships(self, relationships_dict, strict_nodes=False):
        self.grouped_writes.append((relationships_dict, strict_nodes))
        result = {rel_type: len(params) for rel_type, params in relationships_dict.items()}
        result["total"] = sum(result.values())
        return result

    def bulk_create_tvpl_relationships(self, rel_list, query):
        self.tvpl_writes.append((rel_list, query))
        return len(rel_list)

    def bulk_upsert_nodes(self, doc_params, term_params):
        self.node_writes.append((doc_params, term_params))
        for param in term_params:
            node_id = param.get("ID")
            if node_id:
                self.existing_nodes.add(("DIEU_KHOAN", node_id))
        for param in doc_params:
            node_id = param.get("ID") or param.get("cls_ID")
            if node_id:
                self.existing_nodes.add(("VAN_BAN", node_id))

    def fetch_node_properties(self, node_refs, property_names):
        return {
            ref: {
                name: self.node_properties.get(ref, {}).get(name)
                for name in property_names
            }
            for ref in node_refs
        }


class FakeNodeHealer:
    def __init__(self, repo, nodes_to_heal):
        self.repo = repo
        self.nodes_to_heal = set(nodes_to_heal)
        self.calls = []

    def ensure_nodes(self, node_refs):
        refs = set(node_refs)
        self.calls.append(refs)
        healed = refs & self.nodes_to_heal
        self.repo.existing_nodes.update(healed)
        return healed


class TestGraphRelationshipWriteCoordinator(unittest.TestCase):
    def test_strict_auto_heal_builds_missing_target_then_writes_strict(self):
        repo = FakeRepository(existing_nodes={("VAN_BAN", 10)})
        healer = FakeNodeHealer(repo, nodes_to_heal={("VAN_BAN", 20)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
            node_healer=healer,
        )
        grouped = {
            "huong_dan": [
                {
                    "head_ID": 10,
                    "tail_ID": 20,
                    "head_class": "VAN_BAN",
                    "tail_class": "VAN_BAN",
                    "bang_chung": "evidence",
                }
            ]
        }

        result = coordinator.write_grouped_relationships(grouped)

        self.assertEqual(result["total"], 1)
        self.assertEqual(repo.grouped_writes[0][1], True)
        self.assertEqual(healer.calls, [{("VAN_BAN", 20)}])
        self.assertEqual(coordinator.summary()["written"], 1)
        self.assertEqual(coordinator.summary()["healed_nodes"], 1)
        self.assertEqual(coordinator.summary()["deferred"], 0)

    def test_strict_writer_upserts_inserted_clause_targets_before_partition(self):
        repo = FakeRepository(existing_nodes={("DIEU_KHOAN", "dieu_1#20"), ("VAN_BAN", 20)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
        )
        grouped = {
            "bo_sung": [
                {
                    "head_ID": "dieu_1#20",
                    "tail_ID": "dieu_8a#20",
                    "head_class": "DIEU_KHOAN",
                    "tail_class": "DIEU_KHOAN",
                    "target_node_props": {
                        "ID": "dieu_8a#20",
                        "cap_do": "dieu",
                        "tieu_de": "Inserted clause",
                    },
                }
            ],
            "bao_gom_sau_bo_sung": [
                {
                    "head_ID": 20,
                    "tail_ID": "dieu_8a#20",
                    "head_class": "VAN_BAN",
                    "tail_class": "DIEU_KHOAN",
                    "target_node_props": {
                        "ID": "dieu_8a#20",
                        "cap_do": "dieu",
                        "tieu_de": "Inserted clause",
                    },
                }
            ],
        }

        result = coordinator.write_grouped_relationships(grouped)

        self.assertEqual(result["total"], 2)
        self.assertEqual(repo.grouped_writes[0][1], True)
        self.assertIn(("DIEU_KHOAN", "dieu_8a#20"), repo.existing_nodes)
        self.assertEqual(repo.node_writes[0][1][0]["ID"], "dieu_8a#20")
        self.assertEqual(coordinator.summary()["written"], 2)
        self.assertEqual(coordinator.summary()["healed_nodes"], 1)
        self.assertEqual(coordinator.summary()["deferred"], 0)

    def test_strict_no_heal_defers_missing_target_without_writing(self):
        repo = FakeRepository(existing_nodes={("VAN_BAN", 10)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-no-heal",
        )
        grouped = {
            "huong_dan": [
                {
                    "head_ID": 10,
                    "tail_ID": 20,
                    "head_class": "VAN_BAN",
                    "tail_class": "VAN_BAN",
                }
            ]
        }

        result = coordinator.write_grouped_relationships(grouped)

        self.assertEqual(result["total"], 0)
        self.assertEqual(repo.grouped_writes, [])
        self.assertEqual(coordinator.summary()["deferred"], 1)
        self.assertEqual(coordinator.detail_records[0]["reason"], "missing_target")

    def test_strict_writer_remaps_missing_clause_target_to_unique_dk_variant(self):
        repo = FakeRepository(
            existing_nodes={
                ("DIEU_KHOAN", "dieu_1#10"),
                ("DIEU_KHOAN", "dieu_16_dk_1#20"),
            },
            variant_nodes={
                ("DIEU_KHOAN", "dieu_16#20"): ("DIEU_KHOAN", "dieu_16_dk_1#20"),
            },
        )
        healer = FakeNodeHealer(repo, nodes_to_heal=set())
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
            node_healer=healer,
        )

        result = coordinator.write_grouped_relationships(
            {
                "sua_doi": [
                    {
                        "head_ID": "dieu_1#10",
                        "tail_ID": "dieu_16#20",
                        "head_class": "DIEU_KHOAN",
                        "tail_class": "DIEU_KHOAN",
                    }
                ]
            }
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(healer.calls, [])
        self.assertEqual(coordinator.summary()["written"], 1)
        self.assertEqual(coordinator.summary()["deferred"], 0)
        written = repo.grouped_writes[0][0]["sua_doi"][0]
        self.assertEqual(written["tail_ID"], "dieu_16_dk_1#20")

    def test_strict_auto_heal_reports_target_not_found_in_mongo(self):
        class EmptyCollection:
            def find(self, query):
                self.query = query
                return []

        class FakeNodePrep:
            def batch_prepare_nodes(self, docs):
                raise AssertionError("node preparation should not run without Mongo docs")

        repo = FakeRepository(existing_nodes={("VAN_BAN", 10)})
        healer = GraphNodeAutoHealer(
            cls_collection=EmptyCollection(),
            node_prep_service=FakeNodePrep(),
            neo4j_repository=repo,
        )
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
            node_healer=healer,
        )

        result = coordinator.write_grouped_relationships(
            {
                "huong_dan": [
                    {
                        "head_ID": 10,
                        "tail_ID": 20,
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                    }
                ]
            }
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(coordinator.detail_records[0]["reason"], "target_not_found_in_mongo")
        self.assertFalse(coordinator.detail_records[0]["retryable"])
        self.assertEqual(
            coordinator.detail_records[0]["retry_action"],
            "ingest_missing_cls_document_then_rerun",
        )
        self.assertEqual(
            coordinator.summary()["reason_counts"],
            {"target_not_found_in_mongo": 1},
        )

    def test_strict_auto_heal_reports_source_not_found_in_mongo_with_retry_audit(self):
        class EmptyCollection:
            def find(self, query):
                return []

        class FakeNodePrep:
            def batch_prepare_nodes(self, docs):
                raise AssertionError("node preparation should not run without Mongo docs")

        repo = FakeRepository(existing_nodes={("VAN_BAN", 20)})
        healer = GraphNodeAutoHealer(
            cls_collection=EmptyCollection(),
            node_prep_service=FakeNodePrep(),
            neo4j_repository=repo,
        )
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
            node_healer=healer,
        )

        result = coordinator.write_grouped_relationships(
            {
                "huong_dan": [
                    {
                        "head_ID": 10,
                        "tail_ID": 20,
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                    }
                ]
            }
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(coordinator.summary()["deferred"], 1)
        self.assertEqual(coordinator.detail_records[0]["reason"], "source_not_found_in_mongo")
        self.assertFalse(coordinator.detail_records[0]["retryable"])
        self.assertEqual(
            coordinator.detail_records[0]["retry_action"],
            "ingest_missing_cls_document_then_rerun",
        )

    def test_existing_target_with_mismatched_expected_symbol_is_rejected(self):
        repo = FakeRepository(
            existing_nodes={("VAN_BAN", 10), ("VAN_BAN", 20)},
            node_properties={("VAN_BAN", 20): {"so_hieu": "1234/ABC"}},
        )
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
        )

        result = coordinator.write_grouped_relationships(
            {
                "huong_dan": [
                    {
                        "head_ID": 10,
                        "tail_ID": 20,
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                        "target_so_ky_hieu_expected": "1234/HN-VN",
                    }
                ]
            }
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(repo.grouped_writes, [])
        self.assertEqual(coordinator.summary()["rejected"], 1)
        self.assertEqual(coordinator.detail_records[0]["reason"], "target_symbol_mismatch")
        self.assertFalse(coordinator.detail_records[0]["retryable"])
        self.assertEqual(
            coordinator.detail_records[0]["retry_action"],
            "review_target_resolution_before_rerun",
        )
        self.assertEqual(coordinator.detail_records[0]["expected_symbol"], "1234/HN-VN")
        self.assertEqual(coordinator.detail_records[0]["actual_symbol"], "1234/ABC")

    def test_existing_target_with_mismatched_expected_agency_or_year_is_rejected(self):
        cases = [
            (
                {"target_co_quan_expected": "HN-VN"},
                {"co_quan_ban_hanh": "BTP"},
                "target_agency_mismatch",
            ),
            (
                {"target_year_expected": 2024},
                {"ngay_ban_hanh": "15/03/2023"},
                "target_year_mismatch",
            ),
        ]

        for expected_fields, actual_props, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                repo = FakeRepository(
                    existing_nodes={("VAN_BAN", 10), ("VAN_BAN", 20)},
                    node_properties={("VAN_BAN", 20): actual_props},
                )
                coordinator = GraphRelationshipWriteCoordinator(
                    neo4j_repository=repo,
                    mode="strict-auto-heal",
                )

                result = coordinator.write_grouped_relationships(
                    {
                        "huong_dan": [
                            {
                                "head_ID": 10,
                                "tail_ID": 20,
                                "head_class": "VAN_BAN",
                                "tail_class": "VAN_BAN",
                                **expected_fields,
                            }
                        ]
                    }
                )

                self.assertEqual(result["total"], 0)
                self.assertEqual(repo.grouped_writes, [])
                self.assertEqual(coordinator.summary()["rejected"], 1)
                self.assertEqual(coordinator.detail_records[0]["reason"], expected_reason)

    def test_shadow_strict_reports_missing_target_but_uses_legacy_writer(self):
        repo = FakeRepository(existing_nodes={("VAN_BAN", 10)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="shadow-strict",
        )
        grouped = {
            "huong_dan": [
                {
                    "head_ID": 10,
                    "tail_ID": 20,
                    "head_class": "VAN_BAN",
                    "tail_class": "VAN_BAN",
                }
            ]
        }

        result = coordinator.write_grouped_relationships(grouped)

        self.assertEqual(result["total"], 1)
        self.assertEqual(repo.grouped_writes[0][1], False)
        self.assertEqual(coordinator.summary()["shadow_deferred"], 1)

    def test_duplicate_relationships_merge_evidence_and_id_relations(self):
        repo = FakeRepository(existing_nodes={("VAN_BAN", 10), ("VAN_BAN", 20)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-no-heal",
        )
        grouped = {
            "huong_dan": [
                {
                    "head_ID": 10,
                    "tail_ID": 20,
                    "head_class": "VAN_BAN",
                    "tail_class": "VAN_BAN",
                    "pham_vi": "document",
                    "bang_chung": "Hướng dẫn Luật Đất đai",
                    "danh_sach_id_lien_quan": {"dieu_1#10": ["dieu_2#20"]},
                },
                {
                    "head_ID": 10,
                    "tail_ID": 20,
                    "head_class": "VAN_BAN",
                    "tail_class": "VAN_BAN",
                    "pham_vi": "document",
                    "bang_chung": "Quy định chi tiết điểm đ khoản 2 Điều 5",
                    "danh_sach_id_lien_quan": {"dieu_3#10": ["dieu_4#20"]},
                },
            ]
        }

        coordinator.write_grouped_relationships(grouped)

        written = repo.grouped_writes[0][0]["huong_dan"]
        self.assertEqual(len(written), 1)
        self.assertNotIn("danh_sach_bang_chung", written[0])
        self.assertNotIn("so_lan_phat_hien", written[0])
        self.assertEqual(
            written[0]["danh_sach_id_lien_quan"],
            {"dieu_1#10": ["dieu_2#20"], "dieu_3#10": ["dieu_4#20"]},
        )

    def test_writes_summary_and_detail_audit_files(self):
        repo = FakeRepository(existing_nodes={("VAN_BAN", 10)})
        coordinator = GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-no-heal",
        )
        coordinator.write_grouped_relationships(
            {
                "huong_dan": [
                    {
                        "head_ID": 10,
                        "tail_ID": 20,
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                    }
                ]
            }
        )

        tmp_path = Path("scratch") / "test_graph_relationship_audit"
        shutil.rmtree(tmp_path, ignore_errors=True)
        tmp_path.mkdir(parents=True, exist_ok=True)
        try:
            summary_path = tmp_path / "summary.json"
            detail_path = tmp_path / "detail.ndjson"

            coordinator.write_audit_files(summary_path, detail_path)

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            detail = [
                json.loads(line)
                for line in detail_path.read_text(encoding="utf-8").splitlines()
            ]
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

        self.assertEqual(summary["deferred"], 1)
        self.assertEqual(summary["reason_counts"], {"missing_target": 1})
        self.assertEqual(detail[0]["target_doc_id"], 20)


class TestGraphNodeAutoHealer(unittest.TestCase):
    def test_auto_healer_builds_van_ban_and_parent_clause_nodes_from_mongo(self):
        class FakeCursor(list):
            pass

        class FakeCollection:
            def find(self, query):
                self.query = query
                return FakeCursor([{"cls_ID": 20}, {"cls_ID": 30}])

        class FakeNodePrep:
            def batch_prepare_nodes(self, docs):
                doc_params = [{"ID": doc["cls_ID"]} for doc in docs]
                term_params = [{"ID": f"dieu_1#{doc['cls_ID']}"} for doc in docs]
                return doc_params, term_params

        class FakeRepo:
            def __init__(self):
                self.existing_nodes = set()
                self.bulk_calls = []

            def bulk_upsert_nodes(self, doc_params, term_params):
                self.bulk_calls.append((doc_params, term_params))
                for param in doc_params:
                    self.existing_nodes.add(("VAN_BAN", param["ID"]))
                for param in term_params:
                    self.existing_nodes.add(("DIEU_KHOAN", param["ID"]))

            def fetch_existing_node_keys(self, refs):
                return set(refs) & self.existing_nodes

        repo = FakeRepo()
        collection = FakeCollection()
        healer = GraphNodeAutoHealer(
            cls_collection=collection,
            node_prep_service=FakeNodePrep(),
            neo4j_repository=repo,
        )

        healed = healer.ensure_nodes({("VAN_BAN", 20), ("DIEU_KHOAN", "dieu_1#30")})

        self.assertEqual(collection.query, {"cls_ID": {"$in": [20, 30]}})
        self.assertEqual(healed, {("VAN_BAN", 20), ("DIEU_KHOAN", "dieu_1#30")})
        self.assertEqual(len(repo.bulk_calls), 1)


class FakeRepositoryWithNeo4jSession:
    """Fake repository that also supports a driver.session() for TVPL conflict queries."""

    def __init__(self, existing_nodes=None, existing_rels=None):
        self.existing_nodes = set(existing_nodes or [])
        self.tvpl_writes = []
        self._existing_rels = existing_rels or []  # list of {head_ID, tail_ID, rel_type}

    def fetch_existing_node_keys(self, node_refs):
        return {ref for ref in node_refs if ref in self.existing_nodes}

    def bulk_create_multiple_relationships(self, relationships_dict, strict_nodes=False):
        return {"total": sum(len(v) for v in relationships_dict.values())}

    def bulk_create_tvpl_relationships(self, rel_list, query):
        self.tvpl_writes.append(list(rel_list))
        return len(rel_list)

    def bulk_upsert_nodes(self, doc_params, term_params):
        pass

    def fetch_node_properties(self, node_refs, property_names):
        return {}

    @property
    def driver(self):
        existing = self._existing_rels
        return _FakeDriver(existing)

    @property
    def database(self):
        return "neo4j"


class _FakeSession:
    def __init__(self, existing_rels):
        self._existing_rels = existing_rels

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **params):
        pairs = params.get("pairs", [])
        conflict_types = params.get("conflict_types", [])
        rows = []
        for pair in pairs:
            hid = pair["head_ID"]
            tid = pair["tail_ID"]
            for rel in self._existing_rels:
                if (rel["head_ID"] == hid and rel["tail_ID"] == tid
                        and rel["rel_type"] in conflict_types):
                    rows.append({"head_ID": hid, "tail_ID": tid, "rel_type": rel["rel_type"]})
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _FakeDriver:
    def __init__(self, existing_rels):
        self._existing_rels = existing_rels

    def session(self, database=None):
        return _FakeSession(self._existing_rels)


class TestTVPLConflictFilter(unittest.TestCase):
    """write_tvpl_relationships must skip relations that conflict with existing Neo4j rels."""

    def _coordinator(self, existing_rels=None, existing_nodes=None):
        repo = FakeRepositoryWithNeo4jSession(
            existing_nodes=set(existing_nodes or [("VAN_BAN", 10), ("VAN_BAN", 20)]),
            existing_rels=existing_rels or [],
        )
        return GraphRelationshipWriteCoordinator(
            neo4j_repository=repo,
            mode="strict-auto-heal",
        ), repo

    def _tvpl_rel(self, rel_type, head_id=10, tail_id=20):
        return {
            "rel_type": rel_type,
            "head_ID": head_id,
            "tail_ID": tail_id,
            "head_class": "VAN_BAN",
            "tail_class": "VAN_BAN",
        }

    def test_no_existing_conflict_writes_tvpl(self):
        coordinator, repo = self._coordinator()
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("bai_bo")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 1)
        self.assertEqual(len(repo.tvpl_writes[0]), 1)

    def test_existing_bai_bo_blocks_incoming_tvpl_thay_the(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "bai_bo"}]
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("thay_the")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 0, "thay_the must be blocked by existing bai_bo")

    def test_existing_thay_the_blocks_incoming_tvpl_bai_bo(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "thay_the"}]
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("bai_bo")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 0, "bai_bo must be blocked by existing thay_the")

    def test_existing_sua_doi_bo_sung_blocks_tvpl_thay_the_and_bai_bo(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "sua_doi_bo_sung"}]
        )
        rels = [self._tvpl_rel("thay_the"), self._tvpl_rel("bai_bo"), self._tvpl_rel("huy_bo")]
        coordinator.write_tvpl_relationships(rels, query="FAKE_QUERY")
        self.assertEqual(len(repo.tvpl_writes), 0, "all conflict rels must be blocked by sua_doi_bo_sung")

    def test_existing_bai_bo_blocks_tvpl_huy_bo(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "bai_bo"}]
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("huy_bo")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 0)

    def test_existing_bai_bo_does_not_block_same_group_incoming(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "bai_bo"}]
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("bai_bo")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 1, "same-group (bai_bo) must still be written")

    def test_non_conflict_type_always_written(self):
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "bai_bo"}]
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("dan_chieu")], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 1, "dan_chieu must pass through")

    def test_conflict_only_on_same_pair(self):
        """Existing conflict for pair (10,20) must not block writes for pair (10,30)."""
        coordinator, repo = self._coordinator(
            existing_rels=[{"head_ID": 10, "tail_ID": 20, "rel_type": "bai_bo"}],
            existing_nodes={("VAN_BAN", 10), ("VAN_BAN", 20), ("VAN_BAN", 30)},
        )
        coordinator.write_tvpl_relationships(
            [self._tvpl_rel("thay_the", head_id=10, tail_id=30)], query="FAKE_QUERY"
        )
        self.assertEqual(len(repo.tvpl_writes), 1, "different target pair must not be blocked")


if __name__ == "__main__":
    unittest.main()
