"""Small, dependency-light statistics for decision-grade reporting.

Precision is the decision variable, so we report it with a confidence
interval rather than a point estimate, and we test paired rule-vs-LLM
differences for significance instead of eyeballing deltas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

# z for a two-sided 95% interval.
_Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float

    def as_tuple(self) -> Tuple[float, float, float]:
        return self.point, self.low, self.high


def wilson_interval(successes: int, total: int, z: float = _Z_95) -> Interval:
    """Wilson score interval for a binomial proportion.

    More honest than the normal approximation at the extremes (precision near
    1.0) and for small n, which is exactly our regime.
    """
    if total <= 0:
        return Interval(0.0, 0.0, 0.0)
    p = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)) / denom
    return Interval(round(p, 4), round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


def mcnemar_test(only_a_correct: int, only_b_correct: int) -> Tuple[float, float]:
    """McNemar's test on paired binary outcomes (same items, two systems).

    Args:
        only_a_correct: items A got right and B got wrong (b in the 2x2).
        only_b_correct: items B got right and A got wrong (c in the 2x2).

    Returns:
        (chi_square_with_continuity_correction, two_sided_p_value).
        Concordant pairs cancel out and are not needed.
    """
    b, c = only_a_correct, only_b_correct
    n = b + c
    if n == 0:
        return 0.0, 1.0
    chi2 = (abs(b - c) - 1) ** 2 / n  # Edwards continuity correction
    p = math.erfc(math.sqrt(chi2 / 2.0))  # survival fn of chi-square with df=1
    return round(chi2, 4), round(p, 6)
