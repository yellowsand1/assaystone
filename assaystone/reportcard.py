"""One report card for an acceptance contract.

A contract has four independent claims: it conforms to the protocol, it covers
the defect classes it declares, it catches known defects, and it resists an
agent that knows the rules. This module puts them on one page and returns a
single exit code, so a contract can be reviewed and gated as a whole.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .backtest import BacktestSummary, backtest
from .contract import Contract
from .coverage import CoverageReport, analyze_coverage
from .goodhart import GoodhartReport, run_goodhart
from .model import Trace
from .protocol import ContractCheck, check_contract


@dataclass
class ReportCard:
    contract: str
    protocol: ContractCheck
    coverage: CoverageReport
    resistance: GoodhartReport
    domain: str = ""
    recall: BacktestSummary | None = None

    @property
    def ok(self) -> bool:
        if not self.protocol.ok:
            return False
        if self.coverage.at_risk:
            return False
        if self.resistance.broken_claims:
            return False
        if self.resistance.threshold_failures:
            return False
        if self.recall is not None and self.recall.escaped:
            return False
        return True

    @property
    def headline(self) -> str:
        if not self.protocol.ok:
            return (
                f"contract does not conform: "
                f"{len(self.protocol.violations)} violation(s)"
            )
        parts = [
            f"coverage {self.coverage.independent_rate:.0%}",
            f"resistance {self.resistance.resistance:.0%}",
        ]
        if self.recall is not None:
            parts.append(f"recall {self.recall.catch_rate:.0%}")
        if self.coverage.at_risk:
            parts.append(f"{len(self.coverage.at_risk)} at risk")
        if self.resistance.broken_claims:
            parts.append(f"{len(self.resistance.broken_claims)} broken claim(s)")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "contract": self.contract,
            "domain": self.domain,
            "ok": self.ok,
            "headline": self.headline,
            "protocol": self.protocol.to_dict(),
            "coverage": self.coverage.to_dict(),
            "resistance": {
                **self.resistance.summary_dict(),
                "families": self.resistance.family_rows(),
                "thresholds_passed": self.resistance.thresholds_passed,
            },
        }
        if self.recall is not None:
            data["recall"] = {
                "defects": len(self.recall.defects),
                "cleans": len(self.recall.cleans),
                "caught": self.recall.caught,
                "escaped": self.recall.escaped,
                "routed": self.recall.routed,
                "false_alarms": self.recall.false_alarms,
                "catch_rate": round(self.recall.catch_rate, 6),
                "false_alarm_rate": round(self.recall.false_alarm_rate, 6),
                "avg_cost_usd": round(self.recall.avg_cost, 8),
            }
        return data

    def to_markdown(self) -> str:
        lines: list[str] = []
        add = lines.append
        add(f"# Report card: {self.contract}")
        add("")
        add(f"**{'PASS' if self.ok else 'NEEDS WORK'}** — {self.headline}")
        add("")

        add("## Protocol")
        add("")
        if self.protocol.ok:
            add("Contract and verifiers conform to the protocol.")
        else:
            add(f"**{len(self.protocol.violations)} violation(s):**")
            add("")
            for violation in self.protocol.violations:
                add(f"- {violation}")
        add("")

        add("## Coverage")
        add("")
        add("| metric | value |")
        add("|---|---|")
        add(f"| declared defect classes | {len(self.coverage.declared)} |")
        add(
            f"| decided by an independent check | "
            f"{self.coverage.independent_rate:.0%} |"
        )
        add(f"| at risk | {len(self.coverage.at_risk)} |")
        if self.coverage.at_risk:
            add("")
            for tag in self.coverage.at_risk:
                if tag in self.coverage.uncovered:
                    add(f"- `{tag}`: no verifier claims it")
                else:
                    add(f"- `{tag}`: only low-independence checks claim it")
        add("")

        if self.recall is not None:
            add("## Recall (labelled traces)")
            add("")
            add(
                "| defects | caught | escaped | routed | false alarms | "
                "catch rate | false-alarm rate | avg cost |"
            )
            add("|---|---|---|---|---|---|---|---|")
            add(
                f"| {len(self.recall.defects)} | {self.recall.caught} | "
                f"{self.recall.escaped} | {self.recall.routed} | "
                f"{self.recall.false_alarms} | {self.recall.catch_rate:.0%} | "
                f"{self.recall.false_alarm_rate:.0%} | "
                f"${self.recall.avg_cost:.6f} |"
            )
            add("")

        add("## Resistance (Goodhart suite)")
        add("")
        add(
            "| family | defective | caught | escalated | escaped | resistance |"
        )
        add("|---|---|---|---|---|---|")
        for row in self.resistance.family_rows():
            add(
                f"| `{row['family']}` | {row['defective']} | {row['caught']} | "
                f"{row['escalated']} | {row['escaped']} | {row['resistance']:.0%} |"
            )
        add("")
        add(
            f"Declared escape rate: **{self.resistance.declared_escape_rate:.0%}**. "
            f"Broken claims: **{len(self.resistance.broken_claims)}**. "
            f"Surprises: **{len(self.resistance.surprise_escapes)}**."
        )
        add("")
        if self.resistance.broken_claims:
            add("The contract claims defect classes it cannot catch:")
            add("")
            for case in self.resistance.broken_claims:
                add(f"- `{case.case}` (`{case.defect}`)")
            add("")
        return "\n".join(lines)


def run_report_card(
    contract: Contract,
    traces: Sequence[Trace] | None = None,
    baseline: str | Path = ".",
    goodhart_corpus: str | Path | None = None,
    goodhart_thresholds: str | Path | None = None,
) -> ReportCard:
    return ReportCard(
        contract=contract.name,
        domain=contract.domain,
        protocol=check_contract(contract),
        coverage=analyze_coverage(contract),
        resistance=run_goodhart(
            corpus=goodhart_corpus,
            thresholds=goodhart_thresholds,
            contract=contract,
        ),
        recall=(
            backtest(contract, list(traces), baseline) if traces is not None else None
        ),
    )
