"""Match deduplication and conflict-resolution methods for ``BaseExtractor``."""

from typing import Dict, List, Optional, Tuple

from src.domain.extractors.base_extractor_flow.models import PreparedReference
from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared


class MatchDeduplication:
    """Reference deduplication and conflicting-match filter methods."""

    @staticmethod
    def _get_reference_span_dedup_key(reference: PreparedReference) -> Tuple:
        """Return the stable span key used to deduplicate matched targets."""
        clause_identity = tuple(
            (
                component_key,
                component.get("information"),
                component.get("position_start"),
                component.get("position_end"),
            )
            for component_key, component in sorted(reference.reference.items())
            if (
                component_key in BaseExtractorShared.CLAUSE_COMPONENT_KEYS
                and isinstance(component, dict)
            )
        )
        return (
            reference.position_start,
            reference.position_end,
            reference.full_position_start,
            reference.full_position_end,
            clause_identity,
        )

    def _deduplicate_matched_references(
        self,
        matched_references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """Keep one matched target per full reference span."""
        deduped_references: List[PreparedReference] = []
        seen_reference_spans = set()

        for matched_reference in matched_references:
            dedup_key = self._get_reference_span_dedup_key(matched_reference)
            if dedup_key in seen_reference_spans:
                continue
            seen_reference_spans.add(dedup_key)
            deduped_references.append(matched_reference)

        return deduped_references

    def _strip_backward_clause_context_from_dan_chieu(
        self,
        relation_type: str,
        relation_start: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """
        For forward dan_chieu, do not attach an earlier internal clause list to
        a later external document cue.
        """
        if relation_type != "dan_chieu" or relation_start < 0:
            return matched_references

        normalized_references: List[PreparedReference] = []
        for reference in matched_references:
            has_backward_clause = any(
                key in self.CLAUSE_COMPONENT_KEYS
                and isinstance(value, dict)
                and value.get("position_start") is not None
                and value.get("position_start") < relation_start
                for key, value in reference.reference.items()
            )
            if not has_backward_clause:
                normalized_references.append(reference)
                continue

            forward_document_components = {
                key: value.copy()
                for key, value in reference.reference.items()
                if key not in self.CLAUSE_COMPONENT_KEYS
                and isinstance(value, dict)
                and value.get("position_start") is not None
                and value.get("position_end") is not None
                and value.get("position_start") >= relation_start
            }
            if not forward_document_components:
                normalized_references.append(reference)
                continue

            start = min(
                value["position_start"]
                for value in forward_document_components.values()
            )
            end = max(
                value["position_end"]
                for value in forward_document_components.values()
            )
            normalized_references.append(
                PreparedReference(
                    reference=forward_document_components,
                    position_start=start,
                    position_end=end,
                    full_position_start=start,
                    full_position_end=end,
                )
            )

        return normalized_references

    def _filter_conflicting_target_relations(self, matches: List[Dict]) -> List[Dict]:
        """
        Filter out relation matches for the same target reference based on:
        1. Local vs Inherited: Keep local relations if they exist.
        2. Relation Priority: Keep the highest priority relation type (e.g. 'thay_the' > 'dan_chieu').
        """
        if not matches:
            return []

        strong_action_relation_types_by_doc: Dict[str, set] = {}
        for match in matches:
            if (
                match.get("relation_type") not in self.STRONG_ACTION_TARGET_RELATION_TYPES
                or match.get("relation_type") in {"sua_doi_bo_sung", "sua_doi", "bo_sung"}
            ):
                continue
            identifier = self._extract_reference_document_identifier(match.get("reference", {}))
            if identifier:
                strong_action_relation_types_by_doc.setdefault(identifier, set()).add(
                    match.get("relation_type")
                )
        strong_action_doc_ids = set(strong_action_relation_types_by_doc)
        clause_scoped_action_doc_ids = {
            (
                match.get("relation_type"),
                identifier,
            )
            for match in matches
            if match.get("relation_type") in self.CLAUSE_SCOPED_SUPERSEDES_WHOLE_DOCUMENT_RELATION_TYPES
            and self._is_clause_scoped_reference(match.get("reference", {}))
            if (identifier := self._extract_reference_document_identifier(match.get("reference", {})))
        }
        if clause_scoped_action_doc_ids:
            clause_scoped_action_identifiers = {
                identifier
                for _, identifier in clause_scoped_action_doc_ids
            }
            matches = [
                match
                for match in matches
                if not (
                    match.get("relation_type") == "sua_doi_bo_sung"
                    and not match.get("_allow_with_clause_action")
                    and not self._is_clause_scoped_reference(match.get("reference", {}))
                    and self._extract_reference_document_identifier(
                        match.get("reference", {})
                    ) in clause_scoped_action_identifiers
                )
            ]
            if not matches:
                return []

            matches = [
                match
                for match in matches
                if not (
                    match.get("relation_type") in self.CLAUSE_SCOPED_SUPERSEDES_WHOLE_DOCUMENT_RELATION_TYPES
                    and not self._is_clause_scoped_reference(match.get("reference", {}))
                    and (
                        match.get("relation_type"),
                        self._extract_reference_document_identifier(match.get("reference", {})),
                    ) in clause_scoped_action_doc_ids
                )
            ]
            if not matches:
                return []

        if strong_action_doc_ids:
            matches = [
                match
                for match in matches
                if not (
                    match.get("relation_type") == "dan_chieu"
                    and (
                        identifier := self._extract_reference_document_identifier(
                            match.get("reference", {})
                        )
                    )
                    in strong_action_doc_ids
                    and strong_action_relation_types_by_doc.get(identifier)
                    != {"keo_dai_hieu_luc"}
                )
            ]
            if not matches:
                return []

        # Group matches by their target anchor plus full reference span.
        # Inherited document components can live in a parent clause and share
        # one full span across several local clause targets.
        by_target: Dict[Tuple[int, int, int, int], List[Dict]] = {}
        for m in matches:
            anchor_span = self._get_reference_anchor_span(m.get("reference", {}))
            if anchor_span is None:
                key = (
                    m["reference_position_start"],
                    m["reference_position_end"],
                    m["reference_position_start"],
                    m["reference_position_end"],
                )
            else:
                key = (
                    anchor_span["position_start"],
                    anchor_span["position_end"],
                    m["reference_position_start"],
                    m["reference_position_end"],
                )
            by_target.setdefault(key, []).append(m)

        filtered_results = []
        for target_matches in by_target.values():
            if len(target_matches) <= 1:
                filtered_results.extend(target_matches)
                continue

            # 1. Local vs Inherited Priority
            has_local = any(m["relation_position_start"] != -1 for m in target_matches)
            has_inherited = any(m["relation_position_start"] == -1 for m in target_matches)

            if has_local and has_inherited:
                # Keep only the local relations
                target_matches = [
                    m for m in target_matches
                    if m["relation_position_start"] != -1
                ]

            relation_types_for_target = {
                match["relation_type"]
                for match in target_matches
            }
            if {"keo_dai_hieu_luc", "dan_chieu"}.issubset(relation_types_for_target):
                filtered_results.extend(target_matches)
                continue

            # 2. Relation Type Priority (for multiple local relations or multiple inherited)
            if len(target_matches) > 1:
                # Find the maximum priority among the available matches
                max_priority = max(
                    self.RELATION_PRIORITY.get(m["relation_type"], 0)
                    for m in target_matches
                )
                # Keep only matches with that maximum priority level
                target_matches = [
                    m for m in target_matches
                    if self.RELATION_PRIORITY.get(m["relation_type"], 0) == max_priority
                ]

                # Special case: if multiple matches share same max priority (e.g. two separate 'thay_the' cues),
                # pick the one whose relation cue is closer to the reference.
                if len(target_matches) > 1:
                    ref_start = target_matches[0]["reference_position_start"]
                    ref_end = target_matches[0]["reference_position_end"]

                    def get_match_distance(m: Dict) -> int:
                        rel_start = m["relation_position_start"]
                        rel_end = m["relation_position_end"]
                        if rel_start == -1:
                            return 999999
                        if rel_end <= ref_start:
                            return ref_start - rel_end
                        if rel_start >= ref_end:
                            return rel_start - ref_end
                        return 0

                    target_matches.sort(key=get_match_distance)
                    target_matches = [target_matches[0]]

            filtered_results.extend(target_matches)

        # Re-sort to maintain document order based on relation position
        filtered_results.sort(
            key=lambda x: (x["relation_position_start"], x["relation_position_end"])
        )

        return filtered_results
