"""What the environment still owes the gate.

`capability next` makes the *manifest* able to express a stage. This checks the
things outside the manifest that the gate will read: an approval record, a drill
record, a session record. Without them the gate escalates — correctly — and
without this command the operator has to guess which one is missing and what
shape it has.

Nothing here is created on the operator's behalf: an approval is a person's
decision, and a drill is a claim about the world. It prints the command or the
JSON, and says who has to act.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .drill import DrillError
from .drill import load_record as load_drill
from .drill import record_path as drill_record_path
from .plane import CapabilityManifest
from .session_record import DEFAULT_RECORD as RUNTIME_RECORD


@dataclass
class Need:
    oracle: str
    kind: str
    detail: str
    command: str = ""
    snippet: str = ""
    actor: str = "operator"

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracle": self.oracle,
            "kind": self.kind,
            "detail": self.detail,
            "command": self.command,
            "snippet": self.snippet,
            "actor": self.actor,
        }


@dataclass
class Preparation:
    capability: str
    stage: str
    needs: list[Need] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.needs

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "stage": self.stage,
            "ready": self.ready,
            "needs": [item.to_dict() for item in self.needs],
        }


def _approval_need(spec: Any, root: Path) -> Need | None:
    action = str(spec.payload.get("action") or "")
    record = root / str(spec.payload.get("record") or "approvals.json")
    shape = {
        "approvals": [
            {
                "action": action,
                "approved": True,
                "approver": "<the person who approved>",
                "scope": "<what they approved>",
            }
        ]
    }
    if not record.exists():
        return Need(
            oracle=spec.id,
            kind="approval-record",
            detail=(
                f"{record.name} does not exist; `{spec.id}` will escalate until "
                f"someone records the `{action}` approval"
            ),
            command=f"the approver writes {record.name}; shape:",
            snippet=json.dumps(shape, indent=2),
            actor="approver",
        )
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Need(
            oracle=spec.id,
            kind="approval-record",
            detail=f"{record.name} is not readable JSON: {exc}",
            actor="approver",
        )
    approvals = data.get("approvals") if isinstance(data, dict) else data
    entries = [
        item
        for item in (approvals or [])
        if isinstance(item, dict) and item.get("action") == action
    ]
    if not entries:
        return Need(
            oracle=spec.id,
            kind="approval-record",
            detail=f"no `{action}` approval in {record.name}",
            command=f"the approver adds an entry for `{action}`; shape:",
            snippet=json.dumps(shape, indent=2),
            actor="approver",
        )
    if not any(item.get("approved") for item in entries):
        return Need(
            oracle=spec.id,
            kind="approval-denied",
            detail=f"the `{action}` approval in {record.name} is not granted",
            actor="approver",
        )
    if spec.payload.get("hmac_env") and not data.get("signature"):
        return Need(
            oracle=spec.id,
            kind="approval-unsigned",
            detail=(
                f"`{spec.id}` requires a signature, and {record.name} has none"
            ),
            command=(
                "sign the record with the owner key, or remove "
                "`hmac_env` from the oracle"
            ),
            actor="approver",
        )
    return None


def _drill_need(manifest: CapabilityManifest, spec: Any, root: Path) -> Need | None:
    drill_id = str(spec.payload.get("id") or "")
    path = drill_record_path(root, drill_id)
    command = (
        "assaystone capability drill --manifest "
        f"{manifest.source or '.assaystone/capability.json'} --root . "
        f"--id {drill_id}"
    )
    if not drill_id:
        return Need(
            oracle=spec.id,
            kind="drill-missing",
            detail=f"`{spec.id}` names no drill",
            actor="operator",
        )
    if not path.exists():
        return Need(
            oracle=spec.id,
            kind="drill-missing",
            detail=f"no drill record for `{drill_id}` at {path.name}",
            command=command,
            actor="operator",
        )
    try:
        record = load_drill(path)
    except DrillError as exc:
        return Need(
            oracle=spec.id, kind="drill-missing", detail=str(exc), command=command
        )
    if record.get("outcome") != "pass":
        return Need(
            oracle=spec.id,
            kind="drill-failed",
            detail=(
                f"the last drill of `{drill_id}` was "
                f"{record.get('outcome')!r}; the compensation did not restore "
                "the state"
            ),
            command=command,
            actor="operator",
        )
    return None


def _runtime_need(spec: Any, root: Path) -> Need | None:
    record = root / str(spec.payload.get("record") or RUNTIME_RECORD)
    if record.exists():
        return None
    return Need(
        oracle=spec.id,
        kind="session-record",
        detail=(
            f"{record} does not exist; the supervisor writes it when a session "
            "ends"
        ),
        command=(
            "assaystone hook install claude-code --manifest "
            f"{(spec.payload.get('manifest') or '.assaystone/capability.json')} "
            "--mode block"
        ),
        actor="operator",
    )


def prepare(
    manifest: CapabilityManifest, stage: str, root: str | Path
) -> Preparation:
    root = Path(root).resolve()
    result = Preparation(capability=manifest.capability, stage=stage)
    policy = manifest.policies.get(stage)
    if policy is None:
        result.needs.append(
            Need(
                oracle="-",
                kind="no-policy",
                detail=f"no `{stage}` policy; nothing to prepare",
                command=(
                    "assaystone capability next --manifest "
                    ".assaystone/capability.json --apply"
                ),
            )
        )
        return result
    by_id = {item.id: item for item in manifest.oracles}
    for oracle_id in list(dict.fromkeys(policy.require + policy.approvals)):
        spec = by_id.get(oracle_id)
        if spec is None:
            continue
        need = None
        if spec.type == "human":
            need = _approval_need(spec, root)
        elif spec.type == "drill":
            need = _drill_need(manifest, spec, root)
        elif spec.type == "runtime":
            need = _runtime_need(spec, root)
        if need is not None:
            result.needs.append(need)
    return result


def render(result: Preparation) -> str:
    lines = [f"{result.capability} at `{result.stage}`"]
    if result.ready:
        lines.append("")
        lines.append("ready: the gate has everything it reads")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"{len(result.needs)} thing(s) the gate will not find")
    for index, need in enumerate(result.needs, start=1):
        lines.append("")
        lines.append(f"{index}. [{need.actor}] {need.detail}")
        if need.command:
            lines.append(f"   {need.command}")
        if need.snippet:
            lines.extend(f"     {line}" for line in need.snippet.splitlines())
    return "\n".join(lines)
