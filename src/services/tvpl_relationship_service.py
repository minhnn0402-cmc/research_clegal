"""
TVPL Relationship Service.

This service handles building relationships from TVPL (Thư Viện Pháp Luật) lược đồ data.
TVPL is an alternative source for legal document relationships that may differ from
the cls_graph source.
"""

from datetime import datetime
from typing import Dict, List, Set, Optional, Any


class TVPLRelationshipService:
    """
    Service for preparing and building relationships from TVPL lược đồ data.
    
    TVPL provides relationship data in the cls_luoc_do field of documents.
    This service extracts and transforms that data into Neo4j relationships.
    """
    
    # Mapping from TVPL relationship keys to standardized relationship types
    RELATION_MAPPING = {
        "van_ban_can_cu": "can_cu",
        "van_ban_bi_dinh_chinh": "dinh_chinh",
        "van_ban_bi_thay_the": "thay_the",
        "van_ban_dan_chieu": "dan_chieu",
        "van_ban_duoc_huong_dan": "huong_dan",
        "van_ban_duoc_sua_doi_bo_sung": "sua_doi_bo_sung",
        "van_ban_duoc_hop_nhat": "hop_nhat",
        "van_ban_bi_bai_bo": "bai_bo",
        "van_ban_bi_dinh_chi": "dinh_chi",
        "van_ban_bi_huy_bo": "huy_bo",
        "van_ban_quy_dinh_chi_tiet": "quy_dinh_chi_tiet",
        "van_ban_huong_dan": "huong_dan",
        "van_ban_hop_nhat": "hop_nhat",
        "van_ban_sua_doi_bo_sung": "sua_doi_bo_sung",
        "van_ban_dinh_chinh": "dinh_chinh",
        "van_ban_thay_the": "thay_the",
        "van_ban_bai_bo": "bai_bo",
        "van_ban_dinh_chi": "dinh_chi",
        "van_ban_huy_bo": "huy_bo",
        "van_ban_duoc_quy_dinh_chi_tiet": "quy_dinh_chi_tiet",
        "van_ban_keo_dai_hieu_luc": "keo_dai_hieu_luc",
        "van_ban_duoc_keo_dai_hieu_luc": "keo_dai_hieu_luc",
        "van_ban_ngung_hieu_luc": "ngung_hieu_luc",
        "van_ban_bi_ngung_hieu_luc": "ngung_hieu_luc"
    }

    # In Neo4j: A-[thay_the]->B means "B bị A thay thế" (B is OLD, A is NEW)
    # The arrow points from NEWER to OLDER document!
    # True = reverse (list -> current)  
    # False = normal (current -> list)
    REVERSED_RELATIONS = {
        # Example: {cls_ID: 100, "van_ban_thay_the": [70,80]} 
        # Means: 70, 80 (newer) replace 100 (older)
        # Neo4j: 70-[thay_the]->100, 80-[thay_the]->100 (meaning 100 bị 70,80 thay thế)
        "van_ban_thay_the": True,             
        "van_ban_huong_dan": True,           
        "van_ban_sua_doi_bo_sung": True,     
        "van_ban_dinh_chinh": True,          
        "van_ban_hop_nhat": True,         
        "van_ban_quy_dinh_chi_tiet": True,   
        "van_ban_bai_bo": True,              
        "van_ban_dinh_chi": True,          
        "van_ban_huy_bo": True,  
        "van_ban_keo_dai_hieu_luc": True,  
        "van_ban_ngung_hieu_luc": True,     
        
        # Example: {cls_ID: 100, "van_ban_bi_thay_the": [120,130]}
        # Means: 100 (newer) replace 120, 130 (older)
        # Neo4j: 100-[thay_the]->120, 100-[thay_the]->130 (meaning 120, 130 bị 100 thay thế)
        "van_ban_bi_thay_the": False,         
        "van_ban_duoc_huong_dan": False,  
        "van_ban_duoc_sua_doi_bo_sung": False,
        "van_ban_bi_dinh_chinh": False,       
        "van_ban_duoc_hop_nhat": False,       
        "van_ban_bi_bai_bo": False,         
        "van_ban_bi_dinh_chi": False,
        "van_ban_bi_huy_bo": False,
        "van_ban_duoc_quy_dinh_chi_tiet": False,
        "van_ban_duoc_keo_dai_hieu_luc": False,
        "van_ban_bi_ngung_hieu_luc": False,
        
        # Reference relationships: Current references docs in list -> NORMAL
        "van_ban_can_cu": False,              # Current căn cứ list
        "van_ban_dan_chieu": False,           # Current dẫn chiếu list
    }
    
    def __init__(self, timestamp: Optional[str] = None, logger=None):
        """
        Initialize TVPL relationship service.
        
        Args:
            timestamp: Timestamp string for relationship metadata
            logger: Logger instance
        """
        self.timestamp = timestamp or datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        self.logger = logger
    
    def prepare_tvpl_relationships_from_document(
        self, 
        doc: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], Set[int]]:
        """
        Extract and prepare TVPL relationships from a document.
        
        Args:
            doc: Document containing cls_ID and cls_luoc_do fields
            
        Returns:
            Tuple of (relationship_params, related_ids_set)
            - relationship_params: List of dicts for bulk Neo4j creation
            - related_ids_set: Set of related document IDs
        """
        cls_ID = doc.get('cls_ID')
        data_luoc_do = doc.get('cls_luoc_do')
        
        if not cls_ID or not data_luoc_do:
            return [], set()
        
        relationship_params = []
        related_ids = set()
        
        # Process each relationship type in the luoc_do data
        for luoc_do_key, luoc_do_list in data_luoc_do.items():
            # Skip if not a known relationship type or empty list
            if luoc_do_key not in self.RELATION_MAPPING or not luoc_do_list:
                continue
            
            mapped_relation = self.RELATION_MAPPING[luoc_do_key]
            is_reversed = self.REVERSED_RELATIONS.get(luoc_do_key, False)
            
            # Process each related document in the list
            for item in luoc_do_list:
                related_doc_id = item.get('id')
                source = item.get('source', '')
                evidence = item.get('description', '')

                if source != 'tvpl':
                    continue # Only process TVPL source
                
                if not related_doc_id:
                    continue

                # Add to related IDs set
                related_ids.add(int(related_doc_id))
                
                # Create relationship parameter dict
                if is_reversed:
                    # Reverse direction: related_doc -> current_doc
                    relationship_params.append({
                        "head_ID": int(related_doc_id),
                        "tail_ID": int(cls_ID),
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                        "rel_type": mapped_relation,
                        "thoi_gian_cap_nhat": self.timestamp,
                        "nguon_cap_nhat": "tvpl",
                    })
                else:
                    # Normal direction: current_doc -> related_doc
                    relationship_params.append({
                        "head_ID": int(cls_ID),
                        "tail_ID": int(related_doc_id),
                        "head_class": "VAN_BAN",
                        "tail_class": "VAN_BAN",
                        "rel_type": mapped_relation,
                        "thoi_gian_cap_nhat": self.timestamp,
                        "nguon_cap_nhat": "tvpl",
                    })
        
        return relationship_params, related_ids

    @staticmethod
    def get_bulk_relationship_query(strict_nodes: bool = False) -> str:
        """
        Get the Cypher query for bulk creating TVPL relationships.
        
        This query:
        1. Deletes existing TVPL relationships (nguon_cap_nhat='tvpl') for documents being updated
        2. Creates new TVPL relationships ONLY if no relationship of the same type exists
           (prevents TVPL from overwriting algorithm-generated relationships)
        
        Priority: Algorithm relationships > TVPL relationships
        
        Returns:
            Cypher query string
        """
        if strict_nodes:
            return TVPLRelationshipService.get_strict_bulk_relationship_query()

        return """
// Step 1: Reset outgoing TVPL relationships for documents being updated (DISABLED)
/*
CALL apoc.periodic.iterate(
    "
    UNWIND $rel_list AS rel
    WITH DISTINCT rel.head_ID AS hid
    RETURN hid
    ",
    "
    MATCH (v:VAN_BAN {ID: hid})-[r]->(: VAN_BAN)
    WHERE type(r) <> 'bao_gom' AND r.nguon_cap_nhat = 'tvpl'
    DELETE r
    ",
    {
        batchSize: 500,
        parallel: false,
        params: {rel_list: $rel_list}
    }
)
YIELD batches, total, timeTaken, committedOperations, failedOperations, failedBatches, retries, errorMessages, batch, operations
*/

// Step 2: Create new TVPL relationships ONLY if relationship doesn't already exist
WITH 1 AS dummy
UNWIND $rel_list AS rel
// MATCH (head:VAN_BAN {ID: rel.head_ID})
// MATCH (tail:VAN_BAN {ID: rel.tail_ID})
// Ensure nodes exist (use apoc.merge.node for efficiency and safety)
CALL apoc.merge.node(['VAN_BAN'], {ID: rel.head_ID}) YIELD node as head
CALL apoc.merge.node(['VAN_BAN'], {ID: rel.tail_ID}) YIELD node as tail

// Check if relationship of same type already exists (from any source)
OPTIONAL MATCH (head)-[existing]->(tail)
WHERE type(existing) = rel.rel_type
   OR (rel.rel_type = 'thay_the' AND type(existing) = 'bai_bo')
   OR (rel.rel_type = 'bai_bo' AND type(existing) = 'thay_the')
WITH head, tail, rel, existing
WHERE existing IS NULL
CALL apoc.merge.relationship(
    head,
    rel.rel_type,
    {},
    {
        thoi_gian_cap_nhat: rel.thoi_gian_cap_nhat,
        nguon_cap_nhat: rel.nguon_cap_nhat
    },
    tail
) YIELD rel as r
RETURN count(r) as total_processed
"""

    @staticmethod
    def get_strict_bulk_relationship_query() -> str:
        """Get TVPL relationship query that refuses to create missing nodes."""
        return """
WITH 1 AS dummy
UNWIND $rel_list AS rel
MATCH (head:VAN_BAN {ID: rel.head_ID})
MATCH (tail:VAN_BAN {ID: rel.tail_ID})

OPTIONAL MATCH (head)-[existing]->(tail)
WHERE type(existing) = rel.rel_type
   OR (rel.rel_type = 'thay_the' AND type(existing) = 'bai_bo')
   OR (rel.rel_type = 'bai_bo' AND type(existing) = 'thay_the')
WITH head, tail, rel, existing
WHERE existing IS NULL
CALL apoc.merge.relationship(
    head,
    rel.rel_type,
    {},
    {
        thoi_gian_cap_nhat: rel.thoi_gian_cap_nhat,
        nguon_cap_nhat: rel.nguon_cap_nhat
    },
    tail
) YIELD rel as r
RETURN count(r) as total_processed
"""

