"""A reversibility drill: apply the action, run the compensation, compare state.

`rollback` checks that a commit reverse-applies. That is a claim about a diff, not
about the world. A drill is the stronger statement: take the state, perform the
irreversible action, perform its declared compensation, and require the state to
be byte-identical again.

The record it writes is bound to the manifest digest and the commit, so a drill
recorded for other rules or other code is not evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .oracles import run_oracle
from .plane import CapabilityManifest, manifest_digest, repo_head_commit

VERSION = 1
DIRECTORY = Path(".assaystone") / "drills"


class DrillError(ValueError):
    """A drill cannot be run or read."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(path: Path) -> str:
    """A content hash for a file, a tree hash for a directory, "absent" otherwise.

    A directory must be hashed by its contents: hashing it as a file returns
    "absent" and would make a drill over a build directory vacuous.
    """
    import hashlib

    if path.is_dir():
        digest = hashlib.sha256()
        entries = sorted(
            item for item in path.rglob("*") if item.is_file()
        )
        for item in entries:
            digest.update(
                str(item.relative_to(path)).encode("utf-8")
            )
            digest.update(b"\0")
            try:
                digest.update(item.read_bytes())
            except OSError:
                digest.update(b"unreadable")
            digest.update(b"\0")
        return "dir-sha256:" + digest.hexdigest()
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def snapshot(root: Path, paths: list[str]) -> dict[str, str]:
    return {str(item): _hash(root / str(item)) for item in paths}


@dataclass
class DrillResult:
    id: str
    outcome: str
    reasons: list[str] = field(default_factory=list)
    before: dict[str, str] = field(default_factory=dict)
    middle: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)
    action: str = ""
    compensation: str = ""
    action_outcome: str = ""
    compensation_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "action": self.action,
            "compensation": self.compensation,
            "action_outcome": self.action_outcome,
            "compensation_outcome": self.compensation_outcome,
            "before": dict(self.before),
            "middle": dict(self.middle),
            "after": dict(self.after),
        }


def record_path(root: str | Path, drill_id: str) -> Path:
    safe = "".join(
        char if char.isalnum() or char in "-_." else "_" for char in drill_id
    )
    return Path(root) / DIRECTORY / f"{safe}.json"


def run_drill(
    manifest: CapabilityManifest, drill_id: str, root: str | Path
) -> DrillResult:
    root = Path(root).resolve()
    item = next(
        (entry for entry in manifest.reversibility if entry.id == drill_id), None
    )
    if item is None:
        raise DrillError(f"no reversibility entry named {drill_id!r}")
    by_id = {oracle.id: oracle for oracle in manifest.oracles}
    action = by_id.get(item.action)
    compensation = by_id.get(item.compensation)
    if action is None:
        raise DrillError(f"unknown action oracle: {item.action!r}")
    if compensation is None:
        raise DrillError(f"unknown compensation oracle: {item.compensation!r}")
    if not item.state:
        raise DrillError(
            "a drill needs at least one state path to compare before and after"
        )

    before = snapshot(root, item.state)
    result = DrillResult(
        id=drill_id,
        outcome="fail",
        action=item.action,
        compensation=item.compensation,
        before=before,
    )
    action_result = run_oracle(action, root)
    result.action_outcome = action_result.outcome
    result.middle = snapshot(root, item.state)
    if action_result.outcome != "pass":
        result.reasons.append(
            f"the action {item.action!r} did not run: "
            f"{action_result.reasons[0] if action_result.reasons else action_result.outcome}"
        )
        result.after = snapshot(root, item.state)
        return result

    compensation_result = run_oracle(compensation, root)
    result.compensation_outcome = compensation_result.outcome
    result.after = snapshot(root, item.state)
    if compensation_result.outcome != "pass":
        result.reasons.append(
            f"the compensation {item.compensation!r} did not run: "
            f"{compensation_result.reasons[0] if compensation_result.reasons else compensation_result.outcome}"
        )
        return result

    unchanged = [
        path
        for path in item.state
        if result.before.get(str(path)) == result.middle.get(str(path))
    ]
    if len(unchanged) == len(item.state):
        result.reasons.append(
            "the action did not change the observed state, so the drill "
            "proves nothing; check the state paths"
        )
        return result
    drift = [
        path
        for path in item.state
        if result.before.get(str(path)) != result.after.get(str(path))
    ]
    if drift:
        result.reasons.append(
            "the compensation did not restore the state: " + ", ".join(drift)
        )
        return result
    result.outcome = "pass"
    return result


def write_record(
    manifest: CapabilityManifest,
    result: DrillResult,
    root: str | Path,
    actor: str = "unknown",
    at: str | None = None,
) -> Path:
    root = Path(root)
    record = {
        "version": VERSION,
        "at": at or _now(),
        "actor": actor,
        "capability": manifest.capability,
        "manifest_digest": manifest_digest(manifest),
        "commit": repo_head_commit(root),
        **result.to_dict(),
    }
    target = record_path(root, result.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def load_record(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DrillError(f"drill record not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DrillError(f"invalid drill record in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DrillError("drill record must be an object")
    return data


@dataclass
class DrillCheck:
    ok: bool
    outcome: str
    reasons: list[str]
    evidence: list[str]


def verify_record(
    record: dict[str, Any],
    manifest: CapabilityManifest,
    root: str | Path,
    drill_id: str,
    require_commit: bool = True,
    max_age_minutes: float | None = None,
    now: datetime | None = None,
) -> DrillCheck:
    reasons: list[str] = []
    evidence = [f"drill={drill_id}"]
    if record.get("version") != VERSION:
        return DrillCheck(
            ok=False,
            outcome="escalate",
            reasons=[f"unknown drill record version: {record.get('version')!r}"],
            evidence=evidence,
        )
    if record.get("capability") != manifest.capability:
        return DrillCheck(
            ok=False,
            outcome="escalate",
            reasons=[
                f"the drill is for {record.get('capability')!r}, "
                f"not {manifest.capability!r}"
            ],
            evidence=evidence,
        )
    if record.get("manifest_digest") != manifest_digest(manifest):
        return DrillCheck(
            ok=False,
            outcome="escalate",
            reasons=["the drill was run under different acceptance rules"],
            evidence=evidence,
        )
    if max_age_minutes is not None:
        try:
            at = datetime.strptime(
                str(record.get("at")), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            at = None
        if at is None:
            reasons.append("the drill record has no readable timestamp")
        else:
            age = (now or datetime.now(timezone.utc)) - at
            evidence.append(f"age={int(age.total_seconds() // 60)}m")
            if age.total_seconds() > max_age_minutes * 60:
                reasons.append(
                    f"the drill is older than {max_age_minutes:g} minutes"
                )
    if require_commit:
        head = repo_head_commit(root)
        recorded = str(record.get("commit") or "")
        if head and not recorded:
            reasons.append("the drill record has no commit")
        elif head and recorded != head:
            reasons.append(
                f"the drill was run on commit {recorded[:12]}, not {head[:12]}"
            )
    if reasons:
        return DrillCheck(ok=False, outcome="escalate", reasons=reasons, evidence=evidence)
    outcome = str(record.get("outcome") or "")
    evidence.append(f"drill_outcome={outcome or '-'}")
    if outcome != "pass":
        return DrillCheck(
            ok=False,
            outcome="fail",
            reasons=[
                f"the last drill of {drill_id!r} ended in {outcome or 'no outcome'}"
            ]
            + [str(item) for item in (record.get("reasons") or [])][:2],
            evidence=evidence,
        )
    return DrillCheck(ok=True, outcome="pass", reasons=[], evidence=evidence)
