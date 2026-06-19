# Đề Xuất Hệ Thống Hybrid Trích Xuất Quan Hệ Pháp Luật

## 1. Tóm tắt điều hành

Hệ thống hiện tại đã có một rule engine mạnh, hiểu cấu trúc văn bản pháp luật Việt Nam, phân cấp điều/khoản/điểm, phạm vi câu, lịch sử sửa đổi, thẩm quyền ban hành và cách giải quyết văn bản tham chiếu. Kết quả thực nghiệm trong repo cũng cho thấy sử dụng LLM 27B như một bộ sinh quan hệ hoặc fallback cộng dồn làm tăng false positive và giảm precision.

Vì vậy, hướng có xác suất thành công cao nhất không phải là thay regex bằng LLM, mà là:

> **Rule engine sinh candidate → model nhỏ đánh giá candidate → deterministic legal constraints → accept/reject/abstain.**

Trong kiến trúc này:

- Rule/regex tiếp tục đảm nhiệm việc tìm kiếm candidate với recall cao.
- Model nhỏ học cách dự đoán candidate nào là quan hệ thật.
- Các ràng buộc pháp lý xác định tiếp tục là lớp kiểm tra cuối.
- Trường hợp không chắc chắn được đưa vào vùng `abstain`, không tự động ghi vào graph.
- LLM 27B được loại khỏi production hot path, nhưng có thể dùng offline như teacher, annotator và công cụ phân tích lỗi.

NER là một thành phần hỗ trợ để nâng độ phủ reference extraction, nhưng không phải giải pháp trung tâm. Nút thắt lớn hơn nằm ở việc ghép action với đúng target, xác định scope và loại bỏ candidate sai.

---

## 2. Phát biểu bài toán

Đầu vào của hệ thống là văn bản pháp luật đã được phân tách thành các node:

- Văn bản
- Điều
- Khoản
- Điểm

Đầu ra cần xác định các quan hệ như:

- `can_cu`
- `dan_chieu`
- `sua_doi_bo_sung`
- `sua_doi`
- `bo_sung`
- `thay_the`
- `bai_bo`
- `huy_bo`
- `dinh_chi`
- `dinh_chinh`
- `ngung_hieu_luc`
- `keo_dai_hieu_luc`
- `huong_dan`
- `quy_dinh_chi_tiet`
- `hop_nhat`

Đây không phải một bài toán NER thuần túy. Một hệ thống hoàn chỉnh phải giải quyết ít nhất sáu tác vụ:

1. Phát hiện reference tới văn bản hoặc điều khoản.
2. Phát hiện action cue thể hiện loại quan hệ.
3. Ghép action cue với đúng reference.
4. Khôi phục document context từ parent, grandparent hoặc tiêu đề.
5. Kiểm tra scope, thẩm quyền, thời gian và conflict giữa các quan hệ.
6. Resolve reference sang đúng document ID và clause key.

Rule engine hiện tại đã xử lý tốt nhiều trường hợp trong tác vụ 1 và 2. Phần gây false positive đáng kể thường tập trung ở tác vụ 3–5. Do đó, model đầu tiên nên được xây dựng để **đánh giá candidate relation**, không phải thay toàn bộ rule engine bằng một model sinh tự do.

---

## 3. Các phương án kiến trúc

### 3.1. Rule-only

```text
Text → Regex/reference rules → Relation matching → Legal constraints → Graph
```

Ưu điểm:

- Deterministic và dễ audit.
- Chi phí thấp.
- Có độ chính xác tốt trên các cấu trúc đã biết.
- Tận dụng được hiểu biết pháp lý đã tích lũy.

Hạn chế:

- Chi phí bảo trì tăng theo số lượng edge case.
- Khó biểu diễn các tương tác ngữ nghĩa phức tạp.
- Confidence thường được mã hóa thủ công.
- Dễ overfit vào benchmark hoặc văn phong đã gặp.

Rule-only vẫn phải được giữ làm baseline và fallback an toàn.

### 3.2. LLM làm primary extractor

```text
Text/context → LLM 27B → Generated relations → Graph
```

Không khuyến nghị cho production vì:

- Generation có xu hướng tạo thêm false positive.
- Không nhìn thấy đầy đủ graph state và kết quả resolve từ Elasticsearch.
- Khó kiểm soát span, target identity và schema.
- Chi phí và latency cao trên quy mô khoảng 600.000 văn bản.
- Non-determinism và model drift gây khó audit.
- Các quan hệ cấu trúc như `hop_nhat` hoặc inheritance không thể suy ra ổn định chỉ từ local text.

### 3.3. Rule + additive LLM fallback

```text
Rule output ───────────────┐
                          ├→ Merge → Graph
Ambiguous context → LLM ──┘
```

Đây là kiến trúc fallback hiện tại. LLM bổ sung candidate nhưng không sửa hoặc loại bỏ candidate sai của rule.

Đặc tính cố hữu:

- Có thể tăng recall.
- Khó tăng precision.
- Candidate sai của rule vẫn tồn tại.
- Candidate sai của LLM được cộng thêm.

Kiến trúc này không phù hợp với mục tiêu precision-first.

### 3.4. Rule-first candidate verification

```text
Parsed document
      │
      ▼
Rule candidate generator
      │
      ├── deterministic high-confidence ────────────────┐
      │                                                 │
      ├── deterministic invalid → reject                │
      │                                                 ▼
      └── uncertain candidate → Small verifier → accept/reject/abstain
                                                        │
                                                        ▼
                                    ES/CSV resolution + legal constraints
                                                        │
                                                        ▼
                                                       Graph
```

Đây là kiến trúc được khuyến nghị.

Model không phải tự tìm và tự sinh mọi quan hệ. Nó chỉ đánh giá một candidate cụ thể:

```text
Source document: 10/2025/TT-BTC
Detected relation: bai_bo
Cue: "bãi bỏ"
Target: "Nghị định số 10/2023/NĐ-CP"
Current clause: ...
Parent clause: ...
Rule ID: BAI_BO_FORWARD_02

Candidate này có phải quan hệ pháp lý thật không?
```

Output có thể là:

```json
{
  "valid": true,
  "relation_type": "bai_bo",
  "confidence": 0.998
}
```

Hoặc với mô hình ba vùng:

```text
ACCEPT / REJECT / ABSTAIN
```

---

## 4. Candidate dataset

Đơn vị học không nên là toàn bộ clause, mà là một candidate relation:

```text
(source clause, action cue, reference target, proposed relation type)
```

Mỗi record nên có:

```json
{
  "source_so_hieu": "10/2025/TT-BTC",
  "source_document_type": "Thông tư",
  "clause_type": "khoan",
  "content": "...",
  "parent_content": "...",
  "grandparent_content": "...",
  "relation_type": "bai_bo",
  "relation_text": "bãi bỏ",
  "reference_text": "Nghị định số 10/2023/NĐ-CP",
  "reference_payload": {},
  "rule_id": "BAI_BO_FORWARD_02",
  "features": {},
  "label": 0
}
```

Nhãn:

- `1`: candidate khớp với ground truth.
- `0`: candidate là false positive.
- `unknown`: không đủ bằng chứng hoặc có tranh luận về nhãn.

Không nên ép các mẫu `unknown` thành positive hoặc negative.

---

## 5. Model baseline dựa trên feature

Trước khi fine-tune Transformer, nên xây dựng baseline bằng:

- Logistic Regression
- LightGBM
- CatBoost

### 5.1. Feature từ rule engine

Repo hiện tại đã có nhiều tín hiệu giàu giá trị:

- ID của regex/rule kích hoạt.
- Relation type được đề xuất.
- Cue nằm trước hay sau reference.
- Khoảng cách cue–reference.
- Cue và reference có cùng câu hoặc segment không.
- Relation phát hiện trực tiếp hay kế thừa từ ancestor.
- Số cue và số reference trong scope.
- Candidate có nằm trong ngoặc provenance không.
- Có marker `Mẫu số`, `ban hành kèm theo`, `theo quy định tại` không.
- Target là document-level hay clause-level.
- Target có đầy đủ `điểm/khoản/điều` không.
- Source và target document type.
- Source và target authority rank.
- Năm ban hành source/target.
- Title similarity.
- Internal/self-reference.
- Reference được resolve duy nhất hay có nhiều kết quả.
- Có conflict relation khác cho cùng target không.
- Candidate bị rule filter nào cảnh báo.
- Candidate xuất phát từ current, parent, grandparent hay title.

### 5.2. Mục đích

Model feature-based sẽ học:

```text
P(candidate là quan hệ đúng | rule, scope, authority, distance, resolution...)
```

Đây chính là cách học confidence của regex từ dữ liệu thay vì đặt confidence thủ công.

### 5.3. Lợi ích

- Huấn luyện được với dataset nhỏ.
- Inference rất nhanh.
- Feature importance giúp phân tích nguyên nhân FP.
- Dễ đặt threshold riêng theo relation type.
- Dễ debug và rollback.

---

## 6. Small language model làm candidate verifier

Sau baseline feature-based, có thể fine-tune một encoder nhỏ như PhoBERT.

### 6.1. Input representation

```text
[CLS]
[SOURCE] loại văn bản, số hiệu, cơ quan, năm [/SOURCE]
[RELATION] bai_bo [/RELATION]
[CUE] bãi bỏ [/CUE]
[TARGET] Nghị định số 10/2023/NĐ-CP [/TARGET]
[CURRENT] nội dung clause hiện tại [/CURRENT]
[PARENT] nội dung parent [/PARENT]
[GRANDPARENT] nội dung grandparent [/GRANDPARENT]
```

### 6.2. Multi-task outputs

Model có thể học đồng thời:

1. Candidate hợp lệ hay không.
2. Relation type đúng hoặc `NONE`.
3. Direction của relation.
4. Target scope: document hoặc clause.
5. Context source: current, parent, grandparent hoặc title.

Multi-task learning có thể giúp model học cấu trúc thay vì chỉ ghi nhớ keyword.

### 6.3. Kết hợp feature và text

Hai lựa chọn:

- Nối embedding văn bản với feature vector trước classification head.
- Ensemble xác suất của Transformer và LightGBM.

Phương án ensemble dễ triển khai và audit hơn trong giai đoạn đầu.

---

## 7. NER và reference extraction

NER nên là nhánh bổ trợ, không nên thay ngay toàn bộ regex.

### 7.1. Entity types cần cân nhắc

- `LEGAL_DOCUMENT_TYPE`
- `LEGAL_DOCUMENT_NUMBER`
- `LEGAL_DOCUMENT_TITLE`
- `ISSUING_AUTHORITY`
- `ISSUE_DATE`
- `ARTICLE`
- `CLAUSE`
- `POINT`
- `ACTION_CUE`
- `INTERNAL_REFERENCE`

### 7.2. Use case phù hợp

- Luật được nhắc bằng tên nhưng không có số hiệu.
- Tên luật viết tắt.
- Số hiệu có format lạ.
- Cơ quan ban hành nằm xa số hiệu.
- Reference bị chia bởi xuống dòng hoặc punctuation bất thường.
- Reference mà regex không nhận diện.

### 7.3. Cách tích hợp an toàn

NER chỉ nên bổ sung candidate:

```text
Regex reference candidates
          +
NER reference candidates
          │
          ▼
Deduplication + deterministic normalization
          │
          ▼
Candidate verifier
```

NER output không được ghi thẳng vào graph.

---

## 8. Tận dụng corpus 600.000 văn bản chưa gán nhãn

### 8.1. Domain-adaptive pretraining

Hướng unsupervised có giá trị cao nhất là tiếp tục pretrain encoder bằng Masked Language Modeling:

```text
PhoBERT-base
      │
      ▼
MLM trên corpus pháp luật nội bộ
      │
      ▼
Legal-PhoBERT
      │
      ▼
Fine-tune candidate verifier / NER
```

Corpus giúp model học:

- Văn phong pháp lý.
- Cấu trúc số hiệu.
- Cách viết ngày tháng.
- Tên cơ quan ban hành.
- Các mẫu tham chiếu lịch sử.
- Quan hệ giữa từ khóa và cấu trúc điều khoản.

Đây là unsupervised learning an toàn hơn việc tự khám phá relation label.

### 8.2. Weak supervision

Rule hiện có có thể được coi là các labeling functions:

- Rule precision cao → positive signal mạnh.
- Provenance parenthetical → negative.
- Form identifier → negative.
- Self-reference → negative hoặc internal-reference class.
- Authority violation → negative.
- Nhiều rule đồng thuận → positive confidence cao.
- Rule conflict → unknown.
- Không resolve được target → weak negative hoặc unknown, tùy loại.

Label model có thể kết hợp các rule nhiễu thành probabilistic label thay vì coi mọi rule output là ground truth.

### 8.3. Hard-negative mining

Precision phụ thuộc nhiều vào chất lượng negative examples. Cần chủ động sinh:

- Cue đúng nhưng target sai.
- Target đúng nhưng relation type sai.
- Reference thuộc amendment history.
- Reference trong ngoặc mô tả.
- `Mẫu số` hoặc mã biểu mẫu.
- Self-reference.
- Reference ở parent bị ghép sai vào child.
- Hai action trong cùng câu bị cross-join.
- `dan_chieu` bị gán thành action relation.
- Target cùng loại nhưng sai cơ quan hoặc sai năm.
- Candidate đã từng gây FP trong benchmark hoặc production audit.

### 8.4. Self-training

Chỉ nên pseudo-label khi:

- Confidence đã calibration.
- Threshold rất cao.
- Có threshold riêng theo relation.
- Có human audit theo mẫu.
- Không dùng prediction chưa kiểm chứng để tự khuếch đại lỗi qua nhiều vòng.

### 8.5. Điều không nên làm

Không nên dùng clustering hoặc unsupervised relation discovery làm nguồn quan hệ production. Các nhãn pháp lý gần nhau về từ vựng nhưng khác nhau về hiệu lực, thẩm quyền và scope. Không có supervision, model khó đạt precision cần thiết.

---

## 9. Vai trò của LLM 27B

### 9.1. Loại khỏi production hot path

LLM không nên:

- Là primary extractor.
- Append relation trực tiếp vào rule output.
- Ghi kết quả trực tiếp vào graph.
- Tự resolve document identity.
- Dùng confidence tự khai báo làm confidence hệ thống.

### 9.2. Giữ lại trong R&D pipeline

LLM 27B có thể dùng để:

- Gán nhãn sơ bộ cho candidate bất đồng.
- Giải thích tại sao candidate có thể sai.
- Phân nhóm false positive.
- Sinh hard-negative variations.
- Đề xuất rule mới.
- Làm teacher cho model nhỏ.
- Chọn case phục vụ active learning.

Mọi nhãn do LLM sinh cần được:

- Kiểm tra bằng deterministic constraints.
- Human-review trên sample hoặc toàn bộ tập quan trọng.
- Ghi rõ model version, prompt version và timestamp.

### 9.3. Distillation

Quy trình khả thi:

```text
Rule engine tìm uncertain candidates
            │
            ▼
LLM 27B đưa ra KEEP / DROP / ABSTAIN + lý do
            │
            ▼
Human review các mẫu quan trọng
            │
            ▼
Train small verifier
            │
            ▼
Production dùng small verifier
```

Nếu vẫn thử LLM online, chỉ nên thử trên các relation đã cho thấy khả năng cải thiện precision:

- `dinh_chi`
- `dinh_chinh`
- `keo_dai_hieu_luc`
- `ngung_hieu_luc`

Ngay cả khi đó, LLM chỉ nên đóng vai trò veto/gate và phải có `abstain`.

---

## 10. Confidence, calibration và abstention

Softmax probability không tự động là confidence đáng tin cậy.

Sau khi train model cần:

- Temperature scaling.
- Isotonic regression nếu validation data đủ lớn.
- Calibration riêng theo relation type.
- Đo Expected Calibration Error hoặc Brier score.

### 10.1. Ba vùng quyết định

Ví dụ:

```text
P(correct) ≥ 0.995  → ACCEPT
P(correct) ≤ 0.20   → REJECT
0.20 < P < 0.995    → ABSTAIN
```

Threshold thực tế phải được chọn từ validation set.

### 10.2. Precision–coverage

Mục tiêu không chỉ là F1 cao nhất. Với hệ thống precision-first, cần trả lời:

```text
Ở precision ≥ 0.99, hệ thống tự động xử lý được bao nhiêu phần trăm candidate?
```

Đây là risk–coverage hoặc precision–coverage curve.

### 10.3. Threshold theo relation

Không nên dùng một threshold chung:

- `can_cu` có cấu trúc khác `bai_bo`.
- `dan_chieu` có volume và ambiguity cao.
- `hop_nhat` phần lớn phụ thuộc cấu trúc.
- `thay_the` có rủi ro nhầm với `bai_bo` và `sua_doi`.

---

## 11. Thiết kế benchmark

### 11.1. Tránh leakage

Không random split từng dòng relation vì:

- Nhiều dòng thuộc cùng một clause.
- Nhiều clause thuộc cùng một văn bản.
- Các văn bản sửa đổi thường có cấu trúc gần như lặp lại.

Split tối thiểu phải group theo `so_hieu`.

### 11.2. Các tập đánh giá

1. **Document-group holdout**  
   Không để cùng văn bản xuất hiện ở train và test.

2. **Temporal holdout**  
   Train trên văn bản cũ, test trên văn bản mới.

3. **Authority holdout**  
   Holdout một số bộ, tỉnh hoặc loại cơ quan.

4. **Rule-pattern holdout**  
   Test trên pattern chưa xuất hiện trong training.

5. **Hard-negative set**  
   Chỉ gồm clause có keyword nhưng không có quan hệ hợp lệ.

6. **Production audit set**  
   Sample từ 600.000 văn bản, được chuyên gia review.

7. **Reference resolution set**  
   Đánh giá riêng độ chính xác resolve target ID.

### 11.3. Metrics

Metric chính:

- Precision.
- Recall tại precision ≥ 0.99.
- Coverage tại precision ≥ 0.99.
- False positives trên 1.000 văn bản.
- Per-relation precision/recall.
- Hard-negative false-positive rate.
- Calibration/Brier score.
- Unseen-pattern precision.
- Reference resolution accuracy.
- Latency, throughput và memory.

F1 vẫn được báo cáo nhưng không phải tiêu chí quyết định duy nhất.

### 11.4. Confidence interval

Nên dùng Wilson confidence interval cho precision. Chỉ deploy khi lower bound của precision đạt ngưỡng, không chỉ point estimate.

---

## 12. Lộ trình thí nghiệm

### Phase 0 — Chuẩn hóa observability

Mỗi candidate phải ghi lại:

- `candidate_id`
- `rule_id`
- Cue span
- Reference span
- Current/parent/grandparent context
- Relation trước và sau refinement
- Filter decisions
- Authority decision
- Resolution result
- Final disposition

Deliverable:

- Candidate trace JSONL.
- Tool chuyển extraction output + golden labels thành candidate dataset.

### Phase 1 — Feature baseline

1. Sinh candidate trên `golden_eval`.
2. Gán positive/negative bằng evaluator.
3. Train Logistic Regression và LightGBM/CatBoost.
4. Calibration.
5. Báo cáo precision–coverage.

Tiêu chí:

- Phải vượt rule baseline về precision.
- Recall loss nằm trong budget.
- Inference overhead không đáng kể.

### Phase 2 — Hard-negative expansion

1. Thu thập FP từ benchmark.
2. Lấy distractor dataset.
3. Sinh negative bằng perturbation.
4. Sample production để review.
5. Retrain feature model.

### Phase 3 — Small text verifier

1. Fine-tune PhoBERT candidate classifier.
2. So sánh với feature model.
3. Thử ensemble.
4. Error analysis theo relation, authority và context source.

### Phase 4 — Domain-adaptive pretraining

1. Chuẩn bị corpus 600.000 văn bản.
2. Deduplicate và loại boilerplate bất thường.
3. Tiếp tục MLM pretraining.
4. Fine-tune lại NER/verifier.
5. So sánh với PhoBERT gốc.

### Phase 5 — Weak supervision

1. Chuyển các rule thành labeling functions.
2. Học probabilistic labels.
3. Train trên tập weak-labeled lớn.
4. Fine-tune lại bằng golden/human-reviewed data.

### Phase 6 — LLM teacher

1. Chọn candidate ở vùng uncertain.
2. LLM trả `KEEP/DROP/ABSTAIN`.
3. Human-review sample.
4. Distill vào small model.
5. Kiểm tra model nhỏ có giữ được precision gain không.

### Phase 7 — Shadow deployment

Model chạy song song nhưng chưa tác động graph:

```text
Rule production output
Model proposed decision
Human/benchmark truth khi có
```

Theo dõi:

- Candidate bị model loại.
- Candidate model chấp nhận thêm.
- Precision ước lượng theo sampling.
- Drift theo tháng, cơ quan và loại văn bản.

---

## 13. Tiêu chí ra quyết định

### Chấp nhận feature verifier nếu

- Precision tăng có ý nghĩa thống kê.
- Coverage đủ lớn.
- Recall loss nằm trong ngân sách.
- Feature importance hợp lý.
- Không làm tăng đáng kể latency.

### Chấp nhận small Transformer nếu

- Vượt feature baseline trên document/temporal holdout.
- Cải thiện trên unseen-pattern và hard-negative set.
- Calibration tốt sau hiệu chỉnh.
- Chi phí inference phù hợp.

### Chấp nhận domain pretraining nếu

- Cải thiện ổn định qua nhiều seed.
- Cải thiện cả NER và verifier.
- Không chỉ tăng điểm trên random split.

### Chấp nhận LLM online nếu

- Có lợi rõ ràng trên một nhóm relation cụ thể.
- Không làm giảm lower-bound precision.
- Có cơ chế abstain, cache, timeout và deterministic post-validation.
- Lợi ích lớn hơn chi phí vận hành và rủi ro drift.

Nếu không đạt các điều kiện này, LLM chỉ giữ vai trò offline.

---

## 14. Kiến trúc production đề xuất

```text
MongoDB parsed clauses
          │
          ▼
Reference extraction
  ├── Regex/config
  └── Optional NER candidate source
          │
          ▼
Relation cue extraction
          │
          ▼
Candidate construction
          │
          ├── Hard deterministic reject
          ├── High-confidence deterministic accept
          └── Uncertain candidate
                    │
                    ▼
          Feature model / small encoder
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
       ACCEPT     REJECT     ABSTAIN
          │                    │
          ▼                    ▼
 Authority/scope/conflict   Audit queue
 deterministic validation
          │
          ▼
 Reference resolution
          │
          ▼
 MongoDB cls_graph
          │
          ▼
 Strict graph writer
          │
          ▼
 Neo4j
```

Model artifact cần version hóa:

- Training dataset hash.
- Feature schema version.
- Code commit.
- Model version.
- Calibration parameters.
- Per-relation thresholds.
- Evaluation report.

Mọi candidate ghi vào graph nên lưu:

- Nguồn candidate.
- Rule ID.
- Model score.
- Threshold được áp dụng.
- Model version.
- Các deterministic checks đã qua.

---

## 15. Khuyến nghị cuối cùng

1. Không thay rule engine bằng LLM.
2. Không dùng additive LLM fallback cho mục tiêu precision-first.
3. Bắt đầu bằng candidate-level feature model.
4. Sau đó thử PhoBERT/Legal-PhoBERT candidate verifier.
5. Dùng NER để tăng độ phủ reference, không ghi thẳng output NER vào graph.
6. Dùng 600.000 văn bản cho domain-adaptive pretraining và weak supervision.
7. Đầu tư mạnh vào hard-negative mining và production audit set.
8. Dùng LLM 27B làm teacher, error analyst và active-learning assistant.
9. Production phải hỗ trợ `abstain`, threshold theo relation và calibration.
10. Quyết định theo precision–coverage và temporal/document holdout, không chỉ theo F1 trên benchmark hiện tại.

Kiến trúc mục tiêu:

> **Rules for recall, small discriminative models for precision, deterministic constraints for legal safety, and LLMs only for offline knowledge transfer.**

---

## 16. Tài liệu nghiên cứu tham khảo

- Snorkel: Rapid Training Data Creation with Weak Supervision  
  <https://arxiv.org/abs/1711.10160>

- Data Programming: Creating Large Training Sets, Quickly  
  <https://arxiv.org/abs/1605.07723>

- Don't Stop Pretraining: Adapt Language Models to Domains and Tasks  
  <https://aclanthology.org/2020.acl-main.740/>

- PhoBERT: Pre-trained Language Models for Vietnamese  
  <https://aclanthology.org/2020.findings-emnlp.92/>

- LEGAL-BERT: The Muppets Straight Out of Law School  
  <https://aclanthology.org/2020.findings-emnlp.261/>

- A Frustratingly Easy Approach for Entity and Relation Extraction  
  <https://aclanthology.org/2021.naacl-main.5/>

- GLiNER: Generalist Model for Named Entity Recognition  
  <https://arxiv.org/abs/2311.08526>

- On Calibration of Modern Neural Networks  
  <https://proceedings.mlr.press/v70/guo17a.html>

- SelectiveNet: A Deep Neural Network with an Integrated Reject Option  
  <https://proceedings.mlr.press/v97/geifman19a.html>
