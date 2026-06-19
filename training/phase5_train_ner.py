"""Phase 5: optional token-classification training for reference candidate recall."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _require_dependencies():
    try:
        import numpy as np
        import torch
        from datasets import load_dataset
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            DataCollatorForTokenClassification,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit(
            "Phase 5 requires training dependencies. Run: "
            "python -m pip install -r training/requirements.txt"
        ) from exc
    return (
        np,
        torch,
        load_dataset,
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )


def train(
    dataset_path: Path,
    output_dir: Path,
    *,
    model_id: str = "vinai/phobert-base-v2",
    epochs: float = 3.0,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
) -> dict:
    (
        np,
        torch,
        load_dataset,
        AutoModel,
        AutoTokenizer,
        DataCollator,
        Trainer,
        TrainingArguments,
    ) = _require_dependencies()

    dataset = load_dataset("json", data_files=str(dataset_path))["train"]
    required = {"tokens", "ner_tags"}
    if not required.issubset(dataset.column_names):
        raise ValueError(
            "NER JSONL must contain tokens and ner_tags arrays, plus optional label_names."
        )
    label_names = dataset[0].get("label_names") or [
        "O",
        "B-DOC",
        "I-DOC",
        "B-DOC_NUMBER",
        "I-DOC_NUMBER",
        "B-ARTICLE",
        "I-ARTICLE",
        "B-CLAUSE",
        "I-CLAUSE",
        "B-POINT",
        "I-POINT",
    ]
    split = dataset.train_test_split(test_size=0.15, seed=13)
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)

    def tokenize_and_align(batch):
        tokenized = tokenizer(
            batch["tokens"],
            truncation=True,
            is_split_into_words=True,
        )
        aligned = []
        for index, tags in enumerate(batch["ner_tags"]):
            word_ids = tokenized.word_ids(batch_index=index)
            previous = None
            labels = []
            for word_id in word_ids:
                if word_id is None:
                    labels.append(-100)
                elif word_id != previous:
                    labels.append(tags[word_id])
                else:
                    labels.append(-100)
                previous = word_id
            aligned.append(labels)
        tokenized["labels"] = aligned
        return tokenized

    tokenized = split.map(
        tokenize_and_align,
        batched=True,
        remove_columns=split["train"].column_names,
    )
    id2label = dict(enumerate(label_names))
    label2id = {label: index for index, label in id2label.items()}
    model = AutoModel.from_pretrained(
        model_id,
        num_labels=len(label_names),
        id2label=id2label,
        label2id=label2id,
    )
    collator = DataCollator(tokenizer)

    def compute_metrics(prediction):
        logits, labels = prediction
        predictions = np.argmax(logits, axis=-1)
        mask = labels != -100
        return {"token_accuracy": float((predictions[mask] == labels[mask]).mean())}

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
        report_to=[],
        seed=13,
        fp16=torch.cuda.is_available(),
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        tokenizer=tokenizer,
        data_collator=collator,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(str(output_dir / "model"))
    tokenizer.save_pretrained(str(output_dir / "model"))
    report = {
        "model_id": model_id,
        "dataset": str(dataset_path),
        "labels": label_names,
        "metrics": metrics,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training/artifacts/phase5_ner"),
    )
    parser.add_argument("--model-id", default="vinai/phobert-base-v2")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = train(
        args.dataset,
        args.output_dir,
        model_id=args.model_id,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
