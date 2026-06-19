"""Phase 0: build candidate-level datasets and candidate-recall reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import List

from training.common import write_jsonl


def build_candidates(
    golden_path: Path,
    output_path: Path,
    summary_path: Path,
    *,
    distractor_path: Path | None = None,
    assume_exhaustive: bool = False,
    top_k_near_miss: int = 2,
    limit: int | None = None,
) -> dict:
    try:
        from experiment.clause_dataset import load_clause_units, load_distractor_units
        from training.candidate_generator import CandidateGenerator, coverage_summary
    except ImportError as exc:
        raise SystemExit(
            "Phase 0 requires the repository runtime dependencies. Run: "
            "python -m pip install -r requirements.txt"
        ) from exc

    generator = CandidateGenerator(top_k_near_miss=top_k_near_miss)
    golden_units = load_clause_units(golden_path)
    if limit:
        golden_units = golden_units[:limit]

    all_records = []
    records_by_clause = defaultdict(list)
    for index, unit in enumerate(golden_units, 1):
        records = generator.generate(
            unit,
            assume_exhaustive=assume_exhaustive,
        )
        all_records.extend(records)
        records_by_clause[unit.key].extend(records)
        if index % 50 == 0:
            print(f"[phase0] golden clauses: {index}/{len(golden_units)}")

    distractor_count = 0
    if distractor_path:
        distractor_units = load_distractor_units(distractor_path)
        if limit:
            distractor_units = distractor_units[:limit]
        for unit in distractor_units:
            records = generator.generate(unit, hard_negative=True)
            distractor_count += len(records)
            all_records.extend(records)

    write_jsonl(output_path, all_records)
    labels = Counter(record["label"] for record in all_records)
    sources = Counter(record["candidate_source"] for record in all_records)
    summary = {
        "golden_dataset": str(golden_path),
        "distractor_dataset": str(distractor_path) if distractor_path else None,
        "clauses": len(golden_units),
        "candidates": len(all_records),
        "distractor_candidates": distractor_count,
        "labels": dict(labels),
        "candidate_sources": dict(sources),
        "assume_exhaustive": assume_exhaustive,
        "top_k_near_miss": top_k_near_miss,
        "coverage": coverage_summary(golden_units, records_by_clause),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path("evaluation/datasets/golden_eval.csv"),
    )
    parser.add_argument(
        "--distractors",
        type=Path,
        default=Path("evaluation/datasets/distractor_candidates.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/data/generated/candidates.jsonl"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("training/artifacts/phase0_summary.json"),
    )
    parser.add_argument("--top-k-near-miss", type=int, default=2)
    parser.add_argument("--assume-exhaustive", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-distractors", action="store_true")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_candidates(
        golden_path=args.golden,
        distractor_path=None if args.skip_distractors else args.distractors,
        output_path=args.output,
        summary_path=args.summary,
        assume_exhaustive=args.assume_exhaustive,
        top_k_near_miss=args.top_k_near_miss,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
