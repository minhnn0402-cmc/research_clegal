from scripts.audit_failed_graph_resolution import (
    _so_hieu_variants,
    broad_category,
    classify_unresolved_with_exact_hits,
)


def test_failed_resolution_audit_classifies_exact_hit_gap() -> None:
    result = classify_unresolved_with_exact_hits(
        mention_type="nghidinh",
        information="Nghị định số 01/2018/NĐ-CP ngày 06 tháng 8 năm 2018",
        components={
            "so_hieu": "01/2018/nđ-cp",
            "loai_van_ban": "Nghị định",
            "ngay": "06",
            "thang": "08",
            "nam": 2018,
        },
        exact_hits=[
            {
                "_source": {
                    "ID": 1,
                    "so_hieu": "01/2018/NĐ-CP",
                    "loai_van_ban": "Nghị định",
                    "ngay_ban_hanh": "2018-08-06T00:00:00Z",
                }
            }
        ],
    )

    assert result == "nonlaw_full_code:exact_compatible_but_resolver_failed"


def test_failed_resolution_audit_separates_date_mismatch_from_missing_index() -> None:
    date_mismatch = classify_unresolved_with_exact_hits(
        mention_type="nghidinh",
        information="Nghị định số 01/2018/NĐ-CP ngày 06 tháng 8 năm 2018",
        components={
            "so_hieu": "01/2018/nđ-cp",
            "loai_van_ban": "Nghị định",
            "ngay": "06",
            "thang": "08",
            "nam": 2018,
        },
        exact_hits=[
            {
                "_source": {
                    "ID": 1,
                    "so_hieu": "01/2018/NĐ-CP",
                    "loai_van_ban": "Nghị định",
                    "ngay_ban_hanh": "2018-08-05T00:00:00Z",
                }
            }
        ],
    )
    missing = classify_unresolved_with_exact_hits(
        mention_type="nghidinh",
        information="Nghị định số 01/2018/NĐ-CP ngày 06 tháng 8 năm 2018",
        components={"so_hieu": "01/2018/nđ-cp", "loai_van_ban": "Nghị định"},
        exact_hits=[],
    )

    assert date_mismatch == "nonlaw_full_code:exact_exists_date_mismatch"
    assert missing == "nonlaw_full_code:es_no_exact_so_hieu"


def test_failed_resolution_audit_classifies_law_title_without_number() -> None:
    assert (
        broad_category("luat", "Luật Khoáng sản ngày 20 tháng 3 năm 1996")
        == "law_title_date"
    )
    assert (
        classify_unresolved_with_exact_hits(
            mention_type="luat",
            information="Luật Khoáng sản ngày 20 tháng 3 năm 1996",
            components={"tieu_de": "luật khoáng sản", "ngay": "20", "thang": "03", "nam": 1996},
            exact_hits=[],
        )
        == "law_title_date:no_so_hieu"
    )


def test_failed_resolution_audit_uses_canonical_exact_variants() -> None:
    variants = _so_hieu_variants("24/2010/qđ-ttg")

    assert "24/2010/QĐ-TTg" in variants
    assert "24/2010/QD-TTg" in variants
