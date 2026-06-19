from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class RelationEvent:
    source_doc_id: int
    target_doc_id: Optional[int]
    relation_type: str
    source: str
    scope: str
    evidence: str = ""
    id_relations: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    resolution_status: str = "resolved"
    resolution_reason: str = ""

    def dedup_key(self) -> Tuple[str, int, Optional[int], str, str]:
        return (
            self.source,
            self.source_doc_id,
            self.target_doc_id,
            self.relation_type,
            self.scope,
        )

    def to_neo4j_props(self) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "nguon_cap_nhat": "cmcai",
        }
        if self.id_relations:
            props.update({
                "loai_quan_he": "gian_tiep",
                "mo_ta": self.evidence,
                "danh_sach_id_lien_quan": self.id_relations,
                "moi_quan_he_goc": [self.relation_type],
            })
        return props
