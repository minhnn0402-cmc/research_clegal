"""Orchestrate the full benchmark and persist result bundles.

Usage examples:
    PYTHONPATH=. python -m experiment.run_all --dataset golden --workers 12
    PYTHONPATH=. python -m experiment.run_all --dataset golden --sample 60 --workers 8
    PYTHONPATH=. python -m experiment.run_all --dataset distractors --architectures a0 a1 a3_all

Bundles are written to ``experiment/results/<arch>__<dataset>.json`` and can be
re-analysed offline (error analysis, cost model, McNemar) without re-calling
the model.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List

from experiment.architectures.a0_rule_only import RuleOnlyArchitecture
from experiment.architectures.a1_llm_extractor import LlmExtractorArchitecture
from experiment.architectures.a3_llm_gate import LlmGateArchitecture
from experiment.clause_dataset import (
    ClauseUnit, load_clause_units, load_distractor_units, stratified_sample,
)
from experiment.config import DATASETS, DEFAULT_WORKERS, gemini_model, legal_model
from experiment.llm_client import LlmClient
from experiment.rule_engine import RuleEngine
from experiment.runner import run_architecture, save_bundle, summary_line

# Threshold below which a relation type is considered low-precision and worth
# gating in the targeted variant. Derived from the A0 baseline at runtime.
LOW_PRECISION_THRESHOLD = 0.85
A1_MAX_TOKENS = 4096   # multi-entity extraction in thinking mode
GATE_MAX_TOKENS = 32   # {"verdict":"YES"} is ~7 tokens


def _load_units(dataset: str) -> List[ClauseUnit]:
    if dataset == "distractors":
        return load_distractor_units(DATASETS["distractors"])
    return load_clause_units(DATASETS[dataset])


def _low_precision_types(a0_bundle: Dict) -> set:
    types = {
        rel for rel, m in a0_bundle["by_relation_type"].items()
        if (m["tp"] + m["fp"]) >= 10 and m["precision"] < LOW_PRECISION_THRESHOLD
    }
    return types


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Run the relation-extraction LLM benchmark.")
    ap.add_argument("--dataset", default="golden", choices=list(DATASETS))
    ap.add_argument("--sample", type=int, default=0, help="Stratified subset size (0 = full).")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--architectures", nargs="+",
                    default=["a0", "a1", "a3_all", "a3_targeted"],
                    help="Any of: a0 a1 a3_all a3_targeted (+ _gemini variants a1_gemini a3_gemini).")
    args = ap.parse_args(argv)

    units = _load_units(args.dataset)
    if args.sample and args.sample < len(units):
        units = stratified_sample(units, args.sample)
    tag = args.dataset + (f"_s{len(units)}" if args.sample else "")
    print(f"Dataset: {args.dataset}  | units: {len(units)}  | workers: {args.workers}\n")

    rules = RuleEngine()
    legal = legal_model()
    bundles: Dict[str, Dict] = {}

    # A0 must run first; the targeted gate's scope derives from it.
    if any(a.startswith("a0") or a == "a3_targeted" for a in args.architectures):
        b = run_architecture(RuleOnlyArchitecture(rules), units, workers=args.workers)
        bundles["a0_rule_only"] = b
        save_bundle(b, f"a0_rule_only__{tag}.json")
        print(summary_line(b))

    gated = _low_precision_types(bundles["a0_rule_only"]) if "a0_rule_only" in bundles else set()
    if "a3_targeted" in args.architectures:
        print(f"  targeted-gate scope (P<{LOW_PRECISION_THRESHOLD}): {sorted(gated)}")

    def legal_a1():
        return LlmExtractorArchitecture(
            LlmClient(legal, enable_thinking=True, max_tokens=A1_MAX_TOKENS, cache_namespace="a1"))

    def legal_gate(gated_types, name):
        return LlmGateArchitecture(
            rules, LlmClient(legal, enable_thinking=False, max_tokens=GATE_MAX_TOKENS, cache_namespace="gate"),
            gated_types=gated_types, name=name)

    plan = []
    if "a1" in args.architectures:
        plan.append(legal_a1())
    if "a3_all" in args.architectures:
        plan.append(legal_gate(None, "a3_gate_all"))
    if "a3_targeted" in args.architectures:
        plan.append(legal_gate(gated, "a3_gate_targeted"))
    # Gemini free tier = 10 req/min; pace under that and run single-threaded.
    gemini_interval = 6.5
    if "a1_gemini" in args.architectures:
        arch = LlmExtractorArchitecture(
            LlmClient(gemini_model(), max_tokens=A1_MAX_TOKENS,
                      min_interval_s=gemini_interval, cache_namespace="a1"))
        arch.name = "a1_llm_extractor_gemini"
        plan.append(arch)
    if "a3_gemini" in args.architectures:
        plan.append(LlmGateArchitecture(
            rules, LlmClient(gemini_model(), max_tokens=GATE_MAX_TOKENS,
                             min_interval_s=gemini_interval, cache_namespace="gate"),
            gated_types=None, name="a3_gate_all_gemini"))

    for arch in plan:
        telemetry = getattr(arch, "_client", None)
        b = run_architecture(arch, units, workers=args.workers)
        if telemetry is not None:
            b["telemetry"] = telemetry.stats.to_dict()
        bundles[arch.name] = b
        save_bundle(b, f"{arch.name}__{tag}.json")
        print(summary_line(b))

    print("\n=== Summary ===")
    for name, b in bundles.items():
        print(summary_line(b))


if __name__ == "__main__":
    main()
