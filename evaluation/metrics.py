"""
Precision / Recall / F1 calculation for extracted relationships evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class EvalResult:
    """Holds evaluation metrics for one document (or an aggregate)."""

    doc_id: str = "" # Document identifier

    tp: int = 0  # True Positives
    fp: int = 0  # False Positives
    fn: int = 0  # False Negatives

    # Detailed item lists (populated by evaluator)
    true_positives:  List[Dict] = field(default_factory=list)
    false_positives: List[Dict] = field(default_factory=list)
    false_negatives: List[Dict] = field(default_factory=list)

    @property
    def precision(self) -> float:
        """TP / (TP + FP). Returns 0 if no predictions."""
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN). Returns 0 if no ground-truth items."""
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        denom = p + r
        return 2 * p * r / denom if denom else 0.0

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"[{self.doc_id or 'aggregate'}] "
            f"P={self.precision:.3f}  R={self.recall:.3f}  F1={self.f1:.3f}  "
            f"(TP={self.tp}, FP={self.fp}, FN={self.fn})"
        )

    def to_dict(self) -> Dict:
        return {
            "doc_id":          self.doc_id,
            "precision":       round(self.precision, 4),
            "recall":          round(self.recall, 4),
            "f1":              round(self.f1, 4),
            "tp":              self.tp,
            "fp":              self.fp,
            "fn":              self.fn,
            "true_positives":  self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


def compute_metrics(
    true_positives: List[Dict],
    false_positives: List[Dict],
    false_negatives: List[Dict],
    doc_id: str = "",
) -> EvalResult:
    """
    Build an :class:`EvalResult` from already-aligned TP/FP/FN lists.

    Args:
        true_positives:  Matched predictions.
        false_positives: Predictions with no matching ground-truth entry.
        false_negatives: Ground-truth entries not covered by any prediction.
        doc_id:          Document identifier (for display only).

    Returns:
        Populated :class:`EvalResult`.
    """
    return EvalResult(
        doc_id=doc_id,
        tp=len(true_positives),
        fp=len(false_positives),
        fn=len(false_negatives),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def aggregate_results(results: List[EvalResult], doc_id: str = "TOTAL") -> EvalResult:
    """
    Micro-average across multiple :class:`EvalResult` objects.

    Args:
        results: Per-document results.
        doc_id:  Label for the aggregated result.

    Returns:
        Single :class:`EvalResult` with summed TP/FP/FN counts.
    """
    agg = EvalResult(doc_id=doc_id)
    for r in results:
        agg.tp += r.tp
        agg.fp += r.fp
        agg.fn += r.fn
        agg.true_positives.extend(r.true_positives)
        agg.false_positives.extend(r.false_positives)
        agg.false_negatives.extend(r.false_negatives)
    return agg


def aggregate_by_relation(
    results: List[EvalResult],
) -> Dict[str, EvalResult]:
    """
    Micro-average metrics broken down by relation type across multiple documents.

    Collects all TP / FP / FN items from every result, buckets them by the
    ``relation`` field, then computes per-bucket :class:`EvalResult` objects.

    Args:
        results: Per-document :class:`EvalResult` objects.

    Returns:
        ``{relation_type: EvalResult}`` sorted by relation name.
    """
    from collections import defaultdict

    buckets: Dict[str, Dict[str, list]] = defaultdict(
        lambda: {"tp": [], "fp": [], "fn": []}
    )

    for r in results:
        for item in r.true_positives:
            buckets[item.get("relation", "?")]["tp"].append(item) # Use "?" if relation is missing
        for item in r.false_positives:
            buckets[item.get("relation", "?")]["fp"].append(item)
        for item in r.false_negatives:
            buckets[item.get("relation", "?")]["fn"].append(item)

    return {
        rel: EvalResult(
            doc_id=rel,
            tp=len(g["tp"]),
            fp=len(g["fp"]),
            fn=len(g["fn"]),
            true_positives=g["tp"],
            false_positives=g["fp"],
            false_negatives=g["fn"],
        )
        for rel, g in sorted(buckets.items())
    }
