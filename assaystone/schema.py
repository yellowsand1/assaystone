"""Canonical, versioned JSON Schemas for Assaystone trace and contract JSON.

The schemas are pure data (no third-party dependency) so editors and CI can
reference them directly. ``assaystone schema`` prints them and validates
documents against them using a tiny self-contained validator that covers the
subset of JSON Schema the Assaystone documents rely on.
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
    """Raised when a document does not validate against a schema."""


def schema_path(name: str) -> Path:
    try:
        filename = _SCHEMA_FILES[name]
    except KeyError:
        raise SchemaError(f"unknown schema: {name!r} (choose from {sorted(_SCHEMA_FILES)})")
    return SCHEMA_DIR / filename


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def available_schemas() -> list[str]:
    return sorted(_SCHEMA_FILES)


# ---------------------------------------------------------------------------
# Minimal JSON Schema validator (draft 2020-12 subset).
#
# Supports exactly the keywords used by the bundled schemas: ``$schema``,
# ``$id``, ``title``, ``description``, ``type``, ``required``, ``properties``,
# ``additionalProperties``, ``items``, ``enum``, ``const``, ``anyOf``,
# ``oneOf``, ``minimum``, ``maxLength``, ``minItems``, ``$ref`` (local refs
# within the same document only). Unknown keywords are ignored, which keeps the
# validator forward-compatible with richer editor tooling.
# ---------------------------------------------------------------------------

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#"):
        raise SchemaError(f"only local $ref is supported: {ref!r}")
    node: Any = root
    pointer = ref[1:].lstrip("/")
    if pointer:
        for token in pointer.split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                node = node[int(token)]
            else:
                node = node[token]
    if not isinstance(node, dict):
        raise SchemaError(f"$ref did not resolve to an object: {ref!r}")
    return node


def _type_matches(value: Any, type_name: str) -> bool:
    check = _TYPE_CHECKS.get(type_name)
    if check is None:
        raise SchemaError(f"unsupported type in schema: {type_name!r}")
    return check(value)


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []

    if "$ref" in schema:
        errors.extend(_validate(value, _resolve_ref(root, schema["$ref"]), root, path))
        return errors

    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_type_matches(value, t) for t in types):
            errors.append(f"{path}: expected type {'/'.join(types)}, got {type(value).__name__}")
            return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")

    if isinstance(value, str):
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            errors.append(f"{path}: string longer than {max_length} characters")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: {value} is less than minimum {minimum}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in value:
                errors.extend(_validate(value[key], subschema, root, f"{path}.{key}"))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")
        elif isinstance(additional, dict):
            for key in value:
                if key not in properties:
                    errors.extend(_validate(value[key], additional, root, f"{path}.{key}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: expected at least {min_items} items, got {len(value)}")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(_validate(item, items, root, f"{path}[{index}]"))

    if "anyOf" in schema:
        if not any(not _validate(value, option, root, path) for option in schema["anyOf"]):
            errors.append(f"{path}: value does not match any allowed schema in anyOf")

    if "oneOf" in schema:
        matches = sum(1 for option in schema["oneOf"] if not _validate(value, option, root, path))
        if matches != 1:
            errors.append(f"{path}: value matched {matches} schemas in oneOf (expected exactly 1)")

    return errors


def validate_document(document: Any, name: str) -> list[str]:
    """Return a list of human-readable validation errors (empty when valid)."""
    schema = load_schema(name)
    return _validate(document, schema, schema, "$")