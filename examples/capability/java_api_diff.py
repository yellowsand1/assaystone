"""Compare the public API of a compiled Java tree with a git baseline.

This is an example ``command`` payload, not part of the core. Copy it into a
repository and bind it to a criterion:

    {"id": "api-stable", "kind": "invariant",
     "statement": "The public API is unchanged.", "oracle": "api"}

    {"id": "api", "type": "command", "payload": {
       "command": ["python3", ".assaystone/java_api_diff.py",
                   "--baseline", "HEAD"]}}

It compiles the baseline in a temporary worktree, runs ``javap -public`` on both
trees, and fails when a class or a public signature differs. Requires git, Maven,
and a JDK. A Java API change can compile and leave every test green while
breaking downstream consumers; this is the cheap oracle for that case.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def signatures(classes: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(classes.rglob("*.class")):
        name = ".".join(path.relative_to(classes).with_suffix("").parts)
        proc = subprocess.run(
            ["javap", "-public", "-classpath", str(classes), name],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            continue
        lines = [
            line.strip()
            for line in proc.stdout.splitlines()
            if line.strip() and not line.startswith("Compiled from")
        ]
        found[name] = sorted(lines)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument("--classes", default="target/classes")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    base = subprocess.run(
        ["git", "-C", str(root), "rev-parse", args.baseline],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    current = signatures(root / args.classes)
    worktree = Path(tempfile.mkdtemp(prefix="api-baseline-"))
    try:
        subprocess.run(
            [
                "git", "-C", str(root), "worktree", "add",
                "--detach", str(worktree), base,
            ],
            check=True,
            capture_output=True,
        )
        build = subprocess.run(
            ["mvn", "-q", "-o", "-DskipTests", "compile"],
            cwd=worktree,
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            print("baseline build failed", file=sys.stderr)
            print((build.stdout + build.stderr)[-800:], file=sys.stderr)
            return 2
        baseline = signatures(worktree / "target" / "classes")
    finally:
        subprocess.run(
            ["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
        )
        shutil.rmtree(worktree, ignore_errors=True)
    diffs: list[str] = []
    for name in sorted(set(current) | set(baseline)):
        before = baseline.get(name)
        after = current.get(name)
        if before is None:
            diffs.append(f"added class {name}")
            continue
        if after is None:
            diffs.append(f"removed class {name}")
            continue
        removed = [line for line in before if line not in after]
        added = [line for line in after if line not in before]
        if removed:
            diffs.append(f"{name}: removed " + "; ".join(removed))
        if added:
            diffs.append(f"{name}: added " + "; ".join(added))
    if diffs:
        print("public API changed:")
        for item in diffs[:20]:
            print("  " + item)
        return 1
    print(f"public API unchanged ({len(current)} classes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
