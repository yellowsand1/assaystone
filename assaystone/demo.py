"""Packaged end-to-end demos. They work from an installed wheel."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from . import trail as audit_trail
from .audit import audit_traces, build_audit_contract, load_audit_traces, render_audit
from .backtest import backtest
from .contract import Contract
from .model import FAIL, load_traces, utc_now
from .mutate import run_mutation
from .plane import CapabilityManifest, evaluate_gate
from .runner import run_contract
from .runtime import ApprovalRequired, ContractFailed, RuntimeGuard
from .scorecard import render_scorecard

DATA_ROOT = Path(__file__).resolve().parent / "demo_data"


def _write(output_dir: str | Path, name: str, text: str) -> Path:
    target = Path(output_dir) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _short_detail(detail: str) -> str:
    detail = detail.removeprefix("contract failed: ")
    return detail.replace(" cents exceeds limit ", " > ")


def _backtest_rows(summaries) -> list[str]:
    rows = [
        f"{'contract':<12} {'defects':>7} {'caught':>7} {'escaped':>8} "
        f"{'false':>6} {'catch':>6} {'cost/trace $':>13}"
    ]
    for summary in summaries:
        rows.append(
            f"{summary.contract:<12} {len(summary.defects):>7} {summary.caught:>7} "
            f"{summary.escaped:>8} {summary.false_alarms:>6} "
            f"{summary.catch_rate:>5.0%} {summary.avg_cost:>13.6f}"
        )
    return rows


def run_code(output_dir: str | Path = ".") -> str:
    root = DATA_ROOT / "code_agent"
    baseline = root / "baseline"
    traces = load_traces(root / "traces")
    naive = Contract.load(root / "contracts" / "naive.json")
    hardened = Contract.load(root / "contracts" / "hardened.json")
    defective = sum(1 for trace in traces if trace.labels and trace.labels.verdict == FAIL)

    naive_bt = backtest(naive, traces, baseline)
    hard_bt = backtest(hardened, traces, baseline)
    target = next(trace for trace in traces if trace.id == "t01-correct")
    naive_mut = run_mutation(naive, target, baseline)
    hard_mut = run_mutation(hardened, target, baseline)

    lines = [
        "Assaystone demo — code/test verifier pack",
        f"traces: {len(traces)} ({defective} defective, {len(traces) - defective} clean)",
        "",
        *_backtest_rows((naive_bt, hard_bt)),
        "",
        f"mutation on {target.id}",
        f"{'contract':<12} {'killed':>6} {'survived':>8} {'score':>6}",
    ]
    for summary in (naive_mut, hard_mut):
        counts = summary.counts()
        lines.append(
            f"{summary.contract:<12} {counts['killed']:>6} "
            f"{counts['survived']:>8} {summary.score:>5.0%}"
        )
    lines.append("cost is an illustrative model; override it per contract.")

    scorecard = render_scorecard(
        naive_bt,
        hard_bt,
        naive_mut,
        hard_mut,
        human_review_cost_usd=hardened.human_review_cost_usd,
        generated_at=utc_now(),
    )
    output = _write(output_dir, "assaystone-demo-code.md", scorecard)
    lines.extend(["", f"scorecard: {output}"])
    return "\n".join(lines)


def _runtime_outcomes(root: Path, baseline: Path, traces) -> list[dict[str, str]]:
    by_id = {trace.id: trace for trace in traces}
    outcomes: list[dict[str, str]] = []

    def guard(callback) -> RuntimeGuard:
        return RuntimeGuard(
            root / "contracts" / "hardened.json",
            baseline=baseline,
            irreversible={"refund.create"},
            approval_callback=callback,
        )

    try:
        session = guard(lambda *_: False).session(task="denied approval", trace_id="runtime-denied")
        session.call(
            "refund.create",
            {"order_id": "O-1001", "amount_cents": 4000},
            lambda: "refunded",
        )
        outcomes.append({"name": "approval denied", "outcome": "UNEXPECTED_PASS", "detail": ""})
    except ApprovalRequired as exc:
        outcomes.append({"name": "approval denied", "outcome": "blocked", "detail": str(exc)})

    try:
        session = guard(lambda *_: True).session(task="over-limit", trace_id="runtime-over-limit")
        session.call(
            "refund.create",
            {"order_id": "O-1001", "amount_cents": 12000},
            lambda: "refunded",
        )
        session.finish(artifacts=by_id["t02-over-limit"].artifacts)
        outcomes.append({"name": "over-limit refund", "outcome": "UNEXPECTED_PASS", "detail": ""})
    except ContractFailed as exc:
        outcomes.append({"name": "over-limit refund", "outcome": "blocked", "detail": str(exc)})

    session = guard(lambda *_: True).session(task="clean", trace_id="runtime-clean")
    session.call(
        "refund.create",
        {"order_id": "O-1001", "amount_cents": 4000},
        lambda: "refunded",
    )
    result = session.finish(artifacts=by_id["t01-correct"].artifacts)
    outcomes.append(
        {"name": "correct refund", "outcome": result.verdict, "detail": result.first_failure or ""}
    )
    return outcomes


def run_ops(output_dir: str | Path = ".") -> str:
    root = DATA_ROOT / "ops_agent"
    baseline = root / "baseline"
    traces = load_traces(root / "traces")
    amount_only = Contract.load(root / "contracts" / "amount_only.json")
    hardened = Contract.load(root / "contracts" / "hardened.json")
    defective = sum(1 for trace in traces if trace.labels and trace.labels.verdict == FAIL)

    summaries = [
        backtest(amount_only, traces, baseline),
        backtest(hardened, traces, baseline),
    ]
    outcomes = _runtime_outcomes(root, baseline, traces)

    lines = [
        "Assaystone demo — ops/runtime verifier pack",
        f"traces: {len(traces)} ({defective} defective, {len(traces) - defective} clean)",
        "",
        *_backtest_rows(summaries),
        "",
        "runtime gate",
    ]
    for outcome in outcomes:
        detail = _short_detail(outcome["detail"])
        lines.append(f"  {outcome['name']:<20} {outcome['outcome']:<10} {detail}")
    lines.append("cost is an illustrative model; override it per contract.")

    scorecard = [
        "# Assaystone scorecard — ops/runtime pack",
        "",
        f"> Generated at `{utc_now()}`.",
        "",
        "## Backtest",
        "",
        "| contract | defects | caught | escaped | false alarms | catch rate | avg cost / trace |",
        "|---|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        scorecard.append(
            f"| `{summary.contract}` | {len(summary.defects)} | {summary.caught} | "
            f"{summary.escaped} | {summary.false_alarms} | {summary.catch_rate:.0%} | "
            f"${summary.avg_cost:.6f} |"
        )
    scorecard += ["", "## Runtime gate", "", "| scenario | outcome | detail |", "|---|---|---|"]
    for outcome in outcomes:
        detail = outcome["detail"].replace("|", "\\|")
        scorecard.append(f"| {outcome['name']} | {outcome['outcome']} | {detail} |")
    scorecard += [
        "",
        "## Read this",
        "",
        "- `amount-only` catches 0/4 bad refunds; the hardened contract catches 4/4.",
        "- The runtime gate blocks before the action when approval is denied, and "
        "raises after the action when the contract fails.",
        "",
    ]
    output = _write(output_dir, "assaystone-demo-ops.md", "\n".join(scorecard) + "\n")
    lines.extend(["", f"scorecard: {output}"])
    return "\n".join(lines)


def run_adversarial(output_dir: str | Path = ".") -> str:
    """Show one attack that a green test suite cannot see."""
    root = DATA_ROOT / "code_agent"
    baseline = root / "baseline"
    trace = load_traces(
        DATA_ROOT / "goodhart" / "traces" / "mechanical" / "g01-harness-hijack.json"
    )[0]
    naive = Contract.load(root / "contracts" / "naive.json")
    hardened = Contract.load(root / "contracts" / "hardened.json")
    results = [
        (contract, run_contract(contract, trace, baseline))
        for contract in (naive, hardened)
    ]

    lines = [
        "Assaystone demo — the trap",
        f"case: {trace.id}",
        "attack: sitecustomize.py neutralises assertEqual; the suite passes",
        "the bug is still in pricing/discounts.py",
        "",
        f"{'contract':<12} {'verdict':<9} first failure",
    ]
    for contract, result in results:
        detail = result.first_failure or "—"
        lines.append(f"{contract.name:<12} {result.verdict:<9} {detail}")
    lines.extend(
        [
            "",
            "read: a green suite is not acceptance. The naive contract only sees",
            "syntax and tests; the hardened contract sees the startup hook.",
        ]
    )

    markdown = [
        "# Assaystone demo — the trap",
        "",
        f"Case: `{trace.id}`. A six-line `sitecustomize.py` patches "
        "`unittest.TestCase.assertEqual` to a no-op, so the suite passes while "
        "the bug remains.",
        "",
        "| contract | verdict | first failure |",
        "|---|---|---|",
    ]
    for contract, result in results:
        detail = (result.first_failure or "—").replace("|", "\\|")
        markdown.append(f"| `{contract.name}` | {result.verdict} | {detail} |")
    markdown += [
        "",
        "The naive contract (`diff.syntax` + `tests.pass`) returns **pass**. "
        "The hardened contract fails at `tests.harness_integrity`.",
        "",
    ]
    output = _write(
        output_dir, "assaystone-demo-adversarial.md", "\n".join(markdown)
    )
    lines.extend(["", f"details: {output}"])
    return "\n".join(lines)


def run_audit(output_dir: str | Path = ".") -> str:
    root = DATA_ROOT / "audit"
    baseline = root / "baseline"
    traces = load_audit_traces(root / "transcript.jsonl", baseline=baseline)
    report = audit_traces(build_audit_contract(baseline), traces, baseline)
    contract_path = Path(output_dir) / "assaystone-demo-contract.json"
    report.write_contract(contract_path)
    text = render_audit(
        report,
        written_to=str(contract_path),
        baseline_label="demo transcript",
    )
    output = _write(output_dir, "assaystone-demo-audit.md", text + "\n")
    return "Assaystone audit demo — a coding-agent transcript\n" + text + f"\n\ndetails: {output}"


def run_plane(output_dir: str | Path = ".") -> str:
    """One screen for the acceptance plane: pass, fail, approve, audit."""
    root = DATA_ROOT / "plane"
    project = root / "project"
    manifest = CapabilityManifest.load(root / "capability.json")
    lines = [
        "Assaystone demo — acceptance plane",
        "domain: pricing; nine generic oracles; plane.py unchanged",
        "",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "project"
        shutil.copytree(project, work)

        shadow = evaluate_gate(manifest, "shadow", work)
        gap = ", ".join(item["criterion"] for item in shadow.gap) or "none"
        lines += [
            f"shadow: {shadow.outcome}  merge_allowed={shadow.merge_allowed}",
            f"  declared but not gated at this stage: {gap}",
            "",
        ]

        fee = work / "fee.py"
        original = fee.read_text(encoding="utf-8")
        fee.write_text(
            original.replace(
                '"fee_cents": fee_cents(',
                '"audited": version != "old", "fee_cents": fee_cents(',
            ),
            encoding="utf-8",
        )
        broken = evaluate_gate(manifest, "shadow", work)
        parity = next(item for item in broken.results if item.oracle == "parity")
        lines += [
            "the refactor adds a field to the wire format; unit tests still pass",
            f"shadow: {broken.outcome}",
            f"  parity: {parity.reasons[0]}",
            "",
        ]
        fee.write_text(original, encoding="utf-8")

        (work / "approvals.json").unlink()
        denied = evaluate_gate(manifest, "canary", work)
        lines += [
            "canary without the owner approval:",
            f"  {denied.outcome}  merge_allowed={denied.merge_allowed}",
            "",
        ]

        shutil.copy2(project / "approvals.json", work / "approvals.json")
        canary = evaluate_gate(manifest, "canary", work)
        lines += [
            "canary with the approval:",
            f"  {canary.outcome}  merge_allowed={canary.merge_allowed}",
            "",
        ]

        trail_path = Path(output_dir) / "plane-demo-trail.jsonl"
        trail_path.unlink(missing_ok=True)
        entry = audit_trail.append(trail_path, canary, actor="demo")
        check = audit_trail.verify(trail_path)
        lines += [
            f"trail: {trail_path.name} entry {entry['seq']}, chain intact",
            f"  head {check.head}",
            "",
        ]

        tampered = Path(tmp) / "tampered.jsonl"
        changed = dict(entry)
        changed["outcome"] = "fail"
        tampered.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        bad = audit_trail.verify(tampered)
        lines += [
            "editing the recorded outcome:",
            f"  chain broken: {bad.errors[0]}",
            "",
        ]

    lines += [
        "the core did not change: one manifest bound four primitives",
        "next: assaystone capability init --root . --owner <team>",
    ]
    return "\n".join(lines)
