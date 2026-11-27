"""Turn framework message lists into Assaystone traces.

The adapter is intentionally duck-typed: it accepts dicts or SDK objects from
the Claude Agent SDK, OpenAI-style chat/tool messages, and most LangGraph
message states. It never imports a framework.

    from assaystone.adapters import from_claude_agent
    trace = from_claude_agent(messages, artifacts=artifacts, task="fix the bug")
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..model import Artifact, Step, Trace


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value} if value is not None else {}


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                text = getattr(item, "text", None)
                parts.append(str(text) if text is not None else repr(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _blocks(content: Any) -> list[Any]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    if content is None:
        return []
    return [content]


_BLOCK_TYPES = {
    "textblock": "text",
    "tooluseblock": "tool_use",
    "toolresultblock": "tool_result",
    "thinkingblock": "thinking",
}


def _block_type(block: Any) -> str:
    explicit = _get(block, "type")
    if explicit:
        return str(explicit)
    name = type(block).__name__.lower()
    return _BLOCK_TYPES.get(name, name)


def from_messages(
    messages: Sequence[Any],
    *,
    artifacts: Iterable[Artifact] | None = None,
    task: str = "",
    agent: str = "agent",
    trace_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    view: dict[str, Any] | None = None,
) -> Trace:
    """Build a Trace from a list of framework messages."""
    steps: list[Step] = []
    pending: dict[str, int] = {}
    assistant_text: list[str] = []
    input_text = ""
    final_message = ""
    result_meta: dict[str, Any] = {}
    session_id = ""

    for message in messages:
        message_type = str(_get(message, "type") or _get(message, "role") or "").lower()
        content = _get(message, "content")

        if message_type == "result":
            final_message = _stringify(_get(message, "result") or content)
            for key in (
                "subtype",
                "is_error",
                "duration_ms",
                "duration_api_ms",
                "num_turns",
                "total_cost_usd",
                "session_id",
            ):
                value = _get(message, key)
                if value is not None:
                    result_meta[key] = value
            session_id = str(_get(message, "session_id") or session_id)
            continue

        if message_type in ("system",):
            continue

        if message_type in ("assistant", "ai", "model"):
            for call in _get(message, "tool_calls") or []:
                function = _get(call, "function") or {}
                name = _get(function, "name") or _get(call, "name") or "tool"
                raw_args = _get(function, "arguments")
                if raw_args is None:
                    raw_args = _get(call, "args")  # LangChain / LangGraph shape
                step = Step(tool=str(name), args=_as_args(raw_args), result="", ok=True)
                steps.append(step)
                call_id = _get(call, "id")
                if call_id:
                    pending[str(call_id)] = len(steps) - 1

            for block in _blocks(content):
                block_type = _block_type(block)
                if block_type == "text":
                    text = _stringify(_get(block, "text"))
                    if text:
                        assistant_text.append(text)
                elif block_type == "tool_use":
                    name = _get(block, "name") or "tool"
                    step = Step(tool=str(name), args=_as_args(_get(block, "input")), result="", ok=True)
                    steps.append(step)
                    call_id = _get(block, "id")
                    if call_id:
                        pending[str(call_id)] = len(steps) - 1
            continue

        if message_type in ("user", "human"):
            for block in _blocks(content):
                block_type = _block_type(block)
                if block_type == "tool_result":
                    call_id = _get(block, "tool_use_id") or _get(block, "tool_call_id")
                    output = _stringify(_get(block, "content"))
                    is_error = bool(_get(block, "is_error", False))
                    if call_id and str(call_id) in pending:
                        step = steps[pending[str(call_id)]]
                        step.result = output
                        step.ok = not is_error
                elif block_type == "text":
                    text = _stringify(_get(block, "text"))
                    if text and not input_text:
                        input_text = text
            continue

        if message_type == "tool":
            call_id = _get(message, "tool_call_id")
            output = _stringify(content)
            is_error = bool(_get(message, "is_error", False))
            if call_id and str(call_id) in pending:
                step = steps[pending[str(call_id)]]
                step.result = output
                step.ok = not is_error

    if not final_message:
        final_message = assistant_text[-1] if assistant_text else ""

    trace_evidence = dict(evidence or {})
    if result_meta:
        trace_evidence["agent_result"] = result_meta

    return Trace(
        id=trace_id or session_id or f"trace-{int(time.time() * 1000)}",
        task=task,
        agent=agent,
        input=input_text,
        steps=steps,
        artifacts=list(artifacts or []),
        final_message=final_message,
        evidence=trace_evidence,
        view=dict(view or {}),
    )


def from_claude_agent(messages: Sequence[Any], **kwargs: Any) -> Trace:
    """Adapter for Claude Agent SDK message streams."""
    kwargs.setdefault("agent", "claude-agent-sdk")
    return from_messages(messages, **kwargs)


def from_openai_agents(messages: Sequence[Any], **kwargs: Any) -> Trace:
    """Adapter for OpenAI-style chat, tool-call, and tool-result messages."""
    kwargs.setdefault("agent", "openai-agents")
    return from_messages(messages, **kwargs)


def from_langgraph(state: Any, **kwargs: Any) -> Trace:
    """Adapter for a LangGraph state dict (or a bare message list)."""
    messages = state.get("messages", state) if isinstance(state, dict) else state
    kwargs.setdefault("agent", "langgraph")
    return from_messages(messages, **kwargs)


def artifacts_from_git(repo: str | Path, base: str = "HEAD") -> list[Artifact]:
    """Collect tracked changes vs ``base`` plus untracked files as artifacts."""

    root = Path(repo)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
        )

    diff = run("diff", "--name-only", base)
    if diff.returncode != 0:
        return []
    paths = {line.strip() for line in diff.stdout.splitlines() if line.strip()}

    untracked = run("ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        paths.update(line.strip() for line in untracked.stdout.splitlines() if line.strip())

    artifacts: list[Artifact] = []
    for relative in sorted(paths):
        path = root / relative
        if not path.exists():
            artifacts.append(Artifact(relative, "", "deleted"))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        in_base = run("cat-file", "-e", f"{base}:{relative}").returncode == 0
        artifacts.append(Artifact(relative, content, "modified" if in_base else "added"))
    return artifacts
