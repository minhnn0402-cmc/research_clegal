import functools
import re
from typing import Dict, List, Optional

from src.domain.extractors.relation_type_rules import (
    COMPILED_FORWARD_PATTERNS,
    COMPILED_PASSIVE_PATTERNS,
    SEGMENT_DELIMITER_PATTERN,
    SCOPE_DELIMITERS,
    DAN_CHIEU_EXCLUSIONS,
    DAN_CHIEU_DESCRIPTIVE_ACTION_EXCLUSIONS,
    COMPILED_THAY_THE_EDGE_CASE_PATTERN,
    COMPILED_BAI_BO_EDGE_CASE_PATTERN
)

from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared, unidecode
from src.domain.extractors.distractor_filter import DistractorFilter
from src.infrastructure.config import ConfigLoader
from src.domain.extractors.base_extractor_flow.relation_type_edge_cases import (
    RelationTypeEdgeCases,
    _DAN_CHIEU_PHRASE_AMENDMENT_SCOPE_PATTERN,
    _AMENDMENT_REPLACEMENT_DETAIL_PREFIX_PATTERN,
    _CHILD_SCOPE_QUY_DINH_VE_PATTERN,
    _THEO_QUY_DINH_TAI_CLAUSE_PATTERN,
    _THEO_QUY_DINH_TAI_MARKER_PATTERN,
    _DAN_CHIEU_BACKWARD_EFFECTIVE_CUE_PATTERN,
    _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES,
)

_DISTRACTOR_FILTER = DistractorFilter()

@functools.lru_cache(maxsize=1)
def _get_doc_types() -> List[str]:
    return ConfigLoader().doc_clause_types.get("doc_types") or []

_BO_SUNG_WORD_PHRASE_SCOPE_PATTERN = re.compile(
    r"\bBổ\s+sung\s+(?:cụm\s+)?từ\b",
    re.IGNORECASE,
)
# "[thủ tục hành chính | nội dung | …] (đã/được) (công bố|quy định|ban hành kèm
# theo) tại [các] <docs> … hết hiệu lực": the sub-content published in the listed
# documents is superseded, so each listed document is partially amended
# (sua_doi_bo_sung) — not wholly replaced. This distinguishes the construction
# from a whole-document expiry ("Quyết định X hết hiệu lực …" → thay_the) and lets
# the relation distribute across every document in the list instead of collapsing
# to the one nearest the expiry cue.
# Only the sub-content locative is matched here; the expiry ("hết hiệu lực") is
# already confirmed by the edge cue this override is gated on, so it need not be
# re-matched (which would otherwise have to span the whole document list).
_CONTENT_EXPIRY_SDBS_PATTERN = re.compile(
    r"(?:thủ\s+tục\s+hành\s+chính|các\s+thủ\s+tục|một\s+số\s+thủ\s+tục|"
    r"danh\s+mục\s+thủ\s+tục|nội\s+dung)"
    r".{0,80}?(?:đã\s+|được\s+)?(?:công\s+bố|quy\s+định|ban\s+hành\s+kèm\s+theo)\s+tại",
    re.IGNORECASE | re.DOTALL,
)
# "Việc sửa đổi, bổ sung, thay thế, bãi bỏ ... thực hiện theo quy định tại [ref]"
# The action keywords are SUBJECT MATTER regulated by the cited clause, not actions of
# this document.  Any action relation type that appears before "thực hiện theo quy định tại"
# and whose first reference appears after it must be converted to dan_chieu.
_THUC_HIEN_THEO_QUY_DINH_TAI_PATTERN = re.compile(
    r"\bthực\s+hiện\s+theo\s+(?:các\s+)?quy\s+định\s+(?:tại|của)\b",
    re.IGNORECASE,
)
# Generalised form of the pattern above: any standard Vietnamese legal citation cue
# in the bridge from action_end to first_ref means the reference is the LEGAL BASIS
# (căn cứ pháp lý), not the action target → convert to dan_chieu.
# Intentionally omits {doc_clause_types} because the doc/clause type IS the first_ref
# itself — it is not part of the bridge text.
_CITATION_CUE_PREFIX_PATTERN = re.compile(
    r"\btheo\s+(?:đúng\s+)?(?:(?:các|những)\s+)?quy\s+định\s+(?:tại|của)\b"
    r"|\bquy\s+định\s+tại\b"
    r"|\bđược\s+quy\s+định\s+(?:tại|trong)\b"
    r"|\bphù\s+hợp\s+với\b"
    r"|\btrái\s+với\b"
    r"|\bmâu\s+thuẫn\s+với\b"
    r"|\bvi\s+phạm\b",
    re.IGNORECASE,
)
@functools.lru_cache(maxsize=1)
def _get_nay_internal_scope_pattern() -> re.Pattern:
    """Compile '<doc/clause type> này' pattern from YAML config at first call.

    Detects internal self-references like "Điều này", "khoản 1 Điều này",
    "Luật này". When an action relation fires and the sentence scope contains
    only such refs (no external document target), the action is noise.
    """
    config = ConfigLoader().doc_clause_types
    doc_types: List[str] = config.get("doc_types") or []
    clause_types: List[str] = config.get("clause_types") or []
    all_types = doc_types + clause_types
    escaped = [r"\s+".join(re.escape(w) for w in t.split()) for t in all_types]
    return re.compile(
        r"\b(?:" + "|".join(escaped) + r")\s+này\b",
        re.IGNORECASE,
    )
_BAI_BO_DINH_CHI_INTRO_PATTERN = re.compile(
    r"đình\s+chỉ\s+việc\s+thi\s+hành.{0,120}bãi\s+bỏ.{0,160}theo\s+quy\s+định\s+tại",
    re.IGNORECASE | re.DOTALL,
)
_CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN = re.compile(
    r"\btiếp\s+tục\s+thực\s+hiện\s+theo\s+quy\s+định\s+(?:của|tại)\b",
    re.IGNORECASE,
)
_ATTACHED_LIST_AMENDMENT_CUE_PATTERN = re.compile(
    r"\bhủy\s+bỏ\s+(?:toàn\s+bộ\s+)?(?:danh\s+mục|phụ\s+lục|nội\s+dung|"
    r"dự\s+án|công\s+trình)\b.{0,180}\bban\s+hành\s+kèm\s+theo\b",
    re.IGNORECASE | re.DOTALL,
)
_ATTACHED_NUMBERED_ITEM_REPEAL_CUE_PATTERN = re.compile(
    r"\bhủy\s+bỏ\s+(?:\d+|một\s+số|các)\s+"
    r"(?:dự\s+án|công\s+trình|nội\s+dung)\b"
    r".{0,180}\bban\s+hành\s+kèm\s+theo\b",
    re.IGNORECASE | re.DOTALL,
)
_ATTACHED_MATERIAL_ACTION_REFERENCE_PATTERN = re.compile(
    r"\b(?:bãi\s+bỏ|hủy\s+bỏ|thay\s+thế)\s+(?:các\s+)?"
    r"(?:mẫu(?:\s+số)?|danh\s+mục|phụ\s+lục|biểu\s+mẫu)\b"
    r".{0,220}\bkèm\s+theo\b",
    re.IGNORECASE | re.DOTALL,
)
# "Bãi bỏ / thay thế [nội dung | quy chế] … (công bố tại | ban hành kèm theo) <doc>":
# only some content published in / attached to the target document is removed or
# replaced, i.e. the target is partially amended (sua_doi_bo_sung), not wholly
# repealed/replaced. Distinct from "bãi bỏ <Điều/khoản> của <doc>", which is a
# genuine bai_bo of that provision.
_CONTENT_PUBLISHED_AMEND_PATTERN = re.compile(
    r"\b(?:bãi\s+bỏ|thay\s+thế)\s+(?:một\s+phần\s+|toàn\s+bộ\s+)?"
    r"(?:nội\s+dung|quy\s+chế)\b"
    r".{0,120}?\b(?:(?:đã\s+)?công\s+bố\s+tại|ban\s+hành\s+kèm\s+theo)\b",
    re.IGNORECASE | re.DOTALL,
)
_KEO_DAI_EXPLICIT_DAN_CHIEU_CUE_PATTERN = re.compile(
    r"\bthuc\s+hien\s+theo\s+(?:(?:cac\s+)?quy\s+dinh\s+(?:tai|cua)\s+)?"
    r"(?:nghi\s+quyet|quyet\s+dinh|thong\s+tu|nghi\s+dinh|luat)\b",
    re.IGNORECASE,
)
_DINH_CHINH_POST_INTRO_OPERATION_PATTERN = re.compile(
    r"\bđính\s+chính\b.{0,360}\bnhư\s+sau\s*:\s*$",
    re.IGNORECASE | re.DOTALL,
)
_DINH_CHINH_CONTENT_INTEGRATION_PATTERN = re.compile(
    r"\bnội\s+dung\s+đính\s+chính\s+tại\s+(?:điểm|khoản|điều)\b"
    r".{0,220}\blà\s+một\s+phần\s+không\s+tách\s+rời\b",
    re.IGNORECASE | re.DOTALL,
)
_DEFINITION_REPLACEMENT_SCOPE_PATTERN = re.compile(
    r"^\s*(?:[a-zđ]\)\s*)?quy\s+định\s+việc\b",
    re.IGNORECASE,
)
_DEFINITION_REPLACEMENT_BY_PATTERN = re.compile(
    r"\bbằng\s+quy\s+định\s+tại\b",
    re.IGNORECASE,
)

class RelationTypeExtraction(RelationTypeEdgeCases):
    """Relation type extraction."""

    def extract_relation_types(
        self,
        content: str,
        references: List[Dict],
        parent_content: Optional[str] = None,
        grandparent_content: Optional[str] = None,
        clause_type: Optional[str] = None,
        rejected_buffer: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """
        Extract relation keywords matching forward relation logic.
        
        Args: 
            content: Content of the current clause
            references: List of references extracted beforehand
            parent_content: Content of the parent clause
            grandparent_content: Content of the grandparent clause
        
        Returns:
            List of dictionaries with extracted relation keywords
        """
        if not content or not content.strip():
            return []

        if not references:
            # Must have references to extract relation types
            return []

        # 1. Extract all matches using regex
        all_matches = []
        for rel_type, patterns in COMPILED_FORWARD_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    all_matches.append({
                        "relation_type": rel_type,
                        "hint_group": "forward_hints",
                        "position_start": match.start(),
                        "position_end": match.end(),
                        "text": match.group(0),
                        "direction": "FORWARD"
                    })

        for rel_type, patterns in COMPILED_PASSIVE_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    all_matches.append({
                        "relation_type": rel_type,
                        "hint_group": "passive_voice_relation_types",
                        "position_start": match.start(),
                        "position_end": match.end(),
                        "text": match.group(0),
                        "direction": "PASSIVE"
                    })

        # Sort to prioritize longer matches (if start is the same, end is larger)
        all_matches.sort(key=lambda x: (x["position_start"], -x["position_end"]))

        # 2. Filter out overlapping matches
        filtered_matches = []
        last_end = -1
        for m in all_matches:
            if m["position_start"] >= last_end:
                filtered_matches.append(m)
                last_end = m["position_end"]

        valid_results = []
        
        # Get the start positions of all references for quick lookup
        ref_starts = []
        doc_ref_starts = []
        for ref in references:
            # Get the first position in a reference
            positions = [
                value.get("position_start")
                for value in ref.values()
                if isinstance(value, dict) and "position_start" in value
            ]

            if positions:   
                ref_starts.append(positions[0])
                # ref_starts.append(min(positions))
            document_positions = [
                value.get("position_start")
                for key, value in ref.items()
                if (
                    isinstance(value, dict)
                    and key not in {"diem", "khoan", "dieu", "muc", "chuong"}
                    and "position_start" in value
                )
            ]
            if document_positions:
                doc_ref_starts.append(min(document_positions))
        ref_starts.sort()
        doc_ref_starts.sort()

        continue_match = _CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN.search(content)
        if continue_match:
            sentence_end = min(
                [
                    pos
                    for pos in (
                        content.find(separator, continue_match.end())
                        for separator in (".", "\n")
                    )
                    if pos != -1
                ],
                default=len(content),
            )
            if any(continue_match.start() <= ref_start < sentence_end for ref_start in ref_starts):
                return [{
                    "relation_type": "dan_chieu",
                    "relation_value": continue_match.group(0),
                    "hint_group": "forward_hints",
                    "position_start": continue_match.start(),
                    "position_end": continue_match.end(),
                    "direction": "FORWARD",
                }]

        # "Việc [action_keywords] thực hiện theo quy định tại [ref]": the clause describes
        # activity types that are *regulated by* the cited provision — this document is NOT
        # performing those actions.  Detected when action-type forward patterns fire IN THE
        # SAME SENTENCE SCOPE as "thực hiện theo quy định tại/của" and before it, and a
        # reference follows it.  Using same-scope restriction prevents false positives when
        # kéo_dài or other relation types occupy a different sentence.
        thuc_hien_match = _THUC_HIEN_THEO_QUY_DINH_TAI_PATTERN.search(content)
        if thuc_hien_match:
            # Scope start: last hard sentence boundary before the match
            scope_start = max(
                (
                    content.rfind(sep, 0, thuc_hien_match.start())
                    for sep in (".", "\n")
                ),
                default=-1,
            ) + 1
            has_action_signals_in_scope = any(
                m["relation_type"] in {
                    "sua_doi_bo_sung", "sua_doi", "bo_sung",
                    "thay_the", "bai_bo", "huy_bo",
                }
                and scope_start <= m["position_start"] < thuc_hien_match.start()
                for m in filtered_matches
            )
            if has_action_signals_in_scope:
                sentence_end = min(
                    [
                        pos
                        for pos in (
                            content.find(separator, thuc_hien_match.end())
                            for separator in (".", "\n")
                        )
                        if pos != -1
                    ],
                    default=len(content),
                )
                if any(thuc_hien_match.start() <= ref_start < sentence_end for ref_start in ref_starts):
                    return [{
                        "relation_type": "dan_chieu",
                        "relation_value": thuc_hien_match.group(0),
                        "hint_group": "forward_hints",
                        "position_start": thuc_hien_match.start(),
                        "position_end": thuc_hien_match.end(),
                        "direction": "FORWARD",
                    }]

        # 3. Validate relation type (filter out auxiliary descriptions)
        for m in filtered_matches:
            start_pos = m["position_start"]
            end_pos = m["position_end"]

            if m["relation_type"] == "bai_bo":
                local_window_start = max(0, start_pos - 40)
                local_window_end = min(len(content), end_pos + 180)
                local_window = content[local_window_start:local_window_end]
                if _BAI_BO_DINH_CHI_INTRO_PATTERN.search(local_window):
                    continue
                if self._is_post_amendment_intro_bai_bo_continuation(
                    content=content,
                    match=m,
                    filtered_matches=filtered_matches,
                ):
                    m["relation_type"] = "sua_doi_bo_sung"
                elif _ATTACHED_MATERIAL_ACTION_REFERENCE_PATTERN.search(local_window):
                    if self._has_parent_appendix_amendment_context(
                        parent_content,
                        grandparent_content,
                    ):
                        m["relation_type"] = "sua_doi_bo_sung"
                    else:
                        m["relation_type"] = "dan_chieu"

            if m["relation_type"] == "keo_dai_hieu_luc":
                if self._is_indirect_keo_dai_basis_reference(
                    content=content,
                    relation_text=m.get("text", ""),
                    relation_start=start_pos,
                    relation_end=end_pos,
                    ref_starts=doc_ref_starts,
                ):
                    continue

            if (
                m["relation_type"] == "dinh_chi"
                and self._is_indirect_action_basis_reference(
                    content=content,
                    relation_end=end_pos,
                    ref_starts=ref_starts,
                )
            ):
                continue

            if (
                m["relation_type"] == "dinh_chinh"
                and _DINH_CHINH_POST_INTRO_OPERATION_PATTERN.search(
                    content[max(0, start_pos - 420):start_pos]
                )
            ):
                continue

            if (
                m["relation_type"] == "dinh_chinh"
                and _DINH_CHINH_CONTENT_INTEGRATION_PATTERN.search(
                    content[max(0, start_pos - 80):]
                )
            ):
                continue

            if (
                m["relation_type"] == "sua_doi_bo_sung"
                and re.fullmatch(r"điều\s+chỉnh", m.get("text", ""), re.IGNORECASE)
                and re.search(r"\bphạm\s+vi\s+$", content[max(0, start_pos - 20):start_pos], re.IGNORECASE)
            ):
                continue

            if (
                m["relation_type"] in {"quy_dinh_chi_tiet", "huong_dan"}
                and (
                    _AMENDMENT_REPLACEMENT_DETAIL_PREFIX_PATTERN.search(
                        content[max(0, start_pos - 260):start_pos]
                    )
                    or self._is_inside_amendment_replacement_quote(
                        content=content,
                        start_pos=start_pos,
                    )
                )
            ):
                continue
            
            if m["direction"] == "PASSIVE":
                # Find the start of the scope (prefix scope)
                find_starts = [content.rfind(d, 0, start_pos) for d in SCOPE_DELIMITERS]
                prev_punct_pos = max(find_starts) + 1
                
                # Find the end of the scope (suffix scope)
                suffix = content[end_pos:]
                scope_pattern = rf"^[^{''.join(re.escape(d) for d in SCOPE_DELIMITERS)}]*:"
                suffix_match = re.search(scope_pattern, suffix)
                if not suffix_match:
                    continue
                
                has_valid_ref_before = False
                for rs in ref_starts:
                    if prev_punct_pos <= rs < start_pos:
                        has_valid_ref_before = True
                        break
                
                if has_valid_ref_before:
                    m["_next_punct_pos"] = end_pos + suffix_match.end()
                    valid_results.append(m)
                continue
                
            # Drop passive descriptions for forward relation types
            # (E.g. "Sửa đổi, bổ sung Luật Phòng thủ dân sự số 18/2023/QH15 "đã được sửa đổi, bổ sung" một số điều theo Luật số 98/2025/QH15")
            prefix = content[max(0, start_pos - 15):start_pos]
            if re.search(r"(?:đã\s+)?(?:được|bị)\s*$", prefix, re.IGNORECASE):
                continue
                
            # Determine the end position of the current segment
            next_punct_pos = len(content)
            delimiter_match = SEGMENT_DELIMITER_PATTERN.search(content, end_pos)
            if delimiter_match:
                next_punct_pos = delimiter_match.start()
            next_newline_pos = content.find("\n", end_pos)
            if next_newline_pos != -1:
                next_punct_pos = min(next_punct_pos, next_newline_pos)

            # Must connect to at least 1 document/clause before hitting the delimiter
            # NOTE: We allow rs >= start_pos because some patterns (like 'tại Công văn') 
            # now consume the document type, so the reference's start will be inside the relation's span.
            has_valid_ref_in_segment = False
            for rs in ref_starts:   
                if start_pos <= rs < next_punct_pos:
                    has_valid_ref_in_segment = True 
                    break
            
            # Fallback: If no ref found in direct segment, try a broader search IF we detect an dan_chieu exclusion pattern
            # This handles long titles with internal commas or conjunctions before the reference.
            # E.g., Điều 1. Sửa đổi, bổ sung một số điều của Quy định về quản lý và bảo vệ động vật hoang dã trên địa bàn tỉnh Cà Mau 
            # ban hành kèm theo Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010 của Ủy ban nhân dân tỉnh Cà Mau.
            # sua_doi_bo_sung filtered by "và", and before "và" not containing the reference.
            if not has_valid_ref_in_segment:
                valid_ends = [content.find(d, end_pos) for d in SCOPE_DELIMITERS]
                valid_ends = [pos for pos in valid_ends if pos != -1]
                scope_punct_end = min(valid_ends) if valid_ends else len(content)
                
                # Only fallback if we detect and attachment/exclusion phrase in this scope
                scope_text = content[end_pos:scope_punct_end]
                if re.search(DAN_CHIEU_EXCLUSIONS, scope_text, re.IGNORECASE):
                    for rs in ref_starts:
                        if start_pos <= rs < scope_punct_end:
                            has_valid_ref_in_segment = True
                            break

                if (
                    not has_valid_ref_in_segment
                    and m["relation_type"] == "dan_chieu"
                    and _DAN_CHIEU_BACKWARD_EFFECTIVE_CUE_PATTERN.search(
                        m.get("text", "")
                    )
                ):
                    scope_start = max(
                        content.rfind(delimiter, 0, start_pos)
                        for delimiter in SCOPE_DELIMITERS
                    ) + 1
                    has_valid_ref_in_segment = any(
                        scope_start <= rs < start_pos
                        for rs in ref_starts
                    )

            if (
                not has_valid_ref_in_segment
                and m["relation_type"] in {"huy_bo", "bai_bo", "thay_the", "dinh_chi", "ngung_hieu_luc"}
                and (
                    self._forward_relation_points_to_following_list(
                        content=content,
                        relation_end=end_pos,
                        ref_starts=ref_starts,
                    )
                    or self._forward_relation_points_to_semicolon_target_list(
                        content=content,
                        relation_end=end_pos,
                        ref_starts=ref_starts,
                    )
                )
            ):
                has_valid_ref_in_segment = True

            if not has_valid_ref_in_segment and m["relation_type"] == "keo_dai_hieu_luc":
                sentence_end_candidates = [
                    content.find(separator, end_pos)
                    for separator in (".", "\n")
                    if content.find(separator, end_pos) != -1
                ]
                sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(content)
                has_valid_ref_in_segment = any(
                    start_pos <= rs < sentence_end
                    for rs in ref_starts
                )

            if (
                not has_valid_ref_in_segment
                and m["relation_type"] == "sua_doi_bo_sung"
                and _DAN_CHIEU_PHRASE_AMENDMENT_SCOPE_PATTERN.search(
                    content[start_pos:end_pos]
                )
            ):
                sentence_end_candidates = [
                    content.find(separator, end_pos)
                    for separator in (".", "\n")
                    if content.find(separator, end_pos) != -1
                ]
                sentence_end = (
                    min(sentence_end_candidates)
                    if sentence_end_candidates
                    else len(content)
                )
                for rs in ref_starts:
                    if start_pos <= rs < sentence_end:
                        has_valid_ref_in_segment = True
                        break

            # "Bổ sung [cụm] từ X vào Y tại Z" — targets may appear after the first ";"
            # (e.g. "tại tên Chương VIII; tên các điều 60, 61 và 64; các khoản 1, 3 và 4 Điều 60...")
            if (
                not has_valid_ref_in_segment
                and m["relation_type"] == "sua_doi_bo_sung"
                and _BO_SUNG_WORD_PHRASE_SCOPE_PATTERN.search(
                    content[start_pos:min(end_pos + 20, len(content))]
                )
            ):
                sentence_end_candidates = [
                    content.find(separator, end_pos)
                    for separator in (".", "\n")
                    if content.find(separator, end_pos) != -1
                ]
                sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(content)
                for rs in ref_starts:
                    if start_pos <= rs < sentence_end:
                        has_valid_ref_in_segment = True
                        break

            if not has_valid_ref_in_segment:
                continue

            if (
                m["relation_type"] in {"huy_bo", "bai_bo", "dinh_chinh"}
                and self._is_operational_action_relation(
                    content=content,
                    relation_start=m["position_start"],
                    scope_end=next_punct_pos,
                )
            ):
                continue
            
            # Special check for 'dan_chieu': drop if it's 'ban hành kèm theo' or 'kèm theo'
            # IF AND ONLY IF there's another major relation in the same scope
            if m["relation_type"] == "dan_chieu":
                if self._is_document_title_descriptive_dan_chieu(
                    content=content,
                    start_pos=start_pos,
                ):
                    continue
                if self._is_post_action_assignment_basis(
                    content=content,
                    start_pos=start_pos,
                    filtered_matches=filtered_matches,
                ):
                    continue
                if self._should_skip_descriptive_dan_chieu(
                    content=content,
                    start_pos=start_pos,
                    end_pos=end_pos,
                ):
                    continue

                current_scope_start = max([content.rfind(d, 0, start_pos) for d in SCOPE_DELIMITERS]) + 1
                scope_prefix = content[current_scope_start:start_pos]
                if any(
                    re.search(pattern, scope_prefix, re.IGNORECASE)
                    for pattern in DAN_CHIEU_DESCRIPTIVE_ACTION_EXCLUSIONS
                ):
                    continue

                prefix_text = content[max(0, start_pos - 40):start_pos]
                if re.search(DAN_CHIEU_EXCLUSIONS, prefix_text, re.IGNORECASE):
                    # Check for other MAJOR relations in the same scope
                    find_ends = [content.find(d, end_pos) for d in SCOPE_DELIMITERS]
                    curr_valid_ends = [pos for pos in find_ends if pos != -1]
                    current_scope_end = min(curr_valid_ends) if curr_valid_ends else len(content)
                    
                    has_major_relation = False
                    for other in filtered_matches:
                        if other == m:
                            continue
                        if other["relation_type"] == "dan_chieu":
                            continue
                        if (
                            other["relation_type"] in {"huy_bo", "bai_bo", "dinh_chinh"}
                            and self._is_operational_action_relation(
                                content=content,
                                relation_start=other.get("position_start", -1),
                                scope_end=current_scope_end,
                            )
                        ):
                            continue
                        if (
                            other["relation_type"] == "dinh_chi"
                            and self._is_indirect_action_basis_reference(
                                content=content,
                                relation_end=other.get("position_end", -1),
                                ref_starts=ref_starts,
                            )
                        ):
                            continue
                        if current_scope_start <= other["position_start"] < current_scope_end:
                            has_major_relation = True
                            break
                    # Remove dan_chieu relation type if there is another major relation in the same scope
                    if has_major_relation:
                        continue
            
            # "Việc [action] thực hiện theo quy định tại [ref]": the action keywords
            # describe SUBJECT MATTER regulated by the cited clause, not an action
            # performed by this document.  Convert to dan_chieu so the reference is
            # correctly classified and is not absorbed by the action relation's scope.
            if m["relation_type"] in {
                "sua_doi_bo_sung", "sua_doi", "bo_sung",
                "thay_the", "bai_bo", "huy_bo", "dinh_chi",
                "dinh_chinh",
            }:
                sentence_end_candidates = [
                    content.find(sep, end_pos)
                    for sep in (".", "\n")
                    if content.find(sep, end_pos) != -1
                ]
                sentence_end = (
                    min(sentence_end_candidates)
                    if sentence_end_candidates
                    else len(content)
                )
                scoped_ref_starts = [rs for rs in ref_starts if end_pos <= rs < sentence_end]
                if scoped_ref_starts:
                    first_ref = min(scoped_ref_starts)
                    bridge = content[end_pos:first_ref]
                    out_of_scope_ref_starts = [rs for rs in ref_starts if rs >= sentence_end]
                    if not out_of_scope_ref_starts:
                        if _CITATION_CUE_PREFIX_PATTERN.search(bridge):
                            m["relation_type"] = "dan_chieu"
                        elif not any(end_pos <= dr < sentence_end for dr in doc_ref_starts):
                            if _get_nay_internal_scope_pattern().search(content[end_pos:sentence_end]):
                                m["relation_type"] = "dan_chieu"

            m["_next_punct_pos"] = next_punct_pos
            valid_results.append(m)

        # 4. Remove auxiliary descriptions for references (Keep only the first signal in each segment)
        final_results = []
        active_segment_end = -1
        active_segment_relation_type = None
        
        for m in valid_results:
            relation_type = m["relation_type"]
            if relation_type == "huy_bo":
                scope_end = m.get("_next_punct_pos", len(content))
                if _ATTACHED_NUMBERED_ITEM_REPEAL_CUE_PATTERN.search(
                    content[m["position_start"]:scope_end]
                ):
                    continue
                if _ATTACHED_LIST_AMENDMENT_CUE_PATTERN.search(
                    content[m["position_start"]:scope_end]
                ):
                    relation_type = "sua_doi_bo_sung"

            if relation_type in ("bai_bo", "thay_the"):
                scope_end = m.get("_next_punct_pos", len(content))
                if _CONTENT_PUBLISHED_AMEND_PATTERN.search(
                    content[m["position_start"]:scope_end]
                ):
                    relation_type = "sua_doi_bo_sung"

            # If this phrase falls into the forbidden zone (i.e., it is before the end of the segment of a previous relation phrase)
            # Then it is just "auxiliary information" of the previous target document, we remove it.
            # E.g: "Sửa đổi, bổ sung Nghị định số 10/2023/NĐ-CP "quy định chi tiết" một số điều theo Luật số 98/2015/QH15"
            # "quy định chi tiết" is auxiliary information of "Nghị định số 10/2023/NĐ-CP"
            if m["position_start"] < active_segment_end:
                if not (
                    relation_type == "dan_chieu"
                    and active_segment_relation_type == "keo_dai_hieu_luc"
                ):
                    continue
                
            # Keep satisfying matches
            final_results.append({
                "relation_type": relation_type,
                "relation_value": m.get("text"),
                "hint_group": m.get("hint_group", "forward_hints"),
                "position_start": m["position_start"],
                "position_end": m["position_end"],
                "direction": m.get("direction", "FORWARD")
            })
            
            # Update bounds
            active_segment_end = m["_next_punct_pos"]
            active_segment_relation_type = relation_type

        if not any(relation.get("relation_type") == "dan_chieu" for relation in final_results):
            thuc_hien_match = _THUC_HIEN_THEO_QUY_DINH_TAI_PATTERN.search(content)
            if thuc_hien_match:
                final_results.append({
                    "relation_type": "dan_chieu",
                    "relation_value": thuc_hien_match.group(0),
                    "hint_group": "thuc_hien_theo_quy_dinh",
                    "position_start": thuc_hien_match.start(),
                    "position_end": thuc_hien_match.end(),
                    "direction": "FORWARD",
                })

        if (
            any(relation.get("relation_type") == "keo_dai_hieu_luc" for relation in final_results)
            and not any(relation.get("relation_type") == "dan_chieu" for relation in final_results)
        ):
            normalized_content = unidecode(content or "").lower()
            if _KEO_DAI_EXPLICIT_DAN_CHIEU_CUE_PATTERN.search(normalized_content):
                first_keo_dai = next(
                    relation
                    for relation in final_results
                    if relation.get("relation_type") == "keo_dai_hieu_luc"
                )
                final_results.append({
                    "relation_type": "dan_chieu",
                    "relation_value": "theo",
                    "hint_group": "keo_dai_explicit_citation",
                    "position_start": first_keo_dai["position_start"],
                    "position_end": first_keo_dai["position_end"],
                    "direction": "FORWARD",
                })

        if self._should_promote_dan_chieu_to_detail_from_parent(
            content=content,
            parent_content=parent_content,
            grandparent_content=grandparent_content,
            relations=final_results,
        ):
            for relation in final_results:
                relation["relation_type"] = "quy_dinh_chi_tiet"
                relation["hint_group"] = "detail_parent_context"

        if (
            final_results
            and _DEFINITION_REPLACEMENT_SCOPE_PATTERN.search(content or "")
            and _DEFINITION_REPLACEMENT_BY_PATTERN.search(content or "")
            and any(
                ancestor_content
                and ancestor_content.strip().endswith(":")
                and any(
                    pattern.search(ancestor_content)
                    for pattern in COMPILED_FORWARD_PATTERNS["thay_the"]
                )
                for ancestor_content in (parent_content, grandparent_content)
            )
        ):
            final_results = [
                relation
                for relation in final_results
                if relation.get("relation_type") != "dan_chieu"
            ]
        
        # 5. Enumerated relation type:
        # When content contains only the references (no direct relation keyword),
        # or when references appear before any local relation signals,
        # and the parent/grandparent ends with ':' signalling an enumerated list,
        # inherit the relation type from that ancestor.
        # E.g. parent: "Bãi bỏ toàn bộ 02 Thông tư liên tịch sau đây:"
        # content: "Thông tư liên tịch số 135/2008/TTLT-BTC-BTNMT ngày..."

        # if not final_results and references:
        # Calculate boundaries for potential inherited relations
        local_signals = [m for m in final_results if m.get("position_start", -1) >= 0]
        first_signal_pos = min((m["position_start"] for m in local_signals), default=len(content))
        first_ref_pos = ref_starts[0] if ref_starts else len(content)
        has_early_ref = first_ref_pos < first_signal_pos

        # If in the main content there are just containing dan_chieu relation,
        # and its parent/grandparent existed enumerated relation type, 
        # Override the enumerated relation type to dan_chieu
        is_only_dan_chieu_relation_type = (
            final_results and all(r.get("relation_type") == "dan_chieu" for r in final_results)
        )
        has_explicit_dan_chieu_clause_reference = (
            is_only_dan_chieu_relation_type
            and _THEO_QUY_DINH_TAI_CLAUSE_PATTERN.search(content) is not None
        )
        has_explicit_dan_chieu_reference = (
            is_only_dan_chieu_relation_type
            and (
                has_explicit_dan_chieu_clause_reference
                or _THEO_QUY_DINH_TAI_MARKER_PATTERN.search(content) is not None
                or _CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN.search(content) is not None
            )
        )
        has_child_scope_dan_chieu_reference = (
            is_only_dan_chieu_relation_type
            and _CHILD_SCOPE_QUY_DINH_VE_PATTERN.search(content or "") is not None
        )
        has_attached_material_action_reference = (
            is_only_dan_chieu_relation_type
            and _ATTACHED_MATERIAL_ACTION_REFERENCE_PATTERN.search(content or "") is not None
        )
        can_override_dan_chieu_from_ancestor = (
            is_only_dan_chieu_relation_type
            and not has_attached_material_action_reference
        )
        if (not final_results or has_early_ref or can_override_dan_chieu_from_ancestor) and references:
            for ancestor_content in [parent_content, grandparent_content]:
                if not ancestor_content or not ancestor_content.strip():
                    continue 

                stripped_ancestor = ancestor_content.strip()
                # Only trigger when ancestor ends with ':' (enumerated signal)
                if not stripped_ancestor.endswith(':'):
                    continue 

                # Extract relation type from the ancestor
                # COMPILED_FORWARD_PATTERNS acts as both guard and extractor:
                # if no relation keyword is found, filtered_enum stays empty and we skip.
                enum_ancestor_matches = []
                for rel_type, patterns in COMPILED_FORWARD_PATTERNS.items():
                    for pattern in patterns:
                        for match in pattern.finditer(stripped_ancestor):
                            enum_ancestor_matches.append({
                                "relation_type": rel_type,
                                "position_start": match.start(),
                                "position_end": match.end(),
                                "text": match.group(0),
                            })
                
                # Sort: longest match wins at same start position
                enum_ancestor_matches.sort(
                    key=lambda x: (x["position_start"], -x["position_end"])
                )

                # Deduplicate overlapping
                filtered_enum = []
                last_end = -1
                for m in enum_ancestor_matches:
                    if m["position_start"] >= last_end:
                        filtered_enum.append(m)
                        last_end = m["position_end"]

                filtered_enum = self._filter_conflict_or_redundant_relation_types(
                    content=ancestor_content,
                    relations=filtered_enum,
                    doc_types=_get_doc_types(),
                    clause_type=clause_type
                )
                
                # If we found exactly one relation type in the ancestor
                if filtered_enum:
                    best = filtered_enum[0]
                    if (
                        has_explicit_dan_chieu_clause_reference
                        and best["relation_type"] in {"huong_dan", "quy_dinh_chi_tiet"}
                    ):
                        continue
                    if (
                        has_child_scope_dan_chieu_reference
                        and best["relation_type"] in {"huong_dan", "quy_dinh_chi_tiet"}
                    ):
                        continue
                    if (
                        has_explicit_dan_chieu_reference
                        and best["relation_type"] in _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES
                    ):
                        continue
                    final_results = []
                    final_results.append({
                        "relation_type": best["relation_type"],
                        "relation_value": best["text"],
                        "hint_group": "enumerated_relation_types",
                        "position_start": -1,
                        "position_end": -1,
                        "direction": "FORWARD",
                        "source_content": stripped_ancestor,
                    })
                    break # Stop at the first matching ancestor

        # 6. Inherit from parent or grandparent if no direct relation found in content,
        # if not final_results:
        # or if existing signals appear after the first reference.
        # (This is a more general fallback for when section 5 doesn't trigger)
        has_inherited = any(m.get("position_start") == -1 for m in final_results)
        if not has_inherited and (
            not final_results
            or has_early_ref
            or can_override_dan_chieu_from_ancestor
        ):
            for ancestor_content in [parent_content, grandparent_content]:
                if not ancestor_content or not ancestor_content.strip():
                    continue

                # Extract all matches using regex
                ancestor_matches = []
                for rel_type, patterns in COMPILED_FORWARD_PATTERNS.items():
                    for pattern in patterns:
                        for match in pattern.finditer(ancestor_content):
                            ancestor_matches.append({
                                "relation_type": rel_type,
                                "position_start": match.start(),
                                "position_end": match.end(),
                                "text": match.group(0),
                                "direction": "FORWARD"
                            })
                            
                for rel_type, patterns in COMPILED_PASSIVE_PATTERNS.items():
                    for pattern in patterns:
                        for match in pattern.finditer(ancestor_content):
                            ancestor_matches.append({
                                "relation_type": rel_type,
                                "hint_group": "passive_voice_relation_types",
                                "position_start": match.start(),
                                "position_end": match.end(),
                                "text": match.group(0),
                                "direction": "PASSIVE"
                            })
                
                # Sort to prioritize longer matches (if start is the same, end is larger)
                ancestor_matches.sort(key=lambda x: (x["position_start"], -x["position_end"]))

                # Filter out overlapping matches
                filtered_ancestor_matches = []
                last_end = -1
                for m in ancestor_matches:
                    if m["position_start"] >= last_end:
                        filtered_ancestor_matches.append(m)
                        last_end = m["position_end"]

                # Validate relation type (filter out auxiliary descriptions)
                valid_ancestor_results = []

                for m in filtered_ancestor_matches:
                    start_pos = m["position_start"]
                    end_pos = m["position_end"]
                    if m["direction"] == "PASSIVE":
                        suffix = ancestor_content[end_pos:]
                        scope_pattern = rf"^[^{''.join(re.escape(d) for d in SCOPE_DELIMITERS)}]*:"
                        if not re.search(scope_pattern, suffix):
                            continue
                        
                        # We don't strictly require a reference in the ancestor content, 
                        # just output it as a valid inherited relation.
                        valid_ancestor_results.append(m)
                        continue

                    prefix = ancestor_content[max(0, start_pos - 15):start_pos]
                    if re.search(r"(?:đã\s+)?(?:được|bị)\s*$", prefix, re.IGNORECASE):
                        continue
                    
                    # Filter 'dan_chieu' if a major relation is already in the same sentence scope
                    if m["relation_type"] == "dan_chieu":
                        prefix_text = ancestor_content[max(0, start_pos - 40):start_pos]
                        if re.search(DAN_CHIEU_EXCLUSIONS, prefix_text, re.IGNORECASE):
                            # Check for other MAJOR relations in the same scope
                            current_scope_start = max([ancestor_content.rfind(d, 0, start_pos) for d in SCOPE_DELIMITERS]) + 1
                            find_ends = [ancestor_content.find(d, end_pos) for d in SCOPE_DELIMITERS]
                            curr_valid_ends = [pos for pos in find_ends if pos != -1]
                            current_scope_end = min(curr_valid_ends) if curr_valid_ends else len(ancestor_content)
                            
                            has_major_relation = False
                            for other in filtered_ancestor_matches:
                                if other == m:
                                    continue
                                if other["relation_type"] == "dan_chieu":
                                    continue
                                if current_scope_start <= other["position_start"] < current_scope_end:
                                    has_major_relation = True
                                    break
                            if has_major_relation:
                                continue
                            
                    valid_ancestor_results.append(m)

                # Get the first match
                if valid_ancestor_results:
                    m = valid_ancestor_results[0]
                    if (
                        has_explicit_dan_chieu_clause_reference
                        and m["relation_type"] in {"huong_dan", "quy_dinh_chi_tiet"}
                    ):
                        continue
                    if (
                        has_child_scope_dan_chieu_reference
                        and m["relation_type"] in {"huong_dan", "quy_dinh_chi_tiet"}
                    ):
                        continue
                    if (
                        has_explicit_dan_chieu_reference
                        and m["relation_type"] in _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES
                    ):
                        continue
                    if (
                        is_only_dan_chieu_relation_type
                        and m["relation_type"] == "ngung_hieu_luc"
                    ):
                        final_results = []
                    # Keep satisfying matches
                    final_results.append({
                        "relation_type": m["relation_type"],
                        "relation_value": m.get("text"),
                        "hint_group": m.get("hint_group", "forward_hints"),
                        "position_start": -1, # Using -1 to indicate it inherited from grandparent/parent
                        "position_end": -1,
                        "direction": m.get("direction", "FORWARD"),
                        "source_content": ancestor_content,
                    })
                    break

        # 7. CHECK FOR EDGE CASES 
        # If 'hết hiệu lực kể từ ngày + [document type] này có hiệu lực thi hành' is found, 
        # then the relation type is 'thay_the' and remove other relation types
        # If the thay_the signal appears at the end of the content, it means the references must be found at the beginning of the content.
        # If the thay_the signal appears in the parent or grandparent_content, it means the references must be found at the content, not in parent_content or grandparent_content.
        
        # Check for thay_the or bai_bo edge cases
        edge_match_thay_the = COMPILED_THAY_THE_EDGE_CASE_PATTERN.search(content)
        edge_match_bai_bo = COMPILED_BAI_BO_EDGE_CASE_PATTERN.search(content)
        
        edge_text = None
        edge_type = None
        pos_start = -1
        pos_end = -1
        direction = "REVERSE"
        
        if edge_match_thay_the:
            edge_text = edge_match_thay_the.group(0)
            edge_type = "thay_the"
            pos_start = edge_match_thay_the.start()
            pos_end = edge_match_thay_the.end()
        elif edge_match_bai_bo:
            edge_text = edge_match_bai_bo.group(0)
            edge_type = "bai_bo"
            pos_start = edge_match_bai_bo.start()
            pos_end = edge_match_bai_bo.end()
        else:
            # Search ancestors if not found in current content
            for ancestor in [parent_content, grandparent_content]:
                if ancestor:
                    am_tt = COMPILED_THAY_THE_EDGE_CASE_PATTERN.search(ancestor)
                    if am_tt:
                        edge_text = am_tt.group(0)
                        edge_type = "thay_the"
                        direction = "FORWARD"
                        break
                    
                    am_bb = COMPILED_BAI_BO_EDGE_CASE_PATTERN.search(ancestor)
                    if am_bb:
                        edge_text = am_bb.group(0)
                        edge_type = "bai_bo"
                        direction = "FORWARD"
                        break
        
        # Partial-content expiry amends each listed document rather than
        # replacing/repealing it; reclassify so the edge distributes as
        # sua_doi_bo_sung across the whole document list.
        if (
            edge_text
            and edge_type in ("thay_the", "bai_bo")
            and _CONTENT_EXPIRY_SDBS_PATTERN.search(content)
        ):
            edge_type = "sua_doi_bo_sung"

        if (
            edge_text
            and edge_type in ["bai_bo", "thay_the"]
            and _CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN.search(content)
        ):
            edge_text = None

        if edge_text:
            if (
                direction == "REVERSE"
                and self._edge_case_points_to_following_list(
                    content=content,
                    edge_start=pos_start,
                    edge_end=pos_end,
                    ref_starts=ref_starts,
                )
            ):
                direction = "FORWARD"

            # If an edge case signal is found, it overrides all other extracted relation keywords
            # specifically for the current content's references.
            # EXCEPTION: If we already have 'keo_dai_hieu_luc', do not let the edge case override it
            # as it is likely descriptive of the target's state rather than the clause's primary action.
            if edge_type in ["bai_bo", "thay_the"] and any(r["relation_type"] == "keo_dai_hieu_luc" for r in final_results):
                return final_results
            if (
                edge_type in ["bai_bo", "thay_the"]
                and any(r["relation_type"] == "dan_chieu" for r in final_results)
                and _CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN.search(content)
            ):
                return final_results

            post_edge_dan_chieu_results = [
                relation
                for relation in final_results
                if (
                    relation.get("relation_type") == "dan_chieu"
                    and relation.get("position_start", -1) > pos_end
                )
            ]
            final_results = []
            if references:
                final_results.append({
                    "relation_type": edge_type,
                    "relation_value": edge_text,
                    "hint_group": f"edge_case_{edge_type}",
                    "position_start": pos_start,
                    "position_end": pos_end,
                    "direction": direction
                })
                final_results.extend(post_edge_dan_chieu_results)
        
        continue_match = _CONTINUE_IMPLEMENT_DAN_CHIEU_PATTERN.search(content)
        if references and continue_match:
            sentence_end = min(
                [
                    pos
                    for pos in (
                        content.find(separator, continue_match.end())
                        for separator in (".", "\n")
                    )
                    if pos != -1
                ],
                default=len(content),
            )
            if (
                any(continue_match.start() <= ref_start < sentence_end for ref_start in ref_starts)
                and (
                    not final_results
                    or all(
                        relation["relation_type"] == "quy_dinh_chi_tiet"
                        and relation["position_start"] > continue_match.end()
                        for relation in final_results
                    )
                )
            ):
                final_results = [
                    {
                        "relation_type": "dan_chieu",
                        "relation_value": continue_match.group(0),
                        "hint_group": "forward_hints",
                        "position_start": continue_match.start(),
                        "position_end": continue_match.end(),
                        "direction": "FORWARD",
                    }
                ]

        final_results = self._filter_conflict_or_redundant_relation_types(
            content=content,
            relations=final_results,
            doc_types=_get_doc_types(),
            clause_type=clause_type
        )

        kept, distractor_rejected = _DISTRACTOR_FILTER.filter_by_context(
            content=content,
            relation_type_matches=final_results,
            clause_type=clause_type,
        )
        if rejected_buffer is not None and distractor_rejected:
            rejected_buffer.extend(distractor_rejected)
        final_results = kept

        return final_results
