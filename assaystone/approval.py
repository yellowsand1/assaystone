"""Owner approval for the acceptance criteria.

A gate decides against a manifest. If the agent can rewrite the manifest, the
gate is only as trustworthy as the agent's willingness to keep its own rules.
The owner signs a digest of the manifest with a key that is separate from the
gate runner's receipt key, so "who defined acceptable" and "who executed the
check" are two different signers.

Like receipts, this is HMAC: it proves the signer held the key, not public
verifiability. The owner key belongs to the owner, not to CI and not to the
agent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import keys
from .plane import CapabilityManifest, manifest_digest

VERSION = 1
DEFAULT_OWNER_KEY_ENV = "ASSAYSTONE_OWNER_KEY"
APPROVAL_FILENAME = "capability.approval.json"


class ApprovalError(ValueError):
    """An approval cannot be created, read, or verified."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def approval_path_for(manifest: CapabilityManifest) -> Path | None:
    """Default approval file next to the manifest, when its source is known."""
    if not manifest.source:
        return None
    source = Path(manifest.source)
    if not source.is_file():
        return None
    return source.parent / APPROVAL_FILENAME


def _unsigned(approval: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in approval.items() if key != "signature"}


def create_approval(
    manifest: CapabilityManifest,
    approver: str,
    key: str = "",
    at: str | None = None,
    private_key_path: str | Path | None = None,
) -> dict[str, Any]:
    if not key and not private_key_path:
        raise ApprovalError("an owner approval needs a signing key")
    if not manifest.manifest_approval:
        raise ApprovalError(
            "the manifest does not declare manifest_approval: true"
        )
    body: dict[str, Any] = {
        "version": VERSION,
        "capability": manifest.capability,
        "manifest_digest": manifest_digest(manifest),
        "approved_by": approver,
        "at": at or _now(),
    }
    if private_key_path:
        try:
            body["key_id"] = keys.key_id_for_private(private_key_path)
        except keys.SigningKeyError as exc:
            raise ApprovalError(str(exc)) from exc
    try:
        body["signature"] = keys.sign_body(body, key, private_key_path)
    except keys.SigningKeyError as exc:
        raise ApprovalError(str(exc)) from exc
    return body


@dataclass
class ApprovalCheck:
    ok: bool
    info: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def load_approval(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApprovalError(f"approval not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ApprovalError(f"invalid approval JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ApprovalError("approval must be an object")
    return data


def verify_approval(
    approval: dict[str, Any],
    key: str = "",
    manifest: CapabilityManifest | None = None,
    public_key_path: str | Path | None = None,
) -> ApprovalCheck:
    errors: list[str] = []
    info = {
        "approved_by": approval.get("approved_by"),
        "at": approval.get("at"),
        "manifest_digest": approval.get("manifest_digest"),
        "required": True,
        "verified": False,
        "scheme": (
            "ed25519"
            if str(approval.get("signature") or "").startswith("ed25519:")
            else "hmac-sha256"
        ),
        "key_id": approval.get("key_id"),
    }
    if approval.get("version") != VERSION:
        errors.append(f"unsupported approval version: {approval.get('version')!r}")
    if manifest is None:
        errors.append("no manifest to verify against")
    else:
        if approval.get("capability") != manifest.capability:
            errors.append(
                f"approval is for {approval.get('capability')!r}, "
                f"not {manifest.capability!r}"
            )
        current = manifest_digest(manifest)
        if approval.get("manifest_digest") != current:
            errors.append("approval does not match the current manifest digest")
    value = str(approval.get("signature") or "")
    error = keys.verify_body(
        _unsigned(approval),
        value,
        key,
        public_key_path=public_key_path,
    )
    if error:
        errors.append(f"approval {error}")
    elif (
        info["scheme"] == "ed25519"
        and approval.get("key_id")
        and public_key_path
    ):
        try:
            actual = keys.key_id(public_key_path)
        except keys.SigningKeyError as exc:
            errors.append(str(exc))
        else:
            if actual != approval.get("key_id"):
                errors.append("approval public key does not match key_id")
    info["verified"] = not errors
    return ApprovalCheck(ok=not errors, info=info, errors=errors)


def render_check(check: ApprovalCheck) -> str:
    lines = [
        f"approval: {'valid' if check.ok else 'INVALID'}",
        f"approved by: {check.info.get('approved_by') or '-'}",
        f"at: {check.info.get('at') or '-'}",
        f"manifest: {check.info.get('manifest_digest') or '-'}",
    ]
    for error in check.errors:
        lines.append(f"  {error}")
    if check.ok:
        lines.append(
            "note: the owner key proves the signer held it; keep it apart from "
            "the receipt key and the agent."
        )
    return "\n".join(lines)
