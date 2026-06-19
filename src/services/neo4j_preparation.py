"""
Neo4j Knowledge Graph Builder Service.

This module provides the LegalKnowledgeGraphBuilder class which orchestrates
the creation and maintenance of a legal knowledge graph in Neo4j.
"""

import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from tqdm import tqdm
from src.repositories.mongo_repository import MongoRepository
from src.repositories.neo4j_repository import Neo4jRepository
from src.services.node_preparation_service import NodePreparationService
from src.infrastructure.connections import ConnectionManager
from src.infrastructure.config import AppConfig
from src.infrastructure.logging import get_logger
from src.shared.checkpoint import CheckpointManager


class LegalKnowledgeGraphBuilder:
    """
    Builder service for creating and maintaining a legal knowledge graph in Neo4j.
    
    This class orchestrates the entire process of:
    - Extracting document data from MongoDB
    - Transforming data into graph nodes and relationships
    - Loading data into Neo4j with proper error handling and checkpointing
    """
    
    def __init__(
        self,
        logger_name: str = "LegalKnowledgeGraph",
        cls_collection=None,
        ie_collection=None,
        neo4j_repository=None,
    ):
        """
        Initialize the knowledge graph builder.

        Args:
            logger_name: Name for the logger instance
            cls_collection: Optional MongoDB collection for CLS data (injected; skips internal setup)
            ie_collection: Optional MongoDB collection for IE data (injected; skips internal setup)
            neo4j_repository: Optional Neo4jRepository instance (injected; skips internal setup)
        """
        self.logger = get_logger(logger_name)
        self.conn_manager = ConnectionManager()

        if cls_collection is not None and ie_collection is not None:
            self.cls_repository = MongoRepository(cls_collection, self.logger)
            self.ie_repository = MongoRepository(ie_collection, self.logger)
        else:
            self._setup_mongodb_connections()

        if neo4j_repository is not None:
            self.neo4j_repository = neo4j_repository
        else:
            self._setup_neo4j_connection()

        self.timestamp_value = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        self.node_prep_service = NodePreparationService(
            timestamp=self.timestamp_value,
            logger=self.logger
        )

        self.checkpoint_dir = "./logs/checkpoints"
        self._checkpoint_suffix = None

        self.logger.info("[NEO4J] Successfully initialized all connections and services")
    
    def _setup_mongodb_connections(self):
        """Setup MongoDB connections for CLS and IE collections."""
        # Register CLS MongoDB (PRODUCTION - contains cls_ver2 with cls_parsing)
        self.conn_manager.register_mongo_from_env('cls_mongo', 'MONGO_PROD')
        
        cfg = AppConfig()
        cls_collection = self.conn_manager.get_mongo_collection(
            'cls_mongo', cfg.cls_collection, cfg.cls_database
        )

        
        self.cls_repository = MongoRepository(cls_collection, self.logger)
        self.logger.info(f"[NEO4J] Connected to PROD MongoDB: {cfg.cls_database}.{cfg.cls_collection}")

        # Register IE MongoDB (Fallback to MONGO_PROD if MONGO_DEV is not config)
        if os.getenv('MONGO_DEV_HOST') and os.getenv('MONGO_DEV_PORT'):
             self.conn_manager.register_mongo_from_env('ie_mongo', 'MONGO_DEV')
        else:
             self.logger.info("[NEO4J] MONGO_DEV not configured, using MONGO_PROD for IE collection")
             self.conn_manager.register_mongo_from_env('ie_mongo', 'MONGO_PROD')

        ie_collection = self.conn_manager.get_mongo_collection(
            'ie_mongo', cfg.ie_collection, cfg.ie_database
        )

        self.ie_repository = MongoRepository(ie_collection, self.logger)
        self.logger.info(f"[NEO4J] Connected to IE MongoDB: {cfg.ie_database}.{cfg.ie_collection}")

        
        # Create indexes on IE collection
        try:
            ie_collection.create_index("cls_ID", unique=True)
            ie_collection.create_index(
                [("cls_graph", 1), ("cls_ID", 1)], 
                background=True
            )
        except Exception as e:
            self.logger.warning(f"Could not create indexes on IE collection: {e}")
    
    def _setup_neo4j_connection(self):
        """Setup Neo4j connection and repository."""
        # Register Neo4j connection (default to DEV)
        neo4j_env = os.getenv('NEO4J_ENV', 'DEV')  # DEV or PROD
        neo4j_prefix = f'NEO4J_{neo4j_env}'
        
        self.conn_manager.register_neo4j_from_env('neo4j_main', neo4j_prefix)
        
        driver = self.conn_manager.get_neo4j_driver('neo4j_main')
        database = os.getenv(f'{neo4j_prefix}_DATABASE', 'neo4j')
        
        self.neo4j_repository = Neo4jRepository(driver, database, self.logger)
        self.logger.info(f"[NEO4J] Connected to {neo4j_env} Neo4j: database={database}")
        
        # Create constraints
        self.neo4j_repository.create_constraints()
    
    def reset_relations_before_build(
        self,
        vanban_ids: List[int],
        batch_size: int = 500,
    ) -> None:
        """Delete outgoing semantic relationships for in-scope nodes before a fresh build.

        Calls the repository-level batched reset. Preserves bao_gom, nodes, and incoming edges.
        Must only be called with an explicit list of IDs — full-DB wipe is not supported here.
        """
        if not vanban_ids:
            return
        self.logger.info(
            f"[NEO4J][RESET] Resetting outgoing relationships for {len(vanban_ids)} docs "
            f"(bao_gom preserved)..."
        )
        vb_count, dk_count = self.neo4j_repository.reset_outgoing_relationships_by_ids(
            vanban_ids, batch_size=batch_size
        )
        self.logger.info(
            f"[NEO4J][RESET] Done — {vb_count} VAN_BAN rels, {dk_count} DIEU_KHOAN rels deleted"
        )

    def delete_orphan_nodes(self, batch_size: int = 10_000) -> None:
        """Delete VAN_BAN/DIEU_KHOAN nodes left with no relationships at all.

        Calls the repository-level batched orphan deletion. Operates on the
        whole database (not scoped to the current run's doc IDs), so it is
        opt-in and meant to run as a final cleanup pass after a build.
        """
        self.logger.info("[NEO4J][ORPHANS] Scanning for orphan nodes (no relationships)...")
        vb_count, dk_count = self.neo4j_repository.delete_orphan_nodes(batch_size=batch_size)
        self.logger.info(
            f"[NEO4J][ORPHANS] Done — deleted {vb_count} VAN_BAN, {dk_count} DIEU_KHOAN orphan node(s)"
        )

    def build_nodes(
        self,
        batch_size: int = 100,
        total_docs: Optional[int] = None,
        vanban_ids: Optional[List[int]] = None,
        reset_relations: bool = False,
        re_update: bool = False,
        use_checkpoint: bool = True
    ) -> Dict[str, Any]:
        """
        Build VAN_BAN and DIEU_KHOAN nodes in the knowledge graph.

        Args:
            batch_size: Number of documents to process per batch
            total_docs: Maximum number of documents to process (limits vanban_ids if provided)
            vanban_ids: Specific list of VAN_BAN IDs to process (None = all documents)
            reset_relations: If True, delete outgoing semantic rels before building (preserves bao_gom and nodes)
            re_update: If True, update existing nodes with new properties (MERGE instead of CREATE)
            use_checkpoint: If True, enable checkpoint-based resumption

        Returns:
            Dictionary with processing statistics
        """
        self.logger.info("[NEO4J][NODES] Starting node building process")

        # Load checkpoint if enabled
        process_name = "build_nodes"
        if self._checkpoint_suffix:
            process_name = f"{process_name}_{self._checkpoint_suffix}"
        checkpoint_manager = CheckpointManager(process_name, self.checkpoint_dir)
        last_processed_id = None
        if use_checkpoint:
            checkpoint_data = checkpoint_manager.load_checkpoint()
            last_processed_id = checkpoint_data.get('last_doc_id_processed') if checkpoint_data else None
            if last_processed_id:
                self.logger.info(f"[NEO4J][NODES] Resuming from checkpoint: last_id={last_processed_id}")

        # Prepare query and IDs to process
        query, ids_to_process = self._prepare_query_and_ids(
            vanban_ids, total_docs, last_processed_id
        )

        # Reset outgoing relationships before building (scoped, non-destructive)
        if reset_relations and last_processed_id is None and ids_to_process:
            self.reset_relations_before_build(ids_to_process, batch_size=batch_size)
            re_update = True

        # Count total documents
        total_docs_count = self._count_documents_to_process(
            query, ids_to_process, last_processed_id, total_docs
        )

        # Process documents in batches
        stats = self._process_node_batches(
            query=query,
            batch_size=batch_size,
            total_docs=total_docs_count,
            last_processed_id=last_processed_id,
            re_update=re_update,
            process_name=process_name,
            checkpoint_manager=checkpoint_manager,
            use_checkpoint=use_checkpoint
        )
        
        # Clear checkpoint after successful completion
        if use_checkpoint:
            checkpoint_manager.clear_checkpoint()
        
        self.logger.info(
            f"[NEO4J][NODES] ✅ Completed processing {stats['processed']} documents. "
            f"Created {stats['docs_created']} VAN_BAN nodes and {stats['terms_created']} DIEU_KHOAN nodes"
        )
        
        return stats
    
    def enrich_skeleton_nodes(
        self,
        batch_size: int = 500,
        source_doc_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Identify nodes that have only an ID (created as references) and enrich them
        with full metadata from MongoDB.
        
        Args:
            batch_size: Processing batch size
            source_doc_ids: Optional current-build document scope. When provided,
                only skeleton nodes connected to these documents are considered.
            
        Returns:
            Dictionary with enrichment statistics
        """
        import time
        from tqdm import tqdm
        self.logger.info("\n" + "="*80)
        self.logger.info("💎 PHASE 6: ENRICHING SKELETON NODES")
        self.logger.info("   (Fetching properties for nodes created as references)")
        self.logger.info("="*80)
        
        start_time = time.time()
        enriched_vanban = 0
        enriched_dieukhoan = 0
        
        try:
            # 1. Enrich VAN_BAN nodes
            enrich_vb_ids = self.neo4j_repository.get_skeleton_node_ids(
                "VAN_BAN",
                source_doc_ids=source_doc_ids,
            )
            if enrich_vb_ids:
                self.logger.info(f"[NEO4J][ENRICH] Found {len(enrich_vb_ids)} skeleton VAN_BAN nodes")
                for i in tqdm(range(0, len(enrich_vb_ids), batch_size), desc="Enriching VAN_BAN"):
                    batch = enrich_vb_ids[i:i+batch_size]
                    # Fetch from Mongo
                    docs = list(self.cls_repository.collection.find({"cls_ID": {"$in": batch}}))
                    if docs:
                        # Prepare and update
                        doc_params, _ = self.node_prep_service.batch_prepare_nodes(docs)
                        # Correct method call: Pass as doc_params, empty for term_params
                        self.neo4j_repository.bulk_upsert_nodes(doc_params=doc_params, term_params=[])
                        enriched_vanban += len(docs)
                    
            # 2. Enrich DIEU_KHOAN nodes
            enrich_dk_ids = self.neo4j_repository.get_skeleton_node_ids(
                "DIEU_KHOAN",
                source_doc_ids=source_doc_ids,
            )
            if enrich_dk_ids:
                self.logger.info(f"[NEO4J][ENRICH] Found {len(enrich_dk_ids)} skeleton DIEU_KHOAN nodes")
                # DIEU_KHOAN enrichment is more complex as we need to group by parent VAN_BAN ID
                parent_to_dk_map = {}
                for dk_id in enrich_dk_ids:
                    if "#" in str(dk_id):
                        try:
                            parent_id = int(str(dk_id).split("#")[1])
                            if parent_id not in parent_to_dk_map:
                                parent_to_dk_map[parent_id] = []
                            parent_to_dk_map[parent_id].append(dk_id)
                        except (ValueError, IndexError):
                            continue
                
                parent_ids = list(parent_to_dk_map.keys())
                self.logger.info(f"[NEO4J][ENRICH] Batch fetching {len(parent_ids)} parent documents for DIEU_KHOAN enrichment")
                
                # Larger batch reduces round trips; batch_size // 2 is safe for typical doc sizes.
                parent_batch_size = max(1, batch_size // 2)
                for i in tqdm(range(0, len(parent_ids), parent_batch_size), desc="Enriching DIEU_KHOAN"):
                    batch_parents = parent_ids[i:i+parent_batch_size]
                    docs = list(self.cls_repository.collection.find({"cls_ID": {"$in": batch_parents}}))

                    if docs:
                        all_term_params = []
                        for doc in docs:
                            _, term_params = self.node_prep_service.prepare_nodes_from_document(doc)
                            parent_id_val = doc.get("cls_ID")
                            skeleton_list = (
                                parent_to_dk_map.get(parent_id_val)
                                or parent_to_dk_map.get(int(parent_id_val))
                                or []
                            )

                            # Build O(1)-lookup dict once per document instead of O(n) scan
                            term_by_id: Dict[str, Any] = {str(t["ID"]): t for t in term_params}

                            filtered_terms = []
                            for sid in skeleton_list:
                                sid_str = str(sid)
                                # O(1) exact match
                                exact_match = term_by_id.get(sid_str)
                                if exact_match:
                                    filtered_terms.append(exact_match)
                                    continue

                                # Variant match (only when sid has a '#' separator)
                                if "#" in sid_str:
                                    prefix, suffix = sid_str.split("#", 1)
                                    variant_match = next(
                                        (t for id_str, t in term_by_id.items()
                                         if (id_str.startswith(f"{prefix}_dk_") or id_str.startswith(f"{prefix}_bosung_"))
                                         and id_str.endswith(f"#{suffix}")),
                                        None,
                                    )
                                    if variant_match:
                                        new_term = variant_match.copy()
                                        new_term["ID"] = sid_str
                                        filtered_terms.append(new_term)
                            
                            all_term_params.extend(filtered_terms)
                            
                        if all_term_params:
                            self.neo4j_repository.bulk_upsert_nodes(doc_params=[], term_params=all_term_params)
                            enriched_dieukhoan += len(all_term_params)
                            
            duration = time.time() - start_time
            self.logger.info(f"\n[NEO4J][ENRICH] ✅ Completed enrichment: {enriched_vanban} VAN_BAN, {enriched_dieukhoan} DIEU_KHOAN nodes")
            self.logger.info(f"[NEO4J][ENRICH] Duration: {duration:.2f}s")
            
            return {
                "enriched_vanban": enriched_vanban,
                "enriched_dieukhoan": enriched_dieukhoan,
                "duration": duration
            }
            
        except Exception as e:
            self.logger.error(f"[NEO4J][ENRICH] Error during enrichment: {e}")
            return {"error": str(e)}
    
    def build_bao_gom_relationships(
        self,
        batch_size: int = 100,
        total_docs: Optional[int] = None,
        vanban_ids: Optional[List[int]] = None,
        use_checkpoint: bool = True
    ) -> Dict[str, Any]:
        """
        Build BAO_GOM (contains) relationships in the knowledge graph.
        
        Args:
            batch_size: Number of documents to process per batch
            total_docs: Maximum number of documents to process
            vanban_ids: Specific list of VAN_BAN IDs to process
            use_checkpoint: If True, enable checkpoint-based resumption
            
        Returns:
            Dictionary with processing statistics
        """
        self.logger.info("[NEO4J][BAO_GOM] Starting BAO_GOM relationship building process")
        
        # Load checkpoint if enabled
        process_name = "build_bao_gom"
        if self._checkpoint_suffix:
            process_name = f"{process_name}_{self._checkpoint_suffix}"
        checkpoint_manager = CheckpointManager(process_name, self.checkpoint_dir)
        last_processed_id = None
        if use_checkpoint:
            checkpoint_data = checkpoint_manager.load_checkpoint()
            last_processed_id = checkpoint_data.get('last_doc_id_processed') if checkpoint_data else None
            if last_processed_id:
                self.logger.info(f"[NEO4J][BAO_GOM] Resuming from checkpoint: last_id={last_processed_id}")
        
        # Prepare query and IDs to process
        query, ids_to_process = self._prepare_query_and_ids(
            vanban_ids, total_docs, last_processed_id
        )
        
        # Count total documents
        total_docs_count = self._count_documents_to_process(
            query, ids_to_process, last_processed_id, total_docs
        )
        
        # Process relationships in batches
        stats = self._process_relationship_batches(
            query=query,
            batch_size=batch_size,
            total_docs=total_docs_count,
            last_processed_id=last_processed_id,
            process_name=process_name,
            checkpoint_manager=checkpoint_manager,
            use_checkpoint=use_checkpoint
        )
        
        # Clear checkpoint after successful completion
        if use_checkpoint:
            checkpoint_manager.clear_checkpoint()
        
        self.logger.info(
            f"[NEO4J][BAO_GOM] ✅ Completed processing {stats['processed']} documents. "
            f"Created {stats['relationships_created']} BAO_GOM relationships"
        )
        
        return stats
    
    def clear_knowledge_graph(
        self, 
        vanban_ids: Optional[List[int]] = None,
        batch_size: int = 500
    ):
        """
        Clear nodes from the knowledge graph.
        
        Args:
            vanban_ids: If provided, only delete nodes with these IDs.
                       If None, delete ALL nodes in the database.
            batch_size: Number of IDs to process per batch
        """
        if vanban_ids is not None:
            self.logger.info(
                f"[NEO4J][CLEAR] Clearing {len(vanban_ids)} VAN_BAN nodes "
                f"and their related DIEU_KHOAN nodes (batch_size={batch_size})..."
            )
            
            # Delete in batches with progress bar
            with tqdm(total=len(vanban_ids), desc="Clearing nodes", unit="IDs") as pbar:
                for i in range(0, len(vanban_ids), batch_size):
                    batch_ids = vanban_ids[i:i + batch_size]
                    vanban_deleted, dieu_khoan_deleted = self.neo4j_repository.delete_nodes_by_ids(
                        batch_ids, batch_size=len(batch_ids)
                    )
                    pbar.update(len(batch_ids))
            
            self.logger.info("[NEO4J][CLEAR] Successfully cleared specified nodes")
        else:
            self.logger.warning("[NEO4J][CLEAR] ⚠️ CLEARING ALL NODES in database!")
            total_count = self.neo4j_repository.delete_all_nodes()
            self.logger.info(f"[NEO4J][CLEAR] Deleted all {total_count} nodes")
    
    def _prepare_query_and_ids(
        self,
        vanban_ids: Optional[List[int]],
        total_docs: Optional[int],
        last_processed_id: Optional[int]
    ) -> tuple:
        """Prepare MongoDB query and list of IDs to process."""
        if vanban_ids is not None:
            # Apply total_docs limit to vanban_ids if specified
            if total_docs is not None:
                ids_to_process = vanban_ids[:total_docs]
                self.logger.info(
                    f"Using first {len(ids_to_process)} IDs (limited by total_docs={total_docs})"
                )
            else:
                ids_to_process = vanban_ids
                self.logger.info(f"Processing {len(ids_to_process)} specific IDs from list")
            
            query = {
                "$and": [
                    {"cls_ID": {"$exists": True, "$ne": None}},
                    {"cls_ID": {"$in": ids_to_process}}
                ]
            }
        else:
            ids_to_process = None
            query = {"cls_ID": {"$exists": True, "$ne": None}}
        
        return query, ids_to_process
    
    def _clear_nodes_before_build(self, ids_to_process: Optional[List[int]]):
        """Clear nodes before building."""
        if ids_to_process is not None:
            self.clear_knowledge_graph(vanban_ids=ids_to_process)
        else:
            self.clear_knowledge_graph(vanban_ids=None)
    
    def _count_documents_to_process(
        self,
        query: Dict,
        ids_to_process: Optional[List[int]],
        last_processed_id: Optional[int],
        total_docs: Optional[int]
    ) -> int:
        """Count total documents to process."""
        try:
            if ids_to_process is not None:
                total_docs_in_db = self.cls_repository.count_documents(query)
                self.logger.info(
                    f"Found {total_docs_in_db} out of {len(ids_to_process)} "
                    f"specified IDs in MongoDB"
                )
                
                # If checkpoint exists, calculate remaining documents
                if last_processed_id:
                    sorted_ids = sorted(ids_to_process)
                    remaining_ids = [id for id in sorted_ids if id > last_processed_id]
                    return len(remaining_ids)
                else:
                    return total_docs_in_db
            elif not total_docs:
                return self.cls_repository.count_documents(query)
            else:
                return total_docs
        except Exception as e:
            self.logger.warning(f"Could not count documents: {e}")
            return 0
    
    def _process_node_batches(
        self,
        query: Dict,
        batch_size: int,
        total_docs: int,
        last_processed_id: Optional[int],
        re_update: bool,
        process_name: str,
        checkpoint_manager: CheckpointManager,
        use_checkpoint: bool
    ) -> Dict[str, Any]:
        """Process documents in batches to create nodes."""
        total_processed = 0
        total_docs_created = 0
        total_terms_created = 0
        start_time = time.time()
        
        with tqdm(total=total_docs, desc="Building nodes", unit="docs") as pbar:
            while total_processed < total_docs:
                batch_start_time = time.time()
                
                # Add pagination condition
                current_query = query.copy()
                if last_processed_id:
                    if "$and" in current_query:
                        current_query["$and"].append({"cls_ID": {"$gt": last_processed_id}})
                    else:
                        current_query = {
                            "$and": [current_query, {"cls_ID": {"$gt": last_processed_id}}]
                        }
                
                # Fetch batch of documents
                try:
                    docs = self.cls_repository.find_documents(
                        query=current_query,
                        projection={"cls_ID": 1, "cls_parsing": 1, "cls_info": 1, "_id": 0},
                        sort=[("cls_ID", 1)],
                        limit=batch_size
                    )
                    
                    if not docs:
                        break
                    
                    # Prepare node parameters
                    batch_doc_params, batch_term_params = self.node_prep_service.batch_prepare_nodes(docs)
                    
                    # Bulk upsert nodes
                    if batch_doc_params or batch_term_params:
                        docs_created, terms_created = self.neo4j_repository.bulk_upsert_nodes(
                            batch_doc_params, batch_term_params, re_update=re_update
                        )
                        total_docs_created += docs_created
                        total_terms_created += terms_created
                    
                    # Update progress
                    last_processed_id = docs[-1]['cls_ID']
                    batch_size_actual = len(docs)
                    total_processed += batch_size_actual
                    pbar.update(batch_size_actual)
                    
                    # Save checkpoint
                    if use_checkpoint:
                        checkpoint_manager.save_checkpoint(
                            last_processed_id,
                            total_processed
                        )
                    
                    # Log batch completion
                    batch_duration = time.time() - batch_start_time
                    self.logger.info(
                        f"Completed batch ({batch_size_actual} docs) in {batch_duration:.2f}s. "
                        f"Progress: {total_processed}/{total_docs}"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Error processing batch: {e}", exc_info=True)
                    raise

        return {
            'processed': total_processed,
            'docs_created': total_docs_created,
            'terms_created': total_terms_created,
            'duration': time.time() - start_time
        }

    def _process_relationship_batches(
        self,
        query: Dict,
        batch_size: int,
        total_docs: int,
        last_processed_id: Optional[int],
        process_name: str,
        checkpoint_manager: CheckpointManager,
        use_checkpoint: bool
    ) -> Dict[str, Any]:
        """Process documents in batches to create relationships."""
        total_processed = 0
        total_relationships_created = 0
        start_time = time.time()
        
        with tqdm(total=total_docs, desc="Building relationships", unit="docs") as pbar:
            while total_processed < total_docs:
                batch_start_time = time.time()
                
                # Add pagination condition
                current_query = query.copy()
                if last_processed_id:
                    if "$and" in current_query:
                        current_query["$and"].append({"cls_ID": {"$gt": last_processed_id}})
                    else:
                        current_query = {
                            "$and": [current_query, {"cls_ID": {"$gt": last_processed_id}}]
                        }
                
                # Fetch batch of documents
                try:
                    docs = self.cls_repository.find_documents(
                        query=current_query,
                        projection={"cls_ID": 1, "cls_parsing": 1, "_id": 0},
                        sort=[("cls_ID", 1)],
                        limit=batch_size
                    )
                    
                    if not docs:
                        break
                    
                    # Prepare relationship parameters
                    rel_params = self.node_prep_service.batch_prepare_relationships(docs)
                    
                    # Bulk create relationships
                    if rel_params:
                        relationships_created = self.neo4j_repository.bulk_create_relationships(
                            'bao_gom', rel_params
                        )
                        total_relationships_created += relationships_created
                    
                    # Update progress
                    last_processed_id = docs[-1]['cls_ID']
                    batch_size_actual = len(docs)
                    total_processed += batch_size_actual
                    pbar.update(batch_size_actual)
                    
                    # Save checkpoint
                    if use_checkpoint:
                        checkpoint_manager.save_checkpoint(
                            last_processed_id,
                            total_processed
                        )
                    
                    # Log batch completion
                    batch_duration = time.time() - batch_start_time
                    self.logger.info(
                        f"Completed batch ({batch_size_actual} docs) in {batch_duration:.2f}s. "
                        f"Progress: {total_processed}/{total_docs}"
                    )
                    
                except Exception as e:
                    self.logger.error(f"Error processing batch: {e}", exc_info=True)
                    raise

        return {
            'processed': total_processed,
            'relationships_created': total_relationships_created,
            'duration': time.time() - start_time
        }

    # ------------------------------------------------------------------
    # Combined nodes + BAO_GOM in a single MongoDB scan
    # ------------------------------------------------------------------

    def build_nodes_and_bao_gom(
        self,
        batch_size: int = 100,
        total_docs: Optional[int] = None,
        vanban_ids: Optional[List[int]] = None,
        reset_relations: bool = False,
        re_update: bool = False,
        use_checkpoint: bool = True
    ) -> Dict[str, Any]:
        """Build VAN_BAN/DIEU_KHOAN nodes AND BAO_GOM rels in a single MongoDB scan.

        Eliminates the duplicate fetch that occurs when ``build_nodes`` and
        ``build_bao_gom_relationships`` are called separately.
        """
        self.logger.info("[NEO4J][NODES+BAO_GOM] Starting combined node+relationship build")

        process_name = "build_nodes_bao_gom"
        if self._checkpoint_suffix:
            process_name = f"{process_name}_{self._checkpoint_suffix}"
        checkpoint_manager = CheckpointManager(process_name, self.checkpoint_dir)
        last_processed_id = None
        if use_checkpoint:
            checkpoint_data = checkpoint_manager.load_checkpoint()
            last_processed_id = checkpoint_data.get('last_doc_id_processed') if checkpoint_data else None
            if last_processed_id:
                self.logger.info(f"[NEO4J][NODES+BAO_GOM] Resuming from checkpoint: last_id={last_processed_id}")

        query, ids_to_process = self._prepare_query_and_ids(vanban_ids, total_docs, last_processed_id)

        if reset_relations and last_processed_id is None and ids_to_process:
            self.reset_relations_before_build(ids_to_process, batch_size=batch_size)
            re_update = True

        total_docs_count = self._count_documents_to_process(query, ids_to_process, last_processed_id, total_docs)

        stats = self._process_combined_node_bao_gom_batches(
            query=query,
            batch_size=batch_size,
            total_docs=total_docs_count,
            last_processed_id=last_processed_id,
            re_update=re_update,
            process_name=process_name,
            checkpoint_manager=checkpoint_manager,
            use_checkpoint=use_checkpoint,
        )

        if use_checkpoint:
            checkpoint_manager.clear_checkpoint()

        self.logger.info(
            f"[NEO4J][NODES+BAO_GOM] ✅ {stats['processed']} docs | "
            f"{stats['docs_created']} VAN_BAN | {stats['terms_created']} DIEU_KHOAN | "
            f"{stats['relationships_created']} BAO_GOM"
        )
        return stats

    def _process_combined_node_bao_gom_batches(
        self,
        query: Dict,
        batch_size: int,
        total_docs: int,
        last_processed_id: Optional[int],
        re_update: bool,
        process_name: str,
        checkpoint_manager: CheckpointManager,
        use_checkpoint: bool,
    ) -> Dict[str, Any]:
        """Fetch each batch once, prepare nodes + BAO_GOM rels, write both to Neo4j."""
        total_processed = 0
        total_docs_created = 0
        total_terms_created = 0
        total_relationships_created = 0
        start_time = time.time()

        with tqdm(total=total_docs, desc="Building nodes+BAO_GOM", unit="docs") as pbar:
            while total_processed < total_docs:
                current_query = query.copy()
                if last_processed_id:
                    if "$and" in current_query:
                        current_query["$and"].append({"cls_ID": {"$gt": last_processed_id}})
                    else:
                        current_query = {"$and": [current_query, {"cls_ID": {"$gt": last_processed_id}}]}

                try:
                    docs = self.cls_repository.find_documents(
                        query=current_query,
                        projection={"cls_ID": 1, "cls_parsing": 1, "cls_info": 1, "_id": 0},
                        sort=[("cls_ID", 1)],
                        limit=batch_size,
                    )
                    if not docs:
                        break

                    # Single CPU pass: prepare both nodes and BAO_GOM rels
                    batch_doc_params, batch_term_params = self.node_prep_service.batch_prepare_nodes(docs)
                    rel_params = self.node_prep_service.batch_prepare_relationships(docs)

                    if batch_doc_params or batch_term_params:
                        docs_created, terms_created = self.neo4j_repository.bulk_upsert_nodes(
                            batch_doc_params, batch_term_params, re_update=re_update
                        )
                        total_docs_created += docs_created
                        total_terms_created += terms_created

                    if rel_params:
                        total_relationships_created += self.neo4j_repository.bulk_create_relationships(
                            'bao_gom', rel_params
                        )

                    last_processed_id = docs[-1]['cls_ID']
                    batch_size_actual = len(docs)
                    total_processed += batch_size_actual
                    pbar.update(batch_size_actual)

                    if use_checkpoint:
                        checkpoint_manager.save_checkpoint(last_processed_id, total_processed)

                    self.logger.info(
                        f"Combined batch ({batch_size_actual} docs) in "
                        f"{time.time() - start_time:.2f}s total. "
                        f"Progress: {total_processed}/{total_docs}"
                    )

                except Exception as e:
                    self.logger.error(f"Error in combined node+BAO_GOM batch: {e}", exc_info=True)
                    raise

        return {
            'processed': total_processed,
            'docs_created': total_docs_created,
            'terms_created': total_terms_created,
            'relationships_created': total_relationships_created,
            'duration': time.time() - start_time,
        }

    def get_statistics(self) -> Dict[str, int]:
        """
        Get current knowledge graph statistics.
        
        Returns:
            Dictionary with node and relationship counts
        """
        try:
            stats = {
                'total_nodes': self.neo4j_repository.count_nodes(),
                'vanban_nodes': self.neo4j_repository.count_nodes('VAN_BAN'),
                'dieu_khoan_nodes': self.neo4j_repository.count_nodes('DIEU_KHOAN'),
                'total_relationships': self.neo4j_repository.count_relationships(),
                'bao_gom_relationships': self.neo4j_repository.count_relationships('bao_gom')
            }
            return stats
        except Exception as e:
            self.logger.error(f"Error getting statistics: {e}")
            return {}
    
    def close(self):
        """Close all database connections."""
        try:
            self.conn_manager.close_all()
            self.logger.info("All database connections closed successfully")
        except Exception as e:
            self.logger.error(f"Error closing connections: {e}")


# Backward compatibility: alias for existing code
LegalKnowledgeGraph = LegalKnowledgeGraphBuilder
