"""Phase 1: train and calibrate a fast candidate-level feature model."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence

from training.common import (
    choose_accept_threshold,
    choose_reject_threshold,
    read_jsonl,
    stable_split,
)


def _require_ml_dependencies():
    try:
        import joblib
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import precision_recall_fscore_support, roc_auc_score
    except ImportError as exc:
        raise SystemExit(
            "Phase 1 requires training dependencies. Run: "
            "python -m pip install -r training/requirements.txt"
        ) from exc
    return joblib, DictVectorizer, LogisticRegression, precision_recall_fscore_support, roc_auc_score


def _feature_dict(record: Dict[str, Any]) -> Dict[str, Any]:
    features = dict(record.get("features") or {})
    features.update(
        {
            "proposed_relation": record.get("proposed_relation", ""),
            "candidate_source": record.get("candidate_source", ""),
            "clause_type": record.get("clause_type", ""),
        }
    )
    return features


def _fit_calibrator(raw_probabilities, labels, LogisticRegression):
    if len(set(labels)) < 2:
        return None
    calibrator = LogisticRegression(solver="lbfgs")
    calibrator.fit([[float(value)] for value in raw_probabilities], labels)
    return calibrator


def _apply_calibrator(raw_probabilities, calibrator):
    if calibrator is None:
        return [float(value) for value in raw_probabilities]
    return calibrator.predict_proba(
        [[float(value)] for value in raw_probabilities]
    )[:, 1].tolist()


def _classification_report(labels, probabilities, metric_fn, auc_fn) -> Dict[str, Any]:
    predictions = [int(value >= 0.5) for value in probabilities]
    precision, recall, f1, _ = metric_fn(
        labels,
        predictions,
        average="binary",
        zero_division=0,
    )
    report = {
        "count": len(labels),
        "positives": int(sum(labels)),
        "negatives": int(len(labels) - sum(labels)),
        "precision_at_0_5": float(precision),
        "recall_at_0_5": float(recall),
        "f1_at_0_5": float(f1),
    }
    if len(set(labels)) >= 2:
        report["roc_auc"] = float(auc_fn(labels, probabilities))
    return report


def _thresholds_by_relation(
    records: Sequence[Dict[str, Any]],
    probabilities: Sequence[float],
    labels: Sequence[int],
    *,
    target_precision: float,
    target_negative_precision: float,
    min_count: int,
) -> Dict[str, Any]:
    indices_by_relation: Dict[str, List[int]] = defaultdict(list)
    for index, record in enumerate(records):
        indices_by_relation[record.get("proposed_relation", "")].append(index)

    thresholds = {}
    for relation, indices in sorted(indices_by_relation.items()):
        relation_probs = [probabilities[index] for index in indices]
        relation_labels = [labels[index] for index in indices]
        thresholds[relation] = {
            "accept": choose_accept_threshold(
                relation_probs,
                relation_labels,
                target_precision,
                min_count,
            ),
            "reject": choose_reject_threshold(
                relation_probs,
                relation_labels,
                target_negative_precision,
                min_count,
            ),
        }
    thresholds["__global__"] = {
        "accept": choose_accept_threshold(
            probabilities,
            labels,
            target_precision,
            min_count,
        ),
        "reject": choose_reject_threshold(
            probabilities,
            labels,
            target_negative_precision,
            min_count,
        ),
    }
    return thresholds


def _routing_report(records, probabilities, labels, thresholds) -> Dict[str, Any]:
    counts = Counter()
    correct = Counter()
    for record, probability, label in zip(records, probabilities, labels):
        relation = record.get("proposed_relation", "")
        relation_thresholds = thresholds.get(relation, thresholds["__global__"])
        if probability >= relation_thresholds["accept"]["threshold"]:
            route = "ACCEPT"
            is_correct = label == 1
        elif probability <= relation_thresholds["reject"]["threshold"]:
            route = "REJECT"
            is_correct = label == 0
        else:
            route = "UNCERTAIN"
            is_correct = False
        counts[route] += 1
        if is_correct:
            correct[route] += 1
    total = len(records)
    return {
        "counts": dict(counts),
        "coverage": {
            key: value / total if total else 0.0
            for key, value in counts.items()
        },
        "decision_precision": {
            key: correct[key] / counts[key] if counts[key] else None
            for key in ("ACCEPT", "REJECT")
        },
    }


def train_feature_model(
    candidates_path: Path,
    artifact_dir: Path,
    *,
    model_name: str = "logistic",
    target_precision: float = 0.95,
    target_negative_precision: float = 0.95,
    min_threshold_count: int = 10,
) -> Dict[str, Any]:
    (
        joblib,
        DictVectorizer,
        LogisticRegression,
        metric_fn,
        auc_fn,
    ) = _require_ml_dependencies()

    records = [
        record
        for record in read_jsonl(candidates_path)
        if record.get("label") in {"VALID", "INVALID"}
    ]
    if not records:
        raise ValueError("No VALID/INVALID records found. Run Phase 0 first.")

    splits: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        splits[stable_split(str(record.get("so_hieu", "")))].append(record)

    if not splits["train"] or not splits["validation"] or not splits["test"]:
        raise ValueError(
            "Document-group split produced an empty partition. "
            "Use a larger dataset or inspect source document diversity."
        )

    vectorizer = DictVectorizer(sparse=True)
    train_x = vectorizer.fit_transform([_feature_dict(row) for row in splits["train"]])
    train_y = [int(row["label"] == "VALID") for row in splits["train"]]

    if model_name == "logistic":
        model = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            solver="liblinear",
            random_state=13,
        )
    elif model_name == "lightgbm":
        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:
            raise SystemExit(
                "LightGBM is not installed. Install training/requirements.txt "
                "or use --model logistic."
            ) from exc
        model = LGBMClassifier(
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=31,
            class_weight="balanced",
            random_state=13,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Unsupported model: {model_name}")

    model.fit(train_x, train_y)

    val_x = vectorizer.transform([_feature_dict(row) for row in splits["validation"]])
    val_y = [int(row["label"] == "VALID") for row in splits["validation"]]
    val_raw = model.predict_proba(val_x)[:, 1]
    calibrator = _fit_calibrator(val_raw, val_y, LogisticRegression)
    val_probabilities = _apply_calibrator(val_raw, calibrator)

    thresholds = _thresholds_by_relation(
        splits["validation"],
        val_probabilities,
        val_y,
        target_precision=target_precision,
        target_negative_precision=target_negative_precision,
        min_count=min_threshold_count,
    )

    test_x = vectorizer.transform([_feature_dict(row) for row in splits["test"]])
    test_y = [int(row["label"] == "VALID") for row in splits["test"]]
    test_raw = model.predict_proba(test_x)[:, 1]
    test_probabilities = _apply_calibrator(test_raw, calibrator)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = artifact_dir / "feature_model.joblib"
    joblib.dump(
        {
            "model_name": model_name,
            "vectorizer": vectorizer,
            "model": model,
            "calibrator": calibrator,
            "thresholds": thresholds,
            "feature_names": vectorizer.get_feature_names_out().tolist(),
        },
        bundle_path,
    )

    report = {
        "model": model_name,
        "dataset": str(candidates_path),
        "split_counts": {name: len(rows) for name, rows in splits.items()},
        "split_label_counts": {
            name: dict(Counter(row["label"] for row in rows))
            for name, rows in splits.items()
        },
        "validation": _classification_report(val_y, val_probabilities, metric_fn, auc_fn),
        "test": _classification_report(test_y, test_probabilities, metric_fn, auc_fn),
        "thresholds": thresholds,
        "validation_routing": _routing_report(
            splits["validation"],
            val_probabilities,
            val_y,
            thresholds,
        ),
        "test_routing": _routing_report(
            splits["test"],
            test_probabilities,
            test_y,
            thresholds,
        ),
        "artifact": str(bundle_path),
    }
    (artifact_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("training/data/generated/candidates.jsonl"),
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("training/artifacts/phase1"),
    )
    parser.add_argument("--model", choices=["logistic", "lightgbm"], default="logistic")
    parser.add_argument("--target-precision", type=float, default=0.95)
    parser.add_argument("--target-negative-precision", type=float, default=0.95)
    parser.add_argument("--min-threshold-count", type=int, default=10)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = train_feature_model(
        args.candidates,
        args.artifact_dir,
        model_name=args.model,
        target_precision=args.target_precision,
        target_negative_precision=args.target_negative_precision,
        min_threshold_count=args.min_threshold_count,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
