"""Signed gate receipts.

A trail proves that a file was not edited in place. It does not prove who wrote
it: anyone who can write the file can rewrite the chain. A receipt is a small,
signed statement of one decision, bound to the commit, the manifest digest, and
the trail head. CI can require and verify it; a reviewer can check it without
reading the whole trail.

The signature is HMAC-SHA256 with a key held by the gate runner (normally CI).
That is a symmetric trust model: a verifier needs the same key. It proves the
decision came from a holder of the key, not that it is publicly verifiable. The
documentation states that limit; do not imply more.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .oracles import canonical_json

VERSION = 1
DEFAULT_KEY_ENV = "ASSAYSTONE_RECEIPT_KEY"


class ReceiptError(ValueError):
    """A receipt cannot be created or read."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def signature(body: dict[str, Any], key: str) -> str:
    payload = canonical_json(body).encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def _unsigned(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "signature"}


def create_receipt(
    gate: Any,
    root: str | Path,
    key: str,
    actor: str = "unknown",
    trail_path: str | Path | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Build and sign a receipt for one evaluated gate."""
    if not key:
        raise ReceiptError("a receipt needs a signing key")
    root = Path(root).resolve()
    head = ""
    entries = 0
    if trail_path is not None:
        from .trail import verify as verify_trail

        check = verify_trail(trail_path)
        if not check.ok:
            detail = check.errors[0] if check.errors else "unknown error"
            raise ReceiptError(
                f"refusing to sign a receipt for a broken trail: {detail}"
            )
        head = check.head
        entries = check.entries
    body: dict[str, Any] = {
        "version": VERSION,
        "capability": gate.capability,
        "stage": gate.stage,
        "outcome": gate.outcome,
        "merge_allowed": bool(gate.merge_allowed),
        "deploy_allowed": bool(gate.deploy_allowed),
        "commit": _git(root, "rev-parse", "HEAD"),
        "dirty": bool(
            _git(root, "status", "--porcelain", "--untracked-files=no")
        ),
        "manifest_digest": str(gate.manifest_digest or ""),
        "manifest_approval": dict(gate.manifest_approval or {}),
        "waived": list(gate.waived or []),
        "trail_head": head,
        "trail_entries": entries,
        "actor": actor,
        "at": at or _now(),
        "oracles": [
            {
                "id": item.oracle,
                "type": item.type,
                "outcome": item.outcome,
                "digest": item.digest,
                "fingerprint": item.fingerprint,
            }
            for item in gate.results
        ],
        "gap": [item["criterion"] for item in gate.gap],
        "prior": dict(gate.prior or {}),
        "rollback": str(gate.rollback or ""),
    }
    body["signature"] = signature(body, key)
    return body


@dataclass
class ReceiptCheck:
    ok: bool
    receipt: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "capability": self.receipt.get("capability"),
            "stage": self.receipt.get("stage"),
            "outcome": self.receipt.get("outcome"),
            "commit": self.receipt.get("commit"),
            "manifest_digest": self.receipt.get("manifest_digest"),
            "trail_head": self.receipt.get("trail_head"),
            "at": self.receipt.get("at"),
        }


def verify_receipt(
    receipt: dict[str, Any],
    key: str,
    expected_commit: str | None = None,
    expected_manifest_digest: str | None = None,
    expected_outcome: str | None = None,
) -> ReceiptCheck:
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ReceiptCheck(ok=False, errors=["receipt must be an object"])
    if receipt.get("version") != VERSION:
        errors.append(f"unsupported receipt version: {receipt.get('version')!r}")
    signature_value = str(receipt.get("signature") or "")
    if not signature_value.startswith("hmac-sha256:"):
        errors.append("missing or unknown signature")
    elif not key:
        errors.append("no verification key")
    else:
        expected = signature(_unsigned(receipt), key)
        if not hmac.compare_digest(signature_value, expected):
            errors.append("signature does not verify")
    if expected_commit is not None and receipt.get("commit") != expected_commit:
        errors.append(
            f"commit {receipt.get('commit')!r} != expected {expected_commit!r}"
        )
    if (
        expected_manifest_digest is not None
        and receipt.get("manifest_digest") != expected_manifest_digest
    ):
        errors.append("manifest digest does not match the expected value")
    if expected_outcome is not None and receipt.get("outcome") != expected_outcome:
        errors.append(
            f"outcome {receipt.get('outcome')!r} != expected {expected_outcome!r}"
        )
    return ReceiptCheck(ok=not errors, receipt=receipt, errors=errors)


def load_receipt(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReceiptError(f"receipt not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReceiptError(f"invalid receipt JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReceiptError("receipt must be an object")
    return data


def render_check(check: ReceiptCheck) -> str:
    lines = [
        f"receipt: {'valid' if check.ok else 'INVALID'}",
        f"capability: {check.receipt.get('capability', '-')}",
        f"stage: {check.receipt.get('stage', '-')}",
        f"outcome: {check.receipt.get('outcome', '-')}",
        f"commit: {check.receipt.get('commit') or '-'}",
        f"trail head: {check.receipt.get('trail_head') or '-'}",
    ]
    for error in check.errors:
        lines.append(f"  {error}")
    if check.ok:
        lines.append(
            "note: an HMAC receipt proves the signer held the key; it is not "
            "a public signature."
        )
    return "\n".join(lines)
