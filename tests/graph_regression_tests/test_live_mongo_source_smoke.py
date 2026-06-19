import os

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient


pytestmark = pytest.mark.skipif(
    os.getenv("CLS_ENABLE_LIVE_MONGO_TESTS") != "1",
    reason="Live Mongo tests are opt-in. Set CLS_ENABLE_LIVE_MONGO_TESTS=1.",
)


def _load_env():
    values = dotenv_values(".env")
    return {str(key): str(value) for key, value in values.items() if key and value is not None}


def _connect(env):
    database = env["CLS_DATABASE"]
    last_error = None
    for auth_source in (database, "admin", None):
        try:
            kwargs = {
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

    raise RuntimeError(f"Cannot connect to Mongo: {last_error}")


def test_live_mongo_doc_999999999624015_source_contract():
    env = _load_env()
    client = _connect(env)
    try:
        collection = client[env["CLS_DATABASE"]][env.get("CLS_COLLECTION", "cls_ver2")]
        doc = collection.find_one(
            {"cls_ID": 999999999624015},
            {
                "_id": 0,
                "cls_ID": 1,
                "cls_info.title": 1,
                "cls_info.title_without_number": 1,
                "cls_info.so_hieu": 1,
                "cls_info.loai_van_ban": 1,
                "cls_parsing.com_key": 1,
            },
        )
    finally:
        client.close()

    assert doc is not None
    assert doc["cls_info"]["so_hieu"] == "102/2025/QH15"
    assert doc["cls_info"]["loai_van_ban"] == "Luật"
    assert len(doc.get("cls_parsing") or []) == 175
