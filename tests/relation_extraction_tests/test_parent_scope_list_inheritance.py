import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


class TestParentScopeListInheritance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.law_titles = config.law_titles_for_regex
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )

    def test_action_heading_targets_bullet_list_references(self) -> None:
        content = (
            "Điều 1.Hủy bỏ hiệu lực thi hành các Quyết định của UBND tỉnh vì không còn phù hợp "
            "với Nghị định số 35/2001/NĐ-CP ngày 09/7/2001, Nghị định số 04/1999/NĐ-CP "
            "ngày 30/1/1999 của Chính phủ và Thông tư 53/2001/TT-BTC ngày 3/7/2001 "
            "của Bộ Tài chính.\r\n"
            "- Quyết định số 1754/2000/QĐ-UB ngày 21/12/2000 về một số chính sách khuyến khích.\r\n"
            "- Quyết định số 101/2001/QĐ-UB ngày 21/2/2001 về mức thu phí kiểm dịch động vật."
        )

        predictions = extract_single_clause(
            extractor=self.extractor,
            so_hieu="701/2001/QĐ-UB",
            title="",
            clause_type="dieu",
            content=content,
            parent_content="",
            grandparent_content="",
            idx=1,
            law_titles=self.law_titles,
        )
        huy_bo_refs = [
            item["reference"]
            for item in predictions
            if item["relation"] == "huy_bo"
        ]

        self.assertEqual(
            huy_bo_refs,
            [
                "Quyết định số 1754/2000/QĐ-UB ngày 21/12/2000",
                "Quyết định số 101/2001/QĐ-UB ngày 21/2/2001",
            ],
        )


if __name__ == "__main__":
    unittest.main()
