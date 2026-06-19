# Yêu cầu dữ liệu cho Offline Hybrid Relation Extraction

## 1. Kết luận về dữ liệu hiện tại

Dataset trong repo **chưa đủ để train mô hình production**.

| Nguồn hiện có | Quy mô | Dùng được cho | Chưa đủ cho |
|---|---:|---|---|
| `golden_eval.csv` | 1.787 relation, 351 văn bản, 719 clause | Benchmark, candidate-recall audit, prototype feature model | PhoBERT production, threshold theo từng relation |
| `distractor_candidates.csv` | 100 clause, 43 văn bản | Seed hard negatives | Học đầy đủ các kiểu false positive |
| `wrong_extraction_rules_only.csv` | 197 FP, 172 FN | Error taxonomy, bootstrap hard negatives | Training độc lập vì lấy từ chính benchmark |
| NER | 0 mẫu được gán nhãn | Không | Train/evaluate NER |
| Unlabeled legal corpus | Chưa export vào `training/` | Không | Domain-adaptive pretraining |

Phân bố relation hiện tại rất lệch. Các relation hiếm chỉ có:

- `huy_bo`: 14
- `huong_dan`: 15
- `dinh_chi`: 16
- `keo_dai_hieu_luc`: 26

Sau khi chia train/validation/test theo văn bản, mỗi relation hiếm chỉ còn vài mẫu
trong validation/test. Không thể ước lượng precision hoặc calibration theo relation.

Ngoài ra, 224/1.787 relation đến từ riêng văn bản `146/2025/QH15`. Số dòng vì vậy
không tương đương với 1.787 quan sát độc lập.

## 2. Đơn vị dữ liệu quan trọng nhất: candidate relation

Không train trực tiếp từ một dòng `(clause, gold relation)` rồi coi mọi cặp khác là
negative. Đơn vị train phải là:

```text
(source clause, action span, reference span, proposed relation, rule evidence)
    -> VALID / INVALID / UNKNOWN
```

Schema mẫu chỉ để mô tả format:

- `training/data/candidate_annotation_schema_example.jsonl`
- `training/data/ner_schema_example.jsonl`

Hai file trên có `EXAMPLE_ONLY`, **không được đưa vào train**.

### Field bắt buộc

```json
{
  "candidate_id": "stable unique id",
  "source_doc_id": "internal immutable id",
  "so_hieu": "10/2025/TT-BTC",
  "title": "...",
  "issue_date": "2025-01-10",
  "authority": "Bộ Tài chính",
  "doc_type": "thong_tu",
  "clause_key": "khoan_2_dieu_5",
  "clause_type": "khoan",
  "content": "...",
  "parent_content": "...",
  "grandparent_content": "...",
  "action_text": "bãi bỏ",
  "action_span": [12, 19],
  "reference_text": "Điều 5 Nghị định số ...",
  "reference_span": [25, 65],
  "proposed_relation": "bai_bo",
  "candidate_source": "production_match",
  "rule_id": "BAI_BO_FORWARD_02",
  "label": "VALID",
  "correct_relation": "bai_bo",
  "error_reason": null,
  "annotation_complete": true,
  "annotator_id": "expert_01",
  "adjudication_status": "ADJUDICATED"
}
```

### Ý nghĩa nhãn

- `VALID`: proposed relation và target reference đều đúng.
- `INVALID`: candidate sai; nên ghi thêm `error_reason`.
- `UNKNOWN`: ngữ cảnh thiếu, reference mơ hồ hoặc expert chưa thể kết luận.

Nếu relation đúng nhưng loại relation đề xuất sai:

- `label = INVALID`
- `correct_relation = <nhãn đúng>`
- `error_reason = WRONG_RELATION_TYPE`

## 3. Điều kiện bắt buộc để tạo negative

Một clause chỉ được dùng để suy ra negative khi `annotation_complete=true`, nghĩa là
expert đã xem **toàn bộ candidate pairs hợp lý trong clause**.

Nếu annotation hiện tại chỉ liệt kê positive mà không xác nhận tính đầy đủ:

- candidate khớp gold -> `VALID`
- candidate không khớp -> `UNKNOWN`
- không được tự động đổi thành `INVALID`

Nếu bỏ qua nguyên tắc này, model sẽ học false negative từ chính các relation bị bỏ sót.

## 4. Kế hoạch lấy dữ liệu theo vòng, không gán nhãn mù một lần

Không cần expert gán ngay hàng chục nghìn mẫu. Quy trình khuyến nghị:

### Vòng 0 — Export corpus và sinh candidate

Lấy trước **20.000–50.000 văn bản đại diện** từ corpus 600k, phân tầng theo:

- thời kỳ ban hành;
- cơ quan trung ương/địa phương;
- loại văn bản;
- tỉnh/thành;
- văn bản còn/hết hiệu lực;
- clause type;
- văn bản thường, sửa đổi và hợp nhất;
- format số hiệu cũ và mới.

Chạy rule engine để sinh candidate và feature trace. Không cần expert ở bước này.

### Vòng 1 — Seed annotation

Expert gán khoảng **3.000 candidate**:

- 40% production candidates;
- 40% hard negatives/near misses;
- 20% clause không có relation hoặc candidate mơ hồ.

Phải ưu tiên tất cả error families, không sample ngẫu nhiên thuần.

### Vòng 2 — Baseline và active learning

Train Logistic/LightGBM, sau đó lấy thêm từng batch **1.000 candidate**:

- model bất định;
- rule và model bất đồng;
- model tự tin nhưng sai trên audit;
- relation hiếm;
- document/authority/time bucket chưa được phủ.

### Mốc dữ liệu thực dụng

Đây là mốc engineering để bắt đầu learning curve, không phải định luật:

| Mục tiêu | Candidate đã adjudicate | Unique clause | Unique source document |
|---|---:|---:|---:|
| Prototype feature model | 3.000–5.000 | >= 1.000 | >= 500 |
| LightGBM có calibration ban đầu | 8.000–15.000 | 2.000–4.000 | >= 1.000 |
| Fine-tune PhoBERT binary verifier | 15.000–30.000 | >= 4.000 | >= 2.000 |
| Production study tương đối vững | 30.000–50.000 | >= 8.000 | >= 3.000 |

Điểm dừng phải dựa trên learning curve và error saturation. Nếu thêm 1.000 mẫu mà
precision/coverage trên holdout không còn tăng đáng kể, dừng hoặc đổi feature/candidate
generation.

## 5. Sampling hard negative

Negative cần giống positive về bề mặt. Easy negative quá nhiều không giúp model.

Các nhóm bắt buộc:

1. Có action keyword nhưng không có tác động pháp lý.
2. Có nhiều action và nhiều reference; pair bị ghép chéo.
3. Reference thuộc amendment history/provenance trong ngoặc.
4. Self-reference không hợp lệ.
5. Cùng số điều/khoản nhưng sai văn bản.
6. Đúng văn bản nhưng sai điều/khoản/điểm.
7. Đúng target nhưng sai relation type.
8. Action/reference bị ngăn bởi scope delimiter hoặc heading.
9. Action kế thừa sai từ parent/grandparent.
10. Reference resolve được nhiều văn bản hoặc sai authority/year.
11. Mẫu biểu, mã thủ tục, số hồ sơ bị nhận nhầm là số hiệu văn bản.
12. Các FP thực tế từ production.

Trong tập train ban đầu, nên giữ khoảng **40–60% INVALID**, phần lớn là hard negative.
Không ép cân bằng tuyệt đối nếu production prior khác, nhưng validation/test phải phản
ánh cả distribution thực tế và một stress set giàu hard negative.

## 6. Phân bố relation

Phase đầu train **binary verifier dùng chung** cho mọi relation, không train classifier
15 lớp. `proposed_relation` là input; output là candidate đúng/sai.

Mục tiêu lấy nhãn:

- relation phổ biến: tối thiểu 500 `VALID` và 500 hard `INVALID` liên quan;
- relation trung bình: 300 + 300;
- relation hiếm: cố gắng 150–300 + 150–300.

Nếu relation hiếm không đạt mức này:

- giữ rule deterministic;
- dùng threshold global hoặc theo nhóm relation;
- không công bố metric/threshold riêng cho relation đó.

Không oversample bằng cách nhân bản nguyên văn. Có thể oversample trong batch training,
nhưng số liệu evaluation phải dựa trên document độc lập.

## 7. Holdout và độ tin cậy thống kê

Tách theo **văn bản**, không tách ngẫu nhiên theo candidate. Nên có:

1. validation theo document để calibration/chọn threshold;
2. test document holdout không dùng sửa rule;
3. temporal holdout từ giai đoạn mới nhất;
4. stress test hard negatives;
5. nếu có thể, authority/province holdout.

Để tuyên bố precision tối thiểu 99% với Wilson 95% lower bound, ngay cả khi không thấy
lỗi nào vẫn cần ít nhất **381 quyết định ACCEPT độc lập**. Nếu muốn khẳng định 99% cho
từng relation thì cần mức hỗ trợ tương tự cho từng relation; dataset hiện tại không đáp
ứng điều này.

Do đó test set ban đầu nên có ít nhất:

- 2.000–5.000 candidate adjudicated;
- >= 500 văn bản độc lập;
- đủ accepted predictions để tính confidence interval;
- không trùng văn bản hoặc bản hợp nhất gần-duplicate với train.

## 8. Dữ liệu thô cần export từ corpus 600k

Format ưu tiên: JSONL UTF-8, một record cho mỗi clause:

```json
{
  "source_doc_id": "immutable id",
  "so_hieu": "...",
  "title": "...",
  "doc_type": "...",
  "authority": "...",
  "province": "...",
  "issue_date": "YYYY-MM-DD",
  "effective_date": "YYYY-MM-DD",
  "status": "...",
  "is_consolidated": false,
  "clause_key": "...",
  "parent_key": "...",
  "clause_type": "vanban|dieu|khoan|diem",
  "content": "...",
  "parent_content": "...",
  "grandparent_content": "..."
}
```

Yêu cầu:

- giữ nguyên Unicode và dấu câu;
- không bỏ heading/parent context;
- có immutable document/clause ID;
- đánh dấu văn bản hợp nhất và quan hệ version nếu có;
- deduplicate exact/near-duplicate trước khi split;
- không để cùng một document family rơi vào cả train và test.

## 9. DAPT/unsupervised corpus

Domain-adaptive pretraining không cần expert label. Có thể dùng toàn bộ corpus 600k sau
khi:

- loại HTML/OCR noise;
- deduplicate;
- giữ boundary giữa văn bản/clause;
- tách validation theo document và thời gian;
- thống kê số token thực tế trước khi chọn số epoch.

DAPT có thể cải thiện encoder pháp luật nhưng **không thay thế supervised candidate
labels**.

## 10. NER: chỉ lấy sau khi đo candidate recall

Hiện repo không có NER dataset. File `ner_schema_example.jsonl` chỉ minh họa schema.

Chỉ gán NER khi Phase 0 chứng minh regex/reference parser làm mất recall. Format lấy
dữ liệu nên là character spans, không phải BIO token tạo sẵn:

```json
{
  "doc_id": "...",
  "clause_key": "...",
  "text": "...",
  "entities": [
    {"start": 10, "end": 19, "label": "DOC_TYPE", "text": "Nghị định"},
    {"start": 23, "end": 39, "label": "DOC_NUMBER", "text": "10/2023/NĐ-CP"}
  ]
}
```

Label set ban đầu:

- `DOC_TYPE`
- `DOC_NUMBER`
- `DOC_TITLE`
- `ARTICLE`
- `CLAUSE`
- `POINT`
- `AUTHORITY`
- `ISSUE_DATE`

Mốc pilot:

- 2.000–3.000 clause;
- 10.000–20.000 entity spans;
- 20–30% clause không có entity cần tìm;
- double annotation 10–20%.

Sau khi nhận dữ liệu character-span, preprocessing mới chuyển sang BIO theo tokenizer
để tránh lệch tokenization.

## 11. Quality control cho annotation

- Double-annotate 10–20% mẫu.
- Adjudicate mọi disagreement.
- Lưu `annotator_id`, guideline version và thời gian gán nhãn.
- Không bắt expert đoán khi thiếu ngữ cảnh; dùng `UNKNOWN`.
- Audit riêng relation hiếm và các mẫu model tự tin.
- Version dataset; không sửa test set âm thầm.
- LLM 27B chỉ là teacher/suggestion. Nhãn LLM chưa được expert xác nhận không phải gold.

## 12. Thứ tự dữ liệu cần lấy

Ưu tiên:

1. Export 20k–50k văn bản/clause đại diện theo schema Mục 8.
2. Export toàn bộ production extraction trace nếu đã có: rule ID, spans, candidate,
   resolution result và expert verdict.
3. Dùng pipeline sinh queue 3.000 candidate đầu tiên cho expert.
4. Sau baseline, bổ sung active-learning batches.
5. Export toàn bộ 600k cleaned text cho DAPT.
6. Chỉ xây NER corpus nếu candidate-recall analysis xác nhận cần.

## Tài liệu kỹ thuật tham khảo

- Zhong & Chen, 2021, pipelined entity/relation extraction:
  https://aclanthology.org/2021.naacl-main.5/
- Nguyen & Nguyen, 2020, PhoBERT:
  https://aclanthology.org/2020.findings-emnlp.92/
- Gururangan et al., 2020, domain/task-adaptive pretraining:
  https://aclanthology.org/2020.acl-main.740/
- Chalkidis et al., 2020, adaptation in legal NLP:
  https://aclanthology.org/2020.findings-emnlp.261/
- Guo et al., 2017, confidence calibration:
  https://proceedings.mlr.press/v70/guo17a.html
- Geifman & El-Yaniv, 2019, selective prediction/reject option:
  https://proceedings.mlr.press/v97/geifman19a.html
- Ratner et al., 2017, weak supervision/data programming:
  https://www.vldb.org/pvldb/vol11/p269-ratner.pdf
