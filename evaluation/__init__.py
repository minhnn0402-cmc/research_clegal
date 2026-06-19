"""Utilities for evaluating extracted legal relations."""

from evaluation.converter import relations_to_flat
from evaluation.matcher import match_predictions_to_ground_truth
from evaluation.metrics import EvalResult, aggregate_results, compute_metrics

__all__ = [
    "relations_to_flat",
    "match_predictions_to_ground_truth",
    "EvalResult",
    "aggregate_results",
    "compute_metrics",
]
