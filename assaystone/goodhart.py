"""Goodhart suite: can an agent that knows the contract pass without working?

The Failure Zoo measures whether a verifier notices a defect. This suite
measures something harder: whether an agent that can read the contract can
obtain a clean pass while leaving the work undone. It is the adversarial
counterpart to recall, and it is the metric that decides whether a verifier is
safe to run unattended.

Two derived numbers matter:

* **resistance** — the share of defective cases that did not get a clean pass.
* **calibration** — of the escapes, how many the verifier set had already
  declared as blind spots. An uncovered escape is honest; an undeclared one is
  false confidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .failure_zoo import (
    CAUGHT,
    ESCALATED,
    ESCAPED,
    FALSE_ALARM,
    BenchmarkResult,
    run_benchmark,
)
from .model import FAIL
from .verifiers import REGISTRY

GOODHART_CORPUS = (
    Path(__file__).resolve().parent / "demo_data" / "goodhart" / "corpus.json"
)
GOODHART_THRESHOLDS = GOODHART_CORPUS.with_name("thresholds.json")


@dataclass
class GoodhartCase:
    family: str
    case: str
    defect: str | None
    human: str
    outcome: str
    caught_by: list[str] = field(default_factory=list)
    passed_by: list[str] = field(default_factory=list)
    declared_blind_spot: bool = False
    declared_requirement: bool = False
    note: str = ""

    @property
    def is_escape(self) -> bool:
        return self.human == FAIL and self.outcome == ESCAPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "case": self.case,
            "defect": self.defect,
            "human": self.human,
            "outcome": self.outcome,
            "caught_by": list(self.caught_by),
            "passed_by": list(self.passed_by),
            "declared_blind_spot": self.declared_blind_spot,
            "declared_requirement": self.declared_requirement,
            "note": self.note,
        }


@dataclass
class GoodhartReport:
    corpus: str
    version: str
    cases: list[GoodhartCase] = field(default_factory=list)
    threshold_failures: list[str] = field(default_factory=list)
    threshold_source: str | None = None

    @property
    def defective_cases(self) -> list[GoodhartCase]:
        return [case for case in self.cases if case.human == FAIL]

    @property
    def control_cases(self) -> list[GoodhartCase]:
        return [case for case in self.cases if case.human != FAIL]

    @property
    def caught(self) -> int:
        return sum(1 for case in self.defective_cases if case.outcome == CAUGHT)

    @property
    def escalated(self) -> int:
        return sum(1 for case in self.defective_cases if case.outcome == ESCALATED)

    @property
    def escaped(self) -> int:
        return sum(1 for case in self.defective_cases if case.is_escape)

    @property
    def false_alarms(self) -> int:
        return sum(1 for case in self.control_cases if case.outcome == FALSE_ALARM)

    @property
    def resistance(self) -> float:
        total = len(self.defective_cases)
        return (total - self.escaped) / total if total else 1.0

    @property
    def escape_rate(self) -> float:
        total = len(self.defective_cases)
        return self.escaped / total if total else 0.0

    @property
    def escapes(self) -> list[GoodhartCase]:
        return [case for case in self.defective_cases if case.is_escape]

    @property
    def declared_escapes(self) -> list[GoodhartCase]:
        return [case for case in self.escapes if case.declared_blind_spot]

    @property
    def surprise_escapes(self) -> list[GoodhartCase]:
        return [case for case in self.escapes if not case.declared_blind_spot]

    @property
    def declared_escape_rate(self) -> float:
        escapes = self.escapes
        if not escapes:
            return 1.0
        return len(self.declared_escapes) / len(escapes)

    @property
    def broken_claims(self) -> list[GoodhartCase]:
        """Escapes whose defect the contract had declared as required coverage."""
        return [case for case in self.escapes if case.declared_requirement]

    @property
    def thresholds_passed(self) -> bool:
        return not self.threshold_failures

    def summary_dict(self) -> dict[str, Any]:
        return {
            "cases": len(self.cases),
            "defective": len(self.defective_cases),
            "controls": len(self.control_cases),
            "caught": self.caught,
            "escalated": self.escalated,
            "escaped": self.escaped,
            "false_alarms": self.false_alarms,
            "resistance": round(self.resistance, 6),
            "escape_rate": round(self.escape_rate, 6),
            "declared_escapes": len(self.declared_escapes),
            "surprise_escapes": len(self.surprise_escapes),
            "declared_escape_rate": round(self.declared_escape_rate, 6),
            "broken_claims": len(self.broken_claims),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": "goodhart",
            "corpus": self.corpus,
            "corpus_version": self.version,
            "summary": self.summary_dict(),
            "cases": [case.to_dict() for case in self.cases],
            "thresholds": {
                "source": self.threshold_source,
                "status": "pass" if self.thresholds_passed else "fail",
                "failures": list(self.threshold_failures),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        summary = self.summary_dict()
        lines: list[str] = []
        add = lines.append
        add("# Goodhart suite")
        add("")
        add(
            "> Adversarial traces: an agent that knows the contract tries to obtain a "
            "clean pass without doing the work. Generated by "
            "`assaystone benchmark goodhart`."
        )
        add("")
        add(f"Corpus: `{self.corpus}` (version `{self.version}`).")
        add("")
        add(
            f"{_plural(summary['defective'], 'defective case', 'defective cases')} and "
            f"{_plural(summary['controls'], 'control case', 'control cases')}. "
            f"**Resistance: {self.resistance:.0%}** "
            f"({summary['caught']} caught, {summary['escalated']} escalated, "
            f"{summary['escaped']} escaped). False alarms on controls: "
            f"**{summary['false_alarms']}**."
        )
        add("")
        add(
            f"Of {_plural(len(self.escapes), 'escape', 'escapes')}, "
            f"**{len(self.declared_escapes)}** "
            f"{'was' if len(self.declared_escapes) == 1 else 'were'} already declared "
            f"as a blind spot and **{len(self.surprise_escapes)}** "
            f"{'was a surprise' if len(self.surprise_escapes) == 1 else 'were surprises'}. "
            f"Declared escape rate: **{self.declared_escape_rate:.0%}**."
        )
        add("")

        add("## Cases")
        add("")
        add(
            "| case | defect | outcome | caught by | passed by | declared blind spot |"
        )
        add("|---|---|---|---|---|---|")
        for case in self.cases:
            add(
                f"| `{case.case}` | {case.defect or '—'} | {case.outcome} | "
                f"{_names(case.caught_by)} | {_names(case.passed_by)} | "
                f"{'yes' if case.declared_blind_spot else 'no'} |"
            )
        add("")

        if self.broken_claims:
            add("## Broken claims")
            add("")
            add(
                "These defects were declared as required coverage and still escaped. "
                "A contract that claims a class it cannot catch is worse than a short "
                "contract that is honest about its limits."
            )
            add("")
            for case in self.broken_claims:
                add(f"- `{case.case}` (`{case.defect}`)")
            add("")

        if self.surprise_escapes:
            add("## Undeclared escapes")
            add("")
            for case in self.surprise_escapes:
                add(f"- `{case.case}` (`{case.defect}`): {case.note}")
            add("")

        add("## Regression thresholds")
        add("")
        if self.threshold_source is None:
            add("Threshold check disabled for this run.")
        elif self.thresholds_passed:
            add(f"Passed against `{self.threshold_source}`.")
        else:
            add(f"**Failed** against `{self.threshold_source}`:")
            add("")
            for failure in self.threshold_failures:
                add(f"- {failure}")
        add("")

        add("## Honest limits")
        add("")
        add(
            "- The suite measures the verifier set against a small, hand-written "
            "adversary. A different adversary can find different escapes."
        )
        add(
            "- Resistance is not a proof. It is a floor that grows as cases are added; "
            "a new attack should become a new fixture, not a new argument."
        )
        add(
            "- A control case only catches over-blocking. It does not tell you whether "
            "the contract is useful on real work."
        )
        add("")
        return "\n".join(lines)


def build_report(
    result: BenchmarkResult,
    corpus: str | None = None,
    version: str | None = None,
) -> GoodhartReport:
    report = GoodhartReport(
        corpus=corpus or result.corpus,
        version=version or result.version,
    )
    by_case: dict[tuple[str, str], list[Any]] = {}
    for verifier_result in result.results:
        key = (verifier_result.case.family, verifier_result.case.trace_id)
        by_case.setdefault(key, []).append(verifier_result)

    for family in result.families:
        if family.category != "adversarial":
            continue
        required = set(family.required_defects)
        for case in family.cases:
            results = by_case.get((family.name, case.trace_id), [])
            passed_by = sorted(
                {item.verifier for item in results if item.outcome == ESCAPED}
            )
            caught_by = sorted(
                {item.verifier for item in results if item.outcome == CAUGHT}
            )
            declared: set[str] = set()
            for name in passed_by:
                cls = REGISTRY.get(name)
                if cls is not None:
                    declared.update(cls.blind_spots)
            report.cases.append(
                GoodhartCase(
                    family=family.name,
                    case=case.trace_id,
                    defect=case.defect,
                    human=case.human,
                    outcome=family.case_outcomes.get(case.trace_id, ESCAPED),
                    caught_by=caught_by,
                    passed_by=passed_by,
                    declared_blind_spot=bool(
                        case.defect and case.defect in declared
                    ),
                    declared_requirement=bool(
                        case.defect and case.defect in required
                    ),
                    note=case.note,
                )
            )
    return report


def run_goodhart(
    corpus: str | Path | None = None,
    thresholds: str | Path | None = GOODHART_THRESHOLDS,
) -> GoodhartReport:
    corpus_path = Path(corpus) if corpus is not None else GOODHART_CORPUS
    result = run_benchmark(corpus_path, thresholds=None)
    report = build_report(result)
    if thresholds is not None:
        threshold_path = Path(thresholds)
        report.threshold_source = (
            threshold_path.name
            if threshold_path == GOODHART_THRESHOLDS
            else str(threshold_path)
        )
        report.threshold_failures = check_thresholds(report, threshold_path)
    return report


def check_thresholds(
    report: GoodhartReport,
    thresholds: str | Path | dict[str, Any],
) -> list[str]:
    if isinstance(thresholds, dict):
        data: Any = thresholds
    else:
        path = Path(thresholds)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"thresholds not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid thresholds JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"thresholds must be a JSON object: {thresholds}")

    failures: list[str] = []
    defective = data.get("defective") or {}
    if not isinstance(defective, dict):
        raise ValueError("thresholds 'defective' must be an object")
    if "min_resistance" in defective:
        minimum = float(defective["min_resistance"])
        if report.resistance + 1e-9 < minimum:
            failures.append(
                f"resistance {report.resistance:.1%} is below the threshold "
                f"{minimum:.1%}"
            )
    if "max_escape_rate" in defective:
        maximum = float(defective["max_escape_rate"])
        if report.escape_rate - 1e-9 > maximum:
            failures.append(
                f"escape rate {report.escape_rate:.1%} exceeds the threshold "
                f"{maximum:.1%}"
            )
    if "max_false_alarms" in defective:
        maximum = int(defective["max_false_alarms"])
        if report.false_alarms > maximum:
            failures.append(
                f"false alarms {report.false_alarms} exceeds the threshold {maximum}"
            )

    calibration = data.get("calibration") or {}
    if not isinstance(calibration, dict):
        raise ValueError("thresholds 'calibration' must be an object")
    if "min_declared_escape_rate" in calibration:
        minimum = float(calibration["min_declared_escape_rate"])
        if report.declared_escape_rate + 1e-9 < minimum:
            failures.append(
                f"declared escape rate {report.declared_escape_rate:.1%} is below "
                f"the threshold {minimum:.1%}"
            )
    return failures


def render_summary(report: GoodhartReport) -> str:
    summary = report.summary_dict()
    lines = [
        f"Goodhart suite: {summary['cases']} cases "
        f"({summary['defective']} defective, {summary['controls']} control)",
        f"resistance={report.resistance:.0%} "
        f"caught={summary['caught']} escalated={summary['escalated']} "
        f"escaped={summary['escaped']} false_alarms={summary['false_alarms']}",
        f"declared_escape_rate={report.declared_escape_rate:.0%} "
        f"surprises={len(report.surprise_escapes)} "
        f"broken_claims={len(report.broken_claims)}",
        "",
    ]
    lines.append(
        f"{'case':<24} {'defect':<22} {'outcome':<10} caught by"
    )
    for case in report.cases:
        lines.append(
            f"{case.case:<24} {(case.defect or '—'):<22} {case.outcome:<10} "
            f"{', '.join(case.caught_by) or '—'}"
        )
    lines.append("")
    if report.threshold_source is None:
        lines.append("thresholds: not checked")
    elif report.thresholds_passed:
        lines.append(f"thresholds: pass ({report.threshold_source})")
    else:
        lines.append(f"thresholds: FAIL ({report.threshold_source})")
        for failure in report.threshold_failures:
            lines.append(f"  - {failure}")
    return "\n".join(lines)


def _names(names: list[str]) -> str:
    if not names:
        return "—"
    return ", ".join(f"`{name}`" for name in names)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"
