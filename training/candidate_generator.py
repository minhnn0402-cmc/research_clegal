"""Generate candidate-level training records from the production rule engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from evaluation.converter import tail_to_reference
from evaluation.evaluate import _build_clause_context, infer_document_type
from evaluation.matcher import references_match
from experiment.clause_dataset import ClauseUnit
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader

from training.common import relation_compatible, stable_id


_DOC_NUMBER_PATTERN = re.compile(
    r"\b\d{1,5}[A-Za-zĐđ]?[/\-]\d{4}[/\-][A-Za-zĐđ0-9./\-]+\b"
    r"|\b\d{1,5}[A-Za-zĐđ]?[/\-][A-Za-zĐđ][A-Za-zĐđ0-9./\-]+\b",
    re.IGNORECASE,
)
_HARD_DELIMITERS = frozenset({".", ";", "\n"})
_SOFT_DELIMITERS = frozenset({",", ":", "(", ")"})


@dataclass(frozen=True)
class Candidate:
    relation: Dict[str, Any]
    reference: Dict[str, Any]
    source: str


class CandidateGenerator:
    """Build scoped rule candidates without changing production code."""

    def __init__(self, top_k_near_miss: int = 2) -> None:
        config = ConfigLoader()
        self.config = config
        self.top_k_near_miss = max(0, top_k_near_miss)
        self.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    @staticmethod
    def _span(reference: Dict[str, Any]) -> Tuple[int, int]:
        spans = [
            (
                int(value.get("position_start", 0)),
                int(value.get("position_end", 0)),
            )
            for value in reference.values()
            if isinstance(value, dict)
            and value.get("position_start") is not None
            and value.get("position_end") is not None
        ]
        if not spans:
            return (0, 0)
        return min(start for start, _ in spans), max(end for _, end in spans)

    @staticmethod
    def _reference_key(reference: Dict[str, Any]) -> tuple:
        return tuple(
            (
                key,
                " ".join(str(value.get("information", "")).lower().split()),
            )
            for key, value in sorted(reference.items())
            if isinstance(value, dict)
        )

    @staticmethod
    def _relation_span(relation: Dict[str, Any]) -> Tuple[int, int]:
        return (
            int(relation.get("position_start", -1)),
            int(relation.get("position_end", -1)),
        )

    @classmethod
    def _distance(cls, relation: Dict[str, Any], reference: Dict[str, Any]) -> int:
        action_start, action_end = cls._relation_span(relation)
        ref_start, ref_end = cls._span(reference)
        if action_start < 0:
            return 0
        if action_end <= ref_start:
            return ref_start - action_end
        if ref_end <= action_start:
            return action_start - ref_end
        return 0

    def _scoped_candidates(
        self,
        relation_types: Sequence[Dict[str, Any]],
        references: Sequence[Dict[str, Any]],
        production_matches: Sequence[Dict[str, Any]],
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        seen = set()

        for match in production_matches:
            relation = {
                "relation_type": match.get("relation_type"),
                "position_start": match.get("relation_position_start", -1),
                "position_end": match.get("relation_position_end", -1),
                "text": "",
                "direction": "MATCHED",
                "hint_group": "production_match",
            }
            reference = match.get("reference") or {}
            key = (relation["relation_type"], self._reference_key(reference))
            if key not in seen:
                seen.add(key)
                candidates.append(Candidate(relation, reference, "production_match"))

        if self.top_k_near_miss <= 0:
            return candidates

        for relation in relation_types:
            relation_type = relation.get("relation_type")
            ranked = sorted(
                references,
                key=lambda ref: (
                    self._distance(relation, ref),
                    self._span(ref)[0],
                ),
            )
            for reference in ranked[: self.top_k_near_miss]:
                key = (relation_type, self._reference_key(reference))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(Candidate(relation, reference, "scoped_near_miss"))

        return candidates

    def generate(
        self,
        unit: ClauseUnit,
        *,
        assume_exhaustive: bool = False,
        hard_negative: bool = False,
    ) -> List[Dict[str, Any]]:
        data, child_to_parent, clause = _build_clause_context(
            clause_type=unit.clause_type,
            content=unit.content,
            parent_content=unit.parent_content,
            grandparent_content=unit.grandparent_content,
            idx=unit.row_index,
        )
        base = self.extractor.base_extractor
        references = base.extract_references(
            content=unit.content,
            doc_types=self.extractor.doc_types,
            clause_types=self.extractor.clause_types,
            law_titles=self.config.law_titles_for_regex,
            clause_type=unit.clause_type,
            clause_key=clause.get("com_key"),
            data=data,
            child_to_parent=child_to_parent,
            cls_title=unit.title,
        )
        relation_types = base.extract_relation_types(
            content=unit.content,
            references=references,
            parent_content=unit.parent_content,
            grandparent_content=unit.grandparent_content,
            clause_type=unit.clause_type,
        )
        production_matches = (
            base.match_relations(
                references=references,
                relation_types=relation_types,
                content=unit.content,
                source_so_hieu=unit.so_hieu,
                source_title=unit.title,
            )
            if references and relation_types
            else []
        )

        records = []
        for candidate in self._scoped_candidates(
            relation_types,
            references,
            production_matches,
        ):
            record = self._to_record(
                unit=unit,
                candidate=candidate,
                action_count=len(relation_types),
                reference_count=len(references),
                assume_exhaustive=assume_exhaustive,
                hard_negative=hard_negative,
            )
            if record is not None:
                records.append(record)
        return records

    def _to_record(
        self,
        *,
        unit: ClauseUnit,
        candidate: Candidate,
        action_count: int,
        reference_count: int,
        assume_exhaustive: bool,
        hard_negative: bool,
    ) -> Optional[Dict[str, Any]]:
        relation_type = str(candidate.relation.get("relation_type") or "")
        reference_text = tail_to_reference(candidate.reference) or ""
        if not relation_type or not reference_text:
            return None

        action_start, action_end = self._relation_span(candidate.relation)
        ref_start, ref_end = self._span(candidate.reference)
        between_start = min(max(action_end, 0), ref_end)
        between_end = max(min(ref_start, len(unit.content)), max(action_start, 0))
        between = unit.content[between_start:between_end] if between_end > between_start else ""
        direction = str(candidate.relation.get("direction") or "FORWARD")
        context_source = "ancestor" if action_start < 0 else "current"

        matched_gold = None
        for gold in unit.ground_truth:
            if not relation_compatible(gold.get("relation", ""), relation_type):
                continue
            if references_match(gold.get("reference", ""), reference_text):
                matched_gold = gold
                break

        if matched_gold is not None:
            label = "VALID"
        elif hard_negative or candidate.source == "production_match" or assume_exhaustive:
            label = "INVALID"
        else:
            label = "UNKNOWN"

        reference_keys = set(candidate.reference)
        has_clause_component = bool(reference_keys & {"dieu", "khoan", "diem"})
        has_external_document = bool(reference_keys - {"dieu", "khoan", "diem"})
        char_distance = self._distance(candidate.relation, candidate.reference)
        action_text = (
            candidate.relation.get("text")
            or candidate.relation.get("relation_value")
            or (
                unit.content[action_start:action_end]
                if 0 <= action_start < action_end <= len(unit.content)
                else ""
            )
        )

        features: Dict[str, Any] = {
            "proposed_relation": relation_type,
            "candidate_source": candidate.source,
            "rule_hint_group": str(candidate.relation.get("hint_group") or ""),
            "direction": direction,
            "context_source": context_source,
            "clause_type": unit.clause_type,
            "action_before_reference": action_start < 0 or action_end <= ref_start,
            "spans_overlap": action_start >= 0 and not (action_end <= ref_start or ref_end <= action_start),
            "char_distance": char_distance,
            "hard_delimiter_count": sum(char in _HARD_DELIMITERS for char in between),
            "soft_delimiter_count": sum(char in _SOFT_DELIMITERS for char in between),
            "same_hard_scope": not any(char in _HARD_DELIMITERS for char in between),
            "action_count": action_count,
            "reference_count": reference_count,
            "reference_component_count": len(reference_keys),
            "has_clause_component": has_clause_component,
            "has_external_document": has_external_document,
            "has_document_number": bool(_DOC_NUMBER_PATTERN.search(reference_text)),
            "is_inherited": action_start < 0,
            "content_length": len(unit.content),
            "parent_length": len(unit.parent_content),
            "grandparent_length": len(unit.grandparent_content),
            "is_production_match": candidate.source == "production_match",
        }

        return {
            "candidate_id": stable_id(
                unit.so_hieu,
                unit.clause_type,
                unit.content,
                relation_type,
                reference_text,
                candidate.source,
                prefix="cand_",
            ),
            "so_hieu": unit.so_hieu,
            "title": unit.title,
            "clause_type": unit.clause_type,
            "content": unit.content,
            "parent_content": unit.parent_content,
            "grandparent_content": unit.grandparent_content,
            "action_text": str(action_text),
            "action_span": [action_start, action_end],
            "reference_text": reference_text,
            "reference_span": [ref_start, ref_end],
            "reference_payload": candidate.reference,
            "proposed_relation": relation_type,
            "candidate_source": candidate.source,
            "features": features,
            "label": label,
            "matched_gold": matched_gold,
        }


def candidate_covers_gold(record: Dict[str, Any], gold: Dict[str, str]) -> bool:
    return relation_compatible(gold.get("relation", ""), record.get("proposed_relation", "")) and references_match(
        gold.get("reference", ""),
        record.get("reference_text", ""),
    )


def coverage_summary(units: Iterable[ClauseUnit], records_by_clause: Dict[tuple, List[Dict]]) -> Dict[str, Any]:
    total = 0
    covered = 0
    by_relation: Dict[str, Dict[str, int]] = {}
    for unit in units:
        records = records_by_clause.get(unit.key, [])
        for gold in unit.ground_truth:
            total += 1
            relation = gold.get("relation", "")
            bucket = by_relation.setdefault(relation, {"total": 0, "covered": 0})
            bucket["total"] += 1
            is_covered = any(candidate_covers_gold(record, gold) for record in records)
            if is_covered:
                covered += 1
                bucket["covered"] += 1
    for bucket in by_relation.values():
        bucket["recall_ceiling"] = (
            bucket["covered"] / bucket["total"] if bucket["total"] else 0.0
        )
    return {
        "total_gold": total,
        "covered_gold": covered,
        "candidate_recall_ceiling": covered / total if total else 0.0,
        "by_relation": by_relation,
    }

