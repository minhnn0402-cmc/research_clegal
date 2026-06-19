"""Unified command-line entry point for all training phases."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import List


PHASE_MODULES = {
    "prepare-candidates": "training.prepare_candidate_pool",
    "prepare-dapt": "training.prepare_dapt_corpus",
    "phase0": "training.phase0_build_candidates",
    "phase1": "training.phase1_train_features",
    "phase2": "training.phase2_mine_hard_negatives",
    "phase3": "training.phase3_train_phobert",
    "phase4": "training.phase4_domain_pretrain",
    "phase5": "training.phase5_train_ner",
    "phase6": "training.phase6_export_audit_queue",
}


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("phase", choices=sorted(PHASE_MODULES))
        parser.print_help()
        return 0
    phase, remainder = argv[0], argv[1:]
    if phase not in PHASE_MODULES:
        raise SystemExit(
            f"Unknown phase {phase!r}. Choose one of: {', '.join(sorted(PHASE_MODULES))}"
        )
    module = importlib.import_module(PHASE_MODULES[phase])
    return int(module.main(remainder) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
