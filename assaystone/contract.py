"""Acceptance contracts: ordered verifier sets, budgets, and escalation policy."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]


@dataclass
class VerifierSpec:
    name: str
    required: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Contract:
    name: str
    verifiers: list[VerifierSpec]
    test_command: list[str] = field(default_factory=lambda: list(DEFAULT_TEST_COMMAND))
    fail_fast: bool = True
    human_review_cost_usd: float = 6.0
    max_verification_cost_usd: float = 0.05
    # Defect tags this contract is expected to cover. Coverage is a claim
    # about a contract, so the requirement has to be stated, not inferred.
    required_defects: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Contract":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), source=str(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "contract") -> "Contract":
        specs = [
            VerifierSpec(
                name=item["name"],
                required=bool(item.get("required", True)),
                params=dict(item.get("params") or {}),
            )
            for item in data.get("verifiers", [])
        ]
        if not specs:
            raise ValueError(f"contract has no verifiers: {source}")
        return cls(
            name=data.get("name", "contract"),
            verifiers=specs,
            test_command=list(data.get("test_command") or DEFAULT_TEST_COMMAND),
            fail_fast=bool(data.get("fail_fast", True)),
            human_review_cost_usd=float(data.get("human_review_cost_usd", 6.0)),
            max_verification_cost_usd=float(data.get("max_verification_cost_usd", 0.05)),
            required_defects=[str(tag) for tag in data.get("required_defects") or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "test_command": self.test_command,
            "fail_fast": self.fail_fast,
            "human_review_cost_usd": self.human_review_cost_usd,
            "max_verification_cost_usd": self.max_verification_cost_usd,
            "required_defects": list(self.required_defects),
            "verifiers": [
                {
                    "name": spec.name,
                    "required": spec.required,
                    "params": spec.params,
                }
                for spec in self.verifiers
            ],
        }
