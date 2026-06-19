import re
import unicodedata
from src.infrastructure.logging import get_logger


# Initialize logger
logger = get_logger('SearchReferenceInES')


def _fold_so_hieu(value: str | None) -> str:
    """Normalize separators/accents while preserving case for exact ES variants."""
    if value is None:
        return ""

    normalized = str(value).strip()
    normalized = re.sub(r"^\s*số\s+", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.translate({ord("đ"): "d", ord("Đ"): "D"})
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    normalized = re.sub(r"\s*([/-])\s*", r"\1", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _normalize_so_hieu(value: str | None) -> str:
    """Normalize document number for exact post-filter comparison."""
    return _fold_so_hieu(value).upper()


def _canonical_suffix_token(value: str) -> str:
    token = str(value or "")
    if token.lower() == "ttg":
        return "TTg"
    return token.upper()


def _canonical_case_so_hieu(value: str | None) -> str:
    if value is None:
        return ""

    normalized = str(value).strip()
    normalized = re.sub(r"^\s*số\s+", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    normalized = re.sub(r"\s*([/-])\s*", r"\1", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    if "/" not in normalized:
        return normalized

    prefix, suffix = normalized.rsplit("/", 1)
    suffix_parts = [
        _canonical_suffix_token(part)
        for part in suffix.split("-")
        if part
    ]
    if not suffix_parts:
        return normalized
    return f"{prefix}/{'-'.join(suffix_parts)}"


def _so_hieu_exact_variants(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    folded_raw = _fold_so_hieu(raw)
    canonical_raw = _canonical_case_so_hieu(raw)
    folded_canonical = _fold_so_hieu(canonical_raw)
    preferred_order = [
        raw,
        raw.upper(),
        raw.lower(),
        folded_raw,
        folded_raw.upper(),
        folded_raw.lower(),
        canonical_raw,
        folded_canonical,
        folded_canonical.upper(),
        folded_canonical.lower(),
        re.sub(r"[\s\\-]+", "/", raw),
        re.sub(r"[\s/\\]+", "-", raw),
    ]

    ordered_variants = []
    for variant in preferred_order:
        if variant and variant not in ordered_variants:
            ordered_variants.append(variant)
    return ordered_variants


def _is_specific_so_hieu(value: str | None) -> bool:
    """Return True when the number contains an authority suffix, not just a prefix."""
    normalized = _normalize_so_hieu(value)
    if not normalized:
        return False

    if not re.match(r"^\d+/", normalized):
        return False

    final_segment = normalized.rsplit("/", 1)[-1]
    incomplete_suffixes = {
        "ND", "NĐ", "QD", "QĐ", "TT", "TTLT", "NQ", "CT", "VB",
    }
    if final_segment in incomplete_suffixes:
        return False

    if "-" in final_segment:
        return True

    # Quốc hội / UBTVQH numbers are complete without a hyphenated suffix.
    if re.match(r"^(?:QH|UBTVQH)\d{1,3}$", final_segment):
        return True

    # Administrative references such as 1171/KCB are specific even without a
    # year; document-type-only suffixes above remain incomplete.
    return bool(re.search(r"[A-Z]{2,}", final_segment))


def _is_extendable_multi_agency_so_hieu(value: str | None) -> bool:
    """Return True for structured multi-agency suffixes that may be abbreviated."""
    normalized = _normalize_so_hieu(value)
    if "/" not in normalized:
        return False
    suffix = normalized.rsplit("/", 1)[-1]
    return suffix.count("-") >= 2 and bool(re.search(r"[A-Z]", suffix))


def _is_extended_so_hieu_match(hit_so_hieu: str | None, query_so_hieu: str | None) -> bool:
    if not _is_extendable_multi_agency_so_hieu(query_so_hieu):
        return False
    hit = _normalize_so_hieu(hit_so_hieu)
    query = _normalize_so_hieu(query_so_hieu)
    return bool(hit and query and hit != query and hit.startswith(query))


def _normalize_authority(value: str | None) -> str:
    """Normalize issuing authority for post-filtering same-number local docs."""
    if value is None:
        return ""

    text = str(value).strip().lower()
    text = text.replace("ubnd", "ủy ban nhân dân")
    text = text.replace("hđnd", "hội đồng nhân dân")
    text = text.replace("hdnd", "hội đồng nhân dân")
    text = text.translate({ord("đ"): "d", ord("Đ"): "D"})
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _authority_matches(hit_authority: str | None, query_authority: str | None) -> bool:
    query = _normalize_authority(query_authority)
    hit = _normalize_authority(hit_authority)
    if not query or not hit:
        return False

    return query == hit or query in hit or hit in query


def _date_matches(
    hit_date: str | None,
    ngay_ban_hanh: int | None,
    thang_ban_hanh: int | None,
    nam_ban_hanh: int | None,
) -> bool:
    """Return True when the hit date satisfies the explicit date/year in the reference."""
    if not hit_date or nam_ban_hanh is None:
        return False

    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", str(hit_date))
    if not match:
        return False

    hit_year = int(match.group(1))
    hit_month = int(match.group(2)) if match.group(2) else None
    hit_day = int(match.group(3)) if match.group(3) else None

    if hit_year != int(nam_ban_hanh):
        return False
    if thang_ban_hanh is not None and hit_month != int(thang_ban_hanh):
        return False
    if ngay_ban_hanh is not None and hit_day != int(ngay_ban_hanh):
        return False
    return True


def _select_exact_so_hieu_hit(
    hits: list[dict],
    so_hieu: str,
    co_quan_ban_hanh: str | None = None,
    ngay_ban_hanh: int | None = None,
    thang_ban_hanh: int | None = None,
    nam_ban_hanh: int | None = None,
) -> tuple[dict | None, bool]:
    """Return an exact so_hieu hit and whether the result is too ambiguous."""
    query_so_hieu = _normalize_so_hieu(so_hieu)
    if not query_so_hieu:
        return None, False

    exact_hits = [
        hit for hit in hits
        if _normalize_so_hieu(hit.get("_source", {}).get("so_hieu")) == query_so_hieu
    ]
    if not exact_hits:
        exact_hits = [
            hit for hit in hits
            if _is_extended_so_hieu_match(
                hit.get("_source", {}).get("so_hieu"),
                so_hieu,
            )
        ]
        if not exact_hits:
            return None, False

    if co_quan_ban_hanh:
        authority_hits = [
            hit for hit in exact_hits
            if _authority_matches(
                hit.get("_source", {}).get("co_quan_ban_hanh"),
                co_quan_ban_hanh,
            )
        ]
        if authority_hits:
            exact_hits = authority_hits
        elif len(exact_hits) > 1:
            return None, True

    if nam_ban_hanh is not None:
        date_hits = [
            hit for hit in exact_hits
            if _date_matches(
                hit.get("_source", {}).get("ngay_ban_hanh"),
                ngay_ban_hanh,
                thang_ban_hanh,
                nam_ban_hanh,
            )
        ]
        if date_hits:
            exact_hits = date_hits
        elif len(exact_hits) > 1:
            return None, True

    exact_hits.sort(key=lambda hit: hit.get("_score", 0) or 0, reverse=True)
    best_exact_hit = exact_hits[0]
    top_hit = hits[0]

    top_so_hieu = top_hit.get("_source", {}).get("so_hieu")
    top_is_candidate = (
        _normalize_so_hieu(top_so_hieu) == query_so_hieu
        or _is_extended_so_hieu_match(top_so_hieu, so_hieu)
    )
    if not top_is_candidate:
        top_score = float(top_hit.get("_score", 0) or 0)
        exact_score = float(best_exact_hit.get("_score", 0) or 0)
        if abs(top_score - exact_score) <= 0.1:
            return None, True

    return best_exact_hit, False


def search_reference_in_es(so_hieu: str, loai_van_ban: str, co_quan_ban_hanh: str,
                           ngay_ban_hanh: int, thang_ban_hanh: int, nam_ban_hanh: int, cls_nam_ban_hanh: int, es_client) -> int|str|None:
    """
    Search for a reference document in Elasticsearch based on provided criteria.
    """
    must_clauses = []

    contains_local = False
    has_specific_so_hieu = False
    if so_hieu:
        upper_so_hieu = str(so_hieu).upper()
        contains_local = (
            "UBND" in upper_so_hieu
            or "UB" in upper_so_hieu
            or "HĐND" in upper_so_hieu
        )

    if so_hieu:
        # Extract the leading number from so_hieu for prefix filtering
        # e.g., "883/2004/QĐ-UBND" -> "883"
        number_prefix_match = re.match(r'^(\d+)', str(so_hieu).strip())
        number_prefix = number_prefix_match.group(1) if number_prefix_match else None
        
        raw = str(so_hieu).strip()
        has_specific_so_hieu = _is_specific_so_hieu(raw)
        ordered_variants = _so_hieu_exact_variants(raw)

        term_entries = []
        # Assign decreasing boosts so exact original is preferred
        boosts = [12, 9, 7, 6, 5]
        for i, v in enumerate(ordered_variants):
            boost_val = boosts[i] if i < len(boosts) else 2
            term_entries.append({
                "term": {"so_hieu.keyword": {"value": v, "boost": boost_val}}
            })

        # Add wildcard prefix match to ensure number starts correctly
        if number_prefix and not has_specific_so_hieu:
            term_entries.append({
                "wildcard": {
                    "so_hieu.keyword": {
                        "value": f"{number_prefix}*",
                        "boost": 9.0  # High boost for correct prefix
                    }
                }
            })
        
        term_entries.append(
            # case-insensitive match requiring all terms
            {"match": {"so_hieu": {"query": so_hieu, "operator": "and", "boost": 1.0}}}
        )
        if not has_specific_so_hieu:
            term_entries.append(
                # fuzzy fallback for 1-char typos on incomplete numbers only
                {"match": {"so_hieu": {"query": so_hieu, "fuzziness": 1, "boost": 0.5}}}
            )
        elif _is_extendable_multi_agency_so_hieu(raw):
            for v in ordered_variants[:4]:
                term_entries.append({
                    "wildcard": {
                        "so_hieu.keyword": {
                            "value": f"{v}*",
                            "boost": 1.5,
                        }
                    }
                })

        must_clauses.append({
            "bool": {
                "should": term_entries,
                "minimum_should_match": 1
            }
        })

    # loai_van_ban: MUST match (moved to must_clauses for stricter filtering)
    # e.g., "Thông tư" exact match first, then "Thông tư*" for variants (like "Thông tư liên tịch")
    if loai_van_ban:
        must_clauses.append({
            "bool": {
                "should": [
                    # Exact match first (highest priority)
                    {
                        "term": {
                            "loai_van_ban.keyword": {
                                "value": loai_van_ban,
                                "boost": 5.0
                            }
                        }
                    },
                    # Wildcard match for variants (e.g., "Thông tư liên tịch")
                    {
                        "wildcard": {
                            "loai_van_ban.keyword": {
                                "value": f"{loai_van_ban}*",
                                "boost": 3.0
                            }
                        }
                    }
                ],
                "minimum_should_match": 1
            }
        })

    # For a complete document number, fetch exact-number candidates first and
    # use the date only in post-filtering. ES often stores legacy dates with
    # timezone/day drift, and pre-filtering here hides otherwise exact hits.
    if nam_ban_hanh is not None and not has_specific_so_hieu:
        if ngay_ban_hanh is not None and thang_ban_hanh is not None:
            # Full date: exact day match
            try:
                date_str = f"{nam_ban_hanh}-{thang_ban_hanh:02d}-{ngay_ban_hanh:02d}"
                must_clauses.append({
                    "range": {
                        "ngay_ban_hanh": {
                            "gte": f"{date_str}T00:00:00Z",
                            "lte": f"{date_str}T23:59:59Z"
                        }
                    }
                })
            except (ValueError, TypeError):
                pass  # Skip if conversion fails
        else:
            # Year only: match entire year
            must_clauses.append({
                "range": {
                    "ngay_ban_hanh": {
                        "gte": f"{nam_ban_hanh}-01-01T00:00:00Z",
                        "lte": f"{nam_ban_hanh}-12-31T23:59:59Z"
                    }
                }
            })

    # co_quan_ban_hanh matching - MUST match for local government documents (UBND, HĐND)
    if co_quan_ban_hanh and contains_local:
        should_clauses = []
        
        # Original query with highest priority
        should_clauses.extend([
            # Exact phrase match for original
            {
                "match_phrase": {
                    "co_quan_ban_hanh": {
                        "query": co_quan_ban_hanh,
                        "boost": 4.0
                    }
                }
            }
        ])
        
        # Generate alternative query (UBND <-> HĐND)
        alternative_co_quan = None
        if 'UBND' in co_quan_ban_hanh:
            # Replace UBND with HĐND
            alternative_co_quan = co_quan_ban_hanh.replace('UBND', 'HĐND')
        elif 'HĐND' in co_quan_ban_hanh:
            # Replace HĐND with UBND
            alternative_co_quan = co_quan_ban_hanh.replace('HĐND', 'UBND')
        
        # Add alternative query with lower boost (fallback)
        if alternative_co_quan:
            should_clauses.extend([
                # Exact phrase match for alternative
                {
                    "match_phrase": {
                        "co_quan_ban_hanh": {
                            "query": alternative_co_quan,
                            "boost": 2.0
                        }
                    }
                }
            ])
        
        must_clauses.append({
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1
            }
        })

    # No search criteria provided
    if not must_clauses:
        return None
        
    # Build the query. Exact local document numbers are often duplicated across
    # provinces, so post-filtering by date/authority needs a wider candidate set.
    query_size = 50 if has_specific_so_hieu else 3
    query = {
        "_source": ["ID", "so_hieu", "loai_van_ban", "co_quan_ban_hanh", "ngay_ban_hanh", "tieu_de"],
        "size": query_size,
        "query": {
            "bool": {
                "must": must_clauses
            }
        },
        "sort": [
            {"_score": {"order": "desc"}},
            {"ngay_ban_hanh": {"order": "desc"}}  # Tiebreaker: newer documents first
        ]
    }

    try:
        response = es_client.search(index="law_documents_t4", body=query)
        hits = response.get("hits", {}).get("hits", [])

        if len(hits) == 0:
            return None

        if so_hieu and has_specific_so_hieu:
            exact_hit, is_ambiguous = _select_exact_so_hieu_hit(
                hits,
                so_hieu,
                co_quan_ban_hanh,
                ngay_ban_hanh,
                thang_ban_hanh,
                nam_ban_hanh,
            )
            if is_ambiguous:
                return None
            if exact_hit is not None:
                return exact_hit['_source']["ID"]
            return None
        
        # Check for ambiguity
        # if len(hits) > 1:
        #     top_score = hits[0].get('_score', 0)
        #     second_score = hits[1].get('_score', 0)
            
        #     # Reject if top result is not significantly better than second
        #     if top_score < second_score * AMBIGUITY_RATIO:
        #         return None

        #     if has_so_hieu and abs(top_score - second_score) < 0.1:
        #         return None

        # Return the best matching document
        return hits[0]['_source']["ID"]
    
    except Exception as e:
        logger.error(f"Elasticsearch query error: {str(e)}")
        return None
