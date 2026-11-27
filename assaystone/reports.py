"""SARIF and JUnit output for CI systems."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape as xml_escape

from .audit import AuditReport
from .model import ESCALATE, FAIL, RunResult, Trace

TOOL_NAME = "Assaystone"


def _attr(value: str) -> str:
    return xml_escape(value, {'"': "&quot;"})


def _location(trace: Trace | None, reasons: Sequence[str] | None = None) -> str:
    if trace and trace.artifacts:
        paths = [artifact.path for artifact in trace.artifacts]
        for reason in reasons or []:
            for path in paths:
                if path in reason:
                    return path
        return paths[0]
    return trace.id if trace else "assaystone"


def _sarif_document(rules: Sequence[str], results: list[dict], version: str) -> dict:
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": version,
                        "rules": [{"id": rule, "name": rule} for rule in sorted(set(rules))],
                    }
                },
                "results": results,
            }
        ],
    }


def write_sarif(
    path: str | Path,
    traces: Sequence[Trace],
    results: Sequence[RunResult],
    version: str = "0.3.0",
) -> Path:
    traces_by_id = {trace.id: trace for trace in traces}
    rules: list[str] = []
    sarif_results: list[dict] = []
    for result in results:
        if result.verdict not in (FAIL, ESCALATE):
            continue
        trace = traces_by_id.get(result.trace_id)
        for verdict in result.verdicts:
            if verdict.outcome not in (FAIL, ESCALATE):
                continue
            rules.append(verdict.verifier)
            sarif_results.append(
                {
                    "ruleId": verdict.verifier,
                    "level": "error" if verdict.outcome == FAIL else "warning",
                    "message": {
                        "text": "; ".join(verdict.reasons) or verdict.outcome,
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": _location(trace, verdict.reasons)
                                }
                            }
                        }
                    ],
                }
            )
    # A low-independence failure that no independent check confirmed is not a
    # verdict; surface it as a warning so CI and reviewers can see it.
    for result in results:
        if not result.unconfirmed:
            continue
        trace = traces_by_id.get(result.trace_id)
        rules.append("assaystone.unconfirmed")
        sarif_results.append(
            {
                "ruleId": "assaystone.unconfirmed",
                "level": "warning",
                "message": {
                    "text": "unconfirmed low-independence failure(s): "
                    + "; ".join(result.unconfirmed),
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": _location(trace)}
                        }
                    }
                ],
            }
        )

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_sarif_document(rules, sarif_results, version), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_audit_sarif(
    path: str | Path,
    report: AuditReport,
    version: str = "0.3.0",
) -> Path:
    traces_by_id = {trace.id: trace for trace in report.traces}
    rules = [finding.verifier for finding in report.findings]
    sarif_results = []
    for finding in report.findings:
        trace = traces_by_id.get(finding.trace_id)
        sarif_results.append(
            {
                "ruleId": finding.verifier,
                "level": "error" if finding.outcome == FAIL else "warning",
                "message": {"text": "; ".join(finding.reasons) or finding.outcome},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": _location(trace, finding.reasons)
                            }
                        }
                    }
                ],
            }
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_sarif_document(rules, sarif_results, version), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _junit_document(cases: list[tuple[str, str, str, str]], suite: str) -> str:
    failures = sum(1 for _, outcome, _, _ in cases if outcome == FAIL)
    errors = sum(1 for _, outcome, _, _ in cases if outcome == ESCALATE)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites><testsuite name="{_attr(suite)}" tests="{len(cases)}" '
        f'failures="{failures}" errors="{errors}">',
    ]
    for trace_id, outcome, message, details in cases:
        lines.append(f'  <testcase classname="{_attr(suite)}" name="{_attr(trace_id)}">')
        if outcome == FAIL:
            lines.append(
                f'    <failure message="{_attr(message)}">{_attr(details)}</failure>'
            )
        elif outcome == ESCALATE:
            lines.append(f'    <error message="{_attr(message)}">{_attr(details)}</error>')
        lines.append("  </testcase>")
    lines.append("</testsuite></testsuites>")
    return "\n".join(lines) + "\n"


def write_junit(path: str | Path, results: Sequence[RunResult], suite: str = "assaystone") -> Path:
    cases = []
    for result in results:
        details = "; ".join(result.reasons)
        if result.unconfirmed:
            unconfirmed = "unconfirmed: " + "; ".join(result.unconfirmed)
            details = f"{details} | {unconfirmed}" if details else unconfirmed
        cases.append(
            (
                result.trace_id,
                result.verdict,
                result.first_failure or result.verdict,
                details,
            )
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_junit_document(cases, suite), encoding="utf-8")
    return target


def write_audit_junit(
    path: str | Path,
    report: AuditReport,
    suite: str = "assaystone-audit",
) -> Path:
    by_trace: dict[str, list] = {}
    for finding in report.findings:
        by_trace.setdefault(finding.trace_id, []).append(finding)
    cases = []
    for trace in report.traces:
        findings = by_trace.get(trace.id, [])
        if not findings:
            cases.append((trace.id, "pass", "", ""))
            continue
        outcome = ESCALATE if any(f.outcome == ESCALATE for f in findings) else FAIL
        message = findings[0].reasons[0] if findings[0].reasons else findings[0].verifier
        details = "; ".join(
            f"{finding.verifier}: {finding.reasons[0] if finding.reasons else ''}"
            for finding in findings
        )
        cases.append((trace.id, outcome, message, details))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_junit_document(cases, suite), encoding="utf-8")
    return target
