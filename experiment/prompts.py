"""Prompts for the two LLM architectures.

The allowed relation-type list is sourced from the canonical
``relation_types`` module so it can never drift from the rest of the system.
The anti-false-positive rules reuse the domain knowledge already encoded in
``src/domain/llms/prompts.py`` (passive history = metadata, self-reference,
name-as-keyword) rather than re-deriving it.
"""

from __future__ import annotations

from typing import List

from src.domain.model.relation_types import ALL_RELATION_TYPES

# A1 must be allowed to emit the SAME label space the gold uses, otherwise it
# is auto-penalised for type granularity it never had the option to produce.
# Gold distinguishes clause-level ``sua_doi``/``bo_sung`` from doc-level
# ``sua_doi_bo_sung``; ``bao_gom_sau_bo_sung`` is a graph-internal structural
# edge that never appears as an extraction target, so it is excluded.
EXTRACTION_LABELS = tuple(sorted(ALL_RELATION_TYPES - {"bao_gom_sau_bo_sung"}))
_ALLOWED = ", ".join(EXTRACTION_LABELS)

# Essential anti-false-positive rules (mirror the production LangExtract prompt).
_PRECISION_RULES = (
    "QUY TẮC CHỐNG NHẦM (bắt buộc):\n"
    "1. BỊ ĐỘNG = METADATA: cấu trúc 'đã được sửa đổi/bổ sung ... theo ...' mô tả LỊCH SỬ "
    "của văn bản, KHÔNG phải quan hệ do văn bản hiện tại tạo ra → BỎ QUA.\n"
    "2. TỰ THAM CHIẾU: 'Luật này', 'Nghị định này', 'Điều này', 'Thông tư này' → BỎ QUA.\n"
    "3. TÊN ≠ QUAN HỆ: cụm 'Luật sửa đổi, bổ sung một số điều của Luật X' chỉ là TÊN văn bản, "
    "không phải quan hệ. Chỉ trích khi có HÀNH ĐỘNG chủ động (vd 'Sửa đổi Điều 5 Luật X').\n"
    "4. ĐÍCH HỢP LỆ: đích phải là VĂN BẢN hoặc ĐIỀU/KHOẢN/ĐIỂM cụ thể, không phải chương/mục/phần "
    "hay cơ quan/chủ thể."
)


# --- A1: LLM as primary extractor -----------------------------------------
# Balanced (not precision-biased) so A1 is a fair "naive LLM extractor"
# baseline: brief type definitions tell the model what each relation means
# (e.g. a "Căn cứ ..." preamble line is a can_cu, and the three-way amendment
# granularity gold uses).
_TYPE_HINTS = (
    "Ý nghĩa loại quan hệ:\n"
    "- can_cu: dòng 'Căn cứ <văn bản>...' ở phần mở đầu (cơ sở pháp lý).\n"
    "- dan_chieu: dẫn chiếu/tham chiếu tới văn bản hay điều khoản khác.\n"
    "- sua_doi: sửa đổi một điều/khoản/điểm CỤ THỂ. bo_sung: bổ sung thêm một điều/khoản/điểm.\n"
    "- sua_doi_bo_sung: sửa đổi, bổ sung ở cấp VĂN BẢN (vd 'Luật này sửa đổi, bổ sung Luật X').\n"
    "- thay_the: thay thế. bai_bo/huy_bo: bãi bỏ/hủy bỏ. dinh_chi: đình chỉ.\n"
    "- dinh_chinh: đính chính. huong_dan: hướng dẫn thi hành.\n"
    "- quy_dinh_chi_tiet: quy định chi tiết. keo_dai_hieu_luc/ngung_hieu_luc: kéo dài/ngưng hiệu lực."
)

EXTRACTION_SYSTEM = (
    "Bạn là chuyên gia trích xuất quan hệ pháp lý trong văn bản quy phạm pháp luật Việt Nam. "
    "Trích MỌI quan hệ được nêu rõ trong đoạn (kể cả các dòng 'Căn cứ ...' ở phần mở đầu), "
    "mỗi văn bản/điều khoản đích là một quan hệ riêng.\n\n"
    f"Loại quan hệ cho phép: {_ALLOWED}.\n\n"
    f"{_TYPE_HINTS}\n\n"
    f"{_PRECISION_RULES}\n\n"
    "Chỉ trả về JSON: {\"relations\":[{\"type\":\"...\",\"target\":\"...\",\"evidence\":\"...\"}]}. "
    "Nếu không có quan hệ: {\"relations\":[]}. KHÔNG giải thích ngoài JSON."
)


def extraction_user(content: str, parent: str = "", grandparent: str = "") -> str:
    ctx = []
    if grandparent.strip():
        ctx.append(f"[Ngữ cảnh ông/bà] {grandparent.strip()}")
    if parent.strip():
        ctx.append(f"[Ngữ cảnh cha] {parent.strip()}")
    ctx.append(f"[Đoạn cần trích] {content.strip()}")
    return "\n".join(ctx)


# --- A3: LLM as conservative precision gate (false-positive detector) -------
# The rule system resolves document references using whole-document + external
# context (Elasticsearch, law_docs.csv) that this local span may not contain.
# So the gate trusts rules by DEFAULT and only rejects on positive *local*
# evidence of falseness. This abstain-to-keep stance is what protects recall;
# a "confirm every candidate" gate rejects everything it cannot locally see and
# destroys recall (verified empirically).
GATE_SYSTEM = (
    "Bạn kiểm tra một quan hệ pháp lý ỨNG VIÊN do HỆ THỐNG QUY TẮC đề xuất. Hệ thống quy tắc đã "
    "phân giải tên/đích văn bản bằng ngữ cảnh toàn văn bản mà BẠN CÓ THỂ KHÔNG THẤY trong đoạn này. "
    "Vì vậy hãy TIN hệ thống quy tắc theo MẶC ĐỊNH.\n\n"
    "Trả 'NO' CHỈ KHI đoạn nguồn có BẰNG CHỨNG RÕ RÀNG rằng quan hệ này SAI:\n"
    " (a) cấu trúc bị động/lịch sử: 'đã được sửa đổi, bổ sung ... theo ...';\n"
    " (b) tự tham chiếu: đích là 'Luật này/Nghị định này/Điều này';\n"
    " (c) cụm từ chỉ là TÊN văn bản, KHÔNG có động từ hành động pháp lý nào;\n"
    " (d) trong đoạn KHÔNG hề có từ khóa hành động phù hợp với loại quan hệ.\n"
    "Nếu đoạn có hành động pháp lý chủ động phù hợp (căn cứ, dẫn chiếu, sửa đổi, bãi bỏ, thay thế, "
    "đình chỉ, hướng dẫn, quy định chi tiết...) thì trả 'YES', kể cả khi đích không nêu đầy đủ ở đây.\n\n"
    "Chỉ trả JSON {\"verdict\":\"YES|NO\"}."
)


def gate_user(content: str, relation: str, target: str, parent: str = "", grandparent: str = "") -> str:
    ctx = []
    if grandparent.strip():
        ctx.append(f"[Ngữ cảnh ông/bà] {grandparent.strip()}")
    if parent.strip():
        ctx.append(f"[Ngữ cảnh cha] {parent.strip()}")
    ctx.append(f"[Đoạn nguồn] {content.strip()}")
    ctx.append(f"[Ứng viên] quan hệ '{relation}' tới '{target}'")
    return "\n".join(ctx)


def allowed_relation_types() -> List[str]:
    return list(EXTRACTION_LABELS)
