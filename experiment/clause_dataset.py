"""Load an evaluation CSV into clause units.

A *clause unit* is one piece of legal text (with its parent/grandparent
context) plus the list of ground-truth ``(reference, relation)`` pairs that
belong to it. This mirrors exactly how ``evaluation/evaluate.py`` groups rows,
so scores here are comparable to the production evaluator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import pandas as pd

from evaluation.evaluate import normalize_so_hieu_for_evaluation

CLAUSE_ID_COLUMNS = ("so_hieu", "clause_type", "content", "parent_content", "grandparent_content")


@dataclass
class ClauseUnit:
    """One evaluation unit: a clause in context with its gold relations."""

    so_hieu: str
    title: str
    clause_type: str
    content: str
    parent_content: str
    grandparent_content: str
    ground_truth: List[Dict] = field(default_factory=list)  # [{"reference","relation"}]
    row_index: int = 0

    @property
    def key(self) -> tuple:
        return (self.so_hieu, self.clause_type, self.content,
                self.parent_content, self.grandparent_content)


def load_clause_units(dataset_path: Path) -> List[ClauseUnit]:
    """Group an evaluation CSV into clause units (one per unique clause)."""
    df = pd.read_csv(dataset_path, dtype=str).fillna("")
    df["clause_type"] = df["clause_type"].str.strip().str.lower()

    units: Dict[tuple, ClauseUnit] = {}
    for idx, row in df.iterrows():
        so_hieu = normalize_so_hieu_for_evaluation(str(row["so_hieu"]).strip())
        clause_type = str(row["clause_type"]).strip().lower()
        content = str(row["content"]).strip()
        parent = str(row["parent_content"]).strip()
        grandparent = str(row["grandparent_content"]).strip()
        key = (so_hieu, clause_type, content, parent, grandparent)

        if key not in units:
            units[key] = ClauseUnit(
                so_hieu=so_hieu,
                title=str(row.get("title", "")).strip(),
                clause_type=clause_type,
                content=content,
                parent_content=parent,
                grandparent_content=grandparent,
                row_index=idx,
            )
        units[key].ground_truth.append({
            "reference": str(row["reference"]).strip(),
            "relation": str(row["relation"]).strip(),
        })
    return list(units.values())


def load_distractor_units(dataset_path: Path) -> List[ClauseUnit]:
    """Load the hard-negative set as clause units with EMPTY ground truth.

    Each row is a clause where an action keyword appears but no valid relation
    exists, so any relation an architecture emits is a false positive. The
    distractor CSV has no ``reference``/``relation`` columns.
    """
    df = pd.read_csv(dataset_path, dtype=str).fillna("")
    df.columns = [c.lstrip("﻿") for c in df.columns]
    df["clause_type"] = df["clause_type"].str.strip().str.lower()

    units: List[ClauseUnit] = []
    for idx, row in df.iterrows():
        units.append(ClauseUnit(
            so_hieu=normalize_so_hieu_for_evaluation(str(row["so_hieu"]).strip()),
            title=str(row.get("title", "")).strip(),
            clause_type=str(row["clause_type"]).strip().lower(),
            content=str(row["content"]).strip(),
            parent_content=str(row["parent_content"]).strip(),
            grandparent_content=str(row["grandparent_content"]).strip(),
            ground_truth=[],  # hard negative: no valid relation
            row_index=idx,
        ))
    return units


def stratified_sample(units: List[ClauseUnit], n: int, seed: int = 13) -> List[ClauseUnit]:
    """Sample ``n`` clause units stratified by clause type and dominant relation.

    Keeps the relation/clause-type mix representative so a subset run (e.g. the
    Gemini control) is not skewed toward easy or rare cases.
    """
    if n >= len(units):
        return list(units)

    rng = random.Random(seed)
    strata: Dict[tuple, List[ClauseUnit]] = {}
    for u in units:
        dominant = u.ground_truth[0]["relation"] if u.ground_truth else "none"
        strata.setdefault((u.clause_type, dominant), []).append(u)

    sampled: List[ClauseUnit] = []
    total = len(units)
    for bucket in strata.values():
        take = max(1, round(len(bucket) * n / total))
        rng.shuffle(bucket)
        sampled.extend(bucket[:take])

    rng.shuffle(sampled)
    return sampled[:n]
