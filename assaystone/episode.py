"""An episode is one unit of agent work, reconstructed from a repository.

The recorded-trace path is precise but demands that something already wrote a
trace. The common case is simpler: an agent changed a working tree, and a
reviewer wants a decision before merging. This module builds the episode from
git itself — the base ref, the working tree, and the untracked files — so that
``assaystone check`` needs no instrumentation at all.

Provenance matters here. The artifacts are read from disk by the checker, not
reported by the agent, so the trace is marked ``source="runtime"``. That is what
keeps a testimony-reading check from being trusted just because the worktree
happened to contain a file.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .model import Artifact, Trace

DEFAULT_MAX_FILES = 2000


class EpisodeError(ValueError):
    """The repository cannot be turned into an episode."""


def _git(root: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=text,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise EpisodeError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise EpisodeError("git timed out while reading the repository") from exc


def git_root(repo: str | Path) -> Path:
    root = Path(repo).resolve()
    result = _git(root, "rev-parse", "--show-toplevel")
    if result.returncode != 0 or not result.stdout.strip():
        raise EpisodeError(f"{root} is not a git repository")
    return Path(result.stdout.strip()).resolve()


def git_head(root: Path) -> str:
    result = _git(root, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""


def _resolve_base(root: Path, base: str) -> str:
    result = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    if result.returncode != 0:
        raise EpisodeError(f"cannot resolve base ref {base!r}")
    return result.stdout.strip()


def _name_status(root: Path, base: str) -> list[tuple[str, str, str]]:
    """Return (status, old_path, new_path) for the base..worktree diff.

    ``-z`` keeps paths with spaces intact. The status token and the path are
    NUL-separated; renames and copies carry a second path.
    """
    result = _git(root, "diff", "--name-status", "-z", "--find-renames", base, text=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise EpisodeError(f"git diff failed: {message or 'unknown error'}")
    tokens = [token for token in result.stdout.split(b"\0") if token]
    entries: list[tuple[str, str, str]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index].decode("utf-8", "replace")
        index += 1
        if not status:
            continue
        letter = status[0]
        if letter in ("R", "C"):
            if index + 1 >= len(tokens):
                break
            old = tokens[index].decode("utf-8", "replace")
            new = tokens[index + 1].decode("utf-8", "replace")
            index += 2
            entries.append((letter, old, new))
        else:
            if index >= len(tokens):
                break
            path = tokens[index].decode("utf-8", "replace")
            index += 1
            entries.append((letter, path, path))
    return entries


def _untracked(root: Path) -> list[str]:
    result = _git(root, "ls-files", "--others", "--exclude-standard", "-z", text=False)
    if result.returncode != 0:
        return []
    return [
        token.decode("utf-8", "replace")
        for token in result.stdout.split(b"\0")
        if token
    ]


def _read(root: Path, relative: str) -> tuple[str, str]:
    """Read a file as text, or say why it was skipped."""
    try:
        return (root / relative).read_text(encoding="utf-8"), ""
    except UnicodeDecodeError:
        return "", "binary"
    except FileNotFoundError:
        return "", "missing"
    except OSError as exc:
        return "", f"unreadable: {exc}"


def diff_artifacts(root: Path, base: str) -> tuple[list[Artifact], list[str]]:
    """Build artifacts for every change between ``base`` and the working tree."""
    artifacts: list[Artifact] = []
    skipped: list[str] = []
    for status, old, new in _name_status(root, base):
        letter = status[0]
        if letter == "D":
            artifacts.append(Artifact(old, "", "deleted"))
            continue
        if letter in ("R", "C"):
            if letter == "R":
                artifacts.append(Artifact(old, "", "deleted"))
            content, reason = _read(root, new)
            if reason:
                skipped.append(f"{new} ({reason})")
            else:
                artifacts.append(Artifact(new, content, "added"))
            continue
        content, reason = _read(root, new)
        if reason:
            skipped.append(f"{new} ({reason})")
            continue
        artifacts.append(Artifact(new, content, "added" if letter == "A" else "modified"))
    for path in _untracked(root):
        content, reason = _read(root, path)
        if reason:
            skipped.append(f"{path} ({reason})")
            continue
        artifacts.append(Artifact(path, content, "added"))
    artifacts.sort(key=lambda item: item.path)
    return artifacts, skipped


@dataclass
class GitEpisode:
    """A working-tree episode and the base tree it is compared against.

    Use as a context manager: the baseline is a temporary git worktree at the
    base commit, and it is removed on exit.
    """

    repo: str | Path = "."
    base: str = "HEAD"
    task: str = ""
    agent: str = "working-tree"
    max_files: int = DEFAULT_MAX_FILES
    trace: Trace | None = None
    baseline: Path | None = None
    provenance: dict = field(default_factory=dict)
    _tmp: tempfile.TemporaryDirectory | None = None
    _root: Path | None = None

    def __enter__(self) -> "GitEpisode":
        root = git_root(self.repo)
        base_sha = _resolve_base(root, self.base)
        artifacts, skipped = diff_artifacts(root, base_sha)
        if not artifacts:
            raise EpisodeError(
                f"no changes between {self.base} and the working tree; nothing to check"
            )
        if len(artifacts) > self.max_files:
            raise EpisodeError(
                f"{len(artifacts)} changed files exceeds --max-files {self.max_files}; "
                "narrow the check or raise the limit"
            )

        tmp = tempfile.TemporaryDirectory(prefix="assaystone-base-")
        tree = Path(tmp.name) / "tree"
        added = _git(root, "worktree", "add", "--detach", "--quiet", str(tree), base_sha)
        if added.returncode != 0:
            message = added.stderr.strip() or "unknown error"
            raise EpisodeError(f"cannot create the base worktree: {message}")

        body = {
            "base": self.base,
            "base_sha": base_sha,
            "head": git_head(root),
            "artifacts": [[artifact.path, artifact.change] for artifact in artifacts],
        }
        fingerprint = hashlib.sha256(
            repr(sorted(body["artifacts"])).encode("utf-8")
        ).hexdigest()[:12]

        self._root = root
        self._tmp = tmp
        self.baseline = tree
        self.trace = Trace(
            id=f"git-{base_sha[:8]}-{fingerprint}",
            task=self.task,
            agent=self.agent,
            input="",
            steps=[],
            artifacts=artifacts,
            final_message="",
            evidence={
                "git_base": self.base,
                "git_base_sha": base_sha,
                "git_head": body["head"],
                "skipped": skipped,
            },
            source="runtime",
        )
        self.provenance = {
            "kind": "git_worktree",
            "repo": str(root),
            "base": self.base,
            "base_sha": base_sha,
            "head": body["head"],
            "dirty": True,
            "skipped": skipped,
        }
        return self

    def __exit__(self, *exc: object) -> None:
        if self._root is not None and self.baseline is not None:
            _git(self._root, "worktree", "remove", "--force", str(self.baseline))
        if self._tmp is not None:
            self._tmp.cleanup()
        self._tmp = None
