"""The certificate: the artifact a decision is made of.

A verdict without evidence cannot be reviewed. Evidence without provenance
cannot be trusted. A decision without versions cannot be reproduced. The
certificate binds the three into one hash-addressed object, so that a third
party can re-check *what was decided*, *on what evidence*, and *by which
version of which check* — without re-running the agent.

The certificate is not a receipt. A receipt (``assaystone.receipt``) is a
signed statement about a gate decision. A certificate is the evidence bundle
underneath any decision; a receipt may bind its id.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from pathlib import Path
from typing import Any

from . import __version__
from .contract import Contract
from .model import ESCALATE, FAIL, RunResult, Trace
from .verifiers import REGISTRY

SCHEMA = "assaystone.certificate/1"
DEFAULT_ISSUER = "assaystone"


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def digest(value: Any) -> str:
    """A stable, printable digest of any JSON-serializable value."""
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def identity_view(body: dict[str, Any]) -> dict[str, Any]:
    """The part of a certificate that identifies the decision.

    ``issued_at`` is metadata and ``duration_ms`` is a measurement of the
    machine, not of the work. Excluding both is what makes the id stable across
    two runs of the same decision on different hardware.
    """
    material = {key: value for key, value in body.items() if key not in ("id", "issued_at")}
    checks = material.get("checks")
    if isinstance(checks, list):
        material["checks"] = [
            {key: value for key, value in check.items() if key != "duration_ms"}
            if isinstance(check, dict)
            else check
            for check in checks
        ]
    return material


def content_id(body: dict[str, Any]) -> str:
    """The id is the content address of the decision."""
    return digest(identity_view(body))


def _declaration(name: str) -> dict[str, Any]:
    cls = REGISTRY.get(name)
    if cls is None:
        return {"source": "unregistered"}
    return {
        "source": "builtin",
        "claim": getattr(cls, "claim", ""),
        "catches": list(getattr(cls, "catches", ())),
        "blind_spots": list(getattr(cls, "blind_spots", ())),
        "trusts": list(getattr(cls, "trusts", ())),
        "layer": getattr(cls, "layer", ""),
        "declared_cost_usd": getattr(cls, "cost_usd", 0.0),
        "declared_independence": getattr(cls, "independence", "high"),
    }


def _artifact_digests(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "path": artifact.path,
            "change": artifact.change,
            "content": digest(artifact.content),
        }
        for artifact in sorted(trace.artifacts, key=lambda item: item.path)
    ]


def build_certificate(
    result: RunResult,
    contract: Contract,
    trace: Trace,
    *,
    provenance: dict[str, Any] | None = None,
    issued_at: str | None = None,
    tool_version: str | None = None,
) -> dict[str, Any]:
    """Build the certificate for one contract run over one trace."""
    params_by_name = {spec.name: spec.params for spec in contract.verifiers}
    planned = [spec.name for spec in contract.verifiers]
    executed = {verdict.verifier for verdict in result.verdicts}

    checks: list[dict[str, Any]] = []
    for verdict in result.verdicts:
        checks.append(
            {
                "id": verdict.verifier,
                "outcome": verdict.outcome,
                "layer": verdict.layer,
                "evidence": list(verdict.evidence),
                "reasons": list(verdict.reasons),
                "independence": verdict.independence,
                "declared_independence": verdict.declared_independence,
                "cost_usd": round(verdict.cost_usd, 8),
                "duration_ms": round(verdict.duration_ms, 3),
                "params_digest": digest(params_by_name.get(verdict.verifier, {})),
                "declaration": _declaration(verdict.verifier),
            }
        )

    budget_hit = (result.first_failure or "").startswith("verification budget exceeded")
    not_run = []
    for name in planned:
        if name in executed:
            continue
        if budget_hit:
            reason = "verification budget exceeded"
        elif result.verdict == FAIL and contract.fail_fast:
            reason = "skipped after a decisive failure"
        else:
            reason = "not executed"
        not_run.append({"id": name, "reason": reason})

    open_obligations = [item.id for item in contract.criteria if not item.verifiers]
    unknown = [item.id for item in result.criteria if item.outcome == ESCALATE]
    criteria_total = len(result.criteria)

    declared_defects = sorted(set(contract.required_defects))
    caught_by_planned: set[str] = set()
    for name in planned:
        cls = REGISTRY.get(name)
        if cls is not None:
            caught_by_planned.update(getattr(cls, "catches", ()))
    covered_defects = sorted(set(declared_defects) & caught_by_planned)
    uncovered_defects = sorted(set(declared_defects) - caught_by_planned)

    assurance = {
        "criteria_total": criteria_total,
        "criteria_decided": criteria_total - len(unknown),
        "criteria_unknown": len(unknown),
        "assurance_gap": round(len(unknown) / criteria_total, 4) if criteria_total else 0.0,
        "unknown_criteria": unknown,
        "open_obligations": open_obligations,
        "declared_defects": declared_defects,
        "covered_defects": covered_defects,
        "uncovered_defects": uncovered_defects,
        "escalations": list(result.unconfirmed),
        "not_run": not_run,
    }

    routed_to_human = result.verdict == ESCALATE
    human_review = float(contract.human_review_cost_usd)
    cost = {
        "verification_usd": round(result.cost_usd, 8),
        "verification_budget_usd": float(contract.max_verification_cost_usd),
        "human_review_usd": human_review,
        "routed_to_human": routed_to_human,
        "decision_usd": round(result.cost_usd + (human_review if routed_to_human else 0.0), 8),
    }

    subject = {
        "kind": "agent_episode",
        "trace_id": trace.id,
        "agent": trace.agent,
        "task": trace.task,
        "source": trace.source,
        "step_count": len(trace.steps),
        "artifact_count": len(trace.artifacts),
        "trace_digest": digest(trace.to_dict()),
        "artifacts": _artifact_digests(trace),
        "provenance": dict(provenance or {"source": trace.source}),
    }

    body: dict[str, Any] = {
        "schema": SCHEMA,
        "issued_at": issued_at or _now(),
        "issuer": {"name": DEFAULT_ISSUER, "version": tool_version or __version__},
        "subject": subject,
        "contract": {
            "name": contract.name,
            "domain": contract.domain,
            "digest": digest(contract.to_dict()),
            "criteria": [item.to_dict() for item in contract.criteria],
        },
        "decision": {
            "verdict": result.verdict,
            "first_failure": result.first_failure,
            "unconfirmed": list(result.unconfirmed),
        },
        "criterion_outcomes": [item.to_dict() for item in result.criteria],
        "checks": checks,
        "assurance": assurance,
        "cost": cost,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system().lower(),
        },
    }
    body["id"] = content_id(body)
    return body


REQUIRED_KEYS = (
    "schema",
    "issued_at",
    "issuer",
    "subject",
    "contract",
    "decision",
    "checks",
    "assurance",
    "cost",
    "environment",
    "id",
)
VALID_VERDICTS = {"pass", "fail", "escalate"}


def verify_certificate(document: Any) -> dict[str, Any]:
    """Re-check a certificate without trusting the process that wrote it.

    Returns ``{"ok": bool, "id": str, "problems": [...]}``. This checks
    structure and content addressing; it cannot check that the evidence is
    true — only that the certificate has not been edited since it was issued.
    """
    problems: list[str] = []
    if not isinstance(document, dict):
        return {"ok": False, "id": "", "problems": ["certificate is not an object"]}
    for key in REQUIRED_KEYS:
        if key not in document:
            problems.append(f"missing key: {key}")
    if document.get("schema") != SCHEMA:
        problems.append(f"unsupported schema: {document.get('schema')!r}")
    decision = document.get("decision")
    if not isinstance(decision, dict) or decision.get("verdict") not in VALID_VERDICTS:
        problems.append("decision.verdict is not pass|fail|escalate")
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append("checks must be a non-empty list")
    else:
        for index, check in enumerate(checks):
            if not isinstance(check, dict) or "id" not in check or "outcome" not in check:
                problems.append(f"checks[{index}] is missing id or outcome")
                continue
            if check["outcome"] not in VALID_VERDICTS:
                problems.append(f"checks[{index}].outcome is not a verdict")
    if not problems:
        expected = content_id(document)
        if document.get("id") != expected:
            problems.append(f"content id mismatch: expected {expected}")
    return {"ok": not problems, "id": str(document.get("id", "")), "problems": problems}


def to_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return name or "trace"
