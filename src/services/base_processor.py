"""Base processor for batch processing with checkpoint support."""
import time
import logging
from typing import Dict, Optional, List
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo.errors import NotPrimaryError, AutoReconnect, CursorNotFound
from tqdm import tqdm
from src.shared.checkpoint import CheckpointManager


class BatchProcessorConfig:
    """Configuration for batch processing."""
    
    def __init__(
        self,
        batch_size: int = 500,
        max_retries: int = 3,
        retry_delay: int = 5,
        checkpoint_interval: int = 100,
        log_interval: int = 100,
        max_time_ms: int = 300000,
        parallel_processing: bool = True,
        parallel_workers: int = 8,
        log_failures_as_warnings: bool = True
    ):
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.checkpoint_interval = checkpoint_interval
        self.log_interval = log_interval
        self.max_time_ms = max_time_ms
        self.parallel_processing = parallel_processing
        self.parallel_workers = parallel_workers
        self.log_failures_as_warnings = log_failures_as_warnings


class BatchProcessor(ABC):
    """
    Abstract base class for batch processing MongoDB documents.
    Handles checkpointing, retries, and progress tracking.
    
    Responsibilities:
    - Batch iteration and pagination
    - Checkpoint management for recovery
    - Retry logic for database failures
    - Progress logging
    
    Subclasses must implement:
    - get_process_name(): Process identifier for logging
    - get_projection(): MongoDB projection for queries
    - process_document(doc): Business logic for single document
    """
    
    def __init__(
        self,
        collection,
        logger: logging.Logger,
        config: Optional[BatchProcessorConfig] = None
    ):
        """
        Args:
            collection: MongoDB collection to process
            logger: Logger instance
            config: Batch processing configuration
        """
        self.collection = collection
        self.logger = logger
        self.config = config or BatchProcessorConfig()
        self.pbar = None
        self.total_processing_time = 0.0
        self.checkpoint_manager = None
        self.last_successfully_processed_id = None
        self.total_successfully_processed = 0
        
    @abstractmethod
    def get_process_name(self) -> str:
        """Return the name of the processing task (for logging)."""
        pass
    
    def get_checkpoint_name(self) -> str:
        """Return checkpoint name (override for custom names)."""
        # Default: use process name in lowercase without redundant _checkpoint suffix
        return self.get_process_name().lower().replace('processor', '').replace('_', '')
    
    @abstractmethod
    def get_projection(self) -> Dict:
        """Return MongoDB projection for querying documents."""
        pass
    
    @abstractmethod
    def process_document(self, doc: Dict) -> bool:
        """
        Process a single document.
        
        Args:
            doc: Document to process
            
        Returns:
            True if processing was successful, False otherwise
        """
        pass
    
    def build_query(
        self,
        first_condition: Dict,
        re_update: bool,
        updated_docs_list: List[str]
    ) -> Dict:
        """
        Build MongoDB query based on conditions.
        
        Args:
            first_condition: Base query condition
            re_update: Whether to reprocess all documents
            updated_docs_list: List of already processed document IDs
            
        Returns:
            MongoDB query dict
        """
        if not re_update:
            return {
                "$and": [
                    first_condition,
                    {"cls_ID": {"$nin": updated_docs_list}}
                ]
            }
        return {"$and": [first_condition]}
    
    def get_total_docs(self, query: Dict) -> int:
        """Get total number of documents matching query."""
        try:
            return self.collection.count_documents(query)
        except Exception as e:
            self.logger.warning(f"[{self.get_process_name()}] Cannot count documents: {e}")
            return 0
    
    def collect_updated_docs(self, query: Dict) -> List[str]:
        """
        Collect IDs of already processed documents.
        Override this method in subclasses if needed.
        """
        return []
    
    def process_batch(
        self,
        first_condition: Dict,
        re_update: bool = False,
        use_checkpoint: bool = True,
        clear_checkpoint_on_complete: bool = True
    ):
        """
        Main batch processing method with checkpoint support.
        
        Args:
            first_condition: Base MongoDB query condition
            re_update: Whether to reprocess all documents
            use_checkpoint: Whether to use checkpoint for resume capability
        """
        process_name = self.get_process_name()
        self.logger.info(f"[{process_name}] Starting batch processing")
        
        self.checkpoint_manager = CheckpointManager(
            self.get_checkpoint_name()
        ) if use_checkpoint else None
        
        checkpoint_data = self._load_checkpoint(self.checkpoint_manager)
        updated_docs_list = [] if re_update else self.collect_updated_docs(first_condition)
        query_mongo = self.build_query(first_condition, re_update, updated_docs_list)
        total_processed, last_processed_id = self._get_initial_state(checkpoint_data)
        self.last_successfully_processed_id = last_processed_id
        self.total_successfully_processed = total_processed
        
        total_docs = self.get_total_docs(query_mongo)
        total_batches = (total_docs + self.config.batch_size - 1) // self.config.batch_size
        self.logger.info(
            f"[{process_name}] Total documents to process: {total_docs}, "
            f"divided into {total_batches} batches"
        )
        
        # Initialize progress bar (tracks documents CHECKED, not necessarily updated)
        self.pbar = tqdm(
            total=total_docs,
            initial=total_processed,
            desc=f"{process_name}",
            unit="checked",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
        )
        
        # Track both checked and updated counts separately
        total_checked = 0  # Documents fetched/examined
        current_batch_num = 0  # Actual batch number
        
        try:
            while True:
                current_batch_num += 1  # Increment for each batch fetched
                
                docs, batch_processed = self._process_batch_with_retry(
                    query_mongo=query_mongo,
                    last_processed_id=last_processed_id,
                    updated_docs_list=updated_docs_list,
                    current_batch=current_batch_num,
                    total_batches=total_batches,
                    total_processed=total_processed,
                    total_docs=total_docs,
                    checkpoint_manager=self.checkpoint_manager,
                    total_checked=total_checked
                )
                
                total_processed += batch_processed
                total_checked += len(docs) if docs else 0
                
                if docs:
                    last_processed_id = docs[-1].get('cls_ID')
                
                if not docs or len(docs) < self.config.batch_size:
                    # Flush any remaining bulk operations before completing
                    if hasattr(self, '_flush_bulk_buffer'):
                        self._flush_bulk_buffer()
                    
                    if self.pbar:
                        self.pbar.close()
                    self.logger.info(
                        f"[{process_name}] 🎉 Completed: {total_processed}/{total_docs} documents"
                    )
                    if self.checkpoint_manager and clear_checkpoint_on_complete:
                        self.checkpoint_manager.clear_checkpoint()
                        self.logger.info(f"[{process_name}] Checkpoint cleared")
                    break
                
                del docs
                
        except KeyboardInterrupt:
            self.logger.warning(f"\n[{process_name}] ⚠️ Processing interrupted by user (Ctrl+C)")
            # Flush any remaining bulk operations before saving checkpoint
            if hasattr(self, '_flush_bulk_buffer'):
                try:
                    self._flush_bulk_buffer()
                except Exception as e:
                    self.logger.error(f"[{process_name}] Error flushing buffer on interrupt: {e}")
            
            if self.checkpoint_manager and self.last_successfully_processed_id:
                self.checkpoint_manager.save_checkpoint(
                    last_doc_id_processed=self.last_successfully_processed_id,
                    total_doc_processed=self.total_successfully_processed,
                    metadata={"interrupted": True, "reason": "KeyboardInterrupt"}
                )
                self.logger.info(f"[{process_name}] ✅ Checkpoint saved: {self.total_successfully_processed} docs processed")
            raise
            
        except Exception as e:
            self.logger.error(f"\n[{process_name}] ❌ Fatal error during processing: {e}")
            # Flush any remaining bulk operations before saving checkpoint
            if hasattr(self, '_flush_bulk_buffer'):
                try:
                    self._flush_bulk_buffer()
                except Exception as flush_error:
                    self.logger.error(f"[{process_name}] Error flushing buffer on error: {flush_error}")
            
            if self.checkpoint_manager and self.last_successfully_processed_id:
                self.checkpoint_manager.save_checkpoint(
                    last_doc_id_processed=self.last_successfully_processed_id,
                    total_doc_processed=self.total_successfully_processed,
                    metadata={
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "fatal_crash": True
                    }
                )
                self.logger.info(f"[{process_name}] ✅ Checkpoint saved: {self.total_successfully_processed} docs processed")
            raise
            
        finally:
            if self.pbar:
                self.pbar.close()
    
    def _load_checkpoint(self, checkpoint_manager: Optional[CheckpointManager]) -> Optional[Dict]:
        """Load checkpoint if available."""
        if checkpoint_manager and checkpoint_manager.checkpoint_exists():
            checkpoint_data = checkpoint_manager.load_checkpoint()
            self.logger.info(
                f"[{self.get_process_name()}] 🔄 Resuming from checkpoint: "
                f"{checkpoint_manager.get_checkpoint_info()}"
            )
            return checkpoint_data
        return None
    
    def _get_initial_state(self, checkpoint_data: Optional[Dict]) -> tuple:
        """Get initial processing state from checkpoint or start fresh."""
        if checkpoint_data:
            total_doc_processed = checkpoint_data.get("total_doc_processed", 0)
            last_doc_id_processed = checkpoint_data.get("last_doc_id_processed")
            self.logger.info(
                f"[{self.get_process_name()}] Resuming from ID: {last_doc_id_processed}, "
                f"Total doc processed: {total_doc_processed}"
            )
            return total_doc_processed, last_doc_id_processed
        return 0, None
    
    def _process_batch_with_retry(
        self,
        query_mongo: Dict,
        last_processed_id: Optional[str],
        updated_docs_list: List[str],
        current_batch: int,
        total_batches: int,
        total_processed: int,
        total_docs: int,
        checkpoint_manager: Optional[CheckpointManager],
        total_checked: int = 0
    ) -> tuple:
        """Process a single batch with retry logic."""
        process_name = self.get_process_name()
        batch_processed = 0
        docs = []
        
        for attempt in range(self.config.max_retries):
            try:
                query = self._build_batch_query(query_mongo, last_processed_id)
                
                cursor = self.collection.find(
                    query,
                    self.get_projection()
                ).sort("cls_ID", -1).limit(self.config.batch_size).max_time_ms(self.config.max_time_ms)
                
                docs = list(cursor)
                
                if not docs:
                    return docs, batch_processed
                
                self.logger.info(
                    f"[{process_name}] 🔄 Starting Batch {current_batch}/{total_batches} "
                    f"- Fetched {len(docs)} documents to check"
                )
                
                # Process documents in parallel if enabled
                if self.config.parallel_processing:
                    batch_processed = self._process_documents_parallel(
                        docs, updated_docs_list, current_batch, total_batches,
                        total_processed, total_docs, checkpoint_manager
                    )
                else:
                    batch_processed = self._process_documents_sequential(
                        docs, updated_docs_list, current_batch, total_batches,
                        total_processed, total_docs, checkpoint_manager
                    )
                
                progress_percent = ((total_processed + batch_processed) / total_docs * 100) if total_docs > 0 else 0
                checked_so_far = total_checked + len(docs)
                
                self.logger.info(
                    f"[{process_name}] Batch {current_batch}/{total_batches} | "
                    f"Fetched: {len(docs)} docs, Updated: {batch_processed} docs "
                    f"({batch_processed}/{len(docs)} = {batch_processed/len(docs)*100:.1f}% had relationships)"
                )
                self.logger.info(
                    f"[{process_name}] ✅ CUMULATIVE: Checked {checked_so_far}/{total_docs} docs, "
                    f"Updated {total_processed + batch_processed} docs ({progress_percent:.1f}%)"
                )
                
                return docs, batch_processed
                
            except (NotPrimaryError, AutoReconnect, CursorNotFound) as e:
                self.logger.warning(
                    f"[{process_name}] Connection/Cursor issue at batch {current_batch}, "
                    f"attempt {attempt + 1}/{self.config.max_retries}: {e}"
                )
                
                if checkpoint_manager and self.last_successfully_processed_id:
                    checkpoint_manager.save_checkpoint(
                        last_doc_id_processed=self.last_successfully_processed_id,
                        total_doc_processed=self.total_successfully_processed,
                        metadata={
                            "error": str(e),
                            "current_batch": current_batch,
                            "attempt": attempt + 1
                        }
                    )
                
                if attempt < self.config.max_retries - 1:
                    self.logger.info(
                        f"[{process_name}] Retrying batch {current_batch} "
                        f"in {self.config.retry_delay} seconds..."
                    )
                    time.sleep(self.config.retry_delay)
                else:
                    self.logger.error(
                        f"[{process_name}] All {self.config.max_retries} attempts failed "
                        f"at batch {current_batch}. Processed {total_processed} documents."
                    )
                    raise
            
            except Exception as e:
                self.logger.error(
                    f"[{process_name}] Unexpected error at batch {current_batch}: {e}"
                )
                
                if checkpoint_manager and self.last_successfully_processed_id:
                    checkpoint_manager.save_checkpoint(
                        last_doc_id_processed=self.last_successfully_processed_id,
                        total_doc_processed=self.total_successfully_processed,
                        metadata={
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "current_batch": current_batch
                        }
                    )
                raise
        
        return docs, batch_processed

    def _process_documents_sequential(
        self,
        docs: List[Dict],
        updated_docs_list: List[str],
        current_batch: int,
        total_batches: int,
        total_processed: int,
        total_docs: int,
        checkpoint_manager: Optional[CheckpointManager]
    ) -> int:
        """Process documents sequentially (original method)."""
        process_name = self.get_process_name()
        batch_processed = 0
        
        for i, doc in enumerate(docs, 1):
            doc_id = doc.get('cls_ID', 'unknown')
            
            if doc_id in updated_docs_list:
                self.logger.info(
                    f"[{process_name}] Document {doc_id} already processed => Skip"
                )
                continue
            
            try:
                if not self.process_document(doc):
                    if self.config.log_failures_as_warnings:
                        self.logger.warning(
                            f"[{process_name}] ✗ FAILED ID: {doc_id}"
                        )
            except Exception as doc_error:
                self.logger.error(
                    f"[{process_name}] ✗ FAILED ID: {doc_id} | Error: {doc_error}"
                )
                continue
            
            batch_processed += 1
            self.last_successfully_processed_id = doc_id
            self.total_successfully_processed += 1
            
            # Update progress bar
            if self.pbar:
                self.pbar.update(1)
            
            if checkpoint_manager and self.total_successfully_processed % self.config.checkpoint_interval == 0:
                checkpoint_manager.save_checkpoint(
                    last_doc_id_processed=doc_id,
                    total_doc_processed=self.total_successfully_processed,
                    metadata={
                        "current_batch": current_batch,
                        "total_batches": total_batches,
                        "batch_processed": batch_processed
                    }
                )
            
            if i % self.config.log_interval == 0 or i == len(docs):
                progress_percent = ((total_processed + batch_processed) / total_docs * 100) if total_docs > 0 else 0
                self.logger.info(
                    f"[{process_name}] Batch {current_batch}/{total_batches} "
                    f"({i}/{len(docs)}) | Total: {total_processed + batch_processed}/{total_docs} "
                    f"({progress_percent:.1f}%)"
                )
        
        return batch_processed
    
    def _process_documents_parallel(
        self,
        docs: List[Dict],
        updated_docs_list: List[str],
        current_batch: int,
        total_batches: int,
        total_processed: int,
        total_docs: int,
        checkpoint_manager: Optional[CheckpointManager]
    ) -> int:
        """Process documents in parallel using ThreadPoolExecutor."""
        process_name = self.get_process_name()
        batch_processed = 0
        
        # Filter out already processed documents
        docs_to_process = [doc for doc in docs if doc.get('cls_ID') not in updated_docs_list]
        
        if len(docs_to_process) != len(docs):
            skipped = len(docs) - len(docs_to_process)
            self.logger.info(
                f"[{process_name}] Skipping {skipped} already processed documents"
            )
        
        if not docs_to_process:
            return batch_processed
        
        # Process documents in parallel
        with ThreadPoolExecutor(max_workers=self.config.parallel_workers) as executor:
            # Submit all documents for processing
            future_to_doc = {
                executor.submit(self.process_document, doc): doc
                for doc in docs_to_process
            }
            
            # Collect results as they complete
            for i, future in enumerate(as_completed(future_to_doc), 1):
                doc = future_to_doc[future]
                doc_id = doc.get('cls_ID', 'unknown')
                
                try:
                    result = future.result()
                    if not result:
                        if self.config.log_failures_as_warnings:
                            self.logger.warning(
                                f"[{process_name}] ✗ FAILED ID: {doc_id}"
                            )
                    else:
                        batch_processed += 1
                        self.last_successfully_processed_id = doc_id
                        self.total_successfully_processed += 1
                        
                except Exception as doc_error:
                    self.logger.error(
                        f"[{process_name}] ✗ FAILED ID: {doc_id} | Error: {doc_error}"
                    )
                    continue
                
                # Update progress bar
                if self.pbar:
                    self.pbar.update(1)
                
                # Checkpoint at intervals
                if checkpoint_manager and self.total_successfully_processed % self.config.checkpoint_interval == 0:
                    # Flush bulk buffer if applicable
                    if hasattr(self, '_flush_bulk_buffer'):
                        self._flush_bulk_buffer()
                    
                    checkpoint_manager.save_checkpoint(
                        last_doc_id_processed=doc_id,
                        total_doc_processed=self.total_successfully_processed,
                        metadata={
                            "current_batch": current_batch,
                            "total_batches": total_batches,
                            "batch_processed": batch_processed
                        }
                    )
                
                # Log progress
                if i % self.config.log_interval == 0 or i == len(docs_to_process):
                    progress_percent = ((total_processed + batch_processed) / total_docs * 100) if total_docs > 0 else 0
                    self.logger.info(
                        f"[{process_name}] Batch {current_batch}/{total_batches} "
                        f"({i}/{len(docs_to_process)}) | Total: {total_processed + batch_processed}/{total_docs} "
                        f"({progress_percent:.1f}%)"
                    )
        
        # Flush any remaining bulk operations
        if hasattr(self, '_flush_bulk_buffer'):
            self._flush_bulk_buffer()
        
        return batch_processed
    
    def _build_batch_query(self, base_query: Dict, last_processed_id: Optional[str]) -> Dict:
        """Build query for current batch with pagination."""
        if last_processed_id:
            return {
                "$and": [
                    base_query,
                    {"cls_ID": {"$lt": last_processed_id}}
                ]
            }
        return base_query.copy()
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()
