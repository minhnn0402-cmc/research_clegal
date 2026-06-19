import json
from pathlib import Path


DATA_PATH = Path(__file__).parent.parent / "test_data" / "mongo_source_contract_cases.json"


def test_mongo_source_contract_uses_loai_van_ban_as_document_type():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    cases = [case for case in data["cases"] if case["status"] == "active"]

    assert cases
    for case in cases:
        cls_info = case["cls_info"]
        expected = case["expected"]

        cls_document_type = cls_info.get("loai_van_ban", "")

        assert cls_document_type == expected["cls_document_type"]
        assert cls_info.get("doc_type") is None
        assert "loai_van_ban" in cls_info
