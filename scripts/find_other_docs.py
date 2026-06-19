from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import dotenv_values
from pymongo import MongoClient


DEFAULT_START_CLS_ID = 1111171
DEFAULT_END_CLS_ID = 11111780
DEFAULT_COLLECTION = "cls_ver2"
DEFAULT_OUTPUT = Path("data/doc_ids/other_docs.json")


def load_repo_env(env_path: Path) -> Dict[str, str]:
    values = dotenv_values(env_path)
    return {str(key): str(value) for key, value in values.items() if key and value is not None}


def build_mongo_client(env: Dict[str, str], database: str) -> MongoClient:
    last_error: Optional[Exception] = None

    for auth_source in (database, "admin", None):
        try:
            kwargs: Dict[str, Any] = {
                "host": env["MONGO_PROD_HOST"],
                "port": int(env.get("MONGO_PROD_PORT", "27017")),
                "username": env.get("MONGO_PROD_USER"),
                "password": env.get("MONGO_PROD_PASSWORD"),
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


def get_loai_van_ban(doc: Dict[str, Any]) -> Any:
    cls_info = doc.get("cls_info") or {}
    if isinstance(cls_info, dict):
        return cls_info.get("loai_van_ban")
    return None


def find_other_docs(
    client: MongoClient,
    database: str,
    collection_name: str,
    start_cls_id: int,
    end_cls_id: int,
) -> list[Dict[str, Any]]:
    collection = client[database][collection_name]
    query = {"cls_ID": {"$gte": start_cls_id, "$lte": end_cls_id}}
    projection = {
        "_id": 0,
        "cls_ID": 1,
        "cls_info.loai_van_ban": 1,
    }

    docs = []
    for doc in collection.find(query, projection).sort("cls_ID", 1):
        docs.append(
            {
                "doc_id": doc.get("cls_ID"),
                "loai_van_ban": get_loai_van_ban(doc),
            }
        )
    return docs


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find cls_ver2 documents by cls_ID range and export loai_van_ban.",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--database", default=None)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--start", type=int, default=DEFAULT_START_CLS_ID)
    parser.add_argument("--end", type=int, default=DEFAULT_END_CLS_ID)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--ids-out",
        type=Path,
        default=None,
        help="Optional path to also write only doc_id values as a JSON list.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = load_repo_env(args.env_file)
    database = args.database or env.get("CLS_DATABASE") or env.get("MONGO_PROD_DATABASE")
    if not database:
        raise ValueError("Missing CLS_DATABASE or MONGO_PROD_DATABASE")

    client = build_mongo_client(env, database)
    try:
        docs = find_other_docs(
            client=client,
            database=database,
            collection_name=args.collection,
            start_cls_id=args.start,
            end_cls_id=args.end,
        )
    finally:
        client.close()

    write_json(args.out, docs)
    print(f"Wrote {len(docs):,} docs to {args.out}")

    if args.ids_out:
        write_json(args.ids_out, [doc["doc_id"] for doc in docs])
        print(f"Wrote {len(docs):,} doc_ids to {args.ids_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
