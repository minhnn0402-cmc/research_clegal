"""
Document relationships processor service.

This module provides the RelationsProcessorService class which orchestrates the
extraction and updating of document relationships in MongoDB and IE collections.
"""

import json
import gzip
import time
import threading
from typing import Dict, List
from datetime import datetime
from pymongo.collection import Collection
from pymongo import UpdateOne

from src.services.base_processor import BatchProcessor, BatchProcessorConfig
from src.repositories.mongo_repository import MongoRepository
from src.infrastructure.config import ConfigLoader
from src.infrastructure.connections import get_connection_manager
from src.infrastructure.logging import get_logger
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.services.extraction.reference_resolution_service import post_process_relations
from src.utils.relation_utils import get_clause_relations

# Thread-local storage for per-thread RelationsExtractor instances.
# Avoids re-instantiation on every document call across parallel workers.
_thread_local = threading.local()


class RelationsProcessorService(BatchProcessor):
    """
    Service for processing document relationships.
    
    Orchestrates extraction of relationships from legal documents, searches for
    referenced documents, and updates both CLS and IE collections with relationship data.
    """
    
    def __init__(
        self,
        cls_collection: Collection,
        ie_collection: Collection,
        doc_clause_types: Dict = None,
        law_titles_for_regex: List = None,
        config: BatchProcessorConfig = None,
        es_connection_name: str = 'cls_es',
        use_llm: bool = False,
        track_rejections: bool = False,
    ):
        """
        Initialize the document relationships processor service.
        
        Args:
            cls_collection: MongoDB collection for CLS data
            ie_collection: MongoDB collection for IE data
            doc_clause_types: Dictionary with 'doc_types' and 'clause_types'
            law_titles_for_regex: List of law title patterns
            config: Batch processor configuration
            es_connection_name: Name of ES connection in ConnectionManager
            use_llm: Whether to allow LLM (default False)
            
        Raises:
            ValueError: If ES connection is not registered
        """
        logger = get_logger('RelationsProcessorService')
        super().__init__(cls_collection, logger, config)
        
        self.ie_collection = ie_collection
        self.ie_repository = MongoRepository(ie_collection, logger)
        self.use_llm = use_llm
        
        # Load configuration
        config_loader = ConfigLoader()
        self.doc_clause_types = doc_clause_types or config_loader.doc_clause_types
        self.doc_types = self.doc_clause_types.get('doc_types', [])
        self.law_titles_for_regex = law_titles_for_regex or config_loader.law_titles_for_regex
        self.law_dataframe = config_loader.laws_dataframe
        
        self.track_rejections = track_rejections

        # Lock for thread-safe access to shared resources
        self._lock = threading.RLock()

        # Bulk write buffer for IE collection updates
        self.bulk_buffer = []
        self.bulk_buffer_size = 500  # Flush every 500 documents

        # Cross-document ES result cache: eliminates duplicate Elasticsearch lookups
        # when multiple documents reference the same law. Thread-safe via _es_cache_lock.
        # Persisted to disk across pipeline invocations so that subsequent runs against
        # the same source docs (production daily re-ingest, repeated benchmarks, etc.)
        # don't re-issue the same ES queries that returned the same reference_id last
        # time. Cache keys are stable for the same (doc_type, information) pair so
        # they are safe to reuse — references in Vietnamese legal text are
        # effectively immutable identifiers (so_hieu + title + date). On any error
        # loading the persisted cache, we silently start with an empty cache.
        self._es_cache: Dict = {}
        self._es_cache_lock = threading.Lock()
        self._es_cache_path = self._default_es_cache_path()
        self._load_persisted_es_cache()
        
        # Initialize Elasticsearch client
        conn_mgr = get_connection_manager()
        connections = conn_mgr.list_connections()
        
        if es_connection_name not in connections.get('elasticsearch', []):
            raise ValueError(
                f"[RelationsProcessor] Elasticsearch connection '{es_connection_name}' not registered. "
                f"Elasticsearch is required for searching non-law document references. "
                f"Please register it using conn_mgr.register_elasticsearch_from_env("
                f"'{es_connection_name}', 'ES_DEV' or 'ES_PROD')"
            )
        
        self.es_client = conn_mgr.get_es_client_direct(es_connection_name)
        logger.info(
            f'[RelationsProcessor] Elasticsearch client initialized with connection: {es_connection_name}'
        )
    
    def get_process_name(self) -> str:
        """Get the process name for logging."""
        return "DOC_RELS"
    
    def get_checkpoint_name(self) -> str:
        """Return checkpoint name (clean name for file)."""
        # Allow customization via instance variable
        if hasattr(self, '_checkpoint_suffix') and self._checkpoint_suffix:
            return f"doc_rels_processor_{self._checkpoint_suffix}"
        return "doc_rels_processor"
    
    def get_projection(self) -> Dict:
        """Get MongoDB projection for document queries."""
        return {
            "cls_ID": 1,
            "cls_parsing": 1,
            "cls_info.ngay_ban_hanh": 1,
            "cls_info.co_quan_ban_hanh": 1,
            "cls_info.so_hieu": 1,
            "cls_info.loai_van_ban": 1,
            "cls_info.title_without_number": 1,
            "cls_info.title": 1,
            "_id": 0
        }
    
    def collect_updated_docs(self, query: Dict) -> List[str]:
        """
        Collect documents that already have document relationships in IE collection.
        
        Args:
            query: Base query for filtering
            
        Returns:
            List of document IDs that already have cls_doc_rels data
        """
        try:
            docs = self.ie_repository.find_documents(
                query={"cls_doc_rels": {"$exists": True}},
                projection={"cls_ID": 1, "_id": 0}
            )
            return [doc.get('cls_ID') for doc in docs if doc.get('cls_ID')]
        except Exception as e:
            self.logger.warning(f"[RelationsProcessor] Error collecting updated docs: {e}")
            return []
    
    def process_document(self, doc: Dict) -> bool:
        """
        Process a single document to extract document relationships.
        
        Args:
            doc: Document containing cls_ID and cls_parsing data
            
        Returns:
            True if processing successful, False otherwise
        """
        doc_id = doc.get('cls_ID')
        doc_start_time = time.time()
        
        # Validate document structure
        if not doc_id:
            self.logger.warning("[RelationsProcessor] Document missing cls_ID")
            return False
            
        if not doc.get('cls_info'):
            self.logger.warning(f"[RelationsProcessor] Document {doc_id} missing cls_info")
            return False
        
        try:
            self.logger.info(f"[RelationsProcessor] Processing document {doc_id}")
            
            # Extract document metadata
            cls_parsing = doc.get('cls_parsing')

            cls_so_hieu = doc.get('cls_info', {}).get('so_hieu', "")
            cls_info = doc.get('cls_info', {})
            cls_title = cls_info.get('title_without_number') or cls_info.get('title') or ""
            cls_document_type = cls_info.get('loai_van_ban', "")
            
            cls_ngay_ban_hanh = doc.get('cls_info', {}).get('ngay_ban_hanh')
            cls_co_quan_ban_hanh = doc.get('cls_info', {}).get('co_quan_ban_hanh', "")
            
            # Extract year from date
            cls_nam_ban_hanh = self._extract_year(cls_ngay_ban_hanh, doc_id)
            
            # Handle different cls_parsing formats
            cls_parsing = self._process_cls_parsing(cls_parsing, doc_id)
            if cls_parsing is None:
                return False
            
            # Extract document relationships
            extracted_relations = self._extract_relations(
                cls_parsing, cls_so_hieu, cls_title, cls_document_type
            )
            if extracted_relations is None:
                return False
            
            # Process results
            result = self._process_results(
                doc_id=doc_id,
                extracted_relations=extracted_relations,
                cls_nam_ban_hanh=cls_nam_ban_hanh,
                cls_co_quan_ban_hanh=cls_co_quan_ban_hanh,
                cls_so_hieu=cls_so_hieu,
            )
            
            # Log processing time and update stats thread-safely
            doc_duration = time.time() - doc_start_time
            
            with self._lock:
                self.total_processing_time += doc_duration
                
                # Update progress bar with average processing time
                if hasattr(self, 'pbar') and self.pbar:
                    # Use number of documents processed so far for average
                    completed_count = self.pbar.n + 1
                    avg_proc_time = self.total_processing_time / completed_count
                    self.pbar.set_postfix_str(f"avg_proc={avg_proc_time:.2f}s")
            
            self.logger.info(
                f"[RelationsProcessor] Document {doc_id} completed in {doc_duration:.2f} seconds"
            )
            return result
            
        except Exception as e:
            self.logger.error(f"[RelationsProcessor] Error processing {doc_id}: {e}")
            import traceback
            self.logger.error(f"[RelationsProcessor] Traceback: {traceback.format_exc()}")
            return False
    
    def _extract_year(self, ngay_ban_hanh: str, doc_id: int) -> int:
        """Extract year from date string."""
        try:
            return int(ngay_ban_hanh.split("-")[0])
        except (ValueError, IndexError, AttributeError, TypeError):
            self.logger.warning(
                f"Document {doc_id} does not contain valid year: {ngay_ban_hanh}"
            )
            return None
    
    def _process_cls_parsing(self, cls_parsing, doc_id: int) -> List[Dict]:
        """
        Process cls_parsing field handling different formats.
        
        Args:
            cls_parsing: Raw cls_parsing data (dict or list)
            doc_id: Document ID for logging
            
        Returns:
            Parsed cls_parsing list or None if invalid
        """
        try:
            if isinstance(cls_parsing, dict):
                # Format 1: Compressed data in dict
                cls_parsing = cls_parsing['parsing']
                decompressed_bytes = gzip.decompress(cls_parsing)
                cls_parsing = json.loads(decompressed_bytes.decode('utf-8'))
            elif isinstance(cls_parsing, list):
                # Format 2: Already a list (no decompression needed)
                pass
            else:
                self.logger.warning(
                    f"[RelationsProcessor] Skipping document {doc_id}: No parsing data found (cls_parsing is None)"
                )
                return None
        except Exception as e:
            self.logger.error(
                f"[RelationsProcessor] Error processing cls_parsing for {doc_id}: {e}"
            )
            return None
        
        if not cls_parsing:
            self.logger.warning(f"[RelationsProcessor] Document {doc_id} has empty cls_parsing")
            return []
        
        return cls_parsing
    
    def _get_thread_extractor(self) -> RelationsExtractor:
        """Return a per-thread RelationsExtractor, creating one on first use."""
        extractor = getattr(_thread_local, 'extractor', None)
        if extractor is None:
            extractor = RelationsExtractor(
                doc_clause_types=self.doc_clause_types,
                law_titles_for_regex=self.law_titles_for_regex,
                logger=self.logger
            )
            _thread_local.extractor = extractor
        return extractor

    def _extract_relations(
        self, cls_parsing: List[Dict], cls_so_hieu: str,
        cls_title: str, cls_document_type: str = ""
    ) -> List[Dict]:
        """
        Extract document relationships from parsed data.

        Args:
            cls_parsing: Parsed clause data
            cls_so_hieu: Document number
            cls_title: Document title
            cls_document_type: Document type name (e.g. "Luật", "Thông tư")

        Returns:
            List of extracted relationship data or None if error
        """
        try:
            extractor = self._get_thread_extractor()
            relations = extractor.extract_relations(
                data=cls_parsing, cls_so_hieu=cls_so_hieu,
                cls_title=cls_title, cls_document_type=cls_document_type,
                use_llm=self.use_llm, track_rejections=self.track_rejections,
            )
            if self.track_rejections:
                rejected = extractor.rejected_relations
                if rejected:
                    self._write_rejected_relations(cls_so_hieu, rejected)
            return relations
        except Exception as e:
            self.logger.error(
                f"[RelationsProcessor] Error extracting relations for document number {cls_so_hieu}: {e}"
            )
            import traceback
            self.logger.error(f"[RelationsProcessor] Traceback: {traceback.format_exc()}")
            return None

    def _write_rejected_relations(self, cls_so_hieu: str, rejected: List[Dict]) -> None:
        """Persist distractor-filtered relations to cls_graph.rejected for auditability."""
        try:
            update_op = UpdateOne(
                {"cls_so_hieu": cls_so_hieu},
                {
                    "$set": {
                        "cls_graph.rejected": rejected,
                        "cls_graph.rejected_at": datetime.now(),
                    }
                },
                upsert=True,
            )
            with self._lock:
                self.bulk_buffer.append(update_op)
                if len(self.bulk_buffer) >= self.bulk_buffer_size:
                    self._flush_bulk_buffer()
        except Exception as exc:
            self.logger.warning(
                f"[RelationsProcessor] Failed to buffer rejected relations for {cls_so_hieu}: {exc}"
            )
    
    def _process_results(
        self,
        doc_id: int,
        extracted_relations: List[Dict],
        cls_nam_ban_hanh: int,
        cls_co_quan_ban_hanh: str,
        cls_so_hieu: str = '',
    ) -> bool:
        """
        Process extracted relationships and save to database.

        Args:
            doc_id: Document ID
            extracted_relations: Extracted relationship data
            cls_nam_ban_hanh: Year of document issuance
            cls_co_quan_ban_hanh: Issuing authority
            cls_so_hieu: Source document number (used for date-only cache eligibility)

        Returns:
            True if successful, False otherwise
        """
        success = []
        failed = []
        
        if extracted_relations:
            total_rels = sum(len(get_clause_relations(r)) for r in extracted_relations)
            self.logger.info(
                f"[RelationsProcessor] Document {doc_id} starts building cache for "
                f"{total_rels} relationships"
            )
            
            # Post-process relationships
            try:
                success, failed = post_process_relations(
                    extracted_relations=extracted_relations,
                    doc_id=doc_id,
                    nam_ban_hanh=cls_nam_ban_hanh,
                    co_quan_ban_hanh=cls_co_quan_ban_hanh,
                    es_client=self.es_client,
                    shared_cache=self._es_cache,
                    shared_cache_lock=self._es_cache_lock,
                    source_so_hieu=cls_so_hieu,
                )
                
            except Exception as e:
                import traceback
                self.logger.error(
                    f"[RelationsProcessor] Error post-processing extracted_relations for {doc_id}: {e}"
                )
                self.logger.error(f"[RelationsProcessor] Traceback: {traceback.format_exc()}")
                return False
            
            self.logger.info(
                f"[RelationsProcessor] Document {doc_id} finished post-processing with "
                f"{len(success)} successful and {len(failed)} failed relationships"
            )
        else:
            self.logger.info(f"[RelationsProcessor] Document {doc_id} has no extractable relationships")
        
        # Save to IE collection
        return self._save_to_ie_collection(doc_id, success, failed)
    
    def _save_to_ie_collection(
        self,
        doc_id: int,
        success: List[Dict],
        failed: List[Dict]
    ) -> bool:
        """
        Save relationship results to IE collection using bulk buffer.
        
        Args:
            doc_id: Document ID
            success: List of successful relationships
            failed: List of failed relationships
            
        Returns:
            True if successful, False otherwise
        """
        try:
            has_failed = len(failed) > 0
            
            update_op = UpdateOne(
                {"cls_ID": doc_id},
                {
                    "$set": {
                        "cls_graph": {
                            "success": success,
                            "failed": failed,
                            "has_failed": has_failed,
                            "updated_at": datetime.now()
                        }
                    }
                },
                upsert=True
            )
            
            # Thread-safe buffer access
            with self._lock:
                # Add to bulk buffer
                self.bulk_buffer.append(update_op)
                
                # Check threshold and flush while holding lock to prevent races
                if len(self.bulk_buffer) >= self.bulk_buffer_size:
                    self._flush_bulk_buffer()
            
            self.logger.debug(
                f"[RelationsProcessor] Document {doc_id} added to bulk buffer"
            )
            return True
            
        except Exception as e:
            self.logger.error(
                f"[RelationsProcessor] Error buffering update for {doc_id}: {e}"
            )
            return False
    
    def _flush_bulk_buffer(self):
        """Flush bulk write buffer to IE collection."""
        buffer_to_write = []

        with self._lock:
            if not self.bulk_buffer:
                # Even with nothing to flush, persist the ES cache so it survives
                # the process boundary (cheap — JSON dump of a dict that's typically
                # a few hundred entries).
                self._save_persisted_es_cache()
                return

            buffer_to_write = self.bulk_buffer
            self.bulk_buffer = []

        try:
            result = self.ie_collection.bulk_write(buffer_to_write, ordered=False)
            self.logger.info(
                f"[RelationsProcessor] Bulk write completed: {result.modified_count} modified, "
                f"{result.upserted_count} inserted"
            )
            self._save_persisted_es_cache()
        except Exception as e:
            self.logger.error(f"[RelationsProcessor] Error in bulk write: {e}")
            raise

    @staticmethod
    def _default_es_cache_path() -> str:
        """Path used to persist the cross-doc ES reference cache between runs."""
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[2]
        cache_dir = project_root / 'logs'
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir / 'es_reference_cache.json')

    def _load_persisted_es_cache(self) -> None:
        """Load previously-persisted ES reference cache from disk, if present.

        The cache file is a JSON object mapping
            <doc_identity_json>::<year>::<authority> → [reference_id, extracted_info]
        Values are JSON-serializable (str/int/None) because the cache stores either
        an integer ID, a list of IDs, or None — never a callable or non-JSON object.
        Errors are non-fatal: an empty cache is the safe fallback.
        """
        try:
            from pathlib import Path
            path = Path(self._es_cache_path)
            if not path.exists():
                return
            with path.open('r', encoding='utf-8') as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                return
            loaded = 0
            for k, v in payload.items():
                if isinstance(v, list) and len(v) == 2:
                    self._es_cache[k] = (v[0], v[1])
                    loaded += 1
            if loaded:
                self.logger.info(
                    f"[RelationsProcessor] Loaded {loaded} persisted ES cache entries from {path}"
                )
        except Exception as e:
            # Empty cache is the safe fallback — never block startup on cache load.
            self.logger.warning(f"[RelationsProcessor] Could not load ES cache: {e}")

    def _save_persisted_es_cache(self) -> None:
        """Persist the cross-doc ES cache to disk.

        Called from _flush_bulk_buffer so it survives both clean completion and
        mid-run errors. Acquires the cache lock briefly to snapshot.
        """
        try:
            with self._es_cache_lock:
                snapshot = dict(self._es_cache)

            def _coerce(value):
                """Coerce numpy/pandas scalar IDs to native Python types for JSON."""
                if value is None:
                    return None
                if isinstance(value, (list, tuple)):
                    return [_coerce(item) for item in value]
                # numpy.int64 / numpy.float64 / pandas types — try to coerce to int/str
                if hasattr(value, "item"):
                    try:
                        return value.item()
                    except Exception:
                        pass
                if isinstance(value, (int, float, str, bool)):
                    return value
                # Fallback: stringify so we never block the save
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return str(value)

            payload = {}
            for k, v in snapshot.items():
                # _es_cache stores tuples; JSON needs lists. Coerce numpy scalars.
                if isinstance(v, tuple) and len(v) == 2:
                    payload[k] = [_coerce(v[0]), _coerce(v[1])]
            from pathlib import Path
            path = Path(self._es_cache_path)
            tmp_path = path.with_suffix(path.suffix + '.tmp')
            with tmp_path.open('w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False)
            tmp_path.replace(path)
        except Exception as e:
            # Persistence is best-effort — never let cache save block the pipeline.
            self.logger.debug(f"[RelationsProcessor] Could not save ES cache: {e}")
    
