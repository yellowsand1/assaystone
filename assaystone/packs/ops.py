"""Ops/refund pack: state invariants, policy limits, and approval evidence.

The pack reads ``orders.json`` and ``policy.json`` from the workspace. It is a
deliberately small example of a domain pack: deterministic verifiers, no LLM.
"""
from __future__ import annotations

import json
from typing import Any

from ..verifiers import Check, Verifier, VerifyContext, register


def _load_current(ctx: VerifyContext, path: str = "orders.json") -> dict[str, Any] | None:
    try:
        data = json.loads(ctx.current_text(path))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _load_baseline(ctx: VerifyContext, path: str = "orders.json") -> dict[str, Any] | None:
    text = ctx.baseline_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _orders(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((data or {}).get("orders", []))


def _refunds(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((data or {}).get("refunds", []))


@register
class OpsJsonValid(Verifier):
    name = "ops.json_valid"
    layer = "L0"
    cost_usd = 0.000001
    description = "orders.json and policy.json must be valid JSON."
    claim = "orders.json and policy.json parse as JSON objects."
    catches = ("invalid-json",)
    blind_spots = ("valid JSON carrying the wrong values",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        reasons: list[str] = []
        for path in ("orders.json", "policy.json"):
            try:
                json.loads(ctx.current_text(path))
            except FileNotFoundError:
                reasons.append(f"{path}: missing")
            except (json.JSONDecodeError, OSError) as exc:
                reasons.append(f"{path}: invalid JSON ({exc})")
        return (not reasons, reasons, [f"validated {2 - len(reasons)}/2 JSON file(s)"])


@register
class AmountConserved(Verifier):
    name = "ops.amount_conserved"
    layer = "L0"
    cost_usd = 0.000010
    description = "Refunded amount stays within [0, order amount]."
    claim = "Refunded amounts stay within [0, order amount]."
    catches = ("amount-mismatch",)
    blind_spots = ("a refund that is internally consistent but unauthorized",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        data = _load_current(ctx)
        if data is None:
            return None, ["orders.json missing or invalid"], []
        reasons: list[str] = []
        for order in _orders(data):
            amount = int(order.get("amount_cents", 0))
            refunded = int(order.get("refunded_cents", 0))
            if refunded < 0 or refunded > amount:
                reasons.append(f"{order.get('id')}: refunded {refunded} outside [0, {amount}]")
        return (not reasons, reasons, [f"checked {len(_orders(data))} order(s)"])


@register
class NoDoubleRefund(Verifier):
    name = "ops.no_double_refund"
    layer = "L1"
    cost_usd = 0.000020
    description = "Refund ids are unique and the ledger matches refunded_cents."
    claim = "Refund ids are unique and the ledger matches refunded_cents."
    catches = ("double-refund",)
    blind_spots = ("the same refund recorded under two different ids",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        data = _load_current(ctx)
        if data is None:
            return None, ["orders.json missing or invalid"], []
        refunds = _refunds(data)
        ids = [refund.get("id") for refund in refunds if refund.get("id")]
        duplicates = sorted({refund_id for refund_id in ids if ids.count(refund_id) > 1})
        reasons = [f"duplicate refund id: {refund_id}" for refund_id in duplicates]

        by_order: dict[str, int] = {}
        for refund in refunds:
            order_id = refund.get("order_id")
            by_order[order_id] = by_order.get(order_id, 0) + int(refund.get("amount_cents", 0))
        for order in _orders(data):
            order_id = order.get("id")
            ledger = by_order.get(order_id, 0)
            refunded = int(order.get("refunded_cents", 0))
            if ledger != refunded:
                reasons.append(f"{order_id}: ledger {ledger} != refunded_cents {refunded}")
        return (not reasons, reasons, [f"checked {len(refunds)} refund(s)"])


@register
class RefundLimit(Verifier):
    name = "ops.refund_limit"
    layer = "L1"
    cost_usd = 0.000020
    description = "New refunds must stay within the per-refund policy limit."
    claim = "Every new refund is within the per-refund policy limit."
    catches = ("over-limit",)
    blind_spots = ("a limit expressed in policy but not in amount",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        limit = int(params.get("limit_cents", 10000))
        data = _load_current(ctx)
        baseline = _load_baseline(ctx)
        if data is None:
            return None, ["orders.json missing or invalid"], []
        baseline_ids = {refund.get("id") for refund in _refunds(baseline)}
        new_refunds = [
            refund for refund in _refunds(data) if refund.get("id") not in baseline_ids
        ]
        reasons = [
            f"{refund.get('id')}: {refund.get('amount_cents')} cents exceeds limit {limit}"
            for refund in new_refunds
            if int(refund.get("amount_cents", 0)) > limit
        ]
        return (not reasons, reasons, [f"checked {len(new_refunds)} new refund(s)"])


@register
class StatusConsistent(Verifier):
    name = "ops.status_consistent"
    layer = "L1"
    cost_usd = 0.000020
    description = "Order status must match the refunded amount."
    claim = "Each order status matches its refunded amount."
    catches = ("status-inconsistent",)
    blind_spots = ("a consistent but wrong status transition",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        data = _load_current(ctx)
        if data is None:
            return None, ["orders.json missing or invalid"], []
        reasons: list[str] = []
        for order in _orders(data):
            amount = int(order.get("amount_cents", 0))
            refunded = int(order.get("refunded_cents", 0))
            status = order.get("status")
            if refunded == 0:
                expected = "captured"
            elif refunded == amount:
                expected = "refunded"
            else:
                expected = "partially_refunded"
            if status != expected:
                reasons.append(f"{order.get('id')}: status {status!r} but expected {expected!r}")
        return (not reasons, reasons, [f"checked {len(_orders(data))} order(s)"])


def _args_match(planned: dict[str, Any], actual: dict[str, Any]) -> bool:
    """An approval covers the action it names, not just the tool."""
    if not planned:
        return False
    return all(actual.get(key) == value for key, value in planned.items())


@register
class ApprovalLineage(Verifier):
    name = "ops.approval_lineage"
    layer = "L2"
    cost_usd = 0.000025
    independence = "medium"
    description = "Irreversible actions must be preceded by a matching approval request."
    claim = (
        "Every irreversible tool call is preceded by an approved approval.request "
        "for the same arguments."
    )
    catches = ("missing-approval-lineage", "wrong-approval")
    blind_spots = (
        "a forged approval.request step in an agent-written transcript",
        "an approval granted outside the trace and never recorded",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        required = set(params.get("require_approval_for", ["refund.create"]))
        pending: list[tuple[str, dict[str, Any]]] = []
        reasons: list[str] = []
        checked = 0
        for step in ctx.trace.steps:
            if step.tool == "approval.request":
                target = (step.args or {}).get("tool")
                planned = (step.args or {}).get("args") or {}
                if step.ok and target:
                    pending.append((str(target), dict(planned)))
                continue
            if step.tool in required:
                checked += 1
                match = None
                for index, (target, planned) in enumerate(pending):
                    if target == step.tool and _args_match(planned, step.args or {}):
                        match = index
                        break
                if match is None:
                    reasons.append(
                        f"{step.tool}: no preceding approval.request for these arguments"
                    )
                else:
                    pending.pop(match)
        return (
            not reasons,
            reasons,
            [f"checked {checked} irreversible call(s)"],
        )


@register
class RefundLineage(Verifier):
    name = "ops.refund_lineage"
    layer = "L1"
    cost_usd = 0.000025
    independence = "medium"
    description = "Every new refund in the ledger has a matching refund.create step."
    claim = "Each new refund in orders.json matches a recorded refund.create step."
    catches = ("double-refund", "phantom-refund")
    blind_spots = (
        "a forged refund.create step in an agent-written transcript",
        "a refund already present in the baseline ledger",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        data = _load_current(ctx)
        baseline = _load_baseline(ctx)
        if data is None:
            return None, ["orders.json missing or invalid"], []
        baseline_ids = {refund.get("id") for refund in _refunds(baseline)}
        new_refunds = [
            refund for refund in _refunds(data) if refund.get("id") not in baseline_ids
        ]
        remaining = [
            step
            for step in ctx.trace.steps
            if step.tool == "refund.create" and step.ok
        ]
        reasons: list[str] = []
        for refund in new_refunds:
            order_id = refund.get("order_id")
            amount = int(refund.get("amount_cents", 0))
            match = None
            for index, step in enumerate(remaining):
                if (
                    (step.args or {}).get("order_id") == order_id
                    and int((step.args or {}).get("amount_cents", -1)) == amount
                ):
                    match = index
                    break
            if match is None:
                reasons.append(
                    f"{refund.get('id')}: no matching refund.create step "
                    f"for {order_id} / {amount}"
                )
            else:
                # One step justifies one refund; two identical refunds need two.
                remaining.pop(match)
        return (
            not reasons,
            reasons,
            [f"checked {len(new_refunds)} new refund(s)"],
        )


@register
class ApprovalRecorded(Verifier):
    name = "ops.approval_recorded"
    layer = "L2"
    cost_usd = 0.000030
    description = "Irreversible tools must have an approved record in evidence."
    claim = "Every irreversible tool call has an approved record in evidence."
    catches = ("missing-approval",)
    blind_spots = (
        "forged approval records (the evidence channel is written by the agent)",
        "an approval granted for a different amount or target",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        required = set(params.get("require_approval_for", ["refund.create"]))
        approvals = ctx.trace.evidence.get("approvals", [])
        approved_tools = {
            approval.get("tool")
            for approval in approvals
            if isinstance(approval, dict) and approval.get("approved")
        }
        missing = [
            step.tool for step in ctx.trace.steps if step.tool in required and step.tool not in approved_tools
        ]
        reasons = [f"{tool}: no approval recorded" for tool in missing]
        return (not reasons, reasons, [f"{len(approvals)} approval record(s)"])
