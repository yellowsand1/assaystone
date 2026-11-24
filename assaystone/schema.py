"""Canonical, versioned JSON Schemas for Assaystone trace and contract JSON.

The schemas are pure data (no third-party runtime dependency) so editors and CI
can reference them directly. ``assaystone schema`` prints them; the test suite
validates the packaged demo traces/contracts against them with the standard
``jsonschema`` library.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# Bump when the shape of trace/contract JSON changes in a backwards-aware way.
SCHEMA_VERSION = "0.5.0"

TRACE_SCHEMA_NAME = "trace"
CONTRACT_SCHEMA_NAME = "contract"

_SCHEMA_FILES = {
    TRACE_SCHEMA_NAME: "trace.schema.json",
    CONTRACT_SCHEMA_NAME: "contract.schema.json",
}


class SchemaError(ValueError):
    """Raised when a schema name is unknown."""


def schema_path(name: str) -> Path:
    try:
        filename = _SCHEMA_FILES[name]
    except KeyError:
        raise SchemaError(
            f"unknown schema: {name!r} (choose from {sorted(_SCHEMA_FILES)})"
        ) from None
    return SCHEMA_DIR / filename


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def available_schemas() -> list[str]:
    return sorted(_SCHEMA_FILES)
