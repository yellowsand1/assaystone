"""Mutation testing over the change itself.

"Tests pass" says nothing about whether the tests *cover the change*. Inject one
plausible defect at a time into the changed code and run the suite: a mutant the
suite does not kill is a behaviour nobody is checking. That is as close as a
deterministic check gets to "the behaviour is verified", and it needs no
specification beyond the tests the repository already has.

The check is honest about its limits: it only sees Python, it only mutates the
diff, and a surviving mutant may be equivalent rather than a real gap.
"""
from __future__ import annotations

import ast
import copy
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mutate import _apply, _render, _source_candidates


@dataclass
class MutantCase:
    description: str
    target: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "target": self.target,
        }


@dataclass
class MutantOutcome:
    case: MutantCase
    status: str  # killed | survived | invalid
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**self.case.to_dict(), "status": self.status, "detail": self.detail}


@dataclass
class MutationCheck:
    outcome: str
    score: float = 0.0
    killed: int = 0
    survived: int = 0
    invalid: int = 0
    survivors: list[MutantOutcome] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def _changed_lines(root: Path, against: str) -> dict[str, set[int]]:
    """Line numbers this change added, per file. Only those get mutated.

    Mutating a whole changed file measures whether the file is covered; mutating
    the added lines measures whether *the change* is covered, which is the claim.
    """

    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True
        )
        return proc.stdout if proc.returncode == 0 else ""

    lines: dict[str, set[int]] = {}
    current = ""
    for line in run("diff", "-U0", against).splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            lines.setdefault(current, set())
            continue
        if line.startswith("@@") and current:
            match = __import__("re").search(r"\+(\d+)(?:,(\d+))?", line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or 1)
            lines[current].update(range(start, start + count))
    for name in run("ls-files", "--others", "--exclude-standard").splitlines():
        name = name.strip()
        if not name or _is_test_path(name) or _is_excluded(name):
            continue
        path = root / name
        if path.is_file():
            try:
                count = len(path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                continue
            lines.setdefault(name, set()).update(range(1, count + 1))
    return lines


def _changed_python(root: Path, against: str) -> list[str]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True
        )
        return proc.stdout if proc.returncode == 0 else ""

    names = {
        line.strip()
        for line in run("diff", "--name-only", against).splitlines()
        if line.strip()
    }
    names.update(
        line.strip()
        for line in run("ls-files", "--others", "--exclude-standard").splitlines()
        if line.strip()
    )
    return sorted(
        name
        for name in names
        if name.endswith(".py")
        and not _is_test_path(name)
        and not _is_excluded(name)
        and (root / name).is_file()
    )


# Paths the run copies without, so mutating them would fail to find the file.
EXCLUDED_TOPS = frozenset({
    ".git", ".assaystone", "node_modules", ".venv", "venv",
    "__pycache__", "target", "dist", "build",
})


def _is_excluded(name: str) -> bool:
    return name.split("/")[0] in EXCLUDED_TOPS


TEST_MARKERS = ("/test_", "test_", "_test.py", "conftest.py", "/tests/", "tests/")


def _is_test_path(name: str) -> bool:
    """A mutant of a test is not a defect in the product.

    Mutating test code measures nothing: the mutant test is simply a different
    test, and whether it passes says nothing about the change.
    """
    padded = f"/{name}"
    for part in name.split("/"):
        if part in ("tests", "test", "__tests__", "spec"):
            return True
    return any(marker in padded for marker in ("/test_", "_test.py", "conftest.py"))


def cases_for(
    source: str,
    path: str,
    per_operator: int = 2,
    budget: int = 8,
    allowed_lines: set[int] | None = None,
) -> list[MutantCase]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    cases: list[MutantCase] = []
    seen: dict[str, int] = {}
    for operator, node_path, lineno, description in _source_candidates(tree):
        if len(cases) >= budget:
            break
        if allowed_lines is not None and lineno not in allowed_lines:
            continue
        if seen.get(operator, 0) >= per_operator:
            continue
        mutated = copy.deepcopy(tree)
        try:
            _apply(mutated, node_path, operator)
            rendered = _render(mutated)
            ast.parse(rendered)
        except Exception:  # noqa: BLE001 - a bad mutation is skipped
            continue
        seen[operator] = seen.get(operator, 0) + 1
        cases.append(
            MutantCase(
                description=description, target=f"{path}:{lineno}", source=rendered
            )
        )
    return cases


def run_check(
    root: str | Path,
    command: list[str],
    against: str = "HEAD",
    threshold: float = 0.5,
    max_mutants: int = 8,
    timeout: float = 600,
    paths: list[str] | None = None,
) -> MutationCheck:
    root = Path(root).resolve()
    changed = _changed_lines(root, against)
    files = list(paths) if paths else _changed_python(root, against)
    if not files:
        return MutationCheck(
            outcome="escalate",
            reasons=[
                "no changed Python file to mutate; this check cannot speak to "
                "a change it cannot see"
            ],
        )
    cases: list[MutantCase] = []
    for name in files:
        try:
            source = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        cases.extend(
            cases_for(
                source,
                name,
                budget=max(1, max_mutants - len(cases)),
                allowed_lines=None if paths else changed.get(name, set()),
            )
        )
        if len(cases) >= max_mutants:
            break
    cases = cases[:max_mutants]
    if not cases:
        return MutationCheck(
            outcome="escalate",
            reasons=["no mutable construct found in the changed code"],
            files=files,
        )

    work = Path(tempfile.mkdtemp(prefix="assaystone-mutation-"))
    check = MutationCheck(outcome="fail", files=files)
    try:
        target = work / "repo"
        shutil.copytree(
            root,
            target,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".venv", "venv", "node_modules",
                "target", "dist", "build", ".assaystone",
            ),
        )
        baseline = subprocess.run(
            command, cwd=target, capture_output=True, text=True, timeout=timeout
        )
        if baseline.returncode != 0:
            return MutationCheck(
                outcome="escalate",
                reasons=[
                    "the command does not pass on unmutated code; mutation "
                    "testing would only re-measure that failure"
                ],
                files=files,
            )
        for case in cases:
            relative = case.target.rsplit(":", 1)[0]
            path = target / relative
            original = path.read_text(encoding="utf-8")
            try:
                path.write_text(case.source, encoding="utf-8")
                proc = subprocess.run(
                    command, cwd=target, capture_output=True, text=True,
                    timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                check.invalid += 1
                check.survivors.append(
                    MutantOutcome(case=case, status="invalid", detail=str(exc))
                )
                continue
            finally:
                path.write_text(original, encoding="utf-8")
            if proc.returncode == 0:
                check.survived += 1
                check.survivors.append(
                    MutantOutcome(case=case, status="survived")
                )
            else:
                check.killed += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)

    denominator = check.killed + check.survived
    check.score = check.killed / denominator if denominator else 0.0
    if denominator == 0:
        check.outcome = "escalate"
        check.reasons.append("every mutant failed to run; nothing was measured")
        return check
    if check.score < threshold:
        check.outcome = "fail"
        check.reasons.append(
            f"{check.survived} of {denominator} mutants survived "
            f"(score {check.score:.0%}, required {threshold:.0%}): the tests do "
            "not cover these behaviours"
        )
        for outcome in check.survivors[:3]:
            if outcome.status == "survived":
                check.reasons.append(
                    f"  survived: {outcome.case.description}"
                )
        return check
    check.outcome = "pass"
    return check
