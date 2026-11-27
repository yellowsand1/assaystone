"""A registry view across capability manifests in a workspace.

A capability lives next to its evidence: ``.assaystone/`` contains
``capability.json``, ``trail.jsonl``, ``receipt.json``, the owner approval, and
the waivers. Any nested ``.assaystone`` directory is another capability.

The portfolio is a read-only table with a strict mode. It does not create a
second source of truth: every cell comes from the capability card.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .card import StatusCard, build_card
from .plane import CapabilityManifest, PlaneError

SKIP_PARTS = {
    ".git",
    "node_modules",
    "build",
    "dist",
    "target",
    ".venv",
    "venv",
    "__pycache__",
}


def discover(root: str | Path) -> list[Path]:
    root = Path(root).resolve()
    found: list[Path] = []
    for path in root.rglob("capability.json"):
        if ".assaystone" not in path.parts:
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        found.append(path)
    return sorted(found)


@dataclass
class PortfolioEntry:
    path: Path
    card: StatusCard | None = None
    error: str = ""
    critical: list[str] = field(default_factory=list)
    root: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "root": str(self.root) if self.root else "",
            "error": self.error,
            "critical": list(self.critical),
            "card": self.card.to_dict() if self.card else None,
        }

    def label(self) -> str:
        """How to name this capability in a multi-repository report."""
        if self.card is not None:
            return self.card.capability
        return f"{self.path.parent.parent.name}/{self.path.parent.name}"


@dataclass
class Portfolio:
    roots: list[Path] = field(default_factory=list)
    entries: list[PortfolioEntry] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.roots[0] if self.roots else Path(".")

    def critical_count(self) -> int:
        return sum(1 for entry in self.entries if entry.critical)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": [str(item) for item in self.roots],
            "capabilities": [entry.to_dict() for entry in self.entries],
            "critical": self.critical_count(),
        }


def load_index(path: str | Path) -> list[Path]:
    """Read a list of repository roots from a JSON index file.

    The index is a file, not a service: it names where the repositories are, and
    every path in it is resolved relative to the index itself.
    """
    index = Path(path).resolve()
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"index not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid index JSON in {path}: {exc}") from exc
    entries = data.get("roots") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ValueError("an index must list at least one root")
    roots: list[Path] = []
    for item in entries:
        candidate = Path(str(item))
        if not candidate.is_absolute():
            candidate = index.parent / candidate
        roots.append(candidate.resolve())
    return roots


def _critical(card: StatusCard) -> list[str]:
    issues: list[str] = []
    for item in card.never_gated:
        if item["severity"] == "critical":
            issues.append(
                f"criterion `{item['criterion']}` is gated by no stage"
            )
    # A criterion that is gated by a later stage is not a portfolio defect at
    # the current lifecycle stage. The per-stage gap stays on the card as
    # information; strict mode only requires that every declared stage has a
    # passing decision and that every critical criterion is gated somewhere.
    if card.approval.get("required") and not card.approval.get("ok"):
        issues.append("owner approval is not valid")
    if card.trail.get("present") and not card.trail.get("ok"):
        issues.append("trail does not verify")
    if card.receipt.get("present") and not card.receipt.get("ok"):
        issues.append("receipt does not verify")
    if card.waivers.get("present") and not card.waivers.get("ok"):
        issues.append("waiver file does not verify")
    if card.revocations.get("revoked_artifacts"):
        issues.append("an artifact was signed by a revoked key")
    if card.revocations.get("present") and not card.revocations.get("ok"):
        issues.append("the revocation list does not read")
    if not card.trail.get("present"):
        issues.append("no trail evidence")
    else:
        last = card.trail.get("last", {})
        current = last.get(card.lifecycle)
        if current is None:
            issues.append(
                f"no recorded `{card.lifecycle}` gate for the current lifecycle"
            )
        elif current.get("outcome") != "pass":
            issues.append(
                f"the last `{card.lifecycle}` gate was "
                f"`{current.get('outcome')}`"
            )
        current_entry = last.get(card.lifecycle)
        if current_entry and current_entry.get("stale"):
            issues.append(
                f"the last `{card.lifecycle}` decision is for a different "
                "commit"
            )
        for stage, entry in last.items():
            if stage == card.lifecycle:
                continue
            if entry.get("outcome") != "pass":
                issues.append(
                    f"the last `{stage}` gate was `{entry.get('outcome')}`"
                )
    return issues


def build_portfolio(
    roots: str | Path | list[str | Path],
    owner_key: str = "",
    receipt_key: str = "",
    owner_public_key: str | Path | None = None,
) -> Portfolio:
    if isinstance(roots, (str, Path)):
        roots = [roots]
    resolved: list[Path] = []
    for item in roots:
        candidate = Path(item).resolve()
        if candidate not in resolved:
            resolved.append(candidate)
    portfolio = Portfolio(roots=resolved)
    for root in resolved:
      for path in discover(root):
        try:
            manifest = CapabilityManifest.load(path)
        except PlaneError as exc:
            entry = PortfolioEntry(path=path, error=str(exc), root=root)
            entry.critical = [f"manifest is invalid: {exc}"]
            portfolio.entries.append(entry)
            continue
        directory = path.parent

        def sidecar(
            name: str, directory: Path = directory
        ) -> Path | None:
            candidate = directory / name
            return candidate if candidate.exists() else None

        card = build_card(
            manifest,
            root=root,
            trail_path=sidecar("trail.jsonl"),
            receipt_path=sidecar("receipt.json"),
            approval_path=sidecar("capability.approval.json"),
            waivers_path=sidecar("capability.waivers.json"),
            revocations_path=sidecar("capability.revocations.json"),
            owner_key=owner_key,
            owner_public_key=owner_public_key,
            receipt_key=receipt_key,
        )
        portfolio.entries.append(
            PortfolioEntry(
                path=path, card=card, critical=_critical(card), root=root
            )
        )
    return portfolio


def _last(card: StatusCard) -> str:
    last = card.trail.get("last") or {}
    if not last:
        return "-"
    return ", ".join(
        f"{stage}:{entry.get('outcome')}"
        for stage, entry in sorted(last.items())
    )


def render_portfolio(portfolio: Portfolio) -> str:
    if not portfolio.entries:
        where = ", ".join(str(item) for item in portfolio.roots)
        return (
            f"No capabilities found under {where}. "
            "A capability is a `.assaystone/capability.json`."
        )
    multi = len(portfolio.roots) > 1
    repo_head = f"{'repo':<18} " if multi else ""
    rows = [
        f"{repo_head}{'capability':<24} {'owner':<16} {'risk':<8} "
        f"{'lifecycle':<10} {'criteria':<9} {'last':<28} {'approval':<9} "
        f"{'receipt':<8} {'critical':>8}"
    ]
    for entry in portfolio.entries:
        repo = f"{entry.root.name:<18} " if multi and entry.root else (
            " " * 19 if multi else ""
        )
        if entry.card is None:
            rows.append(
                f"{repo}{entry.label():<24} {'-':<16} {'-':<8} "
                f"{'-':<10} {'-':<9} {'-':<28} {'-':<9} {'-':<8} "
                f"{len(entry.critical):>8}"
            )
            continue
        card = entry.card
        approval = (
            "-"
            if not card.approval.get("required")
            else ("ok" if card.approval.get("ok") else "invalid")
        )
        receipt = (
            "-"
            if not card.receipt.get("present")
            else ("ok" if card.receipt.get("ok") else "invalid")
        )
        rows.append(
            f"{repo}{card.capability:<24} {card.owner:<16} {card.risk:<8} "
            f"{card.lifecycle:<10} "
            f"{card.gated_by_some_stage}/{card.criteria:<7} "
            f"{_last(card):<28} {approval:<9} {receipt:<8} "
            f"{len(entry.critical):>8}"
        )
    rows.append("")
    rows.append(
        f"{len(portfolio.entries)} capabilities, "
        f"{portfolio.critical_count()} with critical risks"
    )
    for entry in portfolio.entries:
        label = entry.label()
        if multi and entry.root:
            label = f"{entry.root.name}/{label}"
        for issue in entry.critical:
            rows.append(f"  {label}: {issue}")
    return "\n".join(rows)
