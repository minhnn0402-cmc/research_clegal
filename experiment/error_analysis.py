"""Error analysis over saved result bundles.

Three jobs:
  1. Categorise false positives / false negatives by *cause* using
     deterministic textual signals (no extra model calls).
  2. Label audit — surface gold rows that are likely mislabeled, in particular
     the ``sua_doi`` / ``bo_sung`` / ``sua_doi_bo_sung`` granularity confusion
     where a prediction and a gold item share a reference but differ only in
     amendment granularity (a matcher/label artifact, not a real error).
  3. A0-vs-A3 diff — for every candidate the gate pruned, was it a true
     positive (recall loss) or a false positive (precision gain)?
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from evaluation.matcher import _normalize, references_match

_AMEND_FAMILY = {"sua_doi", "bo_sung", "sua_doi_bo_sung"}
_PASSIVE = re.compile(r"đã được .{0,40}(sửa đổi|bổ sung|thay thế|bãi bỏ).{0,20}theo", re.IGNORECASE)
_NAME_KEYWORD = re.compile(r"luật sửa đổi,?\s*bổ sung một số điều", re.IGNORECASE)
_SELF_REF = re.compile(r"\b(luật|nghị định|thông tư|quyết định|điều|khoản|nghị quyết|pháp lệnh)\s+này\b", re.IGNORECASE)


def load_bundle(path: Path) -> Dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fp_cause(fp: Dict, row: Dict) -> str:
    ref = fp.get("reference", "")
    content = row.get("content", "")
    # Same reference as a gold item but different amendment granularity?
    for gt in row.get("ground_truth", []):
        if gt["relation"] != fp["relation"] and references_match(gt["reference"], ref):
            if {gt["relation"], fp["relation"]} <= _AMEND_FAMILY:
                return "amend_granularity"
            return "relation_type_confusion"
    if _SELF_REF.search(ref):
        return "self_reference"
    if _PASSIVE.search(content):
        return "passive_history"
    if _NAME_KEYWORD.search(content) and _NAME_KEYWORD.search(ref):
        return "name_as_keyword"
    return "other_spurious_target"


def _fn_cause(fn: Dict, row: Dict) -> str:
    ref = fn.get("reference", "")
    for pred in row.get("predictions", []):
        if pred["relation"] != fn["relation"] and references_match(fn["reference"], pred.get("reference", "")):
            if {pred["relation"], fn["relation"]} <= _AMEND_FAMILY:
                return "amend_granularity"
            return "relation_type_confusion"
    # Reference present in some prediction but type/clause off?
    for pred in row.get("predictions", []):
        if _normalize(ref)[:15] and _normalize(ref)[:15] in _normalize(pred.get("reference", "")):
            return "partial_reference"
    return "missed_entirely"


def categorize(bundle: Dict) -> Dict[str, Counter]:
    fp_causes: Counter = Counter()
    fn_causes: Counter = Counter()
    for row in bundle["rows"]:
        for fp in row["fp"]:
            fp_causes[_fp_cause(fp, row)] += 1
        for fn in row["fn"]:
            fn_causes[_fn_cause(fn, row)] += 1
    return {"fp": fp_causes, "fn": fn_causes}


def label_audit(bundle: Dict) -> Dict:
    """Quantify how much of the apparent error is a label/granularity artifact."""
    cats = categorize(bundle)
    fp = cats["fp"]; fn = cats["fn"]
    total_fp = sum(fp.values()); total_fn = sum(fn.values())
    artifact_fp = fp["amend_granularity"]
    artifact_fn = fn["amend_granularity"]
    return {
        "total_fp": total_fp,
        "total_fn": total_fn,
        "amend_granularity_fp": artifact_fp,
        "amend_granularity_fn": artifact_fn,
        "fp_causes": dict(fp),
        "fn_causes": dict(fn),
        "note": (
            "amend_granularity items share a reference with a gold/predicted "
            "item but differ only in sua_doi/bo_sung/sua_doi_bo_sung. These are "
            "label-scheme artifacts, not semantic extraction errors."
        ),
    }


def diff_a0_a3(a0_bundle: Dict, a3_bundle: Dict) -> Dict:
    """Classify every candidate the gate removed (A0 had it, A3 dropped it)."""
    a3_by_key: Dict[Tuple, List[Dict]] = {}
    for row in a3_bundle["rows"]:
        a3_by_key[tuple(row["key"])] = row["predictions"]

    pruned_tp: List[Dict] = []
    pruned_fp: List[Dict] = []
    for row in a0_bundle["rows"]:
        kept = a3_by_key.get(tuple(row["key"]), [])
        kept_keys = {(p["relation"], p["reference"]) for p in kept}
        tp_keys = {(t["relation"], t["reference"]) for t in row["tp"]}
        for pred in row["predictions"]:
            pk = (pred["relation"], pred["reference"])
            if pk in kept_keys:
                continue  # not pruned
            entry = {"relation": pred["relation"], "reference": pred["reference"],
                     "so_hieu": row["so_hieu"], "content": row["content"][:120]}
            (pruned_tp if pk in tp_keys else pruned_fp).append(entry)

    return {
        "pruned_true_positives": len(pruned_tp),
        "pruned_false_positives": len(pruned_fp),
        "precision_gain_items": pruned_fp,
        "recall_loss_items": pruned_tp,
    }
