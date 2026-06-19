import re
from typing import Dict, List, Optional

from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared, unidecode
from src.domain.extractors.relation_type_rules import SCOPE_DELIMITERS

_IMMEDIATE_CONTEXT_LENGTH: int = 15
_DAN_CHIEU_SCOPE_HEADING_PATTERN = re.compile(
    r"(?:^|[\r\n])\s*(?:phạm\s+vi\s+điều\s+chỉnh|đối\s+tượng\s+áp\s+dụng)\b",
    re.IGNORECASE,
)
_DAN_CHIEU_CORRECTION_SCOPE_PATTERN = re.compile(
    r"\bđính\s+chính\b",
    re.IGNORECASE,
)
_DAN_CHIEU_CORRECTION_ACTION_PATTERN = re.compile(
    r"\b(?:được\s+)?sửa\s+(?:đổi\s*,\s*)?thành\b",
    re.IGNORECASE,
)
_DAN_CHIEU_INTERNAL_OBJECT_SCOPE_PATTERN = re.compile(
    r"\bcủa\s+(?:nghị\s+định|thông\s+tư|luật)\s+này\s+áp\s+dụng\s+đối\s+với\s+đối\s+tượng\s+áp\s+dụng\b",
    re.IGNORECASE,
)
# SHARED — also used directly in extract_relation_types()
_DAN_CHIEU_PHRASE_AMENDMENT_SCOPE_PATTERN = re.compile(
    r"\b(?:bỏ|bãi\s+bỏ|thay|thay\s+thế)\s+(?:các\s+)?cụm\s+từ\b",
    re.IGNORECASE,
)
# SHARED — also used directly in extract_relation_types()
_AMENDMENT_REPLACEMENT_DETAIL_PREFIX_PATTERN = re.compile(
    r"\b(?:sửa\s+đổi\s*,\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung|thay\s+thế)\b"
    r".{0,220}\bnhư\s+sau\s*:\s*"
    r"(?:[\r\n\s]*[“\"']?\s*(?:\d+[\).]\s*)?)?$",
    re.IGNORECASE | re.DOTALL,
)
_AMENDMENT_REPLACEMENT_INTRO_PATTERN = re.compile(
    r"\b(?:sửa\s+đổi\s*,\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung|thay\s+thế)\b"
    r".{0,260}\bnhư\s+sau\s*:",
    re.IGNORECASE | re.DOTALL,
)
_FOLLOWING_LIST_MARKER_PATTERN = re.compile(
    r"^\s*:\s*(?:\r?\n\s*)?(?:[a-zđ]\)|\d+[\).])",
    re.IGNORECASE,
)
# SHARED — also used directly in extract_relation_types()
_POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES = {
    "bai_bo",
    "huy_bo",
    "sua_doi_bo_sung",
    "thay_the",
    "dinh_chi",
    "ngung_hieu_luc",
}
_POST_INTRO_DOCUMENT_ACTION_TARGET_PATTERN = re.compile(
    r"^\s*(?:điểm|khoản|điều)\b",
    re.IGNORECASE,
)
_FORWARD_LIST_HEADING_PATTERN = re.compile(
    r"^\s*(?:các\s+)?(?:văn\s+bản|quyết\s+định|nghị\s+quyết|nghị\s+định|"
    r"thông\s+tư|chỉ\s+thị|công\s+văn)\s+(?:sau|sau\s+đây)\s*:"
    r"\s*(?:\r?\n\s*)?(?:[-–•]|\(?[a-zđ]\)|\d+[\).])",
    re.IGNORECASE,
)
_KEO_DAI_TIME_CUE_PATTERN = re.compile(
    r"\bkéo\s+dài\s+thời\s+(?:gian|hạn)\b",
    re.IGNORECASE,
)
_KEO_DAI_INDIRECT_BASIS_MARKER_PATTERN = re.compile(
    r"\btheo\b",
    re.IGNORECASE,
)
_DETAIL_PARENT_WITH_IMPLEMENTING_DECREE_PATTERN = re.compile(
    r"\bquy\s+định\s+chi\s+tiết\b.*\bnghị\s+định\s+số\b.*\bbao\s+gồm\s*:\s*$",
    re.IGNORECASE | re.DOTALL,
)
# SHARED — also used directly in extract_relation_types()
_THEO_QUY_DINH_TAI_CLAUSE_PATTERN = re.compile(
    r"\btheo\s+quy\s+định\s+tại\s+(?:điểm|khoản|điều)\b",
    re.IGNORECASE,
)
# SHARED — also used directly in extract_relation_types()
_THEO_QUY_DINH_TAI_MARKER_PATTERN = re.compile(
    r"\btheo\s+quy\s+định\s+(?:tại|của)\b",
    re.IGNORECASE,
)
_OPERATIONAL_ACTION_OBJECT_PATTERN = re.compile(
    r"\b(?:hủy\s+bỏ\s+công\s+nhận|thu\s+hồi\s+thẻ|đính\s+chính\s+giấy\s+chứng\s+nhận)\b",
    re.IGNORECASE,
)
_PARENT_APPENDIX_AMENDMENT_CONTEXT_PATTERN = re.compile(
    r"\bsua\s+doi\s*,?\s*bo\s+sung\b.{0,260}"
    r"\b(?:phu\s+luc|danh\s+muc|mau|bieu\s+mau)\b.{0,220}\bkem\s+theo\b",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_DESCRIPTIVE_DAN_CHIEU_PATTERN = re.compile(
    r"\b(?:huong\s+dan|quy\s+dinh|thi\s+hanh)\b.{0,220}"
    r"\btai\s+(?:nghi\s+dinh|nghi\s+quyet|luat|thong\s+tu|quyet\s+dinh)\b",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_ACTION_PREFIX_PATTERN = re.compile(
    r"\b(?:bai\s+bo|sua\s+doi|bo\s+sung|thay\s+the|huy\s+bo)\b",
    re.IGNORECASE,
)
_POST_ACTION_ASSIGNMENT_BASIS_PATTERN = re.compile(
    r"\b(?:giao|phan\s+cong|uy\s+quyen)\b.{0,220}"
    r"\b(?:can\s+cu|theo|theo\s+dung)(?:\s+(?:quy\s+dinh\s+)?tai)?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# SHARED — also used directly in extract_relation_types()
_CHILD_SCOPE_QUY_DINH_VE_PATTERN = re.compile(
    r"^\s*\d+\.\s*quy\s+định\s+về\b",
    re.IGNORECASE,
)
_DE_NGHI_TAI_CONG_VAN_SCOPE_PATTERN = re.compile(
    r"\btrên\s+cơ\s+sở\s+đề\s+nghị\b",
    re.IGNORECASE,
)
_TAI_CONG_VAN_RELATION_PATTERN = re.compile(
    r"^\s*tại\s+công\s+văn\b",
    re.IGNORECASE,
)
_EXCEPTION_SELF_DOCUMENT_SCOPE_PATTERN = re.compile(
    r"\btrừ\s+trường\s+hợp\b",
    re.IGNORECASE,
)
# SHARED — also used directly in extract_relation_types()
_DAN_CHIEU_BACKWARD_EFFECTIVE_CUE_PATTERN = re.compile(
    r"\btiếp\s+tục\s+có\s+hiệu\s+lực(?:\s+thi\s+hành)?\b",
    re.IGNORECASE,
)


class RelationTypeEdgeCases:
    """Edge-case predicate helpers for relation type extraction."""

    @staticmethod
    def _has_parent_appendix_amendment_context(*ancestor_contents: Optional[str]) -> bool:
        for ancestor_content in ancestor_contents:
            if not ancestor_content:
                continue
            normalized = unidecode(ancestor_content or "").lower()
            if _PARENT_APPENDIX_AMENDMENT_CONTEXT_PATTERN.search(normalized):
                return True
        return False

    @staticmethod
    def _is_document_title_descriptive_dan_chieu(
        content: str,
        start_pos: int,
    ) -> bool:
        line_start = content.rfind("\n", 0, start_pos) + 1
        line_end = content.find("\n", start_pos)
        if line_end == -1:
            line_end = len(content)
        line = content[line_start:line_end]
        normalized_line = unidecode(line or "").lower()
        if not _TITLE_ACTION_PREFIX_PATTERN.search(normalized_line):
            return False
        if not _TITLE_DESCRIPTIVE_DAN_CHIEU_PATTERN.search(normalized_line):
            return False

        normalized_prefix = unidecode(content[:start_pos] or "").lower()
        can_cu_pos = normalized_prefix.find("can cu")
        return can_cu_pos == -1

    @staticmethod
    def _is_post_action_assignment_basis(
        content: str,
        start_pos: int,
        filtered_matches: List[Dict],
    ) -> bool:
        current_scope_start = max(
            content.rfind(separator, 0, start_pos)
            for separator in (".", "\n")
        ) + 1
        scope_prefix = unidecode(content[current_scope_start:start_pos] or "").lower()
        if not _POST_ACTION_ASSIGNMENT_BASIS_PATTERN.search(scope_prefix):
            return False

        return any(
            other.get("relation_type") in _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES
            and other.get("position_start", -1) < current_scope_start
            for other in filtered_matches
        )

    @staticmethod
    def _is_inside_amendment_replacement_quote(content: str, start_pos: int) -> bool:
        if start_pos <= 0:
            return False

        window = content[max(0, start_pos - 2500):start_pos]
        intro_matches = list(_AMENDMENT_REPLACEMENT_INTRO_PATTERN.finditer(window))
        if not intro_matches:
            return False

        replacement_body_prefix = window[intro_matches[-1].end():]
        curly_open_after_close = replacement_body_prefix.rfind("“") > replacement_body_prefix.rfind("”")
        ascii_double_quote_open = replacement_body_prefix.count('"') % 2 == 1
        ascii_single_quote_open = replacement_body_prefix.count("'") % 2 == 1
        return curly_open_after_close or ascii_double_quote_open or ascii_single_quote_open

    @staticmethod
    def _edge_case_points_to_following_list(
        content: str,
        edge_start: int,
        edge_end: int,
        ref_starts: List[int],
    ) -> bool:
        """Detect headings like 'các Nghị quyết sau đây hết hiệu lực ...:'."""
        if edge_start < 0 or edge_end < 0:
            return False

        prefix = content[max(0, edge_start - 120):edge_start]
        if re.search(r"\bsau\s+đây\b", prefix, re.IGNORECASE) is None:
            return False

        following_ref_starts = [pos for pos in ref_starts if pos >= edge_end]
        if not following_ref_starts:
            return False

        suffix_to_first_ref = content[edge_end:min(following_ref_starts)]
        return _FOLLOWING_LIST_MARKER_PATTERN.search(suffix_to_first_ref) is not None

    @staticmethod
    def _is_indirect_keo_dai_basis_reference(
        content: str,
        relation_text: str,
        relation_start: int,
        relation_end: int,
        ref_starts: List[int],
    ) -> bool:
        if relation_start < 0 or relation_end < 0:
            return False

        if not _KEO_DAI_TIME_CUE_PATTERN.search(relation_text or ""):
            return False

        sentence_end_candidates = [
            content.find(separator, relation_end)
            for separator in (".", "\n")
            if content.find(separator, relation_end) != -1
        ]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(content)
        scoped_ref_starts = [
            ref_start for ref_start in ref_starts
            if relation_end <= ref_start < sentence_end
        ]
        if not scoped_ref_starts:
            return False

        first_ref_start = min(scoped_ref_starts)
        text_before_first_ref = content[relation_end:first_ref_start]
        return bool(_KEO_DAI_INDIRECT_BASIS_MARKER_PATTERN.search(text_before_first_ref))

    @staticmethod
    def _is_indirect_action_basis_reference(
        content: str,
        relation_end: int,
        ref_starts: List[int],
    ) -> bool:
        """Return True when a strong action cue points to a legal-basis reference."""
        if relation_end < 0:
            return False

        sentence_end_candidates = [
            content.find(separator, relation_end)
            for separator in (".", "\n")
            if content.find(separator, relation_end) != -1
        ]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(content)
        scoped_ref_starts = [
            ref_start for ref_start in ref_starts
            if relation_end <= ref_start < sentence_end
        ]
        if not scoped_ref_starts:
            return False

        first_ref_start = min(scoped_ref_starts)
        text_before_first_ref = content[relation_end:first_ref_start]
        return bool(_THEO_QUY_DINH_TAI_MARKER_PATTERN.search(text_before_first_ref))

    @staticmethod
    def _is_post_amendment_intro_bai_bo_continuation(
        content: str,
        match: Dict,
        filtered_matches: List[Dict],
    ) -> bool:
        if match.get("relation_type") != "bai_bo":
            return False

        match_end = match.get("position_end", 0)
        suffix = content[match_end:match_end + 80]
        if not _POST_INTRO_DOCUMENT_ACTION_TARGET_PATTERN.search(suffix):
            return False

        match_start = match.get("position_start", -1)
        for other in filtered_matches:
            if other is match:
                continue
            if other.get("position_start", -1) >= match_start:
                continue
            if other.get("relation_type") != "sua_doi_bo_sung":
                continue
            if not re.search(r"\bbãi\s+bỏ\b", other.get("text", ""), re.IGNORECASE):
                continue

            bridge = content[other.get("position_end", 0):match_start]
            if re.search(r"\bnhư\s+sau\s*:\s*$", bridge, re.IGNORECASE | re.DOTALL):
                return True

        return False

    @staticmethod
    def _is_operational_action_relation(
        content: str,
        relation_start: int,
        scope_end: int,
    ) -> bool:
        """Return True for operational actions, not document relations."""
        if relation_start < 0:
            return False

        scope_text = content[relation_start:scope_end]
        return bool(_OPERATIONAL_ACTION_OBJECT_PATTERN.search(scope_text))

    @staticmethod
    def _should_skip_descriptive_dan_chieu(
        content: str,
        start_pos: int,
        end_pos: int,
    ) -> bool:
        """Return True for descriptive citations that should not become dan_chieu."""
        prefix = content[:start_pos]
        suffix = content[end_pos:]

        if (
            _DAN_CHIEU_SCOPE_HEADING_PATTERN.search(prefix)
            and re.search(r"\bhướng\s+dẫn\b", prefix, re.IGNORECASE)
        ):
            return True

        if (
            _DAN_CHIEU_CORRECTION_SCOPE_PATTERN.search(prefix)
            and _DAN_CHIEU_CORRECTION_ACTION_PATTERN.search(suffix)
        ):
            return True

        current_scope_start = max(
            content.rfind(separator, 0, start_pos)
            for separator in (".", "\n")
        ) + 1
        current_scope_prefix = content[current_scope_start:start_pos]
        if (
            _TAI_CONG_VAN_RELATION_PATTERN.search(content[start_pos:end_pos])
            and _DE_NGHI_TAI_CONG_VAN_SCOPE_PATTERN.search(current_scope_prefix)
        ):
            return True

        if (
            _EXCEPTION_SELF_DOCUMENT_SCOPE_PATTERN.search(current_scope_prefix)
            and re.search(r"^\s+này\b", suffix, re.IGNORECASE)
        ):
            return True

        if _DAN_CHIEU_PHRASE_AMENDMENT_SCOPE_PATTERN.search(
            current_scope_prefix
        ):
            return True

        relation_text = content[start_pos:end_pos]
        if (
            re.search(r"\bquy\s+định\s+tại\s+điều\b", relation_text, re.IGNORECASE)
            and _DAN_CHIEU_INTERNAL_OBJECT_SCOPE_PATTERN.search(content[end_pos:end_pos + 160])
        ):
            return True

        return False

    @staticmethod
    def _should_promote_dan_chieu_to_detail_from_parent(
        content: str,
        parent_content: Optional[str],
        grandparent_content: Optional[str],
        relations: List[Dict],
    ) -> bool:
        """Promote child citations when the parent enumerates the detail scope."""
        if not relations or any(
            relation.get("relation_type") != "dan_chieu"
            for relation in relations
        ):
            return False

        if not _THEO_QUY_DINH_TAI_CLAUSE_PATTERN.search(content or ""):
            return False

        if _CHILD_SCOPE_QUY_DINH_VE_PATTERN.search(content or ""):
            return False

        for ancestor_content in (parent_content, grandparent_content):
            if ancestor_content and _DETAIL_PARENT_WITH_IMPLEMENTING_DECREE_PATTERN.search(
                ancestor_content.strip()
            ):
                return True

        return False

    @staticmethod
    def _filter_conflict_or_redundant_relation_types(
        content: str,
        relations: List[Dict],
        doc_types: List[str],
        clause_type: str
    ) -> List[Dict]:
        """
        Filter out redundant relation types based on specific rules:
        1. Immediately follows a doc_type (e.g., 'Luật sửa đổi, bổ sung').
        2. Immediately followed by a newline (e.g., 'Phạm vi điều chỉnh\\n').
        3. Immediately follows a full document reference in the same scope
        (EXCEPT: inherited, passive, edge cases, enumerated relations).
        """
        filtered_relations = []

        if clause_type == "vanban":
            return relations

        for rel in relations:
            rel_start = rel.get("position_start", -1)
            rel_end = rel.get("position_end", -1)
            direction = rel.get("direction", "FORWARD")
            hint_group = rel.get("hint_group", "")

            # Special relations bypass all rules:
            is_special = (
                rel_start == -1 or
                direction == "PASSIVE" or
                hint_group.startswith("edge_case_") or
                hint_group == "enumerated_relation_types" or
                (
                    rel.get("relation_type") == "dan_chieu"
                    and _DAN_CHIEU_BACKWARD_EFFECTIVE_CUE_PATTERN.search(
                        rel.get("relation_value", "") or ""
                    )
                )
            )

            if is_special:
                filtered_relations.append(rel)
                continue

            if rel_start < 0 or rel_end < 0:
                filtered_relations.append(rel)
                continue

            # Rule 1: Relation immediately follows a document type
            prefix = content[max(0, rel_start - _IMMEDIATE_CONTEXT_LENGTH):rel_start]
            is_rule1 = False
            for dt in doc_types:
                if re.search(rf"\b{re.escape(dt)}\s*$", prefix):
                    is_rule1 = True
                    break

            if is_rule1:
                continue

            # Rule 2: Immediately followed by a newline or end of string
            suffix_after = content[rel_end:min(rel_end + _IMMEDIATE_CONTEXT_LENGTH, len(content))]
            if "\n" in suffix_after and not suffix_after.split("\n")[0].endswith(":"):
                continue

            # Rule 3: Immediately follows a full document reference in same scope
            doc_refs_ends: List[int] = []
            try:
                unfiltered_refs = RelationTypeEdgeCases._extract_doc_references_without_filtering(content, doc_types)
            except Exception:
                unfiltered_refs = []

            for ref in unfiltered_refs:
                span = BaseExtractorShared._get_reference_match_span(ref)
                if span and span.get("position_end") is not None:
                    doc_refs_ends.append(span["position_end"])

            is_rule3 = False
            for doc_end in doc_refs_ends:
                gap = rel_start - doc_end
                if 0 <= gap <= 80:
                    # Check major delimiters only (., ;, \n)
                    major_delim_found = False
                    for major_delim in SCOPE_DELIMITERS:
                        if content.find(major_delim, doc_end, rel_start) != -1:
                            major_delim_found = True
                            break

                    if major_delim_found:
                        continue

                    intervening = content[doc_end:rel_start]

                    # Skip if ends with passive markers
                    if re.search(r"(?:đã\s+)?(?:được|bị)\s*$", intervening, re.IGNORECASE):
                        continue

                    # Skip if relation followed by enumerated pattern
                    after_rel = content[rel_end:min(rel_end + 30, len(content))]
                    if re.search(r"[^:]*:\s*\n", after_rel):
                        continue

                    if (
                        rel.get("relation_type") in _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES
                        and ":" in intervening
                        and _POST_INTRO_DOCUMENT_ACTION_TARGET_PATTERN.search(after_rel)
                    ):
                        continue

                    if re.match(r'^[\s\w,;:\-–—()]{0,80}$', intervening, re.UNICODE):
                        is_rule3 = True
                        break

            if is_rule3:
                continue

            filtered_relations.append(rel)

        return filtered_relations

    @staticmethod
    def _forward_relation_points_to_following_list(
        content: str,
        relation_end: int,
        ref_starts: List[int],
    ) -> bool:
        following_ref_starts = [pos for pos in ref_starts if pos >= relation_end]
        if not following_ref_starts:
            return False

        bridge_to_first_ref = content[relation_end:min(following_ref_starts)]
        return _FORWARD_LIST_HEADING_PATTERN.search(bridge_to_first_ref) is not None

    @staticmethod
    def _forward_relation_points_to_semicolon_target_list(
        content: str,
        relation_end: int,
        ref_starts: List[int],
    ) -> bool:
        sentence_end_candidates = [
            content.find(separator, relation_end)
            for separator in (".", "\n")
            if content.find(separator, relation_end) != -1
        ]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(content)
        scoped_ref_starts = [
            ref_start
            for ref_start in ref_starts
            if relation_end <= ref_start < sentence_end
        ]
        if not scoped_ref_starts:
            return False

        for ref_start in scoped_ref_starts:
            semicolon_pos = content.rfind(";", relation_end, ref_start)
            if semicolon_pos == -1:
                continue
            bridge = content[semicolon_pos + 1:ref_start]
            if re.fullmatch(r"\s*(?:[-–•]|\(?[a-zđ]\)|\d+[\).])?\s*", bridge, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _extract_doc_references_without_filtering(content: str, doc_types: List[str]) -> List[Dict]:
        """
        Extract document references from content without filtering.
        This func is to support the `_filter_conflict_relation_types`,
        it's not the main func to extract document references.
        """
        if not content or not content.strip():
            return []

        shared = BaseExtractorShared()
        doc_references: List[Dict] = []

        # Build lightweight sentence-like scopes to keep spans localised
        scopes = BaseExtractorShared._build_sentence_scopes(content)

        for scope in scopes:
            scope_text = scope["text"]
            scope_start = scope["start_pos"]

            # Find all doc_type matches in this scope and process in-order (stop at next doc_type)
            doc_type_matches: List[Dict] = []
            for doc_type in doc_types:
                doc_type_variants = {doc_type, doc_type.upper()}
                pattern = (
                    r"\b(?:"
                    + "|".join(re.escape(variant) for variant in doc_type_variants)
                    + r")\b"
                )
                for m in re.finditer(pattern, scope_text):
                    doc_type_matches.append({
                        "doc_type_text": m.group(),
                        "doc_type_key": BaseExtractorShared._normalize_doc_type_key(m.group()),
                        "start": m.start(),
                        "end": m.end(),
                    })

            if not doc_type_matches:
                continue

            doc_type_matches.sort(key=lambda x: x["start"])

            # Filter out matches that fall within parentheses
            filtered_matches = []
            for match_info in doc_type_matches:
                match_start = match_info["start"]
                # Count opening and closing parentheses before this match
                text_before = scope_text[:match_start]
                open_parens = text_before.count("(")
                close_parens = text_before.count(")")
                # If unclosed opening parens exist, we're inside parentheses
                if open_parens > close_parens:
                    continue
                filtered_matches.append(match_info)

            if not filtered_matches:
                continue

            doc_type_matches = filtered_matches
            processed_indices = set()
            for idx, match_info in enumerate(doc_type_matches):
                if idx in processed_indices:
                    continue

                local_start = match_info["start"]

                # Find candidate boundary: next match or EOL
                next_match_start = len(scope_text)
                for next_idx in range(idx + 1, len(doc_type_matches)):
                    if next_idx not in processed_indices:
                        next_match_start = doc_type_matches[next_idx]["start"]
                        break

                candidate_text = scope_text[local_start:next_match_start]
                if not candidate_text.strip():
                    continue

                doc_type_key = match_info["doc_type_key"]

                # Try to extract structured components (number, title, date)
                number_match = shared._find_doc_number_match(candidate_text, doc_type_key)
                title_span = BaseExtractorShared._extract_title_span(candidate_text)

                # Require at least a title (for law-like) or a document number for other types
                if title_span is None and number_match is None:
                    # Not a concise reference for this doc_type in this segment; skip
                    continue

                provisional_end = 0
                if title_span is not None:
                    provisional_end = max(provisional_end, title_span[1])
                if number_match is not None:
                    provisional_end = max(provisional_end, number_match.end())
                if provisional_end > 0:
                    date_match = BaseExtractorShared._find_date_or_year_match(candidate_text, provisional_end)

                info_end = provisional_end
                if date_match is not None:
                    info_end += date_match.end()

                # Final information text
                info_text = candidate_text[:info_end].strip(" ,") if info_end > 0 else candidate_text.strip(" ,")

                # Truncate at opening or closing parenthesis
                for paren in ("(", ")"):
                    paren_pos = info_text.find(paren)
                    if paren_pos != -1:
                        info_text = info_text[:paren_pos].strip(" ,")

                # Skip if empty after truncation or contains only punctuation/whitespace
                if not info_text or not re.search(r'[a-zA-ZđðĐÐ0-9]', info_text):
                    continue

                info_start_global = scope_start + local_start
                info_end_global = info_start_global + len(info_text)

                doc_references.append({
                    doc_type_key: {
                        "information": info_text,
                        "position_start": info_start_global,
                        "position_end": info_end_global,
                    }
                })

        # Sort by earliest position_start
        doc_references.sort(key=lambda r: next(iter(r.values())).get("position_start", 0))

        # Post-processing: Merge adjacent law references if they form a compound phrase
        # E.g., "Luật sửa đổi, bổ sung..." followed immediately by "Luật Dược..." should merge
        merged_refs = []
        skip_indices = set()

        for idx, cur_ref in enumerate(doc_references):
            if idx in skip_indices:
                continue

            cur_key = list(cur_ref.keys())[0]
            cur_val = cur_ref[cur_key]
            cur_info = cur_val.get("information", "")
            cur_start = cur_val.get("position_start")

            # Check if this is a "sửa đổi/bổ sung" law followed by another law
            is_modifier_law = (cur_key in ["luat", "boluat"] and
                               ("sửa đổi" in cur_info.lower() or "bổ sung" in cur_info.lower()))

            if is_modifier_law and idx + 1 < len(doc_references) and idx + 1 not in skip_indices:
                next_ref = doc_references[idx + 1]
                next_key = list(next_ref.keys())[0]
                next_val = next_ref[next_key]
                next_end = next_val.get("position_end")

                # Merge if next is also a law type
                if next_key in ["luat", "boluat"]:
                    # Create merged reference spanning both
                    merged_info = content[cur_start:next_end].strip()
                    merged_ref = {
                        cur_key: {
                            "information": merged_info,
                            "position_start": cur_start,
                            "position_end": next_end,
                        }
                    }
                    merged_refs.append(merged_ref)
                    skip_indices.add(idx + 1)
                    continue

            # No merge; keep as-is
            merged_refs.append(cur_ref)

        return merged_refs
