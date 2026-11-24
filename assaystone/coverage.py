"""Coverage analysis for acceptance contracts.

A contract is a claim: "these defect classes are covered." This module turns
that claim into a report. It separates three states that a flat checklist hides:

* covered by an independent check (can decide),
* covered only by a low-independence check (routes to a human),
* not covered at all (residual risk).

The declared defect classes are the input. Coverage that was never asked for is
reported separately, because a long list of checks is not the same as a
contract that covers what the task actually needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .contract import Contract
from .verifiers import REGISTRY, independence_rank


@dataclass
class CoverageReport:
    contract: str
    declared: list[str] = field(default_factory=list)
    covered: dict[str, list[str]] = field(default_factory=dict)
    independent: dict[str, list[str]] = field(default_factory=dict)
    low_independence_only: dict[str, list[str]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    not_declared: dict[str, list[str]] = field(default_factory=dict)
    blind_spots: dict[str, list[str]] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    max_cost_usd: float = 0.0

    @property
    def at_risk(self) -> list[str]:
        return sorted(set(self.uncovered) | set(self.low_independence_only))

    @property
    def coverage_rate(self) -> float:
        if not self.declared:
            return 1.0
        decided = len(set(self.declared) - set(self.at_risk))
        return decided / len(self.declared)

    @property
    def independent_rate(self) -> float:
        if not self.declared:
            return 1.0
        return len(set(self.declared) & set(self.independent)) / len(self.declared)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "declared": list(self.declared),
            "covered": {tag: list(names) for tag, names in sorted(self.covered.items())},
            "independent": {
                tag: list(names) for tag, names in sorted(self.independent.items())
            },
            "low_independence_only": {
                tag: list(names)
                for tag, names in sorted(self.low_independence_only.items())
            },
            "uncovered": list(self.uncovered),
            "at_risk": self.at_risk,
            "not_declared": {
                tag: list(names) for tag, names in sorted(self.not_declared.items())
            },
            "blind_spots": {
                name: list(tags) for name, tags in sorted(self.blind_spots.items())
            },
            "coverage_rate": round(self.coverage_rate, 6),
            "independent_rate": round(self.independent_rate, 6),
            "estimated_cost_usd": round(self.estimated_cost_usd, 8),
            "max_cost_usd": round(self.max_cost_usd, 8),
        }


def analyze_coverage(
    contract: Contract,
    declared: Iterable[str] | None = None,
) -> CoverageReport:
    tags = list(
        dict.fromkeys(
            declared if declared is not None else contract.required_defects
        )
    )
    declared_set = set(tags)
    covered: dict[str, list[str]] = {}
    independent: dict[str, list[str]] = {}
    low: dict[str, list[str]] = {}
    blind: dict[str, list[str]] = {}
    cost = 0.0

    for spec in contract.verifiers:
        cls = REGISTRY.get(spec.name)
        if cls is None:
            raise KeyError(f"unknown verifier in contract: {spec.name}")
        cost += cls.cost_usd
        blind[cls.name] = list(cls.blind_spots)
        for tag in cls.catches:
            covered.setdefault(tag, []).append(cls.name)
            if independence_rank(cls.independence) >= 1:
                independent.setdefault(tag, []).append(cls.name)
            else:
                low.setdefault(tag, []).append(cls.name)

    return CoverageReport(
        contract=contract.name,
        declared=tags,
        covered={tag: sorted(names) for tag, names in sorted(covered.items())},
        independent={
            tag: sorted(names) for tag, names in sorted(independent.items())
        },
        low_independence_only={
            tag: sorted(low[tag])
            for tag in tags
            if tag in low and tag not in independent
        },
        uncovered=sorted(tag for tag in tags if tag not in covered),
        not_declared={
            tag: sorted(names)
            for tag, names in sorted(covered.items())
            if tag not in declared_set
        },
        blind_spots=blind,
        estimated_cost_usd=cost,
        max_cost_usd=contract.max_verification_cost_usd,
    )


def render_coverage(report: CoverageReport) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Contract coverage: {report.contract}")
    add("")
    if not report.declared:
        add(
            "No `required_defects` were declared, so there is nothing to measure. "
            "Add the defect classes this contract must cover."
        )
        add("")
    else:
        add(
            f"Declared defects: **{len(report.declared)}**. "
            f"Decided by an independent check: **{report.independent_rate:.0%}**. "
            f"At risk (uncovered or low-independence only): **{len(report.at_risk)}**."
        )
        add("")
    add(
        f"Estimated cost per run: **${report.estimated_cost_usd:.6f}** "
        f"(budget ${report.max_cost_usd:.6f})."
    )
    add("")

    if report.declared:
        add("| defect | covered by | independent |")
        add("|---|---|---|")
        for tag in report.declared:
            names = report.covered.get(tag, [])
            independent = tag in report.independent
            add(
                f"| `{tag}` | {_names(names)} | "
                f"{'yes' if independent else 'no'} |"
            )
        add("")

    if report.at_risk:
        add("## At risk")
        add("")
        for tag in report.uncovered:
            add(f"- `{tag}`: no verifier in the contract claims to catch it.")
        for tag, names in report.low_independence_only.items():
            add(
                f"- `{tag}`: only low-independence checks claim it "
                f"({_names(names)}); a failure will escalate, not fail."
            )
        add("")

    if report.not_declared:
        add("## Covered but not declared")
        add("")
        add(
            "These tags are caught by the contract but were not part of the "
            "declared requirement. They are a bonus, not evidence of coverage."
        )
        add("")
        for tag, names in report.not_declared.items():
            add(f"- `{tag}`: {_names(names)}")
        add("")

    if report.blind_spots:
        add("## Declared blind spots")
        add("")
        for name, tags in sorted(report.blind_spots.items()):
            if tags:
                add(f"- `{name}`: {', '.join(f'`{tag}`' for tag in tags)}")
        add("")
    return "\n".join(lines)


def _names(names: list[str]) -> str:
    if not names:
        return "—"
    return ", ".join(f"`{name}`" for name in names)
