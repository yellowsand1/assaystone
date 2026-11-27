"""A task spec: obligations a human can read, evidence a machine can check.

A contract says what acceptance means for a task *type*. A spec says what this
task *asked for*: "add a migration", "new behaviour has a test", "do not touch
CI". Each obligation compiles into a criterion whose evidence rules are
deterministic: a changed path, a file that contains a string, a path that must
not change, a file that must exist.

The point is not to parse natural language. It is to make the task's own
checklist an artifact, so the certificate can say which obligations were met,
which were violated, and which could not be decided.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any

from .contract import Contract, Criterion
from .verifiers import VerifyContext

SCHEMA = "assaystone.spec/1"
KINDS = ("path", "contains", "absent", "exists")
MAX_OBLIGATIONS = 200


class SpecError(ValueError):
    """The spec file is not usable."""


def digest(spec: dict[str, Any]) -> str:
    material = json.dumps(
        spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate(spec: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["spec is not an object"]
    if spec.get("schema") != SCHEMA:
        problems.append(f"unsupported schema: {spec.get('schema')!r}")
    obligations = spec.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        return problems + ["obligations must be a non-empty list"]
    if len(obligations) > MAX_OBLIGATIONS:
        problems.append(f"too many obligations: {len(obligations)}")
    seen: set[str] = set()
    for index, obligation in enumerate(obligations):
        if not isinstance(obligation, dict):
            problems.append(f"obligations[{index}] is not an object")
            continue
        oid = str(obligation.get("id") or "").strip()
        if not oid:
            problems.append(f"obligations[{index}] has no id")
        elif oid in seen:
            problems.append(f"duplicate obligation id: {oid}")
        seen.add(oid)
        if not str(obligation.get("statement") or "").strip():
            problems.append(f"{oid or index}: no statement")
        if obligation.get("mode") not in (None, "all", "any"):
            problems.append(f"{oid or index}: mode must be all or any")
        rules = obligation.get("evidence")
        if not isinstance(rules, list) or not rules:
            problems.append(f"{oid or index}: evidence must be a non-empty list")
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                problems.append(f"{oid or index}: evidence rule is not an object")
                continue
            if rule.get("kind") not in KINDS:
                problems.append(f"{oid or index}: unknown evidence kind {rule.get('kind')!r}")
            if not str(rule.get("glob") or "").strip():
                problems.append(f"{oid or index}: evidence rule needs a glob")
    return problems


def load(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpecError(f"spec not found: {path}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc
    problems = validate(data)
    if problems:
        raise SpecError(f"{path}: " + "; ".join(problems))
    return data


def criteria_from_spec(spec: dict[str, Any]) -> list[Criterion]:
    criteria: list[Criterion] = []
    for obligation in spec["obligations"]:
        rules = [dict(rule) for rule in obligation["evidence"]]
        kind = obligation.get("kind")
        if not kind:
            kind = (
                "forbidden_action"
                if all(rule.get("kind") == "absent" for rule in rules)
                else "postcondition"
            )
        oid = str(obligation["id"])
        criteria.append(
            Criterion.from_dict(
                {
                    "id": oid,
                    "kind": kind,
                    "statement": str(obligation["statement"]),
                    "defect": f"spec:{oid}",
                    "verifiers": [],
                    "severity": str(obligation.get("severity") or "high"),
                    "on_unknown": str(obligation.get("on_unknown") or "escalate"),
                    "evidence": rules,
                    "evidence_mode": str(obligation.get("mode") or "all"),
                }
            )
        )
    return criteria


def merge(contract: Contract, spec: dict[str, Any]) -> Contract:
    existing = {criterion.id for criterion in contract.criteria}
    for criterion in criteria_from_spec(spec):
        if criterion.id in existing:
            raise SpecError(f"obligation id collides with a criterion: {criterion.id}")
        contract.criteria.append(criterion)
    return contract


def _changed_lines(before: str, after: str) -> int:
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm="", n=0
    )
    return sum(
        1
        for line in diff
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _matching(ctx: VerifyContext, glob: str) -> list[tuple[str, str]]:
    return [
        (path, change)
        for path, change in ctx.changed()
        if fnmatch.fnmatch(path, glob)
    ]


def _text(ctx: VerifyContext, path: str, change: str) -> str:
    if change == "deleted":
        return ""
    try:
        return ctx.current_text(path)
    except (OSError, UnicodeDecodeError):
        return ctx.baseline_text(path) or ""


def _baseline_glob(ctx: VerifyContext, glob: str) -> list[str]:
    """Files that already exist in the baseline and match the glob."""
    root = Path(ctx.baseline)
    found: list[str] = []
    try:
        for path in root.glob(glob):
            if path.is_file():
                found.append(path.relative_to(root).as_posix())
    except (OSError, ValueError):
        return []
    return sorted(found)


def _rule_path(rule: dict[str, Any], ctx: VerifyContext):
    glob = str(rule["glob"])
    wanted = rule.get("change")
    matches = _matching(ctx, glob)
    if wanted:
        matches = [(path, change) for path, change in matches if change == wanted]
    if not matches:
        return False, [f"no changed path matches {glob}"], []
    minimum = rule.get("min_changed_lines")
    if minimum is not None:
        for path, change in matches:
            before = ctx.baseline_text(path) or ""
            after = _text(ctx, path, change)
            count = _changed_lines(before, after)
            if count >= int(minimum):
                return True, [f"{path}: {count} changed line(s)"], [path]
        return (
            False,
            [f"no matching path has {int(minimum)} changed line(s)"],
            [path for path, _ in matches],
        )
    return True, [f"{len(matches)} path(s) match {glob}"], [path for path, _ in matches]


def _rule_contains(rule: dict[str, Any], ctx: VerifyContext):
    glob = str(rule["glob"])
    needle = str(rule.get("text") or "")
    if not needle:
        return None, ["contains rule needs text"], []
    matches = _matching(ctx, glob)
    if not matches:
        # Nothing changed; the file may already exist in the baseline.
        matches = [(path, "unchanged") for path in _baseline_glob(ctx, glob)]
    if not matches:
        return None, [f"no file matches {glob}"], []
    for path, change in matches:
        text = _text(ctx, path, change)
        if rule.get("regex"):
            import re

            try:
                found = bool(re.search(needle, text))
            except re.error as exc:
                return None, [f"{path}: invalid regex: {exc}"], []
        else:
            found = needle in text
        if found:
            return True, [f"{path} contains {needle!r}"], [path]
    return False, [f"{glob} does not contain {needle!r}"], [p for p, _ in matches]


def _rule_absent(rule: dict[str, Any], ctx: VerifyContext):
    glob = str(rule["glob"])
    matches = _matching(ctx, glob)
    if matches:
        return False, [f"forbidden change: {path}" for path, _ in matches], [
            path for path, _ in matches
        ]
    return True, [f"no change matches {glob}"], []


def _rule_exists(rule: dict[str, Any], ctx: VerifyContext):
    glob = str(rule["glob"])
    deleted = {path for path, change in _matching(ctx, glob) if change == "deleted"}
    matches = [
        (path, change)
        for path, change in _matching(ctx, glob)
        if change != "deleted"
    ]
    names = {path for path, _ in matches}
    for path in _baseline_glob(ctx, glob):
        if path not in deleted and path not in names:
            matches.append((path, "unchanged"))
            names.add(path)
    if matches:
        return True, [f"{path} exists" for path, _ in matches], [
            path for path, _ in matches
        ]
    return False, [f"{glob} does not exist"], []


_RULES = {
    "path": _rule_path,
    "contains": _rule_contains,
    "absent": _rule_absent,
    "exists": _rule_exists,
}


def _evaluate_rule(rule: dict[str, Any], ctx: VerifyContext):
    handler = _RULES.get(str(rule.get("kind")))
    if handler is None:
        return None, [f"unknown evidence kind: {rule.get('kind')!r}"], []
    return handler(rule, ctx)


def evaluate_obligation(
    criterion: Criterion, ctx: VerifyContext
) -> tuple[bool | None, list[str], list[str]]:
    """Evaluate one obligation's evidence rules without a model."""
    results = [_evaluate_rule(rule, ctx) for rule in criterion.evidence]
    reasons = [reason for _, items, _ in results for reason in items]
    evidence = [item for _, _, items in results for item in items]
    outcomes = [ok for ok, _, _ in results]
    if criterion.evidence_mode == "any":
        if any(ok is True for ok in outcomes):
            return True, reasons, evidence
        if outcomes and all(ok is False for ok in outcomes):
            return False, reasons, evidence
        return None, reasons, evidence
    if any(ok is False for ok in outcomes):
        return False, reasons, evidence
    if any(ok is None for ok in outcomes):
        return None, reasons, evidence
    return True, reasons, evidence
