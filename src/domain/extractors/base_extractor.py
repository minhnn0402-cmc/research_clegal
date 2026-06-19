"""
Stable facade for the BaseExtractor pipeline.

The public API stays in this module, while the implementation now follows the
same high-level flow used by ``RelationsExtractor._process_clause``:
1. reference extraction
2. relation-type extraction
3. relation/reference matching
"""

from typing import List

from src.domain.extractors.base_extractor_flow.authority_resolution import (
    AuthorityResolution,
)
from src.domain.extractors.base_extractor_flow.match_deduplication import (
    MatchDeduplication,
)
from src.domain.extractors.base_extractor_flow.reference_extraction import (
    ReferenceExtraction,
)
from src.domain.extractors.base_extractor_flow.reference_normalization import (
    ReferenceNormalization,
)
from src.domain.extractors.base_extractor_flow.relation_matching import (
    RelationMatching,
)
from src.domain.extractors.base_extractor_flow.relation_type_extraction import (
    RelationTypeExtraction,
)
from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared


class BaseExtractor(
    BaseExtractorShared,
    RelationTypeExtraction,
    ReferenceNormalization,
    ReferenceExtraction,
    AuthorityResolution,
    MatchDeduplication,
    RelationMatching,
):
    """Extractor facade with flow-aligned mixins behind a stable public contract."""

    def __init__(self, doc_clause_types: List[str]):
        """Store configured document and clause type labels for downstream stages."""
        self.doc_clause_types = doc_clause_types
