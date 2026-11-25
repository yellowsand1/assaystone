"""The acceptance plane: capability manifests, generic oracles, and gates.

The core knows only four oracle primitives: ``command``, ``file``, ``git``, and
``human``. A domain — Java/Maven, a refund workflow, a data pipeline — is a
manifest that binds criteria to those primitives. Nothing here knows what
``mvn`` is; it is a command payload.

This is deliberately small. It is the shape of the plane, not the whole plane.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RISKS = ("low", "medium", "high", "critical")
STAGES = ("design", "shadow", "canary", "production", "incident", "retired")
ORACLE_TYPES = ("command", "file", "git", "human")
OUTCOMES = ("pass", "fail", "escalate")


class PlaneError(ValueError):
    """The manifest cannot be used."""


@dataclass
class OracleSpec:
    id: str
    type: str
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class StagePolicy:
    require: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    allow_merge: bool = False
    allow_deploy: bool = False
    rollback_required: bool = False


@dataclass
class ManifestCriterion:
    id: str
    kind: str
    statement: str
    oracle: str
    severity: str = "high"


@dataclass
class CapabilityManifest:
    capability: str
    owner: str
    systems: list[str]
    data_classes: list[str]
    irreversible_actions: list[str]
    risk: str
    lifecycle: str
    oracles: list[OracleSpec]
    policies: dict[str, StagePolicy]
    criteria: list[ManifestCriterion] = field(default_factory=list)
    retention: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "CapabilityManifest":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PlaneError(f"manifest not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise PlaneError(f"invalid manifest JSON in {path}: {exc}") from exc
        return cls.from_dict(data, source=str(path))

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], source: str = "capability"
    ) -> "CapabilityManifest":
        if not isinstance(data, dict):
            raise PlaneError(f"manifest must be an object: {source}")
        oracles = [
            OracleSpec(
                id=str(item["id"]),
                type=str(item["type"]),
                description=str(item.get("description") or ""),
                payload=dict(item.get("payload") or {}),
            )
            for item in data.get("oracles") or []
        ]
        policies = {
            str(name): StagePolicy(
                require=[str(item) for item in (value.get("require") or [])],
                approvals=[str(item) for item in (value.get("approvals") or [])],
                allow_merge=bool(value.get("allow_merge", False)),
                allow_deploy=bool(value.get("allow_deploy", False)),
                rollback_required=bool(value.get("rollback_required", False)),
            )
            for name, value in (data.get("policies") or {}).items()
        }
        criteria = [
            ManifestCriterion(
                id=str(item["id"]),
                kind=str(item["kind"]),
                statement=str(item["statement"]),
                oracle=str(item["oracle"]),
                severity=str(item.get("severity") or "high"),
            )
            for item in data.get("criteria") or []
        ]
        manifest = cls(
            capability=str(data.get("capability") or ""),
            owner=str(data.get("owner") or ""),
            systems=[str(item) for item in data.get("systems") or []],
            data_classes=[str(item) for item in data.get("data_classes") or []],
            irreversible_actions=[
                str(item) for item in data.get("irreversible_actions") or []
            ],
            risk=str(data.get("risk") or ""),
            lifecycle=str(data.get("lifecycle") or ""),
            oracles=oracles,
            policies=policies,
            criteria=criteria,
            retention=str(data.get("retention") or ""),
        )
        errors = manifest.validate()
        if errors:
            raise PlaneError("; ".join(errors))
        return manifest

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.capability.strip():
            errors.append("capability is empty")
        if not self.owner.strip():
            errors.append("owner is empty")
        if self.risk not in RISKS:
            errors.append(f"risk {self.risk!r} is not one of {', '.join(RISKS)}")
        if self.lifecycle not in STAGES:
            errors.append(
                f"lifecycle {self.lifecycle!r} is not one of {', '.join(STAGES)}"
            )
        oracle_ids = [item.id for item in self.oracles]
        if len(set(oracle_ids)) != len(oracle_ids):
            errors.append("duplicate oracle id")
        for oracle in self.oracles:
            if not oracle.id.strip():
                errors.append("oracle id is empty")
            if oracle.type not in ORACLE_TYPES:
                errors.append(
                    f"oracle {oracle.id}: unknown type {oracle.type!r}"
                )
        criterion_ids = [item.id for item in self.criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            errors.append("duplicate criterion id")
        for criterion in self.criteria:
            if not criterion.statement.strip():
                errors.append(f"criterion {criterion.id}: empty statement")
            if criterion.oracle not in oracle_ids:
                errors.append(
                    f"criterion {criterion.id}: unknown oracle {criterion.oracle!r}"
                )
        for stage, policy in self.policies.items():
            if stage not in STAGES:
                errors.append(f"policy stage {stage!r} is unknown")
            for oracle_id in policy.require + policy.approvals:
                if oracle_id not in oracle_ids:
                    errors.append(
                        f"policy {stage}: unknown oracle {oracle_id!r}"
                    )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "owner": self.owner,
            "systems": list(self.systems),
            "data_classes": list(self.data_classes),
            "irreversible_actions": list(self.irreversible_actions),
            "risk": self.risk,
            "lifecycle": self.lifecycle,
            "retention": self.retention,
            "criteria": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "statement": item.statement,
                    "oracle": item.oracle,
                    "severity": item.severity,
                }
                for item in self.criteria
            ],
            "oracles": [
                {
                    "id": item.id,
                    "type": item.type,
                    "description": item.description,
                    "payload": item.payload,
                }
                for item in self.oracles
            ],
            "policies": {
                name: {
                    "require": list(policy.require),
                    "approvals": list(policy.approvals),
                    "allow_merge": policy.allow_merge,
                    "allow_deploy": policy.allow_deploy,
                    "rollback_required": policy.rollback_required,
                }
                for name, policy in sorted(self.policies.items())
            },
        }


@dataclass
class OracleResult:
    oracle: str
    type: str
    outcome: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracle": self.oracle,
            "type": self.type,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }


def _result(
    spec: OracleSpec,
    outcome: str,
    reasons: list[str] | None = None,
    evidence: list[str] | None = None,
) -> OracleResult:
    return OracleResult(
        oracle=spec.id,
        type=spec.type,
        outcome=outcome,
        reasons=list(reasons or []),
        evidence=list(evidence or []),
    )


def _tail(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _command(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    command = payload.get("command")
    if not command:
        return _result(spec, "escalate", ["command payload is empty"])
    if isinstance(command, str):
        command = shlex.split(command)
    cwd = root
    if payload.get("cwd"):
        cwd = (root / str(payload["cwd"])).resolve()
        if not cwd.is_relative_to(root.resolve()):
            return _result(spec, "escalate", ["cwd escapes the root"])
    timeout = float(payload.get("timeout", 600))
    expected = int(payload.get("expect_exit", 0))
    try:
        proc = subprocess.run(
            [str(part) for part in command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _result(spec, "escalate", [f"command not found: {command[0]}"])
    except subprocess.TimeoutExpired:
        return _result(spec, "escalate", ["command timed out"])
    output = _tail((proc.stdout or "") + (proc.stderr or ""))
    evidence = [f"exit={proc.returncode}", output] if output else [f"exit={proc.returncode}"]
    if proc.returncode == expected:
        return _result(spec, "pass", [], evidence)
    return _result(
        spec,
        "fail",
        [f"exit {proc.returncode} != expected {expected}"],
        evidence,
    )


def _file(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    path = payload.get("path")
    if not path:
        return _result(spec, "escalate", ["file payload has no path"])
    target = (root / str(path)).resolve()
    if not target.is_relative_to(root.resolve()):
        return _result(spec, "escalate", ["path escapes the root"])
    mode = str(payload.get("mode") or "exists")
    if mode == "exists":
        if target.exists():
            return _result(spec, "pass", [], [str(path)])
        return _result(spec, "fail", [f"missing: {path}"])
    try:
        text = target.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return _result(spec, "fail", [f"cannot read: {path}"])
    if mode == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return _result(spec, "fail", [f"invalid JSON: {exc}"])
        return _result(spec, "pass", [], [str(path)])
    if mode == "contains":
        needle = str(payload.get("needle") or "")
        if needle and needle in text:
            return _result(spec, "pass", [], [str(path)])
        return _result(spec, "fail", [f"does not contain {needle!r}"])
    if mode == "regex":
        pattern = str(payload.get("pattern") or "")
        if pattern and re.search(pattern, text):
            return _result(spec, "pass", [], [str(path)])
        return _result(spec, "fail", [f"does not match {pattern!r}"])
    return _result(spec, "escalate", [f"unknown file mode: {mode!r}"])


def _git(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    mode = str(payload.get("mode") or "clean")
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _result(spec, "escalate", ["git is not available"])
    if inside.returncode != 0:
        return _result(spec, "escalate", ["not a git repository"])
    if mode == "clean":
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if status.returncode != 0:
            return _result(spec, "escalate", ["git status failed"])
        if status.stdout.strip():
            return _result(
                spec,
                "fail",
                ["working tree is not clean"],
                [_tail(status.stdout, 400)],
            )
        return _result(spec, "pass", [], ["clean"])
    if mode == "branch":
        current = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        name = current.stdout.strip()
        expected = str(payload.get("expected") or "")
        if expected and (name == expected or name.startswith(expected)):
            return _result(spec, "pass", [], [name])
        return _result(spec, "fail", [f"branch {name!r} != {expected!r}"])
    return _result(spec, "escalate", [f"unknown git mode: {mode!r}"])


def _human(spec: OracleSpec, root: Path) -> OracleResult:
    payload = spec.payload
    action = str(payload.get("action") or "")
    record = (root / str(payload.get("record") or "approvals.json")).resolve()
    if not record.is_relative_to(root.resolve()):
        return _result(spec, "escalate", ["record path escapes the root"])
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _result(spec, "escalate", [f"no approval record: {record.name}"])
    except json.JSONDecodeError as exc:
        return _result(spec, "escalate", [f"invalid approval record: {exc}"])
    approvals = data.get("approvals") if isinstance(data, dict) else data
    if not isinstance(approvals, list):
        return _result(spec, "escalate", ["approvals must be a list"])
    for item in approvals:
        if not isinstance(item, dict) or item.get("action") != action:
            continue
        if item.get("approved"):
            return _result(
                spec,
                "pass",
                [],
                [str(item.get("approver") or "unknown approver")],
            )
        return _result(spec, "fail", [f"{action}: approval denied"])
    return _result(spec, "escalate", [f"{action}: no approval recorded"])


def run_oracle(spec: OracleSpec, root: str | Path) -> OracleResult:
    root = Path(root).resolve()
    if spec.type == "command":
        return _command(spec, root)
    if spec.type == "file":
        return _file(spec, root)
    if spec.type == "git":
        return _git(spec, root)
    if spec.type == "human":
        return _human(spec, root)
    return _result(spec, "escalate", [f"unknown oracle type: {spec.type!r}"])


@dataclass
class GateResult:
    capability: str
    stage: str
    outcome: str
    results: list[OracleResult] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    merge_allowed: bool = False
    deploy_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "stage": self.stage,
            "outcome": self.outcome,
            "results": [item.to_dict() for item in self.results],
            "missing": list(self.missing),
            "reasons": list(self.reasons),
            "merge_allowed": self.merge_allowed,
            "deploy_allowed": self.deploy_allowed,
        }


def evaluate_gate(
    manifest: CapabilityManifest,
    stage: str,
    root: str | Path,
) -> GateResult:
    if stage not in STAGES:
        raise PlaneError(f"unknown stage: {stage!r}")
    policy = manifest.policies.get(stage)
    if policy is None:
        return GateResult(
            capability=manifest.capability,
            stage=stage,
            outcome="escalate",
            reasons=[f"no policy for stage {stage!r}"],
        )
    by_id = {item.id: item for item in manifest.oracles}
    required = list(dict.fromkeys(policy.require + policy.approvals))
    results: list[OracleResult] = []
    missing: list[str] = []
    for oracle_id in required:
        spec = by_id.get(oracle_id)
        if spec is None:
            missing.append(oracle_id)
            continue
        results.append(run_oracle(spec, root))

    if any(item.outcome == "fail" for item in results):
        outcome = "fail"
    elif missing or any(item.outcome == "escalate" for item in results):
        outcome = "escalate"
    else:
        outcome = "pass"

    reasons = [f"{stage} requires: {', '.join(required) or 'nothing'}"]
    for oracle_id in missing:
        reasons.append(f"missing oracle: {oracle_id}")
    if policy.rollback_required and outcome == "pass":
        reasons.append("rollback plan required")
    return GateResult(
        capability=manifest.capability,
        stage=stage,
        outcome=outcome,
        results=results,
        missing=missing,
        reasons=reasons,
        merge_allowed=policy.allow_merge and outcome == "pass",
        deploy_allowed=policy.allow_deploy and outcome == "pass",
    )


def render_gate(result: GateResult) -> str:
    lines = [
        f"capability: {result.capability}",
        f"stage: {result.stage}",
        f"outcome: {result.outcome}",
        f"merge allowed: {'yes' if result.merge_allowed else 'no'}",
        f"deploy allowed: {'yes' if result.deploy_allowed else 'no'}",
        "",
        f"{'oracle':<20} {'type':<9} {'outcome':<10} reason",
    ]
    for item in result.results:
        reason = item.reasons[0] if item.reasons else ""
        if len(reason) > 80:
            reason = reason[:77] + "..."
        lines.append(
            f"{item.oracle:<20} {item.type:<9} {item.outcome:<10} {reason}"
        )
    for oracle_id in result.missing:
        lines.append(f"{oracle_id:<20} {'-':<9} {'missing':<10} not in manifest")
    for reason in result.reasons:
        lines.append(f"  {reason}")
    return "\n".join(lines)
