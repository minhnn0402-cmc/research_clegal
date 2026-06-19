# Đề Xuất Cascade Hybrid cho Trích Xuất Quan Hệ Pháp Luật

## 1. Mục tiêu và nguyên tắc thiết kế

Hệ thống cần xử lý offline khoảng **600.000 văn bản pháp luật**, ưu tiên:

1. Precision cao và kiểm soát được false positive.
2. Thời gian xử lý đủ ngắn để có thể chạy lại khi rule hoặc model thay đổi.
3. Kết quả có thể audit, giải thích và rollback.
4. Không phụ thuộc vào Generative LLM trong luồng xử lý toàn bộ corpus.
5. Tận dụng tối đa rule engine, dữ liệu chưa gán nhãn và chuyên gia pháp lý hiện có.

Kiến trúc đề xuất:

> **Rule/Regex sinh candidate → deterministic checks → feature model → small semantic verifier → reference resolution và legal constraints → ACCEPT / REJECT / ABSTAIN.**

LLM 27B không tham gia full-corpus inference. Nó chỉ là công cụ hỗ trợ offline cho một phần nhỏ mẫu bất định, active learning và phân tích lỗi.

---

## 2. Phát biểu lại bài toán

Đơn vị dự đoán không phải toàn bộ clause và cũng không phải một chuỗi JSON được sinh tự do. Đơn vị dự đoán là một **candidate relation**:

```text
(
    source clause,
    action cue,
    target reference,
    proposed relation type,
    structural context,
    resolution evidence
)
```

Ví dụ:

```json
{
  "source_so_hieu": "10/2025/TT-BTC",
  "clause_key": "khoan_2_dieu_5",
  "clause_type": "khoan",
  "content": "...",
  "parent_content": "...",
  "grandparent_content": "...",
  "action_text": "bãi bỏ",
  "action_span": [12, 18],
  "reference_text": "Nghị định số 10/2023/NĐ-CP",
  "reference_span": [45, 75],
  "proposed_relation": "bai_bo",
  "rule_id": "BAI_BO_FORWARD_02",
  "context_source": "current",
  "reference_payload": {},
  "resolution_features": {},
  "label": "VALID"
}
```

Các nhãn huấn luyện:

- `VALID`: candidate là quan hệ đúng.
- `INVALID`: candidate là false positive.
- `UNKNOWN`: không đủ bằng chứng hoặc ground truth chưa đủ tin cậy.

Không ép `UNKNOWN` thành positive hoặc negative.

---

## 3. Kiến trúc cascade đề xuất

```text
Parsed document
      │
      ▼
Candidate generation
  ├── Existing Regex/Rules
  └── Optional NER candidate source
      │
      ▼
Deterministic candidate checks
  ├── Hard accept
  ├── Hard reject
  └── Uncertain
      │
      ▼
Calibrated feature model
  ├── ACCEPT
  ├── REJECT
  └── UNCERTAIN
      │
      ▼
Small semantic verifier
  ├── ACCEPT
  ├── REJECT
  └── ABSTAIN
      │
      ▼
Final reference resolution + legal constraints
      │
      ├── Valid → MongoDB / Knowledge Graph
      └── Ambiguous → Audit queue
```

### Tầng 1 — Candidate Generator

#### Nhiệm vụ

Tạo candidate có recall cao từ action cue và reference đã nhận diện.

#### Nguồn candidate

1. Rule/regex hiện tại:
   - Document type và document number.
   - Điều, khoản, điểm.
   - Relation action cue.
   - Parent/grandparent inheritance.
   - Internal references.

2. Optional NER:
   - Chỉ bổ sung reference mà regex bỏ sót.
   - Không ghi trực tiếp output NER vào graph.
   - Chỉ nên phát triển sau khi error analysis chứng minh reference recall là bottleneck.

#### Không cross-join mù toàn bộ

Không mặc định tạo toàn bộ:

```text
C = A × R
```

vì có thể gây candidate explosion và tạo quá nhiều easy negatives không có giá trị.

Candidate production nên được giới hạn bởi:

- Action và reference cùng sentence hoặc cùng scope segment.
- Direction phù hợp: forward, passive hoặc inherited.
- Top-k reference gần action nhất ở mỗi phía.
- Candidate do matcher hiện tại tạo ra.
- Near-miss candidate: reference gần đúng nhưng bị matcher từ chối vì scope, delimiter hoặc conflict.
- Candidate kế thừa từ parent/grandparent phải ghi rõ nguồn context.

Full cross-join chỉ dùng có kiểm soát khi tạo hard negatives cho training.

#### Candidate recall ceiling

Trước khi train model phải đo:

```text
candidate_recall =
    số gold relations có ít nhất một candidate đúng
    / tổng số gold relations
```

Nếu candidate recall thấp, classifier phía sau không thể cứu được. Khi đó cần cải thiện reference/action candidate generation hoặc thêm NER, không nên đổi classifier.

---

### Tầng 2 — Deterministic Candidate Checks

#### Nhiệm vụ

Áp dụng tri thức pháp lý và các invariant có độ tin cậy cao trước khi gọi model.

#### Hard reject có thể gồm

- `Mẫu số`, mã biểu mẫu hoặc identifier không phải văn bản.
- Amendment provenance trong ngoặc.
- Self-reference không hợp lệ đối với relation đang xét.
- Action và reference nằm ngoài scope cho phép.
- Authority violation rõ ràng.
- Candidate không thể resolve và không có đủ identity evidence.
- Conflict xác định với một relation có độ ưu tiên cao hơn.
- Action chỉ là danh từ/mô tả nghiệp vụ, không phải tác động pháp lý.

#### Hard accept có thể gồm

Chỉ dùng với pattern đã được chứng minh có precision rất cao trên:

- Document holdout.
- Temporal holdout.
- Production audit sample.

Hard accept phải được version hóa theo `rule_id`, không dựa trên nhận định chủ quan.

#### Auditability

Mỗi candidate cần lưu:

```json
{
  "candidate_id": "...",
  "rule_id": "...",
  "decision": "HARD_REJECT",
  "reason": "FORM_IDENTIFIER",
  "evidence": "Mẫu số 29-TTr"
}
```

---

### Tầng 3 — Fast Feature Model

#### Mô hình

Baseline theo thứ tự:

1. Logistic Regression.
2. LightGBM.
3. CatBoost.

Không mặc định model phức tạp hơn sẽ tốt hơn. Logistic Regression giúp kiểm tra nhanh tính hữu ích và leakage của feature.

#### Feature groups

**Rule features**

- `rule_id`.
- Proposed relation type.
- Forward/passive/inherited.
- Pattern specificity.
- Số rule đồng thuận hoặc conflict.

**Distance và scope**

- Khoảng cách action–reference.
- Action đứng trước hay sau reference.
- Số dấu `.`, `;`, `,`, xuống dòng ở giữa.
- Cùng sentence/segment hay không.
- Reference thuộc current, parent, grandparent hoặc title.

**Reference anatomy**

- Document-level hoặc clause-level.
- Có số hiệu, tiêu đề, ngày, cơ quan hay không.
- Có đầy đủ điểm/khoản/điều hay không.
- Internal/self-reference.
- Reference nằm trong ngoặc, quote hoặc amendment-history span.

**Resolution features**

- Resolve thành công hay không.
- Số target documents phù hợp.
- Exact document-number match.
- Title similarity.
- Top-1 score và margin top-1/top-2.
- Year/date/authority compatibility.

**Document and legal features**

- Source/target document type.
- Authority rank.
- Source và target year/date.
- Conflict với relation khác trên cùng target.
- Target là inserted clause hay existing clause.

#### Routing ba vùng

Feature model phải được calibration và có ba vùng:

```text
P(correct) >= T_accept[relation] → ACCEPT
P(correct) <= T_reject[relation] → REJECT
otherwise                        → UNCERTAIN
```

Không mặc định `T_accept = 0.99`. Threshold được chọn trên validation set theo mục tiêu:

```text
maximize coverage
subject to precision lower bound >= target
```

Threshold phải riêng theo relation type.

Feature model được phép reject vì phần lớn candidate sinh ra thường là negative. Nếu không có reject path, tải xuống semantic model có thể vẫn quá lớn.

---

### Tầng 4 — Small Semantic Candidate Verifier

#### Giai đoạn đầu: binary verifier

Không bắt đầu bằng classifier 16 lớp. Bài toán đầu tiên nên là:

```text
Candidate này có đúng với proposed relation type không?
VALID / INVALID
```

Proposed relation type được đưa vào input. Binary verifier:

- Dễ học hơn với dataset nhỏ.
- Dễ calibration.
- Phù hợp mục tiêu lọc false positive.
- Không buộc model học lại toàn bộ ontology ngay từ đầu.

Sau khi binary verifier ổn định mới thử multi-task:

1. Candidate validity.
2. Corrected relation type hoặc `NONE`.
3. Document/clause scope.
4. Direction.
5. Context source.

#### Mô hình

Baseline:

- `PhoBERT-base`.

Thí nghiệm tiếp theo:

- PhoBERT được domain-adaptive pretraining trên corpus pháp luật.
- Encoder tiếng Việt nhỏ hơn nếu latency/throughput cần tối ưu.

#### Input representation

Marker phải đánh dấu đúng action và reference:

```text
[RELATION] bai_bo [/RELATION]
[SOURCE] Thông tư 10/2025/TT-BTC [/SOURCE]
[PARENT] ... [/PARENT]
[CURRENT]
... [ACT] bãi bỏ [/ACT]
    [REF] Nghị định số 10/2023/NĐ-CP [/REF] ...
[/CURRENT]
[FEATURES]
direction=forward; inherited=false; exact_number=true; ...
[/FEATURES]
```

Có thể dùng hidden states tại `[ACT]`, `[REF]` và `[CLS]`, sau đó concatenate trước classification head.

#### Decision

Không chỉ dùng entropy thô. Cần calibration trên held-out validation set:

```text
P(valid) >= T_semantic_accept → ACCEPT
P(valid) <= T_semantic_reject → REJECT
otherwise                     → ABSTAIN
```

So sánh các phương pháp:

- Temperature scaling.
- Isotonic regression nếu validation đủ lớn.
- Calibration riêng theo relation.

Metric chính là risk–coverage hoặc precision–coverage, không chỉ F1.

---

### Tầng 5 — Resolution và Legal Constraint Validation

Một phần resolution phải chạy trước model để tạo feature; validation đầy đủ chạy lại sau quyết định model.

#### Trước classifier

- Resolve internal reference.
- Thu thập target candidates từ CSV/Elasticsearch.
- Tạo resolution confidence và ambiguity features.
- Khôi phục document context từ hierarchy.

#### Sau classifier

- Chọn target ID cuối cùng.
- Kiểm tra authority, date, scope và relation conflict.
- Chuẩn hóa direction.
- Deduplicate.
- Chỉ ghi graph khi target đã được ground deterministically.

#### Temporal constraints

Không dùng một luật thời gian chung cho mọi relation.

Ví dụ:

- `thay_the`, `bai_bo`, `sua_doi`: target thường không được ban hành sau source.
- `dan_chieu`: có quy tắc thời gian khác.
- `dinh_chinh`: cần xét văn bản và ngày đính chính.
- Thiếu ngày hoặc dữ liệu mâu thuẫn: chuyển `UNKNOWN`, không hard reject tùy tiện.

Mỗi constraint phải có:

```text
relation type
severity: reject / warning / unknown
reason
evidence
```

---

### Tầng 6 — Abstention và Active Learning

#### Expert là nguồn nhãn chuẩn

Các candidate `ABSTAIN` hoặc vi phạm constraint không rõ ràng được đưa vào expert queue.

Expert workflow nên ưu tiên:

- Candidate có ảnh hưởng lớn tới graph.
- Relation hiếm.
- Model disagreement.
- Pattern mới.
- Temporal/authority ambiguity.
- Candidate đại diện cho một cluster lỗi lớn.

#### Vai trò của LLM 27B

LLM 27B không có quyền tự động ghi edge hoặc override hard constraints.

Nó có thể:

- Đề xuất `KEEP / DROP / ABSTAIN`.
- Giải thích evidence.
- Phân nhóm lỗi.
- Ưu tiên mẫu cho expert.
- Sinh hard-negative variations.
- Làm teacher để distill sang small model.

Output LLM chỉ là một feature hoặc weak label. Expert review vẫn là ground truth cho tập quan trọng.

Nếu expert có thể xử lý toàn corpus trong khoảng 5 ngày, việc dùng LLM trong audit queue chỉ được duy trì khi chứng minh được:

- Giảm thời gian review.
- Không làm giảm agreement.
- Giúp tìm pattern lỗi mới.
- Chi phí thấp hơn giá trị nhãn thu được.

---

## 4. Thiết kế dữ liệu huấn luyện

### Candidate-level labeling

Chạy candidate generator trên `golden_eval.csv`:

- Candidate khớp ground truth → `VALID`.
- Candidate không khớp → chưa mặc định là `INVALID`.
- Chỉ gán `INVALID` khi annotation được xác nhận exhaustive cho clause hoặc qua expert review.
- Candidate có thể là lỗi nhãn → `UNKNOWN`.

### Hard-negative mining

Ưu tiên:

- Cross-pair sai trong câu nhiều action và reference.
- Citation bị ghép thành action relation.
- Passive amendment history.
- Self-reference sai.
- Parent reference bị cross-join vào child.
- Cùng số hiệu nhưng sai cơ quan/năm.
- Sai cấp điểm/khoản/điều.
- Relation-type conflict.
- Candidate từng gây FP trong benchmark hoặc production audit.

Không dùng random clause không có keyword làm negative chính vì quá dễ và không đại diện lỗi production.

### Rejected-candidate trace

Candidate bị hard rule loại vẫn cần được lưu:

- Để audit rule.
- Để tạo negative augmentation.
- Để phát hiện hard filter làm mất recall.

Tuy nhiên, không trộn quá nhiều candidate mà production semantic model không bao giờ nhìn thấy vào training distribution chính.

### Split chống leakage

Không random split từng relation hoặc candidate.

Các benchmark cần có:

1. Document-group holdout theo `so_hieu`.
2. Temporal holdout.
3. Authority/region holdout.
4. Hard-negative test set.
5. Production audit set.
6. Reference-resolution test set.

---

## 5. Loss function và class imbalance

Focal Loss không được coi là bắt buộc.

Phải chạy ablation:

1. Standard cross-entropy.
2. Weighted cross-entropy.
3. Balanced batch sampling.
4. Focal Loss.
5. Asymmetric loss nếu cần.

Tiêu chí không chỉ là F1. Loss phù hợp phải cho:

- Precision tốt ở vùng threshold deploy.
- Calibration tốt.
- Risk–coverage ổn định.
- Không khuếch đại label noise ở relation hiếm.

Không mặc định dùng inverse-frequency weight mạnh cho 15 relation types.

---

## 6. Tận dụng 600.000 văn bản chưa gán nhãn

### Domain-adaptive pretraining

```text
PhoBERT
   ↓ MLM trên corpus pháp luật
Legal-PhoBERT
   ↓ fine-tune
NER / candidate verifier
```

Corpus cần được:

- Deduplicate.
- Loại boilerplate lỗi.
- Giữ cấu trúc điều/khoản/điểm.
- Kiểm soát dữ liệu OCR hoặc encoding hỏng.

### Weak supervision

Rule hiện tại có thể trở thành labeling functions:

- Exact-number + explicit action.
- Passive-history negative.
- Form-identifier negative.
- Authority violation.
- Self-reference.
- Rule agreement.
- Rule conflict.
- Unique/ambiguous resolution.

Weak labels dùng để pretrain verifier, sau đó fine-tune bằng gold và expert-reviewed data.

### Self-training

Chỉ pseudo-label khi:

- Model đã calibration.
- Rule và model đồng thuận.
- Confidence vượt threshold rất cao.
- Có human audit theo mẫu.
- Không tự khuếch đại prediction qua nhiều vòng thiếu kiểm soát.

Không dùng unsupervised clustering để sinh relation edge production.

---

## 7. Benchmark và tiêu chí quyết định

### Metrics chính

- Precision và Wilson 95% confidence interval.
- Recall tại precision target.
- Coverage tại precision target.
- False positives trên 1.000 văn bản.
- Candidate recall ceiling.
- Hard-negative false-positive rate.
- Per-relation metrics.
- Calibration: ECE/Brier score.
- Reference resolution accuracy.
- Throughput và total wall-clock time.

### Decision gate

Chỉ chấp nhận một tầng model khi:

- Precision lower bound tăng hoặc không thấp hơn baseline.
- Recall loss nằm trong budget.
- Coverage đủ lớn.
- Cải thiện tồn tại trên document và temporal holdout.
- Không chỉ tăng điểm trên benchmark đã dùng để phát triển rule.

---

## 8. Kế hoạch thí nghiệm

### Phase 0 — Candidate instrumentation

- Thêm candidate trace JSONL.
- Ghi rule ID, spans, context source, filter decisions và resolution evidence.
- Đo candidate distribution và candidate recall ceiling.

### Phase 1 — Feature baseline

- Logistic Regression.
- LightGBM/CatBoost.
- Calibration.
- Per-relation thresholds.
- Precision–coverage report.

### Phase 2 — Hard-negative expansion

- Mine FP từ benchmark.
- Mine rejected candidates.
- Expert review production sample.
- Tạo temporal và authority holdout.

### Phase 3 — Small semantic verifier

- Binary PhoBERT verifier.
- Ablation input context và marker.
- Ablation loss function.
- ONNX benchmark sau khi model chứng minh có giá trị.

### Phase 4 — Domain adaptation

- MLM pretraining trên corpus pháp luật.
- So sánh PhoBERT và Legal-PhoBERT.
- Đánh giá trên unseen-pattern và temporal holdout.

### Phase 5 — Optional NER

- Chỉ thực hiện nếu FN analysis cho thấy reference extraction là bottleneck.
- So sánh regex-only và regex+NER candidate recall.

### Phase 6 — LLM teacher và active learning

- Chỉ gửi disagreement/abstention candidates.
- So sánh LLM-assisted review với expert-only review.
- Distill weak labels vào small model nếu có lợi.

### Phase 7 — Shadow processing

- Model chạy song song, chưa tác động graph.
- Theo dõi accept/reject/abstain.
- Audit candidate bị loại.
- Đánh giá drift theo thời gian, cơ quan và loại văn bản.

---

## 9. Throughput: giả thuyết cần benchmark

Không khẳng định trước:

- CPU hoàn thành trong 2–4 giờ.
- Chỉ 10–15% candidate xuống PhoBERT.
- GPU hoàn thành trong 8–12 giờ.
- LLM load giảm hơn 99%.

Các con số này là target hypothesis. Cần đo:

- Clauses/document.
- Actions/clause.
- References/clause.
- Candidates/clause sau scope pruning.
- Tỷ lệ hard accept/reject.
- Tỷ lệ feature-model accept/reject/uncertain.
- Sequence-length distribution.
- GPU throughput theo batch size.
- MongoDB/Elasticsearch I/O.
- Abstention rate và expert-review time.

Benchmark tối thiểu:

1. 1.000 văn bản.
2. 10.000 văn bản.
3. Stratified sample theo loại văn bản, thời kỳ và cơ quan.
4. Extrapolation kèm confidence interval, không dùng một point estimate.

Chỉ chuyển sang ONNX/TensorRT sau khi semantic verifier đã chứng minh accuracy gain. Tối ưu inference trước khi chứng minh model có ích sẽ làm tăng chi phí nghiên cứu không cần thiết.

---

## 10. Khuyến nghị cuối cùng

1. Giữ rule engine làm candidate generator và deterministic safety layer.
2. Không dùng LLM 27B để extract toàn bộ corpus.
3. Không cross-join mù toàn bộ action và reference trong production.
4. Xây candidate trace và đo candidate recall trước khi train model.
5. Bắt đầu bằng feature model có calibration.
6. Dùng PhoBERT như binary candidate verifier cho vùng uncertain.
7. Thêm NER khi có bằng chứng regex reference recall là bottleneck.
8. Dùng domain-adaptive pretraining và weak supervision để tận dụng corpus chưa gán nhãn.
9. Dùng `ACCEPT / REJECT / ABSTAIN` với threshold riêng theo relation.
10. LLM 27B chỉ là teacher, error analyst hoặc công cụ hỗ trợ expert.

Kiến trúc mục tiêu:

> **Rules for candidate recall, calibrated discriminative models for precision, deterministic constraints for legal safety, and LLMs only for selective offline assistance.**
