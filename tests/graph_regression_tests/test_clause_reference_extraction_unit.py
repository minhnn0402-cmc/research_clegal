"""Layer 1: unit tests for extraction/classification primitives."""

from __future__ import annotations

import logging
import sys
import types
import unittest
from collections import Counter
from unittest.mock import patch

from src.domain.extractors.base_extractor import BaseExtractor
from src.domain.extractors.internal_reference_resolver import InternalReferenceResolver
from src.domain.extractors.relations_extractor import RelationsExtractor

from tests.graph_regression_tests.helpers import (
    CLAUSE_TYPES,
    DOC_TYPES,
    active,
    component_signature,
    load_cases,
    make_reference,
    trim_signature,
)


logging.disable(logging.INFO)


def _flatten_relation_results(results):
    flattened = []
    for group in results or []:
        for relation_group in group.get("relations", []):
            for tail in relation_group.get("tail", []):
                flattened.append(
                    {
                        "clause_key": group.get("clause_key"),
                        "relation": relation_group.get("relation"),
                        "tail": tail,
                    }
                )
    return flattened


class TestUnitExtractionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()
        cls.extractor = BaseExtractor(doc_clause_types=DOC_TYPES)

    def test_reference_components_preserve_vietnamese_point_labels(self) -> None:
        """EC-01/EC-02: điểm d, điểm đ and điểm d1 must remain distinct."""
        for case in active(self.cases["reference_component_cases"]):
            with self.subTest(case_id=case["id"]):
                references = self.extractor.extract_references(
                    content=case["content"],
                    doc_types=DOC_TYPES,
                    clause_types=CLAUSE_TYPES,
                    law_titles=[],
                    clause_type="dieu",
                    clause_key="dieu_1",
                    data=[],
                    child_to_parent={},
                    cls_title="",
                )

                actual = [trim_signature(component_signature(ref)) for ref in references]

                for expected in case["expected_references"]:
                    self.assertIn(
                        expected,
                        actual,
                        f"{case['id']} missing expected reference {expected}. Actual: {actual}",
                    )

                for negative_case in case.get("negative_references", []):
                    negative = dict(negative_case)
                    reason = negative.pop("reason", "")
                    expected_positive_count = case["expected_references"].count(negative)
                    actual_count = actual.count(negative)
                    self.assertEqual(
                        actual_count,
                        expected_positive_count,
                        f"{case['id']} produced forbidden duplicate/reference {negative}. {reason}",
                    )

    def test_internal_reference_range_preserves_d_stroke_order(self) -> None:
        """EC-03: ranges from điểm d to điểm e include điểm đ in Vietnamese order."""
        for case in active(self.cases["internal_reference_cases"]):
            with self.subTest(case_id=case["id"]):
                data = [
                    {
                        "com_key": clause["com_key"],
                        "com_type": clause["com_type"],
                        "com_title": clause["com_key"],
                    }
                    for clause in case["clauses"]
                ]
                resolver = InternalReferenceResolver(
                    clause_key=case["clause_key"],
                    child_to_parent=case["child_to_parent"],
                    data=data,
                    cls_document_type=case["cls_document_type"],
                    cls_so_hieu=case["cls_so_hieu"],
                )

                matches = resolver.resolve(case["content"])
                if "expected_diem_sequence" in case:
                    actual_diems = [
                        match["reference"]["diem"]["information"]
                        for match in matches
                        if "diem" in match.get("reference", {})
                    ]
                    self.assertEqual(actual_diems, case["expected_diem_sequence"])

                if "expected_reference_signatures" in case:
                    actual = [
                        trim_signature(component_signature(match["reference"]))
                        for match in matches
                    ]
                    for expected in case["expected_reference_signatures"]:
                        self.assertIn(
                            expected,
                            actual,
                            f"{case['id']} missing expected internal reference {expected}. Actual: {actual}",
                        )

    def test_internal_reference_mixed_khoan_and_diem_keeps_explicit_parent_khoan(self) -> None:
        """Mixed refs like 'khoan 1, diem a khoan 2 Dieu 3' keep explicit khoan targets."""
        content = (
            "Nội dung văn bản thông báo thực hiện theo hướng dẫn tại khoản 1, "
            "điểm a khoản 2 Điều 3 của Thông tư liên tịch này."
        )
        data = [
            {"com_key": "dieu_3", "com_type": "dieu", "com_title": "Dieu 3"},
            {"com_key": "khoan_1_dieu_3", "com_type": "khoan", "com_title": "khoan 1"},
            {"com_key": "khoan_2_dieu_3", "com_type": "khoan", "com_title": "khoan 2"},
            {
                "com_key": "diem_a_khoan_2_dieu_3",
                "com_type": "diem",
                "com_title": "diem a",
            },
            {"com_key": "khoan_2_dieu_11", "com_type": "khoan", "com_title": "khoan 2"},
        ]
        resolver = InternalReferenceResolver(
            clause_key="khoan_2_dieu_11",
            child_to_parent={
                "khoan_1_dieu_3": "dieu_3",
                "khoan_2_dieu_3": "dieu_3",
                "diem_a_khoan_2_dieu_3": "khoan_2_dieu_3",
                "khoan_2_dieu_11": "dieu_11",
            },
            data=data,
            cls_document_type="Thông tư liên tịch",
            cls_so_hieu="03/2012/TTLT-VKSNDTC-TANDTC",
        )

        actual = {
            (
                match["reference"].get("diem", {}).get("information"),
                match["reference"].get("khoan", {}).get("information"),
                match["reference"].get("dieu", {}).get("information"),
            )
            for match in resolver.resolve(content)
        }

        self.assertIn((None, "khoản 1", "Điều 3"), actual)
        self.assertIn((None, "khoản 2", "Điều 3"), actual)
        self.assertIn(("điểm a", "khoản 2", "Điều 3"), actual)

    def test_relation_type_classification_regressions(self) -> None:
        """Phrase-level amendments should be SĐBS, and descriptive words should not create false relations."""
        for case in active(self.cases["relation_type_cases"]):
            with self.subTest(case_id=case["id"]):
                reference = make_reference(
                    content=case["content"],
                    reference_text=case["reference_text"],
                    reference_key=case["reference_key"],
                )
                relation_types = self.extractor.extract_relation_types(
                    content=case["content"],
                    references=[reference],
                    clause_type="dieu",
                )
                actual_relations = [item["relation_type"] for item in relation_types]

                expected = case.get("expected_relation")
                if expected is not None:
                    self.assertIn(expected, actual_relations)
                else:
                    self.assertEqual(
                        actual_relations,
                        [],
                        f"{case['id']} should not create any legal relation from descriptive text.",
                    )

                for forbidden in case.get("forbidden_relations", []):
                    self.assertNotIn(
                        forbidden,
                        actual_relations,
                        f"{case['id']} produced forbidden relation {forbidden}",
                    )

    def test_promoted_manual_relation_extraction_cases(self) -> None:
        """Former manual/golden risks now have executable mocked extraction contracts."""
        for case in active(self.cases.get("relation_extraction_cases", [])):
            with self.subTest(case_id=case["id"]):
                extractor = RelationsExtractor(
                    doc_clause_types={
                        "doc_types": DOC_TYPES,
                        "clause_types": CLAUSE_TYPES,
                    },
                    law_titles_for_regex=case.get("law_titles", []),
                )

                def run_extraction():
                    return extractor.extract_relations(
                        data=case["data"],
                        cls_so_hieu=case["cls_so_hieu"],
                        cls_title=case.get("cls_title", ""),
                        cls_document_type=case.get("cls_document_type", ""),
                        use_llm=case.get("use_llm", False),
                    )

                if "llm_targets" in case:
                    fake_module = types.ModuleType("src.domain.llms.relation_fallback")

                    class FakeLangExtractRelationFallback:
                        def __init__(self, *args, **kwargs):
                            pass

                        def extract_relation_targets(self, *args, **kwargs):
                            return case["llm_targets"]

                    fake_module.LangExtractRelationFallback = FakeLangExtractRelationFallback
                    with patch.dict(
                        sys.modules,
                        {"src.domain.llms.relation_fallback": fake_module},
                    ):
                        results = run_extraction()
                else:
                    results = run_extraction()

                flattened = _flatten_relation_results(results)
                actual_counts = Counter(item["relation"] for item in flattened)
                expected_counts = Counter(case.get("expected_relation_counts", {}))

                for relation, expected_count in expected_counts.items():
                    self.assertEqual(
                        actual_counts[relation],
                        expected_count,
                        f"{case['id']} expected {expected_count} {relation} relation(s), got {actual_counts}",
                    )

                if not expected_counts:
                    self.assertEqual(
                        dict(actual_counts),
                        {},
                        f"{case['id']} should not produce relations, got {flattened}",
                    )

                for forbidden in case.get("forbidden_relations", []):
                    self.assertNotIn(
                        forbidden,
                        actual_counts,
                        f"{case['id']} produced forbidden relation {forbidden}: {flattened}",
                    )

                tail_texts = [str(item["tail"]) for item in flattened]
                for expected_text in case.get("expected_tail_contains", []):
                    self.assertTrue(
                        any(expected_text in tail_text for tail_text in tail_texts),
                        f"{case['id']} missing target containing {expected_text}. Actual tails: {tail_texts}",
                    )


if __name__ == "__main__":
    unittest.main()
