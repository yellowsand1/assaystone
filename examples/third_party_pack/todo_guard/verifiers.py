"""A verifier implemented outside the Assaystone package.

This is the shape a third party publishes: one class, one entry point, the six
ABI fields, and no dependency beyond Assaystone's public API. The verifier is
deliberately small; the point is the contract with the scorecard, not the check.
"""
from __future__ import annotations

from typing import Any

from assaystone.verifiers import Check, Verifier, VerifyContext, register

MARKERS = ("TODO", "FIXME", "XXX")


@register
class NoNewTodo(Verifier):
    name = "example.no_new_todo"
    layer = "L2"
    cost_usd = 0.00001
    independence = "high"
    description = "Changed Python files must not add new TODO/FIXME markers."
    claim = "No changed Python file adds a new TODO, FIXME, or XXX marker."
    catches = ("new-todo",)
    blind_spots = (
        "markers added to non-Python files",
        "a marker split across lines",
        "a marker added in a file the contract does not include",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        markers = tuple(params.get("markers") or MARKERS)
        allowed = int(params.get("allowed_new", 0))
        added: list[str] = []
        checked = 0
        for path, change in ctx.changed():
            if change == "deleted" or not path.endswith(".py"):
                continue
            checked += 1
            baseline = set((ctx.baseline_text(path) or "").splitlines())
            for line in set(ctx.current_text(path).splitlines()) - baseline:
                if any(marker in line for marker in markers):
                    added.append(f"{path}: {line.strip()}")
        reasons = [f"new marker: {item}" for item in added]
        if len(added) <= allowed:
            return True, [], [f"checked {checked} Python file(s)"]
        return False, reasons, [f"checked {checked} Python file(s)"]
