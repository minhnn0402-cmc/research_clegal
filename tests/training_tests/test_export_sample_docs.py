from scripts.export_sample_docs import (
    allocate_counts,
    build_cell_targets,
    classify_relation,
    classify_year,
    compact_document,
)


def test_targets_sum_to_requested_limit():
    assert sum(build_cell_targets(3000).values()) == 3000
    assert allocate_counts(7, {"a": 0.5, "b": 0.5}) == {"a": 4, "b": 3}


def test_classification_uses_year_and_relation_metadata():
    assert classify_year("2026-05-12T00:00:00Z") == "Y1"
    assert classify_year("2021-01-01") == "Y2"
    assert classify_year("2017-01-01") == "Y3"
    assert classify_year("2009-01-01") == "Y4"

    assert classify_relation(
        {
            "cls_info": {"title": "Nghị định sửa đổi một số điều"},
            "cls_luoc_do": {},
        }
    ) == "R1"
    assert classify_relation(
        {
            "cls_info": {"title": "Nghị định thông thường"},
            "cls_luoc_do": {"van_ban_huong_dan": [1]},
        }
    ) == "R2"


def test_compaction_removes_heavy_fields_and_requires_supported_clause():
    candidate_doc = {
        "cls_ID": 1,
        "cls_info": {
            "so_hieu": "10/2025/NĐ-CP",
            "title": "Nghị định ví dụ",
            "loai_van_ban": "Nghị định",
            "ngay_ban_hanh": "2025-01-01",
            "download_links": {"FileAttach": "large"},
        },
        "raw_text": "unused",
        "cls_luoc_do": {"unused": [1]},
        "cls_parsing": [
            {
                "com_key": "dieu_1",
                "com_type": "dieu",
                "com_title": "Điều 1. Bãi bỏ Nghị định số 1/2020/NĐ-CP.",
                "com_html": "<p>large</p>",
                "com_title_embedding": "large",
            },
            {
                "com_key": "muc_1",
                "com_type": "muc1",
                "com_title": "Mục không dùng",
            },
        ],
    }
    from scripts.export_sample_docs import Candidate

    compact, reason, text_hash = compact_document(
        candidate_doc,
        Candidate(1, "Y1", "R1", "Nghị định", "central"),
        max_clause_chars=1000,
        max_document_chars=5000,
    )
    assert reason is None
    assert text_hash
    assert compact is not None
    assert set(compact) == {"cls_ID", "cls_info", "cls_parsing", "_sample"}
    assert compact["cls_parsing"] == [
        {
            "com_key": "dieu_1",
            "com_type": "dieu",
            "com_title": "Điều 1. Bãi bỏ Nghị định số 1/2020/NĐ-CP.",
        }
    ]
    assert "download_links" not in compact["cls_info"]
