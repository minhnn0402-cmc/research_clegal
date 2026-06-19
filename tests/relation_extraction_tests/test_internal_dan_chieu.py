"""
Comprehensive tests for internal dan_chieu reference resolution.

Tests the InternalReferenceResolver which detects and resolves internal
references like "khoản 2 Điều này", "Luật này", "từ điểm a đến điểm g
khoản 1 Điều này" within legal documents.
"""

import unittest
from src.domain.extractors.internal_reference_resolver import InternalReferenceResolver


def _make_data(*clauses):
    """Build a minimal cls_parsing list from (com_key, com_type) tuples."""
    return [
        {"com_key": key, "com_type": ctype, "com_title": f"Content of {key}"}
        for key, ctype in clauses
    ]


def _make_hierarchy(pairs):
    """Build child_to_parent from [(child, parent), ...] pairs."""
    return {child: parent for child, parent in pairs}


def _build_resolver(
    clause_key,
    data,
    child_to_parent,
    cls_document_type="Luật",
    cls_so_hieu="59/2024/QH15",
):
    """Build an InternalReferenceResolver with sensible defaults."""
    return InternalReferenceResolver(
        clause_key=clause_key,
        child_to_parent=child_to_parent,
        data=data,
        cls_document_type=cls_document_type,
        cls_so_hieu=cls_so_hieu,
    )


def _extract_ref_info(match, component_key):
    """Helper to extract the 'information' of a specific component from a match."""
    ref = match.get("reference", {})
    comp = ref.get(component_key, {})
    return comp.get("information", "")


class TestRealWorldScenarios(unittest.TestCase):
    """Test with content that mimics real legal documents."""

    def test_effective_date_khoan_references_resolve_to_current_clause(self):
        """
        "Thông tư này có hiệu lực thi hành kể từ ngày 01 tháng 3 năm 2026,
         trừ trường hợp quy định tại khoản 2, khoản 3 Điều này."
        """
        data = _make_data(
            ("dieu_3", "dieu"),
            ("khoan_1_dieu_3", "khoan"),
        )
        c2p = _make_hierarchy([("khoan_1_dieu_3", "dieu_3")])
        resolver = _build_resolver(
            "khoan_1_dieu_3", data, c2p,
            "Thông tư", "77/2025/TT-NHNN"
        )

        content = (
            "Thông tư này có hiệu lực thi hành kể từ ngày 01 tháng 3 năm 2026, "
            "trừ trường hợp quy định tại khoản 2, khoản 3 Điều này."
        )
        matches = resolver.resolve(content)

        # Should get: khoản 2 Điều 3 Thông tư 77/2025/TT-NHNN
        #             khoản 3 Điều 3 Thông tư 77/2025/TT-NHNN
        #             Thông tư 77/2025/TT-NHNN (from "Thông tư này")
        khoan_matches = [m for m in matches if "khoan" in m["reference"]]
        doc_only_matches = [m for m in matches if "khoan" not in m["reference"] and "dieu" not in m["reference"]]

        self.assertEqual(len(khoan_matches), 2)
        khoans = sorted([_extract_ref_info(m, "khoan") for m in khoan_matches])
        self.assertEqual(khoans, ["khoản 2", "khoản 3"])

        for m in khoan_matches:
            self.assertEqual(_extract_ref_info(m, "dieu"), "Điều 3")
            self.assertEqual(
                _extract_ref_info(m, "thongtu"),
                "Thông tư 77/2025/TT-NHNN"
            )

        # "Thông tư này" is also detected
        self.assertEqual(len(doc_only_matches), 1)

    def test_mixed_multi_group_enumeration_resolves_every_group_to_host(self):
        """A multi-group clause enumeration governed by one trailing 'Luật này'
        resolves each group to the host document.

        "… tại các khoản 2, 3 và 4 Điều 64, Điều 65, khoản 4, khoản 5 Điều 66 và
        Điều 67 của Luật này" → 7 references.
        """
        data = _make_data(("dieu_3", "dieu"), ("khoan_3_dieu_3", "khoan"))
        c2p = _make_hierarchy([("khoan_3_dieu_3", "dieu_3")])
        resolver = _build_resolver("khoan_3_dieu_3", data, c2p, "Luật", "59/2024/QH15")
        content = (
            "Quyết định mở phiên họp được thực hiện theo quy định tương ứng tại "
            "các khoản 2, 3 và 4 Điều 64, Điều 65, khoản 4, khoản 5 Điều 66 và "
            "Điều 67 của Luật này."
        )
        matches = resolver.resolve(content)
        rendered = set()
        for m in matches:
            ref = m["reference"]
            parts = []
            if "khoan" in ref:
                parts.append(ref["khoan"]["information"])
            if "dieu" in ref:
                parts.append(ref["dieu"]["information"])
            rendered.add(" ".join(parts))
        for expected in (
            "khoản 2 Điều 64", "khoản 3 Điều 64", "khoản 4 Điều 64",
            "Điều 65", "khoản 4 Điều 66", "khoản 5 Điều 66", "Điều 67",
        ):
            self.assertIn(expected, rendered, rendered)

    def test_enumeration_does_not_cross_external_document_boundary(self):
        """The host enumeration must not absorb clauses bound to a different doc.

        "… tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế … quy
        định tại khoản 6 Điều 7 của Nghị định này" — only 'khoản 6 Điều 7' is
        internal; the Điều 32 group belongs to the external Luật quản lý thuế.
        """
        data = _make_data(("dieu_7", "dieu"), ("khoan_1_dieu_7", "khoan"))
        c2p = _make_hierarchy([("khoan_1_dieu_7", "dieu_7")])
        resolver = _build_resolver("khoan_1_dieu_7", data, c2p, "Nghị định", "129/2013/NĐ-CP")
        content = (
            "Không nộp hồ sơ khai thuế quy định tại các Khoản 1, 2, 3 và Khoản 5 "
            "Điều 32 của Luật quản lý thuế hoặc kể từ ngày hết thời hạn gia hạn "
            "nộp hồ sơ khai thuế quy định tại khoản 6 Điều 7 của Nghị định này."
        )
        matches = resolver.resolve(content)
        for m in matches:
            self.assertNotEqual(m["reference"].get("dieu", {}).get("information"), "Điều 32", m)

    def test_diem_range_a_to_g_expands_to_all_individual_diem(self):
        """
        "Người chưa thành niên là người làm chứng có các quyền và nghĩa vụ
         quy định tại các điểm từ điểm a đến điểm g khoản 1 Điều này
         và các quyền, nghĩa vụ khác theo quy định của Luật này."
        """
        data = _make_data(
            ("dieu_22", "dieu"),
            ("khoan_1_dieu_22", "khoan"),
            ("khoan_2_dieu_22", "khoan"),
        )
        c2p = _make_hierarchy([
            ("khoan_1_dieu_22", "dieu_22"),
            ("khoan_2_dieu_22", "dieu_22"),
        ])
        resolver = _build_resolver(
            "khoan_2_dieu_22", data, c2p,
            "Luật", "59/2024/QH15"
        )

        content = (
            "Người chưa thành niên là người làm chứng có các quyền và nghĩa vụ "
            "quy định tại các điểm từ điểm a đến điểm g khoản 1 Điều này "
            "và các quyền, nghĩa vụ khác theo quy định của Luật này."
        )
        matches = resolver.resolve(content)

        # Range a→g = [a, b, c, d, đ, e, g] = 7 điểm matches
        # + 1 "Luật này" match
        diem_matches = [m for m in matches if "diem" in m["reference"]]
        doc_matches = [m for m in matches if "diem" not in m["reference"] and "dieu" not in m["reference"]]

        self.assertEqual(len(diem_matches), 7)
        diems = [_extract_ref_info(m, "diem") for m in diem_matches]
        expected_diems = ["điểm a", "điểm b", "điểm c", "điểm d", "điểm đ", "điểm e", "điểm g"]
        self.assertEqual(diems, expected_diems)

        # All điểm matches should share the same khoản, điều, and document
        for m in diem_matches:
            self.assertEqual(_extract_ref_info(m, "khoan"), "khoản 1")
            self.assertEqual(_extract_ref_info(m, "dieu"), "Điều 22")
            self.assertEqual(_extract_ref_info(m, "luat"), "Luật 59/2024/QH15")

        # "Luật này" match
        self.assertEqual(len(doc_matches), 1)
        self.assertEqual(_extract_ref_info(doc_matches[0], "luat"), "Luật 59/2024/QH15")

    def test_single_khoan_nay_in_sibling_clause_resolves_to_parent_dieu(self):
        """
        "Ngoài các quyền và nghĩa vụ quy định tại khoản 1 Điều này,
         người chưa thành niên là bị can, bị cáo còn có các quyền..."
        """
        data = _make_data(
            ("dieu_21", "dieu"),
            ("khoan_1_dieu_21", "khoan"),
            ("khoan_2_dieu_21", "khoan"),
        )
        c2p = _make_hierarchy([
            ("khoan_1_dieu_21", "dieu_21"),
            ("khoan_2_dieu_21", "dieu_21"),
        ])
        resolver = _build_resolver(
            "khoan_2_dieu_21", data, c2p,
            "Luật", "59/2024/QH15"
        )

        content = (
            "Ngoài các quyền và nghĩa vụ quy định tại khoản 1 Điều này, "
            "người chưa thành niên là bị can, bị cáo còn có các quyền và nghĩa vụ sau đây:"
        )
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "khoan"), "khoản 1")
        self.assertEqual(_extract_ref_info(matches[0], "dieu"), "Điều 21")
        self.assertEqual(_extract_ref_info(matches[0], "luat"), "Luật 59/2024/QH15")

    def test_multiple_patterns_in_one_clause(self):
        """Content with both 'khoản X Điều này' AND 'Luật này'."""
        data = _make_data(
            ("dieu_10", "dieu"),
            ("khoan_1_dieu_10", "khoan"),
        )
        c2p = _make_hierarchy([("khoan_1_dieu_10", "dieu_10")])
        resolver = _build_resolver(
            "khoan_1_dieu_10", data, c2p,
            "Luật", "59/2024/QH15"
        )

        content = (
            "Được thông báo, giải thích về quyền và nghĩa vụ theo quy định "
            "tại khoản 2, khoản 3 Điều này và các quyền khác theo Luật này."
        )
        matches = resolver.resolve(content)

        # 2 khoản matches + 1 Luật này match = 3
        self.assertEqual(len(matches), 3)

        khoan_matches = [m for m in matches if "khoan" in m["reference"]]
        self.assertEqual(len(khoan_matches), 2)

        luat_matches = [m for m in matches if "khoan" not in m["reference"]]
        self.assertEqual(len(luat_matches), 1)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_empty_content(self):
        data = _make_data(("dieu_1", "dieu"))
        resolver = _build_resolver("dieu_1", data, {}, "Luật", "59/2024/QH15")
        self.assertEqual(resolver.resolve(""), [])
        self.assertEqual(resolver.resolve("   "), [])

    def test_no_internal_references(self):
        """Content without any 'này' references."""
        data = _make_data(("dieu_1", "dieu"))
        resolver = _build_resolver("dieu_1", data, {}, "Luật", "59/2024/QH15")
        content = "Phạm vi điều chỉnh của văn bản pháp luật"
        self.assertEqual(resolver.resolve(content), [])

    def test_missing_cls_document_type_returns_empty(self):
        """No cls_document_type → no resolution for Điều này patterns."""
        data = _make_data(("dieu_1", "dieu"), ("khoan_1_dieu_1", "khoan"))
        c2p = _make_hierarchy([("khoan_1_dieu_1", "dieu_1")])
        resolver = _build_resolver("khoan_1_dieu_1", data, c2p, "", "59/2024/QH15")
        content = "quy định tại khoản 2 Điều này"
        self.assertEqual(resolver.resolve(content), [])

    def test_missing_cls_so_hieu_returns_empty(self):
        """No cls_so_hieu → no resolution."""
        data = _make_data(("dieu_1", "dieu"), ("khoan_1_dieu_1", "khoan"))
        c2p = _make_hierarchy([("khoan_1_dieu_1", "dieu_1")])
        resolver = _build_resolver("khoan_1_dieu_1", data, c2p, "Luật", "")
        content = "quy định tại khoản 2 Điều này"
        # cls_so_hieu is empty, so _doc_info_string is just "Luật" (still valid)
        # But _resolve_internal_dan_chieu in relations_extractor.py checks for non-empty cls_so_hieu
        # At the resolver level, it should still produce results with the partial info
        # This tests the resolver itself, not the guard in relations_extractor.py
        matches = resolver.resolve(content)
        # The resolver creates references with doc_info_string = "Luật"
        self.assertEqual(len(matches), 1)

    def test_vanban_clause_type_no_dieu_ancestor(self):
        """Clause type 'vanban' has no dieu ancestor → no compound matches, only doc matches."""
        data = _make_data(("vanban", "vanban"))
        resolver = _build_resolver("vanban", data, {}, "Luật", "59/2024/QH15")
        content = "theo quy định của Luật này"
        matches = resolver.resolve(content)

        # "Luật này" should still be detected even without dieu ancestor
        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "luat"), "Luật 59/2024/QH15")

    def test_consumed_spans_prevent_double_matching(self):
        """Compound patterns consume spans, preventing standalone patterns from double-matching."""
        data = _make_data(
            ("dieu_5", "dieu"),
            ("khoan_1_dieu_5", "khoan"),
        )
        c2p = _make_hierarchy([("khoan_1_dieu_5", "dieu_5")])
        resolver = _build_resolver("khoan_1_dieu_5", data, c2p, "Luật", "59/2024/QH15")

        content = "khoản 2 Điều này và khoản 3 Điều này"
        matches = resolver.resolve(content)

        # Should get 2 compound matches, NOT additional standalone "Điều này"
        self.assertEqual(len(matches), 2)
        for m in matches:
            self.assertIn("khoan", m["reference"])

    def test_dieu_clause_resolves_itself(self):
        """When a dieu clause references 'Điều này', it should use its own number."""
        data = _make_data(("dieu_10", "dieu"))
        resolver = _build_resolver("dieu_10", data, {}, "Luật", "59/2024/QH15")

        content = "Điều này áp dụng cho các trường hợp sau"
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "dieu"), "Điều 10")


class TestKhoanNay(unittest.TestCase):
    """Test 'khoản này' pattern and its variants."""

    def setUp(self):
        self.data = _make_data(
            ("dieu_5", "dieu"),
            ("khoan_1_dieu_5", "khoan"),
            ("diem_a_khoan_1_dieu_5", "diem"),
        )
        self.c2p = _make_hierarchy([
            ("diem_a_khoan_1_dieu_5", "khoan_1_dieu_5"),
            ("khoan_1_dieu_5", "dieu_5"),
        ])

    def test_diem_khoan_nay(self):
        """'điểm a khoản này' in a diem clause should resolve to the parent khoan and dieu."""
        resolver = _build_resolver(
            "diem_a_khoan_1_dieu_5", self.data, self.c2p,
            "Luật", "59/2024/QH15"
        )
        content = "quy định tại điểm b khoản này"
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "diem"), "điểm b")
        self.assertEqual(_extract_ref_info(matches[0], "khoan"), "khoản 1")
        self.assertEqual(_extract_ref_info(matches[0], "dieu"), "Điều 5")
        self.assertEqual(_extract_ref_info(matches[0], "luat"), "Luật 59/2024/QH15")

    def test_range_diem_khoan_nay(self):
        """'từ điểm a đến điểm c khoản này' expansion."""
        resolver = _build_resolver(
            "diem_a_khoan_1_dieu_5", self.data, self.c2p,
            "Luật", "59/2024/QH15"
        )
        content = "từ điểm a đến điểm c khoản này"
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 3) # a, b, c
        self.assertEqual(_extract_ref_info(matches[0], "diem"), "điểm a")
        self.assertEqual(_extract_ref_info(matches[1], "diem"), "điểm b")
        self.assertEqual(_extract_ref_info(matches[2], "diem"), "điểm c")
        for m in matches:
            self.assertEqual(_extract_ref_info(m, "khoan"), "khoản 1")

    def test_standalone_khoan_nay(self):
        """'khoản này' resolves to the current khoan number."""
        resolver = _build_resolver(
            "diem_a_khoan_1_dieu_5", self.data, self.c2p,
            "Luật", "59/2024/QH15"
        )
        content = "theo quy định tại khoản này"
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "khoan"), "khoản 1")
        self.assertEqual(_extract_ref_info(matches[0], "dieu"), "Điều 5")

    def test_standalone_diem_nay(self):
        """'điểm này' resolves to the current diem label and parent khoan."""
        resolver = _build_resolver(
            "diem_a_khoan_1_dieu_5", self.data, self.c2p,
            "Luật", "59/2024/QH15"
        )
        content = "quy định tại điểm này"
        matches = resolver.resolve(content)

        self.assertEqual(len(matches), 1)
        self.assertEqual(_extract_ref_info(matches[0], "diem"), "điểm a")
        self.assertEqual(_extract_ref_info(matches[0], "khoan"), "khoản 1")
        self.assertEqual(_extract_ref_info(matches[0], "dieu"), "Điều 5")


class TestSpecificDieuDocNay(unittest.TestCase):
    """Test patterns like 'Điều 36 của Luật này' and ranges referring to it."""

    def setUp(self):
        # We don't necessarily need the target clauses in data for the resolver to produce references
        self.data = _make_data(("khoan_8_dieu_3", "khoan"))
        self.c2p = {}

    def test_range_khoan_specific_dieu_doc_nay(self):
        """'quy định từ khoản 1 đến khoản 11 Điều 36 của Luật này'."""
        resolver = _build_resolver(
            "khoan_8_dieu_3", self.data, self.c2p,
            "Luật", "59/2024/QH15"
        )
        content = "quy định từ khoản 1 đến khoản 11 Điều 36 của Luật này"
        matches = resolver.resolve(content)

        # Expected: 11 matches (khoản 1 -> 11) all referencing Điều 36
        self.assertEqual(len(matches), 11)
        for i, m in enumerate(matches):
            self.assertEqual(_extract_ref_info(m, "khoan"), f"khoản {i+1}")
            self.assertEqual(_extract_ref_info(m, "dieu"), "Điều 36")
            self.assertEqual(_extract_ref_info(m, "luat"), "Luật 59/2024/QH15")


if __name__ == "__main__":
    unittest.main()
