import functools
import re
from typing import Dict, List
from src.infrastructure.config import get_config_loader
from src.domain.model.relation_types import ALL_RELATION_TYPES


# ── Static patterns (no config dependency) ──────────────────────────────────

PASSIVE_VOICE_RELATION_PATTERNS: Dict[str, List[str]] = {
    "sua_doi_bo_sung": [
        r"được\s+sửa\s+đổi\s*,\s*bổ\s+sung",
        r"được\s+sửa\s+đổi",
        r"được\s+bổ\s+sung"
    ]
}

COMPILED_PASSIVE_PATTERNS = {
    rel_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for rel_type, patterns in PASSIVE_VOICE_RELATION_PATTERNS.items()
}

SEGMENT_DELIMITER_PATTERN = re.compile(r'[,.;]|\bvà\b|\bhoặc\b', re.IGNORECASE)

SCOPE_DELIMITERS = (".", ";", "\n")

DAN_CHIEU_DESCRIPTIVE_ACTION_EXCLUSIONS = (
    r"\bviệc\s+đình\s+chỉ\s+công\s+tác\b",
)

_BAI_BO_EDGE_CASE_1 = r"hết\s+hiệu\s+lực(?:\s+thi\s+hành)?(?:\s+(?:kể\s+)?từ\s+ngày)?"
BAI_BO_EDGE_CASE_PATTERNS = rf"(?:{_BAI_BO_EDGE_CASE_1})"
COMPILED_BAI_BO_EDGE_CASE_PATTERN = re.compile(BAI_BO_EDGE_CASE_PATTERNS, re.IGNORECASE)


# ── Config-dependent patterns (lazy, built on first access) ──────────────────
#
# FORWARD_RELATION_PATTERNS, COMPILED_FORWARD_PATTERNS, DAN_CHIEU_EXCLUSIONS,
# and COMPILED_THAY_THE_EDGE_CASE_PATTERN embed doc/clause type strings that
# come from doc_and_clause_types.yml via ConfigLoader.  Building them at import
# time forces YAML + CSV loading for every test that touches this module.
# Instead they are built lazily the first time any of these names is accessed,
# via Python's module-level __getattr__ hook backed by an lru_cache builder.

@functools.lru_cache(maxsize=1)
def _build_config_dependent_patterns() -> Dict:
    """Build all config-dependent pattern objects (called at most once)."""
    doc_types = get_config_loader().doc_clause_types["doc_types"]
    clause_types = get_config_loader().doc_clause_types["clause_types"]
    doc_clause_types = (
        r"(?:" + "|".join(re.escape(x) for x in clause_types + doc_types) + r")"
    )

    forward_patterns: Dict[str, List[str]] = {
        "sua_doi_bo_sung": [
            r"sửa\s+đổi\s*,\s*bổ\s+sung",
            r"sửa\s+đổi\s+và\s+bổ\s+sung",
            r"sửa\s+đổi",
            r"bổ\s+sung",
            r"bãi\s+bỏ\s+các\s+cụm\s+từ",
            r"bãi\s+bỏ\s+cụm\s+từ",
            r"bãi\s+bỏ\s+từ",
            r"bỏ\s+các\s+cụm\s+từ",
            r"bỏ\s+cụm\s+từ",
            r"bỏ\s+từ",
            r"thay\s+(?:các\s+)?cụm\s+từ",
            r"thay\s+từ",
            r"thay\s+thế\s+các\s+cụm\s+từ",
            r"thay\s+thế\s+cụm\s+từ",
            r"thay\s+thế\s+từ",
            r"thay\s+thế\s+(?:các\s+)?(?:danh\s+mục|phụ\s+lục|mẫu(?:\s+số)?|biểu\s+mẫu)",
            rf"điều\s+chỉnh(?=\s+(?:{doc_clause_types}))",
            r"bãi\s+bỏ\s+một\s+phần",
            r"bãi\s+bỏ\s+một\s+số\s+điều",
            r"bãi\s+bỏ\s+mục\s+(?:[ivxlcdm]+|\d+)\b",
            r"điều\s+chỉnh\s*,\s*bổ\s+sung",
            r"bãi\s+bỏ\s+một\s+số",
            r"thay\s+thế\s+một\s+số",
            r"bãi\s+bỏ\s*,\s*thay\s+thế\s+một\s+số",
            r"bãi\s+bỏ\s*,\s*thay\s+thế\s+một\s+phần",
            r"bãi\s+bỏ\s*,\s*thay\s+thế\s+các\s+cụm\s+từ",
            r"bãi\s+bỏ\s*,\s*thay\s+thế\s+các\s+điều",
            r"bãi\s+bỏ\s*,\s*thay\s+thế\s+cụm\s+từ",
            r"thay\s+thế\s*,\s*bãi\s+bỏ\s+một\s+số",
            r"thay\s+thế\s*,\s*bãi\s+bỏ\s+một\s+phần",
            r"thay\s+thế\s*,\s*bãi\s+bỏ\s+các\s+cụm\s+từ",
            r"thay\s+thế\s*,\s*bãi\s+bỏ\s+các\s+điều",
            r"thay\s+thế\s*,\s*bãi\s+bỏ\s+cụm\s+từ"
        ],
        "thay_the": [
            r"thay\s+thế"
        ],
        "bai_bo": [
            r"bãi\s+bỏ\s+toàn\s+bộ",
            r"bãi\s+bỏ",
            r"chấm\s+dứt\s+hiệu\s+lực",
            r"thu\s+hồi"
        ],
        "huy_bo": [
            r"hủy\s+bỏ",
            r"thu\s+hồi\s*,\s*hủy\s+bỏ",
            r"thu\s+hồi\s+và\s+hủy\s+bỏ"
        ],
        "dinh_chinh": [
            r"đính\s+chính\s+lỗi\s+kỹ\s+thuật",
            r"đính\s+chính\s+sai\s+sót",
            r"đính\s+chính\s+nội\s+dung",
            r"đính\s+chính",
            r"sửa\s+cụm\s+từ",
            r"sửa\s+tiêu\s+đề"
        ],
        "dinh_chi": [
            r"đình\s+chỉ\s+hiệu\s+lực\s+thi\s+hành",
            r"đình\s+chỉ\s+việc\s+thi\s+hành",
            r"đình\s+chỉ\s+thi\s+hành",
            r"tạm\s+đình\s+chỉ\s+thi\s+hành",
            r"tạm\s+đình\s+chỉ\s+hiệu\s+lực"
        ],
        "ngung_hieu_luc": [
            r"ngưng\s+hiệu\s+lực\s+thi\s+hành",
            r"ngưng\s+hiệu\s+lực\s+toàn\s+bộ",
            r"ngưng\s+hiệu\s+lực"
        ],
        "keo_dai_hieu_luc": [
            r"thống\s+nhất\s+tiếp\s+tục\s+kéo\s+dài\s+thời\s+gian",
            r"thống\s+nhất\s+tiếp\s+tục\s+kéo\s+dài\s+thời\s+hạn",
            r"thống\s+nhất\s+tiếp\s+tục\s+kéo\s+dài\s+hiệu\s+lực",
            r"kéo\s+dài\s+hiệu\s+lực",
            r"kéo\s+dài\s+thời\s+gian",
            r"kéo\s+dài\s+thời\s+hạn"
        ],
        "quy_dinh_chi_tiet": [
            r"quy\s+định\s+chi\s+tiết\s+và\s+hướng\s+dẫn\s+thi\s+hành",
            r"quy\s+định\s+chi\s+tiết"
        ],
        "huong_dan": [
            r"hướng\s+dẫn\s+thi\s+hành",
            r"hướng\s+dẫn\s+thực\s+hiện",
            r"hướng\s+dẫn\s+áp\s+dụng"
        ],
        "dan_chieu": [
            rf"\btheo\s+đúng\s+quy\s+định\s+của\s+{doc_clause_types}\b",
            rf"\btheo\s+quy\s+định\s+của\s+{doc_clause_types}\b",
            r"\btheo\s+(?:các\s+)?quy\s+định\s+tại\s+chương\b",
            rf"\btheo\s+các\s+quy\s+định\s+tại\s+{doc_clause_types}\b",
            rf"\btheo\s+quy\s+định\s+tại\s+{doc_clause_types}\b",
            rf"\btheo\s+quy\s+định\s+{doc_clause_types}\b",
            rf"\bquy\s+định\s+tại\s+{doc_clause_types}\b",
            rf"\bđược\s+quy\s+định\s+trong\s+{doc_clause_types}\b",
            rf"\bđược\s+quy\s+định\s+tại\s+{doc_clause_types}\b",
            rf"\bthuộc\s+phạm\s+vi\s+điều\s+chỉnh\s+của\s+{doc_clause_types}\b",
            rf"\btrên\s+cơ\s+sở\s+{doc_clause_types}\b",
            r"\btiếp\s+tục\s+có\s+hiệu\s+lực(?:\s+thi\s+hành)?\b",
            rf"\btheo\s+{doc_clause_types}\b",
            rf"\btại\s+{doc_clause_types}\b"
        ]
    }

    unknown = set(forward_patterns.keys()) - ALL_RELATION_TYPES
    assert not unknown, (
        f"FORWARD_RELATION_PATTERNS contains relation types not in ALL_RELATION_TYPES: {unknown}"
    )

    compiled_forward = {
        rel_type: [re.compile(p, re.IGNORECASE) for p in patterns]
        for rel_type, patterns in forward_patterns.items()
    }

    dan_chieu_exclusions = (
        rf"\b(?:ban\s+hành\s+)?(?:kèm\s+)?(?:theo\s+)?(?:tại\s+)?{doc_clause_types}"
    )

    doc_types_pattern = r"(?:" + "|".join(re.escape(x) for x in doc_types) + r")"
    thay_the_1 = (
        rf"hết\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:kể\s+)?từ\s+ngày\s+"
        rf"{doc_types_pattern}\s+này\s+có\s+hiệu\s+lực\s+thi\s+hành"
    )
    thay_the_2 = r"có\s+hiệu\s+lực\s+thi\s+hành\s+đến\s+hết\s+ngày"
    thay_the_3 = (
        r"hết\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:kể\s+)?từ\s+ngày\s+"
        r"nghị\s+quyết(?:\s+liên\s+tịch)?\s+này\s+có\s+hiệu\s+lực"
    )
    thay_the_4 = (
        r"hết\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:kể\s+)?từ\s+ngày\s+"
        r"nghị\s+định\s+này\s+có\s+hiệu\s+lực\b"
    )
    thay_the_patterns = (
        rf"(?:{thay_the_1})|(?:{thay_the_2})|(?:{thay_the_3})|(?:{thay_the_4})"
    )
    compiled_thay_the = re.compile(thay_the_patterns, re.IGNORECASE)

    return {
        "FORWARD_RELATION_PATTERNS": forward_patterns,
        "COMPILED_FORWARD_PATTERNS": compiled_forward,
        "DAN_CHIEU_EXCLUSIONS": dan_chieu_exclusions,
        "COMPILED_THAY_THE_EDGE_CASE_PATTERN": compiled_thay_the,
    }


_CONFIG_DEPENDENT_NAMES = frozenset({
    "FORWARD_RELATION_PATTERNS",
    "COMPILED_FORWARD_PATTERNS",
    "DAN_CHIEU_EXCLUSIONS",
    "COMPILED_THAY_THE_EDGE_CASE_PATTERN",
})


def __getattr__(name: str):
    if name in _CONFIG_DEPENDENT_NAMES:
        return _build_config_dependent_patterns()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
