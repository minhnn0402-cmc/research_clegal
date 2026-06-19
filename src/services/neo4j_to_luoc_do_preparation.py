"""
Neo4j to Luoc Do Preparation Service.

This service converts Neo4j relationships back to MongoDB cls_luoc_do format.
It reads relationships from Neo4j and transforms them into the structured
cls_luoc_do format for storage in MongoDB.
"""

import datetime
from typing import List, Dict, Any
from pymongo import UpdateOne

from src.repositories.neo4j_repository import Neo4jRepository
from src.repositories.mongo_repository import MongoRepository
from src.infrastructure.logging import get_logger


class Neo4jToLuocDoPreparation:
    """
    Service for exporting Neo4j relationships to MongoDB cls_luoc_do format.
    
    This service reads relationships from Neo4j and converts them back to the
    cls_luoc_do structure in MongoDB, allowing other services to consume
    relationship data without directly querying Neo4j.
    """
    
    def __init__(
        self,
        neo4j_repository: Neo4jRepository,
        cls_repository: MongoRepository,
        ie_repository: MongoRepository,
        logger=None
    ):
        """
        Initialize Neo4j to Luoc Do preparation service.
        
        Args:
            neo4j_repository: Neo4j repository for reading relationships
            cls_repository: MongoDB repository for CLS collection
            ie_repository: MongoDB repository for IE collection
            logger: Optional logger instance
        """
        self.neo4j_repository = neo4j_repository
        self.cls_repository = cls_repository
        self.ie_repository = ie_repository
        self.logger = logger or get_logger(self.__class__.__name__)
        
        # Get direct access to collections and driver
        self.cls_collection = cls_repository.collection
        self.ie_collection = ie_repository.collection
        self.driver = neo4j_repository.driver
        self.database = neo4j_repository.database
        
        # Alternative logger name for compatibility
        self.logger_neo4j = self.logger
    

    
    def update_luoc_do(
        self, 
        doc_ids: List[int], 
        clear_old_data: bool = True,
        source: str = 'neo4j_export'
    ) -> Dict[str, Any]:
        """Update luoc_do data from Neo4j relationships.
        
        This converts Neo4j relationships back to cls_luoc_do format in MongoDB.
        
        Neo4j semantic: A-[thay_the]->B means "B bị A thay thế" (A is newer, B is older)
        
        Args:
            doc_ids: List of document IDs to update
            clear_old_data: If True, clear old luoc_do data before updating
            source: Source identifier for tracking (default: 'neo4j_export')
            
        Returns:
            Dictionary with processing statistics
        """
        # Template for luoc_do structure (all possible relationship types)
        luoc_do_template = {
            # Active forms (document PERFORMS action on others)
            "van_ban_thay_the": [],
            "van_ban_huong_dan": [],
            "van_ban_sua_doi_bo_sung": [],
            "van_ban_bai_bo": [],
            "van_ban_dinh_chi": [],
            "van_ban_huy_bo": [],
            "van_ban_dinh_chinh": [],
            "van_ban_quy_dinh_chi_tiet": [],
            "van_ban_hop_nhat": [],
            "van_ban_keo_dai_hieu_luc": [],
            "van_ban_ngung_hieu_luc": [],
            
            # Passive forms (document RECEIVES action from others)
            "van_ban_can_cu": [],
            "van_ban_dan_chieu": [],
            "van_ban_bi_thay_the": [],
            "van_ban_duoc_huong_dan": [],
            "van_ban_duoc_sua_doi_bo_sung": [],
            "van_ban_bi_bai_bo": [],
            "van_ban_bi_dinh_chi": [],
            "van_ban_bi_huy_bo": [],
            "van_ban_bi_dinh_chinh": [],
            "van_ban_duoc_quy_dinh_chi_tiet": [],
            "van_ban_duoc_hop_nhat": [],
            "van_ban_duoc_keo_dai_hieu_luc": [],
            "van_ban_bi_ngung_hieu_luc": [],
        }

        # Mapping when document is HEAD of relationship (performs action)
        # Neo4j: head-[rel_type]->tail
        # But remember: A-[thay_the]->B means "B bị A thay thế" (A acts on B)
        # So head ACTS ON tail
        rel_mapping_head = {
            "can_cu": "van_ban_can_cu",                   
            "dan_chieu": "van_ban_dan_chieu",             
            "thay_the": "van_ban_bi_thay_the",
            "huong_dan": "van_ban_duoc_huong_dan",
            "sua_doi_bo_sung": "van_ban_duoc_sua_doi_bo_sung",
            "bai_bo": "van_ban_bi_bai_bo",
            "dinh_chi": "van_ban_bi_dinh_chi",
            "huy_bo": "van_ban_bi_huy_bo",
            "dinh_chinh": "van_ban_bi_dinh_chinh",
            "quy_dinh_chi_tiet": "van_ban_duoc_quy_dinh_chi_tiet",
            "hop_nhat": "van_ban_duoc_hop_nhat",
            "keo_dai_hieu_luc": "van_ban_duoc_keo_dai_hieu_luc",
            "ngung_hieu_luc": "van_ban_bi_ngung_hieu_luc",
        }

        rel_mapping_tail = {
            "thay_the": "van_ban_thay_the",
            "huong_dan": "van_ban_huong_dan",
            "sua_doi_bo_sung": "van_ban_sua_doi_bo_sung",
            "bai_bo": "van_ban_bai_bo",
            "dinh_chi": "van_ban_dinh_chi",
            "huy_bo": "van_ban_huy_bo",
            "dinh_chinh": "van_ban_dinh_chinh",
            "quy_dinh_chi_tiet": "van_ban_quy_dinh_chi_tiet",
            "hop_nhat": "van_ban_hop_nhat",
            "keo_dai_hieu_luc": "van_ban_keo_dai_hieu_luc",
            "ngung_hieu_luc": "van_ban_ngung_hieu_luc",
        }

        # Initialize results dict for each ID
        results = {doc_id: {k: [] for k in luoc_do_template} for doc_id in doc_ids}

        # Query to get all relationships involving the specified IDs
        # We split the query into smaller Neo4j batches to avoid performance issues with large IN clauses
        neo4j_batch_size = 5000
        all_records = []
        
        query = """
            MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
            WHERE type(r) <> 'bao_gom' AND head.ID IN $ids
            RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type,
                   r.nguon_cap_nhat AS source
            UNION
            MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
            WHERE type(r) <> 'bao_gom' AND tail.ID IN $ids
            RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type,
                   r.nguon_cap_nhat AS source
        """

        with self.driver.session(database=self.database) as session:
            for i in range(0, len(doc_ids), neo4j_batch_size):
                batch_ids = doc_ids[i:i + neo4j_batch_size]
                result = session.run(query, {"ids": batch_ids})
                all_records.extend(list(result))

        # Process each relationship
        for record in all_records:
            head_id = record["head_id"]
            tail_id = record["tail_id"]
            rel_type = record["rel_type"]
            source = record.get("source", "cmcai")  # Default to 'cmcai' if no source

            # Skip self-references
            if head_id == tail_id:
                continue

            # If head is in our ID list (document performs action)
            if head_id in results:
                key = rel_mapping_head.get(rel_type)
                if key and key in results[head_id]:
                    results[head_id][key].append({
                        "id": tail_id,
                        "source": source
                    })

            # If tail is in our ID list (document receives action)
            if tail_id in results:
                key = rel_mapping_tail.get(rel_type)
                if key and key in results[tail_id]:
                    results[tail_id][key].append({
                        "id": head_id,
                        "source": source
                    })

        # Bulk update MongoDB
        ops = []
        for cls_ID, luoc_do_data in results.items():
            ops.append(
                UpdateOne(
                    {"cls_ID": cls_ID},
                    {"$set": {
                        "cls_luoc_do": {
                            **luoc_do_data,
                            "updated_at": datetime.datetime.now()
                        }
                    }},
                    upsert=True
                )
            )

        if ops:
            result = self.ie_collection.bulk_write(ops)
            updated_count = result.modified_count + result.upserted_count
            self.logger_neo4j.info(
                f"[NEO4J->LUOC_DO] Updated cls_luoc_do for {updated_count} documents"
            )
        else:
            updated_count = 0
            self.logger_neo4j.warning("[NEO4J->LUOC_DO] No updates to perform")
        
        return {
            'processed': len(doc_ids),
            'updated': updated_count,
            'relationships_found': len(all_records)
        }
