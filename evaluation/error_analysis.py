"""Error analysis helpers for relation extraction benchmark runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from evaluation.evaluate import evaluate_dataset
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader
from src.infrastructure.logging import get_logger


def _empty_counts() -> Dict[str, int]:
    return {"tp": 0, "fp": 0, "fn": 0}


def _sample_item(row: Dict, item: Dict, bucket: str) -> Dict:
    return {
        "bucket": bucket,
        "relation": item.get("relation", "?"),
        "reference": item.get("reference"),
        "clause_type": row.get("clause_type", ""),
        "so_hieu": row.get("so_hieu", ""),
        "content": row.get("content", ""),
        "parent_content": row.get("parent_content", ""),
        "grandparent_content": row.get("grandparent_content", ""),
    }


def summarize_errors(rows: Iterable[Dict], sample_limit: int = 10) -> Dict:
    """Summarize TP/FP/FN by relation and clause type with bounded samples."""
    overall = _empty_counts()
    by_relation: Dict[str, Dict[str, int]] = defaultdict(_empty_counts)
    by_clause_type: Dict[str, Dict[str, int]] = defaultdict(_empty_counts)
    relation_samples: Dict[str, Dict[str, List[Dict]]] = defaultdict(
        lambda: {"tp": [], "fp": [], "fn": []}
    )
    clause_samples: Dict[str, Dict[str, List[Dict]]] = defaultdict(
        lambda: {"tp": [], "fp": [], "fn": []}
    )

    for row in rows:
        clause_type = str(row.get("clause_type", "") or "?")
        for bucket in ("tp", "fp", "fn"):
            for item in row.get(bucket, []) or []:
                relation = str(item.get("relation", "") or "?")
                overall[bucket] += 1
                by_relation[relation][bucket] += 1
                by_clause_type[clause_type][bucket] += 1

                sample = _sample_item(row, item, bucket)
                if len(relation_samples[relation][bucket]) < sample_limit:
                    relation_samples[relation][bucket].append(sample)
                if len(clause_samples[clause_type][bucket]) < sample_limit:
                    clause_samples[clause_type][bucket].append(sample)

    return {
        "overall": dict(overall),
        "by_relation": {
            key: dict(value)
            for key, value in sorted(by_relation.items())
        },
        "by_clause_type": {
            key: dict(value)
            for key, value in sorted(by_clause_type.items())
        },
        "samples": {
            "by_relation": {
                key: {bucket: list(items) for bucket, items in value.items()}
                for key, value in sorted(relation_samples.items())
            },
            "by_clause_type": {
                key: {bucket: list(items) for bucket, items in value.items()}
                for key, value in sorted(clause_samples.items())
            },
        },
    }


def build_error_analysis_report(
    dataset_path: str,
    sample_limit: int = 10,
    use_llm: bool = False,
) -> Dict:
    """Run extraction evaluation and summarize current errors."""
    df = pd.read_csv(dataset_path, sep=",", dtype=str).fillna("")
    df["clause_type"] = df["clause_type"].str.strip().str.lower()

    config = ConfigLoader()
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
        logger=get_logger("ErrorAnalysis"),
    )
    rows = evaluate_dataset(
        df=df,
        extractor=extractor,
        law_titles=config.law_titles_for_regex,
        use_llm=use_llm,
    )

    return summarize_errors(rows, sample_limit=sample_limit)


def main(argv: Optional[List[str]] = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Summarize benchmark TP/FP/FN errors.")
    parser.add_argument("--dataset", required=True, help="Evaluation CSV path.")
    parser.add_argument("--output", required=True, help="JSON report output path.")
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--use-llm", action="store_true", default=False)
    args = parser.parse_args(argv)

    report = build_error_analysis_report(
        dataset_path=args.dataset,
        sample_limit=args.sample_limit,
        use_llm=args.use_llm,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    main()
