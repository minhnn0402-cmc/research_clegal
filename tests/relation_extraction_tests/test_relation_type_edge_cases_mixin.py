import unittest


class TestRelationTypeEdgeCasesMixin(unittest.TestCase):
    """Structural tests: RelationTypeEdgeCases mixin exists and exposes all expected helpers."""

    def test_module_importable(self):
        from src.domain.extractors.base_extractor_flow.relation_type_edge_cases import (  # noqa: F401
            RelationTypeEdgeCases,
        )

    def test_all_helper_methods_present(self):
        from src.domain.extractors.base_extractor_flow.relation_type_edge_cases import (
            RelationTypeEdgeCases,
        )
        expected_methods = [
            "_has_parent_appendix_amendment_context",
            "_is_document_title_descriptive_dan_chieu",
            "_is_post_action_assignment_basis",
            "_is_inside_amendment_replacement_quote",
            "_edge_case_points_to_following_list",
            "_is_indirect_keo_dai_basis_reference",
            "_is_indirect_action_basis_reference",
            "_is_post_amendment_intro_bai_bo_continuation",
            "_is_operational_action_relation",
            "_should_skip_descriptive_dan_chieu",
            "_should_promote_dan_chieu_to_detail_from_parent",
            "_filter_conflict_or_redundant_relation_types",
            "_forward_relation_points_to_following_list",
            "_forward_relation_points_to_semicolon_target_list",
            "_extract_doc_references_without_filtering",
        ]
        for method_name in expected_methods:
            self.assertTrue(
                hasattr(RelationTypeEdgeCases, method_name),
                f"RelationTypeEdgeCases is missing method: {method_name}",
            )

    def test_shared_patterns_exported(self):
        """Shared patterns must be importable from edge_cases for extraction.py to use."""
        from src.domain.extractors.base_extractor_flow.relation_type_edge_cases import (
            _DAN_CHIEU_PHRASE_AMENDMENT_SCOPE_PATTERN,
            _AMENDMENT_REPLACEMENT_DETAIL_PREFIX_PATTERN,
            _CHILD_SCOPE_QUY_DINH_VE_PATTERN,
            _THEO_QUY_DINH_TAI_CLAUSE_PATTERN,
            _THEO_QUY_DINH_TAI_MARKER_PATTERN,
            _DAN_CHIEU_BACKWARD_EFFECTIVE_CUE_PATTERN,
            _POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES,
        )
        self.assertIsInstance(_POST_INTRO_DOCUMENT_ACTION_RELATION_TYPES, (set, frozenset))

    def test_relation_type_extraction_still_has_main_method(self):
        from src.domain.extractors.base_extractor_flow.relation_type_extraction import (
            RelationTypeExtraction,
        )
        self.assertTrue(hasattr(RelationTypeExtraction, "extract_relation_types"))

    def test_base_extractor_mro_includes_edge_cases(self):
        from src.domain.extractors.base_extractor import BaseExtractor
        from src.domain.extractors.base_extractor_flow.relation_type_edge_cases import (
            RelationTypeEdgeCases,
        )
        self.assertIn(RelationTypeEdgeCases, BaseExtractor.__mro__)


if __name__ == "__main__":
    unittest.main()
