"""What is missing to promote a capability, and the exact patch to add it.

A residual-risk list tells you what is unresolved. This turns it into the next
action: which blocker, why, and the JSON or command that removes it. The patch is
a draft — the owner still reviews and signs it — but nobody has to guess the
shape of an approval oracle or a reversibility entry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .plane import CapabilityManifest

ORDER = ("design", "shadow", "canary", "production", "incident", "retired")


APPROVAL_ORACLE = {
    "id": "reviewer",
    "type": "human",
    "description": "a named reviewer approved promotion",
    "payload": {"action": "promote", "record": "approvals.json"},
}


@dataclass
class Blocker:
    kind: str
    detail: str
    fix: str = ""
    command: str = ""
    # Machine-applicable steps. Empty when the fix needs a human decision.
    patch: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "fix": self.fix,
            "command": self.command,
            "appliable": bool(self.patch),
        }


@dataclass
class NextPlan:
    capability: str
    current: str
    target: str
    blockers: list[Blocker] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "current": self.current,
            "target": self.target,
            "ready": self.ready,
            "blockers": [item.to_dict() for item in self.blockers],
        }


def next_stage(manifest: CapabilityManifest) -> str:
    current = manifest.lifecycle
    if current not in ORDER:
        return "shadow"
    index = ORDER.index(current)
    for stage in ORDER[index + 1 :]:
        if stage in ("incident", "retired"):
            break
        return stage
    return "production"


def _approval_snippet() -> str:
    return """    {
      "id": "reviewer",
      "type": "human",
      "description": "a named reviewer approved promotion",
      "payload": {"action": "promote", "record": "approvals.json"}
    }"""


def _template_policy(manifest: CapabilityManifest) -> dict[str, Any]:
    require = [item.id for item in manifest.oracles][:3] or ["build"]
    return {"require": require, "approvals": ["reviewer"], "allow_merge": True}


def _policy_snippet(manifest: CapabilityManifest, target: str) -> str:
    return json.dumps({target: _template_policy(manifest)}, indent=2)


def plan(
    manifest: CapabilityManifest,
    target: str | None = None,
    ready_oracles: set[str] | None = None,
) -> NextPlan:
    """``ready_oracles`` are the ones whose last recorded decision passed."""
    wanted = target or next_stage(manifest)
    plan_ = NextPlan(
        capability=manifest.capability,
        current=manifest.lifecycle,
        target=wanted,
    )
    has_reviewer = any(item.id == "reviewer" for item in manifest.oracles)
    policy = manifest.policies.get(wanted)
    if policy is None:
        patch: list[dict[str, Any]] = []
        if not has_reviewer:
            patch.append({"op": "add_oracle", "value": dict(APPROVAL_ORACLE)})
        patch.append(
            {
                "op": "add_policy",
                "stage": wanted,
                "value": _template_policy(manifest),
            }
        )
        plan_.blockers.append(
            Blocker(
                kind="no-policy",
                detail=f"the manifest declares no `{wanted}` stage",
                fix=_policy_snippet(manifest, wanted),
                patch=patch,
            )
        )
        return plan_

    oracle_ids = {item.id for item in manifest.oracles}
    has_approval = bool(policy.approvals) or manifest.manifest_approval
    if not policy.allow_merge:
        patch = []
        if not has_approval:
            if not has_reviewer:
                patch.append({"op": "add_oracle", "value": dict(APPROVAL_ORACLE)})
            patch.append({"op": "approve", "stage": wanted, "oracle": "reviewer"})
        patch.append({"op": "allow_merge", "stage": wanted})
        plan_.blockers.append(
            Blocker(
                kind="locked-stage",
                detail=(
                    f"`{wanted}` exists but does not allow merging, so nothing "
                    "can move through it"
                ),
                fix=(
                    _approval_snippet() if not has_approval
                    else json.dumps({wanted: {"allow_merge": True}}, indent=2)
                ),
                command=(
                    "then re-run `capability next`"
                    if not patch
                    else "applied by --apply"
                ),
                patch=patch,
            )
        )
    if policy.allow_deploy and not has_approval:
        plan_.blockers.append(
            Blocker(
                kind="no-approval",
                detail=(
                    f"`{wanted}` allows deploy with nothing to approve it"
                ),
                fix=_approval_snippet(),
                command="then add \"reviewer\" to the policy's approvals",
            )
        )
    missing_oracles = [
        name for name in policy.require + policy.approvals if name not in oracle_ids
    ]
    for name in missing_oracles:
        plan_.blockers.append(
            Blocker(
                kind="unknown-oracle",
                detail=f"`{wanted}` names `{name}`, which the manifest does not define",
                command="add the oracle, or remove it from the policy",
            )
        )
    bypassed = [
        item.id
        for item in manifest.criteria
        if item.severity == "critical"
        and item.oracle not in set(policy.require) | set(policy.approvals)
    ]
    for name in bypassed:
        oracle_id = next(
            (item.oracle for item in manifest.criteria if item.id == name), ""
        )
        plan_.blockers.append(
            Blocker(
                kind="ungated-criterion",
                detail=f"critical criterion `{name}` is not gated at `{wanted}`",
                command=f"add `{oracle_id}` to the `{wanted}` policy's require list",
                patch=(
                    [{"op": "require", "stage": wanted, "oracle": oracle_id}]
                    if oracle_id
                    else []
                ),
            )
        )
    if ready_oracles is not None:
        for name in policy.require:
            if name in oracle_ids and name not in ready_oracles:
                plan_.blockers.append(
                    Blocker(
                        kind="no-evidence",
                        detail=f"`{name}` has no passing decision on this trail",
                        command=(
                            f"assaystone gate --manifest "
                            f".assaystone/capability.json --stage {wanted} "
                            f"--root . --audit .assaystone/trail.jsonl"
                        ),
                    )
                )
    return plan_


def render(plan_: NextPlan) -> str:
    lines = [
        f"{plan_.capability}: {plan_.current} -> {plan_.target}",
        "",
    ]
    if plan_.ready:
        lines.append(
            "ready: nothing structural blocks this promotion; run the gate to "
            "decide"
        )
        return "\n".join(lines)
    lines.append(f"{len(plan_.blockers)} blocker(s)")
    for index, blocker in enumerate(plan_.blockers, start=1):
        lines.append("")
        lines.append(f"{index}. {blocker.detail}")
        if blocker.fix:
            lines.append("   add to the manifest:")
            lines.extend(f"     {line}" for line in blocker.fix.splitlines())
        if blocker.command:
            lines.append(f"   then: {blocker.command}")
    return "\n".join(lines)


def apply_patches(
    data: dict[str, Any], plan_: NextPlan
) -> tuple[list[str], list[str]]:
    """Apply every blocker that can be applied mechanically.

    Returns (applied, skipped). A blocker without a patch stays: inventing a
    compensation oracle or a piece of evidence would be the fake the product is
    against.
    """
    applied: list[str] = []
    skipped: list[str] = []
    policies = data.setdefault("policies", {})
    oracles = data.setdefault("oracles", [])
    known = {str(item.get("id")) for item in oracles if isinstance(item, dict)}
    for blocker in plan_.blockers:
        if not blocker.patch:
            skipped.append(blocker.detail)
            continue
        for op in blocker.patch:
            kind = str(op.get("op") or "")
            stage = str(op.get("stage") or "")
            if kind == "add_oracle":
                value = dict(op["value"])
                if value["id"] in known:
                    continue
                oracles.append(value)
                known.add(str(value["id"]))
                applied.append(f"added oracle `{value['id']}`")
            elif kind == "add_policy":
                if stage in policies:
                    continue
                policies[stage] = dict(op["value"])
                applied.append(f"added the `{stage}` policy")
            elif kind in ("approve", "require"):
                policy = policies.setdefault(stage, {"require": []})
                field_name = "approvals" if kind == "approve" else "require"
                entries = policy.setdefault(field_name, [])
                oracle_id = str(op.get("oracle") or "")
                if oracle_id and oracle_id not in entries:
                    entries.append(oracle_id)
                    applied.append(f"`{stage}` now lists `{oracle_id}` in {field_name}")
            elif kind == "allow_merge":
                policy = policies.setdefault(stage, {"require": []})
                if not policy.get("allow_merge"):
                    policy["allow_merge"] = True
                    applied.append(f"`{stage}` allows merging")
    return applied, skipped
