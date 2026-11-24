"""Failure Zoo benchmark: per-verifier recall and false-alarm accounting.

The corpus is a JSON manifest of labelled trace families. Every verifier in a
family's pack is run against every case in that family, so the scorecard can
name which check caught which defect and which check stayed quiet.

The default corpus ships inside the package, so this runs offline and from an
installed wheel. Output carries no timestamps, durations, or absolute paths:
identical inputs produce identical bytes, which makes the scorecard suitable
for CI diffs and regression thresholds.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import AuditError, load_audit_traces
from .model import FAIL, PASS, Label, Trace, load_traces
from .verifiers import REGISTRY, VerifyContext
from .workspace import Workspace

CORPUS_FILE = "corpus.json"
DEFAULT_CORPUS = Path(__file__).resolve().parent / "demo_data" / "failure_zoo" / CORPUS_FILE
DEFAULT_THRESHOLDS = DEFAULT_CORPUS.with_name("thresholds.json")

CAUGHT = "caught"
ESCAPED = "escaped"
FALSE_ALARM = "false_alarm"
CLEAN = "clean"
ESCALATED = "escalated"


class BenchmarkError(Exception):
    """The corpus or threshold file cannot be used."""


@dataclass
class BenchmarkCase:
    family: str
    trace_id: str
    human: str
    defect: str | None
    note: str


@dataclass
class VerifierResult:
    case: BenchmarkCase
    verifier: str
    outcome: str
    reason: str = ""


@dataclass
class VerifierRow:
    name: str
    layer: str
    cases: int = 0
    caught: int = 0
    escaped: int = 0
    false_alarms: int = 0
    clean_passes: int = 0
    escalated: int = 0
    clean_escalated: int = 0

    @property
    def recall(self) -> float:
        decided = self.caught + self.escaped
        return self.caught / decided if decided else 0.0

    @property
    def false_alarm_rate(self) -> float:
        clean = self.false_alarms + self.clean_passes + self.clean_escalated
        return self.false_alarms / clean if clean else 0.0

    @property
    def precision(self) -> float:
        raised = self.caught + self.false_alarms
        return self.caught / raised if raised else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "verifier": self.name,
            "layer": self.layer,
            "cases": self.cases,
            "caught": self.caught,
            "escaped": self.escaped,
            "false_alarms": self.false_alarms,
            "clean_passes": self.clean_passes,
            "escalated": self.escalated,
            "clean_escalated": self.clean_escalated,
            "recall": round(self.recall, 6),
            "false_alarm_rate": round(self.false_alarm_rate, 6),
            "precision": round(self.precision, 6),
        }


@dataclass
class FamilySummary:
    name: str
    cases: list[BenchmarkCase] = field(default_factory=list)
    case_outcomes: dict[str, str] = field(default_factory=dict)  # trace_id -> outcome
    caught_by: dict[str, list[str]] = field(default_factory=dict)
    false_alarmed_by: dict[str, list[str]] = field(default_factory=dict)

    @property
    def defective(self) -> int:
        return sum(1 for case in self.cases if case.human == FAIL)

    @property
    def clean(self) -> int:
        return sum(1 for case in self.cases if case.human == PASS)

    def count(self, outcome: str) -> int:
        return sum(1 for value in self.case_outcomes.values() if value == outcome)

    @property
    def recall(self) -> float:
        return self.count(CAUGHT) / self.defective if self.defective else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.count(FALSE_ALARM) / self.clean if self.clean else 0.0


@dataclass
class BenchmarkResult:
    corpus: str
    version: str
    families: list[FamilySummary] = field(default_factory=list)
    verifiers: list[VerifierRow] = field(default_factory=list)
    results: list[VerifierResult] = field(default_factory=list)
    threshold_failures: list[str] = field(default_factory=list)
    threshold_source: str | None = None

    @property
    def cases(self) -> list[BenchmarkCase]:
        return [case for family in self.families for case in family.cases]

    @property
    def defective(self) -> int:
        return sum(1 for case in self.cases if case.human == FAIL)

    @property
    def clean(self) -> int:
        return sum(1 for case in self.cases if case.human == PASS)

    @property
    def caught(self) -> int:
        return sum(family.count(CAUGHT) for family in self.families)

    @property
    def escaped(self) -> int:
        return sum(family.count(ESCAPED) for family in self.families)

    @property
    def false_alarms(self) -> int:
        return sum(family.count(FALSE_ALARM) for family in self.families)

    @property
    def escalated(self) -> int:
        return sum(family.count(ESCALATED) for family in self.families)

    @property
    def recall(self) -> float:
        return self.caught / self.defective if self.defective else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / self.clean if self.clean else 0.0

    @property
    def thresholds_passed(self) -> bool:
        return not self.threshold_failures

    def summary_dict(self) -> dict[str, Any]:
        return {
            "cases": len(self.cases),
            "defective": self.defective,
            "clean": self.clean,
            "caught": self.caught,
            "escaped": self.escaped,
            "false_alarms": self.false_alarms,
            "escalated": self.escalated,
            "recall": round(self.recall, 6),
            "false_alarm_rate": round(self.false_alarm_rate, 6),
        }

    def family_dicts(self) -> list[dict[str, Any]]:
        out = []
        for family in self.families:
            rows = []
            for case in sorted(family.cases, key=lambda item: item.trace_id):
                rows.append(
                    {
                        "case": case.trace_id,
                        "human": case.human,
                        "defect": case.defect,
                        "note": case.note,
                        "outcome": family.case_outcomes.get(case.trace_id, ESCAPED),
                        "caught_by": family.caught_by.get(case.trace_id, []),
                        "false_alarmed_by": family.false_alarmed_by.get(case.trace_id, []),
                    }
                )
            out.append(
                {
                    "family": family.name,
                    "cases": len(family.cases),
                    "defective": family.defective,
                    "clean": family.clean,
                    "caught": family.count(CAUGHT),
                    "escaped": family.count(ESCAPED),
                    "false_alarms": family.count(FALSE_ALARM),
                    "escalated": family.count(ESCALATED),
                    "recall": round(family.recall, 6),
                    "false_alarm_rate": round(family.false_alarm_rate, 6),
                    "case_results": rows,
                }
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": "failure-zoo",
            "corpus": self.corpus,
            "corpus_version": self.version,
            "summary": self.summary_dict(),
            "families": self.family_dicts(),
            "verifiers": [row.to_dict() for row in self.verifiers],
            "thresholds": {
                "source": self.threshold_source,
                "status": "pass" if self.thresholds_passed else "fail",
                "failures": list(self.threshold_failures),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["family", "case", "human", "defect", "verifier", "outcome", "reason"])
        for result in self.results:
            writer.writerow(
                [
                    result.case.family,
                    result.case.trace_id,
                    result.case.human,
                    result.case.defect or "",
                    result.verifier,
                    result.outcome,
                    result.reason,
                ]
            )
        return buffer.getvalue()

    def to_markdown(self) -> str:
        summary = self.summary_dict()
        lines: list[str] = []
        add = lines.append

        add("# Failure Zoo benchmark")
        add("")
        add(
            "> Generated by `assaystone benchmark failure-zoo`. Deterministic and offline; "
            "rerun the command instead of editing this file by hand."
        )
        add("")
        add(f"Corpus: `{self.corpus}` (version `{self.version}`).")
        add("")
        add("## Corpus")
        add("")
        add(
            f"{summary['cases']} cases: **{summary['defective']} defective**, "
            f"**{summary['clean']} clean**. The full verifier packs caught "
            f"**{summary['caught']}/{summary['defective']}** defective cases with "
            f"**{summary['false_alarms']}** false alarms."
        )
        add("")
        add(
            "| family | cases | defective | clean | caught | escaped | false alarms | "
            "escalated | case recall |"
        )
        add("|---|---|---|---|---|---|---|---|---|")
        for family in self.families:
            add(
                f"| `{family.name}` | {len(family.cases)} | {family.defective} | "
                f"{family.clean} | {family.count(CAUGHT)} | {family.count(ESCAPED)} | "
                f"{family.count(FALSE_ALARM)} | {family.count(ESCALATED)} | "
                f"{_pct(family.recall)} |"
            )
        add("")

        add("## Per-verifier results")
        add("")
        add(
            "Each verifier runs independently against every case in its family. "
            "`recall` is caught / (caught + escaped); escalations are reported "
            "separately because they route to a human rather than decide."
        )
        add("")
        add(
            "| verifier | layer | cases | caught | escaped | false alarms | "
            "clean passes | escalated | recall | false-alarm rate |"
        )
        add("|---|---|---|---|---|---|---|---|---|---|")
        for row in self.verifiers:
            add(
                f"| `{row.name}` | {row.layer} | {row.cases} | {row.caught} | "
                f"{row.escaped} | {row.false_alarms} | {row.clean_passes} | "
                f"{row.escalated} | {_pct(row.recall)} | {_pct(row.false_alarm_rate)} |"
            )
        add("")

        add("## Cases")
        add("")
        add("| family | case | human | defect | caught by | false alarms from |")
        add("|---|---|---|---|---|---|")
        for family in self.families:
            for case in sorted(family.cases, key=lambda item: item.trace_id):
                caught_by = family.caught_by.get(case.trace_id, [])
                alarmed = family.false_alarmed_by.get(case.trace_id, [])
                add(
                    f"| `{family.name}` | `{case.trace_id}` | {case.human} | "
                    f"{case.defect or '—'} | {_verifiers(caught_by)} | "
                    f"{_verifiers(alarmed)} |"
                )
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
            "- This is a small, hand-labelled seed corpus, not a population estimate. "
            "A per-verifier rate here describes these fixtures only."
        )
        add(
            "- `tests.integrity` is path-based: it reports activity (a test file changed), "
            "not intent. A legitimate test edit looks the same as tampering."
        )
        add(
            "- Verifiers are scored independently of contract order and budget. A contract "
            "may stop earlier than this table suggests."
        )
        add(
            "- Cases are labelled by humans. The labels and the manifests are reviewable "
            "in the repository; disagreements are welcome as issues."
        )
        add("")
        return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _verifiers(names: list[str]) -> str:
    if not names:
        return "—"
    return ", ".join(f"`{name}`" for name in names)


def _classify(human: str, verifier_outcome: str) -> str:
    if verifier_outcome == ESCALATED:
        return ESCALATED
    if human == FAIL:
        return CAUGHT if verifier_outcome == FAIL else ESCAPED
    return FALSE_ALARM if verifier_outcome == FAIL else CLEAN


def _load_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"corpus not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid corpus JSON in {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise BenchmarkError(f"corpus must be a JSON object: {target}")
    families = data.get("families")
    if not isinstance(families, list) or not families:
        raise BenchmarkError(f"corpus has no families: {target}")
    if not all(isinstance(family, dict) for family in families):
        raise BenchmarkError(f"corpus families must be objects: {target}")
    return data, target.parent


def _verifier_specs(family: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    specs = family.get("verifiers")
    if not isinstance(specs, list) or not specs:
        raise BenchmarkError(f"family {family.get('name')!r} has no verifiers")
    out: list[tuple[str, dict[str, Any]]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise BenchmarkError(f"family {family.get('name')!r} has a non-object verifier")
        name = spec.get("name")
        if name not in REGISTRY:
            raise BenchmarkError(f"unknown verifier in family {family.get('name')!r}: {name!r}")
        out.append((name, dict(spec.get("params") or {})))
    return out


def _family_cases(family: dict[str, Any], base: Path) -> tuple[list[Trace], Path]:
    name = family.get("name")
    if not isinstance(name, str) or not name:
        raise BenchmarkError("family is missing a name")
    if not family.get("source") or not family.get("baseline"):
        raise BenchmarkError(f"family {name!r} needs a source and a baseline")
    source = (base / family["source"]).resolve()
    baseline = (base / family["baseline"]).resolve()
    kind = family.get("kind", "traces")
    if kind == "traces":
        try:
            traces = load_traces(source)
        except FileNotFoundError as exc:
            raise BenchmarkError(f"family {name!r}: trace source not found: {source}") from exc
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise BenchmarkError(f"family {name!r}: cannot load traces: {exc}") from exc
    elif kind == "transcript":
        try:
            traces = load_audit_traces(
                source,
                format=family.get("format", "auto"),
                baseline=baseline,
            )
        except (AuditError, OSError, json.JSONDecodeError) as exc:
            raise BenchmarkError(f"family {name!r}: {exc}") from exc
    else:
        raise BenchmarkError(f"family {name!r}: unknown kind {kind!r}")
    if not traces:
        raise BenchmarkError(f"family {name!r}: no cases found in {source}")

    override = family.get("label")
    if override is not None and not isinstance(override, dict):
        raise BenchmarkError(f"family {name!r}: label must be an object")
    for trace in traces:
        if trace.labels is None and override:
            trace.labels = Label.from_dict(override)
        if trace.labels is None:
            raise BenchmarkError(f"case {trace.id!r} in family {name!r} has no label")
        if trace.labels.verdict not in (PASS, FAIL):
            raise BenchmarkError(
                f"case {trace.id!r} in family {name!r} has verdict "
                f"{trace.labels.verdict!r}; expected {PASS!r} or {FAIL!r}"
            )
    return traces, baseline


def _run_case(
    case: BenchmarkCase,
    trace: Trace,
    baseline: Path,
    specs: list[tuple[str, dict[str, Any]]],
    test_command: list[str],
) -> list[VerifierResult]:
    ordered = sorted(specs, key=lambda item: (REGISTRY[item[0]].cost_usd, item[0]))
    results: list[VerifierResult] = []
    with Workspace(baseline) as workspace:
        workspace.apply(trace.artifacts)
        ctx = VerifyContext(
            trace=trace,
            workspace=workspace,
            baseline=baseline,
            test_command=test_command,
        )
        for name, params in ordered:
            verifier = REGISTRY[name]()
            try:
                ok, reasons, _evidence = verifier.check(ctx, params)
            except Exception as exc:  # noqa: BLE001 - a crashing verifier fails closed
                ok, reasons = None, [f"verifier crashed: {exc!r}"]
            verifier_outcome = ESCALATED if ok is None else (PASS if ok else FAIL)
            results.append(
                VerifierResult(
                    case=case,
                    verifier=name,
                    outcome=_classify(case.human, verifier_outcome),
                    reason=reasons[0] if reasons else "",
                )
            )
    return results


def run_benchmark(
    corpus: str | Path = DEFAULT_CORPUS,
    thresholds: str | Path | None = DEFAULT_THRESHOLDS,
) -> BenchmarkResult:
    manifest, base = _load_manifest(corpus)
    result = BenchmarkResult(
        corpus=str(manifest.get("name", "failure-zoo")),
        version=str(manifest.get("version", "1")),
    )
    rows: dict[str, VerifierRow] = {}

    for family in manifest["families"]:
        traces, baseline = _family_cases(family, base)
        name = family["name"]
        specs = _verifier_specs(family)
        test_command = list(
            family.get("test_command")
            or ["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
        )
        summary = FamilySummary(name=name)
        for trace in sorted(traces, key=lambda item: item.id):
            case = BenchmarkCase(
                family=name,
                trace_id=trace.id,
                human=trace.labels.verdict,
                defect=trace.labels.defect,
                note=trace.labels.note,
            )
            summary.cases.append(case)
            case_results = _run_case(case, trace, baseline, specs, test_command)
            result.results.extend(case_results)
            for verifier_result in case_results:
                row = rows.get(verifier_result.verifier)
                if row is None:
                    row = VerifierRow(
                        name=verifier_result.verifier,
                        layer=REGISTRY[verifier_result.verifier].layer,
                    )
                    rows[verifier_result.verifier] = row
                row.cases += 1
                if verifier_result.outcome == CAUGHT:
                    row.caught += 1
                elif verifier_result.outcome == ESCAPED:
                    row.escaped += 1
                elif verifier_result.outcome == FALSE_ALARM:
                    row.false_alarms += 1
                elif verifier_result.outcome == CLEAN:
                    row.clean_passes += 1
                elif verifier_result.outcome == ESCALATED:
                    row.escalated += 1
                    if case.human == PASS:
                        row.clean_escalated += 1

            caught_by = sorted(
                {item.verifier for item in case_results if item.outcome == CAUGHT}
            )
            false_alarmed_by = sorted(
                {item.verifier for item in case_results if item.outcome == FALSE_ALARM}
            )
            if case.human == FAIL:
                if caught_by:
                    summary.case_outcomes[trace.id] = CAUGHT
                elif any(item.outcome == ESCAPED for item in case_results):
                    summary.case_outcomes[trace.id] = ESCAPED
                elif case_results:
                    summary.case_outcomes[trace.id] = ESCALATED
            else:
                if false_alarmed_by:
                    summary.case_outcomes[trace.id] = FALSE_ALARM
                elif any(item.outcome == ESCALATED for item in case_results):
                    summary.case_outcomes[trace.id] = ESCALATED
                else:
                    summary.case_outcomes[trace.id] = CLEAN
            summary.caught_by[trace.id] = caught_by
            summary.false_alarmed_by[trace.id] = false_alarmed_by
        result.families.append(summary)

    result.verifiers = sorted(
        rows.values(), key=lambda row: (row.layer, row.name)
    )

    if thresholds is not None:
        threshold_path = Path(thresholds)
        result.threshold_source = (
            threshold_path.name if threshold_path == DEFAULT_THRESHOLDS else str(threshold_path)
        )
        result.threshold_failures = check_thresholds(result, threshold_path)
    return result


def load_thresholds(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"thresholds not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid thresholds JSON in {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise BenchmarkError(f"thresholds must be a JSON object: {target}")
    return data


def check_thresholds(result: BenchmarkResult, thresholds: str | Path | dict[str, Any]) -> list[str]:
    data = load_thresholds(thresholds) if not isinstance(thresholds, dict) else thresholds
    failures: list[str] = []

    case_level = data.get("case_level") or {}
    if not isinstance(case_level, dict):
        raise BenchmarkError("thresholds 'case_level' must be an object")
    if "min_caught" in case_level:
        minimum = int(case_level["min_caught"])
        if result.caught < minimum:
            failures.append(
                f"case-level caught {result.caught} is below the threshold {minimum}"
            )
    if "min_recall" in case_level:
        minimum = float(case_level["min_recall"])
        if result.recall + 1e-9 < minimum:
            failures.append(
                f"case-level recall {result.recall:.1%} is below the threshold {minimum:.1%}"
            )
    if "max_false_alarms" in case_level:
        maximum = int(case_level["max_false_alarms"])
        if result.false_alarms > maximum:
            failures.append(
                f"case-level false alarms {result.false_alarms} exceeds the threshold {maximum}"
            )

    by_name = {row.name: row for row in result.verifiers}
    verifier_thresholds = data.get("verifiers") or {}
    if not isinstance(verifier_thresholds, dict):
        raise BenchmarkError("thresholds 'verifiers' must be an object")
    for name, config in sorted(verifier_thresholds.items()):
        if not isinstance(config, dict):
            raise BenchmarkError(f"{name}: threshold entry must be an object")
        row = by_name.get(name)
        if row is None:
            failures.append(f"{name}: verifier is missing from the corpus results")
            continue
        if "min_caught" in config:
            minimum = int(config["min_caught"])
            if row.caught < minimum:
                failures.append(
                    f"{name}: caught {row.caught} is below the threshold {minimum}"
                )
        if "min_recall" in config:
            minimum = float(config["min_recall"])
            if row.recall + 1e-9 < minimum:
                failures.append(
                    f"{name}: recall {row.recall:.1%} is below the threshold {minimum:.1%}"
                )
        if "max_escaped" in config:
            maximum = int(config["max_escaped"])
            if row.escaped > maximum:
                failures.append(
                    f"{name}: escaped {row.escaped} exceeds the threshold {maximum}"
                )
        if "max_false_alarms" in config:
            maximum = int(config["max_false_alarms"])
            if row.false_alarms > maximum:
                failures.append(
                    f"{name}: false alarms {row.false_alarms} exceeds the threshold {maximum}"
                )
    return failures


def render_summary(result: BenchmarkResult) -> str:
    lines: list[str] = []
    add = lines.append
    add(
        f"Failure Zoo: {len(result.cases)} cases "
        f"({result.defective} defective, {result.clean} clean)"
    )
    add(
        f"case-level: caught={result.caught}/{result.defective} "
        f"escaped={result.escaped} false_alarms={result.false_alarms} "
        f"recall={_pct(result.recall)}"
    )
    add("")
    add(f"{'verifier':<28} {'cases':>5} {'caught':>7} {'escaped':>8} {'false':>6} {'recall':>6}")
    for row in result.verifiers:
        add(
            f"{row.name:<28} {row.cases:>5} {row.caught:>7} {row.escaped:>8} "
            f"{row.false_alarms:>6} {_pct(row.recall):>6}"
        )
    add("")
    if result.threshold_source is None:
        add("thresholds: not checked")
    elif result.thresholds_passed:
        add(f"thresholds: pass ({result.threshold_source})")
    else:
        add(f"thresholds: FAIL ({result.threshold_source})")
        for failure in result.threshold_failures:
            add(f"  - {failure}")
    return "\n".join(lines)
