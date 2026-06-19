# DAPT PhoBERT trên Kaggle T4 x2

Mục tiêu của bước này là tiếp tục pretrain `vinai/phobert-base-v2` bằng masked
language modeling trên corpus pháp luật đã làm sạch. Bước này không gọi LLM và
không học nhãn quan hệ.

## 1. Chuẩn bị trước khi push GitHub

Corpus JSONL thô đã được tạo tại:

```text
training/data/dapt/
├── train.jsonl
├── validation.jsonl
└── manifest.json
```

Nén corpus để đưa lên GitHub:

```powershell
python training/kaggle/package_corpus.py
```

Sau lệnh này cần có:

```text
training/data/dapt/
├── train.jsonl.gz
├── validation.jsonl.gz
├── manifest.json
└── package_manifest.json
```

Chỉ commit các file `.jsonl.gz` và manifest. Không commit JSONL thô.

```powershell
git add training/data/dapt/*.jsonl.gz
git add training/data/dapt/*manifest.json
git add training/kaggle training/KAGGLE_DAPT.md
git commit -m "Add Kaggle DAPT training workflow"
git push
```

`train.jsonl.gz` phải nhỏ hơn giới hạn file 100 MiB của GitHub. Nếu repository
không cho phép commit binary dataset, có thể upload hai file gzip thành Kaggle
Dataset và đặt `CORPUS_DIR` tới thư mục input đó.

## 2. Tạo Kaggle Notebook

Trong Notebook settings:

- Accelerator: `GPU T4 x2`.
- Internet: bật để clone GitHub và tải PhoBERT.
- Persistence: bật nếu tài khoản hỗ trợ.

Clone repository vào `/kaggle/working`:

```bash
cd /kaggle/working
git clone https://github.com/<owner>/<repo>.git cai-legal-research
cd cai-legal-research
```

Nếu repository private, dùng Kaggle Secret thay vì ghi token trực tiếp vào
notebook.

## 3. Cài môi trường

```bash
bash training/kaggle/setup.sh
```

Script giữ nguyên PyTorch/CUDA do Kaggle cung cấp và chỉ cài:

- Transformers
- Datasets
- Accelerate
- SentencePiece
- Safetensors

Output kiểm tra phải hiển thị `cuda_available: true` và hai GPU.

## 4. Chạy DAPT

```bash
bash training/kaggle/run_dapt.sh
```

Cấu hình mặc định cho T4 x2:

| Tham số | Giá trị |
|---|---:|
| Sequence length | 256 |
| Batch mỗi GPU | 8 |
| Gradient accumulation | 2 |
| Effective global batch | 32 |
| Epoch | 1 |
| FP16 | Tự động bật |
| Checkpoint | Mỗi 500 optimizer steps |
| Giữ checkpoint | 2 |

Script tự dùng số GPU mà PyTorch nhìn thấy. Trên T4 x2, `torchrun` tạo hai DDP
process.

## 5. Điều chỉnh khi cần

Nếu CUDA OOM:

```bash
BATCH_SIZE=4 GRAD_ACC=4 bash training/kaggle/run_dapt.sh
```

Effective global batch vẫn là 32.

Chạy một GPU để debug:

```bash
NPROC_PER_NODE=1 BATCH_SIZE=8 GRAD_ACC=4 bash training/kaggle/run_dapt.sh
```

Đổi output:

```bash
OUTPUT_DIR=/kaggle/working/my_dapt_run bash training/kaggle/run_dapt.sh
```

Tắt auto-resume:

```bash
AUTO_RESUME=0 bash training/kaggle/run_dapt.sh
```

Mặc định script tự resume checkpoint gần nhất trong `OUTPUT_DIR`.

## 6. Artifact

Khi hoàn tất:

```text
/kaggle/working/phase4_legal_phobert/
├── model/
└── report.json

/kaggle/working/legal-phobert-dapt.tar.gz
```

Tải `legal-phobert-dapt.tar.gz` từ tab Output hoặc lưu một Notebook Version.

`report.json` chứa:

- Số records và token blocks.
- Effective global batch size.
- Train/eval loss.
- Perplexity.
- Checkpoint đã resume.

MLM loss chỉ xác nhận DAPT chạy đúng. Hiệu quả cuối cùng phải được quyết định
bằng ablation trên candidate verifier:

```text
PhoBERT gốc + cùng labels
so với
Legal-PhoBERT DAPT + cùng labels
```

## 7. Bước sau DAPT

Sau khi tải artifact về:

```powershell
tar -xzf legal-phobert-dapt.tar.gz
```

Model tại `model/` sẽ được dùng làm `--model-id` cho Phase 3. Song song với DAPT,
có thể thực hiện bước sinh candidate và gọi LLM teacher để chuẩn bị silver
labels; hai công việc độc lập.
