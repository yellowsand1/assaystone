"""Render a Markdown scorecard for a contract comparison."""
from __future__ import annotations

from collections import Counter

from .backtest import BacktestSummary
from .mutate import MutationSummary
from .verifiers import REGISTRY


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _money(value: float) -> str:
    return f"${value:.6f}"


def render_scorecard(
    naive_bt: BacktestSummary,
    hard_bt: BacktestSummary,
    naive_mut: MutationSummary,
    hard_mut: MutationSummary,
    human_review_cost_usd: float,
    generated_at: str,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Assaystone scorecard — code/test verifier pack")
    add("")
    add(f"> Verification, not evaluation. Generated at `{generated_at}`.")
    add("")

    add("## Backtest: per trace")
    add("")
    add("| trace | human | naive | hardened | hardened first failure |")
    add("|---|---|---|---|---|")
    hard_by_id = {row.trace_id: row for row in hard_bt.rows}
    naive_by_id = {row.trace_id: row for row in naive_bt.rows}
    for trace_id, hard_row in hard_by_id.items():
        naive_row = naive_by_id.get(trace_id)
        reason = hard_row.first_failure or "—"
        if len(reason) > 90:
            reason = reason[:87] + "..."
        add(
            f"| `{trace_id}` | {hard_row.human} | "
            f"{naive_row.outcome if naive_row else '?'} | {hard_row.outcome} | {reason} |"
        )
    add("")

    add("## Backtest: aggregate")
    add("")
    add(
        "| contract | defects | caught | escaped | routed | false alarms | "
        "catch rate | false-alarm rate | avg cost / trace |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for summary in (naive_bt, hard_bt):
        add(
            f"| `{summary.contract}` | {len(summary.defects)} | {summary.caught} | "
            f"{summary.escaped} | {summary.routed} | {summary.false_alarms} | "
            f"{_pct(summary.catch_rate)} | {_pct(summary.false_alarm_rate)} | "
            f"{_money(summary.avg_cost)} |"
        )
    add("")

    ratio = hard_bt.avg_cost / human_review_cost_usd if human_review_cost_usd else 0.0
    add(
        f"Human review baseline: **${human_review_cost_usd:.2f} / trace**. "
        f"Hardened verification cost is **{ratio * 100:.3f}%** of that."
    )
    add("")

    add("## Mutation testing: can the contract see injected defects?")
    add("")
    add(
        "Target: the correct patch (`t01-correct`). Defects are injected into its artifacts, "
        "one at a time, and the contract is re-run."
    )
    add("")
    add("| operator | naive killed | hardened killed |")
    add("|---|---|---|")
    naive_ops = naive_mut.by_operator()
    hard_ops = hard_mut.by_operator()
    for operator in sorted(set(naive_ops) | set(hard_ops)):
        naive_killed, naive_total = naive_ops.get(operator, (0, 0))
        hard_killed, hard_total = hard_ops.get(operator, (0, 0))
        add(f"| `{operator}` | {naive_killed}/{naive_total} | {hard_killed}/{hard_total} |")
    add("")
    add(
        f"Overall mutation score: naive **{_pct(naive_mut.score)}**, "
        f"hardened **{_pct(hard_mut.score)}** "
        "(killed / (killed + survived), excluding invalid and escalated mutants)."
    )
    add("")

    survivors = hard_mut.survivors()
    if survivors:
        add("Hardened survivors (equivalent mutants or missing checks):")
        add("")
        for result in survivors:
            add(
                f"- `{result.mutant.operator}` at `{result.mutant.target}` — "
                f"{result.mutant.description}"
            )
    else:
        add("Hardened contract killed every valid mutant.")
    add("")

    killed_by = Counter()
    for result in hard_mut.results:
        if result.status == "killed" and result.killed_by:
            killed_by[result.killed_by.split(":", 1)[0]] += 1
    if killed_by:
        add("### Who killed the mutants?")
        add("")
        add("| verifier | mutants killed |")
        add("|---|---|")
        for verifier, count in killed_by.most_common():
            add(f"| `{verifier}` | {count} |")
        add("")

    add("## Verifier ladder (built-in pack)")
    add("")
    add("| verifier | layer | cost / check | independence |")
    add("|---|---|---|---|")
    for name in sorted(REGISTRY, key=lambda item: (REGISTRY[item].cost_usd, item)):
        verifier = REGISTRY[name]
        add(f"| `{verifier.name}` | {verifier.layer} | {_money(verifier.cost_usd)} | {verifier.independence} |")
    add("")

    add("## Declared blind spots")
    add("")
    add(
        "A verifier that cannot name what it misses is claiming to be an oracle. "
        "These are the defect classes each check knows it cannot detect."
    )
    add("")
    for name in sorted(REGISTRY, key=lambda item: (REGISTRY[item].layer, item)):
        verifier = REGISTRY[name]
        if verifier.blind_spots:
            tags = ", ".join(f"`{tag}`" for tag in verifier.blind_spots)
            add(f"- `{name}`: {tags}")
    add("")

    add("## Read this")
    add("")
    add(
        f"- The naive contract (`tests.pass` + `diff.syntax`) caught "
        f"**{naive_bt.caught}/{len(naive_bt.defects)}** labeled defects and let "
        f"**{naive_bt.escaped}** escape."
    )
    add(
        f"- The hardened contract caught **{hard_bt.caught}/{len(hard_bt.defects)}** at "
        f"**{_money(hard_bt.avg_cost)} / trace**, about **{ratio * 100:.3f}%** of the "
        "human review baseline."
    )
    add(
        "- The escaped defects are policy failures — test tampering, forbidden files, "
        "debug prints — that a passing test suite cannot see."
    )
    add(
        f"- The hardened contract is also cheaper on average here "
        f"({_money(hard_bt.avg_cost)} vs {_money(naive_bt.avg_cost)}): policy failures "
        "are killed by sub-cent checks before the expensive test suite runs."
    )
    add(
        "- Mutation testing makes verifier recall measurable. Survivors are either "
        "equivalent mutants or real gaps in the oracle; both are useful findings."
    )
    add(
        "- Backtesting turns 'add a new check' into a measurable decision: catch rate, "
        "false alarms, and cost before enforcement."
    )
    add(
        "- A low-independence failure does not decide alone. The runner seeks an "
        "independent confirmation and escalates if none arrives."
    )
    add("")
    return "\n".join(lines) + "\n"
