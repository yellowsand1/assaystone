"""Backtest a contract against human-labeled historical traces."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .contract import Contract
from .model import ESCALATE, FAIL, PASS, Trace
from .runner import run_contract
from .stats import wilson_interval


@dataclass
class BacktestRow:
    trace_id: str
    human: str
    contract: str
    outcome: str
    first_failure: str | None
    cost_usd: float
    duration_ms: float


@dataclass
class BacktestSummary:
    contract: str
    rows: list[BacktestRow] = field(default_factory=list)

    @property
    def defects(self) -> list[BacktestRow]:
        return [row for row in self.rows if row.human == FAIL]

    @property
    def cleans(self) -> list[BacktestRow]:
        return [row for row in self.rows if row.human == PASS]

    @property
    def caught(self) -> int:
        return sum(1 for row in self.defects if row.outcome == FAIL)

    @property
    def escaped(self) -> int:
        return sum(1 for row in self.defects if row.outcome == PASS)

    @property
    def routed(self) -> int:
        return sum(1 for row in self.defects if row.outcome == ESCALATE)

    @property
    def false_alarms(self) -> int:
        return sum(1 for row in self.cleans if row.outcome == FAIL)

    @property
    def clean_routed(self) -> int:
        return sum(1 for row in self.cleans if row.outcome == ESCALATE)

    @property
    def catch_rate(self) -> float:
        return self.caught / len(self.defects) if self.defects else 0.0

    @property
    def catch_rate_ci95(self) -> tuple[float, float]:
        return wilson_interval(self.caught, len(self.defects))

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / len(self.cleans) if self.cleans else 0.0

    @property
    def false_alarm_ci95(self) -> tuple[float, float]:
        return wilson_interval(self.false_alarms, len(self.cleans))

    @property
    def total_cost(self) -> float:
        return sum(row.cost_usd for row in self.rows)

    @property
    def avg_cost(self) -> float:
        return self.total_cost / len(self.rows) if self.rows else 0.0


def backtest(contract: Contract, traces: list[Trace], baseline: str | Path) -> BacktestSummary:
    summary = BacktestSummary(contract=contract.name)
    for trace in traces:
        if trace.labels is None:
            continue
        result = run_contract(contract, trace, baseline)
        summary.rows.append(
            BacktestRow(
                trace_id=trace.id,
                human=trace.labels.verdict,
                contract=contract.name,
                outcome=result.verdict,
                first_failure=result.first_failure,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
            )
        )
    return summary
