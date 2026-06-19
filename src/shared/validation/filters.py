"""Filtering and validation utilities for document relationships."""
import re
import pandas as pd
import unicodedata
from difflib import SequenceMatcher

# Pre-computed map for 'đ' characters which are not decomposed by NFD
_D_MAP = {ord('đ'): 'd', ord('Đ'): 'D'}





def remove_accents(text: str) -> str:
    """
    Remove Vietnamese accents for comparison.
    Handles standard diacritics via NFD normalization and 
    specifically handles 'đ/Đ' which are not decomposed by NFD.
    """
    if not text:
        return text
    
    # 1. Translate đ/Đ first
    text = text.translate(_D_MAP)
    
    # 2. Decompose and filter out non-spacing marks (accents)
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def _normalize_title_for_match(text: str) -> str:
    normalized = remove_accents(str(text or "").lower())
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_title_conditions(tieu_de: str, law_df: pd.DataFrame) -> pd.Series:
    """Match title-only references conservatively: exact first, fuzzy only if unique."""
    false_conditions = pd.Series(False, index=law_df.index)
    normalized_query = _normalize_title_for_match(tieu_de)
    if not normalized_query:
        return false_conditions

    normalized_titles = law_df["tieu_de"].fillna("").apply(_normalize_title_for_match)
    exact_conditions = normalized_titles == normalized_query
    if exact_conditions.any():
        return exact_conditions

    candidate_indexes = []
    query_tokens = {
        token for token in normalized_query.split()
        if token not in {"luat", "bo", "cua", "ve"}
    }
    for index, normalized_title in normalized_titles.items():
        if not normalized_title:
            continue

        is_substring_candidate = (
            normalized_query in normalized_title
            or normalized_title in normalized_query
        )
        title_tokens = set(normalized_title.split())
        is_token_candidate = bool(query_tokens) and query_tokens <= title_tokens
        similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()
        if is_substring_candidate or is_token_candidate or similarity >= 0.92:
            candidate_indexes.append(index)

    if len(candidate_indexes) != 1:
        return false_conditions

    conditions = false_conditions.copy()
    conditions.loc[candidate_indexes[0]] = True
    return conditions


def _extract_amendment_base_title(tieu_de: str) -> str | None:
    """Return the base law title from amendment-wrapper titles, if present."""
    normalized = _normalize_title_for_match(tieu_de)
    match = re.match(
        r"^(?:luat|bo luat|phap lenh)\s+sua doi bo sung mot so dieu cua\s+(.+)$",
        normalized,
    )
    if not match:
        match = re.match(r"^sua doi bo sung mot so dieu cua\s+(.+)$", normalized)
    if not match:
        return None

    base_title = match.group(1).strip()
    return base_title or None


def _build_base_conditions(
    so_hieu: str,
    tieu_de: str,
    loai_van_ban: str,
    law_df: pd.DataFrame,
) -> pd.Series:
    """
    Build combined filter conditions from the primary document identifiers
    (so_hieu, tieu_de, loai_van_ban) without applying any year constraint.

    so_hieu takes priority: when present, tieu_de is skipped and only loai_van_ban
    is combined as an optional narrowing criterion.  When so_hieu is absent,
    tieu_de is matched exactly first (case-insensitive) then falls back to
    substring matching, and loai_van_ban is always applied when provided.

    Args:
        so_hieu: Document number.
        tieu_de: Document title.
        loai_van_ban: Document type.
        law_df: Law documents dataframe.

    Returns:
        Boolean Series aligned with law_df.index.
    """
    conditions = pd.Series(True, index=law_df.index)

    if so_hieu:
        conditions &= law_df['so_hieu'].str.lower() == so_hieu.lower()
        if tieu_de:
            title_conditions = _build_title_conditions(tieu_de, law_df)
            if not (conditions & title_conditions).any():
                amendment_base_title = _extract_amendment_base_title(tieu_de)
                if amendment_base_title:
                    amendment_title_conditions = _build_title_conditions(amendment_base_title, law_df)
                    if (conditions & amendment_title_conditions).any():
                        title_conditions = amendment_title_conditions
            conditions &= title_conditions
    else:
        # tieu_de: exact match first, then conservative unique fuzzy fallback.
        if tieu_de:
            conditions &= _build_title_conditions(tieu_de, law_df)

    if loai_van_ban:
        loai_van_ban_normalized = remove_accents(loai_van_ban.lower())
        conditions &= law_df['loai_van_ban'].apply(
            lambda x: remove_accents(str(x).lower()) == loai_van_ban_normalized
        )

    return conditions


def _build_date_conditions(
    law_df: pd.DataFrame,
    ngay: int | None,
    thang: int | None,
    nam: int | None,
) -> pd.Series:
    false_conditions = pd.Series(False, index=law_df.index)
    if nam is None or "ngay_ban_hanh" not in law_df.columns:
        return false_conditions

    dates = pd.to_datetime(law_df["ngay_ban_hanh"], errors="coerce")
    conditions = dates.dt.year == int(nam)
    if thang is not None:
        conditions &= dates.dt.month == int(thang)
    if ngay is not None:
        conditions &= dates.dt.day == int(ngay)
    return conditions.fillna(False)


def _reject_ambiguous_title_year_without_date(
    result_df: pd.DataFrame,
    so_hieu: str,
    tieu_de: str,
    nam: int | None,
    ngay: int | None,
    thang: int | None,
) -> pd.DataFrame:
    if so_hieu or not tieu_de or ngay is not None or thang is not None:
        return result_df
    if len(result_df) <= 1:
        return result_df

    normalized_titles = result_df["tieu_de"].fillna("").apply(_normalize_title_for_match)
    normalized_query = _normalize_title_for_match(tieu_de)
    years = pd.to_numeric(result_df["nam_ban_hanh"], errors="coerce")
    exact_title_years = years[normalized_titles == normalized_query]
    same_title_year_counts = exact_title_years.value_counts(dropna=True)
    if not same_title_year_counts.empty and same_title_year_counts.max() > 1:
        # When multiple docs share the same title+year, prefer the canonical entry
        # (so_hieu = 'không số') over gazette/promulgation versions that carry a
        # real decree number (e.g. '68-lct/hđnn8' for Hiến pháp 1992).
        placeholder_mask = result_df["so_hieu"].apply(
            lambda x: remove_accents(str(x or "").lower()).replace(" ", "") in {"", "khongso"}
        )
        placeholder_df = result_df[placeholder_mask]
        if len(placeholder_df) == 1:
            return placeholder_df
        return result_df.iloc[0:0]
    return result_df


def filter_law_dataframe(
    so_hieu: str,
    tieu_de: str,
    loai_van_ban: str,
    nam: int,
    cls_nam_ban_hanh: int,
    law_df: pd.DataFrame,
    ngay: int | None = None,
    thang: int | None = None,
) -> pd.DataFrame:
    """
    Filter the law dataframe based on provided criteria.

    Priority:
    1. so_hieu + loai_van_ban + exact nam (or < cls_nam_ban_hanh) — returns early.
    2. tieu_de + loai_van_ban + exact nam (or < cls_nam_ban_hanh).
    3. Fallback (result_df empty): reuse base conditions + try year == cls_nam_ban_hanh,
       then most-recent year < cls_nam_ban_hanh.

    Args:
        so_hieu: Document number.
        tieu_de: Document title.
        loai_van_ban: Document type.
        nam: Exact year of issuance extracted from the reference text.
        cls_nam_ban_hanh: Year of the classifying (parent) document; used as an
            upper-bound guard when nam is absent.
        law_df: Law documents dataframe.

    Returns:
        Filtered DataFrame, or None when no identifying params are given.
    """
    if all(param is None for param in [so_hieu, tieu_de, loai_van_ban, nam]):
        return None

    year_series = pd.to_numeric(law_df['nam_ban_hanh'], errors='coerce')

    # Build base conditions (identifiers only, no year yet)
    base_conditions = _build_base_conditions(so_hieu, tieu_de, loai_van_ban, law_df)

    # so_hieu is the most specific identifier — apply only an exact year guard (if nam is
    # known) and skip the cls_nam_ban_hanh upper-bound guard entirely, because the referenced
    # document can legally be issued in the same year as the classifying document.
    if so_hieu:
        conditions = base_conditions.copy()
        if nam:
            conditions &= year_series == nam
        result_df = law_df[conditions]
        if nam and (ngay is not None or thang is not None):
            date_conditions = _build_date_conditions(law_df, ngay, thang, nam)
            date_result = law_df[conditions & date_conditions]
            if not date_result.empty:
                result_df = date_result
            elif len(result_df) > 1:
                return result_df.iloc[0:0]
        return result_df

    # For tieu_de-based search, exact year wins. If year is absent, prefer the
    # current document year first, then fall back to the most recent earlier year.
    conditions = base_conditions.copy()
    if nam:
        conditions &= year_series == nam
        result_df = law_df[conditions]
    elif cls_nam_ban_hanh:
        same_year_conditions = base_conditions & (year_series == cls_nam_ban_hanh)
        same_year_df = law_df[same_year_conditions]
        if not same_year_df.empty:
            result_df = same_year_df
        else:
            earlier_mask = base_conditions & (year_series < cls_nam_ban_hanh)
            earlier_df = law_df[earlier_mask]
            if not earlier_df.empty:
                max_year = int(year_series[earlier_mask].max())
                result_df = earlier_df[
                    pd.to_numeric(earlier_df['nam_ban_hanh'], errors='coerce') == max_year
                ]
            else:
                result_df = law_df[conditions & (year_series < cls_nam_ban_hanh)]
    else:
        result_df = law_df[conditions]

    if nam and (ngay is not None or thang is not None):
        date_conditions = _build_date_conditions(law_df, ngay, thang, nam)
        date_result = law_df[conditions & date_conditions]
        if not date_result.empty:
            result_df = date_result
        elif len(result_df) > 1:
            return result_df.iloc[0:0]

    return _reject_ambiguous_title_year_without_date(
        result_df=result_df,
        so_hieu=so_hieu,
        tieu_de=tieu_de,
        nam=nam,
        ngay=ngay,
        thang=thang,
    )
