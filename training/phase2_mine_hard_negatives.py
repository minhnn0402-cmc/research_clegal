"""Phase 2: select difficult INVALID candidates for neural-model training."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from training.common import read_jsonl, write_jsonl


def hardness_score(record: dict) -> float:
    features = record.get("features") or {}
    distance = max(0.0, float(features.get("char_distance", 0.0)))
    score = 1.0 / (1.0 + distance / 20.0)
    if features.get("same_hard_scope"):
        score += 0.5
    if features.get("is_production_match"):
        score += 1.0
    if features.get("has_document_number"):
        score += 0.25
    if features.get("has_clause_component"):
        score += 0.25
    if features.get("action_count", 0) > 1 and features.get("reference_count", 0) > 1:
        score += 0.5
    return score


def mine(
    candidates_path: Path,
    output_path: Path,
    *,
    max_per_relation: int = 2000,
    include_unknown: bool = False,
) -> dict:
    buckets = defaultdict(list)
    allowed = {"INVALID", "UNKNOWN"} if include_unknown else {"INVALID"}
    for record in read_jsonl(candidates_path):
        if record.get("label") not in allowed:
            continue
        record["hardness_score"] = hardness_score(record)
        buckets[record.get("proposed_relation", "")].append(record)

    selected = []
    for relation, rows in buckets.items():
        rows.sort(key=lambda item: item["hardness_score"], reverse=True)
        selected.extend(rows[:max_per_relation])
    selected.sort(key=lambda item: item["hardness_score"], reverse=True)
    write_jsonl(output_path, selected)
    return {
        "source": str(candidates_path),
        "output": str(output_path),
        "selected": len(selected),
        "by_relation": dict(Counter(row.get("proposed_relation", "") for row in selected)),
        "include_unknown": include_unknown,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("training/data/generated/candidates.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/data/generated/hard_negatives.jsonl"),
    )
    parser.add_argument("--max-per-relation", type=int, default=2000)
    parser.add_argument("--include-unknown", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = mine(
        args.candidates,
        args.output,
        max_per_relation=args.max_per_relation,
        include_unknown=args.include_unknown,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

