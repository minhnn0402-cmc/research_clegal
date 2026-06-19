import csv
import json
from pathlib import Path

from training.prepare_dapt_corpus import (
    clean_legal_text,
    evenly_spaced_sample,
    prepare_corpus,
)


def test_clean_legal_text_strips_html_and_preserves_table_text():
    text = clean_legal_text(
        'Điều 1.<p>Nội dung</p>[TABLE]<table><tr><td>A</td><td>B</td></tr></table>'
    )
    assert "<table" not in text
    assert "Nội dung" in text
    assert "A" in text and "B" in text
    assert "[TABLE]" in text


def test_evenly_spaced_sample_preserves_document_coverage():
    rows = [{"index": index} for index in range(10)]
    selected = evenly_spaced_sample(rows, 4)
    assert [row["index"] for row in selected] == [0, 3, 6, 9]


def test_prepare_corpus_excludes_golden_and_splits_by_document(tmp_path: Path):
    source = tmp_path / "source.jsonl"
    golden = tmp_path / "gold.csv"
    output = tmp_path / "dapt"

    with golden.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["so_hieu"])
        writer.writeheader()
        writer.writerow({"so_hieu": "10/2025/NĐ-CP"})

    docs = [
        {
            "cls_ID": 1,
            "cls_info": {
                "so_hieu": "10/2025/NĐ-CP",
                "title": "Nghị định bị loại khỏi DAPT",
                "loai_van_ban": "Nghị định",
                "ngay_ban_hanh": "2025-01-01",
            },
            "cls_parsing": [
                {
                    "com_key": "dieu_1",
                    "com_type": "dieu",
                    "com_title": "Điều 1. Nội dung benchmark không được phép vào corpus.",
                }
            ],
        },
        {
            "cls_ID": 2,
            "cls_info": {
                "so_hieu": "11/2025/NĐ-CP",
                "title": "Nghị định dùng cho DAPT",
                "loai_van_ban": "Nghị định",
                "ngay_ban_hanh": "2025-01-02",
            },
            "cls_parsing": [
                {
                    "com_key": "dieu_1",
                    "com_type": "dieu",
                    "com_title": "<p>Điều 1. Nội dung pháp luật đủ dài để sử dụng.</p>",
                }
            ],
        },
    ]
    source.write_text(
        "".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs),
        encoding="utf-8",
    )

    manifest = prepare_corpus(
        source,
        output,
        golden_path=golden,
        validation_ratio=0.05,
        min_chars=10,
    )
    assert manifest["statistics"]["documents_excluded_golden_overlap"] == 1
    combined = (
        (output / "train.jsonl").read_text(encoding="utf-8")
        + (output / "validation.jsonl").read_text(encoding="utf-8")
    )
    assert "10/2025/NĐ-CP" not in combined
    assert "11/2025/NĐ-CP" in combined
    assert "<p>" not in combined
