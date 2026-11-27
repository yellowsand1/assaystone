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
from .plane import CapabilityManifest, repo_head_commit
from .receipt import ReceiptError, load_receipt, verify_receipt
from .revocation import read_revocations, revocation_path_for
from .session_record import DEFAULT_RECORD, RecordError, load_record, verify_record
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
    revocations: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
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
            "revocations": dict(self.revocations),
            "runtime": dict(self.runtime),
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
    owner_public_key: str | Path | None = None,
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
    try:
        data = load_approval(target)
    except ApprovalError as exc:
        info["errors"].append(str(exc))
        return info
    check = verify_approval(
        data,
        owner_key,
        manifest,
        public_key_path=owner_public_key,
    )
    info.update(check.info)
    info["ok"] = check.ok
    info["errors"] = list(check.errors)
    return info


def _trail_status(
    manifest: CapabilityManifest,
    path: str | Path | None,
    root: str | Path | None = None,
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
    current = ""
    if root is not None:
        current = repo_head_commit(root)
    if not current and manifest.source:
        current = repo_head_commit(manifest.source)
    info["current_commit"] = current
    info["last"] = {
        stage: {
            "seq": entry.get("seq"),
            "outcome": entry.get("outcome"),
            "at": entry.get("at"),
            "hash": entry.get("hash"),
            "commit": entry.get("commit"),
            "stale": bool(
                current
                and entry.get("commit")
                and entry.get("commit") != current
            ),
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
    owner_public_key: str | Path | None = None,
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
    try:
        data = load_waivers(str(target))
    except WaiverError as exc:
        info["ok"] = False
        info["errors"].append(str(exc))
        return info
    check = verify_waivers(
        data,
        owner_key,
        manifest,
        public_key_path=owner_public_key,
    )
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
    revocations_path: str | Path | None = None,
    runtime_path: str | Path | None = None,
    root: str | Path | None = None,
    owner_key: str = "",
    owner_public_key: str | Path | None = None,
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
    card.approval = _approval_status(
        manifest, approval_path, owner_key, owner_public_key
    )
    card.trail = _trail_status(manifest, trail_path, root)
    card.receipt = _receipt_status(receipt_path, receipt_key)
    card.waivers = _waiver_status(
        manifest, waivers_path, owner_key, owner_public_key
    )
    revocations = read_revocations(
        revocations_path or revocation_path_for(manifest.source or None)
    )
    project_fields = [
        ("owner approval", card.approval),
        ("receipt", card.receipt),
    ]
    hits = []
    for label, status in project_fields:
        hit = revocations.is_revoked(status.get("key_id"))
        if hit:
            hits.append({**hit, "artifact": label})
    for item in card.waivers.get("valid", []):
        hit = revocations.is_revoked(item.get("key_id"))
        if hit:
            hits.append({**hit, "artifact": f"waiver for `{item['criterion']}`"})
    record_path = runtime_path or (
        Path(manifest.source).parent / DEFAULT_RECORD
        if manifest.source
        else None
    )
    if record_path is not None and Path(record_path).exists():
        try:
            record = load_record(record_path)
            check = verify_record(
                record, root or Path(record_path).parent.parent
            )
        except RecordError as exc:
            card.runtime = {"present": True, "ok": False, "reasons": [str(exc)]}
        else:
            card.runtime = {
                "present": True,
                "path": str(record_path),
                "ok": check.ok,
                "session": record.get("session_id"),
                "at": record.get("at"),
                "commit": record.get("commit"),
                "gate_outcome": (record.get("gate") or {}).get("outcome"),
                "files": len(record.get("files") or {}),
                "reasons": list(check.reasons),
            }
        if not card.runtime.get("ok"):
            detail = (card.runtime.get("reasons") or ["invalid"])[0]
            card.residual_risks.append(
                f"the runtime record does not describe this code: {detail}"
            )
    else:
        card.runtime = {"present": False}
    card.revocations = {
        "present": bool(
            (revocations_path or revocation_path_for(manifest.source or None))
        ),
        "ok": revocations.ok,
        "errors": list(revocations.errors),
        "entries": len(revocations.revoked),
        "revoked_artifacts": hits,
    }
    for hit in hits:
        card.residual_risks.append(
            f"{hit['artifact']} was signed by a revoked key {hit['key_id']}"
        )
    if not revocations.ok:
        card.residual_risks.append(
            "the revocation list does not read: "
            + (revocations.errors[0] if revocations.errors else "unknown error")
        )

    risks = card.residual_risks
    for item in never:
        risks.append(
            f"criterion `{item.id}` ({item.severity}) is gated by no stage"
        )
    if not card.trail.get("present"):
        risks.append("no trail evidence")
    else:
        last = card.trail.get("last", {})
        current_entry = last.get(card.lifecycle)
        if current_entry is None:
            risks.append(
                f"no recorded `{card.lifecycle}` gate for the current lifecycle"
            )
        elif current_entry.get("outcome") != "pass":
            risks.append(
                f"the last `{card.lifecycle}` gate was "
                f"`{current_entry.get('outcome')}`"
            )
        for stage_name, entry in last.items():
            if entry.get("stale"):
                risks.append(
                    f"the last `{stage_name}` decision was made on a "
                    f"different commit ({str(entry.get('commit'))[:12]} vs "
                    f"{str(card.trail.get('current_commit'))[:12]})"
                )
            if stage_name == card.lifecycle:
                continue
            if entry.get("outcome") != "pass":
                risks.append(
                    f"the last `{stage_name}` gate was "
                    f"`{entry.get('outcome')}`"
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
            marker = " [stale commit]" if entry.get("stale") else ""
            lines.append(
                f"  last {stage}: {entry.get('outcome')} (seq "
                f"{entry.get('seq')}, {str(entry.get('commit'))[:12] or '-'})"
                f"{marker}"
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

    if card.stage_gap:
        gap = ", ".join(
            f"`{item['criterion']}` ({item['severity']})"
            for item in card.stage_gap
        )
        lines.extend(["", f"Stage gap at `{card.stage}`", f"  {gap}"])

    lines.extend(["", "Runtime record"])
    if not card.runtime.get("present"):
        lines.append("  none")
    elif not card.runtime.get("ok"):
        detail = (card.runtime.get("reasons") or ["invalid"])[0]
        lines.append(f"  NOT CURRENT: {detail}")
    else:
        lines.append(
            f"  {card.runtime.get('session') or '-'} at "
            f"{card.runtime.get('at') or '-'}, "
            f"{card.runtime.get('files', 0)} file(s), gate "
            f"{card.runtime.get('gate_outcome') or '-'}"
        )

    lines.extend(["", "Revocations"])
    if not card.revocations.get("present"):
        lines.append("  no revocation list")
    elif not card.revocations.get("ok"):
        lines.append(
            "  INVALID: "
            + (
                (card.revocations.get("errors") or ["invalid"])[0]
            )
        )
    elif card.revocations.get("revoked_artifacts"):
        for hit in card.revocations["revoked_artifacts"]:
            lines.append(f"  {hit['artifact']}: revoked key {hit['key_id']}")
    else:
        lines.append(
            f"  {card.revocations.get('entries', 0)} revoked key(s), none used"
        )

    lines.extend(["", "Residual risk"])
    if not card.residual_risks:
        lines.append("  none reported")
    for risk in card.residual_risks:
        lines.append(f"  - {risk}")
    return "\n".join(lines)
