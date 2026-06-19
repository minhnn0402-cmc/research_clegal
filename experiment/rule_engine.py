"""Thread-safe wrapper around the production rule-based extractor.

Both the rule-only baseline (A0) and the LLM gate (A3) need the exact same
rule candidates the production system would emit. We reuse
``evaluation.evaluate.extract_single_clause`` (which drives the real
``RelationsExtractor._process_clause``) and give each worker thread its own
extractor instance, since ``RelationsExtractor`` keeps mutable per-clause
state that is not safe to share across threads.
"""

from __future__ import annotations

import threading
from typing import Dict, List

from evaluation.evaluate import extract_single_clause
from src.infrastructure.config import ConfigLoader
from src.infrastructure.logging import get_logger
from src.domain.extractors.relations_extractor import RelationsExtractor

from experiment.clause_dataset import ClauseUnit


class RuleEngine:
    """Produces production rule candidates for a clause unit, thread-safely."""

    def __init__(self) -> None:
        self._config = ConfigLoader()
        self._law_titles = self._config.law_titles_for_regex
        self._local = threading.local()

    def _extractor(self) -> RelationsExtractor:
        extractor = getattr(self._local, "extractor", None)
        if extractor is None:
            extractor = RelationsExtractor(
                doc_clause_types=self._config.doc_clause_types,
                law_titles_for_regex=self._law_titles,
                logger=get_logger("RuleEngine"),
            )
            self._local.extractor = extractor
        return extractor

    def predict(self, unit: ClauseUnit) -> List[Dict]:
        """Return rule predictions as flat ``{"reference","relation"}`` items."""
        return extract_single_clause(
            extractor=self._extractor(),
            so_hieu=unit.so_hieu,
            title=unit.title,
            clause_type=unit.clause_type,
            content=unit.content,
            parent_content=unit.parent_content,
            grandparent_content=unit.grandparent_content,
            idx=unit.row_index,
            law_titles=self._law_titles,
            use_llm=False,
        )
