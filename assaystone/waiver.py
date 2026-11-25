"""Owner-signed exceptions for specific criteria.

A strict gate with no exception path gets bypassed. A waiver is the auditable
alternative: the owner accepts one named criterion, for a stated reason, until a
date, under the exact manifest digest that was reviewed. It never turns an
unknown into a pass and never covers an escalation; it can only accept a known
failure.

The waiver key is the owner key, separate from the receipt key. An expired,
forged, or digest-mismatched waiver is not valid.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import keys
from .plane import CapabilityManifest, manifest_digest

VERSION = 1
FILENAME = "capability.waivers.json"


class WaiverError(ValueError):
    """A waiver cannot be created, read, or verified."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def waiver_path_for(manifest: CapabilityManifest) -> Path | None:
    if not manifest.source:
        return None
    source = Path(manifest.source)
    if not source.is_file():
        return None
    return source.parent / FILENAME


def _unsigned(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "signature"}


def _body(
    manifest: CapabilityManifest,
    criterion: str,
    reason: str,
    approved_by: str,
    expires_at: str,
    at: str | None,
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "capability": manifest.capability,
        "manifest_digest": manifest_digest(manifest),
        "criterion": criterion,
        "reason": reason,
        "approved_by": approved_by,
        "at": at or _now(),
        "expires_at": expires_at,
    }


def create_waiver(
    manifest: CapabilityManifest,
    criterion: str,
    reason: str,
    approved_by: str,
    key: str = "",
    expires_at: str = "",
    at: str | None = None,
    private_key_path: str | Path | None = None,
) -> dict[str, Any]:
    if not manifest.waivers:
        raise WaiverError("the manifest does not declare waivers: true")
    if not key and not private_key_path:
        raise WaiverError("a waiver needs a signing key")
    if criterion not in {item.id for item in manifest.criteria}:
        raise WaiverError(f"unknown criterion: {criterion!r}")
    if not reason.strip():
        raise WaiverError("a waiver needs a reason")
    try:
        date.fromisoformat(expires_at)
    except ValueError as exc:
        raise WaiverError("expires_at must be YYYY-MM-DD") from exc
    body = _body(
        manifest, criterion, reason.strip(), approved_by, expires_at, at
    )
    if private_key_path:
        try:
            body["key_id"] = keys.key_id_for_private(private_key_path)
        except keys.SigningKeyError as exc:
            raise WaiverError(str(exc)) from exc
    try:
        body["signature"] = keys.sign_body(body, key, private_key_path)
    except keys.SigningKeyError as exc:
        raise WaiverError(str(exc)) from exc
    return body


def load_waivers(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WaiverError(f"waiver file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WaiverError(f"invalid waiver JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WaiverError("waiver file must be an object")
    return data


@dataclass
class WaiverCheck:
    ok: bool
    valid: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def verify_waivers(
    data: dict[str, Any],
    key: str = "",
    manifest: CapabilityManifest | None = None,
    today: date | None = None,
    public_key_path: str | Path | None = None,
) -> WaiverCheck:
    errors: list[str] = []
    if data.get("version") != VERSION:
        errors.append(f"unsupported waiver version: {data.get('version')!r}")
    if manifest is None:
        errors.append("no manifest to verify against")
        manifest = None
    else:
        if data.get("capability") != manifest.capability:
            errors.append(
                f"waivers are for {data.get('capability')!r}, "
                f"not {manifest.capability!r}"
            )
        current = manifest_digest(manifest)
        if data.get("manifest_digest") != current:
            errors.append("waivers do not match the current manifest digest")
    entries = data.get("waivers")
    if not isinstance(entries, list) or not entries:
        errors.append("waiver file has no entries")
        entries = []
    known = {item.id for item in manifest.criteria} if manifest else set()
    valid: dict[str, dict[str, Any]] = {}
    today = today or datetime.now(timezone.utc).date()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"waiver {index}: not an object")
            continue
        criterion = str(entry.get("criterion") or "")
        if criterion not in known:
            errors.append(f"waiver {index}: unknown criterion {criterion!r}")
            continue
        if criterion in valid:
            errors.append(f"waiver {index}: duplicate criterion {criterion!r}")
            continue
        if not entry.get("reason"):
            errors.append(f"waiver {criterion}: no reason")
            continue
        if not entry.get("approved_by"):
            errors.append(f"waiver {criterion}: no approver")
            continue
        try:
            expires = date.fromisoformat(str(entry.get("expires_at") or ""))
        except ValueError:
            errors.append(f"waiver {criterion}: invalid expires_at")
            continue
        if expires < today:
            errors.append(
                f"waiver {criterion}: expired on {expires.isoformat()}"
            )
            continue
        value = str(entry.get("signature") or "")
        error = keys.verify_body(
            _unsigned(entry),
            value,
            key,
            public_key_path=public_key_path,
        )
        if error:
            errors.append(f"waiver {criterion}: {error}")
            continue
        if (
            str(value).startswith("ed25519:")
            and entry.get("key_id")
            and public_key_path
        ):
            try:
                actual = keys.key_id(public_key_path)
            except keys.SigningKeyError as exc:
                errors.append(f"waiver {criterion}: {exc}")
                continue
            if actual != entry.get("key_id"):
                errors.append(
                    f"waiver {criterion}: public key does not match key_id"
                )
                continue
        valid[criterion] = {
            "criterion": criterion,
            "reason": entry.get("reason"),
            "approved_by": entry.get("approved_by"),
            "at": entry.get("at"),
            "expires_at": entry.get("expires_at"),
            "key_id": entry.get("key_id"),
        }
    # One bad entry makes the whole file untrusted. A partial waiver set after a
    # failed verification is not evidence.
    if errors:
        return WaiverCheck(ok=False, valid={}, errors=errors)
    return WaiverCheck(ok=True, valid=valid)
