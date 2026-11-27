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


@dataclass
class Blocker:
    kind: str
    detail: str
    fix: str = ""
    command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "fix": self.fix,
            "command": self.command,
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


def _policy_snippet(manifest: CapabilityManifest, target: str) -> str:
    require = [item.id for item in manifest.oracles][:3] or ["build"]
    policy = {
        "require": require,
        "approvals": ["reviewer"],
        "allow_merge": True,
    }
    return json.dumps({target: policy}, indent=2)


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
    policy = manifest.policies.get(wanted)
    if policy is None:
        plan_.blockers.append(
            Blocker(
                kind="no-policy",
                detail=f"the manifest declares no `{wanted}` stage",
                fix=_policy_snippet(manifest, wanted),
                command=(
                    "assaystone capability propose --manifest "
                    ".assaystone/capability.json --root ."
                ),
            )
        )
        return plan_

    oracle_ids = {item.id for item in manifest.oracles}
    has_approval = bool(policy.approvals) or manifest.manifest_approval
    if not policy.allow_merge:
        plan_.blockers.append(
            Blocker(
                kind="locked-stage",
                detail=(
                    f"`{wanted}` exists but does not allow merging, so nothing "
                    "can move through it"
                ),
                fix=(
                    json.dumps(
                        {
                            wanted: {
                                "approvals": ["reviewer"],
                                "allow_merge": True,
                            }
                        },
                        indent=2,
                    )
                    if has_approval
                    else _approval_snippet()
                ),
                command=(
                    "add `approvals: [\"reviewer\"]` and `allow_merge: true` "
                    "to the policy, then re-run `capability next`"
                ),
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
    if policy.allow_deploy and not (policy.rollback_required and policy.rollback):
        fix = ""
        if not manifest.reversibility:
            fix = (
                '"reversibility": [\n'
                '      {"id": "promote", "action": "<mutating oracle>",\n'
                '       "compensation": "<undo oracle>", "state": ["<path>"]}\n'
                "    ]"
            )
        plan_.blockers.append(
            Blocker(
                kind="no-rollback",
                detail=f"`{wanted}` allows deploy without rollback evidence",
                fix=fix,
                command=(
                    "assaystone capability drill --manifest "
                    ".assaystone/capability.json --root ."
                ),
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
        plan_.blockers.append(
            Blocker(
                kind="ungated-criterion",
                detail=f"critical criterion `{name}` is not gated at `{wanted}`",
                command=f"add its oracle to the `{wanted}` policy's require list",
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
        lines.append("ready: nothing blocks this promotion")
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
