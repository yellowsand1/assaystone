"""Prepare a release deterministically.

The manual version of this step silently drifted: a fixed-string match stopped
matching once the Unreleased section had content, and eight changelog sections
were never written. This script either does every edit or fails before writing.

    python3 scripts/release_prep.py --version 0.18.0

It expects `docs/releases/v<version>.md` to exist and starts with `# v<version>`.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class PrepError(SystemExit):
    pass


def _replace_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise PrepError(f"{path.relative_to(REPO)}: could not {label}")
    path.write_text(new, encoding="utf-8")


def _bump(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise PrepError(f"{path.relative_to(REPO)}: {old!r} not found")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    version = args.version
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise PrepError(f"--version must be X.Y.Z, got {version!r}")

    notes = REPO / "docs" / "releases" / f"v{version}.md"
    if not notes.exists():
        raise PrepError(f"write {notes.relative_to(REPO)} first")
    first = notes.read_text(encoding="utf-8").splitlines()[0]
    if not first.startswith(f"# v{version}"):
        raise PrepError(f"{notes.relative_to(REPO)} must start with `# v{version}`")

    current = re.search(
        r'__version__ = "([^"]+)"',
        (REPO / "assaystone" / "__init__.py").read_text(encoding="utf-8"),
    )
    if not current:
        raise PrepError("cannot read __version__")
    old = current.group(1)
    if old == version:
        raise PrepError(f"version is already {version}")

    _bump(REPO / "pyproject.toml", f'version = "{old}"', f'version = "{version}"')
    _bump(
        REPO / "assaystone" / "__init__.py",
        f'__version__ = "{old}"',
        f'__version__ = "{version}"',
    )
    _bump(
        REPO / "assaystone" / "init.py",
        f'ACTION_REF = "v{old}"',
        f'ACTION_REF = "v{version}"',
    )
    _bump(REPO / "README.md", f"assaystone@v{old}", f"assaystone@v{version}")
    _bump(REPO / "README.md", f"assaystone=={old}", f"assaystone=={version}")
    _bump(REPO / "README.md", f"`v{old}` — alpha.", f"`v{version}` — alpha.")
    _bump(REPO / "docs" / "release.md", f"git tag v{old}", f"git tag v{version}")
    _bump(
        REPO / "docs" / "release.md",
        f"git push origin v{old}",
        f"git push origin v{version}",
    )

    changelog = REPO / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    match = re.search(
        r"^## Unreleased\n(?P<body>.*?)(?=^## )", text, re.MULTILINE | re.DOTALL
    )
    if not match:
        raise PrepError("CHANGELOG.md has no `## Unreleased` section")
    body = match.group("body").strip()
    if not body or body == "No changes yet.":
        raise PrepError("the Unreleased section has no entries to release")
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section = f"## Unreleased\n\nNo changes yet.\n\n## {version} — {date}\n\n{body}\n\n"
    changelog.write_text(
        text[: match.start()] + section + text[match.end() :], encoding="utf-8"
    )
    print(f"prepared {version}; review the diff, then tag v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
