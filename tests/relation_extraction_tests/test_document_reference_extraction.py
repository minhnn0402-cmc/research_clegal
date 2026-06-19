"""Unit tests for document-level reference extraction."""

import logging
import unittest

from src.domain.extractors.base_extractor import BaseExtractor


logging.disable(logging.INFO)


class TestDocumentReferenceExtraction(unittest.TestCase):
    """Validate rule-based extraction of legal document references."""

    def setUp(self) -> None:
        self.doc_types = ['Luật', 'Bộ luật', 'Hiến pháp', 'Nghị định', 'Thông tư']
        self.clause_types = ['điều', 'khoản', 'điểm']
        self.extractor = BaseExtractor(doc_clause_types=self.doc_types)

    def _extract(self, content: str, law_titles: list = None) -> list:
        return self.extractor.extract_references(
            content=content,
            doc_types=self.doc_types,
            clause_types=self.clause_types,
            law_titles=law_titles or [],
        )

    def test_extracts_law_reference_by_title_and_year(self) -> None:
        """Law-like documents may be extracted using title without a document number."""
        references = self._extract(
            content='Căn cứ Luật tổ chức Chính phủ ngày 19 tháng 6 năm 2015',
            law_titles=['luật tổ chức chính phủ'],
        )

        self.assertEqual(len(references), 1)
        self.assertIn('luat', references[0])
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật tổ chức Chính phủ ngày 19 tháng 6 năm 2015',
        )

    def test_keeps_full_compound_law_title_in_fallback_match(self) -> None:
        """Fallback matching should keep compound law titles instead of truncating at the first comma."""
        references = self._extract(
            content=(
                'Căn cứ Luật sửa đổi, bổ sung một số điều của Luật Ban hành văn bản '
                'quy phạm pháp luật ngày 18 tháng 6 năm 2020.'
            ),
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật sửa đổi, bổ sung một số điều của Luật Ban hành văn bản quy phạm pháp luật ngày 18 tháng 6 năm 2020',
        )

    def test_keeps_date_but_not_issuer_suffix_for_numbered_documents(self) -> None:
        """Document references should stop after the date and ignore issuer suffixes."""
        references = self._extract(
            content='Thực hiện theo Nghị định số 59/2024/NĐ-CP ngày 25/5/2024 của Chính phủ.',
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['nghidinh']['information'],
            'Nghị định số 59/2024/NĐ-CP ngày 25/5/2024',
        )

    def test_accepts_law_number_with_truncated_qh_term(self) -> None:
        """OCR/parser noise may drop one digit from QH terms but the law number is still explicit."""
        references = self._extract(
            content='Theo quy định tại Điều 23 Luật Đường sắt số 95/2025/QH1',
            law_titles=['Luật Đường sắt'],
        )

        extracted = [
            reference['luat']['information']
            for reference in references
            if 'luat' in reference
        ]
        self.assertIn(
            'Luật Đường sắt số 95/2025/QH1',
            extracted,
        )

    def test_rejects_form_identifier_as_document_number(self) -> None:
        """A "Mẫu số …" form code is not a document number; such refs are dropped.

        Hard-negative for the precision leak where a procedural form ("… theo
        Mẫu số 29-TTr") is mistaken for a Quyết định document.
        """
        doc_types = self.doc_types + ['Quyết định']
        extractor = BaseExtractor(doc_clause_types=doc_types)
        for content in (
            'Quyết định gia hạn thời gian thanh tra thực hiện theo Mẫu số 29-TTr '
            'ban hành kèm theo Thông tư này.',
            'Cập nhật vào mục Quyết định thi hành bản án hình sự trong Lý lịch tư '
            'pháp theo mẫu số 01/TT-LLTP.',
        ):
            refs = extractor.extract_references(
                content=content, doc_types=doc_types,
                clause_types=self.clause_types, law_titles=[],
            )
            self.assertEqual(refs, [], msg=content)

    def test_keeps_real_document_alongside_form_identifier(self) -> None:
        """The form code is dropped but a real attached document is still extracted."""
        doc_types = self.doc_types + ['Quyết định']
        extractor = BaseExtractor(doc_clause_types=doc_types)
        references = extractor.extract_references(
            content='Báo cáo theo Mẫu số 05 ban hành kèm theo Quyết định số '
                    '12/2020/QĐ-TTg ngày 01/01/2020.',
            doc_types=doc_types, clause_types=self.clause_types, law_titles=[],
        )
        extracted = [next(iter(r.values())).get('information', '') for r in references]
        self.assertTrue(any('12/2020/QĐ-TTg' in info for info in extracted), extracted)
        self.assertTrue(all('Mẫu số 05' not in info for info in extracted), extracted)

    def test_amendment_provenance_parenthetical_does_not_bind_clause_components(self) -> None:
        """Clause components bind to the governing doc, not a provenance parenthetical.

        In "… tại khoản 1 Điều 5 (được sửa đổi, bổ sung bởi … NĐ 99/2021); khoản 3
        Điều 7 của Nghị định số 50/2019/NĐ-CP", both components belong to the
        governing 50/2019 named after the list. The provenance 99/2021 inside the
        parenthetical must not become a target — but a *standalone* 99/2021
        reference outside any parenthetical is still kept.
        """
        references = self._extract(
            content=(
                'Thay thế cụm từ A bằng cụm từ B tại khoản 1 Điều 5 '
                '(được sửa đổi, bổ sung bởi khoản 2 Điều 1 Nghị định số 99/2021/NĐ-CP); '
                'khoản 3 Điều 7 của Nghị định số 50/2019/NĐ-CP; '
                'khoản 1 Điều 4 Nghị định số 99/2021/NĐ-CP.'
            ),
        )
        rendered = [
            ' '.join(v.get('information', '') for v in r.values() if isinstance(v, dict))
            for r in references
        ]
        # governing-doc binding for the listed components
        self.assertIn('khoản 1 Điều 5 Nghị định số 50/2019/NĐ-CP', rendered)
        self.assertIn('khoản 3 Điều 7 Nghị định số 50/2019/NĐ-CP', rendered)
        # the standalone (non-parenthetical) reference is preserved
        self.assertIn('khoản 1 Điều 4 Nghị định số 99/2021/NĐ-CP', rendered)
        # no component is mis-bound to the provenance document
        self.assertFalse(
            any('Điều 5 Nghị định số 99/2021' in r or 'Điều 7 Nghị định số 99/2021' in r
                for r in rendered),
            rendered,
        )

    def test_provenance_masking_keeps_real_amendment_target_in_parenthetical_free_clause(self) -> None:
        """A normal amendment without any provenance note is unaffected."""
        references = self._extract(
            content='Sửa đổi, bổ sung khoản 2 Điều 3 Nghị định số 10/2020/NĐ-CP.',
        )
        rendered = [
            ' '.join(v.get('information', '') for v in r.values() if isinstance(v, dict))
            for r in references
        ]
        self.assertIn('khoản 2 Điều 3 Nghị định số 10/2020/NĐ-CP', rendered)

    def test_extracts_uppercase_numbered_document_references(self) -> None:
        """Uppercase headings still contain regular numbered document references."""
        references = self._extract(
            content=(
                'NGHỊ ĐỊNH SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ '
                '100/2016/NĐ-CP NGÀY 01 THÁNG 7 NĂM 2016 VÀ NGHỊ ĐỊNH SỐ '
                '12/2015/NĐ-CP NGÀY 12 THÁNG 02 NĂM 2015 CỦA CHÍNH PHỦ'
            ),
        )

        extracted = [
            reference['nghidinh']['information']
            for reference in references
            if 'nghidinh' in reference
        ]
        self.assertIn(
            'NGHỊ ĐỊNH SỐ 100/2016/NĐ-CP NGÀY 01 THÁNG 7 NĂM 2016',
            extracted,
        )
        self.assertIn(
            'NGHỊ ĐỊNH SỐ 12/2015/NĐ-CP NGÀY 12 THÁNG 02 NĂM 2015',
            extracted,
        )

    def test_merges_compound_amendment_law_title_spanning_multiple_law_mentions(self) -> None:
        """A single amendment-law title should not be split into multiple law references."""
        references = self._extract(
            content=(
                'Căn cứ Luật sửa đổi, bổ sung một số điều của Luật thuế giá trị gia tăng, '
                'Luật thuế tiêu thụ đặc biệt và Luật quản lý thuế ngày 06 tháng 4 năm 2016;'
            ),
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật sửa đổi, bổ sung một số điều của Luật thuế giá trị gia tăng, Luật thuế tiêu thụ đặc biệt và Luật quản lý thuế ngày 06 tháng 4 năm 2016',
        )

    def test_merges_amendment_law_title_with_cac_luat_bridge(self) -> None:
        """Amendment titles using 'của các Luật' should stay as one legal basis."""
        references = self._extract(
            content=(
                'Căn cứ Luật sửa đổi, bổ sung một số điều của các Luật về thuế '
                'ngày 26 tháng 11 năm 2014;'
            ),
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật sửa đổi, bổ sung một số điều của các Luật về thuế ngày 26 tháng 11 năm 2014',
        )

    def test_keeps_source_span_when_fuzzy_law_title_is_longer_than_text(self) -> None:
        """Fuzzy title matching should not extend the extraction span beyond source text."""
        references = self._extract(
            content=(
                'Căn cứ Luật Ban hành văn bản quy phạm pháp ngày 22 tháng 6 năm 2015;'
            ),
            law_titles=['Luật Ban hành văn bản quy phạm pháp luật'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Ban hành văn bản quy phạm pháp ngày 22 tháng 6 năm 2015',
        )

    def test_keeps_trailing_qualifier_when_fuzzy_law_title_is_shorter_than_text(self) -> None:
        """Fuzzy title matching should keep specific suffixes such as HĐND và UBND."""
        references = self._extract(
            content=(
                'Căn cứ Luật Ban hành văn bản Quy phạm pháp luật HĐND và UBND '
                'ngày 03/12/2004;'
            ),
            law_titles=['Luật Ban hành văn bản Quy phạm pháp luật'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Ban hành văn bản Quy phạm pháp luật HĐND và UBND ngày 03/12/2004',
        )

    def test_ignores_law_titles_inside_decree_detailing_scope(self) -> None:
        """Law titles inside a cited decree's detailing scope should not become separate căn cứ."""
        references = self._extract(
            content=(
                'Căn cứ Nghị định số 34/2016/NĐ-CP ngày 14 tháng 5 năm 2016 '
                'của Chính phủ quy định chi tiết một số điều và biện pháp thi hành '
                'Luật ban hành văn bản quy phạm pháp luật; '
                'Nghị định số 154/2020/NĐ-CP ngày 31 tháng 12 năm 2020 của Chính phủ '
                'sửa đổi, bổ sung một số điều của Nghị định số 34/2016/NĐ-CP '
                'ngày 14 tháng 5 năm 2016 của Chính phủ quy định chi tiết một số điều '
                'và biện pháp thi hành Luật ban hành văn bản quy phạm pháp luật và '
                'Nghị định số 59/2024/NĐ-CP ngày 25 tháng 5 năm 2024 của Chính phủ '
                'sửa đổi, bổ sung một số điều của Nghị định số 34/2016/NĐ-CP '
                'ngày 14 tháng 5 năm 2016 của Chính phủ quy định chi tiết một số điều '
                'và biện pháp thi hành Luật Ban hành văn bản quy phạm pháp luật đã '
                'được sửa đổi, bổ sung một số điều theo Nghị định số 154/2020/NĐ-CP '
                'ngày 31 tháng 12 năm 2020 của Chính phủ;'
            ),
            law_titles=['Luật ban hành văn bản quy phạm pháp luật'],
        )

        self.assertNotIn(
            'luat',
            [next(iter(reference)) for reference in references],
        )
        self.assertIn(
            'Nghị định số 34/2016/NĐ-CP ngày 14 tháng 5 năm 2016',
            [next(iter(reference.values()))['information'] for reference in references],
        )
        self.assertIn(
            'Nghị định số 154/2020/NĐ-CP ngày 31 tháng 12 năm 2020',
            [next(iter(reference.values()))['information'] for reference in references],
        )
        self.assertIn(
            'Nghị định số 59/2024/NĐ-CP ngày 25 tháng 5 năm 2024',
            [next(iter(reference.values()))['information'] for reference in references],
        )
        self.assertNotIn(
            'Luật ban hành văn bản quy phạm pháp luật và',
            [next(iter(reference.values()))['information'] for reference in references],
        )

    def test_ignores_law_titles_inside_decree_execution_scope(self) -> None:
        """Law titles after 'thi hành' in a cited decree suffix are descriptive, not căn cứ."""
        references = self._extract(
            content=(
                'Căn cứ Nghị định số 181/2004/NĐ-CP ngày 29/10/2004 của Chính Phủ '
                'về thi hành Luật Đất đai 2003; '
                'Nghị định số 198/2004/NĐ-CP ngày 03/12/2004 của Chính phủ;'
            ),
        )

        self.assertEqual(
            [next(iter(reference)) for reference in references],
            ['nghidinh', 'nghidinh'],
        )
        self.assertNotIn(
            'Luật Đất đai 2003',
            [next(iter(reference.values()))['information'] for reference in references],
        )

    def test_ignores_ke_hoach_va_dau_tu_agency_name(self) -> None:
        """Kế hoạch và Đầu tư is an agency name, not a Kế hoạch document reference."""
        references = self.extractor.extract_references(
            content='Theo đề nghị của Sở Kế hoạch và Đầu tư tại Tờ trình số 4699/TTr-SKHĐT.',
            doc_types=[*self.doc_types, 'Kế hoạch'],
            clause_types=self.clause_types,
            law_titles=[],
        )

        self.assertEqual(references, [])

    def test_keeps_real_ke_hoach_document_reference(self) -> None:
        references = self.extractor.extract_references(
            content='Thực hiện Kế hoạch số 123/KH-UBND ngày 01/02/2024.',
            doc_types=[*self.doc_types, 'Kế hoạch'],
            clause_types=self.clause_types,
            law_titles=[],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['kehoach']['information'],
            'Kế hoạch số 123/KH-UBND ngày 01/02/2024',
        )

    def test_extends_law_reference_with_trailing_modifier_before_next_reference(self) -> None:
        """Law references should keep a short qualifier phrase that appears before the next coordinated law."""
        references = self._extract(
            content=(
                'Thông tư quy định chi tiết thi hành Luật Bảo hiểm xã hội, '
                'Luật An toàn vệ sinh lao động về lĩnh vực y tế và Luật Khám bệnh, chữa bệnh.'
            ),
        )

        self.assertEqual(len(references), 3)
        self.assertTrue(
            references[1]['luat']['information'].startswith(
                'Luật An toàn vệ sinh lao động về lĩnh vực y tế'
            ),
        )

    def test_ignores_self_document_references_like_luat_nay(self) -> None:
        """Current-document mentions such as 'Luật này' should not become extracted references."""
        references = self._extract(
            content='Thực hiện theo Luật này và Nghị định số 12/2024/NĐ-CP.',
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['nghidinh']['information'],
            'Nghị định số 12/2024/NĐ-CP',
        )

    def test_law_reference_stops_before_generic_other_law_tail(self) -> None:
        """Named law references should not swallow generic "other law" tails."""
        references = self._extract(
            content=(
                'Tiếp nhận hỗ trợ theo quy định của Luật Các tổ chức tín dụng '
                'và quy định khác của pháp luật có liên quan.'
            ),
            law_titles=['Luật Các tổ chức tín dụng'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Các tổ chức tín dụng',
        )

    def test_clause_law_reference_stops_before_descriptive_qualifier(self) -> None:
        """Clause-scoped law references should stop before operational qualifiers."""
        references = self._extract(
            content=(
                'Đối tượng tinh giản biên chế quy định tại khoản 1 Điều 26 '
                'Luật Bảo hiểm xã hội, có xác nhận của cơ quan Bảo hiểm xã hội.'
            ),
            law_titles=['Luật Bảo hiểm xã hội'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Bảo hiểm xã hội',
        )
        self.assertEqual(
            references[0]['dieu']['information'],
            'Điều 26',
        )
        self.assertEqual(
            references[0]['khoan']['information'],
            'khoản 1',
        )

    def test_law_reference_stops_before_exception_qualifier(self) -> None:
        """Law titles should stop before exception qualifiers."""
        references = self._extract(
            content=(
                'Không nộp hồ sơ khai thuế sau thời hạn quy định tại khoản 6 '
                'Điều 7 Luật quản lý thuế, trừ trường hợp quy định tại khoản 6 Điều 7 Nghị định này.'
            ),
            law_titles=['Luật quản lý thuế'],
        )

        law_references = [reference for reference in references if 'luat' in reference]
        self.assertEqual(
            {reference['luat']['information'] for reference in law_references},
            {'Luật quản lý thuế'},
        )

    def test_law_reference_stops_before_implementation_qualifier(self) -> None:
        """Law titles should stop before implementation-only trailing text."""
        references = self._extract(
            content=(
                'Cơ quan quản lý thuế thực hiện các khoản thu khác theo quy định tại '
                'khoản 7 Điều 39 Luật Phí và lệ phí thực hiện các nội dung quản lý thu.'
            ),
            law_titles=['Luật Phí và lệ phí'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Phí và lệ phí',
        )

    def test_law_reference_stops_before_inline_colon_explanation(self) -> None:
        """Law titles should stop before inline colon explanations."""
        references = self._extract(
            content=(
                'Hỗ trợ theo quy định tại khoản 2 Điều 43 Luật Thủ đô:Được miễn tiền thuê đất.'
            ),
            law_titles=['Luật Thủ đô'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Thủ đô',
        )

    def test_law_reference_stops_before_thi_condition(self) -> None:
        """Law titles should stop before the conditional ``thì`` bridge."""
        references = self._extract(
            content=(
                'Các dự án đầu tư đáp ứng quy định tại khoản 1 Điều 43 '
                'Luật Thủ đô thì được hưởng các ưu đãi.'
            ),
            law_titles=['Luật Thủ đô'],
        )

        self.assertEqual(len(references), 1)
        self.assertEqual(
            references[0]['luat']['information'],
            'Luật Thủ đô',
        )
        self.assertEqual(
            references[0]['khoan']['information'],
            'khoản 1',
        )

    def test_inherits_document_type_for_conjoined_bare_numbered_reference(self) -> None:
        """A bare "và số ..." item should inherit the previous document type."""
        references = self._extract(
            content=(
                'Bãi bỏ các Nghị định số 98/2007/NĐ-CP ngày 07 tháng 6 năm 2007 '
                'và số 13/2009/NĐ-CP ngày 13 tháng 02 năm 2009 của Chính phủ.'
            ),
        )

        self.assertEqual(
            [reference['nghidinh']['information'] for reference in references],
            [
                'Nghị định số 98/2007/NĐ-CP ngày 07 tháng 6 năm 2007',
                'Nghị định số 13/2009/NĐ-CP ngày 13 tháng 02 năm 2009',
            ],
        )

    def test_action_after_intro_document_backfills_clause_targets(self) -> None:
        """Clauses after an action cue should inherit the intro document before ':'."""
        references = self._extract(
            content=(
                'Thông tư số 14/2020/TT-BYT ngày 10 tháng 7 năm 2020 của Bộ trưởng Bộ Y tế: '
                'Bãi bỏ Khoản 3 Điều 8.'
            ),
        )

        self.assertTrue(any(
            reference.get('thongtu', {}).get('information')
            == 'Thông tư số 14/2020/TT-BYT ngày 10 tháng 7 năm 2020'
            and reference.get('khoan', {}).get('information') == 'khoản 3'
            and reference.get('dieu', {}).get('information') == 'Điều 8'
            for reference in references
        ))


if __name__ == '__main__':
    unittest.main()
