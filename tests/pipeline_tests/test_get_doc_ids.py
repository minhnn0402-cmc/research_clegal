import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import get_doc_ids


SAMPLE_DOCS = [
    # Central legal doc (Trung ương + Luật) -> legal + central
    {"cls_ID": 1, "cls_info": {"loai_van_ban": "Luật Đất đai", "dia_danh": "Trung ương", "don_vi": []}},
    # Central non-legal doc (Trung ương, not Luật/Bộ luật/Hiến pháp) -> central only
    {"cls_ID": 2, "cls_info": {"loai_van_ban": "Nghị định", "dia_danh": "Trung ương", "don_vi": []}},
    # Local doc (no Trung ương, has dia_danh) -> local only
    {"cls_ID": 3, "cls_info": {"loai_van_ban": "Quyết định", "dia_danh": "Hà Nội", "don_vi": []}},
    # Dự thảo -> excluded entirely
    {"cls_ID": 4, "cls_info": {"loai_van_ban": "Dự thảo Luật Đất đai", "dia_danh": "Trung ương", "don_vi": []}},
    # Missing loai_van_ban -> excluded entirely
    {"cls_ID": 5, "cls_info": {"loai_van_ban": "", "dia_danh": "Trung ương", "don_vi": []}},
    # No dia_danh/don_vi and not Trung ương -> excluded (neither central nor local)
    {"cls_ID": 6, "cls_info": {"loai_van_ban": "Quyết định", "dia_danh": "", "don_vi": []}},
]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def batch_size(self, n):
        return self

    def __iter__(self):
        return iter(self._docs)


def _make_collection(docs):
    collection = MagicMock()
    collection.find.return_value = _FakeCursor(docs)
    return collection


class TestGetDocIds(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._base = Path(self._tmpdir.name)

        self._paths = {
            "CENTRAL_IDS_PATH": self._base / "central_ids.json",
            "LOCAL_IDS_PATH": self._base / "local_ids.json",
            "LAW_IDS_PATH": self._base / "law_ids.json",
            "LATEST_CENTRAL_IDS_PATH": self._base / "latest_central_ids.json",
            "LATEST_LOCAL_IDS_PATH": self._base / "latest_local_ids.json",
            "LATEST_LAW_IDS_PATH": self._base / "latest_law_ids.json",
        }
        self._patches = [
            patch.object(get_doc_ids, name, str(path))
            for name, path in self._paths.items()
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def _read(self, key):
        path = self._paths[key]
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _make_conn_manager(self, docs):
        collection = _make_collection(docs)
        conn_manager = MagicMock()
        conn_manager.register_mongo_from_env.return_value = None
        conn_manager.get_mongo_collection.return_value = collection
        conn_manager.get_mongo_client.return_value.admin.command.return_value = {"ok": 1}
        return conn_manager, collection

    def test_classifies_and_writes_all_six_files_on_first_run(self):
        conn_manager, _ = self._make_conn_manager(SAMPLE_DOCS)

        result = get_doc_ids.get_doc_ids(conn_manager=conn_manager)

        self.assertEqual(set(result), {
            "central_ids", "local_ids", "law_ids",
            "latest_central_ids", "latest_local_ids", "latest_law_ids",
        })
        self.assertEqual(self._read("LAW_IDS_PATH"), [1])
        self.assertEqual(self._read("CENTRAL_IDS_PATH"), [1, 2])
        self.assertEqual(self._read("LOCAL_IDS_PATH"), [3])
        self.assertEqual(self._read("LATEST_LAW_IDS_PATH"), [1])
        self.assertEqual(self._read("LATEST_CENTRAL_IDS_PATH"), [1, 2])
        self.assertEqual(self._read("LATEST_LOCAL_IDS_PATH"), [3])

    def test_excludes_du_thao_and_docs_without_loai_van_ban_or_location(self):
        conn_manager, _ = self._make_conn_manager(SAMPLE_DOCS)

        get_doc_ids.get_doc_ids(conn_manager=conn_manager)

        all_written_ids = set(self._read("LAW_IDS_PATH")) | set(self._read("CENTRAL_IDS_PATH")) | set(self._read("LOCAL_IDS_PATH"))
        self.assertNotIn(4, all_written_ids)
        self.assertNotIn(5, all_written_ids)
        self.assertNotIn(6, all_written_ids)

    def test_incremental_run_only_reports_new_ids_in_latest_files(self):
        get_doc_ids.save_ids_to_file(str(self._paths["CENTRAL_IDS_PATH"]), [1, 2])
        get_doc_ids.save_ids_to_file(str(self._paths["LOCAL_IDS_PATH"]), [3])
        get_doc_ids.save_ids_to_file(str(self._paths["LAW_IDS_PATH"]), [1])

        new_doc = {"cls_ID": 7, "cls_info": {"loai_van_ban": "Luật Cạnh tranh", "dia_danh": "Trung ương", "don_vi": []}}
        conn_manager, _ = self._make_conn_manager(SAMPLE_DOCS + [new_doc])

        get_doc_ids.get_doc_ids(conn_manager=conn_manager)

        self.assertEqual(self._read("LATEST_LAW_IDS_PATH"), [7])
        self.assertEqual(self._read("LATEST_CENTRAL_IDS_PATH"), [7])
        self.assertEqual(self._read("LATEST_LOCAL_IDS_PATH"), [])
        # Cumulative files grow by exactly the new IDs, preserving prior order.
        self.assertEqual(self._read("LAW_IDS_PATH"), [1, 7])
        self.assertEqual(self._read("CENTRAL_IDS_PATH"), [1, 2, 7])
        self.assertEqual(self._read("LOCAL_IDS_PATH"), [3])

    def test_returns_none_and_writes_nothing_when_connection_fails(self):
        conn_manager = MagicMock()
        conn_manager.register_mongo_from_env.side_effect = RuntimeError("no connection")

        result = get_doc_ids.get_doc_ids(conn_manager=conn_manager)

        self.assertIsNone(result)
        for path in self._paths.values():
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
