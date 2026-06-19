"""Extract date information from legal document text."""
from typing import Dict
import re


def extract_date_issued(text: str) -> Dict:
    """
    Extract day, month, year from legal document text.
    Returns a dictionary with keys 'ngay', 'thang', 'nam' for the first match found, or None if no match.
    Day and month are formatted with leading zeros (two digits).
    """

    # Pattern 1: Slash format - "ngày DD/MM/YYYY" or "ngày DD/M/YYYY"
    pattern_slash = r'ngày\s+(\d{1,2})/(\d{1,2})/(\d{4})'
    match = re.search(pattern_slash, text, re.IGNORECASE)
    if match:
        return {
            'ngay': str(int(match.group(1))).zfill(2),
            'thang': str(int(match.group(2))).zfill(2),
            'nam': int(match.group(3))
        }

    # Pattern 2: Hyphen format - "ngày DD-MM-YYYY" or "ngày DD-M-YYYY"
    pattern_hyphen = r'ngày\s+(\d{1,2})-(\d{1,2})-(\d{4})'
    match = re.search(pattern_hyphen, text, re.IGNORECASE)
    if match:
        return {
            'ngay': str(int(match.group(1))).zfill(2),
            'thang': str(int(match.group(2))).zfill(2),
            'nam': int(match.group(3))
        }

    # Pattern 3: Full date - "ngày DD tháng MM năm YYYY" (case-insensitive)
    pattern_full = r'ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})'
    match = re.search(pattern_full, text, re.IGNORECASE)
    if match:
        return {
            'ngay': str(int(match.group(1))).zfill(2),
            'thang': str(int(match.group(2))).zfill(2),
            'nam': int(match.group(3))
        }
    
    # Pattern 4: Month and year only - "tháng MM năm YYYY"
    pattern_month_year = r'tháng\s+(\d{1,2})\s+năm\s+(\d{4})'
    match = re.search(pattern_month_year, text, re.IGNORECASE)
    if match:
        return {
            'ngay': None,
            'thang': str(int(match.group(1))).zfill(2),
            'nam': int(match.group(2))
        }
    
    # Pattern 5: Year only - "năm YYYY"
    pattern_year = r'năm\s+(\d{4})'
    match = re.search(pattern_year, text, re.IGNORECASE)
    if match:
        return {
            'ngay': None,
            'thang': None,
            'nam': int(match.group(1))
        }
    
    # Pattern 6: Standalone year - "YYYY" (4 digits) at end of text or before punctuation/conjunctions
    # This handles cases like "Luật Hàng không dân dụng Việt Nam 1991"
    pattern_standalone_year = r'\s+(\d{4})(?:\s*(?:,|;|và|$))?'
    match = re.search(pattern_standalone_year, text, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        # Only consider it a year if it's a reasonable year (1900-2100)
        if 1900 <= year <= 2100:
            return {
                'ngay': None,
                'thang': None,
                'nam': year
            }
    
    return None
