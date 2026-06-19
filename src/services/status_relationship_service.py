"""
Status Relationship Preparation Service.

Handles preparation and grouping of status relationships by type.
"""

import gzip
import json
import re
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime

from src.domain.model.relation_types import STATUS_RELATION_TYPES as _MODEL_STATUS_REL_TYPES
from src.infrastructure.logging import get_logger


class StatusRelationshipPreparationService:
    """
    Service for preparing status relationships from IE collection documents.
    
    Groups relationships by type for efficient bulk creation using
    bulk_create_multiple_relationships.
    """
    
    # All valid status relationship types (source of truth: src/domain/model/relation_types.py)
    STATUS_REL_TYPES = list(_MODEL_STATUS_REL_TYPES)

    CONFLICT_RELATION_GROUPS = [
        frozenset({"sua_doi_bo_sung", "sua_doi", "bo_sung"}),
        frozenset({"thay_the"}),
        frozenset({"bai_bo"}),
        frozenset({"huy_bo"}),
    ]
    
    def __init__(
        self,
        timestamp: str = None,
        logger=None,
        neo4j_repository=None,
        inserted_clause_lookup: Optional[Dict[Any, set]] = None,
        existing_clause_lookup: Optional[Dict[Any, set]] = None,
    ):
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
        self.inserted_clause_lookup = defaultdict(set)
        for doc_id, keys in (inserted_clause_lookup or {}).items():
            self.inserted_clause_lookup[doc_id].update(keys or [])
        self.existing_clause_lookup = defaultdict(set)
        for doc_id, keys in (existing_clause_lookup or {}).items():
            self.existing_clause_lookup[doc_id].update(keys or [])
        # Pre-build the static Cypher filter to avoid rebuilding on every delete call
        _filter = ' OR '.join([f'type(r) = "{rt}"' for rt in self.STATUS_REL_TYPES])
        self._delete_query_template = (
            f"CALL {{\n"
            f"    MATCH (source)-[r]->(target)\n"
            f"    WHERE (source.ID IN $doc_ids OR (source:DIEU_KHOAN AND split(toString(source.ID), '#')[-1] IN $doc_ids_str))\n"
            f"      AND ({_filter})\n"
            f"    DELETE r\n"
            f"    RETURN count(r) as deleted_count\n"
            f"}} IN TRANSACTIONS OF 1000 ROWS\n"
            f"RETURN sum(deleted_count) as total_deleted\n"
        )
    
    def delete_status_relationships_for_documents(
        self, 
        doc_ids: List[int],
        batch_size: int = 1000
    ) -> int:
        """
        Delete all status relationships for the given document IDs.
        This ensures clean updates when rebuilding relationships.
        
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
        
        self.logger.info(f"Deleting existing status relationships for {len(doc_ids):,} documents...")
        
        total_deleted = 0
        doc_ids_str = [str(did) for did in doc_ids]
        delete_query = self._delete_query_template

        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i+batch_size]
            batch_ids_str = doc_ids_str[i:i+batch_size]

            try:
                with self.neo4j_repository.driver.session(
                    database=self.neo4j_repository.database
                ) as session:
                    result = session.run(delete_query, doc_ids=batch_ids, doc_ids_str=batch_ids_str)
                    record = result.single()
                    batch_deleted = record['total_deleted'] if record else 0
                    total_deleted += batch_deleted
                    
                    if batch_deleted > 0:
                        self.logger.info(
                            f"  Batch {i//batch_size + 1}: Deleted {batch_deleted:,} relationships "
                            f"for {len(batch_ids):,} documents"
                        )
            
            except Exception as e:
                self.logger.error(f"Error deleting status relationships for batch {i//batch_size + 1}: {e}")
                continue
        
        self.logger.info(f"✅ Total status relationships deleted: {total_deleted:,}")
        return total_deleted
    
    def prepare_status_relationships_from_document(
        self, 
        doc: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract and group status relationships from a single document.
        
        The structure is:
        cls_graph: {
          success: [
            {
              source_key: null,
              source_type: "vanban",
              success: [
                {
                  relationship: "can_cu",
                  target_key: null,
                  target_doc_id: 22843
                },
                ...
              ]
            },
            ...
          ]
        }
        
        Args:
            doc: MongoDB document with cls_graph field
            
        Returns:
            Dictionary mapping relationship types to their parameters
            e.g., {'can_cu': [params], 'sua_doi_bo_sung': [params]}
        """
        try:
            cls_ID = doc.get('cls_ID')
            cls_graph = doc.get('cls_graph', {})
            outer_success_list = cls_graph.get('success', [])
            
            if not outer_success_list:
                return {}
            
            # Group relationships by type
            relationships_by_type = defaultdict(list)
            
            # Iterate through outer success array
            for outer_item in outer_success_list:
                source_key = outer_item.get('source_key')
                inner_success_list = outer_item.get('success', [])
                source_clause_data = self._extract_source_clause_data(doc, source_key)
                source_quoted_block = source_clause_data["quoted_block"]

                # Iterate through inner success array (actual relationships)
                for rel_info in inner_success_list:
                    relationship = rel_info.get('relationship')
                    target_doc_id = rel_info.get('target_doc_id')
                    target_key = rel_info.get('target_key')

                    # Validate required fields
                    if not relationship or not target_doc_id:
                        continue

                    # Only process valid relationship types
                    if relationship not in self.STATUS_REL_TYPES:
                        self.logger.warning(
                            f"Unknown relationship type '{relationship}' in doc {cls_ID}"
                        )
                        continue

                    # Determine node classes
                    head_class = 'DIEU_KHOAN' if source_key else 'VAN_BAN'
                    tail_class = 'DIEU_KHOAN' if target_key else 'VAN_BAN'

                    # Build head and tail IDs
                    head_ID = f"{source_key}#{cls_ID}" if source_key else cls_ID
                    tail_ID = f"{target_key}#{target_doc_id}" if target_key else target_doc_id

                    # Create relationship parameter
                    scope = 'clause' if source_key or target_key else 'document'
                    evidence = rel_info.get('description', '')
                    rel_param = {
                        'head_ID': head_ID,
                        'tail_ID': tail_ID,
                        'head_class': head_class,
                        'tail_class': tail_class,
                        'thoi_gian_cap_nhat': self.timestamp_value,
                        'nguon_cap_nhat': 'cmcai',
                    }

                    if relationship == 'bo_sung' and target_key:
                        self.inserted_clause_lookup[target_doc_id].add(target_key)

                    if relationship == 'bo_sung' and target_key and source_quoted_block:
                        rel_param['target_node_props'] = self._build_inserted_clause_props(
                            target_id=tail_ID,
                            target_key=target_key,
                            quoted_block=source_quoted_block,
                            source_cls_info=doc.get('cls_info'),
                        )

                    if relationship != 'bo_sung' and target_key:
                        synthetic_props = self._build_synthetic_descendant_props(
                            target_doc_id=target_doc_id,
                            target_key=target_key,
                            source_cls_info=doc.get('cls_info'),
                        )
                        if synthetic_props:
                            rel_param['target_node_props'] = synthetic_props

                    
                    # Add to appropriate group
                    relationships_by_type[relationship].append(rel_param)

                    if relationship == 'bo_sung' and target_key:
                        # Walk up all DIEU_KHOAN ancestors emitting bao_gom_sau_bo_sung at each
                        # level. Nested bo_sung targets also need the top inserted article linked
                        # from the amended VAN_BAN because that article is synthetic in the target
                        # document.
                        child_key = target_key
                        child_id = tail_ID
                        child_props = rel_param.get('target_node_props', {})
                        while child_key:
                            parent_key = self._parent_key_for_target_key(child_key)
                            head_id = f"{parent_key}#{target_doc_id}" if parent_key else target_doc_id
                            bgs_entry = {
                                'head_ID': head_id,
                                'tail_ID': child_id,
                                'head_class': 'DIEU_KHOAN' if parent_key else 'VAN_BAN',
                                'tail_class': 'DIEU_KHOAN',
                                'thoi_gian_cap_nhat': self.timestamp_value,
                                'nguon_cap_nhat': 'cmcai',
                                'target_node_props': child_props,
                            }
                            if parent_key:
                                bgs_entry['head_node_props'] = self._build_inserted_clause_props(
                                    target_id=head_id,
                                    target_key=parent_key,
                                    quoted_block='',
                                    source_cls_info=doc.get('cls_info'),
                                )
                            relationships_by_type['bao_gom_sau_bo_sung'].append(bgs_entry)
                            if parent_key is None:
                                break
                            child_key = parent_key
                            child_id = head_id
                            child_props = bgs_entry.get('head_node_props', {})
                    elif target_key and rel_param.get('target_node_props'):
                        self._append_synthetic_containment_edges(
                            relationships_by_type=relationships_by_type,
                            target_doc_id=target_doc_id,
                            target_key=target_key,
                            target_props=rel_param['target_node_props'],
                            source_cls_info=doc.get('cls_info'),
                        )
                    
                    # IMPORTANT: If DIEU_KHOAN -> VAN_BAN, also create parent VAN_BAN -> VAN_BAN
                    if source_key and not target_key:  # DIEU_KHOAN -> VAN_BAN
                        parent_rel_param = {
                            'head_ID': cls_ID,  # Parent VAN_BAN ID
                            'tail_ID': target_doc_id,  # Target VAN_BAN ID
                            'head_class': 'VAN_BAN',
                            'tail_class': 'VAN_BAN',
                            'thoi_gian_cap_nhat': self.timestamp_value,
                            'nguon_cap_nhat': 'cmcai',
                        }
                        relationships_by_type[relationship].append(parent_rel_param)
            
            relationships_by_type = self._filter_conflicting_document_action_relations(
                cls_graph=cls_graph,
                relationships_by_type=relationships_by_type,
            )

            # Deduplicate relationships (multiple DIEU_KHOAN may point to same VAN_BAN)
            deduplicated = {}
            for rel_type, rel_params in relationships_by_type.items():
                seen = set()
                unique_params = []
                for rel_param in rel_params:
                    key = (rel_param['head_ID'], rel_param['tail_ID'])
                    if key not in seen:
                        seen.add(key)
                        unique_params.append(rel_param)
                deduplicated[rel_type] = unique_params
            
            return deduplicated
            
        except Exception as e:
            self.logger.error(
                f"Error preparing status relationships for doc {doc.get('cls_ID')}: {e}"
            )
            return {}

    @classmethod
    def _conflict_priority(cls, relation_type: str) -> int:
        for idx, group in enumerate(cls.CONFLICT_RELATION_GROUPS):
            if relation_type in group:
                return idx
        return -1

    @classmethod
    def _inferred_action_priorities_by_target(cls, cls_graph: Dict[str, Any]) -> Dict[Any, int]:
        priorities: Dict[Any, int] = {}
        for group in cls_graph.get("inferred_relations", []) or []:
            relation_type = group.get("relation") or group.get("inferred_relation")
            priority = cls._conflict_priority(relation_type)
            if priority < 0:
                continue
            for item in group.get("collection", []) or []:
                target_doc_id = item.get("target_doc_id")
                if target_doc_id is None:
                    continue
                priorities[target_doc_id] = min(priorities.get(target_doc_id, priority), priority)
        return priorities

    @classmethod
    def _filter_conflicting_document_action_relations(
        cls,
        *,
        cls_graph: Dict[str, Any],
        relationships_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Keep one action-relation priority group per target VAN_BAN.

        The extraction contract allows dan_chieu to coexist, but forbids
        document-level action conflicts such as sua_doi_bo_sung + thay_the for
        the same source document and target document. Inferred document-level
        relations participate in the same priority rule because they are written
        to the same VAN_BAN -> VAN_BAN graph surface.
        """
        target_best_priority = cls._inferred_action_priorities_by_target(cls_graph)

        for rel_type, rel_params in relationships_by_type.items():
            priority = cls._conflict_priority(rel_type)
            if priority < 0:
                continue
            for rel_param in rel_params:
                if rel_param.get("tail_class") != "VAN_BAN":
                    continue
                target_doc_id = rel_param.get("tail_ID")
                if target_doc_id is None:
                    continue
                target_best_priority[target_doc_id] = min(
                    target_best_priority.get(target_doc_id, priority),
                    priority,
                )

        if not target_best_priority:
            return relationships_by_type

        filtered: Dict[str, List[Dict[str, Any]]] = {}
        for rel_type, rel_params in relationships_by_type.items():
            priority = cls._conflict_priority(rel_type)
            kept_params: List[Dict[str, Any]] = []
            for rel_param in rel_params:
                if priority < 0 or rel_param.get("tail_class") != "VAN_BAN":
                    kept_params.append(rel_param)
                    continue
                target_doc_id = rel_param.get("tail_ID")
                best_priority = target_best_priority.get(target_doc_id)
                if best_priority is None or priority <= best_priority:
                    kept_params.append(rel_param)
            if kept_params:
                filtered[rel_type] = kept_params
        return filtered

    def _extract_source_clause_data(
        self,
        doc: Dict[str, Any],
        source_key: Optional[str],
    ) -> Dict[str, Any]:
        """Extract quoted amendment block from the source clause in cls_parsing."""
        result: Dict[str, Any] = {"quoted_block": ""}
        if not source_key:
            return result
        for item in self._extract_parsing(doc.get('cls_parsing')):
            if item.get('com_key') != source_key:
                continue
            raw_content = item.get('com_title') or ""
            quoted_blocks = re.findall(r'["\u201c\u201d](.*?)["\u201c\u201d]', raw_content, flags=re.DOTALL)
            if quoted_blocks:
                result["quoted_block"] = max(
                    (block.strip() for block in quoted_blocks), key=len, default=""
                )
            return result
        return result

    @staticmethod
    def _extract_parsing(cls_parsing: Any) -> List[Dict[str, Any]]:
        if not cls_parsing:
            return []
        if isinstance(cls_parsing, list):
            return cls_parsing
        if isinstance(cls_parsing, dict) and cls_parsing.get('parsing'):
            try:
                return json.loads(gzip.decompress(cls_parsing['parsing']).decode('utf-8'))
            except Exception:
                return []
        return []

    @staticmethod
    def _parent_key_for_target_key(target_key: str) -> Optional[str]:
        parts = str(target_key).split('_')
        if not parts or parts[0] == 'dieu':
            return None
        return "_".join(parts[2:]) if len(parts) > 2 else None

    def update_inserted_clause_lookup(self, lookup: Dict[Any, set]) -> None:
        for doc_id, keys in (lookup or {}).items():
            self.inserted_clause_lookup[doc_id].update(keys or [])

    def update_existing_clause_lookup(self, lookup: Dict[Any, set]) -> None:
        for doc_id, keys in (lookup or {}).items():
            self.existing_clause_lookup[doc_id].update(keys or [])

    def _find_inserted_ancestor_key(self, target_doc_id: Any, target_key: str) -> Optional[str]:
        known_keys = self.inserted_clause_lookup.get(target_doc_id) or set()
        current_key = target_key
        while current_key:
            if current_key in known_keys:
                return current_key
            current_key = self._parent_key_for_target_key(current_key)
        return None

    def _find_existing_ancestor_key(self, target_doc_id: Any, target_key: str) -> Optional[str]:
        known_keys = self.existing_clause_lookup.get(target_doc_id) or set()
        current_key = target_key
        while current_key:
            if current_key in known_keys:
                return current_key
            current_key = self._parent_key_for_target_key(current_key)
        return None

    def _find_synthetic_anchor_key(self, target_doc_id: Any, target_key: str) -> Optional[str]:
        return (
            self._find_inserted_ancestor_key(target_doc_id, target_key)
            or self._find_existing_ancestor_key(target_doc_id, target_key)
        )

    def _build_synthetic_descendant_props(
        self,
        target_doc_id: Any,
        target_key: str,
        source_cls_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        inserted_ancestor_key = self._find_inserted_ancestor_key(target_doc_id, target_key)
        existing_ancestor_key = self._find_existing_ancestor_key(target_doc_id, target_key)
        anchor_key = inserted_ancestor_key or existing_ancestor_key
        if not anchor_key or anchor_key == target_key:
            return None
        return self._build_inserted_clause_props(
            target_id=f"{target_key}#{target_doc_id}",
            target_key=target_key,
            quoted_block='',
            source_cls_info=source_cls_info,
        )

    def _append_synthetic_containment_edges(
        self,
        *,
        relationships_by_type: Dict[str, List[Dict[str, Any]]],
        target_doc_id: Any,
        target_key: str,
        target_props: Dict[str, Any],
        source_cls_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        inserted_ancestor_key = self._find_inserted_ancestor_key(target_doc_id, target_key)
        existing_ancestor_key = self._find_existing_ancestor_key(target_doc_id, target_key)
        anchor_key = inserted_ancestor_key or existing_ancestor_key
        child_key = target_key
        child_id = f"{target_key}#{target_doc_id}"
        child_props = target_props
        while child_key:
            parent_key = self._parent_key_for_target_key(child_key)
            if parent_key is None:
                break
            head_id = f"{parent_key}#{target_doc_id}"
            bgs_entry = {
                'head_ID': head_id,
                'tail_ID': child_id,
                'head_class': 'DIEU_KHOAN',
                'tail_class': 'DIEU_KHOAN',
                'thoi_gian_cap_nhat': self.timestamp_value,
                'nguon_cap_nhat': 'cmcai',
                'target_node_props': child_props,
            }
            if parent_key != existing_ancestor_key:
                bgs_entry['head_node_props'] = self._build_inserted_clause_props(
                    target_id=head_id,
                    target_key=parent_key,
                    quoted_block='',
                    source_cls_info=source_cls_info,
                )
            relationships_by_type['bao_gom_sau_bo_sung'].append(bgs_entry)
            if parent_key == anchor_key:
                break
            child_key = parent_key
            child_id = head_id
            child_props = bgs_entry.get('head_node_props', {})

    _COMPONENT_LABELS = {"dieu": "Điều", "khoan": "Khoản", "diem": "Điểm"}

    @classmethod
    def _vi_tri_from_target_key(cls, target_key: str) -> str:
        """Build a human-readable position string from the target clause key.

        dieu_8a            → "Điều 8a"
        khoan_4_dieu_7     → "Khoản 4 / Điều 7"
        diem_c_khoan_2_dieu_18b → "Điểm c / Khoản 2 / Điều 18b"
        """
        parts = str(target_key).split('_')
        segments = []
        i = 0
        while i < len(parts) - 1:
            label = cls._COMPONENT_LABELS.get(parts[i])
            if label:
                segments.append(f"{label} {parts[i + 1]}")
                i += 2
            else:
                i += 1
        return " / ".join(segments)

    @classmethod
    def _vi_tri_chi_tiet_from_target_key(cls, target_key: str) -> str:
        """Build vi_tri_chi_tiet dict string from target_key.

        dieu_8a               → "{'dieu': 'Điều 8a.'}"
        khoan_4_dieu_7        → "{'khoan': '4.', 'dieu': 'Điều 7.'}"
        diem_c_khoan_2_dieu_18b → "{'diem': 'c.', 'khoan': '2.', 'dieu': 'Điều 18b.'}"
        """
        parts = str(target_key).split('_')
        d: Dict[str, str] = {}
        i = 0
        while i < len(parts) - 1:
            comp_type = parts[i]
            value = parts[i + 1]
            if comp_type in cls._COMPONENT_LABELS:
                if comp_type == 'dieu':
                    d['dieu'] = f'Điều {value}.'
                else:
                    d[comp_type] = f'{value}.'
                i += 2
            else:
                i += 1
        return str(d)

    def _build_inserted_clause_props(
        self,
        target_id: str,
        target_key: str,
        quoted_block: str,
        source_cls_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        component_type = str(target_key).split('_', 1)[0]
        vi_tri = self._vi_tri_from_target_key(target_key)
        props: Dict[str, Any] = {
            "ID": target_id,
            "cap_do": component_type,
            "noi_dung": quoted_block,
            "thoi_gian_cap_nhat": self.timestamp_value,
        }
        if vi_tri:
            props["vi_tri"] = vi_tri
            props["vi_tri_chi_tiet"] = self._vi_tri_chi_tiet_from_target_key(target_key)
        if source_cls_info:
            for key in (
                "ngay_ban_hanh",
                "ngay_co_hieu_luc",
                "ngay_dang_cong_bao",
                "co_quan_ban_hanh",
                "nguoi_ky",
                "loai_van_ban",
            ):
                value = source_cls_info.get(key)
                if value is not None:
                    props[key] = value
        return props
    
    def batch_prepare_status_relationships(
        self,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Prepare status relationships from multiple documents.
        
        Groups all relationships by type across all documents for efficient
        bulk creation.
        
        Args:
            documents: List of MongoDB documents
            
        Returns:
            Dictionary mapping relationship types to all their parameters
            e.g., {'bai_bo': [params1, params2], 'sua_doi_bo_sung': [params3]}
        """
        # Aggregate relationships by type across all documents
        all_relationships_by_type = defaultdict(list)
        
        for doc in documents:
            doc_relationships = self.prepare_status_relationships_from_document(doc)
            
            # Merge into aggregate dictionary
            for rel_type, rel_params in doc_relationships.items():
                all_relationships_by_type[rel_type].extend(rel_params)
        
        # Convert to regular dict and log statistics
        result = dict(all_relationships_by_type)
        
        if result:
            total_rels = sum(len(params) for params in result.values())
            self.logger.info(
                f"Prepared {total_rels} status relationships across {len(result)} types"
            )
            for rel_type, params in result.items():
                self.logger.debug(f"  {rel_type}: {len(params)} relationships")
        
        return result
    
    def merge_relationship_batches(
        self,
        *batches: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Merge multiple relationship batches by type.
        
        Useful when processing documents in sub-batches and need to aggregate.
        
        Args:
            *batches: Variable number of relationship dictionaries
            
        Returns:
            Merged dictionary with all relationships grouped by type
        """
        merged = defaultdict(list)
        
        for batch in batches:
            for rel_type, rel_params in batch.items():
                merged[rel_type].extend(rel_params)
        
        return dict(merged)
    
    def deduplicate_relationships(
        self,
        relationships_by_type: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Remove duplicate relationships within each type.
        
        Duplicates are identified by matching head_ID and tail_ID.
        
        Args:
            relationships_by_type: Dictionary of relationships by type
            
        Returns:
            Dictionary with duplicates removed
        """
        deduplicated = {}
        
        for rel_type, rel_params in relationships_by_type.items():
            # Use set to track unique (head_ID, tail_ID) pairs
            seen = set()
            unique_params = []
            
            for rel_param in rel_params:
                key = (rel_param['head_ID'], rel_param['tail_ID'])
                if key not in seen:
                    seen.add(key)
                    unique_params.append(rel_param)
            
            deduplicated[rel_type] = unique_params
            
            # Log if duplicates were found
            duplicates_removed = len(rel_params) - len(unique_params)
            if duplicates_removed > 0:
                self.logger.warning(
                    f"Removed {duplicates_removed} duplicate {rel_type} relationships"
                )
        
        return deduplicated
    
    def get_statistics(
        self,
        relationships_by_type: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, int]:
        """
        Get statistics about relationships.
        
        Args:
            relationships_by_type: Dictionary of relationships by type
            
        Returns:
            Dictionary with counts for each type plus total
        """
        stats = {}
        
        for rel_type, rel_params in relationships_by_type.items():
            stats[rel_type] = len(rel_params)
        
        stats['total'] = sum(stats.values())
        
        return stats
