"""Reference normalization, validation, and scope-predicate helpers for ``BaseExtractor``."""

from typing import Dict, List, Optional, Tuple
import re

from src.domain.extractors.base_extractor_flow.shared import unidecode


LAW_LIKE_TYPES = {"luat", "boluat", "hienphap", "phaplenh"}

# If the primary document reference contains any of these phrases, it's likely a self-reference that should be ignored
SUBORDINATE_TRIGGER_PHRASES = [
    r"(?:được\s+)?sửa\s+đổi[,\s]+bổ\s+sung",
    r"quy\s+định\s+chi\s+tiết(?:\s+một\s+số\s+điều)?",
    r"quy\s+định\s+chi\s+tiết\s+và\s+hướng\s+dẫn\s+thi\s+hành",
    r"qui\s+định\s+chi\s+tiết\s+và\s+hướng\s+dẫn\s+thi\s+hành",
    r"quy\s+định\s+chi\s+tiết\s+và\s+ban\s+hành",
    r"quy\s+định\s+chi\s+tiết\s+thi\s+hành\s+một\s+số\s+điều",
    r"quy\s+định\s+chi\s+tiết\s+một\s+số\s+điều\s+và\s+biện\s+pháp\s+thi\s+hành",
    r"hướng\s+dẫn\s+thực\s+hiện\s+quy\s+định",
    r"hướng\s+dẫn\s+thi\s+hành",
    r"về\s+việc",
    r"quy\s+định\s+ngưng\s+hiệu\s+lực\s+thi\s+hành",
    r"bãi\s+bỏ[,\s]+bổ\s+sung\s+một\s+số",
    r"(?:được\s+)?sửa\s+đổi",
    r"(?:được\s+)?bổ\s+sung",
    r"bãi\s+bỏ",
    r"thay\s+thế",
    r"thi\s+hành\s*$",
    r"thi\s+hành\s+(?:luật|bộ\s+luật|nghị\s+quyết|nghị\s+định|thông\s+tư|quyết\s+định|pháp\s+lệnh)\b"
]

# Compile the subordinate trigger patterns into a single regex for efficient searching
SUBORDINATE_TRIGGER_PATTERN = re.compile(
    "|".join(f"(?:{p})" for p in SUBORDINATE_TRIGGER_PHRASES),
    re.IGNORECASE,
)

# Title swallowing (is_amending_continuation) should only happen for standard, non-descriptive connectors.
# A 'clean bridge' only contains action keywords, 'một số điều', and simple separators.
CLEAN_TITLE_CONTINUATION_PATTERN = re.compile(
    r"^\s*(?:sửa\s+đổi|bổ\s+sung|một\s+số\s+điều|của|các|[,\s])+\s*$",
    re.IGNORECASE
)

CLAUSE_SCOPED_DOC_PREFIX_PATTERN = re.compile(
    r"(?:^|[\s,;:])"
    r"(?:điểm|khoản|điều)\s+(?:\d+[A-Za-zĐđ]?|[A-Za-zĐđ])"
    r"(?:\s*,\s*(?:(?:điểm|khoản|điều)\s+)?(?:\d+[A-Za-zĐđ]?|[A-Za-zĐđ]))*"
    r"\s*$",
    re.IGNORECASE,
)

REPEAL_EFFECTIVE_CUE_PATTERN = re.compile(
    r"hết\s+hiệu\s+lực(?:\s+thi\s+hành)?",
    re.IGNORECASE,
)

GENERIC_OTHER_LAW_TAIL_PATTERN = re.compile(
    r"\s+và\s+(?:các\s+)?quy\s+định(?:\s+khác)?\s+của\s+pháp\s+luật"
    r"(?:\s+có\s+liên\s+quan)?\b.*$",
    re.IGNORECASE,
)
GENERIC_OTHER_LEGAL_DOCUMENT_TAIL_PATTERN = re.compile(
    r"\s+và\s+các\s+(?:luật|nghị\s+quyết|pháp\s+lệnh)\b"
    r".{0,260}\bcó\s+liên\s+quan\b.*$",
    re.IGNORECASE | re.DOTALL,
)
LAW_REFERENCE_QUALIFIER_TAIL_PATTERN = re.compile(
    r"(?:,\s*(?:có\s+xác\s+nhận|trừ\s+trường\s+hợp)\b"
    r"|:\s*"
    r"|\s+thì\b"
    r"|\s+như\s+sau\b"
    r"|\s+thực\s+hiện\s+(?:các\s+nội\s+dung|nội\s+dung|việc|theo\s+quy\s+định)\b)"
    r".*$",
    re.IGNORECASE,
)
AMENDMENT_HISTORY_PREFIX_PATTERN = re.compile(
    r"\b(?:đã\s+)?được\s+sửa\s+đổi\s*,?\s*bổ\s+sung\b"
    r".{0,220}\b(?:theo|bởi)\b",
    re.IGNORECASE | re.DOTALL,
)
AMENDED_CLAUSE_TARGET_PREFIX_PATTERN = re.compile(
    r"\b(?:đã\s+)?được\s+sửa\s+đổi(?:\s*,?\s*bổ\s+sung)?\s+tại\b",
    re.IGNORECASE | re.DOTALL,
)
DIRECT_ACTION_REFERENCE_BRIDGE_PATTERN = re.compile(
    r"(?:^|[,;]\s*)"
    r".{0,120}\b(?:đính\s+chính|bãi\s+bỏ|hủy\s+bỏ|đình\s+chỉ)\b"
    r".{0,120}\b(?:tại|của)\s*$",
    re.IGNORECASE | re.DOTALL,
)
ACTION_TARGET_CONTEXT_PATTERN = re.compile(
    r"\b(?:"
    r"ngưng\s+hiệu\s+lực|tạm\s+ngưng\s+hiệu\s+lực|"
    r"đình\s+chỉ|bãi\s+bỏ|hủy\s+bỏ|thay\s+thế|đính\s+chính|"
    r"sửa\s+đổi\s*,?\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung"
    r")\b",
    re.IGNORECASE,
)
ATTACHED_LIST_AMENDMENT_BRIDGE_PATTERN = re.compile(
    r"\b(?:sửa\s+đổi\s*,\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung)\b"
    r".{0,140}\bban\s+hành\s+kèm\s+theo\s*$",
    re.IGNORECASE | re.DOTALL,
)


class ReferenceNormalization:
    """Normalization, validation, and scope-predicate helpers for reference extraction."""

    @staticmethod
    def _build_doc_type_markers(doc_types: List[str]) -> List[str]:
        """Document-type markers are used to validate and enrich extracted references."""
        return [
            doc_type for doc_type in doc_types or []
        ]

    @staticmethod
    def _contains_doc_type_marker(text: str, doc_type_markers: List[str]) -> bool:
        """Return True when ``text`` contains any configured document-type marker."""
        normalized_text = unidecode(text or "").lower()
        return any(
            re.search(r"\b" + re.escape(marker) + r"\b", normalized_text)
            for marker in doc_type_markers
        )

    @staticmethod
    def _is_non_document_doc_type_context(scope_text: str, match_info: Dict) -> bool:
        """Filter document-type words that are part of organization names."""
        if match_info.get("doc_type_key") != "kehoach":
            return False

        suffix = scope_text[match_info["end"]:match_info["end"] + 40]
        return re.match(r"\s+va\s+dau\s+tu\b", unidecode(suffix or "").lower()) is not None

    @staticmethod
    def _has_clause_scoped_prefix(scope_text: str, local_start: int) -> bool:
        """Return True if the document mention is immediately scoped by clauses."""
        prefix_window = scope_text[max(0, local_start - 120):local_start]
        return CLAUSE_SCOPED_DOC_PREFIX_PATTERN.search(prefix_window) is not None

    @staticmethod
    def _has_repeal_effective_cue_after_doc(scope_text: str, local_start: int) -> bool:
        """Return True if a repeal/effective-date cue follows this document mention."""
        suffix_window = scope_text[local_start:local_start + 360]
        return REPEAL_EFFECTIVE_CUE_PATTERN.search(suffix_window) is not None

    @staticmethod
    def _is_conjoined_same_type_reference(
        scope_text: str,
        scope_start: int,
        previous_reference: Dict,
        doc_type_key: str,
        local_start: int,
    ) -> bool:
        """Keep same-type targets joined with 'và' after a descriptive title."""
        previous_doc = previous_reference.get(doc_type_key)
        if not isinstance(previous_doc, dict):
            return False

        previous_end = previous_doc.get("position_end")
        if previous_end is None:
            return False

        previous_end_local = previous_end - scope_start
        if previous_end_local < 0 or previous_end_local > local_start:
            return False

        bridge_text = scope_text[previous_end_local:local_start]
        if len(bridge_text) > 180:
            return False

        normalized_bridge = unidecode(bridge_text or "").lower()
        return re.search(r"\b(?:va|hoac|va/hoac)\s*$", normalized_bridge) is not None

    @staticmethod
    def _is_conjoined_action_target_reference(
        scope_text: str,
        scope_start: int,
        previous_reference: Dict,
        local_start: int,
    ) -> bool:
        """Keep explicit numbered documents joined to an action target list."""
        previous_doc = next(
            (value for value in previous_reference.values() if isinstance(value, dict)),
            None,
        )
        if previous_doc is None:
            return False

        previous_start = previous_doc.get("position_start")
        previous_end = previous_doc.get("position_end")
        if previous_start is None or previous_end is None:
            return False

        previous_start_local = previous_start - scope_start
        previous_end_local = previous_end - scope_start
        if previous_start_local < 0 or previous_end_local < 0 or previous_end_local > local_start:
            return False

        prefix_window = scope_text[max(0, previous_start_local - 140):previous_start_local]
        if ACTION_TARGET_CONTEXT_PATTERN.search(prefix_window) is None:
            return False

        bridge_text = scope_text[previous_end_local:local_start]
        if len(bridge_text) > 260:
            return False

        normalized_bridge = unidecode(bridge_text or "").lower()
        return re.search(r"\b(?:va|hoac|va/hoac)\s*$", normalized_bridge) is not None

    @staticmethod
    def _has_amendment_history_prefix(scope_text: str, local_start: int) -> bool:
        """Return True for amendment-history references after 'được sửa đổi ... theo'."""
        prefix_window = scope_text[max(0, local_start - 260):local_start]
        return AMENDMENT_HISTORY_PREFIX_PATTERN.search(prefix_window) is not None

    @staticmethod
    def _has_clause_scoped_amendment_target_prefix(scope_text: str, local_start: int) -> bool:
        """Return True when a clause-scoped reference is the amended target."""
        prefix_window = scope_text[max(0, local_start - 260):local_start]
        return AMENDED_CLAUSE_TARGET_PREFIX_PATTERN.search(prefix_window) is not None

    @staticmethod
    def _has_direct_action_reference_bridge(bridge_text: str) -> bool:
        """Return True when a skipped descriptive zone starts a new direct action target."""
        normalized_bridge = unidecode(bridge_text or "").lower()
        if re.search(r"\bve\s+viec\b", normalized_bridge):
            return False
        return (
            DIRECT_ACTION_REFERENCE_BRIDGE_PATTERN.search(bridge_text or "") is not None
            or ATTACHED_LIST_AMENDMENT_BRIDGE_PATTERN.search(bridge_text or "") is not None
        )

    @staticmethod
    def _is_list_item_document_reference(scope_text: str, local_start: int) -> bool:
        """Return True when a document reference starts a bullet/list item."""
        line_start = max(
            scope_text.rfind("\n", 0, local_start),
            scope_text.rfind("\r", 0, local_start),
        ) + 1
        line_prefix = scope_text[line_start:local_start]
        return re.match(r"^\s*(?:[-–•]|\(?[a-zđ]\)|\d+[\).])\s*$", line_prefix, re.IGNORECASE) is not None

    @staticmethod
    def _dedup_reference_key(reference: Dict) -> Tuple[Tuple[str, Optional[int], Optional[int]], ...]:
        """Build a stable deduplication key for one normalized reference payload."""
        return tuple(
            (
                key,
                value.get("position_start"),
                value.get("position_end"),
            )
            for key, value in reference.items()
            if isinstance(value, dict)
        )

    def _filter_self_reference_doc_types(
        self,
        scope_text: str,
        doc_type_matches: List[Dict]
    ) -> List[Dict]:
        """
        Filter out doc_type matches that are self-references.
        E.g., "Thông tư này" should be removed, but "Thông tư số 10/2023/TT-BTC" should stay.
        """
        filtered_matches = []
        for match_info in doc_type_matches:
            match_end = match_info["end"]
            # Look ahead after the doc_type token for "này" pattern
            lookahead = scope_text[match_end:match_end + 5]  # Look ahead a bit
            # Check if immediately followed by whitespace and "này"
            if re.match(r"^\s+này\b", lookahead, re.IGNORECASE):
                # This is a self-reference like "Thông tư này", skip it
                continue
            filtered_matches.append(match_info)
        return filtered_matches

    def _is_self_document_reference(self, reference: Dict) -> bool:
        """Drop self-references such as 'Luật này' that should not become tails."""
        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return False

        _, doc_info = primary_document
        information = doc_info.get("information", "")
        if not information:
            return False

        normalized_information = unidecode(information).lower().strip()
        return self.SELF_DOCUMENT_REFERENCE_PATTERN.match(normalized_information) is not None

    def _is_valid_reference(self, reference: Dict, doc_types: List[str]) -> bool:
        """
        Validate whether the document reference is valid.
        References containing 'sửa đổi, bổ sung' are only valid if followed by
        a valid document type (Luật, Nghị định, Thông tư, etc.).
        """
        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return True

        _, doc_info = primary_document
        information = doc_info.get("information", "")
        if not information:
            return True

        normalized_information = unidecode(information).lower().strip()
        if re.search(r"\bthi$", normalized_information):
            return False

        patch_pattern = r"sửa\s+đổi(?:,\s*bổ\s+sung|\s+bổ\s+sung)?"
        match = re.search(patch_pattern, information)

        if match:
            # Check the segment after "sửa đổi, bổ sung"
            after_patch = information[match.end():].strip()
            if not after_patch:
                return False

            # They are valid if after "sửa đổi, bổ sung" a document type follows.
            # We check if any of the doc_types markers appear in the text *after* the patch phrase.
            for dt in doc_types:
                if dt in after_patch:
                    return True
            return False

        return True

    @staticmethod
    def _truncate_scope_before_cutoff(scope: Dict, cutoff_pos: Optional[int]) -> Optional[Dict]:
        """Truncate a sentence scope at the provided global cutoff position."""
        if cutoff_pos is None:
            return scope

        scope_start = scope["start_pos"]
        relative_cutoff = max(0, cutoff_pos - scope_start)
        truncated_text = scope["text"][:relative_cutoff].rstrip()
        if not truncated_text:
            return None

        return {
            "text": truncated_text,
            "start_pos": scope_start,
            "end_pos": scope_start + len(truncated_text),
        }

    @staticmethod
    def _apply_scope_exclusion_rules(
        doc_references: List[Dict],
        cutoff_pos: Optional[int]
    ) -> List[Dict]:
        """Keep only document references that start before the exclusion cutoff."""
        if cutoff_pos is None:
            return doc_references

        filtered_references: List[Dict] = []
        for reference in doc_references:
            first_key = next(iter(reference))
            ref_info = reference[first_key]
            if ref_info.get("position_start", 0) < cutoff_pos:
                filtered_references.append(reference)

        return filtered_references

    def _find_subordinate_cutoff(self, text: str) -> Optional[int]:
        """
        Return the start position of the first subordinate trigger phrase in the text,
        or None if none is found.
        """
        m = SUBORDINATE_TRIGGER_PATTERN.search(text)
        return m.start() if m else None

    def _is_valid_primary(
        self,
        doc_type_key: str,
        document_number_match,           # re.Match | None
        title_match: Optional[Tuple[int, int, str]]
    ) -> bool:
        """
        A valid primary document reference must contain enough information:
        - law_like -> must have title (document number is optional)
        - other types -> must have document number (title is not applicable)
        """
        if doc_type_key in LAW_LIKE_TYPES:
            return document_number_match is not None or title_match is not None

        return document_number_match is not None

    @staticmethod
    def _trim_generic_other_law_tail(information: str) -> str:
        """Remove generic legal-reference tails from an otherwise concrete law title."""
        trimmed = GENERIC_OTHER_LAW_TAIL_PATTERN.sub("", information or "")
        trimmed = GENERIC_OTHER_LEGAL_DOCUMENT_TAIL_PATTERN.sub("", trimmed)
        trimmed = LAW_REFERENCE_QUALIFIER_TAIL_PATTERN.sub("", trimmed)
        return trimmed.strip(" ,")

    @staticmethod
    def _reference_start(reference: Dict) -> int:
        starts = [
            value.get("position_start")
            for value in reference.values()
            if isinstance(value, dict) and value.get("position_start") is not None
        ]
        return min(starts) if starts else 0
