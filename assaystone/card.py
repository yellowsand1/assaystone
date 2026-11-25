"""A one-page status card for one capability.

The gate answers one run. The card answers the operator's question: what is the
current state of acceptance, what was decided last, and what is still unresolved.
It is read-only and never turns missing evidence into a pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .approval import (
    ApprovalError,
    approval_path_for,
    load_approval,
    verify_approval,
)
from .plane import GATING_SEVERITIES, CapabilityManifest
from .receipt import ReceiptError, load_receipt, verify_receipt
from .trail import TrailError
from .trail import read as read_trail
from .trail import verify as verify_trail
from .waiver import WaiverError, load_waivers, verify_waivers, waiver_path_for


@dataclass
class StatusCard:
    capability: str
    owner: str
    risk: str
    lifecycle: str
    stage: str
    criteria: int = 0
    gated_by_some_stage: int = 0
    never_gated: list[dict[str, Any]] = field(default_factory=list)
    stage_gap: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] = field(default_factory=dict)
    trail: dict[str, Any] = field(default_factory=dict)
    receipt: dict[str, Any] = field(default_factory=dict)
    waivers: dict[str, Any] = field(default_factory=dict)
    residual_risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "owner": self.owner,
            "risk": self.risk,
            "lifecycle": self.lifecycle,
            "stage": self.stage,
            "criteria": self.criteria,
            "gated_by_some_stage": self.gated_by_some_stage,
            "never_gated": list(self.never_gated),
            "stage_gap": list(self.stage_gap),
            "stages": list(self.stages),
            "approval": dict(self.approval),
            "trail": dict(self.trail),
            "receipt": dict(self.receipt),
            "waivers": dict(self.waivers),
            "residual_risks": list(self.residual_risks),
        }


def _gated_oracles(manifest: CapabilityManifest) -> set[str]:
    gated: set[str] = set()
    for policy in manifest.policies.values():
        gated.update(policy.require)
        gated.update(policy.approvals)
        if policy.rollback:
            gated.add(policy.rollback)
    return gated


def _stage_gap(
    manifest: CapabilityManifest, stage: str
) -> list[dict[str, Any]]:
    policy = manifest.policies.get(stage)
    if policy is None:
        return []
    gated = set(policy.require) | set(policy.approvals)
    if policy.rollback:
        gated.add(policy.rollback)
    return [
        {
            "criterion": item.id,
            "severity": item.severity,
            "oracle": item.oracle,
        }
        for item in manifest.criteria
        if item.oracle not in gated
    ]


def _approval_status(
    manifest: CapabilityManifest,
    path: str | Path | None,
    owner_key: str,
) -> dict[str, Any]:
    if not manifest.manifest_approval:
        return {"required": False, "ok": True, "errors": []}
    target = path or approval_path_for(manifest)
    info: dict[str, Any] = {
        "required": True,
        "ok": False,
        "path": str(target) if target else "",
        "errors": [],
    }
    if target is None:
        info["errors"].append("no approval path is known")
        return info
    if not owner_key:
        info["errors"].append("owner key is not available")
        return info
    try:
        data = load_approval(target)
    except ApprovalError as exc:
        info["errors"].append(str(exc))
        return info
    check = verify_approval(data, owner_key, manifest)
    info.update(check.info)
    info["ok"] = check.ok
    info["errors"] = list(check.errors)
    return info


def _trail_status(
    manifest: CapabilityManifest, path: str | Path | None
) -> dict[str, Any]:
    if path is None:
        return {"present": False}
    check = verify_trail(path)
    info: dict[str, Any] = {
        "present": True,
        "path": str(path),
        "ok": check.ok,
        "entries": check.entries,
        "head": check.head,
        "errors": list(check.errors),
        "last": {},
    }
    if not check.ok:
        return info
    try:
        entries = read_trail(path)
    except TrailError as exc:
        info["ok"] = False
        info["errors"].append(str(exc))
        return info
    last: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("capability") != manifest.capability:
            continue
        stage = str(entry.get("stage") or "")
        if stage:
            last[stage] = entry
    info["last"] = {
        stage: {
            "seq": entry.get("seq"),
            "outcome": entry.get("outcome"),
            "at": entry.get("at"),
            "hash": entry.get("hash"),
        }
        for stage, entry in last.items()
    }
    return info


def _receipt_status(path: str | Path | None, key: str) -> dict[str, Any]:
    if path is None:
        return {"present": False}
    try:
        data = load_receipt(path)
    except ReceiptError as exc:
        return {
            "present": True,
            "path": str(path),
            "ok": False,
            "errors": [str(exc)],
        }
    check = verify_receipt(data, key)
    return {
        "present": True,
        "path": str(path),
        "ok": check.ok,
        "errors": list(check.errors),
        "outcome": check.receipt.get("outcome"),
        "commit": check.receipt.get("commit"),
        "trail_head": check.receipt.get("trail_head"),
        "at": check.receipt.get("at"),
    }


def _waiver_status(
    manifest: CapabilityManifest,
    path: str | Path | None,
    owner_key: str,
) -> dict[str, Any]:
    if not manifest.waivers:
        return {"enabled": False, "valid": [], "errors": []}
    target = path or waiver_path_for(manifest)
    info: dict[str, Any] = {
        "enabled": True,
        "present": bool(target and Path(target).exists()),
        "path": str(target) if target else "",
        "ok": True,
        "valid": [],
        "errors": [],
    }
    if not info["present"]:
        return info
    if not owner_key:
        info["ok"] = False
        info["errors"].append("owner key is not available")
        return info
    try:
        data = load_waivers(str(target))
    except WaiverError as exc:
        info["ok"] = False
        info["errors"].append(str(exc))
        return info
    check = verify_waivers(data, owner_key, manifest)
    info["ok"] = check.ok
    info["valid"] = list(check.valid.values())
    info["errors"] = list(check.errors)
    return info


def build_card(
    manifest: CapabilityManifest,
    stage: str | None = None,
    trail_path: str | Path | None = None,
    receipt_path: str | Path | None = None,
    approval_path: str | Path | None = None,
    waivers_path: str | Path | None = None,
    owner_key: str = "",
    receipt_key: str = "",
) -> StatusCard:
    current = stage or manifest.lifecycle
    never = manifest.uncovered_criteria()
    card = StatusCard(
        capability=manifest.capability,
        owner=manifest.owner,
        risk=manifest.risk,
        lifecycle=manifest.lifecycle,
        stage=current,
        criteria=len(manifest.criteria),
        gated_by_some_stage=len(manifest.criteria) - len(never),
        never_gated=[
            {"criterion": item.id, "severity": item.severity}
            for item in never
        ],
        stage_gap=_stage_gap(manifest, current),
        stages=[
            {
                "stage": name,
                "require": list(policy.require),
                "approvals": list(policy.approvals),
                "rollback": policy.rollback,
                "after": policy.after,
            }
            for name, policy in manifest.policies.items()
        ],
    )
    card.approval = _approval_status(manifest, approval_path, owner_key)
    card.trail = _trail_status(manifest, trail_path)
    card.receipt = _receipt_status(receipt_path, receipt_key)
    card.waivers = _waiver_status(manifest, waivers_path, owner_key)

    risks = card.residual_risks
    for item in never:
        risks.append(
            f"criterion `{item.id}` ({item.severity}) is gated by no stage"
        )
    for item in card.stage_gap:
        if item["severity"] in GATING_SEVERITIES:
            risks.append(
                f"criterion `{item['criterion']}` ({item['severity']}) is not "
                f"gated at `{current}`"
            )
    for stage_name in manifest.policies:
        entry = card.trail.get("last", {}).get(stage_name)
        if entry is None:
            risks.append(f"no recorded `{stage_name}` gate on this trail")
        elif entry.get("outcome") != "pass":
            risks.append(
                f"the last `{stage_name}` gate was `{entry.get('outcome')}`"
            )
    if card.trail.get("present") and not card.trail.get("ok"):
        detail = (card.trail.get("errors") or ["unknown error"])[0]
        risks.append(f"trail does not verify: {detail}")
    if card.approval.get("required") and not card.approval.get("ok"):
        detail = (card.approval.get("errors") or ["invalid"])[0]
        risks.append(f"owner approval is not valid: {detail}")
    if card.receipt.get("present") and not card.receipt.get("ok"):
        detail = (card.receipt.get("errors") or ["invalid"])[0]
        risks.append(f"receipt does not verify: {detail}")
    for item in card.waivers.get("valid", []):
        risks.append(
            f"criterion `{item['criterion']}` is waived until "
            f"{item.get('expires_at')} by {item.get('approved_by')}"
        )
    if card.waivers.get("present") and not card.waivers.get("ok"):
        detail = (card.waivers.get("errors") or ["invalid"])[0]
        risks.append(f"waiver file does not verify: {detail}")
    if (
        card.receipt.get("ok")
        and card.trail.get("ok")
        and card.receipt.get("trail_head")
        and card.receipt["trail_head"] != card.trail.get("head")
    ):
        risks.append("the receipt was signed for a different trail head")
    return card


def render_card(card: StatusCard) -> str:
    lines = [
        f"Capability: {card.capability}",
        f"owner: {card.owner}  risk: {card.risk}  lifecycle: {card.lifecycle}",
        f"criteria: {card.criteria} total, {card.gated_by_some_stage} gated by "
        f"some stage, {len(card.never_gated)} never gated",
        "",
        "Stages",
    ]
    for item in card.stages:
        parts = [f"require={', '.join(item['require']) or '-'}"]
        if item["approvals"]:
            parts.append(f"approvals={', '.join(item['approvals'])}")
        if item["rollback"]:
            parts.append(f"rollback={item['rollback']}")
        if item["after"]:
            parts.append(f"after={item['after']}")
        lines.append(f"  {item['stage']:<12} " + "  ".join(parts))

    lines.extend(["", "Owner approval"])
    if not card.approval.get("required"):
        lines.append("  not required")
    elif card.approval.get("ok"):
        lines.append(
            f"  valid by {card.approval.get('approved_by') or '-'} "
            f"(digest {str(card.approval.get('manifest_digest'))[:23]}...)"
        )
    else:
        detail = (card.approval.get("errors") or ["invalid"])[0]
        lines.append(f"  INVALID: {detail}")

    lines.extend(["", "Trail"])
    if not card.trail.get("present"):
        lines.append("  not supplied")
    elif not card.trail.get("ok"):
        detail = (card.trail.get("errors") or ["invalid"])[0]
        lines.append(f"  BROKEN: {detail}")
    else:
        lines.append(
            f"  {card.trail['path']}: {card.trail['entries']} entries, "
            f"chain intact, head {str(card.trail.get('head'))[:23]}..."
        )
        for stage, entry in sorted(card.trail.get("last", {}).items()):
            lines.append(
                f"  last {stage}: {entry.get('outcome')} (seq {entry.get('seq')})"
            )

    lines.extend(["", "Receipt"])
    if not card.receipt.get("present"):
        lines.append("  not supplied")
    elif not card.receipt.get("ok"):
        detail = (card.receipt.get("errors") or ["invalid"])[0]
        lines.append(f"  INVALID: {detail}")
    else:
        lines.append(
            f"  valid: {card.receipt.get('outcome')} at commit "
            f"{str(card.receipt.get('commit'))[:12] or '-'}"
        )

    lines.extend(["", "Waivers"])
    if not card.waivers.get("enabled"):
        lines.append("  not enabled")
    elif not card.waivers.get("present"):
        lines.append("  enabled; no waiver file")
    elif not card.waivers.get("ok"):
        detail = (card.waivers.get("errors") or ["invalid"])[0]
        lines.append(f"  INVALID: {detail}")
    else:
        for item in card.waivers.get("valid", []):
            lines.append(
                f"  {item['criterion']}: until {item.get('expires_at')} "
                f"by {item.get('approved_by')}"
            )

    lines.extend(["", "Residual risk"])
    if not card.residual_risks:
        lines.append("  none reported")
    for risk in card.residual_risks:
        lines.append(f"  - {risk}")
    return "\n".join(lines)
