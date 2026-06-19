"""Unit tests for DistractorFilter — 4 rules, 2+ positive + 2+ negative cases each."""

import unittest

from src.domain.extractors.distractor_filter import DistractorFilter


def _make_match(relation_type: str, text: str, start: int = 0) -> dict:
    return {
        "relation_type": relation_type,
        "text": text,
        "position_start": start,
        "position_end": start + len(text),
        "hint_group": "forward_hints",
        "direction": "FORWARD",
    }


class TestDistractorFilterNonLegalBoSung(unittest.TestCase):
    """Rule 1: 'bổ sung' followed by non-legal objects."""

    def setUp(self):
        self.f = DistractorFilter()

    # --- Should reject ---

    def test_bo_sung_ho_so(self):
        content = "3. Cơ quan thẩm quyền yêu cầu bổ sung hồ sơ còn thiếu trong vòng 5 ngày."
        match = _make_match("bo_sung", "bổ sung", content.index("bổ sung"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("non_legal_bo_sung", rejected[0]["rejection_reason"])

    def test_bo_sung_thong_tin(self):
        content = "Chủ đầu tư phải bổ sung thông tin theo yêu cầu của cơ quan chức năng."
        match = _make_match("bo_sung", "bổ sung", content.index("bổ sung"))
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(rejected), 1)

    def test_bo_sung_nguon_luc(self):
        content = "Tỉnh cần bổ sung nguồn lực để thực hiện dự án."
        match = _make_match("bo_sung", "bổ sung", content.index("bổ sung"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(rejected), 1)

    # --- Should NOT reject ---

    def test_sua_doi_bo_sung_legal_target(self):
        content = "Sửa đổi, bổ sung một số điều của Luật số 45/2019/QH14."
        match = _make_match("sua_doi_bo_sung", "sửa đổi, bổ sung", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "sửa đổi, bổ sung should not be rejected")
        self.assertEqual(len(rejected), 0)

    def test_bo_sung_dieu_khoan(self):
        content = "Bổ sung khoản 3a vào Điều 15 Thông tư số 12/2020/TT-BTC."
        match = _make_match("bo_sung", "bổ sung khoản", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "bổ sung điều/khoản should pass through")

    def test_bo_sung_not_followed_by_non_legal(self):
        content = "Bổ sung quy định tại khoản 2 Điều 5 Nghị định số 10/2021/NĐ-CP."
        match = _make_match("sua_doi_bo_sung", "bổ sung quy định", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1)


class TestDistractorFilterNonLegalDinhChi(unittest.TestCase):
    """Rule 2: 'đình chỉ/ngưng hiệu lực' applied to activities/licences."""

    def setUp(self):
        self.f = DistractorFilter()

    # --- Should reject ---

    def test_dinh_chi_hoat_dong(self):
        content = "a) Quyết định đình chỉ hoạt động bị hủy theo quyết định giải quyết khiếu nại."
        match = _make_match("dinh_chi", "đình chỉ", content.index("đình chỉ"))
        kept, rejected = self.f.filter_by_context(content, [match], "diem")
        self.assertEqual(len(rejected), 1)
        self.assertIn("non_legal_dinh_chi", rejected[0]["rejection_reason"])

    def test_dinh_chi_giay_phep(self):
        content = "Cơ quan có thẩm quyền tạm đình chỉ giấy phép kinh doanh trong 30 ngày."
        match = _make_match("dinh_chi", "tạm đình chỉ", content.index("tạm đình chỉ"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(rejected), 1)

    def test_ngung_hieu_luc_chung_chi(self):
        content = "Hiệu lực của chứng chỉ bị ngưng hiệu lực chứng chỉ hành nghề theo quyết định."
        match = _make_match("ngung_hieu_luc", "ngưng hiệu lực", content.index("ngưng hiệu lực"))
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(rejected), 1)

    # --- Should NOT reject ---

    def test_dinh_chi_van_ban_phap_luat(self):
        content = "Đình chỉ hiệu lực thi hành Nghị định số 25/2020/NĐ-CP ngày 28 tháng 2."
        match = _make_match("dinh_chi", "đình chỉ hiệu lực thi hành", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "dinh_chi on a legal document should pass")


class TestDistractorFilterNonLegalKeoDai(unittest.TestCase):
    """Rule 5: 'kéo dài thời gian/thời hạn' applied to admin/personnel activity."""

    def setUp(self):
        self.f = DistractorFilter()

    def test_keo_dai_gia_han_nop_ho_so(self):
        content = "Trường hợp phải kéo dài thời gian gia hạn nộp hồ sơ khai thuế."
        match = _make_match("keo_dai_hieu_luc", "kéo dài thời gian",
                            content.index("kéo dài thời gian"))
        kept, rejected = self.f.filter_by_context(content, [match], "diem")
        self.assertEqual(len(rejected), 1)
        self.assertIn("non_legal_keo_dai", rejected[0]["rejection_reason"])

    def test_keo_dai_nang_bac_luong(self):
        content = "thời gian kéo dài thời gian nâng bậc lương thường xuyên của công chức."
        match = _make_match("keo_dai_hieu_luc", "kéo dài thời gian",
                            content.index("kéo dài thời gian"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(rejected), 1)

    def test_keo_dai_thuc_hien_document_passes(self):
        """'kéo dài thời gian thực hiện <doc>' is a legitimate keo_dai_hieu_luc."""
        content = "Kéo dài thời gian thực hiện Nghị quyết số 18/2022/NQ-HĐND."
        match = _make_match("keo_dai_hieu_luc", "kéo dài thời gian", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "extending implementation of a document should pass")

    def test_keo_dai_hieu_luc_passes(self):
        content = "Kéo dài hiệu lực thi hành Thông tư số 12/2018/TT-BTC."
        match = _make_match("keo_dai_hieu_luc", "kéo dài hiệu lực", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1)

    def test_ngung_hieu_luc_nghi_dinh(self):
        content = "Ngưng hiệu lực toàn bộ Nghị định 123/2019/NĐ-CP cho đến khi có quy định mới."
        match = _make_match("ngung_hieu_luc", "ngưng hiệu lực toàn bộ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1)


class TestDistractorFilterNonLegalHuyBo(unittest.TestCase):
    """Rule 3: 'hủy bỏ/thu hồi' applied to administrative objects."""

    def setUp(self):
        self.f = DistractorFilter()

    # --- Should reject ---

    def test_huy_bo_cong_nhan(self):
        content = "Hủy bỏ công nhận danh hiệu thi đua đối với cá nhân vi phạm."
        match = _make_match("huy_bo", "hủy bỏ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(rejected), 1)
        self.assertIn("non_legal_huy_bo", rejected[0]["rejection_reason"])

    def test_thu_hoi_chung_chi(self):
        content = "Sở cấp phép có quyền thu hồi chứng chỉ hành nghề khi phát hiện vi phạm."
        match = _make_match("huy_bo", "thu hồi", content.index("thu hồi"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(rejected), 1)

    def test_huy_bo_tai_san(self):
        content = "6. Tổ chức thanh lý tài sản nhà nước theo phương thức phá dỡ, hủy bỏ tài sản nhà nước."
        match = _make_match("huy_bo", "hủy bỏ", content.index("hủy bỏ"))
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(rejected), 1)

    # --- Should NOT reject ---

    def test_huy_bo_quyet_dinh_phap_luat(self):
        content = "Hủy bỏ Quyết định số 3009/QĐ-UBND ngày 20/9/2021 của UBND tỉnh ban hành Quy định về chính sách hỗ trợ sáng tạo khoa học."
        match = _make_match("huy_bo", "Hủy bỏ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "Hủy bỏ Quyết định (legal doc) should NOT be rejected")
        self.assertEqual(len(rejected), 0)

    def test_huy_bo_toan_bo_nghi_dinh(self):
        content = "Hủy bỏ toàn bộ nội dung Quyết định số 05/2011/QĐ-UBND ngày 09 tháng 8 năm 2011 của Ủy ban nhân dân quận 7."
        match = _make_match("huy_bo", "Hủy bỏ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1)


class TestDistractorFilterHeadingContext(unittest.TestCase):
    """Rule 4: 'dieu' clause that is a pure article heading."""

    def setUp(self):
        self.f = DistractorFilter()

    # --- Should reject ---

    def test_heading_bai_bo_va_thay_the(self):
        content = "Điều 3. Bãi bỏ và thay thế các văn bản quy định phí, lệ phí"
        match = _make_match("bai_bo", "bãi bỏ", content.index("Bãi bỏ"))
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(rejected), 1)
        self.assertIn("heading_title_context", rejected[0]["rejection_reason"])

    def test_heading_sua_doi_bo_sung(self):
        content = "Điều 2. Sửa đổi, bổ sung một số điều của Thông tư"
        match = _make_match("sua_doi_bo_sung", "sửa đổi, bổ sung", content.index("Sửa đổi"))
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(rejected), 1)

    # --- Should NOT reject ---

    def test_operative_huy_bo_no_dieu_prefix(self):
        content = "Hủy bỏ Quyết định số 3009/QĐ-UBND ngày 20/9/2021 của UBND tỉnh."
        match = _make_match("huy_bo", "Hủy bỏ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "Operative article (no Điều X. prefix) should NOT be rejected")

    def test_heading_with_doc_number_reference(self):
        content = "Điều 5. Bãi bỏ Thông tư số 12/2019/TT-BTC ngày 03 tháng 3 năm 2019"
        match = _make_match("bai_bo", "bãi bỏ", content.index("Bãi bỏ"))
        kept, rejected = self.f.filter_by_context(content, [match], "dieu")
        self.assertEqual(len(kept), 1, "Heading with doc number reference should pass through")

    def test_non_dieu_type_not_affected(self):
        content = "Bãi bỏ điểm a khoản 1 Điều 5"
        match = _make_match("bai_bo", "Bãi bỏ", 0)
        kept, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertEqual(len(kept), 1, "Non-dieu clause type is not subject to heading rule")


class TestDistractorFilterRejectionTracking(unittest.TestCase):
    """Verify that rejection_reason is populated and pass-through items are clean."""

    def setUp(self):
        self.f = DistractorFilter()

    def test_rejection_reason_is_non_empty_string(self):
        content = "Cơ quan thẩm quyền yêu cầu bổ sung hồ sơ theo đúng quy định."
        match = _make_match("sua_doi_bo_sung", "bổ sung", content.index("bổ sung"))
        _, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertTrue(len(rejected) > 0)
        self.assertIsInstance(rejected[0]["rejection_reason"], str)
        self.assertTrue(len(rejected[0]["rejection_reason"]) > 0)

    def test_kept_items_have_no_rejection_reason(self):
        content = "Bổ sung khoản 3a vào Điều 15 Nghị định số 10/2020/NĐ-CP."
        match = _make_match("sua_doi_bo_sung", "bổ sung", 0)
        kept, _ = self.f.filter_by_context(content, [match], "dieu")
        for item in kept:
            self.assertNotIn("rejection_reason", item)

    def test_all_original_keys_preserved_in_rejected(self):
        content = "Cơ quan yêu cầu bổ sung thông tin theo quy định."
        match = _make_match("sua_doi_bo_sung", "bổ sung", content.index("bổ sung"))
        _, rejected = self.f.filter_by_context(content, [match], "khoan")
        self.assertIn("relation_type", rejected[0])
        self.assertIn("text", rejected[0])
        self.assertIn("position_start", rejected[0])
        self.assertIn("rejection_reason", rejected[0])

    def test_mixed_batch_splits_correctly(self):
        content = "Bổ sung hồ sơ theo quy định. Bổ sung khoản 2 vào Điều 5 Luật 45/2019/QH14."
        match_fp = _make_match("sua_doi_bo_sung", "bổ sung", 0)
        match_tp = _make_match("sua_doi_bo_sung", "bổ sung", content.rindex("Bổ sung"))
        kept, rejected = self.f.filter_by_context(content, [match_fp, match_tp], "khoan")
        self.assertEqual(len(rejected), 1, "Only the non-legal 'bổ sung hồ sơ' should be rejected")
        self.assertEqual(len(kept), 1, "The legal 'bổ sung khoản' should be kept")


if __name__ == "__main__":
    unittest.main()
