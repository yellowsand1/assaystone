"""Render a capability manifest as a task brief for an agent.

The gate is post-hoc unless the agent knows what it will be judged on. The
brief is a view of the manifest: the criteria, the oracles, the stage policy,
the exact command to check the work, and the rule that a conflict stops the
task instead of being papered over.
"""
from __future__ import annotations

from .plane import CapabilityManifest


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_brief(
    manifest: CapabilityManifest,
    manifest_path: str = ".assaystone/capability.json",
    stage: str = "shadow",
    task: str = "",
) -> str:
    lines = [f"# Capability: {manifest.capability}", ""]
    lines.append(f"Owner: {manifest.owner}")
    lines.append(f"Risk: {manifest.risk}")
    lines.append(f"Current lifecycle: {manifest.lifecycle}")
    actions = ", ".join(manifest.irreversible_actions) or "none"
    lines.append(f"Irreversible actions: {actions}")
    lines.append("")
    if task.strip():
        lines.extend(["## Task", "", task.strip(), ""])
    lines.extend(
        [
            "## Acceptance criteria",
            "",
            "| id | kind | severity | statement | oracle |",
            "|---|---|---|---|---|",
        ]
    )
    for criterion in manifest.criteria:
        lines.append(
            f"| `{criterion.id}` | {criterion.kind} | {criterion.severity} | "
            f"{_cell(criterion.statement)} | `{criterion.oracle}` |"
        )
    lines.extend(["", "## Oracles", ""])
    for oracle in manifest.oracles:
        description = oracle.description or "no description"
        lines.append(f"- `{oracle.id}` ({oracle.type}): {_cell(description)}")
    policy = manifest.policies.get(stage)
    lines.extend(["", f"## The `{stage}` gate", ""])
    if policy is None:
        lines.append(f"No policy is declared for `{stage}`; the gate escalates.")
    else:
        required = ", ".join(f"`{item}`" for item in policy.require) or "nothing"
        lines.append(f"Requires: {required}.")
        if policy.approvals:
            approvals = ", ".join(f"`{item}`" for item in policy.approvals)
            lines.append(f"Approvals: {approvals}.")
        if policy.rollback_required and policy.rollback:
            lines.append(f"Rollback evidence: `{policy.rollback}`.")
        if policy.after:
            lines.append(
                f"Chained after a recorded `{policy.after}` pass on the trail."
            )
    lines.extend(
        [
            "",
            "## How to check",
            "",
            "```bash",
            f"python3 -m assaystone gate --manifest {manifest_path} "
            f"--stage {stage} --root . --json",
            "```",
            "",
            "Exit `0` is pass, `1` is fail, `2` is escalate. Run it before "
            "reporting done.",
            "",
            "## Rules",
            "",
            "- Do not edit tests, CI, or the capability manifest to make the gate pass.",
            "- If a task conflicts with a criterion, stop and explain; do not violate it.",
            "- A pass is evidence from the oracles, not a claim.",
        ]
    )
    return "\n".join(lines) + "\n"
