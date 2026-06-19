"""Run one architecture over a list of clause units and score it.

Scoring reuses the production ``evaluation.matcher`` and ``evaluation.metrics``
verbatim, so every architecture is judged on an identical contract. Per-clause
predictions are persisted so the error-analysis and A0-vs-A3 diff steps can run
offline without re-calling the model.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from evaluation.matcher import match_predictions_to_ground_truth
from evaluation.metrics import EvalResult, aggregate_by_relation, compute_metrics

from experiment.architectures.base import Architecture
from experiment.clause_dataset import ClauseUnit
from experiment.config import JACCARD_THRESHOLD, RESULTS_DIR
from experiment.stats import wilson_interval


def _score_clause(arch: Architecture, unit: ClauseUnit) -> Dict:
    predictions = arch.predict(unit)
    tp, fp, fn = match_predictions_to_ground_truth(
        unit.ground_truth, predictions, JACCARD_THRESHOLD
    )
    return {
        "key": list(unit.key),
        "so_hieu": unit.so_hieu,
        "clause_type": unit.clause_type,
        "content": unit.content,
        "parent_content": unit.parent_content,
        "grandparent_content": unit.grandparent_content,
        "ground_truth": unit.ground_truth,
        "predictions": predictions,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def run_architecture(
    arch: Architecture,
    units: List[ClauseUnit],
    *,
    workers: int = 1,
    telemetry: Optional[Dict] = None,
    progress_every: int = 100,
) -> Dict:
    """Execute ``arch`` over ``units`` and return a full result bundle."""
    rows: List[Dict] = [None] * len(units)  # type: ignore[list-item]

    def work(i_unit):
        i, unit = i_unit
        row = _score_clause(arch, unit)
        rows[i] = row
        if progress_every and (i + 1) % progress_every == 0:
            print(f"    [{arch.name}] {i + 1}/{len(units)} clauses")
        return None

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, enumerate(units)))
    else:
        for item in enumerate(units):
            work(item)

    all_tp = [x for r in rows for x in r["tp"]]
    all_fp = [x for r in rows for x in r["fp"]]
    all_fn = [x for r in rows for x in r["fn"]]
    overall = compute_metrics(all_tp, all_fp, all_fn, doc_id=arch.name)

    per_row = [compute_metrics(r["tp"], r["fp"], r["fn"]) for r in rows]
    by_relation = {k: v.to_dict() for k, v in aggregate_by_relation(per_row).items()}

    by_clause: Dict[str, EvalResult] = {}
    for r in rows:
        ct = r["clause_type"]
        agg = by_clause.setdefault(ct, EvalResult(doc_id=ct))
        agg.tp += len(r["tp"]); agg.fp += len(r["fp"]); agg.fn += len(r["fn"])

    p_ci = wilson_interval(overall.tp, overall.tp + overall.fp)
    r_ci = wilson_interval(overall.tp, overall.tp + overall.fn)

    bundle = {
        "architecture": arch.name,
        "n_clauses": len(units),
        "overall": {
            **overall.to_dict(),
            "precision_ci95": [p_ci.low, p_ci.high],
            "recall_ci95": [r_ci.low, r_ci.high],
        },
        "by_relation_type": by_relation,
        "by_clause_type": {k: v.to_dict() for k, v in sorted(by_clause.items())},
        "telemetry": telemetry or {},
        "rows": rows,
    }
    return bundle


def save_bundle(bundle: Dict, filename: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(RESULTS_DIR) / filename
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def summary_line(bundle: Dict) -> str:
    o = bundle["overall"]
    pci = o.get("precision_ci95", [0, 0])
    return (
        f"{bundle['architecture']:<22} "
        f"P={o['precision']:.3f} [{pci[0]:.3f},{pci[1]:.3f}]  "
        f"R={o['recall']:.3f}  F1={o['f1']:.3f}  "
        f"(TP={o['tp']} FP={o['fp']} FN={o['fn']}, n={bundle['n_clauses']})"
    )
