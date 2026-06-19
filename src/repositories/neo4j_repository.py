"""
Neo4j repository for knowledge graph operations.

This module provides the Neo4jRepository class which encapsulates all Neo4j
graph database operations related to the legal document knowledge graph.
"""

from typing import Dict, List, Optional, Any, Tuple
from neo4j import Driver
from neo4j.exceptions import Neo4jError

from src.infrastructure.logging import get_logger
from src.domain.queries import nodes, relationships
from src.domain.model.relation_types import PRESERVED_RELATION_TYPES

# Relationship-level batch size for `CALL {} IN TRANSACTIONS` during a
# relations reset. A single document can have millions of edges, so doc-ID
# chunking alone cannot bound transaction size.
RESET_REL_TX_SIZE = 10_000

# Node-level batch size for `CALL {} IN TRANSACTIONS` during orphan node
# deletion. The DB can hold millions of VAN_BAN/DIEU_KHOAN nodes, so the
# scan + delete must be batched server-side to bound transaction size.
ORPHAN_NODE_TX_SIZE = 10_000


class Neo4jRepository:
    """
    Repository for Neo4j graph database operations.
    
    Provides clean abstraction over Neo4j operations for legal document knowledge graph,
    handling node and relationship creation, updates, and queries with proper error handling.
    """
    
    def __init__(self, driver: Driver, database: str, logger=None):
        """
        Initialize the Neo4j repository.
        
        Args:
            driver: Neo4j driver instance
            database: Database name to use
            logger: Optional logger instance (creates one if not provided)
        """
        self.driver = driver
        self.database = database
        self.logger = logger or get_logger(self.__class__.__name__)

    def _execute_with_retry(self, work, *args, **kwargs):
        """Execute a unit of work with retries for transient errors and conflicts."""
        import time
        import random
        from neo4j.exceptions import TransientError, ServiceUnavailable, SessionExpired

        max_retries = 5
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    return session.execute_write(work, *args, **kwargs)
            except (TransientError, ServiceUnavailable, SessionExpired, Exception) as e:
                # Check for IndexEntryConflictException in the error message
                error_msg = str(e)
                is_conflict = "IndexEntryConflictException" in error_msg or "Neo.ClientError.Procedure.ProcedureCallFailed" in error_msg
                
                if (attempt < max_retries - 1) and (is_conflict or isinstance(e, (TransientError, ServiceUnavailable, SessionExpired))):
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self.logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {error_msg[:100]}... Sleeping {delay:.2f}s")
                    time.sleep(delay)
                    continue
                else:
                    self.logger.error(f"Failed after {attempt + 1} attempts: {e}")
                    raise
    
    def create_constraints(self):
        """
        Create uniqueness constraints and indexes for optimal performance.
        
        This ensures data integrity and query performance by creating constraints
        on node IDs.
        """
        try:
            with self.driver.session(database=self.database) as session:
                # Create VAN_BAN constraint (separate statement)
                session.run(
                    "CREATE CONSTRAINT van_ban_id IF NOT EXISTS "
                    "FOR (v:VAN_BAN) REQUIRE v.ID IS UNIQUE"
                )
                # Create DIEU_KHOAN constraint (separate statement)
                session.run(
                    "CREATE CONSTRAINT dieu_khoan_id IF NOT EXISTS "
                    "FOR (d:DIEU_KHOAN) REQUIRE d.ID IS UNIQUE"
                )
                self.logger.info("Successfully created Neo4j constraints and indexes")
        except Neo4jError as e:
            # Constraints might already exist, log warning instead of error
            self.logger.warning(f"Constraints may already exist: {e}")
    
    def bulk_upsert_nodes(
        self, 
        doc_params: List[Dict[str, Any]], 
        term_params: List[Dict[str, Any]],
        re_update: bool = False
    ) -> Tuple[int, int]:
        """Bulk upsert VAN_BAN and DIEU_KHOAN nodes using automatic retries."""
        def _upsert_tx(tx):
            docs_count = 0
            terms_count = 0
            if doc_params:
                query = nodes.bulk_update_for_node_docs if re_update else nodes.bulk_upsert_for_node_docs
                tx.run(query, props_list=doc_params)
                docs_count = len(doc_params)
            if term_params:
                query = nodes.bulk_update_for_node_terms if re_update else nodes.bulk_upsert_for_node_terms
                tx.run(query, props_list=term_params)
                terms_count = len(term_params)
            return docs_count, terms_count

        return self._execute_with_retry(_upsert_tx)
    
    def bulk_create_relationships(
        self, 
        relationship_type: str,
        rel_params: List[Dict[str, Any]]
    ) -> int:
        """Bulk create relationships using automatic retries."""
        if not rel_params:
            return 0

        def _create_rel_tx(tx):
            query = relationships.bulk_upsert_relation_bao_gom if relationship_type == 'bao_gom' else self._get_relationship_query(relationship_type)
            tx.run(query, rel_list=rel_params)
            return len(rel_params)

        return self._execute_with_retry(_create_rel_tx)
    
    def bulk_create_multiple_relationships(
        self,
        relationships_dict: Dict[str, List[Dict[str, Any]]],
        strict_nodes: bool = False
    ) -> Dict[str, int]:
        """Bulk create multiple types of relationships using automatic retries."""
        if not relationships_dict:
            return {'total': 0}

        def _multiple_rel_tx(tx):
            results = {}
            total = 0
            for rel_type, rel_params in relationships_dict.items():
                if not rel_params:
                    results[rel_type] = 0
                    continue
                
                if rel_type == 'bao_gom':
                    tx.run(relationships.bulk_upsert_relation_bao_gom, rel_list=rel_params)
                else:
                    # Transform and run status relationships
                    transformed = self._transform_status_rel_params(rel_type, rel_params)
                    query = (
                        relationships.bulk_upsert_for_status_relations_strict
                        if strict_nodes
                        else relationships.bulk_upsert_for_status_relations
                    )
                    tx.run(query, rel_list=transformed)
                
                count = len(rel_params)
                results[rel_type] = count
                total += count
            results['total'] = total
            return results

        return self._execute_with_retry(_multiple_rel_tx)
    
    def delete_nodes_by_ids(
        self, 
        vanban_ids: List[int], 
        batch_size: int = 500
    ) -> Tuple[int, int]:
        """Delete nodes and their related clause nodes by IDs using retries."""
        total_vanban_deleted = 0
        total_dieu_khoan_deleted = 0
        
        def _delete_tx(tx, ids):
            # First delete DIEU_KHOAN nodes
            dk_query = """
            MATCH (v:VAN_BAN)-[:bao_gom*]->(d:DIEU_KHOAN)
            WHERE v.ID IN $ids
            DETACH DELETE d
            RETURN count(d) as deleted_count
            """
            dk_count = tx.run(dk_query, ids=ids).single()["deleted_count"]
            
            # Then delete VAN_BAN nodes
            vb_query = """
            MATCH (v:VAN_BAN)
            WHERE v.ID IN $ids
            DETACH DELETE v
            RETURN count(v) as deleted_count
            """
            vb_count = tx.run(vb_query, ids=ids).single()["deleted_count"]
            return vb_count, dk_count

        try:
            with self.driver.session(database=self.database) as session:
                for i in range(0, len(vanban_ids), batch_size):
                    batch_ids = vanban_ids[i:i + batch_size]
                    vb_deleted, dk_deleted = session.execute_write(_delete_tx, batch_ids)
                    total_vanban_deleted += vb_deleted
                    total_dieu_khoan_deleted += dk_deleted
            return total_vanban_deleted, total_dieu_khoan_deleted
        except Exception as e:
            self.logger.error(f"Failed to delete nodes: {e}")
            raise
    
    def reset_outgoing_relationships_by_ids(
        self,
        vanban_ids: List[int],
        batch_size: int = 500,
    ) -> Tuple[int, int]:
        """Delete outgoing relationships authored by in-scope VAN_BAN/DIEU_KHOAN nodes.

        Preserves `bao_gom` (the document's own containment) and
        `bao_gom_sau_bo_sung` (PRESERVED_RELATION_TYPES — see relation_types.py
        for why bgs must survive a host-scoped reset). Clause-side traversal
        follows `bao_gom` only, so synthetic bgs subtrees are never entered and
        their edges/nodes are left untouched automatically.

        Nodes and incoming edges are untouched — no DETACH, no node deletion.
        Relationship deletion is batched server-side via
        `CALL {} IN TRANSACTIONS OF RESET_REL_TX_SIZE ROWS` (auto-commit,
        idempotent, safe to retry whole) on top of the existing per-doc-ID
        chunking, since a single document can carry millions of edges.

        Returns (vanban_rel_count, dieu_khoan_rel_count).
        """
        preserved = list(PRESERVED_RELATION_TYPES)
        total_vanban_rels = 0
        total_dieu_khoan_rels = 0

        for i in range(0, len(vanban_ids), batch_size):
            batch_ids = vanban_ids[i:i + batch_size]

            vb_query = f"""
            MATCH (v:VAN_BAN)
            WHERE v.ID IN $ids
            MATCH (v)-[r]->()
            WHERE NOT type(r) IN $preserved
            WITH r
            CALL {{ WITH r DELETE r }} IN TRANSACTIONS OF {RESET_REL_TX_SIZE} ROWS
            RETURN count(r) AS deleted_count
            """
            total_vanban_rels += self._execute_autocommit_with_retry(
                vb_query, ids=batch_ids, preserved=preserved
            )

            dk_query = f"""
            MATCH (v:VAN_BAN)
            WHERE v.ID IN $ids
            MATCH (v)-[:bao_gom*]->(d:DIEU_KHOAN)
            MATCH (d)-[r]->()
            WHERE NOT type(r) IN $preserved
            WITH r
            CALL {{ WITH r DELETE r }} IN TRANSACTIONS OF {RESET_REL_TX_SIZE} ROWS
            RETURN count(r) AS deleted_count
            """
            total_dieu_khoan_rels += self._execute_autocommit_with_retry(
                dk_query, ids=batch_ids, preserved=preserved
            )

        self.logger.info(
            f"Reset outgoing relationships for {len(vanban_ids)} docs: "
            f"{total_vanban_rels} from VAN_BAN, {total_dieu_khoan_rels} from DIEU_KHOAN "
            f"(bao_gom and bao_gom_sau_bo_sung preserved)"
        )
        return total_vanban_rels, total_dieu_khoan_rels

    def delete_orphan_nodes(self, batch_size: int = ORPHAN_NODE_TX_SIZE) -> Tuple[int, int]:
        """Delete VAN_BAN/DIEU_KHOAN nodes that have no relationships at all.

        A node with `NOT (n)--()` has zero incoming and outgoing edges
        (including `bao_gom`), so it is unreachable from the rest of the
        graph and safe to delete outright (no DETACH needed).

        Matched per label and deleted server-side via
        `CALL {} IN TRANSACTIONS OF ORPHAN_NODE_TX_SIZE ROWS` (auto-commit,
        idempotent, safe to retry whole) since the DB can hold millions of
        nodes of each label.

        Returns (van_ban_deleted, dieu_khoan_deleted).
        """
        vb_query = f"""
        MATCH (v:VAN_BAN)
        WHERE NOT (v)--()
        WITH v
        CALL {{ WITH v DELETE v }} IN TRANSACTIONS OF {batch_size} ROWS
        RETURN count(v) AS deleted_count
        """
        vb_count = self._execute_autocommit_with_retry(vb_query)

        dk_query = f"""
        MATCH (d:DIEU_KHOAN)
        WHERE NOT (d)--()
        WITH d
        CALL {{ WITH d DELETE d }} IN TRANSACTIONS OF {batch_size} ROWS
        RETURN count(d) AS deleted_count
        """
        dk_count = self._execute_autocommit_with_retry(dk_query)

        self.logger.info(
            f"Deleted orphan nodes (no relationships): {vb_count} VAN_BAN, {dk_count} DIEU_KHOAN"
        )
        return vb_count, dk_count

    def _execute_autocommit_with_retry(self, query: str, **parameters) -> int:
        """Run an auto-commit query and retry the whole thing on transient errors.

        `CALL {} IN TRANSACTIONS` cannot run inside an explicit transaction
        (execute_write requires one), so it needs a plain auto-commit
        session.run. Retrying the whole query is safe here because
        relationship deletion is idempotent.
        """
        import time
        import random
        try:
            from neo4j.exceptions import TransientError, ServiceUnavailable, SessionExpired
        except ImportError:
            TransientError = ServiceUnavailable = SessionExpired = Neo4jError

        max_retries = 5
        base_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                with self.driver.session(database=self.database) as session:
                    result = session.run(query, **parameters)
                    return result.single()["deleted_count"]
            except (TransientError, ServiceUnavailable, SessionExpired, Exception) as e:
                error_msg = str(e)
                is_conflict = "IndexEntryConflictException" in error_msg or "Neo.ClientError.Procedure.ProcedureCallFailed" in error_msg

                if (attempt < max_retries - 1) and (is_conflict or isinstance(e, (TransientError, ServiceUnavailable, SessionExpired))):
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    self.logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {error_msg[:100]}... Sleeping {delay:.2f}s")
                    time.sleep(delay)
                    continue
                else:
                    self.logger.error(f"Failed after {attempt + 1} attempts: {e}")
                    raise

    def delete_all_nodes(self) -> int:
        """Delete ALL nodes and relationships using retries."""
        def _delete_all_tx(tx):
            query = "MATCH (n) DETACH DELETE n RETURN count(n) as count"
            return tx.run(query).single()["count"]
        
        try:
            with self.driver.session(database=self.database) as session:
                count = session.execute_write(_delete_all_tx)
                self.logger.warning(f"Deleted ALL {count} nodes from database")
                return count
        except Exception as e:
            self.logger.error(f"Failed to delete all nodes: {e}")
            raise
    
    def count_nodes(self, label: Optional[str] = None) -> int:
        """
        Count nodes in the database.
        
        Args:
            label: Optional node label to filter by (e.g., 'VAN_BAN', 'DIEU_KHOAN')
            
        Returns:
            Number of nodes
            
        Raises:
            Neo4jError: If count operation fails
        """
        try:
            with self.driver.session(database=self.database) as session:
                if label:
                    query = f"MATCH (n:{label}) RETURN count(n) as count"
                else:
                    query = "MATCH (n) RETURN count(n) as count"
                
                result = session.run(query)
                return result.single()["count"]
                
        except Neo4jError as e:
            self.logger.error(f"Error counting nodes: {e}")
            raise
    
    def count_relationships(self, relationship_type: Optional[str] = None) -> int:
        """
        Count relationships in the database.
        
        Args:
            relationship_type: Optional relationship type to filter by (e.g., 'bao_gom')
            
        Returns:
            Number of relationships
            
        Raises:
            Neo4jError: If count operation fails
        """
        try:
            with self.driver.session(database=self.database) as session:
                if relationship_type:
                    # Parameterized WHERE avoids Neo4j UnknownRelationshipTypeWarning
                    # when the type doesn't exist yet in the database.
                    query = "MATCH ()-[r]->() WHERE type(r) = $rel_type RETURN count(r) as count"
                    result = session.run(query, rel_type=relationship_type)
                else:
                    result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
                return result.single()["count"]
                
        except Neo4jError as e:
            self.logger.error(f"Error counting relationships: {e}")
            raise
    
    def execute_query(
        self, 
        query: str, 
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a custom Cypher query.
        
        Args:
            query: Cypher query string
            parameters: Optional query parameters
            
        Returns:
            List of result records as dictionaries
            
        Raises:
            Neo4jError: If query execution fails
        """
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, parameters or {})
                return [dict(record) for record in result]
                
        except Neo4jError as e:
            self.logger.error(f"Error executing query: {e}")
            raise
    
    def verify_node_exists(self, node_id: int, label: str = "VAN_BAN") -> bool:
        """
        Verify if a node exists by ID.
        
        Args:
            node_id: Node ID to check
            label: Node label (default: 'VAN_BAN')
            
        Returns:
            True if node exists, False otherwise
        """
        try:
            query = f"MATCH (n:{label} {{ID: $node_id}}) RETURN count(n) > 0 as exists"
            with self.driver.session(database=self.database) as session:
                result = session.run(query, node_id=node_id)
                return result.single()["exists"]
        except Neo4jError as e:
            self.logger.error(f"Error verifying node existence: {e}")
            return False

    def fetch_existing_node_keys(self, node_refs: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
        """Fetch existing node references as (label, ID) tuples."""
        if not node_refs:
            return []

        query = """
        UNWIND $nodes AS node_ref
        MATCH (n {ID: node_ref.id})
        WHERE (node_ref.label = 'VAN_BAN' AND n:VAN_BAN)
           OR (node_ref.label = 'DIEU_KHOAN' AND n:DIEU_KHOAN)
        RETURN node_ref.label AS label, node_ref.id AS id
        """
        rows = self.execute_query(
            query,
            {
                "nodes": [
                    {"label": label, "id": node_id}
                    for label, node_id in set(node_refs)
                ]
            },
        )
        return [(row["label"], row["id"]) for row in rows]

    def fetch_dieu_khoan_variant_node_keys(
        self,
        node_refs: List[Tuple[str, Any]],
    ) -> Dict[Tuple[str, Any], Tuple[str, Any]]:
        """Map missing bare DIEU_KHOAN IDs to a unique existing _dk_/_bosung_ variant."""
        candidates = []
        for label, node_id in set(node_refs):
            node_id_str = str(node_id)
            if label != "DIEU_KHOAN" or "#" not in node_id_str:
                continue

            prefix, suffix = node_id_str.rsplit("#", 1)
            if not prefix or not suffix or "_dk_" in prefix or "_bosung_" in prefix:
                continue

            candidates.append({
                "id": node_id,
                "prefix": prefix,
                "suffix": suffix,
            })

        if not candidates:
            return {}

        query = """
        UNWIND $nodes AS node_ref
        MATCH (n:DIEU_KHOAN)
        WHERE (
                n.ID STARTS WITH (node_ref.prefix + '_dk_')
             OR n.ID STARTS WITH (node_ref.prefix + '_bosung_')
        )
          AND n.ID ENDS WITH ('#' + node_ref.suffix)
        WITH node_ref, collect(n.ID) AS matches
        WHERE size(matches) = 1
        RETURN node_ref.id AS id, matches[0] AS variant_id
        """
        rows = self.execute_query(query, {"nodes": candidates})
        return {
            ("DIEU_KHOAN", row["id"]): ("DIEU_KHOAN", row["variant_id"])
            for row in rows
        }

    def fetch_node_properties(
        self,
        node_refs: List[Tuple[str, Any]],
        property_names: List[str],
    ) -> Dict[Tuple[str, Any], Dict[str, Any]]:
        """Fetch selected node properties keyed by (label, ID)."""
        if not node_refs:
            return {}

        query = """
        UNWIND $nodes AS node_ref
        MATCH (n {ID: node_ref.id})
        WHERE (node_ref.label = 'VAN_BAN' AND n:VAN_BAN)
           OR (node_ref.label = 'DIEU_KHOAN' AND n:DIEU_KHOAN)
        RETURN node_ref.label AS label, node_ref.id AS id, properties(n) AS props
        """
        rows = self.execute_query(
            query,
            {
                "nodes": [
                    {"label": label, "id": node_id}
                    for label, node_id in set(node_refs)
                ]
            },
        )
        return {
            (row["label"], row["id"]): {
                name: (row.get("props") or {}).get(name)
                for name in property_names
            }
            for row in rows
        }

    def fetch_relationship_keys_for_sources(self, doc_ids: List[int]) -> List[Tuple[str, int, int, str]]:
        """Fetch normalized relationship keys for reconciliation/audit."""
        query = """
        MATCH (a)-[r]->(b)
        WHERE r.nguon_cap_nhat IS NOT NULL
          AND type(r) <> 'bao_gom'
          AND type(r) <> 'bao_gom_sau_bo_sung'
        WITH
            a,
            b,
            r,
            split(toString(a.ID), '#') AS source_parts,
            split(toString(b.ID), '#') AS target_parts
        WITH
            CASE
                WHEN a:DIEU_KHOAN AND size(source_parts) > 1 THEN toInteger(source_parts[-1])
                ELSE toInteger(toString(a.ID))
            END AS source_doc_id,
            CASE
                WHEN b:DIEU_KHOAN AND size(target_parts) > 1 THEN toInteger(target_parts[-1])
                ELSE toInteger(toString(b.ID))
            END AS target_doc_id,
            r
        WHERE source_doc_id IN $doc_ids
        RETURN CASE
                   WHEN r.nguon_cap_nhat = 'cmcai' THEN 'cls_graph'
                   WHEN r.nguon_cap_nhat = 'tvpl' THEN 'tvpl'
                   ELSE toString(r.nguon_cap_nhat)
               END AS source,
               source_doc_id AS source_doc_id,
               target_doc_id AS target_doc_id,
               type(r) AS relation_type
        """
        rows = self.execute_query(query, {"doc_ids": doc_ids})
        return [
            (
                row["source"],
                row["source_doc_id"],
                row["target_doc_id"],
                row["relation_type"],
            )
            for row in rows
        ]

    def fetch_relationship_endpoint_keys_for_sources(self, doc_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch relationship keys with exact Neo4j endpoint IDs for strict reconciliation."""
        query = """
        MATCH (a)-[r]->(b)
        WHERE r.nguon_cap_nhat IS NOT NULL
          AND type(r) <> 'bao_gom'
          AND type(r) <> 'bao_gom_sau_bo_sung'
        WITH
            a,
            b,
            r,
            split(toString(a.ID), '#') AS source_parts,
            split(toString(b.ID), '#') AS target_parts
        WITH
            CASE
                WHEN a:DIEU_KHOAN AND size(source_parts) > 1 THEN toInteger(source_parts[-1])
                ELSE toInteger(toString(a.ID))
            END AS source_doc_id,
            CASE
                WHEN b:DIEU_KHOAN AND size(target_parts) > 1 THEN toInteger(target_parts[-1])
                ELSE toInteger(toString(b.ID))
            END AS target_doc_id,
            a,
            b,
            r
        WHERE source_doc_id IN $doc_ids
        RETURN CASE
                   WHEN r.nguon_cap_nhat = 'cmcai' THEN 'cls_graph'
                   WHEN r.nguon_cap_nhat = 'tvpl' THEN 'tvpl'
                   ELSE toString(r.nguon_cap_nhat)
               END AS source,
               source_doc_id AS source_doc_id,
               toString(a.ID) AS source_node_id,
               target_doc_id AS target_doc_id,
               toString(b.ID) AS target_node_id,
               type(r) AS relation_type
        """
        rows = self.execute_query(query, {"doc_ids": doc_ids})
        return [
            {
                "source": row["source"],
                "source_doc_id": row["source_doc_id"],
                "source_node_id": row["source_node_id"],
                "target_doc_id": row["target_doc_id"],
                "target_node_id": row["target_node_id"],
                "relation_type": row["relation_type"],
            }
            for row in rows
        ]
    
    def _get_relationship_query(self, relationship_type: str) -> str:
        """Get the base relationship creation query (atomic)."""
        return f"""
        UNWIND $rel_list AS rel
        MATCH (a {{ID: rel.head_ID}})
        WHERE a:VAN_BAN OR a:DIEU_KHOAN
        MATCH (b {{ID: rel.tail_ID}})
        WHERE b:VAN_BAN OR b:DIEU_KHOAN
        MERGE (a)-[r:{relationship_type}]->(b)
        SET r += coalesce(rel.properties, {{}})
        """
    
    def _transform_status_rel_params(
        self,
        rel_type: str,
        rel_params: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Transform parameters for bulk_upsert_for_status_relations query."""
        import json
        direct_props = {"nguon_cap_nhat", "thoi_gian_cap_nhat"}
        indirect_props = direct_props | {
            "danh_sach_id_lien_quan",
            "loai_quan_he",
            "mo_ta",
            "moi_quan_he_goc",
        }
        transformed_params = []
        for param in rel_params:
            target_node_props = param.get('target_node_props') or {}
            raw_props = {
                k: v for k, v in param.items()
                if k not in [
                    'head_ID',
                    'tail_ID',
                    'head_class',
                    'tail_class',
                    'target_node_props',
                ]
            }
            allowed_props = indirect_props if raw_props.get("loai_quan_he") == "gian_tiep" else direct_props
            rel_props = {k: v for k, v in raw_props.items() if k in allowed_props}
            
            for key, value in list(rel_props.items()):
                if isinstance(value, dict):
                    rel_props[key] = json.dumps(value, ensure_ascii=False)
            
            if 'nguon_cap_nhat' not in rel_props:
                rel_props['nguon_cap_nhat'] = 'cmcai'
            
            transformed_params.append({
                'head_ID': param['head_ID'],
                'tail_ID': param['tail_ID'],
                'head_class': param['head_class'],
                'tail_class': param['tail_class'],
                'rel_type': rel_type,
                'rel_props': rel_props,
                'target_node_props': target_node_props,
            })
        return transformed_params

    
    def get_skeleton_node_ids(
        self,
        label: str,
        source_doc_ids: Optional[List[int]] = None,
    ) -> List[Any]:
        """Identify nodes with only an ID property."""
        def _get_skel_tx(tx):
            if source_doc_ids:
                if label == "VAN_BAN":
                    query = """
                    MATCH (source:VAN_BAN)
                    WHERE source.ID IN $source_doc_ids
                    OPTIONAL MATCH (source)-[:bao_gom*0..4]->(source_clause:DIEU_KHOAN)
                    WITH collect(DISTINCT source) + collect(DISTINCT source_clause) AS source_nodes
                    UNWIND source_nodes AS source_node
                    MATCH (source_node)-[]-(candidate:VAN_BAN)
                    WHERE size(keys(candidate)) <= 1
                    RETURN DISTINCT candidate.ID AS ID
                    """
                elif label == "DIEU_KHOAN":
                    query = """
                    MATCH (source:VAN_BAN)
                    WHERE source.ID IN $source_doc_ids
                    OPTIONAL MATCH (source)-[:bao_gom*0..4]->(source_clause:DIEU_KHOAN)
                    WITH collect(DISTINCT source) + collect(DISTINCT source_clause) AS source_nodes
                    UNWIND source_nodes AS source_node
                    MATCH (source_node)-[]-(anchor)
                    WHERE anchor:DIEU_KHOAN OR anchor:VAN_BAN
                    WITH DISTINCT anchor
                    OPTIONAL MATCH (anchor)-[:bao_gom_sau_bo_sung*1..3]->(desc:DIEU_KHOAN)
                    WITH
                        [x IN collect(DISTINCT CASE WHEN anchor:DIEU_KHOAN THEN anchor END) WHERE x IS NOT NULL] +
                        [x IN collect(DISTINCT desc) WHERE x IS NOT NULL] AS candidates
                    UNWIND candidates AS candidate
                    WITH candidate
                    WHERE size(keys(candidate)) <= 1
                    RETURN DISTINCT candidate.ID AS ID
                    """
                else:
                    query = f"MATCH (n:{label}) WHERE size(keys(n)) <= 1 RETURN n.ID as ID"
                    return [record["ID"] for record in tx.run(query)]
                return [
                    record["ID"]
                    for record in tx.run(query, source_doc_ids=list(source_doc_ids))
                ]

            query = f"MATCH (n:{label}) WHERE size(keys(n)) <= 1 RETURN n.ID as ID"
            return [record["ID"] for record in tx.run(query)]

        try:
            with self.driver.session(database=self.database) as session:
                return session.execute_read(_get_skel_tx)
        except Exception as e:
            self.logger.error(f"Failed to get skeleton node IDs: {e}")
            return []

    def bulk_create_tvpl_relationships(
        self,
        rel_list: List[Dict[str, Any]],
        query: str
    ) -> int:
        """Special bulk create for TVPL relationships with retries."""
        if not rel_list:
            return 0
            
        def _tvpl_tx(tx):
            # The TVPL query contains its own apoc.periodic.iterate for reset
            # but the creation part should be atomic and retryable
            tx.run(query, rel_list=rel_list)
            return len(rel_list)
            
        return self._execute_with_retry(_tvpl_tx)
