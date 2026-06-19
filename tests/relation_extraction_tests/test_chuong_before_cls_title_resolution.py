"""Tests for document reference resolution: chuong context must be tried before cls_title.

Priority rule for missing document references:
  internal reference   → current document (no chuong / cls_title lookup)
  non-internal         → nearest chuong (by position in data) → cls_title
"""
import unittest

from src.domain.extractors.relations_extractor import RelationsExtractor


class TestChuongBeforeClsTitleResolution(unittest.TestCase):

    def setUp(self) -> None:
        self.extractor = RelationsExtractor(
            doc_clause_types={
                "doc_types": ["Luật", "Nghị định", "Thông tư", "Nghị quyết", "Quyết định"],
                "clause_types": ["điều", "khoản", "điểm"],
            }
        )

    # ------------------------------------------------------------------
    # Case 1 – No chuong available: must fall back to cls_title
    # ------------------------------------------------------------------
    def test_falls_back_to_cls_title_when_no_chuong(self):
        """When no chuong precedes the clause, resolve doc ref from cls_title."""
        data = [
            {
                "com_type": "dieu",
                "com_key": "dieu_2",
                "com_title": "Điều 2. Sửa đổi, bổ sung Điều 2",
            }
        ]
        cls_title = (
            "THÔNG TƯ "
            "SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA THÔNG TƯ SỐ 35/2025/TT-NHNN "
            "QUY ĐỊNH VỀ CHO VAY ĐẶC BIỆT ĐỐI VỚI TỔ CHỨC TÍN DỤNG"
        )

        results = self.extractor.extract_relations(
            data=data,
            cls_so_hieu="36/2025/TT-NHNN",
            cls_title=cls_title,
        )

        dieu_2_results = [r for r in results if r["clause_key"] == "dieu_2"]
        self.assertGreater(len(dieu_2_results), 0)

        found = any(
            rel["relation"] == "sua_doi"
            and any(
                "thongtu" in tail
                and "35/2025/TT-NHNN" in tail["thongtu"]["information"]
                for tail in rel["tail"]
            )
            for rel in dieu_2_results[0]["relations"]
        )
        self.assertTrue(
            found,
            "Expected sua_doi → Điều 2 Thông tư 35/2025/TT-NHNN via cls_title fallback",
        )

    # ------------------------------------------------------------------
    # Case 2 – chuong present: must use chuong, NOT cls_title
    # ------------------------------------------------------------------
    def test_prefers_chuong_over_cls_title(self):
        """When a chuong precedes the clause and contains a doc ref, use it over cls_title."""
        data = [
            {
                "com_type": "chuong",
                "com_key": "chuong_1",
                "com_title": (
                    "Chương I\n"
                    "SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA QUY ĐỊNH QUẢN LÝ HOẠT ĐỘNG DU LỊCH "
                    "TRÊN ĐỊA BÀN TỈNH LAI CHÂU BAN HÀNH KÈM THEO QUYẾT ĐỊNH SỐ 08/2020/QĐ-UBND "
                    "NGÀY 26 THÁNG 02 NĂM 2020 ĐƯỢC SỬA ĐỔI, BỔ SUNG BỞI QUYẾT ĐỊNH SỐ "
                    "20/2021/QĐ-UBND NGÀY 17 THÁNG 6 NĂM 2021 CỦA ỦY BAN NHÂN DÂN TỈNH"
                ),
            },
            {
                "com_type": "dieu",
                "com_key": "dieu_1",
                "com_title": "Điều 1. Sửa đổi, bổ sung một số điểm, khoản của Điều 13.",
            },
            {
                "com_type": "khoan",
                "com_key": "khoan_1_dieu_1",
                "com_title": (
                    "1. Bổ sung điểm g, điểm h, điểm i vào sau điểm e khoản 1 Điều 13 như sau:"
                ),
            },
        ]
        # cls_title intentionally has multiple doc refs to expose wrong selection
        cls_title = (
            "Quyết định sửa đổi quy định kèm theo Quyết định 08/2020/QĐ-UBND "
            "được sửa đổi bởi Quyết định 20/2021/QĐ-UBND; Quyết định 09/2023/QĐ-UBND "
            "do tỉnh Lai Châu ban hành"
        )

        results = self.extractor.extract_relations(
            data=data,
            cls_so_hieu="XX/2024/QĐ-UBND",
            cls_title=cls_title,
        )

        khoan_results = [r for r in results if r["clause_key"] == "khoan_1_dieu_1"]
        self.assertGreater(len(khoan_results), 0)

        # Must find at least one bo_sung relation targeting Quyết định 08/2020/QĐ-UBND
        found_correct = any(
            rel["relation"] == "bo_sung"
            and any(
                "quyetdinh" in tail
                and "08/2020/QĐ-UBND" in tail["quyetdinh"]["information"]
                for tail in rel["tail"]
            )
            for rel in khoan_results[0]["relations"]
        )
        self.assertTrue(
            found_correct,
            "Expected bo_sung to target Quyết định 08/2020/QĐ-UBND (from chuong), not other docs",
        )

        # Must NOT resolve to the wrong doc 09/2023/QĐ-UBND
        found_wrong = any(
            rel["relation"] == "bo_sung"
            and any(
                "quyetdinh" in tail
                and "09/2023/QĐ-UBND" in tail["quyetdinh"]["information"]
                for tail in rel["tail"]
            )
            for rel in khoan_results[0]["relations"]
        )
        self.assertFalse(
            found_wrong,
            "Resolver must not pick Quyết định 09/2023/QĐ-UBND from cls_title when chuong provides the ref",
        )

    # ------------------------------------------------------------------
    # Case 3 – Internal reference: skip chuong AND cls_title
    # ------------------------------------------------------------------
    def test_internal_reference_skips_chuong_and_cls_title(self):
        """Internal references (Luật này / Nghị định này) use the current document, not chuong or cls_title."""
        data = [
            {
                "com_type": "chuong",
                "com_key": "chuong_1",
                "com_title": (
                    "Chương I\n"
                    "QUY ĐỊNH CHUNG"
                ),
            },
            {
                "com_type": "dieu",
                "com_key": "dieu_5",
                "com_title": "Điều 5. Nguyên tắc áp dụng",
            },
            {
                "com_type": "khoan",
                "com_key": "khoan_2_dieu_5",
                "com_title": "2. Trường hợp có sự mâu thuẫn giữa các điều, khoản của Nghị định này thì áp dụng theo quy định tại Điều 3 Nghị định này.",
            },
        ]
        cls_title = (
            "Nghị định số 99/2024/NĐ-CP quy định về quản lý an toàn thực phẩm"
        )

        results = self.extractor.extract_relations(
            data=data,
            cls_so_hieu="99/2024/NĐ-CP",
            cls_document_type="Nghị định",
            cls_title=cls_title,
        )

        khoan_results = [r for r in results if r["clause_key"] == "khoan_2_dieu_5"]
        # If there are dan_chieu relations, their target doc must be the current doc (99/2024/NĐ-CP)
        for entry in khoan_results:
            for rel in entry.get("relations", []):
                if rel["relation"] == "dan_chieu":
                    for tail in rel["tail"]:
                        for key, val in tail.items():
                            if key not in {"diem", "khoan", "dieu"}:
                                info = val.get("information", "")
                                self.assertIn(
                                    "99/2024/NĐ-CP",
                                    info,
                                    f"Internal reference must resolve to current doc, got: {info}",
                                )


if __name__ == "__main__":
    unittest.main()
