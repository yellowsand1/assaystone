"""A second outside-the-package verifier: no new secrets in changed files.

This pack exists to prove that the protocol is not shaped around the built-in
checks. It is deterministic, has an explicit pattern list, and declares the
blind spots that a regex-based check always has.
"""
from __future__ import annotations

import re
from typing import Any

from assaystone.verifiers import Check, Verifier, VerifyContext, register

PATTERNS = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github-token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "password-assignment",
        re.compile(r"(?i)\bpassword\s*=\s*[\"'][^\"']{4,}[\"']"),
    ),
)


@register
class NoNewSecrets(Verifier):
    name = "example.no_new_secrets"
    layer = "L2"
    cost_usd = 0.00001
    independence = "high"
    description = "Changed files must not add lines matching a declared secret pattern."
    claim = "No changed file adds a line matching a declared secret pattern."
    catches = ("secret-leak",)
    blind_spots = (
        "encoded or split secrets",
        "secrets already present in the baseline",
        "a secret format not in the pattern list",
    )

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        patterns = PATTERNS
        found: list[str] = []
        checked = 0
        for path, change in ctx.changed():
            if change == "deleted":
                continue
            checked += 1
            baseline = set((ctx.baseline_text(path) or "").splitlines())
            for line in set(ctx.current_text(path).splitlines()) - baseline:
                for name, pattern in patterns:
                    if pattern.search(line):
                        found.append(f"{path}: {name}")
                        break
        return (
            not found,
            found,
            [f"checked {checked} changed file(s)"],
        )
