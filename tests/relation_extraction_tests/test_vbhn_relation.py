"""Unit tests for the VBHN special-case relation builder."""

import logging
import unittest

from src.domain.extractors.relations_extractor import RelationsExtractor
from src.domain.extractors.special_cases_extractor import handle_vbhn_relation


logging.disable(logging.INFO)


class TestVbhnRelation(unittest.TestCase):
    """Validate the benchmark policy: VBHN creates hop_nhat relations."""

    def setUp(self) -> None:
        self.doc_types = ["Luật", "Nghị định", "Thông tư", "Quyết định"]
        self.clause_types = ["điều", "khoản", "điểm"]
        self.law_titles = ["Luật Đất đai", "Luật Nhà ở"]
        self.vbhn_clause_content = (
            "NGHỊ ĐỊNH\n"
            "QUY ĐỊNH VỀ BỒI HOÀN HỌC BỔNG VÀ CHI PHÍ ĐÀO TẠO\n"
            "Nghị định số 143/2013/NĐ-CP ngày 24 tháng 10 năm 2013 của Chính phủ "
            "quy định về bồi hoàn học bổng và chi phí đào tạo, có hiệu lực kể từ "
            "ngày 10 tháng 12 năm 2013, được sửa đổi, bổ sung bởi:\n"
            "Nghị định số 51/2026/NĐ-CP ngày 02 tháng 02 năm 2026 của Chính phủ "
            "sửa đổi, bổ sung một số điều của Nghị định số 143/2013/NĐ-CP.\n"
            "Căn cứ Luật Tổ chức Chính phủ ngày 25 tháng 12 năm 2001;"
        )
        self.extractor = RelationsExtractor(
            doc_clause_types={
                "doc_types": self.doc_types,
                "clause_types": self.clause_types,
            },
            law_titles_for_regex=self.law_titles,
        )

    @staticmethod
    def _flatten(result):
        flattened = []
        for group in result or []:
            for relation_group in group.get("relations", []):
                for tail in relation_group.get("tail", []):
                    flattened.append(
                        {
                            "relation": relation_group.get("relation"),
                            "tail": tail,
                        }
                    )
        return flattened

    def test_handle_vbhn_relation_creates_hop_nhat_graph_relations(self) -> None:
        result = handle_vbhn_relation(
            base_extractor=self.extractor.base_extractor,
            clause_type="vanban",
            clause_key=None,
            clause_content=self.vbhn_clause_content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            build_relations_fn=self.extractor._build_relations,
        )

        flattened = self._flatten(result)
        self.assertEqual([item["relation"] for item in flattened], ["hop_nhat", "hop_nhat"])
        self.assertTrue(
            any("143/2013/NĐ-CP" in str(item["tail"]) for item in flattened)
        )
        self.assertTrue(
            any("51/2026/NĐ-CP" in str(item["tail"]) for item in flattened)
        )

    def test_handle_vbhn_relation_ignores_can_cu_section(self) -> None:
        result = handle_vbhn_relation(
            base_extractor=self.extractor.base_extractor,
            clause_type="vanban",
            clause_key=None,
            clause_content=self.vbhn_clause_content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            build_relations_fn=self.extractor._build_relations,
        )

        self.assertFalse(
            any("Luật Tổ chức Chính phủ" in str(item["tail"]) for item in self._flatten(result))
        )

    def test_handle_vbhn_relation_excludes_amendment_scope_law_names(self) -> None:
        """Bare law names inside an amending act's scope list are not consolidation targets.

        The amending law "Luật số 56/2024/QH15 … sửa đổi, bổ sung một số điều của
        Luật Kế toán, Luật Kiểm toán độc lập, …" lists other laws by name only;
        those must not become separate hop_nhat edges. Only documents cited with
        their own number (the base law and the numbered amending laws) are kept.
        """
        content = (
            "LUẬT\n"
            "CHỨNG KHOÁN\n"
            "Luật Chứng khoán số 54/2019/QH14 ngày 26 tháng 11 năm 2019 của Quốc hội, "
            "có hiệu lực kể từ ngày 01 tháng 01 năm 2021, được sửa đổi, bổ sung bởi:\n"
            "1. Luật số 56/2024/QH15 ngày 29 tháng 11 năm 2024 của Quốc hội sửa đổi, "
            "bổ sung một số điều của Luật Chứng khoán, Luật Kế toán, Luật Kiểm toán "
            "độc lập, Luật Ngân sách nhà nước, Luật Quản lý thuế, có hiệu lực kể từ "
            "ngày 01 tháng 01 năm 2025;\n"
            "2. Luật Phục hồi, phá sản số 142/2025/QH15 ngày 11 tháng 12 năm 2025 "
            "của Quốc hội.\n"
        )
        result = handle_vbhn_relation(
            base_extractor=self.extractor.base_extractor,
            clause_type="vanban",
            clause_key=None,
            clause_content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            build_relations_fn=self.extractor._build_relations,
        )
        tails = [str(item["tail"]) for item in self._flatten(result)]
        # kept: numbered consolidation targets
        self.assertTrue(any("54/2019/QH14" in t for t in tails), tails)
        self.assertTrue(any("56/2024/QH15" in t for t in tails), tails)
        self.assertTrue(any("142/2025/QH15" in t for t in tails), tails)
        # dropped: bare amendment-scope law names
        for bare in ("Luật Kế toán", "Luật Kiểm toán độc lập",
                     "Luật Ngân sách nhà nước", "Luật Quản lý thuế"):
            self.assertFalse(any(bare in t and "/" not in t.split(bare)[-1][:20]
                                 for t in tails),
                             f"{bare} should not be a hop_nhat target: {tails}")
        self.assertEqual(len(tails), 3, tails)

    def test_handle_vbhn_relation_skips_non_vanban_and_clause_only_references(self) -> None:
        non_vanban_result = handle_vbhn_relation(
            base_extractor=self.extractor.base_extractor,
            clause_type="dieu",
            clause_key="dieu_1",
            clause_content="Hợp nhất Luật Đất đai năm 2024.",
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
            build_relations_fn=self.extractor._build_relations,
        )
        self.assertEqual(non_vanban_result, [])


if __name__ == "__main__":
    unittest.main()
