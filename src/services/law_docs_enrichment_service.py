"""
Law documents CSV enrichment service.

Appends newly discovered Luật/Bộ luật/Hiến pháp documents to data/law_docs.csv,
fetching their metadata from the CLS MongoDB collection (cls_ver2.cls_info).
"""

import csv
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pymongo.collection import Collection

from src.infrastructure.config import loai_van_ban_mapping as default_loai_van_ban_mapping
from src.infrastructure.logging import get_logger

# Display names ordered longest-first so prefix matching is unambiguous.
_LOAI_VAN_BAN_DISPLAY_NAMES = ("bộ luật", "hiến pháp", "luật")
_AMENDMENT_TEMPLATE = "sửa đổi, bổ sung một số điều của"
# Matches "(sửa đổi)" with optional surrounding whitespace.
_PAREN_SUA_DOI_RE = re.compile(r"\s*\(sửa đổi\)\s*")
# Matches " sửa đổi" preceded by whitespace (i.e. sửa đổi after the base law name).
_SUA_DOI_RE = re.compile(r"\s+sửa đổi")
# Strips a trailing 4-digit year such as " 2000" or " 1965".
_TRAILING_YEAR_RE = re.compile(r"\s+\d{4}\s*$")
# Strips a year (with optional "năm"/"số" connector) and everything that follows.
# Handles both leading position (e.g. "năm 1992" after type-prefix strip) and
# mid-title position (e.g. "tên luật 1990 29-LCT").
_YEAR_AND_TAIL_RE = re.compile(
    r"(?:^(?:(?:năm|số)\s+)?\d{4}|\s+(?:(?:năm|số)\s+)?\d{4})(?:\s+.*)?$"
)


class LawDocsEnrichmentService:
    """
    Appends rows for newly-discovered law documents (Luật/Bộ luật/Hiến pháp) to law_docs.csv.

    Reads candidate IDs from a `latest_law_ids.json`-style file, fetches their
    `cls_info` from MongoDB, maps fields to the CSV schema, skips IDs already
    present, and rewrites the file atomically — preserving header, column order,
    quoting, and CRLF line endings of the original.
    """

    CSV_COLUMNS = ["STT", "doc_id", "so_hieu", "loai_van_ban", "tieu_de", "nam_ban_hanh"]
    LINE_TERMINATOR = "\r\n"

    def __init__(
        self,
        mongo_collection: Collection,
        csv_path,
        loai_van_ban_mapping: Optional[Dict[str, str]] = None,
        logger=None,
    ):
        """
        Args:
            mongo_collection: MongoDB collection holding `cls_info` documents (cls_ver2).
            csv_path: Path to `law_docs.csv` to enrich in place.
            loai_van_ban_mapping: slug -> Vietnamese display name mapping
                (defaults to the canonical `ConfigLoader.loai_van_ban_mapping`,
                inverted to display-name -> slug for lookup).
            logger: Optional logger instance.
        """
        self.mongo_collection = mongo_collection
        self.csv_path = Path(csv_path)
        self.logger = logger or get_logger(self.__class__.__name__)
        mapping = (
            loai_van_ban_mapping if loai_van_ban_mapping is not None else default_loai_van_ban_mapping
        )
        self._slug_by_loai_van_ban_name = {name: slug for slug, name in mapping.items()}

    def enrich(self, latest_law_ids_path) -> int:
        """
        Append rows for IDs from `latest_law_ids_path` not already in the CSV.

        Returns the number of rows appended.
        """
        candidate_ids = self._load_candidate_ids(latest_law_ids_path)
        if not candidate_ids:
            self.logger.info("[LawDocsEnrichment] No candidate IDs to process")
            return 0

        base_content, existing_doc_ids, next_stt = self._read_existing_csv()
        new_ids = [doc_id for doc_id in candidate_ids if doc_id not in existing_doc_ids]
        if not new_ids:
            self.logger.info(
                "[LawDocsEnrichment] All %d candidate ID(s) already present in %s",
                len(candidate_ids), self.csv_path.name,
            )
            return 0

        rows = self._build_rows(new_ids, next_stt)
        if not rows:
            self.logger.info("[LawDocsEnrichment] No new rows mappable from MongoDB")
            return 0

        self._write_atomic(base_content, rows)
        self.logger.info(
            "[LawDocsEnrichment] Appended %d new row(s) to %s (STT %s..%s)",
            len(rows), self.csv_path.name, rows[0][0], rows[-1][0],
        )
        return len(rows)

    def _load_candidate_ids(self, path) -> List[int]:
        path = Path(path)
        if not path.exists():
            self.logger.warning("[LawDocsEnrichment] %s does not exist", path)
            return []
        with open(path, "r", encoding="utf-8") as f:
            raw_ids = json.load(f)
        # dict.fromkeys preserves first-seen order while deduping
        return list(dict.fromkeys(int(doc_id) for doc_id in raw_ids))

    def _read_existing_csv(self):
        with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
            content = f.read()

        data_rows = list(csv.reader(content.splitlines()))[1:]
        existing_doc_ids = {int(row[1]) for row in data_rows}
        next_stt = int(data_rows[-1][0]) + 1 if data_rows else 0

        if content and not content.endswith(self.LINE_TERMINATOR):
            content += self.LINE_TERMINATOR
        return content, existing_doc_ids, next_stt

    def _build_rows(self, doc_ids: List[int], start_stt: int) -> List[List[str]]:
        docs_by_id = self._fetch_docs(doc_ids)
        rows = []
        stt = start_stt
        for doc_id in doc_ids:
            doc = docs_by_id.get(doc_id)
            if doc is None:
                self.logger.warning("[LawDocsEnrichment] Doc %s not found in MongoDB; skipped", doc_id)
                continue
            new_rows = self._map_doc_to_rows(doc, stt)
            rows.extend(new_rows)
            stt += len(new_rows)
        return rows

    def _fetch_docs(self, doc_ids: List[int]) -> Dict[int, dict]:
        projection = {
            "cls_ID": 1,
            "cls_info.so_hieu": 1,
            "cls_info.loai_van_ban": 1,
            "cls_info.title_without_number": 1,
            "cls_info.ngay_ban_hanh": 1,
            "_id": 0,
        }
        cursor = self.mongo_collection.find({"cls_ID": {"$in": doc_ids}}, projection)
        return {doc["cls_ID"]: doc for doc in cursor if doc.get("cls_ID") is not None}

    def _map_doc_to_rows(self, doc: dict, stt: int) -> List[List[str]]:
        doc_id = doc["cls_ID"]
        cls_info = doc.get("cls_info") or {}

        raw_loai_van_ban = (cls_info.get("loai_van_ban") or "").strip()
        loai_van_ban = self._slug_for_loai_van_ban(raw_loai_van_ban, doc_id)
        nam_ban_hanh = self._parse_year(cls_info.get("ngay_ban_hanh"), doc_id)
        if loai_van_ban is None or nam_ban_hanh is None:
            return []

        so_hieu = (cls_info.get("so_hieu") or "").strip().lower()
        type_lower = raw_loai_van_ban.lower()
        raw_title = (cls_info.get("title_without_number") or "").strip()
        tieu_de = self._normalize_tieu_de(raw_title, type_lower)

        row = [str(stt), str(doc_id), so_hieu, loai_van_ban, tieu_de, str(nam_ban_hanh)]

        # Hiến pháp gets two rows: the short canonical form and the full state name.
        if type_lower == "hiến pháp":
            row2 = [
                str(stt + 1), str(doc_id), so_hieu, loai_van_ban,
                "hiến pháp nước cộng hòa xã hội chủ nghĩa việt nam",
                str(nam_ban_hanh),
            ]
            return [row, row2]

        return [row]

    def _normalize_tieu_de(self, title: str, amendment_type_lower: str) -> str:
        """
        Transform raw title_without_number to the canonical tieu_de format used in law_docs.csv.

        Three outcomes:
        - Already starts with "{type} sửa đổi…" → lowercase as-is (already correct).
        - Contains "(sửa đổi)" → restructure to standard amendment template.
        - Has " sửa đổi" after the base law name (malformed form like
          "Luật X 2000 sửa đổi 10/2000/QH10") → restructure to standard template.

        The standard template is:
          "{amendment_type} sửa đổi, bổ sung một số điều của {target_type} {base_name}"
        """
        title_lower = title.lower()

        # Already well-formed: "{type} sửa đổi …"
        for prefix in _LOAI_VAN_BAN_DISPLAY_NAMES:
            if title_lower.startswith(prefix + " sửa đổi"):
                return title_lower

        # Parenthetical "(sửa đổi)" form: "Luật X (sửa đổi) [year]"
        paren_match = _PAREN_SUA_DOI_RE.search(title_lower)
        if paren_match:
            before = title_lower[: paren_match.start()].strip()
            base_name, target_type = self._extract_base_and_target_type(before, amendment_type_lower)
            return f"{amendment_type_lower} {_AMENDMENT_TEMPLATE} {target_type} {base_name}"

        # Malformed form: "Luật X [year] sửa đổi [so_hieu]"
        sua_doi_match = _SUA_DOI_RE.search(title_lower)
        if sua_doi_match:
            before = title_lower[: sua_doi_match.start()].strip()
            base_name, target_type = self._extract_base_and_target_type(before, amendment_type_lower)
            return f"{amendment_type_lower} {_AMENDMENT_TEMPLATE} {target_type} {base_name}"

        # Regular (non-amendment) title: strip type prefix, redundant prefix,
        # "về việc" connector, and embedded year + trailing noise.
        return self._clean_regular_title(title_lower, amendment_type_lower)

    def _clean_regular_title(self, title_lower: str, type_lower: str) -> str:
        text = title_lower

        # Strip the doc's own type prefix.
        if text.startswith(type_lower):
            text = text[len(type_lower) :].strip()
            # Strip a redundant secondary copy (e.g. "bộ luật bộ luật X").
            if text.startswith(type_lower):
                text = text[len(type_lower) :].strip()

        # Strip "về việc" connector used in older law titles.
        if text.startswith("về việc "):
            text = text[len("về việc ") :].strip()

        # Strip year (with optional "năm"/"số" connector) and everything that follows.
        text = _YEAR_AND_TAIL_RE.sub("", text).strip()

        return f"{type_lower} {text}" if text else type_lower

    def _extract_base_and_target_type(
        self, before_sua_doi: str, amendment_type_lower: str
    ) -> Tuple[str, str]:
        """
        From the title fragment before "sửa đổi", extract (base_law_name, target_loai_van_ban).

        Strips the amendment doc's own type prefix, then detects a secondary type prefix
        in case the amendment modifies a different class of document (e.g. "Luật bộ luật X"
        → amendment="luật", target="bộ luật"). Also strips a trailing 4-digit year.
        """
        text = before_sua_doi.strip()
        target_type = amendment_type_lower  # default: same class as the amendment

        # Strip the amendment's own type prefix.
        if text.startswith(amendment_type_lower):
            text = text[len(amendment_type_lower) :].strip()

        # Detect a secondary type prefix for the target law (e.g. "bộ luật" after "luật").
        for prefix in _LOAI_VAN_BAN_DISPLAY_NAMES:
            if text.startswith(prefix + " ") or text == prefix:
                target_type = prefix
                text = text[len(prefix) :].strip()
                break

        # Strip a trailing year (e.g. " 2000", " 1965").
        text = _TRAILING_YEAR_RE.sub("", text).strip()

        return text, target_type

    def _slug_for_loai_van_ban(self, name: Optional[str], doc_id: int) -> Optional[str]:
        if not name:
            self.logger.warning("[LawDocsEnrichment] Doc %s missing loai_van_ban; skipped", doc_id)
            return None
        slug = self._slug_by_loai_van_ban_name.get(name.strip())
        if slug is None:
            self.logger.warning(
                "[LawDocsEnrichment] Doc %s has unmapped loai_van_ban '%s'; skipped", doc_id, name
            )
        return slug

    def _parse_year(self, ngay_ban_hanh, doc_id: int) -> Optional[int]:
        try:
            return int(str(ngay_ban_hanh).split("-")[0])
        except (ValueError, IndexError, AttributeError, TypeError):
            self.logger.warning(
                "[LawDocsEnrichment] Doc %s has invalid ngay_ban_hanh '%s'; skipped", doc_id, ngay_ban_hanh
            )
            return None

    def _write_atomic(self, base_content: str, rows: List[List[str]]):
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator=self.LINE_TERMINATOR).writerows(rows)
        final_content = base_content + buffer.getvalue()

        fd, tmp_path = tempfile.mkstemp(
            dir=self.csv_path.parent, prefix=f".{self.csv_path.stem}_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp_file:
                tmp_file.write(final_content)
            os.replace(tmp_path, self.csv_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
