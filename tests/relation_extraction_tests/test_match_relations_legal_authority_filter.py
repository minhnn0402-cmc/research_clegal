import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestMatchRelationsLegalAuthorityFilter(unittest.TestCase):
    """Validate that invalid local-to-central strong relations are removed."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=[
                'Luật',
                'Nghị quyết',
                'Nghị định',
                'Thông tư',
                'Quyết định',
            ]
        )

    @staticmethod
    def _reference(content: str, text: str, information: str, key: str) -> dict:
        start = content.index(text)
        return {
            key: {
                'information': information,
                'position_start': start,
                'position_end': start + len(text),
            }
        }

    @staticmethod
    def _relation(content: str, text: str, relation_type: str) -> dict:
        start = content.index(text)
        return {
            'relation_type': relation_type,
            'position_start': start,
            'position_end': start + len(text),
        }

    def test_filters_restricted_relation_from_local_source_to_central_target(self) -> None:
        """A local source document must not keep strong action relations to a central target."""
        content = 'Bãi bỏ Nghị định số 12/2024/NĐ-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghị định số 12/2024/NĐ-CP',
                information='Nghị định số 12/2024/NĐ-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='08/2011/QĐ-UBND',
        )

        self.assertEqual(matches, [])

    def test_keeps_non_restricted_relation_from_local_source_to_central_target(self) -> None:
        """A local source may still keep non-restricted relations such as dan_chieu."""
        content = 'Theo Nghị định số 12/2024/NĐ-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghị định số 12/2024/NĐ-CP',
                information='Nghị định số 12/2024/NĐ-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Theo', 'dan_chieu')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='08/2011/QĐ-UBND',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'dan_chieu')

    def test_keeps_restricted_relation_between_local_documents(self) -> None:
        """A restricted relation should remain when both source and target are local documents."""
        content = 'Bãi bỏ Quyết định số 2143/QĐ-UBND.'
        references = [
            self._reference(
                content=content,
                text='Quyết định số 2143/QĐ-UBND',
                information='Quyết định số 2143/QĐ-UBND',
                key='quyetdinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='08/2011/QĐ-UBND',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0]['reference']['quyetdinh']['information'],
            'Quyết định số 2143/QĐ-UBND',
        )

    def test_keeps_bai_bo_between_same_prime_minister_decisions(self) -> None:
        """CLS-4999: administrative QĐ-TTg repeal targets must not be dropped as regulatory."""
        content = (
            'Bãi bỏ Quyết định số 45/QĐ-TTg ngày 09 tháng 01 năm 2019 '
            'của Thủ tướng Chính phủ.'
        )
        references = [
            self._reference(
                content=content,
                text='Quyết định số 45/QĐ-TTg ngày 09 tháng 01 năm 2019',
                information='Quyết định số 45/QĐ-TTg ngày 09 tháng 01 năm 2019',
                key='quyetdinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='824/QĐ-TTg',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')
        self.assertEqual(
            matches[0]['reference']['quyetdinh']['information'],
            'Quyết định số 45/QĐ-TTg ngày 09 tháng 01 năm 2019',
        )

    def test_keeps_bai_bo_between_same_prime_minister_decisions_with_long_number(self) -> None:
        """CLS-4999: same-authority QĐ-TTg matching must work beyond the 824/45 case."""
        content = (
            'Bãi bỏ Quyết định số 2188/QĐ-TTg ngày 15 tháng 11 năm 2016 '
            'của Thủ tướng Chính phủ.'
        )
        references = [
            self._reference(
                content=content,
                text='Quyết định số 2188/QĐ-TTg ngày 15 tháng 11 năm 2016',
                information='Quyết định số 2188/QĐ-TTg ngày 15 tháng 11 năm 2016',
                key='quyetdinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='82/QĐ-TTg',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_filters_bai_bo_between_different_central_decision_authorities(self) -> None:
        """Same-rank central decisions from different authorities must remain blocked."""
        content = 'Bãi bỏ Quyết định số 45/QĐ-BTC ngày 09 tháng 01 năm 2019.'
        references = [
            self._reference(
                content=content,
                text='Quyết định số 45/QĐ-BTC ngày 09 tháng 01 năm 2019',
                information='Quyết định số 45/QĐ-BTC ngày 09 tháng 01 năm 2019',
                key='quyetdinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='824/QĐ-TTg',
        )

        self.assertEqual(matches, [])

    def test_keeps_restricted_relation_from_central_source_to_central_target(self) -> None:
        """Should not affect central source documents."""
        content = 'Bãi bỏ Nghị định số 12/2024/NĐ-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghị định số 12/2024/NĐ-CP',
                information='Nghị định số 12/2024/NĐ-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/NĐ-CP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_keeps_restricted_relation_for_legacy_local_qd_ub_identifier(self) -> None:
        """Legacy local identifiers such as QĐ-UB should still count as local targets."""
        content = 'Đình chỉ Quyết định số 174/2004/QĐ-UB.'
        references = [
            self._reference(
                content=content,
                text='Quyết định số 174/2004/QĐ-UB',
                information='Quyết định số 174/2004/QĐ-UB',
                key='quyetdinh',
            )
        ]
        relation_types = [self._relation(content, 'Đình chỉ', 'dinh_chi')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='64/2006/QĐ-UBND',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0]['reference']['quyetdinh']['information'],
            'Quyết định số 174/2004/QĐ-UB',
        )

    def test_filters_lower_rank_source_restricted_relation_to_higher_rank_target(self) -> None:
        """A lower-ranked source must not keep destructive relations to a higher-ranked target."""
        content = 'Bai bo Nghi dinh so 12/2024/ND-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghi dinh so 12/2024/ND-CP',
                information='Nghi dinh so 12/2024/ND-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Bai bo', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='01/2024/TT-BTP',
        )

        self.assertEqual(matches, [])

    def test_keeps_lower_rank_source_allowed_relation_to_higher_rank_target(self) -> None:
        """A lower-ranked source may keep relations not blocked by the lower-to-higher policy."""
        content = 'Huong dan Nghi dinh so 12/2024/ND-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghi dinh so 12/2024/ND-CP',
                information='Nghi dinh so 12/2024/ND-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Huong dan', 'huong_dan')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='01/2024/TT-BTP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'huong_dan')

    def test_filters_lower_rank_source_keo_dai_hieu_luc_to_higher_rank_target(self) -> None:
        """A lower-ranked source must not extend the effect of a higher-ranked target."""
        content = 'Keo dai hieu luc Nghi dinh so 12/2024/ND-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghi dinh so 12/2024/ND-CP',
                information='Nghi dinh so 12/2024/ND-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Keo dai hieu luc', 'keo_dai_hieu_luc')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='01/2024/TT-BTP',
        )

        self.assertEqual(matches, [])

    def test_filters_higher_rank_source_restricted_relation_to_lower_rank_target(self) -> None:
        """A higher-ranked source must not keep relations reserved for lower-to-higher targets."""
        content = 'Quy dinh chi tiet Thong tu so 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thong tu so 01/2024/TT-BTP',
                information='Thong tu so 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Quy dinh chi tiet', 'quy_dinh_chi_tiet')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/ND-CP',
        )

        self.assertEqual(matches, [])

    def test_keeps_higher_rank_source_allowed_relation_to_lower_rank_target(self) -> None:
        """A higher-ranked source may keep destructive relations to lower-ranked targets."""
        content = 'Bai bo Thong tu so 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thong tu so 01/2024/TT-BTP',
                information='Thong tu so 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Bai bo', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/ND-CP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_keeps_higher_rank_source_keo_dai_hieu_luc_to_lower_rank_target(self) -> None:
        """A higher-ranked source may extend the effect of a lower-ranked target."""
        content = 'Keo dai hieu luc Thong tu so 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thong tu so 01/2024/TT-BTP',
                information='Thong tu so 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Keo dai hieu luc', 'keo_dai_hieu_luc')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/ND-CP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'keo_dai_hieu_luc')

    def test_filters_administrative_source_bai_bo_to_regulatory_target(self) -> None:
        """An administrative document must not keep bai_bo relations to a regulatory target."""
        content = 'Bai bo Thong tu so 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thong tu so 01/2024/TT-BTP',
                information='Thong tu so 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Bai bo', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='123/QD-BTP',
        )

        self.assertEqual(matches, [])

    def test_filters_lower_rank_source_restricted_relation_to_higher_rank_target_with_vietnamese_text(self) -> None:
        """The lower-to-higher destructive rule must work with Vietnamese diacritics."""
        content = 'Bãi bỏ Nghị định số 12/2024/NĐ-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghị định số 12/2024/NĐ-CP',
                information='Nghị định số 12/2024/NĐ-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='01/2024/TT-BTP',
        )

        self.assertEqual(matches, [])

    def test_keeps_lower_rank_source_allowed_relation_to_higher_rank_target_with_vietnamese_text(self) -> None:
        """The lower-to-higher allow-list behavior must work with Vietnamese diacritics."""
        content = 'Hướng dẫn Nghị định số 12/2024/NĐ-CP.'
        references = [
            self._reference(
                content=content,
                text='Nghị định số 12/2024/NĐ-CP',
                information='Nghị định số 12/2024/NĐ-CP',
                key='nghidinh',
            )
        ]
        relation_types = [self._relation(content, 'Hướng dẫn', 'huong_dan')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='01/2024/TT-BTP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'huong_dan')

    def test_filters_higher_rank_source_restricted_relation_to_lower_rank_target_with_vietnamese_text(self) -> None:
        """The upper-to-lower restricted rule must work with Vietnamese diacritics."""
        content = 'Quy định chi tiết Thông tư số 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thông tư số 01/2024/TT-BTP',
                information='Thông tư số 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Quy định chi tiết', 'quy_dinh_chi_tiet')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/NĐ-CP',
        )

        self.assertEqual(matches, [])

    def test_keeps_higher_rank_source_allowed_relation_to_lower_rank_target_with_vietnamese_text(self) -> None:
        """The upper-to-lower allowed behavior must work with Vietnamese diacritics."""
        content = 'Bãi bỏ Thông tư số 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thông tư số 01/2024/TT-BTP',
                information='Thông tư số 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='12/2024/NĐ-CP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_filters_administrative_source_bai_bo_to_regulatory_target_with_vietnamese_text(self) -> None:
        """The administrative-to-regulatory bai_bo rule must work with Vietnamese diacritics."""
        content = 'Bãi bỏ Thông tư số 01/2024/TT-BTP.'
        references = [
            self._reference(
                content=content,
                text='Thông tư số 01/2024/TT-BTP',
                information='Thông tư số 01/2024/TT-BTP',
                key='thongtu',
            )
        ]
        relation_types = [self._relation(content, 'Bãi bỏ', 'bai_bo')]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='123/QĐ-BTP',
        )

        self.assertEqual(matches, [])


if __name__ == '__main__':
    unittest.main()
