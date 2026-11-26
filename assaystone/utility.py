"""Which checks have ever earned their keep?

Every gate writes a trail. The trail already records, per decision, which oracle
ran and what it said. Reading it answers the cost question empirically instead of
by intuition: which required checks have never observed a failure, which were
removed from the policy but still run, which were added after the evidence
stopped accumulating.

The report does not decide. A check that never fails may be doing its job or may
be vacuous; the number is the input to that judgement, not a replacement for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plane import CapabilityManifest
from .trail import TrailError
from .trail import read as read_trail
from .trail import verify as verify_trail


@dataclass
class OracleStat:
    id: str
    type: str = ""
    runs: int = 0
    fails: int = 0
    escalates: int = 0
    last_outcome: str = ""
    last_at: str = ""
    required: bool = False

    @property
    def passed(self) -> int:
        return self.runs - self.fails - self.escalates

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "runs": self.runs,
            "passed": self.passed,
            "failed": self.fails,
            "escalated": self.escalates,
            "last_outcome": self.last_outcome,
            "last_at": self.last_at,
            "required": self.required,
        }


@dataclass
class StageStat:
    stage: str
    runs: int = 0
    passes: int = 0
    fails: int = 0
    escalates: int = 0
    last_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "runs": self.runs,
            "passes": self.passes,
            "fails": self.fails,
            "escalates": self.escalates,
            "last_at": self.last_at,
        }


@dataclass
class UtilityReport:
    capability: str
    entries: int = 0
    oracles: list[OracleStat] = field(default_factory=list)
    stages: list[StageStat] = field(default_factory=list)
    never_recorded: list[str] = field(default_factory=list)
    never_failed: list[str] = field(default_factory=list)
    unrequired: list[str] = field(default_factory=list)
    declared_unused: list[str] = field(default_factory=list)
    trail_ok: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "entries": self.entries,
            "trail_ok": self.trail_ok,
            "errors": list(self.errors),
            "oracles": [item.to_dict() for item in self.oracles],
            "stages": [item.to_dict() for item in self.stages],
            "never_recorded": list(self.never_recorded),
            "never_failed": list(self.never_failed),
            "unrequired": list(self.unrequired),
            "declared_unused": list(self.declared_unused),
        }


def required_oracles(manifest: CapabilityManifest) -> dict[str, str]:
    """Every oracle a policy names, with the first stage that names it."""
    required: dict[str, str] = {}
    for stage in sorted(manifest.policies):
        policy = manifest.policies[stage]
        names = list(policy.require) + list(policy.approvals)
        if policy.rollback:
            names.append(policy.rollback)
        for name in names:
            required.setdefault(name, stage)
    return required


def build_report(
    manifest: CapabilityManifest, trail_path: str | Path | None
) -> UtilityReport:
    report = UtilityReport(capability=manifest.capability)
    if trail_path is None:
        report.errors.append("no trail supplied; there is no evidence to read")
        report.never_recorded = sorted(required_oracles(manifest))
        return report
    check = verify_trail(trail_path)
    report.trail_ok = check.ok
    if not check.ok:
        report.errors.extend(check.errors)
        return report
    try:
        entries = read_trail(trail_path)
    except TrailError as exc:
        report.trail_ok = False
        report.errors.append(str(exc))
        return report

    required = required_oracles(manifest)
    stats: dict[str, OracleStat] = {
        name: OracleStat(id=name, required=True) for name in required
    }
    by_id = {oracle.id: oracle for oracle in manifest.oracles}
    stages: dict[str, StageStat] = {}
    seen_types: dict[str, str] = {}

    for entry in entries:
        if entry.get("capability") != manifest.capability:
            continue
        report.entries += 1
        stage = str(entry.get("stage") or "")
        if stage:
            stat = stages.setdefault(stage, StageStat(stage=stage))
            stat.runs += 1
            outcome = str(entry.get("outcome") or "")
            if outcome == "pass":
                stat.passes += 1
            elif outcome == "fail":
                stat.fails += 1
            elif outcome == "escalate":
                stat.escalates += 1
            stat.last_at = str(entry.get("at") or stat.last_at)
        for item in entry.get("oracles") or []:
            oracle_id = str(item.get("id") or "")
            if not oracle_id:
                continue
            seen_types[oracle_id] = str(item.get("type") or "")
            stat = stats.setdefault(oracle_id, OracleStat(id=oracle_id))
            stat.runs += 1
            outcome = str(item.get("outcome") or "")
            if outcome == "fail":
                stat.fails += 1
            elif outcome == "escalate":
                stat.escalates += 1
            stat.last_outcome = outcome
            stat.last_at = str(entry.get("at") or stat.last_at)

    for name, stat in stats.items():
        stat.type = seen_types.get(name, "") or (
            by_id[name].type if name in by_id else ""
        )
        if stat.runs == 0:
            report.never_recorded.append(name)
        elif stat.fails == 0 and stat.escalates == 0:
            report.never_failed.append(name)
    report.oracles = [stats[name] for name in sorted(stats)]
    report.stages = [stages[name] for name in sorted(stages)]
    report.unrequired = sorted(
        name for name, stat in stats.items() if not stat.required and stat.runs
    )
    report.declared_unused = sorted(
        oracle.id for oracle in manifest.oracles if oracle.id not in required
    )
    return report


def render_report(report: UtilityReport) -> str:
    lines = [f"capability: {report.capability}"]
    if report.errors:
        for error in report.errors:
            lines.append(f"error: {error}")
        return "\n".join(lines)
    lines.append(f"decisions on this trail: {report.entries}")
    if not report.oracles:
        lines.append("no oracle has run for this capability on this trail")
        return "\n".join(lines)
    lines.extend(
        [
            "",
            f"{'oracle':<24} {'runs':>5} {'pass':>5} {'fail':>5} {'esc':>4} "
            f"{'required':>9}  last",
        ]
    )
    for stat in report.oracles:
        lines.append(
            f"{stat.id:<24} {stat.runs:>5} {stat.passed:>5} {stat.fails:>5} "
            f"{stat.escalates:>4} {('yes' if stat.required else 'no'):>9}  "
            f"{stat.last_outcome or '-'}"
        )
    if report.stages:
        lines.extend(["", "by stage"])
        for stat in report.stages:
            lines.append(
                f"  {stat.stage:<12} {stat.runs:>4} runs "
                f"({stat.passes} pass, {stat.fails} fail, {stat.escalates} escalate)"
            )
    lines.append("")
    if report.never_recorded:
        lines.append(
            "required but never recorded on this trail: "
            + ", ".join(report.never_recorded)
        )
    if report.never_failed:
        lines.append(
            "never observed a failure: " + ", ".join(report.never_failed)
        )
        lines.append(
            "  this is a fact, not a verdict: the check may be doing its job, "
            "or it may be unable to fail"
        )
    if report.unrequired:
        lines.append(
            "ran but no policy requires it now: " + ", ".join(report.unrequired)
        )
    if report.declared_unused:
        lines.append(
            "declared but no policy uses it: " + ", ".join(report.declared_unused)
        )
    return "\n".join(lines)
