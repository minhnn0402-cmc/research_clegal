"""Reference extraction stage for ``BaseExtractor``."""

from typing import Callable, Dict, List, Optional, Tuple
import re

from src.domain.extractors.base_extractor_flow.models import ClauseContext, ReferenceMention
from src.domain.extractors.base_extractor_flow.reference_normalization import (
    CLEAN_TITLE_CONTINUATION_PATTERN,
    LAW_LIKE_TYPES,
    SUBORDINATE_TRIGGER_PATTERN,
)
from src.domain.extractors.base_extractor_flow.shared import unidecode
from src.domain.extractors.content_extractor import ContentExtractor
from src.infrastructure.config import doc_number_patterns_for_regex, loai_van_ban_mapping
from src.shared.text.normalizers import normalize_clause_component_information


# "Luật này", "Thông tư liên tịch này", etc. — signals an internal cross-reference.
# Built from loai_van_ban_mapping (longest-first) so compound types like
# "Thông tư liên tịch" are matched before their shorter prefix "Thông tư".
# When present, cls_title injection is suppressed: the internal reference resolver handles it.
_DOC_TYPE_NAMES_SORTED = sorted(loai_van_ban_mapping.values(), key=len, reverse=True)
_DOC_TYPE_NAY_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(n) for n in _DOC_TYPE_NAMES_SORTED) + r")\s+này\b",
    re.IGNORECASE,
)
# Amendment-provenance parentheticals describe a target's prior amendment
# history — "(được sửa đổi, bổ sung bởi khoản 1 Điều 1 Nghị định số 136/2021/NĐ-CP)"
# — and never name the operative target of the current clause. When such a note
# sits between a clause component and its governing document, its inner
# document/clause references must not become binding anchors, otherwise every
# listed component is mis-attributed to the provenance document instead of the
# governing one named after the list ("… của Nghị định số 27/2019/NĐ-CP"). The
# span is masked (length-preserving) before scope extraction so positions of all
# surrounding references stay valid.
AMENDMENT_PROVENANCE_PARENTHETICAL_PATTERN = re.compile(
    r"\(\s*(?:đã\s+)?được\s+(?:sửa\s+đổi|bổ\s+sung)[^()]*\)",
    re.IGNORECASE,
)


# A "Mẫu số …" / "Biểu mẫu …" identifier is a form/template code, not a legal
# document number. When the only number-like token captured for a non-law
# reference is a form code (e.g. "Quyết định … theo Mẫu số 29-TTr"), the
# reference is spurious. Matched against the candidate text ending right before
# the captured number, so it only fires when the form cue directly precedes it.
FORM_IDENTIFIER_PREFIX_PATTERN = re.compile(
    r"(?:theo\s+)?(?:mẫu(?:\s+số)?|biểu\s+mẫu(?:\s+số)?)\s*$",
    re.IGNORECASE,
)
NUMERIC_DIEM_BEFORE_DOC_PATTERN = re.compile(
    r"\b(?P<label>điểm|Mục)\s+(?P<value>\d+[A-Za-zĐđ]?)\b"
    r"(?=\s+(?:của|thuộc)\s+"
    r"(?:Luật|Bộ\s+luật|Hiến\s+pháp|Nghị\s+quyết|Nghị\s+định|Thông\s+tư|Quyết\s+định|Pháp\s+lệnh)\b)",
    re.IGNORECASE,
)
BARE_CONJOINED_NUMBERED_REFERENCE_PATTERN = re.compile(
    r"\b(?:và|hoặc|và/hoặc)\s+(?P<marker>số)\s+"
    r"(?P<number>\d{1,5}/\d{4}/[A-ZĐ]{1,10}(?:-[A-ZĐ0-9]{1,15})?)\b",
    re.IGNORECASE,
)
POST_INTRO_DOCUMENT_ACTION_PATTERN = re.compile(
    r"^\s*(?:bãi\s+bỏ|hủy\s+bỏ|chấm\s+dứt\s+hiệu\s+lực)\b",
    re.IGNORECASE,
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
AMENDMENT_LAW_COUNT_CLAUSE_PATTERN = re.compile(
    r"\b(?P<khoan>khoản\s+\d+[A-Za-zĐđ]?)\s*,?\s*"
    r"(?P<dieu>Điều\s+\d+[A-Za-zĐđ]?)\s+"
    r"(?P<luat>Luật\s+sửa\s+đổi\s*,\s*bổ\s+sung\s+một\s+số\s+điều\s+của\s+"
    r"\d+\s+Luật\b[^.;\n]*)",
    re.IGNORECASE,
)
ATTACHED_APPENDIX_CLAUSE_DOC_PATTERN = re.compile(
    r"\b(?P<diem>điểm\s+[A-Za-zĐđ]\d*)\s+"
    r"(?P<khoan>khoản\s+\d+[A-Za-zĐđ]?)\s+"
    r"(?P<dieu>Điều\s+\d+[A-Za-zĐđ]?)"
    r"(?P<bridge>.{0,240}?\bphụ\s+lục\b.{0,160}?\bban\s+hành\s+kèm\s+theo\s+)"
    r"(?P<nghidinh>Nghị\s+định\s+số\s+\d{1,5}/\d{4}/NĐ-CP"
    r"(?:\s+ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})?)",
    re.IGNORECASE | re.DOTALL,
)
TITLE_AMENDMENT_TARGET_PREFIX_PATTERN = re.compile(
    r"\b(?:sửa\s+đổi\s*,?\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung|thay\s+thế)\b",
    re.IGNORECASE,
)
TITLE_DESCRIPTIVE_REFERENCE_BRIDGE_PATTERN = re.compile(
    r"\b(?:hướng\s+dẫn|quy\s+định\s+chi\s+tiết|thi\s+hành|về\s+việc)\b",
    re.IGNORECASE,
)
LEADING_AMENDMENT_TARGET_INTRO_PATTERN = re.compile(
    r"\b(?:sửa\s+đổi\s*,?\s*bổ\s+sung|sửa\s+đổi|bổ\s+sung|thay\s+thế)\b"
    r".{0,260}\bnhư\s+sau\s*:",
    re.IGNORECASE | re.DOTALL,
)
INTRO_DOC_CLAUSE_LIST_MARKER_PATTERN = re.compile(
    r"\bnhư\s+sau\s*:",
    re.IGNORECASE,
)


class ReferenceExtraction:
    """Sentence-scope reference extraction and ancestor-context stitching."""

    def _build_clause_context(
        self,
        content: str,
        doc_types: List[str],
        clause_type: Optional[str],
        clause_key: Optional[str],
        data: Optional[List[Dict]],
        child_to_parent: Optional[Dict[str, str]],
        clause_types: List[str],
        law_titles: List[str],
        cls_title: Optional[str] = None
    ) -> ClauseContext:
        content_clause_groups: List[Dict] = []
        content_doc_references: List[Dict] = []
        has_document_refs = False
        if content and clause_types:
            dummy_scope = {"text": content, "start_pos": 0}
            extracted_clauses = self._extract_clause_components_from_scope(dummy_scope, clause_types)
            if extracted_clauses:
                content_clause_groups = self._group_clause_components(extracted_clauses)
                content_doc_references, _ = self._extract_doc_references_from_scope(
                    scope=dummy_scope,
                    doc_types=doc_types,
                    law_titles=law_titles,
                )
                has_document_refs = bool(content_doc_references)

        has_clause_refs = bool(content_clause_groups)
        if not has_clause_refs:
            return ClauseContext(
                sentence_scopes=self._build_sentence_scopes(content),
                is_can_cu_content=content.lstrip().startswith("Căn cứ"),
                doc_type_markers=self._build_doc_type_markers(doc_types),
                ancestor_context={},
                ancestor_doc_reference=None,
                ancestor_doc_references=[],
            )

        ancestor_context = self._find_reference_context_from_ancestors(
            clause_type=clause_type,
            clause_key=clause_key,
            data=data,
            child_to_parent=child_to_parent,
            doc_types=doc_types,
            clause_types=clause_types,
            law_titles=law_titles,
            cls_title=None,
        )
        ancestor_doc_references = self._find_document_references_from_ancestors(
            clause_type=clause_type,
            clause_key=clause_key,
            data=data,
            child_to_parent=child_to_parent,
            doc_types=doc_types,
            clause_types=clause_types,
            law_titles=law_titles,
            cls_title=None,
        )
        ancestor_doc_reference = self._extract_document_reference_from_context(ancestor_context)
        if not ancestor_doc_references and ancestor_doc_reference:
            ancestor_doc_references = [ancestor_doc_reference]

        intro_doc_references = self._select_intro_document_references_for_clause_list(
            content=content,
            clause_groups=content_clause_groups,
            doc_references=content_doc_references,
        )
        if intro_doc_references and not ancestor_doc_references:
            ancestor_doc_references = intro_doc_references
            if ancestor_doc_reference is None:
                intro_doc_reference = intro_doc_references[0]
                doc_key = next(iter(intro_doc_reference))
                if doc_key not in ancestor_context:
                    ancestor_context[doc_key] = intro_doc_reference[doc_key].copy()
                ancestor_doc_reference = self._extract_document_reference_from_context(
                    ancestor_context
                )

        can_use_fallback_ref = (
            bool(cls_title)
            and not has_document_refs
            and not self._self_document_reference_blocks_title_context(
                content=content,
                clause_groups=content_clause_groups,
            )
            and self._clause_groups_have_complete_article_scope(
                clause_groups=content_clause_groups,
                ancestor_context=ancestor_context,
            )
        )
        if can_use_fallback_ref:
            # Try nearest chuong ancestor before falling back to cls_title.
            # chuong is more specific than cls_title, which may list multiple documents.
            fallback_doc_references = self._extract_doc_references_from_chuong(
                clause_key=clause_key,
                data=data,
                doc_types=doc_types,
                clause_types=clause_types,
                law_titles=law_titles,
            )
            if not fallback_doc_references:
                fallback_doc_references = self._extract_document_references_from_cls_title(
                    cls_title=cls_title,
                    doc_types=doc_types,
                    law_titles=law_titles,
                )
                if len(fallback_doc_references) > 1:
                    fallback_doc_references = []
            if fallback_doc_references:
                if ancestor_doc_reference is None:
                    fallback_doc_reference = fallback_doc_references[0]
                    doc_key = next(iter(fallback_doc_reference))
                    if doc_key not in ancestor_context:
                        ancestor_context[doc_key] = fallback_doc_reference[doc_key].copy()
                    ancestor_doc_reference = self._extract_document_reference_from_context(
                        ancestor_context
                    )
                if not ancestor_doc_references:
                    ancestor_doc_references = fallback_doc_references

        return ClauseContext(
            sentence_scopes=self._build_sentence_scopes(content),
            is_can_cu_content=content.lstrip().startswith("Căn cứ"),
            doc_type_markers=self._build_doc_type_markers(doc_types),
            ancestor_context=ancestor_context,
            ancestor_doc_reference=ancestor_doc_reference,
            ancestor_doc_references=ancestor_doc_references,
        )

    @staticmethod
    def _get_reference_span(reference: Dict) -> Tuple[int, int]:
        """Return the full start/end span covered by one reference payload."""
        positions = [
            (
                int(value.get("position_start", 0)),
                int(value.get("position_end", 0)),
            )
            for value in reference.values()
            if isinstance(value, dict)
        ]
        if not positions:
            return 0, 0

        return (
            min(start for start, _ in positions),
            max(end for _, end in positions),
        )

    @classmethod
    def _apply_raw_positions(
        cls,
        reference: Dict,
        position_mapper: Optional[Callable[[int, int], Optional[Tuple[int, int]]]],
    ) -> Dict:
        """Attach raw inclusive offsets while preserving internal clean offsets."""
        copied = cls._copy_reference(reference)
        if position_mapper is None:
            return copied

        for value in copied.values():
            if not isinstance(value, dict):
                continue
            start = value.get("position_start")
            end = value.get("position_end")
            if start is None or end is None or int(start) < 0 or int(end) < 0:
                continue
            raw_span = position_mapper(int(start), int(end))
            if raw_span is None:
                continue
            value["_raw_position_start"] = raw_span[0]
            value["_raw_position_end"] = raw_span[1]

        return copied

    @staticmethod
    def _get_sentence_end(content: str, start_pos: int) -> int:
        """Return the next lightweight sentence boundary after ``start_pos``."""
        candidates = [
            pos
            for separator in (".", ";", "\n")
            for pos in [content.find(separator, start_pos)]
            if pos != -1
        ]
        return min(candidates) if candidates else len(content)

    def _extract_clause_components_from_scope(
        self,
        scope: Dict,
        clause_types: List[str]
    ) -> List[Dict]:
        """Extract clause components (dieu/khoan/diem) from a sentence scope."""
        scope_text = scope["text"]
        scope_start = scope["start_pos"]
        clause_matches: List[Dict] = []

        for clause_type in clause_types:
            clause_key = self._normalize_doc_type_key(clause_type)
            # Get the value pattern for the clause type
            value_patterns = doc_number_patterns_for_regex.get(clause_key, [])
            if not value_patterns:
                continue

            value_pattern = self._get_clause_value_pattern(clause_key, value_patterns)
            clause_label_pattern = re.escape(clause_type)
            if clause_key == "diem":
                clause_label_pattern = rf"(?:{re.escape(clause_type)}|Mục)"
            pattern = (
                r"\b" + clause_label_pattern + r"\b"
                r"(?P<spacing>\s+)"
                r"(?P<value>" + value_pattern + r")"
            )

            for match in re.finditer(pattern, scope_text, re.IGNORECASE):
                value = match.group("value").strip()
                information = normalize_clause_component_information(
                    match.group().strip(),
                    clause_key,
                )
                clause_matches.append({
                    "key": clause_key,
                    "information": information,
                    "position_start": scope_start + match.start(),
                    "position_end": scope_start + match.end(),
                    "local_start": match.start(),
                    "local_end": match.end(),
                    "value": value,
                })

            if clause_key == "diem":
                for match in NUMERIC_DIEM_BEFORE_DOC_PATTERN.finditer(scope_text):
                    value = match.group("value").strip()
                    if any(
                        existing["local_start"] == match.start()
                        and existing["local_end"] == match.end()
                        for existing in clause_matches
                    ):
                        continue

                    information = normalize_clause_component_information(
                        match.group().strip(),
                        clause_key,
                    )
                    clause_matches.append({
                        "key": clause_key,
                        "information": information,
                        "position_start": scope_start + match.start(),
                        "position_end": scope_start + match.end(),
                        "local_start": match.start(),
                        "local_end": match.end(),
                        "value": value,
                    })

        clause_matches.sort(key=lambda item: item["local_start"])
        return [
            match
            for match in clause_matches
            if not (scope_start == 0 and match["local_start"] == 0)
        ]

    @staticmethod
    def _group_clause_components(clause_matches: List[Dict]) -> List[Dict]:
        """Group clause component matches into reference chains."""
        if not clause_matches:
            return []

        ordered_keys = ["diem", "khoan", "dieu"]
        level_map = {key: index for index, key in enumerate(ordered_keys)}
        groups: List[List[Dict]] = []
        current_group: List[Dict] = []
        previous_level: Optional[int] = None

        for match in clause_matches:
            current_level = level_map[match["key"]]

            if current_group and previous_level is not None and current_level <= previous_level:
                groups.append(current_group)
                current_group = []

            current_group.append(match)
            previous_level = current_level

        if current_group:
            groups.append(current_group)

        normalized_groups: List[Dict] = []

        for group in groups:
            normalized_group: Dict = {}
            for key in ordered_keys:
                item = next((entry for entry in group if entry["key"] == key), None)
                if item is not None:
                    normalized_group[key] = {
                        "information": item["information"],
                        "position_start": item["position_start"],
                        "position_end": item["position_end"],
                    }
            if normalized_group:
                normalized_groups.append(normalized_group)

        inherited_dieu: Optional[Dict] = None
        inherited_khoan: Optional[Dict] = None

        for group in reversed(normalized_groups):
            if "dieu" in group:
                inherited_dieu = group["dieu"]
            if "khoan" in group:
                inherited_khoan = group["khoan"]

            if "diem" in group:
                if "khoan" not in group and inherited_khoan is not None:
                    group["khoan"] = inherited_khoan.copy()
                if "dieu" not in group and inherited_dieu is not None:
                    group["dieu"] = inherited_dieu.copy()
            elif "khoan" in group and "dieu" not in group and inherited_dieu is not None:
                group["dieu"] = inherited_dieu.copy()

        return normalized_groups

    @staticmethod
    def _is_dinh_chinh_reference_context(content: str) -> bool:
        normalized_content = unidecode(content or "").lower()
        return "dinh chinh" in normalized_content

    @staticmethod
    def _is_dinh_chinh_correction_target_scope(content: str) -> bool:
        normalized_content = unidecode(content or "").lower()
        return any(
            marker in normalized_content
            for marker in (
                "dinh chinh",
                "sua cum tu",
                "sua tieu de",
                "duoc sua thanh",
                "sua thanh",
                "da ban hanh",
            )
        )

    @staticmethod
    def _find_dinh_chinh_intro_end(content: str) -> Optional[int]:
        normalized_content = unidecode(content or "").lower()
        match = re.search(r"\bdinh\s+chinh\b.*?\bnhu\s+sau\s*:", normalized_content, re.DOTALL)
        return match.end() if match else None

    @classmethod
    def _find_first_quote_or_action_position(cls, text: str) -> Optional[int]:
        normalized_text = unidecode(text or "").lower()
        candidates = [
            pos
            for marker in (
                "dinh chinh",
                "sua cum tu",
                "sua tieu de",
                "duoc sua thanh",
                "sua thanh",
                "da ban hanh",
            )
            for pos in [normalized_text.find(marker)]
            if pos != -1
        ]
        quote_positions = [
            pos
            for quote in ("“", "”", '"')
            for pos in [text.find(quote)]
            if pos != -1
        ]
        candidates.extend(quote_positions)
        return min(candidates) if candidates else None

    def _select_leading_dinh_chinh_clause_groups(
        self,
        scope: Dict,
        clause_groups: List[Dict],
    ) -> List[Dict]:
        if not clause_groups:
            return []

        scope_text = scope["text"]
        local_cutoff = self._find_first_quote_or_action_position(scope_text)
        if local_cutoff is None:
            return []

        cutoff = scope["start_pos"] + local_cutoff
        leading_groups = [
            clause_group
            for clause_group in clause_groups
            if self._get_reference_span(clause_group)[1] <= cutoff
        ]
        if not leading_groups:
            return []

        return [leading_groups[0]]

    def _select_leading_amendment_clause_groups(
        self,
        scope: Dict,
        clause_groups: List[Dict],
    ) -> List[Dict]:
        """Keep amendment targets before the replacement body after ``như sau``."""
        if not clause_groups:
            return []

        scope_text = scope["text"]
        intro_match = LEADING_AMENDMENT_TARGET_INTRO_PATTERN.search(scope_text)
        if not intro_match:
            return []

        cutoff = scope["start_pos"] + intro_match.end()
        return [
            clause_group
            for clause_group in clause_groups
            if self._get_reference_span(clause_group)[1] <= cutoff
        ]

    @staticmethod
    def _get_ancestor_keys(
        clause_type: Optional[str],
        clause_key: Optional[str],
        child_to_parent: Optional[Dict[str, str]]
    ) -> List[str]:
        """Return candidate ancestor keys in nearest-first order."""
        if not clause_type or not clause_key or not child_to_parent:
            return []

        ancestor_keys: List[str] = []
        parent_key = child_to_parent.get(clause_key)

        if clause_type == "khoan" and parent_key:
            ancestor_keys.append(parent_key)
        elif clause_type == "diem" and parent_key:
            ancestor_keys.append(parent_key)
            grandparent_key = child_to_parent.get(parent_key)
            if grandparent_key:
                ancestor_keys.append(grandparent_key)

        return ancestor_keys

    @classmethod
    def _remove_leading_self_clause_component(
        cls,
        reference: Dict,
        ancestor_clause_type: Optional[str]
    ) -> Dict:
        """Drop the leading self-heading component from an ancestor reference."""
        cleaned_reference = cls._copy_reference(reference)

        if ancestor_clause_type not in {"dieu", "khoan", "diem"}:
            return cleaned_reference

        clause_info = cleaned_reference.get(ancestor_clause_type)
        if not isinstance(clause_info, dict):
            return cleaned_reference

        if clause_info.get("position_start") == 0:
            cleaned_reference.pop(ancestor_clause_type, None)

        return cleaned_reference

    @staticmethod
    def _extract_document_reference_from_context(reference_context: Dict) -> Optional[Dict]:
        """Extract the document-only portion from a merged ancestor context."""
        for key, value in reference_context.items():
            if key in {"diem", "khoan", "dieu"}:
                continue
            return {key: value.copy()}
        return None

    def _extract_document_references_from_cls_title(
        self,
        cls_title: str,
        doc_types: List[str],
        law_titles: List[str],
    ) -> List[Dict]:
        """Extract unambiguous document references from the current document title."""
        title_scope = {"text": cls_title, "start_pos": 0}
        title_refs, _ = self._extract_doc_references_from_scope(
            scope=title_scope,
            doc_types=doc_types,
            law_titles=law_titles,
            is_title=True,
        )
        if len(title_refs) > 1 and any(
            keyword in cls_title.lower() for keyword in ["sửa đổi", "bổ sung"]
        ):
            title_refs = self._select_amendment_target_references_from_title(
                cls_title=cls_title,
                title_refs=title_refs,
            )
            if not title_refs:
                return []

        doc_references: List[Dict] = []
        seen_keys = set()
        for reference in title_refs:
            doc_reference = self._extract_document_reference_from_context(reference)
            if doc_reference is None:
                continue
            dedup_key = self._dedup_reference_key(doc_reference)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            doc_references.append(doc_reference)

        return doc_references

    def _select_amendment_target_references_from_title(
        self,
        cls_title: str,
        title_refs: List[Dict],
    ) -> List[Dict]:
        """Keep direct title targets, excluding descriptive legal bases."""
        selected_refs: List[Dict] = []
        previous_end = 0

        for reference in title_refs:
            span_start, span_end = self._get_reference_span(reference)
            bridge_text = cls_title[previous_end:span_start]
            prefix_text = cls_title[:span_start]

            if TITLE_DESCRIPTIVE_REFERENCE_BRIDGE_PATTERN.search(bridge_text):
                previous_end = max(previous_end, span_end)
                continue

            if selected_refs:
                selected_refs.append(reference)
            elif TITLE_AMENDMENT_TARGET_PREFIX_PATTERN.search(prefix_text):
                selected_refs.append(reference)

            previous_end = max(previous_end, span_end)

        return selected_refs

    def _select_intro_document_references_for_clause_list(
        self,
        content: str,
        clause_groups: List[Dict],
        doc_references: List[Dict],
    ) -> List[Dict]:
        """Carry an intro document across ``như sau:`` into the following clause list."""
        if not content or not clause_groups or not doc_references:
            return []

        marker = INTRO_DOC_CLAUSE_LIST_MARKER_PATTERN.search(content)
        if marker is None:
            return []

        marker_start = marker.start()
        marker_end = marker.end()
        has_post_intro_clause = any(
            self._get_reference_span(clause_group)[0] >= marker_end
            for clause_group in clause_groups
        )
        if not has_post_intro_clause:
            return []

        return [
            doc_reference
            for doc_reference in doc_references
            if self._get_reference_span(doc_reference)[1] <= marker_start
        ]

    @classmethod
    def _clause_groups_have_complete_article_scope(
        cls,
        clause_groups: List[Dict],
        ancestor_context: Dict,
    ) -> bool:
        """Return True when title fallback would attach to clear article-scoped targets."""
        enriched_groups = cls._apply_ancestor_context_to_clause_groups(
            clause_groups=clause_groups,
            ancestor_context=ancestor_context,
        )
        if not enriched_groups:
            return False

        for group in enriched_groups:
            if "dieu" not in group:
                return False
            if "diem" in group and "khoan" not in group:
                return False

        return True

    @classmethod
    def _self_document_reference_blocks_title_context(
        cls,
        content: str,
        clause_groups: List[Dict],
    ) -> bool:
        """Only block title fallback when ``... này`` locally qualifies the target."""
        match = _DOC_TYPE_NAY_PATTERN.search(content or "")
        if match is None:
            return False
        if not clause_groups:
            return True

        clause_ends = [
            int(value.get("position_end"))
            for group in clause_groups
            for value in group.values()
            if isinstance(value, dict) and value.get("position_end") is not None
        ]
        if not clause_ends:
            return True

        first_clause_end = min(clause_ends)
        if match.start() <= first_clause_end:
            return True

        bridge = content[first_clause_end:match.start()]
        return len(bridge) <= 100

    @classmethod
    def _apply_ancestor_context_to_clause_groups(
        cls,
        clause_groups: List[Dict],
        ancestor_context: Dict
    ) -> List[Dict]:
        """Backfill missing higher-level clause components from ancestor context."""
        if not clause_groups or not ancestor_context:
            return clause_groups

        enriched_groups: List[Dict] = []

        for clause_group in clause_groups:
            enriched_group: Dict = {}
            has_diem = "diem" in clause_group
            has_khoan = "khoan" in clause_group

            if "diem" in clause_group:
                enriched_group["diem"] = clause_group["diem"].copy()

            if "khoan" in clause_group:
                enriched_group["khoan"] = clause_group["khoan"].copy()
            elif has_diem and "khoan" in ancestor_context:
                enriched_group["khoan"] = ancestor_context["khoan"].copy()

            if "dieu" in clause_group:
                enriched_group["dieu"] = clause_group["dieu"].copy()
            elif (has_diem or has_khoan) and "dieu" in ancestor_context:
                enriched_group["dieu"] = ancestor_context["dieu"].copy()

            enriched_groups.append(enriched_group or cls._copy_reference(clause_group))

        return enriched_groups

    def _find_reference_context_from_ancestors(
        self,
        clause_type: Optional[str],
        clause_key: Optional[str],
        data: Optional[List[Dict]],
        child_to_parent: Optional[Dict[str, str]],
        doc_types: List[str],
        clause_types: List[str],
        law_titles: List[str],
        cls_title: Optional[str] = None
    ) -> Dict:
        """Resolve missing higher-level clause and document context from ancestors."""
        ancestor_context: Dict = {}
        if clause_type and clause_key and data and child_to_parent:
            ancestor_keys = self._get_ancestor_keys(
                clause_type=clause_type,
                clause_key=clause_key,
                child_to_parent=child_to_parent,
            )
            for ancestor_key in ancestor_keys:
                ancestor_clause = next(
                    (item for item in data if item.get("com_key") == ancestor_key),
                    None,
                )
                if ancestor_clause is None:
                    continue

                ancestor_mapped_content = ContentExtractor.get_content_with_positions(ancestor_clause)
                ancestor_content = ancestor_mapped_content.text
                if not ancestor_content.strip():
                    continue

                # Extract references from ancestor content
                ancestor_refs = self.extract_references(
                    content=ancestor_content,
                    doc_types=doc_types,
                    clause_types=clause_types,
                    law_titles=law_titles,
                    clause_type=None,
                    clause_key=None,
                    data=None,
                    child_to_parent=None,
                    position_mapper=ancestor_mapped_content.raw_span,
                )
                for reference in ancestor_refs:
                    # Remove leading self-clause component
                    cleaned_reference = self._remove_leading_self_clause_component(
                        reference=reference,
                        ancestor_clause_type=(ancestor_clause.get("com_type") or "").lower(),
                    )

                    # Add clause references to ancestor context
                    for key in ["khoan", "dieu"]:
                        if key in ancestor_context or key not in cleaned_reference:
                            continue
                        ancestor_context[key] = cleaned_reference[key].copy()

                    doc_reference = self._extract_document_reference_from_context(cleaned_reference)
                    if doc_reference is not None:
                        doc_key = next(iter(doc_reference)) # Get the first key (document type)
                        if doc_key not in ancestor_context:
                            ancestor_context[doc_key] = doc_reference[doc_key].copy()

        # Fallback to cls_title if no document reference found in hierarchy
        if cls_title and not self._extract_document_reference_from_context(ancestor_context):
            title_scope = {"text": cls_title, "start_pos": 0}
            title_refs, _ = self._extract_doc_references_from_scope(
                scope=title_scope,
                doc_types=doc_types,
                law_titles=law_titles,
                is_title=True
            )
            if title_refs:
                # A title with multiple candidate laws is ambiguous provenance. Do
                # not silently pick the last title and create a target relation.
                if len(title_refs) > 1 and any(kw in cls_title.lower() for kw in ["sửa đổi", "bổ sung"]):
                    return ancestor_context

                chosen_ref = title_refs[0]
                    
                doc_reference = self._extract_document_reference_from_context(chosen_ref)
                if doc_reference:
                    doc_key = next(iter(doc_reference))
                    if doc_key not in ancestor_context:
                        ancestor_context[doc_key] = doc_reference[doc_key].copy()

        return ancestor_context

    def _find_document_references_from_ancestors(
        self,
        clause_type: Optional[str],
        clause_key: Optional[str],
        data: Optional[List[Dict]],
        child_to_parent: Optional[Dict[str, str]],
        doc_types: List[str],
        clause_types: List[str],
        law_titles: List[str],
        cls_title: Optional[str] = None,
    ) -> List[Dict]:
        """Collect all document references from ancestors for inherited clause targets."""
        doc_references: List[Dict] = []
        seen_keys = set()
        if clause_type and clause_key and data and child_to_parent:
            ancestor_keys = self._get_ancestor_keys(
                clause_type=clause_type,
                clause_key=clause_key,
                child_to_parent=child_to_parent,
            )
            for ancestor_key in ancestor_keys:
                ancestor_clause = next(
                    (item for item in data if item.get("com_key") == ancestor_key),
                    None,
                )
                if ancestor_clause is None:
                    continue

                ancestor_mapped_content = ContentExtractor.get_content_with_positions(ancestor_clause)
                ancestor_content = ancestor_mapped_content.text
                if not ancestor_content.strip():
                    continue

                ancestor_refs = self.extract_references(
                    content=ancestor_content,
                    doc_types=doc_types,
                    clause_types=clause_types,
                    law_titles=law_titles,
                    clause_type=None,
                    clause_key=None,
                    data=None,
                    child_to_parent=None,
                    position_mapper=ancestor_mapped_content.raw_span,
                )
                for reference in ancestor_refs:
                    cleaned_reference = self._remove_leading_self_clause_component(
                        reference=reference,
                        ancestor_clause_type=(ancestor_clause.get("com_type") or "").lower(),
                    )
                    doc_reference = self._extract_document_reference_from_context(cleaned_reference)
                    if doc_reference is None:
                        continue

                    dedup_key = self._dedup_reference_key(doc_reference)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    doc_references.append(doc_reference)

        if cls_title and not doc_references:
            title_scope = {"text": cls_title, "start_pos": 0}
            title_refs, _ = self._extract_doc_references_from_scope(
                scope=title_scope,
                doc_types=doc_types,
                law_titles=law_titles,
                is_title=True,
            )
            if len(title_refs) > 1 and any(
                kw in cls_title.lower() for kw in ["sửa đổi", "bổ sung"]
            ):
                return doc_references

            for reference in title_refs:
                doc_reference = self._extract_document_reference_from_context(reference)
                if doc_reference is None:
                    continue
                dedup_key = self._dedup_reference_key(doc_reference)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                doc_references.append(doc_reference)

        return doc_references

    @staticmethod
    def _find_chuong_ancestor(
        clause_key: Optional[str],
        data: Optional[List[Dict]],
    ) -> Optional[Dict]:
        """Return the nearest chuong entry that precedes clause_key in data."""
        if not clause_key or not data:
            return None
        clause_idx = next(
            (i for i, item in enumerate(data) if item.get("com_key") == clause_key),
            None,
        )
        if clause_idx is None:
            return None
        for i in range(clause_idx - 1, -1, -1):
            if (data[i].get("com_type") or "").lower() == "chuong":
                return data[i]
        return None

    def _extract_doc_references_from_chuong(
        self,
        clause_key: Optional[str],
        data: Optional[List[Dict]],
        doc_types: List[str],
        clause_types: List[str],
        law_titles: List[str],
    ) -> List[Dict]:
        """Extract document references from the nearest chuong ancestor."""
        chuong = self._find_chuong_ancestor(clause_key=clause_key, data=data)
        if chuong is None:
            return []
        # ContentExtractor skips chuong, so read com_title directly.
        chuong_text = (chuong.get("com_title") or "").strip()
        if not chuong_text:
            return []
        chuong_scope = {"text": chuong_text, "start_pos": 0}
        chuong_refs, _ = self._extract_doc_references_from_scope(
            scope=chuong_scope,
            doc_types=doc_types,
            law_titles=law_titles,
            is_title=True,
        )
        if not chuong_refs:
            return []
        if len(chuong_refs) > 1 and any(
            kw in chuong_text.lower() for kw in ["sửa đổi", "bổ sung"]
        ):
            chuong_refs = self._select_amendment_target_references_from_title(
                cls_title=chuong_text,
                title_refs=chuong_refs,
            )
            if not chuong_refs:
                return []
        doc_references: List[Dict] = []
        seen_keys: set = set()
        for reference in chuong_refs:
            doc_reference = self._extract_document_reference_from_context(reference)
            if doc_reference is None:
                continue
            dedup_key = self._dedup_reference_key(doc_reference)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            doc_references.append(doc_reference)
        return doc_references

    def _combine_clause_and_document_references(
        self,
        clause_groups: List[Dict],
        doc_references: List[Dict]
    ) -> List[Dict]:
        """Combine grouped clause components with one or more document references."""
        if not clause_groups:
            return [self._copy_reference(reference) for reference in doc_references]

        def get_reference_span(reference: Dict) -> Tuple[int, int]:
            positions = [
                (value.get("position_start", 0), value.get("position_end", 0))
                for value in reference.values()
                if isinstance(value, dict)
            ]
            if not positions:
                return 0, 0
            return (
                min(start for start, _ in positions),
                max(end for _, end in positions),
            )

        def build_combined_reference(clause_group: Dict, doc_reference: Dict) -> Dict:
            combined_reference: Dict = {}
            for key in ["diem", "khoan", "dieu"]:
                if key in clause_group:
                    combined_reference[key] = clause_group[key].copy()
            combined_reference.update(self._copy_reference(doc_reference))
            return combined_reference

        combined_references: List[Dict] = []
        assigned_doc_indexes = set()

        doc_spans = [get_reference_span(reference) for reference in doc_references]

        for clause_group in clause_groups:
            clause_start, clause_end = get_reference_span(clause_group)
            # "[clause] của [doc]" is the standard forward structure in Vietnamese law.
            # When a forward candidate exists, strongly penalise any preceding doc so it
            # is only chosen when no following doc is available.
            has_forward_candidate = any(clause_end < doc_start for doc_start, _ in doc_spans)
            best_doc_index: Optional[int] = None
            best_gap: Optional[int] = None

            for index, (doc_start, doc_end) in enumerate(doc_spans):
                if clause_end < doc_start:
                    gap = doc_start - clause_end
                elif doc_end < clause_start:
                    gap = clause_start - doc_end
                    if has_forward_candidate:
                        gap += 1000
                else:
                    gap = 0

                if best_gap is None or gap < best_gap:
                    best_gap = gap
                    best_doc_index = index

            if best_doc_index is None:
                combined_references.append(self._copy_reference(clause_group))
                continue

            combined_references.append(
                build_combined_reference(
                    clause_group=clause_group,
                    doc_reference=doc_references[best_doc_index],
                )
            )
            assigned_doc_indexes.add(best_doc_index)

        for index, doc_reference in enumerate(doc_references):
            if index not in assigned_doc_indexes:
                combined_references.append(self._copy_reference(doc_reference))

        combined_references.sort(key=lambda reference: get_reference_span(reference)[0])

        return combined_references

    def _combine_clause_and_each_document_reference(
        self,
        clause_groups: List[Dict],
        doc_references: List[Dict],
    ) -> List[Dict]:
        """Combine every inherited clause target with every inherited document target."""
        combined_references: List[Dict] = []
        seen_keys = set()

        for clause_group in clause_groups:
            for doc_reference in doc_references:
                combined_reference: Dict = {}
                for key in ["diem", "khoan", "dieu"]:
                    if key in clause_group:
                        combined_reference[key] = clause_group[key].copy()
                combined_reference.update(self._copy_reference(doc_reference))

                dedup_key = self._dedup_reference_key(combined_reference)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                combined_references.append(combined_reference)

        combined_references.sort(key=lambda reference: self._get_reference_span(reference)[0])
        return combined_references

    def _select_scope_references(
        self,
        clause_groups: List[Dict],
        doc_references: List[Dict],
        ancestor_doc_references: List[Dict],
    ) -> List[Dict]:
        """Choose which references survive for the current sentence scope."""
        if clause_groups and doc_references:
            return self._combine_clause_and_document_references(
                clause_groups=clause_groups,
                doc_references=doc_references,
            )

        if clause_groups and ancestor_doc_references:
            return self._combine_clause_and_each_document_reference(
                clause_groups=clause_groups,
                doc_references=ancestor_doc_references,
            )

        if clause_groups:
            return clause_groups

        return doc_references

    def _recover_clause_scoped_doc_references_after_cutoff(
        self,
        scope: Dict,
        clause_groups: List[Dict],
        doc_references: List[Dict],
        cutoff_pos: Optional[int],
    ) -> List[Dict]:
        """Recover clause+doc targets that survive skip-zone filtering."""
        if cutoff_pos is None or not clause_groups or not doc_references:
            return []

        scope_text = scope["text"]
        scope_start = scope["start_pos"]
        recovered_references: List[Dict] = []

        for doc_reference in doc_references:
            doc_start, _ = self._get_reference_span(doc_reference)
            if doc_start < cutoff_pos:
                continue

            local_doc_start = doc_start - scope_start
            if not self._has_clause_scoped_prefix(scope_text, local_doc_start):
                continue
            if not (
                self._has_repeal_effective_cue_after_doc(scope_text, local_doc_start)
                or self._has_clause_scoped_amendment_target_prefix(scope_text, local_doc_start)
            ):
                continue

            prefix_start = max(scope_start, doc_start - 120)
            scoped_clause_groups = []
            for clause_group in clause_groups:
                clause_start, clause_end = self._get_reference_span(clause_group)
                if prefix_start <= clause_start and clause_end <= doc_start:
                    scoped_clause_groups.append(clause_group)

            if scoped_clause_groups:
                recovered_references.extend(
                    self._combine_clause_and_document_references(
                        clause_groups=scoped_clause_groups,
                        doc_references=[doc_reference],
                    )
                )

        return recovered_references

    def _recover_post_cutoff_clause_references_with_intro_doc(
        self,
        scope: Dict,
        clause_groups: List[Dict],
        doc_references: List[Dict],
        cutoff_pos: Optional[int],
    ) -> List[Dict]:
        """Backfill an intro document for clause targets after an action cue."""
        if cutoff_pos is None or not clause_groups or not doc_references:
            return []

        scope_text = scope["text"]
        scope_start = scope["start_pos"]
        cutoff_local = cutoff_pos - scope_start
        if cutoff_local < 0 or cutoff_local >= len(scope_text):
            return []
        if POST_INTRO_DOCUMENT_ACTION_PATTERN.search(scope_text[cutoff_local:]) is None:
            return []

        intro_doc_reference = None
        intro_doc_end = -1
        for doc_reference in doc_references:
            doc_start, doc_end = self._get_reference_span(doc_reference)
            if doc_start <= doc_end <= cutoff_pos and doc_end > intro_doc_end:
                intro_doc_reference = doc_reference
                intro_doc_end = doc_end

        if intro_doc_reference is None:
            return []

        post_cutoff_clause_groups = [
            clause_group
            for clause_group in clause_groups
            if self._get_reference_span(clause_group)[0] >= cutoff_pos
        ]
        if not post_cutoff_clause_groups:
            return []

        return self._combine_clause_and_document_references(
            clause_groups=post_cutoff_clause_groups,
            doc_references=[intro_doc_reference],
        )

    def _recover_dinh_chinh_post_intro_clause_references(
        self,
        scope: Dict,
        content: str,
        clause_types: List[str],
        doc_context: Dict,
    ) -> List[Dict]:
        """Recover the first operative clause after a correction intro cut off by title text."""
        intro_end = self._find_dinh_chinh_intro_end(content)
        if intro_end is None:
            return []
        if not (scope["start_pos"] <= intro_end < scope["end_pos"]):
            return []

        post_intro_scope = {
            "text": content[intro_end:scope["end_pos"]],
            "start_pos": intro_end,
            "end_pos": scope["end_pos"],
        }
        clause_matches = self._extract_clause_components_from_scope(
            scope=post_intro_scope,
            clause_types=clause_types,
        )
        clause_groups = self._group_clause_components(clause_matches)
        leading_clause_groups = self._select_leading_dinh_chinh_clause_groups(
            scope=post_intro_scope,
            clause_groups=clause_groups,
        )
        if not leading_clause_groups:
            return []

        return self._combine_clause_and_document_references(
            clause_groups=leading_clause_groups,
            doc_references=[doc_context],
        )

    def _extract_scope_references(
        self,
        scope: Dict,
        content: str,
        clause_context: ClauseContext,
        doc_types: List[str],
        clause_types: List[str],
        law_titles: List[str],
        inherited_doc_reference: Optional[Dict] = None,
        prefer_dinh_chinh_targets: bool = False,
    ) -> List[Dict]:
        """Extract and resolve references for one sentence scope."""
        doc_references, cutoff_pos = self._extract_doc_references_from_scope(
            scope=scope,
            doc_types=doc_types,
            law_titles=law_titles,
        )
        
        # If there is a cutoff position, truncate the scope before the cutoff position
        effective_scope = self._truncate_scope_before_cutoff(scope, cutoff_pos)
        if effective_scope is None:
            return []

        # Extract clause components from the effective scope
        clause_matches = self._extract_clause_components_from_scope(
            scope=effective_scope,
            clause_types=clause_types,
        )

        # Fallback for semicolon-separated lists:
        # If we have clauses but no document reference in this semicolon-scope,
        # search for a document reference in the broader sentence (delimited by . or \n)
        if not doc_references and clause_matches:
            full_sentence_scope = self._get_full_sentence_scope(
                content=content,
                start_pos=scope["start_pos"],
                end_pos=scope["end_pos"]
            )
            # Find doc references in the full sentence
            sentence_doc_references, _ = self._extract_doc_references_from_scope(
                scope=full_sentence_scope,
                doc_types=doc_types,
                law_titles=law_titles
            )
            if sentence_doc_references:
                doc_references = sentence_doc_references

        # Group clause components by their parent clause
        clause_groups = self._group_clause_components(clause_matches)
        clause_groups = self._apply_ancestor_context_to_clause_groups(
            clause_groups=clause_groups,
            ancestor_context=clause_context.ancestor_context,
        )

        recovered_clause_scoped_references: List[Dict] = []
        if cutoff_pos is not None:
            full_clause_matches = self._extract_clause_components_from_scope(
                scope=scope,
                clause_types=clause_types,
            )
            full_clause_groups = self._group_clause_components(full_clause_matches)
            recovered_clause_scoped_references = (
                self._recover_clause_scoped_doc_references_after_cutoff(
                    scope=scope,
                    clause_groups=full_clause_groups,
                    doc_references=doc_references,
                    cutoff_pos=cutoff_pos,
                )
            )
            recovered_clause_scoped_references.extend(
                self._recover_post_cutoff_clause_references_with_intro_doc(
                    scope=scope,
                    clause_groups=full_clause_groups,
                    doc_references=doc_references,
                    cutoff_pos=cutoff_pos,
                )
            )

        ancestor_doc_references = clause_context.ancestor_doc_references
        if inherited_doc_reference:
            inherited_key = self._dedup_reference_key(inherited_doc_reference)
            inherited_from_ancestors = any(
                self._dedup_reference_key(reference) == inherited_key
                for reference in ancestor_doc_references
            )
            doc_contexts = (
                ancestor_doc_references
                if inherited_from_ancestors and ancestor_doc_references
                else [inherited_doc_reference]
            )
        else:
            doc_contexts = ancestor_doc_references

        doc_context = doc_contexts[0] if doc_contexts else None
        dinh_chinh_doc_context = doc_context
        if prefer_dinh_chinh_targets and dinh_chinh_doc_context is None and doc_references:
            dinh_chinh_doc_context = doc_references[0]

        if prefer_dinh_chinh_targets and dinh_chinh_doc_context:
            recovered_clause_scoped_references.extend(
                self._recover_dinh_chinh_post_intro_clause_references(
                    scope=scope,
                    content=content,
                    clause_types=clause_types,
                    doc_context=dinh_chinh_doc_context,
                )
            )

        if prefer_dinh_chinh_targets and clause_groups and dinh_chinh_doc_context:
            leading_clause_groups = self._select_leading_dinh_chinh_clause_groups(
                scope=scope,
                clause_groups=clause_groups,
            )
            if leading_clause_groups:
                return self._combine_clause_and_document_references(
                    clause_groups=leading_clause_groups,
                    doc_references=[dinh_chinh_doc_context],
                )

        if clause_groups and doc_contexts:
            leading_amendment_groups = self._select_leading_amendment_clause_groups(
                scope=scope,
                clause_groups=clause_groups,
            )
            if leading_amendment_groups:
                return self._combine_clause_and_each_document_reference(
                    clause_groups=leading_amendment_groups,
                    doc_references=doc_contexts,
                )

        selected_references = self._select_scope_references(
            clause_groups=clause_groups,
            doc_references=doc_references,
            ancestor_doc_references=doc_contexts,
        )
        if recovered_clause_scoped_references:
            selected_references.extend(recovered_clause_scoped_references)

        return selected_references

    def _collect_unique_reference_mentions(
        self,
        references: List[Dict]
    ) -> List[ReferenceMention]:
        """Collect references once per dedup span while preserving insertion order."""
        raw_mentions: List[ReferenceMention] = []
        seen_dedup_keys = set()

        # Step 1: Basic deduplication as before
        for reference in references:
            mention = ReferenceMention.from_reference(reference)
            if mention.dedup_key in seen_dedup_keys:
                continue
            seen_dedup_keys.add(mention.dedup_key)
            raw_mentions.append(mention)

        # Step 2: Identify document spans that are already part of a "rich" reference (clause + doc)
        covered_doc_spans = set()
        clause_keys = {"dieu", "khoan", "diem"}
        
        for mention in raw_mentions:
            ref = mention.reference
            has_clauses = any(k in clause_keys for k in ref)
            if has_clauses:
                clause_starts = [
                    v.get("position_start")
                    for k, v in ref.items()
                    if k in clause_keys and isinstance(v, dict)
                ]
                first_clause_start = min(clause_starts) if clause_starts else None
                for k, v in ref.items():
                    if k not in clause_keys and isinstance(v, dict):
                        doc_start = v.get("position_start")
                        if (
                            first_clause_start is not None
                            and doc_start is not None
                            and doc_start < first_clause_start
                        ):
                            continue
                        covered_doc_spans.add((doc_start, v.get("position_end")))

        # Step 3: Filter out document-only references if their span is already covered
        final_mentions: List[ReferenceMention] = []
        for mention in raw_mentions:
            ref = mention.reference
            if len(ref) == 1:
                k = next(iter(ref))
                v = ref[k]
                if k not in clause_keys and isinstance(v, dict):
                    span = (v.get("position_start"), v.get("position_end"))
                    if span in covered_doc_spans:
                        continue # Skip redundant doc-only reference
            
            final_mentions.append(mention)

        return final_mentions

    def _get_full_sentence_scope(self, content: str, start_pos: int, end_pos: int) -> Dict:
        """
        Find the boundaries of a 'True Sentence' (delimited by . or \n) 
        around the current segment (ignoring semicolons).
        """
        # Find the start of the true sentence by looking for . or \n before start_pos
        sent_start = -1
        for separator in (".", "\n"):
            pos = content.rfind(separator, 0, start_pos)
            if pos > sent_start:
                sent_start = pos
        
        sent_start = 0 if sent_start == -1 else sent_start + 1
        
        # Find the end of the true sentence by looking for . or \n after end_pos
        sent_end = len(content)
        for separator in (".", "\n"):
            pos = content.find(separator, end_pos)
            if pos != -1 and pos < sent_end:
                sent_end = pos
        
        return {
            "text": content[sent_start:sent_end],
            "start_pos": sent_start,
            "end_pos": sent_end
        }

    def _recover_bare_conjoined_numbered_references(
        self,
        scope_text: str,
        scope_start: int,
        references: List[Dict],
    ) -> List[Dict]:
        """Recover same-type targets written as 'và số ...' after an explicit reference."""
        if not references:
            return references

        ordered_references = sorted(references, key=self._reference_start)
        recovered_references: List[Dict] = []

        for index, reference in enumerate(ordered_references):
            doc_items = [
                (key, value)
                for key, value in reference.items()
                if isinstance(value, dict) and key not in {"diem", "khoan", "dieu"}
            ]
            if len(doc_items) != 1:
                continue

            doc_type_key, previous_doc = doc_items[0]
            if doc_type_key in LAW_LIKE_TYPES:
                continue

            previous_info = previous_doc.get("information", "")
            doc_type_text_match = re.match(
                r"^\s*(?P<doc_type>.+?)\s+số\b",
                previous_info,
                re.IGNORECASE,
            )
            previous_end = previous_doc.get("position_end")
            if doc_type_text_match is None or previous_end is None:
                continue

            previous_end_local = previous_end - scope_start
            if previous_end_local < 0 or previous_end_local >= len(scope_text):
                continue

            next_reference_start = (
                self._reference_start(ordered_references[index + 1]) - scope_start
                if index + 1 < len(ordered_references)
                else len(scope_text)
            )
            if next_reference_start <= previous_end_local:
                continue

            search_text = scope_text[previous_end_local:next_reference_start]
            doc_type_text = doc_type_text_match.group("doc_type").strip()
            for bare_match in BARE_CONJOINED_NUMBERED_REFERENCE_PATTERN.finditer(search_text):
                bare_start_local = previous_end_local + bare_match.start("marker")
                bare_candidate = scope_text[bare_start_local:next_reference_start]
                number_match = self._find_doc_number_match(bare_candidate, doc_type_key)
                if number_match is None or number_match.start() > 8:
                    continue

                number_end = number_match.end()
                date_match = self._find_date_or_year_match(bare_candidate, number_end)
                info_end_local = bare_start_local + number_end
                date_text = ""
                if date_match is not None:
                    info_end_local += date_match.end()
                    date_text = date_match.group(0)

                raw_number = number_match.group(0)
                normalized_number = re.sub(r"\s*-\s*", "-", raw_number)
                normalized_number = re.sub(r"\s*/\s*", "/", normalized_number)
                normalized_number = re.sub(r"^số\s*", "", normalized_number, flags=re.IGNORECASE)
                normalized_number = re.sub(r"\s+", " ", normalized_number).strip()
                information = f"{doc_type_text} số {normalized_number}{date_text}".strip()

                recovered_references.append({
                    doc_type_key: {
                        "information": information,
                        "position_start": scope_start + bare_start_local,
                        "position_end": scope_start + info_end_local,
                    }
                })

        if not recovered_references:
            return references

        return sorted([*references, *recovered_references], key=self._reference_start)

    def _recover_attached_appendix_clause_doc_references(
        self,
        content: str,
        references: List[Dict],
    ) -> List[Dict]:
        """Recover clause targets tied to an appendix/form attached to a later decree."""
        if not (
            re.search(
                r"^\s*(?:[a-zđ]\)\s*)?quy\s+định\s+việc\b",
                content or "",
                re.IGNORECASE,
            )
            and re.search(
                r"\bbằng\s+quy\s+định\s+tại\b",
                content or "",
                re.IGNORECASE,
            )
        ):
            return references

        recovered_references: List[Dict] = []
        seen_keys = {self._dedup_reference_key(reference) for reference in references}

        for match in ATTACHED_APPENDIX_CLAUSE_DOC_PATTERN.finditer(content or ""):
            reference = {
                "diem": {
                    "information": match.group("diem"),
                    "position_start": match.start("diem"),
                    "position_end": match.end("diem"),
                },
                "khoan": {
                    "information": match.group("khoan"),
                    "position_start": match.start("khoan"),
                    "position_end": match.end("khoan"),
                },
                "dieu": {
                    "information": match.group("dieu"),
                    "position_start": match.start("dieu"),
                    "position_end": match.end("dieu"),
                },
                "nghidinh": {
                    "information": re.sub(r"\s+", " ", match.group("nghidinh")).strip(),
                    "position_start": match.start("nghidinh"),
                    "position_end": match.end("nghidinh"),
                },
            }
            dedup_key = self._dedup_reference_key(reference)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            recovered_references.append(reference)

        if not recovered_references:
            return references

        return sorted([*references, *recovered_references], key=self._reference_start)

    def _recover_amendment_law_count_clause_references(
        self,
        content: str,
        references: List[Dict],
    ) -> List[Dict]:
        """Recover titles like 'khoan 1 Dieu 6 Luat sua doi ... 37 Luat ...'."""
        recovered_references: List[Dict] = []
        recovered_spans: List[Tuple[int, int]] = []

        for match in AMENDMENT_LAW_COUNT_CLAUSE_PATTERN.finditer(content or ""):
            reference = {
                "khoan": {
                    "information": match.group("khoan"),
                    "position_start": match.start("khoan"),
                    "position_end": match.end("khoan"),
                },
                "dieu": {
                    "information": match.group("dieu"),
                    "position_start": match.start("dieu"),
                    "position_end": match.end("dieu"),
                },
                "luat": {
                    "information": match.group("luat").strip(" ,"),
                    "position_start": match.start("luat"),
                    "position_end": match.start("luat") + len(match.group("luat").strip(" ,")),
                },
            }
            recovered_references.append(reference)
            recovered_spans.append(self._get_reference_span(reference))

        if not recovered_references:
            return references

        filtered_references: List[Dict] = []
        for reference in references:
            if any(key in self.CLAUSE_COMPONENT_KEYS for key in reference):
                filtered_references.append(reference)
                continue

            ref_start, ref_end = self._get_reference_span(reference)
            if any(start <= ref_start and ref_end <= end for start, end in recovered_spans):
                continue

            filtered_references.append(reference)

        return sorted(
            [*filtered_references, *recovered_references],
            key=self._reference_start,
        )

    def _extract_doc_references_from_scope(
        self,
        scope: Dict,
        doc_types: List[str],
        law_titles: List[str],
        is_title: bool = False
    ) -> Tuple[List[Dict], Optional[int]]:
        """
        Extract document references from every single scope.

        Rules:
        1. Primary document is the first doc_type match that has enough information
        2. If a trigger appears after a reference, enter skip mode.
        3. In skip mode, only keep references that:
            - Have their own trigger (marking a new primary)
            - OR have a specific title (keeping high-value laws even if they follow a trigger).
        """
        scope_text: str = scope["text"]
        scope_start: int = scope["start_pos"]

        # Step 1: Find all doc_type matches in scope
        doc_type_matches: List[Dict] = []
        for doc_type in doc_types:
            doc_type_variants = {doc_type, doc_type.upper()}
            pattern = (
                r"(?<!\w)(?:"
                + "|".join(re.escape(variant) for variant in doc_type_variants)
                + r")(?!\w)"
            )
            for m in re.finditer(pattern, scope_text):
                doc_type_matches.append({
                    "doc_type_text": m.group(),
                    "doc_type_key":  self._normalize_doc_type_key(m.group()),
                    "start":         m.start(),
                    "end":           m.end(),
                })

        if not doc_type_matches:
            return [], None

        doc_type_matches.sort(key=lambda x: (x["start"], -x["end"]))
        longest_doc_type_matches: List[Dict] = []
        seen_doc_type_starts = set()
        for match_info in doc_type_matches:
            if match_info["start"] in seen_doc_type_starts:
                continue
            longest_doc_type_matches.append(match_info)
            seen_doc_type_starts.add(match_info["start"])
        doc_type_matches = longest_doc_type_matches

        # Early filtering: remove doc_type matches that are self-references like "Thông tư này"
        doc_type_matches = self._filter_self_reference_doc_types(scope_text, doc_type_matches)
        doc_type_matches = [
            match_info
            for match_info in doc_type_matches
            if not self._is_non_document_doc_type_context(scope_text, match_info)
        ]

        # Step 2: Build references with dynamic skip-zone logic
        references: List[Dict] = []
        skip_mode = False # Are we currently in a subordinate zone?
        final_cutoff_pos: Optional[int] = None 
        processed_indices = set()
        last_processed_end = 0

        for idx, match_info in enumerate(doc_type_matches):
            if idx in processed_indices:
                continue

            local_start = match_info["start"]
            doc_type_key = match_info["doc_type_key"]
            
            # Identify if the current match is preceded by a subordinate trigger 
            # relative to the previous reference in this scope.
            bridge_from_prev = scope_text[last_processed_end:local_start]
            is_subordinate_bridge = (
                idx > 0 and 
                SUBORDINATE_TRIGGER_PATTERN.search(bridge_from_prev) is not None
            )

            # Initially, consider text up to the next match
            next_match_start = (
                doc_type_matches[idx + 1]["start"]
                if idx + 1 < len(doc_type_matches)
                else len(scope_text)
            )

            # If this matches an amending law title pattern (e.g. "Luật sửa đổi, bổ sung..."),
            # it will likely contain multiple document type markers for the laws being amended.
            # In such cases, we allow the candidate text to span across subsequent matches 
            # and let the title matching logic find the true boundary (stop phrases like 'số', 'ngày').
            is_amending_continuation = False
            if (
                not is_title
                and doc_type_key in LAW_LIKE_TYPES
                and idx + 1 < len(doc_type_matches)
            ):
                bridge_text = scope_text[match_info["end"]:next_match_start]
                # Swallowing should only happen for standard patterns like "sửa đổi, bổ sung... của".
                # Avoid swallowing across long descriptive bridges that often signal the start of a target list.
                if CLEAN_TITLE_CONTINUATION_PATTERN.match(bridge_text):
                    is_amending_continuation = True

            current_candidate_end = len(scope_text) if is_amending_continuation else next_match_start
            candidate_text = scope_text[local_start:current_candidate_end]
            if not candidate_text.strip():
                continue

            # Extract full info part within this candidate segment
            number_match = self._find_doc_number_match(candidate_text, doc_type_key)

            # Drop a captured number that is actually a form/template code
            # ("… theo Mẫu số 29-TTr"): a form identifier is not a document
            # number. Without it a non-law reference fails _is_valid_primary.
            if number_match is not None and FORM_IDENTIFIER_PREFIX_PATTERN.search(
                candidate_text[:number_match.start()]
            ):
                number_match = None

            title_match: Optional[Tuple[int, int, str]] = None
            if doc_type_key in LAW_LIKE_TYPES:
                title_match = self._find_title_match_advanced(candidate_text, law_titles)
                # title_match = self._find_title_match(candidate_text, law_titles)
                # if title_match is None:
                #     title_match = self._find_fallback_law_title_match(  
                #         candidate_text,
                #         match_info["doc_type_text"],
                #     )

            # Check if the document is valid
            if not self._is_valid_primary(
                doc_type_key=doc_type_key,
                document_number_match=number_match,
                title_match=title_match
            ):
                continue

            # Take the max position of title and document number, then find date or year
            provisional_info_end = max(
                title_match[1] if title_match is not None else 0,
                number_match.end() if number_match is not None else 0,
            )
            # Return date or year match after provisional_info_end
            date_match = self._find_date_or_year_match(candidate_text, provisional_info_end)

            # Determine the end position of the current segment
            info_end = provisional_info_end
            if date_match is not None:
                info_end += date_match.end()

            information = candidate_text[:info_end].strip(" ,") # Remove trailing spaces and commas
            
            # Intercept and truncate if parentheses are found, as they usually indicate 
            # abbreviations or separate notes that shouldn't be in the core information.
            # This also prevents swallowing subsequent document mentions.
            paren_match = re.search(r"[\(\)]", information)
            if paren_match:
                information = information[:paren_match.start()].strip(" ,")

            if doc_type_key in LAW_LIKE_TYPES and number_match is not None:
                number_end = number_match.end()
                numbered_law_prefix = information[:number_end]
                if re.match(r"^\s*Luật\s+số\s+\d", numbered_law_prefix, re.IGNORECASE):
                    subordinate_match = SUBORDINATE_TRIGGER_PATTERN.search(
                        information[number_end:]
                    )
                    if subordinate_match:
                        information = information[
                            :number_end + subordinate_match.start()
                        ].strip(" ,")

            if doc_type_key in LAW_LIKE_TYPES:
                information = self._trim_generic_other_law_tail(information)

            if number_match is not None:
                raw_number = number_match.group(0)
                normalized_number = re.sub(r"\s*-\s*", "-", raw_number)
                normalized_number = re.sub(r"\s*/\s*", "/", normalized_number)
                normalized_number = re.sub(r"\s+", " ", normalized_number).strip()
                if normalized_number != raw_number:
                    information = information.replace(raw_number, normalized_number, 1)

            if not information:
                continue

            # Check if there is a trigger phrase immediately after this reference
            text_after_ref = candidate_text[info_end:]
            trigger_offset = self._find_subordinate_cutoff(text_after_ref)
            has_trigger_after = trigger_offset is not None

            # Decision logic
            should_keep = False 
            if not skip_mode: 
                # The reference is beginning of the scope or a primary document: always keep
                should_keep = True 
            else:
                # We are in a skip zone (e.g. following 'sửa đổi, bổ sung')
                # Exit skip mode ONLY if we find a trigger AFTER this doc AND 
                # the bridge BEFORE it was not subordinate.
                if has_trigger_after and not is_subordinate_bridge:
                    should_keep = True 
                    skip_mode = False 
                elif (
                    self._has_clause_scoped_prefix(scope_text, local_start)
                    and self._has_repeal_effective_cue_after_doc(scope_text, local_start)
                ):
                    should_keep = True
                elif (
                    self._has_clause_scoped_prefix(scope_text, local_start)
                    and self._has_clause_scoped_amendment_target_prefix(scope_text, local_start)
                ):
                    should_keep = True
                elif self._is_list_item_document_reference(scope_text, local_start):
                    should_keep = True
                elif (
                    self._has_direct_action_reference_bridge(bridge_from_prev)
                ):
                    should_keep = True
                    skip_mode = False
                elif (
                    references
                    and doc_type_key in LAW_LIKE_TYPES
                    and not self._has_amendment_history_prefix(scope_text, local_start)
                    and self._is_conjoined_same_type_reference(
                        scope_text=scope_text,
                        scope_start=scope_start,
                        previous_reference=references[-1],
                        doc_type_key=doc_type_key,
                        local_start=local_start,
                    )
                ):
                    should_keep = True
                elif (
                    references
                    and doc_type_key not in LAW_LIKE_TYPES
                    and self._is_conjoined_same_type_reference(
                        scope_text=scope_text,
                        scope_start=scope_start,
                        previous_reference=references[-1],
                        doc_type_key=doc_type_key,
                        local_start=local_start,
                    )
                ):
                    should_keep = True
                elif (
                    references
                    and doc_type_key not in LAW_LIKE_TYPES
                    and number_match is not None
                    and not self._has_amendment_history_prefix(scope_text, local_start)
                    and self._is_conjoined_action_target_reference(
                        scope_text=scope_text,
                        scope_start=scope_start,
                        previous_reference=references[-1],
                        local_start=local_start,
                    )
                ):
                    should_keep = True
                elif title_match is not None and not is_subordinate_bridge:
                    # Only keep high-value named documents in skip zone.
                    # Skip generic numbered documents like "Nghị định số 123/2024/NĐ-CP"
                    title_str = title_match[2]
                    
                    doc_types_pattern = "|".join(re.escape(dt) for dt in doc_types)
                    is_generic_numbered = re.search(
                        rf"^(?:{doc_types_pattern})\s+số\s+\d+", 
                        title_str, 
                        re.IGNORECASE
                    ) is not None
                    
                    is_patch_keyword = any(kw in title_str.lower() for kw in ["sửa đổi", "bổ sung"])
                    
                    if not is_generic_numbered and not is_patch_keyword:
                        # If this is the ONLY document reference after the 
                        # first subordinate trigger in this scope, discard it.
                        # Logic: Check if there are other valid documents in the skip zone.
                        
                        has_others_in_skip_zone = False
                        # 1. Check backward: Any references already added to 'references' list within the skip zone?
                        for r in references:
                            r_start = min(v.get("position_start", 0) for v in r.values() if isinstance(v, dict))
                            if final_cutoff_pos is not None and r_start >= final_cutoff_pos:
                                has_others_in_skip_zone = True
                                break
                        
                        # 2. Check forward: Any future matches in doc_type_matches that are valid primaries?
                        if not has_others_in_skip_zone:
                            for future_idx in range(idx + 1, len(doc_type_matches)):
                                fm = doc_type_matches[future_idx]
                                f_next = doc_type_matches[future_idx + 1]["start"] if future_idx + 1 < len(doc_type_matches) else len(scope_text)
                                f_candidate = scope_text[fm["start"]:f_next]
                                f_num = self._find_doc_number_match(f_candidate, fm["doc_type_key"])
                                f_title = None
                                if fm["doc_type_key"] in LAW_LIKE_TYPES:
                                    f_title = self._find_title_match_advanced(f_candidate, law_titles)
                                
                                if self._is_valid_primary(fm["doc_type_key"], f_num, f_title):
                                    has_others_in_skip_zone = True
                                    break
                                    
                        should_keep = has_others_in_skip_zone
                    else:
                        should_keep = False
                else: 
                    should_keep = False

            
            if is_title:
                should_keep = True

            if should_keep:
                info_start_global = scope_start + local_start
                info_end_global   = info_start_global + len(information)

                references.append({
                    doc_type_key: {
                        "information":    information,
                        "position_start": info_start_global,
                        "position_end":   info_end_global,
                    }
                })

                # Mark subsequent matches as already 'consumed' if they fall within this reference span
                reference_end_local = local_start + len(information)
                for next_idx in range(idx + 1, len(doc_type_matches)):
                    if doc_type_matches[next_idx]["start"] < reference_end_local:
                        processed_indices.add(next_idx)

                # If this primary has a trigger, enter skip mode
                if has_trigger_after:
                    if not skip_mode:
                        skip_mode = True 
                        # Use the first trigger encountered in a primary chain for the cutoff
                        if final_cutoff_pos is None:
                            final_cutoff_pos = info_end_global + trigger_offset

            # Advance tracking to the end of the current reference
            last_processed_end = local_start + info_end

        references = self._recover_bare_conjoined_numbered_references(
            scope_text=scope_text,
            scope_start=scope_start,
            references=references,
        )
        return references, final_cutoff_pos

    @staticmethod
    def _mask_amendment_provenance_parentheticals(content: str) -> str:
        """Blank out "(được sửa đổi, bổ sung bởi …)" provenance notes in place.

        Replaces each matched parenthetical with an equal-length run of spaces so
        the inner document/clause references disappear from extraction while every
        surrounding reference keeps its original character offsets.
        """
        if "(" not in content:
            return content

        def _blank(match: "re.Match[str]") -> str:
            return " " * (match.end() - match.start())

        return AMENDMENT_PROVENANCE_PARENTHETICAL_PATTERN.sub(_blank, content)

    def extract_references(
        self,
        content: str,
        doc_types: List,
        clause_types: List,
        law_titles: List,
        clause_type: Optional[str] = None,
        clause_key: Optional[str] = None,
        data: Optional[List[Dict]] = None,
        child_to_parent: Optional[Dict[str, str]] = None,
        cls_title: Optional[str] = None,
        position_mapper: Optional[Callable[[int, int], Optional[Tuple[int, int]]]] = None,
    ) -> List[Dict]:
        """Extract references from sentence scopes, including clause hierarchy context."""
        if not content or not content.strip():
            return []

        # Step 0: Neutralise amendment-provenance parentheticals so their inner
        # references cannot be mistaken for the operative target. Length-preserving
        # so every other reference keeps its original offsets.
        content = self._mask_amendment_provenance_parentheticals(content)

        # Step 1: Build clause context
        clause_context = self._build_clause_context(
            content=content,
            doc_types=doc_types,
            clause_type=clause_type,
            clause_key=clause_key,
            data=data,
            child_to_parent=child_to_parent,
            clause_types=clause_types,
            law_titles=law_titles,
            cls_title=cls_title,
        )
        collected_references: List[Dict] = []
        active_doc_reference = clause_context.ancestor_doc_reference
        dinh_chinh_intro_end = self._find_dinh_chinh_intro_end(content)
        prefer_dinh_chinh_targets = (
            self._is_dinh_chinh_reference_context(content)
            or (
                active_doc_reference is not None
                and self._is_dinh_chinh_correction_target_scope(content)
            )
        )

        # Step 2: Extract references from each sentence scope
        for scope in clause_context.sentence_scopes:
            scope_references = self._extract_scope_references(
                scope=scope,
                content=content,
                clause_context=clause_context,
                doc_types=doc_types,
                clause_types=clause_types,
                law_titles=law_titles,
                inherited_doc_reference=active_doc_reference,
                prefer_dinh_chinh_targets=prefer_dinh_chinh_targets,
            )
            collected_references.extend(scope_references)

            if (
                dinh_chinh_intro_end is not None
                and scope["start_pos"] < dinh_chinh_intro_end
            ):
                for reference in scope_references:
                    if any(key in self.CLAUSE_COMPONENT_KEYS for key in reference):
                        continue
                    doc_reference = self._extract_document_reference_from_context(reference)
                    if doc_reference is not None:
                        active_doc_reference = doc_reference
                        break

        # Step 3: Collect unique reference mentions
        mentions = self._collect_unique_reference_mentions(collected_references)
        
        # Step 4: Finalize reference mentions
        references = [self._copy_reference(mention.reference) for mention in mentions]
        references = [
            reference
            for reference in references
            if not self._is_self_document_reference(reference)
            and self._is_valid_reference(reference, doc_types)
        ]
        references = self._recover_amendment_law_count_clause_references(
            content=content,
            references=references,
        )
        references = self._recover_attached_appendix_clause_doc_references(
            content=content,
            references=references,
        )
        references.sort(
            key=lambda reference: min(
                value.get("position_start", 0)
                for value in reference.values()
                if isinstance(value, dict)
            )
        )
        if position_mapper is not None:
            references = [
                self._apply_raw_positions(reference, position_mapper)
                for reference in references
            ]
        return references

