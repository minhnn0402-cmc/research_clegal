"""Layer 2: resolver tests for ES and law dataframe target matching."""

from __future__ import annotations

import logging
import unittest

import pandas as pd

from src.search.search_reference_doc import search_reference_doc
from src.search.search_reference_in_es import search_reference_in_es
from src.shared.validation.filters import filter_law_dataframe
from src.utils.relation_utils import should_keep_failed_reference

from tests.graph_regression_tests.helpers import FakeElasticsearch, active, load_cases


logging.disable(logging.INFO)


class NumberQueryOnlyElasticsearch(FakeElasticsearch):
    """Return hits only when the resolver issues a so_hieu.keyword query."""

    def search(self, index, body):
        self.last_index = index
        self.last_body = body
        if "so_hieu.keyword" not in str(body):
            return {"hits": {"hits": []}}
        return {"hits": {"hits": self.hits}}


class SizeRespectingElasticsearch(FakeElasticsearch):
    """Mirror ES size truncation so candidate-window regressions are visible."""

    def search(self, index, body):
        self.last_index = index
        self.last_body = body
        size = int(body.get("size", len(self.hits)))
        return {"hits": {"hits": self.hits[:size]}}


class TitleOperatorAwareElasticsearch(FakeElasticsearch):
    """Return title hits only when the query does not require every title token."""

    def search(self, index, body):
        self.last_index = index
        self.last_body = body
        body_text = str(body)
        if "'operator': 'or'" not in body_text and '"operator": "or"' not in body_text:
            return {"hits": {"hits": []}}
        return {"hits": {"hits": self.hits}}


class LawFamilyTypeAwareElasticsearch(FakeElasticsearch):
    """Return hits only when title lookup includes both Luật and Bộ luật family types."""

    def search(self, index, body):
        self.last_index = index
        self.last_body = body
        body_text = str(body)
        if "Bộ luật" not in body_text:
            return {"hits": {"hits": []}}
        return {"hits": {"hits": self.hits}}


class TestResolverRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()

    def test_reference_doc_lookup_preserves_decimal_document_number(self) -> None:
        """A dotted document number like 66.13/2026/NQ-CP must reach ES intact."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 6613,
                        "so_hieu": "66.13/2026/NQ-CP",
                        "loai_van_ban": "Nghị quyết",
                        "co_quan_ban_hanh": "Chính phủ",
                        "ngay_ban_hanh": "2026-01-27T00:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "nghiquyet",
                "information": "Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(),
            cls_nam_ban_hanh=2026,
            cls_co_quan_ban_hanh="Chính phủ",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 6613)
        self.assertEqual(extracted_information, "66.13/2026/nq-cp")
        self.assertIn("66.13/2026/nq-cp", str(fake_es.last_body).lower())

    def test_law_title_lookup_falls_back_to_es_date_when_dataframe_is_ambiguous(self) -> None:
        """Law title-only refs need ES date fallback when law_docs.csv has same-title same-year rows."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 999999999649675,
                        "so_hieu": "72/2025/QH15",
                        "loai_van_ban": "Luật",
                        "title": "Luật 72/2025/QH15 tổ chức chính quyền địa phương 2025",
                        "ngay_ban_hanh": "2025-06-16T00:00:00Z",
                    },
                },
                {
                    "_score": 25,
                    "_source": {
                        "ID": 175363,
                        "so_hieu": "65/2025/QH15",
                        "loai_van_ban": "Luật",
                        "title": "Luật 65/2025/QH15 tổ chức chính quyền địa phương số 65/2025/QH15 mới nhất",
                        "ngay_ban_hanh": "2025-02-19T00:00:00Z",
                    },
                },
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật Tổ chức chính quyền địa phương ngày 19 tháng 02 năm 2025",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                columns=["doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"]
            ),
            cls_nam_ban_hanh=2025,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 175363)
        self.assertEqual(extracted_information, "luật tổ chức chính quyền địa phương")
        self.assertIn("title", str(fake_es.last_body))

    def test_law_title_date_prefers_single_numbered_duplicate_over_khong_so(self) -> None:
        """Legacy laws may have both a Không số row and one numbered duplicate for the same date."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 9413,
                        "so_hieu": "Không số",
                        "loai_van_ban": "Luật",
                        "title": "Luật Không số khoáng sản",
                        "ngay_ban_hanh": "1996-03-20T17:00:00Z",
                    },
                },
                {
                    "_score": 30,
                    "_source": {
                        "ID": 99999999939624,
                        "so_hieu": "47-L/CTN",
                        "loai_van_ban": "Luật",
                        "title": "Luật 47-L/CTN khoáng sản",
                        "ngay_ban_hanh": "1996-03-20T00:00:00Z",
                    },
                },
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật Khoáng sản ngày 20 tháng 3 năm 1996",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                columns=["doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"]
            ),
            cls_nam_ban_hanh=2025,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 99999999939624)
        self.assertEqual(extracted_information, "luật khoáng sản")

    def test_law_title_date_query_allows_extra_generic_title_tokens(self) -> None:
        """Title+date lookup should tolerate extra descriptors such as 'các cấp'."""
        fake_es = TitleOperatorAwareElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 20068,
                        "so_hieu": "26/2003/QH11",
                        "loai_van_ban": "Luật",
                        "title": "Luật tổ chức Hội đồng nhân dân và Ủy ban nhân dân",
                        "ngay_ban_hanh": "2003-11-26T00:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật Tổ chức HĐND và UBND các cấp ngày 26/11/2003",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                columns=["doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"]
            ),
            cls_nam_ban_hanh=2025,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 20068)
        self.assertEqual(extracted_information, "luật tổ chức hđnd và ubnd các cấp")

    def test_law_title_date_query_searches_law_and_code_family_types(self) -> None:
        """Title+date refs may say Luật while the canonical document type is Bộ luật."""
        fake_es = LawFamilyTypeAwareElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 99999999938702,
                        "so_hieu": "35-L/CTN",
                        "loai_van_ban": "Bộ luật",
                        "title": "Bộ luật 35-L/CTN lao động 1994",
                        "ngay_ban_hanh": "1994-06-23T00:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật Lao động ngày 23 tháng 6 năm 1994",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                columns=["doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"]
            ),
            cls_nam_ban_hanh=2025,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 99999999938702)
        self.assertEqual(extracted_information, "luật lao động")

    def test_law_title_lookup_expands_common_abbreviations(self) -> None:
        """Title refs may abbreviate HĐND/UBND while canonical titles are expanded."""
        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật Tổ chức HĐND và UBND ngày 26 tháng 11 năm 2003",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                [
                    {
                        "doc_id": 20068,
                        "so_hieu": "11/2003/qh11",
                        "loai_van_ban": "luat",
                        "tieu_de": "luật tổ chức hội đồng nhân dân và uỷ ban nhân dân",
                        "nam_ban_hanh": 2003,
                    }
                ]
            ),
            cls_nam_ban_hanh=2003,
            cls_co_quan_ban_hanh="",
            es_client=FakeElasticsearch([]),
        )

        self.assertEqual(doc_id, 20068)
        self.assertEqual(extracted_information, "luật tổ chức hđnd và ubnd")

    def test_law_title_abbreviation_is_not_fuzzy_matched_to_unrelated_short_law(self) -> None:
        """Short law abbreviations must resolve through abbreviation mapping, not fuzzy title match."""
        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "type": "luat",
                "information": "Luật TTHC",
            },
            law_titles_for_regex=[
                "luật dược",
                "luật tố tụng hành chính",
            ],
            law_dataframe=pd.DataFrame(
                [
                    {
                        "doc_id": 18127,
                        "so_hieu": "34/2005/qh11",
                        "loai_van_ban": "luat",
                        "tieu_de": "luật dược",
                        "nam_ban_hanh": 2005,
                    },
                    {
                        "doc_id": 26351,
                        "so_hieu": "64/2010/qh12",
                        "loai_van_ban": "luat",
                        "tieu_de": "luật tố tụng hành chính",
                        "nam_ban_hanh": 2010,
                    },
                ]
            ),
            cls_nam_ban_hanh=2012,
            cls_co_quan_ban_hanh="",
            es_client=FakeElasticsearch([]),
        )

        self.assertEqual(doc_id, 26351)
        self.assertEqual(extracted_information, "luật tố tụng hành chính")

    def test_embedded_law_title_abbreviation_uses_abbreviation_mapping(self) -> None:
        """Embedded abbreviations like 'Luật TTHC trong...' must not fuzzy-match unrelated laws."""
        law_dataframe = pd.DataFrame(
            [
                {
                    "doc_id": 101,
                    "so_hieu": "21/2000/qh10",
                    "loai_van_ban": "luat",
                    "tieu_de": "luật tình trạng khẩn cấp",
                    "nam_ban_hanh": 2000,
                },
                {
                    "doc_id": 102,
                    "so_hieu": "18/2017/qh14",
                    "loai_van_ban": "luat",
                    "tieu_de": "luật thủy sản",
                    "nam_ban_hanh": 2017,
                },
                {
                    "doc_id": 26351,
                    "so_hieu": "64/2010/qh12",
                    "loai_van_ban": "luat",
                    "tieu_de": "luật tố tụng hành chính",
                    "nam_ban_hanh": 2010,
                },
            ]
        )
        law_titles_for_regex = law_dataframe["tieu_de"].tolist()
        cases = [
            (
                "khoản 1 Điều 191 Luật TTHC trong thời hạn 30 ngày",
                26351,
                "luật tố tụng hành chính",
            ),
            (
                "khoản 2 Điều 178 Luật TTHC trong thời hạn 05 ngày làm việc",
                26351,
                "luật tố tụng hành chính",
            ),
            (
                "khoản 2 Điều 109 Luật TTHC phải được thực hiện theo từng vụ án",
                26351,
                "luật tố tụng hành chính",
            ),
        ]

        for information, expected_doc_id, expected_information in cases:
            with self.subTest(information=information):
                doc_id, extracted_information = search_reference_doc(
                    doc_info={
                        "type": "luat",
                        "information": information,
                    },
                    law_titles_for_regex=law_titles_for_regex,
                    law_dataframe=law_dataframe,
                    cls_nam_ban_hanh=2012,
                    cls_co_quan_ban_hanh="",
                    es_client=FakeElasticsearch([]),
                )

                self.assertEqual(doc_id, expected_doc_id)
                self.assertEqual(extracted_information, expected_information)

    def test_es_resolver_exact_suffix_and_ambiguity_policy(self) -> None:
        """EC-04/EC-05: exact số hiệu/suffix/cơ quan must beat wildcard prefix."""
        for case in active(self.cases["es_resolver_cases"]):
            with self.subTest(case_id=case["id"]):
                fake_es = FakeElasticsearch(case["hits"])
                query = case["query"]

                result = search_reference_in_es(
                    so_hieu=query["so_hieu"],
                    loai_van_ban=query["loai_van_ban"],
                    co_quan_ban_hanh=query["co_quan_ban_hanh"],
                    ngay_ban_hanh=query["ngay_ban_hanh"],
                    thang_ban_hanh=query["thang_ban_hanh"],
                    nam_ban_hanh=query["nam_ban_hanh"],
                    cls_nam_ban_hanh=query["cls_nam_ban_hanh"],
                    es_client=fake_es,
                )

                self.assertEqual(result, case["expected_id"])
                self.assertNotIn(result, case.get("negative_ids", []))

    def test_es_resolver_uses_explicit_full_date_with_same_number_same_year(self) -> None:
        """Explicit reference dates must disambiguate same-number local documents."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 2012,
                        "so_hieu": "451/QĐ-UBND",
                        "loai_van_ban": "Quyết định",
                        "co_quan_ban_hanh": "UBND tỉnh Bình Phước",
                        "ngay_ban_hanh": "2012-03-09T00:00:00Z",
                    },
                },
                {
                    "_score": 20,
                    "_source": {
                        "ID": 2025,
                        "so_hieu": "451/QĐ-UBND",
                        "loai_van_ban": "Quyết định",
                        "co_quan_ban_hanh": "UBND tỉnh Bình Phước",
                        "ngay_ban_hanh": "2025-02-28T00:00:00Z",
                    },
                },
            ]
        )

        result = search_reference_in_es(
            so_hieu="451/QĐ-UBND",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="UBND tỉnh Bình Phước",
            ngay_ban_hanh=28,
            thang_ban_hanh=2,
            nam_ban_hanh=2025,
            cls_nam_ban_hanh=2025,
            es_client=fake_es,
        )

        self.assertEqual(result, 2025)

    def test_es_resolver_rejects_prefix_only_when_exact_number_is_missing(self) -> None:
        """A wildcard prefix hit like 866/QĐ-UBND must not satisfy 860/QĐ-UBND."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 866,
                        "so_hieu": "866/QĐ-UBND",
                        "loai_van_ban": "Quyết định",
                        "co_quan_ban_hanh": "UBND tỉnh Bình Phước",
                        "ngay_ban_hanh": "2016-04-15T00:00:00Z",
                    },
                }
            ]
        )

        result = search_reference_in_es(
            so_hieu="860/QĐ-UBND",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="UBND tỉnh Bình Phước",
            ngay_ban_hanh=None,
            thang_ban_hanh=None,
            nam_ban_hanh=None,
            cls_nam_ban_hanh=2025,
            es_client=fake_es,
        )

        self.assertIsNone(result)

    def test_es_resolver_allows_prefix_for_incomplete_document_suffix(self) -> None:
        """Short suffixes like NĐ/QĐ/TTLT are incomplete and may resolve to fuller hits."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 5500,
                        "so_hieu": "55/2005/NĐ-CP",
                        "loai_van_ban": "Nghị định",
                        "co_quan_ban_hanh": "Chính phủ",
                        "ngay_ban_hanh": "2005-01-01T00:00:00Z",
                    },
                }
            ]
        )

        result = search_reference_in_es(
            so_hieu="55/2005/NĐ",
            loai_van_ban="Nghị định",
            co_quan_ban_hanh="Chính phủ",
            ngay_ban_hanh=None,
            thang_ban_hanh=None,
            nam_ban_hanh=None,
            cls_nam_ban_hanh=2005,
            es_client=fake_es,
        )

        self.assertEqual(result, 5500)
        body_text = str(fake_es.last_body)
        self.assertIn("55*", body_text)

    def test_es_query_for_specific_so_hieu_does_not_use_broad_prefix_fallback(self) -> None:
        """CLS-4999: a full QĐ-TTg number must not query with a broad 45* fallback."""
        fake_es = FakeElasticsearch([])

        search_reference_in_es(
            so_hieu="45/QĐ-TTg",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="Thủ tướng Chính phủ",
            ngay_ban_hanh=9,
            thang_ban_hanh=1,
            nam_ban_hanh=2019,
            cls_nam_ban_hanh=2024,
            es_client=fake_es,
        )

        body_text = str(fake_es.last_body)
        self.assertNotIn("45*", body_text)
        self.assertNotIn("'fuzziness': 1", body_text)

    def test_es_query_for_specific_so_hieu_keeps_normalized_exact_variants(self) -> None:
        """CLS-5067: strict suffix search still needs accent-folded exact variants."""
        fake_es = FakeElasticsearch([])

        search_reference_in_es(
            so_hieu="18/2018/NQ-HĐND",
            loai_van_ban="Nghị quyết",
            co_quan_ban_hanh="Hội đồng nhân dân tỉnh Bến Tre",
            ngay_ban_hanh=7,
            thang_ban_hanh=12,
            nam_ban_hanh=2018,
            cls_nam_ban_hanh=2025,
            es_client=fake_es,
        )

        body_text = str(fake_es.last_body)
        self.assertIn("18/2018/NQ-HDND", body_text)
        self.assertNotIn("18*", body_text)
        self.assertNotIn("'fuzziness': 1", body_text)

    def test_es_query_for_specific_so_hieu_includes_canonical_mixed_case_suffix(self) -> None:
        """Lowercase extracted suffixes still need the canonical keyword casing used by ES."""
        fake_es = FakeElasticsearch([])

        search_reference_in_es(
            so_hieu="24/2010/qđ-ttg",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="Thủ tướng Chính phủ",
            ngay_ban_hanh=6,
            thang_ban_hanh=1,
            nam_ban_hanh=2010,
            cls_nam_ban_hanh=2024,
            es_client=fake_es,
        )

        body_text = str(fake_es.last_body)
        self.assertIn("24/2010/QĐ-TTg", body_text)
        self.assertIn("24/2010/QD-TTg", body_text)
        self.assertNotIn("24*", body_text)

    def test_es_query_for_specific_so_hieu_does_not_pre_filter_by_date(self) -> None:
        """Exact full document numbers should use dates only for post-query disambiguation."""
        fake_es = FakeElasticsearch([])

        search_reference_in_es(
            so_hieu="48/2013/NĐ-CP",
            loai_van_ban="Nghị định",
            co_quan_ban_hanh="Chính phủ",
            ngay_ban_hanh=15,
            thang_ban_hanh=5,
            nam_ban_hanh=2013,
            cls_nam_ban_hanh=2024,
            es_client=fake_es,
        )

        must_clauses = fake_es.last_body["query"]["bool"]["must"]
        self.assertNotIn("'range': {'ngay_ban_hanh'", str(must_clauses))

    def test_es_resolver_fetches_enough_exact_local_candidates_for_date_filter(self) -> None:
        """Same-number local documents need a wider exact-candidate window before post-filtering."""
        hits = []
        for day, doc_id in [(22, 154409), (20, 154384), (17, 154315), (15, 155901)]:
            hits.append(
                {
                    "_score": 30,
                    "_source": {
                        "ID": doc_id,
                        "so_hieu": "11/2022/QĐ-UBND",
                        "loai_van_ban": "Quyết định",
                        "co_quan_ban_hanh": "UBND tỉnh",
                        "ngay_ban_hanh": f"2022-06-{day:02d}T00:00:00Z",
                    },
                }
            )
        hits.append(
            {
                "_score": 30,
                "_source": {
                    "ID": 155901,
                    "so_hieu": "11/2022/QĐ-UBND",
                    "loai_van_ban": "Quyết định",
                    "co_quan_ban_hanh": "UBND thành phố Hồ Chí Minh",
                    "ngay_ban_hanh": "2022-04-15T00:00:00Z",
                },
            }
        )
        fake_es = SizeRespectingElasticsearch(hits)

        result = search_reference_in_es(
            so_hieu="11/2022/QĐ-UBND",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="",
            ngay_ban_hanh=15,
            thang_ban_hanh=4,
            nam_ban_hanh=2022,
            cls_nam_ban_hanh=2025,
            es_client=fake_es,
        )

        self.assertEqual(result, 155901)

    def test_es_query_for_incomplete_so_hieu_keeps_prefix_fallback(self) -> None:
        """Incomplete numbers like 45/QĐ still need the older broad fallback behavior."""
        fake_es = FakeElasticsearch([])

        search_reference_in_es(
            so_hieu="45/QĐ",
            loai_van_ban="Quyết định",
            co_quan_ban_hanh="Thủ tướng Chính phủ",
            ngay_ban_hanh=None,
            thang_ban_hanh=None,
            nam_ban_hanh=None,
            cls_nam_ban_hanh=2024,
            es_client=fake_es,
        )

        body_text = str(fake_es.last_body)
        self.assertIn("45*", body_text)
        self.assertIn("'fuzziness': 1", body_text)

    def test_es_resolver_keeps_qd_ttg_suffix_for_cls_4999_examples(self) -> None:
        """CLS-4999: QĐ-TTg references must resolve to QĐ-TTg, not same-number QĐ-UBND."""
        cases = [
            ("45/QĐ-TTg", 9, 1, 2019, 4500, 4501),
            ("2188/QĐ-TTg", 15, 11, 2016, 218800, 218801),
        ]
        for so_hieu, ngay, thang, nam, wrong_id, expected_id in cases:
            with self.subTest(so_hieu=so_hieu):
                fake_es = FakeElasticsearch(
                    [
                        {
                            "_score": 30,
                            "_source": {
                                "ID": wrong_id,
                                "so_hieu": so_hieu.replace("QĐ-TTg", "QĐ-UBND"),
                                "loai_van_ban": "Quyết định",
                                "co_quan_ban_hanh": "Ủy ban nhân dân tỉnh",
                                "ngay_ban_hanh": f"{nam}-{thang:02d}-{ngay:02d}T00:00:00Z",
                            },
                        },
                        {
                            "_score": 20,
                            "_source": {
                                "ID": expected_id,
                                "so_hieu": so_hieu,
                                "loai_van_ban": "Quyết định",
                                "co_quan_ban_hanh": "Thủ tướng Chính phủ",
                                "ngay_ban_hanh": f"{nam}-{thang:02d}-{ngay:02d}T00:00:00Z",
                            },
                        },
                    ]
                )

                result = search_reference_in_es(
                    so_hieu=so_hieu,
                    loai_van_ban="Quyết định",
                    co_quan_ban_hanh="Thủ tướng Chính phủ",
                    ngay_ban_hanh=ngay,
                    thang_ban_hanh=thang,
                    nam_ban_hanh=nam,
                    cls_nam_ban_hanh=2024,
                    es_client=fake_es,
                )

                self.assertEqual(result, expected_id)
                self.assertNotEqual(result, wrong_id)

    def test_es_resolver_allows_full_prefix_for_multi_agency_suffix(self) -> None:
        """Multi-agency suffix refs may omit the final agency expansion like &XH."""
        fake_es = FakeElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 25396,
                        "so_hieu": "03/2010/TTLT-BNV-BTC-BLĐTB&XH",
                        "loai_van_ban": "Thông tư liên tịch",
                        "co_quan_ban_hanh": "Bộ Nội vụ - Bộ Tài chính - Bộ Lao động",
                        "ngay_ban_hanh": "2010-05-27T17:00:00Z",
                    },
                }
            ]
        )

        result = search_reference_in_es(
            so_hieu="03/2010/TTLT-BNV-BTC-BLĐTB",
            loai_van_ban="Thông tư liên tịch",
            co_quan_ban_hanh="",
            ngay_ban_hanh=None,
            thang_ban_hanh=None,
            nam_ban_hanh=None,
            cls_nam_ban_hanh=2025,
            es_client=fake_es,
        )

        self.assertEqual(result, 25396)
        body_text = str(fake_es.last_body)
        self.assertIn("03/2010/TTLT-BNV-BTC-BLĐTB*", body_text)
        self.assertNotIn("03*", body_text)

    def test_law_dataframe_year_resolution_policy(self) -> None:
        """EC-19/EC-20: title-only law references prefer newest valid version unless year is explicit."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 2010,
                    "so_hieu": "56/2010/QH12",
                    "tieu_de": "Luật Thanh tra",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2010,
                },
                {
                    "doc_id": 2025,
                    "so_hieu": "99/2025/QH15",
                    "tieu_de": "Luật Thanh tra",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
            ]
        )

        for case in active(self.cases["law_dataframe_cases"]):
            with self.subTest(case_id=case["id"]):
                result = filter_law_dataframe(
                    so_hieu=case["so_hieu"],
                    tieu_de=case["tieu_de"],
                    loai_van_ban=case["loai_van_ban"],
                    nam=case["nam"],
                    cls_nam_ban_hanh=case["cls_nam_ban_hanh"],
                    law_df=law_df,
                )
                self.assertFalse(result.empty)
                selected = result.copy()
                if case["nam"] is None:
                    selected["nam_ban_hanh_int"] = pd.to_numeric(
                        selected["nam_ban_hanh"],
                        errors="coerce",
                    )
                    selected = selected.sort_values(
                        by="nam_ban_hanh_int",
                        ascending=False,
                )
                self.assertEqual(int(selected.iloc[0]["doc_id"]), case["expected_doc_id"])

    def test_title_only_law_reference_prefers_unique_same_year_version(self) -> None:
        """CLS-5020: title-only references may point to a unique law issued in the same year."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 2013,
                    "so_hieu": "38/2013/QH13",
                    "tieu_de": "Luật Việc làm",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2013,
                },
                {
                    "doc_id": 2025,
                    "so_hieu": "74/2025/QH15",
                    "tieu_de": "Luật Việc làm",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="",
            tieu_de="Luật Việc làm",
            loai_van_ban="luat",
            nam=None,
            cls_nam_ban_hanh=2025,
            law_df=law_df,
        )

        self.assertEqual(result["doc_id"].tolist(), [2025])

    def test_title_only_law_reference_rejects_ambiguous_same_year_versions(self) -> None:
        """CLS-5020: same-year ambiguity must fail instead of falling back to an older law."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 2013,
                    "so_hieu": "38/2013/QH13",
                    "tieu_de": "Luật Việc làm",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2013,
                },
                {
                    "doc_id": 2025,
                    "so_hieu": "74/2025/QH15",
                    "tieu_de": "Luật Việc làm",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
                {
                    "doc_id": 2026,
                    "so_hieu": "75/2025/QH15",
                    "tieu_de": "Luật Việc làm",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="",
            tieu_de="Luật Việc làm",
            loai_van_ban="luat",
            nam=None,
            cls_nam_ban_hanh=2025,
            law_df=law_df,
        )

        self.assertTrue(result.empty)

    def test_law_dataframe_uses_explicit_full_date_for_same_title_same_year(self) -> None:
        """A title-only law reference with a full date must disambiguate same-title same-year laws."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 65,
                    "so_hieu": "65/2025/QH15",
                    "tieu_de": "Luật Tổ chức chính quyền địa phương",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                    "ngay_ban_hanh": "2025-02-19",
                },
                {
                    "doc_id": 72,
                    "so_hieu": "72/2025/QH15",
                    "tieu_de": "Luật Tổ chức chính quyền địa phương",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                    "ngay_ban_hanh": "2025-06-16",
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="",
            tieu_de="Luật Tổ chức chính quyền địa phương",
            loai_van_ban="luat",
            nam=2025,
            cls_nam_ban_hanh=2025,
            law_df=law_df,
            ngay=19,
            thang=2,
        )

        self.assertEqual(result["doc_id"].tolist(), [65])

    def test_law_dataframe_rejects_same_title_same_year_without_date(self) -> None:
        """Without number/date, same-title same-year laws are ambiguous and must not be guessed."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 65,
                    "so_hieu": "65/2025/QH15",
                    "tieu_de": "Luật Tổ chức chính quyền địa phương",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
                {
                    "doc_id": 72,
                    "so_hieu": "72/2025/QH15",
                    "tieu_de": "Luật Tổ chức chính quyền địa phương",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2025,
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="",
            tieu_de="Luật Tổ chức chính quyền địa phương",
            loai_van_ban="luat",
            nam=2025,
            cls_nam_ban_hanh=2025,
            law_df=law_df,
        )

        self.assertTrue(result.empty)

    def test_title_only_fuzzy_ambiguous_policy_rejects(self) -> None:
        """EC-30: title-only fuzzy/substring matches must not pick an ambiguous candidate."""
        for case in active(self.cases.get("title_only_policy_cases", [])):
            with self.subTest(case_id=case["id"]):
                result = filter_law_dataframe(
                    so_hieu=case["so_hieu"],
                    tieu_de=case["tieu_de"],
                    loai_van_ban=case["loai_van_ban"],
                    nam=case["nam"],
                    cls_nam_ban_hanh=case["cls_nam_ban_hanh"],
                    law_df=pd.DataFrame(case["law_dataframe"]),
                )
                if case.get("expected_empty"):
                    self.assertTrue(
                        result.empty,
                        f"{case['id']} should reject ambiguous title-only match, got {result.to_dict('records')}",
                    )

    def test_law_resolver_rejects_so_hieu_title_mismatch(self) -> None:
        """A law reference with conflicting number and title must not resolve."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 70804,
                    "so_hieu": "82/2015/qh13",
                    "tieu_de": "luật tài nguyên môi trường biển và hải đảo",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2015,
                },
                {
                    "doc_id": 70807,
                    "so_hieu": "83/2015/qh13",
                    "tieu_de": "luật ngân sách nhà nước",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2015,
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="83/2015/qh13",
            tieu_de="Luật Tài nguyên, môi trường biển và hải đảo",
            loai_van_ban="luat",
            nam=None,
            cls_nam_ban_hanh=2024,
            law_df=law_df,
        )

        self.assertTrue(result.empty)

    def test_law_resolver_accepts_amendment_wrapper_title_when_so_hieu_matches_base_law(self) -> None:
        """A numbered amendment-style reference may point to the base law title in law_docs.csv."""
        law_df = pd.DataFrame(
            [
                {
                    "doc_id": 177815,
                    "so_hieu": "31/2024/qh15",
                    "tieu_de": "luật đất đai",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2024,
                },
                {
                    "doc_id": 23290,
                    "so_hieu": "25/2001/qh10",
                    "tieu_de": "luật sửa đổi, bổ sung một số điều của luật đất đai",
                    "loai_van_ban": "luat",
                    "nam_ban_hanh": 2001,
                },
            ]
        )

        result = filter_law_dataframe(
            so_hieu="31/2024/qh15",
            tieu_de="Luật sửa đổi, bổ sung một số điều của Luật Đất đai",
            loai_van_ban="luat",
            nam=None,
            cls_nam_ban_hanh=2026,
            law_df=law_df,
        )

        self.assertEqual(result["doc_id"].tolist(), [177815])

    def test_law_resolver_falls_back_to_es_for_numbered_law_missing_from_dataframe(self) -> None:
        """Law-like refs with a number and title should use exact ES number fallback."""
        fake_es = NumberQueryOnlyElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 23094,
                        "so_hieu": "38/2001/PL-UBTVQH10",
                        "loai_van_ban": "Pháp lệnh",
                        "title": "Pháp lệnh 38/2001/PL-UBTVQH10 phí và lệ phí năm 2001",
                        "co_quan_ban_hanh": "Ủy ban Thường vụ Quốc hội",
                        "ngay_ban_hanh": "2001-08-28T00:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "information": "Pháp lệnh phí và lệ phí số 38/2001/PL-UBTVQH10 ngày 28/8/2001",
                "type": "phaplenh",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                [
                    {
                        "doc_id": 1,
                        "so_hieu": "06/2003/pl-ubtvqh11",
                        "tieu_de": "pháp lệnh dân số",
                        "loai_van_ban": "phaplenh",
                        "nam_ban_hanh": 2003,
                    }
                ]
            ),
            cls_nam_ban_hanh=2026,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 23094)
        self.assertEqual(extracted_information, "38/2001/pl-ubtvqh10")
        self.assertIn("so_hieu.keyword", str(fake_es.last_body))

    def test_law_resolver_rejects_exact_number_es_hit_when_title_conflicts(self) -> None:
        """Exact số hiệu alone must not revive old wrong-title law matches."""
        fake_es = NumberQueryOnlyElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 70807,
                        "so_hieu": "83/2015/QH13",
                        "loai_van_ban": "Luật",
                        "title": "Luật ngân sách nhà nước số 83/2015/QH13",
                        "ngay_ban_hanh": "2015-06-25T00:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "information": "Luật Tài nguyên, môi trường biển và hải đảo số 83/2015/QH13",
                "type": "luat",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(
                [
                    {
                        "doc_id": 70807,
                        "so_hieu": "83/2015/qh13",
                        "tieu_de": "luật ngân sách nhà nước",
                        "loai_van_ban": "luat",
                        "nam_ban_hanh": 2015,
                    }
                ]
            ),
            cls_nam_ban_hanh=2026,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertIsNone(doc_id)
        self.assertEqual(extracted_information, "83/2015/qh13")

    def test_law_resolver_accepts_exact_number_es_hit_when_title_is_shorter_but_compatible(self) -> None:
        """Exact law numbers may have a shorter canonical ES title than the reference."""
        fake_es = NumberQueryOnlyElasticsearch(
            [
                {
                    "_score": 30,
                    "_source": {
                        "ID": 8222,
                        "so_hieu": "01/1997/QH10",
                        "loai_van_ban": "Luật",
                        "title": "Luật 01/1997/QH10 ngân hàng Nhà nước",
                        "ngay_ban_hanh": "1997-12-12T17:00:00Z",
                    },
                }
            ]
        )

        doc_id, extracted_information = search_reference_doc(
            doc_info={
                "information": "Luật Ngân hàng Nhà nước Việt Nam số 01/1997/QH10 ngày 12/12/1997",
                "type": "luat",
            },
            law_titles_for_regex=[],
            law_dataframe=pd.DataFrame(columns=["doc_id", "so_hieu", "tieu_de", "loai_van_ban", "nam_ban_hanh"]),
            cls_nam_ban_hanh=2026,
            cls_co_quan_ban_hanh="",
            es_client=fake_es,
        )

        self.assertEqual(doc_id, 8222)
        self.assertEqual(extracted_information, "01/1997/qh10")

    def test_failed_reference_filter_drops_vanban_form_phrases_but_keeps_numbered_external_docs(self) -> None:
        """Generic form phrases are not actionable failed document references."""
        self.assertFalse(
            should_keep_failed_reference(
                {
                    "vanban": {
                        "type": "vanban",
                        "information": "Văn bản đề nghị theo mẫu số 01/MGTH",
                    }
                }
            )
        )
        self.assertTrue(
            should_keep_failed_reference(
                {
                    "vanban": {
                        "type": "vanban",
                        "information": "Văn bản số 8811/UBND-KT ngày 17/10/2011",
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
