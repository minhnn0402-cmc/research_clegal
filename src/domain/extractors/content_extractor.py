"""Content extraction utilities for legal documents."""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple
from src.shared.text.clean_phrase_scope import clean_text_after_thay_the_keyword
from src.shared.text.cleaners import clean_html, normalize_unicode, remove_quoted_text, remove_reason_section


@dataclass(frozen=True)
class PositionMappedContent:
    """Cleaned text plus best-effort offsets back to the original com_title."""

    text: str
    raw_text: str
    clean_to_raw: List[Optional[int]]

    def raw_span(self, start: int, end: int) -> Optional[Tuple[int, int]]:
        """Map a cleaned-text [start, end) span to raw inclusive offsets."""
        if start is None or end is None or end <= start:
            return None

        bounded_start = max(0, int(start))
        bounded_end = min(len(self.clean_to_raw), int(end))
        if bounded_start >= bounded_end:
            return None

        raw_start = next(
            (
                self.clean_to_raw[idx]
                for idx in range(bounded_start, bounded_end)
                if self.clean_to_raw[idx] is not None
            ),
            None,
        )
        raw_end = next(
            (
                self.clean_to_raw[idx]
                for idx in range(bounded_end - 1, bounded_start - 1, -1)
                if self.clean_to_raw[idx] is not None
            ),
            None,
        )
        if raw_start is None or raw_end is None:
            return None
        return int(raw_start), int(raw_end)

    def subcontent(self, sub_text: str) -> "PositionMappedContent":
        """Return a mapper for a substring of this cleaned text."""
        if not sub_text:
            return PositionMappedContent("", self.raw_text, [])

        start = self.text.find(sub_text)
        if start < 0:
            return PositionMappedContent(
                sub_text,
                self.raw_text,
                ContentExtractor._build_clean_to_raw_map(sub_text, self.raw_text),
            )
        end = start + len(sub_text)
        return PositionMappedContent(
            sub_text,
            self.raw_text,
            self.clean_to_raw[start:end],
        )


class ContentExtractor:
    """
    Extracts and processes content from legal document clauses.
    Handles content normalization, cleaning, and segmentation.
    """
    
    CLAUSE_TYPES = {'vanban', 'diem', 'khoan', 'dieu'}

    processed_clause_content_hashes: Set[int] = set()

    @staticmethod 
    def should_skip_clause(clause_info: Dict, processed_clause_content_hashes: Set[int] = None) -> bool:
        """
        Determine if a clause should be skipped.
        
        Args:
            clause_info: Clause information dictionary
            processed_clause_content_hashes: Set of already processed content hashes
            
        Returns:
            True if clause should be skipped, False otherwise
        """
        if processed_clause_content_hashes is None:
            processed_clause_content_hashes = ContentExtractor.processed_clause_content_hashes
        
        if not isinstance(clause_info, dict):
            return True
        
        clause_type = (clause_info.get('com_type') or '').lower()
        if clause_type not in ContentExtractor.CLAUSE_TYPES:
            return True
        
        content = ContentExtractor.get_content(clause_info)
        if not content.strip():
            return True
        
        clause_key = clause_info.get('com_key', '')
        # Use a hash of the clause key and content to track processed clauses, avoiding memory issues with large content
        content_hash = hash(f"{clause_key}:{content}")

        if content_hash in processed_clause_content_hashes:
            return True
        
        processed_clause_content_hashes.add(content_hash)

        return False    

    @staticmethod 
    def get_content(clause: Dict) -> str:
        """
        Extract content from a clause based on its type.
        
        Args:
            clause: Clause dictionary
            
        Returns:
            Cleaned content string
        """
        clause_type = (clause.get('com_type') or '').lower()

        # Exclude com_type not in ['vanban', 'diem', 'khoan', 'dieu']
        if clause_type not in ['vanban', 'diem', 'khoan', 'dieu']:
            return ""

        return ContentExtractor.get_content_with_positions(clause).text

    @staticmethod
    def get_content_with_positions(clause: Dict) -> PositionMappedContent:
        """Extract cleaned content and keep a mapper to raw ``com_title`` offsets."""
        clause_type = (clause.get('com_type') or '').lower()

        if clause_type not in ['vanban', 'diem', 'khoan', 'dieu']:
            return PositionMappedContent("", "", [])

        raw_content = clause.get('com_title', '') or ""

        if not raw_content.strip():
            return PositionMappedContent("", raw_content, [])

        content = clean_html(raw_content)
        content = normalize_unicode(content)
        content = remove_reason_section(content)
        content = clean_text_after_thay_the_keyword(content)
        content = remove_quoted_text(content)

        return PositionMappedContent(
            text=content,
            raw_text=raw_content,
            clean_to_raw=ContentExtractor._build_clean_to_raw_map(content, raw_content),
        )

    @staticmethod
    def _build_clean_to_raw_map(cleaned: str, raw: str) -> List[Optional[int]]:
        """Best-effort subsequence mapper from cleaned content back to raw text."""
        mapping: List[Optional[int]] = []
        raw_index = 0

        for clean_char in cleaned:
            if clean_char.isspace():
                while raw_index < len(raw) and not raw[raw_index].isspace():
                    raw_index += 1
                mapping.append(raw_index if raw_index < len(raw) else None)
                if raw_index < len(raw):
                    raw_index += 1
                continue

            found_index: Optional[int] = None
            while raw_index < len(raw):
                raw_char = raw[raw_index]
                if raw_char == clean_char or raw_char.lower() == clean_char.lower():
                    found_index = raw_index
                    raw_index += 1
                    break
                raw_index += 1

            mapping.append(found_index)

        return mapping
    
