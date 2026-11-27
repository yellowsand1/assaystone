"""Add a labelled case to an existing benchmark corpus.

The benchmark is only as good as its corpus. This command is the on-ramp for
contributors: take a trace or a redacted transcript, attach a human label, and
write it into an existing family so the next benchmark run scores it.

The function never edits the manifest. Families already point at a directory, so
writing one labelled trace is enough, and the manifest stays reviewable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import AuditError, load_audit_traces
from .model import FAIL, PASS, Label, Trace, load_traces


class CorpusError(ValueError):
    """The corpus, family, or case cannot be used."""


@dataclass
class AddedCase:
    corpus: str
    family: str
    path: Path
    trace_id: str
    verdict: str
    defect: str | None


def _manifest(corpus: Path) -> tuple[dict[str, Any], Path]:
    try:
        data = json.loads(corpus.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(f"corpus not found: {corpus}") from exc
    except json.JSONDecodeError as exc:
        raise CorpusError(f"invalid corpus JSON in {corpus}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("families"), list):
        raise CorpusError(f"corpus has no families: {corpus}")
    return data, corpus.parent


def _family(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for family in manifest["families"]:
        if family.get("name") == name:
            return family
    available = ", ".join(sorted(str(item.get("name")) for item in manifest["families"]))
    raise CorpusError(f"unknown family {name!r}; available: {available}")


def _looks_like_trace(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and {"id", "artifacts"} <= set(data)


def _load_one(
    source: Path,
    *,
    baseline: Path,
    fmt: str,
) -> Trace:
    if not source.exists():
        raise CorpusError(f"trace source not found: {source}")
    if _looks_like_trace(source):
        traces = load_traces(source)
    else:
        try:
            traces = load_audit_traces(source, format=fmt, baseline=baseline)
        except (AuditError, OSError, json.JSONDecodeError) as exc:
            raise CorpusError(f"cannot read transcript {source}: {exc}") from exc
    if len(traces) != 1:
        raise CorpusError(
            f"expected exactly one trace from {source}, found {len(traces)}"
        )
    return traces[0]


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not cleaned or cleaned in {".", ".."}:
        raise CorpusError(f"cannot derive a safe case id from {value!r}")
    return cleaned


def add_case(
    corpus: str | Path,
    family_name: str,
    trace_source: str | Path,
    *,
    label: str,
    defect: str | None = None,
    note: str = "",
    baseline: str | Path | None = None,
    fmt: str = "auto",
    case_id: str | None = None,
    force: bool = False,
) -> AddedCase:
    corpus_path = Path(corpus)
    manifest, base = _manifest(corpus_path)
    family = _family(manifest, family_name)

    if family.get("kind", "traces") != "traces":
        raise CorpusError(
            f"family {family_name!r} is {family.get('kind')!r}; "
            "only 'traces' families accept new cases"
        )
    if not family.get("source"):
        raise CorpusError(f"family {family_name!r} has no source")

    verdict = label.strip().lower()
    if verdict not in (PASS, FAIL):
        raise CorpusError("label must be 'pass' or 'fail'")
    defect = (defect or "").strip() or None
    if verdict == FAIL and defect is None:
        raise CorpusError("a failing case needs --defect")
    if verdict == PASS and defect is not None:
        raise CorpusError("a passing case must not declare --defect")

    source_dir = (base / family["source"]).resolve()
    baseline_dir = (
        Path(baseline).resolve()
        if baseline is not None
        else (base / family["baseline"]).resolve()
    )
    trace = _load_one(Path(trace_source), baseline=baseline_dir, fmt=fmt)
    trace.id = _safe_id(case_id or trace.id or "case")
    trace.labels = Label(verdict=verdict, defect=defect, note=note.strip())

    target = source_dir / f"{trace.id}.json"
    if target.exists() and not force:
        raise CorpusError(f"case already exists: {target} (use --force to replace)")
    source_dir.mkdir(parents=True, exist_ok=True)
    trace.save(target)
    return AddedCase(
        corpus=str(corpus_path),
        family=family_name,
        path=target,
        trace_id=trace.id,
        verdict=verdict,
        defect=defect,
    )


def case_outcome(
    corpus: str | Path,
    family_name: str,
    trace_id: str,
) -> dict[str, Any]:
    """Run the corpus and return what the verifier pack did with one case."""
    from .failure_zoo import run_benchmark

    result = run_benchmark(corpus, thresholds=None)
    for family in result.families:
        if family.name != family_name:
            continue
        outcome = family.case_outcomes.get(trace_id, "escaped")
        caught_by = family.caught_by.get(trace_id, [])
        return {
            "family": family_name,
            "case": trace_id,
            "outcome": outcome,
            "caught_by": caught_by,
        }
    raise CorpusError(f"case {trace_id!r} is not in family {family_name!r}")
