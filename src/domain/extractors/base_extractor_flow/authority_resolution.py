"""Authority-policy and document-hierarchy resolution for ``BaseExtractor``."""

import re
from typing import Dict, Optional

from src.domain.extractors.base_extractor_flow.shared import BaseExtractorShared, unidecode

LAW_DOCUMENT_KEYS = BaseExtractorShared.LAW_DOCUMENT_KEYS


class AuthorityResolution:
    """Document hierarchy and authority-policy filter methods."""

    @classmethod
    def _is_local_document_identifier(cls, identifier: Optional[str]) -> bool:
        """Return True when the identifier clearly belongs to a local authority document."""
        return bool(identifier) and any(marker in identifier for marker in cls.LOCAL_AUTHORITY_MARKERS)

    @classmethod
    def _extract_administrative_authority_family(cls, identifier: Optional[str]) -> Optional[str]:
        """Extract a comparable issuing-authority family from administrative identifiers."""
        normalized = cls._normalize_authority_policy_text(identifier)
        if not normalized:
            return None

        if "THU TUONG" in normalized or re.search(r"(?:^|[-/])TTG\b", normalized):
            return "TTG"
        if "CHINH PHU" in normalized or re.search(r"(?:^|[-/])CP\b", normalized):
            return "CP"

        for code in cls.CENTRAL_MINISTRY_CODES:
            if re.search(rf"(?:^|[-/]){re.escape(code)}\b", normalized):
                return code

        return None

    def _is_same_administrative_authority_decision(
        self,
        source_so_hieu: Optional[str],
        target_identifier: Optional[str],
        source_info: Dict[str, Optional[object]],
        target_info: Dict[str, Optional[object]],
    ) -> bool:
        """Return True for same-authority administrative decisions such as QĐ-TTg -> QĐ-TTg."""
        if (
            source_info.get("doc_type") not in self.DECISION_DOCUMENT_TYPES
            or target_info.get("doc_type") not in self.DECISION_DOCUMENT_TYPES
        ):
            return False

        source_family = self._extract_administrative_authority_family(source_so_hieu)
        target_family = self._extract_administrative_authority_family(target_identifier)
        return bool(source_family and target_family and source_family == target_family)

    @staticmethod
    def _normalize_authority_policy_text(value: Optional[str]) -> str:
        """Normalize document identifiers for authority-policy heuristics."""
        if not value:
            return ""

        normalized = unidecode(str(value)).upper()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def _has_year_in_identifier(cls, identifier: Optional[str]) -> bool:
        """Return True when an identifier contains a 4-digit issuance year."""
        return cls._extract_year_from_identifier(identifier) is not None

    @classmethod
    def _infer_document_type_from_identifier(cls, identifier: Optional[str]) -> Optional[str]:
        """Infer the broad document type from a serial number when metadata is unavailable."""
        normalized = cls._normalize_authority_policy_text(identifier)
        if not normalized:
            return None

        if "HIEN PHAP" in normalized:
            return "hienphap"
        if re.search(r"(?:^|[/-])NQLT(?:[/-]|$)", normalized):
            return "nghiquyetlientich"
        if re.search(r"(?:^|[/-])TTLT(?:[/-]|$)", normalized):
            return "thongtulientich"
        if "ND-CP" in normalized or re.search(r"(?:^|[/-])ND(?:[/-]|$)", normalized):
            return "nghidinh"
        if re.search(r"(?:^|[/-])TT(?:[-/]|$)", normalized):
            return "thongtu"
        if re.search(r"(?:^|[/-])NQ(?:[-/]|$)", normalized):
            return "nghiquyet"
        if re.search(r"(?:^|[/-])QD(?:[-/]|$)", normalized):
            return "quyetdinh"
        if re.search(r"(?:^|[/-])KH(?:[-/]|$)", normalized):
            return "kehoach"
        if re.search(r"(?:^|[/-])CT(?:[-/]|$)", normalized):
            return "chithi"
        if re.search(r"(?:^|[/-])CV(?:[-/]|$)", normalized):
            return "congvan"
        if re.search(r"(?:^|/)\d{1,5}/\d{4}/QH\d{1,3}\b", normalized):
            return "luat"
        if "UBTVQH" in normalized:
            return "phaplenh"

        return None

    @classmethod
    def _infer_authority_rank(cls, identifier: Optional[str]) -> Optional[int]:
        """Infer issuing-authority rank from serial suffixes or authority text."""
        normalized = cls._normalize_authority_policy_text(identifier)
        if not normalized:
            return None

        if "HIEN PHAP" in normalized:
            return 140
        if "QUOC HOI" in normalized or re.search(r"(?:^|[/-])QH\d{1,3}\b", normalized):
            return 130
        if "UBTVQH" in normalized:
            return 120
        if "CHU TICH NUOC" in normalized or re.search(r"(?:^|[/-])CTN\b", normalized):
            return 110
        if "CHINH PHU" in normalized or re.search(r"(?:^|[-/])CP\b", normalized):
            return 100
        if "THU TUONG" in normalized or re.search(r"(?:^|[-/])TTG\b", normalized):
            return 90
        if "HDTP" in normalized or "HOI DONG THAM PHAN" in normalized:
            return 85
        if "TANDTC" in normalized or "VKSNDTC" in normalized or "TONG KIEM TOAN" in normalized:
            return 80

        for code in cls.CENTRAL_MINISTRY_CODES:
            if re.search(rf"(?:^|[-/]){re.escape(code)}\b", normalized):
                return 80

        if "TAND CAP CAO" in normalized or "VKSND CAP CAO" in normalized:
            return 70

        if "UBND" in normalized or "HDND" in normalized:
            if "DAC KHU" in normalized or "DON VI HANH CHINH KINH TE DAC BIET" in normalized:
                return 40
            if any(token in normalized for token in (" CAP XA", " PHUONG", " XA ")):
                return 30 if "HDND" in normalized else 20
            if any(token in normalized for token in (" CAP HUYEN", " HUYEN", " QUAN", " THI XA")):
                return 30 if "HDND" in normalized else 20
            return 60 if "HDND" in normalized else 50

        if "TAND TINH" in normalized or "VKSND TINH" in normalized:
            return 60
        if "TAND HUYEN" in normalized or "VKSND HUYEN" in normalized:
            return 30

        return None

    def _build_authority_policy_doc_info(
        self,
        identifier: Optional[str],
        doc_type_key: Optional[str] = None,
    ) -> Dict[str, Optional[object]]:
        """Build the small metadata bundle used by relation authority policy."""
        inferred_doc_type = doc_type_key or self._infer_document_type_from_identifier(identifier)

        # Per the 14-level normative hierarchy rule: a document is considered normative
        # only when its document number contains a 4-digit year (e.g. 28/2018/QH15,
        # 123/2024/NĐ-CP).  Documents without a year (e.g. 706/QĐ-BXD, 42/CP) are
        # administrative and do not participate in the normative hierarchy.
        # Exceptions that are always normative regardless of year (commonly referenced
        # by title only, without a serial number):
        #   Hiến pháp, Luật, Bộ luật, Pháp lệnh, Lệnh
        # Administrative types that are NEVER normative even with a year in their number:
        #   see ADMINISTRATIVE_DOCUMENT_TYPES.
        _INHERENTLY_NORMATIVE = frozenset({"hienphap", "luat", "boluat", "phaplenh", "lenh"})
        has_year = self._has_year_in_identifier(identifier)
        is_regulatory = (
            inferred_doc_type in _INHERENTLY_NORMATIVE
            or (
                inferred_doc_type not in self.ADMINISTRATIVE_DOCUMENT_TYPES
                and has_year
            )
        )
        type_rank = (
            self.DIRECT_DOCUMENT_TYPE_RANKS.get(inferred_doc_type)
            if is_regulatory
            else None
        )
        return {
            "doc_type": inferred_doc_type,
            "type_rank": type_rank,
            "authority_rank": self._infer_authority_rank(identifier),
            "is_regulatory": is_regulatory,
        }

    def _build_reference_authority_policy_doc_info(self, reference: Dict) -> Optional[Dict[str, Optional[object]]]:
        """Build authority-policy metadata for the target reference."""
        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return None

        doc_key, doc_info = primary_document
        information = doc_info.get("information", "") if isinstance(doc_info, dict) else ""
        return self._build_authority_policy_doc_info(
            identifier=information,
            doc_type_key=doc_key,
        )

    def _compare_authority_policy_documents(
        self,
        source_info: Dict[str, Optional[object]],
        target_info: Dict[str, Optional[object]],
    ) -> Optional[str]:
        """Return source_higher/source_lower when the hierarchy is clear."""
        source_type_rank = source_info.get("type_rank")
        target_type_rank = target_info.get("type_rank")
        source_authority_rank = source_info.get("authority_rank")
        target_authority_rank = target_info.get("authority_rank")

        # Authority rank (based on issuing body) takes precedence because it correctly
        # distinguishes e.g. Nghị quyết QH (rank 130) from Nghị quyết HĐND (rank 60).
        if isinstance(source_authority_rank, int) and isinstance(target_authority_rank, int):
            if source_authority_rank > target_authority_rank:
                return "source_higher"
            if source_authority_rank < target_authority_rank:
                return "source_lower"

        if isinstance(source_type_rank, int) and isinstance(target_type_rank, int):
            if source_type_rank > target_type_rank:
                return "source_higher"
            if source_type_rank < target_type_rank:
                return "source_lower"

        # Cross-dimension fallback (conservative): applies only when the source has an
        # authority_rank but no type_rank (non-normative by type, e.g. QĐ without year),
        # AND the target has a type_rank but no authority_rank (referenced only by title,
        # e.g. "Luật An toàn thực phẩm"), AND the target is an inherently-normative type
        # that sits at the top of the normative hierarchy.
        # This catches cases like QĐ-BXD (authority_rank=80) trying to act on Luật
        # (type_rank=130) where the source is clearly lower despite missing type_rank.
        _INHERENTLY_NORMATIVE_FALLBACK = frozenset(
            {"hienphap", "luat", "boluat", "phaplenh", "lenh"}
        )
        target_doc_type = target_info.get("doc_type")
        if (
            isinstance(source_authority_rank, int)
            and not isinstance(source_type_rank, int)
            and not isinstance(target_authority_rank, int)
            and isinstance(target_type_rank, int)
            and target_doc_type in _INHERENTLY_NORMATIVE_FALLBACK
        ):
            if source_authority_rank < target_type_rank:
                return "source_lower"

        source_doc_type = source_info.get("doc_type")
        target_doc_type = target_info.get("doc_type")
        if source_doc_type in self.RESOLUTION_DOCUMENT_TYPES and target_doc_type in self.DECISION_DOCUMENT_TYPES:
            return "source_higher"
        if source_doc_type in self.DECISION_DOCUMENT_TYPES and target_doc_type in self.RESOLUTION_DOCUMENT_TYPES:
            return "source_lower"

        return None

    def _should_filter_by_authority_policy(
        self,
        relation_type: str,
        source_so_hieu: Optional[str],
        reference: Dict,
    ) -> bool:
        """Apply source/target hierarchy restrictions for relation types."""
        if not source_so_hieu:
            return False

        target_info = self._build_reference_authority_policy_doc_info(reference)
        if not target_info:
            return False

        source_info = self._build_authority_policy_doc_info(source_so_hieu)
        source_doc_type = source_info.get("doc_type")
        target_doc_type = target_info.get("doc_type")

        # Administrative ↔ normative: no action relationships in either direction.
        # Administrative docs (congvan, chithi, kehoach, …) cannot modify, repeal,
        # replace, or suspend normative VBQPPL, and vice versa.
        # "Normative" here means has year in number OR is an inherently-normative type
        # (luat, boluat, hienphap, phaplenh).
        target_is_normative = target_info.get("is_regulatory", False)
        source_is_normative = source_info.get("is_regulatory", False)

        if relation_type in self.STRONG_ACTION_TARGET_RELATION_TYPES:
            if (
                source_doc_type in self.ADMINISTRATIVE_DOCUMENT_TYPES
                and target_is_normative
            ):
                return True
            if (
                source_is_normative
                and target_doc_type in self.ADMINISTRATIVE_DOCUMENT_TYPES
            ):
                return True

        hierarchy_direction = self._compare_authority_policy_documents(source_info, target_info)
        target_identifier = self._extract_reference_document_identifier(reference)
        primary_document = self._get_primary_document_component(reference)
        target_information = (
            primary_document[1].get("information", "")
            if primary_document is not None
            else ""
        )
        target_family = (
            self._extract_administrative_authority_family(target_identifier)
            or self._extract_administrative_authority_family(target_information)
        )

        if (
            relation_type in self.STRONG_ACTION_TARGET_RELATION_TYPES
            and target_info.get("doc_type") in self.DECISION_DOCUMENT_TYPES
            and (
                source_family := self._extract_administrative_authority_family(
                    source_so_hieu
                )
            )
            and source_family
            == target_family
        ):
            return False

        if (
            relation_type in self.STRONG_ACTION_TARGET_RELATION_TYPES
            and source_info.get("doc_type") in self.RESOLUTION_DOCUMENT_TYPES
            and target_info.get("doc_type") == "nghidinh"
            and source_info.get("authority_rank") == target_info.get("authority_rank")
        ):
            return False

        if relation_type in self.DETAIL_GUIDANCE_RELATION_TYPES:
            # Non-normative docs (no year in number, e.g. 706/QĐ-BXD) cannot guide or
            # detail normative VBQPPL, and vice versa.
            if not source_is_normative and target_is_normative:
                return True
            if source_is_normative and not target_is_normative:
                return True
            source_level = source_info.get("authority_rank") or source_info.get("type_rank")
            target_level = target_info.get("authority_rank") or target_info.get("type_rank")
            if source_level is not None and source_level == target_level:
                return True

        # bai_bo from a non-normative/non-regulatory source to a normative target:
        # only bai_bo is restricted here, since most other action types (dinh_chinh,
        # sua_doi_bo_sung, …) legitimately cross non-standard-format documents.
        if (
            relation_type == "bai_bo"
            and source_doc_type not in self.REGULATORY_DOCUMENT_KEYS
            and not source_info.get("is_regulatory")
            and target_info.get("is_regulatory")
        ):
            if (
                self._is_local_document_identifier(source_so_hieu)
                and self._is_local_document_identifier(target_identifier)
            ):
                return False
            if self._is_same_administrative_authority_decision(
                source_so_hieu=source_so_hieu,
                target_identifier=target_identifier,
                source_info=source_info,
                target_info=target_info,
            ):
                return False
            return True

        if hierarchy_direction == "source_higher":
            return relation_type in self.UPPER_TO_LOWER_RESTRICTED_RELATIONS
        if hierarchy_direction == "source_lower":
            return relation_type in self.LOWER_TO_UPPER_RESTRICTED_RELATIONS

        return False

    @classmethod
    def _extract_year_from_identifier(cls, identifier: Optional[str]) -> Optional[int]:
        """Return the 4-digit issuance year embedded in a document identifier, or None.

        The issuance year appears either as the middle "/YYYY/" segment of a
        "<serial>/<year>/<authority>" document number (e.g. 24/2014/NĐ-CP), or
        after "năm" in a date phrase (e.g. "... ngày 09 tháng 01 năm 2019").
        A leading 4-digit serial number (e.g. 1077/QĐ-UBND) is not a year.
        """
        normalized = cls._normalize_authority_policy_text(identifier)
        if not normalized:
            return None
        match = re.search(r"(?<=/)(\d{4})(?=/)", normalized)
        if not match:
            match = re.search(r"NAM\s+(\d{4})", normalized)
        return int(match.group(1)) if match else None

    def _extract_document_number_anatomy(self, identifier: Optional[str]) -> Dict:
        """Return {doc_type, authority_suffix, year, level, is_normative} for an identifier.

        Handles serial numbers (e.g. 24/2014/NĐ-CP) and title-only references
        (e.g. 'Luật An toàn thực phẩm').
        """
        doc_type_key: Optional[str] = None
        if identifier:
            norm = self._normalize_authority_policy_text(identifier)
            if norm.startswith("BO LUAT"):
                doc_type_key = "boluat"
            elif norm.startswith("HIEN PHAP"):
                doc_type_key = "hienphap"
            elif norm.startswith("PHAP LENH"):
                doc_type_key = "phaplenh"
            elif norm.startswith("LUAT ") or norm == "LUAT":
                doc_type_key = "luat"

        base_info = self._build_authority_policy_doc_info(identifier, doc_type_key=doc_type_key)

        year = self._extract_year_from_identifier(identifier)

        authority_suffix: Optional[str] = None
        if identifier:
            norm = self._normalize_authority_policy_text(identifier)
            if "/" in norm:
                last_seg = norm.rsplit("/", 1)[1]
                if "-" in last_seg:
                    authority_suffix = last_seg.rsplit("-", 1)[1] or None
                else:
                    authority_suffix = last_seg or None
            if authority_suffix:
                # Strip the legislature-term digits from QH/UBTVQH suffixes
                # (e.g. "QH14" -> "QH", "UBTVQH15" -> "UBTVQH"): the issuing
                # authority (Quoc hoi) is the same across terms.
                term_match = re.match(r"^(QH|UBTVQH)\d{1,3}$", authority_suffix)
                if term_match:
                    authority_suffix = term_match.group(1)

        authority_rank = base_info.get("authority_rank")
        type_rank = base_info.get("type_rank")
        level = authority_rank if authority_rank is not None else type_rank

        return {
            "doc_type": base_info["doc_type"],
            "authority_suffix": authority_suffix,
            "year": year,
            "level": level,
            "is_normative": base_info["is_regulatory"],
        }

    def _is_same_type_and_authority(
        self,
        source_so_hieu: Optional[str],
        reference: Dict,
    ) -> bool:
        """Return True when source and target share the same doc type and issuing authority.

        Both doc_type and authority_suffix must be non-None and equal.  Missing either
        on either side returns False (cautious — cannot confirm equivalence).
        """
        source_anatomy = self._extract_document_number_anatomy(source_so_hieu)
        source_type = source_anatomy.get("doc_type")
        source_authority = source_anatomy.get("authority_suffix")
        if not source_type or not source_authority:
            return False

        target_identifier = self._extract_reference_document_identifier(reference)
        target_anatomy = self._extract_document_number_anatomy(target_identifier)
        target_type = target_anatomy.get("doc_type")
        target_authority = target_anatomy.get("authority_suffix")
        if not target_type or not target_authority:
            return False

        return source_type == target_type and source_authority == target_authority

    def _extract_reference_document_identifier(self, reference: Dict) -> Optional[str]:
        """Extract the primary document identifier from a matched reference."""
        primary_document = self._get_primary_document_component(reference)
        if primary_document is None:
            return None

        doc_key, doc_info = primary_document
        information = doc_info.get("information", "")
        if not information:
            return None

        number_match = self._find_doc_number_match(information, doc_key)
        if number_match:
            return self._normalize_document_number(number_match.group())

        return information.strip()

    def _is_inherently_central_reference(self, reference: Dict) -> bool:
        """Return True when the reference is of a type that is exclusively central."""
        primary = self._get_primary_document_component(reference)
        if not primary:
            return False

        doc_key, _ = primary
        return doc_key in LAW_DOCUMENT_KEYS

    def _should_filter_local_to_central_match(
        self,
        relation_type: str,
        source_so_hieu: Optional[str],
        reference: Dict
    ) -> bool:
        """Apply the authority filter for local documents acting on central ones."""
        if self._should_filter_by_authority_policy(
            relation_type=relation_type,
            source_so_hieu=source_so_hieu,
            reference=reference,
        ):
            return True

        if relation_type not in self.RESTRICTED_LOCAL_TO_CENTRAL_RELATIONS:
            return False

        if not self._is_local_document_identifier(source_so_hieu):
            return False

        if self._is_inherently_central_reference(reference):
            return True

        target_identifier = self._extract_reference_document_identifier(reference)
        if not target_identifier:
            return False

        return not self._is_local_document_identifier(target_identifier)
