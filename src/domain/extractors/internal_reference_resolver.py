"""
Internal reference resolver for dan_chieu (cross-reference) within the same document.

Detects patterns like "khoản 2 Điều này", "Luật này", "từ điểm a đến điểm g
khoản 1 Điều này" and resolves them to fully qualified canonical references
using the clause hierarchy and document metadata.

Only applicable to `dan_chieu` relation type — other relation types correctly
filter out self-references.
"""

import re
from typing import Dict, List, Optional, Tuple

from src.infrastructure.config import loai_van_ban_mapping


# Vietnamese alphabet order used for legal "điểm" labels
# Note: Vietnamese legal documents do NOT use f, j, w, z
VIETNAMESE_DIEM_ALPHABET = [
    "a", "b", "c", "d", "đ", "e", "g", "h", "i", "k",
    "l", "m", "n", "o", "p", "q", "r", "s", "t", "u",
    "v", "x", "y",
]

_MIXED_KHOAN_PREFIX_BEFORE_DIEM = re.compile(
    r"(?:^|[^\w])(?:các\s+)?khoản\s+"
    r"(?P<khoans>\d+(?:\s*,\s*(?:khoản\s+)?\d+)*)\s*,\s*$",
    re.IGNORECASE,
)

# Reverse mapping: "Luật" -> "luat", "Thông tư" -> "thongtu", etc.
_REVERSE_LOAI_VAN_BAN = {v: k for k, v in loai_van_ban_mapping.items()}

# Build regex alternation for all document type names (longest first to avoid partial matching)
_DOC_TYPE_NAMES_SORTED = sorted(loai_van_ban_mapping.values(), key=len, reverse=True)
_DOC_TYPE_ALTERNATION = "|".join(re.escape(name) for name in _DOC_TYPE_NAMES_SORTED)

# Mixed multi-group enumeration governed by a single trailing "(của) <doc> này":
#   "tại các khoản 2, 3 và 4 Điều 64, Điều 65, khoản 4, khoản 5 Điều 66 và Điều 67
#    của Luật này"
# The enum body is restricted to clause-enumeration characters (letters, digits,
# spaces, commas) so it cannot cross a sentence boundary ('.', ';', parentheses).
_MIXED_ENUM_DOC_NAY = re.compile(
    r"\btại\s+(?P<enum>"
    r"(?:(?:các|và|,)\s*)*(?:Điều|khoản|điểm)\s+\d+[a-zđ]?"
    r"(?:\s*(?:,|và)\s*\d+[a-zđ]?)*\s*"          # bare-number continuations
    r"(?:(?:(?:các|và|,)\s*)*(?:Điều|khoản|điểm)\s+\d+[a-zđ]?"
    r"(?:\s*(?:,|và)\s*\d+[a-zđ]?)*\s*)*"          # further clause tokens
    r")"
    r"(?:của\s+)?(?P<doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+này(?!\w)",
    re.IGNORECASE,
)
# A clause keyword + its first number, OR a bare ",/và <number|letter>"
# continuation that inherits the most recent keyword
# ("khoản 2, 3 và 4" → khoản 2/3/4; "điểm a, b" → điểm a/b).
_ENUM_TOKEN_PATTERN = re.compile(
    r"(?P<kw>Điều|khoản|điểm)\s+(?P<knum>\d+[a-zđ]?|[a-zđ])"
    r"|(?:,|và)\s*(?P<bare>\d+[a-zđ]?|[a-zđ])\b",
    re.IGNORECASE,
)
_ENUM_LEVEL = {"diem": 0, "khoan": 1, "dieu": 2}


def _tokenize_enumeration(enum_text: str) -> List[Tuple[str, str]]:
    """Flatten a clause enumeration into ordered (level, number) tokens."""
    tokens: List[Tuple[str, str]] = []
    current_type: Optional[str] = None
    for m in _ENUM_TOKEN_PATTERN.finditer(enum_text):
        if m.group("kw"):
            kw = m.group("kw").lower()
            current_type = "dieu" if kw == "điều" else ("khoan" if kw == "khoản" else "diem")
            tokens.append((current_type, m.group("knum").lower()))
        elif m.group("bare") and current_type is not None:
            bare = m.group("bare").lower()
            # A bare single letter only continues a điểm list; a bare digit
            # continues a khoản/Điều list.
            if bare.isalpha() and current_type != "diem":
                continue
            tokens.append((current_type, bare))
    return tokens


def _group_enumeration_tokens(tokens: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    """Group flat tokens into clause references with hierarchy inheritance."""
    groups: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    previous_level: Optional[int] = None
    for level_name, number in tokens:
        level = _ENUM_LEVEL[level_name]
        if current and previous_level is not None and level <= previous_level:
            groups.append(current)
            current = []
        current.append((level_name, number))
        previous_level = level
    if current:
        groups.append(current)

    normalized = [{t: n for t, n in group} for group in groups]
    inherited_dieu: Optional[str] = None
    inherited_khoan: Optional[str] = None
    for group in reversed(normalized):
        if "dieu" in group:
            inherited_dieu = group["dieu"]
        if "khoan" in group:
            inherited_khoan = group["khoan"]
        if "diem" in group:
            if "khoan" not in group and inherited_khoan is not None:
                group["khoan"] = inherited_khoan
            if "dieu" not in group and inherited_dieu is not None:
                group["dieu"] = inherited_dieu
        elif "khoan" in group and "dieu" not in group and inherited_dieu is not None:
            group["dieu"] = inherited_dieu
    return normalized


# Pattern 1: Range of điểm — "từ điểm a đến điểm g khoản 1 Điều 36 của Luật này" or "Điều này"
_RANGE_DIEM_DIEU_NAY = re.compile(
    r"(?:các\s+)?(?:điểm\s+)?từ\s+điểm\s+(?P<start_diem>[a-zđ])\s+"
    r"đến\s+điểm\s+(?P<end_diem>[a-zđ])\s+"
    r"khoản\s+(?P<khoan>\d+)\s+"
    r"Điều\s+(?:(?P<dieu_num>\d+)\s+(?:(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+)?)?này",
    re.IGNORECASE,
)

# Pattern 2: Range of khoản — "từ khoản 1 đến khoản 11 Điều 36 của Luật này" or "Điều này"
_RANGE_KHOAN_DIEU_NAY = re.compile(
    r"(?:các\s+)?(?:khoản\s+)?từ\s+khoản\s+(?P<start_khoan>\d+)\s+"
    r"đến\s+khoản\s+(?P<end_khoan>\d+)\s+"
    r"Điều\s+(?:(?P<dieu_num>\d+)\s+(?:(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+)?)?này",
    re.IGNORECASE,
)

# Pattern 3: điểm + khoản + Điều... này — "điểm a, b khoản 1 Điều 36 của Luật này" or "Điều này"
_DIEM_KHOAN_DIEU_NAY = re.compile(
    r"(?:các\s+)?(?:điểm\s+)"
    r"(?P<diems>[a-zđ](?:\s*,\s*(?:điểm\s+)?[a-zđ])*(?:\s+và\s+(?:điểm\s+)?[a-zđ])?)\s+"
    r"khoản\s+(?P<khoan>\d+)\s+"
    r"Điều\s+(?:(?P<dieu_num>\d+)\s+(?:(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+)?)?này",
    re.IGNORECASE,
)

# Pattern 4: khoản + Điều... này — "khoản 2, khoản 3 Điều 36 của Luật này" or "Điều này"
_KHOAN_DIEU_NAY = re.compile(
    r"(?:các\s+)?(?:khoản\s+)"
    r"(?P<khoans>\d+(?:\s*,\s*(?:khoản\s+)?\d+)*(?:\s+và\s+(?:khoản\s+)?\d+)?)\s+"
    r"Điều\s+(?:(?P<dieu_num>\d+)\s+(?:(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+)?)?này",
    re.IGNORECASE,
)

# Pattern 5: Article + Doc Nay — "Điều 36 của Luật này" or standalone "Điều này"
_LISTED_DIEU_DOC_NAY = re.compile(
    r"(?<!\w)(?:các\s+)?Điều\s+"
    r"(?P<dieus>\d+[a-z]?(?:\s*,\s*(?:Điều\s+)?\d+[a-z]?)*(?:\s+và\s+(?:Điều\s+)?\d+[a-z]?)?)\s+"
    r"(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+này(?!\w)",
    re.IGNORECASE,
)

_DIEU_DOC_NAY = re.compile(
    r"(?<!\w)Điều\s+(?:(?P<dieu_num>\d+)\s+(?:(?:của\s+)?(?P<spec_doc_type>" + _DOC_TYPE_ALTERNATION + r")\s+)?)?này(?!\w)",
    re.IGNORECASE,
)

# Pattern 6: điểm + khoản này — "điểm a khoản này"
_DIEM_KHOAN_NAY = re.compile(
    r"(?<!\w)(?:các\s+)?(?:điểm\s+)"
    r"(?P<diems>[a-zđ](?:\s*,\s*(?:điểm\s+)?[a-zđ])*(?:\s+và\s+(?:điểm\s+)?[a-zđ])?)\s+"
    r"khoản\s+này(?!\w)",
    re.IGNORECASE,
)

# Pattern 7: Range of điểm + khoản này — "từ điểm a đến điểm c khoản này"
_RANGE_DIEM_KHOAN_NAY = re.compile(
    r"(?<!\w)(?:các\s+)?(?:điểm\s+)?từ\s+điểm\s+(?P<start_diem>[a-zđ])\s+"
    r"đến\s+điểm\s+(?P<end_diem>[a-zđ])\s+"
    r"khoản\s+này(?!\w)",
    re.IGNORECASE,
)

# Pattern 8: Standalone "khoản này"
_STANDALONE_KHOAN_NAY = re.compile(
    r"(?<!\w)khoản\s+này(?!\w)",
    re.IGNORECASE,
)

# Pattern 9: Document-type + này — "Luật này", "Thông tư này"
_DOC_TYPE_NAY = re.compile(
    rf"(?<!\w)(?P<doc_type>{_DOC_TYPE_ALTERNATION})\s+này(?!\w)",
    re.IGNORECASE,
)


class InternalReferenceResolver:
    """
    Resolves internal references ("Điều này", "Luật này", etc.) to fully
    qualified canonical citations for `dan_chieu` relations.
    """

    def __init__(
        self,
        clause_key: Optional[str],
        child_to_parent: Dict[str, str],
        data: List[Dict],
        cls_document_type: str,
        cls_so_hieu: str,
        clause_index_by_key: Optional[Dict[str, Dict]] = None,
    ):
        """
        Args:
            clause_key: com_key of the current clause being processed
            child_to_parent: Hierarchy mapping (child_key -> parent_key)
            data: Full cls_parsing list (all clauses)
            cls_document_type: Document type name, e.g. "Luật", "Thông tư"
            cls_so_hieu: Document number, e.g. "77/2025/TT-NHNN"
            clause_index_by_key: Optional O(1) lookup map for clauses
        """
        self.clause_key = clause_key
        self.child_to_parent = child_to_parent
        self.data = data
        self.cls_document_type = cls_document_type or ""
        self.cls_so_hieu = cls_so_hieu or ""
        self.clause_index_by_key = clause_index_by_key

        # Precompute: find the parent "dieu" and current "khoan" for this clause
        self._parent_dieu_number: Optional[str] = self._find_parent_dieu_number()
        self._current_khoan_number: Optional[str] = self._find_current_khoan_number()

        # Precompute: document identity info string
        self._doc_type_key: Optional[str] = None
        self._doc_info_string: Optional[str] = None
        self._resolve_document_identity()

    def resolve(self, content: str) -> List[Dict]:
        """
        Scan content for internal reference patterns and resolve them.

        Returns:
            List of relation match dicts:
            [{"relation_type": "dan_chieu", "reference": {...}, ...}, ...]
        """
        if not content or not content.strip():
            return []

        matches: List[Dict] = []

        # Order matters: process range/compound patterns FIRST to mark their
        # spans as consumed, preventing simpler patterns from double-matching.
        consumed_spans: List[Tuple[int, int]] = []

        # 0. Mixed multi-group enumeration: "tại các khoản 2, 3 và 4 Điều 64,
        #    Điều 65, khoản 4 Điều 66 và Điều 67 của Luật này" — one trailing doc
        #    governs every listed clause group. Run before the narrower handlers.
        matches.extend(
            self._process_mixed_enumeration_doc_nay(content, consumed_spans)
        )

        # 1. Range of điểm: "từ điểm a đến điểm g khoản X Điều này"
        matches.extend(
            self._process_range_diem_dieu_nay(content, consumed_spans)
        )

        # 2. Range of khoản: "từ khoản 1 đến khoản 5 Điều này"
        matches.extend(
            self._process_range_khoan_dieu_nay(content, consumed_spans)
        )

        # 3. điểm + khoản + Điều này: "điểm a, b khoản 1 Điều này"
        matches.extend(
            self._process_diem_khoan_dieu_nay(content, consumed_spans)
        )

        # 4. khoản + Điều này: "khoản 2, khoản 3 Điều này"
        matches.extend(
            self._process_khoan_dieu_nay(content, consumed_spans)
        )

        # 5. Range of điểm + khoản này: "từ điểm a đến điểm g khoản này"
        matches.extend(
            self._process_range_diem_khoan_nay(content, consumed_spans)
        )

        # 6. điểm + khoản này: "điểm a khoản này"
        matches.extend(
            self._process_diem_khoan_nay(content, consumed_spans)
        )

        # 7. Standalone "khoản này"
        matches.extend(
            self._process_standalone_khoan_nay(content, consumed_spans)
        )

        # 8. Standalone "điểm này"
        matches.extend(
            self._process_standalone_diem_nay(content, consumed_spans)
        )

        # 9. Listed "Điều X, Điều Y của Doc này"
        matches.extend(
            self._process_listed_dieu_doc_nay(content, consumed_spans)
        )

        # 10. Standalone "Điều [X] [của Doc] này"
        matches.extend(
            self._process_dieu_doc_nay(content, consumed_spans)
        )

        # 11. Document-type + này: "Luật này", "Thông tư này"
        matches.extend(
            self._process_doc_type_nay(content, consumed_spans)
        )

        return matches

    def _process_mixed_enumeration_doc_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Resolve a multi-group clause enumeration governed by one '<doc> này'.

        Only fires when the enumeration contains more than one clause group, so
        the narrower single-group handlers keep owning their cases.
        """
        results: List[Dict] = []
        for m in _MIXED_ENUM_DOC_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            if not self._is_matching_doc_type(m.group("doc_type")):
                continue

            tokens = _tokenize_enumeration(m.group("enum"))
            groups = _group_enumeration_tokens(tokens)
            # Defer to the simpler handlers when there is only one group.
            if len(groups) <= 1:
                continue

            built = [
                self._build_reference(
                    diem=group.get("diem"),
                    khoan=group.get("khoan"),
                    dieu=group.get("dieu"),
                    match=m,
                )
                for group in groups
            ]
            built = [ref for ref in built if ref]
            if built:
                consumed.append((m.start(), m.end()))
                results.extend(built)
        return results

    def _process_range_diem_dieu_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'từ điểm a đến điểm g khoản X Điều này'."""
        results: List[Dict] = []
        for m in _RANGE_DIEM_DIEU_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            start_diem = m.group("start_diem").lower()
            end_diem = m.group("end_diem").lower()
            khoan_num = m.group("khoan")

            expanded_diems = expand_vietnamese_diem_range(start_diem, end_diem)
            dieu_num = m.group("dieu_num")
            spec_doc_type = m.group("spec_doc_type")
            
            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            for diem in expanded_diems:
                ref = self._build_reference(
                    diem=diem, khoan=khoan_num, dieu=dieu_num, match=m
                )
                if ref:
                    results.append(ref)

        return results

    def _process_range_khoan_dieu_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'từ khoản 1 đến khoản 5 Điều này'."""
        results: List[Dict] = []
        for m in _RANGE_KHOAN_DIEU_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            start_k = int(m.group("start_khoan"))
            end_k = int(m.group("end_khoan"))
            dieu_num = m.group("dieu_num")
            spec_doc_type = m.group("spec_doc_type")

            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            for k in range(start_k, end_k + 1):
                ref = self._build_reference(khoan=str(k), dieu=dieu_num, match=m)
                if ref:
                    results.append(ref)

        return results

    def _process_diem_khoan_dieu_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'điểm a, b khoản 1 Điều này'."""
        results: List[Dict] = []
        for m in _DIEM_KHOAN_DIEU_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            diems_raw = m.group("diems")
            khoan_num = m.group("khoan")
            dieu_num = m.group("dieu_num")
            spec_doc_type = m.group("spec_doc_type")
            
            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            diems = _parse_listed_items(diems_raw, prefix_word="điểm")
            prefix_match = _MIXED_KHOAN_PREFIX_BEFORE_DIEM.search(
                content[max(0, m.start() - 80):m.start()]
            )
            if prefix_match:
                parent_khoans = _parse_listed_items(
                    prefix_match.group("khoans"),
                    prefix_word="khoản",
                )
                parent_khoans.append(khoan_num)
                seen_parent_khoans = set()
                for parent_khoan in parent_khoans:
                    if parent_khoan in seen_parent_khoans:
                        continue
                    seen_parent_khoans.add(parent_khoan)
                    ref = self._build_reference(
                        khoan=parent_khoan, dieu=dieu_num, match=m
                    )
                    if ref:
                        results.append(ref)

            for diem in diems:
                ref = self._build_reference(
                    diem=diem, khoan=khoan_num, dieu=dieu_num, match=m
                )
                if ref:
                    results.append(ref)

        return results

    def _process_khoan_dieu_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'khoản 2, khoản 3 Điều này'."""
        results: List[Dict] = []
        for m in _KHOAN_DIEU_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            khoans_raw = m.group("khoans")
            dieu_num = m.group("dieu_num")
            spec_doc_type = m.group("spec_doc_type")

            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            khoans = _parse_listed_items(khoans_raw, prefix_word="khoản")

            for khoan in khoans:
                ref = self._build_reference(khoan=khoan, dieu=dieu_num, match=m)
                if ref:
                    results.append(ref)

        return results

    def _process_listed_dieu_doc_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'Điều 30, Điều 31, Điều 32 của Nghị định này'."""
        results: List[Dict] = []
        for m in _LISTED_DIEU_DOC_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            spec_doc_type = m.group("spec_doc_type")
            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            for dieu_num in _parse_listed_items(m.group("dieus"), prefix_word="Điều"):
                ref = self._build_reference(dieu=dieu_num, match=m)
                if ref:
                    results.append(ref)

        return results

    def _process_dieu_doc_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle standalone 'Điều này' or 'Điều 36 của Luật này'."""
        results: List[Dict] = []
        for m in _DIEU_DOC_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            dieu_num = m.group("dieu_num")
            spec_doc_type = m.group("spec_doc_type")

            if spec_doc_type and not self._is_matching_doc_type(spec_doc_type):
                continue

            ref = self._build_reference(dieu=dieu_num, match=m)
            if ref:
                results.append(ref)

        return results

    def _process_diem_khoan_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'điểm a khoản này'."""
        results: List[Dict] = []
        if not self._current_khoan_number:
            return results

        for m in _DIEM_KHOAN_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            diems_raw = m.group("diems")
            diems = _parse_listed_items(diems_raw, prefix_word="điểm")

            for diem in diems:
                ref = self._build_reference(
                    diem=diem, khoan=self._current_khoan_number, match=m
                )
                if ref:
                    results.append(ref)

        return results

    def _process_range_diem_khoan_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'từ điểm a đến điểm g khoản này'."""
        results: List[Dict] = []
        if not self._current_khoan_number:
            return results

        for m in _RANGE_DIEM_KHOAN_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            start_diem = m.group("start_diem").lower()
            end_diem = m.group("end_diem").lower()

            expanded_diems = expand_vietnamese_diem_range(start_diem, end_diem)
            for diem in expanded_diems:
                ref = self._build_reference(
                    diem=diem, khoan=self._current_khoan_number, match=m
                )
                if ref:
                    results.append(ref)

        return results

    def _process_standalone_khoan_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle standalone 'khoản này'."""
        results: List[Dict] = []
        if not self._current_khoan_number:
            return results

        for m in _STANDALONE_KHOAN_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            ref = self._build_reference(
                khoan=self._current_khoan_number, match=m
            )
            if ref:
                results.append(ref)

        return results

    def _process_standalone_diem_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle standalone 'điểm này'."""
        results: List[Dict] = []
        
        # We need both current point and its parent khoan
        if not self._current_khoan_number:
            return results
            
        current_diem = self._find_current_diem_label()
        if not current_diem:
            return results

        # Regex for "điểm này"
        diem_nay_pattern = re.compile(r"(?<!\w)điểm\s+này(?!\w)", re.IGNORECASE)

        for m in diem_nay_pattern.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            ref = self._build_reference(
                diem=current_diem, khoan=self._current_khoan_number, match=m
            )
            if ref:
                results.append(ref)

        return results

    def _process_doc_type_nay(
        self, content: str, consumed: List[Tuple[int, int]]
    ) -> List[Dict]:
        """Handle 'Luật này', 'Thông tư này', etc."""
        results: List[Dict] = []
        for m in _DOC_TYPE_NAY.finditer(content):
            if self._is_consumed(m.start(), m.end(), consumed):
                continue
            consumed.append((m.start(), m.end()))

            # Only resolve if the matched doc type matches the current document type
            matched_doc_type = m.group("doc_type")
            if not self._is_matching_doc_type(matched_doc_type):
                continue

            ref = self._build_doc_only_reference(match=m)
            if ref:
                results.append(ref)

        return results

    def _build_reference(
        self,
        diem: Optional[str] = None,
        khoan: Optional[str] = None,
        dieu: Optional[str] = None,
        match: Optional[re.Match] = None,
    ) -> Optional[Dict]:
        """
        Build a fully qualified internal dan_chieu reference.

        Resolves Article and attaches the document
        identity (cls_document_type + cls_so_hieu).
        """
        target_dieu = dieu or self._parent_dieu_number
        if not target_dieu:
            return None
        if not self._doc_type_key or not self._doc_info_string:
            return None

        reference: Dict = {}

        # Add điểm component
        if diem:
            reference["diem"] = {
                "information": f"điểm {diem}",
                "position_start": match.start() if match else 0,
                "position_end": match.end() if match else 0,
            }

        # Add khoản component
        if khoan:
            reference["khoan"] = {
                "information": f"khoản {khoan}",
                "position_start": match.start() if match else 0,
                "position_end": match.end() if match else 0,
            }

        # Add Điều component (resolved from hierarchy)
        reference["dieu"] = {
            "information": f"Điều {target_dieu}",
            "position_start": match.start() if match else 0,
            "position_end": match.end() if match else 0,
        }

        # Add document component
        reference[self._doc_type_key] = {
            "information": self._doc_info_string,
            "position_start": match.start() if match else 0,
            "position_end": match.end() if match else 0,
        }

        return {
            "relation_type": "dan_chieu",
            "relation_position_start": match.start() if match else 0,
            "relation_position_end": match.end() if match else 0,
            "reference": reference,
        }

    def _build_doc_only_reference(
        self, match: Optional[re.Match] = None
    ) -> Optional[Dict]:
        """Build a document-only reference for 'Luật này', 'Thông tư này'."""
        if not self._doc_type_key or not self._doc_info_string:
            return None

        reference = {
            self._doc_type_key: {
                "information": self._doc_info_string,
                "position_start": match.start() if match else 0,
                "position_end": match.end() if match else 0,
            }
        }

        return {
            "relation_type": "dan_chieu",
            "relation_position_start": match.start() if match else 0,
            "relation_position_end": match.end() if match else 0,
            "reference": reference,
        }

    # ── Private: hierarchy & identity resolution ────────────────────────────

    def _find_parent_dieu_number(self) -> Optional[str]:
        """
        Walk up the clause hierarchy from the current clause to find the
        nearest ancestor with com_type == 'dieu', and extract its number.

        Examples:
            clause_key "diem_a_khoan_1_dieu_22" → walks up → finds dieu_22 → returns "22"
            clause_key "khoan_1_dieu_3" → walks up → finds dieu_3 → returns "3"
            clause_key "dieu_5" → it IS a dieu → returns "5"
        """
        if not self.clause_key or not self.data:
            return None

        # First, check if the current clause itself is a "dieu"
        current_clause = self._find_clause_by_key(self.clause_key)
        if current_clause and (current_clause.get("com_type") or "").lower() == "dieu":
            return (
                self._extract_number_from_key(self.clause_key, "dieu")
                or self._extract_number_from_clause_content(current_clause, "dieu")
            )

        # Walk up the hierarchy
        visited = set()
        current_key = self.clause_key
        while current_key and current_key not in visited:
            visited.add(current_key)
            parent_key = self.child_to_parent.get(current_key)
            if not parent_key:
                break

            parent_clause = self._find_clause_by_key(parent_key)
            if parent_clause and (parent_clause.get("com_type") or "").lower() == "dieu":
                return (
                    self._extract_number_from_key(parent_key, "dieu")
                    or self._extract_number_from_clause_content(parent_clause, "dieu")
                )

            current_key = parent_key

        # Fallback: try extracting dieu from the clause_key string itself
        return self._extract_number_from_key_parts(self.clause_key, "dieu")

    def _find_current_khoan_number(self) -> Optional[str]:
        """
        Find the number of the "khoan" associated with the current clause.
        If the current clause is a khoan, returns its number.
        If the current clause is a diem, walks up to its parent khoan.
        """
        if not self.clause_key:
            return None

        # Check current level
        current_clause = self._find_clause_by_key(self.clause_key)
        if current_clause and (current_clause.get("com_type") or "").lower() == "khoan":
            return (
                self._extract_number_from_key(self.clause_key, "khoan")
                or self._extract_number_from_clause_content(current_clause, "khoan")
            )

        # Check parent level (if current is diem)
        parent_key = self.child_to_parent.get(self.clause_key)
        if parent_key:
            parent_clause = self._find_clause_by_key(parent_key)
            if parent_clause and (parent_clause.get("com_type") or "").lower() == "khoan":
                return (
                    self._extract_number_from_key(parent_key, "khoan")
                    or self._extract_number_from_clause_content(parent_clause, "khoan")
                )

        # Fallback: try parsing from key parts
        return self._extract_number_from_key_parts(self.clause_key, "khoan")

    def _find_current_diem_label(self) -> Optional[str]:
        """Find the label/letter of the current diem."""
        if not self.clause_key:
            return None
            
        current_clause = self._find_clause_by_key(self.clause_key)
        if current_clause and (current_clause.get("com_type") or "").lower() == "diem":
            res = self._extract_label_from_key(self.clause_key, "diem")
            if res:
                return res
            res = self._extract_label_from_clause_content(current_clause)
            if res:
                return res

        return self._extract_label_from_key(self.clause_key, "diem")

    def _find_clause_by_key(self, key: str) -> Optional[Dict]:
        """Find a clause dict in data by its com_key."""
        if self.clause_index_by_key:
            return self.clause_index_by_key.get(key)
            
        for clause in self.data:
            if isinstance(clause, dict) and clause.get("com_key") == key:
                return clause
        return None

    @staticmethod
    def _extract_number_from_key(key: str, com_type: str) -> Optional[str]:
        """
        Extract the number from a com_key for a given component type.
        E.g., "dieu_22" -> "22", "khoan_1" -> "1"
        """
        m = re.search(rf"(?:^|_){re.escape(com_type)}_(\d+)", key, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_label_from_key(key: str, com_type: str) -> Optional[str]:
        """
        Extract a string label (like 'a', 'b') from a com_key.
        E.g., "diem_a" -> "a"
        """
        m = re.search(rf"(?:^|_){re.escape(com_type)}_([a-zđ]\d*)", key, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_number_from_key_parts(key: str, com_type: str) -> Optional[str]:
        """
        Fallback: extract number from embedded parts of a longer key.
        E.g., "diem_a_khoan_1_dieu_22" -> "1" for khoan, "22" for dieu.
        """
        parts = key.split("_")
        for i, part in enumerate(parts):
            if part.lower() == com_type.lower() and i + 1 < len(parts):
                # Next part should be the number
                next_part = parts[i + 1]
                if next_part.isdigit():
                    return next_part
        return None

    @staticmethod
    def _extract_number_from_clause_content(clause: Dict, com_type: str) -> Optional[str]:
        """Extract a legal component number from a clause title/body fallback."""
        text = (clause.get("com_title") or clause.get("content") or "").strip()
        if not text:
            return None

        if com_type.lower() == "dieu":
            match = re.match(r"^\s*Điều\s+(\d+[A-Za-zĐđ]?)\b", text, re.IGNORECASE)
            return match.group(1) if match else None

        if com_type.lower() == "khoan":
            match = re.match(r"^\s*(\d+[A-Za-zĐđ]?)\s*[\.)]", text, re.IGNORECASE)
            return match.group(1) if match else None

        return None

    @staticmethod
    def _extract_label_from_clause_content(clause: Dict) -> Optional[str]:
        """Extract a point label from a clause title/body fallback."""
        text = (clause.get("com_title") or clause.get("content") or "").strip()
        if not text:
            return None

        match = re.match(r"^\s*([A-Za-zĐđ])\s*[\.)]", text, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def _resolve_document_identity(self):
        """
        Map cls_document_type to its internal key and build the full
        information string (e.g. "Luật 59/2024/QH15").
        """
        if not self.cls_document_type:
            return

        # Try exact match first
        doc_type_key = _REVERSE_LOAI_VAN_BAN.get(self.cls_document_type)

        # Try case-insensitive match
        if not doc_type_key:
            normalized = self.cls_document_type.strip()
            for name, key in _REVERSE_LOAI_VAN_BAN.items():
                if name.lower() == normalized.lower():
                    doc_type_key = key
                    break

        if not doc_type_key:
            return

        self._doc_type_key = doc_type_key

        # Build the information string
        if self.cls_so_hieu:
            self._doc_info_string = (
                f"{self.cls_document_type} {self.cls_so_hieu}"
            )
        else:
            self._doc_info_string = self.cls_document_type

    def _is_matching_doc_type(self, matched_text: str) -> bool:
        """Check if the matched doc type text corresponds to the current document."""
        if not self.cls_document_type:
            return False
        return matched_text.strip().lower() == self.cls_document_type.strip().lower()


    @staticmethod
    def _is_consumed(
        start: int, end: int, consumed: List[Tuple[int, int]]
    ) -> bool:
        """Check if a span overlaps with any already-consumed span."""
        for cs, ce in consumed:
            if start < ce and end > cs:
                return True
        return False


def expand_vietnamese_diem_range(start: str, end: str) -> List[str]:
    """
    Expand a range of Vietnamese legal điểm labels.

    Vietnamese alphabet for legal điểm:
    a, b, c, d, đ, e, g, h, i, k, l, m, n, o, p, q, r, s, t, u, v, x, y

    Examples:
        expand_vietnamese_diem_range("a", "g") -> ["a", "b", "c", "d", "đ", "e", "g"]
        expand_vietnamese_diem_range("d", "e") -> ["d", "đ", "e"]
        expand_vietnamese_diem_range("a", "a") -> ["a"]
    """
    start_lower = start.lower()
    end_lower = end.lower()

    try:
        start_idx = VIETNAMESE_DIEM_ALPHABET.index(start_lower)
        end_idx = VIETNAMESE_DIEM_ALPHABET.index(end_lower)
    except ValueError:
        # If one of the letters isn't in our alphabet, return just boundaries
        return [start_lower, end_lower] if start_lower != end_lower else [start_lower]

    if start_idx > end_idx:
        # Reversed range — just return boundaries
        return [start_lower, end_lower]

    return VIETNAMESE_DIEM_ALPHABET[start_idx: end_idx + 1]


def _parse_listed_items(raw: str, prefix_word: str = "") -> List[str]:
    """
    Parse a comma/và-separated list of items, stripping optional prefix words.

    Examples:
        _parse_listed_items("2, khoản 3 và khoản 4", prefix_word="khoản")
            -> ["2", "3", "4"]
        _parse_listed_items("a, b và c", prefix_word="điểm")
            -> ["a", "b", "c"]
    """
    # Replace "và" with comma for uniform processing
    normalized = raw.replace(" và ", ", ")

    items = []
    for part in normalized.split(","):
        part = part.strip()
        # Strip the prefix word if present (e.g., "khoản 3" -> "3")
        if prefix_word:
            part = re.sub(
                rf"^\s*{re.escape(prefix_word)}\s+",
                "",
                part,
                flags=re.IGNORECASE,
            )
        part = part.strip()
        if part:
            items.append(part)

    return items
