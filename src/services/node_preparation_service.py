"""
Node preparation service for Knowledge Graph.

This module provides the NodePreparationService class which handles the preparation
and transformation of document data into Neo4j node parameters.
"""

import gzip
import json
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime

from src.infrastructure.logging import get_logger


class NodePreparationService:
    """
    Service for preparing node parameters from document data.
    
    Handles the transformation of MongoDB document data into properly formatted
    parameters for Neo4j node creation.
    """
    
    def __init__(self, timestamp: Optional[str] = None, logger=None):
        """
        Initialize the node preparation service.
        
        Args:
            timestamp: Optional timestamp string (default: current time)
            logger: Optional logger instance
        """
        self.timestamp_value = timestamp or datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        self.logger = logger or get_logger(self.__class__.__name__)
    
    def prepare_nodes_from_document(
        self, 
        doc: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Prepare VAN_BAN and DIEU_KHOAN node parameters from a MongoDB document.
        
        Args:
            doc: MongoDB document with cls_parsing, cls_ID, and cls_info fields
            
        Returns:
            Tuple of (doc_params, term_params) where:
            - doc_params: List of VAN_BAN node parameters
            - term_params: List of DIEU_KHOAN node parameters
        """
        try:
            # Extract and decompress cls_parsing data
            data_parsing = self._extract_and_decompress_parsing(doc.get('cls_parsing'))
            
            cls_ID = doc.get('cls_ID')
            cls_info = doc.get('cls_info', {})

            # Validate required fields
            if not cls_ID:
                missing_fields = ['cls_ID']
                doc_id = str(doc.get('_id', 'Unknown ID'))
                self.logger.debug(f"Skipping document {doc_id} - missing: {', '.join(missing_fields)}")
                return [], []

            # Extract common information from cls_info
            common_info = self._extract_common_info(cls_info)

            # Prepare node parameters
            doc_params = []
            term_params = []

            # Always create VAN_BAN node parameters
            doc_params.append({
                "ID": cls_ID,
                "name": common_info.get("loai_van_ban"),  # Display name (e.g., "Nghị định", "Thông tư")
                **common_info,
                "thoi_gian_cap_nhat": self.timestamp_value
            })

            if data_parsing:
                for com_info in data_parsing:
                    com_type = com_info.get('com_type')
                    
                    # Only process specific component types
                    if com_type not in ["dieu", "khoan", "diem", "vanban"]:
                        continue
                    
                    if com_type == 'vanban':
                        continue
                        
                    com_key = com_info.get('com_key')
                    if not com_key:
                        continue
                        
                    original_term_id = f"{com_key}#{cls_ID}"

                    # Create DIEU_KHOAN node parameters
                    term_params.append({
                        "ID": original_term_id,
                        "vi_tri": com_info.get("com_path"),
                        "cap_do": com_type,
                        "noi_dung": com_info.get("com_title"),
                        "vi_tri_chi_tiet": str(com_info.get("com_titles_name")),
                        **common_info,
                        "thoi_gian_cap_nhat": self.timestamp_value
                    })

            return doc_params, term_params
            
        except Exception as e:
            self.logger.error(f"Error preparing nodes from document {doc.get('cls_ID')}: {e}")
            return [], []
    
    def prepare_bao_gom_relationships(
        self, 
        doc: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Prepare BAO_GOM relationship parameters from a MongoDB document.
        
        Args:
            doc: MongoDB document with cls_parsing and cls_ID fields
            
        Returns:
            List of relationship parameters with head_ID, tail_ID, and timestamp
        """
        try:
            # Extract and decompress cls_parsing data
            data_parsing = self._extract_and_decompress_parsing(doc.get('cls_parsing'))
            
            cls_ID = doc.get('cls_ID')

            # Validate required fields
            if not (data_parsing and cls_ID):
                return []

            rel_params = []

            for com_info in data_parsing:
                com_type = com_info.get('com_type')
                
                # Only process specific component types
                if com_type not in ["dieu", "khoan", "diem", "vanban"]:
                    continue
                
                com_key = com_info.get('com_key')
                if not com_key:
                    continue

                parts = com_key.split('_')
                # E.g., com_key = "khoan_2_dieu_1" => parts = ["khoan", "2", "dieu", "1"] => head_key = "dieu_1"
                #       com_key = "khoan_2_dieu_1_1_dk_1" => parts = ["khoan", "2", "dieu", "1", "1", "dk", "1"] => head_key = "dieu_1_1_dk_1" 
                #       com_key = "diem_a_khoan_2_dieu_14_1_dk_1" => parts = ["diem", "a", "khoan", "2", "dieu", "14", "1", "dk", "1"] => head_key = "khoan_2_dieu_14_1_dk_1"
                #       com_key = "dieu_14_dk_1" => parts = ["dieu", "14", "dk", "1"] => head_key = ""
                #       com_key = "khoan_2_dieu_14_dk_1" => parts = ["khoan", "2", "dieu", "14", "dk", "1"] => head_key = "dieu_14_dk_1"
                
                # If component starts with "dieu", it connects directly to VAN_BAN (no parent DIEU_KHOAN)
                if parts[0] == 'dieu':
                    head_key = ""
                else:
                    head_key = "_".join(parts[2:])  # E.g., khoan_2_dieu_1 -> dieu_1
                
                tail_id = f"{com_key}#{cls_ID}"

                if not head_key:
                    head_class = 'VAN_BAN'
                    head_id = cls_ID
                    rel_params.append({
                        "head_ID": head_id,
                        "head_class": head_class,
                        "tail_ID": tail_id,
                        "thoi_gian_cap_nhat": self.timestamp_value,
                        "nguon_cap_nhat": "cmcai"
                    })
                else:
                    head_class = 'DIEU_KHOAN'
                    head_id = f"{head_key}#{cls_ID}"
                    rel_params.append({
                        "head_ID": head_id,
                        "head_class": head_class,
                        "tail_ID": tail_id,
                        "thoi_gian_cap_nhat": self.timestamp_value,
                        "nguon_cap_nhat": "cmcai"
                    })

            return rel_params
            
        except Exception as e:
            self.logger.error(f"Error preparing bao_gom relationships for document {doc.get('cls_ID')}: {e}")
            return []
    
    def _extract_and_decompress_parsing(
        self, 
        cls_parsing: Any
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Extract and decompress cls_parsing data.
        
        Args:
            cls_parsing: cls_parsing field from MongoDB document
            
        Returns:
            Decompressed parsing data as list of dictionaries, or None if invalid
        """
        if not cls_parsing:
            return None
        
        try:
            # Handle compressed data
            if isinstance(cls_parsing, dict):
                parsing_data = cls_parsing.get('parsing')
                if parsing_data:
                    decompressed_bytes = gzip.decompress(parsing_data)
                    return json.loads(decompressed_bytes.decode('utf-8'))
            
            # Handle already decompressed data
            if isinstance(cls_parsing, list):
                return cls_parsing
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error decompressing parsing data: {e}")
            return None
    
    def _extract_common_info(self, cls_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract common information fields from cls_info.
        
        Args:
            cls_info: cls_info field from MongoDB document
            
        Returns:
            Dictionary of common information fields
        """
        return {
            "ten_day_du": cls_info.get("title"),
            "so_hieu": cls_info.get("so_hieu"),
            "trich_yeu": cls_info.get("trich_yeu"),
            "tinh_trang_hieu_luc": cls_info.get("tinh_trang_hieu_luc"),
            "ngay_ban_hanh": cls_info.get("ngay_ban_hanh"),
            "ngay_co_hieu_luc": cls_info.get("ngay_co_hieu_luc"),
            "ngay_dang_cong_bao": cls_info.get("ngay_dang_cong_bao"),
            "ngay_het_hieu_luc": cls_info.get("ngay_het_hieu_luc"),
            "nguoi_ky": cls_info.get("nguoi_ky"),
            "co_quan_ban_hanh": cls_info.get("co_quan_ban_hanh"),
            "loai_van_ban": cls_info.get("loai_van_ban"),
        }
    
    def batch_prepare_nodes(
        self, 
        documents: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Prepare nodes from multiple documents in batch.
        
        Args:
            documents: List of MongoDB documents
            
        Returns:
            Tuple of (all_doc_params, all_term_params) aggregated from all documents
        """
        all_doc_params = []
        all_term_params = []
        
        for doc in documents:
            doc_params, term_params = self.prepare_nodes_from_document(doc)
            all_doc_params.extend(doc_params)
            all_term_params.extend(term_params)
        
        return all_doc_params, all_term_params
    
    def batch_prepare_relationships(
        self, 
        documents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Prepare BAO_GOM relationships from multiple documents in batch.
        
        Args:
            documents: List of MongoDB documents
            
        Returns:
            List of all relationship parameters aggregated from all documents
        """
        all_rel_params = []
        
        for doc in documents:
            rel_params = self.prepare_bao_gom_relationships(doc)
            all_rel_params.extend(rel_params)
        
        return all_rel_params
