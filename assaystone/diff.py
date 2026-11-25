"""What changed between two versions of a capability manifest.

An owner approval is bound to a manifest digest, so any change forces a new
review. The reviewer needs to see what actually changed, not a JSON diff: which
criterion appeared, which oracle got weaker, which stage started requiring more.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .plane import CapabilityManifest, manifest_digest


@dataclass
class ManifestDiff:
    old_digest: str
    new_digest: str
    changed: bool
    headline: list[str] = field(default_factory=list)
    criteria_added: list[dict[str, Any]] = field(default_factory=list)
    criteria_removed: list[dict[str, Any]] = field(default_factory=list)
    criteria_changed: list[dict[str, Any]] = field(default_factory=list)
    oracles_added: list[str] = field(default_factory=list)
    oracles_removed: list[str] = field(default_factory=list)
    oracles_changed: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)
    weakened: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_digest": self.old_digest,
            "new_digest": self.new_digest,
            "changed": self.changed,
            "weakened": self.weakened,
            "headline": list(self.headline),
            "criteria": {
                "added": list(self.criteria_added),
                "removed": list(self.criteria_removed),
                "changed": list(self.criteria_changed),
            },
            "oracles": {
                "added": list(self.oracles_added),
                "removed": list(self.oracles_removed),
                "changed": list(self.oracles_changed),
            },
            "policies": list(self.policies),
        }


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _criterion(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "statement": item.statement,
        "oracle": item.oracle,
        "severity": item.severity,
    }


def _mark(headline: list[str], condition: bool, text: str) -> bool:
    if condition:
        headline.append(text)
    return condition


def compare(
    old: CapabilityManifest, new: CapabilityManifest
) -> ManifestDiff:
    diff = ManifestDiff(
        old_digest=manifest_digest(old),
        new_digest=manifest_digest(new),
        changed=manifest_digest(old) != manifest_digest(new),
    )
    weakened = False
    if old.capability != new.capability:
        diff.headline.append(
            f"capability renamed: {old.capability!r} -> {new.capability!r}"
        )
    if old.owner != new.owner:
        diff.headline.append(f"owner: {old.owner!r} -> {new.owner!r}")
    if old.risk != new.risk:
        lowered = SEVERITY_RANK.get(new.risk, 0) < SEVERITY_RANK.get(old.risk, 0)
        diff.headline.append(
            f"risk: {old.risk} -> {new.risk}" + (" (lowered)" if lowered else "")
        )
    if old.lifecycle != new.lifecycle:
        diff.headline.append(
            f"lifecycle: {old.lifecycle} -> {new.lifecycle}"
        )
    if old.manifest_approval != new.manifest_approval:
        diff.headline.append(
            "owner approval: "
            f"{'required' if old.manifest_approval else 'not required'} -> "
            f"{'required' if new.manifest_approval else 'not required'}"
        )
        weakened = weakened or (old.manifest_approval and not new.manifest_approval)
    if old.waivers != new.waivers:
        diff.headline.append(
            "waivers: "
            f"{'enabled' if old.waivers else 'disabled'} -> "
            f"{'enabled' if new.waivers else 'disabled'}"
        )

    old_criteria = {item.id: item for item in old.criteria}
    new_criteria = {item.id: item for item in new.criteria}
    for key in sorted(set(new_criteria) - set(old_criteria)):
        diff.criteria_added.append(_criterion(new_criteria[key]))
    for key in sorted(set(old_criteria) - set(new_criteria)):
        diff.criteria_removed.append(_criterion(old_criteria[key]))
    for key in sorted(set(old_criteria) & set(new_criteria)):
        before, after = old_criteria[key], new_criteria[key]
        if _criterion(before) != _criterion(after):
            diff.criteria_changed.append(
                {"id": key, "before": _criterion(before), "after": _criterion(after)}
            )
            if SEVERITY_RANK.get(after.severity, 0) < SEVERITY_RANK.get(
                before.severity, 0
            ):
                weakened = True
    if diff.criteria_removed:
        weakened = True

    old_oracles = {item.id: item for item in old.oracles}
    new_oracles = {item.id: item for item in new.oracles}
    diff.oracles_added = sorted(set(new_oracles) - set(old_oracles))
    diff.oracles_removed = sorted(set(old_oracles) - set(new_oracles))
    if diff.oracles_removed:
        weakened = True
    for key in sorted(set(old_oracles) & set(new_oracles)):
        before, after = old_oracles[key], new_oracles[key]
        if before.fingerprint != after.fingerprint or before.type != after.type:
            diff.oracles_changed.append(
                {
                    "id": key,
                    "before": {"type": before.type, "fingerprint": before.fingerprint},
                    "after": {"type": after.type, "fingerprint": after.fingerprint},
                }
            )

    old_policies = old.policies
    new_policies = new.policies
    for stage in sorted(set(old_policies) | set(new_policies)):
        before = old_policies.get(stage)
        after = new_policies.get(stage)
        if before is None and after is not None:
            diff.policies.append(
                {
                    "stage": stage,
                    "change": "added",
                    "require": list(after.require),
                    "approvals": list(after.approvals),
                }
            )
            continue
        if before is not None and after is None:
            diff.policies.append({"stage": stage, "change": "removed"})
            weakened = True
            continue
        if before is None or after is None:  # pragma: no cover - exhaustive above
            continue
        changes: dict[str, Any] = {}
        for name in ("require", "approvals"):
            was = set(getattr(before, name))
            now = set(getattr(after, name))
            if was != now:
                changes[name] = {
                    "added": sorted(now - was),
                    "removed": sorted(was - now),
                }
                if was - now:
                    weakened = True
        for name in ("rollback", "after"):
            was, now = getattr(before, name), getattr(after, name)
            if was != now:
                changes[name] = {"before": was, "after": now}
                if name == "rollback" and was and not now:
                    weakened = True
        for name in (
            "allow_merge",
            "allow_deploy",
            "rollback_required",
        ):
            was, now = getattr(before, name), getattr(after, name)
            if was != now:
                changes[name] = {"before": was, "after": now}
        if changes:
            diff.policies.append({"stage": stage, "change": "changed", **changes})

    diff.weakened = _mark(
        diff.headline,
        weakened,
        "this change removes or lowers assurance",
    )
    return diff


def render_diff(diff: ManifestDiff, old_label: str, new_label: str) -> str:
    lines = [
        f"old: {old_label}  {diff.old_digest[:23]}...",
        f"new: {new_label}  {diff.new_digest[:23]}...",
        "",
    ]
    if not diff.changed:
        lines.append("the manifests are identical")
        return "\n".join(lines)
    for item in diff.headline:
        lines.append(f"- {item}")
    if diff.criteria_added:
        lines.append("\ncriteria added:")
        for item in diff.criteria_added:
            lines.append(
                f"  + {item['id']} ({item['severity']}) via {item['oracle']}: "
                f"{item['statement']}"
            )
    if diff.criteria_removed:
        lines.append("\ncriteria removed:")
        for item in diff.criteria_removed:
            lines.append(f"  - {item['id']} ({item['severity']})")
    if diff.criteria_changed:
        lines.append("\ncriteria changed:")
        for item in diff.criteria_changed:
            before, after = item["before"], item["after"]
            fields = [
                name
                for name in ("kind", "statement", "oracle", "severity")
                if before[name] != after[name]
            ]
            detail = ", ".join(
                f"{name}: {before[name]!r} -> {after[name]!r}" for name in fields
            )
            lines.append(f"  ~ {item['id']}: {detail}")
    if diff.oracles_added:
        lines.append("\noracles added: " + ", ".join(diff.oracles_added))
    if diff.oracles_removed:
        lines.append("\noracles removed: " + ", ".join(diff.oracles_removed))
    if diff.oracles_changed:
        lines.append("\noracles changed:")
        for item in diff.oracles_changed:
            lines.append(
                f"  ~ {item['id']}: {item['before']['fingerprint']} -> "
                f"{item['after']['fingerprint']}"
            )
    if diff.policies:
        lines.append("\npolicies:")
        for item in diff.policies:
            if item["change"] == "added":
                lines.append(
                    f"  + {item['stage']}: require={item['require']} "
                    f"approvals={item['approvals']}"
                )
            elif item["change"] == "removed":
                lines.append(f"  - {item['stage']}")
            else:
                parts = [
                    f"{key}={value!r}"
                    for key, value in item.items()
                    if key not in ("stage", "change")
                ]
                lines.append(f"  ~ {item['stage']}: " + ", ".join(parts))
    return "\n".join(lines)
