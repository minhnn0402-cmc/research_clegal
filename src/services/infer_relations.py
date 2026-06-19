"""
Program to infer indirect document-to-document relationships from cls_graph.success data
Author: stevehoang
Date: 2026-01-29

This program transforms cls_graph.success data into a structured format
suitable for creating indirect VAN_BAN -> VAN_BAN relationships in Neo4j.
"""

import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from pymongo.collection import Collection

from src.infrastructure.logging import get_logger
from src.infrastructure.connections import ConnectionManager
from src.services.base_processor import BatchProcessor, BatchProcessorConfig
from src.domain.relation_constants import RELATION_DESCRIPTIONS, COMPONENT_NAMES

load_dotenv(override=True)


class RelationTransformer:
    """
    Handles transformation of cls_graph data to inferred_relations format.
    
    Separates data transformation logic from processing orchestration,
    making the code more testable and maintainable.
    """
    
    @staticmethod
    def is_roman_numeral(s: str) -> bool:
        """Check if string is a valid Roman numeral."""
        if not s:
            return False
        # Roman numerals only contain I, V, X, L, C, D, M
        return all(c in 'IVXLCDM' for c in s.upper())
    
    @staticmethod
    def parse_component_key(com_key: str) -> str:
        """
        Parse component key to readable Vietnamese format.
        
        Args:
            com_key: Component key like "khoan_1_dieu_219"
            
        Returns:
            Readable format like "Khoản 1 Điều 219"
            
        Examples:
            >>> RelationTransformer.parse_component_key("khoan_1_dieu_219")
            "Khoản 1 Điều 219"
            >>> RelationTransformer.parse_component_key("diem_a_khoan_2")
            "Điểm a Khoản 2"
            >>> RelationTransformer.parse_component_key("dieu_42a")
            "Điều 42a"
        """
        parts = com_key.split('_')
        readable = []
        
        i = 0
        while i < len(parts):
            if parts[i] in COMPONENT_NAMES:
                if i + 1 < len(parts):
                    next_part = parts[i + 1]
                    # For diem, accept both digits and letters (a, b, c, etc.)
                    if parts[i] == 'diem' and (next_part.isdigit() or next_part.isalpha()):
                        readable.append(
                            f"{COMPONENT_NAMES[parts[i]]} {next_part}"
                        )
                        i += 2
                    # For chuong and phan, accept Roman numerals in addition to digits
                    elif parts[i] in ('chuong', 'phan') and (next_part.isdigit() or RelationTransformer.is_roman_numeral(next_part)):
                        # Keep Roman numerals uppercase
                        display_value = next_part.upper() if RelationTransformer.is_roman_numeral(next_part) else next_part
                        readable.append(
                            f"{COMPONENT_NAMES[parts[i]]} {display_value}"
                        )
                        i += 2
                    # For other components, accept digits (allow alphanumeric for 'dieu' like 42a)
                    elif parts[i] not in ('diem', 'chuong', 'phan'):
                        is_valid = next_part.isalnum() if parts[i] == 'dieu' else next_part.isdigit()
                        if is_valid:
                            readable.append(
                                f"{COMPONENT_NAMES[parts[i]]} {next_part}"
                            )
                            i += 2
                        else:
                            i += 1
                    else:
                        i += 1
                else:
                    i += 1
            else:
                i += 1
        
        return ' '.join(readable)
    
    @staticmethod
    def build_description(rels: Dict[str, List[str]], relation: str) -> str:
        """
        Build description text for the relationship.
        
        Args:
            rels: Dictionary mapping source_key#{cls_ID} to target_key#{target_doc_id} list
            relation: Relationship type (e.g., 'sua_doi_bo_sung')
            
        Returns:
            Formatted description text with grouped targets by source
            
        Example:
            "Các điều khoản tác động trực tiếp:
            \tKhoản 3 Điều 49 sửa đổi, bổ sung Khoản 17 Điều 4, Khoản 16 Điều 4."
        """
        relation_desc = RELATION_DESCRIPTIONS.get(
            relation, relation
        )
        
        description_lines = []
        
        for source_key, target_keys in rels.items():
            # Parse source key (remove #{cls_ID} suffix)
            source_com_key = source_key.split('#')[0]
            source_readable = RelationTransformer.parse_component_key(source_com_key)
            
            # Parse all target keys
            target_readables = []
            for target_key in target_keys:
                # Parse target key (remove #{doc_ID} suffix)
                target_com_key = target_key.split('#')[0]
                target_readable = RelationTransformer.parse_component_key(target_com_key)
                target_readables.append(target_readable)
            
            # Group targets with comma separation
            targets_text = ', '.join(target_readables)
            description_lines.append(
                f"{source_readable} {relation_desc} {targets_text}."
            )
        
        return '\n'.join(description_lines)
    
    @staticmethod
    def transform_cls_graph(cls_graph: Dict[str, Any], cls_ID: int) -> List[Dict[str, Any]]:
        """
        Transform cls_graph to indirected_doc_to_doc format.
        
        Args:
            cls_graph: Dictionary containing cls_graph data with 'success' array
            cls_ID: Current document ID
            
        Returns:
            List of relation objects with structure:
            [
                {
                    'relation': 'sua_doi_bo_sung',
                    'collection': [
                        {
                            'doc_ID': 12345,
                            'rels': {
                                'khoan_1_dieu_219#999': ['dieu_32#12345'],
                                'khoan_2_dieu_219#999': ['dieu_4#12345']
                            },
                            'description': '...'
                        }
                    ]
                }
            ]
        """
        success_array = cls_graph.get('success', [])
        
        if not success_array:
            return []
        
        # Group by relation and doc_ID and original_relation
        # Structure: inferred_relation -> (target_doc_id, original_relation) -> {'id_relations': {source_key: [target_keys]}}
        grouped_data: Dict[str, Dict[tuple, Dict[str, Any]]] = {}
        
        for item in success_array:
            source_key = item.get('source_key')
            success = item.get('success', [])
            
            # Skip if no source_key
            if not source_key:
                continue
            
            for status in success:
                relation = status.get('relationship')
                target_key = status.get('target_key')
                target_doc_id = status.get('target_doc_id')
                
                # Only process when both source_key and target_key are not null
                if not target_key or not target_doc_id or not relation:
                    continue
                
                # Skip target_key that are not dieu/khoan/diem (muc, phan, chuong are excluded)
                if target_key.startswith(('muc_', 'phan_', 'chuong_')):
                    continue

                # Map relation to inferred_relation
                if relation in ['sua_doi_bo_sung', 'sua_doi', 'bo_sung', 'thay_the', 'bai_bo', 'huy_bo', 'dinh_chi']:
                    inferred_relation = 'sua_doi_bo_sung'
                elif relation in ['huong_dan', 'quy_dinh_chi_tiet']:
                    inferred_relation = 'huong_dan'
                elif relation == 'dan_chieu':
                    inferred_relation = 'dan_chieu'
                elif relation == 'dinh_chinh':
                    inferred_relation = 'dinh_chinh'
                elif relation == 'keo_dai_hieu_luc':
                    inferred_relation = 'keo_dai_hieu_luc'
                elif relation == 'ngung_hieu_luc':
                    inferred_relation = 'ngung_hieu_luc'
                else:
                    # For unknown relations, keep the original relation name
                    inferred_relation = relation

                # Initialize nested dictionaries - group by both target_doc_id AND original relation
                if inferred_relation not in grouped_data:
                    grouped_data[inferred_relation] = {}
                
                # Use tuple of (target_doc_id, relation) as key to separate different relationships
                doc_relation_key = (target_doc_id, relation)
                
                if doc_relation_key not in grouped_data[inferred_relation]:
                    grouped_data[inferred_relation][doc_relation_key] = {
                        'id_relations': {}
                    }
                
                # Create keys with ID suffixes
                source_key_with_id = f"{source_key}#{cls_ID}"
                target_key_with_id = f"{target_key}#{target_doc_id}"
                
                if source_key_with_id not in grouped_data[inferred_relation][doc_relation_key]['id_relations']:
                    grouped_data[inferred_relation][doc_relation_key]['id_relations'][source_key_with_id] = []
                
                # Add target_key if not already present
                if target_key_with_id not in grouped_data[inferred_relation][doc_relation_key]['id_relations'][source_key_with_id]:
                    grouped_data[inferred_relation][doc_relation_key]['id_relations'][source_key_with_id].append(
                        target_key_with_id
                    )
        
        # Transform to final structure
        result = []
        
        for inferred_relation, doc_groups in grouped_data.items():
            collection = []
            
            for (target_doc_id, original_relation), data in doc_groups.items():
                id_relations = data['id_relations']
                description = RelationTransformer.build_description(id_relations, original_relation)
                
                collection.append({
                    'target_doc_id': target_doc_id,
                    'relation': original_relation,
                    'id_relations': id_relations,
                    'description': description
                })
            
            result.append({
                'inferred_relation': inferred_relation,
                'collection': collection
            })
        
        return result


class InferredRelationsProcessor(BatchProcessor):
    """
    Batch processor for creating inferred_relations field in documents.
    
    Extends BatchProcessor to leverage existing infrastructure for
    batch processing, checkpointing, and error handling.
    """
    
    def __init__(self, collection: Collection, logger, config: Optional[BatchProcessorConfig] = None):
        """
        Initialize the processor.
        
        Args:
            collection: MongoDB collection to process
            logger: Logger instance
            config: Batch processing configuration
        """
        super().__init__(collection, logger, config)
        self.transformer = RelationTransformer()
    
    def get_process_name(self) -> str:
        """Return process name for logging."""
        return "InferredRelationsProcessor"
    
    def get_checkpoint_name(self) -> str:
        """Return checkpoint name (clean name for file)."""
        # Allow customization via instance variable
        if hasattr(self, '_checkpoint_suffix') and self._checkpoint_suffix:
            return f"inferred_relations_{self._checkpoint_suffix}"
        return "inferred_relations"
    
    def get_projection(self) -> Dict[str, int]:
        """Return MongoDB projection for querying documents."""
        return {
            "cls_ID": 1,
            "cls_graph": 1,
            "_id": 0
        }
    
    def process_document(self, doc: Dict[str, Any]) -> bool:
        """
        Process a single document to create inferred_relations.
        
        Args:
            doc: Document containing cls_ID and cls_graph
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cls_ID = doc.get('cls_ID')
            cls_graph = doc.get('cls_graph', {})
            
            if not cls_graph:
                # Silent skip - no cls_graph means nothing to process
                return False
            
            # Transform data using RelationTransformer
            inferred_relations = self.transformer.transform_cls_graph(cls_graph, cls_ID)
            
            # Only update if there's data
            if inferred_relations:
                self.collection.update_one(
                    {'cls_ID': cls_ID},
                    {'$set': {'cls_graph.inferred_relations': inferred_relations}}
                )
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error processing document {doc.get('cls_ID')}: {e}")
            return False


class InferredRelationsBuilder:
    """
    Main orchestrator for building inferred_relations field.
    
    Coordinates MongoDB connection and batch processing using the
    InferredRelationsProcessor.
    """
    
    def __init__(self, ie_collection=None):
        """
        Initialize connections and logger.
        
        Args:
            ie_collection: Optional MongoDB collection. If not provided,
                          will create new connection using environment variables.
        """
        # Use fixed log name so old log is deleted on each run
        self.logger = get_logger("InferRelations")
        
        if ie_collection is not None:
            # Use provided collection
            self.ie_collection = ie_collection
            self.conn_manager = None
            self.logger.info("Using provided MongoDB collection")
        else:
            # Create new connection using environment variables
            self.conn_manager = ConnectionManager()
            
            # Register MongoDB connection from environment
            self.conn_manager.register_mongo_from_env('ie_mongo', 'MONGO_DEV')
            
            # Get collection
            ie_database_name = os.getenv('MONGO_IE_DATABASE', 'ie')
            ie_collection_name = os.getenv('MONGO_IE_COLLECTION', 'ie_collection')
            
            self.ie_collection = self.conn_manager.get_mongo_collection(
                'ie_mongo',
                ie_collection_name,
                ie_database_name
            )
            
            self.logger.info("Connected to MongoDB IE collection successfully")
    
    def process_documents(
        self,
        batch_size: int = 100,
        limit: Optional[int] = None,
        doc_ids: Optional[List[int]] = None,
        use_checkpoint: bool = True
    ) -> Dict[str, Any]:
        """
        Process documents to create inferred_relations field.
        
        Args:
            batch_size: Number of documents to process per batch
            limit: Maximum number of documents to process
            doc_ids: Specific list of document IDs to process
            use_checkpoint: Whether to use checkpoint for resume capability
            
        Returns:
            Dictionary with processing statistics
        """
        self.logger.info("Starting process to create inferred_relations field")
        
        # Build query
        if doc_ids:
            first_condition = {
                "cls_graph": {"$exists": True, "$ne": None},
                "cls_ID": {"$in": doc_ids}
            }
            self.logger.info(f"Processing {len(doc_ids)} specific documents")
        else:
            first_condition = {
                "cls_graph": {"$exists": True, "$ne": None}
            }
        
        # Configure batch processor
        config = BatchProcessorConfig(
            batch_size=batch_size,
            max_retries=3,
            retry_delay=5,
            checkpoint_interval=100,
            log_interval=100,
            log_failures_as_warnings=False  # Don't log as warnings - returning False is normal
        )
        
        # Create processor and execute
        processor = InferredRelationsProcessor(
            collection=self.ie_collection,
            logger=self.logger,
            config=config
        )
        
        # Process batch (this doesn't return anything, just processes)
        try:
            processor.process_batch(
                first_condition=first_condition,
                re_update=False,
                use_checkpoint=use_checkpoint
            )
            
            # Get statistics from processor
            results = {
                'processed': processor.total_successfully_processed,
                'updated': processor.total_successfully_processed,
                'skipped': 0,
                'errors': 0
            }
            
        except Exception as e:
            self.logger.error(f"Error during batch processing: {e}")
            results = {
                'processed': getattr(processor, 'total_successfully_processed', 0),
                'updated': 0,
                'skipped': 0,
                'errors': 1
            }
        
        self.logger.info("=" * 80)
        self.logger.info("PROCESSING COMPLETED")
        self.logger.info("=" * 80)
        
        return results
    
    def close(self):
        """Close database connections."""
        if self.conn_manager is not None:
            self.conn_manager.close_all()
            self.logger.info("Closed all database connections")
        else:
            self.logger.info("Using external collection, no connections to close")


def main():
    """
    Main entry point for running the inferred relations builder.
    
    Usage example:
        from src.services.infer_relations import main
        main()
    """
    builder = InferredRelationsBuilder()
    
    try:
        # Process all documents with cls_graph
        results = builder.process_documents(
            batch_size=100,
            use_checkpoint=True
        )
        
        print(f"\n{'='*80}")
        print("Processing Summary:")
        print(f"Total Processed: {results.get('processed', 0)}")
        print(f"Successfully Updated: {results.get('updated', 0)}")
        print(f"Skipped: {results.get('skipped', 0)}")
        print(f"Errors: {results.get('errors', 0)}")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"Error during processing: {e}")
        raise
    finally:
        builder.close()


if __name__ == "__main__":
    main()
