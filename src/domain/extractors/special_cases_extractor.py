import re
from typing import Callable, Dict, List, Optional, Tuple

from src.domain.extractors.base_extractor import BaseExtractor
from src.domain.extractors.base_extractor_flow.reference_extraction import (
    ReferenceExtraction,
)
from src.utils.vbhn_handler import get_content_vbhn

# A document consolidated into a VBHN is always cited with its own document
# number (e.g. "Luật … số 56/2024/QH15", "Nghị định số 143/2013/NĐ-CP"). Bare
# law names that appear in a VBHN preamble are the *amendment scope* of an
# amending act ("… sửa đổi, bổ sung một số điều của Luật Kế toán, Luật …"),
# not separate consolidation targets, so they must not become hop_nhat edges.
_VBHN_DOCUMENT_NUMBER_PATTERN = re.compile(
    r"\bsố\s+\S*\d"
    r"|\b\d{1,5}[A-Za-zĐđ]?\s*/\s*\d{2,4}\b"
    r"|\b\d{2,}\s*/\s*[A-ZĐ]",
    re.IGNORECASE,
)


def _reference_has_document_number(reference: Dict) -> bool:
    """True when any component of *reference* carries an explicit document number."""
    for component in reference.values():
        if isinstance(component, dict):
            information = component.get("information", "")
            if information and _VBHN_DOCUMENT_NUMBER_PATTERN.search(information):
                return True
    return False


def handle_vbhn_relation(
    base_extractor: BaseExtractor,
    clause_type: str,
    clause_key: Optional[str],
    clause_content: str,
    doc_types: List[str],
    clause_types: List[str],
    law_titles: List[str],
    build_relations_fn: Callable[..., List[Dict]],
    data: Optional[List[Dict]] = None,
    child_to_parent: Optional[Dict[str, str]] = None,
    position_mapper: Optional[Callable[[int, int], Optional[Tuple[int, int]]]] = None,
) -> List[Dict]:
    """
    Build benchmark-aligned ``hop_nhat`` relations for VBHN documents.

    A VBHN preamble lists the base document and documents consolidated into it.
    These targets are modeled as document-level ``hop_nhat`` edges, while legal
    status phrases inside the same preamble are intentionally not classified as
    ``sua_doi_bo_sung``/``thay_the``/``bai_bo``.
    """
    if clause_type != "vanban" or not clause_content or not clause_content.strip():
        return []

    preamble_content = get_content_vbhn(clause_content)
    references = ReferenceExtraction.extract_references(
        base_extractor,
        content=preamble_content,
        doc_types=doc_types,
        clause_types=clause_types,
        law_titles=law_titles,
        clause_type=clause_type,
        clause_key=clause_key,
        data=data,
        child_to_parent=child_to_parent,
        position_mapper=position_mapper,
    )
    if not references:
        return []

    # Keep only genuine consolidation targets: documents cited with their own
    # number. This drops bare law-name mentions that belong to an amending act's
    # amendment-scope list inside the same preamble.
    consolidation_targets = [
        reference for reference in references
        if _reference_has_document_number(reference)
    ]
    if not consolidation_targets:
        return []

    relation_matches = [
        {
            "relation_type": "hop_nhat",
            "reference": reference,
        }
        for reference in consolidation_targets
    ]

    return build_relations_fn(
        relation_matches=relation_matches,
        clause_type=clause_type,
        clause_key=clause_key,
    )


def handle_cancu_relation(
    base_extractor: BaseExtractor,
    clause_type: str,
    clause_key: Optional[str],
    clause_content: str,
    doc_types: List[str],
    clause_types: List[str],
    law_titles: List[str],
    build_relations_fn: Callable[..., List[Dict]],
    data: Optional[List[Dict]] = None,
    child_to_parent: Optional[Dict[str, str]] = None,
    position_mapper: Optional[Callable[[int, int], Optional[Tuple[int, int]]]] = None,
) -> List[Dict]:
    """
    Build isolated ``can_cu`` relations from the leading ``Căn cứ`` block.
    """
    if clause_type != 'vanban' or not clause_content or not clause_content.strip():
        return []

    references = ReferenceExtraction.extract_references(
        base_extractor,
        content=clause_content,
        doc_types=doc_types,
        clause_types=clause_types,
        law_titles=law_titles,
        clause_type=clause_type,
        clause_key=clause_key,
        data=data,
        child_to_parent=child_to_parent,
        position_mapper=position_mapper,
    )
    if not references:
        return []

    relation_matches = [
        {
            'relation_type': 'can_cu',
            'reference': reference,
        }
        for reference in references
    ]

    return build_relations_fn(
        relation_matches=relation_matches,
        clause_type=clause_type,
        clause_key=clause_key,
    )
