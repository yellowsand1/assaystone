"""Compare a candidate against an incumbent over repeated measurements.

A single request is not a canary: two healthy services differ run to run. This
samples both sides, compares the central tendency, and asks whether the
difference is larger than the tolerance *and* supported by the data. With small
samples the honest tool is a bootstrap interval, not a normal approximation.

Deterministic: the resampling uses a fixed seed, so the same inputs give the
same verdict. A gate that flips on a random draw would be worse than no gate.
"""
from __future__ import annotations

import json
import random
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

# A bare number, not the digits inside an identifier like "p95".
FLOAT = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?")
SEED = 20261125


@dataclass
class Sample:
    values: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": len(self.values),
            "errors": len(self.errors),
            "median": round(statistics.median(self.values), 6)
            if self.values
            else None,
        }


@dataclass
class Comparison:
    outcome: str
    reasons: list[str] = field(default_factory=list)
    baseline: Sample = field(default_factory=Sample)
    candidate: Sample = field(default_factory=Sample)
    change: float = 0.0
    low: float = 0.0
    high: float = 0.0
    evidence: list[str] = field(default_factory=list)


def extract(result: Any, json_path: str = "") -> float:
    """Pull one number out of an oracle result, or raise."""
    output = str(getattr(result, "output", "") or "").strip()
    if json_path:
        data = json.loads(output)
        current: Any = data
        for part in json_path.split("."):
            if isinstance(current, dict):
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                raise KeyError(json_path)
        return float(current)
    match = FLOAT.search(output)
    if not match:
        raise ValueError("the output contains no number")
    return float(match.group(0))


def _bootstrap_means(values: list[float], rounds: int = 2000) -> list[float]:
    rng = random.Random(SEED)
    count = len(values)
    return [
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(rounds)
    ]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def compare_means(
    baseline: list[float], candidate: list[float], confidence: float = 0.95
) -> tuple[float, float, float]:
    """Bootstrap interval for candidate - baseline."""
    if len(baseline) < 2 or len(candidate) < 2:
        raise ValueError("two samples per side are required")
    baseline_means = _bootstrap_means(baseline)
    candidate_means = _bootstrap_means(candidate)
    differences = [
        right - left for right, left in zip(candidate_means, baseline_means, strict=False)
    ]
    tail = (1 - confidence) / 2
    return (
        statistics.fmean(candidate) - statistics.fmean(baseline),
        _percentile(differences, tail),
        _percentile(differences, 1 - tail),
    )


def run_comparison(
    sample_side: Callable[[str], tuple[float | None, str]],
    samples: int = 10,
    max_relative_increase: float = 0.10,
    confidence: float = 0.95,
    allow_errors: int = 0,
) -> Comparison:
    baseline = Sample()
    candidate = Sample()
    for index in range(samples):
        for name, side in (("baseline", baseline), ("candidate", candidate)):
            value, error = sample_side(name)
            if value is None:
                side.errors.append(f"sample {index}: {error}")
            else:
                side.values.append(value)

    result = Comparison(
        outcome="pass",
        baseline=baseline,
        candidate=candidate,
        evidence=[
            f"baseline={baseline.to_dict()['median']}",
            f"candidate={candidate.to_dict()['median']}",
            f"samples={samples}",
        ],
    )
    if len(baseline.errors) > allow_errors or len(candidate.errors) > allow_errors:
        result.outcome = "escalate"
        detail = (candidate.errors or baseline.errors or ["unknown"])[0]
        result.reasons.append(
            f"the comparison could not complete: {detail}"
        )
        return result
    if len(baseline.values) < 5 or len(candidate.values) < 5:
        result.outcome = "escalate"
        result.reasons.append(
            "fewer than five usable measurements per side; a canary cannot "
            "distinguish a regression from noise at this sample size"
        )
        return result
    if not baseline.values or statistics.fmean(baseline.values) == 0:
        result.outcome = "escalate"
        result.reasons.append("the baseline value is zero; relative change is undefined")
        return result

    change, low, high = compare_means(
        baseline.values, candidate.values, confidence
    )
    result.change, result.low, result.high = change, low, high
    relative = change / statistics.fmean(baseline.values)
    result.evidence.append(f"relative={relative:+.1%}")
    result.evidence.append(f"ci=[{low:.4f}, {high:.4f}]")
    if relative > max_relative_increase and low > 0:
        result.outcome = "fail"
        result.reasons.append(
            f"the candidate is {relative:+.1%} worse than the baseline "
            f"(limit {max_relative_increase:+.1%}) and the {confidence:.0%} "
            f"interval for the difference is [{low:.4f}, {high:.4f}], "
            "which excludes zero"
        )
        return result
    if relative > max_relative_increase:
        result.evidence.append("the interval includes zero; not a regression yet")
    return result
