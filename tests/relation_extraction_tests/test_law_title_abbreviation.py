"""Unit tests for law title abbreviation normalization.

Tests the build_law_title_abbreviation_map and normalize_law_title_abbreviation
helpers that expand abbreviated Luật/Bộ luật titles (e.g. "luật tthc") to their
full official forms before document ID lookup.
"""

import unittest

import pandas as pd

from src.search.search_reference_doc import (
    _law_title_abbrev_map_cache,
    build_law_title_abbreviation_map,
    normalize_law_title_abbreviation,
)


def _make_law_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"])


SAMPLE_LAW_DF = _make_law_df([
    {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật tố tụng hành chính", "nam_ban_hanh": 2015},
    {"doc_id": 2, "so_hieu": "không số", "loai_van_ban": "boluat", "tieu_de": "bộ luật dân sự", "nam_ban_hanh": 2015},
    {"doc_id": 3, "so_hieu": "không số", "loai_van_ban": "boluat", "tieu_de": "bộ luật tố tụng hình sự", "nam_ban_hanh": 2015},
    {"doc_id": 4, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật xử lý vi phạm hành chính", "nam_ban_hanh": 2012},
    {"doc_id": 5, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật doanh nghiệp", "nam_ban_hanh": 2020},
])


class TestBuildLawTitleAbbreviationMap(unittest.TestCase):

    def test_luat_prefix_keys_use_accent_stripped_prefix(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertIn("luat tthc", abbrev_map)

    def test_boluat_prefix_keys_preserve_space(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertIn("bo luat ds", abbrev_map)
        self.assertIn("bo luat tths", abbrev_map)

    def test_luat_tthc_maps_to_full_title(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertEqual(abbrev_map["luat tthc"], "luật tố tụng hành chính")

    def test_bo_luat_ds_maps_to_full_title(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertEqual(abbrev_map["bo luat ds"], "bộ luật dân sự")

    def test_bo_luat_tths_maps_to_full_title(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertEqual(abbrev_map["bo luat tths"], "bộ luật tố tụng hình sự")

    def test_luat_xlvphc_maps_to_full_title(self):
        abbrev_map = build_law_title_abbreviation_map(SAMPLE_LAW_DF)
        self.assertEqual(abbrev_map["luat xlvphc"], "luật xử lý vi phạm hành chính")

    def test_ambiguous_abbreviation_maps_to_none(self):
        # Two luật entries that produce the same abbreviation "luật ab"
        df = _make_law_df([
            {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật an bình", "nam_ban_hanh": 2010},
            {"doc_id": 2, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật ấn bản", "nam_ban_hanh": 2012},
        ])
        abbrev_map = build_law_title_abbreviation_map(df)
        # Both produce "luat ab" — must be marked as ambiguous (None)
        self.assertIn("luat ab", abbrev_map)
        self.assertIsNone(abbrev_map["luat ab"])

    def test_non_luat_boluat_types_excluded(self):
        df = _make_law_df([
            {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "nghi_dinh", "tieu_de": "nghị định về doanh nghiệp", "nam_ban_hanh": 2020},
        ])
        abbrev_map = build_law_title_abbreviation_map(df)
        self.assertEqual(len(abbrev_map), 0)

    def test_cache_does_not_reuse_stale_map_for_different_dataframe(self):
        df = _make_law_df([
            {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "nghi_dinh", "tieu_de": "nghị định về doanh nghiệp", "nam_ban_hanh": 2020},
        ])
        cache_key = id(df)
        original_cache_entry = _law_title_abbrev_map_cache.get(cache_key)
        _law_title_abbrev_map_cache[cache_key] = {"luat stale": "luật stale"}
        try:
            abbrev_map = build_law_title_abbreviation_map(df)
        finally:
            if original_cache_entry is None:
                _law_title_abbrev_map_cache.pop(cache_key, None)
            else:
                _law_title_abbrev_map_cache[cache_key] = original_cache_entry

        self.assertEqual(abbrev_map, {})


class TestNormalizeLawTitleAbbreviation(unittest.TestCase):

    def test_luat_tthc_normalized_to_full_title(self):
        result = normalize_law_title_abbreviation("luật tthc", SAMPLE_LAW_DF)
        self.assertEqual(result, "luật tố tụng hành chính")

    def test_bo_luat_ds_normalized_to_full_title(self):
        result = normalize_law_title_abbreviation("bộ luật ds", SAMPLE_LAW_DF)
        self.assertEqual(result, "bộ luật dân sự")

    def test_bo_luat_tths_normalized_to_full_title(self):
        result = normalize_law_title_abbreviation("bộ luật tths", SAMPLE_LAW_DF)
        self.assertEqual(result, "bộ luật tố tụng hình sự")

    def test_luat_xlvphc_normalized_to_full_title(self):
        result = normalize_law_title_abbreviation("luật xlvphc", SAMPLE_LAW_DF)
        self.assertEqual(result, "luật xử lý vi phạm hành chính")

    def test_full_title_unchanged(self):
        result = normalize_law_title_abbreviation("luật tố tụng hành chính", SAMPLE_LAW_DF)
        self.assertEqual(result, "luật tố tụng hành chính")

    def test_unknown_abbreviation_unchanged(self):
        result = normalize_law_title_abbreviation("luật abc123", SAMPLE_LAW_DF)
        self.assertEqual(result, "luật abc123")

    def test_ambiguous_abbreviation_returns_original(self):
        df = _make_law_df([
            {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật an bình", "nam_ban_hanh": 2010},
            {"doc_id": 2, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật ấn bản", "nam_ban_hanh": 2012},
        ])
        result = normalize_law_title_abbreviation("luật ab", df)
        # Must not silently pick one; must return original
        self.assertEqual(result, "luật ab")

    def test_empty_string_returns_empty(self):
        result = normalize_law_title_abbreviation("", SAMPLE_LAW_DF)
        self.assertEqual(result, "")

    def test_non_luat_prefix_unchanged(self):
        result = normalize_law_title_abbreviation("nghị định nd", SAMPLE_LAW_DF)
        self.assertEqual(result, "nghị định nd")

    def test_case_insensitive_matching(self):
        result = normalize_law_title_abbreviation("Luật TTHC", SAMPLE_LAW_DF)
        self.assertEqual(result, "luật tố tụng hành chính")

    def test_abbreviation_with_trailing_clause_context(self):
        # _fallback_law_title is greedy and captures the full tail; the normalizer
        # must still resolve the abbreviation prefix and discard the trailing context.
        result = normalize_law_title_abbreviation(
            "luật tthc để mở phiên tòa theo quy định tại khoản 3 điều 117",
            SAMPLE_LAW_DF,
        )
        self.assertEqual(result, "luật tố tụng hành chính")

    def test_bo_luat_abbreviation_with_trailing_clause_context(self):
        result = normalize_law_title_abbreviation(
            "bộ luật ds theo quy định tại điều 15",
            SAMPLE_LAW_DF,
        )
        self.assertEqual(result, "bộ luật dân sự")

    def test_abbreviation_with_comma_separator(self):
        # "Luật TTHC, Viện kiểm sát..." — comma immediately after the abbreviation
        result = normalize_law_title_abbreviation(
            "luật tthc, viện kiểm sát phải trả lại hồ sơ vụ án",
            SAMPLE_LAW_DF,
        )
        self.assertEqual(result, "luật tố tụng hành chính")

    def test_ambiguous_prefix_returns_original(self):
        df = _make_law_df([
            {"doc_id": 1, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật an bình", "nam_ban_hanh": 2010},
            {"doc_id": 2, "so_hieu": "không số", "loai_van_ban": "luat", "tieu_de": "luật ấn bản", "nam_ban_hanh": 2012},
        ])
        result = normalize_law_title_abbreviation(
            "luật ab để mở phiên tòa theo quy định",
            df,
        )
        self.assertEqual(result, "luật ab để mở phiên tòa theo quy định")


if __name__ == "__main__":
    unittest.main()
