# Offline Training Pipeline

Thư mục này triển khai research harness cho kiến trúc hybrid trong
[`idea.md`](../idea.md). Code production trong `src/` không bị thay đổi.

> **Dataset status:** dữ liệu hiện tại chỉ đủ cho benchmark và prototype, chưa đủ để
> train model production. Xem yêu cầu lấy dữ liệu, schema annotation và mốc quy mô tại
> [`DATASET_REQUIREMENTS.md`](DATASET_REQUIREMENTS.md).

## Nguyên tắc

```text
Rules/Regex candidates
        ↓
Deterministic checks
        ↓
Calibrated feature model
        ↓ uncertain only
PhoBERT binary verifier
        ↓
Resolution + legal constraints
        ↓
ACCEPT / REJECT / ABSTAIN
```

LLM 27B không chạy trên toàn bộ corpus. Phase 6 chỉ tạo audit queue để expert
hoặc LLM teacher xử lý chọn lọc.

## Cấu trúc

| Phase | File | Kết quả |
|---|---|---|
| 0 | `phase0_build_candidates.py` | Candidate JSONL và candidate-recall ceiling |
| 1 | `phase1_train_features.py` | Logistic/LightGBM, calibration và thresholds |
| 2 | `phase2_mine_hard_negatives.py` | Hard-negative JSONL |
| 3 | `phase3_train_phobert.py` | Binary PhoBERT candidate verifier |
| 4 | `phase4_domain_pretrain.py` | Legal-PhoBERT qua masked language modelling |
| 5 | `phase5_train_ner.py` | Optional reference NER |
| 6 | `phase6_export_audit_queue.py` | Candidate abstention queue |

## Cài đặt

Các phase rule-only dùng dependency hiện tại của repo. Các phase ML cần:

```powershell
python -m pip install -r training/requirements.txt
```

Torch nên được cài theo CUDA version của máy trước khi chạy Phase 3–5 nếu cần
GPU. Không thêm các dependency này vào `requirements.txt` chính để production
rule pipeline vẫn nhẹ.

## Phase 0 — Candidate instrumentation

Chạy trên full golden set và hard negatives:

```powershell
python -m training.run phase0
```

Smoke test:

```powershell
python -m training.run phase0 --limit 20
```

Output mặc định:

- `training/data/generated/candidates.jsonl`
- `training/artifacts/phase0_summary.json`

Candidate được tạo từ:

- Cặp mà production matcher đã ghép.
- Tối đa `k` near-miss references gần mỗi action cue.

Không full cross-join trong production candidate generation.

Quy tắc gán nhãn:

- Khớp gold → `VALID`.
- Production prediction không khớp gold → `INVALID`.
- Candidate từ distractor set → `INVALID`.
- Near-miss chưa được chứng minh sai → `UNKNOWN`.

Nếu xác nhận mọi clause trong dataset đã được annotation exhaustive:

```powershell
python -m training.run phase0 --assume-exhaustive
```

Khi đó mọi near-miss không khớp gold được gán `INVALID`. Không nên dùng flag này
nếu chưa audit độ đầy đủ của annotation.

`phase0_summary.json` báo `candidate_recall_ceiling`. Đây là giới hạn trên của
mọi classifier phía sau. Nếu ceiling thấp, cần sửa candidate generation hoặc
thêm NER; đổi classifier không thể cứu gold relation chưa từng được tạo.

## Phase 1 — Feature baseline

Logistic Regression:

```powershell
python -m training.run phase1 --model logistic
```

LightGBM:

```powershell
python -m training.run phase1 --model lightgbm
```

Model dùng document-group split xác định theo `so_hieu`; candidate cùng văn bản
không bị chia qua train/test.

Artifact:

```text
training/artifacts/phase1/
├── feature_model.joblib
└── report.json
```

`report.json` gồm:

- Classification metrics.
- Threshold `ACCEPT`/`REJECT` theo relation.
- Wilson precision lower bound.
- Coverage của ba vùng `ACCEPT/REJECT/UNCERTAIN`.

Ví dụ thay đổi quality target:

```powershell
python -m training.run phase1 `
  --target-precision 0.99 `
  --target-negative-precision 0.98 `
  --min-threshold-count 20
```

Nếu dataset chưa đủ lớn, threshold có thể không auto-accept/reject candidate
nào. Đây là kết quả hợp lệ, không nên hạ threshold chỉ để tạo coverage đẹp.

## Phase 2 — Hard-negative mining

```powershell
python -m training.run phase2
```

Hardness ưu tiên:

- Production false positive.
- Action/reference cùng hard scope.
- Candidate gần action.
- Clause chứa nhiều action và reference.
- Reference có document number hoặc clause component.

Output:

```text
training/data/generated/hard_negatives.jsonl
```

`UNKNOWN` mặc định không được coi là negative. Chỉ thêm khi đã có chiến lược
review:

```powershell
python -m training.run phase2 --include-unknown
```

## Phase 3 — PhoBERT binary verifier

```powershell
python -m training.run phase3 `
  --model-id vinai/phobert-base-v2 `
  --epochs 3 `
  --batch-size 16
```

Input của model đánh dấu riêng:

- Proposed relation.
- Source document.
- Grandparent/parent/current clause.
- `[ACT]...[/ACT]`.
- `[REF]...[/REF]`.
- Một tập feature rút gọn.

Phase đầu chỉ học `VALID/INVALID`. Không ép model học lại 15 relation types khi
mục tiêu trước mắt là lọc false positive. Relation correction/multi-task là
thí nghiệm sau khi binary verifier vượt feature baseline.

Artifact:

```text
training/artifacts/phase3_phobert/
├── model/
└── report.json
```

## Phase 4 — Domain-adaptive pretraining

Chuẩn bị corpus sạch từ export MongoDB. Bước này tự động loại document trùng
`golden_eval`, clean HTML, deduplicate clause và split theo document:

```powershell
python -m training.run prepare-dapt
```

Mặc định mỗi document đóng góp tối đa 120 clause được lấy cách đều để văn bản hợp
nhất hoặc văn bản rất dài không áp đảo số token. Có thể thay đổi bằng
`--max-clauses-per-document`.

Output:

```text
training/data/dapt/
├── train.jsonl
├── validation.jsonl
└── manifest.json
```

Phase 4 tokenize toàn bộ text rồi ghép thành block token; không truncate từng clause:

```powershell
python -m training.run phase4 `
  --corpus training/data/dapt `
  --epochs 1
```

Hướng dẫn đầy đủ để đóng gói corpus và chạy trên Kaggle T4 x2:
[`KAGGLE_DAPT.md`](KAGGLE_DAPT.md).

Sau đó dùng artifact làm `--model-id` cho Phase 3:

```powershell
python -m training.run phase3 `
  --model-id training/artifacts/phase4_legal_phobert/model
```

Phải so sánh PhoBERT gốc và Legal-PhoBERT trên cùng document/temporal holdout.

## Phase 5 — Optional NER

Chỉ chạy khi FN analysis cho thấy regex bỏ sót reference là bottleneck.

Schema JSONL:

```json
{
  "tokens": ["Điều", "5", "Nghị", "định", "10/2023/NĐ-CP"],
  "ner_tags": [5, 6, 1, 2, 3],
  "label_names": ["O", "B-DOC", "I-DOC", "B-DOC_NUMBER", "..."]
}
```

Schema minh họa có tại `training/data/ner_schema_example.jsonl`. File này có nhãn
`EXAMPLE_ONLY`, không phải dataset train.

```powershell
python -m training.run phase5 `
  --dataset training/data/ner_train.jsonl
```

NER chỉ bổ sung candidate. Output NER không được ghi trực tiếp vào KG.

## Phase 6 — Audit queue

Sau Phase 1:

```powershell
python -m training.run phase6
```

Mặc định chỉ score candidate `UNKNOWN` và xuất những candidate nằm giữa hai
threshold:

```text
training/data/generated/audit_queue.jsonl
```

Queue này phục vụ:

- Expert review.
- LLM 27B teacher.
- Active learning.
- Error clustering.

LLM verdict không phải ground truth và không được ghi edge trực tiếp.

## Evaluation contract

Các phase phải báo:

- Candidate recall ceiling.
- Precision và Wilson 95% confidence interval.
- Recall tại precision target.
- ACCEPT/REJECT coverage.
- Abstention rate.
- Metrics theo relation.
- Document/temporal holdout.
- Hard-negative FP rate.
- Wall-clock throughput.

Không dùng random candidate split vì gây leakage từ cùng văn bản.

## Trình tự khuyến nghị

1. Chạy Phase 0 và audit candidate recall.
2. Chạy Logistic Regression trước.
3. Chạy LightGBM chỉ khi logistic cho thấy feature có tín hiệu.
4. Mở rộng hard negatives.
5. Chỉ train PhoBERT nếu feature model chưa đạt precision–coverage mục tiêu.
6. Chỉ train NER khi reference recall là bottleneck.
7. Chỉ tối ưu ONNX/TensorRT sau khi model chứng minh accuracy gain.
