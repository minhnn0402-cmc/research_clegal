#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Export a compact, stratified legal-document corpus for the training POC.

The exporter deliberately uses two phases:

1. Scan only lightweight metadata and keep bounded reservoirs per
   (year bucket, relation bucket).
2. Fetch full ``cls_parsing`` only for reserve candidates, validate it, remove
   heavy/duplicated fields, and write accepted documents atomically as JSONL.

This avoids the previous failure mode where "latest documents" were mostly
technical standards and where HTML/embeddings made a 3k-document file >2 GB.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# These are normative/legal document families used by the relation extractor.
# Technical standards and regulations are intentionally excluded: words such
# as "thay thế" or "bổ sung" have a different semantic distribution there.
ALLOWED_DOCUMENT_TYPES: Tuple[str, ...] = (
    "Hiến pháp",
    "Bộ luật",
    "Luật",
    "Pháp lệnh",
    "Nghị định",
    "Nghị quyết",
    "Nghị quyết liên tịch",
    "Thông tư",
    "Thông tư liên tịch",
    "Quyết định",
    "Chỉ thị",
    "Công văn",
    "Công điện",
    "Lệnh",
    "Sắc lệnh",
    "Văn bản hợp nhất",
)

SUPPORTED_CLAUSE_TYPES = frozenset({"vanban", "dieu", "khoan", "diem"})

YEAR_BUCKETS: Tuple[str, ...] = ("Y1", "Y2", "Y3", "Y4")
RELATION_BUCKETS: Tuple[str, ...] = ("R1", "R2", "R3", "R4")

# 40% 2024-2026, 30% 2020-2023, 20% 2015-2019, 10% older.
YEAR_WEIGHTS: Mapping[str, float] = {
    "Y1": 0.40,
    "Y2": 0.30,
    "Y3": 0.20,
    "Y4": 0.10,
}

# R1 amendment/repeal; R2 citation/guidance; R3 effectiveness/status; R4 random.
RELATION_WEIGHTS: Mapping[str, float] = {
    "R1": 0.40,
    "R2": 0.30,
    "R3": 0.15,
    "R4": 0.15,
}

RELATION_LUOC_DO_KEYS: Mapping[str, Tuple[str, ...]] = {
    "R1": (
        "van_ban_sua_doi_bo_sung",
        "van_ban_duoc_sua_doi",
        "van_ban_duoc_sua_doi_bo_sung",
        "van_ban_bi_bai_bo",
        "van_ban_bi_bai_bo_mot_phan",
        "van_ban_bi_huy_bo",
        "van_ban_bi_huy_bo_mot_phan",
        "van_ban_bi_thay_the",
        "van_ban_bi_thay_the_mot_phan",
        "van_ban_thay_the",
    ),
    "R2": (
        "van_ban_can_cu",
        "van_ban_dan_chieu",
        "van_ban_quy_dinh_chi_tiet",
        "van_ban_huong_dan",
        "van_ban_duoc_huong_dan",
    ),
    "R3": (
        "van_ban_bi_dinh_chi",
        "van_ban_bi_dinh_chi_mot_phan",
        "van_ban_dinh_chinh",
        "van_ban_bi_dinh_chinh",
        "van_ban_hop_nhat",
        "van_ban_duoc_hop_nhat",
        "van_ban_gia_han",
        "van_ban_ngung_hieu_luc",
    ),
}

RELATION_TITLE_TERMS: Mapping[str, Tuple[str, ...]] = {
    "R1": ("sửa đổi", "bổ sung", "bãi bỏ", "hủy bỏ", "thay thế"),
    "R2": ("dẫn chiếu", "căn cứ", "quy định chi tiết", "hướng dẫn"),
    "R3": (
        "hiệu lực",
        "đình chỉ",
        "đính chính",
        "hợp nhất",
        "kéo dài",
        "tạm ngưng",
    ),
}

INFO_FIELDS: Tuple[str, ...] = (
    "so_hieu",
    "trich_yeu",
    "title",
    "title_without_number",
    "title_suggest",
    "tinh_trang_hieu_luc",
    "ngay_ban_hanh",
    "ngay_co_hieu_luc",
    "ngay_dang_cong_bao",
    "ngay_het_hieu_luc_mot_phan",
    "ngay_het_hieu_luc",
    "co_quan_ban_hanh",
    "loai_van_ban",
    "don_vi",
    "linh_vuc",
    "dia_danh",
    "type_of_van_ban",
)

# Enough for the current extractor and hierarchy reconstruction. Explicitly
# omit com_html, all embeddings, and com_titles_content (duplicates com_title).
CLAUSE_FIELDS: Tuple[str, ...] = (
    "com_key",
    "com_path",
    "com_type",
    "com_title",
    "com_name",
    "com_titles_name",
)


@dataclass(frozen=True)
class Candidate:
    cls_id: Any
    year_bucket: str
    relation_bucket: str
    document_type: str
    authority: str


@dataclass
class Reservoir:
    capacity: int
    rng: random.Random
    items: List[Candidate] = field(default_factory=list)
    seen: int = 0

    def add(self, item: Candidate) -> None:
        """Uniform bounded reservoir sampling for one coarse bucket."""
        self.seen += 1
        if len(self.items) < self.capacity:
            self.items.append(item)
            return
        replacement = self.rng.randrange(self.seen)
        if replacement < self.capacity:
            self.items[replacement] = item


def load_repo_env(env_path: Path) -> Dict[str, str]:
    """Merge .env values into process environment without logging secrets."""
    env = dict(os.environ)
    if not env_path.exists():
        return env
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise SystemExit(
            "python-dotenv is required. Run: python -m pip install -r requirements.txt"
        ) from exc
    for key, value in dotenv_values(env_path).items():
        if key and value is not None:
            env[str(key)] = str(value)
    return env


def build_mongo_client(env: Mapping[str, str], database: str) -> Any:
    """Create and verify a MongoDB client."""
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise SystemExit(
            "pymongo is required. Run: python -m pip install -r requirements.txt"
        ) from exc

    host = env.get("MONGO_PROD_HOST")
    if not host:
        raise ValueError("Missing MONGO_PROD_HOST.")

    last_error: Optional[Exception] = None
    for auth_source in (database, "admin", None):
        client = None
        try:
            kwargs: Dict[str, Any] = {
                "host": host,
                "port": int(env.get("MONGO_PROD_PORT", "27017")),
                "username": env.get("MONGO_PROD_USER"),
                "password": env.get("MONGO_PROD_PASSWORD"),
                "serverSelectionTimeoutMS": 8_000,
                "connectTimeoutMS": 15_000,
                "socketTimeoutMS": 120_000,
                "maxPoolSize": 4,
                "retryReads": True,
            }
            if auth_source:
                kwargs["authSource"] = auth_source
            client = MongoClient(**kwargs)
            client.admin.command("ping")
            return client
        except Exception as exc:
            last_error = exc
            if client is not None:
                client.close()
    raise RuntimeError(f"Mongo connection failed: {last_error}")


def parse_year(value: Any) -> Optional[int]:
    if isinstance(value, datetime):
        return value.year
    text = str(value or "").strip()
    if len(text) < 4:
        return None
    try:
        year = int(text[:4])
    except ValueError:
        return None
    return year if 1800 <= year <= 2100 else None


def classify_year(value: Any) -> str:
    year = parse_year(value)
    if year is not None and 2024 <= year <= 2026:
        return "Y1"
    if year is not None and 2020 <= year <= 2023:
        return "Y2"
    if year is not None and 2015 <= year <= 2019:
        return "Y3"
    return "Y4"


def _has_values(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, bytearray, Sequence, Mapping)):
        return len(value) > 0
    return bool(value)


def classify_relation(doc: Mapping[str, Any]) -> str:
    """Coarse sampling label; this is not a relation ground-truth label."""
    info = doc.get("cls_info") or {}
    title = " ".join(
        str(info.get(key) or "")
        for key in ("title", "title_without_number", "trich_yeu")
    ).lower()
    luoc_do = doc.get("cls_luoc_do") or {}

    # Priority is intentional: amendment/repeal docs first, then status docs,
    # then generic citation/guidance docs.
    for bucket in ("R1", "R3", "R2"):
        if any(
            _has_values(luoc_do.get(key))
            for key in RELATION_LUOC_DO_KEYS[bucket]
        ):
            return bucket
        if any(term in title for term in RELATION_TITLE_TERMS[bucket]):
            return bucket
    return "R4"


def classify_authority(info: Mapping[str, Any]) -> str:
    location = str(info.get("dia_danh") or "").lower()
    units = info.get("don_vi") or []
    authority = str(info.get("co_quan_ban_hanh") or "").lower()
    combined = " ".join(
        [location, authority]
        + [str(item).lower() for item in units if item is not None]
    )
    local_markers = (
        "tỉnh ",
        "thành phố ",
        "hđnd",
        "ubnd",
        "ủy ban nhân dân",
        "hội đồng nhân dân",
    )
    if any(marker in combined for marker in local_markers):
        return "local"
    return "central"


def allocate_counts(total: int, weights: Mapping[str, float]) -> Dict[str, int]:
    """Largest-remainder allocation, preserving an exact total."""
    raw = {key: total * weight for key, weight in weights.items()}
    allocated = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(allocated.values())
    insertion_order = {key: index for index, key in enumerate(weights)}
    ranked = sorted(
        weights,
        key=lambda key: (
            -(raw[key] - allocated[key]),
            -weights[key],
            insertion_order[key],
        ),
    )
    for key in ranked[:remainder]:
        allocated[key] += 1
    return allocated


def build_cell_targets(limit: int) -> Dict[Tuple[str, str], int]:
    year_targets = allocate_counts(limit, YEAR_WEIGHTS)
    targets: Dict[Tuple[str, str], int] = {}
    for year_bucket, year_total in year_targets.items():
        relation_targets = allocate_counts(year_total, RELATION_WEIGHTS)
        for relation_bucket, count in relation_targets.items():
            targets[(year_bucket, relation_bucket)] = count
    return targets


def year_query(bucket: str) -> Dict[str, Any]:
    # Production export currently stores ISO strings. Supporting BSON datetimes
    # would require an OR query and can be added if the source schema changes.
    if bucket == "Y1":
        return {"$gte": "2024-01-01", "$lt": "2027-01-01"}
    if bucket == "Y2":
        return {"$gte": "2020-01-01", "$lt": "2024-01-01"}
    if bucket == "Y3":
        return {"$gte": "2015-01-01", "$lt": "2020-01-01"}
    return {"$lt": "2015-01-01"}


def extract_parsing(doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Decode supported cls_parsing shapes without retaining raw compressed data."""
    parsing = doc.get("cls_parsing")
    if isinstance(parsing, list):
        return [item for item in parsing if isinstance(item, dict)]
    if not isinstance(parsing, dict):
        return []
    raw = parsing.get("parsing")
    if not raw:
        return []
    try:
        if isinstance(raw, str):
            raw = raw.encode("latin1")
        decoded = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return []
    return [item for item in decoded if isinstance(item, dict)] if isinstance(decoded, list) else []


def compact_info(info: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: info[key]
        for key in INFO_FIELDS
        if key in info and info[key] not in (None, "", [], {})
    }


def compact_parsing(
    parsing: Iterable[Mapping[str, Any]],
    *,
    max_clause_chars: int,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Keep only extractor-supported clauses and reject pathological outliers."""
    compact: List[Dict[str, Any]] = []
    seen_keys = set()
    for clause in parsing:
        clause_type = str(clause.get("com_type") or "").lower().strip()
        if clause_type not in SUPPORTED_CLAUSE_TYPES:
            continue
        title = clause.get("com_title")
        if not isinstance(title, str) or not title.strip():
            continue
        if len(title) > max_clause_chars:
            return [], "oversized_clause"

        clause_key = str(clause.get("com_key") or "").strip()
        dedupe_key = (clause_key, clause_type, title)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        row = {
            key: clause[key]
            for key in CLAUSE_FIELDS
            if key in clause and clause[key] not in (None, "", [], {})
        }
        row["com_type"] = clause_type
        compact.append(row)

    if not compact:
        return [], "no_supported_clause_text"
    return compact, None


def document_text_hash(parsing: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha1()
    for clause in parsing:
        digest.update(str(clause.get("com_type") or "").encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(clause.get("com_title") or "").encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def compact_document(
    doc: Mapping[str, Any],
    candidate: Candidate,
    *,
    max_clause_chars: int,
    max_document_chars: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    info = doc.get("cls_info") or {}
    document_type = str(info.get("loai_van_ban") or "")
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        return None, "disallowed_document_type", None
    if not info.get("so_hieu") or not info.get("title"):
        return None, "missing_identity_metadata", None

    parsing, reason = compact_parsing(
        extract_parsing(doc),
        max_clause_chars=max_clause_chars,
    )
    if reason:
        return None, reason, None
    text_chars = sum(len(str(row.get("com_title") or "")) for row in parsing)
    if text_chars > max_document_chars:
        return None, "oversized_document", None

    text_hash = document_text_hash(parsing)
    compact = {
        "cls_ID": doc.get("cls_ID"),
        "cls_info": compact_info(info),
        "cls_parsing": parsing,
        "_sample": {
            "year_bucket": candidate.year_bucket,
            "relation_bucket": candidate.relation_bucket,
            "authority": classify_authority(info),
            "supported_clause_count": len(parsing),
            "supported_text_chars": text_chars,
        },
    }
    return compact, None, text_hash


def round_robin_candidates(
    candidates: Sequence[Candidate],
    rng: random.Random,
) -> List[Candidate]:
    """Order candidates to alternate document types and authority levels."""
    groups: MutableMapping[Tuple[str, str], List[Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[(candidate.document_type, candidate.authority)].append(candidate)
    for rows in groups.values():
        rng.shuffle(rows)

    keys = sorted(groups)
    rng.shuffle(keys)
    ordered: List[Candidate] = []
    while keys:
        next_keys = []
        for key in keys:
            rows = groups[key]
            if rows:
                ordered.append(rows.pop())
            if rows:
                next_keys.append(key)
        keys = next_keys
    return ordered


def chunked(values: Sequence[Candidate], size: int) -> Iterator[Sequence[Candidate]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def metadata_projection() -> Dict[str, int]:
    return {
        "_id": 0,
        "cls_ID": 1,
        "cls_info.so_hieu": 1,
        "cls_info.title": 1,
        "cls_info.title_without_number": 1,
        "cls_info.trich_yeu": 1,
        "cls_info.ngay_ban_hanh": 1,
        "cls_info.loai_van_ban": 1,
        "cls_info.co_quan_ban_hanh": 1,
        "cls_info.dia_danh": 1,
        "cls_info.don_vi": 1,
        "cls_luoc_do": 1,
    }


def full_projection() -> Dict[str, int]:
    projection = {
        "_id": 0,
        "cls_ID": 1,
        "cls_parsing": 1,
    }
    for field_name in INFO_FIELDS:
        projection[f"cls_info.{field_name}"] = 1
    return projection


def scan_candidate_reservoirs(
    collection: Any,
    targets: Mapping[Tuple[str, str], int],
    *,
    reserve_multiplier: int,
    scan_limit_per_year: int,
    seed: int,
    batch_size: int,
) -> Tuple[Dict[Tuple[str, str], Reservoir], Counter]:
    reservoirs = {
        cell: Reservoir(
            capacity=max(target * reserve_multiplier, target + 25),
            rng=random.Random(f"{seed}:{cell[0]}:{cell[1]}"),
        )
        for cell, target in targets.items()
    }
    stats: Counter = Counter()

    base_query = {
        "cls_ID": {"$exists": True, "$ne": None},
        "cls_info.loai_van_ban": {"$in": list(ALLOWED_DOCUMENT_TYPES)},
        "cls_parsing": {"$exists": True, "$ne": None},
    }

    for year_bucket in YEAR_BUCKETS:
        query = dict(base_query)
        query["cls_info.ngay_ban_hanh"] = year_query(year_bucket)
        cursor = collection.find(
            query,
            metadata_projection(),
            no_cursor_timeout=True,
        ).batch_size(batch_size)
        if scan_limit_per_year > 0:
            cursor = cursor.limit(scan_limit_per_year)
        try:
            for doc in cursor:
                stats["metadata_scanned"] += 1
                info = doc.get("cls_info") or {}
                actual_year_bucket = classify_year(info.get("ngay_ban_hanh"))
                relation_bucket = classify_relation(doc)
                document_type = str(info.get("loai_van_ban") or "")
                candidate = Candidate(
                    cls_id=doc.get("cls_ID"),
                    year_bucket=actual_year_bucket,
                    relation_bucket=relation_bucket,
                    document_type=document_type,
                    authority=classify_authority(info),
                )
                reservoirs[(actual_year_bucket, relation_bucket)].add(candidate)
        finally:
            cursor.close()
        print(
            f"  metadata {year_bucket}: scanned="
            f"{sum(res.seen for (year, _), res in reservoirs.items() if year == year_bucket):,}"
        )
    return reservoirs, stats


def fetch_documents(
    collection: Any,
    candidates: Sequence[Candidate],
) -> Dict[Any, Dict[str, Any]]:
    ids = [candidate.cls_id for candidate in candidates]
    cursor = collection.find(
        {"cls_ID": {"$in": ids}},
        full_projection(),
    )
    return {doc.get("cls_ID"): doc for doc in cursor}


def can_accept_type(
    document_type: str,
    type_counts: Mapping[str, int],
    *,
    max_per_type: int,
) -> bool:
    return type_counts.get(document_type, 0) < max_per_type


def write_json_line(handle: Any, row: Mapping[str, Any]) -> None:
    json.dump(
        row,
        handle,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    handle.write("\n")


def export_documents(
    collection: Any,
    reservoirs: Mapping[Tuple[str, str], Reservoir],
    targets: Mapping[Tuple[str, str], int],
    out_path: Path,
    *,
    limit: int,
    fetch_batch_size: int,
    max_type_share: float,
    max_clause_chars: int,
    max_document_chars: int,
    seed: int,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    ordered_by_cell = {
        cell: round_robin_candidates(reservoir.items, rng)
        for cell, reservoir in reservoirs.items()
    }
    attempted_ids = set()
    accepted_ids = set()
    accepted_hashes = set()
    type_counts: Counter = Counter()
    year_counts: Counter = Counter()
    relation_counts: Counter = Counter()
    authority_counts: Counter = Counter()
    reject_counts: Counter = Counter()
    cell_counts: Counter = Counter()
    max_per_type = max(1, math.ceil(limit * max_type_share))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    def process_candidates(
        candidates: Sequence[Candidate],
        handle: Any,
        *,
        cell: Optional[Tuple[str, str]],
        target: int,
    ) -> int:
        added = 0
        for batch in chunked(candidates, fetch_batch_size):
            unseen = [
                candidate
                for candidate in batch
                if candidate.cls_id not in attempted_ids
            ]
            if not unseen:
                continue
            attempted_ids.update(candidate.cls_id for candidate in unseen)
            docs = fetch_documents(collection, unseen)
            for candidate in unseen:
                if added >= target or len(accepted_ids) >= limit:
                    break
                doc = docs.get(candidate.cls_id)
                if doc is None:
                    reject_counts["not_found_on_full_fetch"] += 1
                    continue
                compact, reason, text_hash = compact_document(
                    doc,
                    candidate,
                    max_clause_chars=max_clause_chars,
                    max_document_chars=max_document_chars,
                )
                if reason:
                    reject_counts[reason] += 1
                    continue
                assert compact is not None and text_hash is not None
                document_type = str(compact["cls_info"].get("loai_van_ban") or "")
                if not can_accept_type(
                    document_type,
                    type_counts,
                    max_per_type=max_per_type,
                ):
                    reject_counts["document_type_cap"] += 1
                    continue
                if text_hash in accepted_hashes:
                    reject_counts["duplicate_supported_text"] += 1
                    continue

                write_json_line(handle, compact)
                accepted_ids.add(candidate.cls_id)
                accepted_hashes.add(text_hash)
                type_counts[document_type] += 1
                year_counts[candidate.year_bucket] += 1
                relation_counts[candidate.relation_bucket] += 1
                authority_counts[compact["_sample"]["authority"]] += 1
                if cell is not None:
                    cell_counts[cell] += 1
                added += 1
            if added >= target or len(accepted_ids) >= limit:
                break
        return added

    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        for cell in sorted(targets):
            target = targets[cell]
            added = process_candidates(
                ordered_by_cell[cell],
                handle,
                cell=cell,
                target=target,
            )
            print(f"  cell {cell}: accepted={added}/{target}")

        # Backfill from all unattempted reserves if validation caused deficits.
        deficit = limit - len(accepted_ids)
        if deficit > 0:
            backfill_pool = [
                candidate
                for rows in ordered_by_cell.values()
                for candidate in rows
                if candidate.cls_id not in attempted_ids
            ]
            rng.shuffle(backfill_pool)
            added = process_candidates(
                backfill_pool,
                handle,
                cell=None,
                target=deficit,
            )
            print(f"  backfill: accepted={added}/{deficit}")

    # Never destroy the previous usable corpus after a failed/empty export.
    if accepted_ids:
        os.replace(temp_path, out_path)
    elif temp_path.exists():
        temp_path.unlink()

    return {
        "requested": limit,
        "exported": len(accepted_ids),
        "complete": len(accepted_ids) == limit,
        "output": str(out_path.resolve()),
        "output_bytes": out_path.stat().st_size if out_path.exists() else 0,
        "targets": {f"{year}/{relation}": count for (year, relation), count in targets.items()},
        "accepted_by_cell": {
            f"{year}/{relation}": cell_counts[(year, relation)]
            for year, relation in targets
        },
        "year_distribution": dict(year_counts),
        "relation_sampling_distribution": dict(relation_counts),
        "document_type_distribution": dict(type_counts),
        "authority_distribution": dict(authority_counts),
        "rejections": dict(reject_counts),
        "attempted_full_documents": len(attempted_ids),
        "max_documents_per_type": max_per_type,
        "removed_fields": [
            "raw_text",
            "cls_html",
            "cls_luoc_do",
            "download_links",
            "com_html",
            "*_embedding",
            "com_titles_content",
            "com_titles_content_embedding",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/exported_docs.jsonl"),
    )
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--database", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--reserve-multiplier",
        type=int,
        default=5,
        help="Metadata reserves per target cell; larger values survive more invalid parsings.",
    )
    parser.add_argument(
        "--scan-limit-per-year",
        type=int,
        default=50_000,
        help="Maximum lightweight metadata rows scanned per year bucket; 0 means unlimited.",
    )
    parser.add_argument("--mongo-batch-size", type=int, default=1000)
    parser.add_argument("--fetch-batch-size", type=int, default=32)
    parser.add_argument(
        "--max-type-share",
        type=float,
        default=0.40,
        help="Hard maximum share for one document type.",
    )
    parser.add_argument("--max-clause-chars", type=int, default=100_000)
    parser.add_argument("--max-document-chars", type=int, default=2_000_000)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.limit <= 0:
        raise SystemExit("--limit must be positive.")
    if args.reserve_multiplier < 2:
        raise SystemExit("--reserve-multiplier must be >= 2.")
    if not 0.10 <= args.max_type_share <= 1.0:
        raise SystemExit("--max-type-share must be between 0.10 and 1.0.")
    if args.fetch_batch_size <= 0 or args.mongo_batch_size <= 0:
        raise SystemExit("Batch sizes must be positive.")


def main() -> int:
    args = parse_args()
    validate_args(args)
    env_path = args.env_file if args.env_file.is_absolute() else PROJECT_ROOT / args.env_file
    out_path = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    report_path = args.report or out_path.with_suffix(".report.json")
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path

    env = load_repo_env(env_path)
    database = args.database or env.get("CLS_DATABASE") or "vanbanphapluat"
    collection_name = args.collection or env.get("CLS_COLLECTION") or "cls_ver2"
    targets = build_cell_targets(args.limit)

    print("=== EXPORT LEGAL RELATION-EXTRACTION POC CORPUS ===")
    print(f"database={database} collection={collection_name}")
    print(f"target={args.limit:,} output={out_path}")
    print(
        "policy=legal-types-only, usable vanban/dieu/khoan/diem, "
        f"max-type-share={args.max_type_share:.0%}"
    )

    client = build_mongo_client(env, database)
    try:
        collection = client[database][collection_name]
        print("\n[1/2] Scanning lightweight metadata...")
        reservoirs, scan_stats = scan_candidate_reservoirs(
            collection,
            targets,
            reserve_multiplier=args.reserve_multiplier,
            scan_limit_per_year=args.scan_limit_per_year,
            seed=args.seed,
            batch_size=args.mongo_batch_size,
        )
        print("\nCandidate reserves:")
        for cell in sorted(targets):
            reservoir = reservoirs[cell]
            print(
                f"  {cell}: target={targets[cell]:4d} "
                f"seen={reservoir.seen:6d} reserved={len(reservoir.items):5d}"
            )

        print("\n[2/2] Fetching, validating and compacting selected documents...")
        report = export_documents(
            collection,
            reservoirs,
            targets,
            out_path,
            limit=args.limit,
            fetch_batch_size=args.fetch_batch_size,
            max_type_share=args.max_type_share,
            max_clause_chars=args.max_clause_chars,
            max_document_chars=args.max_document_chars,
            seed=args.seed,
        )
        report["metadata_scan"] = dict(scan_stats)
        report["config"] = {
            "database": database,
            "collection": collection_name,
            "seed": args.seed,
            "reserve_multiplier": args.reserve_multiplier,
            "scan_limit_per_year": args.scan_limit_per_year,
            "allowed_document_types": list(ALLOWED_DOCUMENT_TYPES),
            "year_weights": dict(YEAR_WEIGHTS),
            "relation_weights": dict(RELATION_WEIGHTS),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    finally:
        client.close()

    print("\n=== RESULT ===")
    print(f"exported={report['exported']:,}/{report['requested']:,}")
    print(f"jsonl={report['output']} ({report['output_bytes'] / 1024 / 1024:.1f} MiB)")
    print(f"report={report_path.resolve()}")
    if not report["complete"]:
        print(
            "WARNING: target was not filled. Inspect report rejections and increase "
            "--scan-limit-per-year or --reserve-multiplier."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
