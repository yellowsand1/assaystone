"""Built-in domain verifier packs.

Importing this package registers every pack. The core runner stays
domain-agnostic; packs add verifiers only.
"""
from . import external, ops  # noqa: F401

__all__ = ["external", "ops"]
