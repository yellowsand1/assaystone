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
from ..certificate import build_certificate
from ..certificate import to_json as certificate_json
from ..contract import Contract
from ..episode import EpisodeError, GitEpisode
from ..policy import (
    DEFAULT_POLICY,
    POLICY_FILE,
    ActionDecision,
    ActionPolicy,
    PolicyError,
    evaluate_action,
    paths_for,
    record_decision,
    scan_secrets,
)
from ..replay import git_preimage, is_git_repo, is_git_root
from ..runner import run_contract


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


def _write_runtime_record(
    cwd: Path,
    config: dict[str, Any],
    payload: dict[str, Any],
    gate_result: Any | None,
    findings: int,
) -> None:
    """Record what this supervisor saw. Never claims more than it observed."""
    if config.get("record") is False:
        return
    try:
        from ..session_record import write_record

        paths = {
            str(item)
            for item in (config.get("record_paths") or [])
            if isinstance(item, str)
        }
        if is_git_root(cwd):
            for artifact in artifacts_from_git(cwd):
                # The evidence directory is not the work under review, and it
                # changes when the record is written.
                if artifact.path == ".assaystone" or artifact.path.startswith(
                    ".assaystone/"
                ):
                    continue
                paths.add(artifact.path)
        entry_hash = ""
        trail_ref = config.get("trail")
        if gate_result is not None and trail_ref:
            from ..trail import append as append_trail

            target = Path(str(trail_ref))
            if not target.is_absolute():
                target = cwd / target
            actor = os.environ.get("ASSAYSTONE_ACTOR") or os.environ.get(
                "USER"
            ) or "hook"
            try:
                entry_hash = str(append_trail(target, gate_result, actor=actor)
                                 .get("hash", ""))
            except Exception:  # noqa: BLE001 - the record is still useful
                entry_hash = ""
        write_record(
            cwd,
            session_id=str(payload.get("session_id") or ""),
            relative_paths=paths,
            gate=gate_result,
            findings=findings,
            commit=str(getattr(gate_result, "commit", "") or ""),
            entry_hash=entry_hash,
        )
    except Exception:  # noqa: BLE001 - a hook must not break the session
        return


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
        return (
            evaluate_gate(
                manifest, stage, cwd, skip_types={"runtime", "drill"}
            ),
            "",
        )
    except Exception as exc:  # noqa: BLE001 - a hook must not break the session
        return None, f"assaystone: capability gate failed: {exc}"


def _hook_mode(config: dict[str, Any]) -> str:
    return (
        os.environ.get("ASSAYSTONE_HOOK_MODE")
        or config.get("mode")
        or "warn"
    ).lower()


def _run_final_gate(cwd: Path, config: dict[str, Any]) -> tuple[int, str]:
    """Run the contract on the working tree before the session stops.

    This is the pre-final position: the same contract as CI, with the same
    certificate, evaluated while the agent can still fix the work.
    """
    gate = config.get("gate")
    if not isinstance(gate, dict):
        return 0, ""
    ref = str(gate.get("contract") or ".assaystone/contract.json")
    contract_path = Path(ref)
    if not contract_path.is_absolute():
        contract_path = cwd / contract_path
    try:
        contract = Contract.load(contract_path)
    except (OSError, ValueError, KeyError) as exc:
        return 0, f"assaystone: final gate contract is not readable: {exc}"

    base = str(gate.get("base") or "HEAD")
    try:
        with GitEpisode(cwd, base=base) as episode:
            result = run_contract(contract, episode.trace, episode.baseline)
            document = build_certificate(
                result, contract, episode.trace, provenance=episode.provenance
            )
    except EpisodeError as exc:
        return 0, f"assaystone: final gate skipped: {exc}"

    cert_dir = cwd / ".assaystone" / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / f"{document['subject']['trace_id']}.certificate.json"
    cert_path.write_text(certificate_json(document), encoding="utf-8")

    if result.verdict == "pass":
        return 0, ""
    lines = [f"Assaystone final gate: {result.verdict.upper()}"]
    for verdict in result.verdicts:
        if verdict.outcome == "pass":
            continue
        reason = verdict.reasons[0] if verdict.reasons else ""
        lines.append(f"  {verdict.outcome.upper():<8} {verdict.verifier:<24} {reason[:120]}")
    lines.append(f"certificate: {cert_path}")
    mode = (os.environ.get("ASSAYSTONE_HOOK_MODE") or config.get("mode") or "warn").lower()
    if mode == "block":
        return 2, "\n".join(lines) + "\n\nFix the findings and continue."
    return 0, "\n".join(lines) + "\n\nSet mode=block to enforce."


def run_hook(payload: dict[str, Any]) -> tuple[int, str]:
    if payload.get("stop_hook_active"):
        return 0, ""
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    config = _load_config(cwd)
    mode = _hook_mode(config)
    session_id = str(payload.get("session_id") or "")

    if config.get("gate"):
        return _run_final_gate(cwd, config)

    gate_result, gate_error = _capability_gate(cwd, config)
    gate_failed = bool(
        gate_result is not None and gate_result.outcome != "pass"
    )
    gate_message = ""
    if gate_result is not None and gate_failed:
        gate_message = _compact_gate(gate_result)

    transcript = payload.get("transcript_path")
    audit_findings = 0
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
            audit_findings = len(report.findings)
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

    _write_runtime_record(cwd, config, payload, gate_result, audit_findings)

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


def _load_action_policy(cwd: Path) -> tuple[ActionPolicy | None, str]:
    path = cwd / ".assaystone" / POLICY_FILE
    try:
        return ActionPolicy.load(path), ""
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError, PolicyError) as exc:
        return None, f"assaystone: pre-tool policy is not usable: {exc}"


def run_pre_hook(payload: dict[str, Any]) -> tuple[int, str]:
    """Decide one tool call before it executes.

    Exit 2 blocks the call in Claude Code and shows stderr to the model. A
    missing policy is passive on purpose: installing a hook must not silently
    start denying work.
    """
    event = str(payload.get("hook_event_name") or "PreToolUse")
    if event != "PreToolUse":
        return 0, ""
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    policy, error = _load_action_policy(cwd)
    if error:
        return 0, error
    if policy is None:
        return 0, ""

    tool = str(payload.get("tool_name") or "")
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        args = {}
    decision = evaluate_action(tool, args, cwd, policy)
    if policy.record:
        record_decision(
            cwd,
            session_id=str(payload.get("session_id") or ""),
            tool=tool,
            args=args,
            decision=decision,
        )

    mode = (
        os.environ.get("ASSAYSTONE_HOOK_MODE") or policy.mode or "warn"
    ).lower()
    if decision.allowed:
        return 0, ""
    reason = decision.reasons[0] if decision.reasons else "denied by policy"
    rule = f" (rule: {decision.rule})" if decision.rule else ""
    message = f"Assaystone pre-tool gate: {tool} denied — {reason}{rule}"
    if mode == "block":
        return 2, message + "\n\nSet mode=warn in .assaystone/policy.json to report only."
    return 0, message + "\n\nSet mode=block in .assaystone/policy.json to enforce."


_WRITE_TOOLS = {
    "write",
    "write_file",
    "create_file",
    "create",
    "edit",
    "str_replace",
    "replace_in_file",
    "str_replace_editor",
    "multiedit",
}


def _post_violations(
    tool: str, args: dict[str, Any], response: Any, policy: ActionPolicy, cwd: Path
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    paths = paths_for(tool, args)
    if policy.post_syntax and tool.lower() in _WRITE_TOOLS:
        import ast

        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = cwd / path
            if path.suffix != ".py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                ast.parse(text)
            except SyntaxError as exc:
                violations.append(f"{raw}: syntax error: {exc.msg} (line {exc.lineno})")
    if policy.post_secrets:
        candidates: list[Any] = [
            args.get("content"),
            args.get("new_string"),
            args.get("command"),
        ]
        if isinstance(response, dict):
            candidates.extend(
                [response.get("stdout"), response.get("output"), response.get("content")]
            )
        elif isinstance(response, str):
            candidates.append(response)
        for text in candidates:
            if not isinstance(text, str):
                continue
            for kind in scan_secrets(text):
                violations.append(f"{kind} in {tool} output")
    # Stable order, no duplicates.
    return sorted(set(violations)), paths


def run_post_hook(payload: dict[str, Any]) -> tuple[int, str]:
    """Check what the action produced, then feed the defect back to the model.

    Exit 2 in Claude Code shows stderr to the model and lets it correct on the
    next step. The action already happened; this is the earliest point where the
    result can be checked without undoing it.
    """
    event = str(payload.get("hook_event_name") or "PostToolUse")
    if event != "PostToolUse":
        return 0, ""
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    policy, error = _load_action_policy(cwd)
    if error:
        return 0, error
    if policy is None:
        return 0, ""

    tool = str(payload.get("tool_name") or "")
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        args = {}
    violations, paths = _post_violations(
        tool, args, payload.get("tool_response"), policy, cwd
    )
    decision = ActionDecision(
        allowed=not violations,
        reasons=violations,
        rule="post_conditions" if violations else "",
    )
    if policy.record:
        record_decision(
            cwd,
            session_id=str(payload.get("session_id") or ""),
            tool=tool,
            args=args,
            decision=decision,
            phase="post",
            details={"violations": violations, "paths": paths},
        )
    if not violations:
        return 0, ""

    mode = (os.environ.get("ASSAYSTONE_HOOK_MODE") or policy.mode or "warn").lower()
    message = "Assaystone post-tool: " + "; ".join(violations[:3])
    if mode == "block":
        return 2, message + "\n\nFix the file and continue."
    return 0, message + "\n\nSet mode=block in .assaystone/policy.json to enforce."


def _ensure_command_hook(
    hooks: dict[str, Any],
    event: str,
    command: str,
    matcher: str | None = None,
) -> bool:
    groups = hooks.setdefault(event, [])
    for group in groups:
        if not isinstance(group, dict):
            continue
        if matcher is not None and group.get("matcher") not in (None, matcher):
            continue
        for hook in group.get("hooks", []) or []:
            if isinstance(hook, dict) and hook.get("command") == command:
                return False
    entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    groups.append(entry)
    return True


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
    settings_changed = _ensure_command_hook(hooks, "Stop", command)
    pre_command = "assaystone hook claude-code-pre"
    if mode == "block":
        pre_command = "ASSAYSTONE_HOOK_MODE=block " + pre_command
    settings_changed = (
        _ensure_command_hook(hooks, "PreToolUse", pre_command, matcher="*")
        or settings_changed
    )
    post_command = "assaystone hook claude-code-post"
    if mode == "block":
        post_command = "ASSAYSTONE_HOOK_MODE=block " + post_command
    settings_changed = (
        _ensure_command_hook(hooks, "PostToolUse", post_command, matcher="*")
        or settings_changed
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if settings_changed:
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    root = (
        target.parent.parent
        if target.parent.name == ".claude"
        else target.parent
    )
    policy_path = root / ".assaystone" / POLICY_FILE
    if not policy_path.exists():
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps(DEFAULT_POLICY, indent=2) + "\n", encoding="utf-8"
        )
    config_changed = False
    if manifest:
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


def main_pre() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"assaystone hook: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("assaystone hook: expected a JSON object on stdin", file=sys.stderr)
        return 0
    code, message = run_pre_hook(payload)
    if message:
        print(message, file=sys.stderr if code == 2 else sys.stdout)
    return code


def main_post() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"assaystone hook: invalid JSON on stdin: {exc}", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        print("assaystone hook: expected a JSON object on stdin", file=sys.stderr)
        return 0
    code, message = run_post_hook(payload)
    if message:
        print(message, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
