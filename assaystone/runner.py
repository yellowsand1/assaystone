"""Contract runner: cheapest sufficient verifier first; pass / fail / escalate."""
from __future__ import annotations

import time
from pathlib import Path

from .contract import Contract
from .model import (
    ESCALATE,
    FAIL,
    PASS,
    CriterionVerdict,
    RunResult,
    Trace,
    Verdict,
)
from .verifiers import REGISTRY, Verifier, VerifyContext, independence_rank
from .workspace import Workspace


def run_contract(contract: Contract, trace: Trace, baseline: str | Path) -> RunResult:
    started = time.perf_counter()
    verdicts: list[Verdict] = []
    total_cost = 0.0
    decisive_failure: str | None = None
    escalation_reason: str | None = None
    unconfirmed: list[str] = []

    for spec in contract.verifiers:
        if spec.name not in REGISTRY:
            raise KeyError(f"unknown verifier in contract: {spec.name}")

    with Workspace(baseline) as workspace:
        workspace.apply(trace.artifacts)
        ctx = VerifyContext(
            trace=trace,
            workspace=workspace,
            baseline=Path(baseline).resolve(),
            test_command=contract.test_command,
        )

        specs = sorted(contract.verifiers, key=lambda item: REGISTRY[item.name].cost_usd)
        for spec in specs:
            verifier: Verifier = REGISTRY[spec.name]()

            if total_cost + verifier.cost_usd > contract.max_verification_cost_usd:
                escalation_reason = f"verification budget exceeded before {verifier.name}"
                break

            check_started = time.perf_counter()
            try:
                ok, reasons, evidence = verifier.check(ctx, spec.params)
            except Exception as exc:  # noqa: BLE001 - a crashing verifier must fail closed
                ok, reasons, evidence = None, [f"verifier crashed: {exc!r}"], []
            duration_ms = (time.perf_counter() - check_started) * 1000

            verdicts.append(
                Verdict(
                    verifier=verifier.name,
                    layer=verifier.layer,
                    ok=ok,
                    reasons=reasons,
                    evidence=evidence,
                    cost_usd=verifier.cost_usd,
                    duration_ms=duration_ms,
                    independence=verifier.independence,
                )
            )
            total_cost += verifier.cost_usd

            if ok is None:
                if spec.required:
                    if escalation_reason is None:
                        escalation_reason = (
                            f"{verifier.name}: {reasons[0] if reasons else 'unresolved'}"
                        )
                    # Do not stop on an inconclusive check. `fail_fast` exists
                    # to skip work after a decisive failure, not to let an
                    # escalation hide one that a later check can still find.
                continue

            if ok is False and spec.required:
                reason = f"{verifier.name}: {reasons[0] if reasons else 'failed'}"
                if independence_rank(verifier.independence) >= 1:
                    if decisive_failure is None:
                        decisive_failure = reason
                    if contract.fail_fast:
                        break
                else:
                    # A low-independence check cannot decide alone. Keep going
                    # so an independent check can confirm or leave it for review.
                    unconfirmed.append(reason)

    if decisive_failure is not None:
        overall = FAIL
        first_failure = decisive_failure
    elif unconfirmed:
        overall = ESCALATE
        first_failure = f"unconfirmed low-independence failure: {unconfirmed[0]}"
    elif escalation_reason is not None:
        overall = ESCALATE
        first_failure = escalation_reason
    else:
        overall = PASS
        first_failure = None

    criterion_verdicts: list[CriterionVerdict] = []
    if contract.criteria:
        by_name = {verdict.verifier: verdict for verdict in verdicts}
        for criterion in contract.criteria:
            if criterion.verifiers:
                bound = [name for name in criterion.verifiers if name in by_name]
            else:
                bound = [
                    name
                    for name in by_name
                    if name in REGISTRY
                    and criterion.defect in REGISTRY[name].catches
                ]
            related = [by_name[name] for name in bound]
            reasons: list[str] = []
            if not related:
                outcome = ESCALATE
                reasons.append("no bound verifier ran")
            elif any(verdict.ok is False for verdict in related):
                outcome = FAIL
                reasons = [
                    reason
                    for verdict in related
                    if verdict.ok is False
                    for reason in verdict.reasons
                ]
            elif any(verdict.ok is None for verdict in related):
                outcome = ESCALATE
                reasons = [
                    reason
                    for verdict in related
                    if verdict.ok is None
                    for reason in verdict.reasons
                ]
            else:
                outcome = PASS
            if outcome == ESCALATE and criterion.on_unknown == "fail":
                outcome = FAIL
                reasons.append("on_unknown=fail")
            criterion_verdicts.append(
                CriterionVerdict(
                    id=criterion.id,
                    kind=criterion.kind,
                    defect=criterion.defect,
                    severity=criterion.severity,
                    outcome=outcome,
                    verifiers=bound,
                    reasons=reasons,
                )
            )

        # A critical or high criterion gates the run. A low/medium gap is
        # reported in the result but does not block.
        gating = [
            item
            for item in criterion_verdicts
            if item.severity in ("critical", "high")
        ]
        blocking = [item for item in gating if item.outcome == FAIL]
        unknown = [item for item in gating if item.outcome == ESCALATE]
        if blocking and overall != FAIL:
            overall = FAIL
            first_failure = (
                f"criterion {blocking[0].id}: "
                f"{blocking[0].reasons[0] if blocking[0].reasons else 'failed'}"
            )
        elif unknown and overall == PASS:
            overall = ESCALATE
            first_failure = (
                f"criterion {unknown[0].id}: "
                f"{unknown[0].reasons[0] if unknown[0].reasons else 'unresolved'}"
            )

    return RunResult(
        trace_id=trace.id,
        contract=contract.name,
        verdict=overall,
        verdicts=verdicts,
        cost_usd=total_cost,
        duration_ms=(time.perf_counter() - started) * 1000,
        first_failure=first_failure,
        unconfirmed=unconfirmed,
        criteria=criterion_verdicts,
    )
