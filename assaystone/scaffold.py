"""Draft a capability manifest by inspecting a repository.

This is onboarding, not verification. The detection is deliberately shallow —
a build file, a test directory, a branch convention — and it produces a
*declaration* that the plane then checks. If detection is wrong, the manifest is
wrong in the open: every claim it makes is bound to an oracle that either runs
or escalates.

Nothing here is imported by ``plane.py``. A new build tool is a detection
branch in this module that emits a command payload; the core stays domain-blind.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path(".assaystone") / "capability.json"


class ScaffoldError(ValueError):
    """No recognizable build or test surface was found."""


@dataclass
class Detection:
    stack: str
    oracles: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _command(oracle_id: str, command: list[str], timeout: int) -> dict[str, Any]:
    return {
        "id": oracle_id,
        "type": "command",
        "payload": {"command": command, "timeout": timeout},
    }


def _artifact(path: str) -> dict[str, Any]:
    return {"id": "artifact", "type": "file", "payload": {"path": path, "mode": "exists"}}


def _has_any(root: Path, *names: str) -> bool:
    return any((root / name).exists() for name in names)


def _git_branch_prefix(root: Path) -> str:
    """Pick the feature-branch convention this repository already uses."""
    if not (root / ".git").exists():
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "branch", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    branches = proc.stdout.splitlines()
    for prefix in ("feature/", "feat/"):
        if any(item.startswith(prefix) for item in branches):
            return prefix
    return "feature/"


def _branch_oracle(root: Path, notes: list[str]) -> list[dict[str, Any]]:
    prefix = _git_branch_prefix(root)
    if not prefix:
        return []
    notes.append(
        f"branch oracle expects a {prefix}* branch; adjust it if your "
        "convention differs"
    )
    return [
        {
            "id": "branch",
            "type": "git",
            "payload": {"mode": "branch", "expected": prefix},
        }
    ]


def _maven_packaging(root: Path) -> str:
    import xml.etree.ElementTree as ElementTree

    try:
        document = ElementTree.parse(root / "pom.xml")
    except (OSError, ElementTree.ParseError):
        return ""
    for path in (
        "{http://maven.apache.org/POM/4.0.0}packaging",
        "packaging",
    ):
        node = document.getroot().find(path)
        if node is not None:
            return (node.text or "").strip()
    return ""


def _detect_maven(root: Path, notes: list[str]) -> Detection:
    binary = "./mvnw" if (root / "mvnw").exists() else "mvn"
    oracles = [_command("build", [binary, "-q", "-DskipTests", "compile"], 600)]
    if (root / "src" / "test" / "java").is_dir():
        oracles.append(_command("tests", [binary, "-q", "test"], 900))
    if _maven_packaging(root) == "pom":
        notes.append(
            "aggregator pom: there is no target/classes; run init inside a "
            "module for an artifact check"
        )
    else:
        oracles.append(_artifact("target/classes"))
    if binary == "./mvnw":
        notes.append("using the Maven wrapper")
    return Detection(stack="maven", oracles=oracles, notes=notes)


def _detect_gradle(root: Path, notes: list[str]) -> Detection:
    binary = "./gradlew" if (root / "gradlew").exists() else "gradle"
    kotlin = (root / "src" / "main" / "kotlin").is_dir()
    task = "compileKotlin" if kotlin else "compileJava"
    oracles = [_command("build", [binary, "-q", task], 600)]
    if (root / "src" / "test").is_dir():
        oracles.append(_command("tests", [binary, "-q", "test"], 900))
    layout = "kotlin" if kotlin else "java"
    oracles.append(_artifact(f"build/classes/{layout}/main"))
    return Detection(stack="gradle", oracles=oracles, notes=notes)


def _npm_scripts(root: Path) -> dict[str, str]:
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def _detect_node(root: Path, notes: list[str]) -> Detection:
    scripts = _npm_scripts(root)
    oracles: list[dict[str, Any]] = []
    if "build" in scripts:
        oracles.append(_command("build", ["npm", "run", "build", "--silent"], 600))
    if "test" in scripts:
        oracles.append(_command("tests", ["npm", "test", "--silent"], 900))
    if not oracles:
        raise ScaffoldError(
            "package.json has no build or test script; add one or write the "
            "manifest by hand"
        )
    return Detection(stack="node", oracles=oracles, notes=notes)


def _detect_python(root: Path, notes: list[str]) -> Detection:
    tests = (root / "tests").is_dir() or bool(list(root.glob("test_*.py")))
    if not tests:
        raise ScaffoldError(
            "Python project without a tests/ directory or test_*.py; add a "
            "test oracle or write the manifest by hand"
        )
    return Detection(
        stack="python",
        oracles=[_command("tests", ["python3", "-m", "pytest", "-q"], 900)],
        notes=notes,
    )


def _detect_go(root: Path, notes: list[str]) -> Detection:
    return Detection(
        stack="go",
        oracles=[_command("tests", ["go", "test", "./..."], 900)],
        notes=notes,
    )


def _detect_rust(root: Path, notes: list[str]) -> Detection:
    return Detection(
        stack="rust",
        oracles=[_command("tests", ["cargo", "test", "--quiet"], 900)],
        notes=notes,
    )


def detect(root: str | Path) -> Detection:
    root = Path(root).resolve()
    notes: list[str] = []
    if (root / "pom.xml").exists():
        detection = _detect_maven(root, notes)
    elif _has_any(root, "build.gradle", "build.gradle.kts"):
        detection = _detect_gradle(root, notes)
    elif (root / "package.json").exists():
        detection = _detect_node(root, notes)
    elif _has_any(root, "pyproject.toml", "setup.py", "setup.cfg"):
        detection = _detect_python(root, notes)
    elif (root / "go.mod").exists():
        detection = _detect_go(root, notes)
    elif (root / "Cargo.toml").exists():
        detection = _detect_rust(root, notes)
    else:
        raise ScaffoldError(
            "no recognized build or test surface (pom.xml, gradle, "
            "package.json, pyproject.toml, go.mod, Cargo.toml); "
            "write the manifest by hand or run this inside a module"
        )
    detection.oracles.extend(_branch_oracle(root, notes))
    return detection


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "capability"


def build_manifest(
    root: str | Path, owner: str = "unassigned"
) -> tuple[dict[str, Any], Detection]:
    root = Path(root).resolve()
    detection = detect(root)
    oracle_ids = [item["id"] for item in detection.oracles]
    severity = {"build": "critical", "tests": "critical", "artifact": "critical"}
    criteria = [
        {
            "id": item["id"],
            "kind": "precondition" if item["id"] == "branch" else "postcondition",
            "statement": {
                "build": "The project builds.",
                "tests": "The test suite passes.",
                "artifact": "The build emitted its output.",
                "branch": "The change is on a feature branch.",
            }[item["id"]],
            "oracle": item["id"],
            "severity": "high" if item["id"] == "branch" else severity[item["id"]],
        }
        for item in detection.oracles
    ]
    data = {
        "capability": _slug(root.name),
        "owner": owner,
        "systems": ["git", detection.stack] if "branch" in oracle_ids else [detection.stack],
        "data_classes": ["internal"],
        "irreversible_actions": ["merge"],
        "risk": "high",
        "lifecycle": "design",
        "retention": "30d",
        "criteria": criteria,
        "oracles": detection.oracles,
        "policies": {
            "shadow": {"require": oracle_ids, "allow_merge": False},
            "canary": {"require": oracle_ids, "allow_merge": True},
            "production": {
                "require": oracle_ids,
                "allow_merge": True,
                "allow_deploy": True,
            },
        },
    }
    return data, detection


def init_capability(
    root: str | Path,
    out: str | Path | None = None,
    owner: str | None = None,
    force: bool = False,
) -> tuple[Path, dict[str, Any], Detection]:
    root = Path(root).resolve()
    target = Path(out) if out else root / DEFAULT_OUT
    if target.exists() and not force:
        raise ScaffoldError(f"{target} exists; pass --force to overwrite")
    data, detection = build_manifest(root, owner=owner or "unassigned")
    from .plane import CapabilityManifest, PlaneError

    try:
        CapabilityManifest.from_dict(data, source=str(target))
    except PlaneError as exc:  # a draft that cannot be used is a bug
        raise ScaffoldError(f"generated manifest is invalid: {exc}") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return target, data, detection


def next_steps(data: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if data.get("owner") == "unassigned":
        steps.append("set owner to the team that owns this capability")
    steps.append(
        "add an approval oracle to the canary and production policies"
    )
    steps.append(
        "add a rollback oracle, then set rollback_required on production"
    )
    steps.append(
        "run the gate and inspect every escalation before trusting the draft"
    )
    return steps


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "DEFAULT_OUT",
    "Detection",
    "ScaffoldError",
    "build_manifest",
    "detect",
    "display_path",
    "init_capability",
    "next_steps",
]
