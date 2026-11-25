"""Command line interface for Assaystone."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, demo
from . import keys as signing_keys
from . import trail as audit_trail
from .approval import (
    DEFAULT_OWNER_KEY_ENV,
    ApprovalError,
    approval_path_for,
    create_approval,
)
from .audit import AuditError, audit_traces, build_audit_contract, load_audit_traces, render_audit
from .backtest import backtest
from .brief import render_brief
from .card import build_card, render_card
from .compose import compose, render_plan
from .contract import Contract
from .corpus import CorpusError, add_case, case_outcome
from .coverage import analyze_coverage, render_coverage
from .failure_zoo import (
    DEFAULT_CORPUS,
    DEFAULT_THRESHOLDS,
    BenchmarkError,
    render_summary,
    run_benchmark,
)
from .goodhart import (
    GOODHART_CORPUS,
    GOODHART_THRESHOLDS,
    run_goodhart,
)
from .goodhart import (
    render_summary as render_goodhart_summary,
)
from .hooks.claude_code import install_claude_code
from .hooks.claude_code import main as claude_code_hook_main
from .init import init_project
from .leaderboard import LeaderboardError, run_leaderboard
from .leaderboard import render_summary as render_leaderboard
from .model import ESCALATE, FAIL, PASS, load_traces
from .mutate import run_mutation
from .oracles import OracleError, OracleRegistry
from .plane import (
    GATING_SEVERITIES,
    CapabilityManifest,
    PlaneError,
    evaluate_gate,
    render_gate,
)
from .portfolio import build_portfolio, render_portfolio
from .protocol import (
    check_contract,
    check_manifest,
    describe_protocol,
    render_protocol,
    write_schemas,
)
from .receipt import (
    DEFAULT_KEY_ENV,
    ReceiptError,
    create_receipt,
    load_receipt,
    render_check,
    verify_receipt,
)
from .replay import git_preimage, is_git_repo
from .reportcard import run_report_card
from .reports import write_audit_junit, write_audit_sarif, write_junit, write_sarif
from .runner import run_contract
from .scaffold import (
    ScaffoldError,
    display_path,
    init_capability,
    next_steps,
)
from .sessions import SessionDiscoveryError, find_latest_session
from .waiver import (
    WaiverError,
    create_waiver,
    load_waivers,
    waiver_path_for,
)


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _load_contract(path: str) -> Contract | None:
    try:
        return Contract.load(path)
    except FileNotFoundError:
        print(f"error: contract not found: {path}", file=sys.stderr)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"error: invalid contract {path}: {exc}", file=sys.stderr)
    return None


def _load_traces_arg(path: str):
    try:
        traces = load_traces(path)
    except FileNotFoundError:
        print(f"error: trace path not found: {path}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"error: invalid trace JSON in {path}: {exc}", file=sys.stderr)
        return None
    if not traces:
        print(f"error: no trace files found in {path}", file=sys.stderr)
        return None
    return traces


def _summary(results: list) -> dict:
    return {
        "total": len(results),
        "pass": sum(1 for result in results if result.verdict == PASS),
        "fail": sum(1 for result in results if result.verdict == FAIL),
        "escalate": sum(1 for result in results if result.verdict == ESCALATE),
        "cost_usd": round(sum(result.cost_usd for result in results), 8),
    }


def _gh_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit_github(results: list) -> None:
    for result in results:
        if result.verdict == FAIL:
            reason = result.first_failure or "contract failed"
            print(f"::error title=Assaystone {_gh_escape(result.trace_id)}::{_gh_escape(reason)}")
        elif result.verdict == ESCALATE:
            reason = result.first_failure or "needs human review"
            print(f"::warning title=Assaystone {_gh_escape(result.trace_id)}::{_gh_escape(reason)}")


def _write_github_outputs(results: list) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    if any(result.verdict == FAIL for result in results):
        verdict = FAIL
    elif any(result.verdict == ESCALATE for result in results):
        verdict = ESCALATE
    else:
        verdict = PASS
    findings = sum(
        1
        for result in results
        for finding in result.verdicts
        if finding.outcome != PASS
    )
    values = {
        "verdict": verdict,
        "findings": findings,
        "traces": len(results),
    }
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _write_step_summary(contract: Contract, results: list) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        f"## Assaystone — `{contract.name}`",
        "",
        "| trace | verdict | reason |",
        "|---|---|---|",
    ]
    for result in results:
        reason = (result.first_failure or "").replace("|", "\\|")
        lines.append(f"| `{result.trace_id}` | {result.verdict} | {reason} |")
    lines.append("")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _strip_evidence(results: list) -> None:
    for result in results:
        for verdict in result.verdicts:
            verdict.evidence = []


def _strip_audit_evidence(report) -> None:
    for finding in report.findings:
        finding.evidence = []


def cmd_verify(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract)
    if contract is None:
        return 1
    traces = _load_traces_arg(args.trace)
    if traces is None:
        return 1
    baseline = Path(args.baseline)
    results = [run_contract(contract, trace, baseline) for trace in traces]
    if args.no_evidence:
        _strip_evidence(results)

    if not args.json:
        if args.sarif:
            print(f"sarif: {_display(write_sarif(args.sarif, traces, results, __version__))}")
        if args.junit:
            print(f"junit: {_display(write_junit(args.junit, results))}")

    if args.json:
        print(
            json.dumps(
                {
                    "contract": contract.name,
                    "summary": _summary(results),
                    "results": [result.to_dict() for result in results],
                },
                indent=2,
            )
        )
    else:
        for trace, result in zip(traces, results, strict=True):
            print(
                f"{trace.id:<24} {result.verdict.upper():<9} "
                f"{result.cost_usd:.6f} USD  {result.duration_ms:.1f} ms"
            )
            for verdict in result.verdicts:
                mark = {PASS: "+", FAIL: "x", ESCALATE: "?"}[verdict.outcome]
                print(f"  [{mark}] {verdict.verifier:<24} {verdict.layer:<3} {verdict.duration_ms:6.1f} ms")
                for reason in verdict.reasons[:3]:
                    print(f"      {reason}")

    if args.github:
        _emit_github(results)
        _write_step_summary(contract, results)
        _write_github_outputs(results)

    if any(result.verdict == FAIL for result in results):
        return 1
    if any(result.verdict == ESCALATE for result in results):
        return 2
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    source = args.source
    baseline = Path(args.baseline or ".")
    audit_format = args.format
    git_repo = args.git_repo
    if args.latest:
        if source:
            print("error: use either a source path or --latest, not both", file=sys.stderr)
            return 2
        try:
            session = find_latest_session(args.latest)
        except SessionDiscoveryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = str(session.path)
        if args.baseline is None:
            baseline = session.cwd or Path.cwd()
        if audit_format == "auto":
            audit_format = args.latest
        if git_repo is None and is_git_repo(baseline):
            git_repo = str(baseline)
        if not args.json:
            print(
                f"latest {args.latest} session: {session.path}",
                file=sys.stderr,
            )
    if not source:
        print("error: provide a trace path or use --latest {claude-code,codex}", file=sys.stderr)
        return 2

    try:
        traces = load_audit_traces(
            source,
            format=audit_format,
            git_repo=git_repo,
            baseline=baseline,
            workspace=args.workspace or args.git_preimage,
        )
    except AuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not traces:
        print(f"error: no traces found in {source}", file=sys.stderr)
        return 2

    contract = build_audit_contract(baseline, run_tests=args.run_tests)
    report = None
    if args.git_preimage:
        if not is_git_repo(baseline):
            print(
                "warning: --git-preimage requires a git repository; using the working tree",
                file=sys.stderr,
            )
        else:
            preimage = git_preimage(
                baseline,
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
            report.baseline = baseline.resolve()
    if report is None:
        report = audit_traces(contract, traces, baseline)
    if args.no_evidence:
        _strip_audit_evidence(report)

    if args.sarif:
        path = write_audit_sarif(args.sarif, report, __version__)
        if not args.json:
            print(f"sarif: {_display(path)}")
    if args.junit:
        path = write_audit_junit(args.junit, report)
        if not args.json:
            print(f"junit: {_display(path)}")

    written = None
    if args.write_contract:
        written = _display(report.write_contract(args.write_contract))

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_audit(report, written_to=written))
    return report.exit_code(args.fail_on)


def cmd_record(args: argparse.Namespace) -> int:
    try:
        traces = load_audit_traces(
            args.transcript,
            format=args.format,
            git_repo=args.git_repo,
            baseline=args.baseline,
            workspace=args.workspace,
        )
    except AuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not traces:
        print(f"error: no traces found in {args.transcript}", file=sys.stderr)
        return 1
    if len(traces) != 1:
        print(
            f"error: expected one trace, got {len(traces)}; use `audit` for directories",
            file=sys.stderr,
        )
        return 1
    trace = traces[0]
    if args.trace_id:
        trace.id = args.trace_id
    if args.task:
        trace.task = args.task
    if args.agent:
        trace.agent = args.agent
    if args.out == "-":
        print(json.dumps(trace.to_dict(), indent=2, ensure_ascii=False))
    else:
        trace.save(args.out)
        print(f"recorded {args.out} ({len(trace.steps)} steps, {len(trace.artifacts)} artifacts)")
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract)
    if contract is None:
        return 2
    traces = None
    if args.trace:
        traces = _load_traces_arg(args.trace)
        if traces is None:
            return 2
    thresholds = (
        None if args.no_goodhart_thresholds
        else (args.goodhart_thresholds or GOODHART_THRESHOLDS)
    )
    try:
        card = run_report_card(
            contract,
            traces=traces,
            baseline=args.baseline,
            goodhart_corpus=args.goodhart_corpus,
            goodhart_thresholds=thresholds,
        )
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.stdout == "json":
        print(json.dumps(card.to_dict(), indent=2))
    else:
        print(card.to_markdown())

    for label, path, text in (
        ("markdown", args.md, card.to_markdown()),
        ("json", args.json, json.dumps(card.to_dict(), indent=2) + "\n"),
    ):
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{label}: {_display(target)}")
    return 0 if card.ok else 1


def cmd_protocol(args: argparse.Namespace) -> int:
    if args.check_manifest:
        try:
            data = json.loads(
                Path(args.check_manifest).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            print(f"error: manifest not found: {args.check_manifest}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: invalid manifest JSON: {exc}", file=sys.stderr)
            return 2
        violations = check_manifest(data)
        if args.json:
            print(
                json.dumps(
                    {
                        "manifest": args.check_manifest,
                        "ok": not violations,
                        "violations": violations,
                    },
                    indent=2,
                )
            )
        elif not violations:
            print(f"manifest {args.check_manifest}: ok")
        else:
            print(
                f"manifest {args.check_manifest}: "
                f"{len(violations)} violation(s)"
            )
            for violation in violations:
                print(f"  - {violation}")
        return 0 if not violations else 1

    if args.check:
        contract = _load_contract(args.check)
        if contract is None:
            return 2
        result = check_contract(contract)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        elif result.ok:
            print(f"contract {result.contract}: ok")
        else:
            print(f"contract {result.contract}: {len(result.violations)} violation(s)")
            for violation in result.violations:
                print(f"  - {violation}")
        return 0 if result.ok else 1

    if args.schemas:
        for path in write_schemas(args.schemas):
            print(_display(Path(path)))

    if args.json:
        print(json.dumps(describe_protocol(), indent=2))
    else:
        print(render_protocol())
    return 0


def _registry(path: str | None) -> OracleRegistry | None:
    return OracleRegistry.load(path) if path else None


def cmd_capability(args: argparse.Namespace) -> int:
    if args.capability_command == "init":
        return _cmd_capability_init(args)
    if args.capability_command == "brief":
        return _cmd_capability_brief(args)
    if args.capability_command == "accept":
        return _cmd_capability_accept(args)
    if args.capability_command == "status":
        return _cmd_capability_status(args)
    if args.capability_command == "waive":
        return _cmd_capability_waive(args)
    if args.capability_command == "list":
        return _cmd_capability_list(args)
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.json:
        print(f"capability {manifest.capability}: ok")
        print(
            f"  owner={manifest.owner} risk={manifest.risk} "
            f"lifecycle={manifest.lifecycle}"
        )
        print(
            f"  oracles={len(manifest.oracles)} "
            f"criteria={len(manifest.criteria)} "
            f"policies={len(manifest.policies)}"
        )
        if manifest.registry:
            print(
                f"  registry={manifest.registry} "
                f"fingerprint={manifest.registry_fingerprint}"
            )
        if manifest.manifest_approval:
            print("  owner approval: required (capability.approval.json)")
        uncovered = manifest.uncovered_criteria()
        total = len(manifest.criteria)
        print(f"  criteria gated by some stage: {total - len(uncovered)}/{total}")
        if uncovered:
            print(
                "  not gated by any stage: "
                + ", ".join(f"{item.id} ({item.severity})" for item in uncovered)
            )
    if args.json:
        data = manifest.to_dict()
        data["uncovered_criteria"] = [
            {"id": item.id, "severity": item.severity, "oracle": item.oracle}
            for item in manifest.uncovered_criteria()
        ]
        print(json.dumps(data, indent=2))
    if args.strict and any(
        item.severity in GATING_SEVERITIES
        for item in manifest.uncovered_criteria()
    ):
        print(
            "error: a critical criterion is not gated by any stage",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_capability_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    try:
        path, data, detection = init_capability(
            root,
            out=args.out,
            owner=args.owner,
            force=args.force,
            ci=args.ci,
            hook=args.hook,
        )
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    steps = next_steps(data)
    if args.json:
        print(
            json.dumps(
                {
                    "path": str(path),
                    "stack": detection.stack,
                    "notes": detection.notes,
                    "manifest": data,
                    "next": steps,
                    "workflow": str(
                        root / ".github" / "workflows" / "assaystone.yml"
                    )
                    if args.ci
                    else "",
                    "hook": str(root / ".assaystone" / "hook.json")
                    if args.hook
                    else "",
                },
                indent=2,
            )
        )
        return 0
    print(f"wrote {display_path(path, root)}")
    print(f"stack: {detection.stack}")
    print(f"oracles: {', '.join(item['id'] for item in data['oracles'])}")
    for note in detection.notes:
        print(f"note: {note}")
    if args.ci:
        print(
            "wrote "
            + display_path(
                root / ".github" / "workflows" / "assaystone.yml", root
            )
        )
    if args.hook:
        print(
            "wrote "
            + display_path(root / ".assaystone" / "hook.json", root)
        )
        print(
            "install the hook: assaystone hook install claude-code "
            f'--manifest {display_path(path, root)} --mode block'
        )
    print("next:")
    for step in steps:
        print(f"  - {step}")
    print(
        f"\nrun: assaystone gate --manifest {display_path(path, root)} "
        "--stage shadow --root ."
    )
    return 0


def _cmd_capability_list(args: argparse.Namespace) -> int:
    portfolio = build_portfolio(
        args.root,
        owner_key=os.environ.get(args.owner_key_env) or "",
        receipt_key=os.environ.get(args.receipt_key_env) or "",
        owner_public_key=args.owner_public_key,
    )
    if args.json:
        print(json.dumps(portfolio.to_dict(), indent=2))
    else:
        print(render_portfolio(portfolio))
    if args.strict and portfolio.critical_count():
        return 1
    return 0


def _cmd_capability_waive(args: argparse.Namespace) -> int:
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    key = os.environ.get(args.key_env) or ""
    if not key and not args.private_key_file:
        print(
            f"error: set {args.key_env} or pass --private-key-file",
            file=sys.stderr,
        )
        return 2
    try:
        entry = create_waiver(
            manifest,
            args.criterion,
            args.reason,
            args.approver or manifest.owner,
            key,
            args.expires,
            private_key_path=args.private_key_file,
        )
    except WaiverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    target = Path(args.out) if args.out else waiver_path_for(manifest)
    if target is None:
        print("error: the manifest has no source path; pass --out", file=sys.stderr)
        return 1
    existing = []
    if target.exists():
        try:
            data = load_waivers(target)
        except WaiverError:
            data = {}
        if (
            data.get("capability") == manifest.capability
            and data.get("manifest_digest")
            == entry["manifest_digest"]
        ):
            existing = [
                item
                for item in data.get("waivers") or []
                if item.get("criterion") != entry["criterion"]
            ]
    payload = {
        "version": entry["version"],
        "capability": entry["capability"],
        "manifest_digest": entry["manifest_digest"],
        "waivers": existing + [entry],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"waiver: {target} criterion {entry['criterion']} "
        f"until {entry['expires_at']} by {entry['approved_by']}"
    )
    return 0


def _cmd_capability_status(args: argparse.Namespace) -> int:
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    card = build_card(
        manifest,
        stage=args.stage,
        trail_path=args.trail,
        receipt_path=args.receipt,
        approval_path=args.approval,
        owner_key=os.environ.get(args.owner_key_env) or "",
        owner_public_key=args.owner_public_key,
        receipt_key=os.environ.get(args.receipt_key_env) or "",
    )
    if args.json:
        print(json.dumps(card.to_dict(), indent=2))
    else:
        print(render_card(card))
    return 0


def _cmd_capability_accept(args: argparse.Namespace) -> int:
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    key = os.environ.get(args.key_env) or ""
    if not key and not args.private_key_file:
        print(
            f"error: set {args.key_env} or pass --private-key-file",
            file=sys.stderr,
        )
        return 2
    try:
        approval = create_approval(
            manifest,
            args.approver or manifest.owner,
            key,
            private_key_path=args.private_key_file,
        )
    except ApprovalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    target = Path(args.out) if args.out else approval_path_for(manifest)
    if target is None:
        print("error: the manifest has no source path; pass --out", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(approval, indent=2) + "\n", encoding="utf-8")
    print(
        f"approval: {target} by {approval['approved_by']} "
        f"manifest {approval['manifest_digest'][:23]}..."
    )
    return 0


def _cmd_capability_brief(args: argparse.Namespace) -> int:
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = render_brief(
        manifest,
        manifest_path=args.manifest,
        stage=args.stage,
        task=args.task or "",
    )
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(text, end="")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    try:
        manifest = CapabilityManifest.load(
            args.manifest, registry=_registry(args.registry)
        )
    except (PlaneError, OracleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        result = evaluate_gate(
            manifest,
            args.stage,
            args.root,
            strict=args.strict,
            trail_path=args.audit,
            approval_path=args.manifest_approval,
            owner_key=os.environ.get(args.owner_key_env) or "",
            owner_public_key=args.owner_public_key,
            waivers_path=args.waivers,
        )
    except PlaneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    actor = (
        args.actor
        or os.environ.get("ASSAYSTONE_ACTOR")
        or os.environ.get("USER")
        or "unknown"
    )
    receipt_key = ""
    if args.receipt:
        if not args.receipt_key_file:
            receipt_key = os.environ.get(args.receipt_key_env) or ""
            if not receipt_key:
                print(
                    f"error: --receipt needs {args.receipt_key_env} or "
                    "--receipt-key-file",
                    file=sys.stderr,
                )
                return 2
    entry = None
    if args.audit:
        previous = audit_trail.last_manifest_digest(
            args.audit, result.capability
        )
        if (
            previous
            and previous != result.manifest_digest
            and not args.accept_manifest_change
        ):
            result.outcome = "escalate"
            result.merge_allowed = False
            result.deploy_allowed = False
            result.reasons.append(
                "manifest changed since the last gate on this trail; review "
                "the diff and re-run with --accept-manifest-change"
            )
        try:
            entry = audit_trail.append(args.audit, result, actor=actor)
        except (OSError, audit_trail.TrailError) as exc:
            print(f"error: cannot write trail: {exc}", file=sys.stderr)
            return 2
    receipt = None
    if args.receipt:
        try:
            receipt = create_receipt(
                result,
                args.root,
                receipt_key,
                actor=actor,
                trail_path=args.audit,
                private_key_path=args.receipt_key_file,
            )
        except ReceiptError as exc:
            print(f"error: cannot sign receipt: {exc}", file=sys.stderr)
            return 2
        target = Path(args.receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
    if args.json:
        data = result.to_dict()
        if entry is not None:
            data["trail"] = {
                "path": args.audit,
                "seq": entry["seq"],
                "hash": entry["hash"],
            }
        if receipt is not None:
            data["receipt"] = {
                "path": args.receipt,
                "signature": receipt["signature"],
                "commit": receipt["commit"],
                "trail_head": receipt["trail_head"],
            }
        print(json.dumps(data, indent=2))
    else:
        print(render_gate(result))
        if entry is not None:
            print(
                f"\ntrail: {args.audit} entry {entry['seq']} "
                f"hash {entry['hash'][:23]}..."
            )
        if receipt is not None:
            print(
                f"receipt: {args.receipt} commit {receipt['commit'] or '-'} "
                f"signature {receipt['signature'][:31]}..."
            )
    if result.outcome == "pass":
        return 0
    return 1 if result.outcome == "fail" else 2


def cmd_key(args: argparse.Namespace) -> int:
    if args.key_command == "fingerprint":
        try:
            print(signing_keys.key_id(args.public))
        except signing_keys.SigningKeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.key_command != "generate":
        print(f"error: unknown key command {args.key_command!r}", file=sys.stderr)
        return 2
    try:
        private, public = signing_keys.generate(
            args.private, args.public, force=args.force
        )
        key_id = signing_keys.key_id(public)
    except signing_keys.SigningKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"private: {private}")
    print(f"public:  {public}")
    print(f"key id:  {key_id}")
    print("Keep the private key out of CI and out of the agent's environment.")
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    if args.receipt_command != "verify":
        print(
            f"error: unknown receipt command {args.receipt_command!r}",
            file=sys.stderr,
        )
        return 2
    try:
        data = load_receipt(args.path)
    except ReceiptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    key = os.environ.get(args.key_env) or ""
    check = verify_receipt(
        data,
        key,
        expected_commit=args.commit,
        expected_manifest_digest=args.manifest_digest,
        expected_outcome=args.outcome,
        public_key_path=args.public_key,
    )
    if args.json:
        print(json.dumps(check.to_dict(), indent=2))
    else:
        print(render_check(check))
    return 0 if check.ok else 1


def cmd_trail(args: argparse.Namespace) -> int:
    if args.trail_command != "verify":
        print(f"error: unknown trail command {args.trail_command!r}", file=sys.stderr)
        return 2
    check = audit_trail.verify(args.path, expected_head=args.expect)
    if args.json:
        print(json.dumps(check.to_dict(), indent=2))
    else:
        print(audit_trail.render_check(check))
    return 0 if check.ok else 1


def cmd_leaderboard(args: argparse.Namespace) -> int:
    try:
        board = run_leaderboard(args.manifest)
    except (LeaderboardError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.stdout == "json":
        print(json.dumps(board.to_dict(), indent=2))
    elif args.stdout == "summary":
        print(render_leaderboard(board))
    else:
        print(board.to_markdown())

    for label, path, text in (
        ("markdown", args.md, board.to_markdown()),
        ("json", args.json, json.dumps(board.to_dict(), indent=2) + "\n"),
    ):
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{label}: {_display(target)}")
    return 0 if board.ok else 1


def cmd_corpus(args: argparse.Namespace) -> int:
    try:
        added = add_case(
            args.corpus,
            args.family,
            args.trace,
            label=args.label,
            defect=args.defect,
            note=args.note or "",
            baseline=args.baseline,
            fmt=args.format,
            case_id=args.id,
            force=args.force,
        )
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"added {added.family}/{added.trace_id} -> {_display(added.path)}")
    label = added.verdict
    if added.defect:
        label = f"{label} ({added.defect})"
    print(f"label: {label}")

    if args.validate:
        try:
            outcome = case_outcome(args.corpus, added.family, added.trace_id)
        except CorpusError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        caught = ", ".join(outcome["caught_by"]) or "—"
        print(f"outcome: {outcome['outcome']} ({caught})")
    else:
        print("next: rerun the benchmark, or pass --validate to score it now")
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract) if args.contract else None
    if args.contract and contract is None:
        return 2
    try:
        plan = compose(
            contract,
            declared=args.require,
            budget_usd=args.budget,
            contract_only=args.contract_only,
            require_independent=not args.allow_low_independence,
        )
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(render_plan(plan))
    return 0 if plan.ok else 1


def cmd_coverage(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract)
    if contract is None:
        return 2
    try:
        report = analyze_coverage(contract, args.require)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_coverage(report))
    if args.strict and report.at_risk:
        return 1
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract)
    if contract is None:
        return 1
    traces = _load_traces_arg(args.trace)
    if traces is None:
        return 1
    summary = backtest(contract, traces, args.baseline)
    print(f"contract: {summary.contract}")
    for row in summary.rows:
        reason = f"  {row.first_failure}" if row.first_failure else ""
        print(
            f"  {row.trace_id:<24} human={row.human:<4} contract={row.outcome:<8} "
            f"{row.cost_usd:.6f} USD{reason}"
        )
    print()
    print(
        f"defects={len(summary.defects)} caught={summary.caught} escaped={summary.escaped} "
        f"routed={summary.routed} false_alarms={summary.false_alarms}"
    )
    print(
        f"catch_rate={summary.catch_rate:.1%} "
        f"false_alarm_rate={summary.false_alarm_rate:.1%} "
        f"avg_cost={summary.avg_cost:.6f} USD"
    )
    return 0


def cmd_mutate(args: argparse.Namespace) -> int:
    contract = _load_contract(args.contract)
    if contract is None:
        return 1
    traces = _load_traces_arg(args.trace)
    if traces is None:
        return 1
    target = traces[0]
    summary = run_mutation(contract, target, args.baseline, max_total=args.max_mutants)
    counts = summary.counts()
    print(f"contract: {summary.contract}  target: {target.id}")
    print(
        f"killed={counts['killed']} survived={counts['survived']} "
        f"escalated={counts['escalated']} invalid={counts['invalid']}  "
        f"score={summary.score:.1%}"
    )
    for operator, (killed, total) in sorted(summary.by_operator().items()):
        print(f"  {operator:<24} {killed}/{total}")
    for survivor in summary.survivors():
        print(
            f"  SURVIVED {survivor.mutant.operator:<24} {survivor.mutant.target}  "
            f"{survivor.mutant.description}"
        )
    return 0


def cmd_benchmark_failure_zoo(args: argparse.Namespace) -> int:
    thresholds = None if args.no_thresholds else (args.thresholds or DEFAULT_THRESHOLDS)
    try:
        result = run_benchmark(args.corpus or DEFAULT_CORPUS, thresholds)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.stdout == "json":
        print(result.to_json(), end="")
    elif args.stdout == "markdown":
        print(result.to_markdown())
    elif args.stdout == "csv":
        print(result.to_csv(), end="")
    else:
        print(render_summary(result))

    for label, path, text in (
        ("markdown", args.md, result.to_markdown()),
        ("json", args.json, result.to_json()),
        ("csv", args.csv, result.to_csv()),
    ):
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{label}: {_display(target)}")

    return 0 if result.thresholds_passed else 1


def cmd_benchmark_goodhart(args: argparse.Namespace) -> int:
    thresholds = None if args.no_thresholds else (args.thresholds or GOODHART_THRESHOLDS)
    contract = _load_contract(args.contract) if args.contract else None
    if args.contract and contract is None:
        return 2
    try:
        report = run_goodhart(
            args.corpus or GOODHART_CORPUS, thresholds, contract=contract
        )
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.stdout == "json":
        print(report.to_json(), end="")
    elif args.stdout == "markdown":
        print(report.to_markdown())
    else:
        print(render_goodhart_summary(report))

    for label, path, text in (
        ("markdown", args.md, report.to_markdown()),
        ("json", args.json, report.to_json()),
    ):
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{label}: {_display(target)}")

    return 0 if report.thresholds_passed else 1


def cmd_init(args: argparse.Namespace) -> int:
    try:
        result = init_project(args.path, force=args.force, ci=args.ci)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created {_display(result['contract'])}")
    print(f"created {_display(result['readme'])}")
    if result.get("workflow"):
        print(f"created {_display(result['workflow'])}")
    if result["warning"]:
        print(f"warning: {result['warning']}")
    print()
    print("Next:")
    print("  1. record traces and put them in .assaystone/traces/")
    print("  2. assaystone verify --contract .assaystone/contract.json --trace .assaystone/traces")
    print(
        "  3. pytest --assaystone-contract .assaystone/contract.json "
        "--assaystone-traces .assaystone/traces"
    )
    return 0


def cmd_hook_claude_code(args: argparse.Namespace) -> int:
    return claude_code_hook_main()


def cmd_hook_install(args: argparse.Namespace) -> int:
    settings = (
        Path.home() / ".claude" / "settings.json"
        if args.user
        else Path(args.path) / ".claude" / "settings.local.json"
    )
    if args.user and args.manifest:
        print(
            "error: a capability manifest needs a project settings file, not --user",
            file=sys.stderr,
        )
        return 1
    try:
        target, changed = install_claude_code(
            settings,
            mode=args.mode,
            manifest=args.manifest,
            stage=args.stage,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(("installed" if changed else "already installed") + f": {_display(target)}")
    print("Restart Claude Code to load the hook.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    if args.pack == "ops":
        print(demo.run_ops(output_dir))
    elif args.pack == "audit":
        print(demo.run_audit(output_dir))
    elif args.pack == "adversarial":
        print(demo.run_adversarial(output_dir))
    elif args.pack == "plane":
        print(demo.run_plane(output_dir))
    else:
        print(demo.run_code(output_dir))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assaystone",
        description="The assay stone for AI agents: verification, not evaluation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo_parser = sub.add_parser("demo", help="run an end-to-end demo")
    demo_parser.add_argument(
        "pack",
        nargs="?",
        choices=["code", "ops", "audit", "adversarial", "plane"],
        default="code",
    )
    demo_parser.add_argument("--output-dir", default=".")
    demo_parser.set_defaults(func=cmd_demo)

    audit = sub.add_parser(
        "audit",
        help="find silent failures in existing traces",
        epilog="Exit codes: 0 clean, 1 findings, 2 unable to audit.",
    )
    audit.add_argument(
        "source",
        nargs="?",
        help="trace JSON, transcript JSONL, LangSmith / Langfuse / OTel export, or a directory",
    )
    audit.add_argument(
        "--latest",
        choices=["claude-code", "codex"],
        help="audit the newest local transcript for this workspace",
    )
    audit.add_argument(
        "--baseline",
        default=None,
        help="pre-session repository; defaults to the current directory or session cwd",
    )
    audit.add_argument("--git-repo", default=None)
    audit.add_argument(
        "--format",
        choices=[
            "auto",
            "trace",
            "messages",
            "claude-code",
            "codex",
            "langsmith",
            "langfuse",
            "otel",
        ],
        default="auto",
    )
    audit.add_argument("--run-tests", action="store_true")
    audit.add_argument(
        "--workspace",
        action="store_true",
        help="read current files (post-session / hook mode) instead of replaying edits",
    )
    audit.add_argument(
        "--git-preimage",
        action="store_true",
        help="use git HEAD as the pre-session baseline for diff-based checks",
    )
    audit.add_argument("--write-contract", default=None, metavar="PATH")
    audit.add_argument("--json", action="store_true")
    audit.add_argument("--sarif", default=None, metavar="PATH")
    audit.add_argument("--junit", default=None, metavar="PATH")
    audit.add_argument("--no-evidence", action="store_true")
    audit.add_argument("--fail-on", choices=["none", "high", "any"], default="any")
    audit.set_defaults(func=cmd_audit)

    hook = sub.add_parser("hook", help="run or install a framework hook")
    hook_sub = hook.add_subparsers(dest="hook_name", required=True)
    claude = hook_sub.add_parser("claude-code", help="Claude Code Stop hook runner")
    claude.set_defaults(func=cmd_hook_claude_code)
    install = hook_sub.add_parser("install", help="install a hook")
    install_sub = install.add_subparsers(dest="install_target", required=True)
    install_claude = install_sub.add_parser("claude-code", help="install the Claude Code Stop hook")
    install_claude.add_argument("--path", default=".")
    install_claude.add_argument("--user", action="store_true", help="write ~/.claude/settings.json")
    install_claude.add_argument("--mode", choices=["warn", "block"], default="warn")
    install_claude.add_argument(
        "--manifest", default=None, help="capability manifest for the Stop gate"
    )
    install_claude.add_argument(
        "--stage",
        default="shadow",
        choices=["design", "shadow", "canary", "production", "incident", "retired"],
    )
    install_claude.set_defaults(func=cmd_hook_install)

    verify = sub.add_parser(
        "verify",
        help="run a contract over recorded traces",
        epilog="Exit codes: 0 all pass, 1 at least one fail, 2 no fails but at least one escalate.",
    )
    verify.add_argument("--contract", required=True)
    verify.add_argument("--trace", required=True, help="trace file or directory")
    verify.add_argument("--baseline", default=".")
    output = verify.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="machine-readable JSON output")
    output.add_argument(
        "--github",
        action="store_true",
        help="emit GitHub Actions annotations and a step summary",
    )
    verify.add_argument("--sarif", default=None, metavar="PATH")
    verify.add_argument("--junit", default=None, metavar="PATH")
    verify.add_argument("--no-evidence", action="store_true")
    verify.set_defaults(func=cmd_verify)

    scorecard_parser = sub.add_parser(
        "scorecard",
        help=(
            "one report card: conformance, coverage, recall on labelled "
            "traces, and resistance to a contract-aware agent"
        ),
        epilog=(
            "Exit codes: 0 the contract passes all four checks, 1 it needs "
            "work, 2 load error."
        ),
    )
    scorecard_parser.add_argument("--contract", required=True)
    scorecard_parser.add_argument(
        "--trace",
        default=None,
        help="labelled trace file or directory; enables the recall section",
    )
    scorecard_parser.add_argument("--baseline", default=".")
    scorecard_parser.add_argument(
        "--goodhart-corpus",
        default=None,
        metavar="PATH",
        help="adversarial corpus; defaults to the packaged goodhart corpus",
    )
    scorecard_parser.add_argument(
        "--goodhart-thresholds",
        default=None,
        metavar="PATH",
        help="resistance thresholds; defaults to the packaged thresholds",
    )
    scorecard_parser.add_argument(
        "--no-goodhart-thresholds",
        action="store_true",
        help="do not check resistance thresholds",
    )
    scorecard_parser.add_argument(
        "--stdout",
        choices=["markdown", "json"],
        default="markdown",
        help="format printed to stdout",
    )
    scorecard_parser.add_argument("--md", default=None, metavar="PATH")
    scorecard_parser.add_argument("--json", default=None, metavar="PATH")
    scorecard_parser.set_defaults(func=cmd_scorecard)

    protocol_parser = sub.add_parser(
        "protocol",
        help="show the verifier protocol, export schemas, or check a contract",
        epilog=(
            "The protocol is the machine-readable contract between a verifier "
            "and the scorecard. Exit codes: 0 ok, 1 contract violates the "
            "protocol, 2 load error."
        ),
    )
    protocol_parser.add_argument(
        "--json", action="store_true", help="machine-readable JSON output"
    )
    protocol_parser.add_argument(
        "--schemas",
        default=None,
        metavar="DIR",
        help="write contract/verifier/verdict JSON Schemas to DIR",
    )
    protocol_parser.add_argument(
        "--check",
        default=None,
        metavar="CONTRACT",
        help="check a contract against the protocol instead of printing it",
    )
    protocol_parser.add_argument(
        "--check-manifest",
        default=None,
        metavar="PATH",
        help="check a verifier manifest (JSON) against the protocol",
    )
    protocol_parser.set_defaults(func=cmd_protocol)

    coverage_parser = sub.add_parser(
        "coverage",
        help="check which declared defect classes a contract covers",
        epilog=(
            "Exit codes: 0 report written, 1 at-risk defects with --strict, "
            "2 contract error."
        ),
    )
    coverage_parser.add_argument("--contract", required=True)
    coverage_parser.add_argument(
        "--require",
        action="append",
        default=None,
        metavar="TAG",
        help="defect tag the contract must cover; repeatable. "
        "Defaults to the contract's required_defects.",
    )
    coverage_parser.add_argument(
        "--json", action="store_true", help="machine-readable JSON output"
    )
    coverage_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if a declared defect is uncovered or only weakly covered",
    )
    coverage_parser.set_defaults(func=cmd_coverage)

    backtest_parser = sub.add_parser("backtest", help="score a contract against human labels")
    backtest_parser.add_argument("--contract", required=True)
    backtest_parser.add_argument("--trace", required=True)
    backtest_parser.add_argument("--baseline", default=".")
    backtest_parser.set_defaults(func=cmd_backtest)

    mutate = sub.add_parser("mutate", help="inject defects and measure verifier recall")
    mutate.add_argument("--contract", required=True)
    mutate.add_argument("--trace", required=True)
    mutate.add_argument("--baseline", default=".")
    mutate.add_argument("--max-mutants", type=int, default=18)
    mutate.set_defaults(func=cmd_mutate)

    benchmark = sub.add_parser("benchmark", help="run a reproducible benchmark suite")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_name", required=True)
    failure_zoo = benchmark_sub.add_parser(
        "failure-zoo",
        help="score every built-in verifier against the labelled Failure Zoo corpus",
        epilog=(
            "Runs offline against packaged fixtures. Exit codes: 0 thresholds pass, "
            "1 regression below threshold, 2 corpus error."
        ),
    )
    failure_zoo.add_argument(
        "--corpus",
        default=None,
        metavar="PATH",
        help="corpus manifest; defaults to the packaged failure_zoo/corpus.json",
    )
    failure_zoo.add_argument(
        "--thresholds",
        default=None,
        metavar="PATH",
        help="regression thresholds; defaults to the packaged thresholds.json",
    )
    failure_zoo.add_argument(
        "--no-thresholds",
        action="store_true",
        help="report results without checking regression thresholds",
    )
    failure_zoo.add_argument(
        "--stdout",
        choices=["summary", "markdown", "json", "csv"],
        default="summary",
        help="format printed to stdout",
    )
    failure_zoo.add_argument("--md", default=None, metavar="PATH", help="write Markdown scorecard")
    failure_zoo.add_argument("--json", default=None, metavar="PATH", help="write JSON results")
    failure_zoo.add_argument("--csv", default=None, metavar="PATH", help="write per-check CSV")
    failure_zoo.set_defaults(func=cmd_benchmark_failure_zoo)

    goodhart = benchmark_sub.add_parser(
        "goodhart",
        help=(
            "measure whether an agent that knows the contract can pass "
            "without doing the work"
        ),
        epilog=(
            "Runs offline against packaged adversarial fixtures. Exit codes: "
            "0 thresholds pass, 1 regression below threshold, 2 corpus error."
        ),
    )
    goodhart.add_argument(
        "--contract",
        default=None,
        metavar="PATH",
        help=(
            "score this contract's verifiers instead of the corpus manifests; "
            "the contract's domain selects the families"
        ),
    )
    goodhart.add_argument(
        "--corpus",
        default=None,
        metavar="PATH",
        help="corpus manifest; defaults to the packaged goodhart/corpus.json",
    )
    goodhart.add_argument(
        "--thresholds",
        default=None,
        metavar="PATH",
        help="regression thresholds; defaults to the packaged thresholds.json",
    )
    goodhart.add_argument(
        "--no-thresholds",
        action="store_true",
        help="report results without checking regression thresholds",
    )
    goodhart.add_argument(
        "--stdout",
        choices=["summary", "markdown", "json"],
        default="summary",
        help="format printed to stdout",
    )
    goodhart.add_argument("--md", default=None, metavar="PATH", help="write Markdown report")
    goodhart.add_argument("--json", default=None, metavar="PATH", help="write JSON results")
    goodhart.set_defaults(func=cmd_benchmark_goodhart)

    init = sub.add_parser("init", help="scaffold a contract for the current repository")
    init.add_argument("--path", default=".")
    init.add_argument("--force", action="store_true", help="overwrite an existing contract")
    init.add_argument("--ci", action="store_true", help="also write a GitHub Actions workflow")
    init.set_defaults(func=cmd_init)

    capability_parser = sub.add_parser(
        "capability",
        help="validate a capability manifest",
    )
    capability_sub = capability_parser.add_subparsers(
        dest="capability_command", required=True
    )
    capability_validate = capability_sub.add_parser(
        "validate", help="check a capability manifest"
    )
    capability_validate.add_argument("--manifest", required=True, metavar="PATH")
    capability_validate.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    capability_validate.add_argument("--json", action="store_true")
    capability_validate.add_argument(
        "--strict",
        action="store_true",
        help="fail when a critical criterion is gated by no stage",
    )
    capability_validate.set_defaults(func=cmd_capability)

    capability_init = capability_sub.add_parser(
        "init", help="draft a capability manifest from the repository"
    )
    capability_init.add_argument("--root", default=".")
    capability_init.add_argument(
        "--out", default=None, help="manifest path (default .assaystone/capability.json)"
    )
    capability_init.add_argument("--owner", default=None)
    capability_init.add_argument("--force", action="store_true")
    capability_init.add_argument(
        "--ci", action="store_true", help="write a GitHub Actions gate workflow"
    )
    capability_init.add_argument(
        "--hook",
        action="store_true",
        help="write .assaystone/hook.json for the Claude Code Stop gate",
    )
    capability_init.add_argument("--json", action="store_true")
    capability_init.set_defaults(func=cmd_capability)

    capability_brief = capability_sub.add_parser(
        "brief", help="render a task brief for an agent from a manifest"
    )
    capability_brief.add_argument("--manifest", required=True, metavar="PATH")
    capability_brief.add_argument(
        "--stage",
        default="shadow",
        choices=["design", "shadow", "canary", "production", "incident", "retired"],
    )
    capability_brief.add_argument("--task", default="", help="the task text")
    capability_brief.add_argument("--out", default=None, metavar="PATH")
    capability_brief.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    capability_brief.set_defaults(func=cmd_capability)

    capability_accept = capability_sub.add_parser(
        "accept", help="sign the manifest digest as its owner"
    )
    capability_accept.add_argument("--manifest", required=True, metavar="PATH")
    capability_accept.add_argument("--out", default=None, metavar="PATH")
    capability_accept.add_argument("--approver", default=None)
    capability_accept.add_argument(
        "--key-env", default=DEFAULT_OWNER_KEY_ENV
    )
    capability_accept.add_argument(
        "--private-key-file", default=None, metavar="PATH"
    )
    capability_accept.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    capability_accept.set_defaults(func=cmd_capability)

    capability_status = capability_sub.add_parser(
        "status", help="summarize the current state of acceptance"
    )
    capability_status.add_argument("--manifest", required=True, metavar="PATH")
    capability_status.add_argument("--trail", default=None, metavar="PATH")
    capability_status.add_argument("--receipt", default=None, metavar="PATH")
    capability_status.add_argument("--approval", default=None, metavar="PATH")
    capability_status.add_argument("--waivers", default=None, metavar="PATH")
    capability_status.add_argument(
        "--stage",
        default=None,
        choices=["design", "shadow", "canary", "production", "incident", "retired"],
    )
    capability_status.add_argument(
        "--owner-key-env", default=DEFAULT_OWNER_KEY_ENV
    )
    capability_status.add_argument(
        "--owner-public-key", default=None, metavar="PATH"
    )
    capability_status.add_argument(
        "--receipt-key-env", default=DEFAULT_KEY_ENV
    )
    capability_status.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    capability_status.add_argument("--json", action="store_true")
    capability_status.set_defaults(func=cmd_capability)

    capability_waive = capability_sub.add_parser(
        "waive", help="sign an exception for one criterion"
    )
    capability_waive.add_argument("--manifest", required=True, metavar="PATH")
    capability_waive.add_argument("--criterion", required=True)
    capability_waive.add_argument("--reason", required=True)
    capability_waive.add_argument("--expires", required=True, metavar="YYYY-MM-DD")
    capability_waive.add_argument("--approver", default=None)
    capability_waive.add_argument("--out", default=None, metavar="PATH")
    capability_waive.add_argument(
        "--key-env", default=DEFAULT_OWNER_KEY_ENV
    )
    capability_waive.add_argument(
        "--private-key-file", default=None, metavar="PATH"
    )
    capability_waive.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    capability_waive.set_defaults(func=cmd_capability)

    capability_list = capability_sub.add_parser(
        "list", help="list capabilities and their evidence in a workspace"
    )
    capability_list.add_argument("--root", default=".")
    capability_list.add_argument(
        "--owner-key-env", default=DEFAULT_OWNER_KEY_ENV
    )
    capability_list.add_argument(
        "--owner-public-key", default=None, metavar="PATH"
    )
    capability_list.add_argument(
        "--receipt-key-env", default=DEFAULT_KEY_ENV
    )
    capability_list.add_argument("--json", action="store_true")
    capability_list.add_argument(
        "--strict", action="store_true", help="fail on any critical risk"
    )
    capability_list.set_defaults(func=cmd_capability)

    gate_parser = sub.add_parser(
        "gate",
        help="evaluate a capability at a lifecycle stage",
        epilog=(
            "Exit codes: 0 pass, 1 fail, 2 escalate or manifest error. The "
            "command runs the oracles declared in the manifest; only run "
            "manifests you trust."
        ),
    )
    gate_parser.add_argument("--manifest", required=True, metavar="PATH")
    gate_parser.add_argument(
        "--stage",
        required=True,
        choices=["design", "shadow", "canary", "production", "incident", "retired"],
    )
    gate_parser.add_argument("--root", default=".")
    gate_parser.add_argument(
        "--registry", metavar="PATH", default=None, help="oracle registry JSON"
    )
    gate_parser.add_argument(
        "--strict",
        action="store_true",
        help="escalate when a critical criterion is not gated at this stage",
    )
    gate_parser.add_argument(
        "--audit", metavar="PATH", default=None, help="append to this trail file"
    )
    gate_parser.add_argument("--actor", default=None, help="who ran the gate")
    gate_parser.add_argument(
        "--accept-manifest-change",
        action="store_true",
        help="record a reviewed manifest change instead of escalating",
    )
    gate_parser.add_argument(
        "--receipt", metavar="PATH", default=None,
        help="write a signed receipt for this decision",
    )
    gate_parser.add_argument(
        "--receipt-key-env", default=DEFAULT_KEY_ENV,
        help="environment variable holding the HMAC receipt key",
    )
    gate_parser.add_argument(
        "--receipt-key-file", default=None, metavar="PATH",
        help="Ed25519 private key for the receipt",
    )
    gate_parser.add_argument(
        "--manifest-approval", metavar="PATH", default=None,
        help="owner approval for the manifest digest",
    )
    gate_parser.add_argument(
        "--owner-key-env", default=DEFAULT_OWNER_KEY_ENV,
        help="environment variable holding the owner HMAC key",
    )
    gate_parser.add_argument(
        "--owner-public-key", default=None, metavar="PATH",
        help="Ed25519 public key for owner approvals and waivers",
    )
    gate_parser.add_argument(
        "--waivers", metavar="PATH", default=None,
        help="owner-signed criterion waivers",
    )
    gate_parser.add_argument("--json", action="store_true")
    gate_parser.set_defaults(func=cmd_gate)

    trail_parser = sub.add_parser(
        "trail", help="verify a hash-chained gate audit trail"
    )
    trail_sub = trail_parser.add_subparsers(dest="trail_command", required=True)
    trail_verify = trail_sub.add_parser("verify", help="check the hash chain")
    trail_verify.add_argument("path", metavar="PATH")
    trail_verify.add_argument(
        "--expect",
        default=None,
        metavar="HASH",
        help="anchored head hash; detects truncation of the tail",
    )
    trail_verify.add_argument("--json", action="store_true")
    trail_verify.set_defaults(func=cmd_trail)

    receipt_parser = sub.add_parser(
        "receipt", help="verify a signed gate receipt"
    )
    receipt_sub = receipt_parser.add_subparsers(
        dest="receipt_command", required=True
    )
    receipt_verify = receipt_sub.add_parser("verify", help="check a receipt")
    receipt_verify.add_argument("path", metavar="PATH")
    receipt_verify.add_argument("--key-env", default=DEFAULT_KEY_ENV)
    receipt_verify.add_argument(
        "--public-key", default=None, metavar="PATH",
        help="Ed25519 public key for an ed25519 receipt",
    )
    receipt_verify.add_argument("--commit", default=None)
    receipt_verify.add_argument("--manifest-digest", default=None)
    receipt_verify.add_argument(
        "--outcome", default=None, choices=["pass", "fail", "escalate"]
    )
    receipt_verify.add_argument("--json", action="store_true")
    receipt_verify.set_defaults(func=cmd_receipt)

    key_parser = sub.add_parser("key", help="generate signing keys")
    key_sub = key_parser.add_subparsers(dest="key_command", required=True)
    key_generate = key_sub.add_parser("generate", help="generate an Ed25519 pair")
    key_generate.add_argument("--private", required=True, metavar="PATH")
    key_generate.add_argument("--public", required=True, metavar="PATH")
    key_generate.add_argument("--force", action="store_true")
    key_generate.set_defaults(func=cmd_key)

    key_fingerprint = key_sub.add_parser(
        "fingerprint", help="print the key id of a public key"
    )
    key_fingerprint.add_argument("--public", required=True, metavar="PATH")
    key_fingerprint.set_defaults(func=cmd_key)

    compose_parser = sub.add_parser(
        "compose",
        help=(
            "choose the cheapest independent cover for declared defect "
            "classes, and report what no check decides"
        ),
        epilog=(
            "Coverage is a weighted set cover: each declared class needs one "
            "medium/high independence check. Exit codes: 0 all covered and "
            "within budget, 1 uncovered or over budget, 2 input error."
        ),
    )
    compose_parser.add_argument("--contract", default=None, metavar="PATH")
    compose_parser.add_argument(
        "--require",
        action="append",
        default=None,
        metavar="TAG",
        help="defect class to cover; repeatable. Defaults to required_defects.",
    )
    compose_parser.add_argument(
        "--budget", type=float, default=None, metavar="USD"
    )
    compose_parser.add_argument(
        "--contract-only",
        action="store_true",
        help="plan from the contract's own verifiers instead of the registry",
    )
    compose_parser.add_argument(
        "--allow-low-independence",
        action="store_true",
        help="let low-independence checks cover a class",
    )
    compose_parser.add_argument("--json", action="store_true")
    compose_parser.set_defaults(func=cmd_compose)

    leaderboard_parser = sub.add_parser(
        "leaderboard",
        help="compare several contracts on coverage, recall, resistance, and cost",
        epilog=(
            "The manifest lists an entry per contract, with optional traces and "
            "baseline. Exit codes: 0 every entry passes, 1 at least one needs "
            "work, 2 manifest error."
        ),
    )
    leaderboard_parser.add_argument("--manifest", required=True, metavar="PATH")
    leaderboard_parser.add_argument(
        "--stdout",
        choices=["markdown", "summary", "json"],
        default="markdown",
    )
    leaderboard_parser.add_argument("--md", default=None, metavar="PATH")
    leaderboard_parser.add_argument("--json", default=None, metavar="PATH")
    leaderboard_parser.set_defaults(func=cmd_leaderboard)

    corpus_parser = sub.add_parser(
        "corpus",
        help="add a labelled case to an existing benchmark corpus",
        epilog=(
            "The manifest is never edited: an existing family points at a "
            "directory, so the new labelled trace is picked up by the next run. "
            "Exit codes: 0 added, 2 corpus or input error."
        ),
    )
    corpus_sub = corpus_parser.add_subparsers(
        dest="corpus_command", required=True
    )
    corpus_add = corpus_sub.add_parser(
        "add",
        help="write one labelled trace into a family",
    )
    corpus_add.add_argument("--corpus", required=True, metavar="PATH")
    corpus_add.add_argument("--family", required=True)
    corpus_add.add_argument(
        "--trace",
        required=True,
        metavar="PATH",
        help="a trace JSON, a transcript, or an observability export",
    )
    corpus_add.add_argument("--label", required=True, choices=["pass", "fail"])
    corpus_add.add_argument(
        "--defect",
        default=None,
        metavar="TAG",
        help="required for a failing case; the shared defect vocabulary",
    )
    corpus_add.add_argument("--note", default="")
    corpus_add.add_argument(
        "--baseline",
        default=None,
        metavar="DIR",
        help="baseline used to replay a transcript; defaults to the family's",
    )
    corpus_add.add_argument(
        "--format",
        default="auto",
        choices=[
            "auto",
            "trace",
            "messages",
            "claude-code",
            "codex",
            "langsmith",
            "langfuse",
            "otel",
        ],
    )
    corpus_add.add_argument("--id", default=None, metavar="CASE_ID")
    corpus_add.add_argument("--force", action="store_true")
    corpus_add.add_argument(
        "--validate",
        action="store_true",
        help="rerun the corpus and report what the verifier pack did",
    )
    corpus_add.set_defaults(func=cmd_corpus)

    record = sub.add_parser("record", help="convert a transcript or export into a trace")
    record.add_argument("--transcript", required=True, help="transcript, export, or trace file")
    record.add_argument("--out", required=True, help="output trace path, or - for stdout")
    record.add_argument(
        "--format",
        choices=[
            "auto",
            "trace",
            "messages",
            "claude-code",
            "codex",
            "langsmith",
            "langfuse",
            "otel",
        ],
        default="auto",
    )
    record.add_argument("--baseline", default=None)
    record.add_argument("--git-repo", default=None)
    record.add_argument("--workspace", action="store_true")
    record.add_argument("--task", default="")
    record.add_argument("--agent", default="")
    record.add_argument("--trace-id", default=None)
    record.set_defaults(func=cmd_record)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
