import unittest

from src.domain.extractors.base_extractor import BaseExtractor
from src.utils.post_processing import _create_clause_key_reference


class TestDecimalDiemReference(unittest.TestCase):
    def test_extracts_letter_dot_number_diem_reference(self) -> None:
        extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"]
        )

        references = extractor.extract_references(
            content="Căn cứ tại điểm b.4 khoản 11 Điều 13 Nghị định 126/2020/NĐ-CP",
            doc_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"],
            clause_types=["điểm", "khoản", "điều"],
            law_titles=[],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["diem"]["information"], "điểm b.4")
        self.assertEqual(references[0]["khoan"]["information"], "khoản 11")
        self.assertEqual(references[0]["dieu"]["information"], "Điều 13")

    def test_clause_key_reference_removes_decimal_separator_from_diem(self) -> None:
        target_key = _create_clause_key_reference(
            {
                "diem": "điểm b.4",
                "khoan": "khoản 11",
                "dieu": "Điều 13",
            }
        )

        self.assertEqual(target_key, "diem_b4_khoan_11_dieu_13")

    def test_clause_key_reference_preserves_d_stroke_point_label(self) -> None:
        target_key = _create_clause_key_reference(
            {
                "diem": "điểm đ",
                "khoan": "khoản 2",
                "dieu": "Điều 12",
            }
        )

        self.assertEqual(target_key, "diem_đ_khoan_2_dieu_12")

    def test_clause_key_reference_keeps_plain_d_distinct_from_d_stroke(self) -> None:
        target_key = _create_clause_key_reference(
            {
                "diem": "điểm d",
                "khoan": "khoản 2",
                "dieu": "Điều 12",
            }
        )

        self.assertEqual(target_key, "diem_d_khoan_2_dieu_12")

    def test_relation_matching_keeps_multiple_letter_dot_number_diem_targets(self) -> None:
        extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"]
        )
        content = (
            "Điều 1. Sửa đổi, bổ sung điểm b.3, điểm b.4 khoản 11 Điều 13 "
            "Nghị định 126/2020/NĐ-CP như sau: nội dung mới."
        )

        references = extractor.extract_references(
            content=content,
            doc_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"],
            clause_types=["điểm", "khoản", "điều"],
            law_titles=[],
        )
        relation_types = extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu="373/2025/NĐ-CP",
        )

        matched_points = [
            match["reference"]["diem"]["information"]
            for match in matches
            if match["relation_type"] == "sua_doi"
        ]

        self.assertEqual(matched_points, ["điểm b.3", "điểm b.4"])

    def test_clause_level_exact_bo_sung_uses_bo_sung_relation(self) -> None:
        extractor = BaseExtractor(
            doc_clause_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"]
        )
        content = "Bổ sung khoản 5 Điều 8 Nghị định 01/2026/NĐ-CP."

        references = extractor.extract_references(
            content=content,
            doc_types=["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"],
            clause_types=["điểm", "khoản", "điều"],
            law_titles=[],
        )
        relation_types = extractor.extract_relation_types(content=content, references=references)
        matches = extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu="02/2026/NĐ-CP",
        )

        self.assertIn("bo_sung", {match["relation_type"] for match in matches})


if __name__ == "__main__":
    unittest.main()
