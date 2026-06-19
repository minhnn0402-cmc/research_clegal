import json
from dotenv import load_dotenv
import os
import sys
from pathlib import Path
from tqdm import tqdm
import time
import re

# Allow running directly (`python scripts/get_doc_ids.py`) where sys.path[0]
# is `scripts/`, not the repo root that `src.*` imports require.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.config import AppConfig
from src.infrastructure.connections import ConnectionManager

load_dotenv()

CENTRAL_IDS_PATH = "./data/doc_ids/central_ids.json"
LOCAL_IDS_PATH = "./data/doc_ids/local_ids.json"
LAW_IDS_PATH = "./data/doc_ids/law_ids.json"
LATEST_CENTRAL_IDS_PATH = "./data/doc_ids/latest_central_ids.json"
LATEST_LOCAL_IDS_PATH = "./data/doc_ids/latest_local_ids.json"
LATEST_LAW_IDS_PATH = "./data/doc_ids/latest_law_ids.json"


def load_existing_ids(file_path):
    """Load existing IDs from a JSON file. Return empty list if file doesn't exist."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    return []


def save_ids_to_file(file_path, ids):
    """Save IDs to a JSON file."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(ids, file, ensure_ascii=False, indent=2)


def get_doc_ids(conn_manager=None):
    """
    Discover new document IDs from the CLS MongoDB collection and write
    `central/local/law` (cumulative) and `latest_*` (this-run-only) ID files
    under `./data/doc_ids/`.

    Args:
        conn_manager: Optional `ConnectionManager` instance (defaults to the
            process singleton). Lets tests/orchestrators inject a pre-configured
            connection without touching the singleton's global state.

    Returns:
        Dict mapping logical names to the file paths written, or `None` if the
        MongoDB connection could not be established.
    """
    start_time = time.time()
    print("\n" + "="*60)
    print(" " * 15 + "DOCUMENT ID DISCOVERY")
    print("="*60)

    # Pre-compile regexes for Python speed
    re_legal_type = re.compile(r"^(Luật|Bộ luật|Hiến pháp)", re.IGNORECASE)
    re_trung_uong = re.compile(r"Trung ương", re.IGNORECASE)
    re_duthao = re.compile(r"^Dự thảo", re.IGNORECASE)

    # Connect to MongoDB via the named `cls_mongo` connection (PRODUCTION)
    print("\n[1/4] Connecting to MongoDB...")
    try:
        conn_manager = conn_manager or ConnectionManager()
        conn_manager.register_mongo_from_env('cls_mongo', 'MONGO_PROD')
        cfg = AppConfig()
        cls_collection = conn_manager.get_mongo_collection(
            'cls_mongo', cfg.cls_collection, cfg.cls_database
        )
        # Test connection
        conn_manager.get_mongo_client('cls_mongo').admin.command('ping')
        print("✓ Connected successfully.")
    except Exception as e:
        print(f"✗ Connection failed: {str(e)}")
        return None

    # Load existing IDs
    print("\n[2/4] Loading existing IDs from local files...")
    old_legal_ids_list = load_existing_ids(LAW_IDS_PATH)
    old_central_ids_list = load_existing_ids(CENTRAL_IDS_PATH)
    old_local_ids_list = load_existing_ids(LOCAL_IDS_PATH)
    
    old_legal_ids = set(old_legal_ids_list)
    old_central_ids = set(old_central_ids_list)
    old_local_ids = set(old_local_ids_list)
    
    print(f"  • Legal:   {len(old_legal_ids):>7} IDs")
    print(f"  • Central: {len(old_central_ids):>7} IDs")
    print(f"  • Local:   {len(old_local_ids):>7} IDs")

    # Fetch and Filter strategy
    # Fetch all documents that have a valid ID (regardless of cls_parsing)
    base_filter = {"cls_ID": {"$exists": True, "$ne": None}}
    
    # Project minimal fields needed for filtering
    projection = {
        "cls_ID": 1, 
        "cls_info.loai_van_ban": 1, 
        "cls_info.dia_danh": 1, 
        "cls_info.don_vi": 1, 
        "_id": 0
    }

    print("\n[3/4] Streaming and filtering documents from MongoDB...")
    print("      (This bypasses slow DB-side regex scans for better performance)")
    
    all_legal_ids = []
    all_central_ids = []
    all_local_ids = []

    cursor = cls_collection.find(base_filter, projection).batch_size(10000)
    
    print() # Add newline for breathing room
    with tqdm(desc="  • Processing Documents", unit="docs") as pbar:
        for doc in cursor:
            pbar.update(1)
            doc_id = doc.get("cls_ID")
            if not doc_id:
                continue
            
            info = doc.get("cls_info", {})
            loai_van_ban = info.get("loai_van_ban", "") or ""
            
            # Skip documents where loai_van_ban is null or contains "Dự thảo"
            if not loai_van_ban or re_duthao.search(loai_van_ban):
                continue
            
            dia_danh = info.get("dia_danh", "") or ""
            don_vi_list = info.get("don_vi", []) or []
            
            # Check for "Trung ương" in dia_danh or don_vi
            is_trung_uong = False
            if dia_danh and re_trung_uong.search(dia_danh):
                is_trung_uong = True
            else:
                for dv in don_vi_list:
                    if dv and re_trung_uong.search(dv):
                        is_trung_uong = True
                        break
            
            # 1. Legal Docs: (Type match) AND (Trung ương)
            if is_trung_uong and loai_van_ban and re_legal_type.search(loai_van_ban):
                all_legal_ids.append(doc_id)
            
            # 2. Central Docs: (Trung ương)
            if is_trung_uong:
                all_central_ids.append(doc_id)
            # 3. Local Docs: (NOT Trung ương) AND (Has dia_danh OR don_vi)
            elif (dia_danh and dia_danh.strip()) or (don_vi_list and any(dv.strip() for dv in don_vi_list)):
                all_local_ids.append(doc_id)

    # Find new IDs
    print("\n[4/4] Comparing with local storage and saving...")
    new_legal_ids = [doc_id for doc_id in all_legal_ids if doc_id not in old_legal_ids]
    new_central_ids = [doc_id for doc_id in all_central_ids if doc_id not in old_central_ids]
    new_local_ids = [doc_id for doc_id in all_local_ids if doc_id not in old_local_ids]

    # Save results
    save_ids_to_file(LATEST_LAW_IDS_PATH, new_legal_ids)
    save_ids_to_file(LATEST_CENTRAL_IDS_PATH, new_central_ids)
    save_ids_to_file(LATEST_LOCAL_IDS_PATH, new_local_ids)

    if new_legal_ids:
        save_ids_to_file(LAW_IDS_PATH, old_legal_ids_list + new_legal_ids)
    if new_central_ids:
        save_ids_to_file(CENTRAL_IDS_PATH, old_central_ids_list + new_central_ids)
    if new_local_ids:
        save_ids_to_file(LOCAL_IDS_PATH, old_local_ids_list + new_local_ids)

    # Final Summary Table
    duration = time.time() - start_time
    print("\n" + "="*60)
    print(f"{'CATEGORY':<20} | {'FOUND':<10} | {'NEW':<10} | {'TOTAL'}")
    print("-" * 60)
    print(f"{'Legal Docs':<20} | {len(all_legal_ids):<10} | {len(new_legal_ids):<10} | {len(old_legal_ids) + len(new_legal_ids)}")
    print(f"{'Central Docs':<20} | {len(all_central_ids):<10} | {len(new_central_ids):<10} | {len(old_central_ids) + len(new_central_ids)}")
    print(f"{'Local Docs':<20} | {len(all_local_ids):<10} | {len(new_local_ids):<10} | {len(old_local_ids) + len(new_local_ids)}")
    print("="*60)
    print(f"Total time: {duration:.2f}s")
    print("\n✓ Process completed successfully!")

    return {
        "central_ids": CENTRAL_IDS_PATH,
        "local_ids": LOCAL_IDS_PATH,
        "law_ids": LAW_IDS_PATH,
        "latest_central_ids": LATEST_CENTRAL_IDS_PATH,
        "latest_local_ids": LATEST_LOCAL_IDS_PATH,
        "latest_law_ids": LATEST_LAW_IDS_PATH,
    }


if __name__ == "__main__":
    get_doc_ids()