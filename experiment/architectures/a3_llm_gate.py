"""A3 — Rule-first + LLM conservative precision gate (the precision-first design).

Rules generate candidates (the production recall net, including document-level
reference resolution). The LLM then acts as a *false-positive detector*: it
trusts the rule by default and answers ``NO`` only on positive local evidence
that the candidate is wrong (passive history, self-reference, title-only, no
matching action verb). Everything else is kept. The gate can only *prune*,
never inject, so A3's kept set is always a subset of A0's candidates — a later
A0-vs-A3 diff exactly quantifies false positives pruned (precision gain) vs
true positives pruned (recall loss).

``gated_types`` optionally restricts the gate to specific relation types (the
low-precision ones), leaving high-precision types untouched to minimise
true-positive pruning. Parse failures default to KEEP (abstain-to-keep).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from experiment.architectures.base import dedupe
from experiment.clause_dataset import ClauseUnit
from experiment.llm_client import LlmClient
from experiment.prompts import GATE_SYSTEM, gate_user
from experiment.rule_engine import RuleEngine


class LlmGateArchitecture:
    def __init__(
        self,
        rule_engine: RuleEngine,
        client: LlmClient,
        *,
        gated_types: Optional[Set[str]] = None,
        name: str = "a3_llm_gate",
    ) -> None:
        self._rules = rule_engine
        self._client = client
        self._gated_types = gated_types  # None => gate every candidate
        self.name = name

    def _keeps(self, unit: ClauseUnit, relation: str, target: str) -> bool:
        """Return True to keep the candidate. Default-keep on parse failure."""
        messages = [
            {"role": "system", "content": GATE_SYSTEM},
            {"role": "user", "content": gate_user(
                unit.content, relation, target, unit.parent_content, unit.grandparent_content)},
        ]
        data = self._client.complete_json(messages)
        verdict = str((data or {}).get("verdict", "")).strip().upper() if isinstance(data, dict) else ""
        return verdict != "NO"  # only an explicit NO prunes

    def predict(self, unit: ClauseUnit) -> List[Dict]:
        candidates = dedupe(self._rules.predict(unit))
        kept: List[Dict] = []
        for cand in candidates:
            in_scope = self._gated_types is None or cand["relation"] in self._gated_types
            if not in_scope or self._keeps(unit, cand["relation"], cand["reference"]):
                kept.append(cand)
        return kept
