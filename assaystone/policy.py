"""Deterministic action policy for harness pre-tool gates.

A pre-tool gate decides *before* the action happens. There is no diff yet, so
the acceptance contract cannot run; the decision is made from a small, local
policy: denied tools, denied paths, denied shell patterns, and a workspace
boundary.

The decision is written to a runtime record. The agent cannot write that record,
which is what lets a later certificate treat it as evidence instead of testimony.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

POLICY_FILE = "policy.json"
ALLOW = "allow"
DENY = "deny"
_MODES = {"warn", "block"}

# Keys that carry a path the tool will write or edit.
_PATH_KEYS = ("file_path", "path", "notebook_path", "target_file")
_SECRET_KEYS = ("token", "password", "secret", "api_key", "apikey", "authorization")
_SECRET_IN_TEXT = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key|authorization)\b\s*[=:]\s*\S+"
)


class PolicyError(ValueError):
    """The policy file is not usable."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def redact(text: str, limit: int = 160) -> str:
    """Keep a preview useful without copying secrets into a record."""
    text = _SECRET_IN_TEXT.sub(lambda m: f"{m.group(1)}=***", text)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _redact_args(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***" if str(key).lower() in _SECRET_KEYS else _redact_args(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_args(item) for item in value]
    if isinstance(value, str):
        return redact(value, limit=400)
    return value


def _path_matches(path: str, pattern: str) -> bool:
    pattern = pattern.rstrip("/")
    if not pattern:
        return False
    return path == pattern or path.startswith(pattern + "/")


@dataclass
class ActionPolicy:
    mode: str = "warn"
    deny_tools: tuple[str, ...] = ()
    deny_paths: tuple[str, ...] = ()
    deny_commands: tuple[str, ...] = ()
    allow_write_roots: tuple[str, ...] = ()
    record: bool = True
    _commands: tuple[re.Pattern[str], ...] = field(default=(), repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionPolicy":
        if not isinstance(data, dict):
            raise PolicyError("policy must be a JSON object")
        mode = str(data.get("mode") or "warn").lower()
        if mode not in _MODES:
            raise PolicyError(f"unknown mode: {mode!r} (use warn or block)")

        def strings(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise PolicyError(f"{key} must be a list of strings")
            return tuple(value)

        try:
            commands = tuple(re.compile(pattern) for pattern in strings("deny_commands"))
        except re.error as exc:
            raise PolicyError(f"invalid deny_commands pattern: {exc}") from exc

        return cls(
            mode=mode,
            deny_tools=strings("deny_tools"),
            deny_paths=strings("deny_paths"),
            deny_commands=tuple(str(pattern) for pattern in strings("deny_commands")),
            allow_write_roots=strings("allow_write_roots"),
            record=bool(data.get("record", True)),
            _commands=commands,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ActionPolicy":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "deny_tools": list(self.deny_tools),
            "deny_paths": list(self.deny_paths),
            "deny_commands": list(self.deny_commands),
            "record": self.record,
        }
        if self.allow_write_roots:
            out["allow_write_roots"] = list(self.allow_write_roots)
        return out


DEFAULT_POLICY = {
    "mode": "warn",
    "deny_paths": [".github/workflows/", ".github/actions/"],
    "deny_commands": [
        r"rm\s+-rf\s+/(?:\s|$)",
        r"git\s+push\s+(?:--force|-f)\b",
        r"chmod\s+777\b",
        r"DROP\s+(?:TABLE|DATABASE)\b",
    ],
    "record": True,
}


@dataclass
class ActionDecision:
    allowed: bool
    reasons: list[str]
    rule: str = ""

    @property
    def outcome(self) -> str:
        return ALLOW if self.allowed else DENY


def _resolve_paths(tool: str, args: dict[str, Any]) -> list[str]:
    if tool.lower() in {"bash", "shell"}:
        return []
    return [str(args[key]) for key in _PATH_KEYS if isinstance(args.get(key), str) and args[key]]


def evaluate_action(
    tool: str,
    args: dict[str, Any],
    root: str | Path,
    policy: ActionPolicy,
) -> ActionDecision:
    root_path = Path(root).resolve()

    if tool in policy.deny_tools:
        return ActionDecision(False, [f"tool {tool!r} is denied"], "deny_tools")

    for raw in _resolve_paths(tool, args):
        candidate = Path(raw)
        absolute = candidate if candidate.is_absolute() else root_path / candidate
        resolved = absolute.resolve()
        if not resolved.is_relative_to(root_path):
            return ActionDecision(
                False,
                [f"{raw} is outside the workspace {root_path}"],
                "workspace_boundary",
            )
        relative = resolved.relative_to(root_path).as_posix()
        for pattern in policy.deny_paths:
            if _path_matches(relative, pattern):
                return ActionDecision(
                    False, [f"{relative} matches denied path {pattern!r}"], "deny_paths"
                )
        if policy.allow_write_roots and not any(
            _path_matches(relative, allowed) for allowed in policy.allow_write_roots
        ):
            return ActionDecision(
                False,
                [f"{relative} is outside allow_write_roots"],
                "allow_write_roots",
            )

    command = args.get("command")
    if isinstance(command, str):
        for pattern in policy._commands:
            match = pattern.search(command)
            if match:
                return ActionDecision(
                    False,
                    [f"command matches denied pattern {pattern.pattern!r}"],
                    "deny_commands",
                )

    return ActionDecision(True, [], "")


def record_path(root: str | Path) -> Path:
    return Path(root) / ".assaystone" / "session.jsonl"


def record_decision(
    root: str | Path,
    *,
    session_id: str,
    tool: str,
    args: dict[str, Any],
    decision: ActionDecision,
) -> Path | None:
    """Append a runtime-written decision. Never raises into the harness."""
    path = record_path(root)
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool": tool,
        "args_digest": digest(_redact_args(args)),
        "paths": _resolve_paths(tool, args),
        "decision": decision.outcome,
        "reasons": list(decision.reasons),
        "rule": decision.rule,
    }
    command = args.get("command")
    if isinstance(command, str):
        entry["command"] = redact(command)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return path
    except OSError:
        return None
