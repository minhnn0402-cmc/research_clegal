"""A0 — Rule-only baseline (current production behaviour)."""

from __future__ import annotations

from typing import Dict, List

from experiment.architectures.base import dedupe
from experiment.clause_dataset import ClauseUnit
from experiment.rule_engine import RuleEngine


class RuleOnlyArchitecture:
    name = "a0_rule_only"

    def __init__(self, rule_engine: RuleEngine) -> None:
        self._rules = rule_engine

    def predict(self, unit: ClauseUnit) -> List[Dict]:
        return dedupe(self._rules.predict(unit))
