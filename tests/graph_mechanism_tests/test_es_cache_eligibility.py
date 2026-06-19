"""Tests for persistent ES cache eligibility gating.

These tests verify:
1. is_persistent_es_cache_eligible() correctly classifies references.
2. post_process_relations() respects the eligibility rules at both read and write.
"""

from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

from src.services.extraction.reference_resolution_service import (
    is_persistent_es_cache_eligible,
    post_process_relations,
)


class TestCacheEligibilityUnit(unittest.TestCase):
    """Unit tests for is_persistent_es_cache_eligible()."""

    # ---- Central documents (clear so_hieu, no local markers) ----

    def test_central_nghidinh_with_so_hieu_is_eligible(self):
        doc_info = {'type': 'nghidinh', 'information': 'Nghị định số 45/2021/NĐ-CP ngày 30/4/2021'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_central_thongtu_with_so_hieu_is_eligible(self):
        doc_info = {'type': 'thongtu', 'information': 'Thông tư số 09/2020/TT-BGTVT'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Bộ GTVT'))

    def test_central_doc_empty_authority_is_still_eligible(self):
        """Central so_hieu is globally unique; source authority is not required."""
        doc_info = {'type': 'nghidinh', 'information': 'Nghị định số 100/2019/NĐ-CP'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, ''))

    def test_central_doc_none_authority_is_still_eligible(self):
        doc_info = {'type': 'nghidinh', 'information': 'Nghị định số 100/2019/NĐ-CP'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, None))

    # ---- Local documents — locality gate comes from SOURCE doc's so_hieu ----

    def test_local_source_ubnd_with_authority_is_eligible(self):
        """Source doc is UBND (QĐ-UBND type-code) and authority is provided → eligible."""
        doc_info = {'type': 'quyetdinh', 'information': 'Quyết định số 10/2020/QĐ-UBND'}
        self.assertTrue(is_persistent_es_cache_eligible(
            doc_info, 'UBND Hà Nội', source_so_hieu='10/2020/QĐ-UBND'
        ))

    def test_local_source_hdnd_with_authority_is_eligible(self):
        """Source doc is HĐND (NQ-HĐND type-code) and authority is provided → eligible."""
        doc_info = {'type': 'quyetdinh', 'information': 'Nghị quyết số 05/2021/NQ-HĐND'}
        self.assertTrue(is_persistent_es_cache_eligible(
            doc_info, 'HĐND TP.HCM', source_so_hieu='05/2021/NQ-HĐND'
        ))

    def test_local_source_ubnd_without_authority_is_not_eligible(self):
        """Source doc is UBND but no authority — different provinces reuse the same numbers."""
        doc_info = {'type': 'quyetdinh', 'information': 'Quyết định số 10/2020/QĐ-UBND'}
        self.assertFalse(is_persistent_es_cache_eligible(
            doc_info, '', source_so_hieu='10/2020/QĐ-UBND'
        ))

    def test_local_source_ubnd_none_authority_is_not_eligible(self):
        doc_info = {'type': 'quyetdinh', 'information': 'Quyết định số 10/2020/QĐ-UBND'}
        self.assertFalse(is_persistent_es_cache_eligible(
            doc_info, None, source_so_hieu='10/2020/QĐ-UBND'
        ))

    def test_local_source_ubnd_whitespace_authority_is_not_eligible(self):
        doc_info = {'type': 'quyetdinh', 'information': 'Quyết định số 03/2022/QĐ-UBND'}
        self.assertFalse(is_persistent_es_cache_eligible(
            doc_info, '   ', source_so_hieu='03/2022/QĐ-UBND'
        ))

    def test_central_source_referencing_local_ubnd_doc_is_eligible(self):
        """A central source (NĐ-CP) referencing a UBND doc must be eligible without
        authority — locality is always determined by the SOURCE doc's so_hieu type-code,
        not the referenced doc's so_hieu."""
        doc_info = {'type': 'quyetdinh', 'information': 'Quyết định số 10/2020/QĐ-UBND'}
        self.assertTrue(is_persistent_es_cache_eligible(
            doc_info, '', source_so_hieu='45/2021/NĐ-CP'
        ))

    # ---- Title-only references (no document number pattern) ----

    def test_title_only_luat_dat_dai_is_not_eligible(self):
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai'}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_title_only_empty_information_is_not_eligible(self):
        doc_info = {'type': 'luat', 'information': ''}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_title_only_nghi_quyet_is_not_eligible(self):
        doc_info = {'type': 'nghiquyet', 'information': 'Nghị quyết về phát triển kinh tế biển'}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_title_only_none_information_is_not_eligible(self):
        doc_info = {'type': 'luat', 'information': None}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    # ---- Issued-date and administrative (no year-anchor) formats ----

    def test_title_with_issued_date_is_eligible(self):
        """A title-only string that includes an issued date (DD/MM/YYYY) is uniquely
        identifiable and must be treated as eligible for persistent caching."""
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai ngày 30/4/2021'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_admin_doc_without_year_anchor_is_eligible(self):
        """Administrative documents use NUMBER/TYPE-ISSUER format without a year
        component.  These must still be recognised as having a document number."""
        doc_info = {'type': 'congvan', 'information': 'Công văn số 1234/BGTVT-VT'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Bộ GTVT'))

    def test_written_date_ngay_thang_nam_is_eligible(self):
        """'ngày DD tháng MM năm YYYY' written form must trigger date-based caching."""
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai ngày 10 tháng 05 năm 2015'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_partial_date_ngay_thang_without_nam_is_not_eligible(self):
        """'ngày DD tháng MM' without năm is not specific enough to cache — year is required."""
        doc_info = {'type': 'nghiquyet', 'information': 'Nghị quyết ngày 10 tháng 5'}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Quốc hội'))

    def test_nam_year_alone_is_eligible(self):
        """'năm YYYY' alone is sufficient to make a title-only reference eligible."""
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai năm 2021'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    # ---- Document-number letter constraint and authority-detection precision ----

    def test_doc_number_without_letters_is_not_eligible(self):
        """A YAML pattern match that contains only digits and punctuation (no letters)
        must not qualify as a document number.  E.g. '30/4' is a date fragment, not a so_hieu."""
        doc_info = {'type': 'vanban', 'information': 'Báo cáo 30/4 về tình hình kinh tế'}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_issued_date_without_ngay_prefix_is_not_eligible(self):
        """A DD/MM/YYYY sequence that is NOT preceded by the keyword 'ngày' must not
        trigger date-based caching — it is not a confirmed issued-date marker."""
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai 30/4/2021'}
        self.assertFalse(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_ub_abbreviation_not_ubnd_does_not_require_authority(self):
        """'UB' alone (e.g. Ủy ban Kinh tế) must not fire the local-authority gate.
        Only UBND and HĐND mark provincial/district documents."""
        doc_info = {'type': 'nghidinh', 'information': 'Nghị định số 45/2021/NĐ-CP theo UB Kinh tế'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, ''))

    def test_digit_fragment_before_doc_number_is_eligible(self):
        """When a digit-only fragment matches a YAML catch-all before a valid so_hieu
        in the information string, the reference must still be eligible — finditer
        must find the letter-containing match further along the string."""
        doc_info = {'type': 'nghidinh', 'information': 'Điều 30/4 của Nghị định số 45/2021/NĐ-CP'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_hyphen_separated_date_ngay_is_eligible(self):
        """'ngày DD-MM-YYYY' (hyphen separator) must trigger date-based caching,
        same as the slash-separated form."""
        doc_info = {'type': 'luat', 'information': 'Luật Đất đai ngày 12-12-2012'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, 'Chính phủ'))

    def test_ubnd_in_title_text_not_in_type_code_does_not_require_authority(self):
        """A central document whose reference title mentions 'UBND' in its body text
        (not in the so_hieu type-code suffix) must not be misclassified as local."""
        doc_info = {'type': 'nghidinh', 'information': 'Nghị định số 45/2021/NĐ-CP hướng dẫn cho UBND tỉnh'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, ''))

    def test_date_only_ubnd_in_title_text_not_misclassified_as_local(self):
        """A date-only reference whose information text mentions 'UBND' as subject matter
        must not require authority when the source document is central.  Locality is
        determined from the source document's cls_so_hieu type-code suffix, not from
        scanning the information string."""
        doc_info = {'type': 'luat', 'information': 'Luật về UBND năm 2021'}
        self.assertTrue(is_persistent_es_cache_eligible(doc_info, '', source_so_hieu='45/2021/NĐ-CP'))

    def test_date_only_local_source_so_hieu_without_authority_is_not_eligible(self):
        """A date-only reference from a UBND source doc (QĐ-UBND type-code) must not
        be cached without authority — locality comes from source_so_hieu, not information."""
        doc_info = {'type': 'nghiquyet', 'information': 'Nghị quyết năm 2020'}
        self.assertFalse(is_persistent_es_cache_eligible(
            doc_info, '', source_so_hieu='05/2020/QĐ-UBND'
        ))

    def test_date_only_with_local_source_so_hieu_and_authority_is_eligible(self):
        """A date-only reference from a UBND source doc IS eligible when authority is provided."""
        doc_info = {'type': 'nghiquyet', 'information': 'Nghị quyết năm 2020'}
        self.assertTrue(is_persistent_es_cache_eligible(
            doc_info, 'UBND Hà Nội', source_so_hieu='05/2020/QĐ-UBND'
        ))


class TestPersistentCacheGating(unittest.TestCase):
    """Integration tests: shared cache read/write are correctly gated."""

    def _make_extracted_relations(self, doc_type: str, information: str) -> list:
        """Return a minimal extracted_relations list for one document-level relation."""
        return [{
            'clause_key': 'dieu_1',
            'clause_type': 'vanban',
            'relations': [{
                'relation': 'dan_chieu',
                'tail': [{
                    doc_type: {'information': information},
                }],
            }],
        }]

    @patch('src.services.extraction.reference_resolution_service.search_reference_doc')
    def test_stale_title_only_cache_entry_is_not_reused(self, mock_search):
        """A stale shared-cache entry for a title-only reference must be bypassed."""
        mock_search.return_value = (999, 'Luật Đất đai')

        information = 'Luật Đất đai'
        doc_info_key = json.dumps(
            {'information': information, 'type': 'luat'}, sort_keys=True, ensure_ascii=False
        )
        stale_s_key = f"{doc_info_key}::2020::Bộ TN&MT"
        shared_cache = {stale_s_key: (888, 'Luật Đất đai')}  # stale wrong id
        lock = threading.Lock()

        post_process_relations(
            extracted_relations=self._make_extracted_relations('luat', information),
            doc_id=1,
            nam_ban_hanh=2020,
            co_quan_ban_hanh='Bộ TN&MT',
            es_client=None,
            shared_cache=shared_cache,
            shared_cache_lock=lock,
        )

        # ES search must have been called — stale entry was not read
        mock_search.assert_called_once()

    @patch('src.services.extraction.reference_resolution_service.search_reference_doc')
    def test_title_only_result_is_not_written_to_shared_cache(self, mock_search):
        """A title-only resolution must NOT be stored in the persistent shared cache."""
        mock_search.return_value = (999, 'Luật Đất đai')

        information = 'Luật Đất đai'
        shared_cache: dict = {}
        lock = threading.Lock()

        post_process_relations(
            extracted_relations=self._make_extracted_relations('luat', information),
            doc_id=1,
            nam_ban_hanh=2020,
            co_quan_ban_hanh='Chính phủ',
            es_client=None,
            shared_cache=shared_cache,
            shared_cache_lock=lock,
        )

        # shared_cache must remain empty — nothing written for title-only
        self.assertEqual(shared_cache, {})

    @patch('src.services.extraction.reference_resolution_service.search_reference_doc')
    def test_central_doc_with_so_hieu_is_written_to_shared_cache(self, mock_search):
        """A central document with a clear so_hieu IS stored in the shared cache."""
        mock_search.return_value = (42, '45/2021/NĐ-CP')

        information = 'Nghị định số 45/2021/NĐ-CP'
        shared_cache: dict = {}
        lock = threading.Lock()

        post_process_relations(
            extracted_relations=self._make_extracted_relations('nghidinh', information),
            doc_id=1,
            nam_ban_hanh=2021,
            co_quan_ban_hanh='Chính phủ',
            es_client=None,
            shared_cache=shared_cache,
            shared_cache_lock=lock,
        )

        self.assertTrue(len(shared_cache) > 0, "Central doc should be written to shared cache")

    @patch('src.services.extraction.reference_resolution_service.search_reference_doc')
    def test_local_doc_without_authority_is_not_written_to_shared_cache(self, mock_search):
        """A local UBND source doc without authority must NOT be cached persistently."""
        mock_search.return_value = (77, '10/2020/QĐ-UBND')

        information = 'Quyết định số 10/2020/QĐ-UBND'
        shared_cache: dict = {}
        lock = threading.Lock()

        post_process_relations(
            extracted_relations=self._make_extracted_relations('quyetdinh', information),
            doc_id=1,
            nam_ban_hanh=2020,
            co_quan_ban_hanh='',  # no authority
            es_client=None,
            shared_cache=shared_cache,
            shared_cache_lock=lock,
            source_so_hieu='10/2020/QĐ-UBND',
        )

        self.assertEqual(shared_cache, {}, "Local source doc without authority must not be cached")

    @patch('src.services.extraction.reference_resolution_service.search_reference_doc')
    def test_local_doc_with_authority_is_written_to_shared_cache(self, mock_search):
        """A local UBND source doc WITH authority IS stored in the shared cache."""
        mock_search.return_value = (77, '10/2020/QĐ-UBND')

        information = 'Quyết định số 10/2020/QĐ-UBND'
        shared_cache: dict = {}
        lock = threading.Lock()

        post_process_relations(
            extracted_relations=self._make_extracted_relations('quyetdinh', information),
            doc_id=1,
            nam_ban_hanh=2020,
            co_quan_ban_hanh='UBND Hà Nội',
            es_client=None,
            shared_cache=shared_cache,
            shared_cache_lock=lock,
            source_so_hieu='10/2020/QĐ-UBND',
        )

        self.assertTrue(len(shared_cache) > 0, "Local source doc with authority should be cached")


if __name__ == '__main__':
    unittest.main()
