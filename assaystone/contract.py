"""Acceptance contracts: ordered verifier sets, budgets, and escalation policy."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]

CRITERION_KINDS = (
    "precondition",
    "invariant",
    "postcondition",
    "forbidden_action",
    "evidence",
)
SEVERITIES = ("critical", "high", "medium", "low")
ON_UNKNOWN = ("escalate", "fail")


@dataclass
class VerifierSpec:
    name: str
    required: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Criterion:
    """One acceptance criterion, independent of how it is checked.

    The statement is for a human. The defect is the shared tag that binds it to
    verifiers, the benchmark, and coverage. A criterion with no verifier is a
    declared requirement with no check: that is the assurance gap, not a bug.
    """

    id: str
    kind: str
    statement: str
    defect: str
    verifiers: list[str] = field(default_factory=list)
    severity: str = "high"
    on_unknown: str = "escalate"
    # Deterministic evidence rules for a spec obligation. A criterion with
    # evidence is decided by the rules, not by a verifier.
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_mode: str = "all"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Criterion":
        if not isinstance(data, dict):
            raise ValueError("criterion must be an object")
        for required in ("id", "kind", "statement", "defect"):
            if required not in data:
                raise ValueError(f"criterion is missing {required}")
        cid = str(data["id"]).strip()
        kind = str(data["kind"]).strip()
        statement = str(data["statement"]).strip()
        defect = str(data["defect"]).strip()
        if not cid or not statement or not defect:
            raise ValueError("criterion id, statement, and defect must be non-empty")
        if kind not in CRITERION_KINDS:
            raise ValueError(f"criterion {cid}: unknown kind {kind!r}")
        severity = str(data.get("severity") or "high").strip()
        if severity not in SEVERITIES:
            raise ValueError(f"criterion {cid}: unknown severity {severity!r}")
        on_unknown = str(data.get("on_unknown") or "escalate").strip()
        if on_unknown not in ON_UNKNOWN:
            raise ValueError(f"criterion {cid}: unknown on_unknown {on_unknown!r}")
        verifiers = [str(name) for name in data.get("verifiers") or []]
        evidence = data.get("evidence") or []
        if not isinstance(evidence, list) or not all(
            isinstance(rule, dict) for rule in evidence
        ):
            raise ValueError(f"criterion {cid}: evidence must be a list of objects")
        evidence_mode = str(data.get("evidence_mode") or "all").strip()
        if evidence_mode not in ("all", "any"):
            raise ValueError(f"criterion {cid}: evidence_mode must be all or any")
        return cls(
            id=cid,
            kind=kind,
            statement=statement,
            defect=defect,
            verifiers=verifiers,
            severity=severity,
            on_unknown=on_unknown,
            evidence=[dict(rule) for rule in evidence],
            evidence_mode=evidence_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "statement": self.statement,
            "defect": self.defect,
            "verifiers": list(self.verifiers),
            "severity": self.severity,
            "on_unknown": self.on_unknown,
            **(
                {
                    "evidence": [dict(rule) for rule in self.evidence],
                    "evidence_mode": self.evidence_mode,
                }
                if self.evidence
                else {}
            ),
        }


@dataclass
class Contract:
    name: str
    verifiers: list[VerifierSpec]
    test_command: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_COMMAND))
    fail_fast: bool = True
    human_review_cost_usd: float = 6.0
    max_verification_cost_usd: float = 0.05
    # Defect tags this contract is expected to cover. Coverage is a claim
    # about a contract, so the requirement has to be stated, not inferred.
    required_defects: list[str] = field(default_factory=list)
    # Optional domain label ("code", "ops", ...). A benchmark only applies a
    # contract's verifiers to corpus families in the same domain.
    domain: str = ""
    # Human-readable acceptance criteria. Optional in v1, but the criteria are
    # what make a contract legible to a domain expert rather than only to an
    # engineer who knows the verifier names.
    criteria: list[Criterion] = field(default_factory=list)
    # A pass must rest on at least one measured, independent check. Without it
    # the run escalates: an unmeasured instrument may report, not decide.
    require_measured: bool = False
    # A pass must rest on a native (or restored) view of the execution. A
    # judgment about a compacted or delegated summary is not the same decision.
    require_native_view: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "Contract":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), source=str(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "contract") -> "Contract":
        specs = [
            VerifierSpec(
                name=item["name"],
                required=bool(item.get("required", True)),
                params=dict(item.get("params") or {}),
            )
            for item in data.get("verifiers", [])
        ]
        if not specs:
            raise ValueError(f"contract has no verifiers: {source}")
        raw_criteria = data.get("criteria") or []
        if not isinstance(raw_criteria, list):
            raise ValueError(f"criteria must be a list: {source}")
        criteria = [Criterion.from_dict(item) for item in raw_criteria]
        required = [str(tag) for tag in data.get("required_defects") or []]
        if not required and criteria:
            # A criterion is a requirement; the defect tag is its identity.
            required = list(dict.fromkeys(item.defect for item in criteria))
        return cls(
            name=data.get("name", "contract"),
            verifiers=specs,
            test_command=list(data.get("test_command") or DEFAULT_TEST_COMMAND),
            fail_fast=bool(data.get("fail_fast", True)),
            human_review_cost_usd=float(data.get("human_review_cost_usd", 6.0)),
            max_verification_cost_usd=float(data.get("max_verification_cost_usd", 0.05)),
            required_defects=required,
            domain=str(data.get("domain") or ""),
            criteria=criteria,
            require_measured=bool(data.get("require_measured", False)),
            require_native_view=bool(data.get("require_native_view", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "test_command": self.test_command,
            "fail_fast": self.fail_fast,
            "human_review_cost_usd": self.human_review_cost_usd,
            "max_verification_cost_usd": self.max_verification_cost_usd,
            "required_defects": list(self.required_defects),
            "domain": self.domain,
            "require_measured": self.require_measured,
            "require_native_view": self.require_native_view,
            "verifiers": [
                {
                    "name": spec.name,
                    "required": spec.required,
                    "params": spec.params,
                }
                for spec in self.verifiers
            ],
        }
        if self.criteria:
            out["criteria"] = [item.to_dict() for item in self.criteria]
        return out
