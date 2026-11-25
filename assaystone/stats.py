"""Small-sample confidence intervals for proportions.

A corpus of 17 cases does not produce a precise rate. The Wilson score interval
is stable for small n and for proportions near 0 or 1, so the benchmark can say
"85% (95% CI 58-96%, n=13)" instead of implying a population estimate.
"""
from __future__ import annotations

import math


def wilson_interval(
    successes: int, total: int, z: float = 1.96
) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1 + (z * z) / total
    centre = (proportion + (z * z) / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + (z * z) / (4 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))
