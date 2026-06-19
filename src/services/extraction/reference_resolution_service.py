from concurrent.futures import ThreadPoolExecutor, as_completed

from copy import deepcopy
import functools
import json
import re
import threading
from typing import Dict, FrozenSet, List
import os
from src.shared.text.normalizers import unidecode
from src.infrastructure.logging import get_logger

from src.domain.relation_constants import (
    SEARCHABLE_CLAUSE_TYPES,
    SEARCHABLE_CLAUSE_TYPE_SET,
    RELATION_COMPONENT_NAME_MAPPING,
    RELATION_COMPONENT_HIERARCHY,
    RELATION_COMPONENT_TYPES,
    RELATION_COMPONENT_PREFIX_PATTERNS
)
from src.search.search_reference_doc import search_reference_doc
from src.infrastructure.config import ConfigLoader
from src.utils.relation_utils import get_clause_relations, should_keep_failed_reference

logger = get_logger('PostProcessing')

# Markers in a Vietnamese legal document number that identify a locally-issued
# Identifies local-authority markers in a so_hieu type-code suffix.
# UBND (provincial committee) and HĐND (provincial assembly) appear in the
# type-code part of local document numbers (e.g. QĐ-UBND, NQ-HĐND) and signal
# that different provinces may reuse the same number — caching requires authority.
# Applied only to the suffix after the last '/' in a matched so_hieu, NOT to the
# full information string, to avoid false positives when a central document's
# reference text mentions these bodies in its title.
_LOCAL_AUTHORITY_RE = re.compile(r'\b(?:UBND|H[ĐD]ND)\b', re.IGNORECASE)

# Clause-component pattern keys in doc_number_patterns.yml that match clause
# identifiers (e.g. "a", "1") rather than document-level so_hieu strings.
# These must be excluded when building the document-number detection regex.
_CLAUSE_COMPONENT_TYPES = frozenset({'diem', 'khoan', 'dieu'})

# Matches Vietnamese issued-date markers.  Any of the following triggers
# date-based cache eligibility:
#   ngày DD/MM/YYYY or DD-MM-YYYY  — numeric compact form (slash or hyphen)
#   ngày DD tháng MM năm YYYY      — full written form; năm is required
#   năm YYYY                       — year alone is sufficient
# Requiring a keyword ("ngày" or "năm") prevents bare numeric sequences from
# accidentally qualifying.  "ngày DD tháng MM" without năm is intentionally
# excluded — day+month without a year is not specific enough to cache safely.
_DATE_IN_INFORMATION_RE = re.compile(
    r'\bngày\s+\d{1,2}[/-]\d{1,2}[/-]\d{4}\b'
    r'|\bngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}\b'
    r'|\bnăm\s+\d{4}\b',
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=1)
def _get_compiled_doc_number_pattern() -> re.Pattern:
    """Compile so_hieu patterns from doc_number_patterns.yml.

    Type-specific patterns (nghidinh, thongtu, congvan, etc.) are placed before
    the generic 'vanban' catch-all patterns in the alternation.  This ordering
    ensures that at any string position the specific pattern — which always
    produces a letter-containing match — is attempted first.  Without it the
    short catch-all (e.g. the vanban pattern) would shadow a longer, more
    specific match such as 45/2021/NĐ-CP by matching only 45/2021.
    Clause-component types (diem, khoan, dieu) are excluded throughout.
    Compiled once and cached for the process lifetime.
    """
    raw = ConfigLoader().doc_number_patterns_for_regex
    specific = [
        p
        for doc_type, patterns in raw.items()
        if doc_type not in _CLAUSE_COMPONENT_TYPES and doc_type != 'vanban'
        for p in patterns
    ]
    catchall = list(raw.get('vanban', []))
    return re.compile(
        '|'.join(f'(?:{p})' for p in specific + catchall),
        re.IGNORECASE,
    )


def is_persistent_es_cache_eligible(
    doc_info: Dict,
    source_authority: str,
    source_so_hieu: str = '',
) -> bool:
    """Return True if this reference may be stored in the shared persistent ES cache.

    Rules:
    - A so_hieu match must contain at least one letter (pure-digit YAML catch-all
      matches such as "30/4" are rejected as document numbers).
    - Title-only with no so_hieu and no issued-date keyword: never cached.
    - Title with a "ngày"/"năm" date marker: eligible (subject to authority check).
      Accepted forms: "ngày DD[/-]MM[/-]YYYY", "ngày DD tháng MM năm YYYY",
      "năm YYYY".
    - Central documents (so_hieu with no UBND/HĐND in the type-code suffix):
      always eligible.
    - Local documents (UBND or HĐND in the type-code suffix after the last '/'):
      eligible only when source_authority is non-empty.
    - Date-only references (no so_hieu): locality is inferred from the source
      document's cls_so_hieu type-code suffix.  If the source is a UBND/HĐND
      document (e.g. QĐ-UBND, NQ-HĐND), its date-only references are also
      considered local and require authority disambiguation.
    """
    information = (doc_info or {}).get('information') if doc_info else None
    if not information or not isinstance(information, str):
        return False

    # Collect all YAML matches that contain at least one letter.  finditer is used
    # so a digit-only catch-all hit earlier in the string does not hide a valid
    # letter-containing so_hieu that follows it.
    letter_matches = [
        m.group()
        for m in _get_compiled_doc_number_pattern().finditer(information)
        if any(c.isalpha() for c in m.group())
    ]
    has_doc_number = bool(letter_matches)
    has_date = bool(_DATE_IN_INFORMATION_RE.search(information))

    if not has_doc_number and not has_date:
        return False  # pure title-only — no discriminating identifier

    # Locality is always determined by the SOURCE document's cls_so_hieu type-code
    # suffix (the segment after the last '/').  The referenced document's own so_hieu
    # is not used: a UBND marker in the reference text may be subject matter, not a
    # type-code marker, and a central source referencing a provincial document does
    # not make that reference ambiguous across provinces.
    source_type_code = (source_so_hieu or '').rsplit('/', 1)[-1]
    is_local = bool(_LOCAL_AUTHORITY_RE.search(source_type_code))

    if is_local:
        return bool(source_authority and str(source_authority).strip())

    return True  # central document or unambiguous date-anchored reference


@functools.lru_cache(maxsize=1)
def _get_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 1) * 4))


@functools.lru_cache(maxsize=1)
def _get_law_titles_for_regex() -> list:
    return ConfigLoader().law_titles_for_regex


@functools.lru_cache(maxsize=1)
def _get_law_dataframe():
    return ConfigLoader().laws_dataframe


def _prepare_reference_for_mongo(reference_tail: Dict) -> Dict:
    """Return a Mongo-safe reference payload with raw inclusive offsets."""
    if not isinstance(reference_tail, dict):
        return reference_tail

    prepared = deepcopy(reference_tail)
    for key, value in prepared.items():
        if not isinstance(value, dict):
            continue

        raw_start = value.pop("_raw_position_start", None)
        raw_end = value.pop("_raw_position_end", None)
        for private_key in list(value.keys()):
            if private_key.startswith("_raw_"):
                value.pop(private_key, None)

        if key in SEARCHABLE_CLAUSE_TYPES:
            value["information"] = _post_processing_component_name(
                value.get("information", ""),
                key,
            )

        if raw_start is not None and raw_end is not None:
            value["position_start"] = int(raw_start)
            value["position_end"] = int(raw_end)
            continue

        start = value.get("position_start")
        end = value.get("position_end")
        if start is None or end is None:
            continue
        value["position_start"] = int(start)
        value["position_end"] = int(end) - 1 if int(end) >= 0 else int(end)

    return prepared




def post_process_relations(
    extracted_relations: List,
    doc_id: int,
    nam_ban_hanh: int,
    co_quan_ban_hanh: str,
    es_client,
    shared_cache: Dict = None,
    shared_cache_lock: threading.Lock = None,
    source_so_hieu: str = '',
):
    """
    Post-process the extracted relationships data.

    Args:
        extracted_relations: The extracted relationships data.
        doc_id: The ID of the document being processed.
        nam_ban_hanh: The year of issuance of the document.
        co_quan_ban_hanh: The issuing authority of the document (cls_co_quan_ban_hanh).
        es_client: Elasticsearch client instance.
        shared_cache: Optional cross-document cache (thread-safe dict keyed by
            "<doc_identity_json>::<year>::<authority>"). Shared across all docs in
            a batch to eliminate duplicate ES lookups.
        shared_cache_lock: Lock protecting shared_cache writes.
        source_so_hieu: The source document's so_hieu (cls_so_hieu), used to infer
            locality for date-only references.

    Returns:
        Tuple[List[Dict], List[Dict]]: (success_results, failed_results)
    """
    success_results = []
    failed_results = []
    cache = {}
    cache_lock = threading.Lock()

    # Pre-fetch all unique document references in parallel for efficiency
    all_refs = []
    for data in extracted_relations:
        all_refs.extend(get_clause_relations(data))

    unique_doc_to_search = {}
    for ref in all_refs:
        tail = ref.get('tail', {})
        if not isinstance(tail, dict) or not tail:
            continue

        # Find document type key
        doc_type_key = None
        for key in tail.keys():
            if key not in SEARCHABLE_CLAUSE_TYPES:
                doc_type_key = key
                break

        if not doc_type_key:
            continue

        # Create doc_identity without position information for consistent caching
        doc_raw = tail[doc_type_key]
        doc_identity = {
            'type': doc_type_key,
            'information': doc_raw.get('information', '')
        }

        try:
            cache_key = json.dumps(doc_identity, sort_keys=True, ensure_ascii=False)
        except Exception:
            cache_key = f"{doc_type_key}:{doc_identity['information']}"

        if cache_key not in cache:
            unique_doc_to_search[cache_key] = doc_identity

    if unique_doc_to_search:
        # Check shared cross-document cache before hitting Elasticsearch
        need_es_fetch: Dict = {}
        if shared_cache is not None and shared_cache_lock is not None:
            for c_key, d_info in unique_doc_to_search.items():
                if not is_persistent_es_cache_eligible(d_info, co_quan_ban_hanh, source_so_hieu):
                    need_es_fetch[c_key] = d_info
                    continue
                s_key = f"{c_key}::{nam_ban_hanh}::{co_quan_ban_hanh}"
                with shared_cache_lock:
                    if s_key in shared_cache:
                        cache[c_key] = shared_cache[s_key]
                    else:
                        need_es_fetch[c_key] = d_info
        else:
            need_es_fetch = unique_doc_to_search

        if need_es_fetch:
            logger.info(
                f"[PostProcessing] Document {doc_id} pre-fetching {len(need_es_fetch)}"
                f"/{len(unique_doc_to_search)} unique references (rest from cache)..."
            )
            search_futures = {
                _get_executor().submit(
                    search_reference_doc,
                    doc_info=d_info,
                    law_titles_for_regex=_get_law_titles_for_regex(),
                    law_dataframe=_get_law_dataframe(),
                    cls_nam_ban_hanh=nam_ban_hanh,
                    cls_co_quan_ban_hanh=co_quan_ban_hanh,
                    es_client=es_client
                ): c_key for c_key, d_info in need_es_fetch.items()
            }
            for future in as_completed(search_futures, timeout=60):
                c_key = search_futures[future]
                try:
                    result = future.result(timeout=5)
                except Exception as e:
                    logger.warning(f"[PostProcessing] Pre-fetch error for {c_key[:100]}: {e}")
                    result = (None, None)
                with cache_lock:
                    cache[c_key] = result
                # Populate shared cache so other documents skip this ES call,
                # but only for references that satisfy the cache eligibility policy.
                if shared_cache is not None and shared_cache_lock is not None:
                    d_info = need_es_fetch[c_key]
                    if is_persistent_es_cache_eligible(d_info, co_quan_ban_hanh, source_so_hieu):
                        s_key = f"{c_key}::{nam_ban_hanh}::{co_quan_ban_hanh}"
                        with shared_cache_lock:
                            shared_cache[s_key] = result

    for data in extracted_relations:
        clause_key = data.get('clause_key')
        clause_type = data.get('clause_type')
        reference_data = get_clause_relations(data)

        if not clause_type:
            continue

        # clause_key is allowed to be None for document-level relations (vanban)
        if clause_type != 'vanban' and not clause_key:
            continue

        if not reference_data:
            continue

        success = []
        failed = []

        # Split references into cache-hits (process inline) and ES-bound (dispatch to executor).
        # Avoiding thread pool overhead for cache hits is a significant speedup when
        # most references were resolved in the pre-fetch phase above.
        inline_refs = []   # (original_idx, ref) — cache hit, no network needed
        remote_refs = []   # (original_idx, ref) — must hit ES

        for idx, ref in enumerate(reference_data):
            tail = ref.get('tail', {}) if isinstance(ref, dict) else {}
            doc_type_key = next(
                (k for k in tail if k not in SEARCHABLE_CLAUSE_TYPES), None
            ) if isinstance(tail, dict) else None
            if doc_type_key:
                doc_raw = tail[doc_type_key]
                doc_identity = {
                    'type': doc_type_key,
                    'information': doc_raw.get('information', ''),
                }
                try:
                    ck = json.dumps(doc_identity, sort_keys=True, ensure_ascii=False)
                except Exception:
                    ck = f"{doc_type_key}:{doc_identity['information']}"
                if ck in cache:
                    inline_refs.append((idx, ref))
                    continue
            remote_refs.append((idx, ref))

        results_all = [None] * len(reference_data)

        # Process cache-hit references inline (no executor overhead)
        for idx, ref in inline_refs:
            try:
                results_all[idx] = _process_single_reference(
                    ref, doc_id, nam_ban_hanh, co_quan_ban_hanh, clause_key, cache, cache_lock, es_client
                )
            except Exception as e:
                logger.warning(f"[PostProcessing] Inline processing error for {doc_id}/{clause_key}: {e}")
                failed_tail = ref.get('tail') if isinstance(ref, dict) else None
                results_all[idx] = (None, _prepare_reference_for_mongo(failed_tail))

        # Dispatch ES-bound references to thread pool
        if remote_refs:
            future_to_orig_idx = {}
            for orig_idx, ref in remote_refs:
                future = _get_executor().submit(
                    _process_single_reference,
                    ref, doc_id, nam_ban_hanh, co_quan_ban_hanh, clause_key, cache, cache_lock, es_client
                )
                future_to_orig_idx[future] = orig_idx

            for future in as_completed(future_to_orig_idx, timeout=60):
                orig_idx = future_to_orig_idx[future]
                try:
                    results_all[orig_idx] = future.result(timeout=5)
                except Exception as e:
                    logger.warning(f"[PostProcessing] Parallel processing error for {doc_id}/{clause_key}: {e}")
                    ref = reference_data[orig_idx]
                    failed_tail = ref.get('tail') if isinstance(ref, dict) else None
                    results_all[orig_idx] = (None, _prepare_reference_for_mongo(failed_tail))

        for result in results_all:
            if result is None:
                continue
            success_status, failed_status = result
            if success_status:
                success.extend(success_status)
            if failed_status:
                failed.append(failed_status)

        if success:
            success = _filter_conflicting_relations(success)
            success_results.append({
                "source_key": clause_key,
                "source_type": clause_type,
                "success": success
            })

        if failed:
            failed_results.append({
                "source_key": clause_key,
                "source_type": clause_type,
                "failed": failed
            })

    logger.info(f"[PostProcessing] Document {doc_id} FINAL: {len(success_results)} success groups, {len(failed_results)} failed groups")
    return success_results, failed_results


# Priority order for mutually-exclusive action relations to the same target document.
# A relation earlier in the list (lower index = higher priority) blocks any relation
# that appears later in the list from co-existing for the same (source, target_doc_id) pair.
# Clause-level bo_sung is folded into the sua_doi_bo_sung bucket because at the
# document level the inferred relation is always sua_doi_bo_sung.
_CONFLICT_RELATION_PRIORITY: List[frozenset] = [
    frozenset({"sua_doi_bo_sung", "sua_doi", "bo_sung"}),  # highest priority
    frozenset({"thay_the"}),
    frozenset({"bai_bo"}),
    frozenset({"huy_bo"}),                                  # lowest priority
]


def _conflict_priority(relationship: str) -> int:
    """Return the conflict-group index for a relation type (-1 = not in any group)."""
    for idx, group in enumerate(_CONFLICT_RELATION_PRIORITY):
        if relationship in group:
            return idx
    return -1


def _filter_conflicting_relations(success: List[Dict]) -> List[Dict]:
    """Enforce the rule: at most one 'action' relation group per (source, target_doc_id).

    Rules (per target document):
    - If sua_doi / bo_sung / sua_doi_bo_sung exists → remove thay_the, bai_bo, huy_bo
    - Elif thay_the exists → remove bai_bo, huy_bo
    - Elif bai_bo exists → remove huy_bo
    dan_chieu and other non-action relations are untouched.

    This operates on the flat success list for one source clause.
    """
    # Group by target_doc_id to detect conflicts
    # target_doc_id may be None when the reference was not resolved; skip those.
    by_target: Dict[int, List[Dict]] = {}
    for item in success:
        tid = item.get("target_doc_id")
        if tid is None:
            continue
        by_target.setdefault(int(tid), []).append(item)

    if not any(len(v) > 1 for v in by_target.values()):
        return success  # fast path: no target has multiple entries

    remove_set: set = set()
    for target_doc_id, items in by_target.items():
        rels_present = {item.get("relationship") for item in items}
        # Find the highest-priority conflict group that has at least one match
        best_priority = min(
            (_conflict_priority(r) for r in rels_present if _conflict_priority(r) >= 0),
            default=-1,
        )
        if best_priority < 0:
            continue  # no conflicting action relations for this target
        for item in items:
            rel = item.get("relationship")
            p = _conflict_priority(rel)
            if p > best_priority:
                remove_set.add(id(item))

    if not remove_set:
        return success
    return [item for item in success if id(item) not in remove_set]


# ---------------------------------------------------------------------------
# Reference hierarchy validation
# ---------------------------------------------------------------------------

_VALID_CLAUSE_KEY_PATTERNS: FrozenSet[FrozenSet[str]] = frozenset({
    frozenset(),                           # Văn bản only
    frozenset({"dieu"}),                   # Điều + Văn bản
    frozenset({"diem", "dieu"}),           # điểm + Điều + Văn bản (special case)
    frozenset({"khoan", "dieu"}),          # khoản + Điều + Văn bản
    frozenset({"diem", "khoan", "dieu"}),  # điểm + khoản + Điều + Văn bản
})


def _get_clause_key_set(reference_tail: Dict) -> FrozenSet[str]:
    """Return the set of clause-type keys present in a reference tail."""
    return frozenset(k for k in reference_tail if k in SEARCHABLE_CLAUSE_TYPE_SET)


def _is_valid_reference_hierarchy(clause_key_set: FrozenSet[str]) -> bool:
    """Return True when the clause keys form a valid legal hierarchy."""
    return clause_key_set in _VALID_CLAUSE_KEY_PATTERNS


def _process_single_reference(
    ref: Dict,
    doc_id: int,
    nam_ban_hanh: int,
    co_quan_ban_hanh: str,
    clause_key: str,
    cache: Dict,
    cache_lock: threading.Lock,
    es_client
):
    """
    Process a single reference to determine if it can be successfully matched.

    Args:
        ref (Dict): The reference data.
        doc_id (int): The ID of the document being processed.
        nam_ban_hanh (int): The year of issuance of the document.
        co_quan_ban_hanh (str): The issuing authority of the document.
        clause_key (str): The key of the clause being processed.
        cache (Dict): Cache of document information to avoid redundant searches.
        es_client: Elasticsearch client instance (required for non-law document types).

    Returns:
        Tuple[List[Dict], List[Dict]]: A tuple containing:
            - A list of successfully processed reference data.
            - A list of failed reference data.
    """
    if not isinstance(ref, dict):
        return None, None

    relation = ref.get('relation')
    reference_tail = ref.get('tail', {})

    if not relation or not isinstance(reference_tail, dict) or not reference_tail:
        return None, None

    # Find document type key (not a clause type)
    doc_type_key = None
    for key in reference_tail.keys():
        if key not in SEARCHABLE_CLAUSE_TYPES:
            doc_type_key = key
            break

    if not doc_type_key:
        logger.warning(f"[SingleReferenceProcessing] Document {doc_id} - {clause_key} - No document type found in tail: {list(reference_tail.keys())}")
        return None, None

    # Discard references whose clause hierarchy is incomplete (e.g. khoản/điểm without Điều).
    clause_key_set = _get_clause_key_set(reference_tail)
    if not _is_valid_reference_hierarchy(clause_key_set):
        logger.debug(
            f"[HierarchyValidation] Document {doc_id} - {clause_key}: "
            f"invalid hierarchy {sorted(clause_key_set)}, discarded."
        )
        return None, None

    try:
        doc_raw = reference_tail[doc_type_key]
        doc_identity = {
            'type': doc_type_key,
            'information': doc_raw.get('information', '')
        }

        reference_ids = None
        cache_key = None
        extracted_information = None
        cache_hit = False

        if cache is not None:
            # Create cache key excluding position information for consistent hits
            try:
                cache_key = json.dumps(doc_identity, sort_keys=True, ensure_ascii=False)
            except Exception:
                cache_key = f"{doc_type_key}:{doc_identity['information']}"

            # Return cached result if exists (thread-safe read)
            # Use cache_lock to prevent race condition
            with cache_lock:
                if cache_key in cache:
                    reference_ids, extracted_information = cache[cache_key]
                    cache_hit = True

        # Search if no cached result (either cache is None or key not found)
        if not cache_hit:
            reference_ids, extracted_information = search_reference_doc(
                doc_info=doc_identity,
                law_titles_for_regex=_get_law_titles_for_regex(),
                law_dataframe=_get_law_dataframe(),
                cls_nam_ban_hanh=nam_ban_hanh,
                cls_co_quan_ban_hanh=co_quan_ban_hanh,
                es_client=es_client
            )
            # Update cache if it exists (thread-safe write)
            if cache is not None and cache_key:
                with cache_lock:
                    cache[cache_key] = (reference_ids, extracted_information)

        # Final check if we have results
        if reference_ids is None or (isinstance(reference_ids, list) and len(reference_ids) == 0):
            logger.warning(f"[SingleReferenceProcessing] Document {doc_id} - {clause_key} not found for relationship '{relation}' with reference: {doc_identity['information']}")
            if should_keep_failed_reference(reference_tail):
                return None, _prepare_reference_for_mongo(reference_tail)
            return None, None

        # Overwrite information with normalized extracted value (so_hieu or tieu_de)
        if extracted_information:
            reference_tail[doc_type_key]['information'] = extracted_information

        # Extract information for clause_key (exclude document type, keep only clause components)
        res_for_key = {k: v['information'] for k, v in reference_tail.items() if k != doc_type_key}
        try:
            processed_clause_key = _create_clause_key_reference(res_for_key) if res_for_key else None
        except Exception as e:
            logger.warning(f"[SingleReferenceProcessing] Document {doc_id} - {clause_key} could not create clause_key from data {res_for_key}: {e}")
            processed_clause_key = None

        # Handle both list and single ID cases
        results = []
        if isinstance(reference_ids, list):
            first_valid_appended = False
            for ref_doc_id in reference_ids:
                if ref_doc_id is None:
                    continue

                # Filter out self-references for relations other than 'dan_chieu'
                if int(ref_doc_id) == int(doc_id) and relation != "dan_chieu":
                    continue

                # Assign clause_key only to the first matched document if there are multiple
                paired_clause_key = processed_clause_key if (not first_valid_appended or processed_clause_key is None) else None
                first_valid_appended = True

                results.append({
                    "relationship": relation,
                    "target_doc_id": int(ref_doc_id),
                    "target_key": paired_clause_key,
                    "target_value": _prepare_reference_for_mongo(reference_tail)
                })
        else:
            # Filter out self-references for relations other than 'dan_chieu'
            if int(reference_ids) == int(doc_id) and relation != "dan_chieu":
                return None, None

            results.append({
                "relationship": relation,
                "target_doc_id": int(reference_ids),
                "target_key": processed_clause_key,
                "target_value": _prepare_reference_for_mongo(reference_tail)
            })

        return results, None

    except Exception:
        if should_keep_failed_reference(reference_tail):
            return None, _prepare_reference_for_mongo(reference_tail)
        return None, None


def _create_clause_key_reference(res_for_key: Dict) -> str:
    """
    Create a unique clause key reference string based on the extracted components.
    Uses RELATION_COMPONENT_HIERARCHY for ordering and RELATION_COMPONENT_NAME_MAPPING
    for naming components from relation_constants.
    """
    if not res_for_key:
        return None

    # Sort by hierarchy depth (most specific first)
    # We find the 'primary' component (e.g., 'diem' if 'diem', 'khoan', 'dieu' are all present)
    primary_component = None
    for priority_type in RELATION_COMPONENT_TYPES:
        if priority_type in res_for_key:
            primary_component = priority_type
            break

    if not primary_component or primary_component not in RELATION_COMPONENT_HIERARCHY:
        return None

    key_components_list = RELATION_COMPONENT_HIERARCHY[primary_component]
    component_key_parts = []

    for com_key in key_components_list:
        if com_key in res_for_key:
            standardized_part = _post_processing_component_name(
                component_value=res_for_key[com_key],
                component_type=com_key
            )
            if standardized_part:
                prefix = RELATION_COMPONENT_NAME_MAPPING.get(com_key, com_key)
                component_key_parts.append(f"{prefix}_{standardized_part}")

    return "_".join(component_key_parts) if component_key_parts else None


def _post_processing_component_name(component_value: str, component_type: str):
    """
    Post-process component value to create a standardized component name (identifier only).
    Example: "điểm g" -> "g", "khoản 2" -> "2", "Điều 42" -> "42"
    """
    if not component_value:
        return ""

    component_value = str(component_value).strip()

    # 1. Remove the type prefix if it exists
    if component_type in RELATION_COMPONENT_PREFIX_PATTERNS:
        pattern = RELATION_COMPONENT_PREFIX_PATTERNS[component_type]
        component_value = re.sub(pattern, '', component_value, flags=re.IGNORECASE)

    # 2. Handle special case for vanban (slugify)
    if component_type == 'vanban':
        component_value = re.sub(r"[ \-/]", "_", unidecode(component_value))

    if component_type == 'diem':
        component_value = re.sub(r"(?<=\w)\.(?=\d+\b)", "", component_value)
        d_stroke_marker = "DSTROKEMARKER"
        component_value = re.sub(r"[Đđ]", d_stroke_marker, component_value)
        component_value = unidecode(component_value).replace(d_stroke_marker, "đ")
        component_value = component_value.lower()
    else:
        # Remove remaining diacritics for keys and keep legacy ASCII keys for
        # non-point components such as dieu/khoan/vanban.
        component_value = unidecode(component_value)
    component_value = re.sub(r"[^\w\d]", " ", component_value).strip()
    component_key = re.sub(r"\s+", " ", component_value)

    return component_key
