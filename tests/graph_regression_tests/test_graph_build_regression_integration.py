"""Layer 4: integration/runtime regression tests."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, List

from tests.graph_regression_tests.helpers import (
    active,
    import_service_module_with_fake_infrastructure,
    load_cases,
)


logging.disable(logging.INFO)


class _FakeLogger:
    def debug(self, *args, **kwargs) -> None:
        pass

    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass


class TestIntegrationRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()

    def test_reset_relations_before_build_calls_repository(self) -> None:
        """EC-24: --reset-relations must call reset_outgoing_relationships_by_ids with the exact IDs."""
        module = import_service_module_with_fake_infrastructure(
            "src.services.neo4j_preparation"
        )
        LegalKnowledgeGraphBuilder = module.LegalKnowledgeGraphBuilder

        for case in active(self.cases["build_graph_cases"]):
            with self.subTest(case_id=case["id"]):
                builder = object.__new__(LegalKnowledgeGraphBuilder)
                builder.logger = _FakeLogger()
                reset_calls: List[List[int]] = []

                class _FakeRepo:
                    def reset_outgoing_relationships_by_ids(self, ids, batch_size=500):
                        reset_calls.append(list(ids))
                        return 0, 0

                builder.neo4j_repository = _FakeRepo()
                builder.reset_relations_before_build(case["ids_to_process"])

                self.assertEqual(reset_calls, [case["ids_to_process"]])

    def test_inferred_relation_transform_keeps_clause_detail(self) -> None:
        """EC-23 backend contract: inferred graph data must preserve source/target clause detail."""
        module = import_service_module_with_fake_infrastructure(
            "src.services.infer_relations"
        )
        RelationTransformer = module.RelationTransformer

        for case in active(self.cases.get("inferred_relation_cases", [])):
            with self.subTest(case_id=case["id"]):
                result = RelationTransformer.transform_cls_graph(
                    cls_graph=case["cls_graph"],
                    cls_ID=case["cls_ID"],
                )
                relation_group = next(
                    item for item in result
                    if item["inferred_relation"] == case["expected_inferred_relation"]
                )
                collection_item = next(
                    item for item in relation_group["collection"]
                    if item["target_doc_id"] == case["expected_target_doc_id"]
                )
                self.assertEqual(
                    collection_item["id_relations"],
                    case["expected_id_relations"],
                )
                self.assertEqual(
                    collection_item["relation"],
                    case["expected_original_relation"],
                )

    def test_ui_relation_contract_prefers_cls_graph_and_supplements_tvpl(self) -> None:
        """EC-23: UI contract prefers cls_graph relation; TVPL only supplements."""
        module = import_service_module_with_fake_infrastructure(
            "src.services.infer_relations"
        )
        RelationTransformer = module.RelationTransformer

        for case in active(self.cases.get("ui_relation_source_cases", [])):
            with self.subTest(case_id=case["id"]):
                inferred = RelationTransformer.transform_cls_graph(
                    cls_graph=case["cls_graph"],
                    cls_ID=case["cls_ID"],
                )
                cls_graph_items = []
                for group in inferred:
                    for item in group["collection"]:
                        cls_graph_items.append(
                            {
                                "source": "cls_graph",
                                "relationship": item["relation"],
                                "target_doc_id": item["target_doc_id"],
                                "id_relations": item["id_relations"],
                                "inferred_relation": group["inferred_relation"],
                            }
                        )

                primary = next(
                    item for item in cls_graph_items
                    if item["target_doc_id"] == case["expected_primary_target_doc_id"]
                )
                supplemental = [
                    item for item in case["tvpl_relations"]
                    if not any(
                        cls_item["target_doc_id"] == item["target_doc_id"]
                        for cls_item in cls_graph_items
                    )
                ]

                self.assertEqual(primary["source"], case["expected_primary_source"])
                self.assertEqual(
                    primary["relationship"],
                    case["expected_primary_relation"],
                )
                self.assertNotEqual(
                    primary["relationship"],
                    case["forbidden_primary_relation"],
                )
                self.assertEqual(
                    sorted({item["source"] for item in supplemental}),
                    sorted(case["expected_supplement_sources"]),
                )

    def test_missing_cls_parsing_documents_skip_without_writing_garbage(self) -> None:
        """EC-25: malformed documents should be skipped, not crash or write cls_graph junk."""
        module = import_service_module_with_fake_infrastructure(
            "src.services.relations_processor_service"
        )
        RelationsProcessorService = module.RelationsProcessorService

        for case in active(self.cases.get("processor_runtime_cases", [])):
            with self.subTest(case_id=case["id"]):
                processor = object.__new__(RelationsProcessorService)
                processor.logger = _FakeLogger()
                processor.bulk_buffer = []
                processor.bulk_buffer_size = 100
                processor._lock = threading.RLock()
                processor.total_processing_time = 0
                processor.pbar = None

                for doc in case["documents"]:
                    self.assertEqual(
                        processor.process_document(doc),
                        case["expected_result"],
                    )

                self.assertEqual(
                    len(processor.bulk_buffer),
                    case["expected_bulk_buffer_size"],
                )

    def test_runtime_requirements_include_declared_dependencies(self) -> None:
        """Runtime smoke guard for dependencies used by graph extraction code."""
        requirements = (Path(__file__).parent.parent.parent / "requirements.txt").read_text(
            encoding="utf-8"
        ).lower()

        for case in active(self.cases["runtime_cases"]):
            with self.subTest(case_id=case["id"]):
                self.assertIn(
                    case["requirement"].lower(),
                    requirements,
                    case["reason"],
                )

    def test_status_relation_payload_uses_direct_edge_whitelist(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        service = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())
        rels = service.prepare_status_relationships_from_document(
            {
                "cls_ID": 10,
                "cls_graph": {
                    "success": [
                        {
                            "source_key": "dieu_1",
                            "source_type": "dieu",
                            "success": [
                                {
                                    "relationship": "huong_dan",
                                    "target_doc_id": 20,
                                    "target_key": "dieu_2",
                                    "description": "cls graph evidence",
                                }
                            ],
                        }
                    ]
                },
            }
        )

        rel = rels["huong_dan"][0]

        self.assertEqual(
            set(rel) - {"head_ID", "tail_ID", "head_class", "tail_class"},
            {"thoi_gian_cap_nhat", "nguon_cap_nhat"},
        )

    def test_clause_scoped_repeal_does_not_create_document_level_bai_bo(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService
        module = import_service_module_with_fake_infrastructure(
            "src.services.infer_relations"
        )
        RelationTransformer = module.RelationTransformer

        cls_graph = {
            "success": [
                {
                    "source_key": "dieu_1",
                    "source_type": "dieu",
                    "success": [
                        {
                            "relationship": "bai_bo",
                            "target_doc_id": 20,
                            "target_key": "khoan_4_dieu_18",
                            "description": "Bãi bỏ khoản 4 Điều 18 Nghị định số 103/2024/NĐ-CP",
                        }
                    ],
                }
            ]
        }

        status_service = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())
        rels = status_service.prepare_status_relationships_from_document(
            {"cls_ID": 10, "cls_graph": cls_graph}
        )

        self.assertEqual(len(rels["bai_bo"]), 1)
        self.assertEqual(rels["bai_bo"][0]["head_class"], "DIEU_KHOAN")
        self.assertEqual(rels["bai_bo"][0]["head_ID"], "dieu_1#10")
        self.assertEqual(rels["bai_bo"][0]["tail_class"], "DIEU_KHOAN")
        self.assertEqual(rels["bai_bo"][0]["tail_ID"], "khoan_4_dieu_18#20")
        self.assertFalse(
            any(
                rel["head_class"] == "VAN_BAN"
                and rel["tail_class"] == "VAN_BAN"
                and rel["head_ID"] == 10
                and rel["tail_ID"] == 20
                for rel in rels["bai_bo"]
            )
        )

        inferred = RelationTransformer.transform_cls_graph(cls_graph, cls_ID=10)
        self.assertEqual(inferred[0]["inferred_relation"], "sua_doi_bo_sung")
        self.assertEqual(inferred[0]["collection"][0]["relation"], "bai_bo")
        self.assertEqual(
            inferred[0]["collection"][0]["id_relations"],
            {"dieu_1#10": ["khoan_4_dieu_18#20"]},
        )

    def test_inferred_sdbs_suppresses_conflicting_document_thay_the(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        cls_graph = {
            "success": [
                {
                    "source_key": "khoan_3_dieu_71",
                    "source_type": "khoan",
                    "success": [
                        {
                            "relationship": "thay_the",
                            "target_doc_id": 20,
                            "target_key": None,
                            "description": "source clause says this document replaces target document",
                        }
                    ],
                },
                {
                    "source_key": "khoan_4_dieu_71",
                    "source_type": "khoan",
                    "success": [
                        {
                            "relationship": "bai_bo",
                            "target_doc_id": 20,
                            "target_key": "khoan_1_dieu_46",
                            "description": "source clause repeals one target clause",
                        }
                    ],
                },
            ],
            "inferred_relations": [
                {
                    "relation": "sua_doi_bo_sung",
                    "collection": [
                        {
                            "target_doc_id": 20,
                            "relation": "bai_bo",
                            "id_relations": {"khoan_4_dieu_71#10": ["khoan_1_dieu_46#20"]},
                        }
                    ],
                }
            ],
        }

        service = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())
        rels = service.prepare_status_relationships_from_document(
            {"cls_ID": 10, "cls_graph": cls_graph}
        )

        self.assertNotIn("thay_the", rels)
        self.assertEqual(len(rels["bai_bo"]), 1)
        self.assertEqual(rels["bai_bo"][0]["head_ID"], "khoan_4_dieu_71#10")
        self.assertEqual(rels["bai_bo"][0]["tail_ID"], "khoan_1_dieu_46#20")

    def test_clause_sua_doi_bo_sung_variants_infer_document_sdbs(self) -> None:
        module = import_service_module_with_fake_infrastructure(
            "src.services.infer_relations"
        )
        RelationTransformer = module.RelationTransformer

        inferred = RelationTransformer.transform_cls_graph(
            {
                "success": [
                    {
                        "source_key": "dieu_1",
                        "success": [
                            {
                                "relationship": "sua_doi",
                                "target_doc_id": 20,
                                "target_key": "dieu_2",
                            },
                            {
                                "relationship": "bo_sung",
                                "target_doc_id": 20,
                                "target_key": "dieu_3",
                            },
                        ],
                    }
                ]
            },
            cls_ID=10,
        )

        self.assertEqual(inferred[0]["inferred_relation"], "sua_doi_bo_sung")
        self.assertEqual(
            {item["relation"] for item in inferred[0]["collection"]},
            {"sua_doi", "bo_sung"},
        )

    def test_bo_sung_creates_added_clause_containment_payload(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        service = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())
        rels = service.prepare_status_relationships_from_document(
            {
                "cls_ID": 10,
                "cls_parsing": [
                    {
                        "com_key": "dieu_1",
                        "com_type": "dieu",
                        "com_title": 'Bổ sung Điều 8a như sau: "Nội dung Điều 8a mới."',
                    }
                ],
                "cls_graph": {
                    "success": [
                        {
                            "source_key": "dieu_1",
                            "source_type": "dieu",
                            "success": [
                                {
                                    "relationship": "bo_sung",
                                    "target_doc_id": 20,
                                    "target_key": "dieu_8a",
                                }
                            ],
                        }
                    ]
                },
            }
        )

        self.assertEqual(rels["bao_gom_sau_bo_sung"][0]["head_ID"], 20)
        self.assertEqual(rels["bao_gom_sau_bo_sung"][0]["tail_ID"], "dieu_8a#20")
        self.assertEqual(
            rels["bo_sung"][0]["target_node_props"]["noi_dung"],
            "Nội dung Điều 8a mới.",
        )

    def test_nested_bo_sung_creates_top_inserted_article_containment(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        service = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())
        rels = service.prepare_status_relationships_from_document(
            {
                "cls_ID": 168398,
                "cls_info": {"loai_van_ban": "Nghi dinh"},
                "cls_parsing": [
                    {
                        "com_key": "khoan_1_dieu_1",
                        "com_type": "khoan",
                        "com_title": 'Bo sung diem c vao khoan 2 Dieu 18b nhu sau: "Noi dung diem c."',
                    }
                ],
                "cls_graph": {
                    "success": [
                        {
                            "source_key": "khoan_1_dieu_1",
                            "source_type": "khoan",
                            "success": [
                                {
                                    "relationship": "bo_sung",
                                    "target_doc_id": 113297,
                                    "target_key": "diem_c_khoan_2_dieu_18b",
                                }
                            ],
                        }
                    ]
                },
            }
        )

        bgs_edges = {
            (item["head_ID"], item["tail_ID"])
            for item in rels["bao_gom_sau_bo_sung"]
        }

        self.assertIn((113297, "dieu_18b#113297"), bgs_edges)
        self.assertIn(("dieu_18b#113297", "khoan_2_dieu_18b#113297"), bgs_edges)
        self.assertIn(("khoan_2_dieu_18b#113297", "diem_c_khoan_2_dieu_18b#113297"), bgs_edges)

    def test_sua_doi_creates_synthetic_target_only_for_known_inserted_ancestor(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        doc = {
            "cls_ID": 168398,
            "cls_info": {"loai_van_ban": "Nghi dinh"},
            "cls_graph": {
                "success": [
                    {
                        "source_key": "khoan_2_dieu_1",
                        "source_type": "khoan",
                        "success": [
                            {
                                "relationship": "sua_doi",
                                "target_doc_id": 113297,
                                "target_key": "diem_a_khoan_5_dieu_22",
                            }
                        ],
                    }
                ]
            },
        }
        service = StatusRelationshipPreparationService(
            timestamp="now",
            logger=_FakeLogger(),
            inserted_clause_lookup={113297: {"khoan_5_dieu_22"}},
        )

        rels = service.prepare_status_relationships_from_document(doc)

        self.assertEqual(
            rels["sua_doi"][0]["target_node_props"]["ID"],
            "diem_a_khoan_5_dieu_22#113297",
        )
        bgs_edges = {
            (item["head_ID"], item["tail_ID"])
            for item in rels["bao_gom_sau_bo_sung"]
        }
        self.assertIn(("khoan_5_dieu_22#113297", "diem_a_khoan_5_dieu_22#113297"), bgs_edges)

        service_without_lookup = StatusRelationshipPreparationService(timestamp="now", logger=_FakeLogger())

        rels_without_lookup = service_without_lookup.prepare_status_relationships_from_document(doc)

        self.assertNotIn("target_node_props", rels_without_lookup["sua_doi"][0])
        self.assertNotIn("bao_gom_sau_bo_sung", rels_without_lookup)

    def test_sua_doi_creates_synthetic_target_for_existing_parent_anchor(self) -> None:
        from src.services.status_relationship_service import StatusRelationshipPreparationService

        service = StatusRelationshipPreparationService(
            timestamp="now",
            logger=_FakeLogger(),
            existing_clause_lookup={97141: {"dieu_4"}},
        )

        rels = service.prepare_status_relationships_from_document(
            {
                "cls_ID": 168398,
                "cls_info": {"loai_van_ban": "Nghi dinh"},
                "cls_graph": {
                    "success": [
                        {
                            "source_key": "dieu_2",
                            "source_type": "dieu",
                            "success": [
                                {
                                    "relationship": "sua_doi",
                                    "target_doc_id": 97141,
                                    "target_key": "diem_a_khoan_6_dieu_4",
                                }
                            ],
                        }
                    ]
                },
            }
        )

        self.assertEqual(
            rels["sua_doi"][0]["target_node_props"]["ID"],
            "diem_a_khoan_6_dieu_4#97141",
        )
        bgs_edges = {
            (item["head_ID"], item["tail_ID"])
            for item in rels["bao_gom_sau_bo_sung"]
        }
        self.assertIn(("dieu_4#97141", "khoan_6_dieu_4#97141"), bgs_edges)
        self.assertIn(("khoan_6_dieu_4#97141", "diem_a_khoan_6_dieu_4#97141"), bgs_edges)

    def test_bo_sung_synthetic_child_propagation_uses_bounded_descendant_batches(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.app.build_graph_app")

        class FakeCounters:
            relationships_created = 2

        class FakeSummary:
            counters = FakeCounters()

        class FakeResult:
            def __init__(self, records=None):
                self.records = records or []

            def __iter__(self):
                return iter(self.records)

            def consume(self):
                return FakeSummary()

        class FakeTx:
            def __init__(self, session):
                self.session = session

            def run(self, query, **params):
                self.session.queries.append(query)
                self.session.params.append(params)
                if "RETURN DISTINCT" in query:
                    return FakeResult(
                        [
                            {
                                "creator_id": "khoan_1_dieu_1#168398",
                                "creator_label": "DIEU_KHOAN",
                                "parent_id": "dieu_18b#113297",
                            }
                        ]
                    )
                return FakeResult()

        class FakeSession:
            def __init__(self):
                self.queries: List[str] = []
                self.params: List[dict[str, Any]] = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute_read(self, work):
                return work(FakeTx(self))

            def execute_write(self, work, *args):
                return work(FakeTx(self), *args)

        class FakeDriver:
            def __init__(self):
                self.session_obj = FakeSession()

            def session(self, database=None):
                return self.session_obj

        class FakeRepository:
            def __init__(self):
                self.database = "neo4jtest"
                self.driver = FakeDriver()

        repo = FakeRepository()

        created = module._propagate_bo_sung_to_synthetic_children(
            neo4j_repository=repo,
            timestamp="now",
            logger=_FakeLogger(),
        )

        combined_queries = "\n".join(repo.driver.session_obj.queries)
        self.assertEqual(created, 2)
        self.assertIn("bao_gom_sau_bo_sung*1..3", combined_queries)
        self.assertNotIn("ENDS WITH", combined_queries)
        self.assertNotIn("MATCH (child:DIEU_KHOAN)", combined_queries)

    def test_enrich_skeleton_nodes_passes_source_document_scope_to_repository(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.services.neo4j_preparation")
        LegalKnowledgeGraphBuilder = module.LegalKnowledgeGraphBuilder

        class FakeNeo4jRepository:
            def __init__(self):
                self.calls = []

            def get_skeleton_node_ids(self, label, source_doc_ids=None):
                self.calls.append((label, source_doc_ids))
                return []

        builder = object.__new__(LegalKnowledgeGraphBuilder)
        builder.neo4j_repository = FakeNeo4jRepository()
        builder.logger = _FakeLogger()

        builder.enrich_skeleton_nodes(batch_size=100, source_doc_ids=[168398])

        self.assertEqual(
            builder.neo4j_repository.calls,
            [("VAN_BAN", [168398]), ("DIEU_KHOAN", [168398])],
        )

    def test_inferred_relation_payload_uses_indirect_edge_whitelist(self) -> None:
        from src.services.inferred_relationship_service import InferredRelationshipService

        service = InferredRelationshipService(timestamp="now", logger=_FakeLogger())
        rels = service.prepare_inferred_relationships_from_document(
            {
                "cls_ID": 10,
                "cls_graph": {
                    "inferred_relations": [
                        {
                            "relation": "sua_doi_bo_sung",
                            "collection": [
                                {
                                    "target_doc_id": 20,
                                    "relation": "bai_bo",
                                    "description": "inferred evidence",
                                    "id_relations": {"dieu_1#10": ["dieu_2#20"]},
                                }
                            ],
                        }
                    ]
                },
            }
        )

        rel = rels["sua_doi_bo_sung"][0]

        self.assertEqual(
            set(rel) - {"head_ID", "tail_ID", "head_class", "tail_class"},
            {
                "nguon_cap_nhat",
                "loai_quan_he",
                "thoi_gian_cap_nhat",
                "mo_ta",
                "danh_sach_id_lien_quan",
                "moi_quan_he_goc",
            },
        )

    def test_tvpl_relation_payload_uses_direct_edge_whitelist(self) -> None:
        from src.services.tvpl_relationship_service import TVPLRelationshipService

        service = TVPLRelationshipService(timestamp="now", logger=_FakeLogger())
        rels, _ = service.prepare_tvpl_relationships_from_document(
            {
                "cls_ID": 10,
                "cls_info": {
                    "title": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                    "trich_yeu": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                    "so_hieu": "01/2026/TT-BTC",
                    "loai_van_ban": "Thông tư",
                },
                "cls_luoc_do": {
                    "van_ban_duoc_huong_dan": [
                        {
                            "id": 20,
                            "source": "tvpl",
                            "description": "Thông tư hướng dẫn thực hiện Luật Kiểm toán nhà nước",
                        }
                    ]
                },
            }
        )

        rel = rels[0]

        self.assertEqual(
            set(rel) - {"head_ID", "tail_ID", "head_class", "tail_class", "rel_type"},
            {"thoi_gian_cap_nhat", "nguon_cap_nhat"},
        )

    def test_tvpl_bulk_query_writes_whitelisted_props_and_conflict_guard(self) -> None:
        from src.services.tvpl_relationship_service import TVPLRelationshipService

        query = TVPLRelationshipService.get_bulk_relationship_query()

        self.assertIn("nguon_cap_nhat: rel.nguon_cap_nhat", query)
        self.assertIn("rel.rel_type = 'thay_the' AND type(existing) = 'bai_bo'", query)
        self.assertNotIn("nguon_quan_he", query)
        self.assertNotIn("bang_chung", query)
        self.assertNotIn("do_tin_cay", query)

    def test_build_graph_accepts_resolution_and_reconcile_flags(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.build_graph")
        old_argv = sys.argv
        sys.argv = [
            "build_graph.py",
            "--doc-ids-file",
            "data/sample_ids.json",
            "--graph-resolution-mode",
            "strict",
            "--reconcile-after-build",
            "--graph-audit-output",
            "reports/graph_audit.json",
        ]
        try:
            args = module.parse_arguments()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.graph_resolution_mode, "strict")
        self.assertTrue(args.reconcile_after_build)
        self.assertEqual(args.graph_audit_output, "reports/graph_audit.json")

    def test_build_graph_accepts_mongo_extraction_collection_override(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.build_graph")
        old_argv = sys.argv
        sys.argv = [
            "build_graph.py",
            "--doc-ids-file",
            "data/sample_ids.json",
            "--mongo-extraction-collection",
            "test",
        ]
        try:
            args = module.parse_arguments()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.mongo_extraction_collection, "test")

    def test_graph_audit_report_writes_reconciliation_json(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.build_graph")

        docs = [
            {
                "cls_ID": 10,
                "cls_info": {
                    "title": "Nghị định quy định chi tiết Luật Kiểm toán nhà nước",
                    "trich_yeu": "Nghị định quy định chi tiết Luật Kiểm toán nhà nước",
                    "so_hieu": "01/2026/NĐ-CP",
                    "loai_van_ban": "Nghị định",
                },
                "cls_graph": {
                    "success": [
                        {
                            "source_key": None,
                            "success": [
                                {
                                    "relationship": "huong_dan",
                                    "target_doc_id": 20,
                                    "description": "cls evidence",
                                }
                            ],
                        }
                    ]
                },
                "cls_luoc_do": {
                    "van_ban_duoc_huong_dan": [
                        {"id": 20, "source": "tvpl", "description": "duplicate"}
                    ],
                    "van_ban_duoc_quy_dinh_chi_tiet": [
                        {
                            "id": 30,
                            "source": "tvpl",
                            "description": "Nghị định này quy định chi tiết Luật Kiểm toán nhà nước",
                        }
                    ],
                },
            }
        ]

        class FakeRepository:
            def verify_node_exists(self, node_id, label="VAN_BAN"):
                return True

            def fetch_relationship_keys_for_sources(self, doc_ids):
                return {
                    ("cls_graph", 10, 20, "huong_dan"),
                    ("tvpl", 10, 30, "quy_dinh_chi_tiet"),
                }

        tmp_path = Path("scratch") / "test_graph_audit_report"
        shutil.rmtree(tmp_path, ignore_errors=True)
        tmp_path.mkdir(parents=True, exist_ok=True)
        try:
            output_path = tmp_path / "graph_audit.json"

            report = module._write_graph_audit_report(
                doc_ids=[10],
                docs=docs,
                neo4j_repository=FakeRepository(),
                resolution_mode="strict",
                output_path=str(output_path),
                logger=_FakeLogger(),
            )

            written = json.loads(output_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)
        self.assertEqual(report["expected"], 2)
        self.assertEqual(written["expected"], 2)
        self.assertEqual(written["actual"], 2)
        self.assertEqual(written["missing"], [])
        self.assertEqual(written["extra"], [])

    def test_build_graph_accepts_strict_auto_heal_write_mode(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.build_graph")
        old_argv = sys.argv
        sys.argv = [
            "build_graph.py",
            "--doc-ids-file",
            "data/sample_ids.json",
            "--graph-write-mode",
            "strict-auto-heal",
            "--graph-write-audit-output",
            "reports/graph_write_audit.json",
            "--graph-write-detail-output",
            "reports/graph_write_audit_detail.ndjson",
        ]
        try:
            args = module.parse_arguments()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.graph_write_mode, "strict-auto-heal")
        self.assertEqual(args.graph_write_audit_output, "reports/graph_write_audit.json")
        self.assertEqual(args.graph_write_detail_output, "reports/graph_write_audit_detail.ndjson")

    def test_build_graph_defaults_to_strict_auto_heal_write_mode(self) -> None:
        """Default graph writes must not create skeleton nodes for no-fulltext targets."""
        module = import_service_module_with_fake_infrastructure("src.build_graph")
        old_argv = sys.argv
        sys.argv = [
            "build_graph.py",
            "--doc-ids-file",
            "data/sample_ids.json",
        ]
        try:
            args = module.parse_arguments()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.graph_write_mode, "strict-auto-heal")

    def test_status_strict_query_does_not_merge_missing_nodes(self) -> None:
        from src.domain.queries import relationships

        query = relationships.bulk_upsert_for_status_relations_strict

        self.assertIn("MATCH (a {ID: rel.head_ID})", query)
        self.assertIn("MATCH (b {ID: rel.tail_ID})", query)
        self.assertNotIn("apoc.merge.node", query)

    def test_status_batch_does_not_double_count_total_result(self) -> None:
        module = import_service_module_with_fake_infrastructure("src.build_graph")

        class FakeStatusService:
            def prepare_status_relationships_from_document(self, doc):
                return {
                    "huong_dan": [
                        {
                            "head_ID": 10,
                            "tail_ID": 20,
                            "head_class": "VAN_BAN",
                            "tail_class": "VAN_BAN",
                        }
                    ]
                }

            def deduplicate_relationships(self, relationships_by_type):
                return relationships_by_type

        class FakeRepository:
            def bulk_create_multiple_relationships(self, relationships_by_type):
                return {"huong_dan": 1, "total": 1}

        result = module._process_status_relationship_batch(
            docs=[{"cls_ID": 10}],
            status_rel_service=FakeStatusService(),
            neo4j_repo=FakeRepository(),
            logger=_FakeLogger(),
        )

        self.assertEqual(result["relationships_created"], 1)
        self.assertEqual(result["by_type"], {"huong_dan": 1})


if __name__ == "__main__":
    unittest.main()
