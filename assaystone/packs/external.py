"""Adapters for external verification tools.

These verifiers let a contract reuse tools that are already installed, without
making them a runtime dependency. If the tool is missing, the adapter escalates:
the absence of a check is not evidence that the work is acceptable.

The adapters are deliberately explicit about independence. ``external.pytest``
executes Python in the same workspace as the agent, so it shares the runtime
hijack surface and is only ``medium`` independence. ``external.ruff_debug_print``
is static analysis and does not execute the change, so it stays ``high``.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any

from ..verifiers import Check, Verifier, VerifyContext, register

_MISSING = (
    "No module named pytest",
    "No module named ruff",
    "No module named 'pytest'",
    "No module named 'ruff'",
)


def _output(proc: subprocess.CompletedProcess[str], limit: int = 15) -> str:
    text = (proc.stdout or "") + (proc.stderr or "")
    lines = text.strip().splitlines()
    return "\n".join(lines[-limit:]) if lines else "(no output)"


def _tool_missing(text: str) -> bool:
    return any(marker in text for marker in _MISSING)


@register
class ExternalPytest(Verifier):
    name = "external.pytest"
    layer = "L1"
    cost_usd = 0.003
    independence = "medium"
    description = "Run the repository's pytest suite, if pytest is installed."
    claim = "The repository's pytest suite passes in a clean workspace."
    catches = ("regression",)
    blind_spots = (
        "test-harness-hijack",
        "module-shadow",
        "under-tested-change",
        "test-specific-logic",
        "pytest is not installed",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        args = list(params.get("args") or ["-q"])
        timeout = float(params.get("timeout", 60))
        try:
            proc = ctx.workspace.run(
                [sys.executable, "-m", "pytest", *args], timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return None, ["pytest timed out"], []
        output = _output(proc)
        if _tool_missing(output):
            return None, ["pytest is not installed in this environment"], [output]
        if proc.returncode == 0:
            return True, [], [output]
        if proc.returncode == 1:
            return False, ["pytest failed (exit 1)"], [output]
        if proc.returncode == 5:
            return None, ["pytest collected no tests"], [output]
        return None, [f"pytest could not run (exit {proc.returncode})"], [output]


@register
class ExternalRuffDebugPrint(Verifier):
    name = "external.ruff_debug_print"
    layer = "L2"
    cost_usd = 0.0005
    independence = "high"
    description = "Run ruff's T201 rule (no print calls), if ruff is installed."
    claim = "Ruff's T201 rule reports no print() calls in the workspace."
    catches = ("debug-print",)
    blind_spots = (
        "debug output through logging or sys.stdout",
        "rules outside T201",
        "printed code inside an excluded path",
        "ruff is not installed",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        timeout = float(params.get("timeout", 30))
        try:
            proc = ctx.workspace.run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--select",
                    "T201",
                    "--no-cache",
                    ".",
                ],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None, ["ruff timed out"], []
        output = _output(proc)
        if _tool_missing(output):
            return None, ["ruff is not installed in this environment"], [output]
        if proc.returncode == 0:
            return True, [], ["ruff T201: no findings"]
        if proc.returncode == 1:
            return False, ["ruff T201: print() call found"], [output]
        return None, [f"ruff could not run (exit {proc.returncode})"], [output]
