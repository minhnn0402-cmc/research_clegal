"""
Evaluate relation extraction quality.

Expected dataset columns
------------------------
so_hieu
title
clause_type
content
parent_content
grandparent_content
reference
relation

Each row is one ground-truth ``(so_hieu, clause_type, reference, relation)`` pair. Rows that share
the same ``so_hieu + clause_type + content + parent_content +
grandparent_content`` belong to the same clause and are evaluated together.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict # For grouping EvalResults by relation type
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent # Two levels up from evaluation/evaluate.py
sys.path.insert(0, str(_PROJECT_ROOT)) # Look the project root first

from dotenv import load_dotenv
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")


from evaluation.converter import relations_to_flat
from evaluation.matcher import match_predictions_to_ground_truth
from evaluation.metrics import EvalResult, aggregate_by_relation, compute_metrics
from src.infrastructure.config import loai_van_ban_mapping
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader
from src.infrastructure.logging import get_logger

ClauseKey = Tuple[str, str, str, str, str]
REQUIRED_COLUMNS = (
    "so_hieu",
    "title",
    "clause_type",
    "content",
    "parent_content",
    "grandparent_content",
    "reference",
    "relation",
)
CLAUSE_ID_COLUMNS = (
    "so_hieu",
    "clause_type",
    "content",
    "parent_content",
    "grandparent_content",
)

_DOC_TYPE_NAMES = sorted(loai_van_ban_mapping.values(), key=len, reverse=True)
_TITLE_DOC_TYPE_PATTERN = re.compile(
    r"^\s*(?:\d+\.\s*)?(" + "|".join(re.escape(item) for item in _DOC_TYPE_NAMES) + r")\b",
    re.IGNORECASE,
)
_SO_HIEU_DOC_TYPE_PATTERNS = (
    (re.compile(r"NQ-?HĐND|NQ-?CP|NQ-?TW|NQ-?UBTVQH|NQLT", re.IGNORECASE), "Nghị quyết"),
    (re.compile(r"NĐ-?CP", re.IGNORECASE), "Nghị định"),
    (re.compile(r"TTLT", re.IGNORECASE), "Thông tư liên tịch"),
    (re.compile(r"TT-", re.IGNORECASE), "Thông tư"),
    (re.compile(r"QĐ-", re.IGNORECASE), "Quyết định"),
    (re.compile(r"CT-", re.IGNORECASE), "Chỉ thị"),
    (re.compile(r"CV-", re.IGNORECASE), "Công văn"),
    (re.compile(r"QH\d+", re.IGNORECASE), "Luật"),
)
_QH_TERM_BY_YEAR = (
    (2011, 2016, "QH13"),
    (2016, 2021, "QH14"),
    (2021, 2026, "QH15"),
)


def normalize_so_hieu_for_evaluation(so_hieu: str) -> str:
    """Normalize obvious benchmark typos in current document numbers."""
    value = (so_hieu or "").strip()
    match = re.search(r"/(?P<year>\d{4})/QH(?P<term>\d+)\b", value, re.IGNORECASE)
    if not match:
        return value

    year = int(match.group("year"))
    actual_term = f"QH{match.group('term')}"
    for start_year, end_year, expected_term in _QH_TERM_BY_YEAR:
        if start_year <= year <= end_year and actual_term.upper() != expected_term:
            return (
                value[:match.start("term") - 2]
                + expected_term
                + value[match.end("term"):]
            )

    return value


def infer_document_type(title: str, so_hieu: str) -> str:
    """Infer document type for benchmark clauses when source metadata is absent."""
    title_match = _TITLE_DOC_TYPE_PATTERN.search(title or "")
    if title_match:
        return title_match.group(1)

    for pattern, document_type in _SO_HIEU_DOC_TYPE_PATTERNS:
        if pattern.search(so_hieu or ""):
            return document_type

    return ""


def _make_clause(clause_type: str, clause_key: str, content: str) -> Dict:
    """Build a minimal clause node compatible with ``ContentExtractor``."""
    return {
        "com_type": clause_type,
        "com_key": clause_key,
        "com_title": content,
    }


def _build_clause_context(
    clause_type: str,
    content: str,
    parent_content: str,
    grandparent_content: str,
    idx: int,
) -> Tuple[List[Dict], Dict[str, str], Dict]:
    """
    Reconstruct the minimal hierarchy required by ``RelationsExtractor._process_clause``.
    """
    cur_key = f"eval_{idx}"
    parent_key = f"{cur_key}_parent"
    grandparent_key = f"{cur_key}_grandparent"

    # Create the current clause node
    clause = _make_clause(clause_type, cur_key, content)

    # For vanban and dieu, or if parent content is empty, we treat it as a standalone clause.
    if clause_type in {"vanban", "dieu"} or not parent_content.strip():
        return [clause], {}, clause

    # For khoan and diem, we need to create parent (and possibly grandparent) nodes.
    if clause_type == "khoan":
        parent_clause = _make_clause("dieu", parent_key, parent_content)
        return [parent_clause, clause], {cur_key: parent_key}, clause

    if clause_type == "diem":
        parent_clause = _make_clause("khoan", parent_key, parent_content)
        child_to_parent: Dict[str, str] = {cur_key: parent_key}

        if grandparent_content.strip():
            grandparent_clause = _make_clause("dieu", grandparent_key, grandparent_content)
            child_to_parent[parent_key] = grandparent_key
            return [grandparent_clause, parent_clause, clause], child_to_parent, clause

        return [parent_clause, clause], child_to_parent, clause

    return [clause], {}, clause


def extract_single_clause(
    extractor: RelationsExtractor,
    so_hieu: str,
    title: str,
    clause_type: str,
    content: str,
    parent_content: str,
    grandparent_content: str,
    idx: int,
    law_titles: List,
    cls_document_type: str = "",
    use_llm: bool = False,
    rejected_buffer: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Run the latest clause pipeline and flatten its grouped relation output."""
    data, child_to_parent, clause = _build_clause_context(
        clause_type=clause_type,
        content=content,
        parent_content=parent_content,
        grandparent_content=grandparent_content,
        idx=idx,
    )

    extractor.processed_clause_content_hashes.clear() # Clear cache to avoid cross-clause contamination during evaluation

    result = extractor._process_clause(
        data=data,
        child_to_parent=child_to_parent,
        clause=clause,
        law_titles=law_titles,
        cls_so_hieu=so_hieu,
        cls_title=title,
        cls_document_type=cls_document_type or infer_document_type(title, so_hieu),
        use_llm=use_llm,
        rejected_buffer=rejected_buffer,
    )

    return relations_to_flat(result or [])


def evaluate_dataset(
    df: pd.DataFrame,
    extractor: RelationsExtractor,
    law_titles: List,
    jaccard_threshold: float = 0.65,
    verbose: bool = False,
    use_llm: bool = False,
) -> List[Dict]:
    """Evaluate every unique clause in the dataset once."""
    groups: Dict[ClauseKey, Dict] = {}

    for idx, row in df.iterrows():
        so_hieu = normalize_so_hieu_for_evaluation(str(row["so_hieu"]).strip())
        title = str(row.get("title", "")).strip()
        clause_type = str(row["clause_type"]).strip().lower()
        content = str(row["content"]).strip()
        parent_content = str(row["parent_content"]).strip()
        grandparent_content = str(row["grandparent_content"]).strip()
        gt_reference = str(row["reference"]).strip()
        gt_relation = str(row["relation"]).strip()

        key: ClauseKey = (
            so_hieu,
            clause_type,
            content,
            parent_content,
            grandparent_content,
        )

        if key not in groups:
            groups[key] = {
                "so_hieu": so_hieu,
                "title": title,
                "clause_type": clause_type,
                "content": content,
                "parent_content": parent_content,
                "grandparent_content": grandparent_content,
                "ground_truth": [],
                "_first_idx": idx,
            }

        groups[key]["ground_truth"].append(
            {
                "reference": gt_reference,
                "relation": gt_relation,
            }
        )

    results: List[Dict] = []
    total = len(groups)
    
    def process_group(item: Tuple[int, Tuple[ClauseKey, Dict]]) -> Dict:
        idx_pos, (key, group) = item
        if verbose:
            print(f"  [{idx_pos}/{total}] so_hieu={group['so_hieu']}")
            
        predictions = extract_single_clause(
            extractor=extractor,
            so_hieu=group["so_hieu"],
            title=group["title"],
            clause_type=group["clause_type"],
            content=group["content"],
            parent_content=group["parent_content"],
            grandparent_content=group["grandparent_content"],
            idx=group["_first_idx"],
            law_titles=law_titles,
            use_llm=use_llm,
        )

        tp, fp, fn = match_predictions_to_ground_truth(
            group["ground_truth"],
            predictions,
            jaccard_threshold,
        )
        return {
            "clause_key": key,
            "so_hieu": group["so_hieu"],
            "title": group["title"],
            "clause_type": group["clause_type"],
            "content": group["content"],
            "parent_content": group["parent_content"],
            "grandparent_content": group["grandparent_content"],
            "ground_truth": group["ground_truth"],
            "predictions": predictions,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    # Use 16 threads by default for LLM concurrency
    max_workers = 8 if use_llm else 16
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_group, enumerate(groups.items(), 1)))

    return results


def _build_wrong_extraction_df(rows: List[Dict]) -> pd.DataFrame:
    """Flatten FP/FN items back into golden_eval.csv's schema plus an error_type column."""
    records: List[Dict] = []

    for row in rows:
        clause_fields = {
            "so_hieu": row["so_hieu"],
            "title": row["title"],
            "clause_type": row["clause_type"],
            "content": row["content"],
            "parent_content": row["parent_content"],
            "grandparent_content": row["grandparent_content"],
        }

        for item in row["fp"]:
            records.append({
                **clause_fields,
                "reference": item.get("reference", ""),
                "relation": item.get("relation", ""),
                "error_type": "FP",
            })

        for item in row["fn"]:
            records.append({
                **clause_fields,
                "reference": item.get("reference", ""),
                "relation": item.get("relation", ""),
                "error_type": "FN",
            })

    return pd.DataFrame(records, columns=list(REQUIRED_COLUMNS) + ["error_type"])


def _build_eval_result(rows: List[Dict], doc_id: str = "") -> EvalResult:
    all_tp = [item for row in rows for item in row["tp"]]
    all_fp = [item for row in rows for item in row["fp"]]
    all_fn = [item for row in rows for item in row["fn"]]
    return compute_metrics(all_tp, all_fp, all_fn, doc_id=doc_id)


def _breakdown_by_field(rows: List[Dict], field: str) -> Dict[str, EvalResult]:
    groups: Dict[str, List] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {key: _build_eval_result(value, doc_id=key) for key, value in sorted(groups.items())}


def _print_result(result: EvalResult, show_details: bool = False) -> None:
    print(result.summary())
    if not show_details:
        return

    if result.true_positives:
        print("  True Positives:")
        for item in result.true_positives:
            print(f"      [{item['relation']}] {item['reference']}")

    if result.false_positives:
        print("  False Positives:")
        for item in result.false_positives:
            print(f"      [{item['relation']}] {item['reference']}")

    if result.false_negatives:
        print("  False Negatives:")
        for item in result.false_negatives:
            print(f"      [{item.get('relation', '?')}] {item['reference']}")


def _print_table(breakdown: Dict[str, EvalResult], title: str) -> None:
    if not breakdown:
        return

    col = max(max((len(key) for key in breakdown), default=0) + 2, 14)
    header = (
        f"  {'Group':<{col}}"
        f"{'TP':>6}  {'FP':>6}  {'FN':>6}  "
        f"{'Precision':>10}  {'Recall':>8}  {'F1':>8}"
    )
    separator = "  " + "-" * (len(header) - 2)

    print(f"\n{'=' * 60}")
    print(title)
    print(f"{'=' * 60}")
    print(header)
    print(separator)

    for key, result in breakdown.items():
        print(
            f"  {key:<{col}}"
            f"{result.tp:>6}  {result.fp:>6}  {result.fn:>6}  "
            f"{result.precision:>10.3f}  {result.recall:>8.3f}  {result.f1:>8.3f}"
        )

    print(separator)


def evaluate_pipeline(
    dataset_path: str,
    output_path: Optional[str] = None,
    clause_type: Optional[str] = None,
    jaccard_threshold: float = 0.65,
    use_llm: bool = False,
    verbose: bool = False,
    wrong_csv_path: Optional[str] = None,
) -> Dict:
    """
    Externally callable entry point for the evaluation logic.
    Returns a dictionary containing OVERALL, BY_CLAUSE_TYPE, and BY_RELATION metrics.
    """
    dataset_path_obj = Path(dataset_path)
    if not dataset_path_obj.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    df = pd.read_csv(dataset_path_obj, sep=",", dtype=str).fillna("")
    df["clause_type"] = df["clause_type"].str.strip().str.lower()

    if clause_type:
        df = df[df["clause_type"] == clause_type.lower()].reset_index(drop=True)

    config = ConfigLoader()
    logger = get_logger("LegalRelationsEvaluator")
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
        logger=logger,
    )

    rows = evaluate_dataset(
        df=df,
        extractor=extractor,
        law_titles=config.law_titles_for_regex,
        jaccard_threshold=jaccard_threshold,
        verbose=verbose,
        use_llm=use_llm,
    )

    overall = _build_eval_result(rows, doc_id="OVERALL")
    by_clause_type = _breakdown_by_field(rows, "clause_type")
    
    per_row_results = [compute_metrics(row["tp"], row["fp"], row["fn"]) for row in rows]
    by_relation = aggregate_by_relation(per_row_results)

    final_report = {
        "overall": overall.to_dict(),
        "by_clause_type": {k: v.to_dict() for k, v in by_clause_type.items()},
        "by_relation_type": {k: v.to_dict() for k, v in by_relation.items()},
    }

    if output_path:
        out_path_obj = Path(output_path)
        out_path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path_obj, "w", encoding="utf-8") as file:
            json.dump(final_report, file, ensure_ascii=False, indent=2)

    if wrong_csv_path:
        wrong_csv_obj = Path(wrong_csv_path)
        wrong_csv_obj.parent.mkdir(parents=True, exist_ok=True)
        _build_wrong_extraction_df(rows).to_csv(wrong_csv_obj, index=False, encoding="utf-8-sig")

    return final_report


def main(argv: Optional[List[str]] = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Evaluate relation extraction on legal_relations.csv.",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        type=Path,
        required=True,
        help=(
            "CSV file with columns: so_hieu, clause_type, content, "
            "parent_content, grandparent_content, reference, relation."
        ),
    )
    parser.add_argument(
        "--sep",
        default=",",
        help="CSV separator (default: comma). Use \\t for TSV.",
    )
    parser.add_argument(
        "--clause-type",
        default=None,
        help="Evaluate only one clause type (vanban, dieu, khoan, diem).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional path for a JSON report.",
    )
    parser.add_argument(
        "--breakdown",
        action="store_true",
        default=False,
        help="Show per-clause-type and per-relation-type tables.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        default=False,
        help="Print TP, FP, and FN items.",
    )
    parser.add_argument(
        "--jaccard-threshold",
        type=float,
        default=0.65,
        metavar="THRESH",
        help="Jaccard threshold for fallback reference matching (default 0.65).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print per-clause extraction progress.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Allow LLM-assisted extraction.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        default=False,
        help="Clear LLM fallback cache before evaluation.",
    )
    parser.add_argument(
        "--wrong-csv",
        type=Path,
        default=Path("evaluation/datasets/report/wrong_extraction.csv"),
        help="Path for the FP/FN CSV export (golden_eval.csv schema + error_type column).",
    )
    parser.add_argument(
        "--skip-wrong-csv",
        action="store_true",
        default=False,
        help="Do not export the wrong_extraction.csv file.",
    )

    args = parser.parse_args(argv)
    
    if args.clear_cache:
        cache_dir = Path(".cache/legal_extraction/llm_fallback")
        if cache_dir.exists():
            print(f"Clearing LLM cache: {cache_dir}")
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            print("Cache directory does not exist, nothing to clear.")

    print(f"Dataset  : {args.dataset}")
    print("Extracting...")
    
    results = evaluate_pipeline(
        dataset_path=str(args.dataset),
        output_path=str(args.output) if args.output else None,
        clause_type=args.clause_type,
        jaccard_threshold=args.jaccard_threshold,
        use_llm=args.use_llm,
        verbose=args.verbose,
        wrong_csv_path=None if args.skip_wrong_csv else str(args.wrong_csv),
    )
    
    overall_res = EvalResult(
        tp=results["overall"]["tp"],
        fp=results["overall"]["fp"],
        fn=results["overall"]["fn"],
        true_positives=results["overall"]["true_positives"],
        false_positives=results["overall"]["false_positives"],
        false_negatives=results["overall"]["false_negatives"],
        doc_id="OVERALL"
    )

    print(f"\n{'=' * 60}")
    print("OVERALL")
    print(f"{'=' * 60}")
    _print_result(overall_res, show_details=args.details)

    if args.breakdown:
        # Reconstruct by_clause_type breakdown
        by_clause_type = {
            k: EvalResult(
                tp=v["tp"], 
                fp=v["fp"], 
                fn=v["fn"],
                true_positives=v["true_positives"],
                false_positives=v["false_positives"],
                false_negatives=v["false_negatives"],
                doc_id=k
            )
            for k, v in results["by_clause_type"].items()
        }
        _print_table(by_clause_type, "BY CLAUSE TYPE")

        # Reconstruct by_relation_type breakdown
        by_relation = {
            k: EvalResult(
                tp=v["tp"], 
                fp=v["fp"], 
                fn=v["fn"],
                true_positives=v["true_positives"],
                false_positives=v["false_positives"],
                false_negatives=v["false_negatives"],
                doc_id=k
            )
            for k, v in results["by_relation_type"].items()
        }
        _print_table(by_relation, "BY RELATION TYPE")

    if args.output:
        # The file is already saved within evaluate_pipeline if output_path was passed.
        # If not already saved or if we want to ensure it, we can do it here.
        if not (args.output.exists()):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as file:
                json.dump(results, file, ensure_ascii=False, indent=2)
        print(f"\nReport saved to: {args.output}")

    if not args.skip_wrong_csv:
        print(f"Wrong extractions saved to: {args.wrong_csv}")


if __name__ == "__main__":
    main()
