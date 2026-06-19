#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

export PIP_DISABLE_PIP_VERSION_CHECK=1
export TOKENIZERS_PARALLELISM=false
export HF_HOME="${HF_HOME:-/kaggle/working/.cache/huggingface}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-${HF_HOME}/datasets}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HOME}/transformers}"

mkdir -p "${HF_HOME}" "${HF_DATASETS_CACHE}" "${TRANSFORMERS_CACHE}"

echo "[setup] Python: $(python --version)"
echo "[setup] Installing DAPT dependencies without replacing Kaggle PyTorch..."
python -m pip install --quiet --upgrade -r training/requirements-kaggle.txt

python - <<'PY'
import json
import torch
import transformers
import datasets
import accelerate

gpus = [
    {
        "index": index,
        "name": torch.cuda.get_device_name(index),
        "memory_gib": round(
            torch.cuda.get_device_properties(index).total_memory / 1024**3, 2
        ),
    }
    for index in range(torch.cuda.device_count())
]
print(json.dumps({
    "torch": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_version": torch.version.cuda,
    "gpus": gpus,
    "transformers": transformers.__version__,
    "datasets": datasets.__version__,
    "accelerate": accelerate.__version__,
}, indent=2))

if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available. Enable GPU in Kaggle settings.")
PY

python -m py_compile \
  training/phase4_domain_pretrain.py \
  training/prepare_dapt_corpus.py \
  training/run.py

echo "[setup] Environment ready."
