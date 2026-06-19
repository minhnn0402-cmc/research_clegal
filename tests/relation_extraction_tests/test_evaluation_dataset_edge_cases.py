import csv
from pathlib import Path
import unittest

from evaluation.evaluate import extract_single_clause
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


def _dataset_rows():
    dataset_path = Path(__file__).parents[2] / "evaluation" / "datasets" / "relation_pairs.csv"
    with dataset_path.open(encoding="utf-8-sig", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle), start=1):
            row["_dataset_idx"] = idx
            yield row


def _row_by_reference(
    so_hieu,
    relation,
    reference_contains,
    clause_type=None,
    content_contains=None,
):
    for row in _dataset_rows():
        if (
            row.get("so_hieu") == so_hieu
            and row.get("relation") == relation
            and reference_contains in row.get("reference", "")
            and (clause_type is None or row.get("clause_type") == clause_type)
            and (content_contains is None or content_contains in row.get("content", ""))
        ):
            return row
    raise AssertionError(
        f"Missing dataset row for {so_hieu} {relation} containing {reference_contains!r}"
    )


def _refs_for_relation(predictions, relation):
    return [
        item["reference"]
        for item in predictions or []
        if item.get("relation") == relation
    ]


def _assert_has_ref(testcase, predictions, relation, *tokens):
    refs = _refs_for_relation(predictions, relation)
    testcase.assertTrue(
        any(all(token in ref for token in tokens) for ref in refs),
        f"Missing {relation} reference with tokens {tokens!r}; got {refs!r}",
    )


def _assert_lacks_ref(testcase, predictions, relation, *tokens):
    refs = _refs_for_relation(predictions, relation)
    testcase.assertFalse(
        any(all(token in ref for token in tokens) for ref in refs),
        f"Unexpected {relation} reference with tokens {tokens!r}; got {refs!r}",
    )


class TestPlanRemainingErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = ConfigLoader()
        cls.extractor = RelationsExtractor(
            doc_clause_types=config.doc_clause_types,
            law_titles_for_regex=config.law_titles_for_regex,
        )
        cls.law_titles = config.law_titles_for_regex

    def _predictions_for_row(self, row):
        return extract_single_clause(
            extractor=self.extractor,
            so_hieu=row.get("so_hieu", ""),
            title=row.get("title", ""),
            clause_type=row.get("clause_type", ""),
            content=row.get("content", ""),
            parent_content=row.get("parent_content", ""),
            grandparent_content=row.get("grandparent_content", ""),
            idx=int(row["_dataset_idx"]),
            law_titles=self.law_titles,
        )

    def test_article_sdbs_headings_stay_operational(self) -> None:
        for title_token in ("An toàn thực phẩm", "Phòng, chống tác hại"):
            row = _row_by_reference(
                "28/2018/QH14",
                "sua_doi_bo_sung",
                title_token,
                clause_type="dieu",
            )
            predictions = self._predictions_for_row(row)

            _assert_has_ref(
                self,
                predictions,
                "sua_doi_bo_sung",
                title_token,
            )

    def test_descriptive_title_citation_is_not_dan_chieu(self) -> None:
        row = _row_by_reference("2/2022/TT-VPCP", "can_cu", "34/2016")
        predictions = self._predictions_for_row(row)

        _assert_lacks_ref(self, predictions, "dan_chieu", "34/2016")

    def test_inserted_article_heading_is_document_sdbs_not_bo_sung(self) -> None:
        row = _row_by_reference("108/2025/QH15", "sua_doi_bo_sung", "88/2015/QH13")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "sua_doi_bo_sung", "88/2015/QH13")
        _assert_lacks_ref(self, predictions, "bo_sung", "70a", "88/2015/QH13")

    def test_effective_date_thay_the_targets_only_expiring_document(self) -> None:
        first_row = _row_by_reference("116/2025/QH15", "thay_the", "86/2015/QH13")
        second_row = _row_by_reference("116/2025/QH15", "thay_the", "24/2018/QH14")

        first_predictions = self._predictions_for_row(first_row)
        _assert_has_ref(self, first_predictions, "thay_the", "86/2015/QH13")
        _assert_lacks_ref(self, first_predictions, "thay_the", "24/2018/QH14")

        second_predictions = self._predictions_for_row(second_row)
        _assert_has_ref(self, second_predictions, "thay_the", "24/2018/QH14")
        _assert_lacks_ref(self, second_predictions, "thay_the", "86/2015/QH13")

    def test_keo_dai_explicit_theo_citations_also_emit_dan_chieu(self) -> None:
        row = _row_by_reference("11/2022/NQ-HĐND", "dan_chieu", "33/2016")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "keo_dai_hieu_luc", "33/2016")
        _assert_has_ref(self, predictions, "keo_dai_hieu_luc", "40/2019")
        _assert_has_ref(self, predictions, "dan_chieu", "33/2016")
        _assert_has_ref(self, predictions, "dan_chieu", "40/2019")

    def test_keo_dai_amendment_history_theo_is_not_dan_chieu(self) -> None:
        row = _row_by_reference("216/2025/QH15", "keo_dai_hieu_luc", "55/2010")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "keo_dai_hieu_luc", "55/2010")
        _assert_lacks_ref(self, predictions, "dan_chieu", "55/2010")
        _assert_lacks_ref(self, predictions, "dan_chieu", "107/2020")

    def test_keo_dai_post_effective_thuc_hien_theo_is_dan_chieu(self) -> None:
        row = _row_by_reference("70/2020/TT-BTC", "dan_chieu", "127/2018")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "keo_dai_hieu_luc", "14/2020")
        _assert_has_ref(self, predictions, "dan_chieu", "127/2018")

    def test_transition_thuc_hien_theo_quy_dinh_is_dan_chieu(self) -> None:
        row = _row_by_reference("29/2025/TT-BYT", "dan_chieu", "01/2018")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "dan_chieu", "01/2018")

    def test_transition_document_list_keeps_external_docs(self) -> None:
        row = _row_by_reference("29/2025/TT-BYT", "dan_chieu", "21/2018")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "dan_chieu", "21/2018")
        _assert_has_ref(self, predictions, "dan_chieu", "39/2021")
        _assert_has_ref(self, predictions, "dan_chieu", "54/2024")

    def test_external_law_after_or_keeps_article_reference(self) -> None:
        row = _row_by_reference("129/2013/NĐ-CP", "dan_chieu", "Điều 33")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "dan_chieu", "Điều 33", "Luật quản lý thuế")

    def test_post_action_assignment_basis_is_not_dan_chieu(self) -> None:
        row = _row_by_reference("2143/QĐ-UBND", "huy_bo", "1247/QĐ-UBND")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "huy_bo", "1247/QĐ-UBND")
        _assert_lacks_ref(self, predictions, "dan_chieu", "Điều 39")

    def test_partial_repeal_child_adds_whole_document_sdbs(self) -> None:
        row = _row_by_reference("14/2022/TT-BYT", "sua_doi_bo_sung", "14/2020/TT-BYT")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "bai_bo", "14/2020/TT-BYT")
        _assert_has_ref(self, predictions, "sua_doi_bo_sung", "14/2020/TT-BYT")

    def test_multi_parent_inserted_khoan_uses_first_concrete_target(self) -> None:
        row = _row_by_reference("133/2025/QH15", "bo_sung", "1a")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "bo_sung", "1a", "67/2025/QH15")
        _assert_lacks_ref(self, predictions, "bo_sung", "1a", "116/2025/QH15")

    def test_numbered_khoan_inherits_parent_sua_doi_target(self) -> None:
        row = _row_by_reference(
            "373/2025/NĐ-CP",
            "sua_doi",
            "khoản 8 Điều 13",
            content_contains="Trường hợp cơ quan thuế",
        )
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "sua_doi", "khoản 8", "126/2020/NĐ-CP")

    def test_appendix_replacement_keeps_new_self_appendix_as_dan_chieu(self) -> None:
        row = _row_by_reference("373/2025/NĐ-CP", "dan_chieu", "373/2025")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "sua_doi_bo_sung", "126/2020/NĐ-CP")
        _assert_has_ref(self, predictions, "dan_chieu", "373/2025/NĐ-CP")

    def test_repealing_attached_forms_uses_parent_source_and_repealed_doc(self) -> None:
        row = _row_by_reference("373/2025/NĐ-CP", "sua_doi_bo_sung", "80/2021/TT-BTC")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "dan_chieu", "126/2020/NĐ-CP")
        _assert_has_ref(self, predictions, "sua_doi_bo_sung", "80/2021/TT-BTC")
        _assert_lacks_ref(self, predictions, "dan_chieu", "80/2021/TT-BTC")

    def test_self_document_tail_does_not_inherit_previous_external_law(self) -> None:
        row = _row_by_reference("129/2013/NĐ-CP", "dan_chieu", "khoản 6 Điều 7")
        predictions = self._predictions_for_row(row)

        _assert_has_ref(self, predictions, "dan_chieu", "khoản 6 Điều 7", "129/2013/NĐ-CP")
        _assert_lacks_ref(self, predictions, "dan_chieu", "khoản 6 Điều 7", "Luật quản lý thuế")


if __name__ == "__main__":
    unittest.main()
