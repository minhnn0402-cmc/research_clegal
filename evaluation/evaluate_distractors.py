"""
Evaluate false-positive rate on distractor candidates.

Distractor candidates are clauses that contain action-like keywords but should
NOT produce any legal relation.  A candidate is a false positive when the
extractor emits at least one relation for it.

Expected dataset columns
------------------------
so_hieu
title
clause_type
content
parent_content
grandparent_content
keyword
reason_not_relation
suggested_label
audit_status
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.evaluate import extract_single_clause, normalize_so_hieu_for_evaluation, infer_document_type
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader
from src.infrastructure.logging import get_logger

REQUIRED_COLUMNS = (
    "so_hieu",
    "title",
    "clause_type",
    "content",
    "parent_content",
    "grandparent_content",
    "keyword",
    "reason_not_relation",
)

_AMBIGUOUS_REASON_PREFIX = "Có keyword giống action relationship nhưng extractor không xác định"


def _load_and_validate(dataset_path: Path) -> pd.DataFrame:
    df = pd.read_csv(dataset_path, dtype=str).fillna("")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in distractor CSV: {missing}")
    df["clause_type"] = df["clause_type"].str.strip().str.lower()
    return df


def run_distractor_evaluation(
    df: pd.DataFrame,
    extractor: RelationsExtractor,
    law_titles: List,
    clause_type_filter: Optional[str],
    verbose: bool,
    track_rejections: bool = True,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Returns (fp_items, all_items, all_rejected) where:
    - fp_items: rows where extractor produced at least one relation (false positives)
    - all_items: every processed row
    - all_rejected: every relation rejected by DistractorFilter across all candidates
    """
    if clause_type_filter:
        df = df[df["clause_type"] == clause_type_filter.lower()].reset_index(drop=True)

    fp_items: List[Dict] = []
    all_items: List[Dict] = []
    all_rejected: List[Dict] = []
    total = len(df)

    for idx, row in df.iterrows():
        so_hieu = normalize_so_hieu_for_evaluation(str(row["so_hieu"]).strip())
        title = str(row.get("title", "")).strip()
        clause_type = str(row["clause_type"]).strip().lower()
        content = str(row["content"]).strip()
        parent_content = str(row["parent_content"]).strip()
        grandparent_content = str(row["grandparent_content"]).strip()
        keyword = str(row.get("keyword", "")).strip()
        reason = str(row.get("reason_not_relation", "")).strip()

        if verbose:
            print(f"  [{idx + 1}/{total}] so_hieu={so_hieu} keyword={keyword!r}")

        local_rejected: Optional[List[Dict]] = [] if track_rejections else None

        predictions = extract_single_clause(
            extractor=extractor,
            so_hieu=so_hieu,
            title=title,
            clause_type=clause_type,
            content=content,
            parent_content=parent_content,
            grandparent_content=grandparent_content,
            idx=int(idx),
            law_titles=law_titles,
            cls_document_type=infer_document_type(title, so_hieu),
            rejected_buffer=local_rejected,
        )

        if track_rejections and local_rejected:
            all_rejected.extend(local_rejected)

        item = {
            "so_hieu": so_hieu,
            "title": title,
            "clause_type": clause_type,
            "content": content,
            "keyword": keyword,
            "reason_not_relation": reason,
            "extracted_relations": predictions,
            "is_fp": len(predictions) > 0,
            "is_ambiguous": reason.startswith(_AMBIGUOUS_REASON_PREFIX) and len(predictions) > 0,
        }
        all_items.append(item)
        if item["is_fp"]:
            fp_items.append(item)

    return fp_items, all_items, all_rejected


def build_report(
    fp_items: List[Dict],
    all_items: List[Dict],
    all_rejected: Optional[List[Dict]] = None,
) -> Dict:
    fp_by_keyword: Dict[str, int] = defaultdict(int)
    fp_by_clause_type: Dict[str, int] = defaultdict(int)
    fp_by_reason: Dict[str, int] = defaultdict(int)
    ambiguous_cases: List[Dict] = []

    for item in fp_items:
        fp_by_keyword[item["keyword"]] += 1
        fp_by_clause_type[item["clause_type"]] += 1

        reason = item["reason_not_relation"]
        reason_key = reason[:80] if len(reason) > 80 else reason
        fp_by_reason[reason_key] += 1

        if item["is_ambiguous"]:
            ambiguous_cases.append({
                "so_hieu": item["so_hieu"],
                "clause_type": item["clause_type"],
                "keyword": item["keyword"],
                "content": item["content"][:200],
                "extracted_relations": item["extracted_relations"],
            })

    serializable_fp_items = [
        {
            "so_hieu": it["so_hieu"],
            "clause_type": it["clause_type"],
            "keyword": it["keyword"],
            "content": it["content"][:300],
            "reason_not_relation": it["reason_not_relation"],
            "extracted_relations": it["extracted_relations"],
        }
        for it in fp_items
    ]

    # Aggregate rejection reasons from DistractorFilter (new rules)
    rejection_reason_distribution: Dict[str, int] = defaultdict(int)
    for r in (all_rejected or []):
        rule_name = r.get("rejection_reason", "unknown").split(":")[0].strip()
        rejection_reason_distribution[rule_name] += 1

    return {
        "total_candidates": len(all_items),
        "fp_count": len(fp_items),
        "fp_rate": round(len(fp_items) / len(all_items), 4) if all_items else 0.0,
        "fp_by_keyword": dict(sorted(fp_by_keyword.items(), key=lambda x: -x[1])),
        "fp_by_clause_type": dict(sorted(fp_by_clause_type.items(), key=lambda x: -x[1])),
        "fp_by_reason": dict(sorted(fp_by_reason.items(), key=lambda x: -x[1])),
        "rejection_reason_distribution": dict(sorted(rejection_reason_distribution.items(), key=lambda x: -x[1])),
        "ambiguous_count": len(ambiguous_cases),
        "ambiguous_cases": ambiguous_cases,
        "fp_items": serializable_fp_items,
    }


def compare_reports(before: Dict, after: Dict) -> None:
    """Print a side-by-side before/after comparison table."""
    b_total = before["total_candidates"]
    b_fp = before["fp_count"]
    a_fp = after["fp_count"]
    reduction = b_fp - a_fp
    reduction_pct = round(reduction / b_fp * 100, 1) if b_fp else 0.0

    print(f"\n{'=' * 60}")
    print("BEFORE / AFTER COMPARISON")
    print(f"{'=' * 60}")
    print(f"  Total candidates : {b_total}")
    print(f"  FP before        : {b_fp}  ({before['fp_rate'] * 100:.1f}%)")
    print(f"  FP after         : {a_fp}  ({after['fp_rate'] * 100:.1f}%)")
    print(f"  Reduction        : {reduction} ({reduction_pct}%)")
    print(f"  Ambiguous (after): {after['ambiguous_count']}")

    print(f"\n{'─' * 40}")
    print("  FP by keyword (after):")
    for kw, count in after["fp_by_keyword"].items():
        b_count = before["fp_by_keyword"].get(kw, 0)
        print(f"    {kw:<30} {b_count:>4} → {count:>4}")

    if after.get("rejection_reason_distribution"):
        print(f"\n{'─' * 40}")
        print("  Rejection reasons:")
        for reason, count in after["rejection_reason_distribution"].items():
            print(f"    {count:>4}  {reason}")


def evaluate_distractors_pipeline(
    dataset_path: str,
    output_path: Optional[str] = None,
    clause_type: Optional[str] = None,
    verbose: bool = False,
    before_report_path: Optional[str] = None,
    after_report_path: Optional[str] = None,
) -> Dict:
    """Externally callable entry point. Returns the full report dict."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Distractor dataset not found: {dataset_path}")

    df = _load_and_validate(path)
    config = ConfigLoader()
    logger = get_logger("DistractorEvaluator")
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
        logger=logger,
    )

    fp_items, all_items, all_rejected = run_distractor_evaluation(
        df=df,
        extractor=extractor,
        law_titles=config.law_titles_for_regex,
        clause_type_filter=clause_type,
        verbose=verbose,
        track_rejections=True,
    )

    report = build_report(fp_items, all_items, all_rejected)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    if before_report_path and after_report_path:
        before = json.loads(Path(before_report_path).read_text(encoding="utf-8"))
        after = json.loads(Path(after_report_path).read_text(encoding="utf-8"))
        compare_reports(before, after)
    elif before_report_path:
        before = json.loads(Path(before_report_path).read_text(encoding="utf-8"))
        compare_reports(before, report)

    return report


def main(argv: Optional[List[str]] = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Evaluate false-positive rate on distractor candidates.",
    )
    parser.add_argument("--dataset", "-d", type=Path, required=False)
    parser.add_argument("--clause-type", default=None)
    parser.add_argument("--output", "-o", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    parser.add_argument(
        "--before-report",
        type=Path,
        default=None,
        help="JSON report from a previous run to compare against.",
    )
    parser.add_argument(
        "--after-report",
        type=Path,
        default=None,
        help="JSON report produced after filtering to compare against --before-report.",
    )
    args = parser.parse_args(argv)

    # Comparison-only mode: both reports supplied, no dataset needed
    if args.before_report and args.after_report and not args.dataset:
        before = json.loads(args.before_report.read_text(encoding="utf-8"))
        after = json.loads(args.after_report.read_text(encoding="utf-8"))
        compare_reports(before, after)
        return

    if not args.dataset:
        parser.error("--dataset is required unless both --before-report and --after-report are provided")

    print(f"Dataset  : {args.dataset}")
    print("Running extractor on distractor candidates...")

    report = evaluate_distractors_pipeline(
        dataset_path=str(args.dataset),
        output_path=str(args.output) if args.output else None,
        clause_type=args.clause_type,
        verbose=args.verbose,
        before_report_path=str(args.before_report) if args.before_report else None,
    )

    print(f"\n{'=' * 60}")
    print("DISTRACTOR EVALUATION RESULTS")
    print(f"{'=' * 60}")
    print(f"  Total candidates : {report['total_candidates']}")
    print(f"  False positives  : {report['fp_count']} ({report['fp_rate'] * 100:.1f}%)")
    print(f"  Ambiguous cases  : {report['ambiguous_count']}")

    if report["fp_by_keyword"]:
        print(f"\n{'─' * 40}")
        print("  FP by keyword:")
        for kw, count in report["fp_by_keyword"].items():
            print(f"    {kw:<30} {count}")

    if report["fp_by_clause_type"]:
        print(f"\n{'─' * 40}")
        print("  FP by clause type:")
        for ct, count in report["fp_by_clause_type"].items():
            print(f"    {ct:<20} {count}")

    if report.get("rejection_reason_distribution"):
        print(f"\n{'─' * 40}")
        print("  Rejection reasons (DistractorFilter rules fired):")
        for rule, count in report["rejection_reason_distribution"].items():
            print(f"    {count:>4}  {rule}")

    if report["fp_items"]:
        print(f"\n{'─' * 40}")
        print("  False positive items:")
        for item in report["fp_items"]:
            print(f"    [{item['clause_type']}] so_hieu={item['so_hieu']} keyword={item['keyword']!r}")
            for rel in item["extracted_relations"]:
                print(f"        → [{rel['relation']}] {rel['reference']}")

    if args.output:
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    main()
