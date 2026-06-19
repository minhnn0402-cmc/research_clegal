from src.domain.graph import RelationEvent


class GraphTargetResolver:
    def __init__(self, neo4j_repository, mode: str = "strict"):
        if mode not in {"strict", "permissive"}:
            raise ValueError("mode must be 'strict' or 'permissive'")
        self.neo4j_repository = neo4j_repository
        self.mode = mode

    def resolve(self, event: RelationEvent) -> RelationEvent:
        if event.target_doc_id is None:
            return self._replace(event, None, "missing_target", "target_doc_id is empty")

        if self.neo4j_repository.verify_node_exists(event.target_doc_id, "VAN_BAN"):
            return self._replace(event, event.target_doc_id, "resolved", "")

        if self.mode == "permissive":
            return self._replace(
                event,
                event.target_doc_id,
                "skeleton_target",
                f"target node {event.target_doc_id} is missing; write skeleton relationship",
            )

        return self._replace(
            event,
            None,
            "missing_target",
            f"target node {event.target_doc_id} does not exist",
        )

    @staticmethod
    def _replace(event: RelationEvent, target_doc_id, status: str, reason: str) -> RelationEvent:
        return RelationEvent(
            source_doc_id=event.source_doc_id,
            target_doc_id=target_doc_id,
            relation_type=event.relation_type,
            source=event.source,
            scope=event.scope,
            evidence=event.evidence,
            id_relations=event.id_relations,
            confidence=event.confidence,
            resolution_status=status,
            resolution_reason=reason,
        )
