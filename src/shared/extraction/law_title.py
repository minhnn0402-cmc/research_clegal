"""Extract law titles from text using fuzzy matching."""
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import List

_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)
_MAX_ABBREVIATION_TOKENS = 2
_MIN_ABBREVIATION_LENGTH = 2
_MAX_ABBREVIATION_LENGTH = 12


def _normalize_text(text: str) -> str:
    """Normalize text by removing punctuation and extra spaces."""
    # Remove punctuation but keep spaces
    text = re.sub(r'[,;.!?()]', ' ', text)
    # Normalize multiple spaces to single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def _tokenize(text: str) -> set:
    """Tokenize text into words."""
    return set(_normalize_text(text).split())


def _calculate_similarity(text: str, law_title: str) -> tuple:
    """
    Calculate similarity between text and law title using multiple methods.
    
    Returns:
        tuple: (exact_match, token_overlap_ratio, sequence_similarity)
    """
    text_normalized = text.lower()
    law_title_normalized = law_title.lower()
    
    # 1. Check for exact substring match
    exact_match = law_title_normalized in text_normalized
    
    # 2. Token-based matching (handles missing words, punctuation)
    text_tokens = _tokenize(text)
    title_tokens = _tokenize(law_title)
    
    if not title_tokens:
        return (False, 0.0, 0.0)
    
    # Calculate how many title tokens appear in text
    matching_tokens = title_tokens.intersection(text_tokens)
    token_overlap_ratio = len(matching_tokens) / len(title_tokens)
    
    # 3. Sequence similarity (handles word order, typos)
    text_clean = _normalize_text(text)
    title_clean = _normalize_text(law_title)
    sequence_similarity = SequenceMatcher(None, text_clean, title_clean).ratio()
    
    return (exact_match, token_overlap_ratio, sequence_similarity)


def _find_exact_standalone_title(
    text_normalized: str,
    law_titles: tuple[str, ...],
) -> str:
    for law_title in law_titles:
        if law_title and law_title.lower() == text_normalized:
            return law_title
    return ""


def _normalized_words(text: str) -> list[str]:
    return _WORD_PATTERN.findall(_normalize_text(text))


@lru_cache(maxsize=8)
def _build_title_abbreviation_candidates(
    law_titles: tuple[str, ...],
) -> frozenset[str]:
    candidates: set[str] = set()

    for law_title in law_titles:
        tokens = _normalized_words(law_title)
        if len(tokens) < 2:
            continue

        for prefix_length in range(1, min(3, len(tokens))):
            significant_tokens = tokens[prefix_length:]
            abbreviation = "".join(token[0] for token in significant_tokens)
            if len(abbreviation) < _MIN_ABBREVIATION_LENGTH:
                continue
            prefix = " ".join(tokens[:prefix_length])
            candidates.add(f"{prefix} {abbreviation}")

    return frozenset(candidates)


def _looks_like_short_law_abbreviation(text: str) -> bool:
    tokens = _normalized_words(text)
    if len(tokens) < 2:
        return False

    for prefix_length in range(1, min(3, len(tokens))):
        tail = tokens[prefix_length:]
        compact_tail = "".join(tail)
        if (
            1 <= len(tail) <= _MAX_ABBREVIATION_TOKENS
            and _MIN_ABBREVIATION_LENGTH
            <= len(compact_tail)
            <= _MAX_ABBREVIATION_LENGTH
        ):
            return True
    return False


def _contains_title_abbreviation_candidate(
    text: str,
    title_abbreviations: frozenset[str],
) -> bool:
    normalized_text = _normalize_text(text)
    for abbreviation in title_abbreviations:
        if re.search(rf"(?:^|\s){re.escape(abbreviation)}(?:$|\s)", normalized_text):
            return True
    return False


def extract_law_title(text: str, law_titles_for_regex: List) -> str:
    """
    Extract law title from the given text using provided law titles for regex matching.
    Uses fuzzy matching to handle missing words, punctuation, and variations.

    Args:
        text (str): The text to search for law titles.
        law_titles_for_regex (List): A list of law titles to use for regex matching.

    Returns:
        str: The extracted law title if found, otherwise an empty string.
    """
    if not text or not law_titles_for_regex:
        return ""
    
    # Normalize text to lowercase for case-insensitive matching
    text_normalized = text.lower()
    law_titles = tuple(str(law_title or "") for law_title in law_titles_for_regex)

    exact_standalone_title = _find_exact_standalone_title(
        text_normalized,
        law_titles,
    )
    if exact_standalone_title:
        return exact_standalone_title
    title_abbreviations = _build_title_abbreviation_candidates(law_titles)
    if (
        (
            _looks_like_short_law_abbreviation(text_normalized)
            and _normalize_text(text_normalized) in title_abbreviations
        )
        or _contains_title_abbreviation_candidate(
            text_normalized,
            title_abbreviations,
        )
    ):
        return ""
    
    # Check if input text is about an amendment law
    text_is_amendment = "sửa đổi" in text_normalized or "bổ sung" in text_normalized
    
    # CRITICAL FIX: Check for incomplete compound reference
    # E.g., "Luật sửa đổi, bổ sung một số điều của Luật Tổ chức Chính phủ" (missing "và Luật Tổ chức chính quyền địa phương")
    # This happens when the reference extractor splits a compound law reference
    # If text is an amendment AND ends abruptly after "của Luật X", it's likely incomplete
    if text_is_amendment and re.search(r'của\s+luật\s+[^\n]+$', text_normalized) and not re.search(r'và\s+luật', text_normalized):
        # This looks like an incomplete compound reference
        # Only match amendment laws that explicitly mention BOTH laws in the amendment title
        # Filter: require the title to contain ALL significant words from the text
        # This prevents fuzzy matching to unrelated short amendment laws
        pass  # Will apply stricter matching below
    
    # Find all matching law titles
    matches = []
    
    for law_title in law_titles_for_regex:
        if not law_title:
            continue
            
        law_title_normalized = law_title.lower()
        
        # Calculate similarity scores
        exact_match, token_overlap, sequence_sim = _calculate_similarity(text, law_title)
        
        # Only consider if there's reasonable similarity
        # Accept if: exact match OR high token overlap (80%+) OR decent sequence similarity (60%+)
        if exact_match or token_overlap >= 0.8 or sequence_sim >= 0.6:
            
            # Check if this is an amendment law
            is_amendment = "sửa đổi" in law_title_normalized or "bổ sung" in law_title_normalized
            
            # CRITICAL FIX: For incomplete compound references, apply strict filtering
            # If text is amendment but doesn't contain "và", and ends with "của Luật X",
            # it's likely an incomplete split from a compound reference
            # In such cases, require higher overlap AND check if the title contains the law name mentioned
            text_has_conjunction = " và " in text_normalized
            text_ends_with_law = re.search(r'của\s+(luật|bộ\s+luật)\s+\w+', text_normalized)
            
            is_incomplete_split = (
                text_is_amendment 
                and not text_has_conjunction 
                and text_ends_with_law is not None
            )
            
            if is_incomplete_split:
                # Incomplete split detected - the text mentions "của Luật X" without "và"
                # This means the reference was split, and we need to ensure we don't match
                # to a short, unrelated amendment law
                
                # Extract the law name mentioned in the text (after "của")
                law_name_match = re.search(r'của\s+(luật|bộ\s+luật)\s+([\w\s]+?)(?:\s+ngày|\s+năm|$)', text_normalized)
                if law_name_match:
                    mentioned_law_name = law_name_match.group(2).strip()
                    
                    # Check if the candidate title actually mentions this law
                    # For compound amendments like "luật A và luật B", both names should be present
                    if mentioned_law_name not in law_title_normalized:
                        # The candidate doesn't mention the law we're looking for - skip it
                        continue
                    
                    # If the candidate DOES contain the mentioned law AND also contains "và"
                    # (indicating it's a compound amendment), LOWER the token overlap requirement
                    # because the text is incomplete
                    if " và " in law_title_normalized:
                        # This is likely the correct compound amendment - accept lower overlap (70%+)
                        if token_overlap < 0.70:
                            continue
                    else:
                        # Single-target amendment - require high overlap
                        if token_overlap < 0.92:
                            continue
                else:
                    # Couldn't extract law name - require very high overlap
                    if token_overlap < 0.92:
                        continue
            
            # Base score: prioritize by match quality
            if exact_match:
                base_score = 10000
            else:
                # Fuzzy match: combine token overlap and sequence similarity
                base_score = int((token_overlap * 6000) + (sequence_sim * 4000))
            
            # Length bonus: longer titles are more specific
            length_bonus = len(law_title_normalized)
            
            # Apply amendment preference based on whether text is about amendment or not
            if text_is_amendment:
                # If text mentions amendment, prefer amendment laws
                amendment_bonus = 5000 if is_amendment else -5000
            else:
                # If text doesn't mention amendment, prefer non-amendment laws
                amendment_bonus = -5000 if is_amendment else 0
            
            # Total score
            total_score = base_score + length_bonus + amendment_bonus
            
            matches.append({
                'title': law_title,
                'score': total_score,
                'exact_match': exact_match,
                'token_overlap': token_overlap,
                'sequence_sim': sequence_sim,
                'is_amendment': is_amendment
            })
    
    if not matches:
        return ""
    
    # Sort by score (descending)
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    # Return the best match
    return matches[0]['title']
