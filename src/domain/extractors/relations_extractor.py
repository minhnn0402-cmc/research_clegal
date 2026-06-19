"""Document relationship extraction orchestration."""

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple

from src.domain.builders.hierarchy_builder import HierarchyBuilder
from src.domain.model.relation_types import (
    EXTRACTOR_RELATION_TYPES as _RT_EXTRACTOR,
    LLM_ELIGIBLE_RELATION_TYPES as _RT_LLM_ELIGIBLE,
    LLM_FALLBACK_RELATION_TYPES as _RT_LLM_FALLBACK,
    MAJOR_RELATION_TYPES as _RT_MAJOR,
)
from src.domain.relation_constants import SEARCHABLE_CLAUSE_TYPE_SET
from src.domain.extractors.base_extractor import BaseExtractor
from src.domain.extractors.base_extractor_flow.shared import unidecode
from src.domain.extractors.content_extractor import ContentExtractor
from src.shared.text.clean_phrase_scope import extract_can_cu_section
from src.utils.vbhn_handler import is_vanban_hop_nhat
from src.domain.extractors.special_cases_extractor import (
    handle_cancu_relation,
    handle_vbhn_relation,
)
from src.shared.extraction.multiple_reference_expander import expand_multiple_references
from src.domain.extractors.internal_reference_resolver import InternalReferenceResolver
from src.infrastructure.config import loai_van_ban_mapping


# "Điều X của Thông tư liên tịch này", "Điều 5 của Nghị quyết này", etc.
# Built from loai_van_ban_mapping (longest-first) so compound types like
# "Thông tư liên tịch" are matched before their shorter prefix "Thông tư".
_DOC_TYPE_NAMES_SORTED_FOR_INTERNAL = sorted(
    loai_van_ban_mapping.values(), key=len, reverse=True
)
_INTERNAL_DOC_CHUA_NAY_PATTERN = re.compile(
    r"\bcủa\s+(?:" + "|".join(re.escape(n) for n in _DOC_TYPE_NAMES_SORTED_FOR_INTERNAL) + r")\s+này\b",
    re.IGNORECASE,
)



class RelationsExtractor:
    """
    Extractor for document relationships data.
    
    This class processes legal document clauses to extract relationships between
    documents such as references, amendments, replacements, and revocations.
    """
    SUPPORTED_CLAUSE_TYPES = frozenset({"dieu", "khoan", "diem", "vanban"})
    LLM_FALLBACK_RELATION_TYPES = _RT_LLM_FALLBACK
    _LLM_ELIGIBLE_RELATION_TYPES = _RT_LLM_ELIGIBLE
    _MAJOR_RELATION_TYPES = _RT_MAJOR
    _PARENT_APPENDIX_SELF_SOURCE_CUE_PATTERN = re.compile(
        r"\bban\s+hanh\b.{0,260}\b(?:phu\s+luc|mau|danh\s+muc|bieu\s+mau)\b"
        r".{0,180}\bkem\s+theo\s+(?:nghi\s+dinh|thong\s+tu|luat|quyet\s+dinh)\s+nay\b",
        re.IGNORECASE | re.DOTALL,
    )
    _PARENT_APPENDIX_SOURCE_CONTEXT_PATTERN = re.compile(
        r"\bsua\s+doi\s*,?\s*bo\s+sung\b.{0,260}"
        r"\b(?:phu\s+luc|danh\s+muc|mau|bieu\s+mau)\b.{0,220}\bkem\s+theo\b",
        re.IGNORECASE | re.DOTALL,
    )
    _INTERNAL_DAN_CHIEU_ALLOWED_PREFIX_PATTERN = re.compile(
        r"(?:"
        r"theo\s+(?:đúng\s+)?quy\s+định"
        r"|quy\s+định\s+(?:tại|của|trong)"
        r"|được\s+quy\s+định\s+(?:tại|trong)"
        r"|các\s+quy\s+định\s+tại"
        r"|ban\s+hành\s+kèm\s+theo"
        r"|được\s+ban\s+hành\s+theo"
        r"|tuân\s+thủ\s+các\s+quy\s+định"
        r"|đính\s+chính\s+tại"
        r"|theo\s+hướng\s+dẫn\s+tại"
        r"|tại\s+(?:mục|chương|phần)\b[^\.;:\n]{0,80}"
        r")\s*$",
        re.IGNORECASE,
    )
    # _INTERNAL_CLAUSE_DIRECT_CUE_PATTERN = re.compile(
    #     r"\b(?:tại|theo)\s*$",
    #     re.IGNORECASE,
    # )
    _INTERNAL_ACTION_EXCEPTION_PREFIX_PATTERN = re.compile(
        r"\btrừ\s+trường\s+hợp\s+quy\s+định\s+tại\s*$",
        re.IGNORECASE,
    )
    _INTERNAL_ACTION_EFFECT_CONTEXT_PATTERN = re.compile(
        r"\b(?:hết\s+hiệu\s+lực|ngưng\s+hiệu\s+lực|chấm\s+dứt\s+hiệu\s+lực|"
        r"bãi\s+bỏ|hủy\s+bỏ|thay\s+thế|đình\s+chỉ)(?:\s+thi\s+hành)?\b",
        re.IGNORECASE,
    )
    
    def __init__(self, 
                 doc_clause_types: Optional[Dict] = None,
                 law_titles_for_regex: Optional[List] = None,
                 logger=None):
        """
        Initialize the document relationships extractor.
        
        Args:
            doc_clause_types: Dictionary containing 'doc_types' and 'clause_types' lists
            law_titles_for_regex: List of law title patterns for matching
            logger: Logger instance for logging operations
        """
        self.doc_clause_types = doc_clause_types or {}
        self.doc_types = self.doc_clause_types.get('doc_types', [])
        self.clause_types = self.doc_clause_types.get('clause_types', [])
        self.law_titles_for_regex = law_titles_for_regex or []
        self.logger = logger

        self.base_extractor = BaseExtractor(
            doc_clause_types=self.doc_types
        )
        self.processed_clause_content_hashes: Set[str] = set()
        self._hashes_lock = threading.Lock()
        self._rejected_relations: List[Dict] = []
        self._rejected_lock = threading.Lock()
        # Reusable per-extractor clause pool. Created lazily on first
        # extract_relations call (max_workers depends on use_llm). Reusing the
        # pool across documents avoids 16x thread spawn/shutdown cycles per doc.
        self._clause_pool: Optional[ThreadPoolExecutor] = None
        self._clause_pool_workers: int = 0

    def get_relationship_types(self) -> List[str]:
        """
        Get the list of supported relationship types.

        Returns:
            List of relationship type strings
        """
        return list(_RT_EXTRACTOR)

    def close(self) -> None:
        """Shut down the reusable clause pool, if one was created."""
        if self._clause_pool is not None:
            self._clause_pool.shutdown(wait=False)
            self._clause_pool = None
            self._clause_pool_workers = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _get_ancestor_clause_contents(
        child_to_parent: Dict,
        clause_key: str,
        clause_index_by_key: Optional[Dict[str, Dict]] = None,
        data: Optional[List[Dict]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Return parent and grandparent clause contents for relation inheritance."""
        if not clause_key:
            return None, None

        clause_lookup = clause_index_by_key or {}
        if not clause_lookup and data:
            for item in data:
                if not isinstance(item, dict):
                    continue
                item_key = item.get("com_key")
                if not item_key or item_key in clause_lookup:
                    continue
                clause_lookup[item_key] = item
        parent_content = None
        grandparent_content = None

        parent_key = child_to_parent.get(clause_key)
        if parent_key:
            parent_clause = clause_lookup.get(parent_key)
            if parent_clause is not None:
                parent_content = ContentExtractor.get_content(parent_clause)

            grandparent_key = child_to_parent.get(parent_key)
            if grandparent_key:
                grandparent_clause = clause_lookup.get(grandparent_key)
                if grandparent_clause is not None:
                    grandparent_content = ContentExtractor.get_content(grandparent_clause)

        return parent_content, grandparent_content

    @staticmethod
    def _index_clauses_by_key(data: List[Dict]) -> Dict[str, Dict]:
        """Build an O(1) lookup map for ancestor-content resolution."""
        clauses_by_key: Dict[str, Dict] = {}
        for clause in data:
            if not isinstance(clause, dict):
                continue
            clause_key = clause.get("com_key")
            if not clause_key or clause_key in clauses_by_key:
                continue
            clauses_by_key[clause_key] = clause
        return clauses_by_key

    @property
    def rejected_relations(self) -> List[Dict]:
        """Snapshot of relations rejected by DistractorFilter in the last extract_relations call."""
        with self._rejected_lock:
            return list(self._rejected_relations)

    def extract_relations(
        self, data: Dict, cls_so_hieu: str, cls_title: str,
        cls_document_type: str = "", use_llm: bool = False,
        track_rejections: bool = False,
    ) -> List[Dict]:
        """
        Extract document relationships data from the provided parsed document data.
        
        Args:
            data: Parsed document data containing clause information
            cls_so_hieu: Document number
            cls_title: Document title
            cls_document_type: Document type name (e.g. "Luật", "Thông tư")
            use_llm: Whether to allow LLM (default False)
            
        Returns:
            List of dictionaries with extracted relationship data
        """
        results = []
        law_titles = self.law_titles_for_regex
        clause_index_by_key = self._index_clauses_by_key(data)

        _, child_to_parent = HierarchyBuilder.build_hierarchy(data_parsing=data)

        if track_rejections:
            with self._rejected_lock:
                self._rejected_relations = []

        def process_one(clause_info: Dict) -> Optional[List[Dict]]:
            local_rejected: Optional[List[Dict]] = [] if track_rejections else None

            # Thread-safe skip check
            with self._hashes_lock:
                if ContentExtractor.should_skip_clause(
                    clause_info,
                    self.processed_clause_content_hashes
                ):
                    return None

            result = self._process_clause(
                data=data,
                child_to_parent=child_to_parent,
                clause=clause_info,
                law_titles=law_titles,
                cls_so_hieu=cls_so_hieu,
                cls_title=cls_title,
                cls_document_type=cls_document_type,
                use_llm=use_llm,
                clause_index_by_key=clause_index_by_key,
                rejected_buffer=local_rejected,
            )

            if track_rejections and local_rejected:
                with self._rejected_lock:
                    self._rejected_relations.extend(local_rejected)

            return result

        # Pre-filter to only supported clause types with non-empty content so the
        # thread pool doesn't pay submission overhead for clauses that _process_clause
        # would immediately discard.
        eligible = [
            c for c in data
            if isinstance(c, dict)
            and (c.get("com_type") or "").lower() in self.SUPPORTED_CLAUSE_TYPES
            and ContentExtractor.get_content(c).strip()
        ]

        # Per-clause work is regex-heavy and CPU-bound (no ES/IO inside
        # _process_clause itself — ES is done later in post_process_relations).
        # When LLM is disabled the work cannot benefit from threading because
        # Python regex holds the GIL; the outer 8-worker doc pool already
        # provides concurrency across documents. Running clauses serially here
        # eliminates GIL contention from 8x16 contending threads and is
        # measurably faster on VPN-bound benchmarks where CPU is the inner
        # bottleneck. The pool is only used when LLM is enabled (I/O-bound).
        if use_llm:
            max_workers = 8
            if self._clause_pool is None or self._clause_pool_workers != max_workers:
                if self._clause_pool is not None:
                    self._clause_pool.shutdown(wait=False)
                self._clause_pool = ThreadPoolExecutor(max_workers=max_workers)
                self._clause_pool_workers = max_workers
            batch_results = list(self._clause_pool.map(process_one, eligible))
        else:
            batch_results = [process_one(c) for c in eligible]

        for res in batch_results:
            if res:
                results.extend(res)

        # Clear processed hashes for next document
        with self._hashes_lock:
            self.processed_clause_content_hashes.clear()

        return results

    def _process_clause(
        self,
        data: List[Dict],
        child_to_parent: Dict,
        clause: Dict,
        law_titles: List,
        cls_so_hieu: str,
        cls_title: str,
        cls_document_type: str = "",
        use_llm: bool = False,
        clause_index_by_key: Optional[Dict[str, Dict]] = None,
        rejected_buffer: Optional[List[Dict]] = None,
    ) -> Optional[List[Dict]]:
        """
        Process a single clause to extract relationship data.
        
        Args:
            data: Full parsed document data
            child_to_parent: Hierarchy mapping from HierarchyBuilder
            clause: Current clause information to process
            law_titles: List of law title patterns
            cls_so_hieu: Document number
            cls_title: Document title
            cls_document_type: Document type name (e.g. "Luật", "Thông tư")
            use_llm: Whether to allow LLM (default False)
            clause_index_by_key: O(1) lookup map for ancestor-content resolution

        Returns:
            Dictionary with clause and relationship data, or None if no relationships found
        """
        clause_type = (clause.get("com_type") or "").lower()
        clause_key = clause.get("com_key", "")

        if clause_type not in self.SUPPORTED_CLAUSE_TYPES:
            return None

        clause_mapped_content = ContentExtractor.get_content_with_positions(clause)
        clause_content = clause_mapped_content.text
        if not clause_content.strip():
            return None

        # Handle VBHN
        if is_vanban_hop_nhat(cls_so_hieu):
            vbhn_case_result = self._extract_vbhn_relations(
                clause_type=clause_type,
                clause_key=clause_key,
                clause_content=clause_content,
                position_mapper=clause_mapped_content.raw_span,
                law_titles=law_titles,
                data=data,
                child_to_parent=child_to_parent,
            )
            return vbhn_case_result or None

        can_cu_relations, operative_content, operative_mapped_content = self._extract_can_cu_relations_and_content(
            clause_type=clause_type,
            clause_key=clause_key,
            clause_mapped_content=clause_mapped_content,
            law_titles=law_titles,
            data=data,
            child_to_parent=child_to_parent,
        )

        generic_relations = self._extract_generic_relations(
            clause_type=clause_type,
            clause_key=clause_key,
            content=operative_content,
            law_titles=law_titles,
            cls_so_hieu=cls_so_hieu,
            cls_title=cls_title,
            cls_document_type=cls_document_type,
            use_llm=use_llm,
            data=data,
            child_to_parent=child_to_parent,
            clause_index_by_key=clause_index_by_key,
            position_mapper=operative_mapped_content.raw_span,
            rejected_buffer=rejected_buffer,
        )

        return self._merge_clause_relation_groups(
            clause_type=clause_type,
            clause_key=clause_key,
            can_cu_relations=can_cu_relations,
            generic_relations=generic_relations,
        )

    def _extract_vbhn_relations(
        self,
        clause_type: str,
        clause_key: Optional[str],
        clause_content: str,
        law_titles: List,
        data: List[Dict],
        child_to_parent: Dict,
        cls_title: Optional[str] = None,
        position_mapper=None,
    ) -> List[Dict]:
        """Stage 0: isolate VBHN-only extraction flow."""
        return handle_vbhn_relation(
            base_extractor=self.base_extractor,
            clause_type=clause_type,
            clause_key=clause_key,
            clause_content=clause_content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=law_titles,
            build_relations_fn=self._build_relations,
            data=data,
            child_to_parent=child_to_parent,
            position_mapper=position_mapper,
        )

    def _extract_can_cu_relations_and_content(
        self,
        clause_type: str,
        clause_key: Optional[str],
        clause_mapped_content,
        law_titles: List,
        data: List[Dict],
        child_to_parent: Dict,
    ) -> Tuple[List[Dict], str, object]:
        """Stage 1: split ``vanban`` into can-cu block and operative remainder."""
        clause_content = clause_mapped_content.text
        if clause_type != "vanban":
            return [], clause_content, clause_mapped_content

        can_cu_section, remaining_content = extract_can_cu_section(clause_content)
        can_cu_mapped_content = clause_mapped_content.subcontent(can_cu_section)
        remaining_mapped_content = clause_mapped_content.subcontent(remaining_content or "")
        can_cu_relations = handle_cancu_relation(
            base_extractor=self.base_extractor,
            clause_type=clause_type,
            clause_key=clause_key,
            clause_content=can_cu_section,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=law_titles,
            build_relations_fn=self._build_relations,
            data=data,
            child_to_parent=child_to_parent,
            position_mapper=can_cu_mapped_content.raw_span,
        )
        return can_cu_relations, remaining_content or "", remaining_mapped_content

    def _extract_generic_relations(
        self,
        clause_type: str,
        clause_key: Optional[str],
        content: str,
        law_titles: List,
        cls_so_hieu: str,
        cls_title: str,
        cls_document_type: str = "",
        use_llm: bool = False,
        data: List[Dict] = None,
        child_to_parent: Dict = None,
        clause_index_by_key: Optional[Dict[str, Dict]] = None,
        position_mapper=None,
        rejected_buffer: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Extract generic relations from a clause.
        
        Args:
            clause_type: Type of the clause
            clause_key: Key of the clause
            content: Content of the clause
            law_titles: List of law titles
            cls_so_hieu: So hieu of the document
            cls_title: Title of the document
            cls_document_type: Document type name (e.g. "Luật", "Thông tư")
            use_llm: Whether to use LLM for relation extraction
            data: List of documents
            child_to_parent: Dictionary mapping child to parent
            clause_index_by_key: Dictionary mapping clause key to clause
        
        Returns:
            List of dictionaries with extracted relations
        """
        references = self.base_extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=law_titles,
            clause_type=clause_type,
            clause_key=clause_key,
            data=data,
            child_to_parent=child_to_parent,
            cls_title=cls_title,
            position_mapper=position_mapper,
        )
        # if not references:
        #     return []

        parent_content, grandparent_content = self._get_ancestor_clause_contents(
            child_to_parent=child_to_parent,
            clause_key=clause_key,
            clause_index_by_key=clause_index_by_key,
            data=data,
        )

        relation_types = []
        relation_matches = []
        needs_llm_fallback = False

        if references:
            relation_types = self.base_extractor.extract_relation_types(
                content=content,
                references=references,
                parent_content=parent_content,
                grandparent_content=grandparent_content,
                clause_type=clause_type,
                rejected_buffer=rejected_buffer,
            )
            # if not relation_types:
            #     return []   
            
            if relation_types:
                relation_matches = self.base_extractor.match_relations(
                    references=references,
                    relation_types=relation_types,
                    content=content,
                    source_so_hieu=cls_so_hieu,
                    source_title=cls_title,
                )
            elif use_llm:
                needs_llm_fallback = True

        # Use LLM fallback
        if use_llm and references and not needs_llm_fallback:
            needs_llm_fallback = self._evaluate_llm_trigger(
                relation_types=relation_types,
                relation_matches=relation_matches,
                references=references,
            )

        if needs_llm_fallback:
            try:
                from src.domain.llms.relation_fallback import LangExtractRelationFallback

                llm_fallback = LangExtractRelationFallback(logger=self.logger)

                # Build full hierarchical context so the LLM can resolve references that
                # span parent/grandparent clauses (e.g. document reference in parent heading).
                context_parts = [p for p in [grandparent_content, parent_content, content] if p and p.strip()]
                full_context = "\n".join(context_parts)

                llm_targets = llm_fallback.extract_relation_targets(
                    content=full_context,
                    clause_content=content,
                )

                if llm_targets:
                    for target in llm_targets:
                        ref = target.get("reference")
                        if ref:
                            relation_matches.append({
                                "relation_type": target.get("relation_type"),
                                "relation_position_start": target.get("position_start"),
                                "relation_position_end": target.get("position_end"),
                                "reference": ref
                            })
            except Exception as exc:
                if self.logger:
                    self.logger.warning(
                        "[LLM Fallback] Failed for clause %s, using rule-based only: %s",
                        clause_key or clause_type,
                        exc,
                    )

        # After the normal extraction pipeline, scan for internal references
        # like "khoản 2 Điều này", "Luật này" and resolve them to full citations.
        internal_dan_chieu_matches = self._resolve_internal_dan_chieu(
            content=content,
            clause_key=clause_key,
            child_to_parent=child_to_parent,
            data=data,
            cls_document_type=cls_document_type,
            cls_so_hieu=cls_so_hieu,
            clause_index_by_key=clause_index_by_key,
        )
        if internal_dan_chieu_matches:
            relation_matches.extend(
                self._filter_internal_dan_chieu_matches(
                    content=content,
                    matches=internal_dan_chieu_matches,
                )
            )
        relation_matches.extend(
            self._resolve_parent_appendix_source_dan_chieu(
                content=content,
                parent_content=parent_content,
                grandparent_content=grandparent_content,
                law_titles=law_titles,
            )
        )

        return self._build_relations(
            relation_matches=relation_matches,
            clause_type=clause_type,
            clause_key=clause_key,
        )

    def _evaluate_llm_trigger(
        self,
        relation_types: List[Dict],
        relation_matches: List[Dict],
        references: List[Dict],
    ) -> bool:
        """Return True when rule-based extraction is risky enough to ask the LLM."""
        detected_types = {
            relation_type.get("relation_type")
            for relation_type in relation_types or []
            if relation_type.get("relation_type")
        }
        has_eligible_type = bool(detected_types & self._LLM_ELIGIBLE_RELATION_TYPES)

        # C1: relation keyword exists but no target could be matched.
        if has_eligible_type and not relation_matches:
            return True

        # C3: too many references were left unmatched by the rule matcher.
        if has_eligible_type and relation_matches:
            if len(references or []) - len(relation_matches or []) >= 2:
                return True

        # C4a: "quy dinh chi tiet" and "huong dan" often co-fire in one sentence.
        if len(detected_types & {"quy_dinh_chi_tiet", "huong_dan"}) >= 2:
            return True

        # C4b: "dan_chieu" mixed with stronger action relations is ambiguous.
        if "dan_chieu" in detected_types and detected_types & self._MAJOR_RELATION_TYPES:
            return True

        # C5: clause-only target lacks a document component and needs context recovery.
        for match in relation_matches or []:
            reference = match.get("reference") or {}
            has_external_document = any(
                key not in SEARCHABLE_CLAUSE_TYPE_SET
                for key, value in reference.items()
                if isinstance(value, dict)
            )
            if not has_external_document:
                return True

        return False

    def _resolve_parent_appendix_source_dan_chieu(
        self,
        content: str,
        parent_content: Optional[str],
        grandparent_content: Optional[str],
        law_titles: List,
    ) -> List[Dict]:
        """Add the amended source document for child clauses issuing attached forms."""
        normalized_content = unidecode(content or "").lower()
        cue = self._PARENT_APPENDIX_SELF_SOURCE_CUE_PATTERN.search(normalized_content)
        if cue is None:
            return []

        for ancestor_content in (parent_content, grandparent_content):
            if not ancestor_content:
                continue
            normalized_ancestor = unidecode(ancestor_content or "").lower()
            if not self._PARENT_APPENDIX_SOURCE_CONTEXT_PATTERN.search(normalized_ancestor):
                continue

            ancestor_references = self.base_extractor.extract_references(
                content=ancestor_content,
                doc_types=self.doc_types,
                clause_types=self.clause_types,
                law_titles=law_titles,
            )
            for reference in ancestor_references:
                doc_reference = self.base_extractor._extract_document_reference_from_context(
                    reference
                )
                if doc_reference is None:
                    continue
                return [{
                    "relation_type": "dan_chieu",
                    "relation_position_start": cue.start(),
                    "relation_position_end": cue.end(),
                    "reference": doc_reference,
                }]

        return []

    @classmethod
    def _get_internal_match_span(cls, match: Dict) -> Tuple[int, int]:
        """Return the local content span covered by an internal match."""
        reference = match.get("reference") or {}
        positions = [
            (value.get("position_start", 0), value.get("position_end", 0))
            for value in reference.values()
            if isinstance(value, dict)
        ]
        if not positions:
            return (
                int(match.get("relation_position_start") or 0),
                int(match.get("relation_position_end") or 0),
            )
        return (
            min(start for start, _ in positions),
            max(end for _, end in positions),
        )

    @classmethod
    def _is_internal_dan_chieu_context(cls, content: str, match: Dict) -> bool:
        """Keep internal references only when a real dan_chieu cue introduces them."""
        start, end = cls._get_internal_match_span(match)
        prefix = content[max(0, start - 100):start]
        suffix = content[end:end + 80]
        reference = match.get("reference") or {}
        has_clause_scope = any(key in SEARCHABLE_CLAUSE_TYPE_SET for key in reference)
        action_prefix = content[max(0, start - 240):start]
        if (
            has_clause_scope
            and cls._INTERNAL_ACTION_EXCEPTION_PREFIX_PATTERN.search(prefix)
            and cls._INTERNAL_ACTION_EFFECT_CONTEXT_PATTERN.search(action_prefix)
        ):
            return False
        if (
            not has_clause_scope
            and re.search(r"\btrừ\s+trường\s+hợp\b", prefix, re.IGNORECASE)
            and re.search(
                r"theo\s+(?:các\s+)?quy\s+định\s+(?:tại|của|trong)\s*$",
                prefix,
                re.IGNORECASE,
            )
            is None
        ):
            return False
        if (
            not has_clause_scope
            and re.search(r"^\s*thì\s+áp\s+dụng\s+theo\b", suffix, re.IGNORECASE)
        ):
            return False
        if (
            not has_clause_scope
            and re.search(r"^\s*gồm\s*:", suffix, re.IGNORECASE)
        ):
            return False

        # "Điều X của [doc_type] này" — always a valid internal cross-reference
        # regardless of the prefix cue, because the "này" suffix is unambiguous.
        if _INTERNAL_DOC_CHUA_NAY_PATTERN.search(content[start:end]):
            return True

        normalized_prefix = unidecode(prefix or "").lower()
        if re.search(
            r"\bbang\b.{0,220}\b(?:phu\s+luc|danh\s+muc|mau|bieu\s+mau)\b"
            r".{0,160}\bkem\s+theo\s*$",
            normalized_prefix,
            re.IGNORECASE | re.DOTALL,
        ):
            return True
        # if (
        #     has_clause_scope
        #     and cls._INTERNAL_CLAUSE_DIRECT_CUE_PATTERN.search(prefix)
        # ):
        #     return True

        return cls._INTERNAL_DAN_CHIEU_ALLOWED_PREFIX_PATTERN.search(prefix) is not None

    @classmethod
    def _filter_internal_dan_chieu_matches(
        cls,
        content: str,
        matches: List[Dict],
    ) -> List[Dict]:
        """Drop internal self-references from effective-date/action text."""
        filtered: List[Dict] = []
        seen = set()

        for match in matches or []:
            if not cls._is_internal_dan_chieu_context(content, match):
                continue

            reference = match.get("reference") or {}
            dedup_key = (
                match.get("relation_type"),
                cls._build_reference_dedup_key(reference),
            )
            if dedup_key in seen:
                continue

            seen.add(dedup_key)
            filtered.append(match)

        whole_document_keys = {
            cls._build_reference_dedup_key(match.get("reference") or {})
            for match in filtered
            if not any(
                key in SEARCHABLE_CLAUSE_TYPE_SET
                for key in (match.get("reference") or {})
            )
        }
        if whole_document_keys:
            filtered = [
                match
                for match in filtered
                if not (
                    any(
                        key in SEARCHABLE_CLAUSE_TYPE_SET
                        for key in (match.get("reference") or {})
                    )
                    and cls._document_only_reference_key(match.get("reference") or {})
                    in whole_document_keys
                )
            ]

        return filtered

    @classmethod
    def _document_only_reference_key(cls, reference: Dict) -> tuple:
        dedup_parts: List[Tuple[str, str]] = []
        for key, value in sorted((reference or {}).items()):
            if not (
                isinstance(value, dict)
                and key not in SEARCHABLE_CLAUSE_TYPE_SET
                and value.get("information")
            ):
                continue
            info = value.get("information", "")
            if isinstance(info, str):
                info = " ".join(info.lower().split())
            dedup_parts.append((key, info))
        return tuple(dedup_parts)

    @staticmethod
    def _resolve_internal_dan_chieu(
        content: str,
        clause_key: Optional[str],
        child_to_parent: Optional[Dict],
        data: Optional[List[Dict]],
        cls_document_type: str,
        cls_so_hieu: str,
        clause_index_by_key: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Detect and resolve internal references ('Điều này', 'Luật này', etc.)
        as dan_chieu relation matches.

        This is called after the normal extraction pipeline to capture
        self-references that are intentionally filtered out by the standard
        reference extraction (since for most relation types, self-references
        should be ignored — dan_chieu is the exception).

        Args:
            content: Clause content text
            clause_key: com_key of the current clause
            child_to_parent: Hierarchy mapping
            data: Full cls_parsing data
            cls_document_type: Document type name (e.g. "Luật", "Thông tư")
            cls_so_hieu: Document number (e.g. "59/2024/QH15")

        Returns:
            List of relation match dicts compatible with _build_relations
        """
        if not content or not clause_key or child_to_parent is None or not data:
            return []
        if not cls_document_type or not cls_so_hieu:
            return []

        resolver = InternalReferenceResolver(
            clause_key=clause_key,
            child_to_parent=child_to_parent,
            data=data,
            cls_document_type=cls_document_type,
            cls_so_hieu=cls_so_hieu,
            clause_index_by_key=clause_index_by_key,
        )
        return resolver.resolve(content)

    @staticmethod
    def _merge_clause_relation_groups(
        clause_type: str,
        clause_key: Optional[str],
        can_cu_relations: List[Dict],
        generic_relations: List[Dict],
    ) -> List[Dict]:
        """Stage 5: merge special-case and generic relations into one clause payload."""
        if can_cu_relations and generic_relations:
            return [{
                "clause_type": clause_type,
                "clause_key": clause_key,
                "relations": (
                    can_cu_relations[0]["relations"]
                    + generic_relations[0]["relations"]
                ),
            }]

        return can_cu_relations or generic_relations
        
    @staticmethod
    def _has_external_document_reference(reference: Dict) -> bool:
        """Return True when a matched reference contains an external document node."""
        return any(key not in SEARCHABLE_CLAUSE_TYPE_SET for key in reference)

    @staticmethod
    def _build_reference_dedup_key(reference: Dict) -> Tuple[Tuple[str, str], ...]:
        """Build a stable dedup key for a matched reference payload, ignoring positions."""
        dedup_parts: List[Tuple[str, str]] = []
        for key in sorted(reference.keys()):
            value = reference.get(key)
            if not isinstance(value, dict):
                continue
            
            # Use only doc_type and information for deduplication
            info = value.get("information", "")
            if isinstance(info, str):
                # Basic normalization for comparison
                info = " ".join(info.lower().split())
                
            dedup_parts.append((key, info))
        return tuple(dedup_parts)

    def _build_relations(
        self,
        relation_matches: List[Dict],
        clause_type: Optional[str] = None,
        clause_key: Optional[str] = None
    ) -> List[Dict]:
        """
        Convert ``match_relations`` output into the grouped clause-level schema.

        Args:
            relation_matches: Matches returned by ``BaseExtractor.match_relations``.
            clause_type: Type of the source clause.
            clause_key: Unique key of the source clause.

        Returns:
            List containing one grouped clause entry, or an empty list when no
            valid document relationship is present.
        """
        if not clause_type:
            return []

        if clause_type != 'vanban' and not clause_key:
            return []

        relations: List[Dict] = []

        grouped_relations: Dict[str, List[Dict]] = {}
        # 1. Sort matches by relation priority to ensure strong relations (thay_the) are processed first
        sorted_matches = sorted(
            relation_matches or [],
            key=lambda m: self.base_extractor.RELATION_PRIORITY.get(m.get("relation_type"), 0),
            reverse=True
        )
        whole_document_dan_chieu_keys = set()
        for match in sorted_matches:
            if match.get("relation_type") != "dan_chieu":
                continue
            for exp_ref in expand_multiple_references([match.get("reference") or {}]):
                if (
                    self._has_external_document_reference(exp_ref)
                    and not any(key in SEARCHABLE_CLAUSE_TYPE_SET for key in exp_ref)
                ):
                    whole_document_dan_chieu_keys.add(
                        self._build_reference_dedup_key(exp_ref)
                    )

        candidates: List[Tuple[str, Dict, tuple]] = []
        relation_types_by_doc: Dict[tuple, Set[str]] = {}

        for match in sorted_matches:
            relation_type = match.get('relation_type')
            reference = match.get('reference')

            if not relation_type or not isinstance(reference, dict):
                continue
            
            # Expand multiple references (e.g., "khoản 1, 2 và 3" -> 3 separate references)
            expanded_refs = expand_multiple_references([reference])
            
            for exp_ref in expanded_refs:
                if not self._has_external_document_reference(exp_ref):
                    continue
                if (
                    relation_type == "dan_chieu"
                    and any(key in SEARCHABLE_CLAUSE_TYPE_SET for key in exp_ref)
                    and self._document_only_reference_key(exp_ref)
                    in whole_document_dan_chieu_keys
                ):
                    continue

                # Unique key for this document identity (ignoring position and relation_type)
                doc_identity_key = self._build_reference_dedup_key(exp_ref)
                candidates.append((relation_type, exp_ref, doc_identity_key))
                relation_types_by_doc.setdefault(doc_identity_key, set()).add(relation_type)

        dedup_seen: Set[Tuple[str, tuple]] = set()
        for relation_type, exp_ref, doc_identity_key in candidates:
            if self._is_conflicting_relation_for_document(
                relation_type=relation_type,
                relation_types_for_doc=relation_types_by_doc.get(doc_identity_key, set()),
            ):
                continue

            dedup_key = (relation_type, self._build_reference_dedup_key(exp_ref))
            if dedup_key in dedup_seen:
                continue
            dedup_seen.add(dedup_key)

            if relation_type not in grouped_relations:
                grouped_relations[relation_type] = []
            grouped_relations[relation_type].append(exp_ref)

        for relation_type, tails in grouped_relations.items():
            relations.append({
                'relation': relation_type,
                'tail': tails,
            })

        if not relations:
            return []

        return [{
            'clause_type': clause_type,
            'clause_key': clause_key,
            'relations': relations,
        }]

    @staticmethod
    def _is_conflicting_relation_for_document(
        relation_type: str,
        relation_types_for_doc: Set[str],
    ) -> bool:
        """Apply document-target conflict priority while allowing citations to coexist."""
        if relation_type in {"dan_chieu", "can_cu", "keo_dai_hieu_luc"}:
            return False
        if "sua_doi_bo_sung" in relation_types_for_doc:
            return relation_type in {"thay_the", "bai_bo", "huy_bo", "huong_dan", "quy_dinh_chi_tiet"}
        if "thay_the" in relation_types_for_doc:
            return relation_type in {"bai_bo", "huy_bo"}
        if "bai_bo" in relation_types_for_doc:
            return relation_type == "huy_bo"
        return False
