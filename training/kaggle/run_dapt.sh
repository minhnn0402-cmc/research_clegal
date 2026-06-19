#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

export TOKENIZERS_PARALLELISM=false
export HF_HOME="${HF_HOME:-/kaggle/working/.cache/huggingface}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-${HF_HOME}/datasets}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HOME}/transformers}"
export NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"

CORPUS_DIR="${CORPUS_DIR:-training/data/dapt}"
OUTPUT_DIR="${OUTPUT_DIR:-/kaggle/working/phase4_legal_phobert}"
MODEL_ID="${MODEL_ID:-vinai/phobert-base-v2}"
MAX_LENGTH="${MAX_LENGTH:-256}"
EPOCHS="${EPOCHS:-1}"
BATCH_SIZE="${BATCH_SIZE:-8}"
GRAD_ACC="${GRAD_ACC:-2}"
PREPROCESS_WORKERS="${PREPROCESS_WORKERS:-2}"
DATALOADER_WORKERS="${DATALOADER_WORKERS:-2}"
SAVE_STEPS="${SAVE_STEPS:-500}"
EVAL_STEPS="${EVAL_STEPS:-500}"
LOGGING_STEPS="${LOGGING_STEPS:-25}"
SEED="${SEED:-13}"
AUTO_RESUME="${AUTO_RESUME:-1}"

if [[ ! -f "${CORPUS_DIR}/train.jsonl" && ! -f "${CORPUS_DIR}/train.jsonl.gz" ]]; then
  echo "Missing train.jsonl(.gz) in ${CORPUS_DIR}" >&2
  exit 1
fi
if [[ ! -f "${CORPUS_DIR}/validation.jsonl" && ! -f "${CORPUS_DIR}/validation.jsonl.gz" ]]; then
  echo "Missing validation.jsonl(.gz) in ${CORPUS_DIR}" >&2
  exit 1
fi

GPU_COUNT="$(python - <<'PY'
import torch
print(torch.cuda.device_count())
PY
)"
if [[ "${GPU_COUNT}" -lt 1 ]]; then
  echo "No CUDA GPU detected." >&2
  exit 1
fi
NPROC_PER_NODE="${NPROC_PER_NODE:-${GPU_COUNT}}"

mkdir -p "${OUTPUT_DIR}"

echo "[run] GPUs=${GPU_COUNT}; DDP processes=${NPROC_PER_NODE}"
echo "[run] model=${MODEL_ID}"
echo "[run] corpus=${CORPUS_DIR}"
echo "[run] output=${OUTPUT_DIR}"
echo "[run] per-device batch=${BATCH_SIZE}; accumulation=${GRAD_ACC}"
echo "[run] effective global batch=$((BATCH_SIZE * GRAD_ACC * NPROC_PER_NODE))"

RESUME_ARGS=()
if [[ "${AUTO_RESUME}" == "1" ]]; then
  RESUME_ARGS+=(--resume-from-checkpoint)
fi

torchrun \
  --standalone \
  --nnodes=1 \
  --nproc_per_node="${NPROC_PER_NODE}" \
  -m training.run phase4 \
  --corpus "${CORPUS_DIR}" \
  --output-dir "${OUTPUT_DIR}" \
  --model-id "${MODEL_ID}" \
  --max-length "${MAX_LENGTH}" \
  --epochs "${EPOCHS}" \
  --batch-size "${BATCH_SIZE}" \
  --gradient-accumulation-steps "${GRAD_ACC}" \
  --preprocessing-workers "${PREPROCESS_WORKERS}" \
  --dataloader-workers "${DATALOADER_WORKERS}" \
  --save-steps "${SAVE_STEPS}" \
  --eval-steps "${EVAL_STEPS}" \
  --logging-steps "${LOGGING_STEPS}" \
  --save-total-limit 2 \
  --seed "${SEED}" \
  "${RESUME_ARGS[@]}"

ARTIFACT="/kaggle/working/legal-phobert-dapt.tar.gz"
tar -czf "${ARTIFACT}" -C "${OUTPUT_DIR}" model report.json

echo "[run] Training complete."
echo "[run] Model directory: ${OUTPUT_DIR}/model"
echo "[run] Report: ${OUTPUT_DIR}/report.json"
echo "[run] Download artifact: ${ARTIFACT}"
