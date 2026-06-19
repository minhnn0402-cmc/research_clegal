import re
from typing import List, Dict
from src.domain.relation_constants import SEARCHABLE_CLAUSE_TYPES
from src.shared.validation.filters import remove_accents


def _is_non_document_vanban_phrase(information: str) -> bool:
    """Return True for generic form/procedure phrases that are not legal documents."""
    normalized = remove_accents(information.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if not normalized.startswith('van ban'):
        return False

    form_phrase_patterns = (
        r'\bvan ban de nghi\b',
        r'\bmau so\b',
        r'\bbieu mau\b',
        r'\bto khai\b',
        r'\bho so\b',
        r'\bban chinh\b',
        r'\bban sao\b',
    )
    return any(re.search(pattern, normalized) for pattern in form_phrase_patterns)


def get_clause_relations(clause_data: Dict) -> List[Dict]:
    """
    Return the normalized relation list for one extracted clause payload.
    
    This function flattens the relationship structure by expanding nested 'tail' lists 
    into individual relation entries. Each returned entry will have a single dictionary 
    item in its 'tail' field.
    
    Args:
        clause_data: A dictionary containing clause-level extraction results.
        
    Returns:
        A list of flattened relationship dictionaries.
    """
    if not isinstance(clause_data, dict):
        return []

    relations = clause_data.get('relations')
    if not isinstance(relations, list):
        return []

    # Flatten relations if tail is a list of references
    flattened = []
    for rel_info in relations:
        if not isinstance(rel_info, dict):
            continue

        rel_type = rel_info.get('relation')
        tails = rel_info.get('tail', [])

        if isinstance(tails, dict):
            tails = [tails]

        if not isinstance(tails, list):
            continue

        for t in tails:
            flattened.append({
                'relation': rel_type,
                'tail': t
            })
    return flattened

def should_keep_failed_reference(failed: Dict) -> bool:
    """
    Decide if a document reference that failed to be matched in ES/DB 
    should still be kept in the failed list or discarded.
    
    A reference is kept if it has enough identifying information to be 
    meaningful for manual review or future matching.
    """
    # Find the document type key (not a clause type)
    doc_type_key = None
    for key in failed.keys():
        if key not in SEARCHABLE_CLAUSE_TYPES:
            doc_type_key = key
            break
    
    if not doc_type_key or doc_type_key not in failed:
        return False
    
    doc_info = failed[doc_type_key]
    doc_type = doc_info.get('type', '')
    information = doc_info.get('information', '').strip()

    if not information:
        return False

    # Normalize for comparison (remove accents and spaces)
    info_norm = remove_accents(information.lower()).replace(' ', '')
    type_norm = remove_accents((doc_type or doc_type_key).lower()).replace(' ', '')

    # If the information is just the doc type name itself, it's too vague
    if info_norm == type_norm:
        return False

    if (doc_type or doc_type_key) == 'vanban' and _is_non_document_vanban_phrase(information):
        return False

    # 1. ALWAYS KEEP major document types (Luật, Bộ luật, Hiến pháp)
    # Even without a number, these are high-value references.
    if doc_type in ['hienphap', 'boluat', 'luat']:
        return True

    # 2. MATCH by Number (Số hiệu)
    # Supports: "số 123/2024/NĐ-CP", "số 45/CP", and also "123/2024/NĐ-CP" (without 'số')
    # The pattern looks for digits followed by a slash and more alphanumeric/slash/dash characters
    so_hieu_robust_pattern = r'(\bsố\s+)?\d+/\d{4}/[A-ZĐ\-]+|\b\d+/[A-ZĐ\-]+|(\bsố\s+)\d+'
    if re.search(so_hieu_robust_pattern, information, re.IGNORECASE):
        return True
    
    # 3. MATCH by Date
    # Supports: "ngày 01/01/2024", "ngày 01 tháng 01 năm 2024", "01/10/2023"
    date_robust_pattern = (
        r'\bngày\s+\d{1,2}(?:\s*[\/\-]\s*\d{1,2}(?:\s*[\/\-]\s*\d{2,4})?)?|' # ngày 01/01/2024
        r'\bngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|'               # ngày 01 tháng 01 năm 2024
        r'\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}'                             # 01/10/2023
    )
    if re.search(date_robust_pattern, information, re.IGNORECASE):
        return True
    
    # 4. MATCH by Specific Year
    if re.search(r'\bnăm\s+\d{4}\b', information, re.IGNORECASE):
        return True

    # 5. Fallback: Long descriptive titles
    # If a title is reasonably long (> 30 chars), it's likely a specific descriptive mention
    # worth keeping even if it lacks a formal number/date yet.
    if len(information) > 30:
        return True
    
    return False
