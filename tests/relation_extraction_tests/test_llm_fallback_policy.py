import os
import sys
import types
import unittest
from unittest.mock import patch

from src.domain.extractors.base_extractor import BaseExtractor
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.domain.llms.relation_fallback import LangExtractRelationFallback


class _DummyExtraction:
    def __init__(self, extraction_text: str, attributes: dict):
        self.extraction_text = extraction_text
        self.attributes = attributes
        self.char_interval = None


class _DummyAnnotatedDocument:
    def __init__(self, extractions: list):
        self.extractions = extractions


def _doc_ref(key: str, information: str) -> dict:
    return {
        key: {
            "information": information,
            "position_start": 0,
            "position_end": len(information),
        }
    }


class _RuleExtractorWithGap:
    RELATION_PRIORITY = BaseExtractor.RELATION_PRIORITY

    def __init__(self):
        self.references = [
            _doc_ref("luat", "Luat A"),
            _doc_ref("nghidinh", "Nghi dinh B"),
            _doc_ref("thongtu", "Thong tu C"),
        ]

    def extract_references(self, **_kwargs):
        return self.references

    def extract_relation_types(self, **_kwargs):
        return [{"relation_type": "sua_doi_bo_sung"}]

    def match_relations(self, **_kwargs):
        return [
            {
                "relation_type": "sua_doi_bo_sung",
                "reference": self.references[0],
            }
        ]


class _RuleExtractorWithAmbiguousTypes:
    RELATION_PRIORITY = BaseExtractor.RELATION_PRIORITY

    def __init__(self):
        self.calls = 0
        self.reference = _doc_ref("luat", "Luat A")

    def extract_references(self, **_kwargs):
        return [self.reference]

    def extract_relation_types(self, **_kwargs):
        return [
            {"relation_type": "dan_chieu"},
            {"relation_type": "sua_doi_bo_sung"},
        ]

    def match_relations(self, **_kwargs):
        return [
            {
                "relation_type": "sua_doi_bo_sung",
                "reference": self.reference,
            }
        ]


class TestLlmFallbackPolicy(unittest.TestCase):
    def test_relation_fallback_derives_vietnamese_reference_payload(self) -> None:
        content = "Sửa đổi điểm đ khoản 2 Điều 5 Luật Đất đai."
        target = "điểm đ khoản 2 Điều 5 Luật Đất đai"
        fallback = LangExtractRelationFallback(model_id="cmc-legal")

        with patch.object(fallback, "_get_from_cache", return_value=None), patch.object(
            fallback,
            "_save_to_cache",
        ), patch.object(
            fallback,
            "_run_langextract",
            return_value=_DummyAnnotatedDocument(
                [
                    _DummyExtraction(
                        extraction_text="điểm đ khoản 2 Điều 5",
                        attributes={
                            "type": "sua_doi_bo_sung",
                            "target": target,
                            "evidence": content,
                        },
                    )
                ]
            ),
        ):
            result = fallback.extract_relation_targets(content, clause_content=content)

        self.assertEqual(len(result), 1)
        reference = result[0]["reference"]
        self.assertEqual(reference["luat"]["information"], "Luật Đất đai")
        self.assertEqual(reference["dieu"]["information"], "Điều 5")
        self.assertEqual(reference["khoan"]["information"], "khoản 2")
        self.assertEqual(reference["diem"]["information"], "điểm đ")
        self.assertEqual(reference["diem"]["position_start"], content.index("điểm đ"))
        self.assertEqual(reference["luat"]["position_start"], content.index("Luật Đất đai"))

    def test_evaluate_llm_trigger_covers_refactor_conditions(self) -> None:
        extractor = RelationsExtractor()
        complete_match = {
            "relation_type": "dan_chieu",
            "reference": _doc_ref("luat", "Luat A"),
        }
        incomplete_match = {
            "relation_type": "dan_chieu",
            "reference": {"dieu": {"information": "Dieu 5"}},
        }

        self.assertTrue(
            extractor._evaluate_llm_trigger(
                relation_types=[{"relation_type": "sua_doi_bo_sung"}],
                relation_matches=[],
                references=[_doc_ref("luat", "Luat A")],
            )
        )
        self.assertTrue(
            extractor._evaluate_llm_trigger(
                relation_types=[{"relation_type": "sua_doi_bo_sung"}],
                relation_matches=[complete_match],
                references=[
                    _doc_ref("luat", "Luat A"),
                    _doc_ref("nghidinh", "Nghi dinh B"),
                    _doc_ref("thongtu", "Thong tu C"),
                ],
            )
        )
        self.assertTrue(
            extractor._evaluate_llm_trigger(
                relation_types=[
                    {"relation_type": "quy_dinh_chi_tiet"},
                    {"relation_type": "huong_dan"},
                ],
                relation_matches=[complete_match],
                references=[_doc_ref("luat", "Luat A")],
            )
        )
        self.assertTrue(
            extractor._evaluate_llm_trigger(
                relation_types=[
                    {"relation_type": "dan_chieu"},
                    {"relation_type": "sua_doi_bo_sung"},
                ],
                relation_matches=[complete_match],
                references=[_doc_ref("luat", "Luat A")],
            )
        )
        self.assertTrue(
            extractor._evaluate_llm_trigger(
                relation_types=[{"relation_type": "dan_chieu"}],
                relation_matches=[incomplete_match],
                references=[{"dieu": {"information": "Dieu 5"}}],
            )
        )
        self.assertFalse(
            extractor._evaluate_llm_trigger(
                relation_types=[{"relation_type": "dan_chieu"}],
                relation_matches=[complete_match],
                references=[_doc_ref("luat", "Luat A")],
            )
        )

    def test_llm_gap_trigger_appends_targets_without_dropping_rule_matches(self) -> None:
        extractor = RelationsExtractor()
        extractor.base_extractor = _RuleExtractorWithGap()

        fake_module = types.ModuleType("src.domain.llms.relation_fallback")

        class FakeLangExtractRelationFallback:
            def __init__(self, *args, **kwargs):
                pass

            def extract_relation_targets(self, *args, **kwargs):
                return [
                    {
                        "relation_type": "sua_doi_bo_sung",
                        "reference": _doc_ref("nghidinh", "Nghi dinh B"),
                    }
                ]

        fake_module.LangExtractRelationFallback = FakeLangExtractRelationFallback
        with patch.dict(sys.modules, {"src.domain.llms.relation_fallback": fake_module}):
            result = extractor._extract_generic_relations(
                clause_type="dieu",
                clause_key="dieu_1",
                content="Sua doi Luat A, Nghi dinh B va Thong tu C.",
                law_titles=[],
                cls_so_hieu="99/2025/QH15",
                cls_title="",
                cls_document_type="Luat",
                use_llm=True,
                data=[],
                child_to_parent={},
                clause_index_by_key={},
            )

        tails = result[0]["relations"][0]["tail"]
        tail_infos = {next(iter(tail.values()))["information"] for tail in tails}

        self.assertEqual(len(tails), 2)
        self.assertEqual(tail_infos, {"Luat A", "Nghi dinh B"})

    def test_ambiguous_type_trigger_invokes_llm_but_priority_keeps_rule_match(self) -> None:
        extractor = RelationsExtractor()
        fake_rule_extractor = _RuleExtractorWithAmbiguousTypes()
        extractor.base_extractor = fake_rule_extractor

        fake_module = types.ModuleType("src.domain.llms.relation_fallback")
        calls = {"count": 0}

        class FakeLangExtractRelationFallback:
            def __init__(self, *args, **kwargs):
                pass

            def extract_relation_targets(self, *args, **kwargs):
                calls["count"] += 1
                return [
                    {
                        "relation_type": "huong_dan",
                        "reference": fake_rule_extractor.reference,
                    }
                ]

        fake_module.LangExtractRelationFallback = FakeLangExtractRelationFallback
        with patch.dict(sys.modules, {"src.domain.llms.relation_fallback": fake_module}):
            result = extractor._extract_generic_relations(
                clause_type="dieu",
                clause_key="dieu_1",
                content="Sua doi, dan chieu Luat A.",
                law_titles=[],
                cls_so_hieu="99/2025/QH15",
                cls_title="",
                cls_document_type="Luat",
                use_llm=True,
                data=[],
                child_to_parent={},
                clause_index_by_key={},
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(result[0]["relations"][0]["relation"], "sua_doi_bo_sung")
        self.assertEqual(len(result[0]["relations"]), 1)


class TestLlmFallbackConfig(unittest.TestCase):
    def test_relation_fallback_reads_environment_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LEGAL_LLM_MODEL_ID": "legal-model-from-env",
                "LEGAL_LLM_BASE_URL": "http://llm.internal/v1",
                "LEGAL_LLM_API_KEY": "env-api-key",
            },
        ):
            fallback = LangExtractRelationFallback()

        self.assertEqual(fallback.model_id, "legal-model-from-env")
        self.assertEqual(fallback.base_url, "http://llm.internal/v1")
        self.assertEqual(fallback.api_key, "env-api-key")


if __name__ == "__main__":
    unittest.main()
