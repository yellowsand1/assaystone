"""A record that the tool wrote, not the agent.

The transcript oracle reads a file the agent's harness wrote. It is downgraded as
testimony for exactly that reason. This module produces the other half: when a
session ends, the Stop hook writes what *it* observed — the commit, the files it
saw, their hashes, and the gate outcome — and the `runtime` oracle decides
against that record.

A record is not a receipt: it is unsigned and lives next to the work. It answers
"did this session end in a passing gate on *this* code, and has anything changed
since?" — a question the agent cannot answer about itself.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = 1
DEFAULT_RECORD = Path(".assaystone") / "runtime" / "last.json"


class RecordError(ValueError):
    """A runtime record cannot be written or read."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def observe(
    root: str | Path, relative_paths: Iterable[str]
) -> dict[str, str]:
    """Content hashes of the files this host can see right now."""
    root = Path(root)
    files: dict[str, str] = {}
    for relative in sorted(set(relative_paths)):
        if not relative:
            continue
        target = root / relative
        digest = _hash_file(target)
        files[relative] = digest or "absent"
    return files


def write_record(
    root: str | Path,
    session_id: str,
    relative_paths: Iterable[str],
    gate: Any | None = None,
    findings: int = 0,
    commit: str = "",
    path: str | Path | None = None,
) -> Path:
    """Write what the supervisor observed at the end of a session."""
    root = Path(root)
    at = _now()
    record = {
        "version": VERSION,
        "source": "runtime",
        "at": _text(at),
        "session_id": session_id,
        "root": str(root),
        "commit": commit,
        "files": observe(root, relative_paths),
        "gate": {
            "capability": getattr(gate, "capability", ""),
            "stage": getattr(gate, "stage", ""),
            "outcome": getattr(gate, "outcome", ""),
            "manifest_digest": getattr(gate, "manifest_digest", ""),
            "commit": getattr(gate, "commit", ""),
        }
        if gate is not None
        else {},
        "audit": {"findings": findings},
    }
    target = Path(path) if path else root / DEFAULT_RECORD
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if session_id:
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_" for char in session_id
        )[:120]
        sibling = target.parent / f"{safe}.json"
        if sibling != target:
            sibling.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return target


def load_record(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecordError(f"runtime record not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecordError(f"invalid runtime record in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordError("runtime record must be an object")
    return data


@dataclass
class RecordCheck:
    ok: bool
    reasons: list[str]
    evidence: list[str]
    outcome: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }


def verify_record(
    record: dict[str, Any],
    root: str | Path,
    require_outcome: str = "pass",
    require_commit: bool = True,
    max_age_minutes: float | None = None,
    now: datetime | None = None,
) -> RecordCheck:
    """Decide whether this record still describes the code in front of us."""
    root = Path(root)
    reasons: list[str] = []
    evidence = [f"session={record.get('session_id') or '-'}"]

    if record.get("version") != VERSION:
        return RecordCheck(
            ok=False,
            outcome="escalate",
            reasons=[f"unknown record version: {record.get('version')!r}"],
            evidence=evidence,
        )
    if record.get("source") != "runtime":
        return RecordCheck(
            ok=False,
            outcome="escalate",
            reasons=[
                "the record does not claim to be runtime-authored "
                f"(source={record.get('source')!r})"
            ],
            evidence=evidence,
        )

    age_reason = ""
    if max_age_minutes is not None:
        try:
            observed_at = datetime.strptime(
                str(record.get("at")), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            observed_at = None
        if observed_at is None:
            age_reason = "the record has no readable timestamp"
        else:
            age = (now or _now()) - observed_at
            evidence.append(f"age={int(age.total_seconds() // 60)}m")
            if age > timedelta(minutes=max_age_minutes):
                age_reason = (
                    f"the record is older than {max_age_minutes:g} minutes"
                )
    if age_reason:
        return RecordCheck(
            ok=False, outcome="escalate", reasons=[age_reason], evidence=evidence
        )

    gate = record.get("gate") or {}
    if require_outcome:
        observed = str(gate.get("outcome") or "")
        evidence.append(f"gate={observed or '-'}")
        if not observed:
            return RecordCheck(
                ok=False,
                outcome="escalate",
                reasons=["the record contains no gate result"],
                evidence=evidence,
            )
        if observed != require_outcome:
            return RecordCheck(
                ok=False,
                outcome="fail",
                reasons=[f"the session ended with gate outcome {observed!r}"],
                evidence=evidence,
            )

    if require_commit:
        commit = str(record.get("commit") or "")
        gate_commit = str(gate.get("commit") or "")
        if commit and gate_commit and commit != gate_commit:
            return RecordCheck(
                ok=False,
                outcome="escalate",
                reasons=[
                    "the record's commit differs from the gate's commit; "
                    "one of them is stale"
                ],
                evidence=evidence,
            )
        from .plane import repo_head_commit

        head = repo_head_commit(root)
        if head and commit and head != commit:
            return RecordCheck(
                ok=False,
                outcome="escalate",
                reasons=[
                    f"the record was written for commit {commit[:12]}, not "
                    f"{head[:12]}"
                ],
                evidence=evidence,
            )
        if head and not commit:
            return RecordCheck(
                ok=False,
                outcome="escalate",
                reasons=["the record has no commit; it cannot describe this code"],
                evidence=evidence,
            )

    drift: list[str] = []
    files = record.get("files") or {}
    if not isinstance(files, dict) or not files:
        evidence.append("files=0")
        reasons.append("the record observed no files")
    for relative, recorded in sorted(files.items()):
        current = _hash_file(root / str(relative)) or "absent"
        if current != recorded:
            drift.append(str(relative))
    if drift:
        evidence.append(f"drift={len(drift)}")
        return RecordCheck(
            ok=False,
            outcome="escalate",
            reasons=[
                "the workspace changed after the session ended: "
                + ", ".join(drift[:5])
            ],
            evidence=evidence,
        )
    if files:
        evidence.append(f"files={len(files)}")
    if reasons:
        return RecordCheck(ok=False, outcome="escalate", reasons=reasons, evidence=evidence)
    return RecordCheck(ok=True, reasons=[], evidence=evidence)
