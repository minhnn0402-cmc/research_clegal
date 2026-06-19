"""A1 — LLM as primary extractor (the "just use an LLM" hypothesis).

The clause (with parent/grandparent context) is sent to the model, which
emits relations directly. Output is validated against the canonical relation
types and deduped. No rules are involved, so this isolates the LLM's own
precision/recall.
"""

from __future__ import annotations

from typing import Dict, List

from experiment.architectures.base import dedupe
from experiment.clause_dataset import ClauseUnit
from experiment.llm_client import LlmClient
from experiment.prompts import EXTRACTION_SYSTEM, allowed_relation_types, extraction_user


class LlmExtractorArchitecture:
    name = "a1_llm_extractor"

    def __init__(self, client: LlmClient) -> None:
        self._client = client
        self._allowed = set(allowed_relation_types())

    def predict(self, unit: ClauseUnit) -> List[Dict]:
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {"role": "user", "content": extraction_user(
                unit.content, unit.parent_content, unit.grandparent_content)},
        ]
        data = self._client.complete_json(messages)
        relations = (data or {}).get("relations", []) if isinstance(data, dict) else []

        out: List[Dict] = []
        for item in relations:
            if not isinstance(item, dict):
                continue
            relation = str(item.get("type", "")).strip()
            target = str(item.get("target", "")).strip()
            if relation in self._allowed and target:
                out.append({"relation": relation, "reference": target})
        return dedupe(out)
