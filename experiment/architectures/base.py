"""Common architecture interface.

An architecture maps one clause unit to a flat list of predicted relations,
``[{"reference": str, "relation": str}, ...]`` — exactly the shape the
``evaluation.matcher`` expects.
"""

from __future__ import annotations

from typing import Dict, List, Protocol

from experiment.clause_dataset import ClauseUnit


class Architecture(Protocol):
    name: str

    def predict(self, unit: ClauseUnit) -> List[Dict]:
        ...


def dedupe(predictions: List[Dict]) -> List[Dict]:
    """Drop exact duplicate (relation, reference) pairs, preserving order."""
    seen = set()
    out: List[Dict] = []
    for p in predictions:
        key = (p.get("relation", ""), p.get("reference", "").strip())
        if key in seen or not key[1]:
            continue
        seen.add(key)
        out.append(p)
    return out
