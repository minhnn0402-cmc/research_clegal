import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.services.law_docs_enrichment_service import LawDocsEnrichmentService


SAMPLE_CSV = (
    "STT,doc_id,so_hieu,loai_van_ban,tieu_de,nam_ban_hanh\r\n"
    "0,1105,không số,luat,luật cải cách ruộng đất,1953\r\n"
    "1,888,12/2020/qh14,boluat,\"bộ luật dân sự, sửa đổi\",2020"
)

LOAI_VAN_BAN_MAPPING = {"luat": "Luật", "boluat": "Bộ luật"}


def _make_collection(docs):
    collection = MagicMock()
    collection.find.return_value = iter(docs)
    return collection


class TestLawDocsEnrichmentService(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self._tmpdir.name) / "law_docs.csv"
        self.csv_path.write_text(SAMPLE_CSV, encoding="utf-8", newline="")
        self.ids_path = Path(self._tmpdir.name) / "latest_law_ids.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_ids(self, ids):
        with open(self.ids_path, "w", encoding="utf-8") as f:
            json.dump(ids, f)

    def _read_csv_rows(self):
        with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
            return list(csv.reader(f.read().splitlines()))

    def test_appends_mapped_row_preserving_schema_order_and_encoding(self):
        # "(sửa đổi)" form is restructured to the standard amendment template.
        self._write_ids([2001])
        collection = _make_collection([
            {
                "cls_ID": 2001,
                "cls_info": {
                    "so_hieu": "  10/2026/QH15  ",
                    "loai_van_ban": "Luật",
                    "title_without_number": "  Luật Đất đai (sửa đổi)  ",
                    "ngay_ban_hanh": "2026-01-15T00:00:00",
                },
            }
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 1)
        rows = self._read_csv_rows()
        self.assertEqual(rows[0], ["STT", "doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            rows[3],
            ["2", "2001", "10/2026/qh15", "luat",
             "luật sửa đổi, bổ sung một số điều của luật đất đai", "2026"],
        )
        # Original bytes preserved as an exact prefix; CRLF line endings throughout.
        raw = self.csv_path.read_bytes()
        self.assertEqual(raw[: len(SAMPLE_CSV.encode("utf-8"))], SAMPLE_CSV.encode("utf-8"))
        self.assertNotIn(b"\r\n\n", raw)

    def test_continues_stt_from_last_existing_row(self):
        self._write_ids([2001, 2002])
        collection = _make_collection([
            {"cls_ID": 2001, "cls_info": {"so_hieu": "a", "loai_van_ban": "Luật",
                                           "title_without_number": "doc a", "ngay_ban_hanh": "2026-01-01"}},
            {"cls_ID": 2002, "cls_info": {"so_hieu": "b", "loai_van_ban": "Bộ luật",
                                           "title_without_number": "doc b", "ngay_ban_hanh": "2025-06-01"}},
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        service.enrich(self.ids_path)

        rows = self._read_csv_rows()
        self.assertEqual([rows[3][0], rows[4][0]], ["2", "3"])

    def test_skips_doc_ids_already_present_in_csv(self):
        self._write_ids([1105, 3001])
        collection = _make_collection([
            {"cls_ID": 3001, "cls_info": {"so_hieu": "c", "loai_van_ban": "Luật",
                                           "title_without_number": "doc c", "ngay_ban_hanh": "2026-02-01"}},
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 1)
        # Mongo is queried only for the not-yet-present ID.
        query = collection.find.call_args[0][0]
        self.assertEqual(query["cls_ID"]["$in"], [3001])
        rows = self._read_csv_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[3][1], "3001")

    def test_dedupes_repeated_ids_within_input_file(self):
        self._write_ids([4001, 4001, 4001])
        collection = _make_collection([
            {"cls_ID": 4001, "cls_info": {"so_hieu": "d", "loai_van_ban": "Luật",
                                           "title_without_number": "doc d", "ngay_ban_hanh": "2026-03-01"}},
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 1)
        rows = self._read_csv_rows()
        self.assertEqual(len(rows), 4)

    def test_skips_doc_missing_from_mongo(self):
        self._write_ids([5001])
        collection = _make_collection([])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 0)
        self.assertEqual(len(self._read_csv_rows()), 3)

    def test_skips_doc_with_unmapped_loai_van_ban(self):
        self._write_ids([6001])
        collection = _make_collection([
            {"cls_ID": 6001, "cls_info": {"so_hieu": "e", "loai_van_ban": "Nghị quyết",
                                           "title_without_number": "doc e", "ngay_ban_hanh": "2026-04-01"}},
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 0)
        self.assertEqual(len(self._read_csv_rows()), 3)

    def test_skips_doc_with_unparsable_ngay_ban_hanh(self):
        self._write_ids([7001])
        collection = _make_collection([
            {"cls_ID": 7001, "cls_info": {"so_hieu": "f", "loai_van_ban": "Luật",
                                           "title_without_number": "doc f", "ngay_ban_hanh": None}},
        ])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 0)
        self.assertEqual(len(self._read_csv_rows()), 3)

    def test_returns_zero_and_writes_nothing_when_no_candidate_ids(self):
        self._write_ids([])
        collection = _make_collection([])
        service = LawDocsEnrichmentService(collection, self.csv_path, loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING)
        original_bytes = self.csv_path.read_bytes()

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 0)
        collection.find.assert_not_called()
        self.assertEqual(self.csv_path.read_bytes(), original_bytes)


class TestNormalizeTieuDe(unittest.TestCase):
    """Unit tests for LawDocsEnrichmentService._normalize_tieu_de."""

    def _svc(self):
        collection = MagicMock()
        return LawDocsEnrichmentService(
            collection, "/tmp/dummy.csv", loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING
        )

    def _normalize(self, title, loai="Luật"):
        return self._svc()._normalize_tieu_de(title.strip(), loai.lower())

    # ── Already well-formed (starts with "{type} sửa đổi…") ──────────────────

    def test_well_formed_full_template_lowercased_as_is(self):
        title = "Luật sửa đổi, bổ sung một số điều của Luật Nghĩa vụ quân sự"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật nghĩa vụ quân sự",
        )

    def test_well_formed_short_form_lowercased_as_is(self):
        # Older entries: "sửa đổi, bổ sung" without "một số điều của"
        title = "Luật sửa đổi, bổ sung Luật Tổ chức Tòa án nhân dân"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung luật tổ chức tòa án nhân dân",
        )

    def test_well_formed_bo_luat_target_lowercased_as_is(self):
        title = "Luật sửa đổi, bổ sung một số điều của Bộ luật Hình sự"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của bộ luật hình sự",
        )

    def test_well_formed_bo_luat_amending_bo_luat(self):
        title = "Bộ luật sửa đổi, bổ sung một số điều của Bộ luật Dân sự"
        self.assertEqual(
            self._normalize(title, "Bộ luật"),
            "bộ luật sửa đổi, bổ sung một số điều của bộ luật dân sự",
        )

    # ── Parenthetical "(sửa đổi)" form ───────────────────────────────────────

    def test_paren_sua_doi_converted_to_template(self):
        # "Luật X (sửa đổi) [year]" → standard template, year stripped
        title = "Luật Đất đai (sửa đổi) 1998"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật đất đai",
        )

    def test_paren_sua_doi_no_year(self):
        title = "Luật Đất đai (sửa đổi)"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật đất đai",
        )

    def test_paren_sua_doi_long_name(self):
        title = "Luật khuyến khích đầu tư trong nước (sửa đổi) 1998"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật khuyến khích đầu tư trong nước",
        )

    # ── Malformed: "{type} {name} [year] sửa đổi [so_hieu]" ─────────────────

    def test_malformed_with_year_and_so_hieu(self):
        # "Luật X 1965 sửa đổi 45/LCT" → strip year + so_hieu
        title = "Luật nghĩa vụ quân sự 1965 sửa đổi 45/LCT"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật nghĩa vụ quân sự",
        )

    def test_malformed_with_year_only(self):
        title = "Luật dầu khí 2000 sửa đổi"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật dầu khí",
        )

    def test_malformed_with_so_hieu_only(self):
        title = "Luật đầu tư nước ngoài tại Việt Nam 2000 sửa đổi 18/2000/QH10"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của luật đầu tư nước ngoài tại việt nam",
        )

    def test_malformed_lua_bo_luat_target_detected_from_title(self):
        # "Luật bộ luật X" → amendment type "luật", target type "bộ luật"
        title = "Luật bộ luật Tố tụng hình sự 1990 sửa đổi 39-LCT/HĐNN8"
        self.assertEqual(
            self._normalize(title),
            "luật sửa đổi, bổ sung một số điều của bộ luật tố tụng hình sự",
        )

    def test_malformed_bo_luat_amending_bo_luat(self):
        # Amendment type "bộ luật", no secondary prefix
        title = "Bộ luật Dân sự sửa đổi"
        self.assertEqual(
            self._normalize(title, "Bộ luật"),
            "bộ luật sửa đổi, bổ sung một số điều của bộ luật dân sự",
        )

    # ── No "sửa đổi" — unchanged ──────────────────────────────────────────────

    def test_no_sua_doi_returns_lowercased(self):
        title = "Luật Đất đai"
        self.assertEqual(self._normalize(title), "luật đất đai")


class TestCleanRegularTitle(unittest.TestCase):
    """Unit tests for LawDocsEnrichmentService._clean_regular_title (via _normalize_tieu_de)."""

    def _svc(self):
        return LawDocsEnrichmentService(
            MagicMock(), "/tmp/dummy.csv", loai_van_ban_mapping=LOAI_VAN_BAN_MAPPING
        )

    def _normalize(self, title, loai="Luật"):
        return self._svc()._normalize_tieu_de(title.strip(), loai.lower())

    def test_strips_trailing_year(self):
        self.assertEqual(self._normalize("Luật Công đoàn 1957"), "luật công đoàn")

    def test_strips_year_and_so_hieu(self):
        self.assertEqual(
            self._normalize("Luật đầu tư nước ngoài tại Việt Nam 1996 29-LCT/HĐNN8"),
            "luật đầu tư nước ngoài tại việt nam",
        )

    def test_strips_nam_connector_and_year(self):
        self.assertEqual(
            self._normalize("Bộ luật Hàng hải năm 2005", "Bộ luật"),
            "bộ luật hàng hải",
        )

    def test_strips_redundant_type_prefix_and_year(self):
        # "Bộ luật bộ Luật X năm 1990" → "bộ luật x"
        self.assertEqual(
            self._normalize("Bộ luật bộ Luật Hàng hải năm 1990", "Bộ luật"),
            "bộ luật hàng hải",
        )

    def test_strips_ve_viec_prefix(self):
        self.assertEqual(
            self._normalize("Luật về việc ban hành văn bản quy phạm pháp luật 1996"),
            "luật ban hành văn bản quy phạm pháp luật",
        )

    def test_strips_leading_nam_year_for_hien_phap(self):
        # After stripping "hiến pháp", remainder is "năm 1992" — year at start position.
        self.assertEqual(
            self._normalize("Hiến pháp năm 1992", "Hiến pháp"),
            "hiến pháp",
        )

    def test_no_year_unchanged(self):
        self.assertEqual(self._normalize("Luật Đất đai"), "luật đất đai")


class TestHienPhapTwoRows(unittest.TestCase):
    """Hiến pháp docs should produce two CSV rows: short form and full state name."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self._tmpdir.name) / "law_docs.csv"
        self.csv_path.write_text(SAMPLE_CSV, encoding="utf-8", newline="")
        self.ids_path = Path(self._tmpdir.name) / "latest_law_ids.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_ids(self, ids):
        with open(self.ids_path, "w", encoding="utf-8") as f:
            json.dump(ids, f)

    def _read_csv_rows(self):
        with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
            return list(csv.reader(f.read().splitlines()))

    def test_hien_phap_appends_two_rows(self):
        hienphap_mapping = {"luat": "Luật", "boluat": "Bộ luật", "hienphap": "Hiến pháp"}
        self._write_ids([8001])
        collection = _make_collection([
            {
                "cls_ID": 8001,
                "cls_info": {
                    "so_hieu": "",
                    "loai_van_ban": "Hiến pháp",
                    "title_without_number": "Hiến pháp năm 1992",
                    "ngay_ban_hanh": "1992-04-15T00:00:00",
                },
            }
        ])
        service = LawDocsEnrichmentService(
            collection, self.csv_path, loai_van_ban_mapping=hienphap_mapping
        )

        appended = service.enrich(self.ids_path)

        self.assertEqual(appended, 2)
        rows = self._read_csv_rows()
        self.assertEqual(len(rows), 5)  # header + 2 original + 2 new
        self.assertEqual(rows[3][4], "hiến pháp")
        self.assertEqual(rows[4][4], "hiến pháp nước cộng hòa xã hội chủ nghĩa việt nam")
        # Both rows share the same doc_id.
        self.assertEqual(rows[3][1], rows[4][1])
        # STT is sequential.
        self.assertEqual([rows[3][0], rows[4][0]], ["2", "3"])


if __name__ == "__main__":
    unittest.main()
