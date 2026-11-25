"""Built-in domain verifier packs.

Importing this package registers every pack. The core runner stays
domain-agnostic; packs add verifiers only.
"""
from . import data, external, ops, research  # noqa: F401

__all__ = ["data", "external", "ops", "research"]
