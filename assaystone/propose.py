"""Propose acceptance criteria from what the repository already contains.

A domain expert should not have to invent a standard from nothing. Most of the
standard is already visible: the public API is a contract, a migration without a
down path is a one-way door, a new dependency is a supply-chain change, and a
deleted test is a defect. This module reads the repository and proposes the
criteria its own structure implies, with the evidence that justifies each one.

A proposal is a draft, not a decision: every proposed check runs, or escalates
when it cannot. The point is that the starting manifest checks the things this
repository actually has, instead of three build commands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HELPER_DIR = Path(".assaystone") / "checks"

JAVA_API_DIFF = '''"""Compare the public API of a compiled Java tree with a git baseline."""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def signatures(classes):
    found = {}
    for path in sorted(classes.rglob("*.class")):
        name = ".".join(path.relative_to(classes).with_suffix("").parts)
        proc = subprocess.run(
            ["javap", "-public", "-classpath", str(classes), name],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            continue
        found[name] = sorted(
            line.strip()
            for line in proc.stdout.splitlines()
            if line.strip() and not line.startswith("Compiled from")
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument("--classes", default="target/classes")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    base = subprocess.run(
        ["git", "-C", str(root), "rev-parse", args.baseline],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    current = signatures(root / args.classes)
    worktree = Path(tempfile.mkdtemp(prefix="api-baseline-"))
    try:
        subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "--detach",
             str(worktree), base],
            check=True, capture_output=True,
        )
        build = subprocess.run(
            ["mvn", "-q", "-o", "-DskipTests", "compile"],
            cwd=worktree, capture_output=True, text=True,
        )
        if build.returncode != 0:
            print("baseline build failed", file=sys.stderr)
            return 2
        baseline = signatures(worktree / "target" / "classes")
    finally:
        subprocess.run(
            ["git", "-C", str(root), "worktree", "remove", "--force",
             str(worktree)],
            capture_output=True,
        )
        shutil.rmtree(worktree, ignore_errors=True)
    diffs = []
    for name in sorted(set(current) | set(baseline)):
        before, after = baseline.get(name), current.get(name)
        if before is None:
            diffs.append(f"added class {name}")
        elif after is None:
            diffs.append(f"removed class {name}")
        else:
            for line in before:
                if line not in after:
                    diffs.append(f"{name}: removed {line}")
            for line in after:
                if line not in before:
                    diffs.append(f"{name}: added {line}")
    if diffs:
        print("public API changed:")
        for item in diffs[:20]:
            print("  " + item)
        return 1
    print(f"public API unchanged ({len(current)} classes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

DEPS_DIFF = '''"""Fail when the declared dependency set changes against a git baseline."""
import json
import re
import subprocess
import sys
from pathlib import Path


def _run(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def _pom(text):
    return set(
        re.findall(r"<artifactId>([^<]+)</artifactId>\\s*</dependency>", text)
    )


def _package_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    names = set()
    for key in ("dependencies", "devDependencies"):
        names.update((data.get(key) or {}).keys())
    return names


def _pyproject(text):
    names = set(re.findall(r"^\\s*[\\"']?([A-Za-z0-9_.-]+)[\\"']?\\s*[><=~!]", text, re.M))
    return {name for name in names if len(name) > 1}


def _requirements(text):
    return {
        line.split("==")[0].split(">=")[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }


PARSERS = {
    "pom.xml": _pom,
    "package.json": _package_json,
    "pyproject.toml": _pyproject,
    "requirements.txt": _requirements,
}


def main() -> int:
    root = Path.cwd().resolve()
    changed = []
    for name, parser in PARSERS.items():
        path = root / name
        if not path.exists():
            continue
        current = parser(path.read_text(encoding="utf-8"))
        base = _run(root, "show", f"HEAD:{name}")
        before = parser(base.stdout) if base.returncode == 0 else set()
        added = sorted(current - before)
        removed = sorted(before - current)
        for item in added:
            changed.append(f"{name}: added {item}")
        for item in removed:
            changed.append(f"{name}: removed {item}")
    if changed:
        print("the dependency set changed:")
        for item in changed[:20]:
            print("  " + item)
        return 1
    print("dependency set unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

MIGRATION_DOWN = '''"""Fail when a new migration has no declared down path."""
import re
import subprocess
import sys
from pathlib import Path

MARKERS = re.compile(
    r"(^--\\s*(down|undo|rollback)\\b)|(^\\s*//\\s*(down|undo)\\b)"
    r"|(^--\\s*\\+migrate\\s+Down)",
    re.IGNORECASE | re.MULTILINE,
)


def main() -> int:
    root = Path.cwd().resolve()
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-status", "HEAD"],
        capture_output=True, text=True,
    ).stdout
    changed = [
        line.split("\\t", 1)[1]
        for line in out.splitlines()
        if (line.startswith("A\\t") or line.startswith("M\\t"))
        and line.lower().endswith(".sql")
    ]
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
    ).stdout.splitlines()
    added = sorted(
        {item for item in changed + untracked if item.lower().endswith(".sql")}
    )
    missing = []
    for name in added:
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        if not MARKERS.search(text):
            missing.append(name)
    if missing:
        print("new migrations without a down path:")
        for name in missing:
            print("  " + name)
        print("add a `-- down` section or a matching rollback file")
        return 1
    print(f"migrations reversible ({len(added)} new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

HELPERS = {
    "java_api_diff.py": JAVA_API_DIFF,
    "deps_diff.py": DEPS_DIFF,
    "migrations_down.py": MIGRATION_DOWN,
}


@dataclass
class Proposal:
    id: str
    kind: str
    statement: str
    severity: str
    oracle: dict[str, Any]
    why: str
    helper: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "statement": self.statement,
            "severity": self.severity,
            "oracle": self.oracle,
            "why": self.why,
            "helper": self.helper,
        }


@dataclass
class Scan:
    stack: str
    has_tests: bool = False
    has_ci: bool = False
    has_java_sources: bool = False
    has_python_package: bool = False
    has_dependency_manifest: bool = False
    migration_dirs: list[str] = field(default_factory=list)


TEST_DIRS = ("tests", "src/test/java", "src/test", "test", "__tests__")
MIGRATION_DIRS = (
    "src/main/resources/db/migration",
    "db/migration",
    "migrations",
    "sql/migrations",
)


def scan(root: str | Path, stack: str = "") -> Scan:
    root = Path(root)
    facts = Scan(stack=stack)
    facts.has_tests = any((root / item).is_dir() for item in TEST_DIRS)
    facts.has_ci = (root / ".github" / "workflows").is_dir()
    facts.has_java_sources = (
        (root / "src" / "main" / "java").is_dir()
        or (root / "src" / "main" / "kotlin").is_dir()
    )
    facts.has_python_package = bool(
        list(root.glob("*/__init__.py")) or list(root.glob("src/*/__init__.py"))
    )
    facts.has_dependency_manifest = any(
        (root / name).exists()
        for name in ("pom.xml", "package.json", "pyproject.toml",
                     "requirements.txt")
    )
    facts.migration_dirs = [
        item for item in MIGRATION_DIRS if (root / item).is_dir()
    ]
    return facts


def propose(facts: Scan) -> list[Proposal]:
    proposals: list[Proposal] = []

    if facts.has_java_sources and facts.stack == "maven":
        proposals.append(
            Proposal(
                id="api-unchanged",
                kind="invariant",
                statement="The public API is unchanged.",
                severity="critical",
                oracle={
                    "id": "api",
                    "type": "command",
                    "description": "javap against the baseline commit",
                    "payload": {
                        "command": [
                            "python3",
                            ".assaystone/checks/java_api_diff.py",
                            "--baseline",
                            "HEAD",
                        ],
                        "timeout": 600,
                        "unknown_exit": [2],
                    },
                },
                why=(
                    "src/main/java exists and the module is packaged: the public "
                    "API is what downstream consumers compile against, and a "
                    "green build cannot see a broken one"
                ),
                helper="java_api_diff.py",
            )
        )

    if facts.has_tests:
        proposals.append(
            Proposal(
                id="tests-intact",
                kind="forbidden_action",
                statement="No test was deleted, weakened, or replaced.",
                severity="critical",
                oracle={
                    "id": "tests_intact",
                    "type": "verifier",
                    "description": "the tests.integrity check",
                    "payload": {"name": "tests.integrity", "params": {}},
                },
                why=(
                    "a test tree exists: a suite that passes because the failing "
                    "test disappeared is the canonical agent failure"
                ),
            )
        )

    if facts.has_ci:
        proposals.append(
            Proposal(
                id="ci-intact",
                kind="forbidden_action",
                statement="The CI configuration is unchanged.",
                severity="high",
                oracle={
                    "id": "ci_intact",
                    "type": "verifier",
                    "description": "the diff.ci_surface check",
                    "payload": {"name": "diff.ci_surface", "params": {}},
                },
                why=(
                    ".github/workflows exists: weakening CI is cheaper than "
                    "fixing the code, so it is a defect even when the build is "
                    "green"
                ),
            )
        )

    if facts.stack == "python" and facts.has_tests:
        proposals.append(
            Proposal(
                id="change-covered",
                kind="postcondition",
                statement="The change is covered by the tests.",
                severity="high",
                oracle={
                    "id": "mutation",
                    "type": "mutation",
                    "description": (
                        "mutate the added lines and require the suite to "
                        "kill most of them"
                    ),
                    "payload": {
                        "command": ["python3", "-m", "pytest", "-q"],
                        "against": "HEAD",
                        "threshold": 0.5,
                        "max_mutants": 6,
                        "timeout": 900,
                        "cost_usd": 0.05,
                        "mutates": True,
                    },
                },
                why=(
                    "a Python test suite exists: passing tests do not prove "
                    "the change is covered, and a surviving mutant is a "
                    "behaviour nobody checks"
                ),
            )
        )

    if facts.has_dependency_manifest:
        proposals.append(
            Proposal(
                id="deps-unchanged",
                kind="invariant",
                statement="The declared dependency set is unchanged.",
                severity="high",
                oracle={
                    "id": "deps",
                    "type": "command",
                    "description": "compare the dependency set with the baseline",
                    "payload": {
                        "command": [
                            "python3",
                            ".assaystone/checks/deps_diff.py",
                        ],
                        "timeout": 120,
                    },
                },
                why=(
                    "a dependency manifest exists: adding a dependency is a "
                    "supply-chain change that a test suite will not notice"
                ),
                helper="deps_diff.py",
            )
        )

    for directory in facts.migration_dirs:
        proposals.append(
            Proposal(
                id="migrations-reversible",
                kind="invariant",
                statement="Every new migration declares a down path.",
                severity="critical",
                oracle={
                    "id": "migrations_down",
                    "type": "command",
                    "description": "a new migration must be reversible",
                    "payload": {
                        "command": [
                            "python3",
                            ".assaystone/checks/migrations_down.py",
                        ],
                        "timeout": 120,
                    },
                },
                why=(
                    f"{directory} exists: a migration without a down path is a "
                    "one-way door"
                ),
                helper="migrations_down.py",
            )
        )
        break

    return proposals


def materialise(root: str | Path, proposals: list[Proposal]) -> list[Path]:
    """Write the helper scripts a proposal needs. They are payloads, not core."""
    root = Path(root)
    written: list[Path] = []
    for proposal in proposals:
        if not proposal.helper:
            continue
        target = root / HELPER_DIR / proposal.helper
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(HELPERS[proposal.helper], encoding="utf-8")
        written.append(target)
    return written
