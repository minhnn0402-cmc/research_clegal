from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from dotenv import dotenv_values
from pymongo import MongoClient


SOURCE_PROJECTION = {
    "_id": 0,
    "cls_ID": 1,
    "cls_info.title": 1,
    "cls_info.title_without_number": 1,
    "cls_info.so_hieu": 1,
    "cls_info.loai_van_ban": 1,
    "cls_info.type_of_van_ban": 1,
    "cls_parsing": 1,
}


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


def find_document(collection, cls_id: int) -> Dict[str, Any]:
    queries = (
        {"cls_ID": cls_id},
        {"cls_ID": str(cls_id)},
        {"doc_id": cls_id},
        {"doc_id": str(cls_id)},
        {"id": cls_id},
        {"id": str(cls_id)},
    )
    for query in queries:
        doc = collection.find_one(query, SOURCE_PROJECTION)
        if doc:
            doc["_matched_query"] = query
            return doc
    raise LookupError(f"Document not found for cls_ID={cls_id}")


def extract_parsing(doc: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Return cls_parsing as a list, handling list and compressed payload shapes."""
    parsing = doc.get("cls_parsing") or []
    if isinstance(parsing, list):
        return parsing

    if isinstance(parsing, dict) and parsing.get("parsing"):
        raw = parsing["parsing"]
        if isinstance(raw, str):
            raw = raw.encode("latin1")
        return json.loads(gzip.decompress(raw).decode("utf-8"))

    return []


def compact_clause(clause: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "com_key": clause.get("com_key"),
        "com_type": clause.get("com_type"),
        "com_path": clause.get("com_path"),
        "com_title": clause.get("com_title"),
        "com_content": clause.get("com_content") or clause.get("content") or clause.get("com_title"),
    }


def build_snapshot(doc: Dict[str, Any], com_keys: Iterable[str]) -> Dict[str, Any]:
    cls_info = doc.get("cls_info") or {}
    selected_keys = set(com_keys)
    parsing = extract_parsing(doc)
    if selected_keys:
        parsing = [
            clause
            for clause in parsing
            if isinstance(clause, dict) and clause.get("com_key") in selected_keys
        ]

    return {
        "source": "mongo",
        "cls_ID": doc.get("cls_ID"),
        "matched_query": doc.get("_matched_query"),
        "cls_info": {
            "title": cls_info.get("title"),
            "title_without_number": cls_info.get("title_without_number"),
            "so_hieu": cls_info.get("so_hieu"),
            "loai_van_ban": cls_info.get("loai_van_ban"),
            "type_of_van_ban": cls_info.get("type_of_van_ban"),
        },
        "cls_parsing_count": len(doc.get("cls_parsing") or []),
        "selected_cls_parsing": [compact_clause(clause) for clause in parsing],
    }


def parse_relation_assertion(value: str) -> Dict[str, str]:
    """Parse ``relation=reference`` CLI values into regression assertion dicts."""
    if "=" not in value:
        raise ValueError(f"Relation assertion must use relation=reference format: {value}")
    relation, reference = value.split("=", 1)
    relation = relation.strip()
    reference = reference.strip()
    if not relation or not reference:
        raise ValueError(f"Relation assertion must include relation and reference: {value}")
    return {"relation": relation, "reference": reference}


def build_relation_fixture_case(
    doc: Dict[str, Any],
    com_keys: Iterable[str],
    case_id: str,
    status: str,
    priority: str,
    expected_relations: list[Dict[str, str]],
    forbidden_relations: list[Dict[str, str]],
) -> Dict[str, Any]:
    """Build a test_mongo_derived_regression_cases-compatible fixture case."""
    cls_info = doc.get("cls_info") or {}
    snapshot = build_snapshot(doc, com_keys)
    return {
        "id": case_id,
        "status": status,
        "priority": priority,
        "source": {
            "cls_ID": doc.get("cls_ID"),
            "so_hieu": cls_info.get("so_hieu"),
            "title": cls_info.get("title"),
            "loai_van_ban": cls_info.get("loai_van_ban"),
        },
        "data": snapshot["selected_cls_parsing"],
        "expected_relations": expected_relations,
        "forbidden_relations": forbidden_relations,
        "fixture_source": {
            "kind": "mongo_snapshot",
            "matched_query": doc.get("_matched_query"),
            "selected_com_keys": list(com_keys),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export compact Mongo source data for reviewed regression fixtures.",
    )
    parser.add_argument("--cls-id", type=int, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--database", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--com-key", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--as-relation-case",
        action="store_true",
        help="Write a relation regression fixture case instead of a raw source snapshot.",
    )
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--status", default="active")
    parser.add_argument("--priority", default="P1")
    parser.add_argument(
        "--expected",
        action="append",
        default=[],
        help="Expected relation assertion in relation=reference format. Repeatable.",
    )
    parser.add_argument(
        "--forbidden",
        action="append",
        default=[],
        help="Forbidden relation assertion in relation=reference format. Repeatable.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = load_repo_env(args.env_file)
    database = args.database or env.get("CLS_DATABASE") or env.get("MONGO_PROD_DATABASE")
    collection_name = args.collection or env.get("CLS_COLLECTION", "cls_ver2")
    if not database:
        raise ValueError("Missing CLS_DATABASE or MONGO_PROD_DATABASE")

    client = build_mongo_client(env, database)
    try:
        doc = find_document(client[database][collection_name], args.cls_id)
        if args.as_relation_case:
            snapshot = build_relation_fixture_case(
                doc=doc,
                com_keys=args.com_key,
                case_id=args.case_id or f"MONGO-{args.cls_id}",
                status=args.status,
                priority=args.priority,
                expected_relations=[
                    parse_relation_assertion(value)
                    for value in args.expected
                ],
                forbidden_relations=[
                    parse_relation_assertion(value)
                    for value in args.forbidden
                ],
            )
        else:
            snapshot = build_snapshot(doc, args.com_key)
    finally:
        client.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote Mongo source snapshot: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
