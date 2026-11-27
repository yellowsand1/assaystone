"""Measured reliability for each check.

A certificate that says *which* check decided is not enough: a reviewer also
needs to know what that check is worth. This module carries the measurements —
recall on labelled defects, false alarms on clean cases, and adversarial recall
against an agent that knows the contract — and attaches them to the check.

The measurements are generated from the public corpora by
``scripts/build_reliability.py``; the package ships the resulting
``reliability.json`` so a decision can be built offline. The file is not a
leaderboard: it is the calibration record for the instruments used by a
certificate.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

SCHEMA = "assaystone.reliability/1"
PACKAGE_FILE = "reliability.json"


def path() -> Path:
    return Path(__file__).resolve().parent / PACKAGE_FILE


def corpus_digest(paths: list[str | Path]) -> str:
    digest = hashlib.sha256()
    for item in sorted(str(Path(p)) for p in paths):
        digest.update(Path(item).read_bytes())
    return "sha256:" + digest.hexdigest()


def load(source: str | Path | None = None) -> dict[str, Any]:
    target = Path(source) if source is not None else path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema": SCHEMA, "checks": {}, "corpus_digest": "", "measured_at": ""}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "checks": {}, "corpus_digest": "", "measured_at": ""}
    data.setdefault("checks", {})
    return data


def profile_for(name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """The reliability entry for one check, or an explicit unmeasured record."""
    source = data if data is not None else load()
    entry = (source.get("checks") or {}).get(name)
    if not entry:
        return {"status": "unmeasured"}
    return dict(entry)


def build(tool_version: str = "") -> dict[str, Any]:
    """Run the corpora and return a reliability profile.

    Imported lazily: certificates must be buildable without the benchmark
    machinery, and a benchmark must not run on every decision.
    """
    from . import __version__
    from .failure_zoo import DEFAULT_CORPUS, run_benchmark
    from .goodhart import GOODHART_CORPUS, run_goodhart
    from .verifiers import REGISTRY

    benchmark = run_benchmark(DEFAULT_CORPUS, None)
    goodhart = run_goodhart(GOODHART_CORPUS, None)

    checks: dict[str, Any] = {}
    for row in benchmark.verifiers:
        cls = REGISTRY.get(row.name)
        defective = row.caught + row.escaped + row.escalated
        clean = row.false_alarms + row.clean_passes + row.clean_escalated
        families: dict[str, Any] = {}
        for result in benchmark.results:
            if result.verifier != row.name:
                continue
            family = families.setdefault(
                result.case.family,
                {"caught": 0, "escaped": 0, "escalated": 0, "false_alarms": 0},
            )
            if result.case.human == "fail":
                if result.outcome == "caught":
                    family["caught"] += 1
                elif result.outcome == "escalated":
                    family["escalated"] += 1
                else:
                    family["escaped"] += 1
            elif result.outcome == "false_alarm":
                family["false_alarms"] += 1

        catches = set(getattr(cls, "catches", ())) if cls else set()
        declared = [
            result
            for result in benchmark.results
            if result.verifier == row.name
            and result.case.human == "fail"
            and result.case.defect in catches
        ]
        declared_caught = sum(1 for result in declared if result.outcome == "caught")
        declared_escaped = sum(1 for result in declared if result.outcome == "escaped")
        declared_escalated = sum(1 for result in declared if result.outcome == "escalated")
        declared_total = declared_caught + declared_escaped + declared_escalated

        adversarial = [
            case
            for case in goodhart.cases
            if case.human == "fail" and case.defect in catches
        ]
        adversarial_caught = sum(1 for case in adversarial if row.name in case.caught_by)

        checks[row.name] = {
            "status": "measured" if declared_total else "unmeasured",
            # On the defect classes the check claims. This is the number a
            # reviewer needs; the broad rate mixes in families it never claimed.
            "recall": (
                round(declared_caught / declared_total, 6) if declared_total else None
            ),
            "broad_recall": round(row.recall, 6),
            "false_alarm_rate": (
                round(row.false_alarm_rate, 6) if clean else None
            ),
            "declared_cases": declared_total,
            "caught": declared_caught,
            "escaped": declared_escaped,
            "escalated": declared_escalated,
            "probed_cases": defective,
            "clean_cases": clean,
            "false_alarms": row.false_alarms,
            "by_family": families,
            "adversarial_cases": len(adversarial),
            "adversarial_caught": adversarial_caught,
            "layer": row.layer,
            "claim": getattr(cls, "claim", "") if cls else "",
            "catches": sorted(catches),
            "blind_spots": list(getattr(cls, "blind_spots", ())) if cls else [],
            "cost_usd": getattr(cls, "cost_usd", 0.0) if cls else 0.0,
        }

    return {
        "schema": SCHEMA,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool_version": tool_version or __version__,
        "corpus_digest": corpus_digest([DEFAULT_CORPUS, GOODHART_CORPUS]),
        "checks": checks,
    }


def calibration(checks: list[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize how much of a decision rests on measured instruments."""
    source = data if data is not None else load()
    entries = {name: profile_for(name, source) for name in checks}
    measured = {
        name: entry for name, entry in entries.items() if entry.get("recall") is not None
    }
    unmeasured = sorted(set(entries) - set(measured))
    alarms_measured = {
        name: entry
        for name, entry in entries.items()
        if entry.get("false_alarm_rate") is not None
    }
    recalls = [
        entry["recall"] for entry in measured.values() if entry.get("recall") is not None
    ]
    alarms = [
        entry["false_alarm_rate"]
        for entry in measured.values()
        if entry.get("false_alarm_rate") is not None
    ]
    return {
        "measured_checks": len(measured),
        "unmeasured_checks": len(unmeasured),
        "calibration_gap": (
            round(len(unmeasured) / len(entries), 4) if entries else 0.0
        ),
        "unmeasured": unmeasured,
        "false_alarm_checks": len(alarms_measured),
        "min_recall": round(min(recalls), 6) if recalls else None,
        "max_false_alarm_rate": round(max(alarms), 6) if alarms else None,
        "corpus_digest": source.get("corpus_digest", ""),
        "measured_at": source.get("measured_at", ""),
    }


def render_markdown(profile: dict[str, Any]) -> str:
    """A human table; generated, never hand-edited."""
    lines = [
        "# Check reliability",
        "",
        "Generated by `scripts/build_reliability.py`. Do not edit by hand.",
        "",
        f"- measured at: `{profile['measured_at']}`",
        f"- tool version: `{profile['tool_version']}`",
        f"- corpus digest: `{profile['corpus_digest']}`",
        "",
        "Recall is measured on the defect classes a check *claims* (its",
        "`catches`), not on every case the benchmark applies it to. `n` is the",
        "number of defective cases behind the number. A small `n` means the",
        "number is a floor, not an estimate.",
        "",
        "| check | layer | recall | n | false alarms | clean n | adversarial |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(profile["checks"].items()):
        recall = "—" if entry.get("recall") is None else f"{entry['recall']:.0%}"
        alarms = (
            "—"
            if entry.get("false_alarm_rate") is None
            else f"{entry['false_alarm_rate']:.0%}"
        )
        adversarial = (
            "—"
            if not entry.get("adversarial_cases")
            else f"{entry['adversarial_caught']}/{entry['adversarial_cases']}"
        )
        lines.append(
            f"| `{name}` | {entry.get('layer', '')} | {recall} | "
            f"{entry.get('declared_cases', 0)} | {alarms} | "
            f"{entry.get('clean_cases', 0)} | {adversarial} |"
        )
    lines.extend(
        [
            "",
            "## What this is not",
            "",
            "- Not a ranking of checks. Each row is a partial oracle with a",
            "  declared blind spot; the set, not the row, is the decision.",
            "- Not a population estimate. The corpus is a floor with a known",
            "  sample size.",
            "- Not a vendor comparison. External packs can ship the same profile;",
            "  the certificate cites the digest of whichever profile it used.",
        ]
    )
    return "\n".join(lines) + "\n"
