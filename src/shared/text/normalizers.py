"""Text normalization and keyword processing."""
import re 
try:
    from unidecode import unidecode
except ImportError:  # pragma: no cover - fallback for minimal test environments
    import unicodedata

    def unidecode(value: str) -> str:
        """Best-effort ASCII transliteration when ``unidecode`` is unavailable."""
        value = value.replace('Đ', 'D').replace('đ', 'd')
        normalized = unicodedata.normalize('NFKD', value)
        return normalized.encode('ascii', 'ignore').decode('ascii')


def process_keyword_information(text: str, type: str) -> str:
    """
    Process keyword information based on its type.
    Extracts structured references like "Điều 1, 2, 3" or "Khoản 1 và 2".

    Args:
        text: The text to be processed
        type: The type of the keyword (dieu, khoan, diem, etc.)
        
    Returns:
        Processed keyword information or None if not found
    """
    STRUCT_PATTERNS = {
        'dieu': r"^(Điều\s+\d+(?:\s*,\s*\d+)*(?:\s+và\s+\d+)?)",
        'khoan': r"^((?:Khoản|khoản)\s+\d+(?:\s*,\s*\d+)*(?:\s+và\s+\d+)?)",
        'diem': r"^((?:Điểm|điểm)\s+[a-zđ](?:\s*,\s*[a-zđ])*(?:\s+và\s+[a-zđ])?)",
        'chuong': r"^((?:Chương|chương)\s+(?:\d+|[IVXLCDM]+)(?:\s*,\s*(?:\d+|[IVXLCDM]+))*(?:\s+và\s+(?:\d+|[IVXLCDM]+))?)",
        'muc': r"^((?:Mục|mục)\s+(?:\d+|[IVXLCDM]+)(?:\s*,\s*(?:\d+|[IVXLCDM]+))*(?:\s+và\s+(?:\d+|[IVXLCDM]+))?)",
        'phan': r"^((?:Phần|phần)\s+(?:\d+|[IVXLCDM]+)(?:\s*,\s*(?:\d+|[IVXLCDM]+))*(?:\s+và\s+(?:\d+|[IVXLCDM]+))?)",
    }

    STOP_SYMBOLS = [".", ":", "\u201c", "\u201d", "\n"]  # Period, colon, left quote, right quote, newline
    STOP_PATTERN = "|".join(re.escape(s) for s in STOP_SYMBOLS)
    
    text = text.strip()
    if not text:
        return None

    if type in STRUCT_PATTERNS:
        pattern = STRUCT_PATTERNS[type]
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            keyword_information = match.group(1).strip()

            # Avoid returning the same as type
            if unidecode(keyword_information.lower()) == type:
                return None

            # Check for stop symbols after the matched keyword information
            stop_match = re.search(STOP_PATTERN, keyword_information)
            if stop_match:
                return keyword_information[:stop_match.start()].strip()

            return keyword_information.strip()
        return None

    else:
        stop_match = re.search(STOP_PATTERN, text)
        if stop_match:
            return text[:stop_match.start()].strip()
        return text.strip()


def normalize_clause_component_information(text: str, type: str) -> str:
    """
    Normalize clause-component labels to a stable canonical form.

    Examples:
    - ``Khoản 5`` -> ``khoản 5``
    - ``điểm b`` -> ``điểm b``
    - ``điều 32`` -> ``Điều 32``
    """
    if not text:
        return text

    normalized_text = re.sub(r'\s+', ' ', text).strip()
    label_map = {
        'diem': 'điểm',
        'khoan': 'khoản',
        'dieu': 'Điều',
    }
    canonical_label = label_map.get(type)
    if canonical_label is None:
        return normalized_text

    return re.sub(
        r'^\w+',
        canonical_label,
        normalized_text,
        count=1,
        flags=re.IGNORECASE
    )
