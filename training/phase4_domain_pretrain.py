"""Phase 4: domain-adaptive masked-language-model pretraining."""

from __future__ import annotations

import argparse
import json
import math
import os
from itertools import chain
from pathlib import Path


def _require_dependencies():
    try:
        import torch
        from datasets import DatasetDict, load_dataset
        from transformers import (
            AutoModelForMaskedLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
        from transformers.trainer_utils import get_last_checkpoint
    except ImportError as exc:
        raise SystemExit(
            "Phase 4 requires training dependencies. On Kaggle run: "
            "bash training/kaggle/setup.sh"
        ) from exc
    return (
        torch,
        DatasetDict,
        load_dataset,
        AutoModelForMaskedLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
        get_last_checkpoint,
    )


def _resolve_split_file(corpus_path: Path, split_name: str) -> Path:
    candidates = (
        corpus_path / f"{split_name}.jsonl",
        corpus_path / f"{split_name}.jsonl.gz",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Missing {split_name}.jsonl or {split_name}.jsonl.gz in {corpus_path}"
    )


def train(
    corpus_path: Path,
    output_dir: Path,
    *,
    model_id: str = "vinai/phobert-base-v2",
    max_length: int = 256,
    epochs: float = 1.0,
    batch_size: int = 16,
    learning_rate: float = 5e-5,
    mlm_probability: float = 0.15,
    gradient_accumulation_steps: int = 1,
    preprocessing_workers: int = 1,
    dataloader_workers: int = 2,
    save_steps: int = 500,
    eval_steps: int = 500,
    logging_steps: int = 25,
    save_total_limit: int = 2,
    warmup_ratio: float = 0.06,
    weight_decay: float = 0.01,
    resume_from_checkpoint: str | None = None,
    seed: int = 13,
) -> dict:
    (
        torch,
        DatasetDict,
        load_dataset,
        AutoModel,
        AutoTokenizer,
        DataCollator,
        Trainer,
        TrainingArguments,
        get_last_checkpoint,
    ) = _require_dependencies()
    if not corpus_path.exists():
        raise FileNotFoundError(corpus_path)

    if corpus_path.is_dir():
        train_path = _resolve_split_file(corpus_path, "train")
        validation_path = _resolve_split_file(corpus_path, "validation")
        split = load_dataset(
            "json",
            data_files={
                "train": str(train_path),
                "validation": str(validation_path),
            },
        )
    elif corpus_path.suffix.lower() == ".jsonl":
        dataset = load_dataset("json", data_files={"train": str(corpus_path)})["train"]
        random_split = dataset.train_test_split(test_size=0.05, seed=13)
        split = DatasetDict(
            train=random_split["train"],
            validation=random_split["test"],
        )
    else:
        dataset = load_dataset("text", data_files={"train": str(corpus_path)})["train"]
        random_split = dataset.train_test_split(test_size=0.05, seed=13)
        split = DatasetDict(
            train=random_split["train"],
            validation=random_split["test"],
        )
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            return_special_tokens_mask=True,
            add_special_tokens=True,
        )

    tokenized = split.map(
        tokenize,
        batched=True,
        remove_columns=split["train"].column_names,
        num_proc=preprocessing_workers,
        desc="Tokenizing DAPT corpus",
    )

    def group_texts(batch):
        concatenated = {
            key: list(chain.from_iterable(batch[key]))
            for key in batch
        }
        total_length = len(concatenated["input_ids"])
        total_length = (total_length // max_length) * max_length
        if total_length == 0:
            return {key: [] for key in concatenated}
        return {
            key: [
                values[index : index + max_length]
                for index in range(0, total_length, max_length)
            ]
            for key, values in concatenated.items()
        }

    tokenized = tokenized.map(
        group_texts,
        batched=True,
        batch_size=1000,
        num_proc=preprocessing_workers,
        desc=f"Grouping tokens into {max_length}-token blocks",
    )
    model = AutoModel.from_pretrained(model_id)
    collator = DataCollator(
        tokenizer=tokenizer,
        mlm=True,
        mlm_probability=mlm_probability,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(output_dir),
        learning_rate=learning_rate,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        num_train_epochs=epochs,
        eval_strategy="steps",
        save_strategy="steps",
        eval_steps=eval_steps,
        save_steps=save_steps,
        logging_steps=logging_steps,
        save_total_limit=save_total_limit,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        dataloader_num_workers=dataloader_workers,
        dataloader_pin_memory=torch.cuda.is_available(),
        ddp_find_unused_parameters=False,
        report_to=[],
        seed=seed,
        data_seed=seed,
        fp16=torch.cuda.is_available(),
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        tokenizer=tokenizer,
        data_collator=collator,
    )

    checkpoint: str | bool | None = None
    if resume_from_checkpoint:
        if resume_from_checkpoint == "auto":
            checkpoint = get_last_checkpoint(str(output_dir))
        else:
            checkpoint = resume_from_checkpoint

    train_result = trainer.train(resume_from_checkpoint=checkpoint)
    metrics = trainer.evaluate()
    eval_loss = metrics.get("eval_loss")
    perplexity = (
        float(math.exp(eval_loss))
        if isinstance(eval_loss, (int, float)) and eval_loss < 100
        else None
    )

    report = {
        "model_id": model_id,
        "corpus": str(corpus_path),
        "train_records": len(split["train"]),
        "validation_records": len(split["validation"]),
        "train_chunks": len(tokenized["train"]),
        "validation_chunks": len(tokenized["validation"]),
        "max_length": max_length,
        "world_size": int(os.environ.get("WORLD_SIZE", "1")),
        "per_device_batch_size": batch_size,
        "gradient_accumulation_steps": gradient_accumulation_steps,
        "effective_global_batch_size": (
            batch_size
            * gradient_accumulation_steps
            * int(os.environ.get("WORLD_SIZE", "1"))
        ),
        "resumed_from_checkpoint": checkpoint,
        "train_metrics": train_result.metrics,
        "metrics": metrics,
        "perplexity": perplexity,
    }
    if trainer.is_world_process_zero():
        model_dir = output_dir / "model"
        trainer.save_model(str(model_dir))
        tokenizer.save_pretrained(str(model_dir))
        (output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training/artifacts/phase4_legal_phobert"),
    )
    parser.add_argument("--model-id", default="vinai/phobert-base-v2")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--mlm-probability", type=float, default=0.15)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    parser.add_argument("--preprocessing-workers", type=int, default=1)
    parser.add_argument("--dataloader-workers", type=int, default=2)
    parser.add_argument("--save-steps", type=int, default=500)
    parser.add_argument("--eval-steps", type=int, default=500)
    parser.add_argument("--logging-steps", type=int, default=25)
    parser.add_argument("--save-total-limit", type=int, default=2)
    parser.add_argument("--warmup-ratio", type=float, default=0.06)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument(
        "--resume-from-checkpoint",
        nargs="?",
        const="auto",
        default=None,
        help="Checkpoint path, or omit the value to auto-resume from output-dir.",
    )
    parser.add_argument("--seed", type=int, default=13)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = train(
        args.corpus,
        args.output_dir,
        model_id=args.model_id,
        max_length=args.max_length,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        mlm_probability=args.mlm_probability,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        preprocessing_workers=args.preprocessing_workers,
        dataloader_workers=args.dataloader_workers,
        save_steps=args.save_steps,
        eval_steps=args.eval_steps,
        logging_steps=args.logging_steps,
        save_total_limit=args.save_total_limit,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        resume_from_checkpoint=args.resume_from_checkpoint,
        seed=args.seed,
    )
    if int(os.environ.get("RANK", "0")) == 0:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
