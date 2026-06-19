"""Read-only audit for unresolved graph references stored in MongoDB.

The script classifies existing ``cls_graph.failed`` mentions against the current
resolver and Elasticsearch index. It does not mutate MongoDB or ES.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient

from src.domain.extractors.components_extractor import extract_document_components
from src.infrastructure.config import ConfigLoader
from src.search.search_reference_doc import _normalize_title_tokens, search_reference_doc
from src.search.search_reference_in_es import _normalize_so_hieu, _so_hieu_exact_variants
from src.utils.relation_utils import should_keep_failed_reference


META_KEYS = {"information", "position_start", "position_end", "index", "check_in_quotes"}
LAW_TYPES = {"luat", "boluat", "hienphap", "phaplenh"}


class SimpleElasticsearch:
    """Minimal ES client compatible with ``client.search(index=..., body=...)``."""

    def __init__(self, endpoint: str, username: str | None = None, password: str | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.context = ssl._create_unverified_context()
        self.token = None
        if username or password:
            raw = f"{username or ''}:{password or ''}".encode()
            self.token = base64.b64encode(raw).decode()

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/{index}/_search",
            data=data,
            method="POST",
        )
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Basic {self.token}")

        with urllib.request.urlopen(request, timeout=20, context=self.context) as response:
            return json.loads(response.read().decode("utf-8"))


def has_full_code(information: str) -> bool:
    return bool(re.search(r"\d{1,5}/\d{4}/[A-Za-zĐđ0-9.-]+", information or ""))


def has_explicit_date(information: str) -> bool:
    return bool(
        re.search(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"
            r"|ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}",
            information or "",
            flags=re.IGNORECASE,
        )
    )


def broad_category(mention_type: str, information: str) -> str:
    if mention_type in LAW_TYPES:
        if has_full_code(information):
            return "law_full_code"
        if has_explicit_date(information):
            return "law_title_date"
        return "law_title_only"
    if has_full_code(information):
        return "nonlaw_full_code"
    if has_explicit_date(information):
        return "nonlaw_date"
    return "nonlaw_title_internal"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def date_matches(hit_date: str | None, ngay: Any, thang: Any, nam: Any) -> bool:
    nam_int = _to_int(nam)
    if nam_int is None or not hit_date:
        return False

    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", str(hit_date))
    if not match:
        return False

    if int(match.group(1)) != nam_int:
        return False

    thang_int = _to_int(thang)
    ngay_int = _to_int(ngay)
    hit_month = int(match.group(2)) if match.group(2) else None
    hit_day = int(match.group(3)) if match.group(3) else None

    if thang_int is not None and hit_month != thang_int:
        return False
    if ngay_int is not None and hit_day != ngay_int:
        return False
    return True


def type_compatible(query_type: str | None, hit_type: str | None) -> bool:
    if not query_type:
        return True
    query = str(query_type).lower().strip()
    hit = str(hit_type or "").lower().strip()
    return bool(hit and hit.startswith(query))


def _so_hieu_variants(so_hieu: str) -> list[str]:
    return _so_hieu_exact_variants(so_hieu)


def classify_unresolved_with_exact_hits(
    mention_type: str,
    information: str,
    components: dict[str, Any],
    exact_hits: list[dict[str, Any]],
) -> str:
    category = broad_category(mention_type, information)
    so_hieu = components.get("so_hieu")
    if not so_hieu:
        return f"{category}:no_so_hieu"
    if not exact_hits:
        return f"{category}:es_no_exact_so_hieu"

    query_type = components.get("loai_van_ban") or ""
    type_hits = [
        hit
        for hit in exact_hits
        if type_compatible(query_type, hit.get("_source", {}).get("loai_van_ban"))
    ]
    if not type_hits:
        return f"{category}:exact_exists_type_mismatch"

    if components.get("nam") is not None:
        date_hits = [
            hit
            for hit in type_hits
            if date_matches(
                hit.get("_source", {}).get("ngay_ban_hanh"),
                components.get("ngay"),
                components.get("thang"),
                components.get("nam"),
            )
        ]
        if not date_hits:
            return f"{category}:exact_exists_date_mismatch"

    return f"{category}:exact_compatible_but_resolver_failed"


def _mention_parts(mention: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    for key, value in mention.items():
        if key not in META_KEYS and isinstance(value, dict):
            return key, str(value.get("information") or ""), value
    return "unknown", str(mention.get("information") or ""), {
        "information": mention.get("information"),
        "type": "unknown",
    }


def _source_year(cls_info: dict[str, Any]) -> int:
    for key in ("nam_ban_hanh", "year"):
        value = _to_int(cls_info.get(key))
        if value is not None:
            return value
    date = str(cls_info.get("ngay_ban_hanh") or "")
    if len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return 9999


def _connect_mongo(env: dict[str, str], database: str) -> MongoClient:
    last_error: Exception | None = None
    for auth_source in (database, env.get("CLS_DATABASE"), "admin", None):
        try:
            kwargs: dict[str, Any] = {
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
        except Exception as exc:  # pragma: no cover - environment dependent
            last_error = exc
    raise RuntimeError(f"Cannot connect to MongoDB: {last_error}")


def _exact_so_hieu_hits(es_client: SimpleElasticsearch, so_hieu: str) -> list[dict[str, Any]]:
    if not so_hieu:
        return []

    should = [
        {"term": {"so_hieu.keyword": {"value": variant, "boost": 10}}}
        for variant in _so_hieu_variants(so_hieu)
    ]
    body = {
        "_source": [
            "ID",
            "so_hieu",
            "loai_van_ban",
            "co_quan_ban_hanh",
            "ngay_ban_hanh",
            "title",
            "tieu_de",
        ],
        "size": 10,
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
    }

    response = es_client.search("law_documents_t4", body)
    hits = response.get("hits", {}).get("hits", [])
    query_so_hieu = _normalize_so_hieu(so_hieu)
    return [
        hit
        for hit in hits
        if _normalize_so_hieu(hit.get("_source", {}).get("so_hieu")) == query_so_hieu
    ]


def _law_title_date_hits(
    es_client: SimpleElasticsearch,
    tieu_de: str,
    loai_van_ban: str,
    ngay: Any,
    thang: Any,
    nam: Any,
) -> list[dict[str, Any]]:
    if not tieu_de or nam is None:
        return []

    must: list[dict[str, Any]] = [
        {"match": {"title": {"query": tieu_de, "operator": "and"}}},
    ]
    if loai_van_ban:
        must.append({"term": {"loai_van_ban.keyword": loai_van_ban}})
    if ngay is not None and thang is not None:
        date_str = f"{int(nam):04d}-{int(thang):02d}-{int(ngay):02d}"
        must.append(
            {
                "range": {
                    "ngay_ban_hanh": {
                        "gte": f"{date_str}T00:00:00Z",
                        "lte": f"{date_str}T23:59:59Z",
                    }
                }
            }
        )
    else:
        must.append(
            {
                "range": {
                    "ngay_ban_hanh": {
                        "gte": f"{int(nam):04d}-01-01T00:00:00Z",
                        "lte": f"{int(nam):04d}-12-31T23:59:59Z",
                    }
                }
            }
        )

    body = {
        "_source": ["ID", "so_hieu", "loai_van_ban", "ngay_ban_hanh", "title", "tieu_de"],
        "size": 10,
        "query": {"bool": {"must": must}},
    }
    response = es_client.search("law_documents_t4", body)
    hits = response.get("hits", {}).get("hits", [])
    query_tokens = _normalize_title_tokens(tieu_de)
    return [
        hit
        for hit in hits
        if query_tokens and query_tokens <= _normalize_title_tokens(
            hit.get("_source", {}).get("title") or hit.get("_source", {}).get("tieu_de") or ""
        )
    ]


def _title_date_root_cause(
    category: str,
    components: dict[str, Any],
    title_date_hits: list[dict[str, Any]],
) -> str:
    if category != "law_title_date" or components.get("so_hieu"):
        return ""
    if not title_date_hits:
        return "law_title_date:es_no_title_date_hit"
    if len(title_date_hits) == 1:
        return "law_title_date:title_date_hit_resolver_failed"
    return "law_title_date:title_date_ambiguous"


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv(args.env)
    env = {
        str(key): str(value)
        for key, value in dotenv_values(args.env).items()
        if key and value is not None
    }
    config = ConfigLoader()
    es_client = SimpleElasticsearch(
        env["ES_PROD_ENDPOINT"],
        env.get("ES_PROD_USER"),
        env.get("ES_PROD_PASSWORD"),
    )
    mongo_client = _connect_mongo(env, args.db)

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    stats = Counter()
    try:
        collection = mongo_client[args.db][args.coll]
        projection = {"_id": 0, "cls_ID": 1, "cls_info": 1, "cls_graph.failed": 1}
        for doc in collection.find({"cls_graph.has_failed": True}, projection).batch_size(500):
            cls_info = doc.get("cls_info") or {}
            context = {
                "source_doc": doc.get("cls_ID"),
                "cls_year": _source_year(cls_info),
                "authority": str(cls_info.get("co_quan_ban_hanh") or ""),
            }
            for entry in doc.get("cls_graph", {}).get("failed") or []:
                for mention in entry.get("failed") or []:
                    stats["failed_mentions_in_mongo"] += 1
                    keep = should_keep_failed_reference(mention)
                    if keep:
                        stats["kept_by_current_failed_filter"] += 1
                    else:
                        stats["dropped_by_current_failed_filter"] += 1
                        continue

                    mention_type, information, value = _mention_parts(mention)
                    key = (mention_type, information)
                    if key not in unique:
                        unique[key] = {
                            "count": 0,
                            "doc_info": dict(value),
                            "context": context,
                        }
                    unique[key]["count"] += 1
    finally:
        mongo_client.close()

    top_mentions = sorted(unique.items(), key=lambda item: item[1]["count"], reverse=True)[: args.top]
    root_counts = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for (mention_type, information), item in top_mentions:
        count = item["count"]
        doc_info = dict(item["doc_info"])
        doc_info.setdefault("type", mention_type)

        resolved_id, extracted = search_reference_doc(
            doc_info=doc_info,
            law_titles_for_regex=config.law_titles_for_regex,
            law_dataframe=config.laws_dataframe,
            cls_nam_ban_hanh=item["context"]["cls_year"],
            cls_co_quan_ban_hanh=item["context"]["authority"],
            es_client=es_client,
        )
        if resolved_id is not None:
            root = "resolved_by_current_code"
            exact_hits: list[dict[str, Any]] = []
            title_date_hits: list[dict[str, Any]] = []
        else:
            components = extract_document_components(
                str(doc_info.get("information") or ""),
                mention_type,
                config.law_titles_for_regex,
            ) or {}
            category = broad_category(mention_type, information)
            exact_hits = _exact_so_hieu_hits(es_client, components.get("so_hieu") or "")
            root = classify_unresolved_with_exact_hits(
                mention_type=mention_type,
                information=information,
                components=components,
                exact_hits=exact_hits,
            )
            title_date_hits = []
            title_date_root = _title_date_root_cause(
                category,
                components,
                _law_title_date_hits(
                    es_client,
                    components.get("tieu_de") or "",
                    components.get("loai_van_ban") or "",
                    components.get("ngay"),
                    components.get("thang"),
                    components.get("nam"),
                ),
            )
            if title_date_root:
                root = title_date_root

        root_counts[root] += count
        if len(samples[root]) < args.sample_limit:
            hit_source = exact_hits[0].get("_source") if exact_hits else None
            samples[root].append(
                {
                    "count": count,
                    "mention_type": mention_type,
                    "information": information,
                    "resolved_id": resolved_id,
                    "extracted": extracted,
                    "sample_exact_hit": hit_source,
                }
            )

    return {
        "collection": f"{args.db}.{args.coll}",
        "top_unique_limit": args.top,
        "failed_mentions_in_mongo": stats["failed_mentions_in_mongo"],
        "kept_by_current_failed_filter": stats["kept_by_current_failed_filter"],
        "dropped_by_current_failed_filter": stats["dropped_by_current_failed_filter"],
        "unique_kept_failed_mentions": len(unique),
        "top_weighted_total": sum(item["count"] for _, item in top_mentions),
        "root_summary": root_counts.most_common(),
        "samples": samples,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--db", default="ie")
    parser.add_argument("--coll", default="ie_collection")
    parser.add_argument("--top", type=int, default=1000)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--output", help="Optional JSON output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_audit(args)
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))


if __name__ == "__main__":
    main()
