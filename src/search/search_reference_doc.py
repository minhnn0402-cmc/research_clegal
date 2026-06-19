import re
import weakref
import pandas as pd 
from typing import Dict, List
from src.shared.extraction.components_extractor import extract_document_components
from src.shared.validation.filters import (
    _extract_amendment_base_title,
    filter_law_dataframe as filter_law_df,
    remove_accents,
)
from src.search.search_reference_in_es import search_reference_in_es, _fold_so_hieu, _normalize_so_hieu
from src.infrastructure.logging import get_logger


logger = get_logger("SearchReferenceDoc")

# Keyed on id(law_df), with object identity validation to avoid stale hits if
# Python later reuses an id for a different temporary dataframe.
_law_title_abbrev_map_cache: dict[int, tuple[weakref.ReferenceType, dict[str, str | None]]] = {}

_LUAT_BOLUAT_PREFIXES: dict[str, tuple[str, str]] = {
    # loai_van_ban_key: (tieu_de_prefix_lowercase, accent_stripped_key_prefix)
    "luat": ("luật ", "luat"),
    "boluat": ("bộ luật ", "bo luat"),
}


def build_law_title_abbreviation_map(law_df: pd.DataFrame) -> dict[str, str | None]:
    """
    Build an abbreviation lookup map from law_docs.csv Luật/Bộ luật entries.

    Key format: "{accent_stripped_prefix} {abbreviation}".lower()
    e.g., "luat tthc" → "luật tố tụng hành chính"

    When multiple titles produce the same key the value is None (ambiguous —
    the caller must not auto-resolve).
    """
    df_id = id(law_df)
    cached = _law_title_abbrev_map_cache.get(df_id)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and cached[0]() is law_df
    ):
        return cached[1]
    if cached is not None:
        _law_title_abbrev_map_cache.pop(df_id, None)

    abbrev_candidates: dict[str, list[str]] = {}

    for _, row in law_df.iterrows():
        loai_van_ban = str(row.get("loai_van_ban", "") or "").strip().lower()
        tieu_de = str(row.get("tieu_de", "") or "").strip()

        if loai_van_ban not in _LUAT_BOLUAT_PREFIXES:
            continue

        tieu_de_prefix, key_prefix = _LUAT_BOLUAT_PREFIXES[loai_van_ban]
        tieu_de_lower = tieu_de.lower()

        if not tieu_de_lower.startswith(tieu_de_prefix):
            continue

        significant = tieu_de_lower[len(tieu_de_prefix):].strip()
        if not significant:
            continue

        words = remove_accents(significant).lower().split()
        if not words:
            continue

        abbreviation = "".join(w[0] for w in words if w).upper()
        if len(abbreviation) < 2:
            continue

        key = f"{key_prefix} {abbreviation.lower()}"
        if key not in abbrev_candidates:
            abbrev_candidates[key] = []
        if tieu_de_lower not in abbrev_candidates[key]:
            abbrev_candidates[key].append(tieu_de_lower)

    result: dict[str, str | None] = {
        key: (titles[0] if len(titles) == 1 else None)
        for key, titles in abbrev_candidates.items()
    }
    _law_title_abbrev_map_cache[df_id] = (weakref.ref(law_df), result)
    return result


def normalize_law_title_abbreviation(tieu_de: str, law_df: pd.DataFrame) -> str:
    """
    Normalize an abbreviated Luật/Bộ luật title to its full official form.

    e.g. "luật tthc" → "luật tố tụng hành chính"

    Ambiguous abbreviations (multiple official titles) are never auto-resolved;
    the original tieu_de is returned unchanged.
    """
    if not tieu_de:
        return tieu_de

    stripped = re.sub(r"\s+", " ", remove_accents(tieu_de.lower().strip()))
    abbrev_map = build_law_title_abbreviation_map(law_df)

    # Exact match
    if stripped in abbrev_map:
        mapped = abbrev_map[stripped]
        if mapped is not None:
            return mapped

    # Prefix match: _fallback_law_title can capture trailing clause context
    # (e.g. "luật tthc để mở phiên tòa..." or "luật tthc, viện kiểm sát...").
    # Accept any non-alphanumeric boundary after the key (space, comma, colon, etc.).
    for key, full_title in abbrev_map.items():
        if (
            full_title is not None
            and stripped.startswith(key)
            and len(stripped) > len(key)
            and not stripped[len(key)].isalnum()
        ):
            return full_title

    return tieu_de


def _expand_common_title_abbreviations(value: str) -> str:
    expanded = str(value or "")
    replacements = [
        (r"\bhđnd\b|\bhdnd\b", "hội đồng nhân dân"),
        (r"\bubnd\b", "ủy ban nhân dân"),
    ]
    for pattern, replacement in replacements:
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    return expanded


def _normalize_title_tokens(value: str) -> set[str]:
    normalized = remove_accents(_expand_common_title_abbreviations(value).lower())
    normalized = re.sub(r"\b\d{1,5}/\d{4}/[a-z0-9-]+\b", " ", normalized)
    normalized = re.sub(r"\b\d{1,5}\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = set(re.sub(r"\s+", " ", normalized).strip().split())
    return tokens - {"so", "moi", "nhat", "nam"}


def _hit_date_matches(hit_date: str | None, ngay: int | None, thang: int | None, nam: int | None) -> bool:
    if not hit_date or nam is None:
        return False
    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", str(hit_date))
    if not match:
        return False
    hit_year = int(match.group(1))
    hit_month = int(match.group(2)) if match.group(2) else None
    hit_day = int(match.group(3)) if match.group(3) else None
    if hit_year != int(nam):
        return False
    if thang is not None and hit_month != int(thang):
        return False
    if ngay is not None and hit_day != int(ngay):
        return False
    return True


def _is_placeholder_so_hieu(value: str | None) -> bool:
    normalized = remove_accents(str(value or "").lower())
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return normalized in {"", "khong so"}


def _select_single_law_hit(hits: list[dict]) -> dict | None:
    if len(hits) == 1:
        return hits[0]

    numbered_hits = [
        hit
        for hit in hits
        if not _is_placeholder_so_hieu(hit.get("_source", {}).get("so_hieu"))
    ]
    if len(numbered_hits) == 1:
        return numbered_hits[0]
    return None


def _law_so_hieu_variants(so_hieu: str) -> list[str]:
    raw = str(so_hieu or "").strip()
    folded_raw = _fold_so_hieu(raw)
    preferred_order = [
        raw,
        raw.upper(),
        raw.lower(),
        folded_raw,
        folded_raw.upper(),
        folded_raw.lower(),
    ]

    variants = []
    for value in preferred_order:
        if value and value not in variants:
            variants.append(value)
    return variants


def _law_type_query_clause(loai_van_ban: str) -> dict:
    normalized = remove_accents(str(loai_van_ban or "").lower()).strip()
    if normalized in {"luat", "bo luat"}:
        values = ["Luật", "Bộ luật"]
    else:
        values = [loai_van_ban]
    return {
        "bool": {
            "should": [
                {"term": {"loai_van_ban.keyword": value}}
                for value in values
                if value
            ],
            "minimum_should_match": 1,
        }
    }


def _title_is_compatible_with_hit(tieu_de: str, hit_title: str | None) -> bool:
    if not tieu_de:
        return True

    query_tokens = _normalize_title_tokens(tieu_de)
    if not query_tokens:
        return True

    hit_tokens = _normalize_title_tokens(hit_title or "")
    if not hit_tokens:
        return False
    if _title_tokens_are_compatible(query_tokens, hit_tokens):
        return True

    base_title = _extract_amendment_base_title(tieu_de)
    if base_title:
        base_tokens = _normalize_title_tokens(base_title)
        return bool(base_tokens and _title_tokens_are_compatible(base_tokens, hit_tokens))

    return False


def _title_tokens_are_compatible(query_tokens: set[str], hit_tokens: set[str]) -> bool:
    if query_tokens <= hit_tokens:
        return True

    overlap = query_tokens & hit_tokens
    min_overlap = min(3, len(query_tokens))
    if len(overlap) < min_overlap:
        return False
    return len(overlap) / len(query_tokens) >= 0.75


def _build_law_number_query_body(
    so_hieu: str,
    loai_van_ban: str,
) -> dict:
    """Build the ES query body for searching a law by so_hieu (number)."""
    term_entries = []
    boosts = [12, 9, 7, 6, 5]
    for index, variant in enumerate(_law_so_hieu_variants(so_hieu)):
        boost_val = boosts[index] if index < len(boosts) else 2
        term_entries.append(
            {"term": {"so_hieu.keyword": {"value": variant, "boost": boost_val}}}
        )
    term_entries.append(
        {"match": {"so_hieu": {"query": so_hieu, "operator": "and", "boost": 1.0}}}
    )

    must_clauses = [
        {
            "bool": {
                "should": term_entries,
                "minimum_should_match": 1,
            }
        }
    ]
    if loai_van_ban:
        must_clauses.append(_law_type_query_clause(loai_van_ban))

    return {
        "_source": ["ID", "so_hieu", "loai_van_ban", "title", "ngay_ban_hanh"],
        "size": 10,
        "query": {"bool": {"must": must_clauses}},
        "sort": [
            {"_score": {"order": "desc"}},
            {"ngay_ban_hanh": {"order": "desc"}},
        ],
    }


def _process_law_number_hits(
    hits: list,
    so_hieu: str,
    tieu_de: str,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
) -> int | str | None:
    """Post-process ES hits from a law-number query into a single ID (or None)."""
    if not hits:
        return None

    query_so_hieu = _normalize_so_hieu(so_hieu)
    exact_hits = [
        hit
        for hit in hits
        if _normalize_so_hieu(hit.get("_source", {}).get("so_hieu")) == query_so_hieu
    ]
    if not exact_hits:
        return None

    compatible_hits = [
        hit
        for hit in exact_hits
        if _title_is_compatible_with_hit(tieu_de, hit.get("_source", {}).get("title"))
    ]
    if not compatible_hits:
        return None

    if nam is not None:
        date_hits = [
            hit
            for hit in compatible_hits
            if _hit_date_matches(hit.get("_source", {}).get("ngay_ban_hanh"), ngay, thang, nam)
        ]
        selected_hit = _select_single_law_hit(date_hits)
        if selected_hit:
            return selected_hit.get("_source", {}).get("ID")
        if date_hits:
            return None

    if len(compatible_hits) == 1:
        return compatible_hits[0].get("_source", {}).get("ID")
    return None


def _search_law_number_in_es(
    so_hieu: str,
    tieu_de: str,
    loai_van_ban: str,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
    es_client,
) -> int | str | None:
    if not so_hieu or es_client is None:
        return None

    query = _build_law_number_query_body(so_hieu, loai_van_ban)

    try:
        response = es_client.search(index="law_documents_t4", body=query)
    except Exception as exc:
        logger.error(f"Elasticsearch law number fallback query error: {str(exc)}")
        return None

    return _process_law_number_hits(
        response.get("hits", {}).get("hits", []),
        so_hieu,
        tieu_de,
        ngay,
        thang,
        nam,
    )


def _build_law_title_query_body(
    tieu_de: str,
    loai_van_ban: str,
    nam: int | None,
) -> dict:
    """Build the ES query body for searching a law by title."""
    lookup_tieu_de = _expand_common_title_abbreviations(tieu_de)
    has_explicit_date = nam is not None
    title_operator = "or" if has_explicit_date else "and"
    return {
        "_source": ["ID", "so_hieu", "loai_van_ban", "title", "ngay_ban_hanh"],
        "size": 50 if has_explicit_date else 10,
        "query": {
            "bool": {
                "must": [
                    {"match": {"title": {"query": lookup_tieu_de, "operator": title_operator}}},
                    _law_type_query_clause(loai_van_ban),
                ]
            }
        },
        "sort": [
            {"_score": {"order": "desc"}},
            {"ngay_ban_hanh": {"order": "desc"}},
        ],
    }


def _process_law_title_hits(
    hits: list,
    tieu_de: str,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
) -> int | str | None:
    """Post-process ES hits from a law-title query into a single ID (or None)."""
    if not hits:
        return None

    lookup_tieu_de = _expand_common_title_abbreviations(tieu_de)
    query_tokens = _normalize_title_tokens(lookup_tieu_de)
    title_hits = [
        hit
        for hit in hits
        if query_tokens
        and _title_is_compatible_with_hit(lookup_tieu_de, hit.get("_source", {}).get("title", ""))
    ]
    if not title_hits:
        return None
    hits = title_hits

    if nam is not None:
        date_hits = [
            hit for hit in hits
            if _hit_date_matches(hit.get("_source", {}).get("ngay_ban_hanh"), ngay, thang, nam)
        ]
        selected_hit = _select_single_law_hit(date_hits)
        if selected_hit:
            return selected_hit.get("_source", {}).get("ID")
        if date_hits:
            return None

    if len(hits) == 1:
        return hits[0].get("_source", {}).get("ID")
    return None


def _search_law_title_in_es(
    tieu_de: str,
    loai_van_ban: str,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
    es_client,
) -> int | str | None:
    if not tieu_de or es_client is None:
        return None

    query = _build_law_title_query_body(tieu_de, loai_van_ban, nam)

    try:
        response = es_client.search(index="law_documents_t4", body=query)
    except Exception as exc:
        logger.error(f"Elasticsearch title fallback query error: {str(exc)}")
        return None

    return _process_law_title_hits(
        response.get("hits", {}).get("hits", []),
        tieu_de,
        ngay,
        thang,
        nam,
    )


def _search_law_combined_msearch(
    so_hieu: str,
    tieu_de: str,
    loai_van_ban: str,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
    es_client,
) -> int | str | None:
    """Issue law-by-number AND law-by-title queries in a single ES _msearch call.

    Falls back gracefully:
    - If so_hieu is empty, runs only the title query.
    - If tieu_de is empty, runs only the number query.
    - On any error, returns None (caller treats as "not found").

    Replaces the previous sequential pattern:
      _search_law_number_in_es → if found return; else _search_law_title_in_es
    with a single network round-trip that fetches both result sets at once.
    Saves one VPN round-trip per call.
    """
    if es_client is None:
        return None

    # Fallback for test mocks / minimal clients that only implement `.search`.
    if not hasattr(es_client, "msearch"):
        if so_hieu:
            result = _search_law_number_in_es(
                so_hieu, tieu_de, loai_van_ban, ngay, thang, nam, es_client
            )
            if result is not None:
                return result
        if tieu_de:
            return _search_law_title_in_es(
                tieu_de, loai_van_ban, ngay, thang, nam, es_client
            )
        return None

    bodies: list = []
    kinds: list = []  # parallel list: which result post-processor to use

    if so_hieu:
        bodies.append({"index": "law_documents_t4"})
        bodies.append(_build_law_number_query_body(so_hieu, loai_van_ban))
        kinds.append("number")

    if tieu_de:
        bodies.append({"index": "law_documents_t4"})
        bodies.append(_build_law_title_query_body(tieu_de, loai_van_ban, nam))
        kinds.append("title")

    if not bodies:
        return None

    try:
        response = es_client.msearch(body=bodies)
    except (AttributeError, TypeError):
        if so_hieu:
            result = _search_law_number_in_es(
                so_hieu, tieu_de, loai_van_ban, ngay, thang, nam, es_client
            )
            if result is not None:
                return result
        if tieu_de:
            return _search_law_title_in_es(
                tieu_de, loai_van_ban, ngay, thang, nam, es_client
            )
        return None
    except Exception as exc:
        logger.error(f"Elasticsearch msearch (combined law) error: {str(exc)}")
        return None

    responses = response.get("responses", []) if response is not None else []
    if not responses:
        return None

    # Process number first (matches previous sequential preference)
    for kind, resp in zip(kinds, responses):
        if resp is None:
            continue
        hits = resp.get("hits", {}).get("hits", [])
        if kind == "number":
            result = _process_law_number_hits(hits, so_hieu, tieu_de, ngay, thang, nam)
        else:
            result = _process_law_title_hits(hits, tieu_de, ngay, thang, nam)
        if result is not None:
            return result

    return None


def search_reference_doc(doc_info: Dict, law_titles_for_regex: List, law_dataframe: pd.DataFrame,
                        cls_nam_ban_hanh: int, cls_co_quan_ban_hanh: str, es_client) -> tuple: 
    """
    Search for a reference document based on extracted document information.
    
    Args:
        doc_info: Document reference info dict with 'information', 'type', etc. 
                  e.g., {'information': 'Nghị định số 45/2021/NĐ-CP...', 'type': 'nghidinh', ...}
        law_titles_for_regex: List of law titles for regex matching
        law_dataframe: DataFrame containing law documents
        cls_nam_ban_hanh: Year of issuance of current document
        cls_co_quan_ban_hanh: Issuing authority of current document
        es_client: Elasticsearch client instance (required for non-law document types)
        
    Returns:
        Document ID if found, None otherwise
    """
    doc_text = doc_info.get('information', '')
    doc_type = doc_info.get('type', '')
    
    if not doc_text or not doc_type:
        return None, None

    components_regex_result = extract_document_components(
        vanban_text=doc_text,
        keyword_type=doc_type,
        law_titles_for_regex=law_titles_for_regex
    )

    if not components_regex_result:
        return None, None
    
    # Extract values directly from the single result dict
    tieu_de = components_regex_result.get('tieu_de', '')
    so_hieu = components_regex_result.get('so_hieu', '')
    loai_van_ban = components_regex_result.get('loai_van_ban', '')
    ngay = components_regex_result.get('ngay', None)
    thang = components_regex_result.get('thang', None)
    nam = components_regex_result.get('nam', None)
    
    extracted_information = so_hieu or tieu_de or doc_text

    # ==== DEBUGGING PRINTS ====
    # logger.debug(f"Extracted components: {components_regex_result}")
    # ==== END DEBUGGING PRINTS ====

    ngay_int = int(ngay) if ngay is not None else None
    thang_int = int(thang) if thang is not None else None
    nam_int = int(nam) if nam is not None else None

    # Note: loai_van_ban is capitalized (e.g., 'Luật', 'Bộ luật', 'Hiến pháp')
    if loai_van_ban in ['Hiến pháp', 'Bộ luật', 'Luật', 'Pháp lệnh']:
        # Convert "Hiến pháp" to "hienphap" for filtering
        loai_van_ban = remove_accents(loai_van_ban).replace(" ", "").lower()
        original_tieu_de = tieu_de
        tieu_de = normalize_law_title_abbreviation(tieu_de, law_dataframe)
        if not so_hieu and tieu_de != original_tieu_de:
            extracted_information = tieu_de
        lookup_tieu_de = _expand_common_title_abbreviations(tieu_de)

        # if (so_hieu is None or so_hieu == '') and nam_int is None:
        #     nam_int = cls_nam_ban_hanh
        
        filtered_law_df = filter_law_df(
            so_hieu=so_hieu,
            tieu_de=lookup_tieu_de,
            loai_van_ban=loai_van_ban,
            nam=nam_int,
            cls_nam_ban_hanh=cls_nam_ban_hanh,
            law_df=law_dataframe,
            ngay=ngay_int,
            thang=thang_int,
        )

        if not filtered_law_df.empty:
            # Make a copy to avoid SettingWithCopyWarning
            filtered_law_df = filtered_law_df.copy()
            
            if nam_int is not None:
                # Convert nam_ban_hanh to numeric for year diff calculation
                filtered_law_df['nam_ban_hanh_int'] = pd.to_numeric(filtered_law_df['nam_ban_hanh'], errors='coerce')
                filtered_law_df['year_diff'] = abs(filtered_law_df['nam_ban_hanh_int'] - nam_int)
                closest_law = filtered_law_df.loc[filtered_law_df['year_diff'].idxmin()]
                return closest_law['doc_id'], extracted_information
            else:
                # If nam_int is not provided, sort by nam_ban_hanh descending and take the most recent
                filtered_law_df['nam_ban_hanh_int'] = pd.to_numeric(filtered_law_df['nam_ban_hanh'], errors='coerce')
                filtered_law_df = filtered_law_df.sort_values(by='nam_ban_hanh_int', ascending=False)
                closest_law = filtered_law_df.iloc[0]
                return closest_law['doc_id'], extracted_information

        # Combined msearch: issue law-by-number AND law-by-title in one round-trip
        # when both are needed. This collapses what was previously two sequential
        # ES queries (over VPN) into a single network round-trip, with identical
        # semantics — the number result still wins if present, falling back to
        # the title result.
        reference_doc_id = _search_law_combined_msearch(
            so_hieu=so_hieu,
            tieu_de=lookup_tieu_de,
            loai_van_ban=components_regex_result.get('loai_van_ban', ''),
            ngay=ngay_int,
            thang=thang_int,
            nam=nam_int,
            es_client=es_client,
        )
        if reference_doc_id is not None:
            return reference_doc_id, extracted_information
    else:
        reference_doc_id = search_reference_in_es(
            so_hieu=so_hieu,
            loai_van_ban=loai_van_ban,
            co_quan_ban_hanh=cls_co_quan_ban_hanh,
            ngay_ban_hanh=ngay_int,
            thang_ban_hanh=thang_int,
            nam_ban_hanh=nam_int,
            cls_nam_ban_hanh=cls_nam_ban_hanh,
            es_client=es_client
        )

        if reference_doc_id is not None:
            return reference_doc_id, extracted_information
    
    return None, extracted_information
