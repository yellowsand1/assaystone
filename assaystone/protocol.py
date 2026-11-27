"""The Assaystone verifier protocol, version 1.

The protocol is deliberately small. It defines what a verifier must declare,
what a verdict may say, and what an acceptance contract may contain. The goal
is that a verifier written in another language can be judged by the same
scorecard as the built-in ones.

A verifier that cannot answer ``blind_spots`` is not a verifier; it is an
oracle claim. The schema makes that answer mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import packs as _packs  # noqa: F401 - registers built-in domain packs
from .contract import CRITERION_KINDS, ON_UNKNOWN, SEVERITIES, Contract
from .verifiers import REGISTRY

PROTOCOL_VERSION = "1"
LAYERS = ["L0", "L1", "L2", "L3", "L4"]
INDEPENDENCE = ["high", "medium", "low"]

CONTRACT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://assaystone.dev/protocol/v1/contract.schema.json",
    "title": "Assaystone acceptance contract v1",
    "type": "object",
    "required": ["name", "verifiers"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "test_command": {"type": "array", "items": {"type": "string"}},
        "fail_fast": {"type": "boolean"},
        "human_review_cost_usd": {"type": "number", "minimum": 0},
        "max_verification_cost_usd": {"type": "number", "minimum": 0},
        "required_defects": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "domain": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {"$ref": "#/$defs/criterion"},
        },
        "verifiers": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/verifierSpec"},
        },
    },
    "$defs": {
        "criterion": {
            "type": "object",
            "required": ["id", "kind", "statement", "defect"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "kind": {"enum": list(CRITERION_KINDS)},
                "statement": {"type": "string", "minLength": 1},
                "defect": {"type": "string", "minLength": 1},
                "verifiers": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
                "severity": {"enum": list(SEVERITIES)},
                "on_unknown": {"enum": list(ON_UNKNOWN)},
            },
        },
        "verifierSpec": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "required": {"type": "boolean"},
                "params": {"type": "object"},
            },
        }
    },
}

VERIFIER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://assaystone.dev/protocol/v1/verifier.schema.json",
    "title": "Assaystone verifier manifest v1",
    "type": "object",
    "required": [
        "name",
        "version",
        "layer",
        "independence",
        "claim",
        "catches",
        "blind_spots",
        "cost",
    ],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "layer": {"enum": list(LAYERS)},
        "independence": {"enum": list(INDEPENDENCE)},
        "claim": {"type": "string", "minLength": 1},
        "catches": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "blind_spots": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "trusts": {
            "type": "array",
            "items": {
                "enum": [
                    "baseline",
                    "artifacts",
                    "trace",
                    "evidence",
                    "workspace",
                ]
            },
            "uniqueItems": True,
        },
        "cost": {
            "type": "object",
            "required": ["usd"],
            "additionalProperties": False,
            "properties": {
                "usd": {"type": "number", "minimum": 0},
                "ms": {"type": "number", "minimum": 0},
            },
        },
        "description": {"type": "string"},
        "params": {"type": "object"},
    },
}

VERDICT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://assaystone.dev/protocol/v1/verdict.schema.json",
    "title": "Assaystone verdict v1",
    "type": "object",
    "required": ["verifier", "layer", "outcome", "independence"],
    "additionalProperties": False,
    "properties": {
        "verifier": {"type": "string", "minLength": 1},
        "layer": {"enum": list(LAYERS)},
        "outcome": {"enum": ["pass", "fail", "escalate"]},
        "independence": {"enum": list(INDEPENDENCE)},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "cost_usd": {"type": "number", "minimum": 0},
        "duration_ms": {"type": "number", "minimum": 0},
    },
}

SCHEMAS = {
    "contract": CONTRACT_SCHEMA,
    "verifier": VERIFIER_SCHEMA,
    "verdict": VERDICT_SCHEMA,
}


@dataclass
class ContractCheck:
    contract: str
    violations: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "ok": self.ok,
            "violations": list(self.violations),
        }


def _conforms(cls: type) -> bool:
    return bool(
        cls.claim
        and cls.catches
        and cls.blind_spots
        and cls.trusts
        and cls.independence in INDEPENDENCE
        and cls.layer in LAYERS
    )


def describe_verifiers() -> list[dict[str, Any]]:
    """Return the machine-readable manifest of every registered verifier."""
    out: list[dict[str, Any]] = []
    for name in sorted(REGISTRY):
        cls = REGISTRY[name]
        out.append(
            {
                "name": cls.name,
                "version": PROTOCOL_VERSION,
                "layer": cls.layer,
                "independence": cls.independence,
                "claim": cls.claim,
                "catches": list(cls.catches),
                "blind_spots": list(cls.blind_spots),
                "trusts": list(cls.trusts),
                "cost": {"usd": cls.cost_usd},
                "description": cls.description,
                "builtin": cls.__module__.startswith("assaystone"),
                "conformant": _conforms(cls),
            }
        )
    return out


def describe_protocol() -> dict[str, Any]:
    verifiers = describe_verifiers()
    return {
        "protocol": "assaystone-verifier",
        "version": PROTOCOL_VERSION,
        "layers": list(LAYERS),
        "independence_levels": list(INDEPENDENCE),
        "outcomes": ["pass", "fail", "escalate"],
        "schemas": {name: schema["$id"] for name, schema in SCHEMAS.items()},
        "verifiers": verifiers,
        "conformant": sum(1 for item in verifiers if item["conformant"]),
        "nonconformant": [
            item["name"] for item in verifiers if not item["conformant"]
        ],
    }


MANIFEST_FIELDS = (
    "name",
    "version",
    "layer",
    "independence",
    "claim",
    "catches",
    "blind_spots",
    "cost",
)


def check_manifest(data: dict[str, Any]) -> list[str]:
    """Validate a verifier manifest without a full JSON Schema engine."""
    violations: list[str] = []
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]

    for field_name in MANIFEST_FIELDS:
        if field_name not in data:
            violations.append(f"missing field: {field_name}")

    if "name" in data and not str(data["name"]).strip():
        violations.append("name is empty")
    if "version" in data and not str(data["version"]).strip():
        violations.append("version is empty")
    if "layer" in data and data["layer"] not in LAYERS:
        violations.append(
            f"layer {data['layer']!r} is not one of {', '.join(LAYERS)}"
        )
    if "independence" in data and data["independence"] not in INDEPENDENCE:
        violations.append(
            f"independence {data['independence']!r} is not one of "
            f"{', '.join(INDEPENDENCE)}"
        )
    if "claim" in data and not str(data["claim"]).strip():
        violations.append("claim is empty")
    for list_field in ("catches", "blind_spots"):
        value = data.get(list_field)
        if value is None:
            continue
        if not isinstance(value, list) or not value:
            violations.append(f"{list_field} must be a non-empty array")
        elif any(not str(item).strip() for item in value):
            violations.append(f"{list_field} contains an empty tag")

    cost = data.get("cost")
    if cost is not None:
        if not isinstance(cost, dict):
            violations.append("cost must be an object")
        else:
            if "usd" not in cost:
                violations.append("cost.usd is required")
            elif not isinstance(cost["usd"], (int, float)) or cost["usd"] < 0:
                violations.append("cost.usd must be a non-negative number")
    return violations


def check_contract(contract: Contract) -> ContractCheck:
    """Check a contract against the protocol, without a full JSON Schema engine."""
    violations: list[str] = []
    if not contract.name.strip():
        violations.append("contract name is empty")
    if not contract.verifiers:
        violations.append("contract has no verifiers")

    seen: set[str] = set()
    for spec in contract.verifiers:
        if spec.name in seen:
            violations.append(f"duplicate verifier in contract: {spec.name}")
        seen.add(spec.name)
        if spec.name not in REGISTRY:
            violations.append(f"unknown verifier: {spec.name}")

    contract_names = {spec.name for spec in contract.verifiers}
    seen_criteria: set[str] = set()
    for criterion in contract.criteria:
        if criterion.id in seen_criteria:
            violations.append(f"duplicate criterion id: {criterion.id}")
        seen_criteria.add(criterion.id)
        if criterion.kind not in CRITERION_KINDS:
            violations.append(
                f"criterion {criterion.id}: unknown kind {criterion.kind!r}"
            )
        if criterion.severity not in SEVERITIES:
            violations.append(
                f"criterion {criterion.id}: unknown severity "
                f"{criterion.severity!r}"
            )
        if criterion.on_unknown not in ON_UNKNOWN:
            violations.append(
                f"criterion {criterion.id}: unknown on_unknown "
                f"{criterion.on_unknown!r}"
            )
        if not criterion.statement.strip():
            violations.append(f"criterion {criterion.id}: empty statement")
        if criterion.defect not in contract.required_defects:
            violations.append(
                f"criterion {criterion.id}: defect {criterion.defect!r} "
                "is not in required_defects"
            )
        for name in criterion.verifiers:
            if name not in REGISTRY:
                violations.append(
                    f"criterion {criterion.id}: unknown verifier {name!r}"
                )
            elif name not in contract_names:
                violations.append(
                    f"criterion {criterion.id}: {name!r} is not in the "
                    "contract's verifiers"
                )

    if len(set(contract.required_defects)) != len(contract.required_defects):
        violations.append("required_defects contains duplicates")

    for tag in contract.required_defects:
        if not tag.strip():
            violations.append("required_defects contains an empty tag")

    for spec in contract.verifiers:
        cls = REGISTRY.get(spec.name)
        if cls is None:
            continue
        if cls.independence not in INDEPENDENCE:
            violations.append(
                f"{cls.name}: independence {cls.independence!r} is not one of "
                f"{', '.join(INDEPENDENCE)}"
            )
        if cls.layer not in LAYERS:
            violations.append(
                f"{cls.name}: layer {cls.layer!r} is not one of {', '.join(LAYERS)}"
            )
        if not cls.claim.strip():
            violations.append(f"{cls.name}: missing claim")
        if not cls.catches:
            violations.append(f"{cls.name}: catches is empty")
        if not cls.blind_spots:
            violations.append(f"{cls.name}: blind_spots is empty")
    return ContractCheck(contract=contract.name, violations=violations)


def render_protocol() -> str:
    description = describe_protocol()
    lines = [
        f"# Assaystone verifier protocol v{description['version']}",
        "",
        f"Verifiers: **{len(description['verifiers'])}**",
        f"Layers: {', '.join(description['layers'])}",
        f"Independence levels: {', '.join(description['independence_levels'])}",
        f"Outcomes: {', '.join(description['outcomes'])}",
        "",
        "| verifier | layer | independence | cost | claim |",
        "|---|---|---|---|---|",
    ]
    for item in description["verifiers"]:
        lines.append(
            f"| `{item['name']}` | {item['layer']} | {item['independence']} | "
            f"${item['cost']['usd']:.6f} | {item['claim']} |"
        )
    lines.append("")
    lines.append("## Declared blind spots")
    lines.append("")
    for item in description["verifiers"]:
        if item["blind_spots"]:
            lines.append(
                f"- `{item['name']}`: "
                + ", ".join(f"`{tag}`" for tag in item["blind_spots"])
            )
    lines.append("")
    return "\n".join(lines)


def write_schemas(directory: str) -> list[str]:
    import json
    from pathlib import Path

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, schema in SCHEMAS.items():
        path = target / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written.append(str(path))
    return written
