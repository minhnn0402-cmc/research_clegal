"""
Main program for processing legal document relationships.

This is the production entry point for batch processing document relationships.
It reads document IDs from a JSON file.

Usage:
    python -m src.extract_relations [--doc-ids-file PATH] [--batch-size N]
"""

# ruff: noqa: E402

import sys
import argparse
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.infrastructure.logging import get_logger
from src.infrastructure.connections import get_connection_manager
from src.infrastructure.config import AppConfig
from src.services.base_processor import BatchProcessorConfig
from src.services.relations_processor_service import RelationsProcessorService
from src.services.infer_relations import InferredRelationsBuilder
from src.shared.data.json_loader import load_doc_ids


def parse_arguments(argv=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Process legal document relationships',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Process documents from default file
    python -m src.extract_relations

    # Process documents from custom file
    python -m src.extract_relations --doc-ids-file data/my_documents.json

    # Process with custom batch size
    python -m src.extract_relations --doc-ids-file data/my_documents.json --batch-size 1000

    # Process with custom checkpoint interval
    python -m src.extract_relations --doc-ids-file data/my_documents.json --checkpoint-interval 500
        """
    )
    
    parser.add_argument(
        '--doc-ids-file',
        type=str,
        default='debug/sample_doc_ids.json',
        help='Path to JSON file containing document IDs (default: debug/sample_doc_ids.json)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Number of documents to process per batch (default: 500)'
    )
    
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Maximum number of retries for failed operations (default: 3)'
    )
    
    parser.add_argument(
        '--checkpoint-interval',
        type=int,
        default=100,
        help='Save checkpoint every N documents (default: 100)'
    )
    
    parser.add_argument(
        '--log-interval',
        type=int,
        default=100,
        help='Log progress every N documents (default: 100)'
    )
    
    parser.add_argument(
        '--skip-already-processed',
        action='store_true',
        help='Skip documents that already have relationship data'
    )
    
    parser.add_argument(
        '--parallel-workers',
        type=int,
        default=8,
        help='Number of parallel workers for document processing (default: 8)'
    )
    
    parser.add_argument(
        '--no-parallel',
        action='store_true',
        help='Disable parallel processing (process documents sequentially)'
    )
    
    parser.add_argument(
        '--bulk-buffer-size',
        type=int,
        default=100,
        help='Size of bulk write buffer for database updates (default: 100)'
    )
    
    parser.add_argument(
        '--infer-batch-size',
        type=int,
        default=100,
        help='Batch size for inferred relations processing (default: 100)'
    )
    
    parser.add_argument(
        '--skip-infer-relations',
        action='store_true',
        help='Skip inferred relations processing (runs by default after main processing)'
    )
    
    parser.add_argument(
        '--only-infer-relations',
        action='store_true',
        help='Run ONLY inferred relations processing (skip main document processing)'
    )
    
    parser.add_argument(
        '--use-llm',
        action='store_true',
        help='Enable LLM for relation extraction (default: disabled)'
    )

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

    parser.add_argument(
        '--mongo-extraction-collection',
        type=str,
        help='MongoDB collection name for extraction output (overrides IE_COLLECTION env var)'
    )

    parser.add_argument(
        '--clear-es-cache',
        action='store_true',
        help='Clear the persisted Elasticsearch reference cache before starting extraction'
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


def _has_env_values(prefix: str, keys: List[str]) -> bool:
    """Return True when all required env vars for a prefix are present and non-empty."""
    for key in keys:
        value = os.getenv(f"{prefix}_{key}")
        if value is None or str(value).strip() == "":
            return False
    return True


def _pick_elasticsearch_prefix() -> str:
    """
    Pick Elasticsearch env prefix in priority order.

    Priority:
    1. ES_DEV_*
    2. ES_PROD_*
    """
    for prefix in ("ES_DEV", "ES_PROD"):
        if _has_env_values(prefix, ["ENDPOINT"]):
            return prefix

    raise ValueError(
        "No Elasticsearch endpoint found. Set one of: "
        "ES_DEV_ENDPOINT, ES_PROD_ENDPOINT"
    )


def setup_connections(logger) -> Tuple[object, str]:
    """Setup database connections and return the active ES connection name."""
    logger.info("Setting up database connections...")
    
    conn_mgr = get_connection_manager()
    
    try:
        # Register MongoDB connections
        conn_mgr.register_mongo_from_env('cls_mongo_prod', 'MONGO_PROD')
        mongo_dev_required = ['HOST', 'PORT', 'USER', 'PASSWORD', 'DATABASE']

        if _has_env_values("MONGO_DEV", mongo_dev_required):
            conn_mgr.register_mongo_from_env('cls_mongo_dev', 'MONGO_DEV')
            logger.info("✅ MongoDB connections registered (PROD and DEV)")
        else:
            logger.info("✅ MongoDB connection registered (PROD)")
            logger.warning(
                "MONGO_DEV_* variables not fully set; skipping DEV Mongo registration"
            )
        
        # Register Elasticsearch.
        es_prefix = _pick_elasticsearch_prefix()
        es_connection_name = 'cls_es'
        conn_mgr.register_elasticsearch_from_env(es_connection_name, es_prefix)
        logger.info(f"✅ Elasticsearch connection registered from {es_prefix}_*")
        
        return conn_mgr, es_connection_name
        
    except Exception as e:
        logger.error(f"❌ Connection setup failed: {e}")
        raise


def get_collections(conn_mgr, logger, ie_collection_override=None):
    """Get MongoDB collections."""
    logger.info("Getting MongoDB collections...")

    try:
        cfg = AppConfig()
        cls_db_name = cfg.cls_database
        cls_collection_name = cfg.cls_collection
        ie_db_name = cfg.ie_database
        ie_collection_name = ie_collection_override or cfg.ie_collection

        # Get source collection (PROD - contains document data)
        cls_collection = conn_mgr.get_mongo_collection(
            'cls_mongo_prod',
            cls_collection_name,
            db_name=cls_db_name,
        )
        logger.info("✅ CLS collection retrieved (PROD)")
        
        # Get target collection (PROD - stores relationship results)
        ie_collection = conn_mgr.get_mongo_collection(
            'cls_mongo_prod',
            ie_collection_name,
            db_name=ie_db_name,
        )
        if ie_collection_override:
            logger.info(f"✅ IE collection retrieved (PROD) [overridden to: {ie_collection_name}]")
        else:
            logger.info("✅ IE collection retrieved (PROD)")
        
        return cls_collection, ie_collection
        
    except Exception as e:
        logger.error(f"❌ Failed to get collections: {e}")
        raise


def create_processor(
    cls_collection,
    ie_collection,
    config,
    logger,
    checkpoint_suffix=None,
    use_llm: bool = False,
    es_connection_name: str = 'cls_es',
):
    """Create document relationships processor."""
    logger.info("Creating RelationsProcessorService...")
    
    try:
        processor = RelationsProcessorService(
            cls_collection=cls_collection,
            ie_collection=ie_collection,
            config=config,
            es_connection_name=es_connection_name,
            use_llm=use_llm
        )
        
        # Set checkpoint suffix if provided
        if checkpoint_suffix:
            processor._checkpoint_suffix = checkpoint_suffix
            logger.info(f"   Checkpoint suffix: {checkpoint_suffix}")
        
        logger.info("✅ Processor created successfully")
        logger.info(f"   Service: {type(processor).__name__}")
        logger.info(f"   Batch size: {config.batch_size}")
        logger.info(f"   Max retries: {config.max_retries}")
        logger.info(f"   Checkpoint interval: {config.checkpoint_interval}")
        logger.info(f"   LLM fallback: {'enabled' if use_llm else 'disabled'}")
        
        return processor
        
    except Exception as e:
        logger.error(f"❌ Processor creation failed: {e}")
        raise


def load_document_ids(file_path: str, logger) -> Optional[List[int]]:
    """Load document IDs from JSON file."""
    logger.info(f"Loading document IDs from: {file_path}")
    
    try:
        doc_ids = load_doc_ids(file_path)
        
        if not doc_ids:
            logger.warning("⚠️ No document IDs found in file")
            return None
        
        logger.info(f"✅ Loaded {len(doc_ids)} document IDs")
        
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


def run_inferred_relations(doc_ids: List[int], batch_size: int, logger, ie_collection, checkpoint_suffix=None):
    """
    Run inferred relations builder after main processing.
    
    Args:
        doc_ids: List of document IDs that were processed
        batch_size: Batch size for processing
        logger: Logger instance
        ie_collection: MongoDB collection to use for inferred relations
        checkpoint_suffix: Optional suffix for checkpoint file
    """
    logger.info("\n" + "="*80)
    logger.info("STARTING INFERRED RELATIONS PROCESSING")
    logger.info("="*80)
    logger.info(f"Processing {len(doc_ids)} documents for inferred relations")
    if checkpoint_suffix:
        logger.info(f"Checkpoint suffix: {checkpoint_suffix}")
    logger.info("")
    
    builder = InferredRelationsBuilder(ie_collection=ie_collection)
    
    # Set checkpoint suffix if provided
    if checkpoint_suffix and hasattr(builder, 'processor'):
        builder.processor._checkpoint_suffix = checkpoint_suffix
    
    try:
        start_time = time.time()
        
        # Process documents to create inferred_relations field
        results = builder.process_documents(
            batch_size=batch_size,
            doc_ids=doc_ids,
            use_checkpoint=True
        )
        
        # Calculate duration
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Display summary
        logger.info("\n" + "="*80)
        logger.info("INFERRED RELATIONS PROCESSING SUMMARY")
        logger.info("="*80)
        
        if results:
            logger.info(f"Total Processed: {results.get('processed', 0)}")
            logger.info(f"Successfully Updated: {results.get('updated', 0)}")
            logger.info(f"Skipped: {results.get('skipped', 0)}")
            logger.info(f"Errors: {results.get('errors', 0)}")
        else:
            logger.warning("No results returned from processing")
            
        logger.info(f"Duration: {timedelta(seconds=int(total_duration))}")
        logger.info("="*80)
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Inferred relations processing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    finally:
        builder.close()


def main(argv=None):
    """Main entry point."""

    # Parse arguments
    args = parse_arguments(argv)
    
    # Initialize logger
    logger = get_logger('ExtractRelations')
    
    logger.info("="*80)
    logger.info("LEGAL DOCUMENT RELATIONSHIPS PROCESSOR")
    logger.info("="*80)
    
    # Setup environment
    setup_environment(logger)
    
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
    logger.info("")
    
    # Setup connections
    try:
        conn_mgr, es_connection_name = setup_connections(logger)
        cls_collection, ie_collection = get_collections(
            conn_mgr, logger, args.mongo_extraction_collection
        )
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}")
        return 1

    # Clear ES cache if requested (before any processor is created)
    if args.clear_es_cache:
        from src.services.relations_processor_service import RelationsProcessorService
        from pathlib import Path as _Path
        cache_path = _Path(RelationsProcessorService._default_es_cache_path())
        if cache_path.exists():
            cache_path.unlink()
            logger.info(f"✅ ES reference cache cleared: {cache_path}")
        else:
            logger.info("ℹ️ No ES reference cache file found to clear")
    
    # If only running inferred relations, skip main processing
    if args.only_infer_relations:
        logger.info("\n" + "="*80)
        logger.info("⚙️ RUNNING ONLY INFERRED RELATIONS PROCESSING")
        logger.info("="*80)
        logger.info("Main document processing will be SKIPPED\n")
        
        # Clear checkpoint if requested
        if args.clear_checkpoint:
            from src.shared.checkpoint import CheckpointManager
            checkpoint_mgr = CheckpointManager(f'inferred_relations_{checkpoint_suffix}')
            if checkpoint_mgr.checkpoint_exists():
                checkpoint_mgr.clear_checkpoint()
                logger.info("✅ Inferred relations checkpoint cleared")
            else:
                logger.info("ℹ️ No checkpoint found to clear")
        
        try:
            infer_results = run_inferred_relations(
                doc_ids=doc_ids,
                batch_size=args.infer_batch_size,
                logger=logger,
                ie_collection=ie_collection,
                checkpoint_suffix=checkpoint_suffix
            )
            
            if infer_results:
                logger.info("✅ Inferred relations processing completed successfully")
                return 0
            else:
                logger.warning("⚠️ Inferred relations processing had issues")
                return 1
        except Exception as e:
            logger.error(f"❌ Inferred relations processing failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 1
        finally:
            conn_mgr.close_all()
    
    # Clear checkpoint if requested
    if args.clear_checkpoint:
        from src.shared.checkpoint import CheckpointManager
        checkpoint_mgr = CheckpointManager(f'doc_rels_processor_{checkpoint_suffix}')
        if checkpoint_mgr.checkpoint_exists():
            checkpoint_mgr.clear_checkpoint()
            logger.info("✅ Checkpoint cleared")
        else:
            logger.info("ℹ️ No checkpoint found to clear")
    
    # Create processor configuration
    config = BatchProcessorConfig(
        batch_size=args.batch_size,
        max_retries=args.max_retries,
        retry_delay=5,
        checkpoint_interval=args.checkpoint_interval,
        log_interval=args.log_interval,
        max_time_ms=300000,  # 5 minutes timeout
        parallel_processing=not args.no_parallel,
        parallel_workers=args.parallel_workers
    )
    
    # Create processor
    try:
        processor = create_processor(
            cls_collection, 
            ie_collection, 
            config, 
            logger,
            checkpoint_suffix=checkpoint_suffix,
            use_llm=args.use_llm,
            es_connection_name=es_connection_name,
        )
        
        # Configure bulk buffer size if specified
        if hasattr(processor, 'bulk_buffer_size'):
            processor.bulk_buffer_size = args.bulk_buffer_size
            logger.info(f"Bulk buffer size set to: {args.bulk_buffer_size}")
            
    except Exception as e:
        logger.error(f"❌ Processor creation failed: {e}")
        return 1
    
    # Build query
    first_condition = {'cls_ID': {'$in': doc_ids}}
    
    # Skip already processed documents if requested
    if args.skip_already_processed:
        logger.info("Collecting already processed documents...")
        already_processed = processor.collect_updated_docs(first_condition)
        
        if already_processed:
            logger.info(f"Found {len(already_processed)} already processed documents")
            logger.info("Excluding them from processing...")
            
            # Remove already processed from doc_ids
            remaining_ids = [doc_id for doc_id in doc_ids if doc_id not in already_processed]
            
            if not remaining_ids:
                logger.info("✅ All documents already processed!")
                return 0
            
            logger.info(f"Remaining documents to process: {len(remaining_ids)}")
            first_condition = {'cls_ID': {'$in': remaining_ids}}
    
    # Start processing
    logger.info("\n" + "="*80)
    logger.info("STARTING BATCH PROCESSING")
    logger.info("="*80)
    logger.info(f"Total documents: {len(doc_ids)}")
    logger.info(f"Query: {first_condition}")
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    # Record start time
    start_time = time.time()
    
    # Scale handling: If we have many IDs, chunk the MongoDB query to stay efficient
    # MongoDB planning for $in with 100k+ IDs can be very slow.
    MAX_IDS_PER_QUERY = AppConfig().max_ids_per_query
    
    # Sort IDs for consistent pagination (essential for $lt resume logic)
    all_doc_ids = sorted(doc_ids, reverse=True)
    
    try:
        # If total IDs exceed threshold, process in query-friendly chunks
        if len(all_doc_ids) > MAX_IDS_PER_QUERY:
            logger.info(f"🚀 Large dataset detected ({len(all_doc_ids)} docs). Processing in chunks of {MAX_IDS_PER_QUERY} to optimize MongoDB...")
            
            # Note: We still use the same checkpoint suffix for the whole task
            # BatchProcessor will pick up from the last doc_id across chunks
            
            for i in range(0, len(all_doc_ids), MAX_IDS_PER_QUERY):
                chunk = all_doc_ids[i:i + MAX_IDS_PER_QUERY]
                chunk_condition = {'cls_ID': {'$in': chunk}}
                
                logger.info(f"📦 Processing ID Chunk {i//MAX_IDS_PER_QUERY + 1} ({len(chunk)} docs)")
                
                # Run batch for this chunk
                # Clear checkpoint only on the VERY LAST chunk
                is_last_chunk = (i + MAX_IDS_PER_QUERY >= len(all_doc_ids))
                
                processor.process_batch(
                    first_condition=chunk_condition,
                    re_update=True,
                    use_checkpoint=True,
                    clear_checkpoint_on_complete=is_last_chunk
                )
        else:
            # Standard single-batch processing for smaller sets
            first_condition = {'cls_ID': {'$in': all_doc_ids}}
            processor.process_batch(
                first_condition=first_condition,
                re_update=True,
                use_checkpoint=True
            )
        
        # Calculate and display duration statistics
        end_time = time.time()
        total_duration = end_time - start_time
        avg_time_per_doc = total_duration / len(doc_ids) if doc_ids else 0
        
        logger.info("\n" + "="*80)
        logger.info("✅ BATCH PROCESSING COMPLETED SUCCESSFULLY")
        logger.info("="*80)
        logger.info(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Total duration: {timedelta(seconds=int(total_duration))}")
        logger.info(f"Documents processed: {len(doc_ids)}")
        logger.info(f"Average time per document: {avg_time_per_doc:.2f} seconds")
        logger.info(f"Processing speed: {len(doc_ids)/total_duration:.2f} docs/second")
        logger.info("="*80)
        
        # Run inferred relations builder (unless explicitly skipped)
        if not args.skip_infer_relations:
            logger.info("\n")
            infer_results = run_inferred_relations(
                doc_ids=doc_ids,
                batch_size=args.infer_batch_size,
                logger=logger,
                ie_collection=ie_collection,
                checkpoint_suffix=checkpoint_suffix
            )
            
            if infer_results:
                logger.info("✅ Inferred relations processing completed successfully")
            else:
                logger.warning("⚠️ Inferred relations processing had issues")
        else:
            logger.info("\n⏭️ Skipping inferred relations processing (--skip-infer-relations flag set)")
        
        return 0
        
    except KeyboardInterrupt:
        end_time = time.time()
        elapsed = end_time - start_time
        logger.warning("\n⚠️ Processing interrupted by user (Ctrl+C)")
        logger.info(f"Elapsed time before interruption: {timedelta(seconds=int(elapsed))}")
        logger.info("You can resume from the last checkpoint")
        return 130
        
    except Exception as e:
        end_time = time.time()
        elapsed = end_time - start_time
        logger.error(f"\n❌ Processing failed: {e}")
        logger.error(f"Elapsed time before failure: {timedelta(seconds=int(elapsed))}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
