"""Scaffold an acceptance contract for an existing repository."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ACTION_REF = "v0.23.0"

# The defect classes a generated contract claims to cover. Coverage is only
# meaningful when the requirement is stated independently of the checks, so this
# list is fixed and the user is asked to trim it.
DEFAULT_REQUIRED_DEFECTS = (
    "regression",
    "test-tampering",
    "test-harness-hijack",
    "test-support-tampering",
    "module-shadow",
    "ci-bypass",
    "forbidden-path",
    "unverified-language",
    "debug-print",
    "false-claim",
)


def _detect_test_command(root: Path) -> tuple[list[str], bool]:
    if (
        (root / "pytest.ini").exists()
        or (root / "conftest.py").exists()
        or (root / "tox.ini").exists()
    ):
        return ["{python}", "-m", "pytest", "-q"], True
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        if "[tool.pytest" in text:
            return ["{python}", "-m", "pytest", "-q"], True
    for name in ("tests", "test"):
        if (root / name).exists():
            return ["{python}", "-m", "unittest", "discover", "-s", name, "-t", ".", "-v"], True
    return ["{python}", "-m", "pytest", "-q"], False


def _detect_protected(root: Path) -> list[str]:
    return [f"{name}/" for name in ("tests", "test", "spec") if (root / name).exists()]


def _detect_forbidden(root: Path) -> list[str]:
    candidates = ["ci/", ".github/workflows/", ".github/actions/", "Makefile", "pyproject.toml", "package.json", "Dockerfile"]
    return [path for path in candidates if (root / path.rstrip("/")).exists()]


def build_contract(root: str | Path) -> tuple[dict[str, Any], str | None]:
    root = Path(root).resolve()
    test_command, has_tests = _detect_test_command(root)
    protected = _detect_protected(root) or ["tests/"]
    forbidden = _detect_forbidden(root) or ["ci/", ".github/workflows/"]

    verifiers: list[dict[str, Any]] = [
        {"name": "budget.steps", "required": True, "params": {"max_steps": 40}},
        {"name": "diff.syntax", "required": True},
        {
            "name": "diff.forbidden_paths",
            "required": True,
            "params": {"forbidden": forbidden},
        },
        {"name": "diff.ci_surface", "required": True},
        {
            "name": "tests.integrity",
            "required": True,
            "params": {"protected_prefixes": protected},
        },
        {"name": "tests.harness_integrity", "required": True},
        {"name": "tests.support_integrity", "required": True},
        {"name": "diff.max_lines", "required": True, "params": {"max_changed_lines": 300}},
        {"name": "diff.public_api", "required": True},
        {"name": "diff.language_coverage", "required": True},
        {"name": "quality.no_debug_prints", "required": True},
        {"name": "evidence.claims", "required": True},
    ]
    warning = None
    if has_tests:
        verifiers.append({"name": "tests.pass", "required": True})
    else:
        warning = (
            "No test suite detected. The contract has no runtime oracle; "
            "add tests or a custom verifier before enforcing it."
        )

    required = [
        tag for tag in DEFAULT_REQUIRED_DEFECTS if tag != "regression" or has_tests
    ]
    contract = {
        "name": root.name,
        "domain": "code",
        "test_command": test_command,
        "fail_fast": True,
        "human_review_cost_usd": 6.0,
        "max_verification_cost_usd": 0.05,
        "required_defects": required,
        "verifiers": verifiers,
    }
    return contract, warning


def init_project(root: str | Path = ".", force: bool = False, ci: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    directory = root / ".assaystone"
    contract_path = directory / "contract.json"
    readme_path = directory / "README.md"

    if contract_path.exists() and not force:
        raise FileExistsError(f"{contract_path} already exists; use --force to overwrite")

    contract, warning = build_contract(root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "traces").mkdir(exist_ok=True)
    (directory / "traces" / ".gitkeep").write_text("", encoding="utf-8")
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    workflow_path = None
    if ci:
        workflow_path = root / ".github" / "workflows" / "assaystone.yml"
        if workflow_path.exists() and not force:
            warning = (warning + " " if warning else "") + (
                f"{workflow_path} already exists; left unchanged"
            )
        else:
            workflow_path.parent.mkdir(parents=True, exist_ok=True)
            workflow_path.write_text(
                "name: assaystone\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  verify:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                f"      - uses: yellowsand1/assaystone@{ACTION_REF}\n"
                "        with:\n"
                "          contract: .assaystone/contract.json\n"
                "          traces: .assaystone/traces\n",
                encoding="utf-8",
            )
    readme_path.write_text(
        "# Assaystone\n\n"
        "Generated by `assaystone init`.\n\n"
        "- Contract: `.assaystone/contract.json`\n"
        "- Traces: `.assaystone/traces/`\n"
        "- Required defects: `required_defects` in the contract. Trim it to the\n"
        "  classes that matter here; `assaystone coverage` reports the rest.\n\n"
        "Adjust `test_command` and verifier params to match your repository.\n\n"
        "```bash\n"
        "assaystone verify --contract .assaystone/contract.json "
        "--trace .assaystone/traces\n"
        "pytest --assaystone-contract .assaystone/contract.json "
        "--assaystone-traces .assaystone/traces\n"
        "```\n",
        encoding="utf-8",
    )
    return {
        "contract": contract_path,
        "readme": readme_path,
        "workflow": workflow_path,
        "contract_data": contract,
        "warning": warning,
    }
