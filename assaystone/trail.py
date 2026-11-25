"""Hash-chained audit trail for gate decisions.

Each entry names the capability, stage, actor, outcome, the digest of every
oracle it ran, and the declared criteria the stage did not gate. Entries are
linked by hash, so editing or deleting one breaks the chain and ``verify``
reports where.

What this does **not** prove, and the documentation says so:

* authenticity — whoever can write the file can rewrite the whole chain;
* freshness — truncating the tail leaves a valid chain.

Both are addressed by anchoring the head hash somewhere the writer does not
control (a CI log, a signed git commit, a transparency log) and passing it to
``verify(..., expected_head=...)``.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .oracles import canonical_json

GENESIS = "sha256:" + "0" * 64


class TrailError(ValueError):
    """The trail cannot be written or read."""


def _entry_hash(entry: dict[str, Any]) -> str:
    body = {key: value for key, value in entry.items() if key != "hash"}
    return "sha256:" + hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_for(
    gate: Any,
    actor: str,
    at: str | None = None,
    prev: str = GENESIS,
    seq: int = 0,
) -> dict[str, Any]:
    """Build an unsigned trail entry from a ``GateResult``."""
    entry: dict[str, Any] = {
        "seq": seq,
        "at": at or _now(),
        "capability": gate.capability,
        "stage": gate.stage,
        "outcome": gate.outcome,
        "actor": actor,
        "merge_allowed": gate.merge_allowed,
        "deploy_allowed": gate.deploy_allowed,
        "rollback_required": bool(getattr(gate, "rollback_required", False)),
        "rollback": str(getattr(gate, "rollback", "") or ""),
        "manifest_lifecycle": str(
            getattr(gate, "manifest_lifecycle", "") or ""
        ),
        "oracles": [
            {
                "id": item.oracle,
                "type": item.type,
                "outcome": item.outcome,
                "digest": item.digest,
                "ref": item.ref,
                "version": item.version,
                "fingerprint": item.fingerprint,
            }
            for item in gate.results
        ],
        "missing": list(gate.missing),
        "gap": [item["criterion"] for item in gate.gap],
        "strict": bool(getattr(gate, "strict", False)),
        "prev": prev,
    }
    entry["hash"] = _entry_hash(entry)
    return entry


def read(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(
        file_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TrailError(f"line {number}: invalid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise TrailError(f"line {number}: entry must be an object")
        entries.append(entry)
    return entries


def append(
    path: str | Path,
    gate: Any,
    actor: str = "unknown",
    at: str | None = None,
) -> dict[str, Any]:
    file_path = Path(path)
    entries = read(file_path)
    if entries:
        check = verify(file_path)
        if not check.ok:
            raise TrailError(
                "refusing to append to a broken trail: "
                + "; ".join(check.errors[:3])
            )
        last = entries[-1]
        prev = str(last.get("hash") or "")
        seq = int(last.get("seq", len(entries) - 1)) + 1
    else:
        prev = GENESIS
        seq = 0
    entry = entry_for(gate, actor=actor, at=at, prev=prev, seq=seq)
    line = canonical_json(entry) + "\n"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        file_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
    )
    try:
        os.write(descriptor, line.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return entry


@dataclass
class TrailCheck:
    path: str
    ok: bool
    entries: int = 0
    head: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "entries": self.entries,
            "head": self.head,
            "errors": list(self.errors),
        }


def verify(path: str | Path, expected_head: str | None = None) -> TrailCheck:
    file_path = Path(path)
    if not file_path.exists():
        return TrailCheck(path=str(path), ok=False, errors=["trail not found"])
    try:
        entries = read(file_path)
    except TrailError as exc:
        return TrailCheck(path=str(path), ok=False, errors=[str(exc)])
    if not entries:
        return TrailCheck(path=str(path), ok=False, errors=["trail is empty"])
    errors: list[str] = []
    prev = GENESIS
    for index, entry in enumerate(entries):
        missing = [
            key
            for key in ("seq", "at", "capability", "stage", "outcome", "hash")
            if key not in entry
        ]
        if missing:
            errors.append(f"entry {index}: missing {', '.join(missing)}")
            continue
        if entry.get("seq") != index:
            errors.append(
                f"entry {index}: seq {entry.get('seq')!r} != position {index}"
            )
        if entry.get("prev") != prev:
            errors.append(
                f"entry {index}: prev does not match entry {index - 1}"
            )
        actual = _entry_hash(entry)
        if entry.get("hash") != actual:
            errors.append(f"entry {index}: hash mismatch (entry was modified)")
        prev = str(entry.get("hash") or "")
    head = str(entries[-1].get("hash") or "")
    if expected_head and head != expected_head:
        errors.append("head hash does not match the anchored value")
    return TrailCheck(
        path=str(path),
        ok=not errors,
        entries=len(entries),
        head=head,
        errors=errors,
    )


def render_check(check: TrailCheck) -> str:
    lines = [
        f"trail: {check.path}",
        f"entries: {check.entries}",
        f"head: {check.head or '-'}",
        f"chain: {'intact' if check.ok else 'BROKEN'}",
    ]
    for error in check.errors:
        lines.append(f"  {error}")
    if check.ok:
        lines.append(
            "note: a local chain proves integrity, not authenticity; anchor "
            "the head hash externally (CI log, signed commit, transparency log)."
        )
    return "\n".join(lines)
