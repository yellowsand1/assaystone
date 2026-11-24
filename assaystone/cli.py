"""Command line interface for Assaystone."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, demo
from .audit import AuditError, audit_traces, build_audit_contract, load_audit_traces, render_audit
from .backtest import backtest
from .contract import Contract
from .failure_zoo import (
    DEFAULT_CORPUS,
    DEFAULT_THRESHOLDS,
    BenchmarkError,
    render_summary,
    run_benchmark,
)
from .hooks.claude_code import install_claude_code
from .hooks.claude_code import main as claude_code_hook_main
from .init import init_project
from .model import ESCALATE, FAIL, PASS, load_traces
from .mutate import run_mutation
from .replay import git_preimage, is_git_repo
from .reports import write_audit_junit, write_audit_sarif, write_junit, write_sarif
from .runner import run_contract
from .schema import SchemaError, available_schemas, load_schema, schema_path, validate_document
from .sessions import SessionDiscoveryError, find_latest_session


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
    try:
        target, changed = install_claude_code(settings, mode=args.mode)
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
    else:
        print(demo.run_code(output_dir))
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    if args.command_name == "list":
        for name in available_schemas():
            print(name)
        return 0
    if args.command_name == "validate":
        try:
            document = json.loads(Path(args.document).read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: invalid JSON in {args.document}: {exc}", file=sys.stderr)
            return 2
        errors = validate_document(document, args.schema)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"{args.document}: valid {args.schema} document")
        return 0
    # default: print the schema itself
    try:
        schema = load_schema(args.schema)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(schema, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assaystone",
        description="The assay stone for AI agents: verification, not evaluation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo_parser = sub.add_parser("demo", help="run an end-to-end demo")
    demo_parser.add_argument("pack", nargs="?", choices=["code", "ops", "audit"], default="code")
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

    init = sub.add_parser("init", help="scaffold a contract for the current repository")
    init.add_argument("--path", default=".")
    init.add_argument("--force", action="store_true", help="overwrite an existing contract")
    init.add_argument("--ci", action="store_true", help="also write a GitHub Actions workflow")
    init.set_defaults(func=cmd_init)

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

    schema = sub.add_parser(
        "schema",
        help="print or validate Assaystone JSON Schemas",
        epilog="Exit codes: 0 ok, 1 validation failed, 2 usage/IO error.",
    )
    schema_sub = schema.add_subparsers(dest="command_name")
    schema_sub.add_parser("list", help="list available schema names")
    for schema_name in available_schemas():
        show = schema_sub.add_parser(schema_name, help=f"print the {schema_name} JSON Schema")
        show.set_defaults(command_name="show", schema=schema_name)
    validate = schema_sub.add_parser("validate", help="validate a document against a schema")
    validate.add_argument("schema", choices=available_schemas())
    validate.add_argument("document", help="path to the JSON document to validate")
    validate.set_defaults(command_name="validate")
    schema.set_defaults(func=cmd_schema, command_name="show", schema="trace")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
