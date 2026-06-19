from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple

from src.domain.graph import RelationEvent


class GraphReconciliationService:
    def __init__(self, neo4j_repository):
        self.neo4j_repository = neo4j_repository

    def compare(self, doc_ids: List[int], expected_events: Iterable[RelationEvent]):
        expected_events = list(expected_events)
        if hasattr(self.neo4j_repository, "fetch_relationship_endpoint_keys_for_sources"):
            return self._compare_endpoints(doc_ids, expected_events)

        expected_keys = {
            self._document_key(event)
            for event in expected_events
            if event.target_doc_id is not None
        }
        actual_keys = set(self.neo4j_repository.fetch_relationship_keys_for_sources(doc_ids))

        return {
            "expected": len(expected_keys),
            "actual": len(actual_keys),
            "missing": sorted(expected_keys - actual_keys),
            "extra": sorted(actual_keys - expected_keys),
            "comparison_level": "document",
        }

    def _compare_endpoints(self, doc_ids: List[int], expected_events: Iterable[RelationEvent]):
        expected_details = self._build_expected_endpoint_details(expected_events)
        actual_details = [
            self._normalize_endpoint_detail(row, "actual")
            for row in self.neo4j_repository.fetch_relationship_endpoint_keys_for_sources(doc_ids)
        ]

        expected_by_key = {self._endpoint_key(detail): detail for detail in expected_details}
        actual_by_key = {self._endpoint_key(detail): detail for detail in actual_details}
        expected_keys = set(expected_by_key)
        actual_keys = set(actual_by_key)
        missing_keys = expected_keys - actual_keys
        extra_keys = actual_keys - expected_keys
        matched_keys = expected_keys & actual_keys

        return {
            "comparison_level": "endpoint",
            "expected": len(expected_keys),
            "actual": len(actual_keys),
            "matched": len(matched_keys),
            "missing": [expected_by_key[key] for key in sorted(missing_keys)],
            "extra": [actual_by_key[key] for key in sorted(extra_keys)],
            "summary": {
                "missing": len(missing_keys),
                "extra": len(extra_keys),
                "by_relation_type": self._count_by(expected_details, "relation_type"),
            },
            "canonicalized_expected_endpoints": sum(
                1
                for detail in expected_details
                if detail.get("target_original_node_id") or detail.get("source_original_node_id")
            ),
        }

    def _build_expected_endpoint_details(
        self,
        expected_events: Iterable[RelationEvent],
    ) -> List[Dict[str, Any]]:
        details = []
        for event in expected_events:
            if event.target_doc_id is None:
                continue
            if event.id_relations:
                details.extend(self._clause_endpoint_details(event))
            else:
                details.append(self._document_endpoint_detail(event))
        return self._canonicalize_expected_details(details)

    def _clause_endpoint_details(self, event: RelationEvent) -> List[Dict[str, Any]]:
        details = []
        for source_node_id, target_node_ids in event.id_relations.items():
            if not isinstance(target_node_ids, list):
                target_node_ids = [target_node_ids]
            for target_node_id in target_node_ids:
                details.append(
                    self._normalize_endpoint_detail(
                        {
                            "source": event.source,
                            "source_doc_id": self._doc_id_from_node_id(source_node_id, event.source_doc_id),
                            "source_node_id": source_node_id,
                            "target_doc_id": self._doc_id_from_node_id(target_node_id, event.target_doc_id),
                            "target_node_id": target_node_id,
                            "relation_type": event.relation_type,
                            "resolution_status": event.resolution_status,
                        },
                        "expected",
                    )
                )
        return details

    def _document_endpoint_detail(self, event: RelationEvent) -> Dict[str, Any]:
        return self._normalize_endpoint_detail(
            {
                "source": event.source,
                "source_doc_id": event.source_doc_id,
                "source_node_id": event.source_doc_id,
                "target_doc_id": event.target_doc_id,
                "target_node_id": event.target_doc_id,
                "relation_type": event.relation_type,
                "resolution_status": event.resolution_status,
            },
            "expected",
        )

    def _canonicalize_expected_details(self, details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        node_refs = []
        for detail in details:
            node_refs.append(self._node_ref(detail["source_node_id"]))
            node_refs.append(self._node_ref(detail["target_node_id"]))

        existing_refs = set()
        if hasattr(self.neo4j_repository, "fetch_existing_node_keys"):
            existing_refs = set(self.neo4j_repository.fetch_existing_node_keys(node_refs))

        missing_refs = [ref for ref in node_refs if ref not in existing_refs]
        variant_map = {}
        if hasattr(self.neo4j_repository, "fetch_dieu_khoan_variant_node_keys"):
            variant_map = self.neo4j_repository.fetch_dieu_khoan_variant_node_keys(missing_refs)

        canonicalized = []
        for detail in details:
            updated = dict(detail)
            source_ref = self._node_ref(updated["source_node_id"])
            target_ref = self._node_ref(updated["target_node_id"])
            if source_ref in variant_map:
                updated["source_original_node_id"] = updated["source_node_id"]
                updated["source_node_id"] = str(variant_map[source_ref][1])
            if target_ref in variant_map:
                updated["target_original_node_id"] = updated["target_node_id"]
                updated["target_node_id"] = str(variant_map[target_ref][1])
            canonicalized.append(updated)
        return canonicalized

    @staticmethod
    def _normalize_endpoint_detail(row: Dict[str, Any], origin: str) -> Dict[str, Any]:
        return {
            "source": row["source"],
            "source_doc_id": int(row["source_doc_id"]),
            "source_node_id": str(row["source_node_id"]),
            "target_doc_id": int(row["target_doc_id"]),
            "target_node_id": str(row["target_node_id"]),
            "relation_type": row["relation_type"],
            "origin": origin,
            **({"resolution_status": row["resolution_status"]} if row.get("resolution_status") else {}),
        }

    @staticmethod
    def _endpoint_key(detail: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            detail["source"],
            detail["source_doc_id"],
            detail["source_node_id"],
            detail["target_doc_id"],
            detail["target_node_id"],
            detail["relation_type"],
        )

    @staticmethod
    def _document_key(event: RelationEvent) -> Tuple[Any, ...]:
        return (
            event.source,
            event.source_doc_id,
            event.target_doc_id,
            event.relation_type,
        )

    @staticmethod
    def _doc_id_from_node_id(node_id: Any, fallback: int) -> int:
        node_id_str = str(node_id)
        if "#" in node_id_str:
            return int(node_id_str.rsplit("#", 1)[1])
        return int(fallback)

    @staticmethod
    def _node_ref(node_id: Any) -> Tuple[str, Any]:
        node_id_str = str(node_id)
        if "#" in node_id_str:
            return ("DIEU_KHOAN", node_id_str)
        return ("VAN_BAN", int(node_id))

    @staticmethod
    def _count_by(details: List[Dict[str, Any]], field: str) -> Dict[str, int]:
        return dict(Counter(detail[field] for detail in details))
