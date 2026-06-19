from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def test_cls_181_diem_c_khoan_2_dieu_38_definition_replacement_targets():
    """Mongo cls_ID=999999999646124, diem c/khoan 2/dieu 38."""
    config = ConfigLoader()
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
    )
    content = (
        "c) Quy định việc xác định sản phẩm có tổng giá trị tài nguyên, khoáng sản "
        "cộng với chi phí năng lượng chiếm từ 51% giá thành sản phẩm trở lên tại "
        "điểm a khoản 1 Điều 11 và khoản 2 Điều 15 Nghị định số 134/2016/NĐ-CP "
        "ngày 01 tháng 9 năm 2016 của Chính phủ quy định chi tiết một số điều và "
        "biện pháp thi hành Luật Thuế xuất khẩu, thuế nhập khẩu (đã được sửa đổi, "
        "bổ sung tại Nghị định số 18/2021/NĐ-CP ngày 11 tháng 3 năm 2021 của "
        "Chính phủ sửa đổi, bổ sung một số điều của Nghị định số 134/2016/NĐ-CP "
        "ngày 01 tháng 9 năm 2016 của Chính phủ quy định chi tiết một số điều và "
        "biện pháp thi hành Luật Thuế xuất khẩu, thuế nhập khẩu), điểm b khoản 2 "
        "Điều 4 và Mẫu số 14, Phụ lục II ban hành kèm theo Nghị định số "
        "26/2023/NĐ-CP ngày 31 tháng 5 năm 2023 của Chính phủ về Biểu thuế xuất "
        "khẩu, Biểu thuế nhập khẩu ưu đãi, Danh mục hàng hóa và mức thuế tuyệt "
        "đối, thuế hỗn hợp và thuế nhập khẩu ngoài hạn ngạch thuế quan bằng quy "
        "định tại Phụ lục V ban hành kèm theo Nghị định này."
    )

    predictions = extract_single_clause(
        extractor=extractor,
        so_hieu="181/2025/NĐ-CP",
        title="Nghị định 181/2025/NĐ-CP hướng dẫn Luật Thuế giá trị gia tăng",
        clause_type="diem",
        content=content,
        parent_content="2. Nghị định này thay thế:",
        grandparent_content="Điều 38. Hiệu lực thi hành",
        idx=1,
        law_titles=config.law_titles_for_regex,
        cls_document_type="Nghị định",
        use_llm=False,
    )
    pairs = {(item["relation"], item["reference"]) for item in predictions}

    assert (
        "sua_doi",
        "điểm a khoản 1 Điều 11 Nghị định số 134/2016/NĐ-CP ngày 01 tháng 9 năm 2016",
    ) in pairs
    assert (
        "sua_doi",
        "khoản 2 Điều 15 Nghị định số 134/2016/NĐ-CP ngày 01 tháng 9 năm 2016",
    ) in pairs
    assert (
        "thay_the",
        "điểm b khoản 2 Điều 4 Nghị định số 26/2023/NĐ-CP ngày 31 tháng 5 năm 2023",
    ) in pairs
    assert ("dan_chieu", "Nghị định 181/2025/NĐ-CP") in pairs

    assert (
        "thay_the",
        "điểm a khoản 1 Điều 11 Nghị định số 134/2016/NĐ-CP ngày 01 tháng 9 năm 2016",
    ) not in pairs
    assert not any(
        "18/2021/NĐ-CP" in item["reference"]
        for item in predictions
    )
