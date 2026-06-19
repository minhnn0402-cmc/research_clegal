"""Prepare a clean, leakage-safe corpus for domain-adaptive pretraining."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional


try:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, UnicodeError):
    pass


_WHITESPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_PSEUDO_TABLE_OPEN = re.compile(r"\[TABLE\]", re.IGNORECASE)
_PSEUDO_TABLE_CLOSE = re.compile(r"\[(?:/|\\)TABLE\]", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_QH_NUMBER = re.compile(r"/(?P<year>\d{4})/QH(?P<term>\d+)\b", re.IGNORECASE)
_QH_TERM_BY_YEAR = (
    (2011, 2016, "QH13"),
    (2016, 2021, "QH14"),
    (2021, 2026, "QH15"),
)


class _TextHTMLParser(HTMLParser):
    """Strip tags while preserving readable boundaries and table markers."""

    _BLOCK_TAGS = frozenset(
        {
            "address",
            "article",
            "blockquote",
            "div",
            "dl",
            "dt",
            "dd",
            "figcaption",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "li",
            "main",
            "ol",
            "p",
            "section",
            "tr",
            "ul",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.table_depth = 0

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self.table_depth == 0:
                self.parts.append("\n[TABLE]\n")
            self.table_depth += 1
        elif tag in {"br", "hr"} or tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)
            if self.table_depth == 0:
                self.parts.append("\n[/TABLE]\n")
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def normalize_so_hieu(value: Any) -> str:
    """Normalize document numbers consistently for leakage checks."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    match = _QH_NUMBER.search(text)
    if match:
        year = int(match.group("year"))
        actual = f"QH{match.group('term')}"
        for start, end, expected in _QH_TERM_BY_YEAR:
            if start <= year <= end and actual.upper() != expected:
                text = (
                    text[: match.start("term") - 2]
                    + expected
                    + text[match.end("term") :]
                )
                break
    text = text.upper().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", text)


def load_golden_so_hieu(path: Path) -> set[str]:
    if not path.exists():
        return set()
    values = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = normalize_so_hieu(row.get("so_hieu"))
            if normalized:
                values.add(normalized)
    return values


def clean_legal_text(value: Any) -> str:
    """Remove HTML/control noise while preserving natural legal text."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = unicodedata.normalize("NFC", value)
    text = _CONTROL_CHARS.sub(" ", text)
    text = _PSEUDO_TABLE_OPEN.sub(" [TABLE] ", text)
    text = _PSEUDO_TABLE_CLOSE.sub(" [/TABLE] ", text)

    parser = _TextHTMLParser()
    try:
        parser.feed(text)
        parser.close()
        text = parser.text()
    except Exception:
        # HTMLParser is tolerant, but keep a deterministic fallback.
        text = html.unescape(text)

    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _WHITESPACE.sub(" ", line.replace("\u00a0", " ")).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines)
    text = _BLANK_LINES.sub("\n\n", text)
    text = text.replace("[TABLE]\n[TABLE]", "[TABLE]")
    text = text.replace("[/TABLE]\n[/TABLE]", "[/TABLE]")
    return text.strip()


def stable_validation_split(group: str, validation_ratio: float) -> str:
    bucket = int(hashlib.sha1(group.encode("utf-8")).hexdigest()[:8], 16)
    value = bucket / 0xFFFFFFFF
    return "validation" if value < validation_ratio else "train"


def iter_exported_documents(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if isinstance(value, dict):
                yield value


def write_json_line(handle: Any, row: Mapping[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    handle.write("\n")


def build_record(
    *,
    doc: Mapping[str, Any],
    text: str,
    record_type: str,
    clause: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    info = doc.get("cls_info") or {}
    record = {
        "doc_id": str(doc.get("cls_ID") or ""),
        "so_hieu": str(info.get("so_hieu") or ""),
        "document_type": str(info.get("loai_van_ban") or ""),
        "issue_date": str(info.get("ngay_ban_hanh") or ""),
        "record_type": record_type,
        "text": text,
    }
    if clause is not None:
        record.update(
            {
                "clause_key": str(clause.get("com_key") or ""),
                "clause_type": str(clause.get("com_type") or ""),
            }
        )
    return record


def evenly_spaced_sample(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Select deterministic positions across a long document, preserving order."""
    if limit <= 0 or len(rows) <= limit:
        return rows
    if limit == 1:
        return [rows[len(rows) // 2]]
    indices = {
        round(index * (len(rows) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [rows[index] for index in sorted(indices)]


def prepare_corpus(
    source: Path,
    output_dir: Path,
    *,
    golden_path: Path,
    validation_ratio: float = 0.05,
    min_chars: int = 20,
    max_clauses_per_document: int = 120,
    include_titles: bool = True,
    exclude_golden_overlap: bool = True,
) -> Dict[str, Any]:
    golden = load_golden_so_hieu(golden_path) if exclude_golden_overlap else set()
    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train.jsonl"
    validation_path = output_dir / "validation.jsonl"
    manifest_path = output_dir / "manifest.json"
    temp_train = train_path.with_suffix(".jsonl.tmp")
    temp_validation = validation_path.with_suffix(".jsonl.tmp")

    stats = Counter()
    split_docs = Counter()
    split_records = Counter()
    types = Counter()
    years = Counter()
    seen_text_hashes: set[str] = set()
    excluded_so_hieu: List[str] = []

    try:
        with temp_train.open("w", encoding="utf-8", newline="\n") as train_handle, (
            temp_validation.open("w", encoding="utf-8", newline="\n")
        ) as validation_handle:
            for doc in iter_exported_documents(source):
                stats["documents_seen"] += 1
                info = doc.get("cls_info") or {}
                so_hieu = str(info.get("so_hieu") or "")
                normalized_so_hieu = normalize_so_hieu(so_hieu)
                if normalized_so_hieu and normalized_so_hieu in golden:
                    stats["documents_excluded_golden_overlap"] += 1
                    if len(excluded_so_hieu) < 100:
                        excluded_so_hieu.append(so_hieu)
                    continue

                doc_id = str(doc.get("cls_ID") or normalized_so_hieu or so_hieu)
                split = stable_validation_split(doc_id, validation_ratio)
                output_handle = (
                    validation_handle if split == "validation" else train_handle
                )
                doc_record_count = 0
                local_text_hashes: set[str] = set()

                if include_titles:
                    title = clean_legal_text(info.get("title"))
                    if len(title) >= min_chars:
                        digest = hashlib.sha1(title.encode("utf-8")).hexdigest()
                        local_text_hashes.add(digest)
                        if digest not in seen_text_hashes:
                            seen_text_hashes.add(digest)
                            write_json_line(
                                output_handle,
                                build_record(
                                    doc=doc,
                                    text=title,
                                    record_type="document_title",
                                ),
                            )
                            split_records[split] += 1
                            doc_record_count += 1
                            stats["title_records"] += 1
                        else:
                            stats["records_deduplicated"] += 1

                clause_records: List[Dict[str, Any]] = []
                for clause in doc.get("cls_parsing") or []:
                    if not isinstance(clause, dict):
                        continue
                    text = clean_legal_text(clause.get("com_title"))
                    if len(text) < min_chars:
                        stats["records_too_short"] += 1
                        continue
                    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
                    if digest in local_text_hashes:
                        stats["records_deduplicated"] += 1
                        continue
                    local_text_hashes.add(digest)
                    clause_records.append(
                        build_record(
                            doc=doc,
                            text=text,
                            record_type="clause",
                            clause=clause,
                        )
                    )

                if (
                    max_clauses_per_document > 0
                    and len(clause_records) > max_clauses_per_document
                ):
                    stats["documents_clause_capped"] += 1
                    stats["records_removed_by_document_cap"] += (
                        len(clause_records) - max_clauses_per_document
                    )
                    clause_records = evenly_spaced_sample(
                        clause_records,
                        max_clauses_per_document,
                    )

                for record in clause_records:
                    text = record["text"]
                    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
                    if digest in seen_text_hashes:
                        stats["records_deduplicated"] += 1
                        continue
                    seen_text_hashes.add(digest)
                    write_json_line(
                        output_handle,
                        record,
                    )
                    split_records[split] += 1
                    doc_record_count += 1
                    stats["clause_records"] += 1
                    stats["clean_text_chars"] += len(text)

                if doc_record_count:
                    split_docs[split] += 1
                    types[str(info.get("loai_van_ban") or "<missing>")] += 1
                    year_text = str(info.get("ngay_ban_hanh") or "")
                    if len(year_text) >= 4 and year_text[:4].isdigit():
                        years[year_text[:4]] += 1
                else:
                    stats["documents_without_usable_records"] += 1

        os.replace(temp_train, train_path)
        os.replace(temp_validation, validation_path)
    except Exception:
        for path in (temp_train, temp_validation):
            if path.exists():
                path.unlink()
        raise

    manifest = {
        "source": str(source.resolve()),
        "golden_dataset": str(golden_path.resolve()),
        "output": {
            "train": str(train_path.resolve()),
            "validation": str(validation_path.resolve()),
        },
        "config": {
            "validation_ratio": validation_ratio,
            "min_chars": min_chars,
            "max_clauses_per_document": max_clauses_per_document,
            "include_titles": include_titles,
            "exclude_golden_overlap": exclude_golden_overlap,
        },
        "documents": dict(split_docs),
        "records": dict(split_records),
        "statistics": dict(stats),
        "document_types": dict(types),
        "years": dict(sorted(years.items())),
        "excluded_golden_so_hieu_sample": sorted(set(excluded_so_hieu)),
        "bytes": {
            "train": train_path.stat().st_size,
            "validation": validation_path.stat().st_size,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/exported_docs.jsonl"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("training/data/dapt"),
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path("evaluation/datasets/golden_eval.csv"),
    )
    parser.add_argument("--validation-ratio", type=float, default=0.05)
    parser.add_argument("--min-chars", type=int, default=20)
    parser.add_argument("--max-clauses-per-document", type=int, default=120)
    parser.add_argument("--skip-titles", action="store_true")
    parser.add_argument("--keep-golden-overlap", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if not 0.01 <= args.validation_ratio <= 0.25:
        raise SystemExit("--validation-ratio must be between 0.01 and 0.25.")
    if args.min_chars < 1:
        raise SystemExit("--min-chars must be positive.")
    if args.max_clauses_per_document < 0:
        raise SystemExit("--max-clauses-per-document must be >= 0.")
    manifest = prepare_corpus(
        args.source,
        args.output_dir,
        golden_path=args.golden,
        validation_ratio=args.validation_ratio,
        min_chars=args.min_chars,
        max_clauses_per_document=args.max_clauses_per_document,
        include_titles=not args.skip_titles,
        exclude_golden_overlap=not args.keep_golden_overlap,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
