"""Ed25519 keys for receipts.

An HMAC receipt proves the signer held a shared key: the verifier needs the same
secret. An Ed25519 receipt lets the signer keep a private key and publish only
the public key, so a third party can verify a decision without being able to
make one.

``cryptography`` is an optional extra. Without it, Ed25519 functions raise a
clear error; the HMAC path is unaffected and the core stays dependency-free.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path


class SigningKeyError(ValueError):
    """An Ed25519 key cannot be generated, loaded, or used."""


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:
        raise SigningKeyError(
            "ed25519 needs the cryptography package (pip install assaystone[crypto])"
        ) from exc
    return ed25519, serialization, InvalidSignature


def generate(
    private_path: str | Path,
    public_path: str | Path,
    force: bool = False,
) -> tuple[Path, Path]:
    ed25519, serialization, _ = _crypto()
    private = Path(private_path)
    public = Path(public_path)
    if not force and (private.exists() or public.exists()):
        raise SigningKeyError(
            f"{private} or {public} exists; pass --force to overwrite"
        )
    key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private.parent.mkdir(parents=True, exist_ok=True)
    public.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        private, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    try:
        os.write(descriptor, private_bytes)
    finally:
        os.close(descriptor)
    public.write_bytes(public_bytes)
    return private, public


def load_private(path: str | Path):
    ed25519, serialization, _ = _crypto()
    try:
        data = Path(path).read_bytes()
        key = serialization.load_pem_private_key(data, password=None)
    except (OSError, ValueError) as exc:
        raise SigningKeyError(f"cannot read private key {path}: {exc}") from exc
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SigningKeyError(f"{path} is not an Ed25519 private key")
    return key


def load_public(path: str | Path):
    ed25519, serialization, _ = _crypto()
    try:
        data = Path(path).read_bytes()
        key = serialization.load_pem_public_key(data)
    except (OSError, ValueError) as exc:
        raise SigningKeyError(f"cannot read public key {path}: {exc}") from exc
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise SigningKeyError(f"{path} is not an Ed25519 public key")
    return key


def sign(body: bytes, private_path: str | Path) -> str:
    key = load_private(private_path)
    signature = key.sign(body)
    return "ed25519:" + base64.b64encode(signature).decode("ascii")


def verify(body: bytes, signature: str, public_path: str | Path) -> bool:
    _, _, invalid = _crypto()
    if not signature.startswith("ed25519:"):
        return False
    try:
        raw = base64.b64decode(signature.removeprefix("ed25519:"), validate=True)
    except ValueError:
        return False
    key = load_public(public_path)
    try:
        key.verify(raw, body)
    except invalid:
        return False
    return True
