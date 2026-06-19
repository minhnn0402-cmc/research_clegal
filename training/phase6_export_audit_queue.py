"""Phase 6: score candidates with Phase 1 and export the abstention queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.common import read_jsonl, write_jsonl


def _require_dependencies():
    try:
        import joblib
    except ImportError as exc:
        raise SystemExit(
            "Phase 6 requires scikit-learn/joblib dependencies. Run: "
            "python -m pip install -r training/requirements.txt"
        ) from exc
    return joblib


def _feature_dict(record):
    features = dict(record.get("features") or {})
    features.update(
        {
            "proposed_relation": record.get("proposed_relation", ""),
            "candidate_source": record.get("candidate_source", ""),
            "clause_type": record.get("clause_type", ""),
        }
    )
    return features


def export_queue(
    candidates_path: Path,
    model_path: Path,
    output_path: Path,
    *,
    include_known_labels: bool = False,
) -> dict:
    joblib = _require_dependencies()
    bundle = joblib.load(model_path)
    records = list(read_jsonl(candidates_path))
    if not include_known_labels:
        records = [row for row in records if row.get("label") == "UNKNOWN"]
    if not records:
        write_jsonl(output_path, [])
        return {"candidates": 0, "abstained": 0, "output": str(output_path)}

    vectorizer = bundle["vectorizer"]
    model = bundle["model"]
    calibrator = bundle.get("calibrator")
    thresholds = bundle["thresholds"]
    matrix = vectorizer.transform([_feature_dict(row) for row in records])
    raw = model.predict_proba(matrix)[:, 1]
    if calibrator is None:
        probabilities = raw
    else:
        probabilities = calibrator.predict_proba(
            [[float(value)] for value in raw]
        )[:, 1]

    abstained = []
    routed = {"ACCEPT": 0, "REJECT": 0, "ABSTAIN": 0}
    for record, probability in zip(records, probabilities):
        relation = record.get("proposed_relation", "")
        relation_thresholds = thresholds.get(relation, thresholds["__global__"])
        accept_threshold = relation_thresholds["accept"]["threshold"]
        reject_threshold = relation_thresholds["reject"]["threshold"]
        if probability >= accept_threshold:
            route = "ACCEPT"
        elif probability <= reject_threshold:
            route = "REJECT"
        else:
            route = "ABSTAIN"
        routed[route] += 1
        if route == "ABSTAIN":
            enriched = dict(record)
            enriched["feature_model_probability"] = float(probability)
            enriched["distance_to_decision"] = float(
                min(
                    abs(probability - accept_threshold),
                    abs(probability - reject_threshold),
                )
            )
            abstained.append(enriched)

    abstained.sort(
        key=lambda row: (
            row.get("distance_to_decision", 1.0),
            row.get("proposed_relation", ""),
        )
    )
    write_jsonl(output_path, abstained)
    return {
        "candidates": len(records),
        "routes": routed,
        "abstained": len(abstained),
        "output": str(output_path),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("training/data/generated/candidates.jsonl"),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("training/artifacts/phase1/feature_model.joblib"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/data/generated/audit_queue.jsonl"),
    )
    parser.add_argument("--include-known-labels", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = export_queue(
        args.candidates,
        args.model,
        args.output,
        include_known_labels=args.include_known_labels,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

