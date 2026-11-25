"""Claude Code Stop hook: audit the session transcript before the agent stops.

Install:

    assaystone hook install claude-code --mode warn

Environment / config:
    ASSAYSTONE_HOOK_MODE=warn|block      (default: warn)
    ASSAYSTONE_HOOK_FAIL_ON=none|high|any (default: high)
    .assaystone/hook.json:
        {"mode": "warn", "fail_on": "high",
         "ignore": [{"verifier": "tests.integrity",
                     "paths": ["server/tests/**"]}]}
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from ..adapters.messages import artifacts_from_git
from ..audit import AuditReport, audit_traces, build_audit_contract, load_audit_traces
from ..replay import git_preimage, is_git_repo, is_git_root


def _compact_message(report: AuditReport) -> str:
    counts = report.severity_counts()
    lines = [
        "Assaystone audit: "
        f"{counts['critical']} critical, {counts['high']} high, "
        f"{counts['medium']} medium, {counts['low']} low"
    ]
    for finding in report.findings[:5]:
        reason = finding.reasons[0] if finding.reasons else ""
        if len(reason) > 100:
            reason = reason[:97] + "..."
        label = "REVIEW" if finding.outcome == "escalate" else finding.severity.upper()
        lines.append(f"  {label:<8} {finding.verifier:<24} {reason}")
    if len(report.findings) > 5:
        lines.append(f"  ... {len(report.findings) - 5} more")
    lines.append("Full report: assaystone audit <transcript> --baseline .")
    return "\n".join(lines)


def _load_config(cwd: Path) -> dict[str, Any]:
    path = cwd / ".assaystone" / "hook.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _filter_report(report: AuditReport, config: dict[str, Any]) -> AuditReport:
    rules = config.get("ignore") or []
    if not isinstance(rules, list) or not rules:
        return report
    traces = {trace.id: trace for trace in report.traces}
    kept = []
    for finding in report.findings:
        trace = traces.get(finding.trace_id)
        paths = [artifact.path for artifact in trace.artifacts] if trace else []
        ignored = False
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            verifier = rule.get("verifier")
            if verifier and verifier != finding.verifier:
                continue
            patterns = rule.get("paths") or []
            reason_contains = rule.get("reason_contains")
            path_match = bool(patterns) and any(
                fnmatch.fnmatch(path, pattern) for path in paths for pattern in patterns
            )
            reason_match = bool(reason_contains) and any(
                reason_contains in reason for reason in finding.reasons
            )
            if patterns or reason_contains:
                if path_match or reason_match:
                    ignored = True
                    break
            else:
                ignored = True
                break
        if not ignored:
            kept.append(finding)
    return AuditReport(
        baseline=report.baseline,
        traces=report.traces,
        findings=kept,
        suggested_contract=report.suggested_contract,
        warnings=report.warnings,
    )


def _state_file(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return cache / "assaystone" / "hooks" / f"{safe}.json"


def _is_duplicate(session_id: str, message: str) -> bool:
    if not session_id:
        return False
    path = _state_file(session_id)
    signature = hashlib.sha256(message.encode("utf-8")).hexdigest()
    try:
        previous = json.loads(path.read_text(encoding="utf-8")).get("signature")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        previous = None
    if previous == signature:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"signature": signature, "updated_at": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return False


def _compact_gate(result: Any) -> str:
    lines = [
        f"Assaystone gate: {result.capability} at {result.stage} -> {result.outcome}"
    ]
    for item in result.results:
        if item.outcome == "pass":
            continue
        reason = item.reasons[0] if item.reasons else ""
        lines.append(f"  {item.outcome.upper():<8} {item.oracle:<20} {reason[:90]}")
    for reason in result.reasons[:3]:
        if reason:
            lines.append(f"  {reason[:110]}")
    return "\n".join(lines)


def _capability_gate(
    cwd: Path, config: dict[str, Any]
) -> tuple[Any | None, str]:
    ref = config.get("capability")
    if not ref:
        return None, ""
    try:
        from ..plane import CapabilityManifest, evaluate_gate

        path = Path(str(ref))
        if not path.is_absolute():
            path = cwd / path
        manifest = CapabilityManifest.load(path)
        stage = str(config.get("stage") or "shadow")
        return evaluate_gate(manifest, stage, cwd), ""
    except Exception as exc:  # noqa: BLE001 - a hook must not break the session
        return None, f"assaystone: capability gate failed: {exc}"


def _hook_mode(config: dict[str, Any]) -> str:
    return (
        os.environ.get("ASSAYSTONE_HOOK_MODE")
        or config.get("mode")
        or "warn"
    ).lower()


def run_hook(payload: dict[str, Any]) -> tuple[int, str]:
    if payload.get("stop_hook_active"):
        return 0, ""
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    config = _load_config(cwd)
    mode = _hook_mode(config)
    session_id = str(payload.get("session_id") or "")

    gate_result, gate_error = _capability_gate(cwd, config)
    gate_failed = bool(
        gate_result is not None and gate_result.outcome != "pass"
    )
    gate_message = ""
    if gate_result is not None and gate_failed:
        gate_message = _compact_gate(gate_result)

    transcript = payload.get("transcript_path")
    audit_message = ""
    audit_blocked = False
    audit_error = ""
    if transcript:
        transcript_path = Path(str(transcript))
        if not transcript_path.is_absolute():
            transcript_path = cwd / transcript_path
        try:
            traces = load_audit_traces(
                transcript_path, baseline=cwd, workspace=True
            )
            # Bash is the dominant edit channel in real sessions. When cwd is
            # the git root, merge working-tree changes so sed/tee/patch edits
            # are seen.
            if is_git_root(cwd) and traces:
                existing = {
                    artifact.path
                    for trace in traces
                    for artifact in trace.artifacts
                }
                extra = [
                    artifact
                    for artifact in artifacts_from_git(cwd)
                    if artifact.path not in existing
                ]
                if extra:
                    traces[0].artifacts.extend(extra)
            contract = build_audit_contract(cwd)
            report = None
            if is_git_repo(cwd):
                preimage = git_preimage(
                    cwd,
                    [
                        artifact.path
                        for trace in traces
                        for artifact in trace.artifacts
                    ],
                )
                try:
                    report = audit_traces(contract, traces, preimage.name)
                finally:
                    preimage.cleanup()
                report.baseline = cwd
            if report is None:
                report = audit_traces(contract, traces, cwd)
            report = _filter_report(report, config)
            if report.findings:
                audit_message = _compact_message(report)
                fail_on = (
                    os.environ.get("ASSAYSTONE_HOOK_FAIL_ON")
                    or config.get("fail_on")
                    or "high"
                )
                audit_blocked = mode == "block" and bool(
                    report.exit_code(fail_on)
                )
        except Exception as exc:  # noqa: BLE001
            audit_error = f"assaystone: audit failed: {exc}"
    elif gate_result is None and not gate_error:
        return 0, "assaystone: hook payload has no transcript_path"

    if gate_error:
        message = gate_error
        if audit_message:
            message = message + "\n\n" + audit_message
        if _is_duplicate(session_id, message):
            return 0, ""
        return 0, message
    if audit_error and not gate_failed:
        return 0, audit_error
    if not gate_failed and not audit_message and not audit_error:
        return 0, ""

    parts = []
    if gate_message:
        parts.append(gate_message)
    if audit_message:
        parts.append(audit_message)
    if audit_error:
        parts.append(audit_error)
    message = "\n\n".join(parts)

    if mode == "block" and (gate_failed or audit_blocked):
        return 2, message + (
            "\n\nAssaystone blocked the stop. Fix the gate or set "
            "ASSAYSTONE_HOOK_MODE=warn."
        )
    if _is_duplicate(session_id, message):
        return 0, ""
    return 0, message + "\n\nSet ASSAYSTONE_HOOK_MODE=block to enforce."


def install_claude_code(
    settings_path: str | Path,
    mode: str = "warn",
    manifest: str | None = None,
    stage: str = "shadow",
) -> tuple[Path, bool]:
    """Merge the Stop hook into a Claude Code settings file. Returns (path, changed).

    With ``manifest``, also write the project's ``.assaystone/hook.json`` so the
    Stop hook runs that capability gate before the session ends.
    """
    target = Path(settings_path)
    command = "assaystone hook claude-code"
    if mode == "block":
        command = "ASSAYSTONE_HOOK_MODE=block " + command
    try:
        settings = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        settings = {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target}: invalid JSON ({exc})") from exc
    if not isinstance(settings, dict):
        raise ValueError(f"{target}: expected a JSON object")

    hooks = settings.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    settings_changed = True
    for group in stop:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []) or []:
            if isinstance(hook, dict) and hook.get("command") == command:
                settings_changed = False
                break
        if not settings_changed:
            break
    if settings_changed:
        stop.append({"hooks": [{"type": "command", "command": command}]})
    target.parent.mkdir(parents=True, exist_ok=True)
    if settings_changed:
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    config_changed = False
    if manifest:
        root = (
            target.parent.parent
            if target.parent.name == ".claude"
            else target.parent
        )
        config_path = root / ".assaystone" / "hook.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        if (
            config.get("capability") != manifest
            or config.get("stage") != stage
        ):
            config_changed = True
        config["capability"] = manifest
        config["stage"] = stage
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
    return target, settings_changed or config_changed


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"assaystone hook: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("assaystone hook: expected a JSON object on stdin", file=sys.stderr)
        return 0
    code, message = run_hook(payload)
    if message:
        print(message, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
