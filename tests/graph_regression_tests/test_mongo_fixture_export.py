from scripts.export_mongo_source_case import (
    build_relation_fixture_case,
    build_snapshot,
    parse_relation_assertion,
)


def test_build_snapshot_keeps_clause_content_for_offline_fixture():
    doc = {
        "cls_ID": 123,
        "_matched_query": {"cls_ID": 123},
        "cls_info": {
            "title": "Nghị định mẫu",
            "title_without_number": "Nghị định mẫu",
            "so_hieu": "01/2026/NĐ-CP",
            "loai_van_ban": "Nghị định",
        },
        "cls_parsing": [
            {
                "com_key": "dieu_1",
                "com_type": "dieu",
                "com_path": ["dieu_1"],
                "com_title": "Điều 1. Sửa đổi",
                "com_content": "Sửa đổi khoản 1 Điều 2 Nghị định số 02/2025/NĐ-CP.",
            }
        ],
    }

    snapshot = build_snapshot(doc, ["dieu_1"])

    clause = snapshot["selected_cls_parsing"][0]
    assert clause["com_content"] == "Sửa đổi khoản 1 Điều 2 Nghị định số 02/2025/NĐ-CP."
    assert snapshot["cls_info"]["loai_van_ban"] == "Nghị định"


def test_build_relation_fixture_case_uses_regression_schema():
    doc = {
        "cls_ID": 123,
        "_matched_query": {"cls_ID": 123},
        "cls_info": {
            "title": "Nghị định mẫu",
            "so_hieu": "01/2026/NĐ-CP",
            "loai_van_ban": "Nghị định",
        },
        "cls_parsing": [
            {
                "com_key": "dieu_1",
                "com_type": "dieu",
                "com_title": "Điều 1. Sửa đổi",
                "com_content": "Sửa đổi khoản 1 Điều 2 Nghị định số 02/2025/NĐ-CP.",
            }
        ],
    }

    case = build_relation_fixture_case(
        doc=doc,
        com_keys=["dieu_1"],
        case_id="CLS-SAMPLE",
        status="active",
        priority="P1",
        expected_relations=[
            parse_relation_assertion("sua_doi_bo_sung=Nghị định số 02/2025/NĐ-CP")
        ],
        forbidden_relations=[
            parse_relation_assertion("thay_the=Nghị định số 02/2025/NĐ-CP")
        ],
    )

    assert case["id"] == "CLS-SAMPLE"
    assert case["source"] == {
        "cls_ID": 123,
        "so_hieu": "01/2026/NĐ-CP",
        "title": "Nghị định mẫu",
        "loai_van_ban": "Nghị định",
    }
    assert case["data"][0]["com_content"].startswith("Sửa đổi khoản 1")
    assert case["expected_relations"] == [
        {
            "relation": "sua_doi_bo_sung",
            "reference": "Nghị định số 02/2025/NĐ-CP",
        }
    ]
    assert case["forbidden_relations"] == [
        {
            "relation": "thay_the",
            "reference": "Nghị định số 02/2025/NĐ-CP",
        }
    ]
