import os
import argparse
import gzip
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from src.infrastructure.logging import get_logger
from src.services.neo4j_preparation import LegalKnowledgeGraphBuilder
from src.services.status_relationship_service import StatusRelationshipPreparationService
from src.services.inferred_relationship_service import InferredRelationshipService
from src.services.tvpl_relationship_service import TVPLRelationshipService
from src.services.neo4j_to_luoc_do_preparation import Neo4jToLuocDoPreparation
from src.repositories.neo4j_repository import Neo4jRepository
from src.shared.data.json_loader import load_doc_ids

project_root = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Parallel processing helpers
# ---------------------------------------------------------------------------

def _split_into_chunks(ids: List, n: int) -> List[List]:
    """Split a list into at most *n* roughly equal-sized chunks."""
    if not ids or n <= 1:
        return [ids]
    chunk_size = math.ceil(len(ids) / n)
    return [ids[i:i + chunk_size] for i in range(0, len(ids), chunk_size)]


def _enrich_ie_docs_with_cls_data(ie_docs: List[Dict], cls_collection) -> None:
    """Merge cls_parsing and cls_info from cls_ver2 into IE docs in-place.

    Required so that StatusRelationshipPreparationService can extract the
    quoted amendment block and source-document metadata needed to build
    skeleton DIEU_KHOAN node properties for bo_sung relationships.
    """
    if not ie_docs or cls_collection is None:
        return
    ids = [doc["cls_ID"] for doc in ie_docs if doc.get("cls_ID") is not None]
    if not ids:
        return
    cls_by_id = {
        doc["cls_ID"]: doc
        for doc in cls_collection.find(
            {"cls_ID": {"$in": ids}},
            {"cls_ID": 1, "cls_parsing": 1, "cls_info": 1},
        )
    }
    for ie_doc in ie_docs:
        cls_doc = cls_by_id.get(ie_doc.get("cls_ID"))
        if cls_doc:
            ie_doc["cls_parsing"] = cls_doc.get("cls_parsing")
            ie_doc["cls_info"] = cls_doc.get("cls_info")


def _collect_clause_target_doc_ids(ie_docs: List[Dict]) -> List[int]:
    target_doc_ids = set()
    for doc in ie_docs:
        for outer in (doc.get("cls_graph") or {}).get("success", []) or []:
            for rel_info in outer.get("success", []) or []:
                if rel_info.get("target_key") and rel_info.get("target_doc_id") is not None:
                    target_doc_ids.add(rel_info["target_doc_id"])
    return sorted(target_doc_ids)


def _load_inserted_clause_lookup(ie_collection, target_doc_ids: List[int]) -> Dict[Any, set]:
    """Find clause keys that are known to be inserted into target documents."""
    if ie_collection is None or not target_doc_ids:
        return {}

    query = {
        "cls_graph.success.success": {
            "$elemMatch": {
                "relationship": "bo_sung",
                "target_doc_id": {"$in": target_doc_ids},
                "target_key": {"$exists": True, "$ne": None},
            }
        }
    }
    lookup: Dict[Any, set] = {}
    for source_doc in ie_collection.find(query, {"cls_graph.success": 1}):
        for outer in (source_doc.get("cls_graph") or {}).get("success", []) or []:
            for rel_info in outer.get("success", []) or []:
                if rel_info.get("relationship") != "bo_sung":
                    continue
                target_doc_id = rel_info.get("target_doc_id")
                target_key = rel_info.get("target_key")
                if target_doc_id in target_doc_ids and target_key:
                    lookup.setdefault(target_doc_id, set()).add(target_key)
    return lookup


def _extract_clause_keys_from_parsing(cls_parsing: Any) -> set:
    if not cls_parsing:
        return set()
    data = []
    if isinstance(cls_parsing, list):
        data = cls_parsing
    elif isinstance(cls_parsing, dict) and cls_parsing.get("parsing"):
        try:
            data = json.loads(gzip.decompress(cls_parsing["parsing"]).decode("utf-8"))
        except Exception:
            data = []
    return {
        item.get("com_key")
        for item in data
        if item.get("com_key") and item.get("com_type") in {"dieu", "khoan", "diem"}
    }


def _load_existing_clause_lookup(cls_collection, target_doc_ids: List[int]) -> Dict[Any, set]:
    if cls_collection is None or not target_doc_ids:
        return {}

    lookup: Dict[Any, set] = {}
    cursor = cls_collection.find(
        {"cls_ID": {"$in": target_doc_ids}},
        {"cls_ID": 1, "cls_parsing": 1},
    )
    for doc in cursor:
        doc_id = doc.get("cls_ID")
        keys = _extract_clause_keys_from_parsing(doc.get("cls_parsing"))
        if doc_id is not None and keys:
            lookup[doc_id] = keys
    return lookup


def _update_inserted_clause_lookup_for_status_batch(
    status_rel_service: StatusRelationshipPreparationService,
    ie_collection,
    cls_collection,
    batch_docs: List[Dict],
) -> None:
    target_doc_ids = _collect_clause_target_doc_ids(batch_docs)
    status_rel_service.update_inserted_clause_lookup(
        _load_inserted_clause_lookup(ie_collection, target_doc_ids)
    )
    status_rel_service.update_existing_clause_lookup(
        _load_existing_clause_lookup(cls_collection, target_doc_ids)
    )


def _run_status_rels_for_chunk(
    chunk_ids: List[int],
    worker_id: int,
    ie_collection,
    neo4j_repository,
    batch_size: int,
    logger,
    graph_write_coordinator=None,
    cls_collection=None,
) -> Dict[str, Any]:
    """Worker: process status relationships for a sub-chunk of document IDs."""
    service = StatusRelationshipPreparationService(
        logger=logger,
        neo4j_repository=neo4j_repository
    )
    query = {'cls_ID': {'$in': chunk_ids}}
    cursor = ie_collection.find(query, {'cls_ID': 1, 'cls_graph': 1}).batch_size(batch_size)

    total_processed = 0
    total_created = 0
    type_counts: Dict[str, int] = {}
    batch_docs: List[Dict] = []

    for doc in cursor:
        batch_docs.append(doc)
        if len(batch_docs) >= batch_size:
            _enrich_ie_docs_with_cls_data(batch_docs, cls_collection)
            _update_inserted_clause_lookup_for_status_batch(service, ie_collection, cls_collection, batch_docs)
            result = _process_status_relationship_batch(
                batch_docs, service, neo4j_repository, logger, graph_write_coordinator
            )
            total_processed += result['processed']
            total_created += result['relationships_created']
            for k, v in result.get('by_type', {}).items():
                type_counts[k] = type_counts.get(k, 0) + v
            batch_docs = []

    if batch_docs:
        _enrich_ie_docs_with_cls_data(batch_docs, cls_collection)
        _update_inserted_clause_lookup_for_status_batch(service, ie_collection, cls_collection, batch_docs)
        result = _process_status_relationship_batch(
            batch_docs, service, neo4j_repository, logger, graph_write_coordinator
        )
        total_processed += result['processed']
        total_created += result['relationships_created']
        for k, v in result.get('by_type', {}).items():
            type_counts[k] = type_counts.get(k, 0) + v

    logger.info(
        f"[Worker {worker_id}] Status rels: "
        f"{total_processed} docs, {total_created} relationships"
    )
    return {'processed': total_processed, 'relationships_created': total_created, 'by_type': type_counts}


def _run_inferred_rels_for_chunk(
    chunk_ids: List[int],
    worker_id: int,
    ie_collection,
    neo4j_repository,
    batch_size: int,
    logger,
    graph_write_coordinator=None,
) -> Dict[str, Any]:
    """Worker: process inferred relationships for a sub-chunk of document IDs."""
    service = InferredRelationshipService(
        logger=logger,
        neo4j_repository=neo4j_repository
    )
    query = {
        '$and': [
            {'cls_ID': {'$in': chunk_ids}},
            {'cls_graph.inferred_relations': {'$exists': True, '$ne': None}}
        ]
    }
    cursor = ie_collection.find(
        query, {'cls_ID': 1, 'cls_graph.inferred_relations': 1}
    ).batch_size(batch_size)

    total_processed = 0
    total_created = 0
    type_counts: Dict[str, int] = {}
    batch_docs: List[Dict] = []

    for doc in cursor:
        batch_docs.append(doc)
        if len(batch_docs) >= batch_size:
            result = _process_inferred_relationship_batch(
                docs=batch_docs, inferred_rel_service=service,
                neo4j_repo=neo4j_repository, logger=logger,
                graph_write_coordinator=graph_write_coordinator
            )
            total_processed += result['processed']
            total_created += result['relationships_created']
            for k, v in result.get('by_type', {}).items():
                type_counts[k] = type_counts.get(k, 0) + v
            batch_docs = []

    if batch_docs:
        result = _process_inferred_relationship_batch(
            docs=batch_docs, inferred_rel_service=service,
            neo4j_repo=neo4j_repository, logger=logger,
            graph_write_coordinator=graph_write_coordinator
        )
        total_processed += result['processed']
        total_created += result['relationships_created']
        for k, v in result.get('by_type', {}).items():
            type_counts[k] = type_counts.get(k, 0) + v

    logger.info(
        f"[Worker {worker_id}] Inferred rels: "
        f"{total_processed} docs, {total_created} relationships"
    )
    return {'processed': total_processed, 'relationships_created': total_created, 'by_type': type_counts}


def _run_tvpl_rels_for_chunk(
    chunk_ids: List[int],
    worker_id: int,
    cls_collection,
    neo4j_repository,
    timestamp_value: str,
    batch_size: int,
    logger,
    graph_write_coordinator=None,
) -> Dict[str, Any]:
    """Worker: process TVPL relationships for a sub-chunk of document IDs."""
    service = TVPLRelationshipService(timestamp=timestamp_value, logger=logger)
    query = {
        '$and': [
            {'cls_ID': {'$in': chunk_ids}},
            {'cls_luoc_do': {'$exists': True, '$ne': None}}
        ]
    }
    cursor = cls_collection.find(
        query, {'cls_ID': 1, 'cls_luoc_do': 1}
    ).sort('cls_ID', 1).batch_size(batch_size)

    total_processed = 0
    total_created = 0
    all_related_ids: set = set()
    batch_docs: List[Dict] = []
    batch_rel_params: List[Dict] = []

    for doc in cursor:
        rel_params, related_ids = service.prepare_tvpl_relationships_from_document(doc)
        if rel_params:
            batch_rel_params.extend(rel_params)
            all_related_ids.update(related_ids)
            total_processed += 1
        batch_docs.append(doc)

        if len(batch_docs) >= batch_size:
            if batch_rel_params:
                try:
                    if graph_write_coordinator:
                        tvpl_created = graph_write_coordinator.write_tvpl_relationships(
                            rel_list=batch_rel_params,
                            query=service.get_bulk_relationship_query(
                                strict_nodes=graph_write_coordinator.uses_strict_writer()
                            )
                        )
                    else:
                        tvpl_created = neo4j_repository.bulk_create_tvpl_relationships(
                            rel_list=batch_rel_params,
                            query=service.get_bulk_relationship_query()
                        )
                    total_created += tvpl_created
                except Exception as e:
                    logger.error(f"[Worker {worker_id}] Error creating TVPL rels: {e}")
                    raise
            batch_docs = []
            batch_rel_params = []

    if batch_rel_params:
        try:
            if graph_write_coordinator:
                tvpl_created = graph_write_coordinator.write_tvpl_relationships(
                    rel_list=batch_rel_params,
                    query=service.get_bulk_relationship_query(
                        strict_nodes=graph_write_coordinator.uses_strict_writer()
                    )
                )
            else:
                tvpl_created = neo4j_repository.bulk_create_tvpl_relationships(
                    rel_list=batch_rel_params,
                    query=service.get_bulk_relationship_query()
                )
            total_created += tvpl_created
        except Exception as e:
            logger.error(f"[Worker {worker_id}] Error creating final TVPL rels: {e}")
            raise

    logger.info(
        f"[Worker {worker_id}] TVPL: {total_processed} docs, {total_created} relationships"
    )
    return {
        'processed': total_processed,
        'relationships_created': total_created,
        'related_ids': all_related_ids
    }


# ---------------------------------------------------------------------------

def parse_arguments(argv=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Build Legal Knowledge Graph in Neo4j',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Build complete knowledge graph (all phases except TVPL)
    python -m src.build_graph --doc-ids-file data/all_ids.json

    # Build with TVPL relationships included
    python -m src.build_graph --with-tvpl --doc-ids-file data/all_ids.json

    # Update existing nodes with new properties (e.g., after status changes)
    python -m src.build_graph --re-update --only-nodes--doc-ids-file data/updated_docs.json

    # Build only nodes (VAN_BAN and DIEU_KHOAN)
    python -m src.build_graph --only-nodes --doc-ids-file data/sample_ids.json

    # Build only BAO_GOM relationships
    python -m src.build_graph --only-bao-gom --doc-ids-file data/sample_ids.json

    # Build only status relationships
    python -m src.build_graph --only-status-rels --doc-ids-file data/sample_ids.json

    # Build only TVPL relationships
    python -m src.build_graph --only-tvpl --doc-ids-file data/sample_ids.json

    # Reset semantic relationships and rebuild (safe incremental refresh)
    python -m src.build_graph --reset-relations --doc-ids-file data/all_ids.json

    # Custom batch sizes
    python -m src.build_graph --node-batch-size 250 --structural-rel-batch-size 500

    # Skip nodes, build only relationships (including TVPL if --with-tvpl is set)
    python -m src.build_graph --skip-nodes --with-tvpl --doc-ids-file data/all_ids.json
"""
    )

    # Input options
    parser.add_argument(
        '--doc-ids-file',
        type=str,
        default='data/all_ids.json',
        help='Path to JSON file containing document IDs (default: data/all_ids.json)'
    )

    # Neo4j environment selection
    parser.add_argument(
        '--neo4j-env',
        type=str,
        choices=['DEV', 'PROD'],
        default='DEV',
        help='Neo4j environment to use: DEV or PROD (default: DEV)'
    )

    parser.add_argument(
        '--neo4j-database',
        type=str,
        default='neo4j',
        help='Neo4j database name (default: neo4j)'
    )

    # Phase control
    parser.add_argument(
        '--only-nodes',
        action='store_true',
        help='Build ONLY nodes (VAN_BAN and DIEU_KHOAN), skip relationships'
    )

    parser.add_argument(
        '--only-bao-gom',
        action='store_true',
        help='Build ONLY BAO_GOM relationships, skip nodes and status relationships'
    )

    parser.add_argument(
        '--only-status-rels',
        action='store_true',
        help='Build ONLY status relationships (sua_doi, thay_the, etc.), skip nodes and BAO_GOM'
    )

    parser.add_argument(
        '--only-inferred-rels',
        action='store_true',
        help='Build ONLY inferred relationships (thay_the_mot_phan, bai_bo_mot_phan, etc.), skip all other phases'
    )

    parser.add_argument(
        '--only-tvpl',
        action='store_true',
        help='Build ONLY TVPL relationships from cls_luoc_do, skip all other phases'
    )

    parser.add_argument(
        '--only-relationships',
        action='store_true',
        help='Build ONLY relationships (both BAO_GOM and status), skip nodes'
    )

    parser.add_argument(
        '--skip-nodes',
        action='store_true',
        help='Skip node building, build only relationships'
    )

    parser.add_argument(
        '--skip-bao-gom',
        action='store_true',
        help='Skip BAO_GOM relationship building'
    )

    parser.add_argument(
        '--skip-status-rels',
        action='store_true',
        help='Skip status relationship building'
    )

    parser.add_argument(
        '--skip-inferred-rels',
        action='store_true',
        help='Skip inferred relationship building'
    )

    parser.add_argument(
        '--skip-tvpl',
        action='store_true',
        help='Skip TVPL relationship building'
    )

    parser.add_argument(
        '--skip-enrichment',
        action='store_true',
        help='Skip node enrichment phase (PHASE 6)'
    )

    # TVPL options
    parser.add_argument(
        '--with-tvpl',
        action='store_true',
        help='Include TVPL relationships from cls_luoc_do (optional, off by default)'
    )

    parser.add_argument(
        '--mongo-extraction-collection',
        type=str,
        help='MongoDB IE collection name for graph build input (overrides IE_COLLECTION env var)'
    )

    # Graph audit/reconciliation options
    parser.add_argument(
        '--graph-resolution-mode',
        choices=['strict', 'permissive'],
        default='strict',
        help='How graph relationship targets are handled when target nodes are missing.'
    )

    parser.add_argument(
        '--reconcile-after-build',
        action='store_true',
        help='Compare expected graph relation events with relationships written to Neo4j after build.'
    )

    parser.add_argument(
        '--graph-audit-output',
        default='reports/graph_audit.json',
        help='Path for graph reconciliation/audit JSON output.'
    )

    parser.add_argument(
        '--graph-write-mode',
        choices=['legacy', 'shadow-strict', 'strict-auto-heal', 'strict-no-heal'],
        default='strict-auto-heal',
        help='Relationship write safety mode. strict-auto-heal prevents skeleton writes and builds missing nodes from Mongo before retry.'
    )

    parser.add_argument(
        '--graph-write-audit-output',
        default='reports/graph_write_audit.json',
        help='Path for graph write safety summary JSON output.'
    )

    parser.add_argument(
        '--graph-write-detail-output',
        default='reports/graph_write_audit_detail.ndjson',
        help='Path for graph write safety detail NDJSON output.'
    )

    # Batch size options
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Batch size for all operations (default: 500)'
    )

    parser.add_argument(
        '--node-batch-size',
        type=int,
        help='Batch size specifically for node creation (overrides --batch-size)'
    )

    parser.add_argument(
        '--structural-rel-batch-size',
        type=int,
        help='Batch size specifically for structural (BAO_GOM) relationship creation (overrides --batch-size)'
    )

    parser.add_argument(
        '--status-rel-batch-size',
        type=int,
        help='Batch size specifically for status relationship creation (overrides --batch-size)'
    )

    parser.add_argument(
        '--inferred-rel-batch-size',
        type=int,
        help='Batch size specifically for inferred relationship creation (overrides --batch-size)'
    )

    parser.add_argument(
        '--tvpl-batch-size',
        type=int,
        help='Batch size specifically for TVPL relationship creation (overrides --batch-size)'
    )

    # Luoc Do Export Phase Options (Phase 5 - runs last)
    parser.add_argument(
        '--with-luoc-do-export',
        action='store_true',
        help='Export Neo4j relationships back to MongoDB cls_luoc_do field (Phase 5, runs after all other phases)'
    )

    parser.add_argument(
        '--only-luoc-do-export',
        action='store_true',
        help='Only export to luoc_do, skip all building phases'
    )

    parser.add_argument(
        '--skip-luoc-do-export',
        action='store_true',
        help='Skip luoc_do export phase (default behavior)'
    )

    parser.add_argument(
        '--luoc-do-batch-size',
        type=int,
        help='Batch size specifically for luoc_do export (overrides --batch-size)'
    )

    # Processing options
    parser.add_argument(
        '--max-docs',
        type=int,
        help='Maximum number of documents to process (for testing)'
    )

    parser.add_argument(
        '--re-update',
        action='store_true',
        help='Force update existing nodes/relationships with new properties (useful for updating tinh_trang_hieu_luc, thoi_gian_cap_nhat, etc.)'
    )

    parser.add_argument(
        '--force-update',
        action='store_true',
        help='Alias for --re-update (force update existing nodes)'
    )

    parser.add_argument(
        '--reset-relations',
        action='store_true',
        help='Delete outgoing semantic relationships of in-scope nodes before building '
             '(preserves bao_gom, nodes, and incoming edges — safe for incremental runs)'
    )

    parser.add_argument(
        '--delete-orphan-nodes',
        action='store_true',
        help='After building, delete VAN_BAN/DIEU_KHOAN nodes left with no relationships at all '
             '(database-wide cleanup, not scoped to --doc-ids-file)'
    )

    parser.add_argument(
        '--orphan-node-batch-size',
        type=int,
        default=10_000,
        help='Transaction batch size for --delete-orphan-nodes (default: 10000)'
    )

    parser.add_argument(
        '--no-checkpoint',
        action='store_true',
        help='Disable checkpoint/resume capability'
    )

    # Statistics
    parser.add_argument(
        '--show-stats',
        action='store_true',
        help='Show graph statistics before and after building'
    )

    # Checkpoint management
    parser.add_argument(
        '--clear-checkpoint',
        action='store_true',
        help='Clear existing checkpoint before starting (useful when switching document sets)'
    )

    parser.add_argument(
        '--checkpoint-suffix',
        type=str,
        help='Suffix for checkpoint file name (auto-generated from input file if not specified)'
    )

    # Parallel processing options
    parser.add_argument(
        '--parallel-workers',
        type=int,
        default=8,
        help='Number of parallel workers for batch processing (default: 8)'
    )

    parser.add_argument(
        '--no-parallel',
        action='store_true',
        help='Disable parallel processing (process documents sequentially)'
    )

    return parser.parse_args(argv)


def setup_environment(logger):
    """Load environment variables."""
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Environment loaded from {env_path}")
    else:
        logger.warning(f"No .env file found at {env_path}")
        logger.warning("Ensure environment variables are set elsewhere")


def load_document_ids(file_path: str, logger) -> Optional[List[int]]:
    """Load document IDs from JSON file."""
    logger.info(f"Loading document IDs from: {file_path}")

    try:
        doc_ids = load_doc_ids(file_path)

        if not doc_ids:
            logger.warning("⚠️ No document IDs found in file")
            return None

        logger.info(f"✅ Loaded {len(doc_ids):,} document IDs")

        # Show sample IDs
        if len(doc_ids) <= 10:
            logger.info(f"   Document IDs: {doc_ids}")
        else:
            logger.info(f"   First 5: {doc_ids[:5]}")
            logger.info(f"   Last 5: {doc_ids[-5:]}")

        return doc_ids

    except FileNotFoundError:
        logger.error(f"❌ File not found: {file_path}")
        return None
    except Exception as e:
        logger.error(f"❌ Error loading document IDs: {e}")
        return None


def show_statistics(builder: LegalKnowledgeGraphBuilder, phase: str, logger):
    """Display knowledge graph statistics."""
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 KNOWLEDGE GRAPH STATISTICS - {phase}")
    logger.info(f"{'='*80}")

    try:
        stats = builder.get_statistics()

        logger.info("Nodes:")
        logger.info(f"  Total Nodes:           {stats.get('total_nodes', 0):,}")
        logger.info(f"  VAN_BAN Nodes:         {stats.get('vanban_nodes', 0):,}")
        logger.info(f"  DIEU_KHOAN Nodes:      {stats.get('dieu_khoan_nodes', 0):,}")

        logger.info("\nRelationships:")
        logger.info(f"  Total Relationships:   {stats.get('total_relationships', 0):,}")
        logger.info(f"  BAO_GOM:               {stats.get('bao_gom_relationships', 0):,}")

        # Try to get status relationship counts
        try:
            for rel_type in StatusRelationshipPreparationService.STATUS_REL_TYPES:
                count = builder.neo4j_repository.count_relationships(rel_type)
                if count > 0:
                    logger.info(f"  {rel_type:20s} {count:,}")
        except Exception as e:
            logger.debug(f"Could not get detailed relationship stats: {e}")

        logger.info(f"{'='*80}\n")

    except Exception as e:
        logger.error(f"Error getting statistics: {e}")


def _load_graph_audit_docs(builder: LegalKnowledgeGraphBuilder, doc_ids: List[int]) -> List[Dict[str, Any]]:
    """Load and merge cls_graph and TVPL data for audit input."""
    docs_by_id: Dict[int, Dict[str, Any]] = {}

    ie_collection = builder.ie_repository.collection
    for doc in ie_collection.find({'cls_ID': {'$in': doc_ids}}, {'cls_ID': 1, 'cls_graph': 1}):
        cls_id = doc.get('cls_ID')
        if cls_id is None:
            continue
        docs_by_id.setdefault(cls_id, {'cls_ID': cls_id})
        if 'cls_graph' in doc:
            docs_by_id[cls_id]['cls_graph'] = doc.get('cls_graph')

    cls_collection = builder.cls_repository.collection
    for doc in cls_collection.find({'cls_ID': {'$in': doc_ids}}, {'cls_ID': 1, 'cls_luoc_do': 1}):
        cls_id = doc.get('cls_ID')
        if cls_id is None:
            continue
        docs_by_id.setdefault(cls_id, {'cls_ID': cls_id})
        if 'cls_luoc_do' in doc:
            docs_by_id[cls_id]['cls_luoc_do'] = doc.get('cls_luoc_do')

    return list(docs_by_id.values())


def _write_graph_audit_report(
    *,
    doc_ids: List[int],
    docs: List[Dict[str, Any]],
    neo4j_repository,
    resolution_mode: str,
    output_path: str,
    logger,
) -> Dict[str, Any]:
    """Compare expected graph relation events with Neo4j and write a JSON report."""
    import json

    from src.services.graph_relation_source import GraphRelationSource
    from src.services.graph_target_resolver import GraphTargetResolver
    from src.services.graph_reconciliation_service import GraphReconciliationService

    source = GraphRelationSource()
    resolver = GraphTargetResolver(neo4j_repository, mode=resolution_mode)

    expected_events = []
    for doc in docs:
        for event in source.collect_document_events(doc):
            resolved = resolver.resolve(event)
            if resolved.target_doc_id is not None:
                expected_events.append(resolved)

    audit_doc_ids = sorted(set(doc_ids) | {event.source_doc_id for event in expected_events})
    report = GraphReconciliationService(neo4j_repository).compare(audit_doc_ids, expected_events)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"Graph audit report written to {output}")
    return report


def _create_graph_write_coordinator(builder: LegalKnowledgeGraphBuilder, args, logger):
    if args.graph_write_mode == 'legacy':
        return None

    from src.services.graph_relationship_write_coordinator import (
        GraphNodeAutoHealer,
        GraphRelationshipWriteCoordinator,
    )

    healer = None
    if args.graph_write_mode == 'strict-auto-heal':
        healer = GraphNodeAutoHealer(
            cls_collection=builder.cls_repository.collection,
            node_prep_service=builder.node_prep_service,
            neo4j_repository=builder.neo4j_repository,
            logger=logger,
        )

    return GraphRelationshipWriteCoordinator(
        neo4j_repository=builder.neo4j_repository,
        mode=args.graph_write_mode,
        node_healer=healer,
        logger=logger,
    )


def build_nodes_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    reset_relations: bool,
    re_update: bool,
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1
) -> Dict[str, Any]:
    """Execute node building phase."""
    logger.info("\n" + "="*80)
    logger.info("🔨 PHASE 1: BUILDING NODES (VAN_BAN + DIEU_KHOAN)")
    if reset_relations:
        logger.info("   Mode: RESET-RELATIONS (outgoing semantic rels deleted before build)")
    if re_update:
        logger.info("   Mode: RE-UPDATE (updating existing nodes with new properties)")
    if num_workers > 1:
        logger.info(f"   Mode: PARALLEL ({num_workers} workers, checkpoint disabled)")
    else:
        logger.info(f"   Checkpoint: build_nodes_{checkpoint_suffix}")
    logger.info("="*80)

    start_time = time.time()

    try:
        # Use a safe sub-batch size for MongoDB queries
        mongo_id_chunk_size = 5000

        if num_workers > 1:
            logger.info(f"⚡ Parallel mode: distributing across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)

            def _node_worker(chunk_ids):
                return builder.build_nodes(
                    batch_size=batch_size,
                    total_docs=None,
                    vanban_ids=chunk_ids,
                    reset_relations=reset_relations,
                    re_update=re_update,
                    use_checkpoint=False
                )

            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(_node_worker, chunk): i for i, chunk in enumerate(chunks)}
                for future in as_completed(futures):
                    worker_results.append(future.result())

            stats = {
                'processed': sum(r.get('processed', 0) for r in worker_results),
                'docs_created': sum(r.get('docs_created', 0) for r in worker_results),
                'terms_created': sum(r.get('terms_created', 0) for r in worker_results),
            }
        else:
            # --- Sequential processing with MongoDB chunking ---
            total_stats = {'processed': 0, 'docs_created': 0, 'terms_created': 0}

            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                logger.info(f"Chunk {i//mongo_id_chunk_size + 1}: Processing documents {i:,} to {min(i+mongo_id_chunk_size, len(doc_ids)):,}")

                chunk_stats = builder.build_nodes(
                    batch_size=batch_size,
                    total_docs=None,
                    vanban_ids=id_chunk,
                    reset_relations=reset_relations,
                    re_update=re_update,
                    use_checkpoint=use_checkpoint
                )

                for k in total_stats:
                    total_stats[k] += chunk_stats.get(k, 0)

            stats = total_stats

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 1 COMPLETED: NODES")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {stats.get('processed', 0):,}")
        logger.info(f"VAN_BAN Nodes Created:  {stats.get('docs_created', 0):,}")
        logger.info(f"DIEU_KHOAN Created:     {stats.get('terms_created', 0):,}")
        logger.info(f"Total Nodes Created:    {stats.get('docs_created', 0) + stats.get('terms_created', 0):,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {stats.get('processed', 0)/duration:.2f} docs/sec")
        logger.info("="*80 + "\n")

        return stats

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Node building interrupted by user (Ctrl+C)")
        logger.info("Progress saved to checkpoint. You can resume later.")
        raise
    except Exception as e:
        logger.error(f"\n❌ Node building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def _delete_bao_gom_relationships(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    logger,
    batch_size: int = 1000
) -> int:
    """
    Delete all bao_gom relationships for the given document IDs.

    Args:
        builder: The graph builder instance
        doc_ids: List of document IDs
        logger: Logger instance
        batch_size: Batch size for deletion

    Returns:
        Total number of relationships deleted
    """
    if not doc_ids:
        return 0

    total_deleted = 0

    # Process in batches to avoid OOM
    for i in range(0, len(doc_ids), batch_size):
        batch_ids = doc_ids[i:i+batch_size]

        # Delete bao_gom relationships where source VAN_BAN is in the batch
        delete_query = """
        MATCH (source:VAN_BAN)-[r:bao_gom]->(target)
        WHERE source.ID IN $doc_ids
        DELETE r
        RETURN count(r) as deleted_count
        """

        def _delete_tx(tx, ids):
            return tx.run(delete_query, doc_ids=ids).single()["deleted_count"]

        try:
            with builder.neo4j_repository.driver.session(
                database=builder.neo4j_repository.database
            ) as session:
                batch_deleted = session.execute_write(_delete_tx, batch_ids)
                total_deleted += batch_deleted

                if batch_deleted > 0:
                    logger.info(
                        f"  Batch {i//batch_size + 1}: Deleted {batch_deleted:,} bao_gom relationships "
                        f"for {len(batch_ids):,} documents"
                    )
        except Exception as e:
            logger.error(f"Error deleting bao_gom relationships for batch {i//batch_size + 1}: {e}")
            raise

    return total_deleted


def build_bao_gom_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1
) -> Dict[str, Any]:
    """Execute BAO_GOM relationship building phase."""
    logger.info("\n" + "="*80)
    logger.info("🔗 PHASE 2: BUILDING BAO_GOM RELATIONSHIPS")
    if num_workers > 1:
        logger.info(f"   Mode: PARALLEL ({num_workers} workers, checkpoint disabled)")
    else:
        logger.info(f"   Checkpoint: build_bao_gom_{checkpoint_suffix}")
    logger.info("="*80)

    start_time = time.time()

    try:
        # STEP 1: Delete existing bao_gom relationships for these documents
        # logger.info("STEP 1: Deleting existing bao_gom relationships...")
        # deleted_count = _delete_bao_gom_relationships(builder, doc_ids, logger)
        # logger.info(f"Deleted {deleted_count:,} existing relationships\n")

        # STEP 2: Build new relationships
        mongo_id_chunk_size = 5000

        if num_workers > 1:
            # --- Parallel processing ---
            logger.info(f"⚡ Splitting {len(doc_ids):,} documents across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)

            def _bao_gom_worker(chunk_ids):
                return builder.build_bao_gom_relationships(
                    batch_size=batch_size,
                    total_docs=None,
                    vanban_ids=chunk_ids,
                    use_checkpoint=False
                )

            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(_bao_gom_worker, chunk): i for i, chunk in enumerate(chunks)}
                for future in as_completed(futures):
                    worker_results.append(future.result())

            stats = {
                'processed': sum(r.get('processed', 0) for r in worker_results),
                'relationships_created': sum(r.get('relationships_created', 0) for r in worker_results),
            }
        else:
            # --- Sequential processing with MongoDB chunking ---
            total_stats = {'processed': 0, 'relationships_created': 0}

            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                logger.info(f"Chunk {i//mongo_id_chunk_size + 1}: Building bao_gom for documents {i:,} to {min(i+mongo_id_chunk_size, len(doc_ids)):,}")

                chunk_stats = builder.build_bao_gom_relationships(
                    batch_size=batch_size,
                    total_docs=None,
                    vanban_ids=id_chunk,
                    use_checkpoint=use_checkpoint
                )

                for k in total_stats:
                    total_stats[k] += chunk_stats.get(k, 0)

            stats = total_stats

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 2 COMPLETED: bao_gom RELATIONSHIPS")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {stats.get('processed', 0):,}")
        logger.info(f"Relationships Created:  {stats.get('relationships_created', 0):,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {stats.get('processed', 0)/duration:.2f} docs/sec")
        logger.info("="*80 + "\n")

        return stats

    except KeyboardInterrupt:
        logger.warning("\n⚠️ BAO_GOM building interrupted by user (Ctrl+C)")
        logger.info("Progress saved to checkpoint. You can resume later.")
        raise
    except Exception as e:
        logger.error(f"\n❌ bao_gom building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def build_nodes_and_bao_gom_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    reset_relations: bool,
    re_update: bool,
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1
) -> Dict[str, Any]:
    """Execute nodes + BAO_GOM in a single MongoDB scan (combined phase)."""
    logger.info("\n" + "="*80)
    logger.info("🔨 PHASE 1+2: BUILDING NODES + BAO_GOM (combined scan)")
    if reset_relations:
        logger.info("   Mode: RESET-RELATIONS (outgoing semantic rels deleted before build)")
    if re_update:
        logger.info("   Mode: RE-UPDATE (updating existing nodes with new properties)")
    if num_workers > 1:
        logger.info(f"   Mode: PARALLEL ({num_workers} workers, checkpoint disabled)")
    else:
        logger.info(f"   Checkpoint: build_nodes_bao_gom_{checkpoint_suffix}")
    logger.info("="*80)

    start_time = time.time()

    try:
        mongo_id_chunk_size = 5000

        if num_workers > 1:
            logger.info(f"⚡ Parallel mode: distributing across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)

            def _combined_worker(chunk_ids):
                return builder.build_nodes_and_bao_gom(
                    batch_size=batch_size,
                    vanban_ids=chunk_ids,
                    reset_relations=reset_relations,
                    re_update=re_update,
                    use_checkpoint=False
                )

            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(_combined_worker, chunk): i for i, chunk in enumerate(chunks)}
                for future in as_completed(futures):
                    worker_results.append(future.result())

            stats = {
                'processed': sum(r.get('processed', 0) for r in worker_results),
                'docs_created': sum(r.get('docs_created', 0) for r in worker_results),
                'terms_created': sum(r.get('terms_created', 0) for r in worker_results),
                'relationships_created': sum(r.get('relationships_created', 0) for r in worker_results),
            }
        else:
            total_stats = {'processed': 0, 'docs_created': 0, 'terms_created': 0, 'relationships_created': 0}

            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                logger.info(
                    f"Chunk {i//mongo_id_chunk_size + 1}: Building nodes+BAO_GOM for "
                    f"documents {i:,} to {min(i+mongo_id_chunk_size, len(doc_ids)):,}"
                )
                chunk_stats = builder.build_nodes_and_bao_gom(
                    batch_size=batch_size,
                    vanban_ids=id_chunk,
                    reset_relations=reset_relations,
                    re_update=re_update,
                    use_checkpoint=use_checkpoint
                )
                for k in total_stats:
                    total_stats[k] += chunk_stats.get(k, 0)

            stats = total_stats

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 1+2 COMPLETED: NODES + BAO_GOM")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {stats.get('processed', 0):,}")
        logger.info(f"VAN_BAN Nodes Created:  {stats.get('docs_created', 0):,}")
        logger.info(f"DIEU_KHOAN Created:     {stats.get('terms_created', 0):,}")
        logger.info(f"Total Nodes Created:    {stats.get('docs_created', 0) + stats.get('terms_created', 0):,}")
        logger.info(f"BAO_GOM Created:        {stats.get('relationships_created', 0):,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {stats.get('processed', 0)/duration:.2f} docs/sec")
        logger.info("="*80 + "\n")

        return stats

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Combined node+BAO_GOM building interrupted by user (Ctrl+C)")
        logger.info("Progress saved to checkpoint. You can resume later.")
        raise
    except Exception as e:
        logger.error(f"\n❌ Combined node+BAO_GOM building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def _propagate_bo_sung_to_synthetic_children(
    neo4j_repository,
    timestamp: str,
    logger,
    batch_size: int = 200,
) -> int:
    """Propagate bo_sung from inserted-clause creators to their synthetic sub-clauses.

    When clause A does `bo_sung` to an entire inserted clause B (e.g. `dieu_18b`),
    and later another document adds a child of B synthetically (e.g. `khoan_2_dieu_18b`
    created via bao_gom_sau_bo_sung), that child has no explicit bo_sung creator.
    This function derives the missing creator by matching on the clause-key suffix pattern.

    Safety guards:
    - Only targets DIEU_KHOAN nodes that have NO existing bo_sung creator.
    - Only targets nodes that are NOT in the original bao_gom hierarchy (synthetic nodes).
    """
    parent_query = """
    MATCH (creator)-[:bo_sung]->(parent:DIEU_KHOAN)
    WHERE creator.ID IS NOT NULL AND parent.ID IS NOT NULL
    RETURN DISTINCT
           creator.ID AS creator_id,
           CASE WHEN creator:VAN_BAN THEN 'VAN_BAN' ELSE 'DIEU_KHOAN' END AS creator_label,
           parent.ID AS parent_id
    """
    try:
        with neo4j_repository.driver.session(database=neo4j_repository.database) as session:
            def _read_parent_pairs(tx):
                return [dict(record) for record in tx.run(parent_query)]

            parent_pairs = session.execute_read(_read_parent_pairs)
            created = 0

            for creator_label in ("VAN_BAN", "DIEU_KHOAN"):
                label_pairs = [
                    pair for pair in parent_pairs
                    if pair.get("creator_label") == creator_label
                ]
                if not label_pairs:
                    continue

                batch_query = f"""
                UNWIND $pairs AS pair
                MATCH (creator:{creator_label} {{ID: pair.creator_id}})
                MATCH (parent:DIEU_KHOAN {{ID: pair.parent_id}})
                MATCH (parent)-[:bao_gom_sau_bo_sung*1..3]->(child:DIEU_KHOAN)
                WHERE NOT ()-[:bo_sung]->(child)
                  AND NOT ()-[:bao_gom]->(child)
                MERGE (creator)-[r:bo_sung]->(child)
                SET r.nguon_cap_nhat = 'cmcai',
                    r.thoi_gian_cap_nhat = $timestamp
                RETURN count(r) AS touched
                """

                def _write_batch(tx, pairs):
                    return tx.run(batch_query, pairs=pairs, timestamp=timestamp).consume()

                for pair_batch in _split_into_chunks(label_pairs, batch_size):
                    summary = session.execute_write(_write_batch, pair_batch)
                    created += summary.counters.relationships_created

            if created:
                logger.info(f"  Propagated bo_sung to {created} synthetic child clause(s)")
            return created
    except Exception as e:
        logger.error(f"Error propagating bo_sung to synthetic children: {e}")
        return 0


def build_status_relationships_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1,
    graph_write_coordinator=None
) -> Dict[str, Any]:
    """Execute status relationship building phase."""
    logger.info("\n" + "="*80)
    logger.info("🔗 PHASE 3: BUILDING STATUS RELATIONSHIPS")
    logger.info("   (sua_doi_bo_sung, thay_the, bai_bo, can_cu, dan_chieu, etc.)")
    logger.info(f"   Checkpoint: build_status_rels_{checkpoint_suffix}")
    if not use_checkpoint:
        logger.info("   Note: Checkpoint disabled")
    else:
        logger.info("   Note: Mid-phase checkpointing not yet implemented (processes in one pass)")
    logger.info("="*80)

    start_time = time.time()

    try:
        ie_collection = builder.ie_repository.collection

        # Initialize status relationship service with Neo4j repository
        status_rel_service = StatusRelationshipPreparationService(
            logger=logger,
            neo4j_repository=builder.neo4j_repository
        )

        # STEP 1: Delete existing status relationships for these documents
        # logger.info("STEP 1: Deleting existing status relationships...")
        # deleted_count = status_rel_service.delete_status_relationships_for_documents(
        #     doc_ids=doc_ids,
        #     batch_size=1000
        # )
        # logger.info(f"Deleted {deleted_count:,} existing relationships\n")

        # STEP 2: Build query
        query = {'cls_ID': {'$in': doc_ids}} if doc_ids else {}
        if max_docs:
            doc_ids = doc_ids[:max_docs] if doc_ids else None
            query = {'cls_ID': {'$in': doc_ids}}

        # Count documents
        total_docs = ie_collection.count_documents(query)
        logger.info(f"Found {total_docs:,} documents to process for status relationships")

        if total_docs == 0:
            logger.warning("⚠️ No documents found in IE collection matching the doc_ids!")
            logger.warning(f"   Query: {query}")
            logger.warning("   Make sure cls_graph data exists in MongoDB DEV (ie.ie_collection)")
            return {
                'processed': 0,
                'relationships_created': 0,
                'by_type': {},
                'duration': 0
            }

        logger.info("")

        # Process documents in batches of IDs to avoid large $in clauses in MongoDB
        total_processed = 0
        total_relationships_created = 0
        relationship_type_counts = {}

        # Use a safe sub-batch size for MongoDB queries
        mongo_id_chunk_size = 5000

        cls_collection = builder.cls_repository.collection

        if num_workers > 1:
            # --- Parallel processing ---
            logger.info(f"⚡ Parallel mode: distributing across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)
            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {
                    executor.submit(
                        _run_status_rels_for_chunk,
                        chunk, wid, ie_collection, builder.neo4j_repository, batch_size, logger,
                        graph_write_coordinator, cls_collection
                    ): wid
                    for wid, chunk in enumerate(chunks)
                }
                completed = 0
                for future in as_completed(futures):
                    result = future.result()
                    worker_results.append(result)
                    completed += 1
                    logger.info(f"Workers completed: {completed}/{len(chunks)}")

            total_processed = sum(r['processed'] for r in worker_results)
            total_relationships_created = sum(r['relationships_created'] for r in worker_results)
            for r in worker_results:
                for k, v in r.get('by_type', {}).items():
                    relationship_type_counts[k] = relationship_type_counts.get(k, 0) + v
        else:
            # --- Sequential processing with MongoDB chunking ---
            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                chunk_query = {'cls_ID': {'$in': id_chunk}}

                cursor = ie_collection.find(chunk_query, {'cls_ID': 1, 'cls_graph': 1}).batch_size(batch_size)

                batch_docs = []
                for doc in cursor:
                    batch_docs.append(doc)

                    if len(batch_docs) >= batch_size:
                        _enrich_ie_docs_with_cls_data(batch_docs, cls_collection)
                        _update_inserted_clause_lookup_for_status_batch(
                            status_rel_service,
                            ie_collection,
                            cls_collection,
                            batch_docs,
                        )
                        # Process batch
                        batch_stats = _process_status_relationship_batch(
                            batch_docs,
                            status_rel_service,
                            builder.neo4j_repository,
                            logger,
                            graph_write_coordinator
                        )

                        total_processed += batch_stats['processed']
                        total_relationships_created += batch_stats['relationships_created']

                        # Merge relationship type counts
                        for rel_type, count in batch_stats.get('by_type', {}).items():
                            relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + count

                        # Log progress
                        logger.info(
                            f"Progress: {total_processed:,}/{total_docs:,} documents "
                            f"({total_processed/total_docs*100:.1f}%) | "
                            f"{total_relationships_created:,} relationships"
                        )

                        # Clear batch
                        batch_docs = []

                # Process remaining documents in this ID chunk
                if batch_docs:
                    _enrich_ie_docs_with_cls_data(batch_docs, cls_collection)
                    _update_inserted_clause_lookup_for_status_batch(
                        status_rel_service,
                        ie_collection,
                        cls_collection,
                        batch_docs,
                    )
                    batch_stats = _process_status_relationship_batch(
                        batch_docs,
                        status_rel_service,
                        builder.neo4j_repository,
                        logger,
                        graph_write_coordinator
                    )

                    total_processed += batch_stats['processed']
                    total_relationships_created += batch_stats['relationships_created']

                    for rel_type, count in batch_stats.get('by_type', {}).items():
                        relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + count

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 3 COMPLETED: STATUS RELATIONSHIPS")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {total_processed:,}")
        logger.info(f"Total Relationships:    {total_relationships_created:,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {total_processed/duration:.2f} docs/sec")

        logger.info("\nBy Relationship Type:")
        for rel_type in sorted(relationship_type_counts.keys()):
            count = relationship_type_counts[rel_type]
            logger.info(f"  {rel_type:20s} {count:,}")

        logger.info("="*80 + "\n")

        return {
            'processed': total_processed,
            'relationships_created': total_relationships_created,
            'by_type': relationship_type_counts,
            'duration': duration
        }

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Status relationship building interrupted by user (Ctrl+C)")
        logger.info("You can resume by running the command again with --only-status-rels")
        raise
    except Exception as e:
        logger.error(f"\n❌ Status relationship building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def _process_status_relationship_batch(
    docs: List[Dict],
    status_rel_service: StatusRelationshipPreparationService,
    neo4j_repo: Neo4jRepository,
    logger,
    graph_write_coordinator=None
) -> Dict[str, Any]:
    """Process a batch of documents for status relationships."""
    # Collect all relationships by type
    all_relationships_by_type = {}
    processed = 0

    for doc in docs:
        try:
            rels_by_type = status_rel_service.prepare_status_relationships_from_document(doc)

            if rels_by_type:
                processed += 1

                # Merge into all_relationships_by_type
                for rel_type, rel_params in rels_by_type.items():
                    if rel_type not in all_relationships_by_type:
                        all_relationships_by_type[rel_type] = []
                    all_relationships_by_type[rel_type].extend(rel_params)

        except Exception as e:
            logger.warning(f"Error processing doc {doc.get('cls_ID')}: {e}")
            continue

    # Debug: Log what we collected
    if processed == 0:
        logger.warning(f"⚠️ Batch processed 0 documents with relationships out of {len(docs)}")
        logger.debug(f"   Sample doc IDs: {[d.get('cls_ID') for d in docs[:3]]}")
    else:
        logger.debug(f"✓ Batch collected relationships from {processed}/{len(docs)} documents")

    # Deduplicate across the batch to avoid redundant MERGE operations
    if all_relationships_by_type and not graph_write_coordinator:
        all_relationships_by_type = status_rel_service.deduplicate_relationships(all_relationships_by_type)

    # Create relationships in Neo4j (bulk by type)
    total_created = 0
    type_counts = {}

    if all_relationships_by_type:
        try:
            if graph_write_coordinator:
                results = graph_write_coordinator.write_grouped_relationships(all_relationships_by_type)
            else:
                results = neo4j_repo.bulk_create_multiple_relationships(all_relationships_by_type)

            total_created = results.get(
                'total',
                sum(count for rel_type, count in results.items() if rel_type != 'total')
            )
            type_counts = {rel_type: count for rel_type, count in results.items() if rel_type != 'total'}

        except Exception as e:
            logger.error(f"Error creating status relationships: {e}")
            raise

    return {
        'processed': processed,
        'relationships_created': total_created,
        'by_type': type_counts
    }


def build_inferred_relationships_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1,
    graph_write_coordinator=None
) -> Dict[str, Any]:
    """Execute inferred relationship building phase (Phase 3b)."""
    logger.info("\n" + "="*80)
    logger.info("🔗 PHASE 3b: BUILDING INFERRED RELATIONSHIPS")
    logger.info("   (thay_the_mot_phan, bai_bo_mot_phan, huy_bo_mot_phan, etc.)")
    logger.info(f"   Checkpoint: build_inferred_rels_{checkpoint_suffix}")
    if not use_checkpoint:
        logger.info("   Note: Checkpoint disabled")
    else:
        logger.info("   Note: Mid-phase checkpointing not yet implemented (processes in one pass)")
    logger.info("="*80)

    start_time = time.time()

    try:
        ie_collection = builder.ie_repository.collection

        # Initialize inferred relationship service with Neo4j repository
        inferred_rel_service = InferredRelationshipService(
            logger=logger,
            neo4j_repository=builder.neo4j_repository
        )

        # STEP 1: Delete existing inferred relationships for these documents
        # logger.info("STEP 1: Deleting existing inferred relationships...")
        # deleted_count = inferred_rel_service.delete_inferred_relationships_for_documents(
        #     doc_ids=doc_ids,
        #     batch_size=1000
        # )
        # logger.info(f"Deleted {deleted_count:,} existing relationships\n")

        # STEP 2: Build query and count documents
        query = {
            '$and': [
                {'cls_ID': {'$in': doc_ids}} if doc_ids else {},
                {'cls_graph.inferred_relations': {'$exists': True, '$ne': None}}
            ]
        }

        if max_docs:
            query['$and'].append({})

        # Count documents
        total_docs = ie_collection.count_documents(query)
        logger.info(f"Found {total_docs:,} documents with inferred_relations to process")

        if total_docs == 0:
            logger.info("\n" + "="*80)
            logger.info("✅ PHASE 3b COMPLETED: INFERRED RELATIONSHIPS")
            logger.info("="*80)
            logger.info("No documents with inferred_relations found")
            logger.info("="*80 + "\n")
            return {'processed': 0, 'relationships_created': 0, 'by_type': {}}

        logger.info("")

        # Process documents in batches of IDs to avoid large $in clauses in MongoDB
        total_processed = 0
        total_relationships_created = 0
        relationship_type_counts = {}

        # Use a safe sub-batch size for MongoDB queries
        mongo_id_chunk_size = 5000

        if num_workers > 1:
            # --- Parallel processing ---
            logger.info(f"⚡ Parallel mode: distributing across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)
            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {
                    executor.submit(
                        _run_inferred_rels_for_chunk,
                        chunk, wid, ie_collection, builder.neo4j_repository, batch_size, logger,
                        graph_write_coordinator
                    ): wid
                    for wid, chunk in enumerate(chunks)
                }
                completed = 0
                for future in as_completed(futures):
                    result = future.result()
                    worker_results.append(result)
                    completed += 1
                    logger.info(f"Workers completed: {completed}/{len(chunks)}")

            total_processed = sum(r['processed'] for r in worker_results)
            total_relationships_created = sum(r['relationships_created'] for r in worker_results)
            for r in worker_results:
                for k, v in r.get('by_type', {}).items():
                    relationship_type_counts[k] = relationship_type_counts.get(k, 0) + v
        else:
            # --- Sequential processing with MongoDB chunking ---
            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                chunk_query = {
                    '$and': [
                        {'cls_ID': {'$in': id_chunk}},
                        {'cls_graph.inferred_relations': {'$exists': True, '$ne': None}}
                    ]
                }

                cursor = ie_collection.find(
                    chunk_query,
                    {'cls_ID': 1, 'cls_graph.inferred_relations': 1}
                ).batch_size(batch_size)

                batch_docs = []
                for doc in cursor:
                    batch_docs.append(doc)

                    if len(batch_docs) >= batch_size:
                        # Process batch
                        batch_result = _process_inferred_relationship_batch(
                            docs=batch_docs,
                            inferred_rel_service=inferred_rel_service,
                            neo4j_repo=builder.neo4j_repository,
                            logger=logger,
                            graph_write_coordinator=graph_write_coordinator
                        )

                        total_processed += batch_result['processed']
                        total_relationships_created += batch_result['relationships_created']

                        # Merge type counts
                        for rel_type, count in batch_result.get('by_type', {}).items():
                            relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + count

                        logger.info(
                            f"Progress: {total_processed:,}/{total_docs:,} docs | "
                            f"{total_relationships_created:,} relationships"
                        )

                        batch_docs = []

                    if max_docs and total_processed >= max_docs:
                        break

                # Process remaining documents
                if batch_docs:
                    batch_result = _process_inferred_relationship_batch(
                        docs=batch_docs,
                        inferred_rel_service=inferred_rel_service,
                        neo4j_repo=builder.neo4j_repository,
                        logger=logger,
                        graph_write_coordinator=graph_write_coordinator
                    )

                    total_processed += batch_result['processed']
                    total_relationships_created += batch_result['relationships_created']

                    for rel_type, count in batch_result.get('by_type', {}).items():
                        relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + count

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 3b COMPLETED: INFERRED RELATIONSHIPS")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {total_processed:,}")
        logger.info(f"Total Relationships:    {total_relationships_created:,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {total_processed/duration:.2f} docs/sec")

        logger.info("\nBy Relationship Type:")
        for rel_type in sorted(relationship_type_counts.keys()):
            logger.info(f"  {rel_type:25s}: {relationship_type_counts[rel_type]:,}")

        logger.info("="*80 + "\n")

        return {
            'processed': total_processed,
            'relationships_created': total_relationships_created,
            'by_type': relationship_type_counts,
            'duration': duration
        }

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Inferred relationship building interrupted by user (Ctrl+C)")
        logger.info("You can resume by running the command again with --only-inferred-rels")
        raise
    except Exception as e:
        logger.error(f"\n❌ Inferred relationship building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def _process_inferred_relationship_batch(
    docs: List[Dict],
    inferred_rel_service: InferredRelationshipService,
    neo4j_repo,
    logger,
    graph_write_coordinator=None
) -> Dict[str, Any]:
    """Process a batch of documents for inferred relationships."""
    # Collect all relationships by type
    all_relationships_by_type = {}
    processed = 0

    for doc in docs:
        try:
            rels_by_type = inferred_rel_service.prepare_inferred_relationships_from_document(doc)

            if rels_by_type:
                processed += 1
                # Merge into all_relationships_by_type
                for rel_type, params_list in rels_by_type.items():
                    if rel_type not in all_relationships_by_type:
                        all_relationships_by_type[rel_type] = []
                    all_relationships_by_type[rel_type].extend(params_list)

        except Exception as e:
            logger.error(f"Error processing doc {doc.get('cls_ID')}: {e}")

    # Create relationships in Neo4j (bulk by type)
    total_created = 0
    type_counts = {}

    if all_relationships_by_type:
        try:
            if graph_write_coordinator:
                result = graph_write_coordinator.write_grouped_relationships(all_relationships_by_type)
            else:
                result = neo4j_repo.bulk_create_multiple_relationships(all_relationships_by_type)
            total_created = result.get('total', 0)  # Changed from 'total_created' to 'total'
            # Remove 'total' from type_counts
            type_counts = {k: v for k, v in result.items() if k != 'total'}

        except Exception as e:
            logger.error(f"Error creating relationships in Neo4j: {e}")
            raise

    return {
        'processed': processed,
        'relationships_created': total_created,
        'by_type': type_counts
    }


def build_tvpl_relationships_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    use_checkpoint: bool,
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1,
    graph_write_coordinator=None
) -> Dict[str, Any]:
    """Execute TVPL relationship building phase."""
    logger.info("\n" + "="*80)
    logger.info("🔗 PHASE 4: BUILDING TVPL RELATIONSHIPS")
    logger.info("   (Building relationships from cls_luoc_do - TVPL source)")
    logger.info(f"   Checkpoint: build_tvpl_{checkpoint_suffix}")
    if not use_checkpoint:
        logger.info("   Note: Checkpoint disabled")
    else:
        logger.info("   Note: Mid-phase checkpointing not yet implemented (processes in one pass)")
    logger.info("="*80)

    start_time = time.time()

    try:
        # Get CLS collection (cls_luoc_do is in PROD MongoDB)
        cls_collection = builder.cls_repository.collection

        # Initialize TVPL relationship service
        tvpl_service = TVPLRelationshipService(
            timestamp=builder.timestamp_value,
            logger=logger
        )

        # Build query
        query = {
            '$and': [
                {'cls_ID': {'$in': doc_ids}} if doc_ids else {},
                {'cls_luoc_do': {'$exists': True, '$ne': None}}
            ]
        }

        if max_docs:
            doc_ids = doc_ids[:max_docs] if doc_ids else None
            query = {
                '$and': [
                    {'cls_ID': {'$in': doc_ids}},
                    {'cls_luoc_do': {'$exists': True, '$ne': None}}
                ]
            }

        # Count documents
        total_docs = cls_collection.count_documents(query)
        logger.info(f"Found {total_docs:,} documents with cls_luoc_do to process")

        if total_docs == 0:
            logger.warning("⚠️ No documents found with cls_luoc_do!")
            logger.warning(f"   Query: {query}")
            logger.warning("   Make sure cls_luoc_do exists in MongoDB PROD (cls_ver2 collection)")
            return {
                'processed': 0,
                'relationships_created': 0,
                'related_ids': set(),
                'duration': 0
            }

        logger.info("")

        # Process documents in batches of IDs to avoid large $in clauses in MongoDB
        total_processed = 0
        total_relationships_created = 0
        all_related_ids = set()

        # Use a safe sub-batch size for MongoDB queries
        mongo_id_chunk_size = 5000

        if num_workers > 1:
            # --- Parallel processing ---
            logger.info(f"⚡ Parallel mode: distributing across {num_workers} workers")
            chunks = _split_into_chunks(doc_ids, num_workers)
            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {
                    executor.submit(
                        _run_tvpl_rels_for_chunk,
                        chunk, wid, cls_collection,
                        builder.neo4j_repository, builder.timestamp_value,
                        batch_size, logger, graph_write_coordinator
                    ): wid
                    for wid, chunk in enumerate(chunks)
                }
                completed = 0
                for future in as_completed(futures):
                    result = future.result()
                    worker_results.append(result)
                    completed += 1
                    logger.info(f"Workers completed: {completed}/{len(chunks)}")

            total_processed = sum(r['processed'] for r in worker_results)
            total_relationships_created = sum(r['relationships_created'] for r in worker_results)
            for r in worker_results:
                all_related_ids.update(r.get('related_ids', set()))
        else:
            # --- Sequential processing with MongoDB chunking ---
            for i in range(0, len(doc_ids), mongo_id_chunk_size):
                id_chunk = doc_ids[i:i + mongo_id_chunk_size]
                chunk_query = {
                    '$and': [
                        {'cls_ID': {'$in': id_chunk}},
                        {'cls_luoc_do': {'$exists': True, '$ne': None}}
                    ]
                }

                cursor = cls_collection.find(
                    chunk_query,
                    {'cls_ID': 1, 'cls_luoc_do': 1}
                ).sort('cls_ID', 1).batch_size(batch_size)

                batch_docs = []
                batch_rel_params = []

                for doc in cursor:
                    # Prepare relationships from this document
                    rel_params, related_ids = tvpl_service.prepare_tvpl_relationships_from_document(doc)

                    if rel_params:
                        batch_rel_params.extend(rel_params)
                        all_related_ids.update(related_ids)
                        total_processed += 1

                    batch_docs.append(doc)

                    # Process batch when it reaches batch_size
                    if len(batch_docs) >= batch_size:
                        if batch_rel_params:
                            try:
                                # Execute bulk relationship creation using retryable repository method
                                if graph_write_coordinator:
                                    tvpl_created = graph_write_coordinator.write_tvpl_relationships(
                                        rel_list=batch_rel_params,
                                        query=tvpl_service.get_bulk_relationship_query(
                                            strict_nodes=graph_write_coordinator.uses_strict_writer()
                                        )
                                    )
                                else:
                                    tvpl_created = builder.neo4j_repository.bulk_create_tvpl_relationships(
                                        rel_list=batch_rel_params,
                                        query=tvpl_service.get_bulk_relationship_query()
                                    )
                                total_relationships_created += tvpl_created

                                logger.info(
                                    f"Progress: {total_processed:,}/{total_docs:,} documents "
                                    f"({total_processed/total_docs*100:.1f}%) | "
                                    f"{total_relationships_created:,} relationships"
                                )

                            except Exception as e:
                                logger.error(f"Error creating TVPL relationships for batch: {e}")
                                raise

                        # Clear batch
                        batch_docs = []
                        batch_rel_params = []

                        # Clean up memory
                        import gc
                        gc.collect()

                # Process remaining documents in this ID chunk
                if batch_rel_params:
                    try:
                        if graph_write_coordinator:
                            tvpl_created = graph_write_coordinator.write_tvpl_relationships(
                                rel_list=batch_rel_params,
                                query=tvpl_service.get_bulk_relationship_query(
                                    strict_nodes=graph_write_coordinator.uses_strict_writer()
                                )
                            )
                        else:
                            tvpl_created = builder.neo4j_repository.bulk_create_tvpl_relationships(
                                rel_list=batch_rel_params,
                                query=tvpl_service.get_bulk_relationship_query()
                            )
                        total_relationships_created += tvpl_created

                        logger.info(
                            f"Progress: {total_processed:,}/{total_docs:,} documents "
                            f"({total_processed/total_docs*100:.1f}%) | "
                            f"{total_relationships_created:,} relationships"
                        )

                    except Exception as e:
                        logger.error(f"Error creating TVPL relationships for final batch: {e}")
                        raise

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 4 COMPLETED: TVPL RELATIONSHIPS")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {total_processed:,}")
        logger.info(f"Total Relationships:    {total_relationships_created:,}")
        logger.info(f"Related Doc IDs Found:  {len(all_related_ids):,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {total_processed/duration:.2f} docs/sec")
        logger.info("="*80 + "\n")

        return {
            'processed': total_processed,
            'relationships_created': total_relationships_created,
            'related_ids': all_related_ids,
            'duration': duration
        }

    except KeyboardInterrupt:
        logger.warning("\n⚠️ TVPL relationship building interrupted by user (Ctrl+C)")
        logger.info("You can resume by running the command again with --only-tvpl or --with-tvpl")
        raise
    except Exception as e:
        logger.error(f"\n❌ TVPL relationship building failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def build_luoc_do_export_phase(
    builder: LegalKnowledgeGraphBuilder,
    doc_ids: List[int],
    batch_size: int,
    max_docs: Optional[int],
    checkpoint_suffix: str,
    logger,
    num_workers: int = 1
) -> Dict[str, Any]:
    """Execute Phase 5: Export Neo4j relationships back to MongoDB cls_luoc_do.

    This phase reads all relationships from Neo4j for each document and converts them
    back to the cls_luoc_do format in MongoDB. This allows other services to consume
    the relationship data without directly querying Neo4j.

    This phase runs LAST, after all relationship building phases (algorithm + TVPL),
    so it captures the complete final state of relationships.
    """
    logger.info("\n" + "="*80)
    logger.info("📤 PHASE 5: EXPORTING NEO4J TO LUOC_DO")
    logger.info("   (Converting Neo4j relationships back to MongoDB cls_luoc_do format)")
    logger.info(f"   Checkpoint: luoc_do_export_{checkpoint_suffix}")
    logger.info("="*80)

    start_time = time.time()

    try:
        # Initialize Neo4j to Luoc Do service
        luoc_do_service = Neo4jToLuocDoPreparation(
            neo4j_repository=builder.neo4j_repository,
            cls_repository=builder.cls_repository,
            ie_repository=builder.ie_repository,
            logger=logger
        )

        # Process document IDs (limit if max_docs specified)
        processing_doc_ids = doc_ids[:max_docs] if max_docs else doc_ids

        logger.info(f"Will process {len(processing_doc_ids):,} documents")
        if num_workers > 1:
            logger.info(f"⚡ Parallel mode: {num_workers} workers")
        logger.info(f"Batch size: {batch_size}\n")

        # Execute the export
        total_processed = 0
        total_updated = 0

        if num_workers > 1:
            # --- Parallel processing ---
            chunks = _split_into_chunks(processing_doc_ids, num_workers)

            def _luoc_do_worker(chunk_ids):
                svc = Neo4jToLuocDoPreparation(
                    neo4j_repository=builder.neo4j_repository,
                    cls_repository=builder.cls_repository,
                    ie_repository=builder.ie_repository,
                    logger=logger
                )
                return svc.update_luoc_do(doc_ids=chunk_ids, source='neo4j_export')

            worker_results = []
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(_luoc_do_worker, chunk): i for i, chunk in enumerate(chunks)}
                completed = 0
                for future in as_completed(futures):
                    result = future.result()
                    worker_results.append(result)
                    completed += 1
                    logger.info(f"Workers completed: {completed}/{len(chunks)}")

            total_processed = len(processing_doc_ids)
            total_updated = sum(r.get('updated', 0) for r in worker_results)
        else:
            # --- Sequential processing ---
            for i in range(0, len(processing_doc_ids), batch_size):
                batch_ids = processing_doc_ids[i:i+batch_size]

                try:
                    # Update luoc_do for this batch
                    result = luoc_do_service.update_luoc_do(
                        doc_ids=batch_ids,
                        source='neo4j_export'
                    )

                    total_processed += len(batch_ids)
                    total_updated += result.get('updated', 0)

                    progress_pct = (total_processed / len(processing_doc_ids)) * 100
                    logger.info(
                        f"Progress: {total_processed:,}/{len(processing_doc_ids):,} "
                        f"({progress_pct:.1f}%) | Updated: {total_updated:,}"
                    )

                except Exception as e:
                    logger.error(f"Error processing batch {i//batch_size + 1}: {e}")
                    continue

        duration = time.time() - start_time

        logger.info("\n" + "="*80)
        logger.info("✅ PHASE 5 COMPLETED: LUOC_DO EXPORT")
        logger.info("="*80)
        logger.info(f"Documents Processed:    {total_processed:,}")
        logger.info(f"Documents Updated:      {total_updated:,}")
        logger.info(f"Duration:               {timedelta(seconds=int(duration))}")
        logger.info(f"Average Speed:          {total_processed/duration:.2f} docs/sec")
        logger.info("="*80 + "\n")

        return {
            'processed': total_processed,
            'updated': total_updated,
            'duration': duration
        }

    except Exception as e:
        logger.error(f"\n❌ Luoc Do export failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


# ---------------------------------------------------------------------------
# Application orchestrator
# ---------------------------------------------------------------------------

class BuildGraphApp:
    """Orchestrates the full graph build pipeline from parsed CLI args."""

    def __init__(self, args):
        self.args = args

    def run(self) -> int:
        """Run the graph build pipeline. Returns exit code."""
        args = self.args

        # Initialize logger
        logger = get_logger('Neo4jBuilder')

        logger.info("="*80)
        logger.info("🚀 LEGAL KNOWLEDGE GRAPH BUILDER")
        logger.info("="*80)
        logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Setup environment
        setup_environment(logger)

        # Configure Neo4j environment
        os.environ['NEO4J_ENV'] = args.neo4j_env
        env_var_name = f'NEO4J_{args.neo4j_env}_DATABASE'
        os.environ[env_var_name] = args.neo4j_database
        if args.mongo_extraction_collection:
            os.environ['IE_COLLECTION'] = args.mongo_extraction_collection
        logger.info(f"🎯 Neo4j Environment: {args.neo4j_env}")
        logger.info(f"📊 Neo4j Database: {args.neo4j_database}\n")

        if args.mongo_extraction_collection:
            logger.info(f"Mongo IE Collection: {args.mongo_extraction_collection}\n")

        # Load document IDs
        doc_ids = load_document_ids(args.doc_ids_file, logger)
        if not doc_ids:
            logger.error("❌ Cannot proceed without document IDs")
            return 1

        # Generate checkpoint suffix from input file name if not provided
        if args.checkpoint_suffix:
            checkpoint_suffix = args.checkpoint_suffix
        else:
            # Extract filename without extension and use as suffix
            from pathlib import Path
            input_filename = Path(args.doc_ids_file).stem  # e.g., "chunk_1_ids" from "chunk_1_ids.json"
            checkpoint_suffix = input_filename

        logger.info(f"📌 Checkpoint suffix: {checkpoint_suffix}")

        # Determine number of parallel workers
        num_workers = 1 if args.no_parallel else args.parallel_workers
        if num_workers > 1:
            logger.info(f"⚡ Parallel processing: ENABLED ({num_workers} workers)")
        else:
            logger.info("⚙️ Parallel processing: DISABLED (sequential)")

        logger.info("")

        # Apply max_docs limit if specified
        if args.max_docs:
            original_count = len(doc_ids)
            doc_ids = doc_ids[:args.max_docs]
            logger.info(f"⚠️ Limited to first {args.max_docs:,} documents (out of {original_count:,})\n")

        # Determine batch sizes
        node_batch_size = args.node_batch_size or args.batch_size
        rel_batch_size = args.structural_rel_batch_size or args.batch_size
        status_rel_batch_size = args.status_rel_batch_size or args.batch_size
        inferred_rel_batch_size = args.inferred_rel_batch_size or args.batch_size
        tvpl_batch_size = args.tvpl_batch_size or args.batch_size
        luoc_do_batch_size = args.luoc_do_batch_size or args.batch_size

        # Determine re-update mode
        re_update = args.re_update or args.force_update
        if re_update:
            logger.info("🔄 Mode: RE-UPDATE - Will update existing nodes with new properties\n")

        # Determine which phases to run
        use_checkpoint = not args.no_checkpoint

        run_nodes = True
        run_bao_gom = True
        run_status_rels = True
        run_inferred_rels = True  # Phase 3b - inferred relationships (on by default)
        run_tvpl = args.with_tvpl  # TVPL is optional, off by default
        run_luoc_do_export = args.with_luoc_do_export  # Luoc Do Export is optional, off by default

        # Handle exclusive flags
        if args.only_nodes:
            run_bao_gom = False
            run_status_rels = False
            run_inferred_rels = False
            run_tvpl = False
            run_luoc_do_export = False
            logger.info("🎯 Mode: NODES ONLY\n")
        elif args.only_bao_gom:
            run_nodes = False
            run_status_rels = False
            run_inferred_rels = False
            run_tvpl = False
            run_luoc_do_export = False
            logger.info("🎯 Mode: BAO_GOM ONLY\n")
        elif args.only_status_rels:
            run_nodes = False
            run_bao_gom = False
            run_inferred_rels = False
            run_tvpl = False
            run_luoc_do_export = False
            logger.info("🎯 Mode: STATUS RELATIONSHIPS ONLY\n")
        elif args.only_inferred_rels:
            run_nodes = False
            run_bao_gom = False
            run_status_rels = False
            run_inferred_rels = True
            run_tvpl = False
            run_luoc_do_export = False
            logger.info("🎯 Mode: INFERRED RELATIONSHIPS ONLY\n")
        elif args.only_tvpl:
            run_nodes = False
            run_bao_gom = False
            run_status_rels = False
            run_inferred_rels = False
            run_tvpl = True
            run_luoc_do_export = False
            logger.info("🎯 Mode: TVPL RELATIONSHIPS ONLY\n")
        elif args.only_luoc_do_export:
            run_nodes = False
            run_bao_gom = False
            run_status_rels = False
            run_inferred_rels = False
            run_tvpl = False
            run_luoc_do_export = True
            logger.info("🎯 Mode: LUOC_DO EXPORT ONLY\n")
        elif args.only_relationships:
            run_nodes = False
            run_inferred_rels = False
            run_tvpl = False
            run_luoc_do_export = False
            logger.info("🎯 Mode: RELATIONSHIPS ONLY (BAO_GOM + STATUS)\n")

        # Handle skip flags
        if args.skip_nodes:
            run_nodes = False
            logger.info("⏭️ Skipping nodes\n")
        if args.skip_bao_gom:
            run_bao_gom = False
            logger.info("⏭️ Skipping BAO_GOM relationships\n")
        if args.skip_status_rels:
            run_status_rels = False
            logger.info("⏭️ Skipping status relationships\n")
        if args.skip_inferred_rels:
            run_inferred_rels = False
            logger.info("⏭️ Skipping inferred relationships\n")
        if args.skip_tvpl:
            run_tvpl = False
            logger.info("⏭️ Skipping TVPL relationships\n")
        if args.skip_luoc_do_export:
            run_luoc_do_export = False
            logger.info("⏭️ Skipping luoc_do export\n")

        run_enrichment = not args.skip_enrichment

        # Validate configuration
        if not (run_nodes or run_bao_gom or run_status_rels or run_inferred_rels or run_tvpl or run_luoc_do_export):
            logger.error("❌ No phases selected to run! Check your arguments.")
            return 1

        # Initialize builder
        builder = None
        try:
            logger.info("Initializing Knowledge Graph Builder...")
            builder = LegalKnowledgeGraphBuilder()
            logger.info("✅ Builder initialized successfully\n")
        except Exception as e:
            logger.error(f"❌ Failed to initialize builder: {e}")
            return 1

        graph_write_coordinator = _create_graph_write_coordinator(builder, args, logger)

        # Clear checkpoints if requested
        if args.clear_checkpoint:
            from src.shared.checkpoint import CheckpointManager
            checkpoint_dir = "./logs/checkpoints"

            # Define checkpoint names for each phase
            checkpoint_names = []
            if run_nodes and run_bao_gom:
                checkpoint_names.append(f"build_nodes_bao_gom_{checkpoint_suffix}")
            elif run_nodes:
                checkpoint_names.append(f"build_nodes_{checkpoint_suffix}")
            elif run_bao_gom:
                checkpoint_names.append(f"build_bao_gom_{checkpoint_suffix}")
            if run_status_rels:
                checkpoint_names.append(f"build_status_rels_{checkpoint_suffix}")
            if run_inferred_rels:
                checkpoint_names.append(f"build_inferred_rels_{checkpoint_suffix}")
            if run_tvpl:
                checkpoint_names.append(f"build_tvpl_{checkpoint_suffix}")
            if run_luoc_do_export:
                checkpoint_names.append(f"luoc_do_export_{checkpoint_suffix}")

            # Clear checkpoints
            cleared_count = 0
            for checkpoint_name in checkpoint_names:
                checkpoint_mgr = CheckpointManager(checkpoint_name, checkpoint_dir)
                if checkpoint_mgr.checkpoint_exists():
                    checkpoint_mgr.clear_checkpoint()
                    cleared_count += 1
                    logger.info(f"✅ Cleared checkpoint: {checkpoint_name}")

            if cleared_count == 0:
                logger.info("ℹ️ No checkpoints found to clear")
            else:
                logger.info(f"✅ Cleared {cleared_count} checkpoint(s)\n")

        # Show initial statistics if requested
        if args.show_stats:
            show_statistics(builder, "BEFORE BUILD", logger)

        # Record overall start time
        overall_start_time = time.time()

        try:
            # PHASE 1+2: Nodes + BAO_GOM (single MongoDB scan when both active)
            if run_nodes and run_bao_gom:
                build_nodes_and_bao_gom_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=node_batch_size,
                    max_docs=args.max_docs,
                    reset_relations=args.reset_relations,
                    re_update=re_update,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers
                )
            elif run_nodes:
                build_nodes_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=node_batch_size,
                    max_docs=args.max_docs,
                    reset_relations=args.reset_relations,
                    re_update=re_update,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers
                )
            elif run_bao_gom:
                build_bao_gom_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=rel_batch_size,
                    max_docs=args.max_docs,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers
                )

            # PHASE 3: Build Status Relationships
            if run_status_rels:
                build_status_relationships_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=status_rel_batch_size,
                    max_docs=args.max_docs,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers,
                    graph_write_coordinator=graph_write_coordinator
                )
                logger.info("🔗 PHASE 3 POST: Propagating bo_sung to synthetic child clauses...")
                _propagate_bo_sung_to_synthetic_children(
                    neo4j_repository=builder.neo4j_repository,
                    timestamp=builder.timestamp_value,
                    logger=logger,
                )

            # PHASE 3b: Build Inferred Relationships
            if run_inferred_rels:
                build_inferred_relationships_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=inferred_rel_batch_size,
                    max_docs=args.max_docs,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers,
                    graph_write_coordinator=graph_write_coordinator
                )

            # PHASE 4: Build TVPL Relationships (Optional)
            if run_tvpl:
                build_tvpl_relationships_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=tvpl_batch_size,
                    max_docs=args.max_docs,
                    use_checkpoint=use_checkpoint,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers,
                    graph_write_coordinator=graph_write_coordinator
                )

            if graph_write_coordinator:
                graph_write_coordinator.write_audit_files(
                    args.graph_write_audit_output,
                    args.graph_write_detail_output,
                )
                logger.info(f"Graph write audit written to {args.graph_write_audit_output}")

            if args.reconcile_after_build:
                audit_docs = _load_graph_audit_docs(builder, doc_ids)
                _write_graph_audit_report(
                    doc_ids=doc_ids,
                    docs=audit_docs,
                    neo4j_repository=builder.neo4j_repository,
                    resolution_mode=args.graph_resolution_mode,
                    output_path=args.graph_audit_output,
                    logger=logger,
                )

            # PHASE 7: Delete Orphan Nodes (Optional, database-wide cleanup)
            if args.delete_orphan_nodes:
                builder.delete_orphan_nodes(batch_size=args.orphan_node_batch_size)

            # PHASE 6: Enrich Skeleton Nodes
            if run_enrichment:
                builder.enrich_skeleton_nodes(
                    batch_size=args.batch_size,
                    source_doc_ids=doc_ids,
                )

            # PHASE 5: Export to Luoc Do (Optional - runs LAST)
            if run_luoc_do_export:
                build_luoc_do_export_phase(
                    builder=builder,
                    doc_ids=doc_ids,
                    batch_size=luoc_do_batch_size,
                    max_docs=args.max_docs,
                    checkpoint_suffix=checkpoint_suffix,
                    logger=logger,
                    num_workers=num_workers
                )

            # Calculate total duration
            total_duration = time.time() - overall_start_time

            # Show final statistics if requested
            if args.show_stats:
                show_statistics(builder, "AFTER BUILD", logger)

            # Final summary
            logger.info("\n" + "="*80)
            logger.info("🎉 KNOWLEDGE GRAPH BUILD COMPLETED SUCCESSFULLY")
            logger.info("="*80)
            logger.info(f"Total Duration: {timedelta(seconds=int(total_duration))}")
            logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("="*80 + "\n")

            return 0

        except KeyboardInterrupt:
            logger.warning("\n\n⚠️ Build process interrupted by user (Ctrl+C)")
            logger.info("Progress has been saved. You can resume by running the same command again.")
            return 130

        except Exception as e:
            logger.error(f"\n\n❌ Build process failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 1

        finally:
            # Clean up
            if builder is not None:
                try:
                    builder.close()
                    logger.info("✅ All connections closed")
                except Exception as e:
                    logger.error(f"Error closing connections: {e}")
