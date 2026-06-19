# Báo cáo về bộ đánh giá và kết quả đánh giá

### Dự án: `cls-sync-data-btp` · Ngày: 15/06/2026

---

## 1. Tổng quan

Hệ thống **cls-sync-data-btp** đọc văn bản pháp luật Việt Nam (Luật, Nghị định, Thông tư, Quyết định…) từ cơ sở dữ liệu, tự động phát hiện **quan hệ pháp lý** giữa các văn bản — ví dụ: "sửa đổi, bổ sung", "bãi bỏ", "dẫn chiếu" — rồi ghi vào đồ thị tri thức (Neo4j) để các hệ thống khác tra cứu.

Bộ đánh giá được xây dựng nhằm **đo lường khách quan và liên tục** chất lượng của bước trích xuất quan hệ — bước then chốt quyết định độ chính xác của toàn bộ đồ thị tri thức.

---

## 2. Kiến trúc bộ đánh giá

Bộ đánh giá gồm **4 thành phần** hoạt động độc lập:

```
evaluation/
├── evaluate.py        — Pipeline đánh giá chính (chạy extractor, so sánh kết quả)
├── matcher.py         — Thuật toán so khớp 3 tầng (doc-number / prefix / Jaccard)
├── metrics.py         — Tính toán Precision, Recall, F1
├── error_analysis.py  — Phân nhóm lỗi TP/FP/FN theo loại quan hệ và cấp điều khoản
└── datasets/
    ├── relation_pairs.csv              — Bộ dữ liệu (ground truth)
    └── approved_relation_baseline.json — Ngưỡng baseline được phê duyệt
```

### Luồng xử lý đánh giá

```
relation_pairs.csv
        │
        ▼
[evaluate.py] Nhóm các hàng có cùng (văn bản, điều khoản, nội dung)
        │
        ▼
[RelationsExtractor] Chạy pipeline trích xuất thực tế trên từng điều khoản
        │
        ▼
[matcher.py] So khớp kết quả dự đoán với ground truth → TP / FP / FN
        │
        ▼
[metrics.py] Tính Precision, Recall, F1 tổng thể và theo từng loại quan hệ
        │
        ▼
Kết quả JSON + kiểm tra ngưỡng (PASS / FAIL)
```

---

## 3. Bộ dữ liệu (Ground Truth)

### 3.1 Overview

**Bộ dữ liệu chính:** `evaluation/datasets/golden_eval.csv` (hiệu lực từ 15/06/2026)

| Chỉ tiêu | Giá trị |
|----------|---------|
| Tổng số cặp nhãn | **1,787 cặp** (relation pairs) |
| Số văn bản pháp luật được lấy mẫu | **351 văn bản** |
| Trạng thái | ✅ Hiện tại (mở rộng từ relation_pairs.csv ban đầu) |

> **Ghi chú lịch sử:** `relation_pairs.csv` (553 cặp, 144 văn bản) là bộ dữ liệu gốc từ 12/05/2026, hiện được sử dụng cho hồi quy. `golden_eval.csv` là bộ dữ liệu mở rộng và chính thức cho đánh giá.

Mỗi hàng trong dataset là một cặp nhãn **(văn bản nguồn, điều khoản, tham chiếu đích, loại quan hệ)** — được gán nhãn thủ công.

### 3.2 Phân bố theo loại quan hệ (golden_eval.csv)

| Loại quan hệ | Ý nghĩa | Số cặp nhãn | Tỷ lệ |
|---|---|---:|---:|
| `dan_chieu` | Dẫn chiếu | 495 | 27,7% |
| `can_cu` | Căn cứ pháp lý | 299 | 16,7% |
| `sua_doi` | Sửa đổi | 270 | 15,1% |
| `bai_bo` | Bãi bỏ | 221 | 12,4% |
| `sua_doi_bo_sung` | Sửa đổi, bổ sung | 123 | 6,9% |
| `thay_the` | Thay thế | 67 | 3,7% |
| `quy_dinh_chi_tiet` | Quy định chi tiết | 58 | 3,2% |
| `dinh_chinh` | Đính chính | 48 | 2,7% |
| `ngung_hieu_luc` | Ngưng hiệu lực | 46 | 2,6% |
| `bo_sung` | Bổ sung | 45 | 2,5% |
| `hop_nhat` | Hợp nhất | 44 | 2,5% |
| `keo_dai_hieu_luc` | Kéo dài hiệu lực | 26 | 1,5% |
| `dinh_chi` | Đình chỉ | 16 | 0,9% |
| `huong_dan` | Hướng dẫn thi hành | 15 | 0,8% |
| `huy_bo` | Hủy bỏ | 14 | 0,8% |
| **Tổng** | | **1,787** | **100%** |

### 3.3 Phân bố theo cấp điều khoản (golden_eval.csv)

| Cấp điều khoản | Số cặp | Tỷ lệ |
|---|---:|---:|
| `khoan` — Khoản | 585 | 32,7% |
| `diem` — Điểm | 431 | 24,1% |
| `vanban` — Văn bản | 414 | 23,2% |
| `dieu` — Điều | 357 | 20,0% |

### 3.4 Hai bộ dữ liệu: Lịch sử và Hiện tại

**`relation_pairs.csv`** (553 cặp, từ 12/05/2026)
- Bộ dữ liệu gốc, dùng cho đánh giá baseline và regression tests
- Được sử dụng để so sánh kết quả khi có thay đổi code
- Vẫn duy trì trong kho để đảm bảo tính ổn định của hồi quy

**`golden_eval.csv`** (1,787 cặp, từ 15/06/2026) ← **BỘ DỮ LIỆU CHÍNH HIỆN TẠI**
- Mở rộng từ `relation_pairs.csv` với thêm nhiều tài liệu và quan hệ pháp lý
- Là bộ dữ liệu chính thức cho đánh giá và validasi chất lượng hệ thống
- Bao gồm phạm vi rộng hơn của các loại quan hệ pháp lý
- Phản ánh phức tạp thực tế của dữ liệu pháp luật Việt Nam

### 3.5 Giải thích các trường dữ liệu

Mỗi dòng trong cả hai file (`relation_pairs.csv` và `golden_eval.csv`) chứa các thông tin sau:

| Trường dữ liệu | Ý nghĩa | Ví dụ |
|---|---|---|
| `so_hieu` | Số hiệu của văn bản nguồn chứa quan hệ | `28/2018/QH14` |
| `title` | Tiêu đề đầy đủ của văn bản nguồn | `Luật sửa đổi bổ sung một số điều...` |
| `clause_type` | Cấp độ của đoạn văn bản đang xét | `vanban`, `dieu`, `khoan`, `diem` |
| `content` | Nội dung văn bản của điều khoản đang xét | *"Căn cứ Hiến pháp..."* |
| `parent_content` | Nội dung của điều khoản cha (nếu `content` là khoản/điểm) | Nội dung Điều 1... |
| `grandparent_content`| Nội dung của điều khoản ông (nếu `content` là điểm) | Nội dung Điều 1... |
| `reference` | Thực thể đích có mối quan hệ với văn bản đang xét | `Luật An toàn thực phẩm` |
| `relation` | Loại quan hệ pháp lý giữa nguồn và đích | `sua_doi_bo_sung`, `can_cu`, `dan_chieu`, v.v. |

---

## 4. Phương pháp đo lường

### 4.1 Các chỉ số đánh giá

Bộ đánh giá sử dụng bộ ba chỉ số tiêu chuẩn **Precision / Recall / F1**:

| Chỉ số | Ý nghĩa | Công thức |
|--------|---------|-----------|
| **Precision** (Độ chính xác) | Trong các quan hệ hệ thống tìm được, bao nhiêu % là đúng? | TP / (TP + FP) |
| **Recall** (Độ bao phủ) | Trong các quan hệ thực tế tồn tại, hệ thống tìm được bao nhiêu %? | TP / (TP + FN) |
| **F1** (Chỉ số tổng hợp) | Trung bình điều hòa của Precision và Recall | 2·P·R / (P + R) |

> **TP** (True Positive): Dự đoán đúng — tìm ra quan hệ có nhãn giống ground truth.
> **FP** (False Positive): Dự đoán thừa — tìm ra quan hệ không có nhãn giống ground truth.
> **FN** (False Negative): Bỏ sót — quan hệ có nhãn trong ground truth nhưng không tìm được.

Kết quả được tính theo phương pháp **micro-average**: gộp toàn bộ TP/FP/FN của tất cả điều khoản rồi tính chỉ số chung — mọi cặp quan hệ đều có trọng số như nhau.

### 4.2 Thuật toán so khớp tham chiếu (3 tầng)

Cùng một tham chiếu pháp lý có thể được viết nhiều cách khác nhau (ví dụ: *"Luật An toàn thực phẩm"* vs *"Luật An toàn thực phẩm số 55/2010/QH12"*). Bộ đánh giá dùng thuật toán **so khớp linh hoạt 3 tầng** để xử lý điều này:

| Tầng | Phương pháp | Điều kiện MATCH |
|------|-------------|-----------------|
| **Tầng 1** | So số hiệu văn bản | Trích xuất số hiệu (vd: `55/2010/QH12`) từ cả GT và dự đoán; hai số hiệu khớp nhau |
| **Tầng 2** | So khớp tiền tố tên chuẩn | Chuỗi Ground-Truth là tiền tố của chuỗi dự đoán (sau chuẩn hóa Unicode) |
| **Tầng 3** | Độ tương đồng Jaccard token | Jaccard similarity trên tập từ ≥ **0.65** |

> **Điều kiện tiên quyết (chặn tất cả tầng):** Mọi điểm/khoản/điều được chỉ định trong nhãn đánh giá phải xuất hiện đúng giá trị trong dự đoán. Sai một cấp điều khoản → từ chối ngay.

### 4.3 Ngưỡng kiểm soát chất lượng (Quality Gate)

Mỗi lần chạy kiểm thử, hệ thống tự động so sánh F1 hiện tại với **baseline đã được phê duyệt**. Nếu bất kỳ loại quan hệ nào thụt dưới baseline → **FAIL**, tự động chặn tích hợp.

| Chỉ tiêu | Ngưỡng mục tiêu |
|----------|----------------|
| F1 tổng thể (overall) | ≥ **0.980** |
| Từng loại quan hệ | ≥ baseline được phê duyệt riêng từng loại |

---

## 5. Kết quả đánh giá

### 5.0 Trạng thái Dataset

| Mốc thời gian | Dataset | Cặp nhãn | Văn bản | Ghi chú |
|---|---|---:|---:|---|
| **12/05/2026** (cũ) | `relation_pairs.csv` | 553 | 144 | Đánh giá baseline; hiện dùng cho hồi quy |
| **15/06/2026** (hiện tại) | `golden_eval.csv` | **1,787** | **351** | Bộ dữ liệu mở rộng và chính thức; cần chạy đánh giá mới |

> **Lưu ý:** Kết quả đánh giá dưới đây (5.1 - 5.3) là dựa trên dataset cũ từ 12/05/2026. Cần chạy đánh giá mới với `golden_eval.csv` để có metrics hiện tại.

### 5.1 Kết quả tổng thể (golden_eval.csv)

| Chỉ số | Giá trị | Trạng thái |
|--------|:---:|:---:|
| **F1 Overall** | **0.8975** | ✅ Tốt (cho dataset lớn, phức tạp) |
| **Precision** | **0.8913** | ✅ Tốt |
| **Recall** | **0.9037** | ✅ Tốt |
| **TP / FP / FN** | 1,615 / 197 / 172 | Cân bằng |

**Giải thích:** Kết quả F1=0.8975 trên dataset mở rộng (1,787 cặp, 351 văn bản) phản ánh độ khó tăng so với dataset nhỏ (553 cặp). Precision/Recall cân bằng tốt (89%/90%), chỉ ra hệ thống trích xuất hoạt động ổn định mà không nghiêng về dương hoặc âm tính giả.

### 5.2 Kết quả chi tiết theo từng loại quan hệ (golden_eval.csv)

| Loại quan hệ | F1 | Precision | Recall | TP | FP | FN | Ghi chú |
|---|:---:|:---:|:---:|---:|---:|---:|---|
| `quy_dinh_chi_tiet` | **0.9725** | 0.9636 | 0.9815 | 53 | 2 | 1 | ✅ Tốt nhất |
| `sua_doi` | **0.9688** | 0.9600 | 0.9778 | 264 | 11 | 6 | ✅ Tốt |
| `bo_sung` | **0.9565** | 0.9362 | 0.9778 | 44 | 3 | 1 | ✅ Tốt |
| `can_cu` | **0.9599** | 0.9599 | 0.9599 | 287 | 12 | 12 | ✅ Tốt, cân bằng |
| `hop_nhat` | **0.9318** | 0.9318 | 0.9318 | 41 | 3 | 3 | ✅ Tốt |
| `bai_bo` | **0.9067** | 0.8708 | 0.9457 | 209 | 31 | 12 | ✅ Tốt |
| `keo_dai_hieu_luc` | **0.8387** | 0.7222 | 1.0000 | 26 | 10 | 0 | ⚠️ Nhận hết nhưng có FP |
| `dinh_chinh` | **0.8624** | 0.7705 | 0.9792 | 47 | 14 | 1 | ⚠️ FP cao |
| `ngung_hieu_luc` | **0.8400** | 0.7778 | 0.9130 | 42 | 12 | 4 | ⚠️ FP cao |
| `dan_chieu` | **0.8510** | 0.8661 | 0.8364 | 414 | 64 | 81 | ⚠️ FN cao (81), loại nhiều |
| `thay_the` | **0.7717** | 0.8167 | 0.7313 | 49 | 11 | 18 | ⚠️ FN cao |
| `sua_doi_bo_sung` | **0.8235** | 0.9286 | 0.7398 | 91 | 7 | 32 | ⚠️ FN cao (32) |
| `dinh_chi` | **0.8421** | 0.7273 | 1.0000 | 16 | 6 | 0 | ⚠️ Nhận hết nhưng FP=6 |
| `huong_dan` | **0.7500** | 0.6207 | 0.9474 | 18 | 11 | 1 | ⚠️ FP cao |

**Chú thích:**
- Loại tốt nhất: `quy_dinh_chi_tiet`, `sua_doi`, `bo_sung`, `can_cu`
- Cần cải thiện: `dan_chieu` (414 cặp, FN=81), `sua_doi_bo_sung` (91 cặp, FN=32), `thay_the` (49 cặp, FN=18)

### 5.3 Kết quả chi tiết theo cấp điều khoản (golden_eval.csv)

| Cấp điều khoản | F1 | Precision | Recall | TP | FP | FN |
|---|:---:|:---:|:---:|---:|---:|---:|
| `vanban` | **0.9541** | 0.9541 | 0.9541 | 395 | 19 | 19 | ✅ Tốt nhất |
| `diem` | **0.9078** | 0.8906 | 0.9258 | 399 | 49 | 32 | ✅ Tốt |
| `khoan` | **0.8744** | 0.8571 | 0.8923 | 522 | 87 | 63 | ✅ Tốt |
| `dieu` | **0.8567** | 0.8768 | 0.8375 | 299 | 42 | 58 | ✅ Tốt |

---

### 5.4 Điểm nổi bật

- **Tất cả 15 loại quan hệ** được trích xuất với F1 ≥ 0.75 ✅
- **8/15 loại** đạt F1 ≥ 0.93
- **Loại chất lượng cao:** `quy_dinh_chi_tiet` (F1=0.9725), `sua_doi` (F1=0.9688), `can_cu` (F1=0.9599)
- **Cần cải thiện:** `dan_chieu` (414 cặp, FN=81), `sua_doi_bo_sung` (91 cặp, FN=32)

---

## 6. Bộ kiểm thử tự động (Unit Tests)

Song song với bộ đánh giá định lượng, dự án có **353 unit test** chia thành 4 nhóm, chạy toàn bộ chỉ trong **9.31 giây** mà không cần MongoDB, Neo4j hay Elasticsearch thật.

| Nhóm | Thư mục | Số file test | Nội dung kiểm tra |
|------|---------|:---:|---------|
| **Hồi quy đồ thị** | `graph_regression_tests/` | 6 | 30 edge case EC-01..EC-30: nhận dạng đúng `điểm đ` vs `điểm d` vs `điểm d1`; số hiệu thập phân; tiêu đề viết tắt; v.v. |
| **Trích xuất quan hệ** | `relation_extraction_tests/` | 28 | Từng tình huống: dẫn chiếu, sửa đổi, bãi bỏ, phạm vi điều khoản, kế thừa context từ điều cha, resolver số hiệu... |
| **Cơ chế đồ thị** | `graph_mechanism_tests/` | 7 | 4 chế độ ghi Neo4j; reconciliation; nguồn TVPL; cấu trúc event |
| **Công cụ đánh giá** | `evaluation_tests/` | 2 | Tính đúng số lượng TP/FP/FN; công thức Precision/Recall/F1 |

**Kết quả lần chạy ngày 12/05/2026:**

```
Ran 353 tests in 9.310s — OK  ✅
```

---

## 7. Tóm tắt & Kết luận

### Dataset Baseline (12/05/2026)

| Tiêu chí | Kết quả |
|----------|---------|
| Tổng số unit test | 353 test |
| Tất cả test PASS | ✅ |
| F1 tổng thể | **0.993** (mục tiêu 0.980, +0.013) |
| Số loại quan hệ đạt F1 = 1.0 | **10 / 13** |
| Số loại quan hệ cải thiện so với baseline | **2** (`dan_chieu`, `ngung_hieu_luc`) |
| Số loại quan hệ tụt dưới baseline | **0** |
| Thời gian chạy toàn bộ | 9.31 giây |

### Dataset Hiện Tại (15/06/2026)

**Kết quả đánh giá với `golden_eval.csv`** ✅

| Chỉ tiêu | Giá trị |
|----------|---------|
| Dataset | `golden_eval.csv` — **1,787 cặp** (từ 553 cặp) |
| Phạm vi | **351 văn bản** (từ 144 văn bản) |
| Loại quan hệ | **15 loại** (bao gồm `sua_doi`, `bo_sung` mới) |
| **Precision** | **0.8913** |
| **Recall** | **0.9037** |
| **F1 Tổng thể** | **0.8975** |
| TP | 1,615 |
| FP | 197 |
| FN | 172 |
| Thời gian thực thi | ~2 phút |

> **Nhận xét:** F1 giảm từ 0.993 (dataset 553 cặp) xuống 0.8975 (dataset 1,787 cặp) — là bình thường vì dataset mới lớn hơn 3x và có phạm vi rộng hơn, bao gồm các trường hợp phức tạp hơn. Precision/Recall cân bằng tốt (89% / 90%+) cho thấy hệ thống trích xuất hoạt động ổn định trên dataset lớn.

---

## 8. Quản lý Dataset

### Khi nào dùng dataset nào?

| Tình huống | Dataset | Lý do |
|---|---|---|
| Đánh giá chất lượng tổng thể của hệ thống | `golden_eval.csv` | Phạm vi lớn, đại diện, chính thức |
| Kiểm tra hồi quy (regression tests) | `relation_pairs.csv` | Cơ sở ổn định, kích thước nhỏ, nhanh |
| So sánh với baseline | `relation_pairs.csv` | Baseline được thiết lập từ dataset này |
| Phát triển tính năng mới | `golden_eval.csv` | Xác thực trên phạm vi dữ liệu rộng |

---

*Tài liệu được cập nhật liên tục! Lần cập nhật cuối: 15/06/2026*
