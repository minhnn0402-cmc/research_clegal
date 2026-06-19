"""Unit tests for match_relations implementation.

These tests verify that the match_relations correctly pairs relation
keywords with document references based on direction (FORWARD / PASSIVE)
and position (inherited with position_start=-1).

Test data is derived from real examples in
evaluation/datasets/legal_relations_cleaned.csv.
"""

import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestMatchRelationsForward(unittest.TestCase):
    """Forward relation matching: the cue appears before the reference."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị quyết', 'Nghị định', 'Thông tư', 'Quyết định']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = ['Luật Đất đai', 'Luật Căn cước']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def test_forward_bai_bo_with_single_reference(self) -> None:
        """'Bãi bỏ' followed by a single clause+doc reference."""
        content = 'Bãi bỏ điểm a khoản 1 Điều 2 Nghị quyết số 956/2020/UBTVQH14.'

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')
        # The reference should start at 'điểm a'
        self.assertEqual(
            matches[0]['reference_position_start'],
            content.index('điểm a'),
        )

    def test_dieu_chinh_license_content_is_dan_chieu_not_sdbs(self) -> None:
        """'Điều chỉnh nội dung giấy phép' is not a legal amendment cue."""
        content = (
            'Điều 17. Điều chỉnh nội dung giấy phép khai thác khoáng sản, '
            'giấy phép khai thác tận thu khoáng sản trong trường hợp quy định '
            'tại điểm n khoản 2 Điều 59, điểm n khoản 2 Điều 70 của '
            'Luật Địa chất và khoáng sản'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Địa chất và khoáng sản'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='54/2024/QH15',
        )

        self.assertNotIn(
            'sua_doi_bo_sung',
            [match['relation_type'] for match in matches],
        )
        self.assertEqual([match['relation_type'] for match in matches], ['dan_chieu', 'dan_chieu'])
        self.assertTrue(any(match['reference']['dieu']['information'] == 'Điều 59' for match in matches))
        self.assertTrue(any(match['reference']['dieu']['information'] == 'Điều 70' for match in matches))

    def test_replacing_appendix_form_or_list_is_sdbs_not_document_replacement(self) -> None:
        """Replacing an appendix/list/form inside a decree is a partial amendment."""
        content = (
            '1. Thay thế danh mục thông báo tại Phụ lục II ban hành kèm theo '
            'Nghị định số 126/2020/NĐ-CP bằng danh mục thông báo tại Phụ lục II '
            'kèm theo Nghị định này.\n'
            '2. Thay thế Mẫu số 01/CCTT-TĐMN quy định tại Phụ lục II '
            'Nghị định số 126/2020/NĐ-CP thành Mẫu số 01/CCTT-TĐMN tại '
            'Phụ lục II kèm theo Nghị định này.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        relations = [match['relation_type'] for match in matches]
        self.assertIn('sua_doi_bo_sung', relations)
        self.assertNotIn('thay_the', relations)
        self.assertTrue(any(
            match['reference']['nghidinh']['information'] == 'Nghị định số 126/2020/NĐ-CP'
            for match in matches
        ))

    def test_sdbs_list_excludes_amendment_history_law_reference(self) -> None:
        """A law cited as prior amendment history is not a direct SĐBS target."""
        content = (
            'Luật An toàn thực phẩm số 55/2010/QH12, Luật Công chứng số 53/2014/QH13, '
            'Luật Dược số 105/2016/QH13, Luật Đầu tư số 67/2014/QH13, '
            'Luật Đầu tư công số 49/2014/QH13, Luật Điện lực số 28/2004/QH11 '
            'đã được sửa đổi, bổ sung một số điều theo Luật số 24/2012/QH13, '
            'Luật Hóa chất số 06/2007/QH12, Luật Khoa học và công nghệ số 29/2013/QH13, '
            'Luật Phòng, chống tác hại của thuốc lá số 09/2012/QH13, '
            'Luật Sử dụng năng lượng tiết kiệm và hiệu quả số 50/2010/QH12 và '
            'Luật Trẻ em số 102/2016/QH13.'
        )
        reference_infos = [
            'Luật An toàn thực phẩm số 55/2010/QH12',
            'Luật Công chứng số 53/2014/QH13',
            'Luật Dược số 105/2016/QH13',
            'Luật Đầu tư số 67/2014/QH13',
            'Luật Đầu tư công số 49/2014/QH13',
            'Luật Điện lực số 28/2004/QH11',
            'Luật số 24/2012/QH13',
            'Luật Hóa chất số 06/2007/QH12',
            'Luật Khoa học và công nghệ số 29/2013/QH13',
            'Luật Phòng, chống tác hại của thuốc lá số 09/2012/QH13',
            'Luật Sử dụng năng lượng tiết kiệm và hiệu quả số 50/2010/QH12',
            'Luật Trẻ em số 102/2016/QH13',
        ]
        references = [
            {
                'luat': {
                    'information': info,
                    'position_start': content.index(info),
                    'position_end': content.index(info) + len(info),
                }
            }
            for info in reference_infos
        ]
        relation_types = [{
            'relation_type': 'sua_doi_bo_sung',
            'relation_value': 'sửa đổi, bổ sung',
            'hint_group': 'forward_hints',
            'position_start': -1,
            'position_end': -1,
            'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='28/2018/QH14',
        )
        matched_infos = [
            match['reference']['luat']['information']
            for match in matches
        ]

        self.assertNotIn('Luật số 24/2012/QH13', matched_infos)
        self.assertIn('Luật Điện lực số 28/2004/QH11', matched_infos)
        self.assertIn('Luật Hóa chất số 06/2007/QH12', matched_infos)

    def test_sdbs_list_excludes_multiple_amendment_history_law_references(self) -> None:
        """All laws after 'đã được sửa đổi... theo' are prior amendment history."""
        content = (
            '1. Sửa đổi, bổ sung Luật Xây dựng số 50/2014/QH13 đã được sửa đổi, '
            'bổ sung một số điều theo Luật số 03/2016/QH14, Luật số 35/2018/QH14, '
            'Luật số 40/2019/QH14, Luật số 62/2020/QH14, Luật số 45/2024/QH15, '
            'Luật số 47/2024/QH15 và Luật số 55/2024/QH15 như sau:'
        )
        reference_infos = [
            'Luật Xây dựng số 50/2014/QH13',
            'Luật số 03/2016/QH14',
            'Luật số 35/2018/QH14',
            'Luật số 40/2019/QH14',
            'Luật số 62/2020/QH14',
            'Luật số 45/2024/QH15',
            'Luật số 47/2024/QH15',
            'Luật số 55/2024/QH15',
        ]
        references = [
            {
                'luat': {
                    'information': info,
                    'position_start': content.index(info),
                    'position_end': content.index(info) + len(info),
                }
            }
            for info in reference_infos
        ]
        relation_types = [{
            'relation_type': 'sua_doi_bo_sung',
            'relation_value': 'sửa đổi, bổ sung',
            'hint_group': 'forward_hints',
            'position_start': -1,
            'position_end': -1,
            'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='99/2025/QH15',
        )
        matched_infos = [
            match['reference']['luat']['information']
            for match in matches
        ]

        self.assertEqual(matched_infos, ['Luật Xây dựng số 50/2014/QH13'])

    def test_cham_dut_hieu_luc_thi_hanh_maps_to_bai_bo(self) -> None:
        """'Chấm dứt hiệu lực thi hành' is treated as a repeal/removal target."""
        content = (
            'Điều 1. Chấm dứt hiệu lực thi hành Quyết định số 2896/QĐ-UBND '
            'ngày 19/12/2018 của UBND tỉnh.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual([match['relation_type'] for match in matches], ['bai_bo'])
        self.assertEqual(
            matches[0]['reference']['quyetdinh']['information'],
            'Quyết định số 2896/QĐ-UBND ngày 19/12/2018',
        )

    def test_local_decision_without_year_can_repeal_local_decision_target(self) -> None:
        """Local QĐ sources without a year should still match local QĐ repeal targets."""
        content = (
            'Điều 1. Chấm dứt hiệu lực thi hành Quyết định số 2896/QĐ-UBND '
            'ngày 19/12/2018 của UBND tỉnh.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='25/QĐ-UBND',
        )

        self.assertEqual([match['relation_type'] for match in matches], ['bai_bo'])
        self.assertEqual(
            matches[0]['reference']['quyetdinh']['information'],
            'Quyết định số 2896/QĐ-UBND ngày 19/12/2018',
        )

    def test_post_intro_document_action_matches_clause_target(self) -> None:
        """Action cues after an intro document and ':' should target following clauses."""
        content = (
            'Thông tư số 14/2020/TT-BYT ngày 10 tháng 7 năm 2020 của Bộ trưởng Bộ Y tế: '
            'Bãi bỏ Khoản 3 Điều 8.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='14/2022/TT-BYT',
        )

        self.assertEqual([match['relation_type'] for match in matches], ['bai_bo'])
        self.assertEqual(
            matches[0]['reference']['thongtu']['information'],
            'Thông tư số 14/2020/TT-BYT ngày 10 tháng 7 năm 2020',
        )
        self.assertEqual(matches[0]['reference']['khoan']['information'], 'khoản 3')
        self.assertEqual(matches[0]['reference']['dieu']['information'], 'Điều 8')

    def test_repeal_list_keeps_multiple_clauses_with_shared_inherited_document_span(self) -> None:
        """Different clause anchors sharing one inherited document span must not be deduped."""
        content = '1. Bãi bỏ Khoản 4, Khoản 5 Điều 4'
        inherited_doc = {
            'information': 'Nghị định số 83/2014/NĐ-CP ngày 03 tháng 9 năm 2014',
            'position_start': 0,
            'position_end': 100,
        }
        references = [
            {
                'khoan': {'information': 'khoản 4', 'position_start': 10, 'position_end': 17},
                'dieu': {'information': 'Điều 4', 'position_start': 28, 'position_end': 34},
                'nghidinh': inherited_doc,
            },
            {
                'khoan': {'information': 'khoản 5', 'position_start': 19, 'position_end': 26},
                'dieu': {'information': 'Điều 4', 'position_start': 28, 'position_end': 34},
                'nghidinh': inherited_doc,
            },
        ]
        relation_types = [{
            'relation_type': 'bai_bo',
            'relation_value': 'Bãi bỏ',
            'hint_group': 'forward_hints',
            'position_start': content.index('Bãi bỏ'),
            'position_end': content.index('Bãi bỏ') + len('Bãi bỏ'),
            'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='08/2018/NĐ-CP',
        )

        self.assertEqual(
            [match['reference']['khoan']['information'] for match in matches],
            ['khoản 4', 'khoản 5'],
        )

    def test_partial_phrase_repeal_targets_clause_as_amendment(self) -> None:
        """Removing a phrase at a clause amends that clause and should not be whole-doc repeal."""
        content = (
            'Thông tư số 26/2019/TT-BYT ngày 30 tháng 8 năm 2019: '
            'Bãi bỏ Điều 9 và cụm từ "và cập nhật Quyết định sửa đổi, bổ sung" '
            'tại Khoản 1 Điều 10.'
        )
        doc = {
            'information': 'Thông tư số 26/2019/TT-BYT ngày 30 tháng 8 năm 2019',
            'position_start': 0,
            'position_end': 51,
        }
        references = [
            {'thongtu': doc},
            {
                'dieu': {
                    'information': 'Điều 9',
                    'position_start': content.index('Điều 9'),
                    'position_end': content.index('Điều 9') + len('Điều 9'),
                },
                'thongtu': doc,
            },
            {
                'khoan': {
                    'information': 'khoản 1',
                    'position_start': content.index('Khoản 1'),
                    'position_end': content.index('Khoản 1') + len('Khoản 1'),
                },
                'dieu': {
                    'information': 'Điều 10',
                    'position_start': content.index('Điều 10'),
                    'position_end': content.index('Điều 10') + len('Điều 10'),
                },
                'thongtu': doc,
            },
        ]
        relation_types = [
            {
                'relation_type': 'bai_bo',
                'relation_value': 'Bãi bỏ',
                'hint_group': 'forward_hints',
                'position_start': content.index('Bãi bỏ'),
                'position_end': content.index('Bãi bỏ') + len('Bãi bỏ'),
                'direction': 'FORWARD',
            },
            {
                'relation_type': 'sua_doi_bo_sung',
                'relation_value': 'Bãi bỏ một phần',
                'hint_group': 'forward_hints',
                'position_start': -1,
                'position_end': -1,
                'direction': 'FORWARD',
            },
        ]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='14/2022/TT-BYT',
        )

        relation_to_refs = [
            (
                match['relation_type'],
                match['reference'].get('khoan', match['reference'].get('dieu', match['reference']['thongtu']))['information'],
            )
            for match in matches
        ]
        self.assertEqual(
            relation_to_refs,
            [
                ('sua_doi', 'khoản 1'),
                ('bai_bo', 'Điều 9'),
            ],
        )

    def test_expiry_excludes_multiple_amendment_history_law_references(self) -> None:
        """Replacement/expiry targets ignore multiple prior amendment-history laws."""
        content = (
            '2. Luật Công chứng số 53/2014/QH13 đã được sửa đổi, bổ sung một số '
            'điều theo Luật số 28/2018/QH14 và Luật số 16/2023/QH15 '
            '(sau đây gọi là Luật Công chứng số 53/2014/QH13) hết hiệu lực kể từ '
            'ngày Luật này có hiệu lực thi hành.'
        )
        reference_infos = [
            'Luật Công chứng số 53/2014/QH13',
            'Luật số 28/2018/QH14',
            'Luật số 16/2023/QH15',
        ]
        references = [
            {
                'luat': {
                    'information': info,
                    'position_start': content.index(info),
                    'position_end': content.index(info) + len(info),
                }
            }
            for info in reference_infos
        ]
        relation_types = [{
            'relation_type': 'thay_the',
            'relation_value': 'hết hiệu lực kể từ ngày Luật này có hiệu lực',
            'hint_group': 'reverse_hints',
            'position_start': content.index('hết hiệu lực'),
            'position_end': content.index('hết hiệu lực') + len('hết hiệu lực kể từ ngày Luật này có hiệu lực'),
            'direction': 'REVERSE',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='46/2024/QH15',
        )
        matched_infos = [
            match['reference']['luat']['information']
            for match in matches
        ]

        self.assertEqual(matched_infos, ['Luật Công chứng số 53/2014/QH13'])

class TestMatchRelationsBackward(unittest.TestCase):
    """Backward / passive-voice relation matching: the reference appears before the cue."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị quyết', 'Nghị định', 'Thông tư', 'Quyết định']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = ['Luật Đất đai']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def test_backward_sua_doi_bo_sung(self) -> None:
        """Backward / passive-voice relation matching: the reference appears before the cue."""
        content = 'Điều 13 Luật Đất đai được sửa đổi, bổ sung như sau:'

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types, 
            clause_types=self.clause_types, 
            law_titles=self.law_titles)

        relation_types = self.extractor.extract_relation_types(
            content=content, 
            references=references)

        matches = self.extractor.match_relations(
            references=references, 
            relation_types=relation_types, 
            content=content)
        
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'sua_doi_bo_sung')
        # The reference should appear before the relation cue (backward match).
        relation_start = matches[0]['relation_position_start']
        ref_end = matches[0]['reference_position_end']
        self.assertLessEqual(
            ref_end, relation_start,
            "Backward match: reference end should be at or before the relation cue start",
        )

    def test_backward_thay_the_resolution_effective_date_matches_all_prior_resolutions(self) -> None:
        """Nghị quyết hết hiệu lực từ ngày nghị quyết này có hiệu lực là quan hệ thay thế."""
        content = (
            'Nghị quyết số 37/2012/QH13 ngày 23 tháng 11 năm 2012 của Quốc hội '
            'về công tác phòng, chống vi phạm pháp luật và tội phạm, công tác của '
            'Viện kiểm sát nhân dân, của Tòa án nhân dân và công tác thi hành án '
            'năm 2013, Nghị quyết số 63/2013/QH13 ngày 27 tháng 11 năm 2013 của '
            'Quốc hội về tăng cường các biện pháp đấu tranh phòng, chống tội phạm, '
            'Nghị quyết số 111/2015/QH13 ngày 27 tháng 11 năm 2015 của Quốc hội '
            'về công tác phòng, chống vi phạm pháp luật và tội phạm, công tác của '
            'Viện kiểm sát nhân dân, của Tòa án nhân dân và công tác thi hành án '
            'năm 2016 và các năm tiếp theo hết hiệu lực thi hành kể từ ngày '
            'Nghị quyết này có hiệu lực.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='96/2019/QH14',
        )

        matched_infos = [
            match['reference']['nghiquyet']['information']
            for match in matches
        ]

        self.assertEqual(
            [relation_type['relation_type'] for relation_type in relation_types],
            ['thay_the'],
        )
        self.assertEqual([match['relation_type'] for match in matches], ['thay_the'] * 3)
        self.assertTrue(any('37/2012/QH13' in info for info in matched_infos))
        self.assertTrue(any('63/2013/QH13' in info for info in matched_infos))
        self.assertTrue(any('111/2015/QH13' in info for info in matched_infos))

    def test_backward_thay_the_excludes_amendment_history_reference(self) -> None:
        """References inside amendment-history descriptions are not direct replacement targets."""
        content = (
            'Nghị quyết số 15/2012/NQ-HĐND ngày 07 tháng 12 năm 2012 của Hội đồng '
            'nhân dân thành phố Cần Thơ quy định chế độ dinh dưỡng đặc thù đối với '
            'vận động viên, huấn luyện viên thể thao; mức chi tổ chức các giải thể '
            'thao và điều chỉnh, bổ sung Nghị quyết số 11/2011/NQ-HĐND ngày 08 '
            'tháng 12 năm 2011 của Hội đồng nhân dân thành phố Cần Thơ hết hiệu '
            'lực thi hành kể từ ngày Nghị quyết này có hiệu lực thi hành.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='23/2025/NQ-HĐND',
        )

        matched_infos = [
            match['reference']['nghiquyet']['information']
            for match in matches
        ]

        self.assertEqual([match['relation_type'] for match in matches], ['thay_the'])
        self.assertTrue(any('15/2012/NQ-HĐND' in info for info in matched_infos))
        self.assertFalse(any('11/2011/NQ-HĐND' in info for info in matched_infos))

    def test_backward_thay_the_keeps_clause_scoped_decree_as_partial_repeal(self) -> None:
        """Whole expired decrees are replaced while clause-scoped targets remain partial repeal."""
        content = (
            '3. Nghị định số 141/2013/NĐ-CP ngày 24 tháng 10 năm 2013 của Chính phủ '
            'quy định chi tiết và hướng dẫn thi hành một số điều của Luật Giáo dục '
            'đại học và Nghị định số 99/2019/NĐ-CP ngày 30 tháng 12 năm 2019 của '
            'Chính phủ quy định chi tiết và hướng dẫn thi hành một số điều của Luật '
            'sửa đổi, bổ sung một số điều của Luật Giáo dục đại học '
            '(Nghị định số 99/2019/NĐ-CP) và Điều 104, Điều 105 Nghị định số '
            '125/2024/NĐ-CP ngày 05 tháng 10 năm 2024 của Chính phủ quy định về '
            'điều kiện đầu tư và hoạt động trong lĩnh vực giáo dục '
            '(Nghị định số 125/2024/NĐ-CP) hết hiệu lực thi hành kể từ ngày '
            'Nghị định này có hiệu lực, trừ trường hợp quy định tại Điều 14 '
            'Nghị định này.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Giáo dục đại học'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='91/2026/NĐ-CP',
        )

        relation_by_target = {
            (
                match['reference'].get('dieu', {}).get('information'),
                match['reference']['nghidinh']['information'],
            ): match['relation_type']
            for match in matches
            if 'nghidinh' in match['reference']
        }

        self.assertEqual([relation_type['relation_type'] for relation_type in relation_types], ['thay_the'])
        self.assertEqual(
            relation_by_target[(None, 'Nghị định số 141/2013/NĐ-CP ngày 24 tháng 10 năm 2013')],
            'thay_the',
        )
        self.assertEqual(
            relation_by_target[(None, 'Nghị định số 99/2019/NĐ-CP ngày 30 tháng 12 năm 2019')],
            'thay_the',
        )
        self.assertEqual(
            relation_by_target[('Điều 104', 'Nghị định số 125/2024/NĐ-CP ngày 05 tháng 10 năm 2024')],
            'bai_bo',
        )
        self.assertEqual(
            relation_by_target[('Điều 105', 'Nghị định số 125/2024/NĐ-CP ngày 05 tháng 10 năm 2024')],
            'bai_bo',
        )
        self.assertFalse(any('luat' in match['reference'] for match in matches))

    def test_backward_bai_bo_clause_scoped_target_becomes_sua_doi_bo_sung(self) -> None:
        """Partial repeal of a clause-level target is treated as sua_doi_bo_sung."""
        doc_types = self.doc_types + ['Thông tư liên tịch']
        content = (
            'Số: 08/2021/TT-BTP\n\n'
            'Hà Nội, ngày 11 tháng 11 năm 2021\n\n'
            'THÔNG TƯ\n\n'
            'BÃI BỎ MỘT SỐ VĂN BẢN QUY PHẠM PHÁP LUẬT DO BỘ TRƯỞNG BỘ TƯ PHÁP BAN HÀNH, LIÊN TỊCH BAN HÀNH\n\n'
            'Căn cứ Luật Ban hành văn bản quy phạm pháp luật ngày 22 tháng 6 năm 2015;\n\n'
            'Căn cứ Luật sửa đổi, bổ sung một số điều của Luật Ban hành văn bản quy phạm pháp luật ngày 14 tháng 6 năm 2020;\n\n'
            'Căn cứ Nghị định số 34/2016/NĐ-CP ngày 14 tháng 5 năm 2016 của Chính phủ quy định chi tiết một số điều và biện pháp thi hành Luật Ban hành văn bản quy phạm pháp luật;\n\n'
            'Căn cứ Nghị định số 154/2020/NĐ-CP ngày 31 tháng 12 năm 2020 của Chính phủ sửa đổi, bổ sung một số điều của Nghị định số 34/2016/NĐ-CP ngày 14 tháng 5 năm 2016 của Chính phủ quy định chi tiết một số điều và biện pháp thi hành Luật Ban hành văn bản quy phạm pháp luật;\n\n'
            'Căn cứ Nghị định số 96/2017/NĐ-CP ngày 16 tháng 8 năm 2017 của Chính phủ quy định chức năng, nhiệm vụ, quyền hạn và cơ cấu tổ chức của Bộ Tư pháp;\n\n'
            'Theo đề nghị của Cục trưởng Cục Kiểm tra văn bản quy phạm pháp luật;\n\n'
            'Bộ trưởng Bộ Tư pháp ban hành Thông tư bãi bỏ một số văn bản quy phạm pháp luật do Bộ trưởng Bộ Tư pháp ban hành, liên tịch ban hành.\n\n'
            'Điều 1. Bãi bỏ toàn bộ văn bản quy phạm pháp luật\n\n'
            'Bãi bỏ toàn bộ Thông tư số 10/2019/TT-BTP ngày 30 tháng 12 năm 2019 của Bộ trưởng Bộ Tư pháp Quy định về tiêu chuẩn chức danh Giám đốc, Phó Giám đốc Sở Tư pháp thuộc Uỷ ban nhân dân tỉnh, thành phố trực thuộc Trung ương.\n\n'
            'Điều 2. Bãi bỏ một phần văn bản quy phạm pháp luật\n\n'
            'Bãi bỏ Mục II Thông tư liên tịch số 02/2008/TTLT-BTP-TWHCCBVN ngày 09 tháng 6 năm 2008 của Bộ Tư pháp, Trung ương Hội Cựu chiến binh Việt Nam Hướng dẫn phối hợp xây dựng văn bản quy phạm pháp luật, tuyên truyền, phổ biến, giáo dục pháp luật, trợ giúp pháp lý đối với Cựu chiến binh.\n\n'
            'Điều 3. Điều khoản thi hành\n\n'
            'Thông tư này có hiệu lực thi hành kể từ ngày 11 tháng 11 năm 2021./.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=doc_types,
            clause_types=self.clause_types,
            law_titles=[],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='08/2021/TT-BTP',
        )

        relation_by_target = {}
        for match in matches:
            for ref_value in match['reference'].values():
                if isinstance(ref_value, dict) and 'information' in ref_value:
                    relation_by_target[ref_value['information']] = match['relation_type']

        self.assertEqual(
            relation_by_target['Thông tư số 10/2019/TT-BTP ngày 30 tháng 12 năm 2019'],
            'bai_bo',
        )
        self.assertEqual(
            relation_by_target['Thông tư liên tịch số 02/2008/TTLT-BTP-TWHCCBVN ngày 09 tháng 6 năm 2008'],
            'sua_doi_bo_sung',
        )

    def test_backward_dinh_chi_intro_does_not_map_as_bai_bo(self) -> None:
        """The cited decree is referenced under 'theo quy định tại', not directly repealed."""
        content = (
            'Văn bản trái pháp luật bị đình chỉ việc thi hành, bãi bỏ toàn bộ hoặc '
            'một phần theo quy định tại Điều 4 của Nghị định số 78/2025/NĐ-CP '
            'ngày 01 tháng 4 năm 2025 của Chính phủ quy định chi tiết một số điều '
            'và biện pháp để tổ chức, hướng dẫn thi hành Luật Ban hành văn bản '
            'quy phạm pháp luật.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Ban hành văn bản quy phạm pháp luật'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='78/2025/NĐ-CP',
        )

        self.assertEqual([match['relation_type'] for match in matches], ['dan_chieu'])
        self.assertEqual(
            matches[0]['reference']['nghidinh']['information'],
            'Nghị định số 78/2025/NĐ-CP ngày 01 tháng 4 năm 2025',
        )

    def test_huy_bo_after_article_heading_matches_joint_resolution(self) -> None:
        """A newline before 'Điều 1. Hủy bỏ...' must not suppress the local relation."""
        content = (
            'Theo đề nghị của Vụ trưởng Vụ Pháp chế,\n\n'
            'Điều 1. Hủy bỏ Nghị quyết liên tịch số 22/2006/NQLT-BGDĐT-HKHVN '
            'ngày 12/5/2006 Liên tịch Bộ Giáo dục và Đào tạo và Hội Khuyến học '
            'Việt Nam về việc phối hợp hoạt động triển khai thực hiện Quyết định '
            'số 112/2005/QĐ-TTg ngày 18/5/2005 của Thủ tướng Chính phủ.'
        )
        doc_types = self.doc_types + ['Nghị quyết liên tịch']

        references = self.extractor.extract_references(
            content=content,
            doc_types=doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual([match['relation_type'] for match in matches], ['huy_bo'])
        self.assertEqual(
            matches[0]['reference']['nghiquyetlientich']['information'],
            'Nghị quyết liên tịch số 22/2006/NQLT-BGDĐT-HKHVN ngày 12/5/2006',
        )

    def test_huy_bo_heading_applies_to_following_bullet_decisions(self) -> None:
        """An action heading like 'Hủy bỏ các Quyết định sau:' applies to bullets."""
        content = (
            'Hủy bỏ các Quyết định sau:\n'
            '- Quyết định số 1754/2000/QĐ-UB ngày 21/12/2000 về một số chính sách '
            'khuyến khích đối với giáo viên trường THPT Chuyên và giáo viên trong '
            'tỉnh có thành tích đặc biệt xuất sắc.\n\n'
            '- Quyết định số 101/2001/QĐ-UB ngày 21/2/2001 về mức thu phí kiểm dịch '
            'động vật.E24'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        matched_infos = [
            match['reference']['quyetdinh']['information']
            for match in matches
        ]

        self.assertEqual([match['relation_type'] for match in matches], ['huy_bo', 'huy_bo'])
        self.assertTrue(any('1754/2000/QĐ-UB' in info for info in matched_infos))
        self.assertTrue(any('101/2001/QĐ-UB' in info for info in matched_infos))

    def test_huy_bo_matches_multiple_same_type_decisions_in_one_sentence(self) -> None:
        """Do not drop a second same-type target after a descriptive title bridge."""
        content = (
            'Điều 1. Hủy bỏ Quyết định số 860/QĐ-UBND ngày 22/4/2008 của UBND tỉnh '
            'về việc phê duyệt dự án đầu tư xây dựng công trình và Quyết định số '
            '1979/QĐ-UBND ngày 23/9/2008 của UBND tỉnh về việc phê duyệt kế hoạch '
            'đấu thầu, công trình: Bệnh viện Đa khoa huyện Bù Đăng, tỉnh Bình Phước.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        matched_infos = [
            match['reference']['quyetdinh']['information']
            for match in matches
        ]

        self.assertEqual([match['relation_type'] for match in matches], ['huy_bo', 'huy_bo'])
        self.assertTrue(any('860/QĐ-UBND' in info for info in matched_infos))
        self.assertTrue(any('1979/QĐ-UBND' in info for info in matched_infos))

    def test_ngung_hieu_luc_matches_clause_targets(self) -> None:
        """'Ngưng hiệu lực thi hành' keeps the repo's separate ngung_hieu_luc type."""
        content = (
            'Điều 1. Ngưng hiệu lực thi hành Điều 63, điểm c khoản 1 Điều 64, '
            'điểm b khoản 2 và khoản 3 Điều 65 Nghị định số 26/2019/NĐ-CP ngày '
            '08 tháng 3 năm 2019 của Chính phủ quy định chi tiết một số điều và '
            'biện pháp thi hành Luật thủy sản cho đến khi sửa đổi các quy định.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual([relation['relation_type'] for relation in relation_types], ['ngung_hieu_luc'])
        self.assertEqual([match['relation_type'] for match in matches], ['ngung_hieu_luc'] * 4)

    def test_tam_ngung_hieu_luc_following_document_list_targets(self) -> None:
        """A temporary suspension heading applies to the following numbered document list."""
        content = (
            'Tạm ngưng hiệu lực áp dụng cho đến khi Luật An toàn thực phẩm (sửa đổi) '
            'và Nghị định hướng dẫn Luật An toàn thực phẩm (sửa đổi) có hiệu lực '
            'thi hành đối với các văn bản sau đây:\n\n'
            '1. Nghị định số 46/2026/NĐ-CP ngày 26 tháng 01 năm 2026 của Chính phủ '
            'quy định chi tiết thi hành một số điều và biện pháp để tổ chức, hướng '
            'dẫn thi hành Luật An toàn thực phẩm.\n\n'
            '2. Nghị quyết số 66.13/2026/NQ-CP ngày 27 tháng 01 năm 2026 của Chính '
            'phủ quy định về công bố, đăng ký sản phẩm thực phẩm.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật An toàn thực phẩm'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        matched_infos = [
            next(iter(match['reference'].values()))['information']
            for match in matches
        ]

        self.assertEqual([relation['relation_type'] for relation in relation_types], ['ngung_hieu_luc'])
        self.assertEqual([match['relation_type'] for match in matches], ['ngung_hieu_luc', 'ngung_hieu_luc'])
        self.assertTrue(any('46/2026/NĐ-CP' in info for info in matched_infos))
        self.assertTrue(any('66.13/2026/NQ-CP' in info for info in matched_infos))
        self.assertFalse(any(info == 'Luật An toàn thực phẩm' for info in matched_infos))

    def test_keo_dai_thoi_gian_tam_giu_is_not_effective_extension(self) -> None:
        """Operational phrases like 'kéo dài thời gian tạm giữ' are not keo_dai_hieu_luc."""
        content = (
            'Điều 21. Kéo dài thời gian tạm giữ\n\n'
            '1. Trường hợp cần kéo dài thời gian tạm giữ theo quy định tại khoản 3 '
            'Điều 122 Luật Xử lý vi phạm hành chính thì trước khi hết thời hạn tạm '
            'giữ người theo thủ tục hành chính ghi trong quyết định, người có thẩm '
            'quyền tạm giữ ra quyết định kéo dài thời gian tạm giữ.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Xử lý vi phạm hành chính'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertNotIn('keo_dai_hieu_luc', [relation['relation_type'] for relation in relation_types])
        self.assertEqual([match['relation_type'] for match in matches], ['dan_chieu'])

    def test_keo_dai_thoi_gian_giai_ngan_is_not_effective_extension(self) -> None:
        """Operational phrases about extending disbursement time are not legal effective-extension cues."""
        content = (
            'Việc chuyển nguồn các khoản chi ngân sách nhà nước và kéo dài thời gian '
            'thực hiện, giải ngân vốn đầu tư công hằng năm của chương trình mục tiêu '
            'quốc gia thực hiện theo quy định của Luật Ngân sách nhà nước, Luật Đầu tư công.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Ngân sách nhà nước', 'Luật Đầu tư công'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertNotIn('keo_dai_hieu_luc', [relation['relation_type'] for relation in relation_types])
        self.assertEqual({match['relation_type'] for match in matches}, {'dan_chieu'})

    def test_keo_dai_thoi_gian_lap_quy_hoach_is_not_effective_extension(self) -> None:
        """Extending the planning process timeline is not extending the Planning Law's effect."""
        content = (
            'Trường hợp bị ảnh hưởng của thiên tai, dịch bệnh làm ảnh hưởng đến tiến '
            'độ lập quy hoạch quy định tại các khoản 1, 2, 3 và 4 Điều này, cơ quan '
            'có thẩm quyền xem xét, chấp thuận kéo dài thời gian lập quy hoạch nhưng '
            'tối đa không quá 06 tháng so với quy định tại các khoản 1, 2, 3 và 4 '
            'Điều này theo Luật Quy hoạch.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Quy hoạch'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertNotIn('keo_dai_hieu_luc', [relation['relation_type'] for relation in relation_types])
        self.assertNotIn('keo_dai_hieu_luc', [match['relation_type'] for match in matches])

    def test_keo_dai_thoi_gian_before_theo_luat_is_not_effective_extension(self) -> None:
        """A law reference after 'theo' is legal basis, not the extended target."""
        content = (
            'Cơ quan có thẩm quyền kéo dài thời gian thẩm định hồ sơ nhưng không '
            'quá 06 tháng theo quy định của Luật Quy hoạch.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=['Luật Quy hoạch'],
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertNotIn('keo_dai_hieu_luc', [relation['relation_type'] for relation in relation_types])
        self.assertNotIn('keo_dai_hieu_luc', [match['relation_type'] for match in matches])

    def test_thay_the_effective_date_heading_matches_following_clause_targets(self) -> None:
        """A heading ending with ':' applies thay_the to the following clause-level list."""
        content = (
            '6. Các nội dung quy định về mức thu, chế độ thu, nộp, quản lý và sử '
            'dụng phí bình tuyển, công nhận cây mẹ, cây đầu dòng (trừ cây lâm '
            'nghiệp, rừng giống) quy định tại các Nghị quyết sau đây hết hiệu lực '
            'thi hành kể từ ngày Nghị quyết này có hiệu lực thi hành:\n'
            'b) Điểm a khoản 1 Điều 3 Nghị quyết số 06/2023/NQ-HĐND ngày 12 tháng '
            '10 năm 2023 của Hội đồng nhân dân tỉnh Vĩnh Long về Quy định miễn, '
            'giảm phí, lệ phí sử dụng dịch vụ công trực tuyến, thanh toán trực '
            'tuyến trên địa bàn tỉnh Vĩnh Long.\n'
            'd) Khoản 1, khoản 2 Điều 4 Nghị quyết số 17/2024/NQ-HĐND ngày 01 '
            'tháng 11 năm 2024 của Hội đồng nhân dân tỉnh Trà Vinh về quy định '
            'phí bình tuyển, công nhận cây mẹ, cây đầu dòng, vườn giống cây lâm '
            'nghiệp, rừng giống trên địa bàn tỉnh Trà Vinh.'
        )

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )
        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='26/2025/NQ-HĐND',
        )

        matched_signatures = {
            (
                match['reference'].get('diem', {}).get('information'),
                match['reference'].get('khoan', {}).get('information'),
                match['reference'].get('dieu', {}).get('information'),
                match['reference']['nghiquyet']['information'],
            )
            for match in matches
        }

        self.assertEqual([relation_type['relation_type'] for relation_type in relation_types], ['thay_the'])
        self.assertEqual([match['relation_type'] for match in matches], ['thay_the'] * 3)
        self.assertIn(
            (
                'điểm a',
                'khoản 1',
                'Điều 3',
                'Nghị quyết số 06/2023/NQ-HĐND ngày 12 tháng 10 năm 2023',
            ),
            matched_signatures,
        )
        self.assertIn(
            (
                None,
                'khoản 1',
                'Điều 4',
                'Nghị quyết số 17/2024/NQ-HĐND ngày 01 tháng 11 năm 2024',
            ),
            matched_signatures,
        )
        self.assertIn(
            (
                None,
                'khoản 2',
                'Điều 4',
                'Nghị quyết số 17/2024/NQ-HĐND ngày 01 tháng 11 năm 2024',
            ),
            matched_signatures,
        )


class TestMatchRelationsInherited(unittest.TestCase):
    """Inherited relation matching: relation from parent/grandparent with position_start=-1."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị quyết', 'Nghị định', 'Thông tư', 'Quyết định', 'Thông tư liên tịch']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = []
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def test_inherited_bai_bo_from_parent(self) -> None:
        """Content has only references; parent has 'Bãi bỏ toàn bộ' + ':' => enumerated inheritance."""
        content = 'Nghị định số 35/2005/NĐ-CP ngày 17 tháng 3 năm 2005 của Chính phủ.'
        parent_content = 'Điều 1. Bãi bỏ toàn bộ các nghị định'

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
            parent_content=parent_content,
        )

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')
        self.assertEqual(matches[0]['relation_position_start'], -1)
        self.assertEqual(matches[0]['relation_position_end'], -1)


class TestMatchRelationsSourceTitleParam(unittest.TestCase):
    """C1: match_relations accepts an optional source_title kwarg without changing output."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Nghị quyết', 'Nghị định', 'Thông tư', 'Quyết định']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.law_titles = ['Luật Đất đai', 'Luật Căn cước']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def test_source_title_kwarg_does_not_change_output(self) -> None:
        """Passing source_title is accepted and produces identical matches."""
        content = 'Bãi bỏ điểm a khoản 1 Điều 2 Nghị quyết số 956/2020/UBTVQH14.'

        references = self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=self.law_titles,
        )
        relation_types = self.extractor.extract_relation_types(
            content=content,
            references=references,
        )

        matches_without = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )
        matches_with = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_title='Nghị định quy định chi tiết một số điều',
        )

        self.assertEqual(matches_with, matches_without)


class TestMatchRelationsActionTypeRefinement(unittest.TestCase):
    """C2: _refine_action_relation_type wired into _build_matches_for_reference_set."""

    def setUp(self) -> None:
        self.extractor = BaseExtractor(
            doc_clause_types=['Luật', 'Nghị định', 'Thông tư', 'Công văn']
        )

    @staticmethod
    def _ref(content: str, text: str, information: str, key: str) -> dict:
        start = content.index(text)
        return {key: {"information": information, "position_start": start, "position_end": start + len(text)}}

    def test_thay_the_cross_type_bai_bo_allowed_becomes_bai_bo(self) -> None:
        """§4/§5: NĐ-CP 'thay thế' a TT-NHNN -> different type, level/year OK -> bai_bo."""
        content = (
            'Thay thế Thông tư số 13/2016/TT-NHNN ngày 30 tháng 6 năm 2016 của '
            'Thống đốc Ngân hàng Nhà nước quy định về cho vay tiêu dùng.'
        )
        references = [self._ref(content, 'Thông tư số 13/2016/TT-NHNN', '13/2016/TT-NHNN', 'thongtu')]
        relation_types = [{
            'relation_type': 'thay_the', 'position_start': 0, 'position_end': 9,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='125/2020/NĐ-CP',
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_bai_bo_same_type_authority_high_title_sim_becomes_thay_the(self) -> None:
        """§6 case B: same TT-NHNN authority + high title similarity -> thay_the."""
        content = (
            'Bãi bỏ Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018 của Thống đốc '
            'Ngân hàng Nhà nước Việt Nam quy định về hệ thống kiểm soát nội bộ của ngân '
            'hàng thương mại, chi nhánh ngân hàng nước ngoài.'
        )
        references = [self._ref(content, 'Thông tư số 13/2018/TT-NHNN', '13/2018/TT-NHNN', 'thongtu')]
        relation_types = [{
            'relation_type': 'bai_bo', 'position_start': 0, 'position_end': 7,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='83/2025/TT-NHNN',
            source_title=(
                'Thông tư quy định về hệ thống kiểm soát nội bộ của ngân hàng '
                'thương mại, chi nhánh ngân hàng nước ngoài'
            ),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'thay_the')

    def test_bai_bo_same_type_authority_realistic_title_with_ban_hanh_becomes_thay_the(self) -> None:
        """§6 case B: realistic cls_title (ends '...do <Authority> ban hành') vs in-content
        target description (starts 'của <Authority> ...') for the SAME regulation must
        still be recognised as high similarity -> thay_the.

        Regression for cls_ID 999999999694233: production cls_info.title_without_number
        always carries the 'do <Authority> ban hành' suffix, unlike the hand-trimmed
        source_title in test_bai_bo_same_type_authority_high_title_sim_becomes_thay_the.
        """
        content = (
            'Bãi bỏ Thông tư số 13/2018/TT-NHNN ngày 18 tháng 5 năm 2018 của Thống đốc '
            'Ngân hàng Nhà nước Việt Nam quy định về hệ thống kiểm soát nội bộ của ngân '
            'hàng thương mại, chi nhánh ngân hàng nước ngoài.'
        )
        references = [self._ref(content, 'Thông tư số 13/2018/TT-NHNN', '13/2018/TT-NHNN', 'thongtu')]
        relation_types = [{
            'relation_type': 'bai_bo', 'position_start': 0, 'position_end': 7,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
            source_so_hieu='83/2025/TT-NHNN',
            source_title=(
                'Thông tư quy định về hệ thống kiểm soát nội bộ của ngân hàng thương mại, '
                'chi nhánh ngân hàng nước ngoài do Thống đốc Ngân hàng Nhà nước Việt Nam '
                'ban hành'
            ),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'thay_the')

    def test_bai_bo_non_node_section_target_becomes_sua_doi_bo_sung(self) -> None:
        """Non-node targets such as mục map action edits to the containing document."""
        content = 'Bãi bỏ Mục II Nghị định số 10/2020/NĐ-CP.'
        references = [self._ref(content, 'Nghị định số 10/2020/NĐ-CP', '10/2020/NĐ-CP', 'nghidinh')]
        relation_types = [{
            'relation_type': 'bai_bo', 'position_start': 0, 'position_end': 6,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'sua_doi_bo_sung')

    def test_ngung_hieu_luc_non_node_appendix_target_becomes_dan_chieu(self) -> None:
        """Effect-suspension relations on non-node targets cite the containing document."""
        content = 'Ngưng hiệu lực thi hành Phụ lục I ban hành kèm theo Nghị định số 10/2020/NĐ-CP.'
        references = [self._ref(content, 'Nghị định số 10/2020/NĐ-CP', '10/2020/NĐ-CP', 'nghidinh')]
        relation_types = [{
            'relation_type': 'ngung_hieu_luc', 'position_start': 0, 'position_end': 23,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'dan_chieu')

    def test_quy_dinh_chi_tiet_non_node_form_target_becomes_huong_dan(self) -> None:
        """Detail/guidance relations on non-node targets map to huong_dan."""
        content = 'Quy định chi tiết Mẫu số 01 ban hành kèm theo Thông tư số 10/2020/TT-BTC.'
        references = [self._ref(content, 'Thông tư số 10/2020/TT-BTC', '10/2020/TT-BTC', 'thongtu')]
        relation_types = [{
            'relation_type': 'quy_dinh_chi_tiet', 'position_start': 0, 'position_end': 17,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'huong_dan')

    def test_mot_phan_text_does_not_trigger_non_node_component_override(self) -> None:
        """The component rule must not treat generic 'một phần' text as Phần I/II."""
        content = 'Bãi bỏ một phần Nghị định số 10/2020/NĐ-CP.'
        references = [self._ref(content, 'Nghị định số 10/2020/NĐ-CP', '10/2020/NĐ-CP', 'nghidinh')]
        relation_types = [{
            'relation_type': 'bai_bo', 'position_start': 0, 'position_end': 6,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')

    def test_clause_scoped_reference_does_not_trigger_non_node_component_override(self) -> None:
        """Clause nodes are built separately, so điều/khoản/điểm keep normal relation logic."""
        content = 'Bãi bỏ Điều 3 Nghị định số 10/2020/NĐ-CP.'
        article_start = content.index('Điều 3')
        references = [{
            **self._ref(content, 'Nghị định số 10/2020/NĐ-CP', '10/2020/NĐ-CP', 'nghidinh'),
            'dieu': {
                'information': 'Điều 3',
                'position_start': article_start,
                'position_end': article_start + len('Điều 3'),
            },
        }]
        relation_types = [{
            'relation_type': 'bai_bo', 'position_start': 0, 'position_end': 6,
            'hint_group': 'forward_hints', 'direction': 'FORWARD',
        }]

        matches = self.extractor.match_relations(
            references=references,
            relation_types=relation_types,
            content=content,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['relation_type'], 'bai_bo')


if __name__ == '__main__':
    unittest.main()
