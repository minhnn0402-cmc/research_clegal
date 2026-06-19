"""Extrapolate per-architecture cost to production scale (600k documents).

The decisive cost asymmetry:
  * A1 (LLM extractor) issues one call per *clause* — dense, scales with the
    whole corpus.
  * A3 (gate) issues one call per *rule candidate* — sparse, scales with the
    number of relations the rules already found (a small fraction of clauses).

Token volume and wall-clock are reported (provider-agnostic). Monetary cost is
left as ``tokens × your_unit_price`` since the internal model's price is not
public.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

PRODUCTION_DOCS = 600_000


@dataclass
class CostProfile:
    name: str
    calls: int
    n_clauses: int
    total_tokens: int
    latency_s_total: float
    latency_s_mean: float

    @property
    def calls_per_clause(self) -> float:
        return self.calls / self.n_clauses if self.n_clauses else 0.0

    @property
    def tokens_per_call(self) -> float:
        return self.total_tokens / self.calls if self.calls else 0.0


def profile_from_bundle(bundle: Dict) -> Optional[CostProfile]:
    tel = bundle.get("telemetry") or {}
    if not tel.get("calls"):
        return None
    return CostProfile(
        name=bundle["architecture"],
        calls=tel["calls"],
        n_clauses=bundle["n_clauses"],
        total_tokens=tel.get("total_tokens", 0),
        latency_s_total=tel.get("latency_s_total", 0.0),
        latency_s_mean=tel.get("latency_s_mean", 0.0),
    )


def extrapolate(
    profile: CostProfile,
    *,
    docs: int = PRODUCTION_DOCS,
    clauses_per_doc: float = 30.0,
    workers: int = 32,
) -> Dict:
    """Project one architecture's cost to ``docs`` documents.

    ``calls_per_clause`` is measured on the (relation-dense) eval set, so for
    A1 it is ~1 (one call per clause) and for A3 it is the candidates-per-clause
    rate. In production most clauses carry no relation, so A3's real call rate
    is *lower* than measured here — i.e. the A3 numbers below are an upper
    bound, the A1 numbers are representative.
    """
    total_clauses = docs * clauses_per_doc
    total_calls = total_clauses * profile.calls_per_clause
    total_tokens = total_calls * profile.tokens_per_call
    # Wall-clock assuming `workers` concurrent calls at the mean latency.
    wall_clock_h = (total_calls * profile.latency_s_mean) / workers / 3600.0
    return {
        "architecture": profile.name,
        "assumptions": {"docs": docs, "clauses_per_doc": clauses_per_doc, "workers": workers},
        "calls_per_clause": round(profile.calls_per_clause, 3),
        "tokens_per_call": round(profile.tokens_per_call, 1),
        "latency_s_mean": round(profile.latency_s_mean, 3),
        "total_calls_millions": round(total_calls / 1e6, 2),
        "total_tokens_billions": round(total_tokens / 1e9, 3),
        "wall_clock_hours": round(wall_clock_h, 1),
        "wall_clock_days": round(wall_clock_h / 24.0, 2),
    }
