"""Phase 3: fine-tune PhoBERT as a binary candidate verifier."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from training.common import build_marked_text, read_jsonl, stable_split


SPECIAL_TOKENS = [
    "[RELATION]",
    "[/RELATION]",
    "[SOURCE]",
    "[/SOURCE]",
    "[GRANDPARENT]",
    "[/GRANDPARENT]",
    "[PARENT]",
    "[/PARENT]",
    "[CURRENT]",
    "[/CURRENT]",
    "[FEATURES]",
    "[/FEATURES]",
    "[ACT]",
    "[/ACT]",
    "[REF]",
    "[/REF]",
]


def _require_dependencies():
    try:
        import numpy as np
        import torch
        from sklearn.metrics import precision_recall_fscore_support
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit(
            "Phase 3 requires neural training dependencies. Run: "
            "python -m pip install -r training/requirements.txt"
        ) from exc
    return (
        np,
        torch,
        precision_recall_fscore_support,
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )


def train(
    candidates_path: Path,
    output_dir: Path,
    *,
    model_id: str = "vinai/phobert-base-v2",
    max_length: int = 512,
    epochs: float = 3.0,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
) -> dict:
    (
        np,
        torch,
        metric_fn,
        AutoModel,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    ) = _require_dependencies()

    records = [
        row
        for row in read_jsonl(candidates_path)
        if row.get("label") in {"VALID", "INVALID"}
    ]
    splits = {"train": [], "validation": [], "test": []}
    for row in records:
        splits[stable_split(str(row.get("so_hieu", "")))].append(row)
    if any(not rows for rows in splits.values()):
        raise ValueError("An empty document-group split was produced.")

    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
    tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})
    model = AutoModel.from_pretrained(model_id, num_labels=2)
    model.resize_token_embeddings(len(tokenizer))

    class CandidateDataset(torch.utils.data.Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, index):
            row = self.rows[index]
            encoded = tokenizer(
                build_marked_text(row),
                truncation=True,
                max_length=max_length,
                padding=False,
            )
            encoded["labels"] = int(row["label"] == "VALID")
            return encoded

    def compute_metrics(eval_prediction):
        logits, labels = eval_prediction
        predictions = np.argmax(logits, axis=-1)
        precision, recall, f1, _ = metric_fn(
            labels,
            predictions,
            average="binary",
            zero_division=0,
        )
        return {
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "accuracy": float((predictions == labels).mean()),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(output_dir),
        learning_rate=learning_rate,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        num_train_epochs=epochs,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_f1",
        greater_is_better=True,
        logging_steps=25,
        report_to=[],
        seed=13,
        fp16=torch.cuda.is_available(),
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=CandidateDataset(splits["train"]),
        eval_dataset=CandidateDataset(splits["validation"]),
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    test_metrics = trainer.evaluate(CandidateDataset(splits["test"]), metric_key_prefix="test")
    trainer.save_model(str(output_dir / "model"))
    tokenizer.save_pretrained(str(output_dir / "model"))

    report = {
        "model_id": model_id,
        "dataset": str(candidates_path),
        "split_counts": {key: len(value) for key, value in splits.items()},
        "split_labels": {
            key: dict(Counter(row["label"] for row in value))
            for key, value in splits.items()
        },
        "test_metrics": test_metrics,
    }
    (output_dir / "report.json").write_text(
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
        "--output-dir",
        type=Path,
        default=Path("training/artifacts/phase3_phobert"),
    )
    parser.add_argument("--model-id", default="vinai/phobert-base-v2")
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = train(
        args.candidates,
        args.output_dir,
        model_id=args.model_id,
        max_length=args.max_length,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
