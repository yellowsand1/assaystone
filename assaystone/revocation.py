"""A revocation list for signing keys.

Keys have no expiry and no identity system. The smallest honest addition is a
file: a committed list of key ids that must no longer be trusted, with a reason
and a date. Every Ed25519 artifact is checked against it.

A revoked key does not make a decision false; it makes the decision unable to
stand on its own. The gate escalates rather than failing, because the answer is
a human re-decision under a current key, not a red mark on a past run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = 1
FILENAME = "capability.revocations.json"


class RevocationError(ValueError):
    """The revocation list cannot be read or used."""


def revocation_path_for(source: str | Path | None) -> Path | None:
    if not source:
        return None
    path = Path(source)
    if not path.is_file():
        return None
    return path.parent / FILENAME


def load_revocations(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RevocationError(f"revocation list not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RevocationError(f"invalid revocation JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RevocationError("revocation list must be an object")
    return data


@dataclass
class RevocationCheck:
    ok: bool = True
    revoked: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def is_revoked(self, key_id: str | None) -> dict[str, Any] | None:
        if not key_id:
            return None
        return self.revoked.get(str(key_id))


def read_revocations(
    path: str | Path | None,
) -> RevocationCheck:
    if path is None or not Path(path).exists():
        return RevocationCheck(ok=True)
    try:
        data = load_revocations(path)
    except RevocationError as exc:
        return RevocationCheck(ok=False, errors=[str(exc)])
    errors: list[str] = []
    if data.get("version") != VERSION:
        errors.append(f"unsupported revocation version: {data.get('version')!r}")
    entries = data.get("revoked")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        errors.append("revoked must be a list")
        entries = []
    revoked: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"revocation {index}: not an object")
            continue
        key_id = str(entry.get("key_id") or "")
        if not key_id.startswith("sha256:"):
            errors.append(f"revocation {index}: key_id must look like sha256:<hex>")
            continue
        if not entry.get("reason"):
            errors.append(f"revocation {key_id}: no reason")
            continue
        revoked[key_id] = {
            "key_id": key_id,
            "reason": entry.get("reason"),
            "at": entry.get("at"),
            "by": entry.get("by"),
        }
    return RevocationCheck(ok=not errors, revoked=revoked, errors=errors)


def revocation_for(
    path: str | Path | None, key_id: str | None
) -> dict[str, Any] | None:
    return read_revocations(path).is_revoked(key_id)
