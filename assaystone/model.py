"""Core data model for Assaystone."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

PASS = "pass"
FAIL = "fail"
ESCALATE = "escalate"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Step:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "result": self.result, "ok": self.ok}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            tool=data.get("tool", ""),
            args=dict(data.get("args") or {}),
            result=data.get("result", ""),
            ok=bool(data.get("ok", True)),
        )


@dataclass
class Artifact:
    path: str
    content: str = ""
    change: str = "modified"  # added | modified | deleted

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "content": self.content, "change": self.change}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        return cls(
            path=data["path"],
            content=data.get("content", ""),
            change=data.get("change", "modified"),
        )


@dataclass
class Label:
    verdict: str  # pass | fail
    defect: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "defect": self.defect, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Label":
        return cls(verdict=data["verdict"], defect=data.get("defect"), note=data.get("note", ""))


@dataclass
class Verdict:
    verifier: str
    layer: str
    ok: bool | None
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    # Effective independence after provenance: an agent-written testimony
    # downgrades a check to low. The declared value is kept for transparency.
    independence: str = "high"
    declared_independence: str = "high"

    @property
    def outcome(self) -> str:
        if self.ok is None:
            return ESCALATE
        return PASS if self.ok else FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "verifier": self.verifier,
            "layer": self.layer,
            "outcome": self.outcome,
            "reasons": self.reasons,
            "evidence": self.evidence,
            "cost_usd": round(self.cost_usd, 8),
            "duration_ms": round(self.duration_ms, 2),
            "independence": self.independence,
            "declared_independence": self.declared_independence,
        }


@dataclass
class CriterionVerdict:
    """What one acceptance criterion decided, independent of the check."""

    id: str
    kind: str
    defect: str
    severity: str
    outcome: str
    verifiers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    # "check" when a verifier decided it, "evidence" when a spec rule did.
    source: str = "check"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "defect": self.defect,
            "severity": self.severity,
            "outcome": self.outcome,
            "verifiers": list(self.verifiers),
            "reasons": list(self.reasons),
            "source": self.source,
            "evidence": list(self.evidence),
        }


@dataclass
class RunResult:
    trace_id: str
    contract: str
    verdict: str
    verdicts: list[Verdict] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    first_failure: str | None = None
    # Failures raised by low-independence verifiers that no independent
    # verifier confirmed. They route to a human instead of deciding.
    unconfirmed: list[str] = field(default_factory=list)
    # Per-criterion outcomes. Empty when the contract declares no criteria.
    criteria: list[CriterionVerdict] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for verdict in self.verdicts:
            out.extend(verdict.reasons)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "contract": self.contract,
            "verdict": self.verdict,
            "cost_usd": round(self.cost_usd, 8),
            "duration_ms": round(self.duration_ms, 2),
            "first_failure": self.first_failure,
            "unconfirmed": list(self.unconfirmed),
            "criteria": [c.to_dict() for c in self.criteria],
            "verdicts": [v.to_dict() for v in self.verdicts],
        }


@dataclass
class Trace:
    id: str
    task: str
    agent: str = "unknown"
    input: str = ""
    steps: list[Step] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    final_message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    labels: Label | None = None
    created_at: str = field(default_factory=utc_now)
    # Who wrote the trace: "agent" (a transcript or export) or "runtime" (a
    # guard that recorded the steps itself). Testimony from an agent trace is
    # not independent evidence.
    source: str = "agent"

    def artifact_map(self) -> dict[str, Artifact]:
        return {a.path: a for a in self.artifacts}

    def with_artifacts(self, artifacts: Iterable[Artifact]) -> "Trace":
        merged = self.artifact_map()
        for artifact in artifacts:
            merged[artifact.path] = artifact
        return replace(self, artifacts=list(merged.values()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "agent": self.agent,
            "input": self.input,
            "steps": [s.to_dict() for s in self.steps],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "final_message": self.final_message,
            "evidence": self.evidence,
            "labels": self.labels.to_dict() if self.labels else None,
            "created_at": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trace":
        return cls(
            id=data["id"],
            task=data.get("task", ""),
            agent=data.get("agent", "unknown"),
            input=data.get("input", ""),
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts", [])],
            final_message=data.get("final_message", ""),
            evidence=dict(data.get("evidence") or {}),
            labels=Label.from_dict(data["labels"]) if data.get("labels") else None,
            created_at=data.get("created_at", utc_now()),
            source=str(data.get("source") or "agent"),
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Trace":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_traces(path: str | Path) -> list[Trace]:
    target = Path(path)
    if target.is_dir():
        return [Trace.load(f) for f in sorted(target.glob("*.json"))]
    return [Trace.load(target)]
