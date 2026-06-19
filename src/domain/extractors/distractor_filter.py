"""
Distractor filter for relation type extraction.

Filters false-positive action keywords that match relation patterns syntactically
but do not represent actual legal relations.  All rules are purely regex-based
(no external lookups) so they add negligible overhead to the hot path.

Integration point: called in RelationTypeExtraction.extract_relation_types()
after _filter_conflict_or_redundant_relation_types() and before return.

Each rule returns a rejection_reason string on rejection, or None to pass.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.domain.extractors.base_extractor_flow.shared import unidecode

# ---------------------------------------------------------------------------
# Compiled patterns — module-level singletons, compiled once at import time
# ---------------------------------------------------------------------------

# Rule 1: "bổ sung" followed immediately by non-legal objects within ~50 chars.
# Non-legal objects: dossiers, information, documentation, resources, tasks.
_NON_LEGAL_BO_SUNG_OBJECTS = re.compile(
    r"\b(?:hồ\s+sơ|thông\s+tin|tài\s+liệu|nguồn\s+lực|nhiệm\s+vụ|"
    r"kinh\s+phí|ngân\s+sách|nhân\s+lực|cán\s+bộ|biên\s+chế|"
    r"tiêu\s+chí|định\s+mức|chỉ\s+tiêu|phương\s+án)\b",
    re.IGNORECASE,
)
# "bổ sung" keyword anchor — matches only the "bổ sung" form, not "sửa đổi, bổ sung"
_BO_SUNG_KEYWORD_ONLY = re.compile(
    r"^bổ\s+sung\b",
    re.IGNORECASE,
)

# Rule 2: "đình chỉ" or "ngưng hiệu lực" followed by activity/licence objects.
_NON_LEGAL_DINH_CHI_OBJECTS = re.compile(
    r"\b(?:hoạt\s+động|giấy\s+phép|chứng\s+chỉ|công\s+nhận|"
    r"thi\s+hành\s+án|chứng\s+nhận|đăng\s+ký|kinh\s+doanh)\b",
    re.IGNORECASE,
)
_DINH_CHI_KEYWORD = re.compile(
    r"^(?:đình\s+chỉ|tạm\s+đình\s+chỉ|ngưng\s+hiệu\s+lực)\b",
    re.IGNORECASE,
)

# Rule 3: "hủy bỏ" / "thu hồi" applied to administrative objects (not documents).
_NON_LEGAL_HUY_BO_OBJECTS = re.compile(
    r"\b(?:công\s+nhận\b|thẻ\b|chứng\s+chỉ|tài\s+sản|"
    r"quyết\s+định\s+công\s+nhận|giấy\s+phép|chứng\s+nhận|"
    r"đăng\s+ký|kết\s+quả|hồ\s+sơ)\b",
    re.IGNORECASE,
)
_HUY_BO_KEYWORD = re.compile(
    r"^(?:hủy\s+bỏ|thu\s+hồi)\b",
    re.IGNORECASE,
)

# Rule 4: Pure heading/title context — "dieu" clause that IS the article heading.
# Requires the "Điều X." prefix so that operative articles ("Hủy bỏ Quyết định
# số ...") are never rejected — only the article title line itself is in scope.
_HEADING_ACTION_OPENER = re.compile(
    r"^Điều\s+\d+\.\s*(?:Bãi\s+bỏ|Thay\s+thế|Sửa\s+đổi|Hủy\s+bỏ|Đình\s+chỉ)\b",
    re.IGNORECASE,
)
_HEADING_NUMERIC_REFERENCE = re.compile(
    r"\b(?:"
    r"Điều\s+\d"               # clause reference: Điều X
    r"|[Kk]hoản\s+\d"          # subclause: khoản X
    r"|[Đđ]iểm\s+[a-zđ]"      # point: điểm a
    r"|\d{1,3}/\d{4}/"         # standard doc number: 12/2019/TT
    r"|\d{2,}/\d{4}"           # year-only format: 12/2019
    r"|\d{2,}/[A-ZĐƯƠẮẺẼẸ]"   # Vietnamese doc numbers: 3009/QĐ, 49/QĐ, 101/NĐ
    r")",
    re.IGNORECASE,
)
_HEADING_DOCUMENT_TARGET = re.compile(
    r"\bcua\s+(?:bo\s+luat|luat|phap\s+lenh|nghi\s+quyet|nghi\s+dinh|"
    r"thong\s+tu|quyet\s+dinh)\s+\S",
    re.IGNORECASE,
)

# Rule 5: "kéo dài thời gian/thời hạn" applied to a personnel/administrative
# activity (extending a deadline or tenure), not to a legal document's effect.
# Deliberately excludes "thực hiện" (extending implementation of a document is a
# legitimate keo_dai_hieu_luc).
_NON_LEGAL_KEO_DAI_OBJECTS = re.compile(
    r"\b(?:gia\s+hạn|giữ\s+chức(?:\s+vụ)?|nâng\s+bậc\s+lương|nâng\s+lương|"
    r"xử\s+lý\s+kỷ\s+luật|công\s+tác|nghỉ\s+hưu|thanh\s+tra)\b",
    re.IGNORECASE,
)
_KEO_DAI_KEYWORD = re.compile(
    r"^kéo\s+dài\s+(?:thời\s+gian|thời\s+hạn)\b",
    re.IGNORECASE,
)

# Lookahead window size for object checks (characters after keyword end)
_OBJECT_LOOKAHEAD = 60


class DistractorFilter:
    """
    Rule-based filter for false-positive action relation keywords.

    Usage::

        _FILTER = DistractorFilter()  # instantiate once at module level

        kept, rejected = _FILTER.filter_by_context(content, final_results, clause_type)

    ``rejected`` items are dicts with all original keys plus ``rejection_reason``.
    """

    def filter_by_context(
        self,
        content: str,
        relation_type_matches: List[Dict],
        clause_type: Optional[str],
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Apply all context-based distractor rules to a list of relation-type matches.

        Returns:
            (kept, rejected) — rejected items carry a ``rejection_reason`` key.
        """
        kept: List[Dict] = []
        rejected: List[Dict] = []

        for match in relation_type_matches:
            reason = self._check(content, match, clause_type or "")
            if reason:
                rejected.append({**match, "rejection_reason": reason})
            else:
                kept.append(match)

        return kept, rejected

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _check(self, content: str, match: Dict, clause_type: str) -> Optional[str]:
        relation_type = match.get("relation_type", "")
        start: int = match.get("position_start", 0)
        end: int = match.get("position_end", start)
        match_text: str = match.get("text") or match.get("relation_value") or ""

        if relation_type in ("sua_doi_bo_sung", "bo_sung"):
            reason = self._is_non_legal_bo_sung(content, start, end, match_text)
            if reason:
                return reason

        if relation_type in ("dinh_chi", "ngung_hieu_luc"):
            reason = self._is_non_legal_dinh_chi(content, start, end, match_text)
            if reason:
                return reason

        if relation_type == "huy_bo":
            reason = self._is_non_legal_huy_bo(content, start, end, match_text)
            if reason:
                return reason

        if relation_type == "keo_dai_hieu_luc":
            reason = self._is_non_legal_keo_dai(content, start, end, match_text)
            if reason:
                return reason

        reason = self._is_heading_or_title_context(content, clause_type)
        if reason:
            return reason

        return None

    # ------------------------------------------------------------------
    # Rule 1 — non-legal "bổ sung"
    # ------------------------------------------------------------------

    def _is_non_legal_bo_sung(
        self,
        content: str,
        match_start: int,
        match_end: int,
        match_text: str,
    ) -> Optional[str]:
        """
        Reject when the matched keyword is specifically "bổ sung" (not "sửa đổi,
        bổ sung") and the immediately following text refers to a non-legal object
        such as a dossier, information set, or budget line.
        """
        if not _BO_SUNG_KEYWORD_ONLY.match(match_text.strip()):
            return None

        following = content[match_end:match_end + _OBJECT_LOOKAHEAD]
        if _NON_LEGAL_BO_SUNG_OBJECTS.search(following):
            return (
                "non_legal_bo_sung: 'bổ sung' applies to a non-legal object "
                "(hồ sơ / thông tin / tài liệu / nguồn lực / nhiệm vụ), "
                "not to a legal article or document"
            )
        return None

    # ------------------------------------------------------------------
    # Rule 2 — non-legal "đình chỉ" / "ngưng hiệu lực"
    # ------------------------------------------------------------------

    def _is_non_legal_dinh_chi(
        self,
        content: str,
        match_start: int,
        match_end: int,
        match_text: str,
    ) -> Optional[str]:
        """
        Reject when "đình chỉ" or "ngưng hiệu lực" applies to an administrative
        object (activity, licence, certificate) rather than a legal document.
        """
        if not _DINH_CHI_KEYWORD.match(match_text.strip()):
            return None

        following = content[match_end:match_end + _OBJECT_LOOKAHEAD]
        if _NON_LEGAL_DINH_CHI_OBJECTS.search(following):
            return (
                "non_legal_dinh_chi: 'đình chỉ/ngưng hiệu lực' applies to an "
                "activity or licence (hoạt động / giấy phép / chứng chỉ), "
                "not to a legal document"
            )
        return None

    # ------------------------------------------------------------------
    # Rule 3 — non-legal "hủy bỏ" / "thu hồi"
    # ------------------------------------------------------------------

    def _is_non_legal_huy_bo(
        self,
        content: str,
        match_start: int,
        match_end: int,
        match_text: str,
    ) -> Optional[str]:
        """
        Reject when "hủy bỏ" or "thu hồi" applies to an administrative object
        (certificate, property, registration result) rather than a legal document.
        """
        if not _HUY_BO_KEYWORD.match(match_text.strip()):
            return None

        following = content[match_end:match_end + _OBJECT_LOOKAHEAD]
        if _NON_LEGAL_HUY_BO_OBJECTS.search(following):
            return (
                "non_legal_huy_bo: 'hủy bỏ/thu hồi' applies to an administrative "
                "object (thẻ / chứng chỉ / tài sản / công nhận), "
                "not to a legal document"
            )
        return None

    # ------------------------------------------------------------------
    # Rule 5 — non-legal "kéo dài thời gian/thời hạn"
    # ------------------------------------------------------------------

    def _is_non_legal_keo_dai(
        self,
        content: str,
        match_start: int,
        match_end: int,
        match_text: str,
    ) -> Optional[str]:
        """
        Reject when "kéo dài thời gian/thời hạn" extends a personnel or
        administrative activity (gia hạn nộp, nâng bậc lương, giữ chức vụ, …)
        rather than a legal document's effect.
        """
        if not _KEO_DAI_KEYWORD.match(match_text.strip()):
            return None

        following = content[match_end:match_end + _OBJECT_LOOKAHEAD]
        if _NON_LEGAL_KEO_DAI_OBJECTS.search(following):
            return (
                "non_legal_keo_dai: 'kéo dài thời gian/thời hạn' extends an "
                "administrative activity (gia hạn / nâng bậc lương / giữ chức vụ), "
                "not a legal document's effect"
            )
        return None

    # ------------------------------------------------------------------
    # Rule 4 — pure heading / title context
    # ------------------------------------------------------------------

    def _is_heading_or_title_context(
        self,
        content: str,
        clause_type: str,
    ) -> Optional[str]:
        """
        Reject when a "dieu"-type clause content IS the article title line —
        starts with "Điều X. [action keyword]" and contains no numeric clause
        or document references.  Operative articles ("Hủy bỏ Quyết định số ...")
        do not start with "Điều X." and are never rejected by this rule.
        """
        if clause_type != "dieu":
            return None

        stripped = content.strip()
        opener_match = _HEADING_ACTION_OPENER.match(stripped)
        if not opener_match:
            return None

        # If the heading is long (> 200 chars) it likely contains actual content
        if len(stripped) > 200:
            return None

        # Search for numeric clause/document references in the text AFTER the opener.
        # The opener itself contains "Điều X." — that number must not be counted.
        remainder = stripped[opener_match.end():]
        if _HEADING_DOCUMENT_TARGET.search(unidecode(remainder or "").lower()):
            return None
        if _HEADING_NUMERIC_REFERENCE.search(remainder):
            return None

        return (
            "heading_title_context: 'dieu' clause is a pure section heading "
            "starting with an action keyword — relational content lives in child nodes"
        )
