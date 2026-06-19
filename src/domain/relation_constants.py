"""Shared constants for document relation extraction and processing."""

SEARCHABLE_CLAUSE_TYPES = (
    'dieu',
    'khoan',
    'diem',
)

SEARCHABLE_CLAUSE_TYPE_SET = frozenset(SEARCHABLE_CLAUSE_TYPES)

# Mapping of component keys to their standardized names
RELATION_COMPONENT_NAME_MAPPING = {
    'vanban': 'vanban',
    'dieu': 'dieu',
    'khoan': 'khoan',
    'diem': 'diem'
}

# Hierarchy of components for building target keys
RELATION_COMPONENT_HIERARCHY = {
    'vanban': ['vanban'],
    'dieu': ['dieu', 'vanban'],
    'khoan': ['khoan', 'dieu', 'vanban'],
    'diem': ['diem', 'khoan', 'dieu', 'vanban']
}
# Ordered list of component types from most specific to least specific
RELATION_COMPONENT_TYPES = (
    'diem',
    'khoan',
    'dieu',
    'vanban'
)

# Regex patterns to identify and remove prefixes from component values
RELATION_COMPONENT_PREFIX_PATTERNS = {
    'dieu': r'^điều\s+',
    'khoan': r'^khoản\s+',
    'diem': r'^điểm\s+',
    'vanban': r'^văn\s*bản\s+'
}

# Mapping relation types to Vietnamese descriptions
RELATION_DESCRIPTIONS = {
    'sua_doi_bo_sung': 'sửa đổi, bổ sung',
    'sua_doi': 'sửa đổi',
    'bo_sung': 'bổ sung',
    'thay_the': 'thay thế',
    'bai_bo': 'bãi bỏ',
    'huy_bo': 'hủy bỏ',
    'dinh_chi': 'đình chỉ',
    'dinh_chinh': 'đính chính',
    'huong_dan': 'hướng dẫn',
    'quy_dinh_chi_tiet': 'quy định chi tiết',
    'keo_dai_hieu_luc': 'kéo dài hiệu lực',
    'dan_chieu': 'dẫn chiếu',
    'ngung_hieu_luc': 'ngưng hiệu lực',
    'bao_gom_sau_bo_sung': 'bao gồm sau bổ sung',
}

# Mapping component types to Vietnamese names
COMPONENT_NAMES = {
    'dieu': 'Điều',
    'khoan': 'khoản',
    'diem': 'điểm',
    'dk': 'đính kèm',
    'bosung': 'bổ sung'
}

