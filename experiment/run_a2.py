"""Measure A2 — the *current* production ``--use-llm`` additive fallback.

Importing ``experiment.config`` first loads the project ``.env`` so the
production ``LangExtractRelationFallback`` finds ``LEGAL_LLM_*`` and actually
calls the model. Runs the real production evaluator path (rule + LLM fallback)
so the number reflects what shipping today's code would do.
"""

from __future__ import annotations

import sys

import experiment.config  # noqa: F401 - import side effect: loads .env
from evaluation.evaluate import evaluate_pipeline


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = evaluate_pipeline(
        dataset_path="evaluation/datasets/golden_eval.csv",
        output_path="experiment/results/a2_current_fallback_raw.json",
        use_llm=True,
    )
    o = report["overall"]
    print(f"A2 rule+current-fallback OVERALL: P={o['precision']:.3f} "
          f"R={o['recall']:.3f} F1={o['f1']:.3f} (TP={o['tp']} FP={o['fp']} FN={o['fn']})")


if __name__ == "__main__":
    main()
