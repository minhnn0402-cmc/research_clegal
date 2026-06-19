"""Text cleaner utilities."""
import re
import unicodedata 


# Module-level compiled patterns
_CLEAN_HTML_PATTERNS = [
    re.compile(r'\[TABLE\].*?\[\\TABLE\]', re.DOTALL),          # [TABLE]...[/TABLE] blocks
    re.compile(r'\[TABLE\].*',             re.DOTALL),          # unclosed [TABLE]
    re.compile(r'<table[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE),  # HTML tables
    re.compile(r'\.\/\..*',               re.DOTALL),          # ./. marker and after
    re.compile(r'\[\d+\].*?(?=\[\d+\]|$)',re.DOTALL),          # footnotes [1], [2]...
]
_HORIZONTAL_WS = re.compile(r'[ \t]+') 
_REASON_PATTERN = re.compile(r'Lý do(?: (?:bãi bỏ|thay thế))?[^.]*\.')
_DOUBLE_QUOTES = re.compile(r'["\u201C\u201D].*?["\u201C\u201D]', re.DOTALL)
_SINGLE_QUOTES = re.compile(r"['\u2018\u2019].*?['\u2018\u2019]", re.DOTALL)

def clean_html(content: str) -> str:
    """Remove tables, HTML tags, ./. markers, and footnotes."""
    if not content:
        return content

    for pattern in _CLEAN_HTML_PATTERNS:
        content = pattern.sub('', content)

    return content.strip()

def normalize_unicode(text: str) -> str: 
    """Guard against mixed NFC/NFD encoding from different document sources."""    
    return unicodedata.normalize('NFC', text)

def remove_reason_section(text: str) -> str:
    """Remove 'Lý do bãi bỏ' / 'Lý do thay thế' section up to the first period."""
    if not text:
        return text

    text = _REASON_PATTERN.sub('', text) # Remove reason section

    return '\n'.join(
        line for line in (
            _HORIZONTAL_WS.sub(' ', line).strip()
            for line in text.splitlines()
        )
        if line
    )

def remove_quoted_text(clause_content: str) -> str:
        """Remove quoted text and normalize horizontal whitespace, preserving newlines."""
        if not clause_content:
            return clause_content

        clause_content = _DOUBLE_QUOTES.sub('', clause_content)
        clause_content = _SINGLE_QUOTES.sub('', clause_content)

        return '\n'.join(
            line for line in (
                _HORIZONTAL_WS.sub(' ', line).strip()
                for line in clause_content.splitlines()
            )
            if line
        )