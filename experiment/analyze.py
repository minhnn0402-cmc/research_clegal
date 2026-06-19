"""Consolidated offline analysis over saved result bundles for one dataset tag.

Reads every ``*__<tag>.json`` bundle in results/, then emits a single
``analysis_<tag>.json`` plus a printed report: comparison table with Wilson
CIs, McNemar paired tests vs the A0 baseline, FP/FN cause breakdowns, the
A0-vs-A3 gate diff, and the production cost extrapolation. Makes no model
calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from experiment.config import RESULTS_DIR
from experiment.cost_model import extrapolate, profile_from_bundle
from experiment.error_analysis import diff_a0_a3, label_audit
from experiment.stats import mcnemar_test


def _recovered_and_gold(bundle: Dict) -> Tuple[set, set]:
    gold, recovered = set(), set()
    for row in bundle["rows"]:
        key = tuple(row["key"])
        missed = {(key, fn["relation"], fn["reference"]) for fn in row["fn"]}
        for gt in row["ground_truth"]:
            item = (key, gt["relation"], gt["reference"])
            gold.add(item)
            if item not in missed:
                recovered.add(item)
    return recovered, gold


def load_bundles(tag: str) -> Dict[str, Dict]:
    bundles: Dict[str, Dict] = {}
    for path in sorted(Path(RESULTS_DIR).glob(f"*__{tag}.json")):
        b = json.loads(path.read_text(encoding="utf-8"))
        bundles[b["architecture"]] = b
    return bundles


def analyze(tag: str) -> Dict:
    bundles = load_bundles(tag)
    if not bundles:
        raise FileNotFoundError(f"No bundles for tag {tag!r} in {RESULTS_DIR}")

    a0 = bundles.get("a0_rule_only")
    a0_recovered = _recovered_and_gold(a0)[0] if a0 else set()

    table: List[Dict] = []
    mcnemar: Dict[str, Dict] = {}
    for name, b in bundles.items():
        o = b["overall"]
        table.append({
            "architecture": name, "precision": o["precision"],
            "precision_ci95": o.get("precision_ci95"), "recall": o["recall"],
            "f1": o["f1"], "tp": o["tp"], "fp": o["fp"], "fn": o["fn"],
        })
        if a0 and name != "a0_rule_only":
            rec, _ = _recovered_and_gold(b)
            only_a0 = len(a0_recovered - rec)   # baseline recovered, system missed
            only_x = len(rec - a0_recovered)    # system recovered, baseline missed
            chi2, p = mcnemar_test(only_a0, only_x)
            mcnemar[name] = {"only_a0_recovered": only_a0, "only_system_recovered": only_x,
                             "chi2": chi2, "p_value": p}

    audits = {name: label_audit(b) for name, b in bundles.items()}
    diffs = {
        name: diff_a0_a3(a0, b)
        for name, b in bundles.items()
        if a0 and name.startswith("a3")
    }
    costs = {}
    for name, b in bundles.items():
        prof = profile_from_bundle(b)
        if prof:
            costs[name] = {cpd: extrapolate(prof, clauses_per_doc=cpd) for cpd in (15, 30, 60)}

    return {"tag": tag, "table": table, "mcnemar_vs_a0": mcnemar,
            "label_audit": audits, "gate_diffs": diffs, "cost_extrapolation": costs}


def print_report(analysis: Dict) -> None:
    print(f"\n{'=' * 78}\nANALYSIS — {analysis['tag']}\n{'=' * 78}")
    print(f"{'architecture':<26}{'P':>7} {'95% CI':>15} {'R':>7} {'F1':>7}   TP/FP/FN")
    print("-" * 78)
    for r in sorted(analysis["table"], key=lambda x: x["architecture"]):
        ci = r.get("precision_ci95") or [0, 0]
        print(f"{r['architecture']:<26}{r['precision']:>7.3f} "
              f"[{ci[0]:.3f},{ci[1]:.3f}] {r['recall']:>7.3f} {r['f1']:>7.3f}   "
              f"{r['tp']}/{r['fp']}/{r['fn']}")

    if analysis["mcnemar_vs_a0"]:
        print(f"\nMcNemar vs A0 (gold-recovery, paired):")
        for name, m in analysis["mcnemar_vs_a0"].items():
            sig = "significant" if m["p_value"] < 0.05 else "n.s."
            print(f"  {name:<24} A0-only={m['only_a0_recovered']:<4} "
                  f"sys-only={m['only_system_recovered']:<4} p={m['p_value']:.4g} ({sig})")

    print("\nGate diffs (A0 -> A3):")
    for name, d in analysis["gate_diffs"].items():
        print(f"  {name:<24} pruned FP (precision gain)={d['pruned_false_positives']:<4} "
              f"pruned TP (recall loss)={d['pruned_true_positives']}")

    print("\nLabel audit (amend-granularity artifacts):")
    for name, a in analysis["label_audit"].items():
        print(f"  {name:<24} FP={a['total_fp']:<4}(artifact {a['amend_granularity_fp']})  "
              f"FN={a['total_fn']:<4}(artifact {a['amend_granularity_fn']})")

    if analysis["cost_extrapolation"]:
        print("\nCost @600k docs, 30 clauses/doc, 32 workers:")
        for name, by_cpd in analysis["cost_extrapolation"].items():
            c = by_cpd[30]
            print(f"  {name:<24} calls={c['total_calls_millions']}M  "
                  f"tokens={c['total_tokens_billions']}B  wall={c['wall_clock_hours']}h "
                  f"({c['wall_clock_days']}d)")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    tag = (argv or sys.argv[1:] or ["golden"])[0]
    analysis = analyze(tag)
    out = Path(RESULTS_DIR) / f"analysis_{tag}.json"
    out.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(analysis)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
