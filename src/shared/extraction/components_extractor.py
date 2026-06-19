from typing import List, Dict, Optional
import re

from src.infrastructure.config import loai_van_ban_mapping, doc_number_patterns_for_regex
from src.shared.extraction.law_title import extract_law_title
from src.shared.extraction.date_issued import extract_date_issued


def _fallback_law_title(vanban_text: str, keyword_type: str) -> Optional[str]:
    label_by_type = {
        "hienphap": "hiến pháp",
        "boluat": "bộ luật",
        "luat": "luật",
        "phaplenh": "pháp lệnh",
    }
    label = label_by_type.get(keyword_type)
    if not label:
        return None

    # Only fallback on explicit dated/year-qualified references. This avoids
    # treating internal references such as "Luật này" as external documents.
    pattern = rf"\b{label}\b\s*(.*?)(?=\s+ngày\s+|\s+năm\s+\d{{4}}\b|\s+công\s+bố\s+theo\b|$)"
    match = re.search(pattern, vanban_text, re.IGNORECASE)
    if not match:
        return None

    title_tail = match.group(1).strip()
    title = f"{label} {title_tail}".strip()
    if title in {label, "luật này", "bộ luật này", "hiến pháp này", "pháp lệnh này"}:
        return None
    return re.sub(r"\s+", " ", title)


def extract_document_components(
    vanban_text: str,
    keyword_type: str,
    law_titles_for_regex: List
) -> Optional[Dict]:
    """
    Apply regex to extract components from the vanban (legal document) text.

    Args:
        vanban_text: The legal document text to extract from
        keyword_type: The type of document (e.g., 'luat', 'nghi_dinh', 'quyet_dinh')
        law_titles_for_regex: List of law title patterns for matching

    Returns:
        Dictionary containing extracted components with keys:
        - position_start, position_end, tieu_de, so_hieu, loai_van_ban, ngay, thang, nam
        Returns None if no pattern matched
    """
    vanban_text = re.sub(r'\s+', ' ', vanban_text).strip().lower()

    effective_keyword_type = keyword_type
    if keyword_type == "thongtu" and re.search(r"thông\s+tư\s+liên\s+tịch|\bttlt\b", vanban_text):
        effective_keyword_type = "thongtulientich"

    loai_van_ban = {k: v for k, v in loai_van_ban_mapping.items() if k == effective_keyword_type}

    if keyword_type in ['hienphap', 'boluat', 'luat', 'phaplenh']:
        law_title = extract_law_title(vanban_text, law_titles_for_regex)
        if not law_title:
            law_title = _fallback_law_title(vanban_text, keyword_type)
    else:
        law_title = None

    ngay_ban_hanh = extract_date_issued(vanban_text)

    regex_patterns = doc_number_patterns_for_regex.get(effective_keyword_type, [])

    for pattern in regex_patterns:
        match = re.search(pattern, vanban_text, re.IGNORECASE)
        if not match:
            continue

        raw_match = match.group()
        match_start = match.start()

        # Regex patterns already bound the document number; keep embedded dots
        # such as "66.13/2026/NQ-CP" and only guard against accidental newlines.
        cut_match = re.split(r'\n', raw_match, maxsplit=1)[0].strip()
        if not cut_match:
            continue

        so_hieu = re.sub(r'^số\s*', '', cut_match, flags=re.IGNORECASE).strip()
        so_hieu = re.sub(r'\s*-\s*', '-', so_hieu)
        so_hieu = re.sub(r'\s*/\s*', '/', so_hieu)
        so_hieu = re.sub(r'/nđcp\b', '/nđ-cp', so_hieu, flags=re.IGNORECASE)
        if effective_keyword_type == "thongtulientich":
            so_hieu = re.sub(r'/ttl\b', '/ttlt', so_hieu, flags=re.IGNORECASE)
        so_hieu = re.sub(r'^(\d{1,5})/tt/(\d{4})/tt-', r'\1/\2/tt-', so_hieu, flags=re.IGNORECASE)
        so_hieu = re.sub(r'^(\d{1,5}(?:\.\d{1,4})?)-(\d{4}/)', r'\1/\2', so_hieu)
        so_hieu = re.sub(r'\s+', ' ', so_hieu).strip()

        match_end = match_start + len(cut_match)

        return {
            'position_start': match_start,
            'position_end': match_end,
            'tieu_de': law_title,
            'so_hieu': so_hieu,
            'loai_van_ban': loai_van_ban.get(effective_keyword_type, ''),
            'ngay': ngay_ban_hanh['ngay'] if ngay_ban_hanh else None,
            'thang': ngay_ban_hanh['thang'] if ngay_ban_hanh else None,
            'nam': ngay_ban_hanh['nam'] if ngay_ban_hanh else None
        }

    if keyword_type in ['hienphap', 'boluat', 'luat', 'phaplenh'] and law_title:
        return {
            'position_start': 0,
            'position_end': len(vanban_text),
            'tieu_de': law_title,
            'so_hieu': '',
            'loai_van_ban': loai_van_ban_mapping.get(keyword_type, ''),
            'ngay': ngay_ban_hanh['ngay'] if ngay_ban_hanh else None,
            'thang': ngay_ban_hanh['thang'] if ngay_ban_hanh else None,
            'nam': ngay_ban_hanh['nam'] if ngay_ban_hanh else None
        }

    return None
