"""Typed domain models used internally by the extractor flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PreparedReference:
    """Normalized reference candidate used during relation/reference matching."""

    reference: Dict
    position_start: int
    position_end: int
    full_position_start: int
    full_position_end: int


@dataclass(frozen=True)
class RelationCue:
    """Normalized relation cue span used during matching."""

    relation_type: str
    position_start: int
    position_end: int

    @classmethod
    def from_payload(cls, relation: Dict) -> Optional["RelationCue"]:
        """Build a normalized cue from synthetic relation payloads."""
        relation_type = relation.get("relation_type", relation.get("key"))
        relation_start = relation.get("position_start", relation.get("start_pos"))
        relation_end = relation.get("position_end", relation.get("end_pos"))

        if relation_type is None or relation_start is None or relation_end is None:
            return None

        return cls(
            relation_type=relation_type,
            position_start=relation_start,
            position_end=relation_end,
        )


@dataclass(frozen=True)
class ClauseContext:
    """Clause-level context shared across reference extraction steps."""

    sentence_scopes: List[Dict]
    is_can_cu_content: bool
    doc_type_markers: List[str]
    ancestor_context: Dict
    ancestor_doc_reference: Optional[Dict]
    ancestor_doc_references: List[Dict]


@dataclass(frozen=True)
class ReferenceMention:
    """Collected reference payload with stable dedup and sort metadata."""

    reference: Dict
    dedup_key: Tuple[Tuple[str, Optional[int], Optional[int]], ...]
    position_start: int

    @classmethod
    def from_reference(cls, reference: Dict) -> "ReferenceMention":
        """Build a normalized mention wrapper from one extracted reference payload."""
        positions = [
            int(value.get("position_start", 0))
            for value in reference.values()
            if isinstance(value, dict)
        ]
        return cls(
            reference=reference,
            dedup_key=tuple(
                (
                    key,
                    value.get("position_start"),
                    value.get("position_end"),
                )
                for key, value in reference.items()
                if isinstance(value, dict)
            ),
            position_start=min(positions) if positions else 0,
        )


@dataclass(frozen=True)
class ReferenceSpan:
    """Sortable anchor span extracted from a reference payload."""

    start: int
    end: int


@dataclass(frozen=True)
class RelationCandidate:
    """Validated relation hint candidate before final overlap resolution."""

    relation_type: str
    hint_group: str
    position_start: int
    position_end: int

    def to_public_match(self) -> Dict:
        """Return the public direct-match payload expected by downstream stages."""
        return {
            "relation_type": self.relation_type,
            "position_start": self.position_start,
            "position_end": self.position_end,
        }
