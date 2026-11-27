"""Plan a contract: choose the cheapest independent cover for declared defects.

Coverage is a requirement, not a checklist. Given the defect classes a contract
must decide and the verifiers available, this module solves the weighted set
cover: the cheapest subset that decides every declared class with at least one
independent check. It also reports what no check can decide, which classes rest
on a single check, and which alternatives were left out.

The solver is exact for small declared sets (a subset DP over defect tags) and
falls back to a deterministic greedy cover above the limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .contract import Contract
from .verifiers import REGISTRY, independence_rank

EXACT_LIMIT = 16


@dataclass(frozen=True)
class Candidate:
    name: str
    cost_usd: float
    independence: str
    catches: tuple[str, ...]
    blind_spots: tuple[str, ...]


@dataclass
class Plan:
    contract: str
    declared: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    covered: dict[str, list[str]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    fragile: list[str] = field(default_factory=list)
    alternatives: dict[str, list[str]] = field(default_factory=dict)
    cost_usd: float = 0.0
    budget_usd: float = 0.0
    pool: int = 0

    @property
    def within_budget(self) -> bool:
        return self.cost_usd <= self.budget_usd + 1e-12

    @property
    def ok(self) -> bool:
        return not self.uncovered and self.within_budget

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "declared": list(self.declared),
            "selected": list(self.selected),
            "covered": {tag: list(names) for tag, names in sorted(self.covered.items())},
            "uncovered": list(self.uncovered),
            "fragile": list(self.fragile),
            "alternatives": {
                tag: list(names) for tag, names in sorted(self.alternatives.items())
            },
            "cost_usd": round(self.cost_usd, 8),
            "budget_usd": round(self.budget_usd, 8),
            "within_budget": self.within_budget,
            "pool": self.pool,
            "ok": self.ok,
        }


def candidates_from_registry(
    names: Iterable[str] | None = None,
) -> list[Candidate]:
    selected = list(names) if names is not None else sorted(REGISTRY)
    out: list[Candidate] = []
    for name in selected:
        cls = REGISTRY.get(name)
        if cls is None:
            raise KeyError(f"unknown verifier: {name}")
        out.append(
            Candidate(
                name=cls.name,
                cost_usd=cls.cost_usd,
                independence=cls.independence,
                catches=tuple(cls.catches),
                blind_spots=tuple(cls.blind_spots),
            )
        )
    return out


def _independent(candidate: Candidate, require_independent: bool) -> bool:
    return not require_independent or independence_rank(candidate.independence) >= 1


def _exact_cover(
    tags: list[str],
    candidates: list[Candidate],
) -> tuple[float, tuple[str, ...]] | None:
    index = {tag: position for position, tag in enumerate(tags)}
    weighted: list[tuple[Candidate, int]] = []
    for candidate in candidates:
        mask = 0
        for tag in candidate.catches:
            if tag in index:
                mask |= 1 << index[tag]
        if mask:
            weighted.append((candidate, mask))
    full = (1 << len(tags)) - 1
    best: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
    for candidate, cmask in weighted:
        snapshot = list(best.items())
        for mask, (cost, names) in snapshot:
            new_mask = mask | cmask
            new_cost = cost + candidate.cost_usd
            new_names = names + (candidate.name,)
            current = best.get(new_mask)
            if current is None or (
                new_cost,
                len(new_names),
                new_names,
            ) < (current[0], len(current[1]), current[1]):
                best[new_mask] = (new_cost, new_names)
    return best.get(full)


def _greedy_cover(
    tags: list[str],
    candidates: list[Candidate],
) -> tuple[float, tuple[str, ...]] | None:
    remaining = set(tags)
    chosen: list[str] = []
    cost = 0.0
    ordered = sorted(candidates, key=lambda item: item.name)
    while remaining:
        active = set(remaining)

        def gain(candidate: Candidate, active: set[str] = active) -> int:
            return len(set(candidate.catches) & active)

        eligible = [item for item in ordered if gain(item) > 0]
        if not eligible:
            return None
        pick = min(
            eligible,
            key=lambda item: (
                item.cost_usd / gain(item),
                item.cost_usd,
                item.name,
            ),
        )
        chosen.append(pick.name)
        cost += pick.cost_usd
        remaining -= set(pick.catches) & remaining
    return cost, tuple(chosen)


def compose(
    contract: Contract | None = None,
    *,
    declared: Iterable[str] | None = None,
    budget_usd: float | None = None,
    candidates: list[Candidate] | None = None,
    contract_only: bool = False,
    require_independent: bool = True,
) -> Plan:
    tags = list(
        dict.fromkeys(
            declared
            if declared is not None
            else (contract.required_defects if contract is not None else [])
        )
    )
    if not tags:
        raise ValueError("no defect classes to plan for; declare required_defects or --require")

    if candidates is None:
        names = (
            [spec.name for spec in contract.verifiers]
            if contract_only and contract is not None
            else None
        )
        candidates = candidates_from_registry(names)

    if budget_usd is None:
        budget_usd = contract.max_verification_cost_usd if contract is not None else 0.05

    usable = [item for item in candidates if _independent(item, require_independent)]
    covered_by: dict[str, list[str]] = {}
    for candidate in usable:
        for tag in candidate.catches:
            if tag in tags:
                covered_by.setdefault(tag, []).append(candidate.name)
    uncovered = sorted(tag for tag in tags if tag not in covered_by)

    solvable = [tag for tag in tags if tag in covered_by]
    result = (
        _exact_cover(solvable, usable)
        if len(solvable) <= EXACT_LIMIT
        else _greedy_cover(solvable, usable)
    )
    if result is None:
        selected: list[str] = []
        cost = 0.0
    else:
        cost, names = result
        selected = list(names)

    by_name = {candidate.name: candidate for candidate in usable}
    covered: dict[str, list[str]] = {}
    for tag in tags:
        covered[tag] = sorted(
            name
            for name in selected
            if tag in by_name[name].catches
        )
    fragile = sorted(tag for tag in tags if len(covered.get(tag, [])) == 1)
    alternatives: dict[str, list[str]] = {}
    for tag in tags:
        options = sorted(
            candidate.name
            for candidate in usable
            if tag in candidate.catches and candidate.name not in selected
        )
        if options:
            alternatives[tag] = options

    return Plan(
        contract=contract.name if contract is not None else "plan",
        declared=tags,
        selected=selected,
        covered=covered,
        uncovered=uncovered,
        fragile=fragile,
        alternatives=alternatives,
        cost_usd=cost,
        budget_usd=budget_usd,
        pool=len(usable),
    )


def render_plan(plan: Plan) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Contract plan: {plan.contract}")
    add("")
    add(
        f"Declared defects: **{len(plan.declared)}**. "
        f"Selected verifiers: **{len(plan.selected)}** of {plan.pool} candidates. "
        f"Cost **${plan.cost_usd:.6f}** / budget ${plan.budget_usd:.6f}"
        f"{'' if plan.within_budget else ' — **over budget**'}."
    )
    add("")
    if plan.selected:
        add("Selected: " + ", ".join(f"`{name}`" for name in plan.selected))
        add("")
    add("| defect | covered by |")
    add("|---|---|")
    for tag in plan.declared:
        names = plan.covered.get(tag, [])
        add(f"| `{tag}` | {', '.join(f'`{name}`' for name in names) or '—'} |")
    add("")
    if plan.uncovered:
        add("## Uncovered")
        add("")
        add("No available independent check decides these classes:")
        add("")
        for tag in plan.uncovered:
            add(f"- `{tag}`")
        add("")
    if plan.fragile:
        add("## Fragile")
        add("")
        add(
            "These classes rest on a single check. One regression in that check "
            "is an uncovered class:"
        )
        add("")
        for tag in plan.fragile:
            add(f"- `{tag}`: {', '.join(f'`{name}`' for name in plan.covered[tag])}")
        add("")
    if plan.alternatives:
        add("## Alternatives")
        add("")
        for tag, names in plan.alternatives.items():
            add(f"- `{tag}`: {', '.join(f'`{name}`' for name in names)}")
        add("")
    return "\n".join(lines)
