"""Tests for action-keyword noise distractor filtering via citation-cue bridge check.

When an action relation keyword (thu hồi, hủy bỏ, bãi bỏ, …) appears in a sentence
whose first legal reference is introduced by a citation cue phrase ("theo quy định tại",
"theo quy định của", "quy định tại", "được quy định tại/trong"), the reference is a
LEGAL BASIS (căn cứ pháp lý), not the target of the action.  The relation must be
converted to dan_chieu.

Additionally, when an action relation fires and the only references in the sentence scope
are internal self-references ("Điều này", "khoản X Điều này", "Luật này", etc.), the
action keyword is noise — no external document is targeted.  The result must be
dan_chieu only.  This applies regardless of how much content appears between the
action keyword and the internal reference.

Contrast: when no citation cue appears in the bridge from action_end to first_ref AND
an external document reference is present, the reference IS the target and the action
relation is preserved.
"""
import logging
import unittest

from src.domain.extractors.base_extractor_flow.relation_type_extraction import RelationTypeExtraction

logging.disable(logging.INFO)


def _ref(content: str, text: str, key: str) -> dict:
    start = content.index(text)
    return {key: {"information": text, "position_start": start, "position_end": start + len(text)}}


class TestActionNoiseThuHoi(unittest.TestCase):
    """Scenario 1: 'thu hồi đất … theo quy định tại khoản/điều' must yield dan_chieu."""

    def setUp(self):
        self.rte = RelationTypeExtraction()

    def test_thu_hoi_dat_theo_quy_dinh_tai_khoan_is_dan_chieu(self):
        """'thu hồi' fires bai_bo but is noise — reference is a legal basis via 'theo quy định tại'."""
        content = (
            "a) Trường hợp chưa có quyết định thu hồi đất thì Ủy ban nhân dân cấp "
            "có thẩm quyền xử lý theo quy định tại khoản 8 và khoản 9 Điều 81 của Luật này;"
        )
        khoan8_start = content.index("khoản 8")
        refs = [{"khoan": {"information": "khoản 8",
                            "position_start": khoan8_start,
                            "position_end": khoan8_start + len("khoản 8")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types, "'thu hồi đất' is noise — bai_bo must not appear")
        self.assertIn("dan_chieu", types)

    def test_thu_hoi_theo_quy_dinh_cua(self):
        """'theo quy định của' variant also triggers dan_chieu conversion."""
        content = (
            "Trường hợp thu hồi giấy phép, xử lý theo quy định của "
            "Luật Xử lý vi phạm hành chính."
        )
        refs = [_ref(content, "Luật Xử lý vi phạm hành chính", "luat")]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types)
        self.assertIn("dan_chieu", types)


class TestActionNoiseHuyBo(unittest.TestCase):
    """Scenario 2: 'hủy bỏ … theo quy định của Luật này và Bộ luật X' must yield dan_chieu."""

    def setUp(self):
        self.rte = RelationTypeExtraction()

    def test_huy_bo_theo_quy_dinh_cua_luat_nay_is_dan_chieu(self):
        """'hủy bỏ' fires huy_bo but the reference is introduced by 'theo quy định của'."""
        content = (
            "Cơ quan điều tra, Viện kiểm sát, Tòa án ra quyết định hủy bỏ quyết định "
            "áp dụng thủ tục rút gọn và giải quyết vụ án theo quy định của Luật này "
            "và Bộ luật Tố tụng hình sự."
        )
        boluat_start = content.index("Bộ luật Tố tụng hình sự")
        refs = [{"boluat": {"information": "Bộ luật Tố tụng hình sự",
                             "position_start": boluat_start,
                             "position_end": boluat_start + len("Bộ luật Tố tụng hình sự")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("huy_bo", types, "'hủy bỏ quyết định … theo quy định của' is noise")
        self.assertIn("dan_chieu", types)


class TestActionRelationPreservedWhenNoCitationCue(unittest.TestCase):
    """Regression: direct action relations (no citation cue in bridge) must be preserved."""

    def setUp(self):
        self.rte = RelationTypeExtraction()

    def test_direct_bai_bo_nghidinh_is_preserved(self):
        """No citation cue in bridge → bai_bo target is real."""
        content = "Bãi bỏ Nghị định số 123/2023/NĐ-CP ngày 10 tháng 3 năm 2023 của Chính phủ."
        nghidinh_start = content.index("Nghị định số 123")
        refs = [{"nghidinh": {"information": "123/2023/NĐ-CP",
                               "position_start": nghidinh_start,
                               "position_end": nghidinh_start + len("Nghị định số 123/2023/NĐ-CP")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertIn("bai_bo", types, "Direct bai_bo target must be preserved")
        self.assertNotIn("dan_chieu", types)

    def test_phu_hop_voi_nghidinh_is_dan_chieu(self):
        """'không còn phù hợp với Nghị định X' — X is the legal basis (căn cứ), must be dan_chieu."""
        content = (
            "Hủy bỏ hiệu lực thi hành các Quyết định vì không còn phù hợp với "
            "Nghị định số 35/2001/NĐ-CP ngày 09/7/2001 của Chính phủ."
        )
        nghidinh_start = content.index("Nghị định số 35")
        refs = [{"nghidinh": {"information": "35/2001/NĐ-CP",
                               "position_start": nghidinh_start,
                               "position_end": nghidinh_start + len("Nghị định số 35/2001/NĐ-CP")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("huy_bo", types, "'phù hợp với' signals legal basis — huy_bo must not appear")
        self.assertIn("dan_chieu", types)

    def test_trai_voi_luat_is_dan_chieu(self):
        """'trái với Luật X' — X là tiêu chuẩn pháp lý bị vi phạm, phải là dan_chieu."""
        content = (
            "Bãi bỏ các quy định trái với Luật Cạnh tranh số 23/2018/QH14."
        )
        luat_start = content.index("Luật Cạnh tranh")
        refs = [{"luat": {"information": "Luật Cạnh tranh số 23/2018/QH14",
                           "position_start": luat_start,
                           "position_end": luat_start + len("Luật Cạnh tranh số 23/2018/QH14")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types, "'trái với' signals legal basis — bai_bo must not appear")
        self.assertIn("dan_chieu", types)

    def test_mau_thuan_voi_is_dan_chieu(self):
        """'mâu thuẫn với Luật X' — X là căn cứ pháp lý xung đột, phải là dan_chieu."""
        content = (
            "Hủy bỏ các điều khoản mâu thuẫn với Bộ luật Dân sự."
        )
        boluat_start = content.index("Bộ luật Dân sự")
        refs = [{"boluat": {"information": "Bộ luật Dân sự",
                             "position_start": boluat_start,
                             "position_end": boluat_start + len("Bộ luật Dân sự")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("huy_bo", types, "'mâu thuẫn với' signals legal basis — huy_bo must not appear")
        self.assertIn("dan_chieu", types)

    def test_vi_pham_is_dan_chieu(self):
        """'vi phạm Luật X' — X là căn cứ pháp lý bị vi phạm, phải là dan_chieu."""
        content = (
            "Bãi bỏ quyết định vi phạm Luật Đất đai."
        )
        luat_start = content.index("Luật Đất đai")
        refs = [{"luat": {"information": "Luật Đất đai",
                           "position_start": luat_start,
                           "position_end": luat_start + len("Luật Đất đai")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types, "'vi phạm' signals legal basis — bai_bo must not appear")
        self.assertIn("dan_chieu", types)

    def test_viec_thuc_hien_theo_quy_dinh_tai_still_works(self):
        """Backward compat: original 'thực hiện theo quy định tại' case still converts."""
        content = (
            "Việc bãi bỏ các thủ tục hành chính thực hiện theo quy định tại "
            "Điều 4 của Nghị định số 78/2025/NĐ-CP."
        )
        nghidinh_start = content.index("Nghị định")
        refs = [{"nghidinh": {"information": "78/2025/NĐ-CP",
                               "position_start": nghidinh_start,
                               "position_end": nghidinh_start + len("Nghị định số 78/2025/NĐ-CP")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types, "Original thực hiện theo quy định tại case must still convert")
        self.assertIn("dan_chieu", types)


class TestActionNoiseNayInternalRef(unittest.TestCase):
    """Action keyword + only internal 'này' self-references → must yield dan_chieu only.

    The action keyword can appear anywhere in the sentence; content of arbitrary
    length may separate it from the 'khoản X Điều này' / 'Luật này' reference.
    No external document target is present, so the action keyword is noise.
    """

    def setUp(self):
        self.rte = RelationTypeExtraction()

    def _clause_ref(self, content: str, text: str) -> dict:
        start = content.index(text)
        return {"khoan": {"information": text, "position_start": start, "position_end": start + len(text)}}

    def test_bai_bo_with_content_before_dieu_nay_is_dan_chieu(self):
        """'bãi bỏ' fires, but the only ref is 'khoản 1 Điều này' — internal, must be dan_chieu."""
        content = (
            "Trường hợp chưa có quyết định bãi bỏ thì Ủy ban nhân dân cấp có thẩm quyền "
            "xử lý theo quy định tại khoản 1 Điều này."
        )
        refs = [self._clause_ref(content, "khoản 1")]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("bai_bo", types, "'bãi bỏ' before 'khoản 1 Điều này' is noise")
        self.assertIn("dan_chieu", types)

    def test_huy_bo_with_content_before_khoan_dieu_nay_is_dan_chieu(self):
        """'hủy bỏ' fires, but the only ref is 'khoản 2 Điều này' — internal."""
        content = (
            "Cơ quan có thẩm quyền ra quyết định hủy bỏ quyết định áp dụng biện pháp "
            "và giải quyết vụ việc theo quy định tại khoản 2 Điều này."
        )
        refs = [self._clause_ref(content, "khoản 2")]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("huy_bo", types, "'hủy bỏ' before 'khoản 2 Điều này' is noise")
        self.assertIn("dan_chieu", types)

    def test_sua_doi_with_content_before_dieu_nay_is_dan_chieu(self):
        """'sửa đổi' fires, but the only ref is 'khoản 3 Điều này' — internal."""
        content = (
            "Nội dung sửa đổi, bổ sung một số quy định không còn phù hợp tại "
            "khoản 3 Điều này như sau:"
        )
        refs = [self._clause_ref(content, "khoản 3")]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertNotIn("sua_doi_bo_sung", types, "'sửa đổi' before 'khoản 3 Điều này' is noise")
        self.assertNotIn("sua_doi", types)

    def test_bai_bo_with_external_doc_ref_is_preserved(self):
        """Regression: 'bãi bỏ' + external doc ref must be preserved even if 'Điều này' also present."""
        content = (
            "Bãi bỏ Điều 5 của Luật Đất đai có liên quan đến quy định tại Điều này."
        )
        luat_start = content.index("Luật Đất đai")
        refs = [{"luat": {"information": "Luật Đất đai",
                           "position_start": luat_start,
                           "position_end": luat_start + len("Luật Đất đai")}}]
        result = self.rte.extract_relation_types(content=content, references=refs)
        types = {r["relation_type"] for r in result}
        self.assertIn("bai_bo", types, "External doc target must be preserved")
