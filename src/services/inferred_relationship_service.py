"""
Inferred Relationship Service.

Handles building Neo4j relationships from cls_graph.inferred_relations field.
This processes indirect/inferred relationships.
"""

from typing import Dict, List, Any
from collections import defaultdict
from datetime import datetime

from src.infrastructure.logging import get_logger


class InferredRelationshipService:
    """
    Service for building Neo4j relationships from cls_graph.inferred_relations.
    
    Processes inferred/indirect relationships created by the infer_relations module.
    These are relationships where only specific clauses are affected (mot_phan).
    """
    
    # Valid inferred relationship types
    INFERRED_REL_TYPES = [
        'sua_doi_bo_sung',
        'dinh_chinh',
        'huong_dan',
        'keo_dai_hieu_luc',
        'dan_chieu',
        'ngung_hieu_luc'
    ]
    
    def __init__(self, timestamp: str = None, logger=None, neo4j_repository=None):
        """
        Initialize the service.

        Args:
            timestamp: Optional timestamp string
            logger: Optional logger instance
            neo4j_repository: Optional Neo4j repository for deletion operations
        """
        self.timestamp_value = timestamp or datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        self.logger = logger or get_logger(self.__class__.__name__)
        self.neo4j_repository = neo4j_repository
        # Pre-build static Cypher filter to avoid rebuilding on every delete call
        _filter = ' OR '.join([f'type(r) = "{rt}"' for rt in self.INFERRED_REL_TYPES])
        self._delete_query_template = (
            f"CALL {{\n"
            f"    MATCH (source:VAN_BAN)-[r]->(target:VAN_BAN)\n"
            f"    WHERE source.ID IN $doc_ids\n"
            f"      AND ({_filter})\n"
            f"      AND r.loai_quan_he = 'gian_tiep'\n"
            f"    DELETE r\n"
            f"    RETURN count(r) as deleted_count\n"
            f"}} IN TRANSACTIONS OF 1000 ROWS\n"
            f"RETURN sum(deleted_count) as total_deleted\n"
        )
    
    def delete_inferred_relationships_for_documents(
        self, 
        doc_ids: List[int],
        batch_size: int = 1000
    ) -> int:
        """
        Delete all inferred relationships for the given document IDs.
        This ensures clean updates when rebuilding inferred relationships.
        
        Processes in batches to avoid OOM.
        
        Args:
            doc_ids: List of document IDs (cls_ID values)
            batch_size: Number of doc IDs to process per deletion query
            
        Returns:
            Total number of relationships deleted
        """
        if not self.neo4j_repository:
            self.logger.warning("No Neo4j repository provided, skipping deletion")
            return 0
        
        if not doc_ids:
            return 0
        
        self.logger.info(f"Deleting existing inferred relationships for {len(doc_ids):,} documents...")
        
        total_deleted = 0
        delete_query = self._delete_query_template

        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i+batch_size]

            try:
                with self.neo4j_repository.driver.session(
                    database=self.neo4j_repository.database
                ) as session:
                    result = session.run(delete_query, doc_ids=batch_ids)
                    record = result.single()
                    batch_deleted = record['total_deleted'] if record else 0
                    total_deleted += batch_deleted
                    
                    if batch_deleted > 0:
                        self.logger.info(
                            f"  Batch {i//batch_size + 1}: Deleted {batch_deleted:,} relationships "
                            f"for {len(batch_ids):,} documents"
                        )
            
            except Exception as e:
                self.logger.error(f"Error deleting inferred relationships for batch {i//batch_size + 1}: {e}")
                continue
        
        self.logger.info(f"✅ Total inferred relationships deleted: {total_deleted:,}")
        return total_deleted
    
    def prepare_inferred_relationships_from_document(
        self, 
        doc: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract and group inferred relationships from a single document.
        
        The structure is:
        cls_graph: {
          inferred_relations: [
            {
              relation: "sua_doi_bo_sung",  // inferred relation type
              collection: [
                {
                  target_doc_id: 12345,
                  relation: "bai_bo",  // original/specific relation type
                  id_relations: {
                    "khoan_1_dieu_219#999": ["dieu_32#12345"],
                    "khoan_2_dieu_219#999": ["dieu_4#12345"]
                  },
                  description: "..."
                }
              ]
            }
          ]
        }
        
        Args:
            doc: MongoDB document with cls_graph.inferred_relations field
            
        Returns:
            Dictionary mapping relationship types to their parameters
            e.g., {'thay_the_mot_phan': [params], 'bai_bo_mot_phan': [params]}
        """
        try:
            cls_ID = doc.get('cls_ID')
            cls_graph = doc.get('cls_graph', {})
            inferred_relations = cls_graph.get('inferred_relations', [])
            
            if not inferred_relations:
                return {}
            
            # Group relationships by type
            relationships_by_type = defaultdict(list)
            
            # Iterate through inferred relations array
            for relation_group in inferred_relations:
                # Support both 'relation' and 'inferred_relation' keys
                relation_type = relation_group.get('relation') or relation_group.get('inferred_relation')
                collection = relation_group.get('collection', [])
                
                if not relation_type or relation_type not in self.INFERRED_REL_TYPES:
                    continue
                
                # Group collection items by target_doc_id to merge duplicates
                grouped_by_target = {}
                
                for item in collection:
                    target_doc_id = item.get('target_doc_id')
                    
                    if not target_doc_id:
                        continue
                    
                    if target_doc_id not in grouped_by_target:
                        grouped_by_target[target_doc_id] = {
                            'id_relations': {},
                            'relations': set(),
                            'descriptions': []
                        }
                    
                    # Merge id_relations
                    id_relations = item.get('id_relations', {})
                    for source_key, target_keys in id_relations.items():
                        if source_key not in grouped_by_target[target_doc_id]['id_relations']:
                            grouped_by_target[target_doc_id]['id_relations'][source_key] = []
                        # Add target keys if not already present
                        for tk in target_keys:
                            if tk not in grouped_by_target[target_doc_id]['id_relations'][source_key]:
                                grouped_by_target[target_doc_id]['id_relations'][source_key].append(tk)
                    
                    # Collect relations
                    original_relation = item.get('relation')
                    if original_relation:
                        grouped_by_target[target_doc_id]['relations'].add(original_relation)
                    
                    # Collect descriptions
                    description = item.get('description', '')
                    if description and description not in grouped_by_target[target_doc_id]['descriptions']:
                        grouped_by_target[target_doc_id]['descriptions'].append(description)
                
                # Create relationship parameters for each unique target_doc_id
                for target_doc_id, merged_data in grouped_by_target.items():
                    # Build moi_quan_he_goc as a list containing ONLY the original relations
                    # (NOT the inferred relation - that's the relationship type itself)
                    moi_quan_he_goc = sorted(list(merged_data['relations']))
                    
                    # Create relationship parameters
                    evidence = '\n'.join(merged_data['descriptions'])
                    rel_params = {
                        'head_ID': cls_ID,
                        'tail_ID': target_doc_id,
                        'head_class': 'VAN_BAN',
                        'tail_class': 'VAN_BAN',
                        'nguon_cap_nhat': 'cmcai',
                        'loai_quan_he': 'gian_tiep',
                        'thoi_gian_cap_nhat': self.timestamp_value,
                        'mo_ta': evidence,  # Join descriptions with newlines
                        'danh_sach_id_lien_quan': merged_data['id_relations'],
                        'moi_quan_he_goc': moi_quan_he_goc  # List of original relation types only
                    }
                    
                    relationships_by_type[relation_type].append(rel_params)
            
            return dict(relationships_by_type)
            
        except Exception as e:
            self.logger.error(
                f"Error preparing inferred relationships from doc {doc.get('cls_ID')}: {e}"
            )
            return {}
    
    def get_relationship_statistics(
        self, 
        relationships_by_type: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, int]:
        """
        Get statistics about relationships by type.
        
        Args:
            relationships_by_type: Dictionary mapping rel types to parameters
            
        Returns:
            Dictionary with counts per type
        """
        return {
            rel_type: len(params)
            for rel_type, params in relationships_by_type.items()
        }
