"""Shared helpers for graph regression test suites."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch


DATA_PATH = Path(__file__).parent.parent / "test_data" / "graph_regression_cases.json"
DOC_TYPES = ["Luật", "Nghị quyết", "Nghị định", "Thông tư", "Quyết định", "Công văn", "Hướng dẫn"]
CLAUSE_TYPES = ["điểm", "khoản", "Điều"]


def load_cases() -> Dict[str, Any]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def active(cases: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    return (case for case in cases if case.get("status") == "active")


def component_signature(reference: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[str]]:
    return {
        "diem": reference.get("diem", {}).get("information"),
        "khoan": reference.get("khoan", {}).get("information"),
        "dieu": reference.get("dieu", {}).get("information"),
        "luat": reference.get("luat", {}).get("information"),
        "nghidinh": reference.get("nghidinh", {}).get("information"),
        "thongtu": reference.get("thongtu", {}).get("information"),
        "quyetdinh": reference.get("quyetdinh", {}).get("information"),
        "congvan": reference.get("congvan", {}).get("information"),
    }


def trim_signature(signature: Dict[str, Optional[str]]) -> Dict[str, str]:
    return {key: value for key, value in signature.items() if value is not None}


def make_reference(content: str, reference_text: str, reference_key: str) -> Dict[str, Dict[str, Any]]:
    start = content.index(reference_text)
    return {
        reference_key: {
            "information": reference_text,
            "position_start": start,
            "position_end": start + len(reference_text),
        }
    }


class FakeElasticsearch:
    def __init__(self, hits: List[Dict[str, Any]]):
        self.hits = hits
        self.last_index = None
        self.last_body = None

    def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.last_index = index
        self.last_body = body
        return {"hits": {"hits": self.hits}}


class _FakeBatchProcessorConfig:
    def __init__(self, **kwargs: Any):
        self.__dict__.update(kwargs)


class _FakeBatchProcessor:
    def __init__(self, *args: Any, **kwargs: Any):
        pass


class _FakeConnectionManager:
    def register_mongo_from_env(self, *args: Any, **kwargs: Any) -> None:
        pass

    def register_neo4j_from_env(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_mongo_collection(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def get_neo4j_driver(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def close_all(self) -> None:
        pass


class _FakeRepository:
    def __init__(self, *args: Any, **kwargs: Any):
        pass


class _FakeNodePreparationService:
    def __init__(self, *args: Any, **kwargs: Any):
        pass


class _FakeCheckpointManager:
    def __init__(self, *args: Any, **kwargs: Any):
        pass


def _module(name: str, **attributes: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def import_service_module_with_fake_infrastructure(module_name: str) -> Any:
    """Import service modules without requiring MongoDB/Neo4j client packages."""
    fake_pymongo_errors = _module(
        "pymongo.errors",
        NotPrimaryError=Exception,
        AutoReconnect=Exception,
        CursorNotFound=Exception,
    )
    fake_modules = {
        "pymongo": _module("pymongo", MongoClient=object, UpdateOne=object),
        "pymongo.collection": _module("pymongo.collection", Collection=object),
        "pymongo.errors": fake_pymongo_errors,
        "neo4j": _module(
            "neo4j",
            GraphDatabase=types.SimpleNamespace(driver=lambda *args, **kwargs: None),
        ),
        "dotenv": _module("dotenv", load_dotenv=lambda *args, **kwargs: None),
        "src.infrastructure.connections": _module(
            "src.infrastructure.connections",
            ConnectionManager=_FakeConnectionManager,
            get_connection_manager=lambda: _FakeConnectionManager(),
        ),
        "src.services.base_processor": _module(
            "src.services.base_processor",
            BatchProcessor=_FakeBatchProcessor,
            BatchProcessorConfig=_FakeBatchProcessorConfig,
        ),
        "src.repositories.mongo_repository": _module(
            "src.repositories.mongo_repository",
            MongoRepository=_FakeRepository,
        ),
        "src.repositories.neo4j_repository": _module(
            "src.repositories.neo4j_repository",
            Neo4jRepository=_FakeRepository,
        ),
        "src.services.node_preparation_service": _module(
            "src.services.node_preparation_service",
            NodePreparationService=_FakeNodePreparationService,
        ),
        "src.shared.checkpoint": _module(
            "src.shared.checkpoint",
            CheckpointManager=_FakeCheckpointManager,
        ),
    }

    sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, fake_modules):
        return importlib.import_module(module_name)
