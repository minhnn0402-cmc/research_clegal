#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script to generate a balanced dataset of 5,000 legal documents from MongoDB.
Deletes the old exported files, queries candidates, applies stratified round-robin sampling,
and fetches full details for the final 5,000 selected documents.
"""

from __future__ import annotations

import os
import sys
import json
import gzip
import shutil
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from collections import defaultdict

# Reconfigure stdout/stderr to use UTF-8 on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from dotenv import dotenv_values
from pymongo import MongoClient

# Allow running directly (e.g. `python scripts/generate_balanced_dataset.py`)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_repo_env(env_path: Path) -> Dict[str, str]:
    """Load env variables from file if it exists, merging with os.environ."""
    env = dict(os.environ)
    if env_path.exists():
        values = dotenv_values(env_path)
        for key, value in values.items():
            if key and value is not None:
                env[str(key)] = str(value)
    return env


def build_mongo_client(env: Dict[str, str], database: str) -> MongoClient:
    """Build a MongoClient using environment variables."""
    last_error: Optional[Exception] = None
    host = env.get("MONGO_PROD_HOST")
    port_str = env.get("MONGO_PROD_PORT", "27017")
    username = env.get("MONGO_PROD_USER")
    password = env.get("MONGO_PROD_PASSWORD")

    if not host:
        raise ValueError("Missing MONGO_PROD_HOST environment variable.")

    for auth_source in (database, "admin", None):
        try:
            kwargs: Dict[str, Any] = {
                "host": host,
                "port": int(port_str),
                "username": username,
                "password": password,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
            }
            if auth_source:
                kwargs["authSource"] = auth_source

            client = MongoClient(**kwargs)
            client.admin.command("ping")
            return client
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Mongo connection failed: {last_error}")


def clean_existing_files():
    """Delete the existing exported files/directories as requested."""
    jsonl_path = Path("data/exported_docs.jsonl")
    json_path = Path("data/exported_docs.json")
    dir_path = Path("data/exported_docs")

    print("\n--- DỌN DẸP DỮ LIỆU CŨ ---")
    if jsonl_path.exists():
        jsonl_path.unlink()
        print(f"✓ Đã xoá file cũ: {jsonl_path.resolve()}")
    if json_path.exists():
        json_path.unlink()
        print(f"✓ Đã xoá file cũ: {json_path.resolve()}")
    if dir_path.exists() and dir_path.is_dir():
        shutil.rmtree(dir_path)
        print(f"✓ Đã xoá thư mục cũ: {dir_path.resolve()}")
    print("--------------------------\n")


def decompress_parsing(doc: Dict[str, Any]) -> Any:
    """Decompress cls_parsing if it is gzip-compressed, otherwise return as is."""
    parsing = doc.get("cls_parsing")
    if not parsing:
        return []
    if isinstance(parsing, list):
        return parsing
    if isinstance(parsing, dict) and "parsing" in parsing:
        raw = parsing["parsing"]
        if not raw:
            return []
        try:
            if isinstance(raw, str):
                raw = raw.encode("latin1")
            decompressed = gzip.decompress(raw).decode("utf-8")
            return json.loads(decompressed)
        except Exception as e:
            return parsing
    return parsing


def classify_year(doc: Dict[str, Any]) -> str:
    """Classify document into year bucket."""
    ngay = doc.get("cls_info", {}).get("ngay_ban_hanh")
    if not ngay or not isinstance(ngay, str):
        return "Y4"
    try:
        year = int(ngay.split("-")[0])
        if 2024 <= year <= 2026:
            return "Y1"  # 2024–2026
        elif 2020 <= year <= 2023:
            return "Y2"  # 2020–2023
        elif 2015 <= year <= 2019:
            return "Y3"  # 2015–2019
        else:
            return "Y4"  # trước 2015
    except Exception:
        return "Y4"


def classify_relation(doc: Dict[str, Any]) -> str:
    """Classify document into relation category based on title keywords and cls_luoc_do."""
    title = (doc.get("cls_info", {}).get("title") or "").lower()
    luoc_do = doc.get("cls_luoc_do") or {}

    # Category 1: Sửa đổi/bổ sung/bãi bỏ/thay thế
    r1_keys = [
        "van_ban_sua_doi_bo_sung", "van_ban_duoc_sua_doi", "van_ban_duoc_sua_doi_bo_sung",
        "van_ban_bi_bai_bo", "van_ban_bi_bai_bo_mot_phan", "van_ban_bi_huy_bo", "van_ban_bi_huy_bo_mot_phan",
        "van_ban_bi_thay_the", "van_ban_bi_thay_the_mot_phan", "van_ban_thay_the"
    ]
    has_r1_luoc_do = any(len(luoc_do.get(k, [])) > 0 for k in r1_keys)
    r1_keywords = ["sửa đổi", "bổ sung", "bãi bỏ", "thay thế"]
    has_r1_title = any(kw in title for kw in r1_keywords)

    if has_r1_luoc_do or has_r1_title:
        return "R1"

    # Category 2: Dẫn chiếu/căn cứ/quy định chi tiết/hướng dẫn
    r2_keys = [
        "van_ban_can_cu", "van_ban_dan_chieu", "van_ban_quy_dinh_chi_tiet",
        "van_ban_huong_dan", "van_ban_duoc_huong_dan"
    ]
    has_r2_luoc_do = any(len(luoc_do.get(k, [])) > 0 for k in r2_keys)
    r2_keywords = ["dẫn chiếu", "căn cứ", "quy định chi tiết", "hướng dẫn"]
    has_r2_title = any(kw in title for kw in r2_keywords)

    if has_r2_luoc_do or has_r2_title:
        return "R2"

    # Category 3: Hiệu lực/đình chỉ/đính chính/hợp nhất
    r3_keys = [
        "van_ban_bi_dinh_chi", "van_ban_bi_dinh_chi_mot_phan", "van_ban_dinh_chinh",
        "van_ban_bi_dinh_chinh", "van_ban_hop_nhat", "van_ban_duoc_hop_nhat"
    ]
    has_r3_luoc_do = any(len(luoc_do.get(k, [])) > 0 for k in r3_keys)
    r3_keywords = ["hiệu lực", "đình chỉ", "đính chính", "hợp nhất"]
    has_r3_title = any(kw in title for kw in r3_keywords)

    if has_r3_luoc_do or has_r3_title:
        return "R3"

    # Category 4: Không quan hệ (Random)
    return "R4"


def classify_type_and_authority(doc: Dict[str, Any]) -> Tuple[str, str]:
    """Classify document type and authority level (Central vs Local)."""
    info = doc.get("cls_info") or {}
    loai_van_ban = (info.get("loai_van_ban") or "").strip()
    loai_lower = loai_van_ban.lower()

    # Document type
    doc_type = "Khác"
    if "nghị định" in loai_lower:
        doc_type = "Nghị định"
    elif "thông tư" in loai_lower:
        doc_type = "Thông tư"
    elif "quyết định" in loai_lower:
        doc_type = "Quyết định"
    elif any(kw in loai_lower for kw in ["luật", "bộ luật", "hiến pháp"]):
        doc_type = "Luật"
    elif "nghị quyết" in loai_lower:
        doc_type = "Nghị quyết"
    elif "hợp nhất" in loai_lower:
        doc_type = "VBHN"

    # Authority level
    dia_danh = info.get("dia_danh") or ""
    don_vi_list = info.get("don_vi") or []
    
    is_trung_uong = False
    if "trung ương" in str(dia_danh).lower():
        is_trung_uong = True
    else:
        for dv in don_vi_list:
            if dv and "trung ương" in str(dv).lower():
                is_trung_uong = True
                break

    authority = "Trung ương" if is_trung_uong else "Địa phương"
    return doc_type, authority


def main() -> int:
    env = load_repo_env(Path(".env"))
    database = env.get("CLS_DATABASE", "vanbanphapluat")
    collection_name = env.get("CLS_COLLECTION", "cls_ver2")

    # Target configurations
    total_target = 5000
    
    year_targets = {
        "Y1": 2000,  # 2024–2026
        "Y2": 1500,  # 2020–2023
        "Y3": 1000,  # 2015–2019
        "Y4": 500,   # trước 2015/rare
    }

    rel_proportions = {
        "R1": 0.40,  # Sửa đổi/bổ sung/bãi bỏ/thay thế
        "R2": 0.30,  # Dẫn chiếu/căn cứ/quy định chi tiết/hướng dẫn
        "R3": 0.15,  # Hiệu lực/đình chỉ/đính chính/hợp nhất
        "R4": 0.15,  # Không quan hệ (Random)
    }

    # Clean existing data files first
    clean_existing_files()

    print("=== BẮT ĐẦU TRUY VẤN VÀ PHÂN TÍCH THỐNG KÊ BỘ DỮ LIỆU ===")
    
    # Connect to Mongo
    try:
        client = build_mongo_client(env, database)
        db = client[database]
        col = db[collection_name]
        print("✓ Kết nối thành công đến MongoDB!")
    except Exception as e:
        print(f"✗ Không thể kết nối tới MongoDB: {e}")
        return 1

    # Fetch candidates for each year range to build a rich candidate pool
    # We query metadata only, prioritizing documents with higher cls_number_of_terms (complexity)
    projection = {
        "_id": 0,
        "cls_ID": 1,
        "cls_info.ngay_ban_hanh": 1,
        "cls_info.loai_van_ban": 1,
        "cls_info.dia_danh": 1,
        "cls_info.don_vi": 1,
        "cls_info.title": 1,
        "cls_luoc_do": 1,
        "cls_number_of_terms": 1,
    }

    year_filters = {
        "Y1": {"cls_info.ngay_ban_hanh": {"$gte": "2024-01-01", "$lte": "2026-12-31"}},
        "Y2": {"cls_info.ngay_ban_hanh": {"$gte": "2020-01-01", "$lte": "2023-12-31"}},
        "Y3": {"cls_info.ngay_ban_hanh": {"$gte": "2015-01-01", "$lte": "2019-12-31"}},
        "Y4": {
            "$or": [
                {"cls_info.ngay_ban_hanh": {"$lt": "2015-01-01"}},
                {"cls_info.ngay_ban_hanh": None},
                {"cls_info.ngay_ban_hanh": {"$exists": False}}
            ]
        }
    }

    # Candidate lists per grid cell (Year, Relation)
    # Grid is year_bucket -> rel_bucket -> list of candidates
    grid: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        y: {r: [] for r in rel_proportions} for y in year_targets
    }

    print("\nĐang lấy danh sách ứng viên từ cơ sở dữ liệu...")
    for y_bucket, y_filter in year_filters.items():
        print(f"  • Truy vấn ứng viên cho nhóm năm {y_bucket} (đang lấy tối đa 20k bản ghi phức tạp nhất)...")
        # Ensure we filter out docs without cls_ID
        query = {"$and": [y_filter, {"cls_ID": {"$exists": True, "$ne": None}}]}
        
        # Fetch candidates without sorting on DB side (to avoid extremely slow database-side sort due to lack of index)
        # We will sort by complexity in Python instead!
        cursor = col.find(query, projection).limit(5000)

        
        count = 0
        for doc in cursor:
            # Classify relation
            r_bucket = classify_relation(doc)
            grid[y_bucket][r_bucket].append(doc)
            count += 1
        print(f"    -> Đã lấy {count:,} ứng viên.")

    # Calculate exact target per cell
    cell_targets = {}
    for y in year_targets:
        for r in rel_proportions:
            cell_targets[(y, r)] = int(year_targets[y] * rel_proportions[r])

    print("\n--- THỐNG KÊ SỐ LƯỢNG ỨNG VIÊN VÀ TARGET THEO BUCKET ---")
    for (y, r), target in cell_targets.items():
        available = len(grid[y][r])
        print(f"  Bucket ({y}, {r}): Target = {target:>4} | Có sẵn = {available:>5}")
    print("------------------------------------------------------\n")

    # Sample candidates in each cell using round-robin over (doc_type, authority)
    selected_ids: Set[int] = set()
    selected_docs_by_cell = defaultdict(list)

    for (y, r), target in cell_targets.items():
        candidates = grid[y][r]
        if not candidates:
            continue
            
        # Group candidates by (doc_type, authority)
        groups = defaultdict(list)
        for doc in candidates:
            doc_type, authority = classify_type_and_authority(doc)
            groups[(doc_type, authority)].append(doc)

        # Sort each sub-group by complexity (cls_number_of_terms or number of references)
        for g_key in groups:
            # Complexity score: terms + total relations count in luoc_do
            def get_complexity(d):
                terms = d.get("cls_number_of_terms") or 0
                luoc_do = d.get("cls_luoc_do") or {}
                ref_count = sum(len(luoc_do.get(k, [])) for k in luoc_do)
                return terms * 10 + ref_count
            
            groups[g_key].sort(key=get_complexity, reverse=True)

        # Round-robin selection
        selected_in_cell = []
        keys = list(groups.keys())
        cell_count = 0
        
        while cell_count < target and any(groups[k] for k in keys):
            for k in keys:
                if groups[k]:
                    doc = groups[k].pop(0)
                    selected_in_cell.append(doc)
                    selected_ids.add(doc["cls_ID"])
                    cell_count += 1
                    if cell_count >= target:
                        break

        selected_docs_by_cell[(y, r)] = selected_in_cell
        print(f"  ✓ Đã chọn {len(selected_in_cell):>4}/{target:>4} tài liệu cho nhóm ({y}, {r})")

    # Check if total selected is under 5,000 and perform backfill if needed
    deficit = total_target - len(selected_ids)
    if deficit > 0:
        print(f"\n[!] Thiếu hụt {deficit} tài liệu do một số cell không đủ ứng viên. Tiến hành backfill từ các nhóm còn dư...")
        
        # Pool all unselected candidates from all cells
        surplus_pool = []
        for y in year_targets:
            for r in rel_proportions:
                # Group remaining candidates by (doc_type, authority)
                for doc in grid[y][r]:
                    if doc["cls_ID"] not in selected_ids:
                        surplus_pool.append(doc)

        # Group surplus by (doc_type, authority)
        surplus_groups = defaultdict(list)
        for doc in surplus_pool:
            doc_type, authority = classify_type_and_authority(doc)
            surplus_groups[(doc_type, authority)].append(doc)

        # Sort by complexity
        for g_key in surplus_groups:
            def get_complexity(d):
                terms = d.get("cls_number_of_terms") or 0
                luoc_do = d.get("cls_luoc_do") or {}
                ref_count = sum(len(luoc_do.get(k, [])) for k in luoc_do)
                return terms * 10 + ref_count
            surplus_groups[g_key].sort(key=get_complexity, reverse=True)

        # Round-robin select deficit docs
        keys = list(surplus_groups.keys())
        backfill_count = 0
        while backfill_count < deficit and any(surplus_groups[k] for k in keys):
            for k in keys:
                if surplus_groups[k]:
                    doc = surplus_groups[k].pop(0)
                    selected_ids.add(doc["cls_ID"])
                    backfill_count += 1
                    if backfill_count >= deficit:
                        break
        print(f"  ✓ Đã bù đắp thành công {backfill_count} tài liệu.")

    print(f"\nTổng số tài liệu được chọn cuối cùng: {len(selected_ids):,} tài liệu.")

    # Show final distribution analysis
    print("\n--- PHÂN TÍCH PHÂN BỐ BỘ DỮ LIỆU ĐÃ CHỌN ---")
    final_years = defaultdict(int)
    final_rels = defaultdict(int)
    final_types = defaultdict(int)
    final_auth = defaultdict(int)

    # Let's collect final list of document details
    print("Đang tải toàn bộ nội dung chi tiết (cls_parsing, raw_text,...) của 5k tài liệu...")
    out_path = Path("data/exported_docs.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Batch query by ID to fetch full details efficiently
    selected_id_list = list(selected_ids)
    batch_size = 100
    count = 0

    # Project only required fields to avoid memory exhaustion from huge fields like cls_html
    final_projection = {
        "_id": 0,
        "cls_ID": 1,
        "cls_info": 1,
        "cls_parsing": 1,
        "raw_text": 1,
        "cls_luoc_do": 1,
    }

    import gc

    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(0, len(selected_id_list), batch_size):
            batch_ids = selected_id_list[i : i + batch_size]
            docs = col.find({"cls_ID": {"$in": batch_ids}}, final_projection)
            for doc in docs:
                # Decompress parsing
                doc["cls_parsing"] = decompress_parsing(doc)
                
                # Statistics update
                y = classify_year(doc)
                r = classify_relation(doc)
                doc_type, authority = classify_type_and_authority(doc)
                
                final_years[y] += 1
                final_rels[r] += 1
                final_types[doc_type] += 1
                final_auth[authority] += 1

                # Write to jsonl safely using json.dump to stream data directly to file and avoid MemoryError
                json.dump(doc, f, default=str, ensure_ascii=False)
                f.write("\n")
                count += 1
                doc.clear()
            
            # Force garbage collection after each batch to prevent RAM build-up
            gc.collect()

    # Close mongo connection
    client.close()

    # Print stats table
    print("\n[Nhóm Năm]")
    for y, count_y in sorted(final_years.items()):
        pct = (count_y / total_target) * 100
        desc = {
            "Y1": "2024–2026",
            "Y2": "2020–2023",
            "Y3": "2015–2019",
            "Y4": "trước 2015/khác"
        }[y]
        print(f"  • {desc:<15}: {count_y:>4} tài liệu ({pct:.1f}%)")

    print("\n[Nhóm Quan Hệ (Relations)]")
    rel_names = {
        "R1": "Sửa đổi/bổ sung/bãi bỏ/thay thế",
        "R2": "Dẫn chiếu/căn cứ/quy định chi tiết/hướng dẫn",
        "R3": "Hiệu lực/đình chỉ/đính chính/hợp nhất",
        "R4": "Random/Không có quan hệ"
    }
    for r, count_r in sorted(final_rels.items()):
        pct = (count_r / total_target) * 100
        print(f"  • {rel_names[r]:<45}: {count_r:>4} tài liệu ({pct:.1f}%)")

    print("\n[Nhóm Loại Văn Bản (Diversity)]")
    for t, count_t in sorted(final_types.items(), key=lambda x: x[1], reverse=True):
        pct = (count_t / total_target) * 100
        print(f"  • {t:<20}: {count_t:>4} tài liệu ({pct:.1f}%)")

    print("\n[Cơ Quan Ban Hành (Authority)]")
    for a, count_a in sorted(final_auth.items()):
        pct = (count_a / total_target) * 100
        print(f"  • {a:<15}: {count_a:>4} tài liệu ({pct:.1f}%)")

    print("\n=======================================================")
    print(f"✓ Hoàn tất! Đã xuất {count:,} tài liệu vào file:")
    print(f"  {out_path.resolve()}")
    print("=======================================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
