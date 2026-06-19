"""Shared constants and low-level helpers for the BaseExtractor flow."""

from typing import Dict, List, Optional, Tuple
import re
from src.shared.text.normalizers import unidecode
from difflib import SequenceMatcher


from src.infrastructure.config import doc_number_patterns_for_regex


class BaseExtractorShared:
    """Shared utilities reused across reference, relation-type, and match stages."""

    LAW_DOCUMENT_TYPES = ["Luật", "Bộ luật", "Hiến pháp", "Pháp lệnh"]
    LAW_DOCUMENT_KEYS = {"luat", "boluat", "hienphap"}
    CLAUSE_COMPONENT_KEYS = frozenset({"dieu", "khoan", "diem"})
    LOCAL_AUTHORITY_MARKERS = ("UBND", "HĐND", "QĐ-UB", "QĐ-HĐ")

    RELATION_PRIORITY = {
        "sua_doi_bo_sung": 110,
        "thay_the": 100,
        "bai_bo": 90,
        "huy_bo": 80,
        "sua_doi": 80,
        "bo_sung": 80,
        "dinh_chi": 80,
        "ngung_hieu_luc": 80,
        "dinh_chinh": 80,
        "keo_dai_hieu_luc": 70,
        "huong_dan": 60,
        "quy_dinh_chi_tiet": 60,
        "can_cu": 40,
        "dan_chieu": 20,
    }

    RESTRICTED_LOCAL_TO_CENTRAL_RELATIONS = frozenset({
        "sua_doi_bo_sung",
        "thay_the",
        "bai_bo",
        "huy_bo",
        "quy_dinh_chi_tiet",
        "huong_dan",
        "ngung_hieu_luc",
        "dinh_chi",
        "dinh_chinh",
        "keo_dai_hieu_luc"
    })

    _SELF_DOC_PREFIXES = (
        r"luat|bo\s+luat|hien\s+phap|nghi\s+quyet(?:\s+lien\s+tich)?"
        r"|thong\s+tu(?:\s+lien\s+tich)?|nghi\s+dinh|quyet\s+dinh"
        r"|phap\s+lenh|chi\s+thi|van\s+ban|cong\s+(?:van|dien)"
        r"|dieu\s+uoc\s+quoc\s+te|huong\s+dan|ke\s+hoach|(?:sac\s+)?lenh"
    )

    SELF_DOCUMENT_REFERENCE_PATTERN = re.compile(
        rf"^(?:{_SELF_DOC_PREFIXES})\s+nay\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_doc_type_key(doc_type: str) -> str:
        """Normalize a Vietnamese document type label to the internal key format."""
        return unidecode(doc_type).replace(" ", "").lower() # E.g. "Nghị định" -> "nghidinh"


    @staticmethod
    def _is_embedded_period(content: str, index: int) -> bool:
        """Return True for periods inside numeric or letter-number tokens."""
        return (
            content[index] == "."
            and index > 0
            and index + 1 < len(content)
            and (
                (
                    content[index - 1].isdigit()
                    and content[index + 1].isdigit()
                )
                or (
                    content[index - 1].isalpha()
                    and content[index + 1].isdigit()
                )
            )
        )

    @classmethod
    def _find_next_separator(cls, content: str, start_pos: int, separators: Tuple[str, ...]) -> int:
        """Return the closest separator after ``start_pos`` or ``len(content)``."""
        next_positions = []
        for separator in separators:
            search_start = start_pos
            while True:
                index = content.find(separator, search_start)
                if index == -1:
                    break
                if separator == "." and cls._is_embedded_period(content, index):
                    search_start = index + 1
                    continue
                next_positions.append(index)
                break
        return min(next_positions) if next_positions else len(content)

    @classmethod
    def _find_previous_separator(cls, content: str, start_pos: int, separators: Tuple[str, ...]) -> int:
        """Return the nearest separator before ``start_pos`` or ``-1`` when absent."""
        previous_positions = []
        for separator in separators:
            search_end = start_pos
            while True:
                index = content.rfind(separator, 0, search_end)
                if index == -1:
                    break
                if separator == "." and cls._is_embedded_period(content, index):
                    search_end = index
                    continue
                previous_positions.append(index)
                break
        return max(previous_positions) if previous_positions else -1

    @staticmethod
    def _build_sentence_scopes(content: str, separators: Optional[set[str]] = None) -> List[Dict]:
        """Split content into sentence-like scopes using lightweight separators."""
        sentence_scopes: List[Dict] = []

        if not content or not content.strip():
            return sentence_scopes

        start_idx = 0
        if separators is None:
            separators = {".", ";", "\n"}

        for idx, char in enumerate(content):
            if char not in separators:
                continue
            if char == "." and BaseExtractorShared._is_embedded_period(content, idx):
                continue

            scope_text = content[start_idx:idx].strip()
            if scope_text:
                left_trim = len(content[start_idx:idx]) - len(content[start_idx:idx].lstrip())
                right_trim = len(content[start_idx:idx].rstrip())
                sentence_scopes.append({
                    "text": scope_text,
                    "start_pos": start_idx + left_trim,
                    "end_pos": start_idx + right_trim,
                })

            start_idx = idx + 1

        trailing_text = content[start_idx:]
        trailing_scope = trailing_text.strip()
        if trailing_scope:
            left_trim = len(trailing_text) - len(trailing_text.lstrip())
            right_trim = len(trailing_text.rstrip())
            sentence_scopes.append({
                "text": trailing_scope,
                "start_pos": start_idx + left_trim,
                "end_pos": start_idx + right_trim,
            })

        return sentence_scopes

    def _find_doc_number_match(self, text: str, doc_type_key: str) -> Optional[re.Match]:
        """Find the first document number match for a document type within a text span."""
        patterns = doc_number_patterns_for_regex.get(doc_type_key, [])
        generic_patterns = [
            r"\b\d{1,5}/\d{4}/[A-ZĐ]{1,10}(?:-[A-ZĐ0-9]{1,15})?\b",
            r"\b\d{1,5}/[A-ZĐ]{1,10}(?:-[A-ZĐ0-9]{1,15})?\b",
            r"\b\d{1,5}-[A-ZĐ]{1,10}(?:/[A-ZĐ0-9]{1,15})?\b",
        ]

        for pattern in [*patterns, *generic_patterns]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match

        return None

    @classmethod
    def _extract_title_span(cls, text: str) -> Optional[tuple[int, int, str]]:
        """Extract title span using structure:
        - Starts with 'Luật', 'Bộ luật' or 'Hiến pháp'
        - End before 'ngày', 'năm', 'số', or end
        """
        # Ensure longest matches first and handle possible special characters
        types_pattern = "|".join(re.escape(t) for t in sorted(cls.LAW_DOCUMENT_TYPES, key=len, reverse=True))
        # Use a stricter lookahead for 'số' (must be followed by a digit) to avoid stopping inside titles
        # Also stop at common bridging/relation words like 'được', 'bị'
        pattern = rf'\b({types_pattern})\s+.*?(?=\s+(?:ngày\b|năm\b|số\s+\d|được\b|bị\b)|;|$)'
        match = re.search(pattern, text)
        
        if not match:
            return None 

        start, end = match.span()
        title = match.group(0).strip()

        title = re.sub(r'[,\s]+$', '', title)
        title = re.sub(r'\s+(?:và|hoặc|đã)$', '', title, flags=re.IGNORECASE)

        return start, start + len(title), title

    @staticmethod 
    def _normalize_text(text: str) -> str: 
        return re.sub(r"\s+", " ", text.lower()).strip()

    @staticmethod 
    def _similarity(a: str, b: str) -> float: 
        return SequenceMatcher(None, BaseExtractorShared._normalize_text(a), BaseExtractorShared._normalize_text(b)).ratio()
    
    @classmethod 
    def _find_title_match_advanced(cls, text: str, law_titles: List[str]) -> Optional[tuple[int, int, str]]:
        """Find the best matching law title contained in a text span.
        1. Regex extraction (primary)
        2. Exact match in provided titles
        3. Fuzzy fallback
        """
        if not text: 
            return None 

        # 1. Regex extraction (primary)
        extracted_span = cls._extract_title_span(text)
        if not extracted_span:
            return None 

        start, end, extracted_title = extracted_span

        if not law_titles:
            return extracted_span

        normalized_extracted = cls._normalize_text(extracted_title)

        # 2. Exact match | Sort by length
        for title in sorted(law_titles, key=len, reverse=True): 
            if not title: 
                continue 

            if cls._normalize_text(title) == normalized_extracted:
                return start, end, title 

        # 3. Fuzzy match 
        best_match = None 
        best_score = 0 

        for title in sorted(law_titles, key=len, reverse=True): 
            if not title: 
                continue 

            score = cls._similarity(extracted_title, title) 
            if score > best_score: 
                best_score = score 
                best_match = title 

        if best_match and best_score > 0.8: 
            return start, end, best_match 

        # 4. Fallback 
        return extracted_span

    @staticmethod
    def _find_title_match(text: str, law_titles: List[str]) -> Optional[tuple[int, int, str]]:
        """Find the best matching law title contained in a text span."""
        lowered_text = text.lower()
        for title in law_titles:
            if not title:
                continue

            lowered_title = title.lower().strip()
            start_pos = lowered_text.find(lowered_title)
            if start_pos != -1:
                return start_pos, start_pos + len(lowered_title), title

        return None

    @staticmethod
    def _find_fallback_law_title_match(
        text: str,
        doc_type_text: str
    ) -> Optional[tuple[int, int, str]]:
        """Fallback title extraction for law-like documents when no configured title matches."""
        escaped_doc_type = re.escape(doc_type_text)

        # Find the document title, e.g., "Luật sửa đổi bổ sung một số điều của Luật X ngày 20/10/2023" => "Luật sửa đổi bổ sung một số điều của Luật X"
        match = re.match(
            rf"^(?P<title>{escaped_doc_type}(?:\s+.+?)?)"
            rf"(?=(?:\s+số\s+\d|\s+ngày\b|\s+năm\b|;|$))",
            text,
        )
        if not match:
            return None

        title = match.group("title").strip()

        if title.lower() == doc_type_text.lower():
            return None

        # Start position is always 0 due to regex anchoring; end position is length of matched title
        return 0, len(title), title

    @staticmethod
    def _find_date_or_year_match(text: str, start_pos: int) -> Optional[re.Match]:
        """Find a date or year phrase following the detected title/number."""
        trailing_text = text[start_pos:]
        patterns = [
            r"^\s+ngày\s+\d{1,2}/\d{1,2}/\d{2,4}\b",
            r"^\s+ngày\s+\d{1,2}-\d{1,2}-\d{2,4}\b",
            r"^\s+ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}\b",
            r"^\s+năm\s+\d{4}\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, trailing_text, re.IGNORECASE)
            if match:
                return match

        return None

    @staticmethod
    def _get_clause_value_pattern(clause_key: str, value_patterns: List[str]) -> str:
        """Pick a safe value pattern for clause extraction."""
        if clause_key == "diem":
            # We need a more specific pattern for "điểm" to avoid overmatching common words that contain "điểm" as a substring (e.g., "điểm a", "điểm b", but not "điểm xuất sắc", "điểm mạnh")
            return r"(?<!\w)[a-zđ](?:\.\d+|\d*)\b(?:\s*,\s*[a-zđ](?:\.\d+|\d*)\b)*(?:\s+và\s+(?!điểm\b)[a-zđ](?:\.\d+|\d*)\b)?"

        return value_patterns[0]

    @staticmethod
    def _copy_reference(reference: Dict) -> Dict:
        """Create a shallow copy of a reference payload."""
        return {
            key: value.copy() if isinstance(value, dict) else value
            for key, value in reference.items()
        }

    @classmethod
    def _get_reference_anchor_span(cls, reference: Dict) -> Optional[Dict]:
        """Build the positional anchor used for relation detection and matching."""
        all_positions = [
            (value.get("position_start"), value.get("position_end"))
            for value in reference.values()
            if isinstance(value, dict)
            and value.get("position_start") is not None
            and value.get("position_end") is not None
        ]
        if not all_positions:
            return None

        clause_positions = [
            (value.get("position_start"), value.get("position_end"))
            for key, value in reference.items()
            if key in cls.CLAUSE_COMPONENT_KEYS
            and isinstance(value, dict)
            and value.get("position_start") is not None
            and value.get("position_end") is not None
        ]
        if clause_positions:
            return {
                "position_start": int(min(start for start, _ in clause_positions)),
                "position_end": int(max(end for _, end in clause_positions)),
            }

        return {
            "position_start": int(min(start for start, _ in all_positions)),
            "position_end": int(max(end for _, end in all_positions)),
        }

    @staticmethod
    def _get_reference_match_span(reference: Dict) -> Optional[Dict]:
        """Build the full structural span for one reference chain."""
        positions = [
            (value.get("position_start"), value.get("position_end"))
            for value in reference.values()
            if isinstance(value, dict)
            and value.get("position_start") is not None
            and value.get("position_end") is not None
        ]
        if not positions:
            return None

        return {
            "position_start": int(min(start for start, _ in positions)),
            "position_end": int(max(end for _, end in positions)),
        }

    def _get_primary_document_component(self, reference: Dict) -> Optional[Tuple[str, Dict]]:
        """Return the first non-clause document component from a reference chain."""
        for key, value in reference.items():
            if key in self.CLAUSE_COMPONENT_KEYS:
                continue
            if isinstance(value, dict):
                return key, value

        return None

    @staticmethod
    def _normalize_document_number(raw_number: str) -> str:
        """Normalize a document number into a stable comparison format."""
        normalized_number = re.sub(r"^\s*số\s+", "", raw_number, flags=re.IGNORECASE).strip()
        normalized_number = re.sub(r"\s*-\s*", "-", normalized_number)
        normalized_number = re.sub(r"\s*/\s*", "/", normalized_number)
        normalized_number = re.sub(r"\s+", " ", normalized_number).strip()
        return normalized_number
