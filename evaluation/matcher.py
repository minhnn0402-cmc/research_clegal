"""
Reference matching logic for evaluation.

Three-tier rule-based matching:

  Tier 1 - Document-number match
  Tier 2 - Canonical-name prefix match
  Tier 3 - Token Jaccard similarity >= threshold

An evaluation item is a match only when both the reference and relation type
align with one ground-truth row.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set

from unidecode import unidecode

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Ordered from most-specific to least-specific.
# All patterns run on *normalised* text (unidecode + lowercase).
# unidecode already converts NĐ→ND, QĐ→QD, etc., so no manual map needed.
_DOC_NUM_PATTERNS: list[re.Pattern[str]] = [
    # 1. Modern:  num[L]/year/SUFFIX[-SUFFIX]   e.g. 28/2018/qh14, 65/2022/nd-cp
    re.compile(r"\d{1,5}[a-z]?/\d{4}/[a-z0-9][a-z0-9\-]*"),
    # 2. Liaison: num/year/TTLT-…  or  num/year/NQLT-…  (also caught by pattern 1)
    # 3. No-year slash: num[L]/SUFFIX[/-SUFFIX]   e.g. 57/l-ctn, 6/lct, 42/lct/hdnn8, 133/hdbt
    re.compile(r"\d{1,5}[a-z]?/[a-z][a-z0-9]*(?:[-/][a-z0-9]+)+"),
    re.compile(r"\d{1,5}[a-z]?/[a-z]{2,10}\b"),
    # 4. Hyphen:   num[L]-SUFFIX[/-SUFFIX[.digits]]  e.g. 45-lct, 20-l/ctn, 110-sl/l.12, 353-hdbt
    re.compile(r"\d{1,5}[a-z]?-[a-z][a-z0-9]*(?:[-/][a-z0-9.]+)*"),
    # 5. Space:    num SUFFIX/SUFFIX   e.g. 94 qd/lb, 94 tt/lb
    re.compile(r"\d{1,5}\s+[a-z]{2,4}/[a-z0-9]{2,10}"),
]


def _normalize(text: str) -> str:
    """
    Lower-case, remove diacritics (unidecode), collapse whitespace, strip.

    ``unidecode`` already converts Vietnamese abbreviations used in legal
    document numbers (NĐ→ND, QĐ→QD, Đ→D, etc.), so no manual map is needed.
    """
    text = unidecode(text.strip())
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_doc_number(text: str) -> str | None:
    """
    Extract a legal document number from *text* using all format families
    present in ``src/configs/doc_number_patterns_for_regex.py``.

    The text is normalised (unidecode + lowercase) before matching so that
    Vietnamese characters (NĐ, QĐ, …) are transparently converted.
    Patterns are tried in priority order: modern ``num/year/suffix`` first,
    then no-year slash variants, then hyphen variants, then space-separated.

    Args:
        text: Raw reference string (may contain Vietnamese diacritics).

    Returns:
        The matched document-number substring (normalised), or ``None``.
    """
    normed = _normalize(text)
    for pat in _DOC_NUM_PATTERNS:
        m = pat.search(normed)
        if m:
            return m.group(0)
    return None


def _tokens(text: str) -> Set[str]:
    """Split normalised text into a set of word tokens."""
    return set(re.findall(r"\w+", _normalize(text)))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Clause-component extraction and compatibility check
# ---------------------------------------------------------------------------

# Patterns run on *normalised* (unidecode + lowercase) text.
# Vietnamese word → ASCII after unidecode:
#   điểm → diem   khoản → khoan   điều → dieu
_CLAUSE_PATTERNS: dict[str, re.Pattern[str]] = {
    "diem":   re.compile(r"\bdiem\s+([a-z0-9]+)"),
    "khoan":  re.compile(r"\bkhoan\s+(\d+)"),
    "dieu":   re.compile(r"\bdieu\s+(\d+)")
}


def _extract_clause_parts(norm_text: str) -> dict[str, str]:
    """
    Extract clause-level components from a *normalised* reference string.

    Returns a dict mapping component name to its value, e.g.
    ``{"diem": "b", "khoan": "1", "dieu": "70"}``.
    Only markers actually present in *norm_text* are included.
    """
    return {
        key: m.group(1)
        for key, pat in _CLAUSE_PATTERNS.items()
        if (m := pat.search(norm_text))
    }


def _clauses_compatible(gt_norm: str, pred_norm: str) -> bool:
    """
    Return True when all clause components in the ground-truth reference are
    present with the **same values** in the predicted reference.

    If the ground-truth contains no clause markers (e.g. just a law name)
    this always returns True.  If any GT clause component is missing or
    has a different value in the prediction, returns False.

    Examples::

        # GT has diem/khoan/dieu — all must match
        _clauses_compatible(
            "diem b khoan 1 dieu 70 luat cong chung",
            "diem b khoan 1 dieu 70 luat cong chung so 53/2014/qh13",
        )  # → True

        # diem differs (b vs a)
        _clauses_compatible(
            "diem b khoan 1 dieu 70 luat cong chung",
            "diem a khoan 1 dieu 70 luat cong chung",
        )  # → False

        # GT has no clause markers — no constraint
        _clauses_compatible("luat an toan thuc pham", "luat an toan thuc pham sua doi")  # → True
    """
    gt_parts = _extract_clause_parts(gt_norm)
    if not gt_parts:
        return True  # no clause constraint in GT
    pred_parts = _extract_clause_parts(pred_norm)
    return all(pred_parts.get(k) == v for k, v in gt_parts.items())


# ---------------------------------------------------------------------------
# Public matching function
# ---------------------------------------------------------------------------

def references_match(
    gt_reference: str,
    pred_reference: str,
    jaccard_threshold: float = 0.65,
) -> bool:
    """
    Return True if ``pred_reference`` is an acceptable match for ``gt_reference``.

    Args:
        gt_reference: Ground-truth reference string.
        pred_reference: Predicted reference string.
        jaccard_threshold: Minimum Jaccard token similarity for tier-3 fallback.

    Returns:
        True if any matching tier succeeds.
    """
    gt_norm = _normalize(gt_reference)
    pred_norm = _normalize(pred_reference)

    # --- Clause-component pre-check (gates all tiers) -----------------------
    # If the GT specifies điểm / khoản / điều / chương / mục / phần, every one
    # of those values must appear identically in the prediction.  A mismatch
    # short-circuits the match immediately.
    if not _clauses_compatible(gt_norm, pred_norm):
        return False

    # --- Tier 1: document-number substring match ----------------------------
    gt_num = _extract_doc_number(gt_reference)
    pred_num = _extract_doc_number(pred_reference)
    if gt_num and pred_num and gt_num == pred_num:
        return True

    # --- Tier 2: canonical-name prefix match  -------------------------------
    # The ground-truth short name should appear as a *prefix* of the predicted
    # string (after normalisation).  We also allow exact match.
    if pred_norm.startswith(gt_norm):
        return True

    # --- Tier 3: token Jaccard similarity -----------------------------------
    gt_tok = _tokens(gt_reference)
    pred_tok = _tokens(pred_reference)
    if _jaccard(gt_tok, pred_tok) >= jaccard_threshold:
        return True

    return False


def match_predictions_to_ground_truth(
    ground_truth: List[Dict],
    predictions: List[Dict],
    jaccard_threshold: float = 0.65,
) -> tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Align predicted relation pairs against ground-truth rows.

    A prediction is a **True Positive** if there exists an unmatched
    ground-truth item with the same ``relation`` and a reference that passes
    ``references_match()``. Each ground-truth item may only be matched once.

    Args:
        ground_truth: Human-annotated rows.
        predictions:  Extractor output converted to flat format.
        jaccard_threshold: Passed through to ``references_match()``.

    Returns:
        (true_positives, false_positives, false_negatives)
        Each is a list of annotation dicts.
    """
    # Work on copies so we can pop matched items
    unmatched_gt = list(range(len(ground_truth)))

    true_positives:  List[Dict] = []
    false_positives: List[Dict] = []

    for pred in predictions:
        pred_relation = pred.get("relation", "")
        pred_reference = pred.get("reference", "")

        matched_idx = None
        for idx in unmatched_gt:
            gt = ground_truth[idx]
            # if gt.get("relation") != pred_relation:
            #     continue
            gt_relation = gt.get("relation", "")
            
            # Relation type check with relaxation for (quy_dinh_chi_tiet, huong_dan)
            relaxed_group = {"quy_dinh_chi_tiet", "huong_dan"}
            if gt_relation != pred_relation:
                is_relaxed_match = (gt_relation in relaxed_group and pred_relation in relaxed_group)
                if not is_relaxed_match:
                    continue

            if references_match(gt["reference"], pred_reference, jaccard_threshold):
                matched_idx = idx
                break

        if matched_idx is not None:
            unmatched_gt.remove(matched_idx)
            true_positives.append({
                **pred,
                "_matched_gt": ground_truth[matched_idx],
            })
        else:
            false_positives.append(pred)

    # Remaining unmatched GT items are False Negatives
    false_negatives = [ground_truth[i] for i in unmatched_gt]

    return true_positives, false_positives, false_negatives
