"""Central configuration for the relation-extraction LLM study.

All tunables live here so no magic constants are scattered across the
harness. Environment values (model id, base url, api key) are read from the
project ``.env`` exactly once, the same file the production pipeline uses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_DIR = PROJECT_ROOT / "experiment"
RESULTS_DIR = EXPERIMENT_DIR / "results"
REPORT_DIR = EXPERIMENT_DIR / "report"
CACHE_DIR = EXPERIMENT_DIR / ".cache"

DATASETS = {
    "golden": PROJECT_ROOT / "evaluation" / "datasets" / "golden_eval.csv",
    "pairs": PROJECT_ROOT / "evaluation" / "datasets" / "relation_pairs.csv",
    "distractors": PROJECT_ROOT / "evaluation" / "datasets" / "distractor_candidates.csv",
}

# Load the project .env once (same file the production pipeline reads).
load_dotenv(PROJECT_ROOT / ".env")

# --- Matching contract (must mirror evaluation defaults) -------------------
JACCARD_THRESHOLD = 0.65

# --- Concurrency -----------------------------------------------------------
# No-think calls are ~0.4s; the gateway tolerates parallelism well.
DEFAULT_WORKERS = 12


@dataclass(frozen=True)
class ModelConfig:
    """Everything needed to call one chat model through an OpenAI-compatible API."""

    name: str
    model_id: str
    base_url: Optional[str]
    api_key: Optional[str]
    # cmc-legal-27 is a Qwen-family reasoning model. Thinking is disabled by
    # passing chat_template_kwargs.enable_thinking=False through extra_body.
    # Other providers (Gemini) ignore this and use ``supports_thinking_toggle=False``.
    supports_thinking_toggle: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.model_id and self.base_url)


def legal_model() -> ModelConfig:
    """The internal model under evaluation (cmc-legal-27)."""
    return ModelConfig(
        name="cmc-legal",
        model_id=os.environ.get("LEGAL_LLM_MODEL_ID", ""),
        base_url=os.environ.get("LEGAL_LLM_BASE_URL", ""),
        api_key=os.environ.get("LEGAL_LLM_API_KEY", ""),
        supports_thinking_toggle=True,
    )


def gemini_model(model_id: str = "gemini-2.5-flash-lite") -> ModelConfig:
    """Control model: Gemini via its OpenAI-compatible endpoint.

    Used only to separate "is it *this* model" from "LLMs in general".
    """
    return ModelConfig(
        name="gemini",
        model_id=model_id,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        supports_thinking_toggle=False,
    )
