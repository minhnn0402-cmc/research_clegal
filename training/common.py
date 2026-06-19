"""Shared utilities for the offline training phases."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Sequence


AMENDMENT_RELATIONS = frozenset({"sua_doi", "bo_sung", "sua_doi_bo_sung"})
GUIDANCE_RELATIONS = frozenset({"quy_dinh_chi_tiet", "huong_dan"})


def relation_compatible(gold: str, proposed: str) -> bool:
    """Return whether two labels are compatible for candidate-validity training."""
    if gold == proposed:
        return True
    if gold in AMENDMENT_RELATIONS and proposed in AMENDMENT_RELATIONS:
        return True
    if gold in GUIDANCE_RELATIONS and proposed in GUIDANCE_RELATIONS:
        return True
    return False


def stable_id(*parts: Any, prefix: str = "") -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}"


def stable_split(group: str, train_ratio: float = 0.70, val_ratio: float = 0.15) -> str:
    """Assign a document group deterministically to train/validation/test."""
    bucket = int(hashlib.sha1(group.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if bucket < train_ratio:
        return "train"
    if bucket < train_ratio + val_ratio:
        return "validation"
    return "test"


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def wilson_lower_bound(successes: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    p = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p + z2 / (2.0 * total)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def choose_accept_threshold(
    probabilities: Sequence[float],
    labels: Sequence[int],
    target_precision: float,
    min_count: int,
) -> Dict[str, Any]:
    """Maximise accepted coverage subject to a Wilson precision lower bound."""
    best: Dict[str, Any] | None = None
    thresholds = sorted(set(float(p) for p in probabilities), reverse=True)
    for threshold in thresholds:
        selected = [i for i, value in enumerate(probabilities) if value >= threshold]
        if len(selected) < min_count:
            continue
        tp = sum(labels[i] == 1 for i in selected)
        lower = wilson_lower_bound(tp, len(selected))
        if lower < target_precision:
            continue
        candidate = {
            "threshold": threshold,
            "count": len(selected),
            "precision": tp / len(selected),
            "precision_lower_bound": lower,
        }
        if best is None or candidate["count"] > best["count"]:
            best = candidate
    return best or {
        "threshold": 1.000001,
        "count": 0,
        "precision": 0.0,
        "precision_lower_bound": 0.0,
    }


def choose_reject_threshold(
    probabilities: Sequence[float],
    labels: Sequence[int],
    target_negative_precision: float,
    min_count: int,
) -> Dict[str, Any]:
    """Maximise rejected coverage subject to a Wilson correctness lower bound."""
    best: Dict[str, Any] | None = None
    thresholds = sorted(set(float(p) for p in probabilities))
    for threshold in thresholds:
        selected = [i for i, value in enumerate(probabilities) if value <= threshold]
        if len(selected) < min_count:
            continue
        correct = sum(labels[i] == 0 for i in selected)
        lower = wilson_lower_bound(correct, len(selected))
        if lower < target_negative_precision:
            continue
        candidate = {
            "threshold": threshold,
            "count": len(selected),
            "negative_precision": correct / len(selected),
            "negative_precision_lower_bound": lower,
        }
        if best is None or candidate["count"] > best["count"]:
            best = candidate
    return best or {
        "threshold": -0.000001,
        "count": 0,
        "negative_precision": 0.0,
        "negative_precision_lower_bound": 0.0,
    }


def insert_markers(
    text: str,
    action_span: Sequence[int],
    reference_span: Sequence[int],
) -> str:
    """Insert non-overlapping action/reference markers into current-clause text."""
    spans = [
        (int(action_span[0]), int(action_span[1]), "[ACT]", "[/ACT]"),
        (int(reference_span[0]), int(reference_span[1]), "[REF]", "[/REF]"),
    ]
    valid = [
        span
        for span in spans
        if 0 <= span[0] < span[1] <= len(text)
    ]
    for start, end, opening, closing in sorted(valid, key=lambda item: item[0], reverse=True):
        text = text[:start] + opening + text[start:end] + closing + text[end:]
    return text


def build_marked_text(record: Dict[str, Any]) -> str:
    """Build the semantic-verifier input representation."""
    current = insert_markers(
        record.get("content", ""),
        record.get("action_span", [-1, -1]),
        record.get("reference_span", [-1, -1]),
    )
    if "[ACT]" not in current:
        action = record.get("action_text") or f"inherited:{record.get('proposed_relation', '')}"
        current = f"[ACT]{action}[/ACT] {current}"
    features = record.get("features", {})
    compact_features = "; ".join(
        f"{key}={features[key]}"
        for key in (
            "direction",
            "context_source",
            "char_distance",
            "hard_delimiter_count",
            "has_document_number",
            "has_clause_component",
        )
        if key in features
    )
    return "\n".join(
        [
            f"[RELATION] {record.get('proposed_relation', '')} [/RELATION]",
            f"[SOURCE] {record.get('so_hieu', '')} | {record.get('title', '')} [/SOURCE]",
            f"[GRANDPARENT] {record.get('grandparent_content', '')} [/GRANDPARENT]",
            f"[PARENT] {record.get('parent_content', '')} [/PARENT]",
            f"[CURRENT] {current} [/CURRENT]",
            f"[FEATURES] {compact_features} [/FEATURES]",
        ]
    )

