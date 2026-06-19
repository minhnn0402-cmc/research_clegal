"""Relation/reference matching stage for ``BaseExtractor``."""

from dataclasses import replace
from typing import Dict, List, Optional, Tuple
import re

from src.domain.extractors.base_extractor_flow.models import PreparedReference, RelationCue
from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared, unidecode
from src.domain.extractors.relation_type_rules import COMPILED_FORWARD_PATTERNS

_DAN_CHIEU_FORWARD_PATTERNS = COMPILED_FORWARD_PATTERNS["dan_chieu"]

PARTIAL_PROVISION_EXPIRY_PATTERN = re.compile(
    r"\bcác\s+quy\s+định\s+tại\s+(?:chương|mục|điều|khoản|điểm)\b",
    re.IGNORECASE,
)


class RelationMatching:
    """Scope-aware relation/reference matching and authority filters."""

    SYNTHETIC_RELATION_POSITION = -1
    DETAIL_GUIDANCE_RELATION_TYPES = frozenset({"quy_dinh_chi_tiet", "huong_dan"})
    STRONG_ACTION_TARGET_RELATION_TYPES = frozenset({
        "bai_bo",
        "huy_bo",
        "dinh_chi",
        "dinh_chinh",
        "ngung_hieu_luc",
        "keo_dai_hieu_luc",
        "sua_doi_bo_sung",
        "sua_doi",
        "bo_sung",
        "thay_the",
        "huong_dan",
        "quy_dinh_chi_tiet",
    })
    CLAUSE_SCOPED_SUPERSEDES_WHOLE_DOCUMENT_RELATION_TYPES = frozenset({
        "bai_bo",
        "huy_bo",
        "dinh_chi",
        "ngung_hieu_luc",
        "sua_doi_bo_sung",
        "sua_doi",
        "bo_sung",
        "thay_the",
    })
    BULLET_LIST_ACTION_RELATION_TYPES = frozenset({
        "huy_bo",
        "bai_bo",
        "thay_the",
        "dinh_chi",
        "ngung_hieu_luc",
    })
    SEMICOLON_LIST_ACTION_RELATION_TYPES = frozenset({
        "dan_chieu",
        "huy_bo",
        "bai_bo",
        "thay_the",
        "dinh_chi",
        "ngung_hieu_luc",
    })
    BULLET_LIST_START_PATTERN = re.compile(r"[\r\n]\s*(?:[-–•]|\(?[a-zđ]\)|\d+[\).])\s*", re.IGNORECASE)
    NON_NODE_COMPONENT_TARGET_PREFIX_PATTERN = re.compile(
        r"\b(?:"
        r"chuong\s+(?:[ivxlcdm]+|\d+[a-z]?)"
        r"|muc\s+(?:[ivxlcdm]+|\d+[a-z]?)"
        r"|phan\s+(?:[ivxlcdm]+|\d+[a-z]?)"
        r"|phu\s+luc(?:\s+(?:[ivxlcdm]+|\d+[a-z]?|[a-z]{1,4}))?"
        r"|bieu\s+mau(?:\s+(?:so\s+)?(?:\d+[\w./-]*|[ivxlcdm]+))?"
        r"|mau\s+(?:so\s+)?(?:\d+[\w./-]*|[ivxlcdm]+)"
        r")\b",
        re.IGNORECASE,
    )
    NON_NODE_COMPONENT_SDBS_RELATION_TYPES = frozenset({
        "bai_bo",
        "bo_sung",
        "huy_bo",
        "sua_doi",
        "thay_the",
    })
    NON_NODE_COMPONENT_DAN_CHIEU_RELATION_TYPES = frozenset({
        "dinh_chi",
        "keo_dai_hieu_luc",
        "ngung_hieu_luc",
    })
    NON_NODE_COMPONENT_HUONG_DAN_RELATION_TYPES = frozenset({
        "quy_dinh_chi_tiet",
        "huong_dan",
    })
    CLAUSE_SCOPED_ACTION_TITLE_SIMILARITY_THRESHOLD = 0.6
    QUOTED_AMENDMENT_INTRO_PATTERN = re.compile(
        r"(?:sửa\s+đổi\s*,\s*bổ\s+sung|bổ\s+sung|thay\s+thế).{0,200}như\s+sau\s*:",
        re.IGNORECASE | re.DOTALL,
    )
    AMENDMENT_PROVENANCE_SCOPE_PATTERN = re.compile(
        r"\b(?:da\s+duoc\s+(?:bo\s+sung|sua\s+doi)|duoc\s+(?:bo\s+sung|sua\s+doi)\s+theo|ve\s+viec\s+sua\s+doi\s*,\s*bo\s+sung|sua\s+doi\s*,\s*bo\s+sung\s+mot\s+so\s+dieu\s+cua)\b",
        re.IGNORECASE,
    )
    ALIAS_SCOPE_PATTERN = re.compile(
        r"\bsau\s+day\s+(?:goi(?:\s+(?:tat|chung))?|viet\s+tat)\s+la\b",
        re.IGNORECASE,
    )
    AMENDMENT_HISTORY_REFERENCE_BRIDGE_PATTERN = re.compile(
        r"\b(?:dieu\s+chinh\s*,\s*bo\s+sung|sua\s+doi\s*,\s*bo\s+sung|sua\s+doi|bo\s+sung)\b",
        re.IGNORECASE,
    )
    SDBS_AMENDMENT_HISTORY_REFERENCE_BRIDGE_PATTERN = re.compile(
        r"\b(?:da\s+)?duoc\s+(?:sua\s+doi(?:\s*,\s*bo\s+sung)?|bo\s+sung).{0,160}\btheo\s*$",
        re.IGNORECASE,
    )
    AMENDMENT_HISTORY_CONTINUATION_BRIDGE_PATTERN = re.compile(
        r"^\s*(?:(?:,|;)\s*)?(?:va|hoac)?\s*$",
        re.IGNORECASE,
    )
    DOCUMENT_NUMBER_CORE_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?/\d{4})\b")
    SUSPENDED_AMENDED_TARGET_BRIDGE_PATTERN = re.compile(
        r"\b(?:da\s+)?duoc\s+sua\s+doi(?:\s*,\s*bo\s+sung)?\s+tai\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    SUSPENDED_AMENDED_TARGET_CUE_PATTERN = re.compile(
        r"\b(?:đã\s+)?được\s+sửa\s+đổi(?:\s*,?\s*bổ\s+sung)?\s+tại\s+",
        re.IGNORECASE | re.DOTALL,
    )
    SDBS_PASSIVE_AMENDMENT_HISTORY_CUE_PATTERN = re.compile(
        r"\b(?:đã\s+)?được\s+(?:sửa\s+đổi(?:\s*,?\s*bổ\s+sung)?|bổ\s+sung)\s+tại\s+",
        re.IGNORECASE | re.DOTALL,
    )
    INSERTED_AMENDMENT_HISTORY_CUE_PATTERN = re.compile(
        r"\b(?:da\s+)?duoc\s+(?:sua\s+doi(?:\s*,?\s*bo\s+sung)?|bo\s+sung)\s+tai\s+",
        re.IGNORECASE | re.DOTALL,
    )
    SOURCE_ARTICLE_HEADING_PATTERN = re.compile(
        r"^\s*Điều\s+(?P<value>\d+[A-Za-zĐđ]?)\b",
        re.IGNORECASE,
    )
    BARE_NUMBERED_DOCUMENT_REFERENCE_PATTERN = re.compile(
        r"^\s*(?:luat|bo\s+luat|phap\s+lenh|nghi\s+quyet(?:\s+lien\s+tich)?|"
        r"nghi\s+dinh|thong\s+tu(?:\s+lien\s+tich)?|quyet\s+dinh)\s+so\b",
        re.IGNORECASE,
    )
    EXPIRY_TARGET_RELATION_TYPES = frozenset({"thay_the", "bai_bo", "keo_dai_hieu_luc"})
    PHRASE_LEVEL_AMENDMENT_COMPONENT_PATTERN = re.compile(
        r"\b(?:thay\s+the|bai\s+bo|bo)\s+(?:mot\s+so\s+)?(?:cac\s+)?cum\s+tu\b",
        re.IGNORECASE,
    )
    BO_SUNG_WORD_PHRASE_PATTERN = re.compile(
        r"\bbo\s+sung\s+(?:cum\s+)?tu\b",
        re.IGNORECASE,
    )
    PARTIAL_PHRASE_CUE_PATTERN = re.compile(r"\bcum\s+tu\b", re.IGNORECASE)
    PARTIAL_PHRASE_TARGET_MARKER_PATTERN = re.compile(r"\btai\b", re.IGNORECASE)
    DAN_CHIEU_DOCUMENT_LIST_CUE_PATTERN = re.compile(
        r"\btheo\s+(?:cac\s+)?quy\s+dinh\s+tai\b",
        re.IGNORECASE,
    )
    DAN_CHIEU_AMENDMENT_HISTORY_PREFIX_PATTERN = re.compile(
        r"\btheo\s+(?:cac\s+)?quy\s+dinh\s+tai\s*$",
        re.IGNORECASE,
    )
    DAN_CHIEU_AMENDMENT_HISTORY_SUFFIX_PATTERN = re.compile(
        r"\b(?:duoc\s+)?sua\s+doi(?:\s*,\s*bo\s+sung)?\b",
        re.IGNORECASE,
    )
    DAN_CHIEU_EXCEPTION_STOP_PATTERN = re.compile(
        r"\btru\s+truong\s+hop\b",
        re.IGNORECASE,
    )
    ACTION_DESCRIPTIVE_TAIL_PATTERN = re.compile(
        r"\b(?:quy\s+dinh\s+chi\s+tiet|huong\s+dan|ve\s+(?:viec\s+)?(?:keo\s+dai|thu\s+hoi))\b",
        re.IGNORECASE,
    )
    NGUNG_HIEU_LUC_DESCRIPTIVE_TAIL_PATTERN = re.compile(
        r"\b(?:huong\s+dan|ve\s+(?:viec\s+)?keo\s+dai)\b",
        re.IGNORECASE,
    )
    SELF_APPLICATION_REFERENCE_PREFIX_PATTERN = re.compile(
        r"\bthi\s+ap\s+dung\s+theo\s*$",
        re.IGNORECASE,
    )
    SELF_DOCUMENT_LIST_PREFIX_PATTERN = re.compile(
        r"\bnay\s*,\s*$",
        re.IGNORECASE,
    )
    RELATED_LAW_TAIL_PATTERN = re.compile(
        r"^\s*(?:,?\s*(?:va|hoac)\s+)?quy\s+dinh\s+khac\b",
        re.IGNORECASE,
    )
    ATTACHED_APPENDIX_SOURCE_PREFIX_PATTERN = re.compile(
        r"\b(?:(?:tai|theo)\s+)?"
        r"(?:mau(?:\s+so)?(?:\s+[\w./-]+){0,8}\s+)?"
        r"(?:phu\s+luc|danh\s+muc|bieu\s+mau|muc|phan)\b"
        r".{0,180}\b(?:ban\s+hanh\s+)?kem\s+theo\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    DEFINITION_REPLACEMENT_SCOPE_PATTERN = re.compile(
        r"^\s*(?:[a-z]\)\s*)?quy\s+dinh\s+viec\b",
        re.IGNORECASE,
    )
    DEFINITION_REPLACEMENT_BY_PATTERN = re.compile(
        r"\bbang\s+quy\s+dinh\s+tai\b",
        re.IGNORECASE,
    )
    DINH_CHINH_OPERATIONAL_MARKER_PATTERN = re.compile(
        r"\b(?:dinh\s+chinh|sua\s+cum\s+tu|sua\s+tieu\s+de|duoc\s+sua\s+thanh|sua\s+thanh|da\s+ban\s+hanh)\b",
        re.IGNORECASE,
    )
    SELF_DOCUMENT_CLAUSE_TAIL_PATTERN = re.compile(
        r"\b(?:cua\s+)?(?:luat|bo\s+luat|hien\s+phap|nghi\s+quyet|"
        r"nghi\s+dinh|thong\s+tu|quyet\s+dinh|phap\s+lenh)\s+nay\b",
        re.IGNORECASE,
    )
    INSERTION_ANCHOR_PATTERN = re.compile(
        r"\bvào\s+(?:sau|trước)\b",
        re.IGNORECASE,
    )
    DINH_CHINH_SCOPE_STOP_PATTERN = re.compile(
        r"\b(?:quy\s+định\s+chi\s+tiết|hướng\s+dẫn\s+thi\s+hành|quy\s+định\s+mã\s+số|sửa\s+đổi\s*,\s*bổ\s+sung|căn\s+cứ)\b",
        re.IGNORECASE,
    )
    DOCUMENT_DATE_PATTERN = re.compile(
        r"\bngày\s+(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})\b",
        re.IGNORECASE,
    )
    DINH_CHINH_DESCRIPTIVE_INTRO_BRIDGE_PATTERN = re.compile(
        r"\b(?:hướng\s+dẫn|quy\s+định|quy\s+định\s+chi\s+tiết)\b",
        re.IGNORECASE,
    )
    DETAIL_LIST_MARKER_PATTERN = re.compile(
        r"\bbao\s+gồm\s*:?",
        re.IGNORECASE,
    )
    EXISTING_DETAIL_GUIDANCE_DOCUMENT_PREFIX_PATTERN = re.compile(
        r"\b(?:cac\s+)?van\s+ban\s+quy\s+dinh\s+chi\s+tiet\s*,?\s*"
        r"(?:va\s+)?huong\s+dan\s+thi\s+hanh\s*$",
        re.IGNORECASE,
    )
    EXISTING_DETAIL_GUIDANCE_DOCUMENT_TAIL_PATTERN = re.compile(
        r"^\s*(?:,?\s*va\s+)?(?:cac\s+)?van\s+ban\s+quy\s+dinh\s+chi\s+tiet\s*,?\s*"
        r"(?:va\s+)?huong\s+dan\s+thi\s+hanh\b",
        re.IGNORECASE,
    )
    LEGISLATIVE_PROGRAM_PROJECT_PATTERN = re.compile(
        r"\bbo\s+sung\s+du\s+an\s+(?:luat|phap\s+lenh|nghi\s+quyet)\b"
        r".{0,360}\bvao\s+chuong\s+trinh\s+"
        r"(?:lap\s+phap|xay\s+dung\s+luat|xay\s+dung\s+phap\s+luat)\b",
        re.IGNORECASE | re.DOTALL,
    )
    TRANSITION_PROVISION_REPEAL_PATTERN = re.compile(
        r"\bbai\s+bo\s+(?:cac\s+)?quy\s+dinh\s+chuyen\s+tiep\b",
        re.IGNORECASE,
    )
    TEMPORAL_EFFECTIVE_REFERENCE_PATTERN = re.compile(
        r"\btruoc\s+thoi\s+diem\b.{0,220}\bco\s+hieu\s+luc\s+thi\s+hanh\b",
        re.IGNORECASE | re.DOTALL,
    )
    ACTION_RELATION_CONTINUATION_BRIDGE_PATTERN = re.compile(
        r"\b(?:bãi\s+bỏ|hủy\s+bỏ|đình\s+chỉ|đính\s+chính|sửa\s+đổi|bổ\s+sung|kéo\s+dài|thay\s+thế)\b",
        re.IGNORECASE,
    )
    AMENDMENT_OF_PREVIOUS_TARGET_SUFFIX_PATTERN = re.compile(
        r"\b(?:sua\s+doi\s*,\s*bo\s+sung|sua\s+doi|bo\s+sung)\b.{0,220}\bcua\b",
        re.IGNORECASE | re.DOTALL,
    )
    NUMBERED_ATTACHED_ITEM_REPEAL_SENTENCE_PATTERN = re.compile(
        r"\bhuy\s+bo\s+(?:\d+|mot\s+so|cac)\s+"
        r"(?:du\s+an|cong\s+trinh|noi\s+dung)\b"
        r".{0,260}\bban\s+hanh\s+kem\s+theo\b",
        re.IGNORECASE | re.DOTALL,
    )
    NHU_SAU_INTRO_PATTERN = re.compile(
        r"\bnhư\s+sau\s*:",
        re.IGNORECASE,
    )
    TOP_LEVEL_INSERTED_ARTICLE_HEADING_PATTERN = re.compile(
        r"^\s*dieu\s+\d+[a-z]?\.\s*bo\s+sung\s+dieu\s+\d+[a-z]?\b"
        r".{0,180}\bvao\s+(?:sau|truoc)\s+dieu\b",
        re.IGNORECASE | re.DOTALL,
    )
    REVERSE_EXPIRY_ITEM_PATTERN = re.compile(r"^\s*(\d+)[\).]\s*", re.IGNORECASE)
    TITLE_DESCRIPTIVE_AUTHORITY_TAIL_PATTERN = re.compile(
        r"\b(?:huong\s+dan|quy\s+dinh|thi\s+hanh)\b.{0,220}"
        r"\btai\s+(?:nghi\s+dinh|nghi\s+quyet|luat|thong\s+tu|quyet\s+dinh)\b",
        re.IGNORECASE | re.DOTALL,
    )
    TITLE_ACTION_PREFIX_PATTERN = re.compile(
        r"\b(?:bai\s+bo|sua\s+doi|bo\s+sung|thay\s+the|huy\s+bo)\b",
        re.IGNORECASE,
    )
    INSERTED_CHILD_KHOAN_SELF_TARGET_PATTERN = re.compile(
        r"\bbo\s+sung\s+khoan\s+[0-9a-z]+\b.{0,120}\bvao\s+sau\s+khoan\b",
        re.IGNORECASE | re.DOTALL,
    )
    UPPER_TO_LOWER_RESTRICTED_RELATIONS = frozenset({
        "quy_dinh_chi_tiet",
        "hop_nhat",
        "huong_dan",
        "can_cu",
    })
    LOWER_TO_UPPER_RESTRICTED_RELATIONS = frozenset({
        "bai_bo",
        "thay_the",
        "huy_bo",
        "dinh_chi",
        "hop_nhat",
        "ngung_hieu_luc",
        "keo_dai_hieu_luc",
        "sua_doi_bo_sung",
        "sua_doi",
        "bo_sung",
    })
    # Normative legal document types (VBQPPL) following the 14-level hierarchy.
    # Administrative docs (congvan, chithi, kehoach, …) are excluded.
    REGULATORY_DOCUMENT_KEYS = frozenset({
        "hienphap",
        "luat",
        "boluat",
        "phaplenh",
        "nghiquyet",
        "nghiquyetlientich",
        "nghidinh",
        "thongtu",
        "thongtulientich",
        "lenh",
    })
    # Administrative (non-normative) document types that must not have action
    # relationships with normative documents in either direction.
    ADMINISTRATIVE_DOCUMENT_TYPES = frozenset({
        "congvan",
        "chithi",
        "congdien",
        "kehoach",
        "huongdan",
        "vanban",
    })
    # 14-level normative hierarchy (type-based rank, used as fallback when the
    # authority identifier cannot be parsed). Authority rank from _infer_authority_rank
    # takes precedence in _compare_authority_policy_documents.
    #  1 Hiến pháp                         → 140
    #  2 Luật / Bộ luật / Nghị quyết QH    → 130
    #  3 Pháp lệnh / Nghị quyết UBTVQH     → 120
    #  4 Lệnh / Quyết định CTN             → 110
    #  5 Nghị định / Nghị quyết CP         → 100
    #  6 Quyết định Thủ tướng              →  90
    #  7 Nghị quyết HĐTP TAND Tối cao      →  85
    #  8 Thông tư (các cơ quan TW)         →  80
    #  9 Thông tư liên tịch                →  70
    # 10 Nghị quyết HĐND tỉnh              →  60
    # 11 Quyết định UBND tỉnh              →  50
    # 12 VBQPPL đặc khu                    →  40
    # 13 Nghị quyết HĐND huyện/xã          →  30
    # 14 Quyết định UBND huyện/xã          →  20
    DIRECT_DOCUMENT_TYPE_RANKS = {
        "hienphap": 140,
        "luat": 130,
        "boluat": 130,
        "phaplenh": 120,
        "lenh": 110,
        "nghidinh": 100,
        # nghiquyet and quyetdinh span multiple levels; authority_rank resolves
        # the exact level. These type-rank values are conservative mid-range fallbacks.
        "nghiquyet": 100,
        "nghiquyetlientich": 100,
        "quyetdinh": 90,
        "thongtu": 80,
        "thongtulientich": 70,
    }
    RESOLUTION_DOCUMENT_TYPES = frozenset({"nghiquyet", "nghiquyetlientich"})
    DECISION_DOCUMENT_TYPES = frozenset({"quyetdinh"})
    CENTRAL_MINISTRY_CODES = frozenset({
        "BCA",
        "BCT",
        "BCN",
        "BGDDT",
        "BGTVT",
        "BKHDT",
        "BKHCN",
        "BLDTBXH",
        "BNG",
        "BNNPTNT",
        "BNV",
        "BQP",
        "BTP",
        "BTC",
        "BTTTT",
        "BTNMT",
        "BVHTTDL",
        "BXD",
        "BYT",
        "NHNN",
        "TANDTC",
        "VKSNDTC",
    })

    def _prepare_references_for_matching(self, references: List[Dict]) -> List[PreparedReference]:
        """Normalize extracted references into sortable match candidates."""
        prepared_references: List[PreparedReference] = []

        for reference in references:
            reference_anchor_span = self._get_reference_anchor_span(reference)
            reference_full_span = self._get_reference_match_span(reference)
            if reference_anchor_span is None or reference_full_span is None:
                continue

            prepared_references.append(
                PreparedReference(
                    reference=self._copy_reference(reference),
                    position_start=reference_anchor_span["position_start"],
                    position_end=reference_anchor_span["position_end"],
                    full_position_start=reference_full_span["position_start"],
                    full_position_end=reference_full_span["position_end"],
                )
            )

        prepared_references.sort(
            key=lambda item: (item.position_start, item.position_end)
        )
        return prepared_references

    @staticmethod
    def _find_enclosing_parentheses_scope(
        content: str,
        position: int
    ) -> Optional[Tuple[int, int]]:
        """Return the nearest ``( ... )`` scope that contains ``position``."""
        stack: List[int] = []

        for index, char in enumerate(content):
            if char == "(":
                stack.append(index)
                continue

            if char != ")" or not stack:
                continue

            start_index = stack.pop()
            if start_index < position < index:
                return start_index, index

        return None

    def _filter_references_by_parentheses_scope(
        self,
        content: str,
        relation_start: int,
        references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """Keep only references that share the same parentheses scope as the relation."""
        if relation_start == self.SYNTHETIC_RELATION_POSITION:
            return references

        parentheses_scope = self._find_enclosing_parentheses_scope(
            content=content,
            position=relation_start,
        )
        if parentheses_scope is None:
            return references

        scope_start, scope_end = parentheses_scope
        return [
            reference
            for reference in references
            if scope_start < reference.position_start
            and reference.position_end <= scope_end
        ]

    @staticmethod
    def _find_parentheses_scopes(content: str) -> List[Tuple[int, int]]:
        """Return all balanced ``( ... )`` scopes in source order."""
        scopes: List[Tuple[int, int]] = []
        stack: List[int] = []

        for index, char in enumerate(content):
            if char == "(":
                stack.append(index)
            elif char == ")" and stack:
                scopes.append((stack.pop(), index))

        scopes.sort()
        return scopes

    def _is_amendment_provenance_parentheses(self, content: str, scope: Tuple[int, int]) -> bool:
        """Detect parenthetical provenance notes that cite amendment history."""
        scope_start, scope_end = scope
        normalized_scope_text = unidecode(content[scope_start + 1:scope_end] or "").lower()
        return self.AMENDMENT_PROVENANCE_SCOPE_PATTERN.search(normalized_scope_text) is not None

    def _filter_parenthetical_amendment_provenance_references(
        self,
        content: str,
        relation_type: str,
        references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """
        Drop amendment-history references inside parentheses when the operative
        relation is outside that parenthetical note.
        """
        if relation_type == "sua_doi_bo_sung" or len(references) <= 1:
            return references

        provenance_scopes = [
            scope
            for scope in self._find_parentheses_scopes(content)
            if self._is_amendment_provenance_parentheses(content, scope)
        ]
        if not provenance_scopes:
            return references

        references_outside_provenance = [
            reference
            for reference in references
            if not any(
                scope_start < reference.position_start
                and reference.full_position_end <= scope_end
                for scope_start, scope_end in provenance_scopes
            )
        ]
        if not references_outside_provenance:
            return references

        return references_outside_provenance

    def _filter_parenthetical_alias_references(
        self,
        content: str,
        references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop short-name aliases such as ``(sau đây gọi là Luật Dược)``."""
        if len(references) <= 1:
            return references

        alias_scopes = []
        for scope_start, scope_end in self._find_parentheses_scopes(content):
            normalized_scope_text = unidecode(content[scope_start + 1:scope_end] or "").lower()
            if self.ALIAS_SCOPE_PATTERN.search(normalized_scope_text):
                alias_scopes.append((scope_start, scope_end))

        if not alias_scopes:
            return references

        references_outside_alias = [
            reference
            for reference in references
            if not any(
                scope_start < reference.position_start
                and reference.full_position_end <= scope_end
                for scope_start, scope_end in alias_scopes
            )
        ]
        if not references_outside_alias:
            return references

        return references_outside_alias

    @staticmethod
    def _is_reference_immediately_after_semicolon(
        content: str,
        anchor_start: int,
        reference_start: int
    ) -> bool:
        """Allow forward/list/inheritance matching across ';' only for the first reference."""
        last_semicolon = content.rfind(";", anchor_start, reference_start)
        if last_semicolon == -1:
            return True

        return content[last_semicolon + 1:reference_start].strip() == ""

    def _filter_forward_like_scope_references(
        self,
        content: str,
        relation_start: int,
        candidate_references: List[PreparedReference],
        anchor_start: int
    ) -> List[PreparedReference]:
        """Filter forward/list-style references by closing boundaries and ';' exception."""
        scope_end = self._find_next_separator(
            content=content,
            start_pos=anchor_start,
            separators=(".", "\n", ":"),
        )
        scoped_references = [
            reference
            for reference in candidate_references
            if anchor_start <= reference.position_start < scope_end
        ]
        scoped_references = self._filter_references_by_parentheses_scope(
            content=content,
            relation_start=relation_start,
            references=scoped_references,
        )

        return [
            reference
            for reference in scoped_references
            if self._is_reference_immediately_after_semicolon(
                content=content,
                anchor_start=anchor_start,
                reference_start=reference.position_start,
            )
        ]

    @staticmethod
    def _is_contiguous_reference_bridge(bridge_text: str) -> bool:
        """Keep only tightly coordinated references in the same local phrase cluster."""
        normalized_bridge = unidecode(bridge_text or "").lower().strip()
        if not normalized_bridge:
            return True

        normalized_bridge = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", normalized_bridge)
        if not normalized_bridge:
            return True

        return normalized_bridge in {"va", "hoac", "va/hoac"}

    def _limit_references_to_nearest_cluster(
        self,
        content: str,
        references: List[PreparedReference],
        direction: str
    ) -> List[PreparedReference]:
        """Limit a scope to the nearest contiguous reference cluster."""
        if len(references) <= 1:
            return references

        ordered_references = sorted(
            references,
            key=lambda item: (item.position_start, item.position_end)
        )

        if direction == "backward":
            cluster = [ordered_references[-1]]
            remaining_references = reversed(ordered_references[:-1])
            for reference in remaining_references:
                bridge_text = content[
                    reference.position_end:cluster[0].position_start
                ]
                if not self._is_contiguous_reference_bridge(bridge_text):
                    break
                cluster.insert(0, reference)
            return cluster

        cluster = [ordered_references[0]]
        for reference in ordered_references[1:]:
            bridge_text = content[
                cluster[-1].position_end:reference.position_start
            ]
            if not self._is_contiguous_reference_bridge(bridge_text):
                last_semicolon = content.rfind(
                    ";",
                    cluster[-1].position_end,
                    reference.position_start,
                )
                if (
                    last_semicolon == -1
                    or content[last_semicolon + 1:reference.position_start].strip() != ""
                ):
                    break
            cluster.append(reference)

        return cluster

    def _find_listing_anchor_start(
        self,
        content: str,
        relation_end: int,
        candidate_references: List[PreparedReference]
    ) -> Optional[int]:
        """Return the position right after the listing ':' when references live there."""
        sentence_end = self._find_next_separator(
            content=content,
            start_pos=relation_end,
            separators=(".", "\n"),
        )
        colon_pos = content.find(":", relation_end, sentence_end)
        if colon_pos == -1:
            return None

        if any(
            relation_end <= reference.position_start < colon_pos
            for reference in candidate_references
        ):
            return None

        if not any(reference.position_start > colon_pos for reference in candidate_references):
            return None

        return colon_pos + 1

    def _filter_backward_scope_references(
        self,
        content: str,
        relation_start: int,
        candidate_references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """Filter backward references by the nearest closing separator on the left."""
        scope_start = self._find_previous_separator(
            content=content,
            start_pos=relation_start,
            separators=(".", ";", "\n", ":"),
        ) + 1
        scoped_references = [
            reference
            for reference in candidate_references
            if scope_start <= reference.position_start
            and reference.position_end <= relation_start
        ]

        return self._filter_references_by_parentheses_scope(
            content=content,
            relation_start=relation_start,
            references=scoped_references,
        )

    def _select_inherited_match_references(
        self,
        prepared_references: List[PreparedReference],
        content: str
    ) -> List[PreparedReference]:
        """Synthetic relations inherited from ancestor content may only target current-scope refs."""
        sentence_scopes = self._build_sentence_scopes(content)
        collected_references: List[PreparedReference] = []
        previous_scope: Optional[Dict] = None

        for scope in sentence_scopes:
            scoped_references = [
                reference
                for reference in prepared_references
                if scope["start_pos"] <= reference.position_start
                and reference.position_start < scope["end_pos"]
            ]
            if not scoped_references:
                if collected_references:
                    break
                continue

            scoped_references = self._filter_references_by_parentheses_scope(
                content=content,
                relation_start=self.SYNTHETIC_RELATION_POSITION,
                references=scoped_references,
            )
            if not scoped_references:
                if collected_references:
                    break
                continue

            if previous_scope is not None:
                bridge_text = content[previous_scope["end_pos"]:scope["start_pos"]]
                if ";" not in bridge_text:
                    break

            collected_references.extend(scoped_references)
            previous_scope = scope

        if (
            collected_references
            and not any(
                key in self.CLAUSE_COMPONENT_KEYS
                for key in collected_references[0].reference
            )
        ):
            collected_references = self._limit_references_to_nearest_cluster(
                content=content,
                references=collected_references,
                direction="forward",
            )

        return collected_references

    def _select_scoped_match_references(
        self,
        prepared_references: List[PreparedReference],
        relation_start: int,
        relation_end: int,
        content: str
    ) -> List[PreparedReference]:
        """Apply scope rules before final relation/reference matching."""
        if relation_start == self.SYNTHETIC_RELATION_POSITION:
            return self._select_inherited_match_references(
                prepared_references=prepared_references,
                content=content,
            )

        references_before = [
            reference
            for reference in prepared_references
            if reference.position_end <= relation_start
        ]
        references_after = [
            reference
            for reference in prepared_references
            if reference.position_start >= relation_end
        ]

        backward_references = self._filter_backward_scope_references(
            content=content,
            relation_start=relation_start,
            candidate_references=references_before,
        )
        backward_references = self._limit_references_to_nearest_cluster(
            content=content,
            references=backward_references,
            direction="backward",
        )
        listing_anchor_start = self._find_listing_anchor_start(
            content=content,
            relation_end=relation_end,
            candidate_references=references_after,
        )
        if listing_anchor_start is not None:
            after_references = self._filter_forward_like_scope_references(
                content=content,
                relation_start=relation_start,
                candidate_references=references_after,
                anchor_start=listing_anchor_start,
            )
        else:
            after_references = self._filter_forward_like_scope_references(
                content=content,
                relation_start=relation_start,
                candidate_references=references_after,
                anchor_start=relation_end,
            )
            after_references = self._limit_references_to_nearest_cluster(
                content=content,
                references=after_references,
                direction="forward",
            )

        if after_references and not backward_references:
            return after_references

        if backward_references and not after_references:
            return backward_references

        if not backward_references and not after_references:
            return []

        nearest_before_gap = min(
            relation_start - reference.position_end
            for reference in backward_references
        )
        nearest_after_gap = min(
            reference.position_start - relation_end
            for reference in after_references
        )
        if nearest_before_gap <= nearest_after_gap:
            return backward_references

        return after_references

    def _build_relation_match(
        self,
        relation_type: str,
        relation_start: int,
        relation_end: int,
        matched_reference: PreparedReference
    ) -> Dict:
        """Create the public match payload for one relation/reference pair."""
        return {
            "relation_type": relation_type,
            "relation_position_start": relation_start,
            "relation_position_end": relation_end,
            "reference_position_start": matched_reference.full_position_start,
            "reference_position_end": matched_reference.full_position_end,
            "reference": self._copy_reference(matched_reference.reference),
        }



    def _get_next_relation_start(
        self,
        ordered_relations: List[Dict],
        current_relation: Dict,
        relation_start: int,
        content: str
    ) -> int:
        """Return the start of the next relation cue after the current one."""
        return min(
            (
                item.get("position_start", len(content))
                for item in ordered_relations
                if item is not current_relation
                and item.get("position_start") is not None
                and item.get("position_start") > relation_start
            ),
            default=len(content),
        )

    def _get_relation_scope_end(
        self,
        content: str,
        relation_end: int,
        next_relation_start: int
    ) -> int:
        """Return the right boundary used by expansion policies."""
        return min(
            self._find_next_separator(
                content=content,
                start_pos=relation_end,
                separators=(".", "\n"),
            ),
            next_relation_start,
        )

    @staticmethod
    def _has_reference_before_relation(
        prepared_references: List[PreparedReference],
        relation_start: int
    ) -> bool:
        """Return True when any prepared reference ends before the relation cue."""
        return any(
            reference.position_end <= relation_start
            for reference in prepared_references
        )

    @staticmethod
    def _can_expand_until_next_relation(
        content: str,
        matched_references: List[PreparedReference],
        scope_end: int
    ) -> bool:
        """Block forward expansion when another list starts after the current targets."""
        return not (
            matched_references
            and ":" in content[
                matched_references[-1].full_position_end:scope_end
            ]
        )

    def _expand_reference_targets_for_relation(
        self,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
        relation_type: str,
        relation_start: int,
        relation_end: int,
        scope_end: int,
        content: str,
        phrase_level_amendment_pattern: re.Pattern[str]
    ) -> List[PreparedReference]:
        """Apply relation-specific expansion policies after scope selection."""
        has_reference_before_relation = self._has_reference_before_relation(
            prepared_references=prepared_references,
            relation_start=relation_start,
        )
        if (
            relation_start == self.SYNTHETIC_RELATION_POSITION
            or has_reference_before_relation
        ):
            return matched_references

        can_expand_until_next_relation = self._can_expand_until_next_relation(
            content=content,
            matched_references=matched_references,
            scope_end=scope_end,
        )
        if not can_expand_until_next_relation:
            return matched_references

        if relation_type in self.DETAIL_GUIDANCE_RELATION_TYPES:
            return [
                reference
                for reference in prepared_references
                if relation_end <= reference.position_start < scope_end
            ]

        if (
            relation_type == "sua_doi_bo_sung"
            and phrase_level_amendment_pattern.search(
                self._normalize_relation_text(content[:scope_end])
            ) is not None
        ):
            return [
                reference
                for reference in prepared_references
                if relation_end <= reference.position_start < scope_end
            ]

        return matched_references

    def _filter_inserted_amendment_references(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        matched_references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """Keep newly inserted clause labels before 'vào sau/trước' anchors."""
        if relation_type != "sua_doi_bo_sung" or len(matched_references) <= 1:
            return matched_references

        scope_end = self._find_next_separator(
            content=content,
            start_pos=relation_end,
            separators=(".", ";", "\n"),
        )
        scope_text = content[relation_end:scope_end]
        marker = self.INSERTION_ANCHOR_PATTERN.search(scope_text)
        if not marker:
            return matched_references

        marker_start = relation_end + marker.start()

        filtered_references = [
            reference
            for reference in matched_references
            if reference.position_start < marker_start
        ]

        return (
            self._pair_inserted_targets_with_inherited_documents(filtered_references)
            or filtered_references
            or matched_references
        )

    def _filter_inserted_child_targets_to_first_document(
        self,
        content: str,
        relation: Dict,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Avoid duplicating a locally inserted child provision across inherited parents."""
        if relation_type != "sua_doi_bo_sung" or len(matched_references) <= 1:
            return matched_references

        normalized_value = unidecode(relation.get("relation_value") or "").lower()
        if not normalized_value.startswith("bo sung"):
            return matched_references

        normalized_content = unidecode(content or "").lower()
        if not self.INSERTED_CHILD_KHOAN_SELF_TARGET_PATTERN.search(normalized_content):
            return matched_references

        filtered_references: List[PreparedReference] = []
        seen_inserted_targets = set()

        for reference in matched_references:
            target_key = self._get_specific_clause_component_key(reference)
            doc_key = self._get_document_component_key(reference)
            if (
                target_key is None
                or target_key[0] != "khoan"
                or doc_key is None
            ):
                filtered_references.append(reference)
                continue

            if target_key in seen_inserted_targets:
                continue
            seen_inserted_targets.add(target_key)
            filtered_references.append(reference)

        return filtered_references or matched_references

    def _pair_inserted_targets_with_inherited_documents(
        self,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """When a heading names multiple amended documents, pair inserted labels by order."""
        if len(matched_references) <= 1:
            return matched_references

        target_order: List[Tuple] = []
        doc_order: List[Tuple] = []
        reference_keys: List[Tuple[PreparedReference, Optional[Tuple], Optional[Tuple]]] = []

        for reference in matched_references:
            target_key = self._get_specific_clause_component_key(reference)
            doc_key = self._get_document_component_key(reference)
            reference_keys.append((reference, target_key, doc_key))
            if target_key is not None and target_key not in target_order:
                target_order.append(target_key)
            if doc_key is not None and doc_key not in doc_order:
                doc_order.append(doc_key)

        if len(doc_order) <= 1 or not target_order or len(target_order) != len(doc_order):
            return matched_references

        shared_anchor_key = self._get_shared_inserted_target_anchor_key(
            [reference for reference, target_key, _ in reference_keys if target_key is not None]
        )
        if shared_anchor_key is not None:
            first_doc_key = doc_order[0]
            filtered_references: List[PreparedReference] = []
            for reference, target_key, doc_key in reference_keys:
                if target_key is None or doc_key is None:
                    filtered_references.append(reference)
                    continue
                if doc_key == first_doc_key:
                    filtered_references.append(reference)
            return filtered_references or matched_references

        filtered_references: List[PreparedReference] = []
        for reference, target_key, doc_key in reference_keys:
            if target_key is None or doc_key is None:
                filtered_references.append(reference)
                continue

            expected_doc_index = target_order.index(target_key)
            if doc_key == doc_order[expected_doc_index]:
                filtered_references.append(reference)

        return filtered_references

    def _get_shared_inserted_target_anchor_key(
        self,
        references: List[PreparedReference],
    ) -> Optional[Tuple]:
        """Return the common parent anchor for sibling inserted targets, if any."""
        anchor_keys = {
            self._get_inserted_target_anchor_key(reference)
            for reference in references
        }
        anchor_keys.discard(None)
        if len(anchor_keys) == 1:
            return next(iter(anchor_keys))
        return None

    @staticmethod
    def _get_inserted_target_anchor_key(
        reference: PreparedReference,
    ) -> Optional[Tuple]:
        """Return the parent clause anchor for an inserted child target."""
        if isinstance(reference.reference.get("diem"), dict):
            khoan = reference.reference.get("khoan")
            dieu = reference.reference.get("dieu")
            if isinstance(khoan, dict) or isinstance(dieu, dict):
                return (
                    "diem_parent",
                    (
                        khoan.get("information"),
                        khoan.get("position_start"),
                        khoan.get("position_end"),
                    ) if isinstance(khoan, dict) else None,
                    (
                        dieu.get("information"),
                        dieu.get("position_start"),
                        dieu.get("position_end"),
                    ) if isinstance(dieu, dict) else None,
                )

        if isinstance(reference.reference.get("khoan"), dict):
            dieu = reference.reference.get("dieu")
            if isinstance(dieu, dict):
                return (
                    "khoan_parent",
                    (
                        dieu.get("information"),
                        dieu.get("position_start"),
                        dieu.get("position_end"),
                    ),
                )

        return None

    @staticmethod
    def _get_specific_clause_component_key(
        reference: PreparedReference,
    ) -> Optional[Tuple[str, Optional[str], Optional[int], Optional[int]]]:
        """Return the most specific clause component identity for pairing."""
        for component_key in ("diem", "khoan", "dieu"):
            component = reference.reference.get(component_key)
            if isinstance(component, dict):
                return (
                    component_key,
                    component.get("information"),
                    component.get("position_start"),
                    component.get("position_end"),
                )
        return None

    def _get_document_component_key(
        self,
        reference: PreparedReference,
    ) -> Optional[Tuple[str, Optional[str], Optional[int], Optional[int]]]:
        """Return the primary document component identity for pairing."""
        primary_document = self._get_primary_document_component(reference.reference)
        if primary_document is None:
            return None

        doc_key, doc_info = primary_document
        return (
            doc_key,
            doc_info.get("information"),
            doc_info.get("position_start"),
            doc_info.get("position_end"),
        )

    def _expand_detail_list_clause_targets(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Attach a preceding detailed law target to clauses listed after ``bao gồm``."""
        if relation_type not in self.DETAIL_GUIDANCE_RELATION_TYPES:
            return matched_references

        document_anchor = next(
            (
                reference
                for reference in matched_references
                if (
                    reference.position_start >= relation_end
                    and not self._is_clause_scoped_reference(reference.reference)
                    and self._get_primary_document_component(reference.reference)
                )
            ),
            None,
        )
        if document_anchor is None:
            return matched_references

        marker = self.DETAIL_LIST_MARKER_PATTERN.search(
            content,
            document_anchor.full_position_end,
        )
        if not marker:
            return matched_references

        doc_key, doc_component = self._get_primary_document_component(
            document_anchor.reference
        )
        clause_targets = [
            reference
            for reference in prepared_references
            if (
                reference.position_start >= marker.end()
                and self._is_clause_scoped_reference(reference.reference)
                and self._get_primary_document_component(reference.reference) is None
            )
        ]
        if not clause_targets:
            return matched_references

        expanded_references: List[PreparedReference] = []
        for clause_target in clause_targets:
            combined_reference = self._copy_reference(clause_target.reference)
            combined_reference[doc_key] = self._copy_reference({doc_key: doc_component})[doc_key]
            expanded_references.append(
                PreparedReference(
                    reference=combined_reference,
                    position_start=clause_target.position_start,
                    position_end=clause_target.position_end,
                    full_position_start=clause_target.full_position_start,
                    full_position_end=clause_target.full_position_end,
                )
            )

        return expanded_references

    def _filter_existing_detail_guidance_document_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop old laws cited as objects of existing guiding-document phrases."""
        if relation_type not in self.DETAIL_GUIDANCE_RELATION_TYPES or not matched_references:
            return matched_references

        normalized_content = unidecode(content or "").lower()
        filtered_references: List[PreparedReference] = []
        for reference in matched_references:
            prefix_start = max(
                normalized_content.rfind(separator, 0, reference.position_start)
                for separator in (".", ";", ":", "\n")
            ) + 1
            prefix = normalized_content[prefix_start:reference.position_start]
            tail_end = min(len(normalized_content), reference.full_position_end + 180)
            tail = normalized_content[reference.full_position_end:tail_end]
            if self.EXISTING_DETAIL_GUIDANCE_DOCUMENT_PREFIX_PATTERN.search(prefix[-180:]):
                continue
            if self.EXISTING_DETAIL_GUIDANCE_DOCUMENT_TAIL_PATTERN.search(tail[:180]):
                continue
            filtered_references.append(reference)

        return filtered_references

    def _should_use_inserted_article_anchor(
        self,
        matched_references: List[PreparedReference],
        marker_start: int,
    ) -> bool:
        """Article insertions like ``Điều 51a vào sau Điều 51`` map to the anchor."""
        inserted_references = [
            reference
            for reference in matched_references
            if reference.position_start < marker_start
        ]
        anchor_references = [
            reference
            for reference in matched_references
            if reference.position_start >= marker_start
        ]
        if not inserted_references or not anchor_references:
            return False

        has_inserted_article_suffix = any(
            self._is_alphanumeric_article_reference(reference.reference)
            for reference in inserted_references
        )
        has_anchor_article = any(
            "dieu" in reference.reference
            for reference in anchor_references
        )
        return has_inserted_article_suffix and has_anchor_article

    @staticmethod
    def _is_alphanumeric_article_reference(reference: Dict) -> bool:
        article = reference.get("dieu")
        if not isinstance(article, dict):
            return False
        information = unidecode(article.get("information", "") or "").lower()
        return re.search(r"\bdieu\s+\d+[a-z]\b", information, re.IGNORECASE) is not None

    def _expand_dan_chieu_document_list_references(
        self,
        content: str,
        relation_type: str,
        relation_start: int,
        relation_end: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Keep all document items in "theo cac quy dinh tai ..." lists."""
        if relation_type != "dan_chieu":
            return matched_references

        normalized_content = unidecode(content or "").lower()
        if not self.DAN_CHIEU_DOCUMENT_LIST_CUE_PATTERN.search(
            normalized_content,
            relation_start,
            relation_end,
        ):
            return matched_references

        sentence_end = self._find_next_separator(
            content=content,
            start_pos=relation_end,
            separators=(".", "\n"),
        )
        stop_match = self.DAN_CHIEU_EXCEPTION_STOP_PATTERN.search(
            normalized_content,
            relation_end,
            sentence_end,
        )
        scope_end = stop_match.start() if stop_match else sentence_end
        expanded_references = [
            reference
            for reference in prepared_references
            if (
                relation_start <= reference.position_start < scope_end
                and not self._is_clause_scoped_reference(reference.reference)
            )
        ]

        return expanded_references or matched_references

    def _filter_self_document_clause_inherited_targets(
        self,
        content: str,
        relation_type: str,
        relation_start: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Do not attach ``khoan/dieu ... cua Luat nay`` to an earlier external doc."""
        if relation_type != "dan_chieu":
            return matched_references

        filtered_references: List[PreparedReference] = []
        for reference in matched_references:
            clause_components = [
                value
                for key, value in reference.reference.items()
                if key in self.CLAUSE_COMPONENT_KEYS
                and isinstance(value, dict)
                and value.get("position_start") is not None
                and value.get("position_end") is not None
            ]
            if not clause_components:
                filtered_references.append(reference)
                continue

            primary_document = self._get_primary_document_component(reference.reference)
            if not primary_document:
                filtered_references.append(reference)
                continue

            _, document_component = primary_document
            document_start = document_component.get("position_start")
            if document_start is None:
                filtered_references.append(reference)
                continue

            clause_start = min(int(item["position_start"]) for item in clause_components)
            clause_end = max(int(item["position_end"]) for item in clause_components)
            normalized_tail = unidecode(content[clause_end:clause_end + 80]).lower()
            inherited_document_before_clause = document_start < clause_start
            self_document_tail = self.SELF_DOCUMENT_CLAUSE_TAIL_PATTERN.search(normalized_tail)
            if (
                (inherited_document_before_clause or document_start > clause_end)
                and self_document_tail
            ):
                if document_start > clause_end and document_start - clause_end < self_document_tail.start():
                    filtered_references.append(reference)
                    continue
                continue

            filtered_references.append(reference)

        return filtered_references

    def _filter_dan_chieu_self_document_tail_references(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop external laws in tails like ``Luật này, Luật X và quy định khác``."""
        if relation_type != "dan_chieu" or relation_end < 0:
            return matched_references

        filtered_references: List[PreparedReference] = []
        for reference in matched_references:
            prefix = unidecode(content[relation_end:reference.position_start] or "").lower()
            suffix = unidecode(content[reference.position_end:reference.position_end + 120] or "").lower()
            if (
                self.SELF_DOCUMENT_LIST_PREFIX_PATTERN.search(prefix)
                and self.RELATED_LAW_TAIL_PATTERN.search(suffix)
            ):
                continue
            filtered_references.append(reference)

        return filtered_references

    def _filter_partial_phrase_amendment_targets(
        self,
        content: str,
        relation: Dict,
        relation_type: str,
        relation_end: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Attach synthetic phrase-level amendments to the clause after "tai"."""
        if (
            relation_type != "sua_doi_bo_sung"
            or len(matched_references) <= 1
            or relation.get("relation_value") != "Bãi bỏ một phần"
        ):
            return matched_references

        normalized_content = unidecode(content or "").lower()
        phrase_start = max(relation_end, 0)
        phrase_match = self.PARTIAL_PHRASE_CUE_PATTERN.search(
            normalized_content,
            phrase_start,
        )
        if not phrase_match:
            return matched_references

        marker_matches = list(
            self.PARTIAL_PHRASE_TARGET_MARKER_PATTERN.finditer(
                normalized_content,
                phrase_match.end(),
            )
        )
        if not marker_matches:
            return matched_references

        target_start = marker_matches[-1].start()
        phrase_targets = [
            reference
            for reference in matched_references
            if (
                self._is_clause_scoped_reference(reference.reference)
                and reference.position_start >= target_start
            )
        ]

        return phrase_targets or matched_references

    def _filter_repeal_targets_before_partial_phrase(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Keep repeal targets before a following phrase-level amendment target."""
        if relation_type != "bai_bo" or len(matched_references) <= 1:
            return matched_references

        normalized_content = unidecode(content or "").lower()
        phrase_match = self.PARTIAL_PHRASE_CUE_PATTERN.search(
            normalized_content,
            max(relation_end, 0),
        )
        if not phrase_match:
            return matched_references

        before_phrase = [
            reference
            for reference in matched_references
            if reference.position_start < phrase_match.start()
        ]
        after_phrase_clauses = [
            reference
            for reference in matched_references
            if (
                reference.position_start >= phrase_match.start()
                and self._is_clause_scoped_reference(reference.reference)
            )
        ]
        if before_phrase and after_phrase_clauses:
            return before_phrase

        return matched_references

    def _filter_legislative_program_project_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Do not treat legislative-program project additions as law amendments."""
        if relation_type != "sua_doi_bo_sung" or not matched_references:
            return matched_references

        normalized_content = unidecode(content or "").lower()
        if not self.LEGISLATIVE_PROGRAM_PROJECT_PATTERN.search(normalized_content):
            return matched_references

        return []

    def _filter_transition_temporal_repeal_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop laws cited only to define when repealed transition rules started."""
        if relation_type != "bai_bo" or not matched_references:
            return matched_references

        normalized_content = unidecode(content or "").lower()
        if not self.TRANSITION_PROVISION_REPEAL_PATTERN.search(normalized_content):
            return matched_references

        filtered_references: List[PreparedReference] = []
        for reference in matched_references:
            window_start = max(0, reference.position_start - 120)
            window_end = min(
                len(normalized_content),
                getattr(reference, "full_position_end", reference.position_end) + 160,
            )
            reference_window = normalized_content[window_start:window_end]
            if self.TEMPORAL_EFFECTIVE_REFERENCE_PATTERN.search(reference_window):
                continue
            filtered_references.append(reference)

        return filtered_references

    def _filter_broad_phrase_intro_amendment_reference(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop a doc-only intro target once the post-intro clause target is explicit."""
        if relation_type != "sua_doi_bo_sung" or len(matched_references) <= 1:
            return matched_references

        intro_match = self.NHU_SAU_INTRO_PATTERN.search(content or "")
        if not intro_match:
            return matched_references

        clause_target_ids = {
            identifier
            for reference in matched_references
            if reference.position_start >= intro_match.end()
            and self._is_clause_scoped_reference(reference.reference)
            if (identifier := self._extract_reference_document_identifier(reference.reference))
        }
        if not clause_target_ids:
            return matched_references

        filtered_references = [
            reference
            for reference in matched_references
            if not (
                reference.position_start < intro_match.start()
                and not self._is_clause_scoped_reference(reference.reference)
                and self._extract_reference_document_identifier(reference.reference)
                in clause_target_ids
            )
        ]

        return filtered_references

    def _filter_numbered_item_repeal_dan_chieu_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop attached-document citations from item repeal sentences."""
        if relation_type != "dan_chieu" or not matched_references:
            return matched_references

        filtered_references: List[PreparedReference] = []
        for reference in matched_references:
            sentence_start, sentence_end = self._find_sentence_scope_for_position(
                content=content,
                position=reference.position_start,
                delimiters=(".", "\n"),
            )
            sentence = unidecode(content[sentence_start:sentence_end] or "").lower()
            if self.NUMBERED_ATTACHED_ITEM_REPEAL_SENTENCE_PATTERN.search(sentence):
                continue
            filtered_references.append(reference)

        return filtered_references

    @staticmethod
    def _find_dinh_chinh_intro_end(content: str) -> Optional[int]:
        normalized_content = unidecode(content or "").lower()
        match = re.search(r"\bdinh\s+chinh\b.*?\bnhu\s+sau\s*:", normalized_content, re.DOTALL)
        return match.end() if match else None

    @staticmethod
    def _is_inside_quote_scope(content: str, position: int, scope_start: int) -> bool:
        prefix = content[scope_start:position]
        if prefix.count("“") > prefix.count("”"):
            return True
        return prefix.count('"') % 2 == 1

    def _is_dinh_chinh_operational_reference(
        self,
        content: str,
        reference: PreparedReference,
        intro_end: int,
    ) -> bool:
        if self._is_inside_quote_scope(content, reference.position_start, intro_end):
            return False

        if any(key in self.CLAUSE_COMPONENT_KEYS for key in reference.reference):
            operation_window = unidecode(
                content[intro_end:min(len(content), reference.full_position_end + 260)] or ""
            ).lower()
            return self.DINH_CHINH_OPERATIONAL_MARKER_PATTERN.search(operation_window) is not None

        bridge = unidecode(content[intro_end:reference.position_start]).lower()
        return re.search(r"\bkem\s+theo\s*$", bridge[-80:]) is not None

    def _expand_dinh_chinh_intro_references(
        self,
        content: str,
        relation_type: str,
        relation_start: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """For correction intros, include operative targets after ``như sau:``."""
        if relation_type != "dinh_chinh" or relation_start < 0:
            return matched_references

        intro_end = self._find_dinh_chinh_intro_end(content)
        if intro_end is None or relation_start > intro_end:
            return matched_references

        expanded_references = list(matched_references)
        expanded_references.extend(
            reference
            for reference in prepared_references
            if reference.position_start >= intro_end
            and self._is_dinh_chinh_operational_reference(
                content=content,
                reference=reference,
                intro_end=intro_end,
            )
        )
        return expanded_references

    def _filter_action_descriptive_tail_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop documents cited only inside a descriptive title after the action target."""
        if relation_type not in {"bai_bo", "huy_bo", "ngung_hieu_luc"} or len(matched_references) <= 1:
            return matched_references

        ordered_references = sorted(
            matched_references,
            key=lambda item: (item.position_start, item.position_end),
        )
        first_reference = ordered_references[0]
        filtered_references = [first_reference]

        for reference in ordered_references[1:]:
            raw_bridge = content[first_reference.full_position_end:reference.position_start] or ""
            if re.search(r"(?:^|[\r\n])\s*(?:[-–•]|\d+[.)]|\(?[a-zđ]\))\s*$", raw_bridge, re.IGNORECASE):
                filtered_references.append(reference)
                continue
            bridge = unidecode(raw_bridge).lower()
            descriptive_tail_pattern = (
                self.NGUNG_HIEU_LUC_DESCRIPTIVE_TAIL_PATTERN
                if relation_type == "ngung_hieu_luc"
                else self.ACTION_DESCRIPTIVE_TAIL_PATTERN
            )
            if descriptive_tail_pattern.search(bridge):
                continue
            filtered_references.append(reference)

        return filtered_references or matched_references

    def _expand_action_semicolon_list_references(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        next_relation_start: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """A single action cue can govern semicolon-separated target items."""
        if relation_type not in self.SEMICOLON_LIST_ACTION_RELATION_TYPES:
            return matched_references

        scope_end = min(
            self._find_next_separator(
                content=content,
                start_pos=relation_end,
                separators=(".", "\n"),
            ),
            next_relation_start,
        )
        if ";" not in content[relation_end:scope_end]:
            return matched_references

        expanded_references = [
            reference
            for reference in prepared_references
            if (
                reference.position_start < scope_end
                and reference.position_end >= relation_end
            )
        ]
        if not expanded_references:
            return matched_references

        has_direct_semicolon_item = False
        for reference in expanded_references:
            semicolon_pos = content.rfind(";", relation_end, reference.position_start)
            if semicolon_pos == -1:
                continue
            bridge = content[semicolon_pos + 1:reference.position_start]
            if re.fullmatch(r"\s*(?:[-–•]|\(?[a-zđ]\)|\d+[\).])?\s*", bridge, re.IGNORECASE):
                has_direct_semicolon_item = True
                break

        if not has_direct_semicolon_item:
            return matched_references

        return expanded_references or matched_references

    def _expand_sdbs_scope_references(
        self,
        content: str,
        relation_type: str,
        relation_start: int,
        relation_end: int,
        next_relation_start: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Phrase-level amendments can target every reference before the sentence ends."""
        if relation_type != "sua_doi_bo_sung" or relation_start < 0:
            return matched_references

        cue_text = unidecode(content[relation_start:relation_end] or "").lower()
        suffix = unidecode(content[relation_end:relation_end + 80] or "").lower()
        is_clause_repeal_amendment = (
            re.search(r"\bbai\s+bo\b", cue_text)
            and re.search(r"^\s*(?:diem|khoan|dieu)\b", suffix)
        )
        if (
            not is_clause_repeal_amendment
            and not re.search(
                r"\b(?:sua\s+doi|bo\s+sung|bo\s+cum\s+tu|bai\s+bo\s+cum\s+tu|thay\s+(?:the|cum\s+tu|tu))",
                cue_text,
            )
        ):
            return matched_references

        scope_end = self._find_next_separator(
            content=content,
            start_pos=relation_end,
            separators=(".", "\n"),
        )
        scope_end = min(scope_end, next_relation_start)
        scoped_references = [
            reference
            for reference in prepared_references
            if relation_end <= reference.position_start < scope_end
        ]
        if len(scoped_references) <= len(matched_references):
            return matched_references

        return scoped_references

    def _reference_has_document_date(self, reference: PreparedReference) -> bool:
        primary_document = self._get_primary_document_component(reference.reference)
        if primary_document is None:
            return False

        _, doc_info = primary_document
        information = doc_info.get("information", "")
        return self.DOCUMENT_DATE_PATTERN.search(information or "") is not None

    def _filter_dinh_chinh_alias_references(
        self,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop short aliases when the same corrected document is already dated."""
        if relation_type != "dinh_chinh" or len(matched_references) <= 1:
            return matched_references

        dated_identifiers = {
            identifier
            for reference in matched_references
            if (identifier := self._extract_reference_document_identifier(reference.reference))
            and self._reference_has_document_date(reference)
        }
        if not dated_identifiers:
            return matched_references

        filtered_references = [
            reference
            for reference in matched_references
            if (
                (identifier := self._extract_reference_document_identifier(reference.reference))
                not in dated_identifiers
                or self._reference_has_document_date(reference)
            )
        ]
        return filtered_references or matched_references

    def _is_dinh_chinh_descriptive_intro_continuation(
        self,
        content: str,
        previous_reference: PreparedReference,
        reference: PreparedReference,
    ) -> bool:
        bridge = content[previous_reference.full_position_end:reference.position_start]
        return (
            self.DINH_CHINH_DESCRIPTIVE_INTRO_BRIDGE_PATTERN.search(bridge or "")
            is not None
            and re.search(r"\bvà\s*$", bridge or "", re.IGNORECASE) is not None
        )

    def _filter_dinh_chinh_descriptive_intro_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Keep the actual correction target, not later documents in its title."""
        if relation_type != "dinh_chinh" or len(matched_references) <= 1:
            return matched_references

        intro_end = self._find_dinh_chinh_intro_end(content)
        if intro_end is None:
            return matched_references

        ordered_references = sorted(
            matched_references,
            key=lambda item: (item.position_start, item.position_end),
        )
        filtered_references: List[PreparedReference] = []
        previous_pre_intro_reference: Optional[PreparedReference] = None

        for reference in ordered_references:
            if reference.position_start >= intro_end:
                filtered_references.append(reference)
                continue

            if (
                previous_pre_intro_reference is not None
                and self._is_dinh_chinh_descriptive_intro_continuation(
                    content=content,
                    previous_reference=previous_pre_intro_reference,
                    reference=reference,
                )
            ):
                previous_pre_intro_reference = reference
                continue

            filtered_references.append(reference)
            previous_pre_intro_reference = reference

        return filtered_references or matched_references

    def _document_number_core(self, information: str) -> Optional[str]:
        match = self.DOCUMENT_NUMBER_CORE_PATTERN.search(information or "")
        return match.group(1) if match else None

    def _harmonize_dinh_chinh_intro_document_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        if relation_type != "dinh_chinh" or len(matched_references) <= 1:
            return matched_references

        intro_end = self._find_dinh_chinh_intro_end(content)
        if intro_end is None:
            return matched_references

        intro_documents: Dict[str, Tuple[str, Dict]] = {}
        post_intro_clause_cores = set()
        for reference in matched_references:
            primary_document = self._get_primary_document_component(reference.reference)
            if primary_document is None:
                continue
            document_key, document_info = primary_document
            core = self._document_number_core(document_info.get("information", ""))
            if not core:
                continue
            if (
                reference.position_start < intro_end
                and not self._is_clause_scoped_reference(reference.reference)
                and self._reference_has_document_date(reference)
            ):
                intro_documents[core] = (document_key, document_info)
            elif (
                reference.position_start >= intro_end
                and document_info.get("position_start", reference.position_start) >= intro_end
                and self._is_clause_scoped_reference(reference.reference)
            ):
                post_intro_clause_cores.add(core)

        if not intro_documents or not post_intro_clause_cores:
            return matched_references

        harmonized: List[PreparedReference] = []
        for reference in matched_references:
            primary_document = self._get_primary_document_component(reference.reference)
            if primary_document is None:
                harmonized.append(reference)
                continue

            document_key, document_info = primary_document
            core = self._document_number_core(document_info.get("information", ""))
            if core in post_intro_clause_cores and reference.position_start < intro_end:
                continue

            if (
                core in intro_documents
                and reference.position_start >= intro_end
                and document_info.get("position_start", reference.position_start) >= intro_end
                and self._is_clause_scoped_reference(reference.reference)
            ):
                _, intro_document_info = intro_documents[core]
                updated_reference = {
                    key: value.copy() if isinstance(value, dict) else value
                    for key, value in reference.reference.items()
                }
                updated_reference[document_key]["information"] = intro_document_info.get(
                    "information",
                    updated_reference[document_key].get("information"),
                )
                harmonized.append(replace(reference, reference=updated_reference))
                continue

            harmonized.append(reference)

        return harmonized or matched_references

    def _filter_dinh_chinh_scope_references(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        matched_references: List[PreparedReference]
    ) -> List[PreparedReference]:
        """Drop legal-basis refs that appear after the corrected target scope."""
        if (
            relation_type != "dinh_chinh"
            or len(matched_references) <= 1
            or relation_end < 0
        ):
            return matched_references

        intro_end = self._find_dinh_chinh_intro_end(content)
        if intro_end is not None:
            stop_match = self.DINH_CHINH_SCOPE_STOP_PATTERN.search(
                content,
                relation_end,
                intro_end,
            )
            if not stop_match:
                return matched_references

            cutoff = stop_match.start()
            scoped_references = [
                reference
                for reference in matched_references
                if reference.position_start < cutoff
                or reference.position_start >= intro_end
            ]
            return scoped_references or matched_references

        stop_match = self.DINH_CHINH_SCOPE_STOP_PATTERN.search(
            content,
            relation_end,
        )
        if not stop_match:
            return matched_references

        cutoff = stop_match.start()
        scoped_references = [
            reference
            for reference in matched_references
            if reference.position_start < cutoff
        ]

        return scoped_references or matched_references

    def _is_top_level_inserted_article_heading(
        self,
        content: Optional[str],
        relation_start: int,
        relation_value: Optional[str],
        reference: Dict,
    ) -> bool:
        """Article-heading insertions amend the document, not the new article itself."""
        if not content or relation_start < 0 or relation_start > 30:
            return False
        if not self._is_clause_scoped_reference(reference):
            return False
        if self._get_primary_document_component(reference) is None:
            return False

        normalized_relation = re.sub(
            r"\s+",
            " ",
            unidecode(relation_value or "").lower(),
        ).strip(" ,.;:")
        if normalized_relation != "bo sung":
            return False

        normalized_content = unidecode(content or "").lower()
        return self.TOP_LEVEL_INSERTED_ARTICLE_HEADING_PATTERN.search(
            normalized_content
        ) is not None

    def _document_only_prepared_reference(
        self,
        matched_reference: PreparedReference,
    ) -> Optional[PreparedReference]:
        """Return a prepared reference containing only the primary document component."""
        primary_document = self._get_primary_document_component(matched_reference.reference)
        if primary_document is None:
            return None

        doc_key, doc_info = primary_document
        doc_reference = {doc_key: doc_info.copy()}
        span = self._get_reference_match_span(doc_reference)
        if span is None:
            return None

        return PreparedReference(
            reference=doc_reference,
            position_start=span["position_start"],
            position_end=span["position_end"],
            full_position_start=span["position_start"],
            full_position_end=span["position_end"],
        )

    @staticmethod
    def _is_partial_repeal_inherited_document_relation(
        relation_type: str,
        relation_value: Optional[str],
        relation_start: int,
        reference: Dict,
    ) -> bool:
        if relation_type != "sua_doi_bo_sung" or relation_start != -1:
            return False
        if any(key in BaseExtractorShared.CLAUSE_COMPONENT_KEYS for key in reference):
            return False
        normalized_value = unidecode(relation_value or "").lower()
        return "bai bo mot phan" in normalized_value

    def _is_descriptive_title_authority_tail(
        self,
        content: str,
        start_pos: int,
    ) -> bool:
        """Return True when a title citation only describes what the document guides."""
        line_start = content.rfind("\n", 0, start_pos) + 1
        line_end = content.find("\n", start_pos)
        if line_end == -1:
            line_end = len(content)

        normalized_line = unidecode(content[line_start:line_end] or "").lower()
        if not self.TITLE_ACTION_PREFIX_PATTERN.search(normalized_line):
            return False
        if not self.TITLE_DESCRIPTIVE_AUTHORITY_TAIL_PATTERN.search(normalized_line):
            return False

        normalized_prefix = unidecode(content[:start_pos] or "").lower()
        return "can cu" not in normalized_prefix

    def _build_matches_for_reference_set(
        self,
        relation_type: str,
        relation_value: Optional[str],
        relation_start: int,
        relation_end: int,
        matched_references: List[PreparedReference],
        source_so_hieu: Optional[str],
        content: str,
        source_title: Optional[str] = None,
    ) -> List[Dict]:
        """Build public matches after policy filters are applied."""
        matches: List[Dict] = []
        has_whole_document_target = any(
            not self._is_clause_scoped_reference(matched_reference.reference)
            for matched_reference in matched_references
        )

        for matched_reference in matched_references:
            effective_relation_type = self._relation_type_for_reference(
                relation_type=relation_type,
                reference=matched_reference.reference,
                has_whole_document_target=has_whole_document_target,
                content=content,
                relation_start=relation_start,
                relation_end=relation_end,
                matched_reference=matched_reference,
                relation_value=relation_value,
            )
            if self._should_filter_by_authority_policy(
                relation_type=effective_relation_type,
                source_so_hieu=source_so_hieu,
                reference=matched_reference.reference,
            ):
                ref_pos = matched_reference.position_start
                scope_start = max(
                    content.rfind(".", 0, ref_pos),
                    content.rfind("\n", 0, ref_pos),
                ) + 1
                scope_end_candidates = [
                    p for p in (content.find(".", ref_pos), content.find("\n", ref_pos))
                    if p != -1
                ]
                scope_end = min(scope_end_candidates) if scope_end_candidates else len(content)
                sentence = content[scope_start:scope_end]
                if any(p.search(sentence) for p in _DAN_CHIEU_FORWARD_PATTERNS):
                    if self._is_descriptive_title_authority_tail(
                        content=content,
                        start_pos=matched_reference.position_start,
                    ):
                        continue
                    effective_relation_type = "dan_chieu"
                else:
                    continue
            elif self._should_filter_local_to_central_match(
                relation_type=effective_relation_type,
                source_so_hieu=source_so_hieu,
                reference=matched_reference.reference,
            ):
                continue
            if effective_relation_type in ("thay_the", "bai_bo"):
                target_title = self._extract_target_title_from_context(
                    content, matched_reference.reference
                )
                title_sim = self._compute_action_title_similarity(source_title, target_title)
                effective_relation_type = self._refine_action_relation_type(
                    detected=effective_relation_type,
                    source_so_hieu=source_so_hieu,
                    reference=matched_reference.reference,
                    title_sim=title_sim,
                )
                if effective_relation_type == "DROP":
                    continue
            if (
                effective_relation_type == "dan_chieu"
                and self._is_self_application_reference(
                    content=content,
                    source_so_hieu=source_so_hieu,
                    matched_reference=matched_reference,
                )
            ):
                continue

            public_reference = matched_reference
            if self._is_top_level_inserted_article_heading(
                content=content,
                relation_start=relation_start,
                relation_value=relation_value,
                reference=matched_reference.reference,
            ):
                public_reference = (
                    self._document_only_prepared_reference(matched_reference)
                    or matched_reference
                )

            match = self._build_relation_match(
                relation_type=effective_relation_type,
                relation_start=relation_start,
                relation_end=relation_end,
                matched_reference=public_reference,
            )
            if self._is_partial_repeal_inherited_document_relation(
                relation_type=effective_relation_type,
                relation_value=relation_value,
                relation_start=relation_start,
                reference=public_reference.reference,
            ):
                match["_allow_with_clause_action"] = True
            matches.append(match)

        return matches

    def _is_self_application_reference(
        self,
        content: str,
        source_so_hieu: Optional[str],
        matched_reference: PreparedReference,
    ) -> bool:
        """Drop current-document references used only in ``thì áp dụng theo ... này``."""
        if not content or not source_so_hieu:
            return False

        identifier = self._extract_reference_document_identifier(matched_reference.reference)
        if not identifier:
            return False
        if identifier.replace(" ", "").lower() != source_so_hieu.replace(" ", "").lower():
            return False

        prefix = unidecode(
            content[max(0, matched_reference.position_start - 80):matched_reference.position_start]
            or ""
        ).lower()
        return self.SELF_APPLICATION_REFERENCE_PREFIX_PATTERN.search(prefix) is not None

    def _relation_type_for_reference(
        self,
        relation_type: str,
        reference: Dict,
        has_whole_document_target: bool,
        content: Optional[str] = None,
        relation_start: int = -1,
        relation_end: int = -1,
        matched_reference: Optional[PreparedReference] = None,
        relation_value: Optional[str] = None,
    ) -> str:
        """Adjust relation type by target scope."""
        if relation_type == "sua_doi_bo_sung" and self._is_clause_scoped_reference(reference):
            normalized_relation_value = re.sub(
                r"\s+",
                " ",
                unidecode(relation_value or "").lower(),
            ).strip(" ,.;:")
            if normalized_relation_value == "bo sung":
                if self._is_top_level_inserted_article_heading(
                    content=content,
                    relation_start=relation_start,
                    relation_value=relation_value,
                    reference=reference,
                ):
                    return "sua_doi_bo_sung"
                # "Bổ sung từ/cụm từ X" = inserting a specific word/phrase into
                # existing text → modifies the clause → sua_doi, not bo_sung.
                if content is not None and relation_end >= 0:
                    cue_window = unidecode(
                        content[max(0, relation_end - 10):relation_end + 15]
                    ).lower()
                    if self.BO_SUNG_WORD_PHRASE_PATTERN.search(cue_window):
                        return "sua_doi"
                return "bo_sung"
            phrase_target_prefix = ""
            if matched_reference is not None and content is not None:
                phrase_target_prefix = unidecode(
                    content[max(0, relation_end):matched_reference.position_start]
                ).lower()
            if (
                normalized_relation_value.startswith("bai bo")
                and not (
                    re.search(
                        r"\b(?:cum\s+tu|tu)\b.{0,360}\btai\b",
                        phrase_target_prefix,
                    )
                    or re.search(
                        r"\bbai\s+bo\s+(?:mot\s+so\s+)?(?:cac\s+)?(?:cum\s+tu|tu)\b",
                        normalized_relation_value,
                    )
                )
            ):
                return "bai_bo"
            return "sua_doi"

        if (
            relation_type == "bai_bo"
            and matched_reference is not None
            and content is not None
            and self._is_clause_scoped_reference(reference)
        ):
            prefix = unidecode(
                content[max(0, relation_end):matched_reference.position_start]
            ).lower()
            if re.search(r"\b(?:cum\s+tu|tu)\b.{0,360}\btai\b", prefix):
                return "sua_doi"

        if (
            matched_reference is not None
            and content is not None
            and self._is_non_node_component_scoped_reference(content, reference)
            and (
                mapped_relation_type := self._relation_type_for_non_node_component_target(
                    relation_type
                )
            )
        ):
            return mapped_relation_type

        if (
            relation_type == "thay_the"
            and matched_reference is not None
            and content is not None
            and self._is_clause_scoped_reference(reference)
            and self._is_definition_replacement_scope(content)
        ):
            document_start = matched_reference.position_start
            primary_document = self._get_primary_document_component(reference)
            if primary_document is not None:
                _, document_info = primary_document
                if document_info.get("position_start") is not None:
                    document_start = int(document_info["position_start"])
            if not self._is_attached_appendix_source_reference(
                content=content,
                reference_start=document_start,
            ):
                return "sua_doi"

        if (
            relation_type == "thay_the"
            and has_whole_document_target
            and self._is_clause_scoped_reference(reference)
        ):
            return "bai_bo"

        if (
            relation_type == "thay_the"
            and matched_reference is not None
            and PARTIAL_PROVISION_EXPIRY_PATTERN.search(
                (content or "")[
                    max(0, matched_reference.position_start - 80):relation_end
                ]
            )
        ):
            return "dan_chieu"

        if (
            relation_type in {"bai_bo", "thay_the"}
            and matched_reference is not None
            and not self._is_clause_scoped_reference(reference)
            and self._is_attached_appendix_source_reference(
                content=content or "",
                reference_start=matched_reference.position_start,
            )
        ):
            return "sua_doi_bo_sung"

        return relation_type

    def _relation_type_for_non_node_component_target(self, relation_type: str) -> Optional[str]:
        if relation_type in self.NON_NODE_COMPONENT_SDBS_RELATION_TYPES:
            return "sua_doi_bo_sung"
        if relation_type in self.NON_NODE_COMPONENT_DAN_CHIEU_RELATION_TYPES:
            return "dan_chieu"
        if relation_type in self.NON_NODE_COMPONENT_HUONG_DAN_RELATION_TYPES:
            return "huong_dan"
        return None

    def _is_non_node_component_scoped_reference(self, content: str, reference: Dict) -> bool:
        """Detect non-node component targets that collapsed to document references."""
        if self._is_clause_scoped_reference(reference):
            return False

        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return False

        _, document_info = primary_document
        document_start = document_info.get("position_start")
        if not isinstance(document_start, int):
            return False

        scope_start = max(
            content.rfind("\n", 0, document_start),
            content.rfind(";", 0, document_start),
            content.rfind(".", 0, document_start),
        ) + 1
        prefix = unidecode(content[scope_start:document_start] or "").lower()
        return self.NON_NODE_COMPONENT_TARGET_PREFIX_PATTERN.search(prefix) is not None

    def _is_clause_scoped_reference(self, reference: Dict) -> bool:
        return any(key in self.CLAUSE_COMPONENT_KEYS for key in reference)

    def _is_definition_replacement_scope(self, content: str) -> bool:
        normalized = unidecode(content or "").lower()
        return (
            self.DEFINITION_REPLACEMENT_SCOPE_PATTERN.search(normalized) is not None
            and self.DEFINITION_REPLACEMENT_BY_PATTERN.search(normalized) is not None
        )

    def _is_attached_appendix_source_reference(
        self,
        content: str,
        reference_start: int,
    ) -> bool:
        """Detect repeal of items inside an appendix/list attached to a source document."""
        if not content or reference_start < 0:
            return False

        prefix = unidecode(content[max(0, reference_start - 220):reference_start] or "").lower()
        local_prefix = prefix[
            max(prefix.rfind(separator) for separator in (".", ";", "\n")) + 1:
        ]
        return self.ATTACHED_APPENDIX_SOURCE_PREFIX_PATTERN.search(local_prefix) is not None

    def _find_sentence_scope_for_position(
        self,
        content: str,
        position: int,
        delimiters: Optional[Tuple[str, ...]] = None,
    ) -> Tuple[int, int]:
        """Return (start, end) of the sentence scope containing ``position``."""
        if delimiters is None:
            delimiters = (".", ";", "\n")

        scope_start = self._find_previous_separator(
            content=content,
            start_pos=position,
            separators=delimiters,
        ) + 1
        scope_end = self._find_next_separator(
            content=content,
            start_pos=position,
            separators=delimiters,
        )
        return scope_start, scope_end

    @staticmethod
    def _is_forward_of_cue(
        ref: PreparedReference,
        relation_start: int,
        relation_end: int,
    ) -> bool:
        """A reference is forward of the cue if it starts at/after cue end,
        or if it overlaps (starts within the cue but extends beyond it).

        The overlap case is common for ``dan_chieu`` patterns such as
        ``theo quy định của Luật`` where the regex captures the document
        type word that is also the beginning of a reference.
        """
        if ref.position_start >= relation_end:
            return True
        # Overlap: ref starts inside the cue body and extends past cue end.
        if ref.position_start >= relation_start and ref.position_end > relation_end:
            return True
        for key, value in ref.reference.items():
            if key in BaseExtractorShared.CLAUSE_COMPONENT_KEYS:
                continue
            if not isinstance(value, dict):
                continue
            component_start = value.get("position_start")
            component_end = value.get("position_end")
            if (
                component_start is not None
                and component_end is not None
                and component_start >= relation_start
                and component_end > relation_end
            ):
                return True
        return False

    def _filter_amendment_history_references(
        self,
        content: str,
        relation_type: str,
        matched_references: List[PreparedReference],
        relation_context: Optional[Dict] = None,
    ) -> List[PreparedReference]:
        """Drop references that only describe amendment history of a prior target."""
        if relation_type == "ngung_hieu_luc" and len(matched_references) > 1:
            amendment_cues = [
                (match.start(), match.end())
                for match in self.SUSPENDED_AMENDED_TARGET_CUE_PATTERN.finditer(content or "")
            ]
            if amendment_cues:
                source_content = (relation_context or {}).get("source_content") or ""
                source_article_value = self._extract_source_article_heading_value(
                    source_content
                )
                amended_clause_targets: List[PreparedReference] = []
                original_clause_targets: List[PreparedReference] = []
                for reference in matched_references:
                    clause_starts = [
                        value.get("position_start")
                        for key, value in reference.reference.items()
                        if key in self.CLAUSE_COMPONENT_KEYS
                        and isinstance(value, dict)
                        and value.get("position_start") is not None
                    ]
                    doc_starts = [
                        value.get("position_start")
                        for key, value in reference.reference.items()
                        if key not in self.CLAUSE_COMPONENT_KEYS
                        and isinstance(value, dict)
                        and value.get("position_start") is not None
                    ]
                    if not clause_starts:
                        continue
                    clause_start = min(clause_starts)
                    doc_start = min(doc_starts) if doc_starts else reference.position_start
                    if any(
                        cue_end <= clause_start <= cue_end + 120
                        and doc_start >= cue_end
                        for _, cue_end in amendment_cues
                    ):
                        amended_clause_targets.append(reference)
                    elif any(
                        reference.full_position_end <= cue_start
                        for cue_start, _ in amendment_cues
                    ):
                        original_clause_targets.append(reference)
                prefer_amended_target = (
                    source_article_value is not None
                    and any(
                        self._reference_article_value(reference) == source_article_value
                        for reference in amended_clause_targets
                    )
                )
                if prefer_amended_target and amended_clause_targets:
                    return amended_clause_targets
                if not prefer_amended_target and original_clause_targets:
                    return original_clause_targets

            ordered_references = sorted(
                matched_references,
                key=lambda item: (item.position_start, item.position_end),
            )
            amended_targets: List[PreparedReference] = []
            for index, reference in enumerate(ordered_references):
                if index == 0:
                    continue
                previous_reference = ordered_references[index - 1]
                if previous_reference.full_position_end > reference.position_start:
                    continue
                bridge_text = content[
                    previous_reference.full_position_end:reference.position_start
                ]
                normalized_bridge = unidecode(bridge_text or "").lower()
                if self.SUSPENDED_AMENDED_TARGET_BRIDGE_PATTERN.search(
                    normalized_bridge[-220:]
                ):
                    amended_targets.append(reference)
            if amended_targets:
                return amended_targets

        if relation_type in {"sua_doi_bo_sung", "sua_doi", "bo_sung", "bai_bo"} and matched_references:
            relation_direction = (relation_context or {}).get("direction")
            if relation_direction not in {"PASSIVE", "REVERSE"}:
                passive_history_cues = [
                    match.start()
                    for match in self.SDBS_PASSIVE_AMENDMENT_HISTORY_CUE_PATTERN.finditer(
                        content or ""
                    )
                ]
                normalized_content = unidecode(content or "").lower()
                passive_history_cues.extend(
                    match.start()
                    for match in self.INSERTED_AMENDMENT_HISTORY_CUE_PATTERN.finditer(
                        normalized_content
                    )
                )
                if passive_history_cues:
                    current_targets = [
                        reference
                        for reference in matched_references
                        if any(
                            reference.position_start < cue_start
                            and reference.position_end <= cue_start
                            for cue_start in passive_history_cues
                        )
                    ]
                    if current_targets:
                        current_targets = self._filter_cross_joined_passive_history_documents(
                            current_targets,
                            passive_history_cues,
                        )
                        return current_targets

            filtered_history_targets = [
                reference
                for reference in matched_references
                if not self._is_dan_chieu_reference_with_amendment_history(
                    content=content,
                    reference=reference,
                )
            ]
            if len(filtered_history_targets) != len(matched_references):
                return filtered_history_targets

        if (
            (
                relation_type not in self.EXPIRY_TARGET_RELATION_TYPES
                and relation_type != "sua_doi_bo_sung"
                and relation_type not in self.DETAIL_GUIDANCE_RELATION_TYPES
            )
            or len(matched_references) <= 1
        ):
            return matched_references

        ordered_references = sorted(
            matched_references,
            key=lambda item: (item.position_start, item.position_end),
        )
        filtered_references: List[PreparedReference] = []
        inside_amendment_history_run = False

        for index, reference in enumerate(ordered_references):
            if index == 0:
                filtered_references.append(reference)
                continue

            previous_reference = ordered_references[index - 1]
            bridge_text = content[
                previous_reference.full_position_end:reference.position_start
            ]
            normalized_bridge = unidecode(bridge_text or "").lower()
            local_bridge = normalized_bridge[
                max(
                    normalized_bridge.rfind(separator)
                    for separator in (".", ";", ":", "\n")
                ) + 1:
            ]
            if relation_type == "sua_doi_bo_sung":
                is_amendment_history_reference = (
                    self.SDBS_AMENDMENT_HISTORY_REFERENCE_BRIDGE_PATTERN.search(
                        local_bridge[-180:]
                    )
                    is not None
                )
            else:
                is_amendment_history_reference = (
                    self.AMENDMENT_HISTORY_REFERENCE_BRIDGE_PATTERN.search(
                        local_bridge[-180:]
                    )
                    is not None
                )

            if (
                not is_amendment_history_reference
                and inside_amendment_history_run
                and self._is_amendment_history_continuation_reference(
                    bridge_text=bridge_text,
                    reference=reference,
                    allow_loose_connective=relation_type == "keo_dai_hieu_luc",
                )
            ):
                is_amendment_history_reference = True

            if is_amendment_history_reference:
                inside_amendment_history_run = True
                continue

            inside_amendment_history_run = False
            filtered_references.append(reference)

        return filtered_references or matched_references

    def _filter_cross_joined_passive_history_documents(
        self,
        references: List[PreparedReference],
        passive_history_cues: List[int],
    ) -> List[PreparedReference]:
        """Drop same-clause references joined to a document mention inside history text."""
        grouped: Dict[Tuple[Tuple[str, str], ...], List[PreparedReference]] = {}
        for reference in references:
            signature = tuple(
                (key, str(value.get("information", "")))
                for key, value in reference.reference.items()
                if key in self.CLAUSE_COMPONENT_KEYS and isinstance(value, dict)
            )
            grouped.setdefault(signature, []).append(reference)

        filtered: List[PreparedReference] = []
        for group in grouped.values():
            doc_before_cue = [
                reference
                for reference in group
                if self._has_document_component_before_any_cue(
                    reference,
                    passive_history_cues,
                )
            ]
            filtered.extend(doc_before_cue or group)

        return filtered

    def _has_document_component_before_any_cue(
        self,
        reference: PreparedReference,
        passive_history_cues: List[int],
    ) -> bool:
        doc_starts = [
            value.get("position_start")
            for key, value in reference.reference.items()
            if key not in self.CLAUSE_COMPONENT_KEYS
            and isinstance(value, dict)
            and value.get("position_start") is not None
        ]
        if not doc_starts:
            return True
        return any(
            doc_start < cue_start
            for doc_start in doc_starts
            for cue_start in passive_history_cues
        )

    @classmethod
    def _extract_source_article_heading_value(cls, source_content: str) -> Optional[str]:
        """Extract the article number from the ancestor heading, if present."""
        match = cls.SOURCE_ARTICLE_HEADING_PATTERN.search(source_content or "")
        if not match:
            return None
        return unidecode(match.group("value") or "").lower()

    @staticmethod
    def _reference_article_value(reference: PreparedReference) -> Optional[str]:
        """Return the normalized article number carried by a prepared reference."""
        article_component = reference.reference.get("dieu")
        if not isinstance(article_component, dict):
            return None
        information = unidecode(article_component.get("information", "") or "").lower()
        match = re.search(r"\bdieu\s+(\d+[a-zđ]?)\b", information, re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    def _is_dan_chieu_reference_with_amendment_history(
        self,
        content: str,
        reference: PreparedReference,
    ) -> bool:
        """Detect a cited document whose later amendment history is descriptive only."""
        prefix = unidecode(
            content[max(0, reference.position_start - 120):reference.position_start] or ""
        ).lower()
        local_prefix = prefix[
            max(prefix.rfind(separator) for separator in (".", ";", ":", "\n")) + 1:
        ]
        if not self.DAN_CHIEU_AMENDMENT_HISTORY_PREFIX_PATTERN.search(local_prefix):
            return False

        suffix = unidecode(
            content[reference.full_position_end:reference.full_position_end + 220] or ""
        ).lower()
        return self.DAN_CHIEU_AMENDMENT_HISTORY_SUFFIX_PATTERN.search(suffix) is not None

    def _filter_keo_dai_amending_resolution_references(
        self,
        content: str,
        relation_type: str,
        relation_start: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Drop a later resolution cited only as amending the extended target."""
        if (
            relation_type != "keo_dai_hieu_luc"
            or relation_start < 0
            or len(matched_references) <= 1
        ):
            return matched_references

        ordered_references = sorted(
            matched_references,
            key=lambda item: (item.position_start, item.position_end),
        )
        first_identifier = self._extract_reference_document_identifier(
            ordered_references[0].reference
        )
        if not first_identifier:
            return matched_references

        normalized_first_identifier = unidecode(first_identifier).lower()
        first_identifier_pattern = re.escape(normalized_first_identifier)
        first_identifier_pattern = first_identifier_pattern.replace(r"\/", r"\s*/\s*")
        first_identifier_pattern = first_identifier_pattern.replace(r"\-", r"\s*-\s*")

        filtered_references = [ordered_references[0]]
        for reference in ordered_references[1:]:
            scope_end = self._find_next_separator(
                content=content,
                start_pos=reference.full_position_end,
                separators=(".", "\n"),
            )
            suffix = unidecode(
                content[reference.full_position_end:scope_end] or ""
            ).lower()
            if (
                self.AMENDMENT_OF_PREVIOUS_TARGET_SUFFIX_PATTERN.search(suffix)
                and re.search(first_identifier_pattern, suffix)
            ):
                continue

            filtered_references.append(reference)

        return filtered_references or matched_references

    def _is_amendment_history_continuation_reference(
        self,
        bridge_text: str,
        reference: PreparedReference,
        allow_loose_connective: bool = False,
    ) -> bool:
        normalized_bridge = unidecode(bridge_text or "").lower()
        if self.AMENDMENT_HISTORY_CONTINUATION_BRIDGE_PATTERN.fullmatch(
            normalized_bridge
        ) is None:
            if (
                not allow_loose_connective
                or
                re.search(r"\b(?:va|hoac)\s*$", normalized_bridge) is None
                or self.ACTION_RELATION_CONTINUATION_BRIDGE_PATTERN.search(
                    normalized_bridge
                ) is not None
            ):
                return False

        return self._is_bare_numbered_document_reference(reference)

    def _is_bare_numbered_document_reference(self, reference: PreparedReference) -> bool:
        for component in reference.reference.values():
            if not isinstance(component, dict):
                continue
            information = component.get("information")
            if not information:
                continue
            normalized_information = unidecode(str(information)).lower()
            if self.BARE_NUMBERED_DOCUMENT_REFERENCE_PATTERN.search(
                normalized_information
            ):
                return True

        return False

    def _can_expand_detail_guidance_scope(self, content: str, relation_start: int) -> bool:
        """Avoid broad expansion for detail phrases quoted inside amendment text."""
        prefix = content[:relation_start]
        amendment_intro = self.QUOTED_AMENDMENT_INTRO_PATTERN.search(prefix)
        if not amendment_intro:
            return True

        quoted_tail = prefix[amendment_intro.end():]
        return re.search(r"[\"“]", quoted_tail) is None

    def _select_bullet_list_action_references(
        self,
        content: str,
        relation_type: str,
        relation_end: int,
        prepared_references: List[PreparedReference],
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Prefer bullet-list targets after action headings over legal-basis refs."""
        if relation_type not in self.BULLET_LIST_ACTION_RELATION_TYPES:
            return matched_references

        marker = self.BULLET_LIST_START_PATTERN.search(content, relation_end)
        if not marker:
            return matched_references

        list_start = marker.start()
        list_references = [
            reference
            for reference in prepared_references
            if reference.position_start >= list_start
        ]
        return list_references or matched_references

    def _filter_reverse_expiry_edge_targets(
        self,
        content: str,
        relation: Dict,
        relation_type: str,
        relation_start: int,
        matched_references: List[PreparedReference],
    ) -> List[PreparedReference]:
        """Bind expiry edge cases to the one enumerated document that expires."""
        if (
            relation_type != "thay_the"
            or relation.get("hint_group") != "edge_case_thay_the"
            or relation.get("direction") != "REVERSE"
            or len(matched_references) <= 1
        ):
            return matched_references

        ordered_references = sorted(
            matched_references,
            key=lambda item: (item.position_start, item.position_end),
        )
        item_match = self.REVERSE_EXPIRY_ITEM_PATTERN.match(content or "")
        if item_match and len(ordered_references) == 2:
            item_index = int(item_match.group(1)) - 1
            if 0 <= item_index < len(ordered_references):
                return [ordered_references[item_index]]

        segment_start = max(
            content.rfind(separator, 0, relation_start)
            for separator in (";", ".", "\n")
        ) + 1
        local_segment = unidecode(content[segment_start:relation_start] or "").lower()
        if self.AMENDMENT_HISTORY_REFERENCE_BRIDGE_PATTERN.search(local_segment):
            return matched_references

        local_references = [
            reference
            for reference in ordered_references
            if reference.position_start >= segment_start
        ]
        return local_references or matched_references

    def _select_forward_references(
        self,
        content: str,
        relation_start: int,
        relation_end: int,
        prepared_references: List[PreparedReference],
        next_relation_start: int,
    ) -> List[PreparedReference]:
        """Select references that appear after the relation cue within the sentence scope."""
        _, sentence_end = self._find_sentence_scope_for_position(content, relation_end)
        # The fence is the earlier of: next relation cue or sentence end.
        fence = min(sentence_end, next_relation_start)

        # Collect refs after (or overlapping with) the relation cue up to the fence.
        candidates = [
            ref for ref in prepared_references
            if self._is_forward_of_cue(ref, relation_start, relation_end)
            and ref.position_start < fence
        ]
        if candidates:
            return candidates

        # Fallback: if no refs found up to the fence but there are refs before
        # the sentence boundary, try the full sentence scope.
        # E.g., relation type is dan_chieu and the regex only captures the first word of a reference that starts within the cue.
        candidates = [
            ref for ref in prepared_references
            if self._is_forward_of_cue(ref, relation_start, relation_end)
            and ref.position_start < sentence_end
        ]
        return candidates

    def _select_backward_references(
        self,
        content: str,
        relation_start: int,
        prepared_references: List[PreparedReference],
        delimiters: Optional[Tuple[str, ...]] = None,
    ) -> List[PreparedReference]:
        """Select references that appear before the relation cue within the sentence scope."""
        sentence_start, _ = self._find_sentence_scope_for_position(
            content, relation_start, delimiters=delimiters,
        )
        return [
            ref for ref in prepared_references
            if ref.position_end <= relation_start and ref.position_start >= sentence_start
        ]

    def _select_nearest_references(
        self,
        content: str,
        relation_start: int,
        relation_end: int,
        prepared_references: List[PreparedReference],
        next_relation_start: int,
        delimiters: Optional[Tuple[str, ...]] = None,
    ) -> List[PreparedReference]:
        """Select references from the nearest side (forward preferred if equidistant)."""
        forward_refs = self._select_forward_references(
            content, relation_start, relation_end, prepared_references, next_relation_start,
        )
        backward_refs = self._select_backward_references(
            content, relation_start, prepared_references, delimiters=delimiters,
        )

        if forward_refs and not backward_refs:
            return forward_refs
        if backward_refs and not forward_refs:
            return backward_refs
        if not forward_refs and not backward_refs:
            return []

        # Both sides have references – pick the nearer side.
        nearest_forward_gap = min(
            ref.position_start - relation_end for ref in forward_refs
        )
        nearest_backward_gap = min(
            relation_start - ref.position_end for ref in backward_refs
        )
        if nearest_backward_gap <= nearest_forward_gap:
            return backward_refs
        return forward_refs

    def match_relations(
        self,
        references: List[Dict],
        relation_types: List[Dict],
        content: str,
        source_so_hieu: Optional[str] = None,
        source_title: Optional[str] = None,
    ) -> List[Dict]:
        """Match extracted relation keywords with extracted references.

        This implementation relies on the ``direction`` and ``hint_group`` metadata produced 
        by ``extract_relation_types`` to decide how references should be paired with each relation cue.

        Matching rules:
        1. **Inherited / enumerated** (``position_start == -1``):
           The relation was inherited from an ancestor clause.  Match *all*
           references found in the current ``content``.

        2. **PASSIVE** direction:
           The verb form indicates the subject (reference) precedes the cue
           (e.g. "… Luật X *được sửa đổi* …").  Select backward references.

        3. **FORWARD** direction (default):
           The cue precedes the target references
           (e.g. "*Bãi bỏ* Điều 5 Luật X").  Select forward references.

        4. When no references are found on the expected side, fall back to
           the nearest-side heuristic used by the old implementation.
        """
        if not content or not content.strip():
            raise ValueError("content is required for match_relations")

        if not references or not relation_types:
            return []

        prepared_references = self._prepare_references_for_matching(references)
        if not prepared_references:
            return []

        ordered_relations = sorted(
            relation_types,
            key=lambda item: (
                item.get("position_start", item.get("start_pos", 0)),
                item.get("position_end", item.get("end_pos", 0)),
            ),
        )

        matches: List[Dict] = []

        for relation in ordered_relations:
            relation_cue = RelationCue.from_payload(relation)
            if relation_cue is None:
                continue

            relation_type = relation_cue.relation_type
            relation_start = relation_cue.position_start
            relation_end = relation_cue.position_end
            direction = relation.get("direction", "FORWARD")

            # Compute fence for forward scoping.
            next_relation_start = self._get_next_relation_start(
                ordered_relations=ordered_relations,
                current_relation=relation,
                relation_start=relation_start,
                content=content,
            )

            # 1. Inherited / enumerated relations
            if relation_start == -1:
                if (
                    relation.get("hint_group") == "enumerated_relation_types"
                    and relation_type in self.BULLET_LIST_ACTION_RELATION_TYPES
                ):
                    matched_references = self._select_inherited_match_references(
                        prepared_references=prepared_references,
                        content=content,
                    )
                else:
                    matched_references = list(prepared_references)
            # 2. PASSIVE / REVERSE
            elif direction in ("PASSIVE", "REVERSE"):
                # For backward matching, we often want to cross semicolons if it's a list.
                relaxed_delimiters = (".", "\n")
                matched_references = self._select_backward_references(
                    content, relation_start, prepared_references,
                    delimiters=relaxed_delimiters,
                )
                matched_references = self._filter_reverse_expiry_edge_targets(
                    content=content,
                    relation=relation,
                    relation_type=relation_type,
                    relation_start=relation_start,
                    matched_references=matched_references,
                )
                # Fallback: if nothing found backward, try nearest.
                if not matched_references:
                    matched_references = self._select_nearest_references(
                        content, relation_start, relation_end,
                        prepared_references, next_relation_start,
                        delimiters=relaxed_delimiters,
                    )
            # 3. FORWARD / default
            else:
                matched_references = self._select_forward_references(
                    content, relation_start, relation_end, prepared_references, next_relation_start,
                )
                if not matched_references and relation_type == "keo_dai_hieu_luc":
                    scope_end = self._find_next_separator(
                        content=content,
                        start_pos=relation_end,
                        separators=(".", "\n"),
                    )
                    matched_references = [
                        reference
                        for reference in prepared_references
                        if relation_end <= reference.position_start < scope_end
                    ]
                if (
                    not matched_references
                    and relation_type == "dan_chieu"
                    and relation.get("hint_group") == "keo_dai_explicit_citation"
                ):
                    scope_end = self._find_next_separator(
                        content=content,
                        start_pos=relation_end,
                        separators=(".", "\n"),
                    )
                    matched_references = [
                        reference
                        for reference in prepared_references
                        if relation_end <= reference.position_start < scope_end
                    ]
                # Fallback: if nothing found forward, try nearest.
                if not matched_references:
                    matched_references = self._select_nearest_references(
                        content, relation_start, relation_end,
                        prepared_references, next_relation_start,
                    )

            if (
                relation_type in self.DETAIL_GUIDANCE_RELATION_TYPES
                and relation_start != -1
                and self._can_expand_detail_guidance_scope(content, relation_start)
            ):
                scope_end = self._get_relation_scope_end(
                    content=content,
                    relation_end=relation_end,
                    next_relation_start=next_relation_start,
                )
                scoped_detail_references = [
                    reference
                    for reference in prepared_references
                    if relation_start <= reference.position_start < scope_end
                    and reference.full_position_end >= relation_end
                ]
                if scoped_detail_references:
                    matched_references = scoped_detail_references

            # Post-processing filters
            matched_references = self._select_bullet_list_action_references(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._expand_dinh_chinh_intro_references(
                content=content,
                relation_type=relation_type,
                relation_start=relation_start,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._expand_action_semicolon_list_references(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                next_relation_start=next_relation_start,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._expand_sdbs_scope_references(
                content=content,
                relation_type=relation_type,
                relation_start=relation_start,
                relation_end=relation_end,
                next_relation_start=next_relation_start,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._filter_amendment_history_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
                relation_context=relation,
            )
            matched_references = self._expand_detail_list_clause_targets(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._filter_existing_detail_guidance_document_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_keo_dai_amending_resolution_references(
                content=content,
                relation_type=relation_type,
                relation_start=relation_start,
                matched_references=matched_references,
            )
            matched_references = self._filter_parenthetical_alias_references(
                content=content,
                references=matched_references,
            )
            matched_references = self._strip_backward_clause_context_from_dan_chieu(
                relation_type=relation_type,
                relation_start=relation_start,
                matched_references=matched_references,
            )
            matched_references = self._filter_dan_chieu_self_document_tail_references(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                matched_references=matched_references,
            )
            matched_references = self._expand_dan_chieu_document_list_references(
                content=content,
                relation_type=relation_type,
                relation_start=relation_start,
                relation_end=relation_end,
                prepared_references=prepared_references,
                matched_references=matched_references,
            )
            matched_references = self._filter_numbered_item_repeal_dan_chieu_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_parenthetical_alias_references(
                content=content,
                references=matched_references,
            )
            matched_references = self._filter_self_document_clause_inherited_targets(
                content=content,
                relation_type=relation_type,
                relation_start=relation_start,
                matched_references=matched_references,
            )
            matched_references = self._deduplicate_matched_references(matched_references)
            matched_references = self._filter_inserted_amendment_references(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                matched_references=matched_references,
            )
            matched_references = self._filter_inserted_child_targets_to_first_document(
                content=content,
                relation=relation,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_dinh_chinh_scope_references(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                matched_references=matched_references,
            )
            matched_references = self._filter_dinh_chinh_descriptive_intro_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._harmonize_dinh_chinh_intro_document_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_dinh_chinh_alias_references(
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_action_descriptive_tail_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_partial_phrase_amendment_targets(
                content=content,
                relation=relation,
                relation_type=relation_type,
                relation_end=relation_end,
                matched_references=matched_references,
            )
            matched_references = self._filter_repeal_targets_before_partial_phrase(
                content=content,
                relation_type=relation_type,
                relation_end=relation_end,
                matched_references=matched_references,
            )
            matched_references = self._filter_broad_phrase_intro_amendment_reference(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_legislative_program_project_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )
            matched_references = self._filter_transition_temporal_repeal_references(
                content=content,
                relation_type=relation_type,
                matched_references=matched_references,
            )

            # Build public match payloads
            matches.extend(
                self._build_matches_for_reference_set(
                    relation_type=relation_type,
                    relation_value=relation.get("relation_value"),
                    relation_start=relation_start,
                    relation_end=relation_end,
                    matched_references=matched_references,
                    source_so_hieu=source_so_hieu,
                    content=content,
                    source_title=source_title,
                )
            )

        matches = self._backfill_shared_article_for_clause_series(
            content=content,
            matches=matches,
        )
        return self._filter_conflicting_target_relations(matches)

    def _backfill_shared_article_for_clause_series(
        self,
        content: str,
        matches: List[Dict],
    ) -> List[Dict]:
        """Propagate a trailing article anchor to earlier clause targets in one series."""
        if len(matches) <= 1:
            return matches

        updated_matches = [match.copy() for match in matches]

        def clause_anchor_start(match: Dict) -> int:
            reference = match.get("reference") or {}
            clause_starts = [
                value.get("position_start")
                for key, value in reference.items()
                if key in self.CLAUSE_COMPONENT_KEYS
                and isinstance(value, dict)
                and value.get("position_start") is not None
            ]
            if clause_starts:
                return min(clause_starts)
            return match.get("reference_position_start", 0)

        ordered_indices = sorted(
            range(len(updated_matches)),
            key=lambda index: (
                clause_anchor_start(updated_matches[index]),
                updated_matches[index].get("reference_position_end", 0),
            ),
        )

        for index in ordered_indices:
            match = updated_matches[index]
            reference = match.get("reference") or {}
            if "dieu" in reference:
                continue
            if not any(key in reference for key in ("diem", "khoan")):
                continue

            identifier = self._extract_reference_document_identifier(reference)
            reference_start = clause_anchor_start(match)
            _, sentence_end = self._find_sentence_scope_for_position(
                content=content,
                position=reference_start,
                delimiters=(".", "\n"),
            )
            best_article = None
            best_article_start = None
            for candidate_index in ordered_indices:
                candidate = updated_matches[candidate_index]
                candidate_start = clause_anchor_start(candidate)
                if candidate_start <= reference_start or candidate_start >= sentence_end:
                    continue
                bridge_text = content[reference_start:candidate_start]
                normalized_bridge = unidecode(bridge_text or "").lower()
                if (
                    self.SDBS_PASSIVE_AMENDMENT_HISTORY_CUE_PATTERN.search(bridge_text)
                    or self.INSERTED_AMENDMENT_HISTORY_CUE_PATTERN.search(normalized_bridge)
                ):
                    continue

                candidate_reference = candidate.get("reference") or {}
                candidate_article = candidate_reference.get("dieu")
                if not isinstance(candidate_article, dict):
                    continue
                if (
                    identifier
                    and self._extract_reference_document_identifier(candidate_reference)
                    != identifier
                ):
                    continue

                candidate_article_start = candidate_article.get("position_start")
                if candidate_article_start is None:
                    continue
                if best_article_start is None or candidate_article_start < best_article_start:
                    best_article = candidate_article
                    best_article_start = candidate_article_start

            if best_article is None:
                continue

            new_reference = {
                key: value.copy() if isinstance(value, dict) else value
                for key, value in reference.items()
            }
            new_reference["dieu"] = best_article.copy()
            match["reference"] = new_reference

            article_end = best_article.get("position_end")
            if article_end is not None:
                match["reference_position_end"] = max(
                    int(match.get("reference_position_end", article_end)),
                    int(article_end),
                )

        return updated_matches

    def _extract_target_title_from_context(
        self,
        content: str,
        reference: Dict,
    ) -> Optional[str]:
        """Extract the target document's descriptive title from reference and surrounding content.

        Pattern 1 — Luật/Bộ luật/Hiến pháp: the title is embedded in reference['information'].
        Pattern 2 — serial-number documents: the description follows the serial number in
        content, after an optional date phrase, up to the first ';' or newline.
        """
        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return None

        doc_key, doc_info = primary_document
        information = doc_info.get("information", "")

        if doc_key in self.LAW_DOCUMENT_KEYS:
            span = self._extract_title_span(information)
            return span[2] if span else None

        position_end = doc_info.get("position_end")
        if not isinstance(position_end, int):
            return None

        date_match = self._find_date_or_year_match(content, position_end)
        desc_start = position_end + (date_match.end() if date_match else 0)

        remaining = content[desc_start:]
        boundary_match = re.search(r"[;\n]", remaining)
        desc_text = (remaining[:boundary_match.start()] if boundary_match else remaining).strip()

        return desc_text if desc_text else None

    _ISSUING_AUTHORITY_SUFFIX_PATTERN = re.compile(
        r"\s+do\s+(?P<authority>.+?)\s+ban\s+hành\.?\s*$", re.IGNORECASE
    )

    def _compute_action_title_similarity(
        self,
        source_title: Optional[str],
        target_title: Optional[str],
    ) -> float:
        """Similarity between source cls_title and an in-content target description.

        ``cls_title`` (``cls_info.title_without_number``) conventionally ends with
        "... do <Authority> ban hành", while in-content target descriptions (from
        ``_extract_target_title_from_context``) typically begin with "của <Authority>
        ...". Both wordings describe the same regulation, but SequenceMatcher
        penalizes the wrapper-phrase mismatch. Strip the matching issuing-authority
        wrapper from both sides and take the higher of the raw and stripped
        similarities.
        """
        source_title = source_title or ""
        target_title = target_title or ""
        baseline = self._similarity(source_title, target_title)

        suffix_match = self._ISSUING_AUTHORITY_SUFFIX_PATTERN.search(source_title)
        if not suffix_match:
            return baseline

        authority = suffix_match.group("authority").strip()
        if not authority:
            return baseline

        prefix_pattern = re.compile(
            r"^\s*của\s+" + re.escape(authority) + r"\b\s*", re.IGNORECASE
        )
        target_core_match = prefix_pattern.match(target_title)
        if not target_core_match:
            return baseline

        source_core = source_title[: suffix_match.start()].strip()
        target_core = target_title[target_core_match.end():].strip()
        return max(baseline, self._similarity(source_core, target_core))

    def _bai_bo_allowed(
        self,
        source_so_hieu: Optional[str],
        reference: Dict,
    ) -> bool:
        """Return True when the source document may validly revoke (bãi bỏ) the target.

        §5 rule: level(source) >= level(target) always; if both normative, also
        year(source) >= year(target).  Missing level or year when needed → False (cautious).
        """
        source_anatomy = self._extract_document_number_anatomy(source_so_hieu)
        source_level = source_anatomy.get("level")
        if source_level is None:
            return False

        target_identifier = self._extract_reference_document_identifier(reference)
        target_anatomy = self._extract_document_number_anatomy(target_identifier)
        target_level = target_anatomy.get("level")
        if target_level is None:
            return False

        if source_level < target_level:
            return False

        if source_anatomy.get("is_normative") and target_anatomy.get("is_normative"):
            source_year = source_anatomy.get("year")
            target_year = target_anatomy.get("year")
            # Title-only references (e.g. "Luật Phòng, chống tác hại của thuốc lá")
            # carry no embedded year; only block on a *confirmed* downward year
            # violation, not on missing metadata.
            if source_year is not None and target_year is not None:
                if source_year < target_year:
                    return False

        return True

    def _demote_or_drop(
        self,
        source_so_hieu: Optional[str],
        reference: Dict,
    ) -> str:
        """Return 'dan_chieu' when direction allows fallback; 'DROP' for normative→non-normative.

        Downward direction (normative source → non-normative target) is blocked per Decision #1.
        Same group (both normative / both non-normative) and upward (admin→normative) → 'dan_chieu'.
        """
        source_normative = self._extract_document_number_anatomy(source_so_hieu).get(
            "is_normative", False
        )
        target_identifier = self._extract_reference_document_identifier(reference)
        target_normative = self._extract_document_number_anatomy(target_identifier).get(
            "is_normative", False
        )

        if source_normative and not target_normative:
            return "DROP"
        return "dan_chieu"

    def _refine_action_relation_type(
        self,
        detected: str,
        source_so_hieu: Optional[str],
        reference: Dict,
        title_sim: float = 0.0,
    ) -> str:
        """Apply §4+§5+§6 refinement to thay_the / bai_bo; pass other types through unchanged.

        Returns 'thay_the', 'bai_bo', 'dan_chieu', or 'DROP'.
        Only the fallback path generates 'DROP' (Decision #1 — direction gate).
        """
        if detected in ("thay_the", "bai_bo"):
            source_anatomy = self._extract_document_number_anatomy(source_so_hieu)
            if source_anatomy.get("level") is None:
                return detected

        if detected == "thay_the":
            if self._is_same_type_and_authority(source_so_hieu, reference):
                return "thay_the"
            if self._bai_bo_allowed(source_so_hieu, reference):
                return "bai_bo"
            return self._demote_or_drop(source_so_hieu, reference)

        if detected == "bai_bo":
            is_same_type_and_authority = self._is_same_type_and_authority(
                source_so_hieu, reference
            )
            clause_scoped_title_match = (
                self._is_clause_scoped_reference(reference)
                and title_sim >= self.CLAUSE_SCOPED_ACTION_TITLE_SIMILARITY_THRESHOLD
            )
            if is_same_type_and_authority and (title_sim >= 0.8 or clause_scoped_title_match):
                return "thay_the"
            if self._bai_bo_allowed(source_so_hieu, reference):
                return "bai_bo"
            return self._demote_or_drop(source_so_hieu, reference)

        return detected

