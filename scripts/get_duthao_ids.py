import json
import pymongo
from dotenv import load_dotenv
import os
from tqdm import tqdm
import time
import re

load_dotenv()

OLD_DUTHAO_IDS = "./data/doc_ids/duthao_ids.json"
LATEST_DUTHAO_IDS = "./data/doc_ids/latest_duthao_ids.json"


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


def get_duthao_ids():
    start_time = time.time()
    print("\n" + "="*60)
    print(" " * 15 + "DỰ THẢO DOCUMENT ID DISCOVERY")
    print("="*60)

    # Pre-compile regex for Python speed
    re_duthao = re.compile(r"^Dự thảo", re.IGNORECASE)

    # Connect to MongoDB
    print("\n[1/4] Connecting to MongoDB...")
    try:
        mongo_client = pymongo.MongoClient(
            host=os.getenv('MONGO_PROD_HOST'),
            port=int(os.getenv('MONGO_PROD_PORT')),
            username=os.getenv('MONGO_PROD_USER'),
            password=os.getenv('MONGO_PROD_PASSWORD'),
            serverSelectionTimeoutMS=5000
        )
        cls_collection = mongo_client[os.getenv('CLS_DATABASE')][os.getenv('CLS_COLLECTION')]
        mongo_client.admin.command('ping')
        print("✓ Connected successfully.")
    except Exception as e:
        print(f"✗ Connection failed: {str(e)}")
        return

    # Load existing IDs
    print("\n[2/4] Loading existing IDs from local file...")
    old_duthao_ids_list = load_existing_ids(OLD_DUTHAO_IDS)
    old_duthao_ids = set(old_duthao_ids_list)
    print(f"  • Existing Dự thảo: {len(old_duthao_ids):>7} IDs")

    # Fetch and Filter strategy
    base_filter = {"cls_ID": {"$exists": True, "$ne": None}}
    projection = {"cls_ID": 1, "cls_info.loai_van_ban": 1, "_id": 0}

    print("\n[3/4] Streaming and filtering documents from MongoDB...")
    
    all_duthao_ids = []
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
            
            if loai_van_ban and re_duthao.search(loai_van_ban):
                all_duthao_ids.append(doc_id)

    # Find new IDs
    print("\n[4/4] Comparing with local storage and saving...")
    new_duthao_ids = [doc_id for doc_id in all_duthao_ids if doc_id not in old_duthao_ids]

    # Save results
    save_ids_to_file(LATEST_DUTHAO_IDS, new_duthao_ids)

    if new_duthao_ids:
        save_ids_to_file(OLD_DUTHAO_IDS, old_duthao_ids_list + new_duthao_ids)

    # Final Summary
    duration = time.time() - start_time
    print("\n" + "="*60)
    print(f"{'CATEGORY':<20} | {'FOUND':<10} | {'NEW':<10} | {'TOTAL'}")
    print("-" * 60)
    print(f"{'Dự thảo':<20} | {len(all_duthao_ids):<10} | {len(new_duthao_ids):<10} | {len(old_duthao_ids) + len(new_duthao_ids)}")
    print("="*60)
    print(f"Total time: {duration:.2f}s")
    print("\n✓ Process completed successfully!")


if __name__ == "__main__":
    get_duthao_ids()
