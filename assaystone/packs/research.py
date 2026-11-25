"""Research/report pack: citations, source existence, and verbatim quotes.

The fourth domain. The artifact is prose, the oracle is a source corpus, and the
criteria are all about evidence: every claim cites, every citation exists, every
quote is real. The acceptance language is unchanged.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..verifiers import Check, Verifier, VerifyContext, register

REPORT = "report.md"
SOURCES = "sources.json"
CITATION = re.compile(r"\[([A-Za-z0-9_.-]+)\]")
QUOTE = re.compile(r"\"([^\"]{8,})\"|“([^”]{8,})”")


def _text(ctx: VerifyContext, path: str) -> str:
    try:
        return ctx.current_text(path)
    except (FileNotFoundError, OSError):
        return ""


def _sources(ctx: VerifyContext, path: str = SOURCES) -> dict[str, str]:
    text = _text(ctx, path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    items = data.get("sources") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = str(item.get("text") or "")
    return out


def _paragraphs(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((number, stripped))
    return out


@register
class ResearchCitations(Verifier):
    name = "research.citations"
    layer = "L1"
    cost_usd = 0.000005
    independence = "high"
    description = "Every non-heading paragraph cites at least one source."
    claim = "Every non-heading paragraph in report.md contains a [source] citation."
    catches = ("uncited-claim",)
    blind_spots = (
        "a cited paragraph with an additional uncited claim",
        "a citation that does not support the claim",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        text = _text(ctx, str(params.get("path") or REPORT))
        reasons = [
            f"line {number}: no citation"
            for number, line in _paragraphs(text)
            if not CITATION.search(line)
        ]
        return (not reasons, reasons, [f"checked {len(_paragraphs(text))} paragraph(s)"])


@register
class ResearchSourcesExist(Verifier):
    name = "research.sources_exist"
    layer = "L0"
    cost_usd = 0.000005
    independence = "high"
    description = "Every cited source id exists in sources.json."
    claim = "Every [id] cited in report.md exists in sources.json."
    catches = ("missing-source",)
    blind_spots = (
        "a cited source that exists but does not support the claim",
        "a retracted source",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        report = _text(ctx, str(params.get("report") or REPORT))
        known = _sources(ctx, str(params.get("sources") or SOURCES))
        if not known:
            return None, ["sources.json missing or invalid"], []
        cited = sorted(set(CITATION.findall(report)))
        reasons = [f"unknown source: {cid}" for cid in cited if cid not in known]
        return (
            not reasons,
            reasons,
            [f"checked {len(cited)} citation(s)"],
        )


@register
class ResearchQuotesVerbatim(Verifier):
    name = "research.quotes_verbatim"
    layer = "L1"
    cost_usd = 0.000005
    independence = "high"
    description = "Every quoted span appears verbatim in a source."
    claim = "Every quoted span in report.md appears verbatim in sources.json."
    catches = ("fabricated-quote",)
    blind_spots = (
        "a paraphrase presented as a quote",
        "a quote split across lines",
        "a translated quote",
    )
    trusts = ("artifacts",)

    def check(self, ctx: VerifyContext, params: dict[str, Any]) -> Check:
        report = _text(ctx, str(params.get("report") or REPORT))
        corpus = "\n".join(_sources(ctx, str(params.get("sources") or SOURCES)).values())
        quotes = [left or right for left, right in QUOTE.findall(report)]
        reasons = [
            f"quote not found in any source: {quote[:60]!r}"
            for quote in quotes
            if quote not in corpus
        ]
        return (
            not reasons,
            reasons,
            [f"checked {len(quotes)} quote(s)"],
        )
