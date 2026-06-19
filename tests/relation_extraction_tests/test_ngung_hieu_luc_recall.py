import unittest

from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def _flatten(results):
    rows = []
    for group in results or []:
        for relation_group in group.get("relations", []):
            for tail in relation_group.get("tail", []):
                rows.append(
                    {
                        "relation": relation_group.get("relation"),
                        "clause_key": group.get("clause_key"),
                        "tail": tail,
                    }
                )
    return rows


class TestNgungHieuLucRecall(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_direct_ngung_hieu_luc_expands_multiple_clause_targets(self) -> None:
        content = (
            "Điều 1. Ngưng hiệu lực thi hành\r\n\r\n"
            "Ngưng hiệu lực thi hành khoản 1 Điều 7 và khoản 2 Điều 75 "
            "Thông tư số 02/2022/TT-BTNMT ngày 10 tháng 01 năm 2022 "
            "của Bộ trưởng Bộ Tài nguyên và Môi trường quy định chi tiết "
            "thi hành một số điều của Luật Bảo vệ môi trường."
        )
        results = self.extractor.extract_relations(
            data=[{"com_type": "dieu", "com_key": "dieu_1", "com_title": content}],
            cls_so_hieu="99/2025/QH15",
            cls_title="",
            cls_document_type="Quyết định",
        )

        flattened = _flatten(results)
        self.assertEqual([row["relation"] for row in flattened], ["ngung_hieu_luc", "ngung_hieu_luc"])
        self.assertTrue(any("khoản 1" in str(row["tail"]) and "Điều 7" in str(row["tail"]) for row in flattened))
        self.assertTrue(any("khoản 2" in str(row["tail"]) and "Điều 75" in str(row["tail"]) for row in flattened))

    def test_child_list_inherits_ngung_hieu_luc_from_parent_heading(self) -> None:
        parent = (
            "Điều 3. Ngưng hiệu lực thi hành đối với các quy định sau đây "
            "tại Nghị định số 65/2022/NĐ-CP đến hết ngày 31 tháng 12 năm 2023"
        )
        child = (
            "2. Quy định về thời gian phân phối trái phiếu của từng đợt phát hành "
            "tại khoản 7, khoản 8 Điều 1 Nghị định số 65/2022/NĐ-CP."
        )
        results = self.extractor.extract_relations(
            data=[
                {"com_type": "dieu", "com_key": "dieu_1", "com_title": parent},
                {"com_type": "khoan", "com_key": "khoan_1_dieu_1", "com_title": child},
            ],
            cls_so_hieu="99/2025/QH15",
            cls_title="",
            cls_document_type="Quyết định",
        )

        flattened = _flatten(results)
        ngung_rows = [
            row
            for row in flattened
            if row["relation"] == "ngung_hieu_luc"
            and row["clause_key"] == "khoan_1_dieu_1"
        ]
        self.assertEqual(len(ngung_rows), 2)
        self.assertTrue(any("khoản 7" in str(row["tail"]) for row in ngung_rows))
        self.assertTrue(any("khoản 8" in str(row["tail"]) for row in ngung_rows))


if __name__ == "__main__":
    unittest.main()
