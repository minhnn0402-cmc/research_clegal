import csv
from pathlib import Path
import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def _refs_for_relation(predictions, relation):
    return [
        item["reference"]
        for item in predictions or []
        if item.get("relation") == relation
    ]


def _load_dataset_clause(so_hieu, content_prefix):
    dataset_path = Path(__file__).parents[2] / "evaluation" / "datasets" / "relation_pairs.csv"
    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("so_hieu") == so_hieu and row.get("content", "").startswith(content_prefix):
                return row
    raise AssertionError(f"Missing dataset clause for {so_hieu}: {content_prefix}")


class TestActionRelationScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )
        cls.law_titles = config.law_titles_for_regex

    def test_bai_bo_stops_before_descriptive_keo_dai_title(self) -> None:
        content = (
            "Điều khoản thi hành Bãi bỏ Nghị quyết số 25/2023/NQ-HĐND "
            "ngày 07 tháng 12 năm 2023 của Hội đồng nhân dân tỉnh Thừa Thiên Huế "
            "về việc kéo dài thời gian thực hiện Nghị quyết số 18/2022/NQ-HĐND "
            "ngày 07 tháng 9 năm 2022 và Nghị quyết số 25/2022/NQ-HĐND "
            "ngày 08 tháng 12 năm 2022 của Hội đồng nhân dân tỉnh Thừa Thiên Huế."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="38/2024/NQ-HĐND",
            title="Nghị quyết kéo dài thời gian thực hiện thí điểm một số chính sách",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "bai_bo"),
            ["Nghị quyết số 25/2023/NQ-HĐND ngày 07 tháng 12 năm 2023"],
        )

    def test_bai_bo_published_content_is_partial_amendment(self) -> None:
        """'Bãi bỏ nội dung … công bố tại <doc>' partially amends the doc (sdbs).

        Removing some content published in a document is a partial amendment, not
        a full repeal — distinct from 'Bãi bỏ Điều/khoản của <doc>' (bai_bo).
        """
        content = (
            "Điều 3. Quyết định này có hiệu lực kể từ ngày ký. "
            "Bãi bỏ nội dung đã công bố tại Quyết định số 830/QĐ-UBND "
            "ngày 22/3/2024 của Chủ tịch UBND tỉnh."
        )
        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="01082/QĐ-UBND",
            title="Quyết định công bố thủ tục hành chính",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=20,
            law_titles=self.law_titles,
        )
        self.assertTrue(
            any("830/QĐ-UBND" in r for r in _refs_for_relation(predictions, "sua_doi_bo_sung")),
            predictions,
        )

    def test_bai_bo_of_specific_clause_stays_bai_bo(self) -> None:
        """Hard-negative: 'Bãi bỏ khoản X Điều Y <doc>' is a genuine repeal."""
        content = "1. Bãi bỏ khoản 5 Điều 25 Thông tư số 02/2014/TT-BCT ngày 16 tháng 01 năm 2014."
        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="44/2024/TT-BCT",
            title="Thông tư",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=21,
            law_titles=self.law_titles,
        )
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])
        self.assertTrue(
            any("02/2014/TT-BCT" in r for r in _refs_for_relation(predictions, "bai_bo")),
            predictions,
        )

    def test_content_expiry_distributes_sua_doi_bo_sung_across_document_list(self) -> None:
        """Partial-content expiry amends every listed document (sua_doi_bo_sung).

        "Các thủ tục hành chính … công bố tại các Quyết định A; B; C … hết hiệu
        lực" supersedes the procedures published in each document, so all of them
        are partially amended — not just the one nearest the expiry cue, and not
        as thay_the/bai_bo.
        """
        content = (
            "Điều 2. Quyết định này có hiệu lực thi hành kể từ ngày ký.\n"
            "Các thủ tục hành chính tương ứng đã công bố tại Quyết định số "
            "11/2020/QĐ-UBND ngày 01/01/2020; Quyết định số 12/2021/QĐ-UBND ngày "
            "02/02/2021; Quyết định số 13/2022/QĐ-UBND ngày 03/03/2022 hết hiệu lực "
            "kể từ ngày Quyết định này có hiệu lực thi hành."
        )
        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="99/2099/QĐ-UBND",
            title="Quyết định công bố thủ tục hành chính",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=10,
            law_titles=self.law_titles,
        )
        sdbs = _refs_for_relation(predictions, "sua_doi_bo_sung")
        for num in ("11/2020/QĐ-UBND", "12/2021/QĐ-UBND", "13/2022/QĐ-UBND"):
            self.assertTrue(any(num in ref for ref in sdbs), (num, predictions))
        # not misclassified as a whole-document replacement/repeal
        self.assertEqual(_refs_for_relation(predictions, "thay_the"), [])
        self.assertEqual(_refs_for_relation(predictions, "bai_bo"), [])

    def test_whole_document_expiry_stays_single_whole_document_relation(self) -> None:
        """Hard-negative: a whole-document expiry is a single whole-doc relation,
        never the distributed sua_doi_bo_sung."""
        content = (
            "Điều 2. Quyết định này có hiệu lực thi hành kể từ ngày ký và thay thế "
            "Quyết định số 99/2010/QĐ-UBND ngày 01/01/2010."
        )
        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="10/2025/QĐ-UBND",
            title="Quyết định",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=11,
            law_titles=self.law_titles,
        )
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])
        whole_doc = (
            _refs_for_relation(predictions, "thay_the")
            + _refs_for_relation(predictions, "bai_bo")
        )
        self.assertTrue(any("99/2010/QĐ-UBND" in ref for ref in whole_doc), predictions)

    def test_huy_bo_stops_before_descriptive_thu_hoi_title(self) -> None:
        content = (
            "Điều 1. Hủy bỏ toàn bộ nội dung Quyết định số 05/2011/QĐ-UBND "
            "ngày 09 tháng 8 năm 2011 của Ủy ban nhân dân quận 7 về thu hồi "
            "Quyết định số 06/2009/QĐ-UBND ngày 07 tháng 4 năm 2009 của "
            "Ủy ban nhân dân quận 7 về Quy trình thẩm định, phê duyệt quy hoạch."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="06/2011/QĐ-UBND",
            title="Quyết định hủy bỏ văn bản quy phạm pháp luật",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "huy_bo"),
            ["Quyết định số 05/2011/QĐ-UBND ngày 09 tháng 8 năm 2011"],
        )

    def test_inherited_bai_bo_list_item_ignores_inner_repeal_title_clause(self) -> None:
        content = (
            "Thông tư số 05/2020/TT-BNV ngày 09 tháng 11 năm 2020 của Bộ trưởng "
            "Bộ Nội vụ bãi bỏ khoản 7 Điều 2 Thông tư số 12/2019/TT-BNV "
            "ngày 04 tháng 11 năm 2019 của Bộ trưởng Bộ Nội vụ quy định chi tiết "
            "thi hành một số điều của Nghị định số 91/2017/NĐ-CP."
        )
        parent_content = (
            "Bãi bỏ toàn bộ văn bản quy phạm pháp luật\r\n"
            "Bãi bỏ toàn bộ 20 văn bản quy phạm pháp luật do Bộ trưởng Bộ Nội vụ "
            "ban hành, liên tịch ban hành sau đây:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="10/2024/TT-BNV",
            title="Thông tư bãi bỏ một số văn bản quy phạm pháp luật",
            clause_type="khoan",
            content=content,
            parent_content=parent_content,
            grandparent_content="",
            idx=3,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "bai_bo"),
            ["Thông tư số 05/2020/TT-BNV ngày 09 tháng 11 năm 2020"],
        )

    def test_dinh_chi_expands_multiple_khoan_targets_under_shared_decision(self) -> None:
        content = (
            "Điều 1. Đình chỉ thi hành Khoản 1 của Điều 8, Quy định kèm theo "
            "Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010 của Ủy ban nhân dân "
            "tỉnh Cà Mau ban hành Quy định về quản lý và bảo vệ động vật hoang dã; "
            "Khoản 2, Khoản 3 của Điều 1 và loài rùa hộp lưng đen thuộc "
            "Quyết định số 03/2014/QĐ-UBND ngày 08/02/2014 của Ủy ban nhân dân "
            "tỉnh Cà Mau sửa đổi, bổ sung một số điều của Quy định."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="1739/QĐ-UBND",
            title="Quyết định đình chỉ thi hành quy định quản lý và bảo vệ động vật hoang dã",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=4,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dinh_chi"),
            [
                "khoản 1 Điều 8 Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010",
                "khoản 2 Điều 1 Quyết định số 03/2014/QĐ-UBND ngày 08/02/2014",
                "khoản 3 Điều 1 Quyết định số 03/2014/QĐ-UBND ngày 08/02/2014",
            ],
        )
        self.assertEqual(_refs_for_relation(predictions, "dan_chieu"), [])

    def test_subject_repeal_semicolon_clause_targets_are_bai_bo(self) -> None:
        content = (
            "7. Bãi bỏ các quy định về trình độ cao đẳng, trường cao đẳng; "
            "Điều 3; điểm b khoản 3 và điểm b khoản 5 Điều 6 "
            "Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011 "
            "của Bộ trưởng Bộ Giáo dục và Đào tạo quy định điều kiện, hồ sơ, "
            "quy trình mở ngành đào tạo, đình chỉ tuyển sinh, thu hồi quyết định "
            "mở ngành đào tạo trình độ đại học, trình độ cao đẳng."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="143/2016/NĐ-CP",
            title="Nghị định điều kiện đầu tư hoạt động trong lĩnh vực giáo dục nghề nghiệp",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=5,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "bai_bo"),
            [
                "Điều 3 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
                "điểm b khoản 3 Điều 6 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
                "điểm b khoản 5 Điều 6 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
            ],
        )
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])
        self.assertEqual(_refs_for_relation(predictions, "dan_chieu"), [])

    def test_subject_repeal_generic_semicolon_clause_targets_stay_bai_bo(self) -> None:
        content = (
            "Bãi bỏ các quy định; Điều 3; điểm b khoản 3 và điểm b khoản 5 Điều 6 "
            "Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011 "
            "của Bộ trưởng Bộ Giáo dục và Đào tạo."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="143/2016/NĐ-CP",
            title="Nghị định điều kiện đầu tư hoạt động trong lĩnh vực giáo dục nghề nghiệp",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=5,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "bai_bo"),
            [
                "Điều 3 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
                "điểm b khoản 3 Điều 6 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
                "điểm b khoản 5 Điều 6 Thông tư số 08/2011/TT-BGDĐT ngày 17 tháng 02 năm 2011",
            ],
        )
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])

    def test_operational_dinh_chi_parent_does_not_override_dan_chieu(self) -> None:
        content = (
            "2. Viện kiểm sát nơi Tòa án đã ra quyết định thi hành án kiểm sát "
            "việc Tòa án ra quyết định đình chỉ thi hành án theo quy định tại "
            "khoản 4 Điều 23, khoản 5 Điều 25, khoản 7 Điều 37, khoản 5 Điều 59, "
            "khoản 5 Điều 85, khoản 5 Điều 97, khoản 6 Điều 107, khoản 6 Điều 112, "
            "khoản 6 Điều 125 và khoản 7 Điều 129 Luật Thi hành án hình sự."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="259/QĐ-VKSTC",
            title=(
                "Quyết định về Quy chế công tác kiểm sát việc tạm giữ, tạm giam, "
                "thi hành án hình sự"
            ),
            clause_type="khoan",
            content=content,
            parent_content="Điều 13. Kiểm sát việc đình chỉ thi hành án",
            grandparent_content="",
            idx=6,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "dinh_chi"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            [
                "khoản 4 Điều 23 Luật Thi hành án hình sự",
                "khoản 5 Điều 25 Luật Thi hành án hình sự",
                "khoản 7 Điều 37 Luật Thi hành án hình sự",
                "khoản 5 Điều 59 Luật Thi hành án hình sự",
                "khoản 5 Điều 85 Luật Thi hành án hình sự",
                "khoản 5 Điều 97 Luật Thi hành án hình sự",
                "khoản 6 Điều 107 Luật Thi hành án hình sự",
                "khoản 6 Điều 112 Luật Thi hành án hình sự",
                "khoản 6 Điều 125 Luật Thi hành án hình sự",
                "khoản 7 Điều 129 Luật Thi hành án hình sự",
            ],
        )

    def test_ngung_hieu_luc_parent_does_not_override_continue_citation(self) -> None:
        content = (
            "2. Tiếp tục thực hiện các thủ tục điện tử đối với tàu biển xuất cảnh, "
            "nhập cảnh, quá cảnh; tàu bay xuất cảnh, nhập cảnh, quá cảnh thông qua "
            "Cơ chế một cửa quốc gia theo quy định tại Quyết định số 34/2016/QĐ-TTg "
            "ngày 23 tháng 8 năm 2016 của Thủ tướng Chính phủ đến hết ngày "
            "30 tháng 6 năm 2018."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="39/2018/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 58/2017/NĐ-CP",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 1. Ngưng hiệu lực thi hành đối với một số quy định tại "
                "Nghị định số 58/2017/NĐ-CP"
            ),
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "ngung_hieu_luc"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Quyết định số 34/2016/QĐ-TTg ngày 23 tháng 8 năm 2016"],
        )

    def test_detail_parent_does_not_override_child_scope_dan_chieu(self) -> None:
        content = (
            "1. Quy định về dữ liệu lâm sàng để bảo đảm an toàn, hiệu quả trong "
            "hồ sơ đăng ký thuốc cổ truyền và tiêu chí để xác định trường hợp "
            "miễn thử, miễn một số giai đoạn thử thuốc cổ truyền trên lâm sàng "
            "tại Việt Nam và thuốc cổ truyền phải yêu cầu thử lâm sàng giai đoạn "
            "4 tại khoản 2, khoản 3 Điều 72 và khoản 4 Điều 89 Luật Dược."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư về đăng ký lưu hành thuốc cổ truyền, dược liệu",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 1. Phạm vi điều chỉnh\r\r\n"
                "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều "
                "của Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung "
                "một số điều của Luật Dược ngày 21 tháng 11 năm 2024 "
                "(sau đây gọi là Luật Dược), bao gồm:"
            ),
            grandparent_content="",
            idx=7,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "quy_dinh_chi_tiet"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            [
                "khoản 2 Điều 72 Luật Dược",
                "khoản 3 Điều 72 Luật Dược",
                "khoản 4 Điều 89 Luật Dược",
            ],
        )

    def test_amendment_history_after_theo_quy_dinh_stays_dan_chieu(self) -> None:
        content = (
            "5. Mẫu nhãn thuốc cổ truyền, vị thuốc cổ truyền, dược liệu và tờ "
            "hướng dẫn sử dụng thuốc cổ truyền dự kiến lưu hành tại Việt Nam "
            "thực hiện theo quy định tại Thông tư số 01/2018/TT-BYT ngày "
            "18 tháng 01 năm 2018 của Bộ trưởng Bộ Y tế quy định ghi nhãn thuốc, "
            "nguyên liệu làm thuốc và tờ hướng dẫn sử dụng thuốc được sửa đổi, "
            "bổ sung tại Thông tư số 23/2023/TT-BYT ngày 30 tháng 11 năm 2023."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư về đăng ký lưu hành thuốc cổ truyền, dược liệu",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 5. Quy định chung về hồ sơ đăng ký lưu hành thuốc cổ truyền, "
                "vị thuốc cổ truyền, dược liệu"
            ),
            grandparent_content="",
            idx=8,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018"],
        )

    def test_sdbs_child_clause_inherits_title_document_and_parent_article(self) -> None:
        content = (
            "1. Sửa đổi, bổ sung điểm b khoản 1 như sau: “b) Người nộp thuế "
            "thuộc diện khai thuế thu nhập cá nhân theo tháng được quy định "
            "tại điểm a khoản 1 Điều 8 Nghị định này nếu đủ điều kiện khai "
            "thuế giá trị gia tăng theo quý thì được lựa chọn khai thuế thu "
            "nhập cá nhân theo quý.”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="373/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 126/2020/NĐ-CP hướng dẫn Luật Quản lý thuế",
            clause_type="khoan",
            content=content,
            parent_content="Điều 1. Sửa đổi, bổ sung một số điểm, khoản của Điều 9 như sau:",
            grandparent_content="",
            idx=10,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            ["điểm b khoản 1 Điều 9 Nghị định 126/2020/NĐ-CP"],
        )

    def test_phrase_level_bai_bo_cum_tu_targets_listed_clauses(self) -> None:
        content = (
            "Điều 8. Bãi bỏ cụm từ tại một số điều của Nghị định số "
            "126/2020/NĐ-CP như sau: Bãi bỏ cụm từ “thuê mặt nước” tại "
            "điểm h khoản 2 Điều 5; điểm e khoản 3, điểm m khoản 4 Điều 8; "
            "khoản 5 Điều 10; điểm d khoản 7 Điều 11."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="373/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 126/2020/NĐ-CP hướng dẫn Luật Quản lý thuế",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=11,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            [
                "điểm h khoản 2 Điều 5 Nghị định số 126/2020/NĐ-CP",
                "điểm e khoản 3 Điều 8 Nghị định số 126/2020/NĐ-CP",
                "điểm m khoản 4 Điều 8 Nghị định số 126/2020/NĐ-CP",
                "khoản 5 Điều 10 Nghị định số 126/2020/NĐ-CP",
                "điểm d khoản 7 Điều 11 Nghị định số 126/2020/NĐ-CP",
            ],
        )

    def test_repeated_amendment_history_after_theo_quy_dinh_stays_dan_chieu(self) -> None:
        content = (
            "5. Mẫu nhãn thuốc cổ truyền, vị thuốc cổ truyền, dược liệu và tờ "
            "hướng dẫn sử dụng thuốc cổ truyền dự kiến lưu hành tại Việt Nam "
            "thực hiện theo quy định tại Thông tư số 01/2018/TT-BYT ngày "
            "18 tháng 01 năm 2018 của Bộ trưởng Bộ Y tế quy định ghi nhãn thuốc, "
            "nguyên liệu làm thuốc và tờ hướng dẫn sử dụng thuốc được sửa đổi, "
            "bổ sung tại Thông tư số 23/2023/TT-BYT ngày 30 tháng 11 năm 2023 "
            "của Bộ Y tế sửa đổi, bổ sung một số điều tại Thông tư số "
            "01/2018/TT-BYT ngày 18 tháng 01 năm 2018 của Bộ trưởng Bộ Y tế "
            "quy định ghi nhãn thuốc, nguyên liệu làm thuốc và tờ hướng dẫn "
            "sử dụng thuốc (sau đây gọi là Thông tư số 01/2018/TT-BYT)."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư về đăng ký lưu hành thuốc cổ truyền, dược liệu",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 5. Quy định chung về hồ sơ đăng ký lưu hành thuốc cổ truyền, "
                "vị thuốc cổ truyền, dược liệu"
            ),
            grandparent_content="",
            idx=8,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018"],
        )

    def test_internal_clause_reference_dedupes_when_document_self_reference_exists(self) -> None:
        content = (
            "Quyết định về danh mục bí mật nhà nước được ban hành theo quy định "
            "của Luật Bảo vệ bí mật nhà nước số 29/2018/QH14 tiếp tục có hiệu lực "
            "thi hành đến thời điểm được ban hành mới theo quy định của Luật này.\r\r\n"
            "Người lập danh mục bí mật nhà nước được quy định tại khoản 2 Điều 9 "
            "của Luật này có trách nhiệm rà soát, đánh giá, đề xuất sửa đổi, "
            "bổ sung danh mục bí mật nhà nước."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="117/2025/QH15",
            title="Luật Bảo vệ bí mật nhà nước",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=11,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            [
                "Luật Bảo vệ bí mật nhà nước số 29/2018/QH14",
                "Luật 117/2025/QH15",
            ],
        )

    def test_self_law_tail_drops_related_external_law_reference(self) -> None:
        content = (
            "3. Vay đặc biệt từ Ngân hàng Nhà nước Việt Nam theo quy định của "
            "Luật này, Luật Các tổ chức tín dụng và quy định khác của pháp luật "
            "có liên quan."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="111/2025/QH15",
            title="Luật Bảo hiểm tiền gửi",
            clause_type="khoan",
            content=content,
            parent_content="Điều 9. Quyền và nghĩa vụ của tổ chức bảo hiểm tiền gửi",
            grandparent_content="",
            idx=9,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Luật 111/2025/QH15"],
        )

    def test_exception_clause_can_reference_current_document(self) -> None:
        content = (
            "1. Hồ sơ nộp trước ngày Thông tư này có hiệu lực thi hành được "
            "tiếp tục thực hiện theo các quy định tại Thông tư số "
            "21/2018/TT-BYT ngày 12 tháng 9 năm 2018, trừ trường hợp cơ sở "
            "có văn bản đề nghị thực hiện theo các quy định tại Thông tư này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư về đăng ký lưu hành thuốc cổ truyền, dược liệu",
            clause_type="khoan",
            content=content,
            parent_content="Điều 39. Điều khoản chuyển tiếp",
            grandparent_content="",
            idx=39,
            law_titles=self.law_titles,
        )

        self.assertIn(
            "Thông tư 29/2025/TT-BYT",
            _refs_for_relation(predictions, "dan_chieu"),
        )

    def test_repealing_procedures_in_attached_appendix_modifies_source_decision(self) -> None:
        content = (
            "1. Quyết định này bãi bỏ 18 thủ tục hành chính số thứ tự từ 04 đến 22 "
            "mục IV - Lĩnh vực tiêu chuẩn, đo lường, chất lượng tại phụ lục ban "
            "hành kèm theo Quyết định số 930/QĐ-UBND ngày 30/6/2025 của Chủ tịch "
            "Ủy ban nhân dân tỉnh Cao Bằng về việc công bố danh mục thủ tục hành "
            "chính mới ban hành."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="335/QĐ-UBND",
            title="Quyết định công bố Danh mục thủ tục hành chính",
            clause_type="khoan",
            content=content,
            parent_content="Điều 3. Quyết định này có hiệu lực thi hành kể từ ngày ký.",
            grandparent_content="",
            idx=9,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "bai_bo"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi_bo_sung"),
            ["Quyết định số 930/QĐ-UBND ngày 30/6/2025"],
        )

    def test_expiry_edge_keeps_later_quy_dinh_tai_dan_chieu_sentence(self) -> None:
        content = (
            "Nghị quyết số 37/2012/QH13 ngày 23 tháng 11 năm 2012, "
            "Nghị quyết số 63/2013/QH13 ngày 27 tháng 11 năm 2013 và "
            "Nghị quyết số 111/2015/QH13 ngày 27 tháng 11 năm 2015 hết hiệu lực "
            "thi hành kể từ ngày Nghị quyết này có hiệu lực.\r\r\n"
            "Các chỉ tiêu, nhiệm vụ quy định tại Nghị quyết số 52/2013/QH13 "
            "ngày 21 tháng 6 năm 2013, Nghị quyết số 69/2013/QH13 ngày "
            "29 tháng 11 năm 2013 và Nghị quyết số 75/2014/QH13 ngày "
            "24 tháng 6 năm 2014 khác với các chỉ tiêu, nhiệm vụ được quy định "
            "trong Nghị quyết này thì áp dụng theo Nghị quyết này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="96/2019/QH14",
            title="Nghị quyết phòng chống tội phạm và vi phạm pháp luật",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=10,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "thay_the"),
            [
                "Nghị quyết số 37/2012/QH13 ngày 23 tháng 11 năm 2012",
                "Nghị quyết số 63/2013/QH13 ngày 27 tháng 11 năm 2013",
                "Nghị quyết số 111/2015/QH13 ngày 27 tháng 11 năm 2015",
            ],
        )
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            [
                "Nghị quyết số 52/2013/QH13 ngày 21 tháng 6 năm 2013",
                "Nghị quyết số 69/2013/QH13 ngày 29 tháng 11 năm 2013",
                "Nghị quyết số 75/2014/QH13 ngày 24 tháng 6 năm 2014",
            ],
        )

    def test_legislative_program_project_addition_is_not_sdbs(self) -> None:
        content = (
            "Giao Bộ trưởng Bộ Nội vụ thừa ủy quyền Thủ tướng Chính phủ, "
            "thay mặt Chính phủ ký Tờ trình của Chính phủ trình Ủy ban Thường vụ "
            "Quốc hội về việc bổ sung dự án Luật sửa đổi, bổ sung một số điều "
            "của Luật Người lao động Việt Nam đi làm việc ở nước ngoài theo hợp "
            "đồng vào Chương trình lập pháp năm 2026 của Quốc hội khóa XVI theo "
            "đúng quy định của Luật Ban hành văn bản quy phạm pháp luật và văn bản "
            "liên quan; chủ động báo cáo, giải trình với Ủy ban Thường vụ Quốc hội "
            "và các cơ quan liên quan của Quốc hội theo quy định."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="112/NQ-CP",
            title=(
                "Nghị quyết bổ sung dự án Luật Người lao động Việt Nam đi làm việc "
                "ở nước ngoài theo hợp đồng sửa đổi vào Chương trình lập pháp năm 2026"
            ),
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])

    def test_transition_provisions_temporal_law_is_not_bai_bo_target(self) -> None:
        content = (
            "a) Phối hợp với các cơ quan liên quan rà soát, tham mưu Chính phủ "
            "bãi bỏ các quy định chuyển tiếp của dự án BT được thực hiện trước "
            "thời điểm Luật Đầu tư theo phương thức đối tác công tư có hiệu lực "
            "thi hành khác với quy định tại Nghị quyết này;"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="16/2026/NQ-CP",
            title=(
                "Nghị quyết quy định về cơ chế, chính sách tháo gỡ khó khăn, "
                "vướng mắc đối với dự án đầu tư theo hình thức Xây dựng - Chuyển giao"
            ),
            clause_type="diem",
            content=content,
            parent_content="2. Bộ Tài chính có trách nhiệm:",
            grandparent_content="Điều 14. Tổ chức thực hiện",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "bai_bo"), [])

    def test_dinh_chinh_keeps_clause_target_after_intro_nhu_sau(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật tại Thông tư số 28/2021/TT-NHNN "
            "ngày 31/12/2021 của Thống đốc Ngân hàng Nhà nước Việt Nam sửa đổi, "
            "bổ sung một số điều của Thông tư số 40/2011/TT-NHNN như sau: "
            "Tại khoản 3 Điều 1 (bổ sung khoản 4 Điều 19a vào sau Điều 19 "
            "Thông tư số 40/2011/TT-NHNN), đính chính cụm từ "
            "“điểm d khoản 1 Điều 152 Nghị định số 155/2020/NĐ-CP” thành cụm từ "
            "“điểm đ khoản 1 Điều 10 Nghị định số 158/2020/NĐ-CP”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="949/QĐ-NHNN",
            title="Quyết định về việc đính chính Thông tư số 28/2021/TT-NHNN",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=5,
            law_titles=self.law_titles,
        )

        refs = _refs_for_relation(predictions, "dinh_chinh")
        self.assertIn("Thông tư số 28/2021/TT-NHNN ngày 31/12/2021", refs)
        self.assertIn("khoản 3 Điều 1 Thông tư số 28/2021/TT-NHNN ngày 31/12/2021", refs)

    def test_dinh_chinh_mot_so_noi_dung_tai_decision(self) -> None:
        content = (
            "Trên cơ sở Công văn số 10/HĐND-TH ngày 15/01/2020 của Thường trực "
            "Hội đồng nhân dân tỉnh về việc đính chính Nghị quyết số 23/2019/NQ-HĐND "
            "ngày 20/12/2019 của Hội đồng nhân dân tỉnh, Ủy ban Nhân dân tỉnh "
            "đính chính một số nội dung tại Quyết định số 80/2019/QĐ-UBND "
            "ngày 21/12/2019 của UBND tỉnh ban hành Bảng giá đất."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="497/UBND-NĐ",
            title="Công văn đính chính Quyết định 80/2019/QĐ-UBND",
            clause_type="vanban",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=6,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dinh_chinh"),
            ["Quyết định số 80/2019/QĐ-UBND ngày 21/12/2019"],
        )

    def test_dinh_chinh_content_integration_clause_is_not_new_correction_target(self) -> None:
        content = (
            "Nội dung đính chính tại Điều 1 Quyết định này là một phần không tách rời "
            "của Nghị định số 62/2025/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="305/QĐ-BCT",
            title="Quyết định đính chính Nghị định số 62/2025/NĐ-CP",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "dinh_chinh"), [])

    def test_dinh_chinh_giay_chung_nhan_is_operational_not_document_correction(self) -> None:
        content = (
            "Đính chính Giấy chứng nhận đã cấp theo quy định tại "
            "Nghị quyết số 254/2025/QH15 của Quốc hội."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="49/2026/NĐ-CP",
            title="Nghị định hướng dẫn Nghị quyết số 254/2025/QH15",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "dinh_chinh"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Nghị quyết số 254/2025/QH15"],
        )

    def test_dinh_chinh_drops_short_alias_when_full_dated_target_exists(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật tại tiêu đề của Điều 10 "
            "Thông tư số 10/2022/TT-BVHTTDL ngày 28 tháng 10 năm 2022 "
            "của Bộ trưởng Bộ Văn hóa, Thể thao và Du lịch quy định mã số "
            "(sau đây gọi tắt là Thông tư số 10/2022/TT-BVHTTDL) như sau:\r\n\r\n"
            "Sửa tiêu đề Điều 10 “Diễn viên hạng III” thành “Diễn viên hạng III”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="2974/QĐ-BVHTTDL",
            title="Quyết định đính chính Thông tư số 10/2022/TT-BVHTTDL",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=7,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dinh_chinh"),
            ["Điều 10 Thông tư số 10/2022/TT-BVHTTDL ngày 28 tháng 10 năm 2022"],
        )

    def test_dinh_chinh_intro_does_not_pull_second_descriptive_document(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật trình bày tại Thông tư số 01/2021/TT-BYT "
            "ngày 25 tháng 01 năm 2021 của Bộ trưởng Bộ Y tế hướng dẫn một số nội dung "
            "để địa phương ban hành chính sách khen thưởng và Thông tư số 02/2021/TT-BYT "
            "ngày 25 tháng 01 năm 2021 của Bộ trưởng Bộ Y tế quy định tiêu chuẩn, nhiệm vụ "
            "của cộng tác viên dân số như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="5335/QĐ-BYT",
            title="Quyết định đính chính Thông tư số 01/2021/TT-BYT",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=8,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dinh_chinh"),
            ["Thông tư số 01/2021/TT-BYT ngày 25 tháng 01 năm 2021"],
        )

    def test_keo_dai_ignores_amendment_history_resolution(self) -> None:
        content = (
            "Kéo dài thời hạn miễn thuế sử dụng đất nông nghiệp được quy định tại "
            "Nghị quyết số 55/2010/QH12 ngày 24 tháng 11 năm 2010 của Quốc hội "
            "về miễn, giảm thuế sử dụng đất nông nghiệp đã được sửa đổi, bổ sung "
            "một số điều theo Nghị quyết số 28/2016/QH14 ngày 11 tháng 11 năm 2016 "
            "của Quốc hội và Nghị quyết số 107/2020/QH14 ngày 10 tháng 6 năm 2020 "
            "của Quốc hội đến hết ngày 31 tháng 12 năm 2030."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="216/2025/QH15",
            title="Luật kéo dài thời hạn miễn thuế sử dụng đất nông nghiệp",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=9,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "keo_dai_hieu_luc"),
            ["Nghị quyết số 55/2010/QH12 ngày 24 tháng 11 năm 2010"],
        )

    def test_huy_bo_danh_muc_ban_hanh_kem_theo_is_sdbs_not_document_cancellation(self) -> None:
        content = (
            "Điều 1. Hủy bỏ danh mục dự án ban hành kèm theo "
            "Nghị quyết số 14/2018/NQ-HĐND ngày 19 tháng 7 năm 2018 "
            "và sửa đổi, bổ sung Danh mục các dự án ban hành kèm theo "
            "Nghị quyết số 16/2020/NQ-HĐND ngày 08 tháng 12 năm 2020 "
            "của Hội đồng nhân dân tỉnh, cụ thể như sau:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="06/2021/NQ-HĐND",
            title="Nghị quyết hủy bỏ và sửa đổi danh mục dự án",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=10,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "huy_bo"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi_bo_sung"),
            [
                "Nghị quyết số 14/2018/NQ-HĐND ngày 19 tháng 7 năm 2018",
                "Nghị quyết số 16/2020/NQ-HĐND ngày 08 tháng 12 năm 2020",
            ],
        )

    def test_keo_dai_drops_resolution_that_only_amends_extended_target(self) -> None:
        content = (
            "Điều 1. Thống nhất kéo dài thời gian thực hiện "
            "Nghị quyết số 18/2022/NQ-HĐND ngày 07 tháng 9 năm 2022 "
            "của Hội đồng nhân dân tỉnh và Nghị quyết số 25/2022/NQ-HĐND "
            "ngày 08 tháng 12 năm 2022 sửa đổi, bổ sung điểm b khoản 1 "
            "Điều 1 của Nghị quyết số 18/2022/NQ-HĐND."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="38/2024/NQ-HĐND",
            title="Nghị quyết kéo dài thời gian thực hiện chính sách",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=11,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "keo_dai_hieu_luc"),
            ["Nghị quyết số 18/2022/NQ-HĐND ngày 07 tháng 9 năm 2022"],
        )

    def test_huy_bo_numbered_projects_attached_to_resolution_is_not_document_cancellation(self) -> None:
        content = (
            "Điều 1. Hủy bỏ 15 dự án ban hành kèm theo "
            "Nghị quyết số 14/2018/NQ-HĐND ngày 19 tháng 7 năm 2018 "
            "sửa đổi, bổ sung Danh mục dự án ban hành kèm theo "
            "Nghị quyết số 30/2017/NQ-HĐND ngày 08 tháng 12 năm 2017."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="06/2021/NQ-HĐND",
            title="Nghị quyết hủy bỏ một số dự án",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=12,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "huy_bo"), [])
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])

    def test_huy_bo_cong_nhan_is_operational_not_document_cancellation(self) -> None:
        content = (
            "Người có thẩm quyền bổ nhiệm, bổ nhiệm lại, cấp, cấp lại, thu hồi "
            "thẻ giám định viên tư pháp, công nhận người, tổ chức giám định tư "
            "pháp theo vụ việc theo quy định của Luật này có thẩm quyền miễn "
            "nhiệm, bổ nhiệm lại, thu hồi thẻ, cấp lại thẻ giám định viên tư "
            "pháp, hủy bỏ công nhận người, tổ chức giám định tư pháp theo vụ "
            "việc đã được người có thẩm quyền bổ nhiệm, cấp thẻ giám định viên "
            "tư pháp, công nhận người, tổ chức giám định tư pháp theo vụ việc "
            "theo quy định của Luật Giám định tư pháp số 13/2012/QH13."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="105/2025/QH15",
            title="Luật Giám định tư pháp",
            clause_type="khoan",
            content=content,
            parent_content="Điều 44. Điều khoản chuyển tiếp",
            grandparent_content="",
            idx=13,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "huy_bo"), [])
        self.assertEqual(_refs_for_relation(predictions, "bai_bo"), [])
        self.assertIn(
            "Luật Giám định tư pháp số 13/2012/QH13",
            _refs_for_relation(predictions, "dan_chieu"),
        )

    def test_passive_amendment_history_after_dan_chieu_keeps_citation_relation(self) -> None:
        content = (
            "Việc xếp cấp chuyên môn kỹ thuật thực hiện theo quy định tại "
            "Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018 "
            "của Bộ trưởng Bộ Y tế được sửa đổi, bổ sung bởi "
            "Thông tư số 21/2024/TT-BYT ngày 17 tháng 10 năm 2024."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư hướng dẫn chức năng chuyên môn kỹ thuật",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=13,
            law_titles=self.law_titles,
        )

        self.assertIn(
            "Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018",
            _refs_for_relation(predictions, "dan_chieu"),
        )
        self.assertNotIn(
            "Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018",
            _refs_for_relation(predictions, "sua_doi_bo_sung"),
        )

    def test_passive_amendment_history_before_following_list_keeps_citation_relation(self) -> None:
        content = (
            "5. Mẫu nhãn thuốc cổ truyền dự kiến lưu hành tại Việt Nam thực hiện "
            "theo quy định tại Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018 "
            "của Bộ trưởng Bộ Y tế quy định ghi nhãn thuốc được sửa đổi, bổ sung tại "
            "Thông tư số 23/2023/TT-BYT ngày 30 tháng 11 năm 2023 sửa đổi, bổ sung "
            "một số điều tại Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018 "
            "(sau đây gọi là Thông tư số 01/2018/TT-BYT) và các quy định sau đây:"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="29/2025/TT-BYT",
            title="Thông tư về đăng ký lưu hành thuốc cổ truyền",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=16,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Thông tư số 01/2018/TT-BYT ngày 18 tháng 01 năm 2018"],
        )
        self.assertEqual(_refs_for_relation(predictions, "sua_doi_bo_sung"), [])

    def test_phrase_level_sdbs_drops_broad_document_before_specific_clause_target(self) -> None:
        content = (
            "Điều 1. Bãi bỏ cụm từ tại Quyết định số 11/2019/QĐ-UBND "
            "ngày 11 tháng 02 năm 2019 như sau: Bãi bỏ cụm từ "
            "“tài nguyên và môi trường” tại Khoản 1 Điều 1 "
            "Quyết định số 11/2019/QĐ-UBND ngày 11 tháng 02 năm 2019."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="15/2021/QĐ-UBND",
            title="Quyết định bãi bỏ cụm từ",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=14,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            ["khoản 1 Điều 1 Quyết định số 11/2019/QĐ-UBND ngày 11 tháng 02 năm 2019"],
        )

    def test_replacement_quote_does_not_emit_quy_dinh_chi_tiet_for_inner_text(self) -> None:
        content = (
            "Điều 1. Sửa đổi, bổ sung Điều 1 như sau: "
            "“Điều 1. Quy định chi tiết điểm d khoản 2 Điều 15 "
            "Nghị định số 08/2022/NĐ-CP ngày 10 tháng 01 năm 2022.”"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="07/2025/TT-BTNMT",
            title="Thông tư sửa đổi quy định kỹ thuật",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=15,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "quy_dinh_chi_tiet"), [])

    def test_replacement_quote_long_inner_text_does_not_emit_quy_dinh_chi_tiet(self) -> None:
        content = (
            "1. Sửa đổi, bổ sung Điều 1 như sau:\r\n\r\n"
            "“1. Quy định chi tiết thi hành điểm a khoản 2 và điểm b khoản 3 Điều 8; "
            "khoản 7 Điều 10; khoản 4 Điều 80; khoản 6 Điều 148 của Luật Bảo vệ môi trường.\r\n\r\n"
            "2. Quy định chi tiết thi hành điểm d khoản 2 Điều 15; điểm d khoản 2 Điều 16 "
            "Nghị định số 08/2022/NĐ-CP ngày 10 tháng 01 năm 2022.”"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="07/2025/TT-BTNMT",
            title="Thông tư sửa đổi Thông tư 02/2022/TT-BTNMT",
            clause_type="khoan",
            content=content,
            parent_content="Điều 1. Sửa đổi, bổ sung Điều 1 Thông tư số 02/2022/TT-BTNMT ngày 10 tháng 01 năm 2022",
            grandparent_content="",
            idx=17,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "quy_dinh_chi_tiet"), [])

    def test_replacement_quote_far_inner_text_does_not_emit_quy_dinh_chi_tiet(self) -> None:
        row = _load_dataset_clause("07/2025/TT-BTNMT", "1. Sửa đổi, bổ sung Điều 1 như sau:")

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu=row["so_hieu"],
            title=row["title"],
            clause_type="khoan",
            content=row["content"],
            parent_content=row["parent_content"],
            grandparent_content="",
            idx=18,
            law_titles=self.law_titles,
        )

        self.assertEqual(_refs_for_relation(predictions, "quy_dinh_chi_tiet"), [])

    def test_ngung_hieu_luc_targets_amended_clause_after_duoc_sua_doi_tai(self) -> None:
        content = (
            "1. Quy định về việc xác định tư cách nhà đầu tư chứng khoán chuyên nghiệp "
            "là cá nhân tại điểm d khoản 1 Điều 8 Nghị định số 153/2020/NĐ-CP "
            "được sửa đổi tại khoản 6 Điều 1 Nghị định số 65/2022/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="08/2023/NĐ-CP",
            title="Nghị định ngưng hiệu lực thi hành quy định về trái phiếu doanh nghiệp",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 1. Ngưng hiệu lực thi hành đối với các quy định sau đây "
                "tại Nghị định số 65/2022/NĐ-CP đến hết ngày 31 tháng 12 năm 2023"
            ),
            grandparent_content="",
            idx=18,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "ngung_hieu_luc"),
            ["khoản 6 Điều 1 Nghị định số 65/2022/NĐ-CP"],
        )

    def test_ngung_hieu_luc_keeps_original_when_amended_article_does_not_match_parent(self) -> None:
        content = (
            "3. Quy định về kết quả xếp hạng tín nhiệm đối với doanh nghiệp phát hành "
            "trái phiếu tại điểm e khoản 2 Điều 12 Nghị định số 153/2020/NĐ-CP "
            "được sửa đổi tại khoản 9 Điều 1 Nghị định số 65/2022/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="08/2023/NĐ-CP",
            title="Nghị định ngưng hiệu lực thi hành quy định về trái phiếu doanh nghiệp",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 3. Ngưng hiệu lực thi hành đối với các quy định sau đây "
                "tại Nghị định số 65/2022/NĐ-CP đến hết ngày 31 tháng 12 năm 2023"
            ),
            grandparent_content="",
            idx=18,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "ngung_hieu_luc"),
            ["điểm e khoản 2 Điều 12 Nghị định số 153/2020/NĐ-CP"],
        )

    def test_ngung_hieu_luc_expands_coordinated_document_targets(self) -> None:
        content = (
            "Tạm ngưng hiệu lực Nghị định số 46/2026/NĐ-CP ngày 26 tháng 01 năm 2026 "
            "của Chính phủ quy định chi tiết một số điều của Luật An toàn thực phẩm "
            "và Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026 của Chính phủ."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="15/2026/NQ-CP",
            title="Nghị quyết ngưng hiệu lực văn bản",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "ngung_hieu_luc"),
            [
                "Nghị định số 46/2026/NĐ-CP ngày 26 tháng 01 năm 2026",
                "Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026",
            ],
        )

    def test_sdbs_uses_title_document_for_standalone_article_target(self) -> None:
        content = "Điều 1. Sửa đổi, bổ sung một số điểm, khoản của Điều 1"

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="77/2025/TT-NHNN",
            title=(
                "Thông tư sửa đổi, bổ sung một số điều của Thông tư số "
                "50/2024/TT-NHNN của Thống đốc Ngân hàng Nhà nước Việt Nam "
                "quy định về an toàn, bảo mật cho việc cung cấp dịch vụ trực "
                "tuyến trong ngành Ngân hàng"
            ),
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=18,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            ["Điều 1 Thông tư số 50/2024/TT-NHNN"],
        )

    def test_sdbs_drops_passive_amendment_history_after_current_target(self) -> None:
        content = (
            "Điều 1. Bãi bỏ cụm từ “và quy định khác có liên quan” tại điểm b "
            "khoản 5 Điều 36 Nghị định số 26/2019/NĐ-CP đã được sửa đổi, "
            "bổ sung tại khoản 14 Điều 1 Nghị định số 37/2024/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="309/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 26/2019/NĐ-CP",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            ["điểm b khoản 5 Điều 36 Nghị định số 26/2019/NĐ-CP"],
        )

    def test_phrase_level_bai_bo_list_inherits_intro_document_across_newline(self) -> None:
        content = (
            "Điều 8. Bãi bỏ cụm từ tại một số điều của Nghị định số 126/2020/NĐ-CP như sau:\n"
            "Bãi bỏ cụm từ “thuê mặt nước” tại điểm h khoản 2 Điều 5; "
            "điểm e khoản 3, điểm m khoản 4 Điều 8; khoản 5 Điều 10; "
            "điểm d khoản 7 Điều 11."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="373/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 126/2020/NĐ-CP hướng dẫn Luật Quản lý thuế",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=8,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi"),
            [
                "điểm h khoản 2 Điều 5 Nghị định số 126/2020/NĐ-CP",
                "điểm e khoản 3 Điều 8 Nghị định số 126/2020/NĐ-CP",
                "điểm m khoản 4 Điều 8 Nghị định số 126/2020/NĐ-CP",
                "khoản 5 Điều 10 Nghị định số 126/2020/NĐ-CP",
                "điểm d khoản 7 Điều 11 Nghị định số 126/2020/NĐ-CP",
            ],
        )

    def test_phrase_level_bai_bo_mot_so_list_is_sdbs_not_bai_bo(self) -> None:
        content = (
            "Điều 9. Bãi bỏ một số điểm, một số khoản tại một số điều của "
            "Nghị định số 126/2020/NĐ-CP như sau:\n"
            "Bãi bỏ điểm b khoản 5 Điều 7; điểm b khoản 2, điểm s khoản 4 Điều 8; "
            "điểm c, điểm d khoản 2 Điều 9; khoản 12 Điều 13; khoản 4 Điều 20; "
            "điểm a.16 khoản 2 Điều 26."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="373/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 126/2020/NĐ-CP hướng dẫn Luật Quản lý thuế",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=9,
            law_titles=self.law_titles,
        )

        expected_targets = [
            "điểm b khoản 5 Điều 7 Nghị định số 126/2020/NĐ-CP",
            "điểm b khoản 2 Điều 8 Nghị định số 126/2020/NĐ-CP",
            "điểm s khoản 4 Điều 8 Nghị định số 126/2020/NĐ-CP",
            "điểm c khoản 2 Điều 9 Nghị định số 126/2020/NĐ-CP",
            "điểm d khoản 2 Điều 9 Nghị định số 126/2020/NĐ-CP",
            "khoản 12 Điều 13 Nghị định số 126/2020/NĐ-CP",
            "khoản 4 Điều 20 Nghị định số 126/2020/NĐ-CP",
            "điểm a.16 khoản 2 Điều 26 Nghị định số 126/2020/NĐ-CP",
        ]
        self.assertEqual(
            _refs_for_relation(predictions, "bai_bo"),
            expected_targets,
        )

    def test_replacing_quoted_form_in_attached_appendix_is_sdbs_not_thay_the(self) -> None:
        content = (
            "12. Thay thế “Đơn đăng ký hoạt động ứng phó và khắc phục hậu quả thiên tai "
            "tại Việt Nam” tại Phụ lục I kèm theo Nghị định số 66/2021/NĐ-CP "
            "ngày 06 tháng 7 năm 2021 của Chính phủ bằng đơn kèm theo tại Phụ lục I "
            "Nghị định này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="53/2026/NĐ-CP",
            title="Nghị định sửa đổi các Nghị định về quản lý hoạt động dự báo, cảnh báo khí tượng thủy văn",
            clause_type="khoan",
            content=content,
            parent_content="Điều 14. Thay thế một số cụm từ tại điểm, khoản và phụ lục như sau:",
            grandparent_content="",
            idx=12,
            law_titles=self.law_titles,
        )

        self.assertIn(
            "Nghị định số 66/2021/NĐ-CP ngày 06 tháng 7 năm 2021",
            _refs_for_relation(predictions, "sua_doi_bo_sung"),
        )
        self.assertEqual(_refs_for_relation(predictions, "thay_the"), [])

    def test_partial_document_heading_does_not_create_document_level_bai_bo(self) -> None:
        content = (
            "2. Bãi bỏ khoản 3, khoản 5 Điều 27 Nghị định số 27/2019/NĐ-CP "
            "ngày 13 tháng 3 năm 2019 của Chính phủ quy định chi tiết một số điều "
            "của Luật Đo đạc và bản đồ.\n"
            "3. Thay thế một số Phụ lục sau:\n"
            "a) Thay thế Mẫu số 03 Phụ lục I ban hành kèm theo Nghị định số 27/2019/NĐ-CP "
            "bằng Mẫu số 01 Phụ lục I kèm theo Nghị định này.\n"
            "c) Thay thế Phụ lục IA ban hành kèm theo Nghị định số 136/2021/NĐ-CP "
            "bằng Phụ lục III kèm theo Nghị định này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="39/2026/NĐ-CP",
            title="Nghị định sửa đổi Nghị định số 27/2019/NĐ-CP và Nghị định số 136/2021/NĐ-CP",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        bai_bo_refs = _refs_for_relation(predictions, "bai_bo")
        self.assertEqual(bai_bo_refs, [])

    def test_operational_tam_dinh_chi_theo_quy_dinh_cua_stays_dan_chieu(self) -> None:
        content = (
            "b) Nhận được yêu cầu của Tòa án về việc tạm đình chỉ thi hành quyết định "
            "công nhận và cho thi hành phán quyết của Trọng tài nước ngoài theo quy định "
            "của Bộ luật Tố tụng dân sự."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="106/2025/QH15",
            title="Luật thi hành án dân sự",
            clause_type="diem",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Bộ luật Tố tụng dân sự"],
        )
        self.assertEqual(_refs_for_relation(predictions, "dinh_chi"), [])

    def test_repealing_attached_forms_keeps_parent_source_as_dan_chieu(self) -> None:
        content = (
            "2. Ban hành Mẫu số 01/TTĐB tại Phụ lục I kèm theo Nghị định này "
            "và bãi bỏ các Mẫu số 01/TTĐB, Mẫu số 02/TTĐB tại Phụ lục II "
            "kèm theo Thông tư số 80/2021/TT-BTC ngày 29 tháng 9 năm 2021 "
            "của Bộ Tài chính."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="373/2025/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 126/2020/NĐ-CP hướng dẫn Luật Quản lý thuế",
            clause_type="khoan",
            content=content,
            parent_content=(
                "Điều 10. Sửa đổi, bổ sung Phụ lục I - Danh mục hồ sơ khai thuế "
                "kèm theo Nghị định số 126/2020/NĐ-CP như sau:"
            ),
            grandparent_content="",
            idx=2,
            law_titles=self.law_titles,
        )

        expected = ["Nghị định số 126/2020/NĐ-CP"]
        self.assertEqual(_refs_for_relation(predictions, "dan_chieu"), expected)
        self.assertEqual(_refs_for_relation(predictions, "bai_bo"), [])
        self.assertEqual(
            _refs_for_relation(predictions, "sua_doi_bo_sung"),
            ["Thông tư số 80/2021/TT-BTC ngày 29 tháng 9 năm 2021"],
        )

    def test_dinh_chinh_uses_intro_document_for_post_intro_clause_target(self) -> None:
        content = (
            "Điều 1. Đính chính lỗi kỹ thuật trình bày tại Thông tư số 40/2021/TT- BGTVT "
            "ngày 31 tháng 12 năm 2021 của Bộ trưởng Bộ Giao thông vận tải ban hành "
            "định mức kinh tế - kỹ thuật công tác thu tiền dịch vụ sử dụng đường bộ "
            "đối với các dự án xây dựng đường bộ do Bộ Giao thông vận tải quản lý như sau:\n\n"
            "Đính chính cụm từ “ngày 01 tháng 03 năm 2021” tại khoản 1 Điều 3 "
            "Thông tư số 40/2021/TT-GTVT thành “ngày 01 tháng 03 năm 2022”."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="190/QĐ- BGTVT",
            title="Quyết định đính chính Thông tư 40/2021/TT-BGTVT",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dinh_chinh"),
            ["khoản 1 Điều 3 Thông tư số 40/2021/TT-BGTVT ngày 31 tháng 12 năm 2021"],
        )

    def test_ngung_hieu_luc_drops_documents_inside_target_title_tail(self) -> None:
        content = (
            "1. Tạm ngưng hiệu lực áp dụng Nghị định số 46/2026/NĐ-CP "
            "ngày 26 tháng 01 năm 2026 của Chính phủ quy định chi tiết thi hành "
            "một số điều và biện pháp để tổ chức, hướng dẫn thi hành Luật An toàn "
            "thực phẩm và Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026 "
            "của Chính phủ về công bố, đăng ký sản phẩm thực phẩm cho đến hết ngày "
            "15 tháng 4 năm 2026."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="09/2026/NQ-CP",
            title="Nghị quyết tạm ngưng hiệu lực và điều chỉnh thời hạn áp dụng Nghị định 46/2026/NĐ-CP",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "ngung_hieu_luc"),
            ["Nghị định số 46/2026/NĐ-CP ngày 26 tháng 01 năm 2026"],
        )

    def test_dan_chieu_expands_semicolon_document_list_after_theo(self) -> None:
        content = (
            "1. Trong thời gian Nghị định này có hiệu lực nhưng Bộ Quốc phòng chưa bảo đảm "
            "trang phục dự lễ mới thì việc mang mặc trang phục dự lễ tiếp tục thực hiện "
            "theo Nghị định số 82/2016/NĐ-CP ngày 01 tháng 7 năm 2016 của Chính phủ "
            "quy định quân hiệu, cấp hiệu, phù hiệu và trang phục của Quân đội nhân dân "
            "Việt Nam; Nghị định số 61/2019/NĐ-CP ngày 10 tháng 7 năm 2019 của Chính phủ "
            "quy định chi tiết một số điều và biện pháp thi hành Luật Cảnh sát biển Việt Nam."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="22/2024/NĐ-CP",
            title="Nghị định sửa đổi Nghị định 82/2016/NĐ-CP và Nghị định 61/2019/NĐ-CP",
            clause_type="khoan",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            [
                "Nghị định số 82/2016/NĐ-CP ngày 01 tháng 7 năm 2016",
                "Nghị định số 61/2019/NĐ-CP ngày 10 tháng 7 năm 2019",
            ],
        )

    def test_dan_chieu_resolves_clause_scoped_self_decision_before_external_doc(self) -> None:
        content = (
            "Điều 2. Quyết định này có hiệu lực kể từ ngày ký. "
            "Nội dung đính chính tại Điều 1 Quyết định này là một phần "
            "không tách rời của Nghị định số 62/2025/NĐ-CP."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="305/QĐ-BCT",
            title="Quyết định đính chính Nghị định 62/2025/NĐ-CP",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Điều 1 Quyết định 305/QĐ-BCT"],
        )

    def test_dan_chieu_keeps_structural_self_document_reference(self) -> None:
        content = (
            "2. Các quy định về quản lý chi phí đầu tư xây dựng tại Mục 1 Chương IV "
            "Nghị định này áp dụng đối với dự án đầu tư xây dựng tuyến đường sắt quốc gia."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="67/2026/NĐ-CP",
            title="Nghị định hướng dẫn thiết kế kỹ thuật tổng thể đường sắt",
            clause_type="khoan",
            content=content,
            parent_content="Điều 2. Đối tượng áp dụng",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Nghị định 67/2026/NĐ-CP"],
        )

    def test_dan_chieu_self_document_container_does_not_shadow_external_clause_target(self) -> None:
        content = (
            "5. Dự án thành phần được quản lý theo các quy định tại Nghị định này gồm: "
            "dự án thành phần, dự án thành phần độc lập, tiểu dự án theo quy định tại "
            "Điều 23 Luật Đường sắt số 95/2025/QH1"
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="67/2026/NĐ-CP",
            title="Nghị định hướng dẫn thiết kế kỹ thuật tổng thể đường sắt",
            clause_type="khoan",
            content=content,
            parent_content="Điều 3. Giải thích từ ngữ",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertEqual(
            _refs_for_relation(predictions, "dan_chieu"),
            ["Điều 23 Luật Đường sắt số 95/2025/QH1"],
        )

    def test_dan_chieu_does_not_inherit_previous_document_when_self_doc_tail_is_explicit(self) -> None:
        content = (
            "a) Không nộp hồ sơ khai thuế sau 90 ngày, kể từ ngày hết thời hạn "
            "nộp hồ sơ khai thuế quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 "
            "của Luật quản lý thuế hoặc kể từ ngày hết thời hạn gia hạn nộp hồ sơ "
            "khai thuế quy định tại Điều 33 của Luật quản lý thuế, trừ trường hợp "
            "quy định tại Khoản 6 Điều 7 Nghị định này."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="129/2013/NĐ-CP",
            title="Nghị định xử phạt vi phạm hành chính cưỡng chế thi hành thuế",
            clause_type="diem",
            content=content,
            parent_content="1. Phạt tiền đối với người nộp thuế khi có một trong các hành vi sau đây:",
            grandparent_content="Điều 11. Xử phạt đối với hành vi trốn thuế, gian lận thuế",
            idx=1,
            law_titles=self.law_titles,
        )

        self.assertIn(
            "khoản 6 Điều 7 Nghị định 129/2013/NĐ-CP",
            _refs_for_relation(predictions, "dan_chieu"),
        )
        self.assertNotIn(
            "khoản 6 Điều 7 Luật quản lý thuế",
            _refs_for_relation(predictions, "dan_chieu"),
        )


if __name__ == "__main__":
    unittest.main()
