"""Data/report pack: schema, totals, and PII checks.

A third domain, deliberately not code: the artifact is a report, the oracle is
arithmetic and a shape, and the forbidden action is a data leak. The acceptance
language is the same.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..verifiers import Check, Verifier, VerifyContext, register

REPORT = "report.json"


def _load(ctx: VerifyContext, path: str = REPORT) -> dict[str, Any] | None:
    try:
        data = json.loads(ctx.current_text(path))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


@register
class DataSchema(Verifier):
    name = "data.schema"
    layer = "L0"
    cost_usd = 0.000005
    independence = "high"
    description = "report.json has the required fields and row shape."
    claim = "report.json has currency, total_cents, and rows with category and amount_cents."
    catches = ("schema-invalid",)
    blind_spots = (
        "a schema-valid report with wrong values",
        "fields outside the declared list",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        path = str(params.get("path") or REPORT)
        data = _load(ctx, path)
        if data is None:
            return False, [f"{path}: missing or invalid JSON"], []
        required = list(
            params.get("required") or ["currency", "total_cents", "rows"]
        )
        row_required = list(
            params.get("row_required") or ["category", "amount_cents"]
        )
        reasons = [f"missing field: {key}" for key in required if key not in data]
        rows = data.get("rows")
        if not isinstance(rows, list):
            reasons.append("rows is not a list")
        else:
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    reasons.append(f"row {index} is not an object")
                    continue
                for key in row_required:
                    if key not in row:
                        reasons.append(f"row {index}: missing {key}")
        return (
            not reasons,
            reasons,
            [f"checked {len(required)} field(s)"],
        )


@register
class DataTotals(Verifier):
    name = "data.totals"
    layer = "L0"
    cost_usd = 0.000005
    independence = "high"
    description = "The sum of row amounts equals total_cents."
    claim = "The sum of report rows equals total_cents."
    catches = ("totals-mismatch",)
    blind_spots = (
        "a consistent report computed from the wrong source",
        "rounding differences outside the tolerance",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        data = _load(ctx, str(params.get("path") or REPORT))
        if data is None:
            return None, ["report.json missing or invalid"], []
        rows = data.get("rows")
        total = data.get("total_cents")
        if not isinstance(rows, list) or not isinstance(total, int):
            return None, ["rows or total_cents is not usable"], []
        try:
            computed = sum(
                int(row.get("amount_cents", 0))
                for row in rows
                if isinstance(row, dict)
            )
        except (TypeError, ValueError):
            return None, ["row amount_cents is not an integer"], []
        tolerance = int(params.get("tolerance_cents", 0))
        if abs(computed - total) > tolerance:
            return (
                False,
                [f"rows sum to {computed}, total_cents is {total}"],
                [],
            )
        return True, [], [f"rows sum to {computed}"]


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


@register
class DataNoPii(Verifier):
    name = "data.no_pii"
    layer = "L1"
    cost_usd = 0.000005
    independence = "high"
    description = "Changed files must not add an email address or phone number."
    claim = "No changed file adds an email address or phone number."
    catches = ("pii-leak",)
    blind_spots = (
        "encoded or split PII",
        "PII in a format outside the patterns",
        "PII already present in the baseline",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        patterns = (("email", EMAIL), ("phone", PHONE))
        found: list[str] = []
        for path, change in ctx.changed():
            if change == "deleted":
                continue
            baseline = set((ctx.baseline_text(path) or "").splitlines())
            for line in set(ctx.current_text(path).splitlines()) - baseline:
                for name, pattern in patterns:
                    if pattern.search(line):
                        found.append(f"{path}: {name}")
                        break
        return (not found, found, [])
