from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.domain.graph import RelationEvent
from src.services.tvpl_relationship_service import TVPLRelationshipService


class GraphRelationSource:
    def collect_document_events(self, doc: Dict[str, Any]) -> List[RelationEvent]:
        cls_id = doc.get("cls_ID")
        if cls_id is None:
            return []

        events: List[RelationEvent] = []
        primary_keys: Set[Tuple[Any, Any, str, str]] = set()

        for event in self._collect_cls_graph_status_events(cls_id, doc.get("cls_graph", {})):
            events.append(event)
            primary_keys.add(self._semantic_key(event))

        for event in self._collect_cls_graph_inferred_events(cls_id, doc.get("cls_graph", {})):
            events.append(event)
            primary_keys.add(self._semantic_key(event))

        for event in self._collect_tvpl_events(cls_id, doc):
            if self._semantic_key(event) in primary_keys or self._conflicts_with_primary(event, primary_keys):
                continue
            events.append(event)

        return events

    def _collect_cls_graph_status_events(
        self,
        cls_id: int,
        cls_graph: Dict[str, Any],
    ) -> Iterable[RelationEvent]:
        for outer_item in cls_graph.get("success", []) or []:
            source_key = outer_item.get("source_key")
            for rel_info in outer_item.get("success", []) or []:
                relation = rel_info.get("relationship")
                target_doc_id = rel_info.get("target_doc_id")
                if not relation or target_doc_id is None:
                    continue
                scope = "clause" if source_key or rel_info.get("target_key") else "document"
                yield RelationEvent(
                    source_doc_id=cls_id,
                    target_doc_id=target_doc_id,
                    relation_type=relation,
                    source="cls_graph",
                    scope=scope,
                    evidence=rel_info.get("description", ""),
                    id_relations=self._status_id_relations(cls_id, source_key, rel_info),
                )

    def _collect_cls_graph_inferred_events(
        self,
        cls_id: int,
        cls_graph: Dict[str, Any],
    ) -> Iterable[RelationEvent]:
        for group in cls_graph.get("inferred_relations", []) or []:
            relation_type = group.get("relation") or group.get("inferred_relation")
            if not relation_type:
                continue
            for item in group.get("collection", []) or []:
                target_doc_id = item.get("target_doc_id")
                if target_doc_id is None:
                    continue
                yield RelationEvent(
                    source_doc_id=cls_id,
                    target_doc_id=target_doc_id,
                    relation_type=relation_type,
                    source="cls_graph",
                    scope="clause",
                    evidence=item.get("description", ""),
                    id_relations=item.get("id_relations", {}) or {},
                )

    def _collect_tvpl_events(self, cls_id: int, doc: Dict[str, Any]) -> Iterable[RelationEvent]:
        cls_luoc_do = doc.get("cls_luoc_do")
        if not cls_luoc_do:
            return

        for luoc_do_key, luoc_do_list in cls_luoc_do.items():
            relation_type = TVPLRelationshipService.RELATION_MAPPING.get(luoc_do_key)
            if not relation_type or not luoc_do_list:
                continue

            is_reversed = TVPLRelationshipService.REVERSED_RELATIONS.get(luoc_do_key, False)
            for item in luoc_do_list:
                if item.get("source", "") != "tvpl":
                    continue
                related_doc_id = item.get("id")
                if related_doc_id is None:
                    continue

                if is_reversed:
                    source_doc_id = int(related_doc_id)
                    target_doc_id = int(cls_id)
                else:
                    source_doc_id = int(cls_id)
                    target_doc_id = int(related_doc_id)

                yield RelationEvent(
                    source_doc_id=source_doc_id,
                    target_doc_id=target_doc_id,
                    relation_type=relation_type,
                    source="tvpl",
                    scope="document",
                    evidence=item.get("description", ""),
                    confidence=0.7,
                )

    @staticmethod
    def _status_id_relations(cls_id: int, source_key: Optional[str], rel_info: Dict[str, Any]) -> Dict[str, Any]:
        target_key = rel_info.get("target_key")
        target_doc_id = rel_info.get("target_doc_id")
        if target_doc_id is None or (not source_key and not target_key):
            return {}
        source_node_id = f"{source_key}#{cls_id}" if source_key else str(cls_id)
        target_node_id = f"{target_key}#{target_doc_id}" if target_key else str(target_doc_id)
        return {source_node_id: [target_node_id]}

    @staticmethod
    def _semantic_key(event: RelationEvent) -> Tuple[Any, Any, str, str]:
        return (
            event.source_doc_id,
            event.target_doc_id,
            event.relation_type,
            event.scope,
        )

    @staticmethod
    def _conflicts_with_primary(
        event: RelationEvent,
        primary_keys: Set[Tuple[Any, Any, str, str]],
    ) -> bool:
        if event.relation_type == "thay_the":
            conflicting_type = "bai_bo"
        elif event.relation_type == "bai_bo":
            conflicting_type = "thay_the"
        else:
            return False
        return (
            event.source_doc_id,
            event.target_doc_id,
            conflicting_type,
            event.scope,
        ) in primary_keys
