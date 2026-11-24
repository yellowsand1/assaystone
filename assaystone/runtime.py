"""Runtime guard: the same contract at the point of action.

    guard = RuntimeGuard(
        ".assaystone/contract.json",
        baseline=".",
        irreversible={"refund.create"},
        approval_callback=ask_human,
    )
    with guard.session(task="refund duplicate charge") as session:
        session.call("read_order", {"order_id": "O-1"}, read_order)
        session.call("refund.create", {"amount_cents": 4000}, do_refund)
        result = session.finish(artifacts=changed_files)

Irreversible tools are blocked unless an approval callback returns True. The full
contract runs at ``finish``; failures raise ``ContractFailed`` and unresolved checks
raise ``EscalationRequired``. Set ``enforce=False`` for shadow mode.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .contract import Contract
from .model import ESCALATE, FAIL, Artifact, RunResult, Step, Trace
from .runner import run_contract

ALLOW = "allow"
REQUIRE_APPROVAL = "require_approval"
DENY = "deny"
_POLICIES = {ALLOW, REQUIRE_APPROVAL, DENY}


class RuntimeBlocked(RuntimeError):
    """A runtime decision stopped the action or the run."""

    def __init__(self, message: str, result: RunResult | None = None):
        super().__init__(message)
        self.result = result


class ApprovalRequired(RuntimeBlocked):
    """An irreversible action needs a human approval."""


class PolicyDenied(RuntimeBlocked):
    """The tool is denied by policy."""


class ContractFailed(RuntimeBlocked):
    """The acceptance contract failed at finish."""


class EscalationRequired(RuntimeBlocked):
    """At least one verifier could not decide; a human must review."""


def _result_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


@dataclass
class RuntimeGuard:
    contract: Contract | str | Path
    baseline: str | Path = "."
    irreversible: set[str] = field(default_factory=set)
    policies: dict[str, str] = field(default_factory=dict)
    approval_callback: Callable[[str, dict[str, Any], Trace], bool] | None = None
    enforce: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            self.contract = Contract.load(self.contract)
        self.baseline = Path(self.baseline)
        self.irreversible = set(self.irreversible)
        self.policies = dict(self.policies)
        for name, policy in self.policies.items():
            if policy not in _POLICIES:
                raise ValueError(f"unknown policy for {name}: {policy}")
        for name in self.irreversible:
            self.policies.setdefault(name, REQUIRE_APPROVAL)

    def policy_for(self, tool: str) -> str:
        return self.policies.get(tool, ALLOW)

    def session(
        self,
        *,
        task: str = "",
        agent: str = "runtime",
        trace_id: str | None = None,
    ) -> "GuardSession":
        return GuardSession(self, task=task, agent=agent, trace_id=trace_id)

    def verify(self, trace: Trace) -> RunResult:
        result = run_contract(self.contract, trace, self.baseline)
        self._enforce(result)
        return result

    def _enforce(self, result: RunResult) -> None:
        if not self.enforce:
            return
        if result.verdict == FAIL:
            raise ContractFailed(f"contract failed: {result.first_failure}", result=result)
        if result.verdict == ESCALATE:
            raise EscalationRequired(
                f"human review required: {result.first_failure}", result=result
            )


class GuardSession:
    def __init__(
        self,
        guard: RuntimeGuard,
        *,
        task: str,
        agent: str,
        trace_id: str | None,
    ):
        self.guard = guard
        self.task = task
        self.agent = agent
        self.trace_id = trace_id or f"runtime-{time.time_ns()}"
        self.steps: list[Step] = []
        self.artifacts: list[Artifact] = []
        self.evidence: dict[str, Any] = {}
        self.final_message = ""
        self._finished = False

    def __enter__(self) -> "GuardSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)

    def record_evidence(self, **kwargs: Any) -> None:
        self.evidence.update(kwargs)

    def snapshot(self) -> Trace:
        return Trace(
            id=self.trace_id,
            task=self.task,
            agent=self.agent,
            steps=list(self.steps),
            artifacts=list(self.artifacts),
            evidence=dict(self.evidence),
            final_message=self.final_message,
        )

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        fn: Callable[[], Any] | None = None,
        *,
        reversible: bool = True,
    ) -> Any:
        args = dict(args or {})
        policy = self.guard.policy_for(tool)
        if not reversible and policy == ALLOW:
            policy = REQUIRE_APPROVAL

        if policy == DENY:
            raise PolicyDenied(f"tool denied by policy: {tool}")

        if policy == REQUIRE_APPROVAL:
            callback = self.guard.approval_callback
            approved = bool(callback(tool, args, self.snapshot())) if callback else False
            # Record the request in the trace, not only in evidence. Evidence is
            # a claim; a step is a lineage that a verifier can walk.
            self.steps.append(
                Step(
                    tool="approval.request",
                    args={"tool": tool, "args": args},
                    result="approved" if approved else "denied",
                    ok=approved,
                )
            )
            self.evidence.setdefault("approvals", []).append(
                {"tool": tool, "args": args, "approved": approved}
            )
            if not approved:
                raise ApprovalRequired(f"approval required for {tool}")

        step = Step(tool=tool, args=args, result="", ok=True)
        if fn is None:
            self.steps.append(step)
            return None
        try:
            value = fn()
        except Exception as exc:
            step.result = repr(exc)
            step.ok = False
            self.steps.append(step)
            raise
        step.result = _result_text(value)
        self.steps.append(step)
        return value

    def finish(
        self,
        *,
        artifacts: list[Artifact] | None = None,
        evidence: dict[str, Any] | None = None,
        final_message: str = "",
    ) -> RunResult:
        if self._finished:
            raise RuntimeError("session already finished")
        self._finished = True
        self.final_message = final_message or self.final_message
        merged_evidence = dict(self.evidence)
        merged_evidence.update(evidence or {})
        trace = Trace(
            id=self.trace_id,
            task=self.task,
            agent=self.agent,
            steps=list(self.steps),
            artifacts=list(self.artifacts) + list(artifacts or []),
            evidence=merged_evidence,
            final_message=self.final_message,
        )
        result = run_contract(self.guard.contract, trace, self.guard.baseline)
        self.guard._enforce(result)
        return result
